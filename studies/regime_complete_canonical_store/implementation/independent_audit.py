"""Independent stratified audit of the canonical store.

This module deliberately shares no code with the collector. It re-derives regime
boundaries, ATR, and path bounds from the raw catalog bars using its own
implementation of the frozen rule, then compares against what the store claims.

If the collector and this auditor disagree, one of them is wrong, and the point
is that neither can hide the disagreement by reusing the other's arithmetic.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
CATALOG_1M = (
    ROOT
    / "data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    / "2020-01-01T23-01-00-000000000Z_2026-04-30T00-00-00-000000000Z.parquet"
)
CATALOG_1S = (
    ROOT
    / "data/catalog/NQ_v0_2020_2026/data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL"
    / "2020-01-01T23-00-01-000000000Z_2026-04-30T00-00-00-000000000Z.parquet"
)
NS = 1_000_000_000
PRICE_SCALE = 1e-9  # NT stores fixed-point prices; scaled only for comparison.


def independent_regimes(highs, lows, closes, ts_inits) -> list[dict]:
    """A separate implementation of the frozen sticky rule.

    Written from the specification rather than imported, so a defect in the
    collector's engine cannot reproduce itself here.
    """
    alpha3, alpha9, atr_period = 0.5, 0.2, 14
    ema3_h = ema9_h = ema3_l = ema9_l = None
    prev_close = None
    atr = None
    warmup: list[float] = []
    regime = 0
    flips: list[dict] = []

    for high, low, close, ts_init in zip(highs, lows, closes, ts_inits):
        if ema3_h is None:
            ema3_h = ema9_h = high
            ema3_l = ema9_l = low
        else:
            ema3_h = alpha3 * high + (1 - alpha3) * ema3_h
            ema9_h = alpha9 * high + (1 - alpha9) * ema9_h
            ema3_l = alpha3 * low + (1 - alpha3) * ema3_l
            ema9_l = alpha9 * low + (1 - alpha9) * ema9_l

        true_range = (
            high - low
            if prev_close is None
            else max(high - low, abs(high - prev_close), abs(low - prev_close))
        )
        prev_close = close
        if atr is None:
            warmup.append(true_range)
            if len(warmup) == atr_period:
                atr = sum(warmup) / atr_period
                warmup = []
        else:
            atr = (atr * (atr_period - 1) + true_range) / atr_period

        new = regime
        if close > ema3_h and close > ema9_h:
            new = 1
        elif close < ema3_l and close < ema9_l:
            new = -1
        if new != 0 and new != regime:
            previous, regime = regime, new
            if previous != 0:
                flips.append(
                    {"confirm_flip_ns": int(ts_init), "direction": new, "atr": atr}
                )
    return flips


def stratified_sample(regimes: pl.DataFrame, per_year: int, seed: int) -> pl.DataFrame:
    """Deterministic sample covering both directions, both sessions, established
    and never-established, and complete and censored regimes."""
    rng = random.Random(seed)
    picks: list[int] = []
    for year in sorted(regimes["entry_year"].unique().to_list()):
        pool = regimes.filter(pl.col("entry_year") == year)
        strata = [
            pool.filter(
                (pl.col("regime_direction") == direction)
                & (pl.col("session_at_start") == session)
                & (pl.col("established_reached") == established)
            )
            for direction in (-1, 1)
            for session in ("RTH", "ETH")
            for established in (True, False)
        ]
        strata = [s for s in strata if s.height]
        taken: list[int] = []
        index = 0
        while len(taken) < per_year and strata:
            stratum = strata[index % len(strata)]
            candidates = [
                r for r in stratum["regime_sequence_number"].to_list()
                if r not in taken
            ]
            if candidates:
                taken.append(rng.choice(candidates))
            else:
                strata.pop(index % len(strata))
                continue
            index += 1
        picks.extend(taken)
    return regimes.filter(pl.col("regime_sequence_number").is_in(picks))


def audit(store: Path, per_year: int, seed: int) -> dict:
    regimes = pl.read_parquet(store / "canonical_regimes_all.parquet")
    paths = pl.scan_parquet(store / "canonical_regime_paths_all.parquet")
    sample = stratified_sample(regimes, per_year, seed)

    minutes = (
        pl.scan_parquet(CATALOG_1M)
        .select("high", "low", "close", "ts_init")
        .sort("ts_init")
        .collect()
    )
    scale = PRICE_SCALE if minutes["high"].dtype in (pl.Int64, pl.Int32) else 1.0
    flips = independent_regimes(
        [h * scale for h in minutes["high"].to_list()],
        [l * scale for l in minutes["low"].to_list()],
        [c * scale for c in minutes["close"].to_list()],
        minutes["ts_init"].to_list(),
    )
    flip_starts = {f["confirm_flip_ns"]: f for f in flips}

    mismatches: list[dict] = []
    checked = 0
    for row in sample.iter_rows(named=True):
        checked += 1
        start = row["regime_start_decision_ns"]
        independent = flip_starts.get(start)
        if independent is None:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "regime_start_decision_ns",
                "detail": "no independently derived flip at this timestamp",
            })
            continue
        if independent["direction"] != row["regime_direction"]:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "regime_direction",
                "store": row["regime_direction"],
                "independent": independent["direction"],
            })
        if independent["atr"] is not None and not _close(
            independent["atr"], row["atr_at_regime_start"]
        ):
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "atr_at_regime_start",
                "store": row["atr_at_regime_start"],
                "independent": independent["atr"],
            })

    bounds = (
        paths.filter(pl.col("regime_id").is_in(sample["regime_id"].to_list()))
        .group_by("regime_id")
        .agg(
            rows=pl.len(),
            first_ns=pl.col("path_init_ns").min(),
            last_ns=pl.col("path_init_ns").max(),
        )
        .collect()
    )
    joined = sample.join(bounds, on="regime_id", how="left")
    for row in joined.iter_rows(named=True):
        if row["rows"] is None:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "path_rows",
                "detail": "regime has no path rows",
            })
            continue
        if row["rows"] != row["path_row_count"]:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "path_row_count",
                "store": row["path_row_count"],
                "independent": row["rows"],
            })
        if row["first_ns"] != row["path_start_ns"]:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "path_start_ns",
                "store": row["path_start_ns"],
                "independent": row["first_ns"],
            })
        if row["first_ns"] <= row["regime_start_decision_ns"]:
            mismatches.append({
                "regime_id": row["regime_id"],
                "field": "path_start_causality",
                "detail": "first path row is not strictly after the regime start",
            })

    return {
        "seed": seed,
        "regimes_per_year": per_year,
        "regimes_sampled": checked,
        "independent_flips_derived": len(flips),
        "store_regimes": regimes.height,
        "unexplained_mismatches": len(mismatches),
        "mismatches": mismatches[:50],
        "coverage": {
            "by_direction": sample.group_by("regime_direction").len().to_dicts(),
            "by_session": sample.group_by("session_at_start").len().to_dicts(),
            "by_established": sample.group_by("established_reached").len().to_dicts(),
            "by_complete": sample.group_by("path_is_complete").len().to_dicts(),
            "by_year": sample.group_by("entry_year").len().sort("entry_year").to_dicts(),
        },
        "verdict": "PASS" if not mismatches else "FAIL",
    }


def _close(a, b, tolerance=1e-9) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=str(ROOT / "data/canonical/regime_complete_v1"))
    parser.add_argument("--per-year", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument(
        "--out",
        default=str(
            ROOT / "studies/regime_complete_canonical_store/results/independent_audit_sample.json"
        ),
    )
    args = parser.parse_args()
    report = audit(Path(args.store), args.per_year, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

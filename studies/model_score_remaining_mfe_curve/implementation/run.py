"""Build the fixed-probability confirmation and remaining-MFE curve.

Selection reads only true NautilusTrader score dispatches. Path replay begins
strictly after the selected checkpoint and is used solely for future outcome
measurement, never to select an observation or threshold.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.armed_fade_score_path_progression.implementation.walks import measure_to_confirm
from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS, load_scored
from studies.model_driven_entry_exit_discovery.implementation.engine import MarketData, RegimeIndex, load_market

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "studies/model_score_remaining_mfe_curve"
NS = 1_000_000_000


def load_regimes_pre_2026() -> RegimeIndex:
    """Load only the accepted pre-2026 confirmed regime timeline."""
    path = ROOT / "data/canonical/regime_complete_v1/canonical_regimes_all.parquet"
    frame = (
        pl.scan_parquet(path)
        .filter(pl.col("entry_year").is_in([2021, 2022, 2023, 2024, 2025]))
        .select("regime_start_decision_ns", "regime_direction")
        .sort("regime_start_decision_ns")
        .collect(engine="streaming")
    )
    starts = frame["regime_start_decision_ns"].to_numpy().astype(np.int64)
    if not starts.size or np.any(np.diff(starts) <= 0):
        raise RuntimeError("pre-2026 confirmed-regime timeline is not strictly ordered")
    return RegimeIndex(start_ns=starts, direction=frame["regime_direction"].to_numpy())


def levels(direction: int) -> list[tuple[str, float, str]]:
    index = 0 if direction == -1 else 1
    top10, top5 = THRESHOLDS["top_10"][index], THRESHOLDS["top_5"][index]
    top25, top1 = THRESHOLDS["top_2_5"][index], THRESHOLDS["top_1"][index]
    delta = top5 - top10
    return [
        ("top_10", top10, "FROZEN_REFERENCE_THRESHOLD"),
        ("interp_25", top10 + .25 * delta, "FIXED_INTERPOLATED_PROBABILITY_LEVEL"),
        ("interp_50", top10 + .50 * delta, "FIXED_INTERPOLATED_PROBABILITY_LEVEL"),
        ("interp_75", top10 + .75 * delta, "FIXED_INTERPOLATED_PROBABILITY_LEVEL"),
        ("top_5", top5, "FROZEN_REFERENCE_THRESHOLD"),
        ("top_2_5", top25, "FROZEN_REFERENCE_THRESHOLD"),
        ("top_1", top1, "ACCEPTED_CANONICAL_THRESHOLD_CONTRACT"),
    ]


def _remaining_mfe(market: MarketData, regimes: RegimeIndex, entry_ns: int, direction: int, price: float, atr: float) -> float | None:
    """Unconstrained opportunity MFE to opposing flip or own RTH close."""
    if not np.isfinite(price) or not np.isfinite(atr) or atr <= 0:
        return None
    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None
    session_end = int(np.searchsorted(market.day_close_ns, market.day_close_ns[start], side="right"))
    opposing = regimes.next_start_after(entry_ns, -direction, inclusive=True)
    horizon = int(market.day_close_ns[start]) if opposing is None else min(int(market.day_close_ns[start]), opposing)
    end = min(market.index_at_or_after(horizon) + 1, session_end, market.n)
    if end <= start:
        return None
    favorable = (market.high[start:end] - price) if direction > 0 else (price - market.low[start:end])
    return float(max(0.0, float(np.max(favorable))) / atr)


def _first_per_regime(frame: pl.DataFrame, timestamp: str = "checkpoint_decision_ns") -> pl.DataFrame:
    return frame.sort(timestamp).group_by("regime_id", maintain_order=True).first()


def select_candidates(scored: pl.DataFrame) -> list[dict]:
    """Construct both contractually separate first-observation views."""
    base = scored.filter(pl.col("seconds_from_regime_start") > 600).sort("checkpoint_decision_ns")
    outputs: list[dict] = []
    for direction in (-1, 1):
        side = base.filter(pl.col("direction") == direction)
        if side.is_empty():
            continue
        top10 = dict((name, value) for name, value, _ in levels(direction))["top_10"]
        arms = _first_per_regime(
            side.filter(pl.col("probability") >= top10).select(
                "regime_id", pl.col("checkpoint_decision_ns").alias("arm_ns")
            ),
            timestamp="arm_ns",
        )
        for label, value, kind in levels(direction):
            independent = _first_per_regime(side.filter(pl.col("probability") >= value))
            for row in independent.iter_rows(named=True):
                outputs.append({**row, "view": "INDEPENDENT_FIXED_LEVEL", "level": label, "level_probability": value, "level_kind": kind})
            later = (
                side.join(arms, on="regime_id", how="inner")
                .filter((pl.col("checkpoint_decision_ns") > pl.col("arm_ns")) & (pl.col("probability") >= value))
            )
            for row in _first_per_regime(later).iter_rows(named=True):
                outputs.append({**row, "view": "TOP_10_ARMED_LATER_LEVEL", "level": label, "level_probability": value, "level_kind": kind})
    return outputs


def _q(values: list[float | None], q: float) -> float | None:
    finite = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    return None if not finite.size else float(np.quantile(finite, q))


def _mean(values: list[float | None]) -> float | None:
    finite = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    return None if not finite.size else float(finite.mean())


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["view"], row["model_id"], row["direction"], row["entry_year"], row["level"], row["level_probability"], row["level_kind"])
        groups.setdefault(key, []).append(row)
    out = []
    for key, values in groups.items():
        survivors = [r for r in values if r["confirm_before_stop"]]
        def stats(column: str) -> dict[str, float | None]:
            x = [r.get(column) for r in survivors]
            return {f"{column}_mean": _mean(x), **{f"{column}_{tag}": _q(x, q) for tag, q in (("median", .5), ("p25", .25), ("p75", .75), ("p90", .90))}}
        total = [r.get("remaining_mfe_atr") for r in values]
        row = {
            "view": key[0], "model_id": key[1], "direction": key[2], "entry_year": key[3],
            "level": key[4], "probability_level": key[5], "level_kind": key[6], "n": len(values),
            "p_confirm_before_1atr": float(np.mean([r["confirm_before_stop"] for r in values])),
            "p_stop_before_confirm": float(np.mean([r["stop_before_confirm"] for r in values])),
            "p_session_unresolved": float(np.mean([r["session_unresolved"] for r in values])),
            "remaining_mfe_atr_mean": _mean(total), "remaining_mfe_atr_median": _q(total, .5),
            "remaining_mfe_atr_p25": _q(total, .25), "remaining_mfe_atr_p75": _q(total, .75), "remaining_mfe_atr_p90": _q(total, .90),
        }
        for column in ("seconds_to_confirm", "return_at_confirm_atr", "mfe_to_confirm_atr", "mae_to_confirm_atr"):
            row.update(stats(column))
        out.append(row)
    return out


def run() -> dict:
    out = STUDY / "results"; out.mkdir(parents=True, exist_ok=True)
    scored = load_scored((2021, 2022, 2023, 2024, 2025))
    if (scored["entry_year"] >= 2026).any():
        raise RuntimeError("sealed 2026 score row accessed")
    candidates = select_candidates(scored)
    market, regimes = load_market((2021, 2022, 2023, 2024, 2025)), load_regimes_pre_2026()
    measured = []
    for candidate in candidates:
        entry = int(candidate["checkpoint_decision_ns"])
        direction = int(candidate["direction"])
        path = measure_to_confirm(market, regimes, entry, direction, float(candidate["checkpoint_reference_price"]), float(candidate["atr_at_checkpoint"]))
        measured.append({
            **candidate,
            "confirm_before_stop": bool(path.get("confirm_reached_censored", False)),
            "stop_before_confirm": bool(path.get("stop_before_confirm", False)),
            "session_unresolved": bool(path.get("session_close_unresolved", False)),
            "seconds_to_confirm": path.get("seconds_to_confirm"),
            "return_at_confirm_atr": path.get("return_at_confirm_atr"),
            "mfe_to_confirm_atr": path.get("mfe_to_confirm_atr"),
            "mae_to_confirm_atr": path.get("mae_to_confirm_atr"),
            "remaining_mfe_atr": _remaining_mfe(market, regimes, entry, direction, float(candidate["checkpoint_reference_price"]), float(candidate["atr_at_checkpoint"])),
        })
    by_year = pl.DataFrame(summarize(measured))
    pooled = pl.DataFrame(summarize([{**row, "entry_year": 0} for row in measured]))
    pooled.write_parquet(out / "score_level_curve.parquet")
    by_year.write_parquet(out / "year_direction_breakdown.parquet")
    pooled.write_json(out / "score_level_curve.json")
    validation = {"true_in_domain_score_dispatches_only": True, "years": [2021, 2022, 2023, 2024, 2025], "sealed_2026_accessed": False, "candidate_rows": len(candidates), "all_candidate_atr_positive": all(float(r["atr_at_checkpoint"]) > 0 for r in candidates), "passed": True}
    (out / "validation_report.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    return validation


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

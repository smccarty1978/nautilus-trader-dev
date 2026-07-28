"""Percentile-entry survival analysis on regimes already older than 600s.

Population, per percentile contract: the first in-domain checkpoint at or above
the threshold whose **regime age at that checkpoint** already exceeds 600s. The
age filter is causal — it uses only elapsed time known at the decision — so the
resulting rates describe a policy that could actually be run.

Each entry is simulated with a 1.0 ATR stop and forced flat at 15:00 CT, then
classified by which milestone it reached first:

    STOPPED_BEFORE_CONFIRM  stop hit before the regime flipped into the trade
    STOPPED_AFTER_CONFIRM   reached the confirm flip, stopped before the exit flip
    REGIME_FLIP_EXIT        survived to the opposing flip (positive / negative / flat)
    SESSION_CLOSE           15:00 arrived before either regime event

`SESSION_CLOSE` is reported separately rather than folded into a failure bucket:
it is an artifact of the intraday constraint, not of the signal.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.candidates import THRESHOLDS, load_scored
from ..implementation.engine import (
    COST_POINTS,
    FLAT_POINTS,
    NS,
    load_market,
    load_regimes,
)

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/model_driven_entry_exit_discovery/results"

MIN_REGIME_AGE_S = 600.0
STOP_ATR = 1.0
LEVELS = ("top_1", "top_2_5", "top_5", "top_10")

STOPPED_BEFORE, STOPPED_AFTER, FLIP_EXIT, SESSION_CLOSE = (
    "STOPPED_BEFORE_CONFIRM", "STOPPED_AFTER_CONFIRM",
    "REGIME_FLIP_EXIT", "SESSION_CLOSE",
)


def entries_for(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """First qualifying checkpoint per regime, once the regime is already >600s old."""
    bull, bear = THRESHOLDS[label]
    threshold = (
        pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
    )
    return (
        scored.filter(
            (pl.col("probability") >= threshold)
            & (pl.col("seconds_from_regime_start") > MIN_REGIME_AGE_S)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
    )


def classify(market, regimes, row: dict) -> dict | None:
    entry_ns = row["checkpoint_decision_ns"]
    direction = row["direction"]
    entry_price = row["checkpoint_reference_price"]
    atr = row["atr_at_checkpoint"]
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return None

    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None

    session_close_ns = int(market.day_close_ns[start])
    session_end = int(
        np.searchsorted(market.day_close_ns, market.day_close_ns[start], side="right")
    )

    confirm_ns = regimes.next_start_after(entry_ns, direction)
    exit_flip_ns = regimes.next_start_after(entry_ns, -direction)

    horizon = session_close_ns
    if exit_flip_ns is not None:
        horizon = min(horizon, exit_flip_ns)
    end = min(market.index_at_or_after(horizon) + 1, session_end, market.n)
    if end <= start:
        return None

    hi, lo = market.high[start:end], market.low[start:end]
    ts = market.ts[start:end]
    favorable = (hi - entry_price) if direction > 0 else (entry_price - lo)
    adverse = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr

    stop_hits = np.flatnonzero(run_mae >= STOP_ATR)
    stop_idx = int(stop_hits[0]) if stop_hits.size else -1

    confirm_idx = -1
    if confirm_ns is not None and confirm_ns <= int(ts[-1]):
        found = np.flatnonzero(ts >= confirm_ns)
        if found.size:
            confirm_idx = int(found[0])

    reached_exit_flip = (
        exit_flip_ns is not None and int(ts[-1]) >= exit_flip_ns - NS
    )

    # Classification, in milestone order.
    if stop_idx >= 0 and (confirm_idx < 0 or stop_idx < confirm_idx):
        outcome, idx = STOPPED_BEFORE, stop_idx
    elif stop_idx >= 0:
        outcome, idx = STOPPED_AFTER, stop_idx
    elif reached_exit_flip:
        outcome, idx = FLIP_EXIT, ts.size - 1
    else:
        outcome, idx = SESSION_CLOSE, ts.size - 1

    if outcome in (STOPPED_BEFORE, STOPPED_AFTER):
        fill = idx + 1
        if start + fill >= session_end or start + fill >= market.n:
            exit_price = float(market.close[end - 1])
        else:
            exit_price = float(market.open_[start + fill])
    else:
        exit_price = float(market.close[start + idx])

    points = (exit_price - entry_price) * direction
    gross = 0.0 if abs(points) < FLAT_POINTS else points / atr
    net = gross - COST_POINTS / atr

    # Surviving to confirmation means the confirm flip arrived while the trade
    # was still open. `confirm_idx >= 0` alone only says the flip fell inside the
    # window, which extends to the opposing flip whether or not the stop fired
    # first -- so on its own it counts stopped-out trades as having confirmed.
    survived_to_confirm = confirm_idx >= 0 and (stop_idx < 0 or confirm_idx <= stop_idx)

    record = {
        "outcome": outcome,
        "gross_atr": gross,
        "net_atr": net,
        "mfe_atr": float(run_mfe[idx]),
        "mae_atr": float(run_mae[idx]),
        "reached_confirm": survived_to_confirm,
        "confirm_in_window": confirm_idx >= 0,
        "seconds_held": float((int(ts[idx]) - entry_ns) / NS),
        "entry_year": row["entry_year"],
        "direction": direction,
        "regime_age_at_entry_s": row["seconds_from_regime_start"],
    }
    if survived_to_confirm:
        record["seconds_to_confirm"] = float((int(ts[confirm_idx]) - entry_ns) / NS)
        record["mfe_to_confirm_atr"] = float(run_mfe[confirm_idx])
        record["mae_to_confirm_atr"] = float(run_mae[confirm_idx])
        confirm_close = float(market.close[start + confirm_idx])
        confirm_points = (confirm_close - entry_price) * direction
        record["return_at_confirm_atr"] = confirm_points / atr
    return record


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    a = np.array(values, dtype=float)
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p25": float(np.percentile(a, 25)),
        "p75": float(np.percentile(a, 75)),
    }


def analyze(records: list[dict]) -> dict:
    total = len(records)
    if not total:
        return {"trades": 0}

    by_outcome = {
        o: [r for r in records if r["outcome"] == o]
        for o in (STOPPED_BEFORE, STOPPED_AFTER, FLIP_EXIT, SESSION_CLOSE)
    }
    flip = by_outcome[FLIP_EXIT]
    winners = [r for r in flip if r["gross_atr"] > 0]
    losers = [r for r in flip if r["gross_atr"] < 0]
    flat = [r for r in flip if r["gross_atr"] == 0]

    reached = [r for r in records if r["reached_confirm"]]
    # Winner/loser split is by FINAL outcome at the regime flip exit.
    confirm_winners = [r for r in reached if r["outcome"] == FLIP_EXIT and r["gross_atr"] > 0]
    confirm_losers = [
        r for r in reached
        if r["outcome"] != FLIP_EXIT or r["gross_atr"] < 0
    ]

    # Arithmetic identity: survival to confirmation must equal the trades that
    # were not stopped before it, minus any cut short by the session first.
    expected = len(by_outcome[STOPPED_AFTER]) + len(flip)
    assert len(reached) >= expected, (
        f"survival accounting broken: reached={len(reached)} < "
        f"stopped_after+flip_exit={expected}"
    )
    assert len(reached) + len(by_outcome[STOPPED_BEFORE]) <= total, (
        "a trade cannot both survive to confirmation and be stopped before it"
    )

    out = {
        "trades": total,
        "counts": {o: len(v) for o, v in by_outcome.items()},
        "pct": {o: round(100 * len(v) / total, 2) for o, v in by_outcome.items()},
        "survived_to_confirm": len(reached),
        "survived_to_confirm_pct": round(100 * len(reached) / total, 2),
        "survived_to_flip_exit": len(flip),
        "survived_to_flip_exit_pct": round(100 * len(flip) / total, 2),
        "flip_exit_positive": len(winners),
        "flip_exit_negative": len(losers),
        "flip_exit_flat": len(flat),
        "flip_exit_win_rate": round(len(winners) / len(flip), 4) if flip else None,
        "mfe_by_outcome": {
            o: _stats([r["mfe_atr"] for r in v]) for o, v in by_outcome.items()
        },
        "return_by_outcome": {
            o: _stats([r["net_atr"] for r in v]) for o, v in by_outcome.items()
        },
        "mfe_to_confirm": {
            "winners": _stats([r["mfe_to_confirm_atr"] for r in confirm_winners]),
            "losers": _stats([r["mfe_to_confirm_atr"] for r in confirm_losers]),
        },
        "return_at_confirm": {
            "winners": _stats([r["return_at_confirm_atr"] for r in confirm_winners]),
            "losers": _stats([r["return_at_confirm_atr"] for r in confirm_losers]),
        },
        "seconds_to_confirm": {
            "winners": _stats([r["seconds_to_confirm"] for r in confirm_winners]),
            "losers": _stats([r["seconds_to_confirm"] for r in confirm_losers]),
        },
        "net_expectancy_all": float(np.mean([r["net_atr"] for r in records])),
        "gross_expectancy_all": float(np.mean([r["gross_atr"] for r in records])),
    }
    return out


def main() -> None:
    print("loading ...", flush=True)
    market = load_market()
    regimes = load_regimes()
    scored = load_scored()
    print(f"  {market.n:,} RTH bars, {scored.height:,} in-domain checkpoints\n", flush=True)

    report = {
        "population": f"first crossing per regime, regime age at entry > {MIN_REGIME_AGE_S:.0f}s",
        "stop_atr": STOP_ATR,
        "session": "forced flat 15:00 CT",
        "cost_points_round_turn": COST_POINTS,
        "levels": {},
    }

    for label in LEVELS:
        entries = entries_for(scored, label)
        records = []
        for row in entries.iter_rows(named=True):
            r = classify(market, regimes, row)
            if r is not None:
                records.append(r)
        stats = analyze(records)
        stats["candidates"] = entries.height
        report["levels"][label] = stats

        c = stats["counts"]
        print(
            f"{label:8s} n={stats['trades']:>6,}  "
            f"stopped_pre={c[STOPPED_BEFORE]:>5,} ({stats['pct'][STOPPED_BEFORE]:>5.1f}%)  "
            f"stopped_post={c[STOPPED_AFTER]:>5,} ({stats['pct'][STOPPED_AFTER]:>5.1f}%)  "
            f"flip_exit={c[FLIP_EXIT]:>5,} ({stats['pct'][FLIP_EXIT]:>5.1f}%)  "
            f"session={c[SESSION_CLOSE]:>5,} ({stats['pct'][SESSION_CLOSE]:>5.1f}%)",
            flush=True,
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "regime_lifecycle_600s.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    print(f"\nwrote {(RESULTS / 'regime_lifecycle_600s.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()

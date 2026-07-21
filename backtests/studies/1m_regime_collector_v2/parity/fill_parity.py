"""Gate 2/3 — fillability + fill_time/fill_price parity.

Re-derives `fillable_at_T`, `fill_time_actual`, `fill_price` INDEPENDENTLY
from raw 1s bars using only the §7.1 spec rules (first 1s bar at or after
fill_time_intended, subject to horizon / slippage cap / termination
gates). Then compares against the collector-emitted values for each
sampled checkpoint.

Matching criteria:
  - `fillable_at_T` must match exactly
  - For fillable rows: `fill_time_actual` must match exactly (int ns)
  - For fillable rows: `fill_price` must match within 1e-12 (bar open
    is a clean price, no tolerance needed; this guards float coercion)

MAX_SLIPPAGE_S and MAX_CHECKPOINT_S must match the collector config.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

MAX_SLIPPAGE_S = 60
MAX_CHECKPOINT_S = 1800


def rederive_fill_for_row(
    signal_time: int,
    fill_time_intended: int,
    regime_exit_time: int | None,
    bars_1s: pd.DataFrame,
) -> dict:
    """Re-derive fill outcome for a single checkpoint.

    Inputs are all int-ns timestamps except bars_1s (DataFrame with
    columns `ts_event`, `open`, `high`, `low`).

    Returns:
      dict with keys: fillable, fill_time_actual, fill_price, reason
    """
    horizon_ns = signal_time + MAX_CHECKPOINT_S * 1_000_000_000

    # Gate 1: fill_time_intended must be strictly before horizon.
    # (Matches collector: checks `cp.fill_time >= horizon_ns` → reject)
    if fill_time_intended >= horizon_ns:
        return {
            "fillable": False,
            "fill_time_actual": None,
            "fill_price": None,
            "reason": "past_horizon",
        }

    # First 1s bar with ts_event ≥ fill_time_intended.
    cand = bars_1s[bars_1s["ts_event"] >= fill_time_intended]
    if len(cand) == 0:
        return {
            "fillable": False,
            "fill_time_actual": None,
            "fill_price": None,
            "reason": "no_bar_after_fit",
        }
    first = cand.iloc[0]
    fat = int(first["ts_event"])
    fp = float(first["open"])

    # Gate 2: slippage cap — actual ts must be within MAX_SLIPPAGE_S of
    # intended. (Matches collector: `slip_ns > slip_cap_ns` → reject)
    slip_ns = fat - fill_time_intended
    if slip_ns > MAX_SLIPPAGE_S * 1_000_000_000:
        return {
            "fillable": False,
            "fill_time_actual": None,
            "fill_price": None,
            "reason": "slippage_cap",
        }

    # Gate 3: regime liveness at fill — event must be alive strictly
    # after fat. (Matches collector: `regime_exit_time <= ts` → reject)
    if regime_exit_time is not None and regime_exit_time <= fat:
        return {
            "fillable": False,
            "fill_time_actual": None,
            "fill_price": None,
            "reason": "terminated_before_fill",
        }

    return {
        "fillable": True,
        "fill_time_actual": fat,
        "fill_price": fp,
        "reason": "ok",
    }


def run_fill_parity(
    sample: pd.DataFrame,
    bars_1s: pd.DataFrame,
) -> pd.DataFrame:
    """Re-derive fill outcomes for each sample row; return comparison df."""
    results = []
    # Index bars by ts_event for faster filtering
    bars_sorted = bars_1s.sort_values("ts_event").reset_index(drop=True)
    bars_ts = bars_sorted["ts_event"].values

    for _, row in sample.iterrows():
        fit = int(row["fill_time_intended"])
        sig_t = int(row["signal_time"])
        exit_t = row["regime_exit_time"]
        if pd.isna(exit_t):
            exit_t = None
        else:
            exit_t = int(exit_t)

        # Slice bars near fit via searchsorted for perf
        lo = np.searchsorted(bars_ts, fit, side="left")
        hi = min(lo + 200, len(bars_sorted))  # 200 bars = ~200s of coverage
        nearby = bars_sorted.iloc[lo:hi]

        derived = rederive_fill_for_row(
            signal_time=sig_t,
            fill_time_intended=fit,
            regime_exit_time=exit_t,
            bars_1s=nearby,
        )

        col_fillable = bool(row["fillable_at_T"])
        col_fat = row["fill_time_actual"]
        col_fp = row["fill_price"]

        fillable_match = (col_fillable == derived["fillable"])
        if derived["fillable"]:
            fat_match = (not pd.isna(col_fat)
                          and int(col_fat) == derived["fill_time_actual"])
            fp_match = (not pd.isna(col_fp)
                         and abs(float(col_fp) - derived["fill_price"])
                         < 1e-12)
        else:
            # Unfillable: both should have null fat/fp
            fat_match = pd.isna(col_fat)
            fp_match = pd.isna(col_fp)

        results.append({
            "event_id": int(row["event_id"]),
            "checkpoint_s": int(row["checkpoint_s"]),
            "is_rth": bool(row.get("is_rth_checkpoint", False)),
            "col_fillable": col_fillable,
            "derived_fillable": derived["fillable"],
            "fillable_match": fillable_match,
            "col_fat": col_fat,
            "derived_fat": derived["fill_time_actual"],
            "fat_match": fat_match,
            "col_fp": col_fp,
            "derived_fp": derived["fill_price"],
            "fp_match": fp_match,
            "derived_reason": derived["reason"],
            "all_match": fillable_match and fat_match and fp_match,
        })
    return pd.DataFrame(results)

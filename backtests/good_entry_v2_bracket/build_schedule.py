"""Build the trade schedule for the NT backtest.

Takes:
  - Phase 3 Huber predictions (score + fill_time_actual + fill_price)
  - v2 event summary (regime_exit_time + regime_exit_price)

Filters to a configurable slice (default: RTH-Short × 180-300s × top-10%
by score), merges in regime-exit info, and emits a schedule parquet
ready for the NT strategy.

Schedule columns:
  - entry_ts_ns           1s bar at which to submit the market order
  - direction             +1 (long) / -1 (short)
  - atr_at_signal         used to compute PT/SL offsets
  - expected_fill_price   offline fill price (for reporting delta vs NT)
  - regime_exit_ts_ns     when to cancel bracket + close position
  - regime_exit_price     offline exit price (reporting delta only)
  - event_id, checkpoint_s, score   audit fields
"""

from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def build_schedule(
    predictions_path: Path,
    event_summary_path: Path,
    out_path: Path,
    slice_name: str,
    top_k_frac: float = 0.10,
) -> pd.DataFrame:
    pred = pd.read_parquet(predictions_path)
    es = pd.read_parquet(event_summary_path)[
        ["event_id", "regime_exit_time", "regime_exit_price",
         "regime_exit_reason"]]
    # predictions file may not carry fill_price / fill_time_actual —
    # merge from the correct year's feature snapshots parquet
    missing = [c for c in ("fill_price", "fill_time_actual")
                if c not in pred.columns]
    if missing:
        feat_cols = ["event_id", "checkpoint_s"] + missing
        # Infer year from predictions — all rows should share the same
        # year since the sweep files are per-year
        years_in_pred = pred["year"].unique() if "year" in pred.columns else []
        if len(years_in_pred) != 1:
            # Fall back to 2025 (legacy behavior) if year column
            # absent or multi-year
            snap_year = 2025
        else:
            snap_year = int(years_in_pred[0])
        feat_path = (
            f"studies/1m_regime_collector_v2/results/"
            f"v2_feature_snapshots_{snap_year}.parquet")
        feat_ = pd.read_parquet(feat_path, columns=feat_cols)
        pred = pred.merge(feat_, on=["event_id", "checkpoint_s"],
                           how="left")

    # Filter to slice
    if slice_name == "rth_short_180_300":
        pred_sub = pred[(pred["is_rth_checkpoint"] == 1)
                         & (pred["signal_direction"] == -1)
                         & (pred["checkpoint_s"] >= 180)
                         & (pred["checkpoint_s"] < 300)]
    elif slice_name == "rth_short":
        pred_sub = pred[(pred["is_rth_checkpoint"] == 1)
                         & (pred["signal_direction"] == -1)]
    elif slice_name == "rth":
        pred_sub = pred[pred["is_rth_checkpoint"] == 1]
    elif slice_name == "rth_300_450":
        pred_sub = pred[(pred["is_rth_checkpoint"] == 1)
                         & (pred["checkpoint_s"] >= 300)
                         & (pred["checkpoint_s"] < 450)]
    else:
        raise ValueError(f"unknown slice: {slice_name}")

    thr = pred_sub["score"].quantile(1.0 - top_k_frac)
    top = pred_sub[pred_sub["score"] >= thr].copy()

    sched = top.merge(es, on="event_id", how="inner")
    sched = sched.sort_values("fill_time_actual").reset_index(drop=True)

    out = pd.DataFrame({
        "entry_ts_ns": sched["fill_time_actual"].astype("int64"),
        "direction": sched["signal_direction"].astype("int8"),
        "atr_at_signal": sched["atr_at_signal"].astype("float64"),
        "expected_fill_price": sched["fill_price"].astype("float64"),
        "regime_exit_ts_ns": sched["regime_exit_time"].astype("int64"),
        "regime_exit_price":
            sched["regime_exit_price"].astype("float64"),
        "regime_exit_reason": sched["regime_exit_reason"].astype("string"),
        "event_id": sched["event_id"].astype("int64"),
        "checkpoint_s": sched["checkpoint_s"].astype("int32"),
        "score": sched["score"].astype("float64"),
    })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    print(f"Slice: {slice_name} top-{int(top_k_frac*100)}%")
    print(f"  Score threshold: {thr:.4f}")
    print(f"  Trades scheduled: {len(out):,}")
    print(f"  Date range: "
           f"{pd.Timestamp(int(out['entry_ts_ns'].min()), unit='ns')} "
           f"- {pd.Timestamp(int(out['entry_ts_ns'].max()), unit='ns')}")
    print(f"  Long/Short: {(out['direction'] == 1).sum()} / "
           f"{(out['direction'] == -1).sum()}")
    print(f"  Saved: {out_path}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--predictions",
        default="studies/good_entry_v2/results/"
                 "phase3_oos_predictions_huber.parquet")
    ap.add_argument(
        "--event-summary",
        default="studies/1m_regime_collector_v2/results/"
                 "v2_event_summary_2025.parquet",
        help="Event summary parquet for the target year — override "
              "for non-2025 runs (e.g. v2_event_summary_2024.parquet)")
    ap.add_argument(
        "--out",
        default="backtests/good_entry_v2_bracket/results/"
                 "schedule_rth_short_180_300.parquet")
    ap.add_argument(
        "--slice",
        choices=["rth_short_180_300", "rth_short", "rth",
                  "rth_300_450"],
        default="rth_short_180_300")
    ap.add_argument("--top-k-frac", type=float, default=0.10)
    args = ap.parse_args()

    build_schedule(
        Path(args.predictions),
        Path(args.event_summary),
        Path(args.out),
        slice_name=args.slice,
        top_k_frac=args.top_k_frac,
    )


if __name__ == "__main__":
    main()

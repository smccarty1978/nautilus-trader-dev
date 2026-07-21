"""Extracts the March-2025 rows from each of the three already-computed,
already-audited entry-policy trigger schedules
(studies/short_rth_pure_flip_score_entry_policy/_work/schedule_trig_*_2025.parquet)
and remaps columns to the NT strategy's expected schedule format.

The strategy reads ONLY: regime_start_ns, signal_decision_ts, atr_at_checkpoint,
entry_direction. confirm_flip_ns is carried for RECONCILIATION ONLY (never
read by the strategy's decision logic), matching
fable5_nt_short_rth_policy_a/build_schedule.py's documented convention.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402


def build(variant_label: str, trigger_key: str) -> pd.DataFrame:
    src = pd.read_parquet(C.ENTRY_POLICY_WORK / f"schedule_{trigger_key}_2025.parquet",
                          columns=["regime_start_ns", "observation_time", "entry_ts",
                                  "atr_at_entry", "confirm_flip_ns"])
    src["month"] = pd.to_datetime(src["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
    month_rows = src[src["month"] == C.SELECTED_MONTH].sort_values("observation_time").reset_index(drop=True)
    out = pd.DataFrame({
        "regime_start_ns": month_rows["regime_start_ns"].astype("int64"),
        "signal_decision_ts": month_rows["observation_time"].astype("int64"),
        "atr_at_checkpoint": month_rows["atr_at_entry"].astype(float),
        "entry_direction": -1,
        "recon_confirm_flip_ns": month_rows["confirm_flip_ns"].astype("int64"),
    })
    if (out["atr_at_checkpoint"] <= 0).any() or out["atr_at_checkpoint"].isna().any():
        raise RuntimeError(f"{variant_label}: non-positive/NaN ATR in schedule")
    if out["regime_start_ns"].duplicated().any():
        raise RuntimeError(f"{variant_label}: duplicate regime_start_ns in schedule "
                          "-- 'at most one entry per regime' violated upstream")
    return out


def main() -> None:
    for label, key in C.VARIANTS.items():
        out = build(label, key)
        out.to_parquet(C.schedule_path(label), index=False)
        print(f"{label} ({key}): {len(out)} entries in {C.SELECTED_MONTH} -> {C.schedule_path(label)}")


if __name__ == "__main__":
    main()

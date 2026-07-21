"""Build the matched-cohort table for the delayed-entry study.

For each event in the v2 corpus that has a fillable T=0 row AND a
fillable T_d row, this module emits one row per (event_id, T_d) with
both T=0 and T_d label values side-by-side. Downstream analysis just
needs to read this single parquet — no further joining required.

Per SPEC.md §"Matched cohort rule":
  matched(T_d) = events fillable at T=0 AND fillable at T_d

This isolates the delay effect from the survivor effect.
"""

from __future__ import annotations
import pandas as pd
from pathlib import Path

CHECKPOINTS = [0, 30, 60, 90, 120, 300, 600]
LABEL_COLS = [
    "regime_exit_pnl_pts",
    "regime_exit_pnl_atr",
    "regime_exit_pnl_dollars",
    "regime_exit_time_s",
    "pt100_before_sl100",
    "pt150_before_sl100",
    "pt200_before_sl100",
    "pt300_before_sl150",
    "mfe_30s_atr", "mae_30s_atr",
    "mfe_60s_atr", "mae_60s_atr",
    "mfe_120s_atr", "mae_120s_atr",
    "mfe_300s_atr", "mae_300s_atr",
    "mfe_600s_atr", "mae_600s_atr",
    "clean_path_120s", "clean_path_300s", "clean_path_600s",
    "fast_fail_60s",
    "strong_followthrough_300s",
]
# Feature columns we keep on every row for stratification
STRATUM_COLS = [
    "signal_direction",
    "is_rth_checkpoint",
    "atr_at_signal",
    "regime_exit_reason",
    "event_total_duration_s",
]


def load_year(features_path: Path, labels_path: Path) -> pd.DataFrame:
    """Load + merge one year of v2 collector output.

    Returns a long table with one row per (event_id, checkpoint_s)
    containing fill state, signal context, and all forward labels.
    """
    feats = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)

    # Pull just what we need from features
    feat_cols = ["event_id", "checkpoint_s", "fillable_at_T",
                  "fill_price", "fill_time_actual",
                  *STRATUM_COLS]
    feats = feats[feat_cols].copy()

    # Pull labels
    lbl_cols = ["event_id", "checkpoint_s", *LABEL_COLS]
    labels = labels[lbl_cols].copy()

    merged = feats.merge(labels, on=["event_id", "checkpoint_s"],
                          how="inner")
    return merged


def build_matched_cohort(
    long_df: pd.DataFrame,
    checkpoints: list[int] = CHECKPOINTS,
) -> pd.DataFrame:
    """Build the per-(event, T_d) matched cohort table.

    For every event whose T=0 row is fillable, emit one row per T_d
    (including T_d=0 itself, for symmetry) with:
      - T=0 label values (suffix `_t0`)
      - T_d label values (suffix `_td`)
      - delta columns (T_d − T=0) for the key endpoints

    Events without a fillable T=0 row are EXCLUDED. Events without a
    fillable T_d row for a given T_d are EXCLUDED from that T_d's
    cohort but kept for other T_d's where they are fillable.
    """
    # Restrict to fillable rows only
    fillable = long_df[long_df["fillable_at_T"] == True].copy()

    # T=0 baseline: one row per event
    t0 = fillable[fillable["checkpoint_s"] == 0].copy()
    t0_baseline = t0[["event_id", *LABEL_COLS,
                       *STRATUM_COLS, "fill_price"]].copy()
    t0_baseline.columns = (["event_id"]
        + [f"{c}_t0" for c in LABEL_COLS]
        + [f"{c}_t0" for c in STRATUM_COLS]
        + ["fill_price_t0"])

    # For each T_d, join T_d rows to T=0 baseline on event_id
    rows = []
    for T_d in checkpoints:
        td_rows = fillable[fillable["checkpoint_s"] == T_d].copy()
        td_view = td_rows[["event_id", *LABEL_COLS, "fill_price"]].copy()
        td_view.columns = (["event_id"]
            + [f"{c}_td" for c in LABEL_COLS]
            + ["fill_price_td"])
        td_view["T_d"] = T_d

        # Inner join on event_id — matched cohort definition
        matched = t0_baseline.merge(td_view, on="event_id", how="inner")
        rows.append(matched)

    matched_long = pd.concat(rows, ignore_index=True)

    # Compute deltas for key endpoints
    for c in LABEL_COLS:
        # Numeric delta where both sides defined; NaN propagates
        matched_long[f"{c}_delta"] = (matched_long[f"{c}_td"]
                                       - matched_long[f"{c}_t0"])

    return matched_long


def collect_all_years(
    results_dir: Path,
    years: list[int],
) -> pd.DataFrame:
    """Load all 6 years and concat into one long table."""
    chunks = []
    for y in years:
        f = results_dir / f"v2_feature_snapshots_{y}.parquet"
        l = results_dir / f"v2_outcome_labels_{y}.parquet"
        if not f.exists():
            print(f"  WARN: missing {f}")
            continue
        df = load_year(f, l)
        df["year"] = y
        chunks.append(df)
        print(f"  {y}: {len(df):,} checkpoint rows")
    return pd.concat(chunks, ignore_index=True)

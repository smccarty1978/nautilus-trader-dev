"""Assemble the good-entry cohort from the v2 corpus.

Output: one row per (event_id, year, checkpoint_s) where checkpoint_s ∈
{0, 30, ..., 600} and the row was emitted by the v2 collector. Each
row includes:
  - all 177 model_feature columns from the feature contract
  - the good_entry_300s label
  - stratification fields (year, is_rth_checkpoint, signal_direction)
  - audit fields (fillable_at_T, mfe_300s_censored, regime_exit_pnl_dollars,
    pt100_before_sl100)

The cohort INCLUDES unfillable rows so we can audit fillability rates
per checkpoint. ML training in Phase 2 will filter to fillable_at_T==1.
"""

from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

CHECKPOINTS = list(range(0, 601, 30))  # 0, 30, 60, ..., 600

# Audit columns kept on every row (in addition to model_feature columns)
AUDIT_COLS_FEATURES = [
    "fillable_at_T",
    "fill_time_actual",
    "fill_price",
    "regime_exit_reason",
    "event_total_duration_s",
]
AUDIT_COLS_LABELS = [
    "mfe_300s_atr",
    "mae_300s_atr",
    "mfe_mae_ratio_300s",
    "mfe_300s_censored",
    "regime_exit_pnl_dollars",
    "regime_exit_pnl_atr",
    "pt100_before_sl100",
]


def load_model_feature_names(contract_path: Path) -> list[str]:
    """Read feature_contract_v2.json and extract role==model_feature."""
    with open(contract_path) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def load_year(
    features_path: Path,
    labels_path: Path,
    model_features: list[str],
) -> pd.DataFrame:
    """Merge one year's features + labels, restricted to checkpoints
    in [0, 600] every 30s. Keeps model_feature cols + audit cols."""
    feats = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)

    # Restrict to T in {0, 30, ..., 600}
    feats = feats[feats["checkpoint_s"].isin(CHECKPOINTS)].copy()
    labels = labels[labels["checkpoint_s"].isin(CHECKPOINTS)].copy()

    # Keep model_feature cols + audit cols (intersection with what's
    # actually emitted — robust to contract drift). Dedupe to keep
    # join keys (event_id, checkpoint_s) exactly once.
    feat_set: list[str] = ["event_id", "checkpoint_s"]
    seen = set(feat_set)
    for c in model_features + AUDIT_COLS_FEATURES:
        if c in feats.columns and c not in seen:
            feat_set.append(c)
            seen.add(c)
    feats = feats[feat_set]

    lbl_set: list[str] = ["event_id", "checkpoint_s"]
    lbl_seen = set(lbl_set)
    for c in AUDIT_COLS_LABELS:
        if c in labels.columns and c not in lbl_seen:
            lbl_set.append(c)
            lbl_seen.add(c)
    labels = labels[lbl_set]

    merged = feats.merge(labels, on=["event_id", "checkpoint_s"],
                          how="inner")
    return merged


def add_label(df: pd.DataFrame) -> pd.DataFrame:
    """Compute good_entry_300s label.

    good_entry_300s = 1 iff mfe_300s_atr > 1.0 AND mfe_mae_ratio_300s > 1.25
    Censored values are kept AS-IS (per project policy — no row exclusion).
    Unfillable rows get label = 0 (no trade entered, can't be a "good entry").
    """
    cond = ((df["mfe_300s_atr"] > 1.0)
             & (df["mfe_mae_ratio_300s"] > 1.25)
             & (df["fillable_at_T"] == True))
    df = df.copy()
    df["good_entry_300s"] = cond.astype("int8")
    return df


def collect_all_years(
    results_dir: Path,
    contract_path: Path,
    years: list[int],
) -> pd.DataFrame:
    """Load all years, restrict to first-600s checkpoints, attach label."""
    model_features = load_model_feature_names(contract_path)
    print(f"  Model features in contract: {len(model_features)}")

    chunks = []
    for y in years:
        f = results_dir / f"v2_feature_snapshots_{y}.parquet"
        l = results_dir / f"v2_outcome_labels_{y}.parquet"
        if not f.exists():
            print(f"  WARN: missing {f}")
            continue
        df = load_year(f, l, model_features)
        df["year"] = y
        chunks.append(df)
        print(f"  {y}: {len(df):,} cohort rows "
               f"(T ∈ {min(CHECKPOINTS)}..{max(CHECKPOINTS)})")

    full = pd.concat(chunks, ignore_index=True)
    full = add_label(full)
    return full

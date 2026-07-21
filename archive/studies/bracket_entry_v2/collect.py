"""Assemble the RTH bracket-entry cohort from the v2 corpus.

For each fillable RTH checkpoint row at T ∈ {0, 30, ..., 600}, attach:
  - good_bracket_entry label (see SPEC.md)
  - resolved/unresolved flag (derived from pt100_before_sl100)
  - all 177 model_feature columns from feature_contract_v2.json
  - audit fields for bracket economics (atr_at_signal, resolution time)

Unresolved rows are KEPT in the cohort (for the unresolved-rate
report) but filtered out at training time.
"""

from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

CHECKPOINTS = list(range(0, 601, 30))  # 0, 30, ..., 600

AUDIT_COLS_FEATURES = [
    "fillable_at_T",
    "fill_time_actual",
    "fill_price",
    "regime_exit_reason",
    "event_total_duration_s",
]
AUDIT_COLS_LABELS = [
    "pt100_before_sl100",
    "mfe_mae_ratio_300s",
    "bracket_resolution_time_s_pt100_before_sl100",
    "mfe_300s_atr",
    "mae_300s_atr",
    "mfe_300s_censored",
    "regime_exit_pnl_dollars",
    "regime_exit_pnl_atr",
]


def load_model_feature_names(contract_path: Path) -> list[str]:
    with open(contract_path) as f:
        c = json.load(f)
    return [f["name"] for f in c["features"]
            if f.get("role") == "model_feature"]


def load_year(
    features_path: Path,
    labels_path: Path,
    model_features: list[str],
) -> pd.DataFrame:
    feats = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)

    feats = feats[feats["checkpoint_s"].isin(CHECKPOINTS)].copy()
    labels = labels[labels["checkpoint_s"].isin(CHECKPOINTS)].copy()

    # Dedupe join keys from the feature column list
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


def add_target(df: pd.DataFrame) -> pd.DataFrame:
    """Compute good_bracket_entry + helper flags.

    good_bracket_entry = 1 iff
        pt100_before_sl100 == 1
        AND mfe_mae_ratio_300s > 1.25     # 300s substitute for 360s
        AND bracket_resolution_time_s_pt100_before_sl100 <= 360
    else 0

    Also flags:
      - unresolved (pt100 is NaN)
      - resolved (pt100 is 0 or 1)
    """
    df = df.copy()
    pt = df["pt100_before_sl100"]
    ratio = df["mfe_mae_ratio_300s"]
    rtime = df["bracket_resolution_time_s_pt100_before_sl100"]

    df["unresolved"] = pt.isna().astype("int8")
    df["resolved"] = (~pt.isna()).astype("int8")

    cond = ((pt == 1)
             & (ratio > 1.25)
             & (rtime <= 360)
             & (df["fillable_at_T"] == True))
    df["good_bracket_entry"] = cond.astype("int8")
    return df


def collect_all_years(
    results_dir: Path,
    contract_path: Path,
    years: list[int],
    rth_only: bool = True,
) -> pd.DataFrame:
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
        print(f"  {y}: {len(df):,} cohort rows (pre-RTH filter)")

    full = pd.concat(chunks, ignore_index=True)

    # Filter to fillable + RTH
    n_pre = len(full)
    full = full[full["fillable_at_T"] == True].copy()
    print(f"  Fillable: {len(full):,} (dropped {n_pre - len(full):,})")

    if rth_only and "is_rth_checkpoint" in full.columns:
        n_pre = len(full)
        full = full[full["is_rth_checkpoint"] == 1].copy()
        print(f"  RTH-only: {len(full):,} "
               f"(dropped {n_pre - len(full):,} ETH)")

    full = add_target(full)

    n_good = int((full["good_bracket_entry"] == 1).sum())
    n_res = int((full["resolved"] == 1).sum())
    print(f"  Resolved: {n_res:,} ({100*n_res/len(full):.1f}%)  "
           f"Good: {n_good:,} "
           f"({100*n_good/n_res:.1f}% of resolved, "
           f"{100*n_good/len(full):.1f}% of all)")

    return full

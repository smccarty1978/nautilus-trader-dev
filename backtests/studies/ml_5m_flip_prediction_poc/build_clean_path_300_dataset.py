"""POC dataset — target_clean_path_300s for T_d ∈ {0, 60, 120}.

Target (per user decisions 2026-04-23):
  target_clean_path_300s = 1 iff:
    forward_mfe_at_300s >= 1.0
    AND forward_mfe_at_300s / forward_mae_at_300s > 1.0
  target_clean_path_300s = 0 if:
    trade died before 300s (no clean path achieved)
    OR forward fields populated but conditions NOT met
  target_clean_path_300s = NaN ONLY if:
    trade is fillable at T but forward fields themselves are unavailable
    (data gap), NOT censoring due to early death

Uses the existing post-fix ml_5m_flip_prediction_dataset.parquet. Pulls
forward fields from trades_all.parquet directly since the ML dataset
excluded them.

Output:
  studies/ml_5m_flip_prediction_poc/results/clean_path_300_dataset.parquet
  studies/ml_5m_flip_prediction_poc/results/clean_path_300_dataset_qa.log
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
                "trades_all.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction_poc/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PARQUET = OUT_DIR / "clean_path_300_dataset.parquet"
OUT_LOG = OUT_DIR / "clean_path_300_dataset_qa.log"

POC_CHECKPOINTS = [0, 60, 120]
MFE_THRESHOLD = 1.0

# Columns to pull from trades_all for forward fields
FWD_STEMS = [
    "forward_mfe_at_300s",
    "forward_mae_at_300s",
    "forward_peak_mfe_atr",
    "forward_peak_mae_atr",
    "forward_pt100_before_sl100",
    "forward_regime_pnl_dollars",
    "forward_regime_remaining_s",
    "dead_before",
    "fillable_at",
    "alive_at",
]


def main():
    lines = []

    print("Loading ML dataset...")
    ds = pd.read_parquet(DS_PATH)
    print(f"  {len(ds):,} rows, {len(ds.columns):,} cols")
    lines.append("=" * 100)
    lines.append("POC DATASET BUILD — clean_path_300s target")
    lines.append("=" * 100)
    lines.append(f"\n  ML dataset rows: {len(ds):,}")

    # Filter to our decision checkpoints + RTH
    sub = ds[
        ds["decision_checkpoint_s"].isin(POC_CHECKPOINTS)
        & (ds["is_rth"] == 1)
    ].copy()
    print(f"  After T∈{POC_CHECKPOINTS} + RTH filter: {len(sub):,}")
    lines.append(
        f"  After T∈{{0, 60, 120}} + RTH filter: {len(sub):,}")

    # Pull forward fields from trades_all per T
    print("Loading forward fields from trades_all...")
    need_cols = ["signal_ts"]
    for stem in FWD_STEMS:
        for T in POC_CHECKPOINTS:
            need_cols.append(f"{stem}_T_{T:03d}")
    trades = pd.read_parquet(TRADES_PATH, columns=need_cols)
    trades = trades.drop_duplicates(subset=["signal_ts"], keep="first")
    trades_idx = trades.set_index("signal_ts")

    # Build target and pull forward fields for each row's T_d
    print("Computing labels...")

    def label_for_row(row):
        """Return target_clean_path_300s and also populate forward_*
        columns."""
        T = int(row["decision_checkpoint_s"])
        tag = f"{T:03d}"
        eid = int(row["event_id"])
        try:
            rec = trades_idx.loc[eid]
        except KeyError:
            return pd.Series({"target_clean_path_300s": np.nan})
        mfe = rec[f"forward_mfe_at_300s_T_{tag}"]
        mae = rec[f"forward_mae_at_300s_T_{tag}"]
        fillable = rec[f"fillable_at_T_{tag}"]
        dead_before = rec[f"dead_before_T_{tag}"]

        # Not fillable at T_d (regime died before fill) → label=0 (no entry)
        # But actually we filter by fillable_at_T later too; here's the
        # semantics:
        # - Not fillable: trade never enters; skip (NaN so we drop)
        # - Fillable + dead before 300s (forward fields NaN):
        #     → label = 0 (no clean path achieved)
        # - Fillable + forward fields available:
        #     → label = 1 if mfe >= 1.0 AND mfe/mae > 1.0 else 0

        if pd.isna(fillable) or fillable != 1:
            return pd.Series({
                "target_clean_path_300s": np.nan,
                "_fwd_mfe_300": np.nan,
                "_fwd_mae_300": np.nan,
            })

        if pd.isna(mfe) or pd.isna(mae):
            # Trade died before 300s, no forward data → label = 0 per
            # user decision C1 (censored = 0, not NaN)
            return pd.Series({
                "target_clean_path_300s": 0,
                "_fwd_mfe_300": np.nan,
                "_fwd_mae_300": np.nan,
            })

        # Compute the target
        if mfe >= MFE_THRESHOLD and mae > 0 and (mfe / mae) > 1.0:
            y = 1
        elif mfe >= MFE_THRESHOLD and mae == 0:
            # Zero MAE with MFE >= 1.0 → "clean path" by definition
            y = 1
        else:
            y = 0
        return pd.Series({
            "target_clean_path_300s": y,
            "_fwd_mfe_300": mfe,
            "_fwd_mae_300": mae,
        })

    # Vectorize per T_d for speed (instead of apply per row)
    sub["target_clean_path_300s"] = np.nan
    sub["_fwd_mfe_300"] = np.nan
    sub["_fwd_mae_300"] = np.nan

    for T in POC_CHECKPOINTS:
        tag = f"{T:03d}"
        tsel = sub["decision_checkpoint_s"] == T
        eids = sub.loc[tsel, "event_id"].values

        mfe = trades_idx[f"forward_mfe_at_300s_T_{tag}"].reindex(eids).values
        mae = trades_idx[f"forward_mae_at_300s_T_{tag}"].reindex(eids).values
        fillable = trades_idx[
            f"fillable_at_T_{tag}"].reindex(eids).values

        n = len(eids)
        y = np.full(n, np.nan)
        # Fillable trades:
        fill_mask = (fillable == 1)
        mfe_nan = np.isnan(mfe)
        mae_nan = np.isnan(mae)

        # Fillable + forward fields present
        ok_fwd = fill_mask & ~mfe_nan & ~mae_nan
        # Compute label
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio_gt_1 = np.where(mae > 0, mfe / mae > 1.0, True)
        label_1 = (mfe >= MFE_THRESHOLD) & ratio_gt_1
        y[ok_fwd & label_1] = 1
        y[ok_fwd & ~label_1] = 0

        # Fillable but forward fields NaN (trade died before 300s) → 0
        y[fill_mask & (mfe_nan | mae_nan)] = 0

        # Not fillable → NaN (data unavailability; row excluded)
        # (default NaN)

        sub.loc[tsel, "target_clean_path_300s"] = y
        sub.loc[tsel, "_fwd_mfe_300"] = mfe
        sub.loc[tsel, "_fwd_mae_300"] = mae

    # Save
    sub.to_parquet(OUT_PARQUET, index=False)
    print(f"  Saved: {OUT_PARQUET}")

    # QA summary
    lines.append(f"\n--- LABEL DISTRIBUTION ---")
    for T in POC_CHECKPOINTS:
        tsub = sub[sub["decision_checkpoint_s"] == T]
        y = tsub["target_clean_path_300s"]
        n = len(tsub)
        n_nan = y.isna().sum()
        n_pos = (y == 1).sum()
        n_neg = (y == 0).sum()
        rate = n_pos / (n_pos + n_neg) * 100 if (n_pos + n_neg) > 0 else 0
        lines.append(
            f"  T_d={T}: N={n:,}  pos={n_pos:,}  neg={n_neg:,}  "
            f"NaN={n_nan:,}  base_rate={rate:.1f}%")

    # By year
    lines.append(f"\n--- LABEL BY YEAR (pooled T) ---")
    for y_yr in sorted(sub["year"].unique()):
        tsub = sub[sub["year"] == y_yr]
        y_l = tsub["target_clean_path_300s"]
        n_pos = (y_l == 1).sum()
        n_neg = (y_l == 0).sum()
        rate = n_pos / (n_pos + n_neg) * 100 if (n_pos + n_neg) > 0 else 0
        lines.append(
            f"  {int(y_yr)}: N_valid={n_pos+n_neg:,}  "
            f"pos={n_pos:,}  rate={rate:.1f}%")

    # By direction
    lines.append(f"\n--- LABEL BY DIRECTION (pooled) ---")
    for d, lbl in [(1, "LONG"), (-1, "SHORT")]:
        tsub = sub[sub["signal_direction"] == d]
        y_l = tsub["target_clean_path_300s"]
        n_pos = (y_l == 1).sum()
        n_neg = (y_l == 0).sum()
        rate = n_pos / (n_pos + n_neg) * 100 if (n_pos + n_neg) > 0 else 0
        lines.append(
            f"  {lbl}: N_valid={n_pos+n_neg:,}  pos={n_pos:,}  "
            f"rate={rate:.1f}%")

    # Splits
    lines.append(f"\n--- TRAIN/VAL/TEST SPLIT (year-based) ---")
    for label, yrs in [("TRAIN", [2020, 2021, 2022, 2023]),
                        ("VAL", [2024]),
                        ("TEST", [2025])]:
        tsub = sub[sub["year"].isin(yrs)]
        y_l = tsub["target_clean_path_300s"]
        n_pos = (y_l == 1).sum()
        n_neg = (y_l == 0).sum()
        rate = n_pos / (n_pos + n_neg) * 100 if (n_pos + n_neg) > 0 else 0
        n_nan = y_l.isna().sum()
        lines.append(
            f"  {label:>6}: rows={len(tsub):,}  "
            f"valid={n_pos+n_neg:,}  NaN={n_nan:,}  pos={n_pos:,}  "
            f"rate={rate:.1f}%")

    out = "\n".join(lines)
    print("\n" + out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved log: {OUT_LOG}")


if __name__ == "__main__":
    main()

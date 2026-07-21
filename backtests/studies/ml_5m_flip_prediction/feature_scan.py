"""Phase 2b — Univariate feature scan (RTH primary, target=300s).

Reports Cohen's d and univariate AUC for each feature, ranked by |d|.
Appendix: same scan for ETH and POOLED at the top-feature level only.

Reads:  studies/ml_5m_flip_prediction/results/ml_5m_flip_prediction_dataset.parquet
Writes: studies/ml_5m_flip_prediction/results/ml_5m_flip_feature_scan.log
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
from sklearn.metrics import roc_auc_score

DATASET = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "ml_5m_flip_feature_scan.log")
TARGET = "target_5m_flip_within_300s"
METADATA_COLS = {
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
    "event_id", "decision_ts", "decision_fill_ts",
}


def scan_features(df: pd.DataFrame, feat_cols: list) -> pd.DataFrame:
    """For each feature, compute Cohen's d, AUC, means in each class."""
    sub = df[df[TARGET].notna()].copy()
    y = sub[TARGET].astype(int)
    pos_mask = y == 1
    neg_mask = y == 0

    rows = []
    for c in feat_cols:
        vals = sub[c].values.astype(float)
        # Handle NaN — drop for this feature only
        valid = ~np.isnan(vals)
        v = vals[valid]
        y_v = y.values[valid]
        pos_v = v[y_v == 1]
        neg_v = v[y_v == 0]
        n_valid = len(v)
        n_pos = len(pos_v)
        n_neg = len(neg_v)
        if n_pos < 20 or n_neg < 20:
            continue
        mean_pos = pos_v.mean()
        mean_neg = neg_v.mean()
        # Pooled SD
        var_pos = pos_v.var(ddof=1) if n_pos > 1 else 0.0
        var_neg = neg_v.var(ddof=1) if n_neg > 1 else 0.0
        pooled_var = (
            ((n_pos - 1) * var_pos + (n_neg - 1) * var_neg)
            / max(n_pos + n_neg - 2, 1)
        )
        pooled_sd = np.sqrt(pooled_var) if pooled_var > 0 else np.nan
        cohens_d = ((mean_pos - mean_neg) / pooled_sd
                    if pooled_sd and pooled_sd > 0 else 0.0)
        # Univariate AUC — higher-value-more-predictive direction
        try:
            auc = roc_auc_score(y_v, v)
        except Exception:
            auc = np.nan
        # Separation score — |AUC - 0.5| maps direction-agnostic
        auc_lift = (abs(auc - 0.5) if not np.isnan(auc) else 0.0)
        rows.append({
            "feature": c,
            "n_valid": n_valid,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "mean_pos": mean_pos,
            "mean_neg": mean_neg,
            "cohens_d": cohens_d,
            "abs_d": abs(cohens_d),
            "auc": auc,
            "auc_lift": auc_lift,
        })
    res = pd.DataFrame(rows)
    return res.sort_values("abs_d", ascending=False).reset_index(drop=True)


def fmt_table(res: pd.DataFrame, n: int = 25) -> str:
    """Format top-N features table."""
    lines = []
    lines.append(
        f"  {'rank':>4} {'feature':<42} "
        f"{'N':>7} {'mean_pos':>10} {'mean_neg':>10} "
        f"{'d':>6} {'AUC':>5} {'AUC_lift':>8}"
    )
    lines.append("  " + "-" * 100)
    for i in range(min(n, len(res))):
        r = res.iloc[i]
        lines.append(
            f"  {i+1:>4} {r['feature']:<42} "
            f"{int(r['n_valid']):>7,} "
            f"{r['mean_pos']:>+10.3f} {r['mean_neg']:>+10.3f} "
            f"{r['cohens_d']:>+6.2f} {r['auc']:>5.3f} "
            f"{r['auc_lift']:>+8.3f}"
        )
    return "\n".join(lines)


def main():
    df = pd.read_parquet(DATASET)
    print(f"Loaded {len(df):,} rows")

    # Feature columns = everything except metadata + targets
    feat_cols = [c for c in df.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")]

    # Drop zero-variance features (should be none after dataset build)
    feat_cols = [c for c in feat_cols if df[c].nunique(dropna=True) > 1]
    print(f"Scanning {len(feat_cols)} features on target={TARGET}")

    rth = df[df["is_rth"] == 1]
    eth = df[df["is_rth"] == 0]

    lines = []
    lines.append("=" * 140)
    lines.append(
        f"ML 5m FLIP PREDICTION — UNIVARIATE FEATURE SCAN  (target={TARGET})")
    lines.append("=" * 140)

    # ---- RTH primary ----
    print("Scanning RTH...")
    res_rth = scan_features(rth, feat_cols)
    n_valid = int(rth[TARGET].notna().sum())
    pos_rate = float(
        (rth[TARGET] == 1).sum() / n_valid * 100) if n_valid > 0 else 0
    lines.append("")
    lines.append(
        f"--- 1. RTH (primary) — N_valid={n_valid:,}, "
        f"base_rate={pos_rate:.1f}% ---")
    lines.append("    Ranked by |Cohen's d|. AUC_lift = |AUC - 0.5|.")
    lines.append("")
    lines.append("  TOP 25 BY |d|:")
    lines.append(fmt_table(res_rth, 25))

    lines.append("")
    lines.append("  TOP 25 BY AUC_lift:")
    top_auc = res_rth.sort_values("auc_lift", ascending=False).head(25)
    for i in range(len(top_auc)):
        r = top_auc.iloc[i]
        lines.append(
            f"  {i+1:>4} {r['feature']:<42} "
            f"d={r['cohens_d']:>+5.2f}  AUC={r['auc']:>5.3f}  "
            f"lift={r['auc_lift']:>+5.3f}  N={int(r['n_valid']):>6,}")

    lines.append("")
    lines.append("  BOTTOM 10 BY |d| (weakest separation):")
    bot = res_rth.tail(10)
    for i in range(len(bot)):
        r = bot.iloc[i]
        lines.append(
            f"     {r['feature']:<42} "
            f"d={r['cohens_d']:>+5.2f}  AUC={r['auc']:>5.3f}")

    # Save full RTH scan
    res_rth.to_parquet(
        "studies/ml_5m_flip_prediction/results/"
        "feature_scan_rth.parquet", index=False)

    # ---- ETH appendix ----
    print("Scanning ETH...")
    res_eth = scan_features(eth, feat_cols)
    n_valid_e = int(eth[TARGET].notna().sum())
    pos_rate_e = float(
        (eth[TARGET] == 1).sum() / n_valid_e * 100) if n_valid_e > 0 else 0
    lines.append("")
    lines.append("=" * 140)
    lines.append(
        f"--- 2. ETH (appendix) — N_valid={n_valid_e:,}, "
        f"base_rate={pos_rate_e:.1f}% ---")
    lines.append(
        "    ETH base rate ≈ 93% — most features will look 'informative' "
        "even when they're only separating session-heuristic quirks.")
    lines.append("")
    lines.append("  TOP 15 BY |d|:")
    lines.append(fmt_table(res_eth, 15))

    # ---- Pooled appendix ----
    print("Scanning POOLED...")
    res_pool = scan_features(df, feat_cols)
    n_valid_p = int(df[TARGET].notna().sum())
    pos_rate_p = float(
        (df[TARGET] == 1).sum() / n_valid_p * 100) if n_valid_p > 0 else 0
    lines.append("")
    lines.append("=" * 140)
    lines.append(
        f"--- 3. POOLED (appendix) — N_valid={n_valid_p:,}, "
        f"base_rate={pos_rate_p:.1f}% ---")
    lines.append(
        "    Pooled scan dominated by `is_rth` (encodes the session "
        "base-rate gap). Not a trading signal.")
    lines.append("")
    lines.append("  TOP 15 BY |d|:")
    lines.append(fmt_table(res_pool, 15))

    # ---- Summary ----
    lines.append("")
    lines.append("=" * 140)
    lines.append("--- 4. SUMMARY ---")
    # Count features with meaningful separation in RTH
    strong = (res_rth["abs_d"] >= 0.3).sum()
    moderate = ((res_rth["abs_d"] >= 0.2) & (res_rth["abs_d"] < 0.3)).sum()
    weak = ((res_rth["abs_d"] >= 0.1) & (res_rth["abs_d"] < 0.2)).sum()
    negligible = (res_rth["abs_d"] < 0.1).sum()
    lines.append(
        f"  RTH |d| distribution (target=300s):")
    lines.append(f"    |d| >= 0.30 (strong):      {strong:>3}")
    lines.append(f"    0.20 <= |d| < 0.30 (moderate): {moderate:>3}")
    lines.append(f"    0.10 <= |d| < 0.20 (weak):   {weak:>3}")
    lines.append(f"    |d| < 0.10 (negligible): {negligible:>3}")
    lines.append(
        f"  Max RTH univariate AUC: {res_rth['auc_lift'].max()+0.5:.3f} "
        f"(lift {res_rth['auc_lift'].max():.3f})")
    top5 = res_rth.head(5)
    lines.append("  Top 5 RTH features:")
    for _, r in top5.iterrows():
        lines.append(
            f"    {r['feature']}: d={r['cohens_d']:+.2f}  "
            f"AUC={r['auc']:.3f}")

    out = "\n".join(lines)
    print(out[:3000])
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\nSaved log:     {OUT_LOG}")
    print("Saved RTH scan parquet: feature_scan_rth.parquet")


if __name__ == "__main__":
    main()

"""P1 vs P4 per-trade comparison + entry-feature correlation.

Question: can entry-time features (observable at decision time) predict
whether P1 (partial+BE) or P4 (full PT 2.0) is the better exit policy?

Method:
  delta_atr = p1_partial_be - p4_full_pt20   (per trade, in ATR units)
  positive delta → P1 better; negative → P4 better.

Outputs:
  1. Per-year delta summary (% trades where P1 > P4).
  2. Spearman correlation between each feature and delta.
  3. Quintile analysis: bin trades by top features, mean delta per bin.
  4. Logistic / threshold chooser rule: predict P(P1 > P4) from features.
  5. Per-year PnL of CHOOSER vs always-P4 vs always-P1.

Universe: hmm_4 state 3 + bar1_confirm OOS cohort (2023-2026, ~1180 trades).
PnL conversion: $ = atr_units * entry_atr * NQ_MULT - $5 RT commission.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMM = 5.0
IN = Path("studies/regime_classification/results/exit_policies_nq.parquet")
OUT = Path("studies/regime_classification/results")
OOS_YEARS = (2023, 2024, 2025, 2026)

FEATURE_COLS = [
    "feat_ret_5s", "feat_ret_30s", "feat_ret_60s", "feat_ret_300s",
    "feat_cum_abs_60s", "feat_rv_30s", "feat_rv_300s",
    "feat_range_atr_60s", "feat_range_atr_300s", "feat_range_atr_1800s",
    "feat_vol_expansion", "feat_efficiency_300s", "feat_chop_ratio_300s",
    "feat_n_dir_changes_60s",
    "feat_body_ratio", "feat_upper_wick", "feat_lower_wick", "feat_close_location",
    "feat_vwap_z_signed", "feat_vwap_z_abs", "feat_vwap_slope_5m_atr",
    "feat_session_pos", "feat_range_pct_60s_vs_1h", "feat_compress_drift",
    "dist_pdh_atr", "dist_pdl_atr", "dist_onh_atr", "dist_onl_atr",
    "et_hour", "in_rth", "in_first_hour",
    "state_dur_before",
]


def pnl_dollar(atr_units, entry_atr, mult=NQ_MULT, comm=COMM):
    return atr_units * entry_atr * mult - comm


def report_per_year(df):
    print(f"\n{'='*78}\n  PER-YEAR DELTA  (P1 - P4 in ATR units; positive = P1 better)\n{'='*78}")
    print(f"  {'year':<6}{'n':>6}{'P4_$/tr':>10}{'P1_$/tr':>10}{'delta_$':>10}"
          f"{'%P1>P4':>10}{'medΔatr':>10}")
    for y in OOS_YEARS:
        sub = df[df["year"] == y].copy()
        if len(sub) == 0:
            continue
        sub["p4_$"] = pnl_dollar(sub["p4_full_pt20"], sub["entry_atr"])
        sub["p1_$"] = pnl_dollar(sub["p1_partial_be"], sub["entry_atr"])
        sub["delta_$"] = sub["p1_$"] - sub["p4_$"]
        sub["delta_atr"] = sub["p1_partial_be"] - sub["p4_full_pt20"]
        wp1 = (sub["delta_atr"] > 0).mean()
        print(f"  {y:<6}{len(sub):>6}{sub['p4_$'].mean():>+10.2f}{sub['p1_$'].mean():>+10.2f}"
              f"{sub['delta_$'].mean():>+10.2f}{wp1:>9.1%}{sub['delta_atr'].median():>+10.3f}")
    # Pooled
    pool = df[df["year"].isin(OOS_YEARS)].copy()
    pool["p4_$"] = pnl_dollar(pool["p4_full_pt20"], pool["entry_atr"])
    pool["p1_$"] = pnl_dollar(pool["p1_partial_be"], pool["entry_atr"])
    pool["delta_$"] = pool["p1_$"] - pool["p4_$"]
    pool["delta_atr"] = pool["p1_partial_be"] - pool["p4_full_pt20"]
    wp1 = (pool["delta_atr"] > 0).mean()
    print(f"  {'OOS':<6}{len(pool):>6}{pool['p4_$'].mean():>+10.2f}{pool['p1_$'].mean():>+10.2f}"
          f"{pool['delta_$'].mean():>+10.2f}{wp1:>9.1%}{pool['delta_atr'].median():>+10.3f}")


def correl_per_feature(df):
    print(f"\n{'='*78}\n  SPEARMAN CORR(feature, delta_atr) — OOS pooled\n{'='*78}")
    pool = df[df["year"].isin(OOS_YEARS)].copy()
    pool["delta_atr"] = pool["p1_partial_be"] - pool["p4_full_pt20"]
    out = []
    for c in FEATURE_COLS:
        if c not in pool.columns:
            continue
        x = pool[c].astype(float)
        # Drop missing
        mask = x.notna() & pool["delta_atr"].notna()
        if mask.sum() < 50:
            continue
        rho = x[mask].rank().corr(pool["delta_atr"][mask].rank())
        out.append((c, rho, mask.sum()))
    out.sort(key=lambda r: abs(r[1]), reverse=True)
    print(f"  {'feature':<32}{'rho':>10}{'n':>8}")
    for name, rho, n in out[:20]:
        marker = "  ←" if abs(rho) > 0.05 else ""
        print(f"  {name:<32}{rho:>+10.3f}{n:>8}{marker}")
    return out


def quintile_analysis(df, feature):
    pool = df[df["year"].isin(OOS_YEARS)].copy()
    pool["delta_atr"] = pool["p1_partial_be"] - pool["p4_full_pt20"]
    pool["p4_$"] = pnl_dollar(pool["p4_full_pt20"], pool["entry_atr"])
    pool["p1_$"] = pnl_dollar(pool["p1_partial_be"], pool["entry_atr"])
    pool["delta_$"] = pool["p1_$"] - pool["p4_$"]
    if feature not in pool.columns:
        return
    pool["q"] = pd.qcut(pool[feature].astype(float), 5, labels=False, duplicates="drop")
    print(f"\n  Quintiles of {feature}")
    print(f"  {'q':>3}{'n':>6}{'mean':>10}{'P4_$/tr':>10}{'P1_$/tr':>10}{'Δ_$/tr':>10}")
    for q in sorted(pool["q"].dropna().unique()):
        sub = pool[pool["q"] == q]
        mx = sub[feature].mean()
        print(f"  {int(q):>3}{len(sub):>6}{mx:>+10.3f}"
              f"{sub['p4_$'].mean():>+10.2f}{sub['p1_$'].mean():>+10.2f}"
              f"{sub['delta_$'].mean():>+10.2f}")


def threshold_chooser(df, feature, gt_uses_p4=True, n_thresholds=20):
    """Find threshold on `feature`: above → use P4, below → use P1 (or reversed)."""
    pool = df[df["year"].isin(OOS_YEARS)].copy()
    pool["p4_$"] = pnl_dollar(pool["p4_full_pt20"], pool["entry_atr"])
    pool["p1_$"] = pnl_dollar(pool["p1_partial_be"], pool["entry_atr"])
    x = pool[feature].astype(float)
    qs = np.linspace(0.05, 0.95, n_thresholds)
    print(f"\n  Threshold scan on {feature}  (gt_uses_p4={gt_uses_p4})")
    print(f"  {'pct':>5}{'thr':>10}{'n_p4':>7}{'n_p1':>7}{'$/tr':>10}{'2023':>9}{'2024':>9}{'2025':>9}{'2026':>9}")
    best = (-1e9, None, None)
    for q in qs:
        thr = x.quantile(q)
        if gt_uses_p4:
            pool["chosen_$"] = np.where(x > thr, pool["p4_$"], pool["p1_$"])
        else:
            pool["chosen_$"] = np.where(x > thr, pool["p1_$"], pool["p4_$"])
        n_p4 = (x > thr).sum() if gt_uses_p4 else (x <= thr).sum()
        n_p1 = len(pool) - n_p4
        mean = pool["chosen_$"].mean()
        per_yr = []
        for y in OOS_YEARS:
            ys = pool[pool["year"] == y]
            if len(ys) == 0:
                per_yr.append(np.nan)
            else:
                per_yr.append(ys["chosen_$"].mean())
        if mean > best[0]:
            best = (mean, thr, q)
        print(f"  {q:>5.2f}{thr:>+10.3f}{n_p4:>7}{n_p1:>7}{mean:>+10.2f}"
              f"{per_yr[0]:>+9.1f}{per_yr[1]:>+9.1f}{per_yr[2]:>+9.1f}{per_yr[3]:>+9.1f}")
    print(f"  best: pooled +${best[0]:.2f}/tr at thr={best[1]:+.3f} (pct {best[2]:.2f})")


def logistic_chooser(df, feature_cols):
    """Predict sign(delta_atr) from features; report per-year PnL of chooser."""
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import StratifiedKFold
    except ImportError:
        print("sklearn not available; skipping logistic chooser")
        return

    pool = df[df["year"].isin(OOS_YEARS)].copy()
    pool["delta_atr"] = pool["p1_partial_be"] - pool["p4_full_pt20"]
    pool["p4_$"] = pnl_dollar(pool["p4_full_pt20"], pool["entry_atr"])
    pool["p1_$"] = pnl_dollar(pool["p1_partial_be"], pool["entry_atr"])
    pool["y_p1_better"] = (pool["delta_atr"] > 0).astype(int)

    cols = [c for c in feature_cols if c in pool.columns]
    X = pool[cols].astype(float).fillna(0.0)
    y = pool["y_p1_better"].values

    # 5-fold CV; train on 4, predict on 1. Use predictions to pick policy.
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    pred = np.zeros(len(pool))
    for tr_idx, te_idx in skf.split(X, y):
        sc = StandardScaler()
        Xtr = sc.fit_transform(X.iloc[tr_idx])
        Xte = sc.transform(X.iloc[te_idx])
        clf = LogisticRegression(max_iter=2000, C=0.5)
        clf.fit(Xtr, y[tr_idx])
        pred[te_idx] = clf.predict_proba(Xte)[:, 1]

    pool["p1_prob"] = pred

    print(f"\n{'='*78}\n  LOGISTIC CHOOSER  (CV; predict P1 better; threshold sweep)\n{'='*78}")
    print(f"  {'thr':>5}{'%P1':>6}{'pool$':>10}{'2023':>9}{'2024':>9}{'2025':>9}{'2026':>9}{'AUC':>8}")
    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(y, pred)
    for thr in np.arange(0.30, 0.71, 0.05):
        pool["chosen_$"] = np.where(pool["p1_prob"] >= thr, pool["p1_$"], pool["p4_$"])
        pct_p1 = (pool["p1_prob"] >= thr).mean()
        mean = pool["chosen_$"].mean()
        per_yr = []
        for yr in OOS_YEARS:
            ys = pool[pool["year"] == yr]
            per_yr.append(ys["chosen_$"].mean() if len(ys) else np.nan)
        print(f"  {thr:>5.2f}{pct_p1:>6.1%}{mean:>+10.2f}"
              f"{per_yr[0]:>+9.1f}{per_yr[1]:>+9.1f}{per_yr[2]:>+9.1f}{per_yr[3]:>+9.1f}{auc:>+8.3f}")

    # Always-P4, always-P1 reference
    print(f"\n  Reference policies:")
    for label, col in [("always-P4", "p4_$"), ("always-P1", "p1_$")]:
        per_yr = []
        for yr in OOS_YEARS:
            ys = pool[pool["year"] == yr]
            per_yr.append(ys[col].mean() if len(ys) else np.nan)
        mean = pool[col].mean()
        print(f"  {label:<12}{'':>11}{mean:>+10.2f}"
              f"{per_yr[0]:>+9.1f}{per_yr[1]:>+9.1f}{per_yr[2]:>+9.1f}{per_yr[3]:>+9.1f}")


def main():
    df = pd.read_parquet(IN)
    df = df[df["year"].isin(OOS_YEARS)].copy()
    print(f"Loaded {len(df):,} OOS trades from {IN.name}")
    print(f"By year: {df['year'].value_counts().sort_index().to_dict()}")

    # 1. Per-year delta
    report_per_year(df)

    # 2. Correlation
    corrs = correl_per_feature(df)
    top_5 = [c[0] for c in corrs[:5] if abs(c[1]) > 0.03]
    print(f"\n  → strongest |corr| features for quintile/threshold analysis: {top_5}")

    # 3. Quintile analysis on top features
    print(f"\n{'='*78}\n  QUINTILE ANALYSIS  (delta_$ per quintile of feature)\n{'='*78}")
    for c in top_5:
        quintile_analysis(df, c)

    # 4. Threshold chooser on top feature
    if top_5:
        c0 = top_5[0]
        rho = next((r for n, r, _ in corrs if n == c0), 0)
        print(f"\n{'='*78}\n  THRESHOLD CHOOSER on {c0} (rho={rho:+.3f})\n{'='*78}")
        # If rho > 0 (feature high → P1 better), then ABOVE threshold uses P1
        threshold_chooser(df, c0, gt_uses_p4=(rho < 0))

    # 5. Logistic CV chooser
    logistic_chooser(df, FEATURE_COLS)


if __name__ == "__main__":
    main()

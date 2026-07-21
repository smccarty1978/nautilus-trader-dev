"""POC — tradeability analysis by score bucket on TEST 2025.

For each variant's model trained on the POC dataset, predict TEST 2025
and bin trades by predicted score. For each bucket, report:
  - N, target (clean_path) rate
  - Median forward_mfe_at_300s, forward_mae_at_300s, ratio
  - PT=1.0/SL=1.0 bracket race outcomes (pt/sl/neither)
  - Simulated bracket $ PnL (per-trade ATR)
  - Regime-exit PnL

Compare top decile / quintile / half vs baseline, and vs bottom decile
(inverse-filter).

Also run the specific filter variants the user cares about:
  - Drop top 30%
  - Keep bottom 50%
  - Keep bottom 25%
  - Keep top 10%
  - Keep top 25%
  - Keep top 50%
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
import lightgbm as lgb

POC_DS_PATH = ("studies/ml_5m_flip_prediction_poc/results/"
                "clean_path_300_dataset.parquet")
TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
                "trades_all.parquet")
OUT_DIR = Path("studies/ml_5m_flip_prediction_poc/results")
OUT_LOG = OUT_DIR / "clean_path_300_score_buckets.log"
TARGET = "target_clean_path_300s"

METADATA_COLS = {
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
    "event_id", "decision_ts", "decision_fill_ts",
    "_fwd_mfe_300", "_fwd_mae_300",
}
NQ_MULT = 20.0
COMMISSION = 5.0

LGB_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "verbose": -1,
}


def fmt_pf(pf):
    if pd.isna(pf):
        return "  n/a"
    if pf == float("inf"):
        return "  inf"
    return f"{pf:>5.2f}"


def stats_pnl(pnl, target):
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    tot = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    tr = (target == 1).mean() * 100
    return {"n": n, "wr%": wr, "avg$": avg, "total$": tot, "pf": pf,
            "target_rate%": tr}


def sim_bracket(atr, bracket, regime_pnl, pt_r=1.0, sl_r=1.0):
    """Return per-trade $ PnL."""
    n = len(atr)
    pnl = np.full(n, np.nan)
    pt_first = bracket == 1
    sl_first = bracket == 0
    neither = pd.isna(bracket)
    pnl[pt_first] = (pt_r * atr[pt_first] * NQ_MULT) - COMMISSION
    pnl[sl_first] = (-sl_r * atr[sl_first] * NQ_MULT) - COMMISSION
    pnl[neither] = regime_pnl[neither]
    return pnl


def main():
    print("Loading POC dataset + forward fields...")
    df = pd.read_parquet(POC_DS_PATH)
    df = df[df[TARGET].notna()].copy()
    print(f"  {len(df):,} valid rows")

    # Also pull per-T forward fields from trades_all for bracket sim
    trades = pd.read_parquet(TRADES_PATH).drop_duplicates(
        subset=["signal_ts"], keep="first").set_index("signal_ts")

    feat_cols = [c for c in df.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]
    print(f"  Features: {len(feat_cols)}")

    lines = []
    lines.append("=" * 100)
    lines.append("POC — TRADEABILITY BY SCORE BUCKET (TEST 2025)")
    lines.append("=" * 100)

    # --- Train pooled model ---
    train_mask = df["year"].isin([2020, 2021, 2022, 2023])
    val_mask = df["year"] == 2024
    test_mask = df["year"] == 2025

    X_tr = df.loc[train_mask, feat_cols].values
    y_tr = df.loc[train_mask, TARGET].astype(int).values
    X_vl = df.loc[val_mask, feat_cols].values
    y_vl = df.loc[val_mask, TARGET].astype(int).values

    print("\nTraining pooled LGBM (T0+60+120)...")
    tr_ds = lgb.Dataset(X_tr, label=y_tr, feature_name=feat_cols)
    vl_ds = lgb.Dataset(X_vl, label=y_vl, reference=tr_ds,
                         feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS, tr_ds, num_boost_round=2000,
        valid_sets=[tr_ds, vl_ds], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    print(f"  best_iter={model.best_iteration}")

    test = df[test_mask].copy()
    test["pred"] = model.predict(test[feat_cols].values)
    print(f"  TEST rows: {len(test):,}")

    # Pull per-row forward fields from trades_all for the respective T_d
    for T in sorted(test["decision_checkpoint_s"].unique()):
        tag = f"{int(T):03d}"
        sel = test["decision_checkpoint_s"] == T
        eids = test.loc[sel, "event_id"].values
        test.loc[sel, "atr_at_signal"] = trades[
            "atr_at_signal"].reindex(eids).values
        test.loc[sel, "bracket100"] = trades[
            f"forward_pt100_before_sl100_T_{tag}"].reindex(eids).values
        test.loc[sel, "bracket150"] = trades[
            f"forward_pt150_before_sl100_T_{tag}"].reindex(eids).values
        test.loc[sel, "regime_pnl"] = trades[
            f"forward_regime_pnl_dollars_T_{tag}"].reindex(eids).values
        test.loc[sel, "mfe_300"] = trades[
            f"forward_mfe_at_300s_T_{tag}"].reindex(eids).values
        test.loc[sel, "mae_300"] = trades[
            f"forward_mae_at_300s_T_{tag}"].reindex(eids).values
        test.loc[sel, "peak_mfe"] = trades[
            f"forward_peak_mfe_atr_T_{tag}"].reindex(eids).values
        test.loc[sel, "peak_mae"] = trades[
            f"forward_peak_mae_atr_T_{tag}"].reindex(eids).values

    # Compute simulated bracket PnL
    test["pnl_pt100"] = sim_bracket(
        test["atr_at_signal"].values,
        test["bracket100"].values,
        test["regime_pnl"].values, 1.0, 1.0)
    test["pnl_pt150"] = sim_bracket(
        test["atr_at_signal"].values,
        test["bracket150"].values,
        test["regime_pnl"].values, 1.5, 1.0)

    # Drop rows missing PnL (shouldn't happen if regime_pnl is available)
    # Keep NaN pnl as 0 for fair comparison (those are trades where regime
    # never resolves — extremely rare)
    test["pnl_pt100"] = test["pnl_pt100"].fillna(0)
    test["pnl_pt150"] = test["pnl_pt150"].fillna(0)

    # Sort by score descending
    test_sorted = test.sort_values("pred", ascending=False).reset_index(
        drop=True)
    n = len(test_sorted)

    # --- Headline on ALL (no filter) ---
    lines.append("\n--- BASELINE (NO ML FILTER) on TEST 2025 ---")
    for lbl, col in [("Clean-path rate", TARGET),
                      ("PT=1.0/SL=1.0 $/trade", "pnl_pt100"),
                      ("PT=1.5/SL=1.0 $/trade", "pnl_pt150")]:
        if col == TARGET:
            rate = (test_sorted[col] == 1).mean() * 100
            lines.append(f"  {lbl:<30}: {rate:.1f}%")
        else:
            s = stats_pnl(test_sorted[col].values, test_sorted[TARGET])
            lines.append(
                f"  {lbl:<30}: Avg=${s['avg$']:+.1f}  "
                f"WR={s['wr%']:.1f}%  PF={fmt_pf(s['pf'])}  "
                f"Total=${s['total$']:+,.0f}")

    # --- Deciles ---
    lines.append("\n--- BY DECILE (D1=highest pred) ---")
    lines.append(
        f"  {'Decile':>7} {'N':>5} {'pred':>6} {'clean%':>7} "
        f"{'MFE':>5} {'MAE':>5} {'ratio':>5}  "
        f"{'pt100$':>8} {'pt100PF':>8}  {'pt150$':>8} {'pt150PF':>8}")
    lines.append("  " + "-" * 95)
    deciles = np.array_split(test_sorted, 10)
    for i, d in enumerate(deciles, 1):
        if len(d) == 0:
            continue
        tr = (d[TARGET] == 1).mean() * 100
        mfe = d["mfe_300"].median() if d["mfe_300"].notna().any() else np.nan
        mae = d["mae_300"].median() if d["mae_300"].notna().any() else np.nan
        ratio = (mfe / mae) if (not pd.isna(mae) and mae > 0) else np.nan
        s100 = stats_pnl(d["pnl_pt100"].values, d[TARGET])
        s150 = stats_pnl(d["pnl_pt150"].values, d[TARGET])
        lines.append(
            f"  D{i:>2}     {len(d):>5,} "
            f"{d['pred'].mean():>5.3f} {tr:>6.1f}% "
            f"{mfe:>4.2f} {mae:>4.2f} {ratio:>5.2f}  "
            f"${s100['avg$']:>+7.1f} {fmt_pf(s100['pf']):>7}  "
            f"${s150['avg$']:>+7.1f} {fmt_pf(s150['pf']):>7}"
        )

    # --- Filter variants ---
    lines.append("\n--- FILTER VARIANTS (subset to keep) ---")
    variants = [
        ("ALL (no filter)", slice(None)),
        ("Keep top 10%", slice(None, n // 10)),
        ("Keep top 25%", slice(None, n // 4)),
        ("Keep top 50%", slice(None, n // 2)),
        ("Drop top 10%", slice(n // 10, None)),
        ("Drop top 25%", slice(n // 4, None)),
        ("Drop top 30%", slice(3 * n // 10, None)),
        ("Keep bottom 50%", slice(n // 2, None)),
        ("Keep bottom 25%", slice(3 * n // 4, None)),
        ("Keep bottom 10%", slice(-n // 10, None)),
    ]
    lines.append(
        f"  {'Filter':<22} {'N':>5} {'clean%':>7} "
        f"{'pt100$':>8} {'pt100PF':>8}  {'pt150$':>8} {'pt150PF':>8}")
    lines.append("  " + "-" * 80)
    for lbl, sl in variants:
        sub = test_sorted.iloc[sl]
        if len(sub) == 0:
            continue
        tr = (sub[TARGET] == 1).mean() * 100
        s100 = stats_pnl(sub["pnl_pt100"].values, sub[TARGET])
        s150 = stats_pnl(sub["pnl_pt150"].values, sub[TARGET])
        lines.append(
            f"  {lbl:<22} {len(sub):>5,} "
            f"{tr:>6.1f}% "
            f"${s100['avg$']:>+7.1f} {fmt_pf(s100['pf']):>7}  "
            f"${s150['avg$']:>+7.1f} {fmt_pf(s150['pf']):>7}")

    # --- Per-decile breakdown with bracket mix ---
    lines.append("\n--- PER-DECILE BRACKET MIX (PT=1.0/SL=1.0) ---")
    lines.append(
        f"  {'Decile':>7} {'N':>5} "
        f"{'pt%':>5} {'sl%':>5} {'none%':>6}  "
        f"{'regime_avg$':>12}")
    lines.append("  " + "-" * 55)
    for i, d in enumerate(deciles, 1):
        if len(d) == 0:
            continue
        n_pt = (d["bracket100"] == 1).sum()
        n_sl = (d["bracket100"] == 0).sum()
        n_nth = d["bracket100"].isna().sum()
        reg_avg = d["regime_pnl"].mean()
        lines.append(
            f"  D{i:>2}     {len(d):>5,} "
            f"{n_pt/len(d)*100:>4.1f}% {n_sl/len(d)*100:>4.1f}% "
            f"{n_nth/len(d)*100:>5.1f}% "
            f"${reg_avg:>+10.1f}")

    # Split by checkpoint within top-decile / bottom-decile
    lines.append("\n--- TOP DECILE by T_d (PT=1.0/SL=1.0) ---")
    top10 = test_sorted.iloc[:n // 10]
    bot10 = test_sorted.iloc[-n // 10:]
    for lbl, grp in [("TOP decile", top10), ("BOTTOM decile", bot10)]:
        lines.append(f"\n  {lbl}:")
        for T in sorted(grp["decision_checkpoint_s"].unique()):
            sub_t = grp[grp["decision_checkpoint_s"] == T]
            if len(sub_t) == 0:
                continue
            s = stats_pnl(sub_t["pnl_pt100"].values, sub_t[TARGET])
            tr = (sub_t[TARGET] == 1).mean() * 100
            lines.append(
                f"    T_d={int(T)}: N={len(sub_t):>4,} "
                f"clean%={tr:>5.1f}% Avg=${s['avg$']:>+7.1f} "
                f"PF={fmt_pf(s['pf'])}")

    # --- VERDICT ---
    lines.append("\n--- VERDICT ---")
    baseline_100 = stats_pnl(
        test_sorted["pnl_pt100"].values, test_sorted[TARGET])
    # Find best filter
    best = ("baseline", baseline_100)
    for lbl, sl in variants:
        sub = test_sorted.iloc[sl]
        if len(sub) == 0:
            continue
        s = stats_pnl(sub["pnl_pt100"].values, sub[TARGET])
        if s["avg$"] > best[1]["avg$"]:
            best = (lbl, s)
    lines.append(
        f"  Baseline (no filter) PT=1.0/SL=1.0: "
        f"Avg=${baseline_100['avg$']:+.1f}, PF={fmt_pf(baseline_100['pf'])}, "
        f"Total=${baseline_100['total$']:+,.0f}")
    lines.append(
        f"  Best filter: '{best[0]}'  "
        f"Avg=${best[1]['avg$']:+.1f}, PF={fmt_pf(best[1]['pf'])}, "
        f"Total=${best[1]['total$']:+,.0f}  "
        f"(lift ${best[1]['avg$'] - baseline_100['avg$']:+.1f}/trade)")
    # Slippage check (1 tick = $5, round trip = $10)
    lift = best[1]["avg$"] - baseline_100["avg$"]
    net_best = best[1]["avg$"] - 10  # after $10 slippage
    lines.append(
        f"  After ~$10 slippage: baseline_net=${baseline_100['avg$']-10:+.1f}, "
        f"best_net=${net_best:+.1f}")
    if net_best > 5:
        lines.append("  → Positive net after slippage — potentially tradeable")
    elif net_best > 0:
        lines.append("  → Marginal positive — very thin edge")
    else:
        lines.append("  → NET NEGATIVE after slippage")

    out = "\n".join(lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()

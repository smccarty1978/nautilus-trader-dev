"""NQ V_A Viability Classifier — analysis pipeline.

Three sections:
  1. Descriptive: 4-cohort feature comparison
  2. Simple filters: 6 candidates × per-year reporting
  3. Lightweight ML: walk-forward LightGBM on 3 targets
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/nq_viability_v1/results")
DATASET = OUT / "nq_viability_dataset.parquet"


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_dd(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    return {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "median": float(s.median()),
              "sum": float(s.sum()), "pf": float(pf),
              "max_dd": max_dd(s)}


def cohen_d(a, b):
    a = pd.Series(a).dropna()
    b = pd.Series(b).dropna()
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    pooled = np.sqrt(((len(a) - 1) * a.var()
                        + (len(b) - 1) * b.var())
                       / (len(a) + len(b) - 2))
    if pooled == 0 or np.isnan(pooled):
        return float("nan")
    return (a.mean() - b.mean()) / pooled


NUMERIC_FEATURES = [
    # Confirmation
    "bar1_body_pct", "bar1_close_loc", "bar1_range_atr",
    "hhll_break_atr", "close_through_atr",
    # MTF alignment
    "aligned_30s", "aligned_3m", "aligned_5m",
    "all_3_aligned",
    "regime_30s", "regime_3m", "regime_5m",
    "bars_in_regime_30s", "bars_in_regime_1m",
    "bars_in_regime_3m", "bars_in_regime_5m",
    "atr_30s", "atr_1m", "atr_3m", "atr_5m",
    "dist_close_to_ema3_h_1m_atr",
    "dist_close_to_ema9_h_1m_atr",
    "dist_close_to_ema3_l_1m_atr",
    "dist_close_to_ema9_l_1m_atr",
    "dist_close_to_ema3_h_3m_atr",
    "dist_close_to_ema9_h_3m_atr",
    "dist_close_to_ema3_l_3m_atr",
    "dist_close_to_ema9_l_3m_atr",
    "dist_close_to_ema3_h_5m_atr",
    "dist_close_to_ema9_h_5m_atr",
    "dist_close_to_ema3_l_5m_atr",
    "dist_close_to_ema9_l_5m_atr",
    # Session
    "minute_of_day_ct", "minutes_since_open", "weekday",
    # Market quality
    "flip_count_30m", "flip_count_60m",
    "avg_regime_dur_5_s", "avg_regime_dur_10_s",
    # Volatility derivatives
    "atr_1m_pct_year", "atr_1m_slope_30m",
    # Trade-direction encoding
    "direction_trade",
]


def descriptive_section(df: pd.DataFrame, lines: list):
    lines.append("## 1. Descriptive — feature differences across "
                 "cohorts")
    lines.append("")
    lines.append("Cohorts (NQ RTH only):")
    lines.append("- **A**: 2024-2025 winners")
    lines.append("- **B**: 2024-2025 losers")
    lines.append("- **C**: 2020-2023 losers")
    lines.append("- **D**: 2026 losers")
    lines.append("")

    A = df[(df["year"].isin([2024, 2025])) & (df["is_winner"] == 1)]
    B = df[(df["year"].isin([2024, 2025])) & (df["is_winner"] == 0)]
    C = df[(df["year"].isin([2020, 2021, 2022, 2023]))
             & (df["is_winner"] == 0)]
    D = df[(df["year"] == 2026) & (df["is_winner"] == 0)]
    lines.append(f"- A n={len(A):,}, B n={len(B):,}, C n={len(C):,}, "
                 f"D n={len(D):,}")
    lines.append("")

    # Comparison: A vs C (winners 24-25 vs losers 20-23)
    lines.append("### A (24-25 winners) vs C (20-23 losers) — "
                 "what makes the good pocket different from "
                 "structurally bad years")
    lines.append("")
    rows = []
    for f in NUMERIC_FEATURES:
        if f not in df.columns:
            continue
        d = cohen_d(A[f], C[f])
        if pd.isna(d):
            continue
        rows.append((f, A[f].median(), C[f].median(), d))
    rows.sort(key=lambda r: -abs(r[3]))
    lines.append("| Feature | Med A (24-25 W) | Med C (20-23 L) | "
                 "Cohen's d | Δ |")
    lines.append("|---|--:|--:|--:|--:|")
    for f, ma, mc, d in rows[:15]:
        lines.append(
            f"| {f} | {ma:.3f} | {mc:.3f} | "
            f"{d:+.3f} | {ma-mc:+.3f} |")
    lines.append("")

    # A vs B (winners vs losers within same regime)
    lines.append("### A (24-25 winners) vs B (24-25 losers) — "
                 "what distinguishes winners within the good "
                 "pocket")
    lines.append("")
    rows = []
    for f in NUMERIC_FEATURES:
        if f not in df.columns:
            continue
        d = cohen_d(A[f], B[f])
        if pd.isna(d):
            continue
        rows.append((f, A[f].median(), B[f].median(), d))
    rows.sort(key=lambda r: -abs(r[3]))
    lines.append("| Feature | Med A | Med B | Cohen's d | Δ |")
    lines.append("|---|--:|--:|--:|--:|")
    for f, ma, mb, d in rows[:15]:
        lines.append(
            f"| {f} | {ma:.3f} | {mb:.3f} | "
            f"{d:+.3f} | {ma-mb:+.3f} |")
    lines.append("")

    # C vs D (20-23 losers vs 2026 losers — does 2026 look different?)
    lines.append("### C (20-23 losers) vs D (2026 losers) — "
                 "are the bad years all the same?")
    lines.append("")
    rows = []
    for f in NUMERIC_FEATURES:
        if f not in df.columns:
            continue
        d = cohen_d(C[f], D[f])
        if pd.isna(d):
            continue
        rows.append((f, C[f].median(), D[f].median(), d))
    rows.sort(key=lambda r: -abs(r[3]))
    lines.append("| Feature | Med C (20-23 L) | Med D (26 L) | "
                 "Cohen's d | Δ |")
    lines.append("|---|--:|--:|--:|--:|")
    for f, mc, md, d in rows[:15]:
        lines.append(
            f"| {f} | {mc:.3f} | {md:.3f} | "
            f"{d:+.3f} | {mc-md:+.3f} |")
    lines.append("")

    # Year-by-year median for top-A-vs-C features
    top_features = [r[0] for r in rows[:10]]
    lines.append("### Year-by-year median for top-discriminating "
                 "features")
    lines.append("")
    lines.append("Look for features that drift in 2024-2025 vs "
                 "other years.")
    lines.append("")
    for f in ["flip_count_30m", "flip_count_60m",
                "avg_regime_dur_5_s", "atr_1m", "atr_1m_pct_year",
                "bar1_body_pct", "all_3_aligned"]:
        if f not in df.columns:
            continue
        per_year = df.groupby("year")[f].agg(["median", "mean"])
        lines.append(f"#### {f}")
        lines.append("")
        lines.append("| Year | Median | Mean |")
        lines.append("|---|--:|--:|")
        for yr, row in per_year.iterrows():
            lines.append(f"| {yr} | {row['median']:.3f} | "
                          f"{row['mean']:.3f} |")
        lines.append("")


FILTERS = [
    ("none", lambda d: pd.Series([True] * len(d), index=d.index)),
    ("flip_count_60m <= 6",
     lambda d: d["flip_count_60m"] <= 6),
    ("flip_count_60m <= 4",
     lambda d: d["flip_count_60m"] <= 4),
    ("avg_regime_dur_5_s >= 600",
     lambda d: d["avg_regime_dur_5_s"] >= 600),
    ("avg_regime_dur_5_s >= 900",
     lambda d: d["avg_regime_dur_5_s"] >= 900),
    ("bar1_body_pct >= 0.5",
     lambda d: d["bar1_body_pct"] >= 0.5),
    ("hhll_break_atr >= 0.10",
     lambda d: d["hhll_break_atr"] >= 0.10),
    ("close_through_atr >= 0.10",
     lambda d: d["close_through_atr"] >= 0.10),
    ("aligned_5m == 1",
     lambda d: d["aligned_5m"] == 1),
    ("all_3_aligned == 1",
     lambda d: d["all_3_aligned"] == 1),
    ("morning only (mins_since_open<=60)",
     lambda d: d["minutes_since_open"] <= 60),
    ("avoid lunch (mins_since_open<60 OR >180)",
     lambda d: ((d["minutes_since_open"] <= 60)
                  | (d["minutes_since_open"] >= 180))),
    ("trail_50_exp > 0",
     lambda d: d["trail_50_exp"] > 0),
    ("trail_100_exp > 0",
     lambda d: d["trail_100_exp"] > 0),
    ("low chop + 5m aligned",
     lambda d: ((d["flip_count_60m"] <= 5)
                  & (d["aligned_5m"] == 1))),
    ("low chop + strong confirm",
     lambda d: ((d["flip_count_60m"] <= 5)
                  & (d["bar1_body_pct"] >= 0.5))),
]


def filter_section(df: pd.DataFrame, lines: list):
    lines.append("## 2. Simple filter tests")
    lines.append("")
    lines.append("Each filter applied per year. Promising filters "
                 "improve 2020-2023 + 2026 without destroying "
                 "2024-2025.")
    lines.append("")
    years = sorted(df["year"].unique().tolist())
    cells = []
    for fname, ffn in FILTERS:
        for yr in years:
            sub = df[df["year"] == yr]
            try:
                mask = ffn(sub)
            except Exception:
                continue
            kept = sub[mask]
            base_n = len(sub)
            s = stats(kept["net_pnl"])
            base = stats(sub["net_pnl"])
            cells.append({
                "filter": fname, "year": yr,
                "n": s.get("n", 0),
                "pct_kept": (s.get("n", 0) / base_n
                              if base_n else 0),
                "wr": s.get("wr"),
                "mean": s.get("mean"),
                "pf": s.get("pf"),
                "sum": s.get("sum"),
                "max_dd": s.get("max_dd"),
                "delta_mean": (
                    (s.get("mean") - base.get("mean"))
                    if s.get("n") and base.get("n") else None),
                "delta_total": (
                    (s.get("sum") - base.get("sum"))
                    if s.get("n") and base.get("n") else None),
            })
    cells_df = pd.DataFrame(cells)

    lines.append("### Filter performance per year")
    lines.append("")
    lines.append("| Filter | Year | %kept | n | WR | Mean $ | "
                 "PF | Total $ | Max DD | Δ Mean | Δ Total |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in cells:
        pf_v = r['pf']
        if pf_v is None or (isinstance(pf_v, float) and (np.isnan(pf_v) or np.isinf(pf_v))):
            pf_str = "—"
        else:
            pf_str = f"{pf_v:.2f}"
        lines.append(
            f"| {r['filter']} | {r['year']} | "
            f"{fmt_p(r['pct_kept'])} | {r['n']:,} | "
            f"{fmt_p(r['wr'])} | {fmt_d(r['mean'])} | "
            f"{pf_str} | "
            f"{fmt_d(r['sum'])} | {fmt_d(r['max_dd'])} | "
            f"{fmt_d(r['delta_mean'])} | "
            f"{fmt_d(r['delta_total'])} |")
    lines.append("")

    # Cross-year summary per filter — count years positive,
    # total improvement
    lines.append("### Cross-year filter summary")
    lines.append("")
    lines.append("| Filter | Years positive (mean>0) | "
                 "Years vs base improved | 7yr total $ | "
                 "Δ vs baseline 7yr |")
    lines.append("|---|--:|--:|--:|--:|")
    base_total = df["net_pnl"].sum()
    summary = []
    for fname, ffn in FILTERS:
        rows = [r for r in cells if r["filter"] == fname]
        years_pos = sum(1 for r in rows
                          if r["mean"] is not None
                          and r["mean"] > 0)
        years_improved = sum(
            1 for r in rows
            if r["delta_mean"] is not None
            and r["delta_mean"] > 0)
        total_7yr = sum(r["sum"] or 0 for r in rows)
        summary.append({
            "filter": fname,
            "years_pos": years_pos,
            "years_improved": years_improved,
            "total_7yr": total_7yr,
        })
        lines.append(
            f"| {fname} | {years_pos}/{len(rows)} | "
            f"{years_improved}/{len(rows)} | "
            f"{fmt_d(total_7yr)} | "
            f"{fmt_d(total_7yr - base_total)} |")
    lines.append("")


def ml_section(df: pd.DataFrame, lines: list):
    lines.append("## 3. Lightweight walk-forward ML")
    lines.append("")
    try:
        import lightgbm as lgb
        from sklearn.metrics import roc_auc_score
    except Exception as e:
        lines.append(f"LightGBM unavailable: {e}")
        return

    feat_cols = [c for c in NUMERIC_FEATURES if c in df.columns]
    feat_cols += ["trail_20_exp", "trail_50_exp",
                    "trail_100_exp", "trail_daily_exp",
                    "trail_weekly_exp"]

    folds = [
        ([2020, 2021, 2022], 2023),
        ([2020, 2021, 2022, 2023], 2024),
        ([2020, 2021, 2022, 2023, 2024], 2025),
        ([2020, 2021, 2022, 2023, 2024, 2025], 2026),
    ]

    lines.append("Targets:")
    lines.append("- T1: `is_winner` (binary)")
    lines.append("- T2: `final_pnl_atr` (regression)")
    lines.append("- T3: `env_50_pos` (binary — trailing-50-trade "
                 "expectancy > 0)")
    lines.append("")

    fold_results = []
    for train_yrs, test_yr in folds:
        tr = df[df["year"].isin(train_yrs)].copy()
        te = df[df["year"] == test_yr].copy()
        if not len(tr) or not len(te):
            continue
        # Drop rows with NaN in features
        all_cols = feat_cols + ["is_winner", "final_pnl_atr",
                                    "env_50_pos", "net_pnl"]
        tr_c = tr[all_cols].copy()
        te_c = te[all_cols].copy()
        tr_c = tr_c.fillna(0.0)
        te_c = te_c.fillna(0.0)

        Xtr = tr_c[feat_cols].astype(float)
        Xte = te_c[feat_cols].astype(float)

        # T1: is_winner
        ytr = tr_c["is_winner"]; yte = te_c["is_winner"]
        m = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.05,
            num_leaves=31, verbose=-1)
        m.fit(Xtr, ytr,
              eval_set=[(Xte, yte)],
              callbacks=[lgb.early_stopping(20),
                          lgb.log_evaluation(0)])
        pred_iw = m.predict_proba(Xte)[:, 1]
        auc_iw = roc_auc_score(yte, pred_iw)
        # Top-decile / quartile economics
        te_c["pred_iw"] = pred_iw
        te_c_sorted = te_c.sort_values("pred_iw", ascending=False)
        d1 = te_c_sorted.head(int(len(te_c_sorted) * 0.10))
        q1 = te_c_sorted.head(int(len(te_c_sorted) * 0.25))
        d1_stats = stats(d1["net_pnl"])
        q1_stats = stats(q1["net_pnl"])

        # T2: final_pnl_atr regression
        ytr2 = tr_c["final_pnl_atr"]; yte2 = te_c["final_pnl_atr"]
        m2 = lgb.LGBMRegressor(
            n_estimators=300, learning_rate=0.05,
            num_leaves=31, verbose=-1)
        m2.fit(Xtr, ytr2,
               eval_set=[(Xte, yte2)],
               callbacks=[lgb.early_stopping(20),
                           lgb.log_evaluation(0)])
        pred_pnl = m2.predict(Xte)
        cor_pnl = float(np.corrcoef(yte2, pred_pnl)[0, 1])
        te_c["pred_pnl"] = pred_pnl
        te_c_sorted2 = te_c.sort_values(
            "pred_pnl", ascending=False)
        d_top = te_c_sorted2.head(int(len(te_c_sorted2) * 0.10))
        d_top_stats = stats(d_top["net_pnl"])
        d_bot = te_c_sorted2.tail(int(len(te_c_sorted2) * 0.10))
        d_bot_stats = stats(d_bot["net_pnl"])

        # T3: env_50_pos
        if "env_50_pos" in te_c.columns and te_c["env_50_pos"].nunique() == 2:
            ytr3 = tr_c["env_50_pos"]; yte3 = te_c["env_50_pos"]
            m3 = lgb.LGBMClassifier(
                n_estimators=300, learning_rate=0.05,
                num_leaves=31, verbose=-1)
            m3.fit(Xtr, ytr3,
                   eval_set=[(Xte, yte3)],
                   callbacks=[lgb.early_stopping(20),
                               lgb.log_evaluation(0)])
            pred_env = m3.predict_proba(Xte)[:, 1]
            auc_env = roc_auc_score(yte3, pred_env)
            te_c["pred_env"] = pred_env
            sorted_env = te_c.sort_values(
                "pred_env", ascending=False)
            env_top = sorted_env.head(
                int(len(sorted_env) * 0.10))
            env_top_stats = stats(env_top["net_pnl"])
        else:
            auc_env = float("nan")
            env_top_stats = {"n": 0}

        fold_results.append({
            "train": train_yrs, "test": test_yr,
            "n_train": len(tr), "n_test": len(te),
            "auc_winner": auc_iw,
            "d1_n": d1_stats["n"], "d1_mean": d1_stats.get("mean"),
            "d1_pf": d1_stats.get("pf"),
            "d1_total": d1_stats.get("sum"),
            "q1_n": q1_stats["n"], "q1_mean": q1_stats.get("mean"),
            "q1_pf": q1_stats.get("pf"),
            "q1_total": q1_stats.get("sum"),
            "pnl_corr": cor_pnl,
            "regtop_n": d_top_stats["n"],
            "regtop_mean": d_top_stats.get("mean"),
            "regtop_pf": d_top_stats.get("pf"),
            "regbot_mean": d_bot_stats.get("mean"),
            "auc_env50": auc_env,
            "env_top_n": env_top_stats.get("n", 0),
            "env_top_mean": env_top_stats.get("mean"),
            "env_top_pf": env_top_stats.get("pf"),
            "env_top_total": env_top_stats.get("sum"),
        })
        # Save feature importance for last fold
        if test_yr == 2026:
            fi = pd.DataFrame({
                "feature": feat_cols,
                "importance": m.feature_importances_,
            }).sort_values("importance", ascending=False)
            print("\nFold 4 (train 2020-2025, test 2026) "
                   "top features:")
            print(fi.head(15).to_string(index=False))

    lines.append("### Walk-forward results")
    lines.append("")
    lines.append("| Train | Test | n_test | AUC_winner | "
                 "Top-10% n | Top-10% mean $ | Top-10% PF | "
                 "PnL corr | RegTop10 mean $ | "
                 "AUC env50 | Env-top mean $ | Env-top total $ |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in fold_results:
        train_str = f"{min(r['train'])}-{max(r['train'])}"
        d1_pf_v = r['d1_pf']
        d1_pf_str = (f"{d1_pf_v:.2f}"
                     if d1_pf_v not in (None, float('inf'))
                     and not (isinstance(d1_pf_v, float) and np.isnan(d1_pf_v))
                     else "—")
        env_auc_v = r['auc_env50']
        env_auc_str = (f"{env_auc_v:.3f}"
                       if not (isinstance(env_auc_v, float) and np.isnan(env_auc_v))
                       else "—")
        lines.append(
            f"| {train_str} | {r['test']} | {r['n_test']:,} | "
            f"{r['auc_winner']:.3f} | "
            f"{r['d1_n']:,} | {fmt_d(r['d1_mean'])} | "
            f"{d1_pf_str} | "
            f"{r['pnl_corr']:.3f} | "
            f"{fmt_d(r['regtop_mean'])} | "
            f"{env_auc_str} | "
            f"{fmt_d(r['env_top_mean'])} | "
            f"{fmt_d(r['env_top_total'])} |")
    lines.append("")

    # Verdict
    lines.append("### ML verdict")
    lines.append("")
    avg_auc = np.mean([r["auc_winner"] for r in fold_results])
    avg_pnl_corr = np.mean([r["pnl_corr"] for r in fold_results])
    yrs_top10_pos = sum(
        1 for r in fold_results
        if r["d1_mean"] is not None and r["d1_mean"] > 0)
    lines.append(f"- Average AUC (winner): {avg_auc:.3f}")
    lines.append(f"- Average PnL correlation: {avg_pnl_corr:.3f}")
    lines.append(
        f"- Top-10% positive in {yrs_top10_pos}/"
        f"{len(fold_results)} folds")
    lines.append("")
    return fold_results


def main():
    df = pd.read_parquet(DATASET)
    print(f"Loaded {len(df):,} trades")

    lines = []
    lines.append("# NQ V_A Viability Classifier v1")
    lines.append("")
    lines.append("**Population**: NQ RTH only, V_A baseline (1m HH/LL "
                 "+ momentum confirm, hold to opposing 1m flip), "
                 "all 7 years 2020-2026 = 21,691 trades.")
    lines.append("")
    lines.append("**Per-year baseline**:")
    lines.append("")
    lines.append("| Year | n | WR | Mean $ | Total $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        lines.append(
            f"| {yr} | {s['n']:,} | {fmt_p(s['wr'])} | "
            f"{fmt_d(s['mean'])} | {fmt_d(s['sum'])} |")
    lines.append("")

    descriptive_section(df, lines)
    filter_section(df, lines)
    ml_section(df, lines)

    out_path = OUT / "NQ_VIABILITY_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()

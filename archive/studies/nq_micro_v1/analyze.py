"""NQ V_A 1s Microstructure analyzer.

Sections:
  1. Descriptive — 4-cohort comparison + global winners-vs-losers,
     ranked by Cohen's d on micro features
  2. Simple filter tests — interpretable thresholds, per-year report
  3. Walk-forward ML — 4 folds, 2 models (LR + LGBM), 4 targets,
     3 feature sets (A=registry-only, B=micro-only, C=combined)
  4. Final verdict
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/nq_micro_v1/results")
DATASET = OUT / "nq_micro_dataset.parquet"


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
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
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    return {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "median": float(s.median()),
              "sum": float(s.sum()), "pf": float(pf),
              "max_dd": max_dd(s),
              "avg_win": avg_win, "avg_loss": avg_loss}


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


def micro_feature_cols(df: pd.DataFrame) -> list[str]:
    """All micro features from the collector — w15s/w30s/w60s_*,
    flip2conf_*, bar1_internal_*, conf2fill_*, plus bar1_extreme*."""
    prefixes = ("w15s_", "w30s_", "w60s_", "flip2conf_",
                  "bar1_internal_", "conf2fill_")
    cols = [c for c in df.columns if c.startswith(prefixes)]
    cols += ["bar1_extreme_pos_pct", "bar1_giveback_from_ext_atr"]
    return [c for c in cols if c in df.columns]


def registry_feature_cols(df: pd.DataFrame) -> list[str]:
    """Registry/context features matching prior viability study."""
    cols = [
        "regime_30s", "regime_3m", "regime_5m",
        "bars_in_regime_30s", "bars_in_regime_1m",
        "bars_in_regime_3m", "bars_in_regime_5m",
        "atr_30s", "atr_1m", "atr_3m", "atr_5m",
        "dist_close_to_ema3_h_1m_atr",
        "dist_close_to_ema9_h_1m_atr",
        "dist_close_to_ema3_l_1m_atr",
        "dist_close_to_ema9_l_1m_atr",
        "dist_close_to_ema3_h_5m_atr",
        "dist_close_to_ema9_h_5m_atr",
        "dist_close_to_ema3_l_5m_atr",
        "dist_close_to_ema9_l_5m_atr",
        "aligned_30s", "aligned_3m", "aligned_5m",
        "all_3_aligned",
        "minute_of_day_ct", "minutes_since_open", "weekday",
        "bar1_body_pct", "bar1_close_loc",
        "bar1_range_atr", "hhll_break_atr", "close_through_atr",
        "direction",
    ]
    return [c for c in cols if c in df.columns]


# ---------------- Section 1: descriptive ----------------
def descriptive_section(df, lines):
    lines.append("## 1. Descriptive — feature differences across cohorts")
    lines.append("")
    A = df[(df["year"].isin([2024, 2025])) & (df["is_winner"] == 1)]
    B = df[(df["year"].isin([2024, 2025])) & (df["is_winner"] == 0)]
    C = df[(df["year"].isin([2020, 2021, 2022, 2023]))
             & (df["is_winner"] == 0)]
    D = df[(df["year"] == 2026) & (df["is_winner"] == 0)]
    Wall = df[df["is_winner"] == 1]
    Lall = df[df["is_winner"] == 0]
    lines.append(f"- A (24-25 winners): n={len(A):,}")
    lines.append(f"- B (24-25 losers):  n={len(B):,}")
    lines.append(f"- C (20-23 losers):  n={len(C):,}")
    lines.append(f"- D (2026 losers):   n={len(D):,}")
    lines.append(f"- All winners:       n={len(Wall):,}")
    lines.append(f"- All losers:        n={len(Lall):,}")
    lines.append("")

    micro = micro_feature_cols(df)

    def rank(group_a, group_b, label_a, label_b, top=20):
        rows = []
        for f in micro:
            d = cohen_d(group_a[f], group_b[f])
            if pd.isna(d):
                continue
            rows.append((f, group_a[f].median(),
                            group_b[f].median(), d))
        rows.sort(key=lambda r: -abs(r[3]))
        lines.append(f"### {label_a} vs {label_b}")
        lines.append("")
        lines.append(f"| Feature | Med {label_a} | Med {label_b} | "
                     "Cohen's d | Δ |")
        lines.append("|---|--:|--:|--:|--:|")
        for f, ma, mb, d in rows[:top]:
            lines.append(
                f"| {f} | {ma:.4f} | {mb:.4f} | "
                f"{d:+.3f} | {ma-mb:+.4f} |")
        lines.append("")
        return rows

    rank(Wall, Lall, "Winners (all)", "Losers (all)")
    rank(A, C, "A (24-25 W)", "C (20-23 L)")
    rank(A, B, "A (24-25 W)", "B (24-25 L)")
    rank(C, D, "C (20-23 L)", "D (2026 L)")


# ---------------- Section 2: simple filters ----------------
def make_filters(df: pd.DataFrame):
    """Build filters from the strongest candidates — only those
    with interpretable economic meaning."""
    return [
        ("none", lambda d: pd.Series([True] * len(d), index=d.index)),
        # Pre-entry trend efficiency
        ("w60s_dir_efficiency >= 0.30",
         lambda d: d["w60s_dir_efficiency"] >= 0.30),
        ("w60s_dir_efficiency >= 0.50",
         lambda d: d["w60s_dir_efficiency"] >= 0.50),
        ("bar1_internal_dir_efficiency >= 0.50",
         lambda d: d["bar1_internal_dir_efficiency"] >= 0.50),
        ("flip2conf_dir_efficiency >= 0.30",
         lambda d: d["flip2conf_dir_efficiency"] >= 0.30),
        # Sign flips / chop
        ("w60s_sign_flip_rate <= 0.30",
         lambda d: d["w60s_sign_flip_rate"] <= 0.30),
        ("w60s_sign_flip_rate <= 0.20",
         lambda d: d["w60s_sign_flip_rate"] <= 0.20),
        ("bar1_internal_sign_flip_rate <= 0.30",
         lambda d: d["bar1_internal_sign_flip_rate"] <= 0.30),
        # Final 10s momentum
        ("w60s_final_10s_momentum_atr > 0",
         lambda d: d["w60s_final_10s_momentum_atr"] > 0),
        ("bar1_internal_final_10s_momentum_atr > 0",
         lambda d: d["bar1_internal_final_10s_momentum_atr"] > 0),
        # Volume imbalance
        ("w60s_dir_vol_imbalance > 0",
         lambda d: d["w60s_dir_vol_imbalance"] > 0),
        ("w60s_dir_vol_imbalance > 0.10",
         lambda d: d["w60s_dir_vol_imbalance"] > 0.10),
        ("bar1_internal_dir_vol_imbalance > 0",
         lambda d: d["bar1_internal_dir_vol_imbalance"] > 0),
        # Counter-move size
        ("w60s_largest_counter_move_atr <= 0.30",
         lambda d: d["w60s_largest_counter_move_atr"] <= 0.30),
        # Confirmation strength
        ("bar1_giveback_from_ext_atr <= 0.30",
         lambda d: d["bar1_giveback_from_ext_atr"] <= 0.30),
        ("bar1_extreme_pos_pct >= 0.7",
         lambda d: d["bar1_extreme_pos_pct"] >= 0.7),
        # Conf-to-fill momentum (post-confirm 30s)
        ("conf2fill_dir_efficiency >= 0.30",
         lambda d: d["conf2fill_dir_efficiency"] >= 0.30),
        ("conf2fill_dir_efficiency >= 0.0",
         lambda d: d["conf2fill_dir_efficiency"] >= 0.0),
        ("conf2fill_net_move_atr >= 0",
         lambda d: d["conf2fill_net_move_atr"] >= 0),
        # Composite
        ("low chop + positive vol imbalance",
         lambda d: ((d["w60s_sign_flip_rate"] <= 0.30)
                      & (d["w60s_dir_vol_imbalance"] > 0))),
        ("efficient + positive final 10s",
         lambda d: ((d["w60s_dir_efficiency"] >= 0.30)
                      & (d["w60s_final_10s_momentum_atr"] > 0))),
    ]


def filter_section(df, lines):
    lines.append("## 2. Simple filter tests")
    lines.append("")
    lines.append("Candidates derived from descriptive analysis. "
                 "Promising = improves 2020-2023 + 2026 without "
                 "destroying 2024-2025.")
    lines.append("")
    years = sorted(df["year"].unique().tolist())
    cells = []
    for fname, ffn in make_filters(df):
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
                "avg_win": s.get("avg_win"),
                "avg_loss": s.get("avg_loss"),
                "delta_mean": (
                    (s.get("mean") - base.get("mean"))
                    if s.get("n") and base.get("n") else None),
                "delta_total": (
                    (s.get("sum") - base.get("sum"))
                    if s.get("n") and base.get("n") else None),
            })

    lines.append("### Per-year filter performance")
    lines.append("")
    lines.append("| Filter | Year | %kept | n | WR | Mean $ | "
                 "PF | Total $ | Max DD | Avg Win | Avg Loss | "
                 "Δ Mean | Δ Total |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in cells:
        pf_v = r['pf']
        pf_str = ("—"
                  if pf_v is None
                  or (isinstance(pf_v, float)
                      and (np.isnan(pf_v) or np.isinf(pf_v)))
                  else f"{pf_v:.2f}")
        lines.append(
            f"| {r['filter']} | {r['year']} | "
            f"{fmt_p(r['pct_kept'])} | {r['n']:,} | "
            f"{fmt_p(r['wr'])} | {fmt_d(r['mean'])} | "
            f"{pf_str} | {fmt_d(r['sum'])} | "
            f"{fmt_d(r['max_dd'])} | "
            f"{fmt_d(r['avg_win'])} | "
            f"{fmt_d(r['avg_loss'])} | "
            f"{fmt_d(r['delta_mean'])} | "
            f"{fmt_d(r['delta_total'])} |")
    lines.append("")

    # Cross-year summary
    lines.append("### Cross-year filter summary")
    lines.append("")
    lines.append("| Filter | Years +mean | Years vs base improved | "
                 "7yr total $ | Δ vs baseline |")
    lines.append("|---|--:|--:|--:|--:|")
    base_total = df["net_pnl"].sum()
    for fname, _ in make_filters(df):
        rows = [r for r in cells if r["filter"] == fname]
        years_pos = sum(1 for r in rows
                          if r["mean"] is not None
                          and r["mean"] > 0)
        years_improved = sum(
            1 for r in rows
            if r["delta_mean"] is not None
            and r["delta_mean"] > 0)
        total_7yr = sum(r["sum"] or 0 for r in rows)
        lines.append(
            f"| {fname} | {years_pos}/{len(rows)} | "
            f"{years_improved}/{len(rows)} | "
            f"{fmt_d(total_7yr)} | "
            f"{fmt_d(total_7yr - base_total)} |")
    lines.append("")
    return cells


# ---------------- Section 3: walk-forward ML ----------------
def ml_section(df, lines, save_predictions=True):
    lines.append("## 3. Walk-forward ML — A/B/C feature sets")
    lines.append("")
    try:
        import lightgbm as lgb
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.preprocessing import StandardScaler
    except Exception as e:
        lines.append(f"sklearn/lightgbm unavailable: {e}")
        return

    feat_A = registry_feature_cols(df)
    feat_B = micro_feature_cols(df)
    feat_C = sorted(set(feat_A + feat_B))
    sets = {"A_registry": feat_A,
            "B_micro": feat_B,
            "C_combined": feat_C}
    lines.append(f"Feature counts — A: {len(feat_A)}, "
                 f"B: {len(feat_B)}, C: {len(feat_C)}")
    lines.append("")

    folds = [
        ([2020, 2021, 2022], 2023),
        ([2020, 2021, 2022, 2023], 2024),
        ([2020, 2021, 2022, 2023, 2024], 2025),
        ([2020, 2021, 2022, 2023, 2024, 2025], 2026),
    ]

    all_results = []
    feat_imp_records = []
    for set_name, feats in sets.items():
        lines.append(f"### Feature set {set_name} ({len(feats)} feats)")
        lines.append("")
        for target in ["final_pnl_positive", "mfe_ge_1_atr",
                          "bad_loser"]:
            lines.append(f"#### Target: {target}")
            lines.append("")
            lines.append("| Train | Test | n_test | LGBM AUC | "
                         "LR AUC | Top-10% n | Top-10% mean $ | "
                         "Top-10% PF | Top-25% mean $ | "
                         "Bottom-10% mean $ | Bottom-10% PF |")
            lines.append(
                "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
            for train_yrs, test_yr in folds:
                tr = df[df["year"].isin(train_yrs)].copy()
                te = df[df["year"] == test_yr].copy()
                cols = feats + [target, "net_pnl"]
                cols = [c for c in cols if c in tr.columns]
                tr_c = tr[cols].fillna(0.0)
                te_c = te[cols].fillna(0.0)
                Xtr = tr_c[feats].astype(float)
                Xte = te_c[feats].astype(float)
                ytr = tr_c[target]; yte = te_c[target]
                if ytr.nunique() < 2 or yte.nunique() < 2:
                    continue
                # LGBM
                m = lgb.LGBMClassifier(
                    n_estimators=300, learning_rate=0.05,
                    num_leaves=31, verbose=-1)
                m.fit(Xtr, ytr,
                      eval_set=[(Xte, yte)],
                      callbacks=[lgb.early_stopping(20),
                                  lgb.log_evaluation(0)])
                pred_g = m.predict_proba(Xte)[:, 1]
                auc_g = roc_auc_score(yte, pred_g)
                # LR with scaling
                sc = StandardScaler()
                Xtr_s = sc.fit_transform(Xtr); Xte_s = sc.transform(Xte)
                lr = LogisticRegression(
                    max_iter=1000, C=0.5, solver="lbfgs")
                lr.fit(Xtr_s, ytr)
                pred_l = lr.predict_proba(Xte_s)[:, 1]
                auc_l = roc_auc_score(yte, pred_l)
                # Use LGBM for economics ranking
                te_c["pred_lgbm"] = pred_g
                te_c_sorted = te_c.sort_values(
                    "pred_lgbm", ascending=False)
                d10 = te_c_sorted.head(int(len(te_c_sorted) * 0.10))
                q25 = te_c_sorted.head(int(len(te_c_sorted) * 0.25))
                bot10 = te_c_sorted.tail(int(len(te_c_sorted) * 0.10))
                s_d10 = stats(d10["net_pnl"])
                s_q25 = stats(q25["net_pnl"])
                s_b10 = stats(bot10["net_pnl"])

                pf_d10 = (f"{s_d10.get('pf'):.2f}"
                          if s_d10.get('pf')
                          and not np.isinf(s_d10.get('pf'))
                          else "—")
                pf_b10 = (f"{s_b10.get('pf'):.2f}"
                          if s_b10.get('pf')
                          and not np.isinf(s_b10.get('pf'))
                          else "—")
                lines.append(
                    f"| {min(train_yrs)}-{max(train_yrs)} | "
                    f"{test_yr} | {len(te):,} | "
                    f"{auc_g:.3f} | {auc_l:.3f} | "
                    f"{s_d10.get('n', 0):,} | "
                    f"{fmt_d(s_d10.get('mean'))} | "
                    f"{pf_d10} | "
                    f"{fmt_d(s_q25.get('mean'))} | "
                    f"{fmt_d(s_b10.get('mean'))} | "
                    f"{pf_b10} |")
                all_results.append({
                    "feature_set": set_name, "target": target,
                    "train": f"{min(train_yrs)}-{max(train_yrs)}",
                    "test": test_yr,
                    "lgbm_auc": auc_g, "lr_auc": auc_l,
                    "top10_mean": s_d10.get("mean"),
                    "top10_n": s_d10.get("n"),
                    "top10_pf": s_d10.get("pf"),
                    "top25_mean": s_q25.get("mean"),
                    "bot10_mean": s_b10.get("mean"),
                    "bot10_pf": s_b10.get("pf"),
                })
                # Feature importance for last fold (2026)
                if test_yr == 2026 and target == "final_pnl_positive":
                    fi = pd.DataFrame({
                        "feature": feats,
                        "importance": m.feature_importances_,
                    }).sort_values("importance", ascending=False)
                    fi["set"] = set_name
                    fi["fold_test"] = 2026
                    feat_imp_records.append(fi)
            lines.append("")

    # Feature importance summary for combined set
    lines.append("### Feature importance — final fold (2026), "
                 "target=final_pnl_positive, feature set C")
    lines.append("")
    if feat_imp_records:
        fi_C = [f for f in feat_imp_records
                  if f["set"].iloc[0] == "C_combined"]
        if fi_C:
            fi_C = fi_C[0]
            lines.append("Top 25 features:")
            lines.append("")
            lines.append("| Feature | Importance |")
            lines.append("|---|--:|")
            for _, r in fi_C.head(25).iterrows():
                lines.append(f"| {r['feature']} | "
                              f"{r['importance']} |")
            lines.append("")
            # How many micro features in top 25?
            top25 = fi_C.head(25)
            micro_cols = set(micro_feature_cols(df))
            n_micro_top = sum(1 for f in top25["feature"]
                                if f in micro_cols)
            lines.append(f"Of top-25 features: **{n_micro_top}** "
                          "are 1s microstructure, the rest are "
                          "registry/context.")
            lines.append("")

    # Save predictions
    if save_predictions and all_results:
        pred_df = pd.DataFrame(all_results)
        pred_df.to_parquet(OUT / "ml_summary.parquet", index=False)

    return all_results


def main():
    df = pd.read_parquet(DATASET)
    print(f"Loaded {len(df):,} trades")

    lines = []
    lines.append("# NQ V_A 1s Microstructure Quality Study v1")
    lines.append("")
    lines.append(
        f"**Population**: NQ RTH only, V_A baseline (1m HH/LL + "
        f"momentum confirm, hold to opposing 1m flip), "
        f"7 years 2020-2026 = {len(df):,} trades.")
    lines.append("")
    lines.append("**Per-year baseline**:")
    lines.append("")
    lines.append("| Year | n | WR | Mean $ | Total $ | "
                 "Clean Win % | Bad Loss % |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        lines.append(
            f"| {yr} | {s['n']:,} | {fmt_p(s['wr'])} | "
            f"{fmt_d(s['mean'])} | {fmt_d(s['sum'])} | "
            f"{fmt_p(sub['clean_winner'].mean())} | "
            f"{fmt_p(sub['bad_loser'].mean())} |")
    lines.append("")

    descriptive_section(df, lines)
    cells = filter_section(df, lines)
    ml_results = ml_section(df, lines)

    # Final verdict
    lines.append("## 4. Final verdict")
    lines.append("")
    # Best filter
    if cells:
        # Build per-filter total
        by_filter = {}
        for r in cells:
            by_filter.setdefault(r["filter"], []).append(r)
        ranked_filters = []
        for fname, rows in by_filter.items():
            if fname == "none":
                continue
            yrs_pos = sum(1 for r in rows
                            if r["mean"] is not None
                            and r["mean"] > 0)
            total = sum(r["sum"] or 0 for r in rows)
            ranked_filters.append((fname, yrs_pos, total))
        ranked_filters.sort(key=lambda r: (-r[1], -r[2]))
        lines.append("**Best 5 filters by years-positive then 7yr total**:")
        lines.append("")
        for fname, yp, tot in ranked_filters[:5]:
            lines.append(f"- `{fname}`: {yp}/7 years positive, "
                          f"{fmt_d(tot)} 7yr total")
        lines.append("")
    # ML summary
    if ml_results:
        ml_df = pd.DataFrame(ml_results)
        lines.append("**ML summary by feature set (target=final_pnl_positive)**:")
        lines.append("")
        ml_pp = ml_df[ml_df["target"] == "final_pnl_positive"]
        for sn in ["A_registry", "B_micro", "C_combined"]:
            sub = ml_pp[ml_pp["feature_set"] == sn]
            avg_auc = sub["lgbm_auc"].mean()
            yrs_pos = (sub["top10_mean"] > 0).sum()
            lines.append(
                f"- {sn}: avg LGBM AUC {avg_auc:.3f}, "
                f"top-10% positive in {yrs_pos}/{len(sub)} folds")
        lines.append("")
    lines.append("**Main question — do 1s microstructure features add "
                 "predictive value beyond existing registry features?**")
    lines.append("")
    if ml_results:
        ml_df = pd.DataFrame(ml_results)
        ml_pp = ml_df[ml_df["target"] == "final_pnl_positive"]
        a_mean = ml_pp[ml_pp["feature_set"] == "A_registry"]["lgbm_auc"].mean()
        b_mean = ml_pp[ml_pp["feature_set"] == "B_micro"]["lgbm_auc"].mean()
        c_mean = ml_pp[ml_pp["feature_set"] == "C_combined"]["lgbm_auc"].mean()
        a_top = ml_pp[ml_pp["feature_set"] == "A_registry"]["top10_mean"].mean()
        b_top = ml_pp[ml_pp["feature_set"] == "B_micro"]["top10_mean"].mean()
        c_top = ml_pp[ml_pp["feature_set"] == "C_combined"]["top10_mean"].mean()
        lines.append(f"- Registry-only AUC: {a_mean:.3f}, "
                      f"avg top-10% mean ${a_top:.2f}")
        lines.append(f"- Micro-only AUC:    {b_mean:.3f}, "
                      f"avg top-10% mean ${b_top:.2f}")
        lines.append(f"- Combined AUC:      {c_mean:.3f}, "
                      f"avg top-10% mean ${c_top:.2f}")
        lines.append("")
        delta_auc = c_mean - a_mean
        delta_top = c_top - a_top
        lines.append(f"- ΔAUC (C - A) = {delta_auc:+.3f}")
        lines.append(f"- Δtop-10% mean (C - A) = ${delta_top:+.2f}")
        lines.append("")

    out_path = OUT / "NQ_V_A_1S_MICROSTRUCTURE_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")

    # Summary JSON
    summary = {
        "n_trades": int(len(df)),
        "n_features_micro": len(micro_feature_cols(df)),
        "n_features_registry": len(registry_feature_cols(df)),
        "ml_results": ml_results,
        "filter_cells": cells,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, default=str, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()

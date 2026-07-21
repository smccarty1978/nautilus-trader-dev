"""Phase 2 markdown report writer."""

from __future__ import annotations
import pandas as pd

from train_phase2 import (
    metrics_block, calibration_table, topk_economics,
    _stratify, STRATA,
)


def _d(v) -> str:
    if pd.isna(v):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def write_phase2_report(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    feat_cols: list[str],
    model,
    out_path,
) -> None:
    """oos_df must already have a `score` column populated by the model."""
    lines: list[str] = []
    lines.append("# Good Entry v2 — Phase 2 LightGBM Report")
    lines.append("")

    # --- Setup section ---
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Features used: {len(feat_cols)} "
                  "(role == model_feature, intersected with collector "
                  "output, numeric-only)")
    lines.append(f"- Train: {len(train_df):,} rows from "
                  f"{train_df['event_id'].nunique():,} events "
                  f"(years 2020-2023)")
    lines.append(f"- Val:   {len(val_df):,} rows from "
                  f"{val_df['event_id'].nunique():,} events "
                  f"(year 2024)")
    lines.append(f"- OOS:   {len(oos_df):,} rows from "
                  f"{oos_df['event_id'].nunique():,} events "
                  f"(year 2025)")
    lines.append(f"- Model: LightGBM binary, early-stopped on val AUC")
    lines.append(f"- Best iteration: {model.best_iteration}")
    lines.append("")

    # --- Headline OOS metrics ---
    lines.append("## OOS metrics (2025)")
    lines.append("")
    m_oos = metrics_block(oos_df)
    lines.append(f"- N rows: {m_oos['n']:,}")
    lines.append(f"- Base rate: {_p(m_oos['base_rate'])}")
    lines.append(f"- **AUC: {m_oos['auc']:.4f}**")
    lines.append(f"- **PR-AUC: {m_oos['pr_auc']:.4f}** "
                  f"(baseline = {m_oos['base_rate']:.4f})")
    lines.append(f"- Brier score: {m_oos['brier']:.4f}")
    lines.append("")

    # --- Per-stratum metrics ---
    lines.append("## OOS AUC / PR-AUC by stratum")
    lines.append("")
    lines.append("| Stratum | n | Base rate | AUC | PR-AUC | Brier |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for s in STRATA:
        sub = _stratify(oos_df, s)
        m = metrics_block(sub)
        lines.append(
            f"| {s} | {m['n']:,} | {_p(m['base_rate'])} | "
            f"{m['auc']:.4f} | {m['pr_auc']:.4f} | "
            f"{m['brier']:.4f} |")
    lines.append("")

    # --- Calibration ---
    lines.append("## Calibration (10 score deciles, OOS)")
    lines.append("")
    cal = calibration_table(oos_df, n_buckets=10)
    lines.append("| Decile | n | Mean predicted | Actual rate | "
                  "Mean PnL $ | PT100 rate (resolved) |")
    lines.append("|--:|--:|--:|--:|--:|--:|")
    for _, r in cal.iterrows():
        lines.append(
            f"| {int(r['bucket'])} | {int(r['n']):,} | "
            f"{r['pred_mean']:.4f} | {_p(r['actual_rate'])} | "
            f"{_d(r['pnl_mean'])} | "
            f"{_p(r['pt100_rate'])} (n={int(r['pt100_n']):,}) |")
    lines.append("")

    # --- Top-k economics ---
    lines.append("## OOS economics by top-k score bucket")
    lines.append("")
    tk = topk_economics(oos_df, [0.10, 0.20, 0.30])
    lines.append("| Top-k | n | good_entry rate | Mean $ | Median $ | "
                  "PT100% (resolved) |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for _, r in tk.iterrows():
        f = r["fraction"]
        lbl = "ALL (baseline)" if f == 1.0 else f"top {int(f*100)}%"
        lines.append(
            f"| {lbl} | {int(r['n']):,} | "
            f"{_p(r['good_entry_rate'])} | "
            f"{_d(r['pnl_mean'])} | {_d(r['pnl_median'])} | "
            f"{_p(r['pt100_rate'])} (n={int(r['pt100_resolved']):,}) |")
    lines.append("")

    # --- Per-stratum top-k economics ---
    lines.append("## OOS top-10% economics by stratum")
    lines.append("")
    lines.append("| Stratum | top-10% n | good_entry rate | Mean $ "
                  "| ALL Mean $ | Lift $ |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for s in STRATA:
        sub = _stratify(oos_df, s)
        if len(sub) == 0:
            continue
        tk = topk_economics(sub, [0.10])
        # Row 0 is ALL baseline, row 1 is top-10%
        if len(tk) < 2:
            continue
        all_pnl = tk.iloc[0]["pnl_mean"]
        top_row = tk.iloc[1]
        lift = top_row["pnl_mean"] - all_pnl
        lines.append(
            f"| {s} | {int(top_row['n']):,} | "
            f"{_p(top_row['good_entry_rate'])} | "
            f"{_d(top_row['pnl_mean'])} | {_d(all_pnl)} | "
            f"{_d(lift)} |")
    lines.append("")

    # --- Feature importance ---
    lines.append("## Top 25 feature importances (gain)")
    lines.append("")
    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": model.feature_importance(importance_type="gain"),
        "split": model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)
    total_gain = imp["gain"].sum()
    imp["pct"] = imp["gain"] / total_gain
    lines.append("| Rank | Feature | % gain | Splits |")
    lines.append("|--:|---|--:|--:|")
    for i, (_, r) in enumerate(imp.head(25).iterrows()):
        lines.append(
            f"| {i+1} | `{r['feature']}` | "
            f"{100 * r['pct']:.1f}% | {int(r['split']):,} |")
    lines.append("")

    # --- Verdict heuristic ---
    lines.append("## Phase 2 verdict")
    lines.append("")
    lift_top10 = (
        topk_economics(oos_df, [0.10]).iloc[1]["pnl_mean"]
        - topk_economics(oos_df, [0.10]).iloc[0]["pnl_mean"])
    auc = m_oos["auc"]
    pr_auc = m_oos["pr_auc"]
    base = m_oos["base_rate"]
    pr_lift = pr_auc - base

    lines.append(f"- OOS AUC: {auc:.4f}")
    lines.append(f"- PR-AUC vs base: {pr_auc:.4f} vs {base:.4f} "
                  f"(lift {pr_lift:+.4f})")
    lines.append(f"- Top-10% economic lift over ALL: {_d(lift_top10)}")

    if auc >= 0.60 and lift_top10 >= 20:
        verdict = ("STRONG — features carry actionable signal. Decide "
                    "whether to (a) tighten the label and re-train or "
                    "(b) move to NT backtest with a top-decile filter.")
    elif auc >= 0.55 and lift_top10 >= 10:
        verdict = ("MODERATE — measurable signal. Worth tightening "
                    "the label (e.g., mfe>1.5 ATR AND ratio>2.0) to "
                    "concentrate the positive class before claiming "
                    "tradeability.")
    else:
        verdict = ("WEAK — features do not predict good_entry_300s "
                    "well enough to act on. Either the label horizon "
                    "is wrong or 1m flips are too noisy at the "
                    "snap-time feature level.")
    lines.append(f"- VERDICT: {verdict}")

    out_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

"""Phase 3 markdown report writer for the RTH-only regression."""

from __future__ import annotations
import numpy as np
import pandas as pd

from train_phase3 import (
    rank_metrics, risk_block, decile_table,
    topk_economics_with_risk, trimmed_mean,
)


def _d(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _f(v, prec=4) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:.{prec}f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def _atr(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.4f}"


def write_phase3_report(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    feat_cols: list[str],
    model,
    out_path,
) -> None:
    lines: list[str] = []
    lines.append("# Good Entry v2 — Phase 3 RTH Regression Report")
    lines.append("")

    # --- Setup ---
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Population: RTH-only checkpoints "
                  "(is_rth_checkpoint == 1)")
    lines.append(f"- Target: `regime_exit_pnl_atr` "
                  "(ATR-normalized hold-to-flip PnL)")
    lines.append(f"- Loss: L2 (MSE)")
    lines.append(f"- Features: {len(feat_cols)} model_feature cols "
                  "(checkpoint_s included for pooling)")
    lines.append(f"- Train: {len(train_df):,} rows from "
                  f"{train_df['event_id'].nunique():,} events "
                  f"(years 2020-2023)")
    lines.append(f"- Val:   {len(val_df):,} rows from "
                  f"{val_df['event_id'].nunique():,} events "
                  f"(year 2024)")
    lines.append(f"- OOS:   {len(oos_df):,} rows from "
                  f"{oos_df['event_id'].nunique():,} events "
                  f"(year 2025)")
    lines.append(f"- Best iteration: {model.best_iteration}")
    lines.append("")

    # --- Headline OOS rank metrics ---
    rm = rank_metrics(oos_df)
    lines.append("## OOS rank quality (2025 RTH)")
    lines.append("")
    lines.append(f"- N: {rm['n']:,}")
    lines.append(f"- **Spearman ρ: {rm['spearman']:.4f}** "
                  f"(p ≈ {rm['spearman_p']:.2e})")
    lines.append(f"- RMSE (ATR units): {rm['rmse']:.4f}")
    lines.append(f"- MAE  (ATR units): {rm['mae']:.4f}")
    lines.append("")

    # --- Decile table (full risk profile per decile) ---
    lines.append("## Decile-by-decile, OOS RTH")
    lines.append("")
    dec = decile_table(oos_df, "regime_exit_pnl_dollars")
    lines.append("| Decile | n | Pred ATR | Actual ATR mean | Actual ATR med "
                  "| $ mean | $ median | $ p25 | $ p75 | "
                  "Trim 5% mean | Win% | Avg win $ | Avg loss $ |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in dec.iterrows():
        lines.append(
            f"| {int(r['decile'])} | {int(r['n']):,} | "
            f"{_atr(r['pred_mean'])} | "
            f"{_atr(r['actual_atr_mean'])} | "
            f"{_atr(r['actual_atr_median'])} | "
            f"{_d(r['usd_mean'])} | {_d(r['usd_median'])} | "
            f"{_d(r['usd_p25'])} | {_d(r['usd_p75'])} | "
            f"{_d(r['trimmed_usd_5pct'])} | "
            f"{_p(r['win_rate'])} | {_d(r['avg_winner_usd'])} | "
            f"{_d(r['avg_loser_usd'])} |")
    lines.append("")
    lines.append("**Reading guide**: a thin-tail mirage shows mean "
                  "diverging from median + trimmed mean; a real signal "
                  "shows mean, median, and trimmed-mean all moving "
                  "together. Win rate trending with the mean is also "
                  "a good signal.")
    lines.append("")

    # --- Top-k economics with risk profile ---
    lines.append("## OOS top-k economics (full risk profile)")
    lines.append("")
    tk = topk_economics_with_risk(oos_df, [0.10, 0.20, 0.30])
    lines.append("| Bucket | n | Mean $ | Median $ | p25 $ | p75 $ "
                  "| Trim 5% mean | Win% | Avg win $ | Avg loss $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in tk.iterrows():
        lines.append(
            f"| {r['label']} | {int(r['n']):,} | "
            f"{_d(r['mean'])} | {_d(r['median'])} | "
            f"{_d(r['p25'])} | {_d(r['p75'])} | "
            f"{_d(r['trimmed_mean_5pct'])} | "
            f"{_p(r['win_rate'])} | {_d(r['avg_winner'])} | "
            f"{_d(r['avg_loser'])} |")
    lines.append("")

    # --- Long vs Short within RTH ---
    lines.append("## OOS top-10% economics: Long vs Short (RTH)")
    lines.append("")
    lines.append("| Side | n | Mean $ | Median $ | Trim 5% | Win% "
                  "| Spearman ρ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for label, mask in [
        ("RTH-Long", oos_df["signal_direction"] == 1),
        ("RTH-Short", oos_df["signal_direction"] == -1),
    ]:
        sub = oos_df[mask]
        if len(sub) == 0:
            continue
        rm_s = rank_metrics(sub)
        # Top-10% of this stratum
        sub_sorted = sub.sort_values("score", ascending=False)
        top = sub_sorted.head(int(round(0.10 * len(sub))))
        rb = risk_block(top["regime_exit_pnl_dollars"])
        lines.append(
            f"| {label} top-10% | {rb['n']:,} | "
            f"{_d(rb['mean'])} | {_d(rb['median'])} | "
            f"{_d(rb['trimmed_mean_5pct'])} | "
            f"{_p(rb['win_rate'])} | "
            f"{rm_s['spearman']:+.4f} |")
        # Baseline for the side
        rb_all = risk_block(sub["regime_exit_pnl_dollars"])
        lines.append(
            f"| {label} ALL | {rb_all['n']:,} | "
            f"{_d(rb_all['mean'])} | {_d(rb_all['median'])} | "
            f"{_d(rb_all['trimmed_mean_5pct'])} | "
            f"{_p(rb_all['win_rate'])} | — |")
    lines.append("")

    # --- T buckets within first 600s ---
    lines.append("## OOS top-10% economics by T bucket (within 600s)")
    lines.append("")
    bins = [(0, 90, "0-90s"), (90, 180, "90-180s"),
             (180, 300, "180-300s"), (300, 450, "300-450s"),
             (450, 601, "450-600s")]
    lines.append("| T bucket | n | top-10% n | top-10% Mean $ "
                  "| top-10% Median $ | top-10% Trim 5% | top-10% Win% |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for lo, hi, label in bins:
        sub = oos_df[(oos_df["checkpoint_s"] >= lo)
                      & (oos_df["checkpoint_s"] < hi)]
        if len(sub) == 0:
            continue
        sub_sorted = sub.sort_values("score", ascending=False)
        top = sub_sorted.head(int(round(0.10 * len(sub))))
        rb = risk_block(top["regime_exit_pnl_dollars"])
        lines.append(
            f"| {label} | {len(sub):,} | {rb['n']:,} | "
            f"{_d(rb['mean'])} | {_d(rb['median'])} | "
            f"{_d(rb['trimmed_mean_5pct'])} | "
            f"{_p(rb['win_rate'])} |")
    lines.append("")

    # --- 2025 OOS by quarter ---
    lines.append("## OOS top-10% economics by 2025 quarter "
                  "(stability check)")
    lines.append("")
    oos_q = oos_df.copy()
    # Decode quarter from checkpoint_s timestamp via fill_time_actual
    oos_q["fill_dt_utc"] = pd.to_datetime(
        oos_q["fill_time_actual"], unit="ns", utc=True)
    oos_q["quarter"] = oos_q["fill_dt_utc"].dt.quarter
    lines.append("| Quarter | n | top-10% n | top-10% Mean $ "
                  "| top-10% Median $ | top-10% Trim 5% | "
                  "top-10% Win% | Spearman ρ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for q in [1, 2, 3, 4]:
        sub = oos_q[oos_q["quarter"] == q]
        if len(sub) == 0:
            continue
        sub_sorted = sub.sort_values("score", ascending=False)
        top = sub_sorted.head(int(round(0.10 * len(sub))))
        rb = risk_block(top["regime_exit_pnl_dollars"])
        rm_q = rank_metrics(sub)
        lines.append(
            f"| 2025-Q{q} | {len(sub):,} | {rb['n']:,} | "
            f"{_d(rb['mean'])} | {_d(rb['median'])} | "
            f"{_d(rb['trimmed_mean_5pct'])} | "
            f"{_p(rb['win_rate'])} | "
            f"{rm_q['spearman']:+.4f} |")
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

    # --- Verdict ---
    lines.append("## Phase 3 verdict")
    lines.append("")
    rho = rm["spearman"]
    top10 = topk_economics_with_risk(oos_df, [0.10]).iloc[1]
    base = topk_economics_with_risk(oos_df, [0.10]).iloc[0]
    lift_mean = top10["mean"] - base["mean"]
    lift_median = top10["median"] - base["median"]
    lift_trim = top10["trimmed_mean_5pct"] - base["trimmed_mean_5pct"]

    lines.append(f"- Spearman ρ on OOS: {rho:+.4f}")
    lines.append(f"- Top-10% lift: mean {_d(lift_mean)}, "
                  f"median {_d(lift_median)}, "
                  f"trimmed-5% {_d(lift_trim)}")

    # Thin-tail mirage detection
    if abs(lift_mean) > 5 and abs(lift_trim) < abs(lift_mean) / 2:
        tail_note = ("THIN-TAIL ARTIFACT — mean lift driven by extreme "
                      "tail; trimmed-mean lift much smaller. Treat with "
                      "skepticism.")
    elif abs(lift_mean) > 5 and abs(lift_trim) >= abs(lift_mean) / 2:
        tail_note = ("Robust — trimmed-mean lift moves with raw mean, "
                      "suggesting genuine payoff ranking rather than "
                      "tail-chasing.")
    else:
        tail_note = "Lift is small enough that tail vs body is moot."
    lines.append(f"- Tail-vs-body read: {tail_note}")
    lines.append("")

    if rho > 0.10 and lift_mean > 20 and lift_trim > 5:
        lines.append("- VERDICT: STRONG. Regression captures durable "
                      "payoff ranking in RTH. Worth NT backtest of "
                      "top-decile filter.")
    elif rho > 0.05 and lift_mean > 10:
        lines.append("- VERDICT: MODERATE. Real but small signal. "
                      "Consider Huber loss / quantile regression / "
                      "RTH-Long-only or RTH-Short-only models before "
                      "committing to backtest.")
    else:
        lines.append("- VERDICT: WEAK. RTH-only regression doesn't "
                      "rescue the binary classifier — magnitude "
                      "ranking is also marginal.")

    out_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

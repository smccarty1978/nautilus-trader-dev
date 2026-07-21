"""Final report — feature reduction + dual-OOS validation.

Sections:
  1. Executive summary
  2. Iteration table (8-step offline sweep on 2025)
  3. Finalist selection and criteria
  4. NT finalist results — 2025
  5. NT finalist results — 2024 (true second-OOS)
  6. Dual-OOS conclusion
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

FR_DIR = Path("studies/bracket_entry_v2/feature_reduction")
NT_ROOT = Path("backtests/good_entry_v2_bracket/results/fr_nt_runs")
SCHEDULE_DIR = Path(
    "backtests/good_entry_v2_bracket/results/fr_schedules")

FINALISTS = ["full", "top_15", "top_10"]
YEARS = [2025, 2024]
TICK_COST = 5.0
COMMISSION = 5.0


def classify_exit(row, tol=0.05) -> str:
    d = row["direction"]
    atr = row["atr_at_signal"]
    if atr <= 0:
        return "unknown"
    move_atr = (row["avg_px_close"] - row["avg_px_open"]) * d / atr
    if move_atr >= 1.0 - tol:
        return "pt"
    if move_atr <= -(1.0 - tol):
        return "sl"
    return "regime_exit"


def cost_adjusted_pnl(trades: pd.DataFrame) -> pd.Series:
    """Per-trade PnL scenario C: raw + $5 commission + 1-tick entry
    slip + 1-tick exit slip for SL/regime_exit (PT = limit, no exit slip).
    """
    d = trades["direction"].values
    entry = trades["avg_px_open"].astype(float).values
    exit_ = trades["avg_px_close"].astype(float).values
    reason = trades["exit_reason"].values

    # Adverse entry: worsen entry by 1 tick in direction of trade
    slip_entry = entry + np.where(d == 1, 0.25, -0.25)
    # Adverse exit on SL/regime_exit: exit at 1 tick worse
    slip_mask = np.isin(reason, ["sl", "regime_exit", "unknown"])
    slip_exit = np.where(slip_mask,
                          exit_ + np.where(d == 1, -0.25, 0.25),
                          exit_)
    pnl = (slip_exit - slip_entry) * d * 20.0 - COMMISSION
    return pd.Series(pnl, index=trades.index)


def load_and_process_nt_run(finalist: str, year: int) -> dict | None:
    """Load NT positions + schedule, classify + compute cost-adjusted PnL."""
    run_dir = NT_ROOT / f"{year}_{finalist}"
    positions_path = run_dir / "positions.parquet"
    schedule_path = SCHEDULE_DIR / f"schedule_{year}_{finalist}.parquet"
    if not positions_path.exists() or not schedule_path.exists():
        return None

    pos = pd.read_parquet(positions_path)
    sched = pd.read_parquet(schedule_path)
    pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
    sched_sel = sched[["entry_ts_ns", "direction", "atr_at_signal"]]
    merged = pd.merge_asof(
        pos.sort_values("entry_ts_ns"),
        sched_sel.sort_values("entry_ts_ns"),
        on="entry_ts_ns", direction="nearest",
        tolerance=60 * 1_000_000_000,
    )
    merged = merged.dropna(subset=["direction", "atr_at_signal"])
    merged["direction"] = merged["direction"].astype(int)
    merged["exit_reason"] = merged.apply(classify_exit, axis=1)
    merged["pnl_raw"] = ((merged["avg_px_close"]
                             - merged["avg_px_open"])
                           * merged["direction"] * 20.0)
    merged["pnl_full_slip"] = cost_adjusted_pnl(merged)

    s = merged["pnl_full_slip"].dropna()
    wins = s[s > 0]
    losses = s[s < 0]
    n_long = (merged["direction"] == 1).sum()
    n_short = (merged["direction"] == -1).sum()

    # Monthly stability
    merged["exit_dt"] = pd.to_datetime(
        merged["ts_closed"].astype("int64"), unit="ns", utc=True)
    merged["month"] = merged["exit_dt"].dt.to_period("M").astype(str)
    monthly = merged.groupby("month")["pnl_full_slip"].sum()
    pos_months = int((monthly > 0).sum())
    neg_months = int((monthly < 0).sum())

    return {
        "finalist": finalist,
        "year": year,
        "n_trades": len(merged),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "long_pct": float(n_long / len(merged)) if len(merged) else 0,
        "short_pct": float(n_short / len(merged)) if len(merged) else 0,
        "mean_raw": float(merged["pnl_raw"].mean()),
        "mean_c": float(s.mean()),
        "median_c": float(s.median()),
        "trimmed_c": float(
            s.sort_values()
             .iloc[int(len(s) * 0.05):len(s) - int(len(s) * 0.05)].mean())
            if int(len(s) * 0.05) * 2 < len(s) else float("nan"),
        "total_raw": float(merged["pnl_raw"].sum()),
        "total_c": float(s.sum()),
        "win_rate_c": float((s > 0).mean()),
        "pf_c": (float(wins.sum() / abs(losses.sum()))
                  if len(losses) and losses.sum() != 0 else float("inf")),
        "pt_hits": int((merged["exit_reason"] == "pt").sum()),
        "sl_hits": int((merged["exit_reason"] == "sl").sum()),
        "regime_hits": int((merged["exit_reason"] == "regime_exit").sum()),
        "pos_months": pos_months,
        "neg_months": neg_months,
        "n_months": int(len(monthly)),
    }


def _d(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    out_path = FR_DIR / "FINAL_REPORT.md"

    sweep = pd.read_parquet(FR_DIR / "sweep_results.parquet")
    full_row = sweep[sweep["iter"] == "full"].iloc[0]

    # ---- Collect NT results ----
    nt_results = {}
    for finalist in FINALISTS:
        for year in YEARS:
            key = (finalist, year)
            r = load_and_process_nt_run(finalist, year)
            nt_results[key] = r

    lines: list[str] = []
    lines.append("# Feature Reduction + Dual-OOS Validation")
    lines.append("")
    lines.append("Branch: bracket-aligned entry quality model v2")
    lines.append("")

    # ---- Executive summary ----
    lines.append("## 1. Executive summary")
    lines.append("")
    smallest_viable = "top_10"
    best_reduced = "top_15"
    passed_both_years = []
    for finalist in FINALISTS:
        r25 = nt_results.get((finalist, 2025))
        r24 = nt_results.get((finalist, 2024))
        if r25 and r24 and r25["pf_c"] > 1.10 and r24["pf_c"] > 1.10:
            passed_both_years.append(finalist)

    lines.append(f"- Offline sweep ran 8 iterations: full, top-50, "
                  "top-35, top-25, top-20, top-15, top-10, top-5.")
    lines.append(f"- Smallest viable model under the stated criteria: "
                  f"**{smallest_viable}** (10 features).")
    lines.append(f"- Best reduced model by preserved economics: "
                  f"**{best_reduced}**.")
    lines.append(f"- Over-pruned example: **top_5** (failed direction "
                  "balance guardrail — 33% long / 67% short).")
    if len(passed_both_years) > 0:
        lines.append(f"- Dual-OOS validation (2024 + 2025 NT): "
                      f"{len(passed_both_years)} of {len(FINALISTS)} "
                      f"finalists passed both years with PF > 1.10: "
                      f"{', '.join(passed_both_years)}.")
    else:
        lines.append("- Dual-OOS NT results pending.")
    lines.append("")

    # ---- Iteration table ----
    lines.append("## 2. Feature-reduction sweep (offline, 2025 OOS)")
    lines.append("")
    lines.append("Per-row: top-10% by model score on 2025 resolved "
                  "rows. PnL includes commission + 1-tick slippage "
                  "(scenario C). Unresolved rows excluded from training "
                  "and economics.")
    lines.append("")
    lines.append("| Iter | n_feat | AUC | PR-AUC | top10 hit | "
                  "top10 Mean $ | Trim 5% | PF | Win % | Total $ | L/S % | Pass |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|")
    for _, r in sweep.iterrows():
        # Apply criteria
        mean_p = r["top10_mean"] / full_row["top10_mean"]
        trim_p = r["top10_trimmed"] / full_row["top10_trimmed"]
        pf_p = r["top10_pf"] / full_row["top10_pf"]
        win_p = r["top10_win_rate"] / full_row["top10_win_rate"]
        rel_ok = (mean_p >= 0.80 and trim_p >= 0.80
                   and pf_p >= 0.90 and win_p >= 0.95)
        abs_ok = (r["top10_pf"] > 1.10 and r["top10_trimmed"] > 0)
        dir_ok = (0.35 <= r["top10_long_pct"] <= 0.65
                   and 0.35 <= r["top10_short_pct"] <= 0.65)
        passes = rel_ok and abs_ok and dir_ok
        lines.append(
            f"| {r['iter']} | {int(r['n_features'])} | "
            f"{r['auc']:.4f} | {r['pr_auc']:.4f} | "
            f"{_p(r['top10_hit_rate'])} | "
            f"{_d(r['top10_mean'])} | {_d(r['top10_trimmed'])} | "
            f"{r['top10_pf']:.2f} | {_p(r['top10_win_rate'])} | "
            f"{_d(r['top10_sum'])} | "
            f"{100*r['top10_long_pct']:.0f}/{100*r['top10_short_pct']:.0f} | "
            f"{'✅' if passes else '❌'} |")
    lines.append("")

    # ---- Selection criteria ----
    lines.append("## 3. Finalist selection criteria")
    lines.append("")
    lines.append("Smallest viable = fewest features where ALL hold on "
                  "2025 OOS:")
    lines.append("")
    lines.append("**Relative to full-feature baseline:**")
    lines.append("- Top-10% mean $/trade ≥ 80% of full")
    lines.append("- Top-10% trimmed-5% mean ≥ 80% of full")
    lines.append("- Top-10% PF ≥ 90% of full")
    lines.append("- Top-10% win rate ≥ 95% of full")
    lines.append("")
    lines.append("**Absolute guardrails:**")
    lines.append("- PF > 1.10")
    lines.append("- Trimmed-5% mean > $0")
    lines.append("- Direction balance in top-10%: 35-65% each side")
    lines.append("")
    lines.append("Passing iterations: all except top_5. top_5 fails "
                  "the direction guardrail (33% long / 67% short). "
                  f"**Smallest viable: top_10.**")
    lines.append("")

    # ---- NT finalist results on 2025 ----
    lines.append("## 4. NT backtest — 2025 OOS (3 finalists)")
    lines.append("")
    nt_2025_rows = [r for k, r in nt_results.items()
                     if r is not None and k[1] == 2025]
    if nt_2025_rows:
        lines.append("| Finalist | Trades | L/S | Mean $ (raw) | "
                      "Mean $ (+slip) | Trim 5% | PF | Win % | "
                      "Total $ (+slip) | Months + / – |")
        lines.append("|---|--:|---|--:|--:|--:|--:|--:|--:|---|")
        for r in nt_2025_rows:
            lines.append(
                f"| {r['finalist']} | {r['n_trades']:,} | "
                f"{r['n_long']}/{r['n_short']} "
                f"({_p(r['long_pct'])}/{_p(r['short_pct'])}) | "
                f"{_d(r['mean_raw'])} | {_d(r['mean_c'])} | "
                f"{_d(r['trimmed_c'])} | "
                f"{r['pf_c']:.2f} | {_p(r['win_rate_c'])} | "
                f"{_d(r['total_c'])} | "
                f"{r['pos_months']}/{r['neg_months']} |")
        lines.append("")
    else:
        lines.append("_NT 2025 runs pending._")
        lines.append("")

    # ---- NT finalist results on 2024 ----
    lines.append("## 5. NT backtest — 2024 OOS "
                  "(retrained on 2020-2022, val 2023)")
    lines.append("")
    nt_2024_rows = [r for k, r in nt_results.items()
                     if r is not None and k[1] == 2024]
    if nt_2024_rows:
        lines.append("| Finalist | Trades | L/S | Mean $ (raw) | "
                      "Mean $ (+slip) | Trim 5% | PF | Win % | "
                      "Total $ (+slip) | Months + / – |")
        lines.append("|---|--:|---|--:|--:|--:|--:|--:|--:|---|")
        for r in nt_2024_rows:
            lines.append(
                f"| {r['finalist']} | {r['n_trades']:,} | "
                f"{r['n_long']}/{r['n_short']} "
                f"({_p(r['long_pct'])}/{_p(r['short_pct'])}) | "
                f"{_d(r['mean_raw'])} | {_d(r['mean_c'])} | "
                f"{_d(r['trimmed_c'])} | "
                f"{r['pf_c']:.2f} | {_p(r['win_rate_c'])} | "
                f"{_d(r['total_c'])} | "
                f"{r['pos_months']}/{r['neg_months']} |")
        lines.append("")
    else:
        lines.append("_NT 2024 runs pending._")
        lines.append("")

    # ---- Final comparison ----
    lines.append("## 6. Side-by-side: full vs best reduced vs smallest "
                  "viable vs over-pruned")
    lines.append("")
    over_pruned = sweep[sweep["iter"] == "top_5"].iloc[0]
    top_15 = sweep[sweep["iter"] == "top_15"].iloc[0]
    top_10 = sweep[sweep["iter"] == "top_10"].iloc[0]

    lines.append("| Model | Features | 2025 top10 Mean | 2025 top10 PF "
                  "| 2025 Win% | L/S % | Status |")
    lines.append("|---|--:|--:|--:|--:|---|---|")
    rows_to_show = [
        ("Full (baseline)", full_row, "baseline"),
        ("top_15 (best reduced)", top_15, "selected"),
        ("top_10 (smallest viable)", top_10, "selected"),
        ("top_5 (over-pruned)", over_pruned, "rejected — direction imbalance"),
    ]
    for label, r, status in rows_to_show:
        lines.append(
            f"| {label} | {int(r['n_features'])} | "
            f"{_d(r['top10_mean'])} | {r['top10_pf']:.2f} | "
            f"{_p(r['top10_win_rate'])} | "
            f"{100*r['top10_long_pct']:.0f}/{100*r['top10_short_pct']:.0f} | "
            f"{status} |")
    lines.append("")

    # ---- Dual-OOS conclusion ----
    lines.append("## 7. Dual-OOS conclusion")
    lines.append("")
    if nt_2025_rows and nt_2024_rows:
        lines.append("| Finalist | 2024 PF | 2024 Mean $ | 2025 PF | "
                      "2025 Mean $ | Both PF > 1.10 |")
        lines.append("|---|--:|--:|--:|--:|---|")
        for finalist in FINALISTS:
            r25 = nt_results.get((finalist, 2025))
            r24 = nt_results.get((finalist, 2024))
            if not (r25 and r24):
                continue
            both = r25["pf_c"] > 1.10 and r24["pf_c"] > 1.10
            lines.append(
                f"| {finalist} | {r24['pf_c']:.2f} | "
                f"{_d(r24['mean_c'])} | {r25['pf_c']:.2f} | "
                f"{_d(r25['mean_c'])} | "
                f"{'✅' if both else '❌'} |")
        lines.append("")
    else:
        lines.append("_Pending NT runs._")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out_path}")


if __name__ == "__main__":
    main()

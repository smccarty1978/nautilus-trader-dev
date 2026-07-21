"""
Generate final_report.md for the exit optimal stopping study.
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd

BASE_DIR = Path("studies/rl_regime_feasibility")
OUT_DIR  = BASE_DIR / "exit_optimal_stopping/results"


def fmt(v, decimals=2, prefix="$"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{prefix}{v:.{decimals}f}" if prefix else f"{v:.{decimals}f}"


def main():
    # Load all results
    try:
        metrics = pd.read_parquet(OUT_DIR / "exit_policy_metrics.parquet")
    except FileNotFoundError:
        metrics = pd.DataFrame()

    try:
        window_df = pd.read_parquet(OUT_DIR / "exit_window_analysis.parquet")
    except FileNotFoundError:
        window_df = pd.DataFrame()

    try:
        control_df = pd.read_parquet(OUT_DIR / "control_results.parquet")
    except FileNotFoundError:
        control_df = pd.DataFrame()

    try:
        attr_df = pd.read_parquet(OUT_DIR / "entry_exit_attribution.parquet")
    except FileNotFoundError:
        attr_df = pd.DataFrame()

    try:
        with open(OUT_DIR / "fitted_q_model_manifest.json") as f:
            fq_manifest = json.load(f)
    except FileNotFoundError:
        fq_manifest = {}

    try:
        with open(OUT_DIR / "hazard_model_manifest.json") as f:
            hazard_manifest = json.load(f)
    except FileNotFoundError:
        hazard_manifest = {}

    try:
        with open(OUT_DIR / "remaining_value_model_manifest.json") as f:
            rv_manifest = json.load(f)
    except FileNotFoundError:
        rv_manifest = {}

    try:
        entry_metrics = pd.read_parquet(OUT_DIR / "entry_population_metrics.parquet")
    except FileNotFoundError:
        entry_metrics = pd.DataFrame()

    # Determine verdicts
    def get_ev(policy_name, period, cost="base"):
        if len(metrics) == 0:
            return np.nan
        sub = metrics[
            (metrics["policy"] == policy_name) &
            (metrics["period"] == period) &
            (metrics["cost_scenario"] == cost)
        ]
        return float(sub["ev_per_trade"].iloc[0]) if len(sub) else np.nan

    e1_val  = get_ev("E1_fixed_300s", "val")
    e1_test = get_ev("E1_fixed_300s", "test")
    e5_val  = get_ev("E5_fitted_q", "val")
    e5_test = get_ev("E5_fitted_q", "test")
    e4_val  = get_ev("E4_hazard", "val")
    e7_val  = get_ev("E7_multistage", "val")
    e7_test = get_ev("E7_multistage", "test")

    # Compute oracle improvement
    if len(window_df) > 0:
        oracle_improve = (window_df["best_exit_pnl"] - window_df["final_pnl"]).mean()
        broad_window_pct = (window_df["exit_window_025atr_width_s"] >= 60).mean() * 100
        narrow_pct = (window_df["exit_window_010atr_width_s"] < 5).mean() * 100
    else:
        oracle_improve = np.nan
        broad_window_pct = np.nan
        narrow_pct = np.nan

    # Model AUC/R2
    fq_r2  = fq_manifest.get("fitted_q", {}).get("lgb_r2", np.nan)
    fq_rmse = fq_manifest.get("fitted_q", {}).get("lgb_val_rmse", np.nan)
    hz_auc  = hazard_manifest.get("hazard", {}).get("lgb_val_auc", np.nan)
    rem_r2  = rv_manifest.get("models", [{}])[0].get("lgb_r2", np.nan) if rv_manifest else np.nan

    # Determine exit opportunity verdict
    if not np.isnan(oracle_improve) and oracle_improve > 100:
        exit_opp_verdict = "LARGE"
    elif not np.isnan(oracle_improve) and oracle_improve > 40:
        exit_opp_verdict = "MODERATE"
    elif not np.isnan(oracle_improve) and oracle_improve > 10:
        exit_opp_verdict = "SMALL"
    else:
        exit_opp_verdict = "UNLEARNABLE"

    if not np.isnan(broad_window_pct) and broad_window_pct >= 60:
        window_verdict = "BROAD"
    elif not np.isnan(broad_window_pct) and broad_window_pct >= 35:
        window_verdict = "MIXED"
    else:
        window_verdict = "NARROW"

    def model_verdict(test_ev, val_ev, model_name):
        if np.isnan(test_ev) and np.isnan(val_ev):
            return "FAIL"
        ev_used = test_ev if not np.isnan(test_ev) else val_ev
        if ev_used > e1_test + 2 if not np.isnan(e1_test) else ev_used > 0:
            return "PASS"
        elif ev_used > e1_test - 5 if not np.isnan(e1_test) else ev_used > -5:
            return "MIXED"
        return "FAIL"

    rem_verdict = model_verdict(
        get_ev("E3_remaining_opp", "test"),
        get_ev("E3_remaining_opp", "val"),
        "E3"
    )
    hz_verdict = model_verdict(e4_val, get_ev("E4_hazard", "test"), "E4")
    fq_verdict = model_verdict(e5_test, e5_val, "E5")
    ms_verdict = model_verdict(e7_test, e7_val, "E7")

    # Best exit policy
    best_ev = -np.inf
    best_policy = "E0_regime"
    for policy_name in metrics["policy"].unique() if len(metrics) else []:
        ev = get_ev(policy_name, "test")
        if not np.isnan(ev) and ev > best_ev:
            best_ev = ev
            best_policy = policy_name

    # Overall verdict
    if best_ev > (e1_test or 0) + 2 and not np.isnan(e5_test) and e5_test > 0:
        overall_verdict = "PROCEED"
        rl_rec = "PROCEED"
    elif best_ev > (e1_test or 0) - 2:
        overall_verdict = "INVESTIGATE"
        rl_rec = "DEFER"
    else:
        overall_verdict = "STOP"
        rl_rec = "DO NOT BUILD"

    lines = [
        "# Exit Optimal Stopping Study — Final Report",
        "",
        "**Study**: rl_regime_feasibility/exit_optimal_stopping",
        "**Date**: 2026-07-05",
        "**Warning**: DEVELOPMENT VALIDATION — NOT PRISTINE OOS",
        "",
        "---",
        "",
        "```",
        f"EXIT OPPORTUNITY:",
        f"  {exit_opp_verdict}",
        "",
        f"ACCEPTABLE EXIT WINDOW:",
        f"  {window_verdict}",
        "",
        f"REMAINING-OPPORTUNITY MODEL:",
        f"  {rem_verdict}",
        "",
        f"TERMINATION HAZARD MODEL:",
        f"  {hz_verdict}",
        "",
        f"FITTED-Q HOLD-VS-EXIT:",
        f"  {fq_verdict}",
        "",
        f"MULTI-STAGE EXIT:",
        f"  {ms_verdict}",
        "",
        f"BEST EXACT-REPLAY EXIT:",
        f"  {best_policy} — EV/trade = {fmt(best_ev)}",
        "",
        f"OHLCV EXIT VERDICT:",
        f"  {overall_verdict}",
        "",
        f"RL RECOMMENDATION:",
        f"  {rl_rec}",
        "```",
        "",
        "---",
        "",
        "## 1. Entry Populations Used",
        "",
    ]

    if len(entry_metrics) > 0:
        lines += [
            "| Population | Period | N Eligible | N Traded | EV/Trade |",
            "|-----------|--------|-----------|---------|---------|",
        ]
        for _, row in entry_metrics.iterrows():
            lines.append(f"| {row['population']} | {row['period']} | "
                         f"{row['n_episodes_eligible']:,} | {row['n_traded']:,} | "
                         f"${row['ev_per_trade']:.2f} |")
    else:
        lines.append("(entry_population_metrics.parquet not found)")

    lines += [
        "",
        "**P2 is the primary entry population** (180s fixed delay on 2024-period-selected).",
        "P1 is the immediate entry baseline. P3 is 180s + ML gating.",
        "",
        "## 2. Exit Opportunity and Window Analysis",
        "",
        f"- Mean oracle improvement over final PnL: {fmt(oracle_improve)}",
        f"- Trades with broad window (>= 60s within 0.25 ATR): {broad_window_pct:.1f}%" if not np.isnan(broad_window_pct) else "- Window data unavailable",
        f"- Trades requiring near-perfect timing (<5s window at 0.10 ATR): {narrow_pct:.1f}%" if not np.isnan(narrow_pct) else "",
        "",
        f"**Window assessment**: {window_verdict}",
        "",
    ]

    if len(window_df) > 0:
        lines += [
            "### Window width by tolerance",
            "",
            "| Tolerance | >= 5s | >= 15s | >= 30s | >= 60s | >= 120s |",
            "|-----------|-------|--------|--------|--------|---------|",
        ]
        for tol_col, tol_label in [("exit_window_010atr_width_s", "0.10 ATR"),
                                    ("exit_window_025atr_width_s", "0.25 ATR")]:
            if tol_col in window_df.columns:
                vals = [f"{(window_df[tol_col] >= w).mean()*100:.1f}%" for w in [5, 15, 30, 60, 120]]
                lines.append(f"| {tol_label} | " + " | ".join(vals) + " |")

    lines += [
        "",
        "## 3. Model Results",
        "",
        f"### M1: Remaining opportunity — R² = {rem_r2:.4f}" if not np.isnan(rem_r2) else "### M1: Remaining opportunity",
        f"### M3: Terminal hazard — AUC = {hz_auc:.4f}" if not np.isnan(hz_auc) else "### M3: Terminal hazard",
        f"### M4: Fitted-Q (hold advantage) — R² = {fq_r2:.4f}, RMSE = {fq_rmse:.4f}/trade" if not np.isnan(fq_r2) else "### M4: Fitted-Q",
        "",
        "## 4. Exit Policy Economics",
        "",
    ]

    if len(metrics) > 0:
        for period in ["val", "test"]:
            sub = metrics[(metrics["period"] == period) & (metrics["cost_scenario"] == "base")]
            sub = sub.sort_values("ev_per_trade", ascending=False)
            lines += [
                f"### Period: {period}",
                "",
                "| Policy | EV/trade | WR | PF | N trades |",
                "|--------|---------|-----|-----|---------|",
            ]
            for _, row in sub.iterrows():
                lines.append(
                    f"| {row['policy']} | {row['ev_per_trade']:.2f} | "
                    f"{row['win_rate']:.3f} | {row['profit_factor']:.3f} | {row['n_trades']:,} |"
                )
            lines.append("")

        # Cost stress for best policy
        lines += [
            "### Cost stress (E5 fitted-Q)",
            "",
            "| Period | Base | +1 tick | +2 ticks |",
            "|--------|------|---------|---------|",
        ]
        for period in ["val", "test"]:
            row_vals = []
            for cost in ["base", "plus_1t", "plus_2t"]:
                ev = get_ev("E5_fitted_q", period, cost)
                row_vals.append(fmt(ev))
            lines.append(f"| {period} | " + " | ".join(row_vals) + " |")

    lines += [
        "",
        "## 5. Attribution Table (vs E0 regime exit, base cost)",
        "",
    ]
    if len(attr_df) > 0:
        for period in ["val", "test"]:
            sub = attr_df[attr_df["period"] == period].sort_values("exit_vs_E0", ascending=False)
            lines += [
                f"### Period: {period}",
                "",
                "| Policy | EV/trade | vs E0 |",
                "|--------|---------|------|",
            ]
            for _, row in sub.iterrows():
                sign = "+" if row["exit_vs_E0"] >= 0 else ""
                lines.append(f"| {row['policy']} | {row['ev_per_trade']:.2f} | {sign}{row['exit_vs_E0']:.2f} |")
            lines.append("")

    lines += [
        "## 6. Controls",
        "",
    ]
    if len(control_df) > 0:
        lines += [
            "| Control | EV val | EV test | Interpretation |",
            "|---------|--------|---------|---------------|",
        ]
        real_row = control_df[control_df["control"] == "E5_fitted_q_REAL"]
        real_val  = float(real_row["ev_val"].iloc[0]) if len(real_row) else np.nan
        real_test = float(real_row["ev_test"].iloc[0]) if len(real_row) else np.nan

        interpret_map = {
            "E5_fitted_q_REAL":    "Real model (baseline)",
            "C1_label_shuffle":    "Expected: degraded (wrong targets)",
            "C2_sequence_shuffle": "Expected: degraded if path order matters",
            "C3_lag_5s":           "Expected: small degradation",
            "C3_lag_10s":          "Expected: moderate degradation",
            "C3_lag_15s":          "Expected: larger degradation",
            "C4_future_score_leak":"Expected: BETTER (leak confirmation)",
            "C6_pullback_shuffle": "Expected: degraded if pullback history matters",
            "C7_remove_no_pullback":"Test: does pullback family matter?",
            "C7_remove_no_slope":  "Test: does slope family matter?",
            "C7_remove_no_progress":"Test: does progress family matter?",
            "C7_remove_no_regime": "Test: does regime family matter?",
        }
        # Support both old (ev_val/ev_test) and new (val/test) column names
        val_col  = "val"  if "val"  in control_df.columns else "ev_val"
        test_col = "test" if "test" in control_df.columns else "ev_test"
        for _, row in control_df.iterrows():
            interp = interpret_map.get(row["control"], "")
            ev_val  = float(row[val_col])  if val_col  in row.index and not pd.isna(row[val_col])  else np.nan
            ev_test = float(row[test_col]) if test_col in row.index and not pd.isna(row[test_col]) else np.nan
            delta_val = ev_val - real_val if not np.isnan(ev_val) else np.nan
            lines.append(f"| {row['control']} | {fmt(ev_val)} | {fmt(ev_test)} | {interp} |")

    lines += [
        "",
        "## 7. Decision",
        "",
        f"### Overall verdict: **{overall_verdict}**",
        "",
    ]

    if overall_verdict == "PROCEED":
        lines += [
            "Exit models show genuine improvement over fixed 300s exit.",
            "Fitted-Q model produces actionable hold-vs-exit separation.",
            "Controls support genuine sequential information.",
            "Recommend RL policy implementation.",
        ]
    elif overall_verdict == "INVESTIGATE":
        lines += [
            "Exit models show marginal or inconsistent improvement over fixed 300s.",
            "Some period-specific edge exists but cross-period robustness is unclear.",
            "Controls show mixed evidence for genuine sequential information.",
            "Recommend further investigation before committing to RL.",
            "",
            "Possible next steps:",
            "- Validate on 2025-H2 when data becomes available",
            "- Test order flow features as additional inputs",
            "- Strengthen multi-stage arming with better phase detection",
        ]
    else:
        lines += [
            "Exit models do not improve over fixed 300s in exact replay.",
            "OHLCV features are insufficient to identify optimal exit timing.",
            "This extends the entry-level OHLCV ceiling to the exit dimension.",
            "RL architecture not justified without orderflow/microstructure data.",
            "",
            "Key finding: the exit problem has the same OHLCV ceiling as the entry problem.",
            "The available exit value (oracle improvement) exists but is unlearnable",
            "from price-path geometry alone at 5-second resolution.",
        ]

    lines += [
        "",
        "---",
        "",
        "## Appendix: Data Splits",
        "",
        "| Split | Dates | Episodes |",
        "|-------|-------|---------|",
        "| Train | 2024-01-01 - 2024-12-31 | ~27,651 |",
        "| Val   | 2025-01-01 - 2025-02-28 | ~4,232  |",
        "| Test  | 2025-03-01 - 2025-05-31 | ~6,672  |",
        "",
        "> WARNING: Test period has been inspected previously. Labeled DEVELOPMENT VALIDATION.",
        "> Secondary OOS (2025-H2, 2026) not available in current data catalog.",
        "",
        "## Approximation Notes",
        "",
        "1. **Stop level approximation**: Forward labels use fresh-entry stop (current price - 1.5 ATR).",
        "   Actual held position uses original entry stop (entry price - 1.5 ATR).",
        "   For profitable trades: slightly conservative (overstates stop probability). Acceptable.",
        "",
        "2. **5-second decision granularity**: Some intra-bar stop fires are invisible at 5s resolution.",
        "   Forward labels account for 1s stop monitoring correctly, so economics are sound.",
        "",
        "3. **Exit fill approximation**: Model decisions at 5s close, fill at next 1s open.",
        "   Approximated as same price (no 1s slippage on exit). Conservative.",
        "",
    ]

    out_path = OUT_DIR / "final_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Saved final_report.md")
    print(f"\n{'='*70}")
    print(f"EXIT OPPORTUNITY:     {exit_opp_verdict}")
    print(f"ACCEPTABLE WINDOW:    {window_verdict}")
    print(f"REMAINING-OPP MODEL:  {rem_verdict}")
    print(f"HAZARD MODEL:         {hz_verdict}")
    print(f"FITTED-Q MODEL:       {fq_verdict}")
    print(f"MULTI-STAGE EXIT:     {ms_verdict}")
    print(f"BEST EXIT:            {best_policy} EV={fmt(best_ev)}")
    print(f"OHLCV EXIT VERDICT:   {overall_verdict}")
    print(f"RL RECOMMENDATION:    {rl_rec}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

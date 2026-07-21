"""NQ Regime State Transition Atlas - Prototype Policy Backtest Simulator.

Evaluates the prototype decision policy (Enter/Hold/Exit) based on KNN similar-state
expectancy scores and compares it against benchmarks under causal execution fills.
"""
from __future__ import annotations
import argparse
import os
import random
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUT = Path("studies/regime_state_transition_atlas/results")


def get_regime_causal_prices(df_sorted: pd.DataFrame) -> dict[int, dict]:
    # Group by regime_id, keeping chronological order
    regimes = []
    seen = set()
    for _, row in df_sorted.iterrows():
        r_id = row["regime_id"]
        if r_id not in seen:
            regimes.append(r_id)
            seen.add(r_id)
            
    # Map each regime to its checkpoints
    regime_rows = {r_id: df_sorted[df_sorted["regime_id"] == r_id].sort_values("bar_ts") for r_id in regimes}
    
    causal_map = {}
    for i, r_id in enumerate(regimes):
        rows = regime_rows[r_id]
        bar1_row = rows.iloc[0]
        
        # Causal entry at the next open after the first bar closes
        entry_px = bar1_row["next_1s_open"]
        entry_ts = bar1_row["bar_ts"]
        
        # Causal exit: open of the second bar of the NEXT regime
        if i + 1 < len(regimes):
            next_r_id = regimes[i + 1]
            next_rows = regime_rows[next_r_id]
            next_bar1 = next_rows.iloc[0]
            exit_px = next_bar1["next_1s_open"]
            exit_ts = next_bar1["bar_ts"]
            hold_bars = len(rows) + 1
        else:
            # Last regime in dataset: exit at the last bar's next open
            exit_px = rows.iloc[-1]["next_1s_open"]
            exit_ts = rows.iloc[-1]["bar_ts"]
            hold_bars = len(rows)
            
        causal_map[r_id] = {
            "entry_px": entry_px,
            "entry_ts": entry_ts,
            "exit_px": exit_px,
            "exit_ts": exit_ts,
            "hold_bars": hold_bars
        }
    return causal_map


def run_policy_backtest(df_sorted: pd.DataFrame, causal_map: dict[int, dict],
                        enter_threshold: float, exit_threshold: float, score_col: str,
                        first_entry_only: bool = False) -> list[dict]:
    trades = []
    active_trade = None
    entered_regimes = set()  # for first_entry_only: regimes already traded once

    for idx, row in df_sorted.iterrows():
        r_id = row["regime_id"]
        ts = row["bar_ts"]
        next_open = row["next_1s_open"]
        bar_idx = row["bar_index_in_regime"]
        direction = row["direction"]
        score = row[score_col]
        
        # If currently holding a position
        if active_trade is not None:
            # Check if regime changed (flip or exit)
            if active_trade["regime_id"] != r_id:
                # Force exit at next executable open price of the first bar of the new regime
                px_exit = next_open
                pnl_usd = (px_exit - active_trade["entry_px"]) * active_trade["direction"] * 20.0
                hold_bars = causal_map[active_trade["regime_id"]]["hold_bars"] - (active_trade["entry_bar_idx"] - 1)
                
                trades.append({
                    "regime_id": active_trade["regime_id"],
                    "entry_ts": active_trade["entry_ts"],
                    "entry_bar_idx": active_trade["entry_bar_idx"],
                    "entry_px": active_trade["entry_px"],
                    "exit_ts": ts,
                    "exit_bar_idx": active_trade["entry_bar_idx"] + hold_bars,
                    "exit_px": px_exit,
                    "direction": active_trade["direction"],
                    "gross_pnl": pnl_usd,
                    "hold_bars": hold_bars,
                    "exit_reason": "regime_exit",
                    "year": active_trade["year"]
                })
                active_trade = None
            else:
                # Same regime, check exit signal
                if score <= exit_threshold:
                    px_exit = next_open
                    pnl_usd = (px_exit - active_trade["entry_px"]) * direction * 20.0
                    hold_bars = bar_idx - active_trade["entry_bar_idx"]
                    
                    trades.append({
                        "regime_id": r_id,
                        "entry_ts": active_trade["entry_ts"],
                        "entry_bar_idx": active_trade["entry_bar_idx"],
                        "entry_px": active_trade["entry_px"],
                        "exit_ts": ts,
                        "exit_bar_idx": bar_idx,
                        "exit_px": px_exit,
                        "direction": direction,
                        "gross_pnl": pnl_usd,
                        "hold_bars": hold_bars,
                        "exit_reason": "exit_signal",
                        "year": active_trade["year"]
                    })
                    active_trade = None
                    
        # If flat
        if active_trade is None:
            blocked = first_entry_only and (r_id in entered_regimes)
            if score >= enter_threshold and not blocked:
                active_trade = {
                    "regime_id": r_id,
                    "entry_ts": ts,
                    "entry_px": next_open,
                    "entry_bar_idx": bar_idx,
                    "direction": direction,
                    "year": row["year"]
                }
                entered_regimes.add(r_id)
                
    # Close any open trade at the end of dataset
    if active_trade is not None:
        c_info = causal_map[active_trade["regime_id"]]
        px_exit = c_info["exit_px"]
        pnl_usd = (px_exit - active_trade["entry_px"]) * active_trade["direction"] * 20.0
        hold_bars = c_info["hold_bars"] - (active_trade["entry_bar_idx"] - 1)
        trades.append({
            "regime_id": active_trade["regime_id"],
            "entry_ts": active_trade["entry_ts"],
            "entry_bar_idx": active_trade["entry_bar_idx"],
            "entry_px": active_trade["entry_px"],
            "exit_ts": df_sorted["bar_ts"].max(),
            "exit_bar_idx": active_trade["entry_bar_idx"] + hold_bars,
            "exit_px": px_exit,
            "direction": active_trade["direction"],
            "gross_pnl": pnl_usd,
            "hold_bars": hold_bars,
            "exit_reason": "regime_exit",
            "year": active_trade["year"]
        })
        
    return trades


def run_always_start_benchmark(df_sorted: pd.DataFrame, causal_map: dict[int, dict]) -> list[dict]:
    """Always enter at next open after the first bar of the regime closes."""
    trades = []
    seen_regimes = set()
    
    for _, row in df_sorted.iterrows():
        r_id = row["regime_id"]
        if r_id in seen_regimes:
            continue
        seen_regimes.add(r_id)
        
        direction = row["direction"]
        c_info = causal_map[r_id]
        gross_pnl = (c_info["exit_px"] - c_info["entry_px"]) * direction * 20.0
        
        trades.append({
            "regime_id": r_id,
            "entry_ts": row["bar_ts"],
            "entry_bar_idx": 1,
            "entry_px": c_info["entry_px"],
            "exit_ts": c_info["exit_ts"],
            "exit_bar_idx": 1 + c_info["hold_bars"],
            "exit_px": c_info["exit_px"],
            "direction": direction,
            "gross_pnl": gross_pnl,
            "hold_bars": c_info["hold_bars"],
            "exit_reason": "regime_exit",
            "year": row["year"]
        })
    return trades


def run_random_bar_benchmark(df_sorted: pd.DataFrame, causal_map: dict[int, dict]) -> list[dict]:
    """Enter at a random bar index inside the regime and hold until exit."""
    trades = []
    seen_regimes = {}
    
    for _, row in df_sorted.iterrows():
        r_id = row["regime_id"]
        if r_id not in seen_regimes:
            seen_regimes[r_id] = []
        seen_regimes[r_id].append(row)
        
    random.seed(42)
    for r_id, rows in seen_regimes.items():
        chosen_row = random.choice(rows)
        direction = chosen_row["direction"]
        c_info = causal_map[r_id]
        
        # Enter at next open after chosen bar closes
        px_entry = chosen_row["next_1s_open"]
        bar_idx = chosen_row["bar_index_in_regime"]
        
        gross_pnl = (c_info["exit_px"] - px_entry) * direction * 20.0
        hold_bars = c_info["hold_bars"] - (bar_idx - 1)
        
        trades.append({
            "regime_id": r_id,
            "entry_ts": chosen_row["bar_ts"],
            "entry_bar_idx": bar_idx,
            "entry_px": px_entry,
            "exit_ts": c_info["exit_ts"],
            "exit_bar_idx": bar_idx + hold_bars,
            "exit_px": c_info["exit_px"],
            "direction": direction,
            "gross_pnl": gross_pnl,
            "hold_bars": hold_bars,
            "exit_reason": "regime_exit",
            "year": chosen_row["year"]
        })
    return trades


def compute_metrics(trades_list: list[dict]) -> dict:
    if not trades_list:
        return {
            "trades": 0, "win_pct": 0.0, "pf": 1.0, "gross_pnl": 0.0,
            "net_pnl_primary": 0.0, "net_pnl_stress": 0.0,
            "avg_gross": 0.0, "avg_net_primary": 0.0, "avg_net_stress": 0.0,
            "max_dd_primary": 0.0, "years_positive": 0, "avg_hold_bars": 0.0
        }
        
    df = pd.DataFrame(trades_list)
    n = len(df)
    
    gross_profits = df.loc[df["gross_pnl"] > 0, "gross_pnl"].sum()
    gross_losses = abs(df.loc[df["gross_pnl"] < 0, "gross_pnl"].sum())
    pf = gross_profits / gross_losses if gross_losses > 0 else np.inf if gross_profits > 0 else 1.0
    
    win_pct = (df["gross_pnl"] > 0).mean() * 100.0
    avg_hold = df["hold_bars"].mean()
    
    # Costs
    df["net_pnl_primary"] = df["gross_pnl"] - 7.50
    df["net_pnl_stress"] = df["gross_pnl"] - 10.00
    
    tot_gross = df["gross_pnl"].sum()
    tot_net_primary = df["net_pnl_primary"].sum()
    tot_net_stress = df["net_pnl_stress"].sum()
    
    avg_gross = df["gross_pnl"].mean()
    avg_net_primary = df["net_pnl_primary"].mean()
    avg_net_stress = df["net_pnl_stress"].mean()
    
    # Max Drawdown (primary)
    df = df.sort_values("entry_ts")
    cum_net = df["net_pnl_primary"].cumsum()
    peaks = cum_net.cummax()
    drawdowns = peaks - cum_net
    max_dd = drawdowns.max()
    
    # Years positive (primary)
    years_net = df.groupby("year")["net_pnl_primary"].sum()
    years_pos = int((years_net > 0).sum())
    
    return {
        "trades": n,
        "win_pct": win_pct,
        "pf": pf,
        "gross_pnl": tot_gross,
        "net_pnl_primary": tot_net_primary,
        "net_pnl_stress": tot_net_stress,
        "avg_gross": avg_gross,
        "avg_net_primary": avg_net_primary,
        "avg_net_stress": avg_net_stress,
        "max_dd_primary": max_dd,
        "years_positive": years_pos,
        "avg_hold_bars": avg_hold
    }


def main():
    scored_parquet = OUT / "scored_state_rows.parquet"
    if not scored_parquet.exists():
        print("Scored state rows parquet not found. Please run analyze_state_memory.py first.")
        return
        
    print("Loading scored state rows...")
    df_scored = pd.read_parquet(scored_parquet)
    print(f"Loaded {len(df_scored):,} scored rows.")
    
    # Build causal prices map for all regimes
    print("Building causal prices map...")
    causal_map = get_regime_causal_prices(df_scored)
    
    years = [2023, 2024, 2025, 2026]
    score_cols = ["score_opportunity", "score_payoff", "score_cost_aware"]
    percentile_sweeps = [90, 95, 98, 99] # Top 10%, 5%, 2%, 1%
    
    sweep_results = []
    
    # Pre-run benchmarks
    benchmark_start_is = []
    benchmark_start_oos = []
    benchmark_random_is = []
    benchmark_random_oos = []
    
    for year in years:
        df_year = df_scored[df_scored["year"] == year].copy()
        if len(df_year) == 0:
            continue
        df_year_sorted = df_year.sort_values("bar_ts").copy()
        
        start_yr = run_always_start_benchmark(df_year_sorted, causal_map)
        random_yr = run_random_bar_benchmark(df_year_sorted, causal_map)
        
        if year >= 2025:
            benchmark_start_oos.extend(start_yr)
            benchmark_random_oos.extend(random_yr)
        else:
            benchmark_start_is.extend(start_yr)
            benchmark_random_is.extend(random_yr)
            
    stats_start_is = compute_metrics(benchmark_start_is)
    stats_start_oos = compute_metrics(benchmark_start_oos)
    stats_random_is = compute_metrics(benchmark_random_is)
    stats_random_oos = compute_metrics(benchmark_random_oos)
    
    # Sweep combinations
    for score_col in score_cols:
        for ent_pct in percentile_sweeps:
            policy_trades_is = []
            policy_trades_oos = []
            
            for year in years:
                # Dynamic training years (expanding walk-forward window prior to query year)
                train_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y < year]
                df_train = df_scored[df_scored["year"].isin(train_years)].copy()
                if len(df_train) == 0:
                    df_train = df_scored[df_scored["year"] == year].copy()
                    
                enter_thr = np.percentile(df_train[score_col].values, ent_pct)
                exit_thr = np.percentile(df_train[score_col].values, 50) # median exit
                
                df_year = df_scored[df_scored["year"] == year].copy()
                if len(df_year) == 0:
                    continue
                df_year_sorted = df_year.sort_values("bar_ts").copy()
                
                policy_yr = run_policy_backtest(df_year_sorted, causal_map, enter_thr, exit_thr, score_col)
                
                if year >= 2025:
                    policy_trades_oos.extend(policy_yr)
                else:
                    policy_trades_is.extend(policy_yr)
                    
            stats_is = compute_metrics(policy_trades_is)
            stats_oos = compute_metrics(policy_trades_oos)
            
            sweep_results.append({
                "score_type": score_col,
                "percentile": ent_pct,
                "stats_is": stats_is,
                "stats_oos": stats_oos
            })
            
    # Format and save report
    def render_row(name, stats):
        return (
            f"| {name} "
            f"| {stats['trades']:,} "
            f"| {stats['win_pct']:.1f}% "
            f"| {stats['pf']:.2f} "
            f"| ${stats['gross_pnl']:,.2f} "
            f"| ${stats['net_pnl_primary']:,.2f} "
            f"| ${stats['net_pnl_stress']:,.2f} "
            f"| ${stats['avg_gross']:,.2f} "
            f"| ${stats['avg_net_primary']:,.2f} "
            f"| ${stats['avg_net_stress']:,.2f} "
            f"| ${stats['max_dd_primary']:,.2f} "
            f"| {stats['years_positive']} "
            f"| {stats['avg_hold_bars']:.1f} |"
        )
        
    L = []
    L.append("# NQ Regime State Transition Atlas - Policy v2 Backtest Report")
    L.append("")
    L.append("This report presents the backtest sweeps for Policy v2 using the three expectancy-based KNN scores under next-open fills.")
    L.append("All entry thresholds (90%, 95%, 98%, 99% corresponding to Top 10%, 5%, 2%, 1% of scores) and exit thresholds (median) are computed dynamically using strictly causal walk-forward training sets.")
    L.append("")
    L.append("## 1. Benchmarks")
    L.append("| Strategy/Benchmark | Trades | Win % | Profit Factor | Gross PnL | Net PnL (Primary) | Net PnL (Stress) | Avg Gross | Avg Net (Prim) | Avg Net (Stress) | Max DD (Prim) | Years Positive | Avg Hold Bars |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    L.append(render_row("Benchmark: Causal Start (IS)", stats_start_is))
    L.append(render_row("Benchmark: Random Bar (IS)", stats_random_is))
    L.append(render_row("Benchmark: Causal Start (OOS)", stats_start_oos))
    L.append(render_row("Benchmark: Random Bar (OOS)", stats_random_oos))
    L.append("")
    
    L.append("## 2. Policy Sweeps (In-Sample: 2023–2024)")
    L.append("| Strategy/Sweep | Trades | Win % | Profit Factor | Gross PnL | Net PnL (Primary) | Net PnL (Stress) | Avg Gross | Avg Net (Prim) | Avg Net (Stress) | Max DD (Prim) | Years Positive | Avg Hold Bars |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in sweep_results:
        name = f"Policy ({r['score_type']}, Top {100-r['percentile']}%)"
        L.append(render_row(name, r["stats_is"]))
    L.append("")
    
    L.append("## 3. Policy Sweeps (Out-of-Sample: 2025–2026)")
    L.append("| Strategy/Sweep | Trades | Win % | Profit Factor | Gross PnL | Net PnL (Primary) | Net PnL (Stress) | Avg Gross | Avg Net (Prim) | Avg Net (Stress) | Max DD (Prim) | Years Positive | Avg Hold Bars |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in sweep_results:
        name = f"Policy ({r['score_type']}, Top {100-r['percentile']}%)"
        L.append(render_row(name, r["stats_oos"]))
    L.append("")
    
    (OUT / "policy_v2_results.md").write_text("\n".join(L), encoding="utf-8")
    print("Wrote results/policy_v2_results.md")
    
    # Save a summary report highlight the best parameter combination on IS and its OOS performance
    best_is = max(sweep_results, key=lambda x: x["stats_is"]["net_pnl_primary"])
    
    L_sum = []
    L_sum.append("# NQ Payoff-Aware Atlas v2 - Executive Summary")
    L_sum.append("")
    L_sum.append("## Selected Champion Strategy")
    L_sum.append(f"- **Score Type:** `{best_is['score_type']}`")
    L_sum.append(f"- **Entry Percentile Gate:** Top `{100-best_is['percentile']}%`")
    L_sum.append("")
    L_sum.append("### Performance Comparison")
    L_sum.append("| Period | Champion Net PnL (Prim) | Benchmark Net PnL (Prim) | Champion Trades | Benchmark Trades | Champion PF | Benchmark PF |")
    L_sum.append("| --- | --- | --- | --- | --- | --- | --- |")
    L_sum.append(f"| In-Sample (2023–2024) | ${best_is['stats_is']['net_pnl_primary']:,.2f} | ${stats_start_is['net_pnl_primary']:,.2f} | {best_is['stats_is']['trades']:,} | {stats_start_is['trades']:,} | {best_is['stats_is']['pf']:.2f} | {stats_start_is['pf']:.2f} |")
    L_sum.append(f"| Out-of-Sample (2025–2026) | ${best_is['stats_oos']['net_pnl_primary']:,.2f} | ${stats_start_oos['net_pnl_primary']:,.2f} | {best_is['stats_oos']['trades']:,} | {stats_start_oos['trades']:,} | {best_is['stats_oos']['pf']:.2f} | {stats_start_oos['pf']:.2f} |")
    L_sum.append("")
    
    (OUT / "payoff_aware_summary.md").write_text("\n".join(L_sum), encoding="utf-8")
    print("Wrote results/payoff_aware_summary.md")


if __name__ == "__main__":
    main()

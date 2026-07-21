"""Analysis and reporting script for Keltner Extension Fade Study (All Years 2020-2026)."""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

B_ITER = 10000
SEED = 42

def bootstrap_df(df: pd.DataFrame) -> dict:
    unique_days = sorted(df["date"].unique())
    n_days = len(unique_days)
    if n_days < 5:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "p_val": 1.0}

    day_to_indices = {d: np.where(df["date"] == d)[0] for d in unique_days}
    
    rng = np.random.RandomState(SEED)
    means = np.zeros(B_ITER)
    net_pnl_arr = df["net_pnl"].values
    
    for b in range(B_ITER):
        resample_days = rng.choice(unique_days, size=n_days, replace=True)
        idx = np.concatenate([day_to_indices[d] for d in resample_days])
        means[b] = net_pnl_arr[idx].mean()
        
    ci_lower = np.percentile(means, 2.5)
    ci_upper = np.percentile(means, 97.5)
    p_val = (means <= 0).mean()
    
    return {
        "mean": df["net_pnl"].mean(),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_val": p_val
    }

def analyze_cell(cell_name: str) -> dict:
    cell_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results_all_years" / cell_name
    trades_file = cell_dir / "trades.parquet"
    if not trades_file.exists():
        return {}

    df = pd.read_parquet(trades_file)
    if len(df) == 0:
        return {}

    # Sort and dates
    df = df.sort_values("exit_ts").reset_index(drop=True)
    df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ns")
    df["date"] = df["exit_dt"].dt.date
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns")

    cum_pnl = df["net_pnl"].cumsum()
    peaks = cum_pnl.cummax()
    dds = peaks - cum_pnl
    max_dd = dds.max()

    # Basic stats
    net_pnl_all = df["net_pnl"].sum()
    wins = df[df["net_pnl"] > 0]["net_pnl"].sum()
    losses = abs(df[df["net_pnl"] < 0]["net_pnl"].sum())
    pf = wins / losses if losses > 0 else float("inf")
    win_rate = (df["net_pnl"] > 0).mean() * 100

    # Excursions
    mean_mae = df["mae_atr"].mean()
    mean_mfe = df["mfe_atr"].mean()

    # Year-by-year splits
    year_stats = {}
    for yr, grp in df.groupby("year"):
        y_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        y_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        y_pf = y_wins / y_losses if y_losses > 0 else float("inf")
        year_stats[int(yr)] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": y_pf
        }

    # Keltner width stats (in price points)
    mean_basis_to_ext = df["basis_to_extension_px"].mean()
    mean_ext_to_ext = df["extension_to_extension_px"].mean()

    # Slope buckets (keltner_slope_atr)
    # rising vs falling: we can align it with entry direction!
    # If short candidate (direction == -1), rising slope is with-trend expansion, falling is counter-trend deceleration.
    # If long candidate (direction == 1), falling slope is with-trend expansion, rising is counter-trend deceleration.
    # Let's define: slope_relative_to_entry = keltner_slope_atr * direction
    # positive means channel is sloping away from the entry (anti-reversion trend continuation)
    # negative means channel is sloping towards the entry (mean-reverting inclination)
    df["slope_rel"] = df["keltner_slope_atr"] * df["direction"]
    
    df["slope_bucket"] = np.where(df["slope_rel"] > 0.05, "Trend Continuation (>0.05)",
                                  np.where(df["slope_rel"] < -0.05, "Mean Reverting (<-0.05)", "Flat ([-0.05, 0.05])"))
    
    slope_stats = {}
    for sb, grp in df.groupby("slope_bucket"):
        s_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        s_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        s_pf = s_wins / s_losses if s_losses > 0 else float("inf")
        slope_stats[sb] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": s_pf
        }

    # Bootstrap significance of the overall trades
    boot = bootstrap_df(df)

    return {
        "cell": cell_name,
        "n_trades": len(df),
        "win_rate": win_rate,
        "pf": pf,
        "net_pnl": net_pnl_all,
        "max_dd": max_dd,
        "worst_loss": df["net_pnl"].min(),
        "mean_mae": mean_mae,
        "mean_mfe": mean_mfe,
        "mean_basis_to_ext": mean_basis_to_ext,
        "mean_ext_to_ext": mean_ext_to_ext,
        "year_stats": year_stats,
        "slope_stats": slope_stats,
        "boot_mean": boot["mean"],
        "boot_ci_lower": boot["ci_lower"],
        "boot_ci_upper": boot["ci_upper"],
        "boot_p_val": boot["p_val"]
    }

def run_analysis():
    cells = [
        "A_rr_0_5_target_0.25",
        "A_rr_0_5_target_0.5",
        "B_stop_2_5_target_0.25",
        "B_stop_2_5_target_0.5"
    ]
    
    results = []
    for cell in cells:
        print(f"Analyzing combined trades for: {cell}...")
        res = analyze_cell(cell)
        if res:
            results.append(res)
            
    if not results:
        print("No trades analyzed. Make sure run_keltner_all_years.py has finished successfully.")
        return

    # Write report
    report_lines = []
    report_lines.append("# Consolidated Multi-Year Keltner Channel extension fade report (2020-2026)\n")
    report_lines.append("## 1. Executive Summary (RTH Only, Net of $10 Friction)")
    report_lines.append("| Cell | Trades | Win Rate | Profit Factor | Net PnL ($) | Max DD ($) | Mean Basis-to-Ext (pts) | Mean Ext-to-Ext (pts) | Bootstrap 95% CI ($/tr) |")
    report_lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    for r in results:
        cell = r["cell"]
        n = r["n_trades"]
        wr = f"{r['win_rate']:.1f}%"
        pf = f"{r['pf']:.2f}"
        pnl = f"${r['net_pnl']:+,.2f}"
        mdd = f"${r['max_dd']:,.2f}"
        b2e = f"{r['mean_basis_to_ext']:.2f}"
        e2e = f"{r['mean_ext_to_ext']:.2f}"
        ci = f"[${r['boot_ci_lower']:.2f}, ${r['boot_ci_upper']:.2f}]"
        report_lines.append(f"| {cell:<22} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {mdd:<10} | {b2e:<23} | {e2e:<21} | {ci:<20} |")

    report_lines.append("\n## 2. Year-by-Year Performance Breakdown")
    for r in results:
        report_lines.append(f"\n### Cell: {r['cell']}")
        report_lines.append("| Year | Trades | Win Rate | Profit Factor | Net PnL ($) |")
        report_lines.append("| :--- | :---: | :---: | :---: | :---: |")
        for yr in sorted(r["year_stats"].keys()):
            s = r["year_stats"][yr]
            pnl_val = f"${s['net_pnl']:+,.2f}"
            report_lines.append(f"| {yr:<4} | {s['n']:<6} | {s['win_rate']:.1f}% | {s['pf']:.2f} | {pnl_val:<11} |")

    report_lines.append("\n## 3. Normalized Slope-relative Performance Gating")
    report_lines.append("The Keltner slope is normalized in ATR units per 3m bar at trade entry. We align the slope with the trade's direction (relative slope = slope * direction):\n")
    report_lines.append("*   **Trend Continuation:** The channel is sloping away from the entry, suggesting strong trending momentum in the breakout direction.")
    report_lines.append("*   **Mean Reverting:** The channel is sloping towards the entry, suggesting potential exhaustion or deceleration.")
    report_lines.append("*   **Flat:** The channel is horizontally stable.\n")
    
    for r in results:
        report_lines.append(f"\n### Cell: {r['cell']}")
        report_lines.append("| Slope Gating Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) |")
        report_lines.append("| :--- | :---: | :---: | :---: | :---: |")
        for sb in sorted(r["slope_stats"].keys()):
            s = r["slope_stats"][sb]
            pnl_val = f"${s['net_pnl']:+,.2f}"
            report_lines.append(f"| {sb:<25} | {s['n']:<6} | {s['win_rate']:.1f}% | {s['pf']:.2f} | {pnl_val:<11} |")

    # Save Markdown report
    results_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results_all_years"
    report_path = results_dir / "consolidated_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
        
    print(f"\nConsolidated Markdown report written to {report_path}")
    
    # Save JSON report
    with open(results_dir / "consolidated_report.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_analysis()

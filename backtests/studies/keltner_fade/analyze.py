"""Analysis and bootstrap reporting script for Keltner Extension Fade Study."""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B_ITER = 10000
SEED = 42


def analyze_cell(cell_dir: Path, cell_info: dict) -> dict:
    trades_file = cell_dir / "trades.parquet"
    if not trades_file.exists():
        return {}

    df = pd.read_parquet(trades_file)
    if len(df) == 0:
        return {}

    # Chronological sort by exit
    df = df.sort_values("exit_ts").reset_index(drop=True)
    df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ns")
    df["date"] = df["exit_dt"].dt.date

    cum_pnl = df["net_pnl"].cumsum()
    peaks = cum_pnl.cummax()
    dds = peaks - cum_pnl
    max_dd = dds.max()

    # Rolling 1m (30 days) and 4m (120 days) max drawdowns
    s_dds = pd.Series(dds.values, index=df["exit_dt"])
    rolling_1m_dd = s_dds.rolling("30D").max().max()
    rolling_4m_dd = s_dds.rolling("120D").max().max()

    # Steamroller metrics
    net_pnl_all = df["net_pnl"].sum()
    
    # 1. Drop worst 1% of trades (largest losses)
    n_drop_worst = max(1, int(len(df) * 0.01))
    df_sorted_worst = df.sort_values("net_pnl", ascending=True)
    net_pnl_no_worst = df_sorted_worst.iloc[n_drop_worst:]["net_pnl"].sum()
    worst_pnl_impact = net_pnl_all - net_pnl_no_worst  # negative number
    
    # 2. Drop best 1% of trades (largest gains)
    n_drop_best = max(1, int(len(df) * 0.01))
    df_sorted_best = df.sort_values("net_pnl", ascending=False)
    net_pnl_no_best = df_sorted_best.iloc[n_drop_best:]["net_pnl"].sum()
    best_pnl_impact = net_pnl_all - net_pnl_no_best   # positive number

    # Win rate and profit factor
    wins = df[df["net_pnl"] > 0]["net_pnl"].sum()
    losses = abs(df[df["net_pnl"] < 0]["net_pnl"].sum())
    pf = wins / losses if losses > 0 else float("inf")
    win_rate = (df["net_pnl"] > 0).mean() * 100

    # Excursions
    mean_mae = df["mae_atr"].mean()
    mean_mfe = df["mfe_atr"].mean()
    max_mae = df["mae_atr"].max()

    # Regime-type classification (trending vs ranging)
    # Trending = bars_in_regime_at_entry >= 15 bars (7.5 min in same direction)
    # Ranging = bars_in_regime_at_entry < 15 bars
    df["regime_type"] = np.where(df["bars_in_regime_at_entry"] >= 15, "Trending", "Ranging")
    
    regime_stats = {}
    for r_type, grp in df.groupby("regime_type"):
        r_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        r_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        r_pf = r_wins / r_losses if r_losses > 0 else float("inf")
        regime_stats[r_type] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": r_pf,
            "worst_loss": grp["net_pnl"].min(),
            "mean_mae": grp["mae_atr"].mean()
        }

    # Session split (RTH vs ETH)
    session_stats = {}
    for s_type, grp in df.groupby("session"):
        s_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        s_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        s_pf = s_wins / s_losses if s_losses > 0 else float("inf")
        session_stats[s_type] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": s_pf,
            "worst_loss": grp["net_pnl"].min(),
            "mean_mae": grp["mae_atr"].mean()
        }

    # Channel width split (Narrow vs Medium vs Wide)
    df["width_bucket"] = np.where(df["atr_at_entry"] <= 15.0, "Narrow (<=15)", 
                                  np.where(df["atr_at_entry"] <= 30.0, "Medium (15-30)", "Wide (>30)"))
    width_stats = {}
    for w_type, grp in df.groupby("width_bucket"):
        w_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        w_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        w_pf = w_wins / w_losses if w_losses > 0 else float("inf")
        width_stats[w_type] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": w_pf,
            "worst_loss": grp["net_pnl"].min(),
            "mean_mae": grp["mae_atr"].mean()
        }

    # Time of day split
    df["entry_dt_ct"] = pd.to_datetime(df["entry_ts"], unit="ns").dt.tz_localize("UTC").dt.tz_convert("America/Chicago")
    df["entry_minute_of_day"] = df["entry_dt_ct"].dt.hour * 60 + df["entry_dt_ct"].dt.minute
    df["time_of_day_bucket"] = np.where(df["session"] == "ETH", "ETH",
                                        np.where(df["entry_minute_of_day"] < 630, "Morning (8:30-10:30 CT)",
                                                 np.where(df["entry_minute_of_day"] < 810, "Midday (10:30-13:30 CT)",
                                                          "Afternoon (13:30-15:00 CT)")))
    time_of_day_stats = {}
    for t_bucket, grp in df.groupby("time_of_day_bucket"):
        t_wins = grp[grp["net_pnl"] > 0]["net_pnl"].sum()
        t_losses = abs(grp[grp["net_pnl"] < 0]["net_pnl"].sum())
        t_pf = t_wins / t_losses if t_losses > 0 else float("inf")
        time_of_day_stats[t_bucket] = {
            "n": len(grp),
            "net_pnl": grp["net_pnl"].sum(),
            "win_rate": (grp["net_pnl"] > 0).mean() * 100,
            "pf": t_pf,
            "worst_loss": grp["net_pnl"].min(),
            "mean_mae": grp["mae_atr"].mean()
        }

    return {
        "n_trades": len(df),
        "win_rate": win_rate,
        "pf": pf,
        "net_pnl": net_pnl_all,
        "worst_loss": df["net_pnl"].min(),
        "max_dd": max_dd,
        "rolling_1m_dd": rolling_1m_dd,
        "rolling_4m_dd": rolling_4m_dd,
        "net_pnl_no_worst_1pct": net_pnl_no_worst,
        "worst_1pct_dropped_net_change": worst_pnl_impact,
        "net_pnl_no_best_1pct": net_pnl_no_best,
        "best_1pct_dropped_net_change": best_pnl_impact,
        "mean_mae": mean_mae,
        "mean_mfe": mean_mfe,
        "max_mae": max_mae,
        "regime_stats": regime_stats,
        "session_stats": session_stats,
        "width_stats": width_stats,
        "time_of_day_stats": time_of_day_stats,
        "df": df  # Return dataframe for bootstrapping
    }


def bootstrap_cell(df: pd.DataFrame) -> dict:
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


def run_analysis():
    results_dir = PROJECT_ROOT / "studies" / "keltner_fade" / "results"
    summary_path = results_dir / "summary.json"
    if not summary_path.exists():
        print(f"Error: Summary file {summary_path} not found.")
        sys.exit(1)
        
    with open(summary_path, "r") as f:
        summary_rows = json.load(f)
        
    analysis_results = []
    
    for cell in summary_rows:
        cell_name = cell["cell"]
        print(f"Analyzing cell: {cell_name}...")
        cell_dir = results_dir / cell_name
        
        metrics = analyze_cell(cell_dir, cell)
        if not metrics:
            print(f"  No trades found for {cell_name}.")
            continue
            
        boot = bootstrap_cell(metrics["df"])
        
        # Assemble summary row
        row = {
            "cell": cell_name,
            "variant": cell["variant"],
            "stop": cell["stop"],
            "target": cell["target"],
            "n_trades": metrics["n_trades"],
            "win_rate": metrics["win_rate"],
            "pf": metrics["pf"],
            "net_pnl": metrics["net_pnl"],
            "worst_loss": metrics["worst_loss"],
            "max_dd": metrics["max_dd"],
            "rolling_1m_dd": metrics["rolling_1m_dd"],
            "rolling_4m_dd": metrics["rolling_4m_dd"],
            "worst_1pct_pnl_impact": metrics["worst_1pct_dropped_net_change"],
            "best_1pct_pnl_impact": metrics["best_1pct_dropped_net_change"],
            "mean_mae": metrics["mean_mae"],
            "mean_mfe": metrics["mean_mfe"],
            "max_mae": metrics["max_mae"],
            "boot_mean": boot["mean"],
            "boot_ci_lower": boot["ci_lower"],
            "boot_ci_upper": boot["ci_upper"],
            "boot_p_val": boot["p_val"],
            "regime_stats": metrics["regime_stats"],
            "session_stats": metrics["session_stats"],
            "width_stats": metrics["width_stats"],
            "time_of_day_stats": metrics["time_of_day_stats"]
        }
        analysis_results.append(row)
        
        print(f"  Trades: {row['n_trades']} | Net PnL: ${row['net_pnl']:+.2f} | Win Rate: {row['win_rate']:.1f}% | PF: {row['pf']:.2f}")
        print(f"  Bootstrap Mean PnL/Trade: ${row['boot_mean']:.2f} | 95% CI: [${row['boot_ci_lower']:.2f}, ${row['boot_ci_upper']:.2f}]")
        print(f"  Worst Loss: ${row['worst_loss']:.2f} | Max DD: ${row['max_dd']:.2f}")
        print(f"  Worst 1% PnL Impact: ${row['worst_1pct_pnl_impact']:.2f} | Best 1% PnL Impact: ${row['best_1pct_pnl_impact']:.2f}")
        
    # Write full analysis report to file
    with open(results_dir / "analysis_report.json", "w") as f:
        json.dump(analysis_results, f, indent=2, default=str)
        
    # Generate Markdown output tables
    generate_markdown_summary(analysis_results)


def generate_markdown_summary(results: list[dict]):
    lines = []
    lines.append("# Keltner Extension Fade Study Summary Parity Report")
    lines.append("\n## Executive Grid Summary (Year 2025)")
    lines.append("| Cell | Variant | Stop (RR or ATR) | Target (ATR) | Trades | Win Rate | Profit Factor | Net PnL ($) | Max DD ($) | Bootstrap 95% CI ($) |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        cell = r["cell"]
        var = r["variant"]
        stop = f"{r['stop']:.4f}" if r["stop"] < 1.0 else f"{r['stop']:.2f}"
        tgt = f"{r['target']:.2f}"
        n = r["n_trades"]
        wr = f"{r['win_rate']:.1f}%"
        pf = f"{r['pf']:.2f}" if r["pf"] != float("inf") else "inf"
        pnl = f"${r['net_pnl']:+,.2f}"
        mdd = f"${r['max_dd']:.2f}"
        ci = f"[${r['boot_ci_lower']:.2f}, ${r['boot_ci_upper']:.2f}]"
        lines.append(f"| {cell:<25} | {var:<7} | {stop:<16} | {tgt:<12} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {mdd:<10} | {ci:<20} |")

    lines.append("\n## Tail Risk Instrumentation (Steamroller Check)")
    lines.append("| Cell | Worst Loss ($) | Worst 1% Impact ($) | Best 1% Impact ($) | Max DD ($) | Rolling 1M DD ($) | Rolling 4M DD ($) | Mean MAE (ATR) | Max MAE (ATR) |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        cell = r["cell"]
        wl = f"${r['worst_loss']:.2f}"
        w1i = f"${r['worst_1pct_pnl_impact']:.2f}"
        b1i = f"${r['best_1pct_pnl_impact']:.2f}"
        mdd = f"${r['max_dd']:.2f}"
        r1m = f"${r['rolling_1m_dd']:.2f}"
        r4m = f"${r['rolling_4m_dd']:.2f}"
        mae = f"{r['mean_mae']:.2f}"
        max_mae = f"{r['max_mae']:.2f}"
        lines.append(f"| {cell:<25} | {wl:<14} | {w1i:<19} | {b1i:<18} | {mdd:<10} | {r1m:<17} | {r4m:<17} | {mae:<14} | {max_mae:<14} |")

    lines.append("\n## Session Stratification (RTH vs. ETH)")
    for r in results:
        lines.append(f"\n### Cell: {r['cell']}")
        lines.append("| Session | Trades | Win Rate | Profit Factor | Net PnL ($) | Worst Loss ($) | Mean MAE (ATR) |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for sess, s in r["session_stats"].items():
            n = s["n"]
            wr = f"{s['win_rate']:.1f}%"
            pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
            pnl = f"${s['net_pnl']:+,.2f}"
            wl = f"${s['worst_loss']:.2f}"
            mae = f"{s['mean_mae']:.2f}"
            lines.append(f"| {sess:<7} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {wl:<14} | {mae:<14} |")

    lines.append("\n## Channel Width Stratification (3x ATR at Entry)")
    for r in results:
        lines.append(f"\n### Cell: {r['cell']}")
        lines.append("| Width Bucket (ATR) | Trades | Win Rate | Profit Factor | Net PnL ($) | Worst Loss ($) | Mean MAE (ATR) |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for wb, s in r["width_stats"].items():
            n = s["n"]
            wr = f"{s['win_rate']:.1f}%"
            pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
            pnl = f"${s['net_pnl']:+,.2f}"
            wl = f"${s['worst_loss']:.2f}"
            mae = f"{s['mean_mae']:.2f}"
            lines.append(f"| {wb:<18} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {wl:<14} | {mae:<14} |")

    lines.append("\n## Time-of-Day Stratification (Chicago Time)")
    for r in results:
        lines.append(f"\n### Cell: {r['cell']}")
        lines.append("| Time Bucket | Trades | Win Rate | Profit Factor | Net PnL ($) | Worst Loss ($) | Mean MAE (ATR) |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for tb, s in r["time_of_day_stats"].items():
            n = s["n"]
            wr = f"{s['win_rate']:.1f}%"
            pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
            pnl = f"${s['net_pnl']:+,.2f}"
            wl = f"${s['worst_loss']:.2f}"
            mae = f"{s['mean_mae']:.2f}"
            lines.append(f"| {tb:<25} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {wl:<14} | {mae:<14} |")

    lines.append("\n## Regime-Type Stratification (Trending vs. Ranging)")
    for r in results:
        lines.append(f"\n### Cell: {r['cell']}")
        lines.append("| Regime Type | Trades | Win Rate | Profit Factor | Net PnL ($) | Worst Loss ($) | Mean MAE (ATR) |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for reg, s in r["regime_stats"].items():
            n = s["n"]
            wr = f"{s['win_rate']:.1f}%"
            pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
            pnl = f"${s['net_pnl']:+,.2f}"
            wl = f"${s['worst_loss']:.2f}"
            mae = f"{s['mean_mae']:.2f}"
            lines.append(f"| {reg:<11} | {n:<6} | {wr:<8} | {pf:<13} | {pnl:<11} | {wl:<14} | {mae:<14} |")

    report_path = PROJECT_ROOT / "studies" / "keltner_fade" / "results" / "report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Markdown report summary written to {report_path}")


if __name__ == "__main__":
    run_analysis()

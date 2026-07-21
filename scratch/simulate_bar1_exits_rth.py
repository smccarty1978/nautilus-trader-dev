import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(p, columns=["high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars

@njit
def simulate_single_trade_path(idx_start, idx_end, px_entry, atr, d, ts_start, ts_1s, high_1s, low_1s, close_1s,
                               pt_atr, sl_atr, gate_time_s, gate_pnl_thresh):
    pt_px = px_entry + d * pt_atr * atr
    sl_px = px_entry - d * sl_atr * atr
    pt_px_rounded = round(pt_px * 4) / 4
    sl_px_rounded = round(sl_px * 4) / 4
    
    exit_px = np.nan
    exit_reason = 0
    
    for j in range(idx_start, idx_end + 1):
        ts = ts_1s[j]
        h, l = high_1s[j], low_1s[j]
        c = close_1s[j]
        dt = ts - ts_start
        
        if (d == 1 and l <= sl_px_rounded) or (d == -1 and h >= sl_px_rounded):
            exit_px = sl_px_rounded
            exit_reason = 2
            break
        if (d == 1 and h >= pt_px_rounded) or (d == -1 and l <= pt_px_rounded):
            exit_px = pt_px_rounded
            exit_reason = 1
            break
        if gate_time_s > 0 and dt >= gate_time_s * 1_000_000_000:
            pnl_gate_atr = (c - px_entry) * d / atr
            if pnl_gate_atr < gate_pnl_thresh:
                exit_px = c
                exit_reason = 3
                break
                
    if np.isnan(exit_px):
        exit_px = close_1s[idx_end]
        exit_reason = 4
        
    return exit_px, exit_reason

def run_simulation_sweep(df_bar1, pt_atr, sl_atr, gate_time_s, gate_pnl_thresh):
    all_years_results = []
    
    for y in sorted(df_bar1["year"].unique()):
        year_cohort = df_bar1[df_bar1["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        try:
            bars = load_1s(y)
        except Exception:
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        idx_entry_arr = np.searchsorted(ts_1s, year_cohort["entry_ts_bar1"].to_numpy(np.int64), side="left")
        idx_exit_arr = np.searchsorted(ts_1s, year_cohort["exit_ts"].to_numpy(np.int64), side="right") - 1
        
        px_entry_arr = year_cohort["entry_px_bar1"].to_numpy(np.float64)
        atr_arr = year_cohort["entry_atr"].to_numpy(np.float64)
        dir_arr = year_cohort["signal_direction"].to_numpy(np.int64)
        ts_start_arr = year_cohort["entry_ts_bar1"].to_numpy(np.int64)
        
        N = len(year_cohort)
        exit_px_arr = np.full(N, np.nan)
        exit_reason_arr = np.zeros(N, dtype=np.int32)
        
        for i in range(N):
            idx_start = idx_entry_arr[i]
            idx_end = idx_exit_arr[i]
            if idx_start >= len(ts_1s) or idx_end >= len(ts_1s) or idx_start > idx_end:
                continue
            exit_px_arr[i], exit_reason_arr[i] = simulate_single_trade_path(
                idx_start, idx_end, px_entry_arr[i], atr_arr[i], dir_arr[i], ts_start_arr[i],
                ts_1s, h_1s, l_1s, c_1s, pt_atr, sl_atr, gate_time_s, gate_pnl_thresh
            )
            
        year_cohort["sim_exit_px"] = exit_px_arr
        year_cohort["sim_exit_reason"] = exit_reason_arr
        all_years_results.append(year_cohort)
        
    df_sim = pd.concat(all_years_results, ignore_index=True)
    df_sim = df_sim.dropna(subset=["sim_exit_px"])
    
    df_sim["gross_pnl_pts"] = (df_sim["sim_exit_px"] - df_sim["entry_px_bar1"]) * df_sim["signal_direction"]
    df_sim["gross_pnl_usd"] = df_sim["gross_pnl_pts"] * 20.0
    df_sim["net_pnl_usd"] = df_sim["gross_pnl_usd"] - 10.0
    
    return df_sim

def evaluate_metrics(df_sim):
    n_trades = len(df_sim)
    if n_trades == 0:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        
    g_wr = (df_sim["gross_pnl_usd"] > 0).mean() * 100
    g_wins = df_sim[df_sim["gross_pnl_usd"] > 0]["gross_pnl_usd"].sum()
    g_losses = abs(df_sim[df_sim["gross_pnl_usd"] < 0]["gross_pnl_usd"].sum())
    g_pf = g_wins / g_losses if g_losses > 0 else float("inf")
    g_pnl = df_sim["gross_pnl_usd"].sum()
    g_ev = g_pnl / n_trades
    
    n_wr = (df_sim["net_pnl_usd"] > 0).mean() * 100
    n_wins = df_sim[df_sim["net_pnl_usd"] > 0]["net_pnl_usd"].sum()
    n_losses = abs(df_sim[df_sim["net_pnl_usd"] < 0]["net_pnl_usd"].sum())
    n_pf = n_wins / n_losses if n_losses > 0 else float("inf")
    n_pnl = df_sim["net_pnl_usd"].sum()
    n_ev = n_pnl / n_trades
    
    reasons = df_sim["sim_exit_reason"].value_counts(normalize=True) * 100
    pt_share = reasons.get(1, 0.0)
    sl_share = reasons.get(2, 0.0)
    gate_share = reasons.get(3, 0.0)
    flip_share = reasons.get(4, 0.0)
    
    return n_trades, g_wr, g_pf, g_pnl, g_ev, n_wr, n_pf, n_pnl, n_ev, pt_share, sl_share, gate_share, flip_share

def main():
    t0 = time.time()
    re_path = "studies/regime_classification/results/flips_excursion_paths.parquet"
    df_all = pd.read_parquet(re_path)
    df_bar1 = df_all[df_all["bar1_confirm"]].copy()
    df_bar1["entry_ts_bar1"] = df_bar1["entry_ts"] + 60 * 1_000_000_000
    
    # Filter for RTH-only entries:
    # 8:30 AM to 3:00 PM Chicago Time (America/Chicago)
    df_bar1["dt"] = pd.to_datetime(df_bar1["entry_ts_bar1"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    df_bar1["minute"] = df_bar1["dt"].dt.hour * 60 + df_bar1["dt"].dt.minute
    df_rth = df_bar1[(df_bar1["minute"] >= 510) & (df_bar1["minute"] < 900)].copy()
    
    print(f"Loaded {len(df_bar1):,} bar1-confirmed trades total.")
    print(f"Filtered to {len(df_rth):,} RTH-only bar1-confirmed trades.")
    
    combinations = [
        # Baseline (No Gate)
        (2.0, 1.5, 0, 0.0, "No Gate"),
        (1.5, 0.75, 0, 0.0, "No Gate"),
        (2.0, 0.75, 0, 0.0, "No Gate"),
        # With 60s Gates
        (1.5, 0.75, 60, 0.1, "60s PnL >= +0.10 ATR"),
        (1.5, 0.75, 60, 0.2, "60s PnL >= +0.20 ATR"),
        (2.0, 0.75, 60, 0.1, "60s PnL >= +0.10 ATR"),
        (2.0, 0.75, 60, 0.2, "60s PnL >= +0.20 ATR"),
        (2.0, 0.75, 60, 0.3, "60s PnL >= +0.30 ATR"),
        (2.0, 1.0, 60, 0.1, "60s PnL >= +0.10 ATR"),
        (2.0, 1.0, 60, 0.2, "60s PnL >= +0.20 ATR"),
        (2.5, 1.0, 60, 0.2, "60s PnL >= +0.20 ATR"),
    ]
    
    print("\n" + "="*145)
    print("  RTH-ONLY SIMULATION SWEEP: GROSS VS NET ANALYSIS FOR BAR1-CONFIRMED REGIME FLIPS (2020-2026)")
    print("="*145)
    print("| PT | SL | Gate Policy | Trades | Gross WR% | Gross PF | Gross EV | Net WR% | Net PF | Net PnL ($) | Net EV | PT% | SL% | Gate% | Flip% |")
    print("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    results = []
    for pt, sl, gt, g_thresh, g_label in combinations:
        df_sim = run_simulation_sweep(df_rth, pt, sl, gt, g_thresh)
        n, g_wr, g_pf, g_pnl, g_ev, n_wr, n_pf, n_pnl, n_ev, pt_pct, sl_pct, g_pct, f_pct = evaluate_metrics(df_sim)
        print(f"| {pt:.1f} | {sl:.2f} | {g_label:<22} | {n:<6,} | {g_wr:>8.1f}% | {g_pf:>8.2f} | {g_ev:>8.2f} | {n_wr:>6.1f}% | {n_pf:>6.2f} | {n_pnl:>+11,.2f} | {n_ev:>6.2f} | {pt_pct:>4.1f}% | {sl_pct:>4.1f}% | {g_pct:>4.1f}% | {f_pct:>4.1f}% |")
        
        results.append({
            "pt": pt, "sl": sl, "gt": gt, "g_thresh": g_thresh, "label": g_label,
            "df": df_sim, "net_pnl": n_pnl, "pf": n_pf, "ev": n_ev
        })

    # Find best candidate and print its yearly breakdown
    best = max(results, key=lambda x: x["net_pnl"])
    print("\n" + "="*95)
    print(f"  YEARLY BREAKDOWN FOR BEST SETUP (NET, RTH-ONLY): PT={best['pt']} / SL={best['sl']} / {best['label']}")
    print("="*95)
    print("| Year | Trades | Gross WR% | Gross PF | Gross EV ($) | Net WR% | Net PF | Net PnL ($) | Net EV ($) |")
    print("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    
    df_best = best["df"]
    for yr, grp in df_best.groupby("year"):
        y_n, y_g_wr, y_g_pf, _, y_g_ev, y_n_wr, y_n_pf, y_n_pnl, y_n_ev, _, _, _, _ = evaluate_metrics(grp)
        print(f"| {int(yr)} | {y_n:<6,} | {y_g_wr:>8.1f}% | {y_g_pf:>8.2f} | {y_g_ev:>12.2f} | {y_n_wr:>6.1f}% | {y_n_pf:>6.2f} | {y_n_pnl:>+11,.2f} | {y_n_ev:>10.2f} |")
        
    print(f"\n[done] Total elapsed: {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()

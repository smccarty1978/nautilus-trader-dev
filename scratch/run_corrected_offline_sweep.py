import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

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
            parts.append(pd.read_parquet(p, columns=["high", "low", "close", "open"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars

def main():
    t_start = time.time()
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df_trades = pd.read_parquet(ds_path)
    print(f"Loaded {len(df_trades):,} trades for study.")
    
    years = sorted(df_trades["year"].unique())
    bars_1m_cache = {}
    
    # Load and resample 1m bars for each year
    for y in years:
        print(f"Loading and computing indicators for year {y}...")
        try:
            bars_1s = load_1s(y)
        except Exception as e:
            print(f"  Failed to load 1s bars for {y}: {e}")
            continue
            
        df_1m = pd.DataFrame()
        df_1m["open"] = bars_1s["open"].resample("1Min").first()
        df_1m["high"] = bars_1s["high"].resample("1Min").max()
        df_1m["low"] = bars_1s["low"].resample("1Min").min()
        df_1m["close"] = bars_1s["close"].resample("1Min").last()
        df_1m = df_1m.dropna()
        
        # Compute MAs
        df_1m["sma9"] = df_1m["close"].rolling(9).mean()
        df_1m["sma13"] = df_1m["close"].rolling(13).mean()
        df_1m["sma21"] = df_1m["close"].rolling(21).mean()
        df_1m["ema9"] = df_1m["close"].ewm(span=9, adjust=False).mean()
        df_1m["ema13"] = df_1m["close"].ewm(span=13, adjust=False).mean()
        df_1m["ema21"] = df_1m["close"].ewm(span=21, adjust=False).mean()
        
        bars_1m_cache[y] = df_1m

    # Pre-parse indices for each trade to speed up inner loops
    trade_meta = {}
    for y in years:
        if y not in bars_1m_cache:
            continue
        df_1m = bars_1m_cache[y]
        ts_1m = df_1m.index.values.astype("int64")
        
        y_trades = df_trades[df_trades["year"] == y].copy()
        parsed_trades = []
        
        for _, row in y_trades.iterrows():
            entry_ts = int(row["entry_ts_bar1"])
            exit_ts = int(row["exit_ts"])
            entry_px = float(row["entry_px_bar1"])
            atr = float(row["entry_atr"])
            d = int(row["signal_direction"])
            
            idx_entry = np.searchsorted(ts_1m, entry_ts, side="left")
            idx_exit = np.searchsorted(ts_1m, exit_ts, side="right") - 1
            
            if idx_entry >= len(ts_1m) or idx_exit >= len(ts_1m) or idx_entry > idx_exit:
                continue
                
            cat_idx = max(0, idx_entry - 1)
            catastrophic_stop = float(df_1m["open"].values[cat_idx])
            
            parsed_trades.append({
                "idx_entry": idx_entry,
                "idx_exit": idx_exit,
                "entry_px": entry_px,
                "atr": atr,
                "d": d,
                "catastrophic_stop": catastrophic_stop
            })
            
        trade_meta[y] = parsed_trades

    # Sweep parameters
    activation_gates = [0.0, 0.5, 1.0]
    stall_counts = [2, 3, 4, 5]
    ma_rules = ["sma9", "sma13", "sma21", "ema9", "ema13", "ema21"]
    sides = ["both", "long", "short"]
    
    results = []
    
    print("\nRunning sweep matrix (216 combinations)...")
    
    for G in activation_gates:
        for S in stall_counts:
            for ma_rule in ma_rules:
                for side in sides:
                    total_trades = 0
                    exit_pnls = []
                    stop_hits = []
                    
                    for y in years:
                        if y not in bars_1m_cache or y not in trade_meta:
                            continue
                            
                        df_1m = bars_1m_cache[y]
                        high_arr = df_1m["high"].to_numpy()
                        low_arr = df_1m["low"].to_numpy()
                        close_arr = df_1m["close"].to_numpy()
                        ma_arr = df_1m[ma_rule].to_numpy()
                        
                        trades = trade_meta[y]
                        
                        for t in trades:
                            d = t["d"]
                            if side == "long" and d != 1:
                                continue
                            if side == "short" and d != -1:
                                continue
                                
                            idx_entry = t["idx_entry"]
                            idx_exit = t["idx_exit"]
                            entry_px = t["entry_px"]
                            atr = t["atr"]
                            active_stop = t["catastrophic_stop"]
                            
                            is_crossed_at_entry = False
                            if d == 1 and entry_px <= active_stop:
                                is_crossed_at_entry = True
                            elif d == -1 and entry_px >= active_stop:
                                is_crossed_at_entry = True
                                
                            milestone_reached = False
                            stall_count = 0
                            is_stopped = False
                            exit_px = close_arr[idx_exit]
                            running_mfe = 0.0
                            
                            # Causal loop starting at idx_entry (loop_offset=0)
                            for j in range(idx_entry, idx_exit + 1):
                                h = high_arr[j]
                                l = low_arr[j]
                                c = close_arr[j]
                                
                                # Causal stop check
                                if d == 1 and l <= active_stop:
                                    is_stopped = True
                                    if is_crossed_at_entry:
                                        exit_px = entry_px
                                    else:
                                        exit_px = active_stop
                                    break
                                elif d == -1 and h >= active_stop:
                                    is_stopped = True
                                    if is_crossed_at_entry:
                                        exit_px = entry_px
                                    else:
                                        exit_px = active_stop
                                    break
                                    
                                # MFE tracking
                                if d == 1:
                                    mfe_bar = (h - entry_px) / atr
                                else:
                                    mfe_bar = (entry_px - l) / atr
                                running_mfe = max(running_mfe, mfe_bar)
                                
                                # Check milestone gate
                                if not milestone_reached:
                                    if running_mfe >= G:
                                        milestone_reached = True
                                        
                                # Track stall and ratchet stops
                                if milestone_reached:
                                    prev_high = high_arr[j - 1]
                                    prev_low = low_arr[j - 1]
                                    
                                    if d == 1:
                                        if h > prev_high:
                                            stall_count = 0
                                        else:
                                            stall_count += 1
                                    else:
                                        if l < prev_low:
                                            stall_count = 0
                                        else:
                                            stall_count += 1
                                            
                                    if stall_count >= S:
                                        ma_val = ma_arr[j]
                                        if not np.isnan(ma_val):
                                            if d == 1:
                                                if ma_val >= c:
                                                    is_stopped = True
                                                    exit_px = c
                                                    break
                                                active_stop = max(active_stop, ma_val)
                                            else:
                                                if ma_val <= c:
                                                    is_stopped = True
                                                    exit_px = c
                                                    break
                                                active_stop = min(active_stop, ma_val)
                                                
                            trade_exit_pnl = ((exit_px - entry_px) * d / atr)
                            exit_pnls.append(trade_exit_pnl)
                            stop_hits.append(is_stopped)
                            total_trades += 1
                            
                    if total_trades == 0:
                        continue
                        
                    df_res = pd.DataFrame({
                        "exit_pnl_atr": exit_pnls,
                        "stop_hit": stop_hits
                    })
                    
                    mean_pnl = df_res["exit_pnl_atr"].mean()
                    stop_freq = df_res["stop_hit"].mean() * 100.0
                    
                    # Compute PF
                    # We assume entry_atr avg is ~20 for USD conversions (for PF calculations)
                    df_res["gross_usd"] = df_res["exit_pnl_atr"] * 20.0 * 20.0
                    df_res["net_usd"] = df_res["gross_usd"] - 10.0
                    
                    g_wins = df_res[df_res["gross_usd"] > 0]["gross_usd"].sum()
                    g_losses = abs(df_res[df_res["gross_usd"] < 0]["gross_usd"].sum())
                    gross_pf = g_wins / g_losses if g_losses > 0 else float("inf")
                    
                    n_wins = df_res[df_res["net_usd"] > 0]["net_usd"].sum()
                    n_losses = abs(df_res[df_res["net_usd"] < 0]["net_usd"].sum())
                    net_pf = n_wins / n_losses if n_losses > 0 else float("inf")
                    
                    results.append({
                        "G": G,
                        "S": S,
                        "ma_rule": ma_rule,
                        "side": side,
                        "total_trades": total_trades,
                        "mean_pnl_atr": mean_pnl,
                        "stop_freq": stop_freq,
                        "gross_pf": gross_pf,
                        "net_pf": net_pf
                    })
                    
    df_sweep = pd.DataFrame(results)
    
    # Sort by mean_pnl_atr descending
    df_sweep = df_sweep.sort_values(by="mean_pnl_atr", ascending=False)
    
    # Save sweep results to CSV
    csv_path = "scratch/corrected_offline_sweep_results.csv"
    df_sweep.to_csv(csv_path, index=False)
    print(f"\nSaved sweep results to {csv_path}")
    
    # Print top 15 results
    print("\n" + "="*80)
    print("  TOP 15 SWEEP RESULTS (CORRECTED OFFLINE)")
    print("="*80)
    print(df_sweep.head(15).to_string(index=False))
    
    # Print long-only best
    print("\n" + "="*80)
    print("  TOP 5 LONG-ONLY SWEEP RESULTS")
    print("="*80)
    print(df_sweep[df_sweep["side"] == "long"].head(5).to_string(index=False))
    
    # Print short-only best
    print("\n" + "="*80)
    print("  TOP 5 SHORT-ONLY SWEEP RESULTS")
    print("="*80)
    print(df_sweep[df_sweep["side"] == "short"].head(5).to_string(index=False))
    
    print(f"\nExecution time: {(time.time() - t_start):.1f}s")

if __name__ == "__main__":
    main()

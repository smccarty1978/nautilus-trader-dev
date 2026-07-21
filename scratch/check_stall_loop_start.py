import os, sys
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
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df_trades = pd.read_parquet(ds_path)
    print(f"Loaded {len(df_trades):,} trades for study.")
    
    years = sorted(df_trades["year"].unique())
    bars_1m_cache = {}
    
    for y in years:
        try:
            bars_1s = load_1s(y)
        except Exception as e:
            print(f"Failed to load 1s bars for {y}: {e}")
            continue
            
        df_1m = pd.DataFrame()
        df_1m["open"] = bars_1s["open"].resample("1Min").first()
        df_1m["high"] = bars_1s["high"].resample("1Min").max()
        df_1m["low"] = bars_1s["low"].resample("1Min").min()
        df_1m["close"] = bars_1s["close"].resample("1Min").last()
        df_1m = df_1m.dropna()
        
        df_1m["sma9"] = df_1m["close"].rolling(9).mean()
        bars_1m_cache[y] = df_1m

    G = 0.5
    S = 3
    
    # We will test:
    # 1. loop_start = idx_entry + 1 (original offline study behavior)
    # 2. loop_start = idx_entry     (correct causal behavior)
    
    for corrected in [False, True]:
        for loop_start_offset in [1, 0]:
            all_results = []
            total_trades = 0
            
            for y in years:
                if y not in bars_1m_cache:
                    continue
                df_1m = bars_1m_cache[y]
                ts_1m = df_1m.index.values.astype("int64")
                
                high_arr = df_1m["high"].to_numpy()
                low_arr = df_1m["low"].to_numpy()
                close_arr = df_1m["close"].to_numpy()
                open_arr = df_1m["open"].to_numpy()
                ma_arr = df_1m["sma9"].to_numpy()
                
                y_trades = df_trades[df_trades["year"] == y].copy()
                exit_pnls = []
                stop_hits = []
                
                for _, row in y_trades.iterrows():
                    entry_ts = int(row["entry_ts_bar1"])
                    exit_ts = int(row["exit_ts"])
                    entry_px = float(row["entry_px_bar1"])
                    atr = float(row["entry_atr"])
                    d = int(row["signal_direction"])
                    
                    idx_entry = np.searchsorted(ts_1m, entry_ts, side="left")
                    idx_exit = np.searchsorted(ts_1m, exit_ts, side="right") - 1
                    
                    if idx_entry >= len(ts_1m) or idx_exit >= len(ts_1m) or idx_entry > idx_exit:
                        exit_pnls.append(np.nan)
                        stop_hits.append(False)
                        continue
                        
                    total_trades += 1
                    cat_idx = max(0, idx_entry - 1)
                    catastrophic_stop = open_arr[cat_idx]
                    
                    active_stop = catastrophic_stop
                    
                    # Check if stop is already crossed at entry
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
                    
                    for j in range(idx_entry + loop_start_offset, idx_exit + 1):
                        h = high_arr[j]
                        l = low_arr[j]
                        c = close_arr[j]
                        
                        # Causal stop check
                        if d == 1 and l <= active_stop:
                            is_stopped = True
                            if corrected and is_crossed_at_entry:
                                exit_px = entry_px
                            else:
                                exit_px = active_stop
                            break
                        elif d == -1 and h >= active_stop:
                            is_stopped = True
                            if corrected and is_crossed_at_entry:
                                exit_px = entry_px
                            else:
                                exit_px = active_stop
                            break
                            
                        # Update MFE
                        if d == 1:
                            mfe_bar = (h - entry_px) / atr
                        else:
                            mfe_bar = (entry_px - l) / atr
                        running_mfe = max(running_mfe, mfe_bar)
                        
                        # Check gate
                        if not milestone_reached:
                            if running_mfe >= G:
                                milestone_reached = True
                                
                        # Track stall and ratchet
                        if milestone_reached:
                            # For the very first bar j = idx_entry, there's no j-1 in the trade, but we can compare to the flip bar
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
                                        if corrected and ma_val >= c:
                                            is_stopped = True
                                            exit_px = c
                                            break
                                        active_stop = max(active_stop, ma_val)
                                    else:
                                        if corrected and ma_val <= c:
                                            is_stopped = True
                                            exit_px = c
                                            break
                                        active_stop = min(active_stop, ma_val)
                                        
                    trade_exit_pnl = ((exit_px - entry_px) * d / atr)
                    exit_pnls.append(trade_exit_pnl)
                    stop_hits.append(is_stopped)
                    
                y_trades["exit_pnl_atr"] = exit_pnls
                y_trades["stop_hit"] = stop_hits
                all_results.append(y_trades)
                
            df_sim = pd.concat(all_results, ignore_index=True).dropna(subset=["exit_pnl_atr"])
            mean_pnl = df_sim["exit_pnl_atr"].mean()
            
            df_sim["gross_usd"] = df_sim["exit_pnl_atr"] * df_sim["entry_atr"] * 20.0
            df_sim["net_usd"] = df_sim["gross_usd"] - 10.0
            
            g_wins = df_sim[df_sim["gross_usd"] > 0]["gross_usd"].sum()
            g_losses = abs(df_sim[df_sim["gross_usd"] < 0]["gross_usd"].sum())
            gross_pf = g_wins / g_losses if g_losses > 0 else float("inf")
            
            n_wins = df_sim[df_sim["net_usd"] > 0]["net_usd"].sum()
            n_losses = abs(df_sim[df_sim["net_usd"] < 0]["net_usd"].sum())
            net_pf = n_wins / n_losses if n_losses > 0 else float("inf")
            
            print(f"Corrected={corrected} | loop_offset={loop_start_offset}:")
            print(f"  Mean PnL (ATR):         {mean_pnl:.4f}")
            print(f"  Gross PF:               {gross_pf:.2f} | Net PF: {net_pf:.2f}")

if __name__ == "__main__":
    main()

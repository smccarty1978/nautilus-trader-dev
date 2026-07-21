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
    
    for y in years:
        print(f"Loading and processing indicators for year {y}...")
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
        df_1m["ema3"] = df_1m["close"].ewm(span=3, adjust=False).mean()
        df_1m["ema9"] = df_1m["close"].ewm(span=9, adjust=False).mean()
        df_1m["sma9"] = df_1m["close"].rolling(9).mean()
        df_1m["sma13"] = df_1m["close"].rolling(13).mean()
        
        bars_1m_cache[y] = df_1m

    # Exit rules to evaluate
    exit_rules = [
        {"name": "Regime Exit (Baseline)", "type": "regime"},
        {"name": "Stall-State SMA9 (S=3, G=0.5)", "type": "stall", "rule": "sma9", "S": 3, "G": 0.5},
        {"name": "Stall-State SMA13 (S=3, G=0.0)", "type": "stall", "rule": "sma13", "S": 3, "G": 0.0},
        {"name": "EMA 3/9 State-Based", "type": "ema_state"},
        {"name": "EMA 3/9 Cross-Based", "type": "ema_cross"}
    ]
    
    results = []
    
    for r in exit_rules:
        total_trades = 0
        trade_pnls = []
        trade_net_pnls_usd = []
        
        for y in years:
            if y not in bars_1m_cache:
                continue
            df_1m = bars_1m_cache[y]
            ts_1m = df_1m.index.values.astype("int64")
            
            high_arr = df_1m["high"].to_numpy()
            low_arr = df_1m["low"].to_numpy()
            close_arr = df_1m["close"].to_numpy()
            open_arr = df_1m["open"].to_numpy()
            
            ema3_arr = df_1m["ema3"].to_numpy()
            ema9_arr = df_1m["ema9"].to_numpy()
            
            if r["type"] == "stall":
                ma_arr = df_1m[r["rule"]].to_numpy()
                
            y_trades = df_trades[df_trades["year"] == y]
            
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
                    
                # Catastrophic stop
                cat_idx = max(0, idx_entry - 1)
                active_stop = open_arr[cat_idx]
                
                exit_px = close_arr[idx_exit]
                
                if r["type"] == "regime":
                    exit_px = close_arr[idx_exit]
                elif r["type"] == "stall":
                    G = r["G"]
                    S = r["S"]
                    milestone_reached = True if G == 0.0 else False
                    stall_count = 0
                    running_mfe = 0.0
                    
                    for j in range(idx_entry + 1, idx_exit + 1):
                        h = high_arr[j]
                        l = low_arr[j]
                        
                        # Stop hit check first
                        if d == 1 and l <= active_stop:
                            exit_px = active_stop
                            break
                        elif d == -1 and h >= active_stop:
                            exit_px = active_stop
                            break
                            
                        if d == 1:
                            mfe_bar = (h - entry_px) / atr
                        else:
                            mfe_bar = (entry_px - l) / atr
                        running_mfe = max(running_mfe, mfe_bar)
                        
                        if not milestone_reached and running_mfe >= G:
                            milestone_reached = True
                            
                        if milestone_reached:
                            if d == 1:
                                if h > high_arr[j - 1]:
                                    stall_count = 0
                                else:
                                    stall_count += 1
                            else:
                                if l < low_arr[j - 1]:
                                    stall_count = 0
                                else:
                                    stall_count += 1
                                    
                            if stall_count >= S:
                                ma_val = ma_arr[j]
                                if not np.isnan(ma_val):
                                    if d == 1:
                                        active_stop = max(active_stop, ma_val)
                                    else:
                                        active_stop = min(active_stop, ma_val)
                                        
                elif r["type"] == "ema_state":
                    for j in range(idx_entry + 1, idx_exit + 1):
                        # Stop hit check first
                        if d == 1 and low_arr[j] <= active_stop:
                            exit_px = active_stop
                            break
                        elif d == -1 and high_arr[j] >= active_stop:
                            exit_px = active_stop
                            break
                            
                        if d == 1 and ema3_arr[j] < ema9_arr[j]:
                            exit_px = close_arr[j]
                            break
                        elif d == -1 and ema3_arr[j] > ema9_arr[j]:
                            exit_px = close_arr[j]
                            break
                            
                elif r["type"] == "ema_cross":
                    for j in range(idx_entry + 1, idx_exit + 1):
                        # Stop hit check first
                        if d == 1 and low_arr[j] <= active_stop:
                            exit_px = active_stop
                            break
                        elif d == -1 and high_arr[j] >= active_stop:
                            exit_px = active_stop
                            break
                            
                        if d == 1:
                            if ema3_arr[j] < ema9_arr[j] and ema3_arr[j-1] >= ema9_arr[j-1]:
                                exit_px = close_arr[j]
                                break
                        else:
                            if ema3_arr[j] > ema9_arr[j] and ema3_arr[j-1] <= ema9_arr[j-1]:
                                exit_px = close_arr[j]
                                break
                                
                trade_exit_pnl = ((exit_px - entry_px) * d / atr)
                trade_pnls.append(trade_exit_pnl)
                
                gross_usd = trade_exit_pnl * atr * 20.0
                net_usd = gross_usd - 10.0
                trade_net_pnls_usd.append(net_usd)
                total_trades += 1
                
        trade_pnls = np.array(trade_pnls)
        trade_net_pnls_usd = np.array(trade_net_pnls_usd)
        
        mean_pnl = np.mean(trade_pnls)
        net_wins = np.sum(trade_net_pnls_usd[trade_net_pnls_usd > 0])
        net_losses = np.sum(np.abs(trade_net_pnls_usd[trade_net_pnls_usd < 0]))
        net_pf = net_wins / net_losses if net_losses > 0 else float("inf")
        total_net_pnl = np.sum(trade_net_pnls_usd)
        
        print(f"Rule: {r['name']} | Trades: {total_trades:,} | Mean PnL: {mean_pnl:.4f} ATR | Net PF: {net_pf:.2f} | Net PnL: ${total_net_pnl:,.2f}")
        
    print(f"Comparison study completed in {(time.time() - t_start):.1f} seconds.")

if __name__ == "__main__":
    main()

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

def generate_ema_crossover_trades(df_1m, year):
    ema3 = df_1m["ema3"].to_numpy()
    ema9 = df_1m["ema9"].to_numpy()
    close_arr = df_1m["close"].to_numpy()
    high_arr = df_1m["high"].to_numpy()
    low_arr = df_1m["low"].to_numpy()
    ts_1m = df_1m.index.values.astype("int64")
    
    # Calculate ATR14 from 1m bars
    tr = np.maximum(high_arr - low_arr, np.maximum(np.abs(high_arr - np.roll(close_arr, 1)), np.abs(low_arr - np.roll(close_arr, 1))))
    tr[0] = high_arr[0] - low_arr[0]
    atr_arr = pd.Series(tr).rolling(14).mean().to_numpy()
    
    trades = []
    active_exit_ts = 0
    
    for j in range(1, len(df_1m)):
        if ts_1m[j] <= active_exit_ts:
            continue
            
        long_cross = (ema3[j] > ema9[j]) and (ema3[j-1] <= ema9[j-1])
        short_cross = (ema3[j] < ema9[j]) and (ema3[j-1] >= ema9[j-1])
        
        if long_cross or short_cross:
            direction = 1 if long_cross else -1
            entry_ts = ts_1m[j]
            entry_px = close_arr[j]
            atr = atr_arr[j]
            if np.isnan(atr) or atr <= 0.0:
                continue
                
            # Default exit: hold until opposite crossover
            opposite_exit_idx = len(df_1m) - 1
            for k in range(j + 1, len(df_1m)):
                if direction == 1:
                    if ema3[k] < ema9[k] and ema3[k-1] >= ema9[k-1]:
                        opposite_exit_idx = k
                        break
                else:
                    if ema3[k] > ema9[k] and ema3[k-1] <= ema9[k-1]:
                        opposite_exit_idx = k
                        break
                        
            exit_ts = ts_1m[opposite_exit_idx]
            active_exit_ts = exit_ts
            
            trades.append({
                "entry_ts_bar1": entry_ts,
                "exit_ts": exit_ts,
                "entry_px_bar1": entry_px,
                "entry_atr": atr,
                "signal_direction": direction,
                "year": year
            })
            
    return pd.DataFrame(trades)

def simulate_exits_corrected(df_trades, bars_1m_cache, exit_type, rule_name="sma9", G=0.5, S=3):
    years = sorted(df_trades["year"].unique())
    total_trades = 0
    exit_pnls = []
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
        
        if exit_type == "stall":
            ma_arr = df_1m[rule_name].to_numpy()
            
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
            
            is_crossed_at_entry = (d == 1 and entry_px <= active_stop) or (d == -1 and entry_px >= active_stop)
            
            exit_px = close_arr[idx_exit]
            
            if exit_type == "regime":
                # Check catastrophic stop hit causally in range
                for j in range(idx_entry, idx_exit + 1):
                    h = high_arr[j]
                    l = low_arr[j]
                    if d == 1 and l <= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
                        break
                    elif d == -1 and h >= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
                        break
            elif exit_type == "stall":
                milestone_reached = True if G == 0.0 else False
                stall_count = 0
                running_mfe = 0.0
                
                for j in range(idx_entry, idx_exit + 1):
                    h = high_arr[j]
                    l = low_arr[j]
                    c = close_arr[j]
                    
                    # Causal stop check
                    if d == 1 and l <= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
                        break
                    elif d == -1 and h >= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
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
                                    if ma_val >= c:
                                        exit_px = c
                                        break
                                    active_stop = max(active_stop, ma_val)
                                else:
                                    if ma_val <= c:
                                        exit_px = c
                                        break
                                    active_stop = min(active_stop, ma_val)
                                    
            elif exit_type == "ema_cross":
                # Exit at close of first bar where ema3 crosses ema9
                for j in range(idx_entry, idx_exit + 1):
                    # Causal stop check
                    if d == 1 and low_arr[j] <= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
                        break
                    elif d == -1 and high_arr[j] >= active_stop:
                        exit_px = entry_px if is_crossed_at_entry else active_stop
                        break
                        
                    if j > idx_entry:
                        if d == 1:
                            if ema3_arr[j] < ema9_arr[j] and ema3_arr[j-1] >= ema9_arr[j-1]:
                                exit_px = close_arr[j]
                                break
                        else:
                            if ema3_arr[j] > ema9_arr[j] and ema3_arr[j-1] <= ema9_arr[j-1]:
                                exit_px = close_arr[j]
                                break
                    else:
                        # At entry, if already crossed, cut immediately
                        if d == 1 and ema3_arr[j] < ema9_arr[j]:
                            exit_px = close_arr[j]
                            break
                        elif d == -1 and ema3_arr[j] > ema9_arr[j]:
                            exit_px = close_arr[j]
                            break
                            
            trade_exit_pnl = ((exit_px - entry_px) * d / atr)
            exit_pnls.append(trade_exit_pnl)
            
            gross_usd = trade_exit_pnl * atr * 20.0
            net_usd = gross_usd - 10.0
            trade_net_pnls_usd.append(net_usd)
            total_trades += 1
            
    exit_pnls = np.array(exit_pnls)
    trade_net_pnls_usd = np.array(trade_net_pnls_usd)
    
    mean_pnl = np.mean(exit_pnls) if len(exit_pnls) > 0 else 0.0
    net_wins = np.sum(trade_net_pnls_usd[trade_net_pnls_usd > 0])
    net_losses = np.sum(np.abs(trade_net_pnls_usd[trade_net_pnls_usd < 0]))
    net_pf = net_wins / net_losses if net_losses > 0 else float("inf")
    total_net_pnl = np.sum(trade_net_pnls_usd)
    
    return total_trades, mean_pnl, net_pf, total_net_pnl

def main():
    t_start = time.time()
    
    ds_path = "scratch/bar1_conditioning_dataset.parquet"
    if not os.path.exists(ds_path):
        print(f"Error: {ds_path} not found.")
        return
        
    df_trades_bar1 = pd.read_parquet(ds_path)
    print(f"Loaded {len(df_trades_bar1):,} Bar1-confirmed trades.")
    
    years = sorted(df_trades_bar1["year"].unique())
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

    # Generate 3/9 EMA crossover trades dynamically
    print("\nGenerating 3/9 EMA Crossover trades (flat-only)...")
    ema_trades_list = []
    for y in years:
        if y not in bars_1m_cache:
            continue
        df_ema_y = generate_ema_crossover_trades(bars_1m_cache[y], y)
        ema_trades_list.append(df_ema_y)
    df_trades_ema = pd.concat(ema_trades_list).reset_index(drop=True)
    print(f"Generated {len(df_trades_ema):,} 3/9 EMA Crossover trades.")

    print("\n" + "="*90)
    print("  COMPARISON 1: EXITS ON BAR1-CONFIRMED FLIPS (LEAKAGE-FREE CORRECTED)")
    print("="*90)
    
    for etype, rname, G, S, desc in [
        ("regime", "", 0.0, 0, "Regime Exit (Baseline)"),
        ("ema_cross", "", 0.0, 0, "EMA 3/9 Crossover Exit"),
        ("stall", "sma13", 0.0, 3, "Stall-State SMA13 (S=3, G=0.0)"),
        ("stall", "sma9", 0.5, 3, "Stall-State SMA9 (S=3, G=0.5)"),
    ]:
        n, mean_p, pf, tot_pnl = simulate_exits_corrected(df_trades_bar1, bars_1m_cache, etype, rname, G, S)
        print(f"{desc:<35} | Trades: {n:,} | Mean: {mean_p:+.4f} ATR | Net PF: {pf:.2f} | Net PnL: ${tot_pnl:,.2f}")

    print("\n" + "="*90)
    print("  COMPARISON 2: ENTRYS (BAR1-CONFIRMED FLIPS VS 3/9 EMA CROSSOVER)")
    print("="*90)
    
    print("A. Gated with Regime Exit (Baseline Exits):")
    for name, df_tr in [("Bar1 Confirmed", df_trades_bar1), ("EMA 3/9 Crossover", df_trades_ema)]:
        n, mean_p, pf, tot_pnl = simulate_exits_corrected(df_tr, bars_1m_cache, "regime")
        print(f"  {name:<20} | Trades: {n:,} | Mean: {mean_p:+.4f} ATR | Net PF: {pf:.2f} | Net PnL: ${tot_pnl:,.2f}")
        
    print("\nB. Gated with Stall-State SMA9 Exit (S=3, G=0.5):")
    for name, df_tr in [("Bar1 Confirmed", df_trades_bar1), ("EMA 3/9 Crossover", df_trades_ema)]:
        n, mean_p, pf, tot_pnl = simulate_exits_corrected(df_tr, bars_1m_cache, "stall", "sma9", 0.5, 3)
        print(f"  {name:<20} | Trades: {n:,} | Mean: {mean_p:+.4f} ATR | Net PF: {pf:.2f} | Net PnL: ${tot_pnl:,.2f}")

    print(f"\nCompleted in {(time.time() - t_start):.1f}s")

if __name__ == "__main__":
    main()

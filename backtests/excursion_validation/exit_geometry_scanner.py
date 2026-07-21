import pandas as pd
import numpy as np
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.core.datetime import dt_to_unix_nanos

def main():
    print("Loading trades...")
    base_dir = Path("backtests/excursion_validation/results")
    dfs = []
    for yr in range(2020, 2027):
        p = base_dir / f"live_{yr}" / "trades.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df = df[df["excursion_bkt"] == "low"].copy()
            dfs.append(df)
            
    trades = pd.concat(dfs, ignore_index=True)
    trades["entry_dt"] = pd.to_datetime(trades["entry_ts"], unit='ns', utc=True).dt.tz_convert('America/New_York')
    trades["trading_day"] = trades["entry_dt"].dt.date
    trades["time_str"] = trades["entry_dt"].dt.strftime("%H:%M")
    trades["year"] = trades["entry_dt"].dt.year
    
    # Needs to match VWAP context
    catalog_1m = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    print("Loading 1m bars for VWAP...")
    bars_1m = catalog_1m.bars(["NQ.XCME-1-MINUTE-LAST-EXTERNAL"])
    df_1m = pd.DataFrame({
        "ts": [b.ts_event for b in bars_1m],
        "close": [float(b.close) for b in bars_1m],
        "volume": [float(b.volume) for b in bars_1m]
    })
    df_1m["dt"] = pd.to_datetime(df_1m["ts"], unit='ns', utc=True).dt.tz_convert('America/New_York')
    df_1m["trading_day"] = df_1m["dt"].dt.date
    df_1m["time_str"] = df_1m["dt"].dt.strftime("%H:%M")
    df_1m["is_rth"] = (df_1m["time_str"] >= "09:30") & (df_1m["time_str"] < "16:00")
    
    rth_bars = df_1m[df_1m["is_rth"]].copy()
    rth_bars["pv"] = rth_bars["close"] * rth_bars["volume"]
    rth_bars["cum_vol"] = rth_bars.groupby("trading_day")["volume"].cumsum()
    rth_bars["cum_pv"] = rth_bars.groupby("trading_day")["pv"].cumsum()
    rth_bars["vwap"] = rth_bars["cum_pv"] / rth_bars["cum_vol"]
    rth_bars["dev_sq"] = rth_bars["volume"] * ((rth_bars["close"] - rth_bars["vwap"]) ** 2)
    rth_bars["cum_dev_sq"] = rth_bars.groupby("trading_day")["dev_sq"].cumsum()
    rth_bars["vwap_std"] = np.sqrt(rth_bars["cum_dev_sq"] / rth_bars["cum_vol"].replace(0, np.nan))
    rth_bars["vwap_std"] = rth_bars["vwap_std"].fillna(0)
    
    rth_subset = rth_bars[["ts", "vwap", "vwap_std"]].sort_values("ts")
    trades = trades.sort_values("entry_ts")
    trades = pd.merge_asof(trades, rth_subset, left_on="entry_ts", right_on="ts", direction="backward", tolerance=60 * 1_000_000_000)
    
    trades["dist_to_vwap"] = trades["entry_fill_price"] - trades["vwap"]
    trades["abs_dist_vwap"] = trades["dist_to_vwap"].abs()
    
    def classify_vwap(row):
        if pd.isna(row["vwap"]): return "Outside_RTH"
        dist, abs_dist = row["dist_to_vwap"], row["abs_dist_vwap"]
        std = row["vwap_std"] if row["vwap_std"] > 0 else 1
        atr = row["atr_at_signal"]
        d = row["direction"]
        
        if abs_dist <= 0.5 * atr: cell = "1_Near"
        elif abs_dist <= 1.0 * std: cell = "2_Inside"
        else: cell = "Other"
            
        if (d == 1 and dist > 0) or (d == -1 and dist < 0): intent = "Away_From"
        else: intent = "Toward"
        return f"{cell} | {intent}"
        
    trades["vwap_context"] = trades.apply(classify_vwap, axis=1)
    
    # The 863 Launchpad trades
    hypo_mask = (trades["vwap_context"].str.contains("1_Near") | trades["vwap_context"].str.contains("2_Inside")) & trades["vwap_context"].str.contains("Away_From")
    hypo_trades = trades[hypo_mask].copy()
    print(f"\nExtracted {len(hypo_trades)} Launchpad Trades.")
    
    del df_1m, rth_bars, rth_subset, bars_1m # Free memory
    
    # Output containers
    results = []
    
    catalog_1s = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    
    for yr in range(2020, 2027):
        yr_trades = hypo_trades[hypo_trades["year"] == yr].copy()
        if len(yr_trades) == 0:
            continue
            
        print(f"Loading 1s bars for {yr}...")
        start = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        end = pd.Timestamp(f"{yr}-12-31 23:59:59", tz="UTC")
        bars_1s = catalog_1s.bars(["NQ.XCME-1-SECOND-LAST-EXTERNAL"], start=dt_to_unix_nanos(start), end=dt_to_unix_nanos(end))
        
        b_ts = np.array([b.ts_event for b in bars_1s])
        b_h = np.array([float(b.high) for b in bars_1s])
        b_l = np.array([float(b.low) for b in bars_1s])
        b_c = np.array([float(b.close) for b in bars_1s])
        
        for idx, row in yr_trades.iterrows():
            px = row["entry_fill_price"]
            atr = row["atr_at_signal"]
            d = row["direction"]
            entry_ts = row["entry_ts"]
            
            # Align targets and stops to tick size (0.25)
            def tick_round(val):
                return round(val * 4) / 4.0
                
            sl_px = tick_round(px - atr) if d == 1 else tick_round(px + atr)
            # Add 1 tick slippage to Stop Loss
            sl_fill = sl_px - 0.25 if d == 1 else sl_px + 0.25
            
            t1_px = tick_round(px + atr) if d == 1 else tick_round(px - atr)
            t125_px = tick_round(px + 1.25*atr) if d == 1 else tick_round(px - 1.25*atr)
            t15_px = tick_round(px + 1.5*atr) if d == 1 else tick_round(px - 1.5*atr)
            t2_px = tick_round(px + 2.0*atr) if d == 1 else tick_round(px - 2.0*atr)
            t25_px = tick_round(px + 2.5*atr) if d == 1 else tick_round(px - 2.5*atr)
            
            start_idx = np.searchsorted(b_ts, entry_ts)
            max_idx = min(start_idx + 7200, len(b_ts)) # 2 hours max
            
            # Tracking variables
            hit_sl = -1
            hit_be = -1
            hit_t1 = -1
            hit_t125 = -1
            hit_t15 = -1
            hit_t2 = -1
            hit_t25 = -1
            
            # Time stops
            ts_3m, ts_5m, ts_10m, ts_30m, ts_60m = None, None, None, None, None
            
            for j in range(start_idx, max_idx):
                h, l, c = b_h[j], b_l[j], b_c[j]
                elapsed_sec = (b_ts[j] - entry_ts) // 1_000_000_000
                
                if elapsed_sec >= 180 and ts_3m is None: ts_3m = c
                if elapsed_sec >= 300 and ts_5m is None: ts_5m = c
                if elapsed_sec >= 600 and ts_10m is None: ts_10m = c
                if elapsed_sec >= 1800 and ts_30m is None: ts_30m = c
                if elapsed_sec >= 3600 and ts_60m is None: ts_60m = c
                
                if d == 1:
                    if l <= sl_px and hit_sl == -1: hit_sl = j
                    if l <= px and hit_be == -1: hit_be = j
                    if h >= t1_px and hit_t1 == -1: hit_t1 = j
                    if h >= t125_px and hit_t125 == -1: hit_t125 = j
                    if h >= t15_px and hit_t15 == -1: hit_t15 = j
                    if h >= t2_px and hit_t2 == -1: hit_t2 = j
                else:
                    if h >= sl_px and hit_sl == -1: hit_sl = j
                    if h >= px and hit_be == -1: hit_be = j
                    if l <= t1_px and hit_t1 == -1: hit_t1 = j
                    if l <= t125_px and hit_t125 == -1: hit_t125 = j
                    if l <= t15_px and hit_t15 == -1: hit_t15 = j
                    if l <= t2_px and hit_t2 == -1: hit_t2 = j
                    
                if elapsed_sec >= 3600:
                    break
                    
            res = {
                "entry_ts": entry_ts,
                "d": d,
                "px": px,
                "sl_fill": sl_fill,
                "t1_px": t1_px,
                "t125_px": t125_px,
                "t15_px": t15_px,
                "t2_px": t2_px,
                "hit_sl": hit_sl,
                "hit_be": hit_be,
                "hit_t1": hit_t1,
                "hit_t125": hit_t125,
                "hit_t15": hit_t15,
                "hit_t2": hit_t2,
                "start_idx": idx,
                "ts_3m": ts_3m,
                "ts_5m": ts_5m,
                "ts_10m": ts_10m,
                "ts_30m": ts_30m,
                "ts_60m": ts_60m,
                "nt_exit_reason": row["exit_reason"]
            }
            results.append(res)
            
    df_res = pd.DataFrame(results)
    
    print("\n=== ASYMMETRY DEEP DIVE ===")
    
    print("\n--- SHORTS: Scalp Geometry ---")
    shorts_df = df_res[df_res["d"] == -1]
    
    def eval_short_grid(t_col, t_px_col):
        wins = 0
        pnl = 0.0
        for _, r in shorts_df.iterrows():
            h_sl = r["hit_sl"]
            h_t = r[t_col]
            
            if h_sl != -1 and h_t != -1:
                if h_t < h_sl:
                    wins += 1
                    pnl += abs(r[t_px_col] - r["px"]) * 20.0
                else:
                    pnl -= abs(r["sl_fill"] - r["px"]) * 20.0
            elif h_t != -1:
                wins += 1
                pnl += abs(r[t_px_col] - r["px"]) * 20.0
            elif h_sl != -1:
                pnl -= abs(r["sl_fill"] - r["px"]) * 20.0
            else:
                exit_px = r["ts_60m"] if pd.notna(r["ts_60m"]) else r["px"]
                pnl += (exit_px - r["px"]) * r["d"] * 20.0
                
            pnl -= 5.0
            
        wr = wins / len(shorts_df) if len(shorts_df) > 0 else 0
        ev = pnl / len(shorts_df) if len(shorts_df) > 0 else 0
        return wr, pnl, ev

    for name, t_col, t_px in [("1.0 ATR", "hit_t1", "t1_px"), ("1.25 ATR", "hit_t125", "t125_px")]:
        wr, pnl, ev = eval_short_grid(t_col, t_px)
        print(f"  Target {name}: Win Rate {wr:.2%} | Net PnL: ${pnl:,.2f} | EV/Trade: ${ev:.2f}")

    print("\n--- SHORTS: Time Stops (1.0 ATR Target) ---")
    def eval_short_time_stop(ts_col, sec_thresh):
        wins = 0
        pnl = 0.0
        for _, r in shorts_df.iterrows():
            h_sl = r["hit_sl"]
            h_t = r["hit_t1"]
            start_idx = 0 # since we reset index to j=0 in the scanner inner loop!
            
            # Did it hit SL before time stop?
            hit_sl_early = (h_sl != -1 and h_sl <= sec_thresh)
            hit_t_early = (h_t != -1 and h_t <= sec_thresh)
            
            if hit_sl_early and hit_t_early:
                if h_t < h_sl:
                    wins += 1
                    pnl += abs(r["t1_px"] - r["px"]) * 20.0
                else:
                    pnl -= abs(r["sl_fill"] - r["px"]) * 20.0
            elif hit_t_early:
                wins += 1
                pnl += abs(r["t1_px"] - r["px"]) * 20.0
            elif hit_sl_early:
                pnl -= abs(r["sl_fill"] - r["px"]) * 20.0
            else:
                # Time stop!
                exit_px = r[ts_col]
                # If short, PnL is (px - exit_px)
                pnl += (r["px"] - exit_px) * 20.0
                if exit_px < r["px"]:
                    wins += 1 # Technically a winning trade if time stopped in profit
                    
            pnl -= 5.0
            
        wr = wins / len(shorts_df) if len(shorts_df) > 0 else 0
        ev = pnl / len(shorts_df) if len(shorts_df) > 0 else 0
        return wr, pnl, ev

    for name, ts_col, secs in [("3m", "ts_3m", 180), ("5m", "ts_5m", 300)]:
        wr, pnl, ev = eval_short_time_stop(ts_col, secs)
        print(f"  Target 1.0 ATR + {name} Time Stop: Win Rate {wr:.2%} | Net PnL: ${pnl:,.2f} | EV/Trade: ${ev:.2f}")

    print("\n--- LONGS: 2-Lot Runner Geometry ---")
    longs_df = df_res[df_res["d"] == 1]
    
    runner_pnl = 0.0
    wins_t1 = 0
    wins_t2 = 0
    
    for _, r in longs_df.iterrows():
        h_sl = r["hit_sl"]
        h_t1 = r["hit_t1"]
        h_t2 = r["hit_t2"]
        h_be = r["hit_be"]
        
        t1_first = False
        if h_t1 != -1 and h_sl != -1: t1_first = h_t1 < h_sl
        elif h_t1 != -1: t1_first = True
            
        if not t1_first:
            runner_pnl -= abs(r["sl_fill"] - r["px"]) * 20.0 * 2
        else:
            wins_t1 += 1
            runner_pnl += abs(r["t1_px"] - r["px"]) * 20.0
            
            if h_t2 != -1 and h_t2 > h_t1:
                if h_be != -1 and h_t1 < h_be < h_t2:
                    runner_pnl += 0.0 
                else:
                    wins_t2 += 1
                    runner_pnl += abs(r["t2_px"] - r["px"]) * 20.0 
            else:
                if h_be != -1 and h_be > h_t1:
                    runner_pnl += 0.0 
                else:
                    exit_px = r["ts_60m"] if pd.notna(r["ts_60m"]) else r["px"]
                    runner_pnl += (exit_px - r["px"]) * r["d"] * 20.0
                
        runner_pnl -= 10.0 
        
    print(f"  Long Runner Net PnL (2-lots): ${runner_pnl:,.2f}")
    print(f"  Long Runner EV/Trade: ${runner_pnl / len(longs_df):.2f}")
    
    
if __name__ == "__main__":
    main()

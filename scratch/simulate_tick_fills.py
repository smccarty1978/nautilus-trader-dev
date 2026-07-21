import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import pyarrow as pa
import time
import os

def main():
    t_start = time.time()
    
    # 1. Load NT trades for 2026
    p_nt = "backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0_2026/trades.parquet"
    if not os.path.exists(p_nt):
        print(f"Error: {p_nt} does not exist.")
        return
    df_nt = pd.read_parquet(p_nt)
    
    # Group by entry_ts to pair c1 and c2
    grouped = df_nt.groupby("entry_ts")
    trades = []
    for entry_ts, group in grouped:
        if len(group) == 2:
            c1 = group.iloc[0]
            c2 = group.iloc[1]
            trades.append({
                "entry_ts": int(entry_ts),
                "direction": int(c1["signal_direction"]),
                "entry_px": float(c1["entry_px"]),
                "entry_atr": float(c1["entry_atr"]),
                "exit_ts_nt": int(c2["exit_ts"]), # Use c2's exit ts as maximum life
                "c1_nt_px": float(c1["exit_px"]),
                "c1_nt_reason": str(c1["exit_reason"]),
                "c2_nt_px": float(c2["exit_px"]),
                "c2_nt_reason": str(c2["exit_reason"]),
            })
    
    print(f"Loaded {len(trades)} trades from Nautilus Trader 2026 backtest.")
    
    # Load features lookup for VWAP distance
    df_feat = pd.read_parquet("studies/regime_classification/results/features_nq_1m.parquet", columns=["vwap_z_abs"])
    if df_feat.index.tz is None:
        df_feat.index = df_feat.index.tz_localize("UTC")
    vwap_z_dict = dict(zip(df_feat.index.values.astype("int64"), df_feat["vwap_z_abs"].values))
    
    results = []
    
    for idx, trade in enumerate(trades):
        entry_ts = trade["entry_ts"]
        d = trade["direction"]
        entry_px = trade["entry_px"]
        atr = trade["entry_atr"]
        exit_ts_nt = trade["exit_ts_nt"]
        
        # Calculate targets
        pt_0p5 = entry_px + d * 0.50 * atr
        pt_2atr = entry_px + d * 2.00 * atr
        sl_px = entry_px - d * 1.50 * atr
        
        # Rounded target/stop prices to nearest NQ tick (0.25)
        pt_0p5_rounded = round(pt_0p5 * 4) / 4
        pt_2atr_rounded = round(pt_2atr * 4) / 4
        sl_px_rounded = round(sl_px * 4) / 4
        
        # Identify month and corresponding MBP parquet file
        dt = pd.to_datetime(entry_ts, unit='ns')
        month = dt.month
        month_str = f"{month:02d}"
        mbp_path = f"data/raw/NQ_v0_mbp1_2026_{month_str}.parquet"
        
        if not os.path.exists(mbp_path):
            print(f"MBP file not found: {mbp_path}. Skipping trade...")
            continue
            
        # Load quotes in a 5s window around trade life
        start_dt = pd.to_datetime(entry_ts - 5 * 1_000_000_000, unit='ns', utc=True)
        end_dt = pd.to_datetime(exit_ts_nt + 5 * 1_000_000_000, unit='ns', utc=True)
        
        # Load parquet sliced table using PyArrow filters
        table = pq.read_table(
            mbp_path,
            columns=["ts_recv", "ts_event", "bid_px_00", "ask_px_00"],
            filters=[
                ("ts_recv", ">=", pa.scalar(start_dt.to_pydatetime())),
                ("ts_recv", "<=", pa.scalar(end_dt.to_pydatetime()))
            ]
        )
        df_ticks = table.to_pandas()
        
        if len(df_ticks) == 0:
            print(f"Warning: No ticks loaded for trade {idx} (timestamp {dt}). Skipping...")
            continue
            
        ts_ns = df_ticks.index.values.astype("int64")
        bid_px = df_ticks["bid_px_00"].values
        ask_px = df_ticks["ask_px_00"].values
        
        # Find index in ticks corresponding to entry_ts
        entry_idx = np.searchsorted(ts_ns, entry_ts, side="left")
        entry_idx = min(entry_idx, len(ts_ns) - 1)
        
        # Chronological Simulation on Ticks
        touch_idx = -1
        c1_tick_px = None
        c1_tick_reason = ""
        c2_tick_px = None
        c2_tick_reason = ""
        
        # Loop to find first touch of SL or PT1
        for j in range(entry_idx, len(ts_ns)):
            bid = bid_px[j]
            ask = ask_px[j]
            t_curr = ts_ns[j]
            
            # Check Stop Loss first (Conservative)
            if (d == 1 and bid <= sl_px_rounded) or (d == -1 and ask >= sl_px_rounded):
                # SL hit! Exits at market on next tick
                next_idx = min(j + 1, len(ts_ns) - 1)
                fill_px = bid_px[next_idx] if d == 1 else ask_px[next_idx]
                c1_tick_px = c2_tick_px = fill_px
                c1_tick_reason = c2_tick_reason = "stop_loss"
                break
                
            # Check PT1 Touch
            if (d == 1 and bid >= pt_0p5_rounded) or (d == -1 and ask <= pt_0p5_rounded):
                # PT1 touched! Limit order fills exactly at limit price
                c1_tick_px = pt_0p5_rounded
                c1_tick_reason = "PT1"
                touch_idx = j
                break
                
            # Max life fallback (if we exceed Nautilus Trader exit ts)
            if t_curr >= exit_ts_nt:
                c1_tick_px = c2_tick_px = bid_px[j] if d == 1 else ask_px[j]
                c1_tick_reason = c2_tick_reason = "regime_flip"
                break
                
        # If PT1 was touched, evaluate Contract 2
        if touch_idx != -1:
            touch_ts = ts_ns[touch_idx]
            # Lookup VWAP distance
            t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
            vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
            
            if vwap_z > 1.0:
                # Exhaustion! Exits runner at market on next tick
                next_idx = min(touch_idx + 1, len(ts_ns) - 1)
                fill_px = bid_px[next_idx] if d == 1 else ask_px[next_idx]
                c2_tick_px = fill_px
                c1_tick_reason = c2_tick_reason = "VWAP_exhaustion"
            else:
                # Near VWAP! Runner contract continues
                # Search chronologically for SL or PT2 or max life
                for k in range(touch_idx + 1, len(ts_ns)):
                    bid = bid_px[k]
                    ask = ask_px[k]
                    t_curr = ts_ns[k]
                    
                    # Check SL
                    if (d == 1 and bid <= sl_px_rounded) or (d == -1 and ask >= sl_px_rounded):
                        next_idx = min(k + 1, len(ts_ns) - 1)
                        fill_px = bid_px[next_idx] if d == 1 else ask_px[next_idx]
                        c2_tick_px = fill_px
                        c2_tick_reason = "stop_loss"
                        break
                        
                    # Check PT2
                    if (d == 1 and bid >= pt_2atr_rounded) or (d == -1 and ask <= pt_2atr_rounded):
                        c2_tick_px = pt_2atr_rounded
                        c2_tick_reason = "PT2"
                        break
                        
                    # Regime exit fallback
                    if t_curr >= exit_ts_nt:
                        c2_tick_px = bid_px[k] if d == 1 else ask_px[k]
                        c2_tick_reason = "regime_flip"
                        break
                        
        # Idealized Study simulation (for comparison)
        # Note: Idealized study completely ignores SL before target!
        touch_idx_ideal = -1
        c1_ideal_px = None
        c1_ideal_reason = ""
        c2_ideal_px = None
        c2_ideal_reason = ""
        
        # First check if touches target at any point
        for j in range(entry_idx, len(ts_ns)):
            bid = bid_px[j]
            ask = ask_px[j]
            t_curr = ts_ns[j]
            if (d == 1 and bid >= pt_0p5_rounded) or (d == -1 and ask <= pt_0p5_rounded):
                touch_idx_ideal = j
                break
            if t_curr >= exit_ts_nt:
                break
                
        if touch_idx_ideal == -1:
            # Never touched target, check initial stop or regime exit
            c1_ideal_px = c2_ideal_px = sl_px_rounded # Assume filled at exact stop price
            c1_ideal_reason = c2_ideal_reason = "stop_loss"
            # Double check if we ever reached SL before regime exit
            hit_sl = False
            for j in range(entry_idx, len(ts_ns)):
                bid = bid_px[j]
                ask = ask_px[j]
                t_curr = ts_ns[j]
                if (d == 1 and bid <= sl_px_rounded) or (d == -1 and ask >= sl_px_rounded):
                    hit_sl = True
                    break
                if t_curr >= exit_ts_nt:
                    break
            if not hit_sl:
                # Exited at regime flip
                # Find exit index in ticks
                exit_idx = np.searchsorted(ts_ns, exit_ts_nt, side="left")
                exit_idx = min(exit_idx, len(ts_ns) - 1)
                c1_ideal_px = c2_ideal_px = bid_px[exit_idx] if d == 1 else ask_px[exit_idx]
                c1_ideal_reason = c2_ideal_reason = "regime_flip"
        else:
            # Touched target! Check VWAP
            touch_ts = ts_ns[touch_idx_ideal]
            t_closed_open = (touch_ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
            vwap_z = vwap_z_dict.get(t_closed_open, 1.0)
            
            c1_ideal_px = pt_0p5_rounded
            if vwap_z > 1.0:
                c2_ideal_px = pt_0p5_rounded
                c1_ideal_reason = c2_ideal_reason = "VWAP_exhaustion"
            else:
                c1_ideal_reason = "PT1"
                # Contract 2 runner
                c2_ideal_px = sl_px_rounded
                c2_ideal_reason = "stop_loss"
                # Search for PT2 or SL
                for k in range(touch_idx_ideal + 1, len(ts_ns)):
                    bid = bid_px[k]
                    ask = ask_px[k]
                    t_curr = ts_ns[k]
                    if (d == 1 and bid <= sl_px_rounded) or (d == -1 and ask >= sl_px_rounded):
                        c2_ideal_px = sl_px_rounded
                        c2_ideal_reason = "stop_loss"
                        break
                    if (d == 1 and bid >= pt_2atr_rounded) or (d == -1 and ask <= pt_2atr_rounded):
                        c2_ideal_px = pt_2atr_rounded
                        c2_ideal_reason = "PT2"
                        break
                    if t_curr >= exit_ts_nt:
                        # Exit at regime close
                        exit_idx = np.searchsorted(ts_ns, exit_ts_nt, side="left")
                        exit_idx = min(exit_idx, len(ts_ns) - 1)
                        c2_ideal_px = bid_px[exit_idx] if d == 1 else ask_px[exit_idx]
                        c2_ideal_reason = "regime_flip"
                        break
                        
        # Record results
        results.append({
            "entry_ts": entry_ts,
            "direction": d,
            "entry_px": entry_px,
            "atr": atr,
            # Idealized Study Exits
            "c1_ideal_px": c1_ideal_px,
            "c1_ideal_reason": c1_ideal_reason,
            "c2_ideal_px": c2_ideal_px,
            "c2_ideal_reason": c2_ideal_reason,
            # Nautilus Trader Exits
            "c1_nt_px": trade["c1_nt_px"],
            "c1_nt_reason": trade["c1_nt_reason"],
            "c2_nt_px": trade["c2_nt_px"],
            "c2_nt_reason": trade["c2_nt_reason"],
            # High-Fidelity Tick Exits
            "c1_tick_px": c1_tick_px,
            "c1_tick_reason": c1_tick_reason,
            "c2_tick_px": c2_tick_px,
            "c2_tick_reason": c2_tick_reason,
        })
        
    df_res = pd.DataFrame(results)
    
    # Calculate PnL in points for each simulation
    # Ideal
    df_res["pnl_ideal_c1"] = (df_res["c1_ideal_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_ideal_c2"] = (df_res["c2_ideal_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_ideal"] = df_res["pnl_ideal_c1"] + df_res["pnl_ideal_c2"]
    
    # NT
    df_res["pnl_nt_c1"] = (df_res["c1_nt_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_nt_c2"] = (df_res["c2_nt_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_nt"] = df_res["pnl_nt_c1"] + df_res["pnl_nt_c2"]
    
    # Tick
    df_res["pnl_tick_c1"] = (df_res["c1_tick_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_tick_c2"] = (df_res["c2_tick_px"] - df_res["entry_px"]) * df_res["direction"]
    df_res["pnl_tick"] = df_res["pnl_tick_c1"] + df_res["pnl_tick_c2"]
    
    # Compare
    print("\n" + "="*120)
    print("  HIGH-FIDELITY MICROSTRUCTURE TICK-BY-TICK FILL SIMULATION battery (OOS 2026)")
    print("  Asset: NQ.XCME Futures | Ticks: 2026 MBP-1 L2 quote parquets | Sizing: 2 Contracts")
    print("="*120)
    
    print("\nAggregated Performance of 2026 Backtest Cohort:")
    print(f"  Idealized Study PnL    : {df_res['pnl_ideal'].sum():+.2f} pts (${df_res['pnl_ideal'].sum()*20.0:,.2f})")
    print(f"  Nautilus Trader PnL    : {df_res['pnl_nt'].sum():+.2f} pts (${df_res['pnl_nt'].sum()*20.0:,.2f})")
    print(f"  True Tick Micro PnL    : {df_res['pnl_tick'].sum():+.2f} pts (${df_res['pnl_tick'].sum()*20.0:,.2f})")
    print(f"  True Micro vs NT Gap   : {df_res['pnl_tick'].sum() - df_res['pnl_nt'].sum():+.2f} pts (${(df_res['pnl_tick'].sum() - df_res['pnl_nt'].sum())*20.0:,.2f})")
    print(f"  True Micro vs Ideal Gap: {df_res['pnl_tick'].sum() - df_res['pnl_ideal'].sum():+.2f} pts (${(df_res['pnl_tick'].sum() - df_res['pnl_ideal'].sum())*20.0:,.2f})")
    
    # Analyze slippage on market orders only (VWAP_exhaustion or stop_loss exits)
    # Let's see how much price drag we get on c2 VWAP_exhaustion trades
    vwap_ex_trades = df_res[df_res["c2_nt_reason"] == "VWAP_exhaustion"]
    print(f"\nSlippage audit on VWAP_exhaustion runner exits (n={len(vwap_ex_trades)}):")
    
    # For these, let's compare c2 fill price:
    # Ideal: pt_0p5
    # NT: trade["c2_nt_px"]
    # Tick: trade["c2_tick_px"]
    # Slippage pts = (ideal_px - fill_px) * direction
    nt_slip = (vwap_ex_trades["c2_ideal_px"] - vwap_ex_trades["c2_nt_px"]) * vwap_ex_trades["direction"]
    tick_slip = (vwap_ex_trades["c2_ideal_px"] - vwap_ex_trades["c2_tick_px"]) * vwap_ex_trades["direction"]
    
    print(f"  Average NT Slippage per Exit: {nt_slip.mean():.4f} pts ({nt_slip.mean()/0.25:.2f} ticks)")
    print(f"  Average Tick Slippage per Exit: {tick_slip.mean():.4f} pts ({tick_slip.mean()/0.25:.2f} ticks)")
    print(f"  Slippage reduction by Tick-simulation: {nt_slip.mean() - tick_slip.mean():.4f} pts ({(nt_slip.mean() - tick_slip.mean())/0.25:.2f} ticks)")
    
    # Stop loss slippage audit
    sl_trades = df_res[df_res["c2_nt_reason"] == "stop_loss"]
    print(f"\nSlippage audit on Stop Loss exits (n={len(sl_trades)}):")
    nt_sl_slip = (sl_trades["c2_ideal_px"] - sl_trades["c2_nt_px"]) * sl_trades["direction"]
    tick_sl_slip = (sl_trades["c2_ideal_px"] - sl_trades["c2_tick_px"]) * sl_trades["direction"]
    print(f"  Average NT SL Slippage per Exit: {nt_sl_slip.mean():.4f} pts ({nt_sl_slip.mean()/0.25:.2f} ticks)")
    print(f"  Average Tick SL Slippage per Exit: {tick_sl_slip.mean():.4f} pts ({tick_sl_slip.mean()/0.25:.2f} ticks)")
    print(f"  SL Slippage reduction by Tick-sim   : {nt_sl_slip.mean() - tick_sl_slip.mean():.4f} pts ({(nt_sl_slip.mean() - tick_sl_slip.mean())/0.25:.2f} ticks)")

    # Let's save a summary markdown table and detailed data for report
    print("\nDetailed Trade Comparison (First 15 trades):")
    print(df_res[["entry_ts", "direction", "c1_ideal_reason", "c1_nt_reason", "c1_tick_reason", "pnl_ideal", "pnl_nt", "pnl_tick"]].head(15).to_string())
    
    # Save df_res to scratch parquet for auditing
    df_res.to_parquet("scratch/tick_fill_simulation_results.parquet")
    print(f"\nResults saved to scratch/tick_fill_simulation_results.parquet in {time.time()-t_start:.1f}s.")

if __name__ == "__main__":
    main()

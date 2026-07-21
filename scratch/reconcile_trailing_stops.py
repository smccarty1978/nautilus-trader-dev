import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

def load_1s_cached(year, cache={}):
    if year in cache:
        return cache[year]
    p = ONE_S.get(year)
    if p and os.path.exists(p):
        print(f"Loading 1s NQ data for {year}...")
        df = pd.read_parquet(p, columns=["high", "low", "close"])
        df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
        cache[year] = df
        return df
    raise FileNotFoundError(f"1s data not found for year {year}")

def run_reconciliation():
    years = [2021, 2022, 2023, 2024]
    
    tp_atr = 1.5
    sl_atr = 1.0
    be_trig_atr = 0.25
    be_lvl_atr = 0.25
    trail_dist_atr = 0.25
    
    total_matched = 0
    total_audited = 0
    pnl_diffs = []
    time_diffs_s = []
    
    exit_reasons_bt = []
    exit_reasons_sim = []
    
    # Store some examples of mismatches for diagnostic purposes
    mismatch_examples = []
    
    for y in years:
        p = PROJECT_ROOT / f"backtests/baseline_flip_parity/results/nq_live_{y}_trail_tp1.5_sl1.0/trades.parquet"
        if not p.exists():
            print(f"Trades file not found: {p}")
            continue
            
        df_bt = pd.read_parquet(p)
        print(f"\nAuditing year {y} ({len(df_bt):,} trades)...")
        
        try:
            bars_1s = load_1s_cached(y)
        except Exception as e:
            print(f"Skipping year {y}: {e}")
            continue
            
        ts_1s = bars_1s.index.astype("int64").to_numpy()
        h_1s = bars_1s["high"].to_numpy(np.float64)
        l_1s = bars_1s["low"].to_numpy(np.float64)
        c_1s = bars_1s["close"].to_numpy(np.float64)
        
        # Search index positions
        entry_ts_arr = df_bt["entry_ts"].to_numpy(np.int64)
        indices = np.searchsorted(ts_1s, entry_ts_arr, side="left")
        
        for i in range(len(df_bt)):
            row = df_bt.iloc[i]
            idx_entry = indices[i]
            if idx_entry >= len(ts_1s):
                continue
                
            px_entry = float(row["entry_px"])
            atr = float(row["entry_atr"])
            d = int(row["signal_direction"])
            ts_start = int(row["entry_ts"])
            
            # Replicate 1s simulation for this trade
            j = min(idx_entry + 1, len(ts_1s) - 1)
            pt_px = tp_atr * atr
            sl_px = -sl_atr * atr
            be_trig_px = be_trig_atr * atr
            be_stop_px = be_lvl_atr * atr
            
            # Apply initial stop rounding and 0.25 tick safety cap
            # Rounding function matches strategy.py
            def _tick_round(val: float) -> float:
                return round(val * 4) / 4.0
            
            if d == 1:
                sl_px = _tick_round(min(px_entry + sl_px, px_entry - 0.25))
            else:
                sl_px = _tick_round(max(px_entry - sl_px, px_entry + 0.25))
                
            current_stop_px = sl_px
            peak_mfe = 0.0
            be_activated = False
            
            outcome = "Time"
            exit_px = None
            exit_ts = None
            
            MAX_HOLD_NS = 4 * 3600 * 1_000_000_000
            
            while j < len(ts_1s):
                t_curr = ts_1s[j]
                dt = t_curr - ts_start
                if dt >= MAX_HOLD_NS:
                    outcome = "max_hold"
                    exit_px = c_1s[j]
                    exit_ts = t_curr
                    break
                    
                h, l, c = h_1s[j], l_1s[j], c_1s[j]
                
                # Check stops
                if d == 1:
                    mfe_bar = (h - px_entry) / atr
                    mae_bar = l - px_entry
                    close_rel = c - px_entry
                    
                    # 1. Check stop hit
                    if l <= current_stop_px:
                        outcome = "SL"
                        exit_px = current_stop_px
                        exit_ts = t_curr
                        break
                    # 2. Check target hit
                    if h >= px_entry + pt_px:
                        outcome = "T"
                        exit_px = px_entry + pt_px
                        exit_ts = t_curr
                        break
                        
                    # 3. Update stop triggers
                    peak_mfe = max(peak_mfe, mfe_bar)
                    potential_stop = sl_px
                    if be_trig_atr > 0.0 and peak_mfe >= be_trig_atr:
                        potential_stop = max(potential_stop, px_entry + be_stop_px)
                    if trail_dist_atr > 0.0 and peak_mfe >= trail_dist_atr:
                        trail_stop_dist = (peak_mfe - trail_dist_atr) * atr
                        potential_stop = max(potential_stop, px_entry + trail_stop_dist)
                    
                    new_stop = _tick_round(potential_stop)
                    if new_stop > current_stop_px:
                        # Check stop-crossing
                        if new_stop >= c:
                            outcome = "SL"
                            exit_px = c
                            exit_ts = t_curr
                            break
                        current_stop_px = new_stop
                else:
                    mfe_bar = (px_entry - l) / atr
                    mae_bar = px_entry - h
                    close_rel = px_entry - c
                    
                    # 1. Check stop hit
                    if h >= current_stop_px:
                        outcome = "SL"
                        exit_px = current_stop_px
                        exit_ts = t_curr
                        break
                    # 2. Check target hit
                    if l <= px_entry - pt_px:
                        outcome = "T"
                        exit_px = px_entry - pt_px
                        exit_ts = t_curr
                        break
                        
                    # 3. Update stop triggers
                    peak_mfe = max(peak_mfe, mfe_bar)
                    potential_stop = sl_px
                    if be_trig_atr > 0.0 and peak_mfe >= be_trig_atr:
                        potential_stop = min(potential_stop, px_entry - be_stop_px)
                    if trail_dist_atr > 0.0 and peak_mfe >= trail_dist_atr:
                        trail_stop_dist = (peak_mfe - trail_dist_atr) * atr
                        potential_stop = min(potential_stop, px_entry - trail_stop_dist)
                        
                    new_stop = _tick_round(potential_stop)
                    if new_stop < current_stop_px:
                        # Check stop-crossing
                        if new_stop <= c:
                            outcome = "SL"
                            exit_px = c
                            exit_ts = t_curr
                            break
                        current_stop_px = new_stop
                        
                j += 1
                
            if exit_px is None and j > idx_entry:
                last_idx = min(j - 1, len(ts_1s) - 1)
                exit_px = c_1s[last_idx]
                exit_ts = ts_1s[last_idx]
                outcome = "max_hold"
                
            # Compare with backtest actual trade
            bt_outcome = row["exit_reason"]
            bt_exit_px = float(row["exit_px"])
            bt_exit_ts = int(row["exit_ts"])
            
            pnl_diff = abs(bt_exit_px - exit_px)
            time_diff = abs(bt_exit_ts - exit_ts) / 1_000_000_000.0
            
            pnl_diffs.append(pnl_diff)
            time_diffs_s.append(time_diff)
            exit_reasons_bt.append(bt_outcome)
            exit_reasons_sim.append(outcome)
            
            # Match condition: PnL difference < 0.5 points and exit time difference < 5s
            is_match = (pnl_diff < 0.5) and (time_diff < 5.0) and (bt_outcome == outcome)
            if is_match:
                total_matched += 1
            else:
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({
                        "year": y,
                        "entry_ts": ts_start,
                        "direction": d,
                        "entry_px": px_entry,
                        "bt_exit_ts": bt_exit_ts,
                        "sim_exit_ts": exit_ts,
                        "bt_exit_px": bt_exit_px,
                        "sim_exit_px": exit_px,
                        "bt_reason": bt_outcome,
                        "sim_reason": outcome,
                        "time_diff": time_diff,
                        "pnl_diff": pnl_diff
                    })
                    
            total_audited += 1
            
    # Calculate stats
    match_rate = total_matched / total_audited * 100 if total_audited > 0 else 0.0
    print("\n" + "="*80)
    print("  TRAILING STOP AUDIT AND RECONCILIATION SUMMARY")
    print("="*80)
    print(f"  Total Trades Audited:         {total_audited:,}")
    print(f"  Perfect Parity Matches:       {total_matched:,} ({match_rate:.2f}%)")
    print(f"  Mean Exit Time Diff (s):      {np.mean(time_diffs_s):.2f}s")
    print(f"  Median Exit Time Diff (s):    {np.median(time_diffs_s):.2f}s")
    print(f"  Mean Exit Price Diff (pts):   {np.mean(pnl_diffs):.4f} pts")
    print(f"  Median Exit Price Diff (pts): {np.median(pnl_diffs):.4f} pts")
    
    # Print exit reasons confusion matrix
    df_confusion = pd.DataFrame({"BT": exit_reasons_bt, "Sim": exit_reasons_sim})
    print("\n  Exit Reasons Correlation Table:")
    print(pd.crosstab(df_confusion["BT"], df_confusion["Sim"]))
    
    if mismatch_examples:
        print("\n  Forensic Mismatch Examples:")
        for idx, ex in enumerate(mismatch_examples):
            entry_dt = pd.to_datetime(ex['entry_ts'], unit='ns', utc=True)
            print(f"    Ex {idx+1}: {entry_dt} | Dir: {ex['direction']} | Entry Px: {ex['entry_px']:.2f}")
            print(f"      BT Exit:  Time={pd.to_datetime(ex['bt_exit_ts'], unit='ns', utc=True)} | Px={ex['bt_exit_px']:.2f} | Reason={ex['bt_reason']}")
            print(f"      Sim Exit: Time={pd.to_datetime(ex['sim_exit_ts'], unit='ns', utc=True)} | Px={ex['sim_exit_px']:.2f} | Reason={ex['sim_reason']}")
            print(f"      Diffs:    Time={ex['time_diff']:.1f}s | Px={ex['pnl_diff']:.2f} pts")
            print()

if __name__ == "__main__":
    run_reconciliation()

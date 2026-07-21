import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from scratch.calculate_conditioning_features import load_1s, compute_1m_indicators, compute_session_metrics

def compute_pf(pnl_pts):
    wins = pnl_pts[pnl_pts > 0].sum()
    losses = abs(pnl_pts[pnl_pts < 0].sum())
    return wins / losses if losses > 0 else float("inf")

def main():
    t0 = time.time()
    
    # Load bar1 excursions dataset
    trades_path = "scratch/predict_bar1_excursions.parquet"
    if not os.path.exists(trades_path):
        print(f"Error: {trades_path} not found.")
        return
        
    df_trades = pd.read_parquet(trades_path)
    print(f"Loaded {len(df_trades):,} trades.")
    
    enriched_dfs = []
    
    # Run audit on a sample year first (e.g. 2023) to see the difference
    for y in [2023, 2024, 2025, 2026]:
        year_trades = df_trades[df_trades["year"] == y].copy()
        if len(year_trades) == 0:
            continue
            
        print(f"\nProcessing year {y}...")
        
        # Load 1s bars and compute 1m indicators
        bars_1s = load_1s(y)
        df_1m = pd.DataFrame()
        df_1m["open"] = bars_1s["open"].resample("1Min").first()
        df_1m["high"] = bars_1s["high"].resample("1Min").max()
        df_1m["low"] = bars_1s["low"].resample("1Min").min()
        df_1m["close"] = bars_1s["close"].resample("1Min").last()
        df_1m = df_1m.dropna()
        
        df_1m = compute_1m_indicators(df_1m)
        df_1m = compute_session_metrics(df_1m)
        
        # Load snapshots database for the year
        snap_p = f"studies/1m_regime_collector_v2/results/v2_feature_snapshots_{y}.parquet"
        if os.path.exists(snap_p):
            df_snap = pd.read_parquet(snap_p)
            df_snap["signal_time"] = df_snap["signal_time"].astype("int64")
            
            # CRITICAL AUDIT FIX 1: Filter for checkpoint_s == 0 BEFORE deduplicating!
            df_snap = df_snap[df_snap["checkpoint_s"] == 0]
            df_snap = df_snap.drop_duplicates(subset=["signal_time", "signal_direction"])
        else:
            print(f"  Snapshots not found for {y}")
            continue
            
        # Merge snapshots features
        year_trades = year_trades.merge(
            df_snap,
            left_on=["entry_ts_bar1", "signal_direction"],
            right_on=["signal_time", "signal_direction"],
            how="inner"
        )
        print(f"  Matched with snapshots: {len(year_trades)}")
        
        # CRITICAL AUDIT FIX 2: Causal alignment index lookup
        # entry_ts_bar1 is the close of the entry bar.
        # We need the 1m bar that has JUST completed at entry_ts_bar1.
        # Since df_1m index is left-aligned (start of the minute), the completed bar ending at entry_ts_bar1
        # starts at (entry_ts_bar1 - 60s).
        target_lookup_ts = year_trades["entry_ts_bar1"].to_numpy("int64") - 60_000_000_000
        
        ts_1m = df_1m.index.values.astype("int64")
        idx_1m = np.searchsorted(ts_1m, target_lookup_ts, side="left")
        
        # Verify alignment
        exact_matches = (ts_1m[idx_1m] == target_lookup_ts)
        print(f"  Exact timestamp matches for 1m bars: {exact_matches.mean()*100:.2f}%")
        
        # Safe boundary check
        valid_idx = (idx_1m >= 0) & (idx_1m < len(ts_1m)) & exact_matches
        year_trades = year_trades[valid_idx].copy()
        idx_1m = idx_1m[valid_idx]
        
        # Extract features causally
        ema3 = df_1m["ema3"].to_numpy()[idx_1m]
        ema13 = df_1m["ema13"].to_numpy()[idx_1m]
        atr = year_trades["entry_atr"].to_numpy()[valid_idx]
        close_px = year_trades["entry_px_bar1"].to_numpy()[valid_idx]
        d = year_trades["signal_direction"].to_numpy()[valid_idx]
        
        # Leak-free feature calculations
        year_trades["dist_ema3_causal"] = (close_px - ema3) * d
        year_trades["dist_ema3_atr_causal"] = year_trades["dist_ema3_causal"] / atr
        
        # Let's compare the non-causal (leaky) vs causal Spearman IC
        # In the original df_snap (which was merged on entry_ts_bar1 directly):
        # Let's see if we can find the leaky ema3 from the 1m df
        idx_1m_leaky = np.searchsorted(ts_1m, year_trades["entry_ts_bar1"].to_numpy("int64"), side="left")
        valid_leaky = (idx_1m_leaky >= 0) & (idx_1m_leaky < len(ts_1m))
        
        ema3_leaky = df_1m["ema3"].to_numpy()[idx_1m_leaky[valid_leaky]]
        year_trades.loc[valid_leaky, "dist_ema3_leaky"] = (close_px[valid_leaky] - ema3_leaky) * d[valid_leaky]
        year_trades.loc[valid_leaky, "dist_ema3_atr_leaky"] = year_trades.loc[valid_leaky, "dist_ema3_leaky"] / atr[valid_leaky]
        
        # Compute Spearman ICs
        sub = year_trades[["dist_ema3_atr_leaky", "dist_ema3_atr_causal", "regime_pnl_pts_bar1"]].dropna()
        ic_leaky, _ = spearmanr(sub["dist_ema3_atr_leaky"], sub["regime_pnl_pts_bar1"])
        ic_causal, _ = spearmanr(sub["dist_ema3_atr_causal"], sub["regime_pnl_pts_bar1"])
        
        print(f"  Spearman IC for Leaky dist_ema3_atr:  {ic_leaky:+.4f}")
        print(f"  Spearman IC for Causal dist_ema3_atr: {ic_causal:+.4f}")
        
        # Run a quick decile split for causal
        sub["decile"] = pd.qcut(sub["dist_ema3_atr_causal"] + np.random.normal(0, 1e-10, len(sub)), 10, labels=False) + 1
        print("  Causal Decile EV and PF:")
        for d_num in [1, 5, 10]:
            d_grp = sub[sub["decile"] == d_num]
            ev = d_grp["regime_pnl_pts_bar1"].mean() * 20.0
            pf = compute_pf(d_grp["regime_pnl_pts_bar1"])
            print(f"    Decile {d_num:2d} | Count: {len(d_grp):<5,} | Gross EV: ${ev:>6.2f} | Gross PF: {pf:.2f}")
            
    print(f"\nAudit completed in {(time.time()-t0)/60:.2f} minutes.")

if __name__ == "__main__":
    main()

"""Volatility Monotonicity Study on NQ Causal KMeans State Flips.

Tests whether the edge of KMeans_4 State 0 is monotonic with volatility (ATR).
Produces sensitivity tables for both symmetric 1.0 ATR brackets and asymmetric setups
to separate physical mechanisms from razor-edge thresholds.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OOS_YEARS = (2023, 2024, 2025, 2026)


def load_1s(year):
    parts = []
    for y in (year - 1, year, year + 1):
        p = ONE_S.get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    return bars


@njit
def scan_exact_excursions(entry_ts_arr, entry_px_arr, entry_atr_arr, dir_arr,
                          ts_1s, high_1s, low_1s, close_1s):
    N = len(entry_ts_arr)
    mfe_1m = np.full(N, np.nan)
    mae_1m = np.full(N, np.nan)
    term_1m = np.full(N, np.nan)
    
    mfe_5m = np.full(N, np.nan)
    mae_5m = np.full(N, np.nan)
    term_5m = np.full(N, np.nan)
    
    indices = np.searchsorted(ts_1s, entry_ts_arr, side="left")
    
    for i in range(N):
        i_entry = indices[i]
        if i_entry >= len(ts_1s) or entry_atr_arr[i] <= 0:
            continue
            
        px_entry = entry_px_arr[i]
        atr = entry_atr_arr[i]
        d = dir_arr[i]
        ts_start = entry_ts_arr[i]
        
        running_mfe = 0.0
        running_mae = 0.0
        
        j = i_entry
        recorded_1m = False
        recorded_5m = False
        
        while j < len(ts_1s):
            dt = ts_1s[j] - ts_start
            if dt > 300 * 1_000_000_000:
                break
                
            h, l, c = high_1s[j], low_1s[j], close_1s[j]
            if d == 1:
                mfe_t = h - px_entry
                mae_t = px_entry - l
            else:
                mfe_t = px_entry - l
                mae_t = h - px_entry
                
            running_mfe = max(running_mfe, mfe_t)
            running_mae = max(running_mae, mae_t)
            
            if dt >= 60 * 1_000_000_000 and not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
                recorded_1m = True
                
            if dt >= 300 * 1_000_000_000 and not recorded_5m:
                mfe_5m[i] = running_mfe / atr
                mae_5m[i] = running_mae / atr
                term_5m[i] = ((c - px_entry) * d) / atr
                recorded_5m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
            if not recorded_5m:
                mfe_5m[i] = running_mfe / atr
                mae_5m[i] = running_mae / atr
                term_5m[i] = ((c - px_entry) * d) / atr
                
    return mfe_1m, mae_1m, term_1m, mfe_5m, mae_5m, term_5m


def main():
    t0 = time.time()
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips from slips_excursion_paths.parquet")
    
    # Re-scan to extract exact terminal prices
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning exact terminal prices for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m1, ma1, t1, m5, ma5, t5 = scan_exact_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m"] = m1
        year_cohort["mae_1m"] = ma1
        year_cohort["term_1m"] = t1
        year_cohort["mfe_5m"] = m5
        year_cohort["mae_5m"] = ma5
        year_cohort["term_5m"] = t5
        
        all_years_df.append(year_cohort)
        
    df = pd.concat(all_years_df, ignore_index=True)
    df_oos = df[df["year"].isin(OOS_YEARS)].copy()
    
    # Target state: KMeans_4 State 0
    df_filtered = df_oos[df_oos["kmeans_4_state"] == 0].copy()
    print(f"Filtered to {len(df_filtered):,} OOS flips in KMeans_4 State 0")
    
    atr_thresholds = [0.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0]
    
    # ── STUDY 1: 5m symmetric 1.0 ATR PT vs 1.0 ATR SL ──
    print(f"\n==============================================================")
    print(f"  STUDY 1: 5-Minute Symmetric Bracket (PT = 1.0, SL = 1.0)")
    print(f"==============================================================")
    print(f"  {'ATR Thresh':<12} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (ATR)':>10} {'EV (NQ $)':>11}")
    print(f"  {'-'*68}")
    
    for thresh in atr_thresholds:
        sub = df_filtered[df_filtered["entry_atr"] >= thresh]
        if len(sub) == 0:
            continue
            
        mfe = sub["mfe_5m"].to_numpy()
        mae = sub["mae_5m"].to_numpy()
        term = sub["term_5m"].to_numpy()
        atrs = sub["entry_atr"].to_numpy()
        
        wins = (mfe >= 1.0) & (mae < 1.0)
        losses = (mae >= 1.0) | ((mfe >= 1.0) & (mae >= 1.0))
        flats = ~(wins | losses)
        
        pnl_atr = np.zeros(len(sub))
        pnl_atr[wins] = 1.0
        pnl_atr[losses] = -1.0
        pnl_atr[flats] = term[flats]
        
        valid = ~np.isnan(pnl_atr) & ~np.isnan(atrs)
        if valid.any():
            ev_atr = np.mean(pnl_atr[valid])
            pnl_usd = pnl_atr * atrs * 20.0 - 10.0
            ev_usd = np.mean(pnl_usd[valid])
        else:
            ev_atr = np.nan
            ev_usd = np.nan
            
        thresh_str = "None" if thresh == 0.0 else f"> {thresh}"
        print(f"  {thresh_str:<12} {len(sub):>8,} {wins.mean():>7.1%} {losses.mean():>7.1%} {flats.mean():>7.1%} {ev_atr:>+10.3f} {ev_usd:>+11.2f}")
        
    # ── STUDY 2: 1m asymmetric 0.50 PT vs 1.50 SL ──
    print(f"\n==============================================================")
    print(f"  STUDY 2: 1-Minute Asymmetric Bracket (PT = 0.50, SL = 1.50)")
    print(f"==============================================================")
    print(f"  {'ATR Thresh':<12} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (ATR)':>10} {'EV (NQ $)':>11}")
    print(f"  {'-'*68}")
    
    for thresh in atr_thresholds:
        sub = df_filtered[df_filtered["entry_atr"] >= thresh]
        if len(sub) == 0:
            continue
            
        mfe = sub["mfe_1m"].to_numpy()
        mae = sub["mae_1m"].to_numpy()
        term = sub["term_1m"].to_numpy()
        atrs = sub["entry_atr"].to_numpy()
        
        wins = (mfe >= 0.5) & (mae < 1.5)
        losses = (mae >= 1.5) | ((mfe >= 0.5) & (mae >= 1.5))
        flats = ~(wins | losses)
        
        pnl_atr = np.zeros(len(sub))
        pnl_atr[wins] = 0.5
        pnl_atr[losses] = -1.5
        pnl_atr[flats] = term[flats]
        
        valid = ~np.isnan(pnl_atr) & ~np.isnan(atrs)
        if valid.any():
            ev_atr = np.mean(pnl_atr[valid])
            pnl_usd = pnl_atr * atrs * 20.0 - 10.0
            ev_usd = np.mean(pnl_usd[valid])
        else:
            ev_atr = np.nan
            ev_usd = np.nan
            
        thresh_str = "None" if thresh == 0.0 else f"> {thresh}"
        print(f"  {thresh_str:<12} {len(sub):>8,} {wins.mean():>7.1%} {losses.mean():>7.1%} {flats.mean():>7.1%} {ev_atr:>+10.3f} {ev_usd:>+11.2f}")
        
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()

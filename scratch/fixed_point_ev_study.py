"""Fixed-point bracket EV study on causal KMeans State 0 flips.

Evaluates whether using fixed-point targets and stops (rather than ATR-scaled ones)
resolves the dimensional distortion under volatility expansion and produces
a highly positive, robust dollar Expected Value.
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
def scan_fixed_excursions(entry_ts_arr, entry_px_arr, dir_arr,
                          ts_1s, high_1s, low_1s, close_1s):
    """Scan forward on 1s bars to calculate excursions in absolute INDEX POINTS."""
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
        if i_entry >= len(ts_1s):
            continue
            
        px_entry = entry_px_arr[i]
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
                mfe_1m[i] = running_mfe
                mae_1m[i] = running_mae
                term_1m[i] = (c - px_entry) * d
                recorded_1m = True
                
            if dt >= 300 * 1_000_000_000 and not recorded_5m:
                mfe_5m[i] = running_mfe
                mae_5m[i] = running_mae
                term_5m[i] = (c - px_entry) * d
                recorded_5m = True
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_1m[i] = running_mfe
                mae_1m[i] = running_mae
                term_1m[i] = (c - px_entry) * d
            if not recorded_5m:
                mfe_5m[i] = running_mfe
                mae_5m[i] = running_mae
                term_5m[i] = (c - px_entry) * d
                
    return mfe_1m, mae_1m, term_1m, mfe_5m, mae_5m, term_5m


def main():
    t0 = time.time()
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips.")
    
    # Re-scan to extract absolute points
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning absolute points for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m1, ma1, t1, m5, ma5, t5 = scan_fixed_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m_pt"] = m1
        year_cohort["mae_1m_pt"] = ma1
        year_cohort["term_1m_pt"] = t1
        year_cohort["mfe_5m_pt"] = m5
        year_cohort["mae_5m_pt"] = ma5
        year_cohort["term_5m_pt"] = t5
        
        all_years_df.append(year_cohort)
        
    df = pd.concat(all_years_df, ignore_index=True)
    df_oos = df[df["year"].isin(OOS_YEARS)].copy()
    
    # Target state: KMeans_4 State 0
    df_filtered = df_oos[df_oos["kmeans_4_state"] == 0].copy()
    print(f"Filtered to {len(df_filtered):,} OOS flips in KMeans_4 State 0")
    
    # Grid of fixed point brackets (NQ index points)
    fixed_targets = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
    fixed_stops = [5.0, 10.0, 15.0, 20.0, 25.0]
    
    for tf in ["1m", "5m"]:
        print(f"\n==============================================================")
        print(f"  TIMEFRAME: {tf} - FIXED-POINT BRACKETS (KMeans_4 State 0 OOS)")
        print(f"==============================================================")
        print(f"  {'PT (pts)':<10} {'SL (pts)':<10} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (pts)':>10} {'EV (NQ $)':>11}")
        print(f"  {'-'*70}")
        
        results = []
        for tgt in fixed_targets:
            for stp in fixed_stops:
                mfe = df_filtered[f"mfe_{tf}_pt"].to_numpy()
                mae = df_filtered[f"mae_{tf}_pt"].to_numpy()
                term = df_filtered[f"term_{tf}_pt"].to_numpy()
                
                wins = (mfe >= tgt) & (mae < stp)
                losses = (mae >= stp) | ((mfe >= tgt) & (mae >= stp))
                flats = ~(wins | losses)
                
                pnl_pts = np.zeros(len(df_filtered))
                pnl_pts[wins] = tgt
                pnl_pts[losses] = -stp
                pnl_pts[flats] = term[flats]
                
                valid = ~np.isnan(pnl_pts)
                if valid.any():
                    ev_pts = np.mean(pnl_pts[valid])
                    # Dollar EV: ev_pts * 20.0 - 10.0 (friction)
                    ev_usd = ev_pts * 20.0 - 10.0
                else:
                    ev_pts = np.nan
                    ev_usd = np.nan
                    
                results.append((tgt, stp, wins.mean(), losses.mean(), flats.mean(), ev_pts, ev_usd))
                
        # Sort by EV (NQ $) descending
        results.sort(key=lambda x: -x[6] if not np.isnan(x[6]) else -999)
        
        for r in results[:10]:
            print(f"  {r[0]:<10.1f} {r[1]:<10.1f} {r[2]:>7.1%} {r[3]:>7.1%} {r[4]:>7.1%} {r[5]:>+10.2f} {r[6]:>+11.2f}")
            
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()

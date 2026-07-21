"""Yearly Volatility Monotonicity & Step-by-Step Progression Study.

Tests:
1. Stability of Volatility-Lift curve across OOS years (2023, 2024, 2025, 2026)
   categorized into Low, Medium, High, Extreme ATR buckets.
2. Step-by-step progression metrics (EV, Trade count, Year-by-year PnL) for:
   Step 1: KMeans State 0 alone
   Step 2: KMeans State 0 + ATR > 15
   Step 3: KMeans State 0 + ATR > 15 + Causal HMM macro filter
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
        
        while j < len(ts_1s):
            dt = ts_1s[j] - ts_start
            if dt > 60 * 1_000_000_000:
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
                
            j += 1
            
        if j > i_entry:
            last_idx = min(j - 1, len(ts_1s) - 1)
            c = close_1s[last_idx]
            if not recorded_1m:
                mfe_1m[i] = running_mfe / atr
                mae_1m[i] = running_mae / atr
                term_1m[i] = ((c - px_entry) * d) / atr
                
    return mfe_1m, mae_1m, term_1m


def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out


def main():
    t0 = time.time()
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips from slips_excursion_paths.parquet")
    
    # Re-scan to extract exact terminal prices at 1m
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
            
        print(f"Scanning 1m terminal prices for year {y}...")
        try:
            bars = load_1s(y)
        except FileNotFoundError:
            print(f"  Skip year {y}: 1s raw parquets not found.")
            continue
            
        ts_1s = bars.index.astype("int64").to_numpy()
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        m1, ma1, t1 = scan_exact_excursions(
            year_cohort["entry_ts"].to_numpy(np.int64),
            year_cohort["entry_px"].to_numpy(np.float64),
            year_cohort["entry_atr"].to_numpy(np.float64),
            year_cohort["signal_direction"].to_numpy(np.int64),
            ts_1s, h_1s, l_1s, c_1s
        )
        
        year_cohort["mfe_1m"] = m1
        year_cohort["mae_1m"] = ma1
        year_cohort["term_1m"] = t1
        
        all_years_df.append(year_cohort)
        
    df = pd.concat(all_years_df, ignore_index=True)
    
    # Load causal states
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    states_5m = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    
    df["kmeans_4_state"] = lookup_state_causal(
        df["entry_ts"].to_numpy(np.int64),
        states_1m.index.values.astype(np.int64),
        states_1m["kmeans_4"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    df["causal_hmm_5m"] = lookup_state_causal(
        df["entry_ts"].to_numpy(np.int64),
        states_5m.index.values.astype(np.int64),
        states_5m["hmm_3"].to_numpy(np.int64),
        300 * 1_000_000_000
    )
    
    df_oos = df[df["year"].isin(OOS_YEARS)].copy()
    
    # ── PART 1: Yearly Volatility Monotonicity Study ──
    # Define ATR Buckets: Low (<=10), Mid (10-15), High (15-20), Extreme (>20)
    def assign_bucket(atr):
        if atr <= 10.0: return "Low Vol (<=10)"
        if atr <= 15.0: return "Mid Vol (10-15)"
        if atr <= 20.0: return "High Vol (15-20)"
        return "Extreme Vol (>20)"
        
    df_oos["vol_bucket"] = df_oos["entry_atr"].apply(assign_bucket)
    buckets = ["Low Vol (<=10)", "Mid Vol (10-15)", "High Vol (15-20)", "Extreme Vol (>20)"]
    
    print(f"\n==============================================================")
    print(f"  PART 1: YEARLY VOLATILITY MONOTONICITY STUDY (asymmetric 1m)")
    print(f"==============================================================")
    
    for y in OOS_YEARS:
        print(f"\n  YEAR {y}:")
        print(f"    {'ATR Bucket':<20} {'Base n':>8} {'Filt n':>8} {'Base Win%':>10} {'Filt Win%':>10} {'Lift (pp)':>10}")
        print(f"    {'-'*70}")
        
        y_df = df_oos[df_oos["year"] == y]
        for b in buckets:
            sub_base = y_df[y_df["vol_bucket"] == b]
            sub_filt = sub_base[sub_base["kmeans_4_state"] == 0]
            
            if len(sub_filt) == 0:
                print(f"    {b:<20} {len(sub_base):>8,} {0:>8,}    -")
                continue
                
            # Race simulation: PT=0.50, SL=1.50
            mfe_b = sub_base["mfe_1m"].to_numpy()
            mae_b = sub_base["mae_1m"].to_numpy()
            wins_b = (mfe_b >= 0.5) & (mae_b < 1.5)
            wr_base = wins_b.mean() * 100
            
            mfe_f = sub_filt["mfe_1m"].to_numpy()
            mae_f = sub_filt["mae_1m"].to_numpy()
            wins_f = (mfe_f >= 0.5) & (mae_f < 1.5)
            wr_filt = wins_f.mean() * 100
            
            lift = wr_filt - wr_base
            print(f"    {b:<20} {len(sub_base):>8,} {len(sub_filt):>8,} {wr_base:>9.1f}% {wr_filt:>9.1f}% {lift:>+9.1f}pp")
            
    # ── PART 2: Step-by-Step Progression Study ──
    print(f"\n==============================================================")
    print(f"  PART 2: STEP-BY-STEP PROGRESSION STUDY (OOS 2023-2026)")
    print(f"==============================================================")
    print(f"  {'Step':<45} {'Trades':>8} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (ATR)':>10} {'EV (NQ $)':>11}")
    print(f"  {'-'*100}")
    
    steps = [
        ("Step 1: KMeans State 0 alone", 
         df_oos[df_oos["kmeans_4_state"] == 0]),
        ("Step 2: KMeans State 0 + ATR > 15", 
         df_oos[(df_oos["kmeans_4_state"] == 0) & (df_oos["entry_atr"] > 15.0)]),
        ("Step 3: KMeans State 0 + ATR > 15 + HMM", 
         df_oos[(df_oos["kmeans_4_state"] == 0) & (df_oos["entry_atr"] > 15.0) & (df_oos["causal_hmm_5m"] == 2)])
    ]
    
    step_results = {}
    for s_name, sub in steps:
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
            
        print(f"  {s_name:<45} {len(sub):>8,} {wins.mean():>7.1%} {losses.mean():>7.1%} {flats.mean():>7.1%} {ev_atr:>+10.3f} {ev_usd:>+11.2f}")
        
        # Calculate year-by-year net PnL in Dollars
        y_pnls = {}
        for y in OOS_YEARS:
            y_sub = sub[sub["year"] == y]
            if len(y_sub) == 0:
                y_pnls[y] = 0.0
                continue
            mfe_y = y_sub["mfe_1m"].to_numpy()
            mae_y = y_sub["mae_1m"].to_numpy()
            term_y = y_sub["term_1m"].to_numpy()
            atrs_y = y_sub["entry_atr"].to_numpy()
            
            wins_y = (mfe_y >= 0.5) & (mae_y < 1.5)
            losses_y = (mae_y >= 1.5) | ((mfe_y >= 0.5) & (mae_y >= 1.5))
            flats_y = ~(wins_y | losses_y)
            
            pnl_atr_y = np.zeros(len(y_sub))
            pnl_atr_y[wins_y] = 0.5
            pnl_atr_y[losses_y] = -1.5
            pnl_atr_y[flats_y] = term_y[flats_y]
            
            pnl_usd_y = pnl_atr_y * atrs_y * 20.0 - 10.0
            y_pnls[y] = pnl_usd_y[~np.isnan(pnl_usd_y)].sum()
        step_results[s_name] = y_pnls
        
    print(f"\n==============================================================")
    print(f"  PART 3: YEAR-BY-YEAR DOLLAR PNL EVOLUTION")
    print(f"==============================================================")
    print(f"  {'Step':<45} {'2023 PnL':>11} {'2024 PnL':>11} {'2025 PnL':>11} {'2026 PnL':>11} {'Total OOS':>12}")
    print(f"  {'-'*100}")
    for s_name, y_pnls in step_results.items():
        total_pnl = sum(y_pnls.values())
        print(f"  {s_name:<45} {y_pnls[2023]:>+10.0f}$ {y_pnls[2024]:>+10.0f}$ {y_pnls[2025]:>+10.0f}$ {y_pnls[2026]:>+10.0f}$ {total_pnl:>+11.0f}$")
        
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()

"""Evaluate exact Expected Value of strictly causal Layered HMM Raw Flips."""
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
            if dt > 300 * 1_000_000_000:  # up to 5m
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
    # Load raw flips
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    print(f"Loaded {len(df_ex):,} flips from slips_excursion_paths.parquet")
    
    # Load fresh, strictly causal states
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    states_5m = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    
    # Look up 1m tactical state causally
    df_ex["causal_hmm_1m"] = lookup_state_causal(
        df_ex["entry_ts"].to_numpy(np.int64),
        states_1m.index.values.astype(np.int64),
        states_1m["hmm_4"].to_numpy(np.int64),
        60 * 1_000_000_000
    )
    
    # Look up 5m macro state causally
    df_ex["causal_hmm_5m"] = lookup_state_causal(
        df_ex["entry_ts"].to_numpy(np.int64),
        states_5m.index.values.astype(np.int64),
        states_5m["hmm_3"].to_numpy(np.int64),
        300 * 1_000_000_000
    )
    
    # Filter for Causal Layering: 1m HMM state 3 AND 5m HMM state 2 in OOS
    df_oos = df_ex[df_ex["year"].isin(OOS_YEARS)].copy()
    df_layered = df_oos[(df_oos["causal_hmm_1m"] == 3) & (df_oos["causal_hmm_5m"] == 2)].copy()
    
    n_layered = len(df_layered)
    print(f"\nFiltered OOS flips (Layered HMM: hmm_4==3 + hmm_3==2): n = {n_layered:,} "
          f"({100*n_layered/len(df_oos):.2f}% of all OOS flips)")
    
    if n_layered == 0:
        print("NO trades filtered under strictly causal HMM parameters.")
        return
        
    # Re-scan to extract exact terminal prices
    all_years_df = []
    for y in sorted(df_layered["year"].unique()):
        year_cohort = df_layered[df_layered["year"] == y].copy()
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
        
    df_res = pd.concat(all_years_df, ignore_index=True)
    
    targets = [0.5, 0.75, 1.0, 1.2, 1.5, 1.8, 2.0]
    stops = [0.5, 0.75, 1.0, 1.2, 1.5]
    
    for tf in ["1m", "5m"]:
        print(f"\n==============================================================")
        print(f"  TIMEFRAME: {tf} - 100% CAUSAL LAYERED HMM EV (hmm_4==3 + hmm_3==2)")
        print(f"==============================================================")
        print(f"  {'PT':<5} {'SL':<5} {'Win%':>8} {'Loss%':>8} {'Flat%':>8} {'EV (ATR)':>12} {'EV (NQ $)':>12}")
        print(f"  {'-'*70}")
        
        results = []
        for tgt in targets:
            for stp in stops:
                mfe = df_res[f"mfe_{tf}"].to_numpy()
                mae = df_res[f"mae_{tf}"].to_numpy()
                term = df_res[f"term_{tf}"].to_numpy()
                atrs = df_res["entry_atr"].to_numpy()
                
                wins = (mfe >= tgt) & (mae < stp)
                losses = (mae >= stp) | ((mfe >= tgt) & (mae >= stp))
                flats = ~(wins | losses)
                
                pnl_atr = np.zeros(len(df_res))
                pnl_atr[wins] = tgt
                pnl_atr[losses] = -stp
                pnl_atr[flats] = term[flats]
                
                valid = ~np.isnan(pnl_atr) & ~np.isnan(atrs)
                if valid.any():
                    ev_atr = np.mean(pnl_atr[valid])
                    pnl_usd = pnl_atr * atrs * 20.0 - 10.0
                    ev_usd = np.mean(pnl_usd[valid])
                else:
                    ev_atr = np.nan
                    ev_usd = np.nan
                
                results.append((tgt, stp, wins.mean(), losses.mean(), flats.mean(), ev_atr, ev_usd))
                
        results.sort(key=lambda x: -x[5] if not np.isnan(x[5]) else -999)
        
        for r in results[:10]:
            print(f"  {r[0]:<5.2f} {r[1]:<5.2f} {r[2]:>7.1%} {r[3]:>7.1%} {r[4]:>7.1%} {r[5]:>+12.3f} {r[6]:>+12.2f}")
            
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")


if __name__ == "__main__":
    main()

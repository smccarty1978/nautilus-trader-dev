"""Calculate drawdowns and equity curves for the three steps."""
import pandas as pd
import numpy as np

def main():
    df_ex = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    
    # Load exact 1m terminal prices from the yearly vol monotonicity study
    # We can rebuild the step series and calculate cumulative PnL and Max Drawdown.
    # To do this correctly, we will load raw flips, run the scan or load the saved columns.
    # Wait, the script scratch/yearly_vol_monotonicity_and_step_study.py has the scanning logic.
    # Let's write a script that does the same scans and then calculates drawdown.
    
    ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2027)}
    ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
    OOS_YEARS = (2023, 2024, 2025, 2026)
    
    def load_1s(year):
        import os
        parts = []
        for y in (year - 1, year, year + 1):
            p = ONE_S.get(y)
            if p and os.path.exists(p):
                parts.append(pd.read_parquet(p, columns=["high", "low", "close"]))
        bars = pd.concat(parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars

    import os
    from numba import njit
    
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

    # Re-scan to extract exact terminal prices
    all_years_df = []
    for y in sorted(df_ex["year"].unique()):
        year_cohort = df_ex[df_ex["year"] == y].copy()
        if len(year_cohort) == 0:
            continue
        try:
            bars = load_1s(y)
        except FileNotFoundError:
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
    
    df_oos = df[df["year"].isin(OOS_YEARS)].copy().sort_values("entry_ts")
    
    steps = [
        ("Step 1: KMeans State 0 alone", 
         df_oos[df_oos["kmeans_4_state"] == 0].copy()),
        ("Step 2: KMeans State 0 + ATR > 15", 
         df_oos[(df_oos["kmeans_4_state"] == 0) & (df_oos["entry_atr"] > 15.0)].copy()),
        ("Step 3: KMeans State 0 + ATR > 15 + HMM", 
         df_oos[(df_oos["kmeans_4_state"] == 0) & (df_oos["entry_atr"] > 15.0) & (df_oos["causal_hmm_5m"] == 2)].copy())
    ]
    
    print("\nDRAWDOWN AND PERFORMANCE ANALYSIS:")
    print("-" * 80)
    for s_name, sub in steps:
        if len(sub) == 0:
            print(f"{s_name}: No trades")
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
        
        pnl_usd = pnl_atr * atrs * 20.0 - 10.0
        pnl_usd = pnl_usd[~np.isnan(pnl_usd)]
        
        # Cumulative PnL
        cum_pnl = np.cumsum(pnl_usd)
        
        # Max Drawdown
        running_max = np.maximum.accumulate(cum_pnl)
        running_max = np.maximum(running_max, 0.0) # Start from 0 peak
        drawdown = running_max - cum_pnl
        max_dd = np.max(drawdown)
        
        # Final PnL
        final_pnl = cum_pnl[-1]
        
        print(f"{s_name:<45}")
        print(f"  Trades:         {len(sub):,}")
        print(f"  Final PnL ($):  {final_pnl:>+11.2f}$")
        print(f"  Max DD ($):     {max_dd:>11.2f}$")
        print(f"  Profit Factor:  {np.sum(pnl_usd[pnl_usd > 0]) / -np.sum(pnl_usd[pnl_usd < 0]):.2f}" if np.sum(pnl_usd[pnl_usd < 0]) < 0 else "  Profit Factor: N/A")
        print()

if __name__ == "__main__":
    main()

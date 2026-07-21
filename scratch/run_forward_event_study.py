"""Run forward return event study for flip entry vs in-regime control vs fully random baselines."""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
os.chdir(PROJECT_ROOT)

ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2027)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
B_ITER = 10000  # 10k iterations for robust significance
SEED = 42
NQ_MULT = 20.0
HORIZONS_MIN = [1, 2, 5, 15, 30, 60, 120]
HORIZONS_SEC = [h * 60 for h in HORIZONS_MIN]

@njit
def scan_horizon_excursions(px_entry, d, ts_1s, high_1s, low_1s, close_1s, idx_start, horizons_sec):
    n_h = len(horizons_sec)
    mfe_pts = np.zeros(n_h)
    mae_pts = np.zeros(n_h)
    ret_pts = np.zeros(n_h)
    
    if len(ts_1s) == 0:
        return ret_pts, mfe_pts, mae_pts
        
    t_start = ts_1s[idx_start]
    
    j = idx_start
    running_mfe = 0.0
    running_mae = 0.0
    
    h_idx = 0
    while j < len(ts_1s) and h_idx < n_h:
        t_curr = ts_1s[j]
        dt = t_curr - t_start
        
        # Excursion update
        h, l = high_1s[j], low_1s[j]
        if d == 1:
            mfe_t = h - px_entry
            mae_t = px_entry - l
        else:
            mfe_t = px_entry - l
            mae_t = h - px_entry
            
        running_mfe = max(running_mfe, mfe_t)
        running_mae = max(running_mae, mae_t)
        
        # Check horizons
        h_limit_ns = horizons_sec[h_idx] * 1_000_000_000
        while dt >= h_limit_ns and h_idx < n_h:
            mfe_pts[h_idx] = running_mfe
            mae_pts[h_idx] = running_mae
            ret_pts[h_idx] = (close_1s[j] - px_entry) * d
            h_idx += 1
            if h_idx < n_h:
                h_limit_ns = horizons_sec[h_idx] * 1_000_000_000
                
        j += 1
        
    # Fill remaining horizons if we hit end of data
    while h_idx < n_h:
        last_j = min(j - 1, len(ts_1s) - 1)
        mfe_pts[h_idx] = running_mfe
        mae_pts[h_idx] = running_mae
        ret_pts[h_idx] = (close_1s[last_j] - px_entry) * d
        h_idx += 1
        
    return ret_pts, mfe_pts, mae_pts

@njit
def precalc_raw_metrics_batch(px_entries, directions, idxs, ts_1s, high_1s, low_1s, close_1s, horizons_sec):
    n = len(px_entries)
    n_h = len(horizons_sec)
    rets = np.zeros((n, n_h))
    mfes = np.zeros((n, n_h))
    maes = np.zeros((n, n_h))
    for i in range(n):
        r, f, a = scan_horizon_excursions(
            px_entries[i], directions[i], ts_1s, high_1s, low_1s, close_1s, idxs[i], horizons_sec
        )
        rets[i] = r
        mfes[i] = f
        maes[i] = a
    return rets, mfes, maes

def load_1s(year):
    p = ONE_S.get(year)
    if p and Path(p).exists():
        bars = pd.read_parquet(p, columns=["high", "low", "close", "open"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        return bars
    raise FileNotFoundError(f"1s NQ file not found for year {year}")

def run_forward_study():
    t0 = time.time()
    
    # 1. Load Bar-1 Confirmed flips and extract Close-Confirmed cohort
    df_flips = pd.read_parquet("studies/regime_classification/results/flips_excursion_paths.parquet")
    df_bar1 = df_flips[df_flips["bar1_confirm"] == 1].copy()
    
    df_dedup = df_bar1.groupby("entry_ts").agg({
        "entry_px_bar1": "first",
        "entry_px_flip": "first",
        "exit_ts": "first",
        "exit_px": "first",
        "signal_direction": "first",
        "entry_atr": "first",
        "year": "first"
    }).reset_index()
    
    df_dedup["bar1_close_confirmed"] = ((df_dedup["entry_px_bar1"] - df_dedup["entry_px_flip"]) * df_dedup["signal_direction"] > 0).astype(int)
    df_cohort = df_dedup[df_dedup["bar1_close_confirmed"] == 1].copy()
    print(f"Loaded {len(df_cohort):,} Close-Confirmed episodes.")
    
    # Load tactical 1m HMM states to lookup ATR at entry t0 (Bar1 close)
    print("Loading 1m states...")
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    state_ts_ns = states_1m.index.values.astype(np.int64)
    state_atrs = states_1m["atr_1m"].to_numpy(np.float64)
    
    def lookup_atr(target_ts):
        idx = np.searchsorted(state_ts_ns, target_ts, side="right") - 1
        if 0 <= idx < len(state_ts_ns):
            return state_atrs[idx]
        return 15.0  # default fallback
        
    years = sorted(df_cohort["year"].unique())
    all_years_results = []
    
    for y in years:
        df_y = df_cohort[df_cohort["year"] == y].copy().reset_index(drop=True)
        if len(df_y) == 0:
            continue
            
        print(f"\n==================================================")
        print(f"Processing year {y} (Episodes: {len(df_y)})...")
        print(f"==================================================")
        
        try:
            bars = load_1s(y)
        except Exception as e:
            print(f"Error loading 1s data for {y}: {e}")
            continue
            
        ts_1s = bars.index.values.astype("int64")
        o_1s = bars["open"].to_numpy(np.float64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        c_1s = bars["close"].to_numpy(np.float64)
        
        # Precompute 1m boundaries
        t_first = ts_1s[0]
        t_last = ts_1s[-1]
        t_boundaries = np.arange(
            ((t_first + 59_999_999_999) // 60_000_000_000) * 60_000_000_000,
            (t_last // 60_000_000_000) * 60_000_000_000,
            60_000_000_000
        )
        bound_indices = np.searchsorted(ts_1s, t_boundaries, side="left")
        
        # Sift control pool candidates
        flip_starts = df_dedup[df_dedup["year"] == y]["entry_ts"].to_numpy(np.int64)
        flip_ends = df_dedup[df_dedup["year"] == y]["exit_ts"].to_numpy(np.int64)
        flip_dirs = df_dedup[df_dedup["year"] == y]["signal_direction"].to_numpy(np.int64)
        
        sort_idx = np.argsort(flip_starts)
        flip_starts = flip_starts[sort_idx]
        flip_ends = flip_ends[sort_idx]
        flip_dirs = flip_dirs[sort_idx]
        
        print("Sifting control pools...")
        control_candidates = []
        for b_idx in range(len(t_boundaries) - 1):
            t_open = t_boundaries[b_idx]
            t_close = t_open + 60_000_000_000
            
            idx = np.searchsorted(flip_starts, t_close, side="right") - 1
            if 0 <= idx < len(flip_starts):
                start = flip_starts[idx]
                end = flip_ends[idx]
                d = flip_dirs[idx]
                
                # Check mid-regime constraint: >= 10m from start and <= 10m from end
                if start + 600_000_000_000 <= t_close <= end - 600_000_000_000:
                    idx_open = bound_indices[b_idx]
                    idx_close = bound_indices[b_idx + 1]
                    if idx_open < len(ts_1s) and idx_close < len(ts_1s):
                        px_open = o_1s[idx_open]
                        px_close = c_1s[idx_close]
                        # Shape condition: confirm bar shape
                        if (px_close - px_open) * d > 0:
                            control_candidates.append({
                                "t0": t_close,
                                "px_entry": px_close,
                                "direction": d,
                                "idx_1s": idx_close,
                                "minute_of_day": (t_close // 60_000_000_000) % 1440
                            })
                            
        print(f"Generated {len(control_candidates):,} control candidates.")
        
        # Generate fully random pool candidates
        print("Sifting fully random candidates...")
        np.random.seed(SEED)
        rand_indices = np.random.choice(len(t_boundaries) - 2, size=30000, replace=False)
        rand_candidates = []
        for b_idx in rand_indices:
            t_open = t_boundaries[b_idx]
            t_close = t_open + 60_000_000_000
            idx_close = bound_indices[b_idx + 1]
            if idx_close < len(ts_1s):
                px_close = c_1s[idx_close]
                rand_candidates.append({
                    "t0": t_close,
                    "px_entry": px_close,
                    "idx_1s": idx_close,
                    "minute_of_day": (t_close // 60_000_000_000) % 1440
                })
        print(f"Generated {len(rand_candidates):,} random candidates.")
        
        # Pre-calculate excursions in points
        print("Pre-calculating Treatment excursions in points...")
        n_ep = len(df_y)
        treat_px = df_y["entry_px_bar1"].to_numpy(np.float64)
        treat_dir = df_y["signal_direction"].to_numpy(np.int64)
        treat_ts = df_y["entry_ts"].to_numpy(np.int64) + 60_000_000_000  # Bar-1 close time
        
        treat_idx = np.searchsorted(ts_1s, treat_ts, side="left")
        # Ensure indices inside array bounds
        treat_idx = np.clip(treat_idx, 0, len(ts_1s) - 1)
        
        treat_rets_raw, treat_mfes_raw, treat_maes_raw = precalc_raw_metrics_batch(
            treat_px, treat_dir, treat_idx, ts_1s, h_1s, l_1s, c_1s, np.array(HORIZONS_SEC, dtype=np.int64)
        )
        
        # Look up exact ATR at t0 (Bar1 close) for each treatment
        treat_atrs = np.array([lookup_atr(t) for t in treat_ts])
        
        # Scale treatment metrics
        treat_rets = np.zeros((n_ep, len(HORIZONS_MIN)))
        treat_mfes = np.zeros((n_ep, len(HORIZONS_MIN)))
        treat_maes = np.zeros((n_ep, len(HORIZONS_MIN)))
        for i in range(n_ep):
            atr = treat_atrs[i]
            treat_rets[i] = treat_rets_raw[i] / atr
            treat_mfes[i] = treat_mfes_raw[i] / atr
            treat_maes[i] = treat_maes_raw[i] / atr
            
        # Pre-calculate raw excursions for Control candidates
        print("Pre-calculating Control raw excursions in points...")
        ctrl_px = np.array([c["px_entry"] for c in control_candidates])
        ctrl_dir = np.array([c["direction"] for c in control_candidates])
        ctrl_idx = np.array([c["idx_1s"] for c in control_candidates])
        
        ctrl_rets_raw, ctrl_mfes_raw, ctrl_maes_raw = precalc_raw_metrics_batch(
            ctrl_px, ctrl_dir, ctrl_idx, ts_1s, h_1s, l_1s, c_1s, np.array(HORIZONS_SEC, dtype=np.int64)
        )
        
        # Pre-calculate raw excursions for Random candidates (assume direction 1, will sign dynamically)
        print("Pre-calculating Random raw excursions in points...")
        rand_px = np.array([r["px_entry"] for r in rand_candidates])
        rand_idx = np.array([r["idx_1s"] for r in rand_candidates])
        
        rand_rets_raw, rand_mfes_raw, rand_maes_raw = precalc_raw_metrics_batch(
            rand_px, np.ones(len(rand_px), dtype=np.int64), rand_idx, ts_1s, h_1s, l_1s, c_1s, np.array(HORIZONS_SEC, dtype=np.int64)
        )
        
        # Fast matching structure
        ctrl_by_tod = {d: {m: [] for m in range(1440)} for d in [-1, 1]}
        for idx, c in enumerate(control_candidates):
            ctrl_by_tod[c["direction"]][c["minute_of_day"]].append(idx)
            
        rand_by_tod = {m: [] for m in range(1440)}
        for idx, r in enumerate(rand_candidates):
            rand_by_tod[r["minute_of_day"]].append(idx)
            
        # Draw 100 controls and 100 rands per treatment episode and store their scaled metrics
        print("Building matched pools (100 draws per treatment)...")
        match_rng = np.random.RandomState(SEED)
        
        ctrl_rets_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        ctrl_mfes_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        ctrl_maes_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        
        rand_rets_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        rand_mfes_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        rand_maes_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        
        ctrl_usd_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        rand_usd_draws = np.zeros((n_ep, 100, len(HORIZONS_MIN)))
        
        for i in range(n_ep):
            t_entry = treat_ts[i]
            tod = (t_entry // 60_000_000_000) % 1440
            d = treat_dir[i]
            atr = treat_atrs[i]
            
            # Find control indices matching direction and within +/-30m of tod
            ctrl_pool_idx = []
            for offset in range(-30, 31):
                offset_tod = (tod + offset) % 1440
                ctrl_pool_idx.extend(ctrl_by_tod[d][offset_tod])
                
            if len(ctrl_pool_idx) == 0:
                ctrl_pool_idx = [idx for idx, c in enumerate(control_candidates) if c["direction"] == d]
                
            # Find random indices within +/-30m of tod
            rand_pool_idx = []
            for offset in range(-30, 31):
                offset_tod = (tod + offset) % 1440
                rand_pool_idx.extend(rand_by_tod[offset_tod])
                
            if len(rand_pool_idx) == 0:
                rand_pool_idx = list(range(len(rand_candidates)))
                
            # Draw 100
            drawn_ctrl_indices = match_rng.choice(ctrl_pool_idx, size=100, replace=True)
            drawn_rand_indices = match_rng.choice(rand_pool_idx, size=100, replace=True)
            
            # Extract metrics and scale by treatment ATR
            ctrl_rets_draws[i] = ctrl_rets_raw[drawn_ctrl_indices] / atr
            ctrl_mfes_draws[i] = ctrl_mfes_raw[drawn_ctrl_indices] / atr
            ctrl_maes_draws[i] = ctrl_maes_raw[drawn_ctrl_indices] / atr
            ctrl_usd_draws[i] = ctrl_rets_raw[drawn_ctrl_indices] * NQ_MULT
            
            # Random candidate raw excursions are signed dynamically based on treatment direction d
            raw_r_rets = rand_rets_raw[drawn_rand_indices]
            raw_r_mfes = rand_mfes_raw[drawn_rand_indices]
            raw_r_maes = rand_maes_raw[drawn_rand_indices]
            
            if d == 1:
                rand_rets_draws[i] = raw_r_rets / atr
                rand_mfes_draws[i] = raw_r_mfes / atr
                rand_maes_draws[i] = raw_r_maes / atr
                rand_usd_draws[i] = raw_r_rets * NQ_MULT
            else:
                rand_rets_draws[i] = -raw_r_rets / atr
                rand_mfes_draws[i] = raw_r_maes / atr
                rand_maes_draws[i] = raw_r_mfes / atr
                rand_usd_draws[i] = -raw_r_rets * NQ_MULT
                
        # 5. Group by Cohorts and run Block Bootstrap
        print("Grouping by cohorts and executing Block Bootstrap...")
        
        cohorts = {
            "ALL": df_y.index.values,
            "LONG": np.where(df_y["signal_direction"] == 1)[0],
            "SHORT": np.where(df_y["signal_direction"] == -1)[0]
        }
        
        year_cohort_results = {}
        
        for c_name, c_idx in cohorts.items():
            n_sub = len(c_idx)
            if n_sub == 0:
                print(f"  Cohort {c_name} has 0 episodes in year {y}, skipping.")
                continue
                
            # Sliced Treatment arrays
            t_rets_sub = treat_rets[c_idx]
            t_mfes_sub = treat_mfes[c_idx]
            t_maes_sub = treat_maes[c_idx]
            t_usd_sub = treat_rets_raw[c_idx] * NQ_MULT
            
            # Sliced draws arrays
            c_rets_draws_sub = ctrl_rets_draws[c_idx]
            c_mfes_draws_sub = ctrl_mfes_draws[c_idx]
            c_maes_draws_sub = ctrl_maes_draws[c_idx]
            c_usd_draws_sub = ctrl_usd_draws[c_idx]
            
            r_rets_draws_sub = rand_rets_draws[c_idx]
            r_mfes_draws_sub = rand_mfes_draws[c_idx]
            r_maes_draws_sub = rand_maes_draws[c_idx]
            r_usd_draws_sub = rand_usd_draws[c_idx]
            
            # Extract date for Calendar Day block bootstrap
            dates_sub = pd.to_datetime(df_y["entry_ts"].iloc[c_idx], unit="ns").dt.date.values
            unique_days_sub = sorted(np.unique(dates_sub))
            day_to_indices_sub = {d: np.where(dates_sub == d)[0] for d in unique_days_sub}
            day_list_sub = list(unique_days_sub)
            n_days_sub = len(day_list_sub)
            
            # Bootstrap loops
            boot_treat_rets = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_treat_asym = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_treat_usd = np.zeros((B_ITER, len(HORIZONS_MIN)))
            
            boot_ctrl_rets = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_ctrl_asym = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_ctrl_usd = np.zeros((B_ITER, len(HORIZONS_MIN)))
            
            boot_rand_rets = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_rand_asym = np.zeros((B_ITER, len(HORIZONS_MIN)))
            boot_rand_usd = np.zeros((B_ITER, len(HORIZONS_MIN)))
            
            boot_rng = np.random.RandomState(SEED)
            
            for b in range(B_ITER):
                # Resample days with replacement
                resample_days = boot_rng.choice(day_list_sub, size=n_days_sub, replace=True)
                # Concatenate local indices
                resample_local_idx = np.concatenate([day_to_indices_sub[d] for d in resample_days])
                
                # Mean metrics of Treatment
                boot_treat_rets[b] = t_rets_sub[resample_local_idx].mean(axis=0)
                boot_treat_asym[b] = (t_mfes_sub[resample_local_idx] - t_maes_sub[resample_local_idx]).mean(axis=0)
                boot_treat_usd[b] = t_usd_sub[resample_local_idx].mean(axis=0)
                
                # Draw control index for each resampled event
                draw_idx = boot_rng.randint(0, 100, size=len(resample_local_idx))
                
                c_rets = c_rets_draws_sub[resample_local_idx, draw_idx]
                c_mfes = c_mfes_draws_sub[resample_local_idx, draw_idx]
                c_maes = c_maes_draws_sub[resample_local_idx, draw_idx]
                c_usd = c_usd_draws_sub[resample_local_idx, draw_idx]
                
                boot_ctrl_rets[b] = c_rets.mean(axis=0)
                boot_ctrl_asym[b] = (c_mfes - c_maes).mean(axis=0)
                boot_ctrl_usd[b] = c_usd.mean(axis=0)
                
                # Draw random index
                r_rets = r_rets_draws_sub[resample_local_idx, draw_idx]
                r_mfes = r_mfes_draws_sub[resample_local_idx, draw_idx]
                r_maes = r_maes_draws_sub[resample_local_idx, draw_idx]
                r_usd = r_usd_draws_sub[resample_local_idx, draw_idx]
                
                boot_rand_rets[b] = r_rets.mean(axis=0)
                boot_rand_asym[b] = (r_mfes - r_maes).mean(axis=0)
                boot_rand_usd[b] = r_usd.mean(axis=0)
                
            res_sub = {
                "n": n_sub,
                "treat_rets": t_rets_sub.mean(axis=0),
                "treat_asym": (t_mfes_sub - t_maes_sub).mean(axis=0),
                "treat_usd": t_usd_sub.mean(axis=0),
                
                "ctrl_rets_mean": boot_ctrl_rets.mean(axis=0),
                "ctrl_asym_mean": boot_ctrl_asym.mean(axis=0),
                "ctrl_usd_mean": boot_ctrl_usd.mean(axis=0),
                
                "rand_rets_mean": boot_rand_rets.mean(axis=0),
                "rand_asym_mean": boot_rand_asym.mean(axis=0),
                "rand_usd_mean": boot_rand_usd.mean(axis=0),
                
                # Distributions to compute significance percentiles
                "boot_ctrl_rets": boot_ctrl_rets,
                "boot_ctrl_asym": boot_ctrl_asym,
                "boot_rand_rets": boot_rand_rets,
                "boot_rand_asym": boot_rand_asym
            }
            year_cohort_results[c_name] = res_sub
            
        all_years_results.append({
            "year": y,
            "cohorts": year_cohort_results
        })
        
        # Print tables for ALL cohort immediately
        print_cohort_table(year_cohort_results["ALL"], f"YEAR {y} - ALL COHORT")
        if "LONG" in year_cohort_results:
            print_cohort_table(year_cohort_results["LONG"], f"YEAR {y} - LONG ONLY")
        if "SHORT" in year_cohort_results:
            print_cohort_table(year_cohort_results["SHORT"], f"YEAR {y} - SHORT ONLY")
            
    # Compute and print Pooled results
    print("\n" + "="*60)
    print("  COMPUTING POOLED RESULTS ACROSS ALL OOS/IS YEARS (2020-2026)")
    print("="*60)
    
    pooled_results = compute_pooled_cohorts(all_years_results)
    
    for c_name, res_sub in pooled_results.items():
        print_cohort_table(res_sub, f"POOLED ALL YEARS (2020-2026) - {c_name} COHORT")
        
    # Save the detailed summary metrics for writing the report
    save_results_to_files(pooled_results, all_years_results)
    
    print(f"\n[done] Total runtime: {(time.time() - t0)/60:.2f} min")

def print_cohort_table(res, label):
    print(f"\n=== {label} (Episodes: {res['n']}) ===")
    print(f"{'Horizon':<8} | {'Treat Drift':<12} | {'Ctrl Drift':<12} | {'Treat Pct':<9} | {'Rand Drift':<12} | {'Treat Asym':<12} | {'Ctrl Asym':<12} | {'Asym Pct':<9} | {'Treat USD':<11} | {'Ctrl USD':<11}")
    print("-" * 128)
    
    for h_idx, h_min in enumerate(HORIZONS_MIN):
        t_drift = res["treat_rets"][h_idx]
        c_drift = res["ctrl_rets_mean"][h_idx]
        r_drift = res["rand_rets_mean"][h_idx]
        t_asym = res["treat_asym"][h_idx]
        c_asym = res["ctrl_asym_mean"][h_idx]
        
        # Percentile of treatment drift and asymmetry relative to control
        c_drift_boot = res["boot_ctrl_rets"][:, h_idx]
        c_asym_boot = res["boot_ctrl_asym"][:, h_idx]
        pct_drift = (c_drift_boot < t_drift).mean() * 100
        pct_asym = (c_asym_boot < t_asym).mean() * 100
        
        t_usd = res["treat_usd"][h_idx]
        c_usd = res["ctrl_usd_mean"][h_idx]
        
        print(f"{h_min:<5} min | {t_drift:>+12.4f} | {c_drift:>+12.4f} | {pct_drift:>7.1f}% | {r_drift:>+12.4f} | {t_asym:>+12.4f} | {c_asym:>+12.4f} | {pct_asym:>7.1f}% | ${t_usd:>+9.2f} | ${c_usd:>+9.2f}")

def compute_pooled_cohorts(all_years_results):
    pooled = {}
    for c_name in ["ALL", "LONG", "SHORT"]:
        # Find years that have this cohort
        valid_years = [y_res for y_res in all_years_results if c_name in y_res["cohorts"]]
        if len(valid_years) == 0:
            continue
            
        weights = np.array([y_res["cohorts"][c_name]["n"] for y_res in valid_years])
        total_n = weights.sum()
        weights_norm = weights / total_n
        
        n_h = len(HORIZONS_MIN)
        p_treat_rets = np.zeros(n_h)
        p_treat_asym = np.zeros(n_h)
        p_treat_usd = np.zeros(n_h)
        p_ctrl_rets = np.zeros(n_h)
        p_ctrl_asym = np.zeros(n_h)
        p_ctrl_usd = np.zeros(n_h)
        p_rand_rets = np.zeros(n_h)
        p_rand_asym = np.zeros(n_h)
        p_rand_usd = np.zeros(n_h)
        
        boot_ctrl_rets = np.zeros((B_ITER, n_h))
        boot_ctrl_asym = np.zeros((B_ITER, n_h))
        boot_rand_rets = np.zeros((B_ITER, n_h))
        boot_rand_asym = np.zeros((B_ITER, n_h))
        
        for h_idx in range(n_h):
            p_treat_rets[h_idx] = sum(y_res["cohorts"][c_name]["treat_rets"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            p_treat_asym[h_idx] = sum(y_res["cohorts"][c_name]["treat_asym"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            p_treat_usd[h_idx] = sum(y_res["cohorts"][c_name]["treat_usd"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            
            p_ctrl_rets[h_idx] = sum(y_res["cohorts"][c_name]["ctrl_rets_mean"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            p_ctrl_asym[h_idx] = sum(y_res["cohorts"][c_name]["ctrl_asym_mean"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            p_ctrl_usd[h_idx] = sum(y_res["cohorts"][c_name]["ctrl_usd_mean"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            
            p_rand_rets[h_idx] = sum(y_res["cohorts"][c_name]["rand_rets_mean"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            p_rand_asym[h_idx] = sum(y_res["cohorts"][c_name]["rand_asym_mean"][h_idx] * w for y_res, w in zip(valid_years, weights_norm))
            
            # Weighted bootstrap draws combination
            for b in range(B_ITER):
                boot_ctrl_rets[b, h_idx] = sum(y_res["cohorts"][c_name]["boot_ctrl_rets"][b, h_idx] * w for y_res, w in zip(valid_years, weights_norm))
                boot_ctrl_asym[b, h_idx] = sum(y_res["cohorts"][c_name]["boot_ctrl_asym"][b, h_idx] * w for y_res, w in zip(valid_years, weights_norm))
                boot_rand_rets[b, h_idx] = sum(y_res["cohorts"][c_name]["boot_rand_rets"][b, h_idx] * w for y_res, w in zip(valid_years, weights_norm))
                boot_rand_asym[b, h_idx] = sum(y_res["cohorts"][c_name]["boot_rand_asym"][b, h_idx] * w for y_res, w in zip(valid_years, weights_norm))
                
        pooled[c_name] = {
            "n": total_n,
            "treat_rets": p_treat_rets,
            "treat_asym": p_treat_asym,
            "treat_usd": p_treat_usd,
            "ctrl_rets_mean": p_ctrl_rets,
            "ctrl_asym_mean": p_ctrl_asym,
            "ctrl_usd_mean": p_ctrl_usd,
            "rand_rets_mean": p_rand_rets,
            "rand_asym_mean": p_rand_asym,
            "boot_ctrl_rets": boot_ctrl_rets,
            "boot_ctrl_asym": boot_ctrl_asym,
            "boot_rand_rets": boot_rand_rets,
            "boot_rand_asym": boot_rand_asym
        }
    return pooled

def save_results_to_files(pooled, all_years_results):
    os.makedirs("studies/forward_return/results", exist_ok=True)
    
    rows = []
    # Save pooled first
    for c_name, res in pooled.items():
        for h_idx, h_min in enumerate(HORIZONS_MIN):
            t_drift = res["treat_rets"][h_idx]
            c_drift = res["ctrl_rets_mean"][h_idx]
            r_drift = res["rand_rets_mean"][h_idx]
            t_asym = res["treat_asym"][h_idx]
            c_asym = res["ctrl_asym_mean"][h_idx]
            
            c_drift_boot = res["boot_ctrl_rets"][:, h_idx]
            c_asym_boot = res["boot_ctrl_asym"][:, h_idx]
            pct_drift = (c_drift_boot < t_drift).mean() * 100
            pct_asym = (c_asym_boot < t_asym).mean() * 100
            
            t_usd = res["treat_usd"][h_idx]
            c_usd = res["ctrl_usd_mean"][h_idx]
            
            rows.append({
                "scope": "pooled",
                "year": 0,
                "cohort": c_name,
                "horizon_min": h_min,
                "n": res["n"],
                "treat_drift_atr": t_drift,
                "ctrl_drift_atr": c_drift,
                "rand_drift_atr": r_drift,
                "treat_asym_atr": t_asym,
                "ctrl_asym_atr": c_asym,
                "pct_drift": pct_drift,
                "pct_asym": pct_asym,
                "treat_usd": t_usd,
                "ctrl_usd": c_usd
            })
            
    # Save yearly
    for y_res in all_years_results:
        y = y_res["year"]
        for c_name, res in y_res["cohorts"].items():
            for h_idx, h_min in enumerate(HORIZONS_MIN):
                t_drift = res["treat_rets"][h_idx]
                c_drift = res["ctrl_rets_mean"][h_idx]
                r_drift = res["rand_rets_mean"][h_idx]
                t_asym = res["treat_asym"][h_idx]
                c_asym = res["ctrl_asym_mean"][h_idx]
                
                c_drift_boot = res["boot_ctrl_rets"][:, h_idx]
                c_asym_boot = res["boot_ctrl_asym"][:, h_idx]
                pct_drift = (c_drift_boot < t_drift).mean() * 100
                pct_asym = (c_asym_boot < t_asym).mean() * 100
                
                t_usd = res["treat_usd"][h_idx]
                c_usd = res["ctrl_usd_mean"][h_idx]
                
                rows.append({
                    "scope": f"year_{y}",
                    "year": y,
                    "cohort": c_name,
                    "horizon_min": h_min,
                    "n": res["n"],
                    "treat_drift_atr": t_drift,
                    "ctrl_drift_atr": c_drift,
                    "rand_drift_atr": r_drift,
                    "treat_asym_atr": t_asym,
                    "ctrl_asym_atr": c_asym,
                    "pct_drift": pct_drift,
                    "pct_asym": pct_asym,
                    "treat_usd": t_usd,
                    "ctrl_usd": c_usd
                })
                
    df = pd.DataFrame(rows)
    df.to_parquet("studies/forward_return/results/forward_study_summary.parquet")
    print(f"\nSaved summary results to studies/forward_return/results/forward_study_summary.parquet")

if __name__ == "__main__":
    run_forward_study()


"""Analyze layered 1m HMM and 5m HMM macro states on RAW 1m flips.

Tactical Frame (1m) : HMM_4 (or other K=3,4,5,6) looked up at flip bar.
Macro Frame (5m)    : HMM_3 / HMM_4 looked up causally at flip moment T.
Entry Moment        : Flip close T (no confirmation).
Outcome             : Dynamic regime-exit (holding from flip close T to next regime flip).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

NS = 1_000_000_000
PRODUCT = "NQ"
OOS_YEARS = (2023, 2024, 2025, 2026)

MIN_POOLED_OOS_N = 100  # slightly lower because layering is more restrictive
MIN_PER_YEAR_N = 15
MIN_YEARS_PASSING_N = 3
MIN_LIFT_PP = 3.0
MIN_YEARS_SAME_SIGN = 3

def lookup_state_1m(target_ts_arr, state_ts_arr, state_arr):
    """Exact-match lookup for 1m states (target = flip bar open ts = T - 60s)."""
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    
    idx = np.searchsorted(state_ts_arr, target_ts_arr, side="left")
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx < len(state_ts_arr)) & (state_ts_arr[np.clip(idx, 0, len(state_ts_arr)-1)] == target_ts_arr)
    out[valid] = state_arr[idx[valid]]
    return out

def lookup_state_5m_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
    """Causal lookup for 5m states (latest 5m bar fully closed at T)."""
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
    re_path = "studies/v_a_excursion_regime/results_v0/nt_regime_exit_nq.parquet"
    re = pd.read_parquet(re_path)
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    
    cohort = re[re["resolved"]].copy()
    cohort["regime_win_flip_int"] = cohort["regime_win_flip"].astype(int)
    print(f"Loaded {len(cohort):,} resolved raw flips from {re_path}")
    
    # Baseline
    oos = cohort[cohort["year"].isin(OOS_YEARS)]
    base = oos["regime_win_flip_int"].mean()
    print(f"OOS Base Win Rate (raw flips, regime exit): {base:.1%}  (n={len(oos):,})")
    
    # Load 1m and 5m states parquets
    states_1m = pd.read_parquet("studies/regime_classification/results/states_nq_1m.parquet")
    state_ts_1m = states_1m.index.values.astype(np.int64)
    
    states_5m = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    state_ts_5m = states_5m.index.values.astype(np.int64)
    
    # Focus on the most promising models
    model_1m = "hmm_4"
    model_5m_list = ["hmm_3", "hmm_4", "kmeans_4"]
    
    print("\nLayering 1m HMM_4 states with 5m HMM/KMeans states...")
    results = []
    
    for s_1m in range(4):  # HMM_4 has states 0, 1, 2, 3
        # Look up 1m state causally (flip bar open time = T - 60s)
        cohort["state_1m"] = lookup_state_1m(cohort["entry_ts"] - 60 * NS, state_ts_1m, states_1m[model_1m])
        
        for m_5m in model_5m_list:
            n_states_5m = int(m_5m.split("_")[-1])
            for s_5m in range(n_states_5m):
                # Look up 5m state causally (latest closed 5m bar at T)
                cohort["state_5m"] = lookup_state_5m_causal(cohort["entry_ts"], state_ts_5m, states_5m[m_5m], 300 * NS)
                
                # Check layered condition
                sub = cohort[(cohort["state_1m"] == s_1m) & (cohort["state_5m"] == s_5m)]
                oos_sub = sub[sub["year"].isin(OOS_YEARS)]
                
                if len(oos_sub) < MIN_POOLED_OOS_N:
                    continue
                    
                lift_pool_pp = (oos_sub["regime_win_flip_int"].mean() - base) * 100
                if abs(lift_pool_pp) < MIN_LIFT_PP:
                    continue
                    
                per_year = []
                for y in OOS_YEARS:
                    g = oos_sub[oos_sub["year"] == y]
                    base_y = oos[oos["year"] == y]["regime_win_flip_int"].mean()
                    if len(g) >= 1:
                        per_year.append((y, len(g), g["regime_win_flip_int"].mean(),
                                          (g["regime_win_flip_int"].mean() - base_y) * 100))
                                          
                years_with_n = sum(1 for y, n, w, lp in per_year if n >= MIN_PER_YEAR_N)
                if years_with_n < MIN_YEARS_PASSING_N:
                    continue
                    
                signs = [np.sign(lp) for y, n, w, lp in per_year if n >= MIN_PER_YEAR_N]
                pos = sum(1 for s in signs if s > 0)
                neg = sum(1 for s in signs if s < 0)
                if max(pos, neg) < MIN_YEARS_SAME_SIGN:
                    continue
                    
                results.append({
                    "state_1m": s_1m,
                    "model_5m": m_5m,
                    "state_5m": s_5m,
                    "n_pool_oos": len(oos_sub),
                    "win_pool_oos": oos_sub["regime_win_flip_int"].mean(),
                    "lift_pool_pp": lift_pool_pp,
                    "per_year": per_year,
                })
                
    if not results:
        print("\nNO LAYERED HMM COMBINATIONS PASSED FILTERS ON RAW FLIPS.")
    else:
        results.sort(key=lambda x: -abs(x["lift_pool_pp"]))
        print(f"\n{len(results)} layered HMM survivor combinations on RAW flips:\n")
        print(f"  {'1m state':<10}{'5m model':<10}{'5m state':<10}{'n_pool':>8}{'win%':>8}{'base%':>8}{'lift':>9}  per-OOS-year")
        for r in results:
            yr_str = " ".join(
                f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                for y, n, w, lp in r["per_year"])
            print(f"  {model_1m}_s{r['state_1m']:<4}{r['model_5m']:<10}s{r['state_5m']:<9}"
                  f"{r['n_pool_oos']:>8,}{r['win_pool_oos']:>7.1%}"
                  f"{base:>7.1%}{r['lift_pool_pp']:>+8.1f}pp  "
                  f"{yr_str}")
                  
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()

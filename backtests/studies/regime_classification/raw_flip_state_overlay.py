"""Analyze 5m macro HMM states overlaid on RAW 1m flips (entering at flip close, no bar1 confirm).

Causal Entry : Flip close T.
Causal State : Latest 5m bar fully closed at T (state_moment = 'flip').
Outcome      : Dynamic regime-exit (holding from flip close T to next regime flip).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

NS = 1_000_000_000
PRODUCT = "NQ"
OUT = Path("studies/regime_classification/results")
OOS_YEARS = (2023, 2024, 2025, 2026)

MIN_POOLED_OOS_N = 200
MIN_PER_YEAR_N = 30
MIN_YEARS_PASSING_N = 3
MIN_LIFT_PP = 3.0
MIN_YEARS_SAME_SIGN = 3

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
    # Load all raw flips with regime-exit outcomes
    re_path = "studies/v_a_excursion_regime/results_v0/nt_regime_exit_nq.parquet"
    re = pd.read_parquet(re_path)
    re["entry_ts"] = re["entry_ts"].astype(np.int64)
    re["signal_direction"] = re["signal_direction"].astype(np.int64)
    
    # We want ALL raw flips
    cohort = re[re["resolved"]].copy()
    cohort["regime_win_flip_int"] = cohort["regime_win_flip"].astype(int)
    print(f"Loaded {len(cohort):,} resolved raw flips from {re_path}")
    
    # Baseline
    oos = cohort[cohort["year"].isin(OOS_YEARS)]
    base = oos["regime_win_flip_int"].mean()
    print(f"OOS Base Win Rate (raw flips, regime exit): {base:.1%}  (n={len(oos):,})")
    print("Per-year baseline:")
    for y in OOS_YEARS:
        g = oos[oos["year"] == y]
        print(f"  {y}: n={len(g):,} win={g['regime_win_flip_int'].mean():.1%}")
        
    # Load 5m states
    states = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    state_ts = states.index.values.astype(np.int64)
    
    state_cols = [f"{m}_{k}" for k in (3, 4, 5, 6)
                  for m in ("hmm", "gmm", "kmeans")]
                  
    all_surv = []
    for sc in state_cols:
        state_arr = states[sc].to_numpy(np.int64)
        target_ts = cohort["entry_ts"].to_numpy(np.int64)
        
        # Look up 5m state causally at flip moment T
        cohort["state"] = lookup_state_causal(target_ts, state_ts, state_arr, 300 * NS)
        
        sub = cohort[(cohort["state"] >= 0)]
        oos_sub = sub[sub["year"].isin(OOS_YEARS)]
        if len(oos_sub) == 0:
            continue
            
        for st in sorted(oos_sub["state"].unique()):
            sub_st = oos_sub[oos_sub["state"] == st]
            if len(sub_st) < MIN_POOLED_OOS_N:
                continue
                
            lift_pool_pp = (sub_st["regime_win_flip_int"].mean() - base) * 100
            if abs(lift_pool_pp) < MIN_LIFT_PP:
                continue
                
            per_year = []
            for y in OOS_YEARS:
                g = sub_st[sub_st["year"] == y]
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
                
            all_surv.append({
                "model_k": sc,
                "state": st,
                "n_pool_oos": len(sub_st),
                "win_pool_oos": sub_st["regime_win_flip_int"].mean(),
                "lift_pool_pp": lift_pool_pp,
                "per_year": per_year,
            })
            
    if not all_surv:
        print("\nNO CELLS PASSED ALL FILTERS ON RAW FLIPS.")
    else:
        all_surv.sort(key=lambda x: -abs(x["lift_pool_pp"]))
        print(f"\n{len(all_surv)} survivor cells on RAW flips:\n")
        print(f"  {'model_k':<14}{'state':<7}{'n_pool':>8}{'win%':>8}{'base%':>8}{'lift':>9}  per-OOS-year")
        for s in all_surv:
            yr_str = " ".join(
                f"{y}:{n}/{w:.0%}/{lp:+.1f}"
                for y, n, w, lp in s["per_year"])
            print(f"  {s['model_k']:<14}{s['state']:<7}"
                  f"{s['n_pool_oos']:>8,}{s['win_pool_oos']:>7.1%}"
                  f"{base:>7.1%}{s['lift_pool_pp']:>+8.1f}pp  "
                  f"{yr_str}")
                  
    print(f"\n[done] {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()

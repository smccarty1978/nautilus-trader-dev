"""Bootstrap CI on V_A C with ATR-normalized filter (ATR >= 0.75).

Same battery as bootstrap_va_c.py — direct comparison.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
OUT = Path("studies/v_a_excursion_regime/results_v0")
N_BOOT = 10_000
SEED = 42
ATR_THR = 0.75


def block_bootstrap(arr, n_iter, block_size, rng):
    n = len(arr)
    out = np.empty(n_iter)
    n_blocks = int(np.ceil(n / block_size))
    for i in range(n_iter):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block_size)[None, :]).ravel()
        idx = idx[:n]
        out[i] = arr[idx].mean()
    return out


def main():
    t0 = time.time()
    print("=" * 78)
    print(f"BOOTSTRAP CI on V_A C — ATR-NORMALIZED FILTER (ATR >= {ATR_THR})")
    print("=" * 78)

    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    feats["f_unr_atr_T_5m"] = (
        feats["f_unr_pnl_T_5m"] / (feats["atr"] * NQ_MULT))

    c_pop = feats[feats["alive_5m"]
                    & (feats["f_unr_atr_T_5m"] >= ATR_THR)].copy()
    c_pop = c_pop.sort_values("entry_ts").reset_index(drop=True)
    pnl = c_pop["d_pnl_5m"].to_numpy()
    print(f"\n  V_A C ATR>={ATR_THR} cohort: {len(c_pop):,}")
    print(f"  Total PnL:  ${pnl.sum():+,.0f}")
    print(f"  Mean PnL:   ${pnl.mean():+.2f}/tr")
    print(f"  Median PnL: ${np.median(pnl):+.2f}/tr")
    print(f"  StdDev:     ${pnl.std():+.2f}")
    print(f"  WR:         {(pnl > 0).mean()*100:.1f}%")

    rng = np.random.default_rng(SEED)

    # Per-year IID
    print(f"\n{'='*78}")
    print(f"PER-YEAR BOOTSTRAP — {N_BOOT:,} iterations, iid resample")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'n':>5}  {'mean$':>10}  "
          f"{'p05':>8}  {'p50':>8}  {'p95':>8}  {'P(mean>0)':>10}")
    pooled_results = {}
    for yr in (2024, 2025, 2026):
        sub = c_pop[c_pop["year"] == yr]
        if len(sub) < 30: continue
        sub_pnl = sub["d_pnl_5m"].to_numpy()
        n_yr = len(sub_pnl)
        idx = rng.integers(0, n_yr, size=(N_BOOT, n_yr))
        means = sub_pnl[idx].mean(axis=1)
        p_pos = (means > 0).mean()
        pooled_results[yr] = means
        print(f"  {yr:<6}  {n_yr:>5,}  ${sub_pnl.mean():>+8.2f}  "
              f"${np.percentile(means, 5):>+6.2f}  "
              f"${np.percentile(means, 50):>+6.2f}  "
              f"${np.percentile(means, 95):>+6.2f}  "
              f"{p_pos*100:>9.1f}%")

    n_all = len(pnl)
    idx = rng.integers(0, n_all, size=(N_BOOT, n_all))
    means_pooled_iid = pnl[idx].mean(axis=1)
    p_pos_iid = (means_pooled_iid > 0).mean()
    print(f"  {'POOLED':<6}  {n_all:>5,}  ${pnl.mean():>+8.2f}  "
          f"${np.percentile(means_pooled_iid, 5):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 50):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 95):>+6.2f}  "
          f"{p_pos_iid*100:>9.1f}%")

    # Block bootstrap
    print(f"\n{'='*78}")
    print(f"BLOCK BOOTSTRAP")
    print(f"{'='*78}")
    print(f"  {'block':<6}  {'mean$':>10}  {'p05':>8}  {'p50':>8}  "
          f"{'p95':>8}  {'P(mean>0)':>10}")
    for bs in [10, 25, 50, int(np.sqrt(n_all))]:
        means_bb = block_bootstrap(pnl, N_BOOT, bs, rng)
        p_pos_bb = (means_bb > 0).mean()
        print(f"  {bs:<6}  ${means_bb.mean():>+8.2f}  "
              f"${np.percentile(means_bb, 5):>+6.2f}  "
              f"${np.percentile(means_bb, 50):>+6.2f}  "
              f"${np.percentile(means_bb, 95):>+6.2f}  "
              f"{p_pos_bb*100:>9.1f}%")

    # Rolling
    print(f"\n{'='*78}")
    print(f"ROLLING WINDOW MEANS")
    print(f"{'='*78}")
    print(f"  {'K':<4}  {'n_win':>10}  {'mean':>8}  {'p05':>8}  "
          f"{'p50':>8}  {'p95':>8}  {'P(>0)':>7}")
    for K in [25, 50, 100, 200, 500]:
        if len(pnl) < K: continue
        roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
        p_pos = (roll > 0).mean()
        print(f"  {K:<4}  {len(roll):>10,}  ${roll.mean():>+6.2f}  "
              f"${np.percentile(roll, 5):>+6.2f}  "
              f"${np.percentile(roll, 50):>+6.2f}  "
              f"${np.percentile(roll, 95):>+6.2f}  "
              f"{p_pos*100:>5.1f}%")

    # Pass/Fail
    print(f"\n{'='*78}")
    print(f"PASS/FAIL")
    print(f"{'='*78}")
    p5_pooled = np.percentile(means_pooled_iid, 5)
    p = p5_pooled > 0
    print(f"  Pooled 5th pctile > $0:           ${p5_pooled:>+8.2f}  "
          f"{'PASS' if p else 'FAIL'}")
    for yr, means in pooled_results.items():
        p5 = np.percentile(means, 5)
        p = p5 > 0
        print(f"  {yr} 5th pctile > $0:              ${p5:>+8.2f}  "
              f"{'PASS' if p else 'FAIL'}")
    bs_default = int(np.sqrt(n_all))
    means_bb = block_bootstrap(pnl, N_BOOT, bs_default, rng)
    p5_bb = np.percentile(means_bb, 5)
    p = p5_bb > 0
    print(f"  Block bs={bs_default} 5th pctile > $0:        ${p5_bb:>+8.2f}  "
          f"{'PASS' if p else 'FAIL'}")
    for K in [50, 100]:
        roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
        p_pos = (roll > 0).mean()
        p = p_pos > 0.7
        print(f"  Rolling-{K} P(>0) > 70%:           {p_pos*100:>+8.1f}%  "
              f"{'PASS' if p else 'FAIL'}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

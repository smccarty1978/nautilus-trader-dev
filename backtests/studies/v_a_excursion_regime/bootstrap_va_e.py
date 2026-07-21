"""Bootstrap CI on V_A E per-trade edge — same battery as
bootstrap_va_c.py but for the +7m + dual momentum variant.

E filter: alive @+7m AND f_net_move_150s_7m >= IS-q10
                       AND f_net_move_300s_7m >= IS-q20
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

OUT = Path("studies/v_a_excursion_regime/results_v0")
N_BOOT = 10_000
SEED = 42


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
    print("BOOTSTRAP CI ON V_A E  (delayed @+7m + dual momentum)")
    print("=" * 78)

    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped: {n_pre:,} -> {len(feats):,}")

    is_alive_7m = feats[feats["alive_7m"]
                          & feats["year"].isin([2024, 2025])]
    thr_150 = is_alive_7m["f_net_move_150s_7m"].quantile(0.10)
    thr_300 = is_alive_7m["f_net_move_300s_7m"].quantile(0.20)
    print(f"\n  V_A E filters:")
    print(f"    f_net_move_150s_7m >= ${thr_150:.2f} (IS q=0.10)")
    print(f"    f_net_move_300s_7m >= ${thr_300:.2f} (IS q=0.20)")
    e_pop = feats[feats["alive_7m"]
                    & (feats["f_net_move_150s_7m"] >= thr_150)
                    & (feats["f_net_move_300s_7m"] >= thr_300)].copy()
    e_pop = e_pop.sort_values("entry_ts").reset_index(drop=True)
    pnl = e_pop["d_pnl_7m"].to_numpy()
    print(f"  V_A E cohort size: {len(e_pop):,}")
    print(f"  Total PnL:         ${pnl.sum():+,.0f}")
    print(f"  Mean PnL:          ${pnl.mean():+.2f}/tr")
    print(f"  Median PnL:        ${np.median(pnl):+.2f}/tr")
    print(f"  StdDev:            ${pnl.std():+.2f}")
    print(f"  WR:                {(pnl > 0).mean()*100:.1f}%")

    rng = np.random.default_rng(SEED)

    print(f"\n{'='*78}")
    print(f"PER-YEAR BOOTSTRAP")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'n':>5}  {'mean$':>10}  "
          f"{'p05':>8}  {'p25':>8}  {'p50':>8}  {'p75':>8}  {'p95':>8}  "
          f"{'P(mean>0)':>10}")
    pooled_results = {}
    for yr in (2024, 2025, 2026):
        sub = e_pop[e_pop["year"] == yr]
        if len(sub) < 30: continue
        sub_pnl = sub["d_pnl_7m"].to_numpy()
        n_yr = len(sub_pnl)
        idx = rng.integers(0, n_yr, size=(N_BOOT, n_yr))
        means = sub_pnl[idx].mean(axis=1)
        p_pos = (means > 0).mean()
        pooled_results[yr] = means
        print(f"  {yr:<6}  {n_yr:>5,}  ${sub_pnl.mean():>+8.2f}  "
              f"${np.percentile(means, 5):>+6.2f}  "
              f"${np.percentile(means, 25):>+6.2f}  "
              f"${np.percentile(means, 50):>+6.2f}  "
              f"${np.percentile(means, 75):>+6.2f}  "
              f"${np.percentile(means, 95):>+6.2f}  "
              f"{p_pos*100:>9.1f}%")

    n_all = len(pnl)
    idx = rng.integers(0, n_all, size=(N_BOOT, n_all))
    means_pooled_iid = pnl[idx].mean(axis=1)
    p_pos_iid = (means_pooled_iid > 0).mean()
    print(f"  {'POOLED':<6}  {n_all:>5,}  ${pnl.mean():>+8.2f}  "
          f"${np.percentile(means_pooled_iid, 5):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 25):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 50):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 75):>+6.2f}  "
          f"${np.percentile(means_pooled_iid, 95):>+6.2f}  "
          f"{p_pos_iid*100:>9.1f}%")

    print(f"\n{'='*78}")
    print(f"BLOCK BOOTSTRAP")
    print(f"{'='*78}")
    block_sizes = [10, 25, 50, int(np.sqrt(n_all))]
    print(f"  {'block':<6}  {'mean$':>10}  {'p05':>8}  {'p25':>8}  "
          f"{'p50':>8}  {'p75':>8}  {'p95':>8}  {'P(mean>0)':>10}")
    for bs in block_sizes:
        means_bb = block_bootstrap(pnl, N_BOOT, bs, rng)
        p_pos_bb = (means_bb > 0).mean()
        print(f"  {bs:<6}  ${means_bb.mean():>+8.2f}  "
              f"${np.percentile(means_bb, 5):>+6.2f}  "
              f"${np.percentile(means_bb, 25):>+6.2f}  "
              f"${np.percentile(means_bb, 50):>+6.2f}  "
              f"${np.percentile(means_bb, 75):>+6.2f}  "
              f"${np.percentile(means_bb, 95):>+6.2f}  "
              f"{p_pos_bb*100:>9.1f}%")

    print(f"\n{'='*78}")
    print(f"ROLLING WINDOW MEANS")
    print(f"{'='*78}")
    print(f"  {'K':<4}  {'n_windows':>10}  {'mean':>8}  "
          f"{'p05':>8}  {'p25':>8}  {'p50':>8}  {'p75':>8}  {'p95':>8}  "
          f"{'P(>0)':>7}")
    for K in [25, 50, 100, 200, 500]:
        if len(pnl) < K: continue
        roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
        p_pos = (roll > 0).mean()
        print(f"  {K:<4}  {len(roll):>10,}  ${roll.mean():>+6.2f}  "
              f"${np.percentile(roll, 5):>+6.2f}  "
              f"${np.percentile(roll, 25):>+6.2f}  "
              f"${np.percentile(roll, 50):>+6.2f}  "
              f"${np.percentile(roll, 75):>+6.2f}  "
              f"${np.percentile(roll, 95):>+6.2f}  "
              f"{p_pos*100:>5.1f}%")

    print(f"\n{'='*78}")
    print(f"ROBUSTNESS PASS/FAIL")
    print(f"{'='*78}")
    print(f"  {'criterion':<55}  {'value':>10}  {'pass':>6}")
    print("  " + "-" * 75)
    p5_pooled = np.percentile(means_pooled_iid, 5)
    p = p5_pooled > 0
    print(f"  {'Pooled 5th percentile bootstrap mean > $0':<55}  "
          f"${p5_pooled:>+8.2f}  {'PASS' if p else 'FAIL':>6}")
    for yr, means in pooled_results.items():
        p5 = np.percentile(means, 5)
        p = p5 > 0
        print(f"  {f'{yr} 5th percentile bootstrap mean > $0':<55}  "
              f"${p5:>+8.2f}  {'PASS' if p else 'FAIL':>6}")
    bs_default = int(np.sqrt(n_all))
    means_bb = block_bootstrap(pnl, N_BOOT, bs_default, rng)
    p5_bb = np.percentile(means_bb, 5)
    p = p5_bb > 0
    print(f"  {f'Block bootstrap (bs={bs_default}) 5th pctile > $0':<55}  "
          f"${p5_bb:>+8.2f}  {'PASS' if p else 'FAIL':>6}")
    for K in [50, 100]:
        roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
        p_pos = (roll > 0).mean()
        p = p_pos > 0.7
        print(f"  {f'Rolling-{K} P(window mean > $0) > 0.7':<55}  "
              f"{p_pos*100:>+8.1f}%  {'PASS' if p else 'FAIL':>6}")

    print(f"\n{'='*78}")
    print(f"WORST ROLLING WINDOWS")
    print(f"{'='*78}")
    for K in [50, 100]:
        roll = pd.Series(pnl).rolling(K).mean()
        e_pop["entry_dt"] = pd.to_datetime(e_pop["entry_ts"], unit="ns",
                                                 utc=True)
        worst_idx = roll.nsmallest(5).index
        print(f"\n  Worst rolling-{K} windows:")
        for idx in worst_idx:
            window_end_dt = e_pop.iloc[idx]["entry_dt"]
            window_start_dt = e_pop.iloc[idx - K + 1]["entry_dt"]
            print(f"    {window_start_dt.strftime('%Y-%m-%d')} -> "
                  f"{window_end_dt.strftime('%Y-%m-%d')}  "
                  f"mean=${roll.iloc[idx]:+.2f}/tr")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

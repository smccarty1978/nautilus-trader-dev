"""Bootstrap CI on V_A C per-trade edge.

V_A C strategy: V_A-confirmed signal + delayed entry @+5m + filter
f_unr_pnl_T_5m >= IS-q80 ($325). 1,269 trades over 2024-2026.

Robustness battery (per memory: many V_A leads have failed this):
  1. Block bootstrap on the chronological PnL series (random
     resampling of trades preserves WR but destroys time-clustering;
     block bootstrap preserves clustering).
  2. Per-year resampling — for each year, resample with replacement
     and compute mean PnL. Report 5th-95th percentile.
  3. Rolling-50 / rolling-100 bootstrap means. Report distribution
     of rolling-window means and percentile of those means > $0.

Pass criteria (per memory pattern):
  - 5th-percentile bootstrap mean > $0  for the pooled series
  - Each year's 5th-percentile bootstrap mean > $0
  - Rolling-50 / rolling-100: median > $0, P(rolling mean > 0) > 0.7

Reports:
  - Summary stats per year and pooled
  - Bootstrap mean distribution per year
  - Rolling-50 / -100 distributions
  - Block bootstrap on full series

Methodology:
  - 10,000 bootstrap iterations
  - Block size for block bootstrap = sqrt(n)
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
    """Stationary block bootstrap on a 1D array. Sample blocks of
    size `block_size` with replacement until length matches arr."""
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
    print("BOOTSTRAP CI ON V_A C  (delayed @+5m + unr ≥ $325)")
    print("=" * 78)

    # Load V_A trades + checkpoint features parquet
    feats = pd.read_parquet(OUT / "checkpoint_features.parquet")
    n_pre = len(feats)
    feats = feats.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)
    if n_pre != len(feats):
        print(f"  deduped: {n_pre:,} -> {len(feats):,}")

    # Apply V_A C filter — IS-fit threshold from prior matched comparison
    is_alive_5m = feats[feats["alive_5m"]
                          & feats["year"].isin([2024, 2025])]
    thr_unr = is_alive_5m["f_unr_pnl_T_5m"].quantile(0.80)
    print(f"\n  V_A C filter: f_unr_pnl_T_5m >= ${thr_unr:.0f} (IS q=0.80)")
    c_pop = feats[feats["alive_5m"]
                    & (feats["f_unr_pnl_T_5m"] >= thr_unr)].copy()
    c_pop = c_pop.sort_values("entry_ts").reset_index(drop=True)
    pnl = c_pop["d_pnl_5m"].to_numpy()
    print(f"  V_A C cohort size: {len(c_pop):,}")
    print(f"  Total PnL:         ${pnl.sum():+,.0f}")
    print(f"  Mean PnL:          ${pnl.mean():+.2f}/tr")
    print(f"  Median PnL:        ${np.median(pnl):+.2f}/tr")
    print(f"  StdDev:            ${pnl.std():+.2f}")
    print(f"  WR:                {(pnl > 0).mean()*100:.1f}%")

    rng = np.random.default_rng(SEED)

    # ===== 1. Per-year iid bootstrap (resample trades w/ replacement) =====
    print(f"\n{'='*78}")
    print(f"PER-YEAR BOOTSTRAP — {N_BOOT:,} iterations, iid resample")
    print(f"  Each iteration draws n trades w/ replacement, computes mean")
    print(f"{'='*78}")
    print(f"  {'year':<6}  {'n':>5}  {'mean$':>10}  "
          f"{'p05':>8}  {'p25':>8}  {'p50':>8}  {'p75':>8}  {'p95':>8}  "
          f"{'P(mean>0)':>10}")
    pooled_results = {}
    for yr in (2024, 2025, 2026):
        sub = c_pop[c_pop["year"] == yr]
        if len(sub) < 30:
            print(f"  {yr}: too few trades ({len(sub)})")
            continue
        sub_pnl = sub["d_pnl_5m"].to_numpy()
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

    # Pooled iid
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

    # ===== 2. Block bootstrap (preserves time clustering) =====
    print(f"\n{'='*78}")
    print(f"BLOCK BOOTSTRAP — preserves time-clustering of trades")
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

    # ===== 3. Rolling window means (every consecutive K trades) =====
    print(f"\n{'='*78}")
    print(f"ROLLING WINDOW MEANS — distribution of consecutive-K trade means")
    print(f"  Tells us how often a 'small' time window is profitable")
    print(f"{'='*78}")
    print(f"  {'K':<4}  {'n_windows':>10}  {'mean':>8}  "
          f"{'p05':>8}  {'p25':>8}  {'p50':>8}  {'p75':>8}  {'p95':>8}  "
          f"{'P(>0)':>7}  {'min':>8}  {'max':>8}")
    for K in [25, 50, 100, 200]:
        if len(pnl) < K: continue
        roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
        p_pos = (roll > 0).mean()
        print(f"  {K:<4}  {len(roll):>10,}  ${roll.mean():>+6.2f}  "
              f"${np.percentile(roll, 5):>+6.2f}  "
              f"${np.percentile(roll, 25):>+6.2f}  "
              f"${np.percentile(roll, 50):>+6.2f}  "
              f"${np.percentile(roll, 75):>+6.2f}  "
              f"${np.percentile(roll, 95):>+6.2f}  "
              f"{p_pos*100:>5.1f}%  "
              f"${roll.min():>+6.2f}  ${roll.max():>+6.2f}")

    # ===== 4. Pass/fail summary =====
    print(f"\n{'='*78}")
    print(f"ROBUSTNESS PASS/FAIL")
    print(f"{'='*78}")
    print(f"  {'criterion':<55}  {'value':>10}  {'pass':>6}")
    print("  " + "-" * 75)
    # Pooled iid 5th percentile > 0
    p5_pooled = np.percentile(means_pooled_iid, 5)
    p_pos = p5_pooled > 0
    print(f"  {'Pooled 5th percentile bootstrap mean > $0':<55}  "
          f"${p5_pooled:>+8.2f}  {'PASS' if p_pos else 'FAIL':>6}")
    # Per-year 5th percentile > 0
    for yr, means in pooled_results.items():
        p5 = np.percentile(means, 5)
        p = p5 > 0
        print(f"  {f'{yr} 5th percentile bootstrap mean > $0':<55}  "
              f"${p5:>+8.2f}  {'PASS' if p else 'FAIL':>6}")
    # Block bootstrap (sqrt-n block)
    bs_default = int(np.sqrt(n_all))
    means_bb = block_bootstrap(pnl, N_BOOT, bs_default, rng)
    p5_bb = np.percentile(means_bb, 5)
    p = p5_bb > 0
    print(f"  {f'Block bootstrap (bs={bs_default}) 5th pctile > $0':<55}  "
          f"${p5_bb:>+8.2f}  {'PASS' if p else 'FAIL':>6}")
    # Rolling-50 P(>0) > 0.7
    K = 50
    roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
    p_pos = (roll > 0).mean()
    p = p_pos > 0.7
    print(f"  {'Rolling-50 P(window mean > $0) > 0.7':<55}  "
          f"{p_pos*100:>+8.1f}%  {'PASS' if p else 'FAIL':>6}")
    K = 100
    roll = pd.Series(pnl).rolling(K).mean().dropna().to_numpy()
    p_pos = (roll > 0).mean()
    p = p_pos > 0.7
    print(f"  {'Rolling-100 P(window mean > $0) > 0.7':<55}  "
          f"{p_pos*100:>+8.1f}%  {'PASS' if p else 'FAIL':>6}")

    # ===== 5. Worst rolling-50 / -100 windows (where did the trades occur?) =====
    print(f"\n{'='*78}")
    print(f"WORST ROLLING WINDOWS — when did C bleed?")
    print(f"{'='*78}")
    for K in [50, 100]:
        roll = pd.Series(pnl).rolling(K).mean()
        c_pop["entry_dt"] = pd.to_datetime(c_pop["entry_ts"], unit="ns",
                                                 utc=True)
        worst_idx = roll.nsmallest(5).index
        print(f"\n  Worst rolling-{K} windows:")
        for idx in worst_idx:
            window_end_dt = c_pop.iloc[idx]["entry_dt"]
            window_start_dt = c_pop.iloc[idx - K + 1]["entry_dt"]
            print(f"    {window_start_dt.strftime('%Y-%m-%d')} -> "
                  f"{window_end_dt.strftime('%Y-%m-%d')}  "
                  f"mean=${roll.iloc[idx]:+.2f}/tr")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

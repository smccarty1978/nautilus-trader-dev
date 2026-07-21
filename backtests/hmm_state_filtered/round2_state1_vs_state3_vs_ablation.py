"""Round 2 brief — State 3 (production) vs State 1 vs clean ablation.

Tasks A+B per the brief:
  A) Clean ablation: target_state=-1 with c1/c2 fix, verify universe correctness
     and that production entries are a strict subset of ablation entries.
  B) State 1 target: target_state=1, same downstream chain as production.

Output: single table, monthly-block-bootstrapped, leading with PASS/FAIL on the
decision rule:
  PASS: pool P(<=0) < 5% AND 2024 no longer stat-sig negative, w/o collapsing 2023/2025.
  FAIL: otherwise — strategy is a marginal trend-follower; deploy small or shelve.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMM = 5.0
RES = Path("backtests/hmm_state_filtered/results")
OOS_YEARS = (2023, 2024, 2025, 2026)
ALL_YEARS = (2020, 2021, 2022) + OOS_YEARS


def load_cohort(prefix: str, years=OOS_YEARS) -> pd.DataFrame:
    rows = []
    for y in years:
        p = RES / f"{prefix}_{y}/trades.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not len(df):
            continue
        df["year"] = y
        df["pnl_$"] = ((df["exit_px"] - df["entry_px"])
                        * df["signal_direction"] * NQ_MULT - COMM)
        df["entry_dt"] = pd.to_datetime(df["entry_ts"])
        df["month"] = df["entry_dt"].dt.to_period("M").astype(str)
        rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def dedup_records(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse identical-leg duplicates introduced by the c1/c2 split."""
    if not len(df):
        return df
    return df.drop_duplicates(
        subset=["entry_ts", "exit_ts", "exit_px", "signal_direction"]
    ).reset_index(drop=True)


def subset_check(prod: pd.DataFrame, abl: pd.DataFrame) -> dict:
    """Verify production entries are a strict subset of ablation entries."""
    prod_keys = set(prod["entry_ts"])
    abl_keys  = set(abl["entry_ts"])
    missing = prod_keys - abl_keys
    extra_in_abl = abl_keys - prod_keys
    return {
        "prod_unique_entries": len(prod_keys),
        "abl_unique_entries":  len(abl_keys),
        "prod_entries_missing_from_abl": len(missing),
        "abl_entries_not_in_prod":       len(extra_in_abl),
        "subset_holds": len(missing) == 0,
        "sample_missing": list(missing)[:5] if missing else [],
    }


def monthly_aggregate(tr: pd.DataFrame) -> pd.DataFrame:
    monthly = tr.groupby("month").agg(
        n_trades=("pnl_$", "count"),
        total_dollars=("pnl_$", "sum"),
    ).reset_index()
    monthly = monthly.rename(columns={"total_dollars": "total_$"})
    return monthly


def block_bootstrap(monthly: pd.DataFrame, n_iter: int = 10000, seed: int = 42):
    if not len(monthly):
        return np.array([]), np.array([])
    rng = np.random.default_rng(seed)
    n_months = len(monthly)
    n_arr = monthly["n_trades"].to_numpy()
    t_arr = monthly["total_$"].to_numpy()
    means = np.zeros(n_iter)
    annual = np.zeros(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_months, size=n_months)
        tot = t_arr[idx].sum()
        n   = n_arr[idx].sum()
        means[i]  = tot / n if n > 0 else 0
        annual[i] = tot / (n_months / 12.0)
    return means, annual


def report_per_year_block_boot(tr: pd.DataFrame, label: str):
    print(f"\n  {label} per-year block bootstrap:")
    print(f"  {'year':<6}{'n':>6}{'obs $/tr':>10}{'boot mean':>11}"
          f"{'5th':>9}{'95th':>9}{'P(<=0)':>9}")
    rng_seed = 42
    for y in OOS_YEARS:
        sub = tr[tr["year"] == y]
        if not len(sub):
            continue
        m = monthly_aggregate(sub)
        means, _ = block_bootstrap(m, seed=rng_seed + y)
        if not len(means):
            continue
        p_neg = (means <= 0).mean()
        marker = " <-- 2024" if y == 2024 else ""
        print(f"  {y:<6}{len(sub):>6}{sub['pnl_$'].mean():>+10.2f}"
              f"{means.mean():>+11.2f}{np.percentile(means, 5):>+9.2f}"
              f"{np.percentile(means, 95):>+9.2f}{p_neg:>9.1%}{marker}")


def report_pooled_block_boot(tr: pd.DataFrame, label: str):
    if not len(tr):
        return None
    monthly = monthly_aggregate(tr)
    means, annual = block_bootstrap(monthly, n_iter=10000)
    pool_obs = tr["pnl_$"].mean()
    pool_total = tr["pnl_$"].sum()
    print(f"\n  {label} POOLED OOS block bootstrap:")
    print(f"    n trades:        {len(tr):,}")
    print(f"    n months:        {len(monthly)}")
    print(f"    observed $/tr:   ${pool_obs:+.2f}")
    print(f"    observed total$: ${pool_total:+,.0f}")
    print(f"    boot mean $/tr:  ${means.mean():+.2f}")
    print(f"    boot std:        ${means.std():.2f}")
    print(f"    boot 5th-pct:    ${np.percentile(means, 5):+.2f}")
    print(f"    boot 95th-pct:   ${np.percentile(means, 95):+.2f}")
    print(f"    P(pool <=0):     {(means <= 0).mean():.1%}")
    print(f"    boot annualized: ${annual.mean():+,.0f}")
    return {
        "n_trades":   len(tr),
        "obs_$/tr":   pool_obs,
        "boot_mean":  means.mean(),
        "boot_5":     np.percentile(means, 5),
        "boot_95":    np.percentile(means, 95),
        "p_neg":      (means <= 0).mean(),
        "annual":     annual.mean(),
        "means":      means,
    }


def long_2024(tr: pd.DataFrame, label: str) -> float:
    sub = tr[(tr["year"] == 2024) & (tr["signal_direction"] == 1)]
    if not len(sub):
        return float("nan")
    return sub["pnl_$"].mean()


def main():
    print("="*100)
    print("ROUND 2 BRIEF — Clean Ablation + State 1 vs State 3 (production)")
    print("="*100)

    # Load all three cohorts
    print("\nLoading cohorts...")
    prod_raw = load_cohort("nq_hmm_4_s3_pt2p0")
    abl_raw  = load_cohort("nq_hmm_4_s-1_pt2p0_cleanAbl")
    s1_raw   = load_cohort("nq_hmm_4_s1_pt2p0")

    prod = dedup_records(prod_raw)
    abl  = dedup_records(abl_raw)
    s1   = dedup_records(s1_raw)

    print(f"  Production (State 3): raw rows={len(prod_raw)} dedup={len(prod)}")
    print(f"  Clean ablation:        raw rows={len(abl_raw)} dedup={len(abl)}")
    print(f"  State 1:               raw rows={len(s1_raw)} dedup={len(s1)}")

    if not len(abl):
        print("\n[clean ablation not yet present — sweep may still be running]")
    if not len(s1):
        print("\n[State 1 trades not yet present — sweep may still be running]")
        return

    # === A) UNIVERSE / SUBSET CHECK ===
    print("\n" + "="*100)
    print(" TASK A — Universe check: clean ablation")
    print("="*100)
    if len(abl):
        check = subset_check(prod, abl)
        print(f"  Production unique entries:    {check['prod_unique_entries']:,}")
        print(f"  Ablation unique entries:      {check['abl_unique_entries']:,}")
        print(f"  Production NOT in ablation:   {check['prod_entries_missing_from_abl']:,}")
        print(f"  Ablation entries beyond prod: {check['abl_entries_not_in_prod']:,}")
        if check["subset_holds"]:
            print(f"  -> SUBSET HOLDS: production entries are a strict subset of ablation.")
            print(f"     Trigger is identical; only state filter toggles between them.")
        else:
            print(f"  -> SUBSET DOES NOT HOLD: {check['prod_entries_missing_from_abl']} prod")
            print(f"     entries are NOT in ablation set. Trigger logic differs between")
            print(f"     state-3 and no-state runs. Examples: {check['sample_missing']}")
            print(f"     STOP — entry trigger needs re-examination before drawing conclusions.")

    # === BLOCK BOOTSTRAP ALL THREE ===
    print("\n" + "="*100)
    print(" PER-YEAR + POOLED BLOCK BOOTSTRAP")
    print("="*100)
    report_per_year_block_boot(prod, "STATE 3 (production)")
    if len(abl): report_per_year_block_boot(abl, "CLEAN ABLATION")
    report_per_year_block_boot(s1,   "STATE 1")

    s3_pool = report_pooled_block_boot(prod, "STATE 3 (production)")
    abl_pool = report_pooled_block_boot(abl, "CLEAN ABLATION") if len(abl) else None
    s1_pool = report_pooled_block_boot(s1,   "STATE 1")

    # === B) DECISION RULE ===
    print("\n" + "="*100)
    print(" DECISION RULE — STATE 1 PASS/FAIL")
    print("="*100)
    # Re-compute 2024 P(<=0) for State 1
    s1_2024 = s1[s1["year"] == 2024]
    s1_2024_m = monthly_aggregate(s1_2024)
    s1_2024_means, _ = block_bootstrap(s1_2024_m, seed=42+2024)
    s1_2024_p_neg = (s1_2024_means <= 0).mean() if len(s1_2024_means) else float("nan")

    pool_below_5 = s1_pool["p_neg"] < 0.05
    y2024_no_longer_sig_neg = s1_2024_p_neg < 0.5  # convention: < 0.5 = no longer sig-neg
    pass_ = pool_below_5 and y2024_no_longer_sig_neg

    print(f"  Required: pool P(<=0) < 5% AND 2024 P(<=0) < 50% (no longer sig-neg)")
    print(f"  State 1 pool P(<=0):      {s1_pool['p_neg']:.1%} {'PASS' if pool_below_5 else 'FAIL'}")
    print(f"  State 1 2024 P(<=0):      {s1_2024_p_neg:.1%} {'PASS' if y2024_no_longer_sig_neg else 'FAIL'}")
    print(f"\n  VERDICT: STATE 1 = {'PASS' if pass_ else 'FAIL'}")
    if pass_:
        print(f"  -> State 1 becomes the new production target.")
        print(f"  -> Re-open significance question; proceed to router as second-stage filter.")
    else:
        print(f"  -> Static target-state engineering does not fix 2024.")
        print(f"  -> Strategy is a marginal trend-follower:")
        print(f"     - Production pool boot mean: ${s3_pool['boot_mean']:+.2f}/tr"
              f", annual ${s3_pool['annual']:+,.0f}")
        print(f"     - State 1 pool boot mean:    ${s1_pool['boot_mean']:+.2f}/tr"
              f", annual ${s1_pool['annual']:+,.0f}")
        print(f"  -> Options: deploy small with hard regime gate (size on efficiency/chop),")
        print(f"             treat as modest sleeve (~$15K/yr), or shelve.")
        print(f"  -> Do NOT proceed to ES replication on a marginal config.")

    # === SUMMARY TABLE ===
    print("\n" + "="*100)
    print(" SUMMARY TABLE")
    print("="*100)
    s3_2024_long = long_2024(prod, "S3")
    s1_2024_long = long_2024(s1, "S1")
    abl_2024_long = long_2024(abl, "ABL") if len(abl) else float("nan")

    print(f"\n  {'metric':<32}{'State 3':>14}{'State 1':>14}{'clean abl':>14}")
    print(f"  {'-'*32}{'-'*14}{'-'*14}{'-'*14}")

    # Per-year $/tr
    for y in OOS_YEARS:
        line = f"  {y} $/tr:                       "
        for d in [prod, s1, abl]:
            if not len(d):
                line += f"{'-':>14}"; continue
            sub = d[d["year"] == y]
            line += f"{sub['pnl_$'].mean() if len(sub) else 0:>+14.2f}"
        print(line)

    # Pooled $/tr
    print(f"\n  {'pooled $/tr (boot mean)':<32}", end="")
    print(f"{s3_pool['boot_mean']:>+14.2f}", end="")
    print(f"{s1_pool['boot_mean']:>+14.2f}", end="")
    print(f"{abl_pool['boot_mean'] if abl_pool else 0:>+14.2f}" if abl_pool else f"{'-':>14}")

    # Pool P(<=0)
    print(f"  {'pooled P(<=0)':<32}", end="")
    print(f"{s3_pool['p_neg']:>14.1%}", end="")
    print(f"{s1_pool['p_neg']:>14.1%}", end="")
    print(f"{abl_pool['p_neg'] if abl_pool else 0:>14.1%}" if abl_pool else f"{'-':>14}")

    # 2024 long $/tr
    print(f"  {'2024 long $/tr':<32}{s3_2024_long:>+14.2f}"
          f"{s1_2024_long:>+14.2f}{abl_2024_long:>+14.2f}")

    # Trade count (deduped)
    print(f"  {'OOS trade count':<32}{len(prod):>14,}"
          f"{len(s1):>14,}{len(abl) if len(abl) else 0:>14,}")


if __name__ == "__main__":
    main()

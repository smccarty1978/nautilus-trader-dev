"""Parse the 24 raw NT runs (studies/adaptive_rank_filter_walkforward/nt_runs/
{policy}_{period}/) into one combined trade-level table plus a combined
skip/eligibility table, joined back to the F2 atlas via decision_ts ==
confirmation_ts.

Policy naming: r0, static_r2, static_r4, a{1,2,4}_{3m,6m,12m}.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from run_nt_adaptive import ALL_POLICIES, PERIODS

WORK_DIR = c.OUT.parent / "_work"


def policy_window(policy: str) -> str | None:
    if policy in ("r0", "static_r2", "static_r4"):
        return None
    return policy.split("_", 1)[1]


def policy_family(policy: str) -> str:
    """r0 / static_r2 / static_r4 / a1 / a2 / a4"""
    if policy in ("r0", "static_r2", "static_r4"):
        return policy
    return policy.split("_", 1)[0]


def month_from_ts(ts_ns: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts_ns, unit="ns", utc=True).dt.tz_convert("America/Chicago")
    return ts.dt.strftime("%Y-%m")


def load_all_trades() -> pd.DataFrame:
    frames = []
    for period_key in PERIODS:
        for policy in ALL_POLICIES:
            p = c.NT_OUT_ROOT / f"{policy}_{period_key}" / "trades.parquet"
            if not p.exists():
                print(f"  MISSING trades.parquet: {policy}/{period_key}")
                continue
            df = pd.read_parquet(p)
            if len(df) == 0:
                continue
            df["policy"] = policy
            df["policy_family"] = policy_family(policy)
            df["window_name"] = policy_window(policy)
            df["period_key"] = period_key
            frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["deploy_month"] = month_from_ts(out["decision_ts"])
    return out


def load_all_skips() -> pd.DataFrame:
    frames = []
    for period_key in PERIODS:
        for policy in ALL_POLICIES:
            p = c.NT_OUT_ROOT / f"{policy}_{period_key}" / "policy_skips.parquet"
            if not p.exists():
                continue
            df = pd.read_parquet(p)
            if len(df) == 0:
                continue
            df["policy"] = policy
            df["policy_family"] = policy_family(policy)
            df["window_name"] = policy_window(policy)
            df["period_key"] = period_key
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["decision_ts", "policy", "policy_family", "window_name", "period_key"])
    out = pd.concat(frames, ignore_index=True)
    out["deploy_month"] = month_from_ts(out["decision_ts"])
    return out


def load_all_cancellations() -> pd.DataFrame:
    frames = []
    for period_key in PERIODS:
        for policy in ALL_POLICIES:
            p = c.NT_OUT_ROOT / f"{policy}_{period_key}" / "pending_cancellations.parquet"
            if not p.exists():
                continue
            df = pd.read_parquet(p)
            if len(df) == 0:
                continue
            df["policy"] = policy
            df["policy_family"] = policy_family(policy)
            df["window_name"] = policy_window(policy)
            df["period_key"] = period_key
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["decision_ts", "policy", "policy_family", "window_name", "period_key"])
    out = pd.concat(frames, ignore_index=True)
    out["deploy_month"] = month_from_ts(out["decision_ts"])
    return out


def load_eligible_population() -> pd.DataFrame:
    """F2 eligible-signal population per month, independent of policy --
    same underlying confirmed-signal count feeds every policy's skip filter."""
    f2 = c.load_f2_atlas()
    in_range = (f2["observation_time"] >= pd.Timestamp("2025-01-01", tz="UTC").value) & \
               (f2["observation_time"] <= pd.Timestamp("2026-04-29 23:59:59", tz="UTC").value)
    f2 = f2[in_range].copy()
    f2["deploy_month"] = month_from_ts(f2["observation_time"])
    return f2


def main():
    print("Loading eligible F2 population...")
    eligible = load_eligible_population()
    eligible.to_parquet(WORK_DIR / "eligible_population.parquet", index=False)
    print(f"  {len(eligible)} eligible signals, Jan2025-Apr2026")

    print("Loading NT trades...")
    trades = load_all_trades()
    trades.to_parquet(WORK_DIR / "nt_trade_results.parquet", index=False)
    print(f"  {len(trades)} filled trades across {trades['policy'].nunique()} policies")

    print("Loading NT policy skips...")
    skips = load_all_skips()
    skips.to_parquet(WORK_DIR / "nt_policy_skips.parquet", index=False)
    print(f"  {len(skips)} policy-skip rows")

    print("Loading NT pending cancellations...")
    cancels = load_all_cancellations()
    cancels.to_parquet(WORK_DIR / "nt_pending_cancellations.parquet", index=False)
    print(f"  {len(cancels)} pending-cancellation rows")

    print("\nPer-policy filled-trade counts:")
    print(trades.groupby("policy").size().sort_values(ascending=False))


if __name__ == "__main__":
    main()

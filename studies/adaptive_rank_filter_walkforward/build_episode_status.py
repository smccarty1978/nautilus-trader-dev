"""Build one master table: every (policy, eligible F2 episode) pair with its
resolved status (skipped / pending_entry_canceled / filled) and net_pnl if
filled. Every downstream metric (monthly, pooled, final-reserved, drawdown,
runner retention, tail dependence, bootstrap, matched-random) is computed
from this single table so every metric uses the identical episode population
and identical status resolution.

Join note: the atlas's `observation_time` (pandas 1m-bar-close pipeline) and
NT's `decision_ts` (live event-loop bucket-close, CollectorV2Strategy) refer
to the same logical confirmation instant but differ by 1-20 seconds due to
cross-pipeline discretization (confirmed empirically: exact-equality join
matched ZERO of 15,629 episodes; a 20s-tolerance nearest-match recovers
15,559/15,607 atlas-"filled" episodes, and correctly matches 0/22 atlas-
"pending_entry_canceled" episodes to an R0 fill). 20s matches
CollectorV2Strategy's own `_skip_match_tolerance_ns`, so the same tolerance
this study's execution layer already uses for its skip-list matching is
reused here for the analysis-side join.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from run_nt_adaptive import ALL_POLICIES

WORK_DIR = c.OUT.parent / "_work"
JOIN_TOLERANCE_NS = 20_000_000_000


def entry_delay_bucket(fill_gap_seconds: float) -> str:
    if pd.isna(fill_gap_seconds):
        return "unknown"
    g = abs(fill_gap_seconds)
    if g <= 1:
        return "0-1s"
    if g <= 5:
        return "1-5s"
    return ">5s"


def asof_join(base: pd.DataFrame, other: pd.DataFrame, other_ts_col: str, value_cols: list[str]) -> pd.DataFrame:
    """Nearest-match `other` onto `base` (keyed on confirmation_ts <-> other_ts_col),
    within JOIN_TOLERANCE_NS. `base` must be sorted by confirmation_ts already;
    returns value_cols aligned to base's original row order."""
    if len(other) == 0:
        out = base[["confirmation_ts"]].copy()
        for col in value_cols:
            out[col] = np.nan
        return out
    other_sorted = other[[other_ts_col] + value_cols].sort_values(other_ts_col)
    merged = pd.merge_asof(base[["confirmation_ts"]], other_sorted,
                             left_on="confirmation_ts", right_on=other_ts_col,
                             direction="nearest", tolerance=JOIN_TOLERANCE_NS)
    return merged


def main():
    eligible = pd.read_parquet(WORK_DIR / "eligible_population.parquet")
    skips = pd.read_parquet(WORK_DIR / "nt_policy_skips.parquet")
    cancels = pd.read_parquet(WORK_DIR / "nt_pending_cancellations.parquet")
    trades = pd.read_parquet(WORK_DIR / "nt_trade_results.parquet")

    eligible = eligible.copy()
    eligible["confirmation_ts"] = eligible["observation_time"].astype("int64")
    eligible["entry_delay_bucket"] = eligible["fill_gap_seconds"].apply(entry_delay_bucket)
    eligible["atr_bucket_static"] = pd.qcut(eligible["atr"], 3, labels=["low", "mid", "high"], duplicates="drop")
    eligible = eligible.sort_values("confirmation_ts").reset_index(drop=True)

    base_cols = ["confirmation_ts", "deploy_month", "direction", "session", "atr",
                 "atr_bucket_static", "entry_delay_bucket", "seq_5r_center_migration_slope_atr",
                 "seq_5r_asym_duration", "baseline_pnl", "trade_status"]
    base = eligible[base_cols].copy()

    rows = []
    for policy in ALL_POLICIES:
        b = base.copy()
        b["policy"] = policy
        b["policy_family"] = "r0" if policy == "r0" else (policy if policy.startswith("static") else policy.split("_", 1)[0])
        b["window_name"] = None if policy in ("r0", "static_r2", "static_r4") else policy.split("_", 1)[1]

        pol_skips = skips[skips["policy"] == policy]
        pol_cancels = cancels[cancels["policy"] == policy]
        pol_trades = trades[trades["policy"] == policy]

        skip_match = asof_join(b, pol_skips, "decision_ts", []) if len(pol_skips) else None
        cancel_match = asof_join(b, pol_cancels, "decision_ts", []) if len(pol_cancels) else None
        trade_match = asof_join(b, pol_trades, "decision_ts", ["net_pnl"])

        skipped = skip_match["decision_ts"].notna().values if skip_match is not None and "decision_ts" in skip_match else np.zeros(len(b), dtype=bool)
        canceled = cancel_match["decision_ts"].notna().values if cancel_match is not None and "decision_ts" in cancel_match else np.zeros(len(b), dtype=bool)
        net_pnl = trade_match["net_pnl"].values

        b["skipped"] = skipped
        b["pending_canceled"] = (~skipped) & canceled
        b["filled"] = (~skipped) & (~canceled) & ~pd.isna(net_pnl)
        b["net_pnl"] = np.where(b["filled"], net_pnl, np.nan)
        rows.append(b)

    status = pd.concat(rows, ignore_index=True)
    status["unresolved"] = ~(status["skipped"] | status["pending_canceled"] | status["filled"])

    status.to_parquet(WORK_DIR / "episode_status.parquet", index=False)
    print(f"episode_status: {len(status)} rows ({len(ALL_POLICIES)} policies x {len(base)} eligible episodes)")
    print(status.groupby("policy")[["skipped", "pending_canceled", "filled", "unresolved"]].sum())


if __name__ == "__main__":
    main()

"""Builds the repaired, F2-only, per-episode table with R0/R1/R2 policy
assignment -- the base table every downstream phase (5-13) reads.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from common import OUT, SRC, load_atlas, repair_and_build_f2, load_frozen_policy

sys.path.insert(0, str(SRC.parent))
from run_flip_filter_replay import apply_policies


def build_episodes() -> pd.DataFrame:
    df_atlas = load_atlas()
    f2_clean, viol_df = repair_and_build_f2(df_atlas)
    frozen = load_frozen_policy()
    thr = frozen["threshold"]

    # R2 (F4 benchmark): reuse the prior study's exact filter logic (F1-F4
    # feature-threshold rules), applied only to the repaired/clean episodes.
    f2_policies = apply_policies(f2_clean, threshold_fail_prob=thr)

    ep = f2_policies.copy()
    ep["frozen_f5_score"] = ep["ridge_log_fail_prob"]
    ep["frozen_threshold"] = thr
    ep["f5_skip"] = ~ep["filter_F5_keep"]
    ep["f4_skip"] = ~ep["filter_F4_keep"]

    ep["baseline_exit_ts"] = ep["ep_end_time"]
    ep["baseline_exit_price"] = ep["exit_price"]
    ep["baseline_net_pnl"] = ep["pnl_base"]

    ep["f5_net_pnl"] = np.where(ep["f5_skip"], 0.0, ep["baseline_net_pnl"])
    ep["f4_net_pnl"] = np.where(ep["f4_skip"], 0.0, ep["baseline_net_pnl"])
    ep["paired_delta_f5"] = ep["f5_net_pnl"] - ep["baseline_net_pnl"]
    ep["paired_delta_f4"] = ep["f4_net_pnl"] - ep["baseline_net_pnl"]

    keep_cols = [
        "episode_id", "population", "observation_time", "entry_price", "direction",
        "session", "month", "period_role", "frozen_f5_score", "frozen_threshold",
        "f5_skip", "f4_skip", "baseline_exit_ts", "baseline_exit_price",
        "baseline_net_pnl", "f5_net_pnl", "f4_net_pnl", "paired_delta_f5",
        "paired_delta_f4", "runner_tier", "atr_bucket", "entry_delay_bucket", "atr",
        "exit_type",
    ]
    ep = ep[keep_cols].rename(columns={"observation_time": "entry_ts"})
    ep["episode_id"] = ep["episode_id"].astype(str)
    return ep


def run():
    ep = build_episodes()
    out = ep.rename(columns={
        "f5_net_pnl": "f5_net_pnl",
        "paired_delta_f5": "paired_delta",
    })
    out.to_parquet(OUT / "f5_episode_results.parquet", index=False)
    print(f"f5_episode_results: {len(out)} eligible F2 episodes, "
          f"{int(out['f5_skip'].sum())} skipped by frozen F5 "
          f"({out['f5_skip'].mean()*100:.2f}%)")
    return ep


if __name__ == "__main__":
    import os
    os.chdir(SRC.parent.parent.parent)
    run()

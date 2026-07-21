"""paired_bootstrap.parquet: for every adaptive policy, a paired bootstrap CI
(episode-level resampling with replacement, 10,000 iterations, matching
studies/rank_filter_oos_validation's convention) for:
  - EV lift vs R0
  - EV lift vs its static counterpart (A2 vs static_r2, A4 vs static_r4;
    A1 has no static counterpart in this study's scope, R0 only)
  - net PnL delta (same comparisons, scaled by eligible-episode count)
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from compute_metrics import POOLED_BLOCKS, month_in_block
from compute_retention_tail import build_pairs

WORK_DIR = c.OUT.parent / "_work"
N_BOOT = 10_000
RNG_SEED = 42

STATIC_COUNTERPART = {"a1": None, "a2": "static_r2", "a4": "static_r4"}


def paired_bootstrap_ci(pol_contrib: np.ndarray, cmp_contrib: np.ndarray, n_boot: int, rng: np.random.Generator):
    n = len(pol_contrib)
    idx = rng.integers(0, n, size=(n_boot, n))
    pol_samples = pol_contrib[idx]
    cmp_samples = cmp_contrib[idx]
    lift_samples = pol_samples.mean(axis=1) - cmp_samples.mean(axis=1)
    pnl_delta_samples = (pol_samples - cmp_samples).sum(axis=1)
    return lift_samples, pnl_delta_samples


def main():
    status = pd.read_parquet(WORK_DIR / "episode_status.parquet")
    adaptive_policies = [p for p in status["policy"].unique() if p not in ("r0", "static_r2", "static_r4")]
    rng = np.random.default_rng(RNG_SEED)

    rows = []
    for block_name, block in POOLED_BLOCKS.items():
        for policy in adaptive_policies:
            family = policy.split("_", 1)[0]  # a1/a2/a4
            comparators = ["r0"]
            static_cp = STATIC_COUNTERPART[family]
            if static_cp:
                comparators.append(static_cp)

            for comparator in comparators:
                df = build_pairs(status, policy, block) if comparator == "r0" else None
                if comparator == "r0":
                    pol_contrib = df["pol_pnl_contrib"].values
                    cmp_contrib = df["r0_pnl_contrib"].values
                else:
                    # policy vs static comparator: build a symmetric pair frame
                    pol = status[(status["policy"] == policy) & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))].set_index("confirmation_ts")
                    stat = status[(status["policy"] == comparator) & (status["deploy_month"].apply(lambda m: month_in_block(m, block)))].set_index("confirmation_ts")
                    joined = pd.DataFrame({
                        "pol_pnl": np.where(pol["filled"], pol["net_pnl"], 0.0),
                        "stat_pnl": np.where(stat["filled"], stat["net_pnl"], 0.0),
                    })
                    pol_contrib = joined["pol_pnl"].values
                    cmp_contrib = joined["stat_pnl"].values

                if len(pol_contrib) == 0:
                    continue
                lift_samples, pnl_delta_samples = paired_bootstrap_ci(pol_contrib, cmp_contrib, N_BOOT, rng)
                real_lift = float(pol_contrib.mean() - cmp_contrib.mean())
                real_pnl_delta = float((pol_contrib - cmp_contrib).sum())

                rows.append({
                    "block": block_name, "policy": policy, "comparator": comparator,
                    "n_episodes": len(pol_contrib),
                    "paired_ev_lift": real_lift,
                    "ev_lift_ci_lo": float(np.percentile(lift_samples, 2.5)),
                    "ev_lift_ci_hi": float(np.percentile(lift_samples, 97.5)),
                    "net_pnl_delta": real_pnl_delta,
                    "pnl_delta_ci_lo": float(np.percentile(pnl_delta_samples, 2.5)),
                    "pnl_delta_ci_hi": float(np.percentile(pnl_delta_samples, 97.5)),
                })

    out = pd.DataFrame(rows)
    out.to_parquet(c.OUT / "paired_bootstrap.parquet", index=False)
    print("paired_bootstrap:", out.shape)
    print(out[out["block"] == "2026_MarApr_final_reserved"].to_string(index=False))


if __name__ == "__main__":
    main()

"""Paired episode-level bootstrap (10,000 iterations) for R1, R2, and R4 vs
R0, pooled over Jun-Dec 2025. Defensively guarantees finite CI fields."""
import numpy as np
import pandas as pd
from common import OUT
from build_episodes import build

N_ITER = 10000
SEED = 20260707


def paired_bootstrap(deltas: np.ndarray, n_iter=N_ITER, seed=SEED) -> dict:
    n = len(deltas)
    if n == 0:
        return {"n_episodes": 0, "n_iterations": n_iter, "mean_paired_lift": 0.0,
                "median_paired_lift": 0.0, "ci_lo_95": 0.0, "ci_hi_95": 0.0,
                "p_gt_0": 0.0, "p_ge_2": 0.0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = deltas[idx].mean(axis=1)
    boot_means = boot_means[np.isfinite(boot_means)]
    if len(boot_means) == 0:
        boot_means = np.array([0.0])
    return {
        "n_episodes": n,
        "n_iterations": n_iter,
        "mean_paired_lift": float(np.mean(boot_means)),
        "median_paired_lift": float(np.median(boot_means)),
        "ci_lo_95": float(np.percentile(boot_means, 2.5)),
        "ci_hi_95": float(np.percentile(boot_means, 97.5)),
        "p_gt_0": float((boot_means > 0).mean()),
        "p_ge_2": float((boot_means >= 2.0).mean()),
    }


def run():
    ep = build()
    rows = []
    for p in ("r1", "r2", "r4"):
        deltas = (ep[f"{p}_net_pnl"] - ep["r0_net_pnl"]).values.astype(np.float64)
        r = paired_bootstrap(deltas)
        r["policy"] = p.upper()
        rows.append(r)
    df = pd.DataFrame(rows)[["policy", "n_episodes", "n_iterations", "mean_paired_lift", "median_paired_lift",
                              "ci_lo_95", "ci_hi_95", "p_gt_0", "p_ge_2"]]
    assert np.isfinite(df[["mean_paired_lift", "ci_lo_95", "ci_hi_95"]].values).all(), "non-finite bootstrap CI found"
    df.to_parquet(OUT / "paired_bootstrap.parquet", index=False)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()

"""Phase 10: Matched-random skip controls.

For each evaluation period, draw 1000 seeds of random skips matched EXACTLY
(same count per stratum) to F5's real skip distribution on
(month, session, direction, entry_delay_bucket, atr_bucket), then compare
F5's real paired EV lift / drawdown change / runner retention against the
empirical distribution of the matched-random controls.
"""
import numpy as np
import pandas as pd
from common import OUT
from f5_episodes import build_episodes
from f5_economics import EVAL_PERIODS

N_SEEDS = 1000
BASE_SEED = 20260707
STRATA_COLS = ["month", "session", "direction", "entry_delay_bucket", "atr_bucket"]


def matched_random_skip_matrix(g: pd.DataFrame, n_seeds: int, base_seed: int) -> np.ndarray:
    """Return boolean matrix (n_seeds, len(g)) of random skips exactly matched
    per-stratum to g['f5_skip'] counts."""
    g = g.reset_index(drop=True)
    n = len(g)
    stratum_key = g[STRATA_COLS].astype(str).agg("|".join, axis=1)
    codes, uniques = pd.factorize(stratum_key)
    k_target = g.groupby(codes)["f5_skip"].sum().reindex(range(len(uniques)), fill_value=0).astype(int).values

    skip_mask = np.zeros((n_seeds, n), dtype=bool)
    rng = np.random.default_rng(base_seed)
    for stratum_id in range(len(uniques)):
        member_pos = np.where(codes == stratum_id)[0]
        m = len(member_pos)
        k = int(k_target[stratum_id])
        if m == 0 or k == 0:
            continue
        k = min(k, m)
        rand_mat = rng.random((n_seeds, m))
        order = np.argsort(rand_mat, axis=1)
        skip_cols = order[:, :k]  # (n_seeds, k) positions within stratum
        seed_idx = np.repeat(np.arange(n_seeds), k)
        global_pos = member_pos[skip_cols.ravel()]
        skip_mask[seed_idx, global_pos] = True
    return skip_mask


def run_period(ep: pd.DataFrame, mask: pd.Series, label: str, n_seeds=N_SEEDS):
    g = ep[mask].sort_values("entry_ts").reset_index(drop=True)
    n = len(g)
    if n == 0:
        return pd.DataFrame(), {}

    skip_mask = matched_random_skip_matrix(g, n_seeds, BASE_SEED + hash(label) % 10_000)
    baseline = g["baseline_net_pnl"].values.astype(np.float64)
    is_runner10 = (g["runner_tier"] == "top10").values

    kept_pnl = baseline[None, :] * (~skip_mask)  # (n_seeds, n)
    total_pnl_change = kept_pnl.sum(axis=1) - baseline.sum()
    paired_ev_lift = total_pnl_change / n

    baseline_runner_pnl = baseline[is_runner10].sum()
    retained_runner_pnl = kept_pnl[:, is_runner10].sum(axis=1)
    runner_retention = retained_runner_pnl / baseline_runner_pnl if baseline_runner_pnl != 0 else np.full(n_seeds, np.nan)

    cum = np.cumsum(kept_pnl, axis=1)
    peak = np.maximum.accumulate(cum, axis=1)
    dd = peak - cum
    max_dd = dd.max(axis=1)

    cum_base = np.cumsum(baseline)
    peak_base = np.maximum.accumulate(cum_base)
    max_dd_base = float((peak_base - cum_base).max())
    max_dd_change = max_dd_base - max_dd

    per_seed = pd.DataFrame({
        "period": label,
        "seed": np.arange(n_seeds),
        "paired_ev_lift": paired_ev_lift,
        "total_pnl_change": total_pnl_change,
        "runner_retention": runner_retention,
        "max_drawdown_change": max_dd_change,
    })

    # Real F5
    f5_deltas = (g["f5_net_pnl"] - g["baseline_net_pnl"]).values
    f5_lift = float(f5_deltas.mean())
    f5_total_change = float(f5_deltas.sum())
    f5_runner_mask = (~g["f5_skip"].values) & is_runner10
    f5_runner_retention = float(g.loc[f5_runner_mask, "baseline_net_pnl"].sum() / baseline_runner_pnl) if baseline_runner_pnl != 0 else float("nan")
    f5_cum = np.cumsum(g["f5_net_pnl"].values)
    f5_peak = np.maximum.accumulate(f5_cum)
    f5_max_dd = float((f5_peak - f5_cum).max())
    f5_dd_change = max_dd_base - f5_max_dd

    summary = {
        "period": label,
        "f5_real_lift": f5_lift,
        "f5_real_total_pnl_change": f5_total_change,
        "f5_real_runner_retention": f5_runner_retention,
        "f5_real_drawdown_change": f5_dd_change,
        "random_mean": float(paired_ev_lift.mean()),
        "random_median": float(np.median(paired_ev_lift)),
        "random_std": float(paired_ev_lift.std()),
        "random_p5": float(np.percentile(paired_ev_lift, 5)),
        "random_p25": float(np.percentile(paired_ev_lift, 25)),
        "random_p75": float(np.percentile(paired_ev_lift, 75)),
        "random_p95": float(np.percentile(paired_ev_lift, 95)),
        "fraction_random_ge_f5": float((paired_ev_lift >= f5_lift).mean()),
        "empirical_p_value": float((paired_ev_lift >= f5_lift).mean()),
        "n_seeds": n_seeds,
        "n_episodes": n,
        "n_skipped": int(g["f5_skip"].sum()),
    }
    return per_seed, summary


def run():
    ep = build_episodes()
    all_seeds = []
    summaries = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        per_seed, summary = run_period(ep, mask, role)
        all_seeds.append(per_seed)
        summaries.append(summary)

    df_seeds = pd.concat(all_seeds, ignore_index=True)
    df_seeds.to_parquet(OUT / "matched_random_skip_controls.parquet", index=False)

    df_summary = pd.DataFrame(summaries)
    df_summary.to_parquet(OUT / "matched_random_skip_summary.parquet", index=False)

    print(df_summary[["period", "f5_real_lift", "random_mean", "random_p5", "random_p95", "empirical_p_value"]].to_string(index=False))
    return df_seeds, df_summary


if __name__ == "__main__":
    import os
    from common import SRC
    os.chdir(SRC.parent.parent.parent)
    run()

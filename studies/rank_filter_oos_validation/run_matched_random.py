"""Matched-random skip controls for R1, R2, and R4: 1000 seeds, exact
per-stratum skip counts matched on month x direction x session x
atr_bucket x entry_delay_bucket. ATR-bucket (and, for consistency,
entry-delay-bucket) edges are FROZEN on the validation period (Jan-Feb 2025)
-- not re-quantiled on the Jun-Dec 2025 test period, per the study brief.
"""
import numpy as np
import pandas as pd
from common import OUT, load_atlas, repair_f2_window, VAL_START, VAL_END
from build_episodes import build

N_SEEDS = 1000
BASE_SEED = 20260707
STRATA_COLS = ["month", "direction", "session", "atr_bucket", "entry_delay_bucket"]


def frozen_bucket_edges(val: pd.DataFrame) -> dict:
    atr_edges = np.percentile(val["atr"].dropna(), [0, 33.333, 66.667, 100])
    atr_edges[0] -= 1e-9
    atr_edges[-1] += 1e-9
    delay_edges = np.percentile(val["seconds_in_current_ordering"].dropna(), [0, 33.333, 66.667, 100])
    delay_edges[0] -= 1e-9
    delay_edges[-1] += 1e-9
    return {"atr_edges": atr_edges, "delay_edges": delay_edges}


def apply_frozen_buckets(ep: pd.DataFrame, edges: dict) -> pd.DataFrame:
    ep = ep.copy()
    ep["atr_bucket"] = pd.cut(ep["atr"], bins=edges["atr_edges"], labels=["low_vol", "mid_vol", "high_vol"]).astype(str)
    ep["atr_bucket"] = ep["atr_bucket"].replace("nan", "mid_vol")  # clip out-of-range (above max val ATR) to nearest
    ep.loc[ep["atr"] > edges["atr_edges"][-1], "atr_bucket"] = "high_vol"
    ep.loc[ep["atr"] < edges["atr_edges"][0], "atr_bucket"] = "low_vol"

    ep["entry_delay_bucket"] = pd.cut(ep["seconds_in_current_ordering"], bins=edges["delay_edges"],
                                       labels=["short_delay", "mid_delay", "long_delay"]).astype(str)
    ep.loc[ep["seconds_in_current_ordering"] > edges["delay_edges"][-1], "entry_delay_bucket"] = "long_delay"
    ep.loc[ep["seconds_in_current_ordering"] < edges["delay_edges"][0], "entry_delay_bucket"] = "short_delay"
    ep["entry_delay_bucket"] = ep["entry_delay_bucket"].replace("nan", "mid_delay")
    return ep


def matched_random_skip_matrix(g: pd.DataFrame, skip_col: str, n_seeds: int, base_seed: int) -> np.ndarray:
    g = g.reset_index(drop=True)
    n = len(g)
    stratum_key = g[STRATA_COLS].astype(str).agg("|".join, axis=1)
    codes, uniques = pd.factorize(stratum_key)
    k_target = g.groupby(codes)[skip_col].sum().reindex(range(len(uniques)), fill_value=0).astype(int).values

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
        skip_cols = order[:, :k]
        seed_idx = np.repeat(np.arange(n_seeds), k)
        global_pos = member_pos[skip_cols.ravel()]
        skip_mask[seed_idx, global_pos] = True
    return skip_mask


def run():
    df_atlas = load_atlas()
    val, _ = repair_f2_window(df_atlas, VAL_START, VAL_END)
    edges = frozen_bucket_edges(val)

    ep = build().sort_values("confirmation_ts").reset_index(drop=True)
    ep = apply_frozen_buckets(ep, edges)

    all_seeds = []
    summaries = []
    for p in ("r1", "r2", "r4"):
        skip_mask = matched_random_skip_matrix(ep, f"{p}_skip", N_SEEDS, BASE_SEED + hash(p) % 10_000)
        # r0_net_pnl is the correct "what would this episode realize under R0"
        # baseline for matched-random comparison: 0.0 for pending-entry-canceled
        # (no capital ever at risk, same for every policy), real PnL if filled.
        # baseline_pnl itself is NaN for canceled rows and must not be used here.
        baseline = ep["r0_net_pnl"].values.astype(np.float64)
        n = len(ep)

        kept_pnl = baseline[None, :] * (~skip_mask)
        random_lift = kept_pnl.sum(axis=1) / n - baseline.mean()

        real_lift = float((ep[f"{p}_net_pnl"] - ep["r0_net_pnl"]).mean())

        seed_df = pd.DataFrame({"policy": p.upper(), "seed": np.arange(N_SEEDS), "lift": random_lift})
        all_seeds.append(seed_df)

        summaries.append({
            "policy": p.upper(),
            "real_ev_lift": real_lift,
            "random_mean": float(random_lift.mean()),
            "random_median": float(np.median(random_lift)),
            "random_p95": float(np.percentile(random_lift, 95)),
            "fraction_random_beating_real": float((random_lift > real_lift).mean()),
            "empirical_p_value": float((random_lift >= real_lift).mean()),
            "n_seeds": N_SEEDS,
            "atr_bucket_edges_source": "frozen on validation period (2025-01-01 to 2025-02-28), applied via fixed pd.cut on primary window",
        })

    df_seeds = pd.concat(all_seeds, ignore_index=True)
    assert df_seeds["lift"].isna().sum() == 0, "NaN in matched-random controls"
    df_seeds.to_parquet(OUT / "matched_random_controls.parquet", index=False)

    df_summary = pd.DataFrame(summaries)
    assert df_summary[["real_ev_lift", "random_mean", "random_median", "random_p95", "empirical_p_value"]].isna().sum().sum() == 0
    df_summary.to_parquet(OUT / "corrected_matched_random_summary.parquet", index=False)

    print(df_summary.to_string(index=False))
    return df_seeds, df_summary


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()

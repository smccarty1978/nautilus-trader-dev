"""Phase 2: matched-random skip controls on the REAL NT trade population
(1000 seeds), matched on month x direction x session x ATR-bucket. ATR-bucket
edges frozen on the validation period (2025-01-01 to 2025-02-28) via the
corrected research table -- not re-quantiled on the NT run's own data.

Note: the corrected research-table matched-random control also matches on
an entry-delay-bucket proxy (seconds_in_current_ordering, unavailable in the
NT strategy's own trade output schema); this NT-side control therefore uses
4 strata (month, direction, session, atr_bucket) rather than 5, documented
here rather than silently dropped.
"""
import numpy as np
import pandas as pd
from common import OUT, load_atlas, repair_f2_window, VAL_START, VAL_END
from parse_nt_results import load_run, POLICIES, PERIODS

N_SEEDS = 1000
BASE_SEED = 20260707
STRATA_COLS = ["month", "direction", "session", "atr_bucket"]


def frozen_atr_edges() -> np.ndarray:
    df_atlas = load_atlas()
    val, _ = repair_f2_window(df_atlas, VAL_START, VAL_END)
    edges = np.percentile(val["atr"].dropna(), [0, 33.333, 66.667, 100])
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    return edges


def build_r0_pool(period: str, atr_edges: np.ndarray) -> pd.DataFrame:
    """R0's own trades + pending cancellations = the full structural
    eligible pool to draw matched-random skips from (canceled episodes
    contribute $0 regardless of any filter, same as every policy)."""
    r0 = load_run("r0", period)
    trades = r0["trades"].copy()
    trades["net_pnl_r0"] = trades["net_pnl"]
    canc = r0["pending_cancellations"].copy()
    if len(canc):
        canc["net_pnl_r0"] = 0.0
        canc["entry_ts"] = canc["decision_ts"]  # for month bucketing only
        canc["session"] = "UNKNOWN"
        canc = canc.rename(columns={})
    pool_cols = ["decision_ts", "direction", "net_pnl_r0"]
    trades_pool = trades[pool_cols + ["session", "atr_at_signal", "entry_ts"]].copy()
    if len(canc):
        canc_pool = canc[["decision_ts", "direction", "net_pnl_r0"]].copy()
        canc_pool["session"] = "UNKNOWN"
        canc_pool["atr_at_signal"] = np.nan
        canc_pool["entry_ts"] = canc["decision_ts"]
        pool = pd.concat([trades_pool, canc_pool], ignore_index=True)
    else:
        pool = trades_pool
    pool["month"] = pd.to_datetime(pool["decision_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
    pool["atr_bucket"] = pd.cut(pool["atr_at_signal"], bins=atr_edges, labels=["low_vol", "mid_vol", "high_vol"]).astype(str)
    pool.loc[pool["atr_bucket"] == "nan", "atr_bucket"] = "mid_vol"
    return pool


def matched_random_skip_matrix(pool: pd.DataFrame, k_target_by_stratum: dict, n_seeds: int, base_seed: int) -> np.ndarray:
    pool = pool.reset_index(drop=True)
    n = len(pool)
    stratum_key = pool[STRATA_COLS].astype(str).agg("|".join, axis=1)
    codes, uniques = pd.factorize(stratum_key)
    k_arr = np.array([k_target_by_stratum.get(u, 0) for u in uniques], dtype=int)

    skip_mask = np.zeros((n_seeds, n), dtype=bool)
    rng = np.random.default_rng(base_seed)
    for stratum_id in range(len(uniques)):
        member_pos = np.where(codes == stratum_id)[0]
        m = len(member_pos)
        k = int(k_arr[stratum_id])
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
    atr_edges = frozen_atr_edges()
    rows = []
    for period in PERIODS:
        pool = build_r0_pool(period, atr_edges)
        pool_key = pool[STRATA_COLS].astype(str).agg("|".join, axis=1)

        for policy in ("r2", "r4"):
            run_p = load_run(policy, period)
            skips = run_p["policy_skips"]
            if len(skips) == 0:
                rows.append({"policy": policy.upper(), "period": period, "real_nt_ev_lift": 0.0,
                             "random_median": 0.0, "random_p95": 0.0, "empirical_p_value": 1.0, "n_seeds": N_SEEDS})
                continue
            skips = skips.copy()
            skips["month"] = pd.to_datetime(skips["decision_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
            # match skipped decision_ts back to the pool row for session/atr bucket
            pool_by_ts = pool.set_index("decision_ts")
            skips["session"] = skips["decision_ts"].map(pool_by_ts["session"]).fillna("UNKNOWN")
            skips["atr_bucket"] = skips["decision_ts"].map(pool_by_ts["atr_bucket"]).fillna("mid_vol")
            skip_stratum_key = skips[STRATA_COLS].astype(str).agg("|".join, axis=1)
            k_target_by_stratum = skip_stratum_key.value_counts().to_dict()

            skip_mask = matched_random_skip_matrix(pool, k_target_by_stratum, N_SEEDS, BASE_SEED + hash(policy + period) % 10_000)
            baseline = pool["net_pnl_r0"].values.astype(np.float64)
            n = len(pool)
            kept_pnl = baseline[None, :] * (~skip_mask)
            random_lift = kept_pnl.sum(axis=1) / n - baseline.mean()

            r0_ev = float(baseline.mean())
            r_ev = float(run_p["trades"]["net_pnl"].sum() / (len(run_p["trades"]) + len(run_p["pending_cancellations"]) + len(run_p["policy_skips"]))) if len(run_p["trades"]) or len(run_p["policy_skips"]) else 0.0
            real_lift = r_ev - r0_ev

            rows.append({
                "policy": policy.upper(), "period": period,
                "real_nt_ev_lift": real_lift,
                "random_mean": float(random_lift.mean()),
                "random_median": float(np.median(random_lift)),
                "random_p95": float(np.percentile(random_lift, 95)),
                "fraction_random_beating_real": float((random_lift > real_lift).mean()),
                "empirical_p_value": float((random_lift >= real_lift).mean()),
                "n_seeds": N_SEEDS,
                "strata": "month x direction x session x atr_bucket (entry_delay_bucket unavailable in NT trade schema, documented)",
                "atr_bucket_edges_source": "frozen on validation period via corrected research table",
            })

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "nt_matched_random_summary.parquet", index=False)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()

"""Aggregate the frozen-policy stability audit's 24 NT runs (8 blocks x
R0/R2/R4) into the required period_metrics / period_runner_retention /
period_drawdown_metrics / period_matched_random / tail_dependence outputs.

Every number here is a RETROSPECTIVE ROBUSTNESS DIAGNOSTIC over already-
frozen R0/R2/R4 policies -- no threshold/exemption was touched, and no
block is being treated as new out-of-sample evidence.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR = PROJECT_ROOT / "studies/rank_filter_oos_validation/results/frozen_stability_audit"
AUDIT_RUNS = AUDIT_DIR / "nt_runs"
RESEARCH_OUT = PROJECT_ROOT / "studies/rank_filter_oos_validation/results"

BLOCK_ORDER = ["2021", "2022", "2023", "2024", "2025_JanFeb", "2025_MarMay", "2025_JunDec", "2026_JanApr29"]
CATALOG_BUG_BLOCKS = {"2021", "2022", "2023", "2024"}
POLICIES = ["r0", "r2", "r4"]

N_SEEDS = 1000
BASE_SEED = 20260707
STRATA_COLS = ["month", "direction", "session", "atr_bucket"]


def load_run(policy: str, block_key: str) -> dict:
    d = AUDIT_RUNS / f"{policy}_{block_key}"
    out = {"policy": policy, "block": block_key}
    for name in ("trades", "policy_skips", "pending_cancellations"):
        p = d / f"{name}.parquet"
        out[name] = pd.read_parquet(p) if p.exists() else pd.DataFrame()
    meta_p = d / "run_meta.json"
    out["meta"] = json.load(open(meta_p)) if meta_p.exists() else {}
    return out


def pf(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    w = x[x > 0].sum()
    l = -x[x < 0].sum()
    return float(w / l) if l > 0 else (float(w) if w > 0 else 0.0)


def max_dd_and_duration(pnl_chrono: np.ndarray) -> tuple[float, int]:
    if len(pnl_chrono) == 0:
        return 0.0, 0
    cum = np.cumsum(pnl_chrono)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max())
    in_dd = dd > 1e-9
    longest = cur = 0
    for flag in in_dd:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    return max_dd, longest


def eligible_counts(run: dict) -> dict:
    n_filled = len(run["trades"])
    n_canceled = len(run["pending_cancellations"])
    n_skipped = len(run["policy_skips"])
    return {
        "eligible_signals": n_filled + n_canceled + n_skipped,
        "pending_entries_canceled": n_canceled,
        "filter_skipped": n_skipped,
        "filled_trades": n_filled,
    }


def policy_metrics_row(run: dict) -> dict:
    trades = run["trades"]
    counts = eligible_counts(run)
    n_elig = counts["eligible_signals"]
    n_filled = counts["filled_trades"]
    net_pnl = trades["net_pnl"].values if len(trades) else np.array([])
    trades_chrono = trades.sort_values("entry_ts") if len(trades) else trades
    pnl_chrono = trades_chrono["net_pnl"].values if len(trades_chrono) else np.array([])
    max_dd, longest_dd = max_dd_and_duration(pnl_chrono)
    return {
        "policy": run["policy"].upper(), "block": run["block"],
        **counts,
        "retention": (n_filled / n_elig) if n_elig else 0.0,
        "ev_per_eligible_signal": float(net_pnl.sum() / n_elig) if n_elig else 0.0,
        "ev_per_filled_trade": float(net_pnl.mean()) if n_filled else 0.0,
        "net_pnl_total": float(net_pnl.sum()) if n_filled else 0.0,
        "win_rate": float((net_pnl > 0).mean()) if n_filled else 0.0,
        "profit_factor": pf(net_pnl),
        "max_drawdown": max_dd,
        "longest_drawdown_duration_trades": longest_dd,
        "catalog_bug_caveat": run["block"] in CATALOG_BUG_BLOCKS,
    }


def build_period_metrics(runs: dict) -> pd.DataFrame:
    rows = [policy_metrics_row(runs[(p, b)]) for b in BLOCK_ORDER for p in POLICIES]
    df = pd.DataFrame(rows)
    for b in BLOCK_ORDER:
        r0_ev = df[(df["policy"] == "R0") & (df["block"] == b)]["ev_per_eligible_signal"].iloc[0]
        r0_pnl = df[(df["policy"] == "R0") & (df["block"] == b)]["net_pnl_total"].iloc[0]
        mask = df["block"] == b
        df.loc[mask, "ev_lift_vs_r0"] = df.loc[mask, "ev_per_eligible_signal"] - r0_ev
        df.loc[mask, "net_pnl_change_vs_r0"] = df.loc[mask, "net_pnl_total"] - r0_pnl
    df["block"] = pd.Categorical(df["block"], categories=BLOCK_ORDER, ordered=True)
    df = df.sort_values(["block", "policy"]).reset_index(drop=True)
    df["block"] = df["block"].astype(str)
    return df


def build_skipped_trade_extremes(runs: dict) -> pd.DataFrame:
    """Largest avoided loss / largest skipped winner per block/policy, using
    the counterfactual R0 outcome for each skipped decision_ts (matched by
    nearest R0 trade, since skipped entries never filled under R2/R4)."""
    rows = []
    for b in BLOCK_ORDER:
        r0 = runs[("r0", b)]["trades"]
        r0_by_ts = r0.set_index("decision_ts") if len(r0) else pd.DataFrame()
        for p in ("r2", "r4"):
            skips = runs[(p, b)]["policy_skips"]
            if len(skips) == 0 or len(r0) == 0:
                rows.append({"block": b, "policy": p.upper(), "largest_avoided_loss": 0.0,
                             "largest_skipped_winner": 0.0, "n_skipped_matched_to_r0": 0})
                continue
            matched_pnls = []
            for ts in skips["decision_ts"].values:
                if ts in r0_by_ts.index:
                    row = r0_by_ts.loc[ts]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                    matched_pnls.append(float(row["net_pnl"]))
            matched_pnls = np.array(matched_pnls)
            rows.append({
                "block": b, "policy": p.upper(),
                "largest_avoided_loss": float(matched_pnls.min()) if len(matched_pnls) else 0.0,
                "largest_skipped_winner": float(matched_pnls.max()) if len(matched_pnls) else 0.0,
                "n_skipped_matched_to_r0": len(matched_pnls),
            })
    return pd.DataFrame(rows)


def build_tail_dependence(runs: dict) -> pd.DataFrame:
    """Effect on paired EV lift after removing the top-1 / top-2 largest
    avoided losses (by magnitude) from the skipped set -- tests whether the
    filter's apparent benefit concentrates in a handful of skipped disasters."""
    rows = []
    for b in BLOCK_ORDER:
        r0 = runs[("r0", b)]["trades"]
        r0_by_ts = r0.set_index("decision_ts") if len(r0) else pd.DataFrame()
        n_elig_r0 = eligible_counts(runs[("r0", b)])["eligible_signals"]
        for p in ("r2", "r4"):
            run_p = runs[(p, b)]
            counts = eligible_counts(run_p)
            n_elig = counts["eligible_signals"]
            skips = run_p["policy_skips"]
            if len(skips) == 0 or len(r0) == 0 or n_elig == 0:
                rows.append({"block": b, "policy": p.upper(), "full_paired_lift": 0.0,
                             "lift_excl_top1_avoided_loss": 0.0, "lift_excl_top2_avoided_losses": 0.0,
                             "fraction_of_lift_from_top1": 0.0, "fraction_of_lift_from_top2": 0.0})
                continue
            skipped_pnls = []
            for ts in skips["decision_ts"].values:
                if ts in r0_by_ts.index:
                    row = r0_by_ts.loc[ts]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                    skipped_pnls.append(float(row["net_pnl"]))
            skipped_pnls = np.array(sorted(skipped_pnls))  # ascending; most negative first
            total_skipped_pnl = skipped_pnls.sum()
            full_lift = -total_skipped_pnl / n_elig  # removing these episodes' PnL from the book

            top1_loss = skipped_pnls[0] if len(skipped_pnls) >= 1 else 0.0
            top2_loss = skipped_pnls[:2].sum() if len(skipped_pnls) >= 2 else (skipped_pnls[0] if len(skipped_pnls) == 1 else 0.0)

            # lift if we DIDN'T skip the top-1 (top-2) largest avoided losses,
            # i.e. only the remaining skips contribute
            remaining_after_1 = total_skipped_pnl - top1_loss
            remaining_after_2 = total_skipped_pnl - top2_loss
            lift_excl_top1 = -remaining_after_1 / n_elig
            lift_excl_top2 = -remaining_after_2 / n_elig

            frac_top1 = (full_lift - lift_excl_top1) / full_lift if full_lift != 0 else 0.0
            frac_top2 = (full_lift - lift_excl_top2) / full_lift if full_lift != 0 else 0.0

            rows.append({
                "block": b, "policy": p.upper(),
                "full_paired_lift": float(full_lift),
                "lift_excl_top1_avoided_loss": float(lift_excl_top1),
                "lift_excl_top2_avoided_losses": float(lift_excl_top2),
                "fraction_of_lift_from_top1": float(frac_top1),
                "fraction_of_lift_from_top2": float(frac_top2),
                "n_skipped": len(skipped_pnls),
            })
    return pd.DataFrame(rows)


def build_runner_retention(runs: dict) -> pd.DataFrame:
    rows = []
    for b in BLOCK_ORDER:
        r0 = runs[("r0", b)]["trades"]
        if len(r0) == 0:
            continue
        p90, p95, p99 = r0["net_pnl"].quantile([0.90, 0.95, 0.99])
        r0 = r0.copy()
        r0["tier"] = "other"
        r0.loc[r0["net_pnl"] >= p90, "tier"] = "top10"
        r0.loc[r0["net_pnl"] >= p95, "tier"] = "top5"
        r0.loc[r0["net_pnl"] >= p99, "tier"] = "top1"
        for tier in ("top10", "top5", "top1"):
            tier_r0 = r0[r0["tier"] == tier]
            baseline_pnl = float(tier_r0["net_pnl"].sum())
            tier_keys = set(zip(tier_r0["decision_ts"].values, tier_r0["direction"].values))
            for p in ("r2", "r4"):
                trades_p = runs[(p, b)]["trades"]
                p_keys = set(zip(trades_p["decision_ts"].values, trades_p["direction"].values)) if len(trades_p) else set()
                retained_keys = tier_keys & p_keys
                retained_pnl = float(tier_r0[tier_r0.apply(lambda r: (r["decision_ts"], r["direction"]) in retained_keys, axis=1)]["net_pnl"].sum()) if len(tier_r0) else 0.0
                rows.append({
                    "block": b, "tier": tier, "policy": p.upper(),
                    "episode_count": len(tier_r0), "baseline_pnl": baseline_pnl,
                    "retained_pnl": retained_pnl,
                    "runner_pnl_retention": (retained_pnl / baseline_pnl) if baseline_pnl != 0 else 1.0,
                    "runner_count_retained": len(retained_keys),
                    "runner_count_skipped": len(tier_keys - p_keys),
                })
    return pd.DataFrame(rows)


def build_drawdown(runs: dict) -> pd.DataFrame:
    rows = []
    for b in BLOCK_ORDER:
        for p in POLICIES:
            trades = runs[(p, b)]["trades"]
            pnl_chrono = trades.sort_values("entry_ts")["net_pnl"].values if len(trades) else np.array([])
            max_dd, longest = max_dd_and_duration(pnl_chrono)
            rows.append({"block": b, "policy": p.upper(), "max_drawdown": max_dd,
                         "longest_drawdown_duration_trades": longest})
    df = pd.DataFrame(rows)
    for b in BLOCK_ORDER:
        r0_dd = df[(df["policy"] == "R0") & (df["block"] == b)]["max_drawdown"].iloc[0]
        mask = df["block"] == b
        df.loc[mask, "drawdown_change_vs_r0"] = r0_dd - df.loc[mask, "max_drawdown"]
    return df


def frozen_atr_edges() -> np.ndarray:
    sys_path_common = PROJECT_ROOT / "studies/rank_filter_oos_validation"
    import sys
    sys.path.insert(0, str(sys_path_common))
    from common import load_atlas, repair_f2_window, VAL_START, VAL_END
    df_atlas = load_atlas()
    val, _ = repair_f2_window(df_atlas, VAL_START, VAL_END)
    edges = np.percentile(val["atr"].dropna(), [0, 33.333, 66.667, 100])
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    return edges


def build_r0_pool(run_r0: dict, atr_edges: np.ndarray) -> pd.DataFrame:
    trades = run_r0["trades"].copy()
    trades["net_pnl_r0"] = trades["net_pnl"]
    canc = run_r0["pending_cancellations"].copy()
    pool_cols = ["decision_ts", "direction", "net_pnl_r0", "session", "atr_at_signal", "entry_ts"]
    trades_pool = trades[pool_cols].copy() if len(trades) else pd.DataFrame(columns=pool_cols)
    if len(canc):
        canc_pool = canc[["decision_ts", "direction"]].copy()
        canc_pool["net_pnl_r0"] = 0.0
        canc_pool["session"] = "UNKNOWN"
        canc_pool["atr_at_signal"] = np.nan
        canc_pool["entry_ts"] = canc["decision_ts"]
        pool = pd.concat([trades_pool, canc_pool], ignore_index=True)
    else:
        pool = trades_pool
    if len(pool) == 0:
        return pool
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


def build_matched_random(runs: dict, atr_edges: np.ndarray) -> pd.DataFrame:
    rows = []
    for b in BLOCK_ORDER:
        pool = build_r0_pool(runs[("r0", b)], atr_edges)
        if len(pool) == 0:
            continue
        for p in ("r2", "r4"):
            run_p = runs[(p, b)]
            skips = run_p["policy_skips"]
            if len(skips) == 0:
                rows.append({"block": b, "policy": p.upper(), "real_ev_lift": 0.0, "random_mean": 0.0,
                             "random_median": 0.0, "random_p95": 0.0, "empirical_p_value": 1.0, "n_seeds": N_SEEDS})
                continue
            skips = skips.copy()
            skips["month"] = pd.to_datetime(skips["decision_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
            pool_by_ts = pool.set_index("decision_ts")
            skips["session"] = skips["decision_ts"].map(pool_by_ts["session"]).fillna("UNKNOWN")
            skips["atr_bucket"] = skips["decision_ts"].map(pool_by_ts["atr_bucket"]).fillna("mid_vol")
            skip_stratum_key = skips[STRATA_COLS].astype(str).agg("|".join, axis=1)
            k_target_by_stratum = skip_stratum_key.value_counts().to_dict()

            skip_mask = matched_random_skip_matrix(pool, k_target_by_stratum, N_SEEDS, BASE_SEED + hash(p + b) % 10_000)
            baseline = pool["net_pnl_r0"].values.astype(np.float64)
            n = len(pool)
            kept_pnl = baseline[None, :] * (~skip_mask)
            random_lift = kept_pnl.sum(axis=1) / n - baseline.mean()

            r0_ev = float(baseline.mean())
            n_elig_p = eligible_counts(run_p)["eligible_signals"]
            r_ev = float(run_p["trades"]["net_pnl"].sum() / n_elig_p) if n_elig_p else 0.0
            real_lift = r_ev - r0_ev

            rows.append({
                "block": b, "policy": p.upper(), "real_ev_lift": real_lift,
                "random_mean": float(random_lift.mean()), "random_median": float(np.median(random_lift)),
                "random_p95": float(np.percentile(random_lift, 95)),
                "fraction_random_beating_real": float((random_lift > real_lift).mean()),
                "empirical_p_value": float((random_lift >= real_lift).mean()),
                "n_seeds": N_SEEDS,
            })
    return pd.DataFrame(rows)


def run():
    runs = {(p, b): load_run(p, b) for b in BLOCK_ORDER for p in POLICIES}

    period_metrics = build_period_metrics(runs)
    extremes = build_skipped_trade_extremes(runs)
    period_metrics = period_metrics.merge(extremes, on=["block", "policy"], how="left")
    period_metrics.to_parquet(AUDIT_DIR / "period_metrics.parquet", index=False)

    runner = build_runner_retention(runs)
    runner.to_parquet(AUDIT_DIR / "period_runner_retention.parquet", index=False)

    dd = build_drawdown(runs)
    dd.to_parquet(AUDIT_DIR / "period_drawdown_metrics.parquet", index=False)

    atr_edges = frozen_atr_edges()
    matched_random = build_matched_random(runs, atr_edges)
    matched_random.to_parquet(AUDIT_DIR / "period_matched_random.parquet", index=False)

    tail_dep = build_tail_dependence(runs)
    tail_dep.to_parquet(AUDIT_DIR / "tail_dependence.parquet", index=False)

    print(period_metrics[["block", "policy", "eligible_signals", "filled_trades", "ev_lift_vs_r0",
                           "net_pnl_change_vs_r0", "max_drawdown"]].to_string(index=False))
    print()
    print(matched_random.to_string(index=False))
    print()
    print(tail_dep.to_string(index=False))
    return runs, period_metrics, runner, dd, matched_random, tail_dep


if __name__ == "__main__":
    import os
    os.chdir(PROJECT_ROOT)
    run()

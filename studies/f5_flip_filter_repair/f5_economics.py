"""Phase 5-6: F5 exact economics per period + monthly, skipped-trade
economics, and paired bootstrap / permutation uncertainty.
"""
import json
import numpy as np
import pandas as pd
from common import OUT
from f5_episodes import build_episodes

EVAL_PERIODS = ["validation", "dev_test", "secondary_2025H2", "secondary_2026"]
RNG_SEED = 20260707


def period_metrics(ep: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    g = ep[mask]
    n_elig = len(g)
    n_skip = int(g["f5_skip"].sum())
    n_ret = n_elig - n_skip
    baseline = g["baseline_net_pnl"]
    f5 = g["f5_net_pnl"]
    retained = g.loc[~g["f5_skip"], "baseline_net_pnl"]

    def pf(x):
        w = x[x > 0].sum()
        l = -x[x < 0].sum()
        return float(w / l) if l > 0 else (float("inf") if w > 0 else 0.0)

    def max_dd(x):
        if len(x) == 0:
            return 0.0
        cum = np.cumsum(x.values)
        peak = np.maximum.accumulate(cum)
        return float((peak - cum).max())

    return {
        "period": label,
        "eligible_n": n_elig,
        "skipped_n": n_skip,
        "retained_n": n_ret,
        "retention": n_ret / n_elig if n_elig else float("nan"),
        "skip_rate": n_skip / n_elig if n_elig else float("nan"),
        "baseline_ev_per_eligible": float(baseline.mean()) if n_elig else float("nan"),
        "f5_ev_per_eligible": float(f5.mean()) if n_elig else float("nan"),
        "f5_ev_per_traded": float(retained.mean()) if n_ret else float("nan"),
        "paired_ev_lift": float((f5 - baseline).mean()) if n_elig else float("nan"),
        "total_pnl_baseline": float(baseline.sum()),
        "total_pnl_f5": float(f5.sum()),
        "total_pnl_change": float((f5 - baseline).sum()),
        "win_rate_baseline": float((baseline > 0).mean()) if n_elig else float("nan"),
        "win_rate_f5_traded": float((retained > 0).mean()) if n_ret else float("nan"),
        "profit_factor_baseline": pf(baseline),
        "profit_factor_f5_traded": pf(retained),
        "max_drawdown_baseline": max_dd(baseline),
        "max_drawdown_f5": max_dd(f5),
    }


def paired_bootstrap(deltas: np.ndarray, n_iter=10000, seed=RNG_SEED) -> dict:
    rng = np.random.default_rng(seed)
    n = len(deltas)
    if n == 0:
        return {"mean": float("nan"), "median": float("nan"), "ci_lo": float("nan"),
                "ci_hi": float("nan"), "p_gt_0": float("nan"), "p_ge_1": float("nan"), "p_ge_2": float("nan")}
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = deltas[idx].mean(axis=1)
    return {
        "mean": float(boot_means.mean()),
        "median": float(np.median(boot_means)),
        "ci_lo": float(np.percentile(boot_means, 2.5)),
        "ci_hi": float(np.percentile(boot_means, 97.5)),
        "p_gt_0": float((boot_means > 0).mean()),
        "p_ge_1": float((boot_means >= 1.0).mean()),
        "p_ge_2": float((boot_means >= 2.0).mean()),
    }


def exact_permutation(deltas_nonzero_signed: np.ndarray, n_perm=20000, seed=RNG_SEED) -> dict:
    """Sign-flip randomization test on the paired deltas (episodes with
    delta==0 contribute nothing to either tail and are kept for the observed
    stat but don't affect the null distribution's spread)."""
    rng = np.random.default_rng(seed + 1)
    n = len(deltas_nonzero_signed)
    if n == 0:
        return {"observed_mean": float("nan"), "p_value_two_sided": float("nan"), "n_permutations": 0}
    observed = deltas_nonzero_signed.mean()
    signs = rng.choice([-1, 1], size=(n_perm, n))
    perm_means = (signs * np.abs(deltas_nonzero_signed)).mean(axis=1)
    p_value = float((np.abs(perm_means) >= np.abs(observed)).mean())
    return {"observed_mean": float(observed), "p_value_two_sided": p_value, "n_permutations": n_perm}


def skipped_trade_economics(g: pd.DataFrame, label: str) -> dict:
    skipped = g[g["f5_skip"]]
    pnl = skipped["baseline_net_pnl"]
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    return {
        "period": label,
        "n_skipped": len(skipped),
        "mean_pnl": float(pnl.mean()) if len(pnl) else float("nan"),
        "median_pnl": float(pnl.median()) if len(pnl) else float("nan"),
        "total_pnl": float(pnl.sum()) if len(pnl) else 0.0,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else float("nan"),
        "profit_factor": float(winners.sum() / -losers.sum()) if len(losers) and losers.sum() != 0 else (float("inf") if len(winners) else 0.0),
        "n_winners_skipped": int((pnl > 0).sum()),
        "n_losers_skipped": int((pnl < 0).sum()),
        "largest_winner_skipped": float(pnl.max()) if len(pnl) else float("nan"),
        "largest_loss_skipped": float(pnl.min()) if len(pnl) else float("nan"),
        "bottom_decile_trade_count": int((skipped["runner_tier"] == "other").sum()),
        "top_decile_runner_count": int((skipped["runner_tier"] == "top10").sum()),
    }


def run():
    ep = build_episodes()

    # --- Period metrics ---
    period_rows = []
    for role in EVAL_PERIODS:
        period_rows.append(period_metrics(ep, ep["period_role"] == role, role))
    period_rows.append(period_metrics(ep, ep["period_role"].isin(EVAL_PERIODS), "combined_post_train"))
    period_rows.append(period_metrics(ep, ep["period_role"] == "train", "train_reference_only"))
    df_period = pd.DataFrame(period_rows)
    df_period.to_parquet(OUT / "f5_period_metrics.parquet", index=False)

    # --- Monthly metrics (every month, not just aggregates) ---
    monthly_rows = []
    for month, g in ep[ep["period_role"].isin(EVAL_PERIODS)].groupby("month"):
        m = period_metrics(ep, ep["month"] == month, month)
        monthly_rows.append(m)
    df_monthly = pd.DataFrame(monthly_rows).sort_values("period")
    df_monthly.to_parquet(OUT / "f5_monthly_metrics.parquet", index=False)

    # --- Skipped-trade economics ---
    skip_rows = [skipped_trade_economics(ep[ep["period_role"] == role], role) for role in EVAL_PERIODS]
    skip_rows.append(skipped_trade_economics(ep[ep["period_role"].isin(EVAL_PERIODS)], "combined_post_train"))
    df_skip = pd.DataFrame(skip_rows)
    df_skip.to_parquet(OUT / "f5_skipped_trade_economics.parquet", index=False)

    # --- Paired bootstrap + exact permutation ---
    boot_rows = []
    perm_rows = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        deltas = (ep.loc[mask, "f5_net_pnl"] - ep.loc[mask, "baseline_net_pnl"]).values
        b = paired_bootstrap(deltas, n_iter=10000)
        b["period"] = role
        b["n_episodes"] = len(deltas)
        boot_rows.append(b)
        p = exact_permutation(deltas, n_perm=20000)
        p["period"] = role
        perm_rows.append(p)

    df_boot = pd.DataFrame(boot_rows)[["period", "n_episodes", "mean", "median", "ci_lo", "ci_hi", "p_gt_0", "p_ge_1", "p_ge_2"]]
    df_boot.to_parquet(OUT / "f5_paired_bootstrap.parquet", index=False)

    df_perm = pd.DataFrame(perm_rows)
    uncertainty = df_boot.merge(df_perm, on="period")
    uncertainty.to_parquet(OUT / "f5_uncertainty_summary.parquet", index=False)

    print(df_period[["period", "eligible_n", "skipped_n", "retention", "paired_ev_lift", "total_pnl_change"]].to_string(index=False))
    print()
    print(df_boot.to_string(index=False))

    return ep, df_period, df_monthly, df_skip, df_boot


if __name__ == "__main__":
    import os
    from common import SRC
    os.chdir(SRC.parent.parent.parent)
    run()

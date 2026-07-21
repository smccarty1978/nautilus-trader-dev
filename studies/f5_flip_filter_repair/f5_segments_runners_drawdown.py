"""Phase 7-9: LONG/SHORT/RTH/ETH segment results, runner-tier preservation,
drawdown / equity-path audit.
"""
import numpy as np
import pandas as pd
from common import OUT
from f5_episodes import build_episodes
from f5_economics import EVAL_PERIODS, paired_bootstrap

SEGMENTS = {
    "LONG": lambda g: g["direction"] == 1,
    "SHORT": lambda g: g["direction"] == -1,
    "RTH": lambda g: g["session"] == "RTH",
    "ETH": lambda g: g["session"] == "ETH",
    "RTH_LONG": lambda g: (g["session"] == "RTH") & (g["direction"] == 1),
    "RTH_SHORT": lambda g: (g["session"] == "RTH") & (g["direction"] == -1),
    "ETH_LONG": lambda g: (g["session"] == "ETH") & (g["direction"] == 1),
    "ETH_SHORT": lambda g: (g["session"] == "ETH") & (g["direction"] == -1),
}


def run_segments(ep: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        base_mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        for seg_name, seg_fn in SEGMENTS.items():
            g = ep[base_mask & seg_fn(ep)]
            n_elig = len(g)
            n_skip = int(g["f5_skip"].sum())
            deltas = (g["f5_net_pnl"] - g["baseline_net_pnl"]).values
            boot = paired_bootstrap(deltas, n_iter=10000)
            rows.append({
                "period": role,
                "segment": seg_name,
                "eligible_n": n_elig,
                "skipped_n": n_skip,
                "retention": (n_elig - n_skip) / n_elig if n_elig else float("nan"),
                "baseline_ev_per_eligible": float(g["baseline_net_pnl"].mean()) if n_elig else float("nan"),
                "f5_ev_per_eligible": float(g["f5_net_pnl"].mean()) if n_elig else float("nan"),
                "paired_ev_lift": float(deltas.mean()) if n_elig else float("nan"),
                "total_pnl_benefit": float(deltas.sum()) if n_elig else 0.0,
                "bootstrap_ci_lo": boot["ci_lo"],
                "bootstrap_ci_hi": boot["ci_hi"],
            })
    return pd.DataFrame(rows)


def run_runner_retention(ep: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        base_mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        g = ep[base_mask]
        for tier in ["top10", "top5", "top1"]:
            t = g[g["runner_tier"] == tier]
            n = len(t)
            n_skip = int(t["f5_skip"].sum())
            baseline_pnl = float(t["baseline_net_pnl"].sum())
            retained_pnl = float(t["f5_net_pnl"].sum())
            skipped_runners = t[t["f5_skip"]]
            rows.append({
                "period": role,
                "tier": tier,
                "episode_count": n,
                "baseline_pnl": baseline_pnl,
                "f5_retained_pnl": retained_pnl,
                "runner_retention_ratio": retained_pnl / baseline_pnl if baseline_pnl != 0 else float("nan"),
                "runners_skipped": n_skip,
                "mean_skipped_runner_pnl": float(skipped_runners["baseline_net_pnl"].mean()) if len(skipped_runners) else float("nan"),
                "max_skipped_runner_pnl": float(skipped_runners["baseline_net_pnl"].max()) if len(skipped_runners) else float("nan"),
            })
    return pd.DataFrame(rows)


def run_drawdown(ep: pd.DataFrame):
    """Chronological (entry-order) equity curve; sign convention: positive
    cumulative PnL is favorable, drawdown = running-peak minus current
    cumulative PnL (a positive number = dollars below the most recent peak)."""
    rows = []
    path_rows = []
    for role in EVAL_PERIODS + ["combined_post_train"]:
        base_mask = ep["period_role"].isin(EVAL_PERIODS) if role == "combined_post_train" else (ep["period_role"] == role)
        g = ep[base_mask].sort_values("entry_ts").copy()
        if len(g) == 0:
            continue

        def dd_stats(pnl_col):
            cum = np.cumsum(g[pnl_col].values)
            peak = np.maximum.accumulate(cum)
            dd = peak - cum
            max_dd = float(dd.max())
            # longest duration in trade-count terms (proxy for "duration")
            in_dd = dd > 1e-9
            longest = 0
            cur = 0
            for flag in in_dd:
                cur = cur + 1 if flag else 0
                longest = max(longest, cur)
            return cum, dd, max_dd, longest

        cum_base, dd_base, max_dd_base, dur_base = dd_stats("baseline_net_pnl")
        cum_f5, dd_f5, max_dd_f5, dur_f5 = dd_stats("f5_net_pnl")

        rows.append({
            "period": role,
            "sign_convention": "positive cumulative PnL = favorable; drawdown = running_peak - current_cum (>=0, larger = worse)",
            "baseline_max_drawdown": max_dd_base,
            "f5_max_drawdown": max_dd_f5,
            "drawdown_improvement": max_dd_base - max_dd_f5,
            "baseline_longest_drawdown_duration_trades": dur_base,
            "f5_longest_drawdown_duration_trades": dur_f5,
        })

        g["cum_pnl_baseline"] = cum_base
        g["cum_pnl_f5"] = cum_f5
        g["drawdown_baseline"] = dd_base
        g["drawdown_f5"] = dd_f5
        g["period"] = role
        path_rows.append(g[["episode_id", "period", "entry_ts", "baseline_net_pnl", "f5_net_pnl",
                             "cum_pnl_baseline", "cum_pnl_f5", "drawdown_baseline", "drawdown_f5", "f5_skip"]])

    return pd.DataFrame(rows), pd.concat(path_rows, ignore_index=True) if path_rows else pd.DataFrame()


def identify_drawdown_causing_skips(ep: pd.DataFrame, dd_metrics: pd.DataFrame) -> pd.DataFrame:
    """For combined_post_train, list the skipped episodes with the largest
    negative baseline PnL during the baseline's max-drawdown episode range --
    these are the episodes most responsible for the drawdown difference."""
    g = ep[ep["period_role"].isin(EVAL_PERIODS)].sort_values("entry_ts").copy()
    cum = np.cumsum(g["baseline_net_pnl"].values)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    trough_idx = int(np.argmax(dd))
    peak_idx = int(np.argmax(cum[: trough_idx + 1])) if trough_idx > 0 else 0
    window = g.iloc[peak_idx: trough_idx + 1]
    skipped_in_window = window[window["f5_skip"]].sort_values("baseline_net_pnl")
    return skipped_in_window[["episode_id", "entry_ts", "baseline_net_pnl"]].head(20)


def run():
    ep = build_episodes()
    seg = run_segments(ep)
    seg.to_parquet(OUT / "f5_segment_results.parquet", index=False)

    runners = run_runner_retention(ep)
    runners.to_parquet(OUT / "f5_runner_retention.parquet", index=False)

    dd, path = run_drawdown(ep)
    dd.to_parquet(OUT / "f5_drawdown_metrics.parquet", index=False)
    path.to_parquet(OUT / "f5_equity_episode_path.parquet", index=False)

    causing = identify_drawdown_causing_skips(ep, dd)
    causing.to_parquet(OUT / "f5_drawdown_causing_skips.parquet", index=False)

    print(seg[seg["period"] == "combined_post_train"][["segment", "eligible_n", "paired_ev_lift", "total_pnl_benefit"]].to_string(index=False))
    print()
    print(runners[runners["period"] == "combined_post_train"].to_string(index=False))
    print()
    print(dd.to_string(index=False))
    return ep, seg, runners, dd


if __name__ == "__main__":
    import os
    from common import SRC
    os.chdir(SRC.parent.parent.parent)
    run()

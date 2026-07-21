"""Corrected monthly, pooled, segment, and drawdown metrics for R0/R1/R2/R4
over the Jun-Dec 2025 primary window. Pending-entry cancellations are
tracked as a first-class outcome distinct from filter-skips and from filled
trades. All aggregates are NaN-safe."""
import numpy as np
import pandas as pd
from common import OUT
from build_episodes import build

POLICIES = ["r0", "r1", "r2", "r4"]
MONTHS = [f"2025-{m:02d}" for m in range(6, 13)]


def pf(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    w = x[x > 0].sum()
    l = -x[x < 0].sum()
    return float(w / l) if l > 0 else (float(w) if w > 0 else 0.0)


def max_dd_and_duration(x_chronological: np.ndarray) -> tuple[float, int]:
    if len(x_chronological) == 0:
        return 0.0, 0
    cum = np.cumsum(x_chronological)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max())
    in_dd = dd > 1e-9
    longest = cur = 0
    for flag in in_dd:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    return max_dd, longest


def policy_metrics(g: pd.DataFrame, policy: str) -> dict:
    pnl_col = f"{policy}_net_pnl"
    status_col = f"{policy}_status"
    skip_col = g[f"{policy}_skip"] if f"{policy}_skip" in g.columns else pd.Series(False, index=g.index)

    n_elig = len(g)
    n_skip = int(skip_col.sum())
    n_canceled = int((g[status_col] == "pending_entry_canceled").sum()) if n_elig else 0
    n_filled = int((g[status_col] == "filled").sum()) if n_elig else 0

    net_pnl = g[pnl_col].values if n_elig else np.array([])
    filled_pnl = g.loc[g[status_col] == "filled", "baseline_pnl"].values if n_elig else np.array([])

    g_chrono = g.sort_values("confirmation_ts") if "confirmation_ts" in g.columns else g
    pnl_chrono = g_chrono[pnl_col].values if n_elig else np.array([])
    max_dd, longest_dd = max_dd_and_duration(pnl_chrono)

    return {
        "policy": policy.upper(),
        "eligible_episodes": n_elig,
        "skipped_episodes": n_skip,
        "pending_entries_canceled": n_canceled,
        "filled_trades": n_filled,
        "retention": (n_filled / n_elig) if n_elig else 0.0,
        "ev_per_eligible": float(net_pnl.mean()) if n_elig else 0.0,
        "ev_per_traded": float(filled_pnl.mean()) if n_filled else 0.0,
        "total_net_pnl": float(net_pnl.sum()) if n_elig else 0.0,
        "win_rate": float((filled_pnl > 0).mean()) if n_filled else 0.0,
        "profit_factor": pf(filled_pnl),
        "max_drawdown": max_dd,
        "longest_drawdown_duration_trades": longest_dd,
    }


def skipped_trade_econ(g: pd.DataFrame, policy: str) -> dict:
    skip_col = g[f"{policy}_skip"]
    # skipped-trade PnL under R0 = what the baseline (E0/delayed, filled or
    # canceled) would have realized had the filter not intervened.
    skipped = g.loc[skip_col & (g["trade_status"] == "filled"), "baseline_pnl"]
    return {
        "policy": policy.upper(),
        "n_skipped": int(skip_col.sum()),
        "n_skipped_that_would_have_filled": len(skipped),
        "mean_pnl": float(skipped.mean()) if len(skipped) else 0.0,
        "median_pnl": float(skipped.median()) if len(skipped) else 0.0,
        "total_pnl": float(skipped.sum()) if len(skipped) else 0.0,
        "winners_skipped": int((skipped > 0).sum()),
        "losers_skipped": int((skipped < 0).sum()),
        "largest_winner_skipped": float(skipped.max()) if len(skipped) else 0.0,
        "largest_loss_skipped": float(skipped.min()) if len(skipped) else 0.0,
    }


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


def run():
    ep = build()

    monthly_rows = []
    for m in MONTHS:
        g = ep[ep["month"] == m]
        for p in POLICIES:
            monthly_rows.append({"month": m, **policy_metrics(g, p)})
    df_monthly = pd.DataFrame(monthly_rows)
    assert df_monthly.isna().sum().sum() == 0, "NaN found in corrected_monthly_results"
    df_monthly.to_parquet(OUT / "corrected_monthly_results.parquet", index=False)

    pooled_rows = [policy_metrics(ep, p) for p in POLICIES]
    df_pooled = pd.DataFrame(pooled_rows)
    r0_ev = df_pooled.loc[df_pooled["policy"] == "R0", "ev_per_eligible"].iloc[0]
    df_pooled["paired_ev_lift"] = df_pooled["ev_per_eligible"] - r0_ev
    assert df_pooled.isna().sum().sum() == 0, "NaN found in pooled_metrics"
    df_pooled.to_parquet(OUT / "pooled_metrics.parquet", index=False)

    skip_rows = [skipped_trade_econ(ep, p) for p in ("r1", "r2", "r4")]
    pd.DataFrame(skip_rows).to_parquet(OUT / "skipped_trade_economics.parquet", index=False)

    seg_rows = []
    for seg_name, seg_fn in SEGMENTS.items():
        g = ep[seg_fn(ep)]
        for p in POLICIES:
            seg_rows.append({"segment": seg_name, "n_in_segment": len(g), **policy_metrics(g, p)})
    df_seg = pd.DataFrame(seg_rows)
    r0_by_seg = df_seg[df_seg["policy"] == "R0"].set_index("segment")["ev_per_eligible"]
    df_seg["paired_ev_lift"] = df_seg.apply(lambda r: r["ev_per_eligible"] - r0_by_seg.get(r["segment"], 0.0), axis=1)
    assert df_seg.isna().sum().sum() == 0, "NaN found in corrected_segment_results"
    df_seg.to_parquet(OUT / "corrected_segment_results.parquet", index=False)

    dd_rows = []
    g_chrono = ep.sort_values("confirmation_ts")
    for p in POLICIES:
        max_dd, longest = max_dd_and_duration(g_chrono[f"{p}_net_pnl"].values)
        dd_rows.append({
            "policy": p.upper(),
            "sign_convention": "positive cumulative PnL = favorable; drawdown = running_peak - current_cum (>=0)",
            "max_drawdown": max_dd,
            "longest_drawdown_duration_trades": longest,
        })
    df_dd = pd.DataFrame(dd_rows)
    r0_dd = df_dd.loc[df_dd["policy"] == "R0", "max_drawdown"].iloc[0]
    df_dd["drawdown_change_vs_r0"] = r0_dd - df_dd["max_drawdown"]
    assert df_dd.isna().sum().sum() == 0, "NaN found in corrected_drawdown_metrics"
    df_dd.to_parquet(OUT / "corrected_drawdown_metrics.parquet", index=False)

    print(df_pooled[["policy", "eligible_episodes", "skipped_episodes", "pending_entries_canceled",
                      "filled_trades", "retention", "ev_per_eligible", "paired_ev_lift", "max_drawdown"]].to_string(index=False))
    print()
    print(df_dd.to_string(index=False))
    return ep, df_monthly, df_pooled, df_seg, df_dd


if __name__ == "__main__":
    import os
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()

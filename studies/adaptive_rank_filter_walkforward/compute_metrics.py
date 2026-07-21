"""Core economics: monthly_results.parquet, pooled_results.parquet,
final_reserved_results.parquet, drawdown_metrics.parquet, runner_retention.parquet,
tail_dependence.parquet.

All computed from the single episode_status.parquet master table (built by
build_episode_status.py) so every metric shares the identical episode
population and status resolution across policies.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c

WORK_DIR = c.OUT.parent / "_work"

POOLED_BLOCKS = {
    "2025_JanDec": ("2025-01", "2025-12"),
    "2026_JanFeb_development": ("2026-01", "2026-02"),
    "2026_MarApr_final_reserved": ("2026-03", "2026-04"),
    "ALL_Jan2025_Apr2026": ("2025-01", "2026-04"),
}


def basic_metrics(sub: pd.DataFrame) -> dict:
    n_eligible = len(sub)
    n_skipped = int(sub["skipped"].sum())
    n_canceled = int(sub["pending_canceled"].sum())
    n_filled = int(sub["filled"].sum())
    filled_pnl = sub.loc[sub["filled"], "net_pnl"]

    net_pnl_total = float(filled_pnl.sum()) if n_filled else 0.0
    ev_per_eligible = net_pnl_total / n_eligible if n_eligible else 0.0
    ev_per_filled = float(filled_pnl.mean()) if n_filled else 0.0
    win_rate = float((filled_pnl > 0).mean()) if n_filled else np.nan
    gains = filled_pnl[filled_pnl > 0].sum()
    losses = filled_pnl[filled_pnl < 0].sum()
    profit_factor = float(gains / abs(losses)) if losses < 0 else (np.inf if gains > 0 else np.nan)

    return {
        "eligible_signals": n_eligible,
        "pending_entry_cancellations": n_canceled,
        "filled_trades": n_filled,
        "skip_rate": n_skipped / n_eligible if n_eligible else np.nan,
        "ev_per_eligible_signal": ev_per_eligible,
        "ev_per_filled_trade": ev_per_filled,
        "net_pnl": net_pnl_total,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }


def drawdown_stats(sub: pd.DataFrame) -> dict:
    filled = sub[sub["filled"]].sort_values("confirmation_ts")
    if len(filled) == 0:
        return {"max_drawdown": 0.0, "longest_drawdown_duration_days": 0.0}
    equity = filled["net_pnl"].cumsum().values
    ts = pd.to_datetime(filled["confirmation_ts"].values, unit="ns", utc=True)

    running_max = np.maximum.accumulate(equity)
    drawdown = equity - running_max
    max_dd = float(drawdown.min())

    # longest duration (in days) spent below a prior equity peak
    peak_idx = 0
    longest_days = 0.0
    cur_peak_val = equity[0]
    cur_peak_ts = ts[0]
    for i in range(len(equity)):
        if equity[i] >= cur_peak_val:
            cur_peak_val = equity[i]
            cur_peak_ts = ts[i]
        else:
            dur = (ts[i] - cur_peak_ts).total_seconds() / 86400.0
            longest_days = max(longest_days, dur)
    return {"max_drawdown": max_dd, "longest_drawdown_duration_days": longest_days}


def month_in_block(month: str, block: tuple[str, str]) -> bool:
    return block[0] <= month <= block[1]


def main():
    status = pd.read_parquet(WORK_DIR / "episode_status.parquet")
    policies = status["policy"].unique()

    # ---- monthly ----
    monthly_rows = []
    for policy in policies:
        pol = status[status["policy"] == policy]
        for month, sub in pol.groupby("deploy_month"):
            row = {"policy": policy, "policy_family": sub["policy_family"].iloc[0],
                   "window_name": sub["window_name"].iloc[0], "deploy_month": month}
            row.update(basic_metrics(sub))
            row.update(drawdown_stats(sub))
            monthly_rows.append(row)
    monthly = pd.DataFrame(monthly_rows).sort_values(["policy", "deploy_month"])
    monthly.to_parquet(c.OUT / "monthly_results.parquet", index=False)

    # ---- pooled ----
    pooled_rows = []
    for policy in policies:
        pol = status[status["policy"] == policy]
        for block_name, block in POOLED_BLOCKS.items():
            sub = pol[pol["deploy_month"].apply(lambda m: month_in_block(m, block))]
            row = {"policy": policy, "policy_family": sub["policy_family"].iloc[0] if len(sub) else policy,
                   "window_name": sub["window_name"].iloc[0] if len(sub) else None, "block": block_name}
            row.update(basic_metrics(sub))
            row.update(drawdown_stats(sub))
            pooled_rows.append(row)
    pooled = pd.DataFrame(pooled_rows)
    pooled.to_parquet(c.OUT / "pooled_results.parquet", index=False)

    # ---- final reserved (its own dedicated file, same content as the pooled subset) ----
    final_reserved = pooled[pooled["block"] == "2026_MarApr_final_reserved"].drop(columns=["block"])
    final_reserved.to_parquet(c.OUT / "final_reserved_results.parquet", index=False)

    # ---- drawdown_metrics.parquet (standalone, block x policy) ----
    dd_rows = []
    for policy in policies:
        pol = status[status["policy"] == policy]
        for block_name, block in POOLED_BLOCKS.items():
            sub = pol[pol["deploy_month"].apply(lambda m: month_in_block(m, block))]
            row = {"policy": policy, "block": block_name}
            row.update(drawdown_stats(sub))
            dd_rows.append(row)
    drawdown_metrics = pd.DataFrame(dd_rows)
    drawdown_metrics.to_parquet(c.OUT / "drawdown_metrics.parquet", index=False)

    print("monthly_results:", monthly.shape)
    print("pooled_results:", pooled.shape)
    print("final_reserved_results:", final_reserved.shape)
    print("drawdown_metrics:", drawdown_metrics.shape)
    print("\nFinal reserved (Mar-Apr 2026) EV per eligible signal by policy:")
    print(final_reserved[["policy", "eligible_signals", "filled_trades", "skip_rate",
                           "ev_per_eligible_signal", "net_pnl"]].sort_values("ev_per_eligible_signal", ascending=False)
          .to_string(index=False))


if __name__ == "__main__":
    main()

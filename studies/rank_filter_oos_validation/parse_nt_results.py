"""Phase 2: parse genuine NautilusTrader BacktestEngine outputs (real fills,
real event-driven trades -- NOT a pandas post-hoc replay) into the required
nt_* deliverables. R0/R2/R4, both periods (2025H2, 2026, never pooled).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from common import OUT, PROJECT_ROOT

NT_RUNS = PROJECT_ROOT / "studies/rank_filter_oos_validation/nt_runs"
POLICIES = ["r0", "r2", "r4"]
PERIODS = ["2025H2", "2026"]


def load_run(policy: str, period: str) -> dict:
    d = NT_RUNS / f"{policy}_{period}"
    out = {"policy": policy, "period": period}
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


def build_trade_results() -> pd.DataFrame:
    rows = []
    for policy in POLICIES:
        for period in PERIODS:
            run = load_run(policy, period)
            trades = run["trades"].copy()
            if len(trades) == 0:
                continue
            trades["policy"] = policy.upper()
            trades["period"] = period
            trades["month"] = pd.to_datetime(trades["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
            rows.append(trades)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def eligible_counts(run: dict) -> dict:
    diag = run["meta"].get("diag", {})
    n_filled = len(run["trades"])
    n_canceled = len(run["pending_cancellations"])
    n_skipped = len(run["policy_skips"])
    n_eligible = n_filled + n_canceled + n_skipped
    # cross-check against diag counters when available
    diag_eligible = diag.get("confirmations_passed_hhll_mom")
    return {
        "eligible_confirmed_signals": n_eligible,
        "pending_entries_canceled": n_canceled,
        "filter_skipped": n_skipped,
        "filled_trades": n_filled,
        "diag_confirmations_passed_hhll_mom": diag_eligible,
        "consistent_with_diag": (diag_eligible is None) or (diag_eligible == n_eligible),
    }


def policy_metrics(run: dict) -> dict:
    trades = run["trades"]
    counts = eligible_counts(run)
    n_elig = counts["eligible_confirmed_signals"]
    n_filled = counts["filled_trades"]

    net_pnl = trades["net_pnl"].values if len(trades) else np.array([])
    trades_chrono = trades.sort_values("entry_ts") if len(trades) else trades
    pnl_chrono = trades_chrono["net_pnl"].values if len(trades_chrono) else np.array([])
    max_dd, longest_dd = max_dd_and_duration(pnl_chrono)

    return {
        "policy": run["policy"].upper(),
        "period": run["period"],
        **counts,
        "retention": (n_filled / n_elig) if n_elig else 0.0,
        "net_pnl_total": float(net_pnl.sum()) if n_filled else 0.0,
        "ev_per_eligible_signal": float(net_pnl.sum() / n_elig) if n_elig else 0.0,
        "ev_per_filled_trade": float(net_pnl.mean()) if n_filled else 0.0,
        "win_rate": float((net_pnl > 0).mean()) if n_filled else 0.0,
        "profit_factor": pf(net_pnl),
        "max_drawdown": max_dd,
        "longest_drawdown_duration_trades": longest_dd,
    }


def run():
    runs = {(p, per): load_run(p, per) for p in POLICIES for per in PERIODS}

    trade_results = build_trade_results()
    trade_results.to_parquet(OUT / "nt_trade_results.parquet", index=False)

    pooled_rows = [policy_metrics(runs[(p, per)]) for p in POLICIES for per in PERIODS]
    df_pooled = pd.DataFrame(pooled_rows)
    for per in PERIODS:
        r0_ev = df_pooled[(df_pooled["policy"] == "R0") & (df_pooled["period"] == per)]["ev_per_eligible_signal"]
        r0_ev = float(r0_ev.iloc[0]) if len(r0_ev) else 0.0
        mask = df_pooled["period"] == per
        df_pooled.loc[mask, "paired_ev_lift"] = df_pooled.loc[mask, "ev_per_eligible_signal"] - r0_ev
    df_pooled.to_parquet(OUT / "nt_pooled_metrics.parquet", index=False)

    print(df_pooled[["policy", "period", "eligible_confirmed_signals", "pending_entries_canceled",
                      "filter_skipped", "filled_trades", "retention", "ev_per_eligible_signal",
                      "paired_ev_lift", "max_drawdown"]].to_string(index=False))
    return runs, trade_results, df_pooled


if __name__ == "__main__":
    import os
    os.chdir(PROJECT_ROOT)
    run()

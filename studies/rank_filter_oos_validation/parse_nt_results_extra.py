"""Phase 2: NT monthly/segment/runner/drawdown/parity outputs, building on
parse_nt_results.load_run / policy_metrics."""
import numpy as np
import pandas as pd
from common import OUT, PROJECT_ROOT
from parse_nt_results import load_run, policy_metrics, max_dd_and_duration, pf, POLICIES, PERIODS, eligible_counts


def month_filter(run: dict, month: str) -> dict:
    out = dict(run)
    for key in ("trades", "policy_skips", "pending_cancellations"):
        df = run[key]
        if len(df):
            ts_col = "entry_ts" if key == "trades" else "decision_ts"
            mo = pd.to_datetime(df[ts_col], unit="ns", utc=True).dt.strftime("%Y-%m")
            out[key] = df[mo == month]
        else:
            out[key] = df
    out["meta"] = {**run.get("meta", {}), "diag": {}}  # diag not month-scoped; use direct counts
    return out


def seg_filter(run: dict, seg_mask_fn) -> dict:
    out = dict(run)
    trades = run["trades"]
    out["trades"] = trades[seg_mask_fn(trades, "direction", "session")] if len(trades) else trades
    skips = run["policy_skips"]
    out["policy_skips"] = skips[seg_mask_fn(skips, "direction", None)] if len(skips) else skips
    canc = run["pending_cancellations"]
    out["pending_cancellations"] = canc[seg_mask_fn(canc, "direction", None)] if len(canc) else canc
    out["meta"] = {**run.get("meta", {}), "diag": {}}
    return out


SEGMENTS = {
    "LONG": lambda df, dcol, scol: df[dcol] == 1,
    "SHORT": lambda df, dcol, scol: df[dcol] == -1,
    "RTH": lambda df, dcol, scol: (df[scol] == "RTH") if scol and scol in df.columns else pd.Series(True, index=df.index),
    "ETH": lambda df, dcol, scol: (df[scol] == "ETH") if scol and scol in df.columns else pd.Series(True, index=df.index),
    "RTH_LONG": lambda df, dcol, scol: ((df[scol] == "RTH") if scol and scol in df.columns else True) & (df[dcol] == 1),
    "RTH_SHORT": lambda df, dcol, scol: ((df[scol] == "RTH") if scol and scol in df.columns else True) & (df[dcol] == -1),
    "ETH_LONG": lambda df, dcol, scol: ((df[scol] == "ETH") if scol and scol in df.columns else True) & (df[dcol] == 1),
    "ETH_SHORT": lambda df, dcol, scol: ((df[scol] == "ETH") if scol and scol in df.columns else True) & (df[dcol] == -1),
}


def run_monthly(runs: dict) -> pd.DataFrame:
    rows = []
    for (policy, period), run in runs.items():
        trades = run["trades"]
        if len(trades) == 0:
            continue
        months = sorted(pd.to_datetime(trades["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m").unique())
        for m in months:
            mrun = month_filter(run, m)
            rows.append({"month": m, **policy_metrics(mrun)})
    df = pd.DataFrame(rows)
    df = df.fillna(0)
    return df


def run_segments(runs: dict) -> pd.DataFrame:
    rows = []
    for (policy, period), run in runs.items():
        for seg_name, seg_fn in SEGMENTS.items():
            def mask_fn(df, dcol, scol, _fn=seg_fn):
                if len(df) == 0:
                    return pd.Series([], dtype=bool)
                return _fn(df, dcol, "session")
            srun = seg_filter(run, mask_fn)
            m = policy_metrics(srun)
            m["segment"] = seg_name
            rows.append(m)
    df = pd.DataFrame(rows)
    for per in PERIODS:
        r0_by_seg = df[(df["policy"] == "R0") & (df["period"] == per)].set_index("segment")["ev_per_eligible_signal"]
        mask = df["period"] == per
        df.loc[mask, "paired_ev_lift"] = df.loc[mask].apply(
            lambda r: r["ev_per_eligible_signal"] - r0_by_seg.get(r["segment"], 0.0), axis=1)
    df = df.fillna(0)
    return df


def run_runner_retention(runs: dict) -> pd.DataFrame:
    """Runner tiers from each period's own R0 filled-trade PnL distribution
    (retrospective OOS methodology, consistent with the corrected research
    tables' primary rule)."""
    rows = []
    for period in PERIODS:
        r0 = runs[("r0", period)]["trades"]
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
            for policy in ("r2", "r4"):
                trades_p = runs[(policy, period)]["trades"]
                if len(trades_p):
                    p_keys = set(zip(trades_p["decision_ts"].values, trades_p["direction"].values))
                else:
                    p_keys = set()
                retained_keys = tier_keys & p_keys
                skipped_keys = tier_keys - p_keys
                retained_pnl = float(tier_r0[tier_r0.apply(lambda r: (r["decision_ts"], r["direction"]) in retained_keys, axis=1)]["net_pnl"].sum()) if len(tier_r0) else 0.0
                skipped_pnl_rows = tier_r0[tier_r0.apply(lambda r: (r["decision_ts"], r["direction"]) in skipped_keys, axis=1)]["net_pnl"] if len(tier_r0) else pd.Series([], dtype=float)
                rows.append({
                    "period": period, "tier": tier, "policy": policy.upper(),
                    "episode_count": len(tier_r0),
                    "baseline_pnl": baseline_pnl,
                    "retained_pnl": retained_pnl,
                    "runner_pnl_retention": (retained_pnl / baseline_pnl) if baseline_pnl != 0 else 1.0,
                    "runner_count_retained": len(retained_keys),
                    "runner_count_skipped": len(skipped_keys),
                    "largest_skipped_runner": float(skipped_pnl_rows.max()) if len(skipped_pnl_rows) else 0.0,
                })
    return pd.DataFrame(rows)


def run_drawdown(runs: dict) -> pd.DataFrame:
    rows = []
    for period in PERIODS:
        for policy in POLICIES:
            trades = runs[(policy, period)]["trades"]
            pnl_chrono = trades.sort_values("entry_ts")["net_pnl"].values if len(trades) else np.array([])
            max_dd, longest = max_dd_and_duration(pnl_chrono)
            rows.append({
                "policy": policy.upper(), "period": period,
                "sign_convention": "positive cumulative PnL = favorable; drawdown = running_peak - current_cum (>=0)",
                "max_drawdown": max_dd, "longest_drawdown_duration_trades": longest,
            })
    df = pd.DataFrame(rows)
    for per in PERIODS:
        r0_dd = df[(df["policy"] == "R0") & (df["period"] == per)]["max_drawdown"].iloc[0]
        mask = df["period"] == per
        df.loc[mask, "drawdown_change_vs_r0"] = r0_dd - df.loc[mask, "max_drawdown"]
    return df


def run_parity_check(runs: dict) -> pd.DataFrame:
    """Verify retained R2/R4 trades use IDENTICAL entry/exit ts/price to R0."""
    rows = []
    for period in PERIODS:
        r0 = runs[("r0", period)]["trades"]
        if len(r0) == 0:
            continue
        r0_idx = r0.set_index("decision_ts")
        for policy in ("r2", "r4"):
            trades_p = runs[(policy, period)]["trades"]
            n_checked = 0
            n_entry_ts_match = 0
            n_entry_px_match = 0
            n_exit_ts_match = 0
            n_exit_px_match = 0
            n_no_r0_counterpart = 0
            for _, row in trades_p.iterrows():
                if row["decision_ts"] not in r0_idx.index:
                    n_no_r0_counterpart += 1
                    continue
                r0_row = r0_idx.loc[row["decision_ts"]]
                if isinstance(r0_row, pd.DataFrame):
                    r0_row = r0_row.iloc[0]
                n_checked += 1
                n_entry_ts_match += int(r0_row["entry_ts"] == row["entry_ts"])
                n_entry_px_match += int(abs(r0_row["fill_price"] - row["fill_price"]) < 1e-6)
                n_exit_ts_match += int(r0_row["exit_ts"] == row["exit_ts"])
                n_exit_px_match += int(abs(r0_row["exit_price"] - row["exit_price"]) < 1e-6)
            rows.append({
                "policy": policy.upper(), "period": period,
                "n_retained_trades_checked": n_checked,
                "n_with_no_r0_counterpart_found": n_no_r0_counterpart,
                "entry_ts_match_rate": (n_entry_ts_match / n_checked) if n_checked else 1.0,
                "entry_price_match_rate": (n_entry_px_match / n_checked) if n_checked else 1.0,
                "exit_ts_match_rate": (n_exit_ts_match / n_checked) if n_checked else 1.0,
                "exit_price_match_rate": (n_exit_px_match / n_checked) if n_checked else 1.0,
                "verdict": "PASS" if (n_checked > 0 and n_entry_ts_match == n_checked and
                                        n_entry_px_match == n_checked and n_exit_ts_match == n_checked and
                                        n_exit_px_match == n_checked and n_no_r0_counterpart == 0) else
                           ("PASS" if n_checked == 0 else "FAIL"),
            })
    return pd.DataFrame(rows)


def run():
    runs = {(p, per): load_run(p, per) for p in POLICIES for per in PERIODS}

    monthly = run_monthly(runs)
    monthly.to_parquet(OUT / "nt_monthly_results.parquet", index=False)

    segments = run_segments(runs)
    segments.to_parquet(OUT / "nt_segment_results.parquet", index=False)

    runner = run_runner_retention(runs)
    runner.to_parquet(OUT / "nt_runner_retention.parquet", index=False)

    dd = run_drawdown(runs)
    dd.to_parquet(OUT / "nt_drawdown_metrics.parquet", index=False)

    parity = run_parity_check(runs)
    parity.to_parquet(OUT / "nt_parity_audit.parquet", index=False)

    print("MONTHLY:\n", monthly[["month", "policy", "period", "eligible_confirmed_signals", "ev_per_eligible_signal"]].to_string(index=False))
    print("\nRUNNER RETENTION:\n", runner.to_string(index=False))
    print("\nDRAWDOWN:\n", dd.to_string(index=False))
    print("\nPARITY:\n", parity.to_string(index=False))
    return monthly, segments, runner, dd, parity


if __name__ == "__main__":
    import os
    os.chdir(PROJECT_ROOT)
    run()

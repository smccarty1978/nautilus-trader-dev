"""Phase 7 driver for F2_CONFIRMED: compute required metrics per
policy/population, separately for 2025 dev_test (Mar-Dec) and 2026
reserved_eval (Jan-Apr) -- never pooled, per the study spec.

E0 baseline is read directly from the Phase 1 raw collection
(_work/nt_raw/<year>/trades.parquet) -- no new NT run needed, since
E0 IS that baseline (hold-to-opposite-flip, no stop policy).
"""
from __future__ import annotations
import json, sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.w0_features import SPLIT_BOUNDARIES
from studies._shared_exit_mgmt.phase7_metrics import (
    load_trades, filter_window, compute_policy_metrics,
)

STUDY_ROOT = Path(__file__).parent
RESULTS_ROOT = STUDY_ROOT / "results"
NT_RAW = STUDY_ROOT / "_work" / "nt_raw"
PHASE6_RAW = STUDY_ROOT / "_work" / "phase6_raw"

# Reduced scope (user-confirmed 2026-07-12): S2/S3/S5 deferred for
# time; only these 9 policies were actually executed in Phase 6.
REDUCED_POLICIES = [
    "E1", "S1_checkpoint", "S1_mfe", "S4_checkpoint", "S4_mfe",
    "S6_checkpoint", "S6_mfe", "S7_checkpoint", "S7_mfe",
]
POLICIES = ["E0"] + REDUCED_POLICIES
STOP_POLICIES = {n for n in REDUCED_POLICIES if n.startswith("S")}
PERIODS = {
    "dev_test_2025": SPLIT_BOUNDARIES["dev_test"],
    "reserved_eval_2026": SPLIT_BOUNDARIES["reserved_eval"],
}
YEARS_FOR_PERIOD = {"dev_test_2025": [2025], "reserved_eval_2026": [2026]}


def load_policy_trades_for_years(policy: str, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        if policy == "E0":
            p = NT_RAW / str(year) / "trades.parquet"
        else:
            p = PHASE6_RAW / policy / str(year) / "trades.parquet"
        if p.exists():
            frames.append(load_trades(p))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_diag_entries_scheduled(policy: str, years: list[int]) -> int:
    total = 0
    for year in years:
        if policy == "E0":
            p = NT_RAW / str(year) / "diag.json"
        else:
            p = PHASE6_RAW / policy / str(year) / "diag.json"
        if p.exists():
            d = json.loads(p.read_text())
            total += d.get("entries_scheduled", 0)
    return total


def main():
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    monthly_rows = []
    segment_rows = []

    for period_name, (start, end) in PERIODS.items():
        years = YEARS_FOR_PERIOD[period_name]

        e0_all = load_policy_trades_for_years("E0", years)
        e0_window = filter_window(e0_all, start, end)
        e0_eligible = load_diag_entries_scheduled("E0", years)
        e0_metrics = compute_policy_metrics(e0_window, e0_window, False,
                                                n_eligible=e0_eligible)
        e0_metrics.pop("giveback_reduction_vs_e0_atr", None)
        e0_avg_giveback = e0_metrics.get("avg_giveback_atr", float("nan"))

        row = {"policy": "E0", "period": period_name}
        row.update(e0_metrics)
        row["giveback_reduction_vs_e0_atr"] = 0.0
        all_rows.append(row)
        print(f"[{period_name}] E0: n_filled={e0_metrics.get('n_filled')}, "
                 f"net_pnl={e0_metrics.get('net_pnl_total'):.0f}, "
                 f"win_rate={e0_metrics.get('win_rate', float('nan')):.3f}",
                 flush=True)

        if len(e0_window):
            e0_window["month"] = pd.to_datetime(
                e0_window["entry_ts"], unit="ns", utc=True).dt.to_period("M")
            for month, g in e0_window.groupby("month", observed=True):
                monthly_rows.append({
                    "policy": "E0", "period": period_name,
                    "month": str(month), "n_trades": len(g),
                    "net_pnl": float(g["net_pnl"].sum()),
                    "win_rate": float((g["net_pnl"] > 0).mean()),
                })
            for (session, direction), g in e0_window.groupby(
                ["session", "direction"], observed=True):
                segment_rows.append({
                    "policy": "E0", "period": period_name,
                    "session": session, "direction": int(direction),
                    "n_trades": len(g), "net_pnl": float(g["net_pnl"].sum()),
                    "win_rate": float((g["net_pnl"] > 0).mean()),
                })

        for name in REDUCED_POLICIES:
            is_stop = name in STOP_POLICIES
            p_all = load_policy_trades_for_years(name, years)
            p_window = filter_window(p_all, start, end)
            p_eligible = load_diag_entries_scheduled(name, years)
            m = compute_policy_metrics(p_window, e0_window, is_stop,
                                           n_eligible=p_eligible)
            m["giveback_reduction_vs_e0_atr"] = (
                e0_avg_giveback - m.get("avg_giveback_atr", float("nan"))
                if "avg_giveback_atr" in m else float("nan"))
            row = {"policy": name, "period": period_name}
            row.update(m)
            all_rows.append(row)
            print(f"[{period_name}] {name}: n_filled={m.get('n_filled')}, "
                     f"net_pnl={m.get('net_pnl_total', float('nan')):.0f}, "
                     f"win_rate={m.get('win_rate', float('nan')):.3f}, "
                     f"giveback_reduction={m.get('giveback_reduction_vs_e0_atr', float('nan')):.3f}",
                     flush=True)

            if len(p_window):
                p_window["month"] = pd.to_datetime(
                    p_window["entry_ts"], unit="ns", utc=True).dt.to_period("M")
                for month, g in p_window.groupby("month", observed=True):
                    monthly_rows.append({
                        "policy": name, "period": period_name,
                        "month": str(month), "n_trades": len(g),
                        "net_pnl": float(g["net_pnl"].sum()),
                        "win_rate": float((g["net_pnl"] > 0).mean()),
                    })
                for (session, direction), g in p_window.groupby(
                    ["session", "direction"], observed=True):
                    segment_rows.append({
                        "policy": name, "period": period_name,
                        "session": session, "direction": int(direction),
                        "n_trades": len(g),
                        "net_pnl": float(g["net_pnl"].sum()),
                        "win_rate": float((g["net_pnl"] > 0).mean()),
                    })

    results_df = pd.DataFrame(all_rows)
    results_df.to_parquet(RESULTS_ROOT / "nt_policy_results.parquet", index=False)

    monthly_df = pd.DataFrame(monthly_rows)
    monthly_df.to_parquet(RESULTS_ROOT / "nt_monthly_results.parquet", index=False)

    segment_df = pd.DataFrame(segment_rows)
    segment_df.to_parquet(RESULTS_ROOT / "nt_segment_results.parquet", index=False)

    runner_cols = ["policy", "period", "runner_retention_top10",
                      "runner_retention_top5", "runner_retention_top1"]
    results_df[runner_cols].to_parquet(
        RESULTS_ROOT / "nt_runner_retention.parquet", index=False)

    dd_cols = ["policy", "period", "max_drawdown",
                  "longest_drawdown_duration_days"]
    results_df[dd_cols].to_parquet(
        RESULTS_ROOT / "nt_drawdown_metrics.parquet", index=False)

    stop_cols = ["policy", "period", "n_stop_policy_exits",
                    "avg_remaining_mfe_sacrificed_atr",
                    "n_true_terminal_stops", "n_false_recovery_stops",
                    "avg_loss_avoided"]
    stop_cols = [c for c in stop_cols if c in results_df.columns]
    results_df[stop_cols].to_parquet(
        RESULTS_ROOT / "nt_stop_quality.parquet", index=False)

    print(f"\nWrote {len(results_df)} policy-period rows to "
             f"{RESULTS_ROOT / 'nt_policy_results.parquet'}")
    print("Wrote nt_monthly_results.parquet, nt_segment_results.parquet, "
             "nt_runner_retention.parquet, nt_drawdown_metrics.parquet, "
             "nt_stop_quality.parquet")


if __name__ == "__main__":
    main()

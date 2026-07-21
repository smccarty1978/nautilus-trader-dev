"""Build indicators.parquet companion files next to each R2/R4 NT run's
trades.parquet, so utils/visualizer_hc.py (run_visualizer_hc.py) can show
the frozen risk score + filter decision (skip / exempt-keep / low-risk-keep)
alongside real price action for every signal in that run's window.

Schema written (matches load_trade_knn's expected long format exactly):
    timestamp: int64 ns since epoch (decision_ts of each confirmed signal)
    indicator: "hc" (frozen ridge_log_fail_prob risk score, 0-1) |
               "hc_state" (0=SKIPPED, 1=EXEMPT-KEEP(high-risk but exempted),
                            3=LOW-RISK-KEEP(below threshold))
    value: float

Score is attached to each NT decision_ts via nearest-timestamp match against
the research atlas (bidirectional, generous tolerance) -- this is a DISPLAY
join only (not used in any trading decision), so the stricter backward-only/
20s tolerance used inside the live backtest strategy does not apply here.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "studies/rank_filter_oos_validation"))
from common import load_atlas, repair_f2_window, load_frozen_config, PROJECT_ROOT as PR

NT_RUNS = PROJECT_ROOT / "studies/rank_filter_oos_validation/nt_runs"

PERIODS = {
    "2025H2": ("2025-06-01", "2025-12-31"),
    "2026": ("2026-01-01", "2026-04-29"),
}
EXEMPTION_COL = {"r2": "seq_5r_center_migration_slope_atr", "r4": "seq_5r_asym_duration"}
EXEMPTION_THRESHOLD = {"r2": 0.005, "r4": 1.5}
DISPLAY_MATCH_TOLERANCE_NS = 60_000_000_000  # 60s, display-only


def nearest_match(query_ts: np.ndarray, ref_ts: np.ndarray, ref_vals: dict[str, np.ndarray], tol_ns: int) -> dict:
    order = np.argsort(ref_ts)
    ref_ts_sorted = ref_ts[order]
    ref_vals_sorted = {k: v[order] for k, v in ref_vals.items()}

    i = np.searchsorted(ref_ts_sorted, query_ts)
    i_lo = np.clip(i - 1, 0, len(ref_ts_sorted) - 1)
    i_hi = np.clip(i, 0, len(ref_ts_sorted) - 1)
    gap_lo = np.abs(ref_ts_sorted[i_lo] - query_ts)
    gap_hi = np.abs(ref_ts_sorted[i_hi] - query_ts)
    use_hi = gap_hi < gap_lo
    idx = np.where(use_hi, i_hi, i_lo)
    gap = np.where(use_hi, gap_hi, gap_lo)

    out = {k: v[idx] for k, v in ref_vals_sorted.items()}
    out["_matched"] = gap <= tol_ns
    return out


def build_for_run(policy: str, period_key: str, thr: float):
    start, end = PERIODS[period_key]
    df_atlas = load_atlas()
    signals, _ = repair_f2_window(df_atlas, start, end)
    ref_ts = signals["confirmation_ts"].values.astype(np.int64)
    ref_score = signals["ridge_log_fail_prob"].values.astype(np.float64)
    ref_exempt_feat = signals[EXEMPTION_COL[policy]].values.astype(np.float64)

    run_dir = NT_RUNS / f"{policy}_{period_key}"
    rows = []
    for fname, outcome in (("trades.parquet", "filled"), ("policy_skips.parquet", "skipped"),
                            ("pending_cancellations.parquet", "canceled")):
        p = run_dir / fname
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if len(df) == 0:
            continue
        query_ts = df["decision_ts"].values.astype(np.int64)
        matched = nearest_match(query_ts, ref_ts, {"score": ref_score, "exempt_feat": ref_exempt_feat},
                                 DISPLAY_MATCH_TOLERANCE_NS)
        for i, ts in enumerate(query_ts):
            if not matched["_matched"][i]:
                continue
            score = float(matched["score"][i])
            exempt_feat = float(matched["exempt_feat"][i])
            is_high_risk = score >= thr
            is_exempt = exempt_feat > EXEMPTION_THRESHOLD[policy]
            if outcome == "skipped":
                code = 0  # SKIPPED
            elif is_high_risk and is_exempt:
                code = 1  # EXEMPT-KEEP: high risk but the exemption saved it
            else:
                code = 3  # LOW-RISK-KEEP (or filled/canceled without needing the exemption)
            rows.append({"timestamp": int(ts), "indicator": "hc", "value": score})
            rows.append({"timestamp": int(ts), "indicator": "hc_state", "value": float(code)})

    if not rows:
        print(f"  [{policy}/{period_key}] no matched signals, skipping indicators.parquet")
        return
    out = pd.DataFrame(rows).sort_values("timestamp")
    out.to_parquet(run_dir / "indicators.parquet", index=False)
    print(f"  [{policy}/{period_key}] wrote {len(out)} indicator rows ({len(out)//2} signals) -> {run_dir/'indicators.parquet'}")


def run():
    frozen = load_frozen_config()
    thr = frozen["score_thresholds_test"]["R2"]
    for policy in ("r2", "r4"):
        for period_key in PERIODS:
            build_for_run(policy, period_key, thr)


if __name__ == "__main__":
    import os
    os.chdir(PROJECT_ROOT)
    run()

"""Builds all 25 trigger variants on 2025 (cutoffs derived) and 2026
(cutoffs applied frozen), one-entry-per-regime schedules, and economics.

Percentile cutoffs are computed on the 2025 raw-score distribution ONLY
and applied unchanged to 2026 (SPEC.md finding 2: raw vs. calibrated score
is immaterial to percentile-threshold trigger families, since calibration
is a monotonic transform).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PURE_FLIP = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
WORK, RESULTS = HERE / "_work", HERE / "results"
for d in (WORK, RESULTS, HERE / "audit"):
    d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE))
from trigger_logic import build_trigger_flags, trigger_column_names  # noqa: E402

SCORE_COL = "score_F3_volume_delta_plus_price_levels__gbt_raw"
TARGET = "bearish_regime_flip_within_300s"
CUTOFF_QUANTILES = {"top20": 0.80, "top15": 0.85, "top10": 0.90, "top5": 0.95, "top2.5": 0.975}

NEEDED_COLS = [
    "regime_start_ns", "observation_time", "confirm_flip_ns", SCORE_COL, TARGET,
    "net_pnl", "exit_reason", "entry_ts", "exit_ts", "atr_at_entry",
    "hit_pre_alignment_stop", "hit_timeout", "hit_post_alignment_stop", "hit_opposing_flip",
    "opposing_flip_exit_positive",
]


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def max_closed_trade_dd(pnl_by_exit_order: pd.Series) -> float:
    eq = np.concatenate(([0.0], pnl_by_exit_order.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(eq) - eq))


def build_schedule(df: pd.DataFrame, trig_col: str) -> pd.DataFrame:
    d = df[df[trig_col]].sort_values(["regime_start_ns", "observation_time"], kind="stable")
    return d.groupby("regime_start_ns", as_index=False, sort=False).first()


def economics(schedule: pd.DataFrame) -> dict:
    n = len(schedule)
    if n == 0:
        return {"trades": 0, "net_pnl": np.nan, "per_trade": np.nan, "gross_profit": np.nan,
                "gross_loss": np.nan, "profit_factor": np.nan, "win_rate": np.nan,
                "avg_winner": np.nan, "avg_loser": np.nan, "max_closed_trade_dd": np.nan,
                "mar_like_score": np.nan, "pre_alignment_stop_rate": np.nan, "timeout_rate": np.nan,
                "post_alignment_stop_rate": np.nan, "opposing_flip_rate": np.nan,
                "opposing_flip_winner_rate": np.nan, "opposing_flip_pnl": np.nan,
                "actual_flip_within_300s_rate": np.nan, "median_hold_s": np.nan}
    pnl = schedule["net_pnl"].astype(float)
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    ordered = schedule.sort_values("exit_ts")["net_pnl"].astype(float)
    dd = max_closed_trade_dd(ordered)
    net = float(pnl.sum())
    hold_s = (schedule["exit_ts"] - schedule["entry_ts"]) / 1e9
    return {
        "trades": n, "net_pnl": net, "per_trade": float(pnl.mean()),
        "gross_profit": float(w.sum()), "gross_loss": float(l.sum()),
        "profit_factor": pf(pnl), "win_rate": float((pnl > 0).mean()),
        "avg_winner": float(w.mean()) if len(w) else np.nan,
        "avg_loser": float(l.mean()) if len(l) else np.nan,
        "max_closed_trade_dd": dd,
        "mar_like_score": (net / dd) if dd > 0 else np.nan,
        "pre_alignment_stop_rate": float(schedule["hit_pre_alignment_stop"].mean()),
        "timeout_rate": float(schedule["hit_timeout"].mean()),
        "post_alignment_stop_rate": float(schedule["hit_post_alignment_stop"].mean()),
        "opposing_flip_rate": float(schedule["hit_opposing_flip"].mean()),
        "opposing_flip_winner_rate": float(schedule["opposing_flip_exit_positive"].mean()),
        "opposing_flip_pnl": float(schedule.loc[schedule["hit_opposing_flip"], "net_pnl"].sum()),
        "actual_flip_within_300s_rate": float(schedule[TARGET].mean()),
        "median_hold_s": float(hold_s.median()),
    }


def load_split(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path, columns=NEEDED_COLS)


def main() -> None:
    t0 = time.time()
    dev_df = load_split(PURE_FLIP / "_work" / "scored_dev_2025.parquet")
    test_df = load_split(PURE_FLIP / "_work" / "scored_test_2026.parquet")

    cutoffs = {name: float(dev_df[SCORE_COL].quantile(q)) for name, q in CUTOFF_QUANTILES.items()}
    (WORK / "cutoffs.json").write_text(json.dumps(cutoffs, indent=2), encoding="utf-8")
    print("Frozen 2025 cutoffs:", cutoffs)

    dev_tagged = build_trigger_flags(dev_df, SCORE_COL, cutoffs)
    test_tagged = build_trigger_flags(test_df, SCORE_COL, cutoffs)
    dev_tagged.to_parquet(WORK / "tagged_2025.parquet", index=False, compression="zstd")
    test_tagged.to_parquet(WORK / "tagged_2026.parquet", index=False, compression="zstd")

    rows = []
    trig_cols = trigger_column_names()
    for split_name, tagged in (("2025", dev_tagged), ("2026", test_tagged)):
        for trig_col in trig_cols:
            schedule = build_schedule(tagged, trig_col)
            schedule.to_parquet(WORK / f"schedule_{trig_col}_{split_name}.parquet",
                               index=False, compression="zstd")
            e = economics(schedule)
            rows.append({"trigger": trig_col, "split": split_name,
                        "cutoff_score": cutoffs.get(trig_col.split("_")[-1]) if "_" in trig_col else np.nan,
                        "mean_score_at_entry": float(schedule[SCORE_COL].mean()) if len(schedule) else np.nan,
                        "median_score_at_entry": float(schedule[SCORE_COL].median()) if len(schedule) else np.nan,
                        **e})

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "trigger_grid_results.csv", index=False)
    print(out[out.split == "2025"].sort_values("mar_like_score", ascending=False).head(10)[
        ["trigger", "trades", "net_pnl", "per_trade", "profit_factor", "mar_like_score"]
    ].to_string(index=False))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

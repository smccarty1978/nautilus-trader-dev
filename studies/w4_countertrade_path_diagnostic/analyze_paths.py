"""Aggregate the collected path checkpoints into the diagnostic deliverables.

Pure aggregation of collect_paths.py output. No thresholds are optimized and
no policy is simulated. W4-based flags are summarized only where score
staleness <= 30s (5s checkpoint cadence upstream; larger gaps mean the score
stream had stopped, e.g. regime age > 1800s).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path(__file__).resolve().parent
OUT = STUDY / "results"
W4_STALE_MAX_S = 30.0
GROUP_ORDER = [
    "stop_before_aligned_flip", "stop_after_aligned_flip",
    "opposite_flip_exit_winner", "opposite_flip_exit_loser",
]


def frac(series: pd.Series) -> float:
    s = series.dropna()
    return float(s.mean()) if len(s) else np.nan


def outcome_group_summary(diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    splits = [
        ("all", []),
        ("direction", ["entry_direction"]),
        ("session", ["session"]),
    ]
    for split_name, extra in splits:
        keys = ["year", "outcome_group"] + extra
        for key, g in diag.groupby(keys):
            key = key if isinstance(key, tuple) else (key,)
            w4_ok = g["w4_last_staleness_s"] <= W4_STALE_MAX_S
            row = dict(zip(keys, key))
            row.update({
                "split": split_name,
                "n": len(g),
                "mean_net_usd": g["net_pnl_usd"].mean(),
                "median_net_usd": g["net_pnl_usd"].median(),
                "total_net_usd": g["net_pnl_usd"].sum(),
                "median_hold_s": g["hold_s"].median(),
                "median_peak_mfe_atr": g["peak_mfe_atr"].median(),
                "mean_peak_mfe_atr": g["peak_mfe_atr"].mean(),
                "pct_reached_025_atr": frac(g["reached_025_atr"]),
                "pct_reached_05_atr": frac(g["reached_05_atr"]),
                "pct_reached_075_atr": frac(g["reached_075_atr"]),
                "pct_reached_10_atr": frac(g["reached_10_atr"]),
                "median_t_peak_s": g["t_peak_s"].median(),
                "median_t_peak_to_exit_s": g["t_peak_to_exit_s"].median(),
                "median_capture_ratio": g["capture_ratio"].median(),
                "median_giveback_from_peak_usd": g["giveback_from_peak_usd"].median(),
                "pct_old_regime_new_extreme": frac(g["old_regime_new_extreme_ever"]),
                "median_t_new_extreme_s": g["t_old_regime_new_extreme_s"].median(),
                "pct_w4_last_above_threshold": frac(
                    g.loc[w4_ok, "w4_last_above_threshold"]),
                "median_w4_change_entry_to_last": g.loc[
                    w4_ok, "w4_change_entry_to_last"].median(),
                "n_w4_fresh": int(w4_ok.sum()),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def early_window_summary(cps: pd.DataFrame, diag: pd.DataFrame) -> pd.DataFrame:
    group_n = diag.groupby(["year", "outcome_group"]).size().rename("n_group")
    rows = []
    early = cps[cps["checkpoint"].isin(["t+60s", "t+120s"])]
    splits = [("all", []), ("direction", ["entry_direction"])]
    for split_name, extra in splits:
        keys = ["year", "checkpoint", "outcome_group"] + extra
        for key, g in early.groupby(keys):
            key = key if isinstance(key, tuple) else (key,)
            named = dict(zip(keys, key))
            fresh = g["w4_staleness_s"] <= W4_STALE_MAX_S
            row = {
                **named, "split": split_name,
                "n_alive": len(g),
                "n_group_total": int(group_n.get(
                    (named["year"], named["outcome_group"]), 0)),
                "mean_pnl_atr": g["pnl_atr"].mean(),
                "median_pnl_atr": g["pnl_atr"].median(),
                "mean_mfe_atr": g["mfe_atr"].mean(),
                "median_mfe_atr": g["mfe_atr"].median(),
                "mean_mae_atr": g["mae_atr"].mean(),
                "median_mae_atr": g["mae_atr"].median(),
                "median_w4_change_from_entry": g.loc[
                    fresh & (g["w4_regime"] == "faded"),
                    "w4_change_from_entry"].median(),
                "pct_flipped": frac(g["aligned_flip_occurred"]),
                "pct_old_regime_new_extreme": frac(g["old_regime_new_extreme"]),
                "pct_w4_above_threshold": frac(g.loc[fresh, "w4_above_threshold"]),
                "n_w4_fresh": int(fresh.sum()),
            }
            rows.append(row)
    out = pd.DataFrame(rows)
    out["pct_alive"] = out["n_alive"] / out["n_group_total"]
    return out


def post_flip_exit_diagnostic(diag: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "year", "regime_start_ns", "outcome_group", "entry_direction", "session",
        "net_pnl_usd", "gross_pnl_usd", "hold_s", "t_flip_s",
        "pnl_at_flip_usd", "pnl_at_flip_atr",
        "post_flip_peak_mfe_atr", "t_flip_to_post_peak_s",
        "post_flip_giveback_atr", "post_flip_giveback_usd",
        "post_flip_max_adverse_atr", "post_flip_revisit_entry",
        "post_flip_adverse_beyond_025_atr", "post_flip_adverse_beyond_05_atr",
        "peak_mfe_atr", "capture_ratio",
        "w4_warn_ts", "t_flip_to_warn_s", "pnl_at_warn_usd", "warned_before_exit",
    ]
    return diag.loc[diag["reached_flip"], cols].reset_index(drop=True)


def main() -> None:
    cps = pd.read_parquet(OUT / "path_checkpoints.parquet")
    diag = pd.read_parquet(OUT / "trade_diagnostics.parquet")

    ogs = outcome_group_summary(diag)
    ews = early_window_summary(cps, diag)
    pfd = post_flip_exit_diagnostic(diag)

    ogs.to_parquet(OUT / "outcome_group_summary.parquet", index=False)
    ews.to_parquet(OUT / "early_window_summary.parquet", index=False)
    pfd.to_parquet(OUT / "post_flip_exit_diagnostic.parquet", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    print("=== outcome_group_summary (split=all) ===")
    print(ogs[ogs["split"] == "all"].round(3).to_string(index=False))
    print("\n=== early_window_summary (split=all) ===")
    print(ews[ews["split"] == "all"].round(3).to_string(index=False))
    print("\n=== post-flip diagnostic group medians ===")
    med = pfd.groupby(["year", "outcome_group"]).agg(
        n=("net_pnl_usd", "size"),
        med_pnl_at_flip=("pnl_at_flip_usd", "median"),
        med_post_peak_atr=("post_flip_peak_mfe_atr", "median"),
        med_t_post_peak=("t_flip_to_post_peak_s", "median"),
        med_giveback_usd=("post_flip_giveback_usd", "median"),
        med_capture=("capture_ratio", "median"),
        pct_warned=("warned_before_exit", "mean"),
        med_t_warn=("t_flip_to_warn_s", "median"),
        med_pnl_at_warn=("pnl_at_warn_usd", "median"),
    ).round(3)
    print(med.to_string())


if __name__ == "__main__":
    main()

"""Layer 2 -- one-entry-per-regime deployable candidate policy.

For each (feature_set, model, retention band, split): for every bullish
regime, select the first eligible RTH checkpoint (earliest observation_time)
whose entry_quality_score clears that split's frozen cutoff (cutoffs are
computed on 2025 dev and applied unchanged to 2026; train uses its own
cutoffs, diagnostic only). Comparable to the current W4 candidate basis
(Baseline A).

Consumes train_and_evaluate.py's scored parquets and frozen cutoffs. Trains
nothing new.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"

BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]
FEATURE_SETS = ["F0_existing_only", "F1_volume_delta_only",
                "F2_price_levels_only", "F3_volume_delta_plus_price_levels"]
MODELS = ["logreg", "gbt"]


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def max_closed_trade_dd(pnl_by_exit_order: pd.Series) -> float:
    eq = np.concatenate(([0.0], pnl_by_exit_order.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(eq) - eq))


def build_schedule(df: pd.DataFrame, score_col: str, cutoff: float) -> pd.DataFrame:
    d = df.sort_values(["regime_start_ns", "observation_time"], kind="stable")
    elig = d[d[score_col] >= cutoff]
    schedule = elig.groupby("regime_start_ns", as_index=False, sort=False).first()
    return schedule


def economics(schedule: pd.DataFrame) -> dict:
    n = len(schedule)
    if n == 0:
        return {"trades": 0, "net_pnl": np.nan, "per_trade": np.nan, "gross_profit": np.nan,
                "gross_loss": np.nan, "profit_factor": np.nan, "win_rate": np.nan,
                "avg_winner": np.nan, "avg_loser": np.nan, "max_closed_trade_dd": np.nan,
                "pre_alignment_stop_rate": np.nan, "timeout_rate": np.nan,
                "post_alignment_stop_rate": np.nan, "opposing_flip_rate": np.nan,
                "opposing_flip_pnl": np.nan}
    pnl = schedule["net_pnl"].astype(float)
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    ordered = schedule.sort_values("exit_ts")["net_pnl"].astype(float)
    return {
        "trades": n, "net_pnl": float(pnl.sum()), "per_trade": float(pnl.mean()),
        "gross_profit": float(w.sum()), "gross_loss": float(l.sum()),
        "profit_factor": pf(pnl), "win_rate": float((pnl > 0).mean()),
        "avg_winner": float(w.mean()) if len(w) else np.nan,
        "avg_loser": float(l.mean()) if len(l) else np.nan,
        "max_closed_trade_dd": max_closed_trade_dd(ordered),
        "pre_alignment_stop_rate": float(schedule["hit_pre_alignment_stop"].mean()),
        "timeout_rate": float(schedule["hit_timeout"].mean()),
        "post_alignment_stop_rate": float(schedule["hit_post_alignment_stop"].mean()),
        "opposing_flip_rate": float(schedule["hit_opposing_flip"].mean()),
        "opposing_flip_pnl": float(schedule.loc[schedule["hit_opposing_flip"], "net_pnl"].sum()),
    }


def monthly(schedule: pd.DataFrame) -> pd.DataFrame:
    if len(schedule) == 0:
        return pd.DataFrame(columns=["month", "trades", "net_pnl"])
    g = schedule.copy()
    g["month"] = pd.to_datetime(g["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
    return g.groupby("month").agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum")).reset_index()


def exit_attribution(schedule: pd.DataFrame) -> pd.DataFrame:
    if len(schedule) == 0:
        return pd.DataFrame(columns=["exit_reason", "count", "pct", "net_pnl"])
    counts = schedule["exit_reason"].value_counts()
    pnl = schedule.groupby("exit_reason")["net_pnl"].sum()
    return pd.DataFrame({
        "exit_reason": counts.index, "count": counts.values,
        "pct": (counts / len(schedule) * 100).values,
        "net_pnl": [float(pnl.get(r, 0.0)) for r in counts.index],
    })


def main() -> None:
    cutoffs = json.loads((WORK / "retention_cutoffs.json").read_text(encoding="utf-8"))
    splits = {
        "train": WORK / "scored_train.parquet",
        "2025": WORK / "scored_dev_2025.parquet",
        "2026": WORK / "scored_test_2026.parquet",
    }
    econ_rows, monthly_rows, exit_rows = [], [], []

    for fs_name in FEATURE_SETS:
        for model_name in MODELS:
            key = f"{fs_name}__{model_name}"
            score_col = f"score_{key}"
            for split_name, path in splits.items():
                df = pd.read_parquet(path, columns=[
                    "regime_start_ns", "observation_time", score_col, "net_pnl", "exit_ts",
                    "entry_ts", "exit_reason", "hit_pre_alignment_stop", "hit_timeout",
                    "hit_post_alignment_stop", "hit_opposing_flip"])
                for band in BANDS:
                    cutoff = cutoffs[key][str(band)] if str(band) in cutoffs[key] else cutoffs[key][band]
                    schedule = build_schedule(df, score_col, cutoff)
                    out = WORK / f"schedule_{key}_{split_name}_{band}.parquet"
                    schedule.to_parquet(out, index=False, compression="zstd")
                    e = economics(schedule)
                    econ_rows.append({"feature_set": fs_name, "model": model_name,
                                      "split": split_name, "retention_band": band,
                                      "layer": "layer2_one_per_regime", **e})
                    m = monthly(schedule)
                    for _, r in m.iterrows():
                        monthly_rows.append({"feature_set": fs_name, "model": model_name,
                                             "split": split_name, "retention_band": band, **r.to_dict()})
                    ea = exit_attribution(schedule)
                    for _, r in ea.iterrows():
                        exit_rows.append({"feature_set": fs_name, "model": model_name,
                                          "split": split_name, "retention_band": band, **r.to_dict()})

    pd.DataFrame(econ_rows).to_csv(RESULTS / "economic_results.csv", index=False)
    pd.DataFrame(monthly_rows).to_csv(RESULTS / "monthly_results.csv", index=False)
    pd.DataFrame(exit_rows).to_csv(RESULTS / "exit_reason_attribution.csv", index=False)

    print(pd.DataFrame(econ_rows)[(pd.DataFrame(econ_rows)["split"] == "2025")
                                  & (pd.DataFrame(econ_rows)["retention_band"] == 0.35)
                                  ].to_string(index=False))


if __name__ == "__main__":
    main()

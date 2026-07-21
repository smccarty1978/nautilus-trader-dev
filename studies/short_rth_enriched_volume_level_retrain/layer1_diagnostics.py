"""Layer 1 -- row-level diagnostics on all eligible rows, per (feature_set,
model, retention band, split). Descriptive only, NOT deployable PnL (rows
overlap heavily within a regime by construction -- see Layer 2 for the
deployable one-entry-per-regime policy).

Consumes train_and_evaluate.py's scored parquets and frozen cutoffs.
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
CLASSES = ["opposing_flip_winner", "opposing_flip_loser", "pre_alignment_stop",
           "confirmation_timeout", "post_alignment_stop"]


def main() -> None:
    cutoffs = json.loads((WORK / "retention_cutoffs.json").read_text(encoding="utf-8"))
    splits = {
        "train": WORK / "scored_train.parquet",
        "2025": WORK / "scored_dev_2025.parquet",
        "2026": WORK / "scored_test_2026.parquet",
    }
    rows = []
    for fs_name in FEATURE_SETS:
        for model_name in MODELS:
            key = f"{fs_name}__{model_name}"
            score_col = f"score_{key}"
            for split_name, path in splits.items():
                df = pd.read_parquet(path, columns=[score_col, "outcome_class", "net_pnl"])
                y = df["outcome_class"].to_numpy()
                for band in BANDS:
                    cutoff = cutoffs[key][str(band)] if str(band) in cutoffs[key] else cutoffs[key][band]
                    retained = (df[score_col] >= cutoff).to_numpy()
                    n_retained = int(retained.sum())
                    row = {
                        "feature_set": fs_name, "model": model_name, "split": split_name,
                        "retention_band": band, "cutoff_score": cutoff,
                        "n_total": len(df), "n_retained": n_retained,
                        "retention_rate": float(retained.mean()),
                        "net_pnl_retained_sum_DESCRIPTIVE_ONLY": float(df.loc[retained, "net_pnl"].sum()),
                        "net_pnl_all_sum_DESCRIPTIVE_ONLY": float(df["net_pnl"].sum()),
                    }
                    for cls in CLASSES:
                        row[f"rate_all_{cls}"] = float((y == cls).mean())
                        row[f"rate_retained_{cls}"] = (
                            float((y[retained] == cls).mean()) if n_retained else np.nan)
                    rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "retention_band_results.csv", index=False)
    print(out[(out.split == "2025") & (out.retention_band == 0.35)][
        ["feature_set", "model", "n_retained", "retention_rate",
         "rate_retained_opposing_flip_winner", "rate_retained_pre_alignment_stop"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()

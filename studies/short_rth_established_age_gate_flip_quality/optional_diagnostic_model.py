"""Optional bounded diagnostic model -- is the 240s surface more learnable
than the 120s surface? NOT a production candidate; reuses
`[[short_rth_enriched_retrain_overfits_2025]]`'s fit_logistic/fit_gbt
verbatim rather than reimplementing. Train 2021-2024, inspect 2025, sealed
2026, on the first-eligible-per-regime surface, combined (F3) feature set
only (population is far too small per-gate/per-year to justify a full
4-feature-set x 2-model grid the way the enriched retrain did).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
WORK, RESULTS = HERE / "_work", HERE / "results"
if str(ENRICHED_RETRAIN) not in sys.path:
    sys.path.insert(0, str(ENRICHED_RETRAIN))
from train_and_evaluate import fit_gbt, fit_logistic, score_logistic  # noqa: E402

GATES = ["gate_a_120s", "bridge_180s", "gate_b_240s"]
TARGETS = ["bearish_flip_within_300s_and_followthrough_1A", "adverse_move_1p25A_before_bearish_flip"]
TRAIN_YEARS, DEV_YEAR, TEST_YEAR = (2021, 2022, 2023, 2024), 2025, 2026


def main() -> None:
    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))
    cols = feature_sets["F3_volume_delta_plus_price_levels"]

    rows = []
    for gate in GATES:
        train_df = pd.concat(
            [pd.read_parquet(WORK / f"first_eligible_{gate}_{y}.parquet", columns=cols + TARGETS)
             for y in TRAIN_YEARS], ignore_index=True)
        dev_df = pd.read_parquet(WORK / f"first_eligible_{gate}_{DEV_YEAR}.parquet", columns=cols + TARGETS)
        test_df = pd.read_parquet(WORK / f"first_eligible_{gate}_{TEST_YEAR}.parquet", columns=cols + TARGETS)

        for target in TARGETS:
            train_y = train_df[target].astype(int).to_numpy()
            dev_y = dev_df[target].astype(int).to_numpy()
            test_y = test_df[target].astype(int).to_numpy()
            train_X, dev_X, test_X = train_df[cols], dev_df[cols], test_df[cols]

            if train_y.sum() < 10 or train_y.sum() == len(train_y):
                continue

            lr_model, imp, sc = fit_logistic(train_X, train_y)
            lr_dev = score_logistic(lr_model, imp, sc, dev_X)[:, 1]
            lr_test = score_logistic(lr_model, imp, sc, test_X)[:, 1]

            gbt_model = fit_gbt(train_X, train_y)
            gbt_dev = gbt_model.predict_proba(dev_X)[:, 1]
            gbt_test = gbt_model.predict_proba(test_X)[:, 1]

            for model_name, dev_s, test_s in (("logreg", lr_dev, lr_test), ("gbt", gbt_dev, gbt_test)):
                dev_auc = (roc_auc_score(dev_y, dev_s) if 0 < dev_y.sum() < len(dev_y) else np.nan)
                test_auc = (roc_auc_score(test_y, test_s) if 0 < test_y.sum() < len(test_y) else np.nan)
                rows.append({
                    "gate": gate, "target": target, "model": model_name,
                    "train_rows": len(train_df), "train_positive_rate": float(train_y.mean()),
                    "dev_rows": len(dev_df), "dev_positive_rate": float(dev_y.mean()),
                    "dev_auc": dev_auc,
                    "test_rows": len(test_df), "test_positive_rate": float(test_y.mean()),
                    "test_auc": test_auc,
                })

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "optional_model_diagnostics.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()

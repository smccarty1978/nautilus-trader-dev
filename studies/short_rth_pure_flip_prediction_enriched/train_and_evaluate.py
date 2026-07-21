"""Phase 1 -- train, calibrate, and evaluate the pure flip-prediction models
across four feature sets (F0 existing / F1 volume-delta / F2 price-level /
F3 combined) and two model families (regularized logistic regression,
capped-depth HistGradientBoostingClassifier), on the single binary target
`bearish_regime_flip_within_300s`.

Train: 2021-2024. Calibrate (isotonic + sigmoid) on 2025 only, using
`sklearn.frozen.FrozenEstimator` so the base model is never refit. Evaluate
raw AND calibrated scores on sealed 2026. No 2026 involvement in any fit,
calibration, or selection step.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             log_loss, roc_auc_score)
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
WORK, RESULTS = HERE / "_work", HERE / "results"


def _load_module(name: str, path: Path):
    """This file and the enriched-retrain study's are both literally named
    `train_and_evaluate.py` -- a plain `from train_and_evaluate import ...`
    would collide via sys.modules bare-name caching. Load under a distinct
    internal name instead (same pattern already used and audited in
    `[[short_rth_pure_flip_prediction_enriched]]`'s own phase0_prepare_data.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_enriched_retrain_train_eval = _load_module(
    "_enriched_retrain_train_eval", ENRICHED_RETRAIN / "train_and_evaluate.py")
fit_gbt = _enriched_retrain_train_eval.fit_gbt
fit_logistic = _enriched_retrain_train_eval.fit_logistic

TARGET = "bearish_regime_flip_within_300s"
RANDOM_STATE = 42


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def make_logreg_pipeline(model, imputer, scaler) -> Pipeline:
    """Wrap the 3 separately-fitted objects `fit_logistic` returns into a
    single already-fitted sklearn Pipeline -- required so
    CalibratedClassifierCV(FrozenEstimator(...)) can treat it as one
    estimator without ever re-fitting the imputer/scaler/model."""
    return Pipeline([("imputer", imputer), ("scaler", scaler), ("model", model)])


def metrics_row(y: np.ndarray, proba: np.ndarray) -> dict:
    if len(np.unique(y)) < 2:
        return {"auc": np.nan, "average_precision": np.nan,
                "brier": np.nan, "logloss": np.nan}
    return {
        "auc": float(roc_auc_score(y, proba)),
        "average_precision": float(average_precision_score(y, proba)),
        "brier": float(brier_score_loss(y, proba)),
        "logloss": float(log_loss(y, proba, labels=[0, 1])),
    }


def calibration_deciles(score: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"score": score, "y": y})
    df["decile"] = pd.qcut(df["score"], 10, labels=False, duplicates="drop")
    return df.groupby("decile").agg(
        n=("y", "size"), mean_predicted=("score", "mean"), actual_rate=("y", "mean")
    ).reset_index()


def main() -> None:
    t0 = time.time()
    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))

    train_df = pd.read_parquet(WORK / "train_2021_2024_prepared.parquet")
    dev_df = pd.read_parquet(WORK / "prepared_2025.parquet")
    test_df = pd.read_parquet(WORK / "prepared_2026.parquet")
    train_y = train_df[TARGET].astype(int).to_numpy()
    dev_y = dev_df[TARGET].astype(int).to_numpy()
    test_y = test_df[TARGET].astype(int).to_numpy()

    print(f"train={len(train_df):,} dev={len(dev_df):,} test={len(test_df):,}")
    print(f"positive rate: train={train_y.mean():.4f} dev={dev_y.mean():.4f} test={test_y.mean():.4f}")

    diag_rows, calib_frames, importance_rows = [], [], []

    for fs_name, cols in feature_sets.items():
        train_X, dev_X, test_X = train_df[cols], dev_df[cols], test_df[cols]

        for model_name in ("logreg", "gbt"):
            key = f"{fs_name}__{model_name}"
            print(f"--- fitting {key} ({len(cols)} features) ---")
            tm0 = time.time()

            if model_name == "logreg":
                model, imputer, scaler = fit_logistic(train_X, train_y)
                base_estimator = make_logreg_pipeline(model, imputer, scaler)
                coefs = model.coef_[0]
                for fi, feat in enumerate(cols):
                    importance_rows.append({"feature_set": fs_name, "model": model_name,
                                            "feature": feat, "coefficient": float(coefs[fi])})
            else:
                base_estimator = fit_gbt(train_X, train_y)
                rng = np.random.default_rng(RANDOM_STATE)
                sample_idx = rng.choice(len(dev_X), size=min(20000, len(dev_X)), replace=False)
                from sklearn.inspection import permutation_importance
                r = permutation_importance(base_estimator, dev_X.iloc[sample_idx], dev_y[sample_idx],
                                           n_repeats=3, random_state=RANDOM_STATE,
                                           scoring="roc_auc", n_jobs=1)
                for fi, feat in enumerate(cols):
                    importance_rows.append({"feature_set": fs_name, "model": model_name,
                                            "feature": feat, "coefficient": float(r.importances_mean[fi])})

            proba_train = base_estimator.predict_proba(train_X)[:, 1]
            proba_dev = base_estimator.predict_proba(dev_X)[:, 1]
            proba_test = base_estimator.predict_proba(test_X)[:, 1]

            row = {"feature_set": fs_name, "model": model_name, "n_features": len(cols),
                   "fit_time_s": round(time.time() - tm0, 1)}
            for split_name, y, proba in (("train", train_y, proba_train),
                                        ("2025", dev_y, proba_dev),
                                        ("2026", test_y, proba_test)):
                for k, v in metrics_row(y, proba).items():
                    row[f"{split_name}_{k}_raw"] = v

            # Calibration: fit ONLY on 2025 (dev), base estimator frozen.
            calib_results = {}
            for method in ("isotonic", "sigmoid"):
                calibrated = CalibratedClassifierCV(FrozenEstimator(base_estimator), method=method)
                calibrated.fit(dev_X, dev_y)
                cal_proba_dev = calibrated.predict_proba(dev_X)[:, 1]
                cal_proba_test = calibrated.predict_proba(test_X)[:, 1]
                calib_results[method] = {"dev": cal_proba_dev, "test": cal_proba_test}
                for split_name, y, proba in (("2025", dev_y, cal_proba_dev), ("2026", test_y, cal_proba_test)):
                    for k, v in metrics_row(y, proba).items():
                        row[f"{split_name}_{k}_calibrated_{method}"] = v

            diag_rows.append(row)

            for split_name, y, proba in (("2025_raw", dev_y, proba_dev), ("2026_raw", test_y, proba_test),
                                        ("2025_isotonic", dev_y, calib_results["isotonic"]["dev"]),
                                        ("2026_isotonic", test_y, calib_results["isotonic"]["test"]),
                                        ("2025_sigmoid", dev_y, calib_results["sigmoid"]["dev"]),
                                        ("2026_sigmoid", test_y, calib_results["sigmoid"]["test"])):
                c = calibration_deciles(proba, y)
                c["feature_set"], c["model"], c["split_and_calibration"] = fs_name, model_name, split_name
                calib_frames.append(c)

            for split_df, proba in ((train_df, proba_train), (dev_df, proba_dev), (test_df, proba_test)):
                split_df[f"score_{key}_raw"] = proba
            dev_df[f"score_{key}_isotonic"] = calib_results["isotonic"]["dev"]
            test_df[f"score_{key}_isotonic"] = calib_results["isotonic"]["test"]
            dev_df[f"score_{key}_sigmoid"] = calib_results["sigmoid"]["dev"]
            test_df[f"score_{key}_sigmoid"] = calib_results["sigmoid"]["test"]

            print(f"    {key}: fit {row['fit_time_s']}s, "
                  f"2025 AUC raw={row['2025_auc_raw']:.4f} 2026 AUC raw={row['2026_auc_raw']:.4f}")

    pd.DataFrame(diag_rows).to_csv(RESULTS / "model_metrics.csv", index=False)
    pd.concat(calib_frames, ignore_index=True).to_csv(RESULTS / "calibration_deciles.csv", index=False)
    pd.DataFrame(importance_rows).to_csv(RESULTS / "feature_importance.csv", index=False)

    train_df.to_parquet(WORK / "scored_train.parquet", index=False, compression="zstd")
    dev_df.to_parquet(WORK / "scored_dev_2025.parquet", index=False, compression="zstd")
    test_df.to_parquet(WORK / "scored_test_2026.parquet", index=False, compression="zstd")

    manifest = {
        "runtime_s": round(time.time() - t0, 1),
        "train_rows": len(train_df), "dev_rows": len(dev_df), "test_rows": len(test_df),
        "train_positive_rate": float(train_y.mean()), "dev_positive_rate": float(dev_y.mean()),
        "test_positive_rate": float(test_y.mean()),
        "feature_sets": {k: len(v) for k, v in feature_sets.items()},
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "train_and_evaluate_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(pd.DataFrame(diag_rows)[["feature_set", "model", "2025_auc_raw", "2026_auc_raw",
                                   "2025_average_precision_raw", "2026_average_precision_raw"]
                                   ].to_string(index=False))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

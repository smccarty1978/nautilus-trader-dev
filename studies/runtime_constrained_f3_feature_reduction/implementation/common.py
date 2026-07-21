"""Shared helpers: dynamic imports (this repo's established pattern for
`train_and_evaluate.py` bare-name collisions), model-persistence contract
(atomic write -> reload+verify -> hash -> promote), and manifest building.
Reused by every Phase 2/5 training script in this study -- not duplicated
per-script.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
SRC_STUDY = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
PREREQS = ROOT / "studies" / "nt_live_scoring_infra_prereqs"

ARTIFACTS = STUDY / "artifacts" / "models"
RESULTS = STUDY / "results"
CONFIG = STUDY / "config"
WORK = STUDY / "_work"
for d in (ARTIFACTS, RESULTS, CONFIG, WORK):
    d.mkdir(parents=True, exist_ok=True)

TARGET = "bearish_regime_flip_within_300s"
TRAIN_YEARS = [2021, 2022, 2023, 2024]
SELECTION_YEAR = 2025


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_enriched = _load_module("_rc_f3_enriched_retrain_train_eval", ENRICHED_RETRAIN / "train_and_evaluate.py")
fit_gbt = _enriched.fit_gbt
assert _enriched.RANDOM_STATE == 42, (
    f"expected RANDOM_STATE==42 in {ENRICHED_RETRAIN/'train_and_evaluate.py'}, "
    f"got {_enriched.RANDOM_STATE} -- audit resolution #6 guard tripped")
RANDOM_STATE_ASSERTED = _enriched.RANDOM_STATE

_prereqs_inventory = _load_module("_rc_f3_prereqs_inventory", PREREQS / "phase1_feature_inventory.py")
classify_feature = _prereqs_inventory.classify
DUMMY_SUFFIX_RE = _prereqs_inventory.DUMMY_SUFFIX_RE


_TRAIN_DF = None
_DEV_DF = None


def load_train_dev():
    """Cached loader -- train_2021_2024_prepared.parquet (813,972 rows) and
    prepared_2025.parquet (198,255 rows). NEVER loads prepared_2026.parquet
    (forbidden, SPEC.md Guardrails)."""
    global _TRAIN_DF, _DEV_DF
    if _TRAIN_DF is None:
        _TRAIN_DF = pd.read_parquet(SRC_STUDY / "_work" / "train_2021_2024_prepared.parquet")
    if _DEV_DF is None:
        _DEV_DF = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    return _TRAIN_DF, _DEV_DF


def metrics_row(y: np.ndarray, proba: np.ndarray) -> dict:
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 log_loss, roc_auc_score)
    if len(np.unique(y)) < 2:
        return {"auc": None, "average_precision": None, "brier": None, "logloss": None}
    return {
        "auc": float(roc_auc_score(y, proba)),
        "average_precision": float(average_precision_score(y, proba)),
        "brier": float(brier_score_loss(y, proba)),
        "logloss": float(log_loss(y, proba, labels=[0, 1])),
    }


def train_and_persist(model_id: str, ordered_features: list[str], *,
                       model_family: str = "HistGradientBoostingClassifier",
                       source_note: str = "", status: str = "candidate") -> dict:
    """Fit `fit_gbt` on the frozen 2021-2024 population restricted to
    `ordered_features`, evaluate on the complete 2025 population, and persist
    per the mandatory model-persistence contract (atomic write -> reload +
    verify -> hash -> promote). Returns the manifest dict. Never overwrites
    an existing artifact whose hash would differ -- raises instead."""
    t0 = time.time()
    train_df, dev_df = load_train_dev()

    missing = [f for f in ordered_features if f not in train_df.columns]
    if missing:
        raise ValueError(f"{model_id}: {len(missing)} features missing from training data, e.g. {missing[:5]}")

    train_X = train_df[ordered_features]
    dev_X = dev_df[ordered_features]
    train_y = train_df[TARGET].astype(int).to_numpy()
    dev_y = dev_df[TARGET].astype(int).to_numpy()

    model = fit_gbt(train_X, train_y)
    proba_train = model.predict_proba(train_X)[:, 1]
    proba_dev = model.predict_proba(dev_X)[:, 1]

    model_dir = ARTIFACTS / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = model_dir / "model.joblib.tmp"
    import joblib
    joblib.dump(model, tmp_path)
    tmp_hash = sha256_file(tmp_path)

    # reload + verify before promotion
    reloaded = joblib.load(tmp_path)
    reloaded_proba_dev = reloaded.predict_proba(dev_X)[:, 1]
    if not np.array_equal(reloaded_proba_dev, proba_dev):
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"{model_id}: reload-and-rescore mismatch, refusing to promote")

    final_path = model_dir / "model.joblib"
    if final_path.exists():
        existing_hash = sha256_file(final_path)
        if existing_hash != tmp_hash:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"{model_id}: existing artifact hash {existing_hash} != new hash {tmp_hash} "
                f"-- refusing to overwrite, use a new versioned model_id instead")
        tmp_path.unlink()  # identical content already promoted, nothing to do
    else:
        tmp_path.replace(final_path)
    model_sha256 = sha256_file(final_path)

    feat_list_obj = {"model_id": model_id, "ordered_features": ordered_features, "n_features": len(ordered_features)}
    (model_dir / "feature_list.json").write_text(json.dumps(feat_list_obj, indent=2))
    feature_list_sha256 = hashlib.sha256(json.dumps(ordered_features).encode()).hexdigest()

    metrics = {
        "train": metrics_row(train_y, proba_train),
        "dev_2025": metrics_row(dev_y, proba_dev),
        "n_train_rows": len(train_df), "n_dev_rows": len(dev_df),
        "train_positive_rate": float(train_y.mean()), "dev_positive_rate": float(dev_y.mean()),
    }
    (model_dir / "metrics_2025.json").write_text(json.dumps(metrics, indent=2))

    import sklearn
    manifest = {
        "model_id": model_id, "model_family": model_family, "target": TARGET,
        "score_method": "predict_proba(...)[:, 1]", "positive_class_index": 1,
        "n_features": len(ordered_features),
        "ordered_feature_list_sha256": feature_list_sha256,
        "model_sha256": model_sha256,
        "training_data_sha256": sha256_file(SRC_STUDY / "_work" / "train_2021_2024_prepared.parquet"),
        "development_data_sha256": sha256_file(SRC_STUDY / "_work" / "prepared_2025.parquet"),
        "training_years": TRAIN_YEARS, "selection_year": SELECTION_YEAR,
        "training_row_count": len(train_df), "development_row_count": len(dev_df),
        "hyperparameters": {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200,
                            "random_state": RANDOM_STATE_ASSERTED},
        "random_seed": RANDOM_STATE_ASSERTED,
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "fit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fit_runtime_s": round(time.time() - t0, 1),
        "source_model_or_parent_ranking": source_note,
        "registry_contract_version": "nt_live_scoring_infra_prereqs Phase 2 schema (window/window_unit/reset_policy/snapshot_anchor)",
        "feature_inventory_hash": None,  # filled in by caller once inventory exists
        "status": status,
    }
    (model_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[{model_id}] n_features={len(ordered_features)} "
          f"train_auc={metrics['train']['auc']:.4f} dev_auc={metrics['dev_2025']['auc']:.4f} "
          f"fit_runtime={manifest['fit_runtime_s']}s")
    return manifest

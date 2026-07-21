"""Phase 0 required pytest coverage ("model artifact load + rescoring
tolerance") -- flagged missing by the completion-gate audit
(`phase0_reconstruct_model.py`'s own internal tolerance check is a
one-shot script assertion, not a regression-tested pytest case). This
test independently loads the persisted `.joblib` artifact and re-confirms
it still scores within tolerance against the stored reference, so a
silent future change to the artifact or upstream parquet files would be
caught here rather than only at the next full script re-run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
SRC_STUDY = ROOT / "studies" / "short_rth_pure_flip_prediction_enriched"
MODEL_PATH = STUDY / "_work" / "F3_volume_delta_plus_price_levels__gbt_reconstructed.joblib"
MANIFEST_PATH = STUDY / "results" / "phase0_manifest.json"
SCORE_COL = "score_F3_volume_delta_plus_price_levels__gbt_raw"

pytestmark = pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Phase 0 artifact not built yet -- run phase0_reconstruct_model.py")


def _load_sample(n: int = 2000):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    feature_sets = json.loads((SRC_STUDY / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    cols = feature_sets[manifest["feature_set"]]
    dev_df = pd.read_parquet(SRC_STUDY / "_work" / "prepared_2025.parquet")
    scored = pd.read_parquet(SRC_STUDY / "_work" / "scored_dev_2025.parquet", columns=[SCORE_COL])
    rng = np.random.default_rng(42)
    idx = rng.choice(len(dev_df), size=min(n, len(dev_df)), replace=False)
    return dev_df.iloc[idx][cols], scored.iloc[idx][SCORE_COL].to_numpy(), manifest


def test_manifest_reports_successful_reproduction():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["reproduction_ok"] is True
    assert manifest["max_abs_diff_vs_stored_reference"] < manifest["tolerance"] or \
        manifest["max_abs_diff_vs_stored_reference"] == 0.0


def test_persisted_artifact_sha256_matches_manifest():
    import hashlib
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    h = hashlib.sha256()
    with MODEL_PATH.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    assert h.hexdigest() == manifest["model_artifact_sha256"]


def test_loaded_artifact_reproduces_stored_scores_within_tolerance():
    import joblib
    X_sample, stored_scores, manifest = _load_sample()
    model = joblib.load(MODEL_PATH)
    live_scores = model.predict_proba(X_sample)[:, 1]
    abs_diff = np.abs(live_scores - stored_scores)
    assert float(abs_diff.max()) < 1e-6, (
        f"loading the persisted artifact fresh and re-scoring a held-out "
        f"sample must still reproduce the stored reference scores; "
        f"max_abs_diff={abs_diff.max():.3e}")


def test_loaded_artifact_has_expected_hyperparameters():
    import joblib
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    model = joblib.load(MODEL_PATH)
    hp = manifest["hyperparameters"]
    assert model.max_depth == hp["max_depth"]
    assert model.learning_rate == hp["learning_rate"]
    assert model.max_iter == hp["max_iter"]
    assert model.random_state == hp["random_state"]
    assert list(model.classes_) == [0, 1]

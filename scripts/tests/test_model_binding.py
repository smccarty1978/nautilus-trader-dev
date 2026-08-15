"""Tests for model binding validation in scripts/check_model_binding.py.
====================================================================
"""

import sys
from pathlib import Path
import joblib
import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_model_binding import validate_model_binding, calculate_sha256


@pytest.fixture
def dummy_model(tmp_path):
    # Train tiny classifier on 3 features
    X = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9], [1, 3, 5]])
    y = np.array([0, 1, 0, 1])
    clf = HistGradientBoostingClassifier(max_iter=5, random_state=42)
    clf.fit(X, y)
    
    # Save model
    model_file = tmp_path / "model.joblib"
    joblib.dump(clf, model_file)
    sha = calculate_sha256(model_file)
    return model_file, sha


def test_valid_model_binding(dummy_model):
    model_file, sha = dummy_model
    features = ["down_vol_ratio_10s", "consecutive_up_1s", "range_30s_atr"]
    valid, code, errors = validate_model_binding(model_file, features, sha)
    assert valid is True
    assert code == "MODEL_BINDING_CLEAR"
    assert errors == []


def test_model_hash_mismatch(dummy_model):
    model_file, _ = dummy_model
    features = ["down_vol_ratio_10s", "consecutive_up_1s", "range_30s_atr"]
    valid, code, errors = validate_model_binding(model_file, features, expected_sha256="wrong_hash" * 4)
    assert valid is False
    assert any("hash mismatch" in e for e in errors)


def test_feature_count_mismatch(dummy_model):
    model_file, sha = dummy_model
    # Give 2 features instead of 3
    features = ["down_vol_ratio_10s", "consecutive_up_1s"]
    valid, code, errors = validate_model_binding(model_file, features, sha)
    assert valid is False
    assert any("count mismatch" in e for e in errors)

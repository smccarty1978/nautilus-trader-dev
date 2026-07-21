"""Tests for model_runtime.py and threshold_policy.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
ROOT = Path(__file__).resolve().parents[3]
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import pytest  # noqa: E402

import common as C  # noqa: E402
from model_runtime import ModelRuntime, ModelRuntimeError  # noqa: E402
from threshold_policy import ThresholdPolicy  # noqa: E402

MODEL_AVAILABLE = C.MODEL_PATH.exists() and C.FEATURE_SETS_PATH.exists()
pytestmark = pytest.mark.skipif(not MODEL_AVAILABLE, reason="requires persisted F3_top25_gbt_v1 artifact")


@pytest.fixture(scope="module")
def runtime():
    verified = C.verify_frozen_model_inputs()
    return ModelRuntime(C.MODEL_PATH, verified["feature_list"],
                        C.EXPECTED_MODEL_SHA256, C.sha256_file)


def test_model_hash_gate_rejects_tampered_path(tmp_path):
    fake = tmp_path / "model.joblib"
    fake.write_bytes(b"not a real model")
    with pytest.raises(ModelRuntimeError, match="hash mismatch"):
        ModelRuntime(fake, ["f1", "f2"], "deadbeef", C.sha256_file)


def test_model_classes_are_0_1(runtime):
    assert list(runtime.model.classes_) == [0, 1]


def test_score_rejects_wrong_length(runtime):
    with pytest.raises(ModelRuntimeError, match="expected 25 features"):
        runtime.score([0.0] * 10)


def test_score_dict_rejects_missing_features(runtime):
    partial = {f: 0.0 for f in runtime.ordered_features[:5]}
    with pytest.raises(ModelRuntimeError, match="missing features"):
        runtime.score_dict(partial)


def test_score_dict_rejects_extra_features(runtime):
    full = {f: 0.0 for f in runtime.ordered_features}
    full["not_a_real_feature"] = 1.0
    with pytest.raises(ModelRuntimeError, match="unexpected extra features"):
        runtime.score_dict(full)


def test_score_dict_rejects_wrong_order(runtime):
    reordered = {f: 0.0 for f in reversed(runtime.ordered_features)}
    with pytest.raises(ModelRuntimeError, match="key order"):
        runtime.score_dict(reordered)


def test_score_is_deterministic(runtime):
    vec = [0.0] * len(runtime.ordered_features)
    s1 = runtime.score(vec)
    s2 = runtime.score(vec)
    assert s1 == s2


def test_score_dict_matches_score_list(runtime):
    d = {f: float(i) for i, f in enumerate(runtime.ordered_features)}
    vec = [d[f] for f in runtime.ordered_features]
    assert runtime.score_dict(d) == runtime.score(vec)


def test_threshold_policy_r5_r2_5_ordering():
    policy = ThresholdPolicy(top_5pct_threshold=0.5, top_2_5pct_threshold=0.6)
    assert policy.r5_trigger(0.55) is True
    assert policy.r2_5_trigger(0.55) is False
    assert policy.r5_trigger(0.5) is True  # boundary inclusive
    assert policy.r2_5_trigger(0.6) is True


def test_threshold_policy_from_frozen_file():
    path = C.CONFIG / "frozen_thresholds.json"
    if not path.exists():
        pytest.skip("frozen_thresholds.json not yet generated")
    policy = ThresholdPolicy.from_frozen_file(path)
    d = json.loads(path.read_text())
    assert policy.top_5pct_threshold == d["top_5pct_threshold"]
    assert policy.top_2_5pct_threshold == d["top_2_5pct_threshold"]
    assert policy.top_5pct_threshold < policy.top_2_5pct_threshold

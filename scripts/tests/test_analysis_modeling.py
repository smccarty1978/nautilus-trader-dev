"""A3 tests: reproducible modelling provenance. Synthetic data only.

No real study model is trained here and no threshold is derived from real data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.analysis import errors as E  # noqa: E402
from research.analysis import modeling as MOD  # noqa: E402
from research.analysis.spec import parse_analysis_spec  # noqa: E402

FEATURES = ["f0", "f1", "f2", "f3"]


def synthetic_xy(n=400, seed=11, partition="train"):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURES))), columns=FEATURES)
    logit = 1.2 * X["f0"] - 0.8 * X["f1"] + 0.3 * X["f2"]
    y = pd.Series((rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int))
    meta = pd.DataFrame({"_partition": [partition] * n})
    return X, y, meta


def arms_spec(seed=42):
    return parse_analysis_spec({
        "analysis_id": "abc", "collection": {"run_id": "r1"}, "seed": seed,
        "model_arms": [
            {"name": "A", "features": ["f0"], "description": "frozen base"},
            {"name": "B", "features": ["f0", "f1"], "description": "A + structural"},
            {"name": "C", "features": ["f0", "f1", "f2"], "description": "B + productivity"},
        ],
    })


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_fit_records_complete_provenance():
    X, y, meta = synthetic_xy()
    m = MOD.fit_model(X, y, arm="A", seed=7, dataset_identity_sha256="d" * 64,
                      analysis_spec_sha256="s" * 64, meta=meta)
    p = m.provenance
    assert p.ordered_features == FEATURES and p.n_features == 4
    assert p.n_rows == len(X) and p.seed == 7
    assert p.dataset_identity_sha256 == "d" * 64
    assert p.analysis_spec_sha256 == "s" * 64
    assert len(p.model_sha256) == 64
    assert p.library_versions["python"] and "sklearn" in p.library_versions
    assert p.split_policy["kind"] == "single_partition"
    assert p.split_policy["fit_partitions"] == ["train"]
    assert len(p.fit_identity_sha256) == 64


def test_same_inputs_and_seed_reproduce_identical_identity_and_predictions():
    X, y, meta = synthetic_xy()
    a = MOD.fit_model(X, y, arm="A", seed=5, dataset_identity_sha256="d", meta=meta)
    b = MOD.fit_model(X, y, arm="A", seed=5, dataset_identity_sha256="d", meta=meta)
    assert a.provenance.fit_identity_sha256 == b.provenance.fit_identity_sha256
    assert a.provenance.model_sha256 == b.provenance.model_sha256

    sa, ia = MOD.score_and_record(a, X)
    sb, ib = MOD.score_and_record(b, X)
    assert ia == ib
    np.testing.assert_allclose(sa, sb)


def test_changing_seed_changes_fit_identity():
    X, y, meta = synthetic_xy()
    a = MOD.fit_model(X, y, arm="A", seed=1, meta=meta)
    b = MOD.fit_model(X, y, arm="A", seed=2, meta=meta)
    assert a.provenance.fit_identity_sha256 != b.provenance.fit_identity_sha256


def test_changing_feature_set_changes_fit_identity():
    X, y, meta = synthetic_xy()
    a = MOD.fit_model(X[["f0", "f1"]], y, arm="A", seed=1, meta=meta)
    b = MOD.fit_model(X[["f0", "f2"]], y, arm="A", seed=1, meta=meta)
    assert a.provenance.fit_identity_sha256 != b.provenance.fit_identity_sha256


def test_prediction_identity_changes_with_scores():
    assert MOD.prediction_identity([0.1, 0.2]) == MOD.prediction_identity([0.1, 0.2])
    assert MOD.prediction_identity([0.1, 0.2]) != MOD.prediction_identity([0.1, 0.3])


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


def test_fit_refuses_to_mix_train_and_dev():
    X, y, _ = synthetic_xy(n=100)
    meta = pd.DataFrame({"_partition": ["train"] * 50 + ["dev"] * 50})
    with pytest.raises(E.PartitionMixing, match="PARTITION_MIXING"):
        MOD.fit_model(X, y, arm="A", meta=meta)


def test_fit_refuses_outcome_columns_as_features():
    X, y, meta = synthetic_xy()
    X = X.copy()
    X["flip_ts"] = 1
    with pytest.raises(E.SchemaSurplus, match="outcome columns"):
        MOD.fit_model(X, y, arm="A", meta=meta)


def test_fit_refuses_empty_or_misaligned_input():
    X, y, meta = synthetic_xy()
    with pytest.raises(E.SchemaMissing):
        MOD.fit_model(X.iloc[0:0], y.iloc[0:0], arm="A")
    with pytest.raises(E.SchemaMissing):
        MOD.fit_model(X, y.iloc[:-1], arm="A")


def test_unsupported_estimator_is_rejected():
    X, y, meta = synthetic_xy()
    with pytest.raises(E.InvalidAnalysisSpec, match="unsupported estimator"):
        MOD.fit_model(X, y, arm="A", estimator="telepathy", meta=meta)


def test_prediction_requires_the_fitted_features():
    X, y, meta = synthetic_xy()
    m = MOD.fit_model(X, y, arm="A", meta=meta)
    with pytest.raises(E.SchemaMissing, match="missing fitted features"):
        m.predict_proba(X.drop(columns=["f1"]))


def test_prediction_reindexes_to_fitted_order_not_frame_order():
    """Same members in a different order must not silently change the input."""
    X, y, meta = synthetic_xy()
    m = MOD.fit_model(X, y, arm="A", meta=meta)
    reordered = X[FEATURES[::-1]]
    np.testing.assert_allclose(m.predict_proba(X), m.predict_proba(reordered))


# ---------------------------------------------------------------------------
# Declared A/B/C arms
# ---------------------------------------------------------------------------


def test_arms_must_be_predeclared():
    X, y, meta = synthetic_xy()
    bare = parse_analysis_spec({"analysis_id": "a", "collection": {"run_id": "r"}})
    with pytest.raises(E.InvalidAnalysisSpec, match="predeclared"):
        MOD.fit_arms(X, y, bare, meta=meta)


def test_arm_requesting_absent_features_is_rejected():
    X, y, meta = synthetic_xy()
    spec = parse_analysis_spec({
        "analysis_id": "a", "collection": {"run_id": "r"},
        "model_arms": [{"name": "A", "features": ["f0", "not_collected"]}],
    })
    with pytest.raises(E.SchemaMissing, match="absent from the collection"):
        MOD.fit_arms(X, y, spec, meta=meta)


def test_abc_arms_fit_with_shared_seed_and_distinct_identities():
    X, y, meta = synthetic_xy()
    spec = arms_spec()
    models = MOD.fit_arms(X, y, spec, dataset_identity_sha256="d" * 64, meta=meta)
    assert set(models) == {"A", "B", "C"}
    assert [models[k].provenance.n_features for k in ("A", "B", "C")] == [1, 2, 3]
    assert all(m.provenance.seed == spec.seed for m in models.values())
    assert all(m.provenance.analysis_spec_sha256 == spec.analysis_spec_sha256
               for m in models.values())
    ids = {m.provenance.fit_identity_sha256 for m in models.values()}
    assert len(ids) == 3


def test_model_manifest_written_with_all_arms(tmp_path):
    X, y, meta = synthetic_xy()
    models = MOD.fit_arms(X, y, arms_spec(), dataset_identity_sha256="d" * 64, meta=meta)
    out = tmp_path / "model_manifest.json"
    payload = MOD.write_model_manifest(models, out)
    assert out.is_file()
    on_disk = json.loads(out.read_text())
    assert set(on_disk["arms"]) == {"A", "B", "C"}
    for arm in on_disk["arms"].values():
        for key in ("ordered_features", "seed", "model_sha256", "library_versions",
                    "split_policy", "fit_identity_sha256"):
            assert key in arm


# ---------------------------------------------------------------------------
# Threshold freeze
# ---------------------------------------------------------------------------


def _train_meta(n: int, partition: str = "train") -> pd.DataFrame:
    return pd.DataFrame({"_partition": [partition] * n})


def test_threshold_freeze_records_its_derivation_population():
    rng = np.random.default_rng(0)
    scores = rng.random(500)
    y = (scores > 0.7).astype(int)
    rec = MOD.freeze_threshold(scores, y, meta=_train_meta(500), method="quantile", value=0.9,
                               dataset_identity_sha256="d" * 64)
    assert rec["derivation_population"] == "train"
    assert rec["derivation_population_source"] == "derived_from_meta_partition"
    assert rec["derivation_n"] == 500
    assert 0 < rec["selected_rate"] < 0.2
    assert rec["dataset_identity_sha256"] == "d" * 64
    assert len(rec["threshold_freeze_sha256"]) == 64


def test_threshold_freeze_identity_is_stable_and_sensitive():
    scores = np.linspace(0, 1, 100)
    y = (scores > 0.5).astype(int)
    train, dev = _train_meta(100), _train_meta(100, "dev")
    a = MOD.freeze_threshold(scores, y, meta=train, value=0.9)
    b = MOD.freeze_threshold(scores, y, meta=train, value=0.9)
    c = MOD.freeze_threshold(scores, y, meta=train, value=0.8)
    d = MOD.freeze_threshold(scores, y, meta=dev, value=0.9)
    assert a["threshold_freeze_sha256"] == b["threshold_freeze_sha256"]
    assert a["threshold_freeze_sha256"] != c["threshold_freeze_sha256"]
    # The derivation population is bound into the identity: same scores, same
    # parameter, different population -> different threshold artifact.
    assert a["threshold_freeze_sha256"] != d["threshold_freeze_sha256"]


def test_threshold_freeze_rejects_empty_and_unknown_method():
    with pytest.raises(E.SchemaMissing):
        MOD.freeze_threshold([], [], meta=_train_meta(0))
    with pytest.raises(E.InvalidAnalysisSpec, match="unsupported threshold method"):
        MOD.freeze_threshold([0.1, 0.2], [0, 1], meta=_train_meta(2), method="vibes")


def test_library_versions_reported():
    v = MOD.library_versions()
    assert v["python"]
    assert set(v) >= {"python", "numpy", "pandas", "sklearn", "lightgbm"}

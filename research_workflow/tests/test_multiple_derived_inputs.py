"""RT-04 -- every declared frozen derived input is scored, in order, both populations.

The collector bound only ``di_list[0]`` and only in episode mode. Now it builds an
ordered list of scorers (one per ``features.derived_inputs`` entry), scores all of them
in ``_apply_derived_scores`` for checkpoint-grid and episode candidates alike, and
preflight fails closed if a declared runtime-scored input has no bound scorer.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sklearn.linear_model import LogisticRegression

from research.analysis.modeling import FittedModel, FitProvenance
from research_workflow.generic_collector import GenericStudyCollector
from research_workflow.model_artifacts import persist_models
from research_workflow.runtime_bindings import verify_runtime_contract


# --------------------------------------------------------------------------- #
# _apply_derived_scores: order, all scorers, null-input -> null column, no leak
# --------------------------------------------------------------------------- #
class _FakeScorer:
    def __init__(self, value):
        self.value = value

    def score(self, inputs, *, checkpoint_ts, direction, availability_ts):  # noqa: ARG002
        return SimpleNamespace(score=self.value)


def _collector_with(scorers):
    obj = GenericStudyCollector.__new__(GenericStudyCollector)
    obj._derived_scorers = scorers
    return obj


def test_all_declared_scores_filled_in_order():
    obj = _collector_with([
        {"name": "score_a", "scorer": _FakeScorer(0.10), "surface": {"LONG": ["f1"], "SHORT": ["f1"]}},
        {"name": "score_b", "scorer": _FakeScorer(0.90), "surface": {"LONG": ["f1", "f2"], "SHORT": ["f1", "f2"]}},
    ])
    rec = {"observation_ts": 1, "regime_direction": 1, "f1": 1.0, "f2": 2.0}
    obj._apply_derived_scores(rec)
    assert rec["score_a"] == pytest.approx(0.10)
    assert rec["score_b"] == pytest.approx(0.90)


def test_null_input_yields_null_column_not_missing():
    obj = _collector_with([
        {"name": "score_a", "scorer": _FakeScorer(0.5), "surface": {"LONG": ["f1"], "SHORT": ["f1"]}},
    ])
    rec = {"observation_ts": 1, "regime_direction": 1, "f1": None}
    obj._apply_derived_scores(rec)
    assert "score_a" in rec and rec["score_a"] is None


def test_no_undeclared_score_column_written():
    obj = _collector_with([
        {"name": "score_a", "scorer": _FakeScorer(0.5), "surface": {"LONG": ["f1"], "SHORT": ["f1"]}},
    ])
    rec = {"observation_ts": 1, "regime_direction": -1, "f1": 1.0}
    obj._apply_derived_scores(rec)
    assert set(rec) == {"observation_ts", "regime_direction", "f1", "score_a"}


def test_zero_scorers_is_a_noop():
    obj = _collector_with([])
    rec = {"observation_ts": 1, "regime_direction": 1}
    obj._apply_derived_scores(rec)
    assert rec == {"observation_ts": 1, "regime_direction": 1}


# --------------------------------------------------------------------------- #
# preflight -- 1:1 scorer coverage, unique names
# --------------------------------------------------------------------------- #
def _register(root, name_seed):
    study = root / "studies" / f"parent_{name_seed}"
    study.mkdir(parents=True)
    est = LogisticRegression().fit([[0, 0], [1, 1]], [0, 1])
    prov = FitProvenance("A", "logistic_regression", ["x", "y"], 2, 2, 0, {}, {}, None, None, {}, "x")
    rec = persist_models(
        study, {"A": FittedModel(est, prov)},
        {"arms": {"A": {**prov.to_dict(), "fit_identity_sha256": prov.fit_identity_sha256}}},
    )["records"][0]
    reg = root / "studies" / "model_registry" / f"{rec['model_id']}.json"
    body = json.loads(reg.read_text())
    body["scientific_status"] = "VALID_PRIMARY"
    reg.write_text(json.dumps(body))
    return rec["model_id"]


def _compiled_study(root, derived):
    study = root / "studies" / "child"
    (study / "audit").mkdir(parents=True)
    compiled = {
        "study_id": "child",
        "strategy_class": "research_workflow.generic_collector.GenericStudyCollector",
        "spec": {"execution": {"strategy_class": "research_workflow.generic_collector.GenericStudyCollector"},
                 "features": {"derived_inputs": derived}},
        "contracts": {
            "target_contract": {},
            "population_contract": {"population_type": "regime_state"},
            "feature_contract": {"derived_inputs": derived},
        },
    }
    (study / "compiled_study.json").write_text(json.dumps(compiled))
    return study


def _di(name, model_id):
    return {"name": name, "kind": "frozen_external_model_score", "model_id": model_id,
            "retrain_prohibited": True}


def test_two_external_models_both_bind(tmp_path):
    m1, m2 = _register(tmp_path, "1"), _register(tmp_path, "2")
    study = _compiled_study(tmp_path, [_di("score_a", m1), _di("score_b", m2)])
    r = verify_runtime_contract(study, scope="all")
    assert not any("derived_input" in m["primitive"] or "scorer_coverage" in m["primitive"]
                   for m in r["missing"]), r["missing"]


def test_missing_scorer_binding_fails_preflight(tmp_path):
    m1 = _register(tmp_path, "1")
    study = _compiled_study(tmp_path, [_di("score_a", m1), _di("score_b", "0" * 64)])
    r = verify_runtime_contract(study, scope="all")
    reasons = " ".join(m["reason"] for m in r["missing"])
    assert "score_b" in reasons or "SCORER_UNBOUND" in reasons
    assert not r["passed"]


def test_duplicate_derived_names_fail_preflight(tmp_path):
    m1, m2 = _register(tmp_path, "1"), _register(tmp_path, "2")
    study = _compiled_study(tmp_path, [_di("dup", m1), _di("dup", m2)])
    r = verify_runtime_contract(study, scope="all")
    assert any("DUPLICATE_NAME" in m["reason"] for m in r["missing"]), r["missing"]

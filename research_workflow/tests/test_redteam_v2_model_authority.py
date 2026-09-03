"""Packet B -- model authority.

B1 (CRITICAL-3): score mode must AUTHENTICATE the requested model identity before any
``score()`` call -- directory/manifest self-consistency, a recomputable identity_rule,
canonical bytes, the feature/preprocessing contract, caller-declared expectations, tier
reusability, and golden-frame prediction equivalence. A model copied under another id, a
manifest with an edited ``model_id``, corrupted canonical bytes, a tampered golden fixture,
a reordered feature surface, a mismatched expectation, and a non-reusable tier/status must
all be refused -- both directly (``authenticate_model``) and through the score-mode runtime
path (``V2Lifecycle._score_models``).

B2 (WARNING): a derived/frozen model score's causal availability is ``max(input
availability, score evaluation timestamp)`` -- never the decision epoch assigned blindly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from research_workflow import model_store as ms
from research_workflow.external_model_scoring import ExternalModelScoringError, FrozenExternalModelScorer
from research_workflow.grammar import compile_study, load_spec
from research_workflow.lifecycle_v2 import V2Lifecycle
from research_workflow.tests.test_external_model_scoring import fixture as external_scorer_fixture

FEATS = ["f0", "f1", "f2"]
ROOT = Path(__file__).resolve().parents[2]


def _lineage(**kw) -> ms.ModelLineage:
    ordered_inputs = kw.pop("ordered_inputs", list(FEATS))
    base = dict(
        study_id="redteam_b_study", cell_id="LONG_SL1_0", direction="LONG", target_arm="SL1_0",
        fold_id="final", config_id="C00", seed=42, ordered_inputs=ordered_inputs,
        feature_contract_sha256=hashlib.sha256(json.dumps(ordered_inputs).encode()).hexdigest(),
        preprocessing_contract_sha256="identity", target_contract_sha256="c" * 64,
        target_frame_identity="d" * 64, training_population_identity="e" * 64,
        train_years=[2021, 2022], validation_years=[2023], hyperparameters={},
        family="logistic_regression", fit_identity_sha256=None, closure_identities={}, model_role="primary",
    )
    base.update(kw)
    return ms.ModelLineage(**base)


def _train_frame(n: int = 64, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(n, len(FEATS))), columns=FEATS)
    return X


def _store(root: Path, *, tier: str = "registry", selection_status: str = "selected",
          ordered_inputs=None, identity_rule: str | None = None, target_arm: str = "SL1_0") -> tuple[str, pd.DataFrame]:
    X = _train_frame()
    y = pd.Series(((X["f0"] + 0.5 * X["f1"]) > 0).astype(int))
    est = LogisticRegression(max_iter=200).fit(X, y)
    lineage_kw = {"target_arm": target_arm}
    if ordered_inputs is not None:
        lineage_kw["ordered_inputs"] = ordered_inputs
    lineage = _lineage(**lineage_kw)
    model_id = hashlib.sha256(json.dumps(lineage.__dict__, sort_keys=True, default=str).encode()).hexdigest()
    kwargs = {}
    if identity_rule is not None:
        kwargs["identity_rule"] = identity_rule
    ms.store_model(model_id=model_id, estimator=est, lineage=lineage, tier=tier, selection_status=selection_status,
                   metrics={}, golden_train_frame=X, model_root=root, golden_rows=len(X), **kwargs)
    return model_id, X


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "model_root"


# --------------------------------------------------------------------------- #
# B1: authenticate_model
# --------------------------------------------------------------------------- #

def test_f_legit_model_authenticates_and_returns_evidence(root: Path):
    model_id, _ = _store(root)
    evidence = ms.authenticate_model(model_id, model_root=root)
    assert evidence["model_id"] == model_id
    assert evidence["identity_rule"] == "v2_lineage_sha256"
    assert evidence["golden"]["status"] == "PASS"
    assert evidence["tier"] == "registry" and evidence["selection_status"] == "selected"


def test_a_copied_model_dir_refuses_without_manifest_edit(root: Path):
    model_id, _ = _store(root)
    src = ms.model_dir(model_id, root)
    dst = ms.model_dir("copied-id", root)
    import shutil
    shutil.copytree(src, dst)
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model("copied-id", model_root=root)


def test_a_copied_model_dir_refuses_even_with_manifest_id_edited(root: Path):
    model_id, _ = _store(root)
    src = ms.model_dir(model_id, root)
    dst = ms.model_dir("copied-id-2", root)
    import shutil
    shutil.copytree(src, dst)
    manifest_path = dst / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_id"] = "copied-id-2"  # attacker also edits the self-consistency field
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model("copied-id-2", model_root=root)


def test_b_corrupted_canonical_bytes_refused(root: Path):
    model_id, _ = _store(root)
    manifest = ms.read_manifest(model_id, root)
    canon_path = ms.model_dir(model_id, root) / "canonical" / manifest["canonical"]["path"]
    data = bytearray(canon_path.read_bytes())
    data[0] ^= 0xFF
    canon_path.write_bytes(bytes(data))
    with pytest.raises(ms.ModelStoreError, match="CANONICAL_BYTES_CORRUPT"):
        ms.authenticate_model(model_id, model_root=root)


def test_c_tampered_golden_prediction_refused(root: Path):
    model_id, _ = _store(root)
    manifest = ms.read_manifest(model_id, root)
    expected_path = ms.model_dir(model_id, root) / manifest["golden"]["expected_path"]
    body = json.loads(expected_path.read_text(encoding="utf-8"))
    body["expected_scores"][0] = float(body["expected_scores"][0]) + 1.0
    expected_path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ms.ModelStoreError, match="GOLDEN_PREDICTION_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root)


def test_c_missing_golden_frame_refused(root: Path):
    model_id, _ = _store(root)
    manifest_path = ms.model_dir(model_id, root) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["golden"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ms.ModelStoreError, match="GOLDEN_FRAME_MISSING"):
        ms.authenticate_model(model_id, model_root=root)


def test_d_reordered_ordered_inputs_refused(root: Path):
    model_id, _ = _store(root)
    manifest_path = ms.model_dir(model_id, root) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lineage"]["ordered_inputs"] = list(reversed(manifest["lineage"]["ordered_inputs"]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH|FEATURE_CONTRACT_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root)


def test_e_expectation_mismatch_refused(root: Path):
    model_id, _ = _store(root)
    with pytest.raises(ms.ModelStoreError, match="MODEL_EXPECTATION_MISMATCH"):
        ms.authenticate_model(model_id, expect={"target_arm": "WRONG_ARM"}, model_root=root)
    # a correct expectation passes
    ms.authenticate_model(model_id, expect={"target_arm": "SL1_0", "study_id": "redteam_b_study"}, model_root=root)


def test_h_ledger_rejected_tier_refused_for_reuse(root: Path):
    model_id, _ = _store(root, tier="ledger", selection_status="rejected")
    with pytest.raises(ms.ModelStoreError, match="MODEL_TIER_NOT_REUSABLE"):
        ms.authenticate_model(model_id, model_root=root)


def test_legacy_unrecomputable_identity_rule_fails_closed(root: Path):
    model_id, _ = _store(root, identity_rule="legacy_v1_immutable_unrecomputable")
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_UNVERIFIABLE"):
        ms.authenticate_model(model_id, model_root=root)


# --------------------------------------------------------------------------- #
# B1 (g): the score-mode runtime path refuses the same attacks and passes a legit model
# --------------------------------------------------------------------------- #

def _score_frame() -> pd.DataFrame:
    X = _train_frame(n=64, seed=1)
    frame = X.copy()
    frame["y"] = ((X["f0"] + 0.5 * X["f1"]) > 0).astype(int)
    frame["_year"] = 2023
    return frame


def test_g_score_models_refuses_attacks_and_passes_legit(root: Path, monkeypatch):
    monkeypatch.setattr("research_workflow.roots.resolve_model_root", lambda *a, **k: root)
    model_id, _ = _store(root)
    frame = _score_frame()

    def _models(mid):
        return [{"id": mid, "label": "y", "subset": {}, "name": "primary"}]

    scored = V2Lifecycle._score_models(frame, _models(model_id))
    assert scored[0]["model_authentication"]["golden"]["status"] == "PASS"

    bad_id, _ = _store(root, tier="ledger", selection_status="rejected", target_arm="SL2_0")
    with pytest.raises(ms.ModelStoreError, match="MODEL_TIER_NOT_REUSABLE"):
        V2Lifecycle._score_models(frame, _models(bad_id))

    src = ms.model_dir(model_id, root); dst = ms.model_dir("copied-runtime", root)
    import shutil
    shutil.copytree(src, dst)
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        V2Lifecycle._score_models(frame, _models("copied-runtime"))


def test_g_score_models_honors_expect(root: Path, monkeypatch):
    monkeypatch.setattr("research_workflow.roots.resolve_model_root", lambda *a, **k: root)
    model_id, _ = _store(root)
    frame = _score_frame()
    models = [{"id": model_id, "label": "y", "subset": {}, "name": "primary", "expect": {"target_arm": "NOT_THIS_ARM"}}]
    with pytest.raises(ms.ModelStoreError, match="MODEL_EXPECTATION_MISMATCH"):
        V2Lifecycle._score_models(frame, models)


# --------------------------------------------------------------------------- #
# B2: derived-score causal availability
# --------------------------------------------------------------------------- #

def test_i_late_input_marks_score_unavailable_at_t(tmp_path):
    scorer = FrozenExternalModelScorer.bind(external_scorer_fixture(tmp_path), parent_dir=tmp_path)
    with pytest.raises(ExternalModelScoringError, match="NOT_AVAILABLE_AT_CHECKPOINT"):
        scorer.score({"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="LONG", availability_ts={"a": 8, "b": 11})


def test_ii_all_inputs_on_time_available_at_t(tmp_path):
    scorer = FrozenExternalModelScorer.bind(external_scorer_fixture(tmp_path), parent_dir=tmp_path)
    obs = scorer.score({"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="SHORT", availability_ts={"a": 8, "b": 9})
    assert obs.available_at_ns == 10


def test_iii_async_evaluation_availability_is_max_inputs_and_evaluation(tmp_path):
    scorer = FrozenExternalModelScorer.bind(external_scorer_fixture(tmp_path), parent_dir=tmp_path)
    obs = scorer.score({"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="SHORT",
                       availability_ts={"a": 3, "b": 5}, score_evaluation_ts=8)
    assert obs.available_at_ns == 8  # max(5, 8), not checkpoint_ts and not blind T
    with pytest.raises(ExternalModelScoringError, match="NOT_AVAILABLE_AT_CHECKPOINT"):
        scorer.score({"a": 1.0, "b": 0.0}, checkpoint_ts=10, direction="SHORT",
                     availability_ts={"a": 3, "b": 5}, score_evaluation_ts=11)


def test_iv_compiled_availability_table_names_the_rule_and_dependencies():
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_a" / "study.yaml")
    spec["features"]["derived_inputs"] = [{
        "name": "parent_score", "kind": "frozen_external_model_score",
        "ordered_feature_surfaces": {"LONG": ["f0"], "SHORT": ["f0"]},
    }]
    out = compile_study(spec, repo_root=ROOT)
    assert out.ok, out.card()
    rows = out.plan.availability["rows"]
    row = next(r for r in rows if r["id"] == "derived.parent_score")
    assert row["kind"] == "derived_score"
    assert row["availability_rule"] == "max(inputs) ∪ evaluation"
    assert row["dependencies"] == ["f0"]


# --------------------------------------------------------------------------- #
# Packet B follow-up: legacy_v1_committed_registry identity rule
# --------------------------------------------------------------------------- #

def _git_init(repo: Path) -> None:
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)


def _commit_file(repo: Path, rel: str) -> None:
    import subprocess
    subprocess.run(["git", "add", rel], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"add {rel}"], cwd=str(repo), check=True)


def _legacy_manifest_and_record(root: Path, repo: Path, *, commit: bool = True,
                                record_overrides: dict | None = None,
                                legacy_overrides: dict | None = None) -> str:
    """A migrated-style manifest (identity_rule legacy_v1_immutable_unrecomputable +
    legacy_registry_record) plus a v1 registry record at studies/model_registry/<id>.json
    inside a fresh tmp git repo, matching the real migration layout."""
    model_id, _ = _store(root, identity_rule="legacy_v1_immutable_unrecomputable", target_arm="LEGACY_ARM")
    manifest_path = ms.model_dir(model_id, root) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical_sha = manifest["canonical"]["byte_sha256"]  # sklearn_pickle -> compared to artifact_sha256
    record = {"model_id": model_id, "study_id": manifest["lineage"]["study_id"],
             "artifact_sha256": canonical_sha, "runtime_identity_sha256": "rt-sha-legacy-1"}
    record.update(record_overrides or {})
    legacy = {"runtime_identity_sha256": "rt-sha-legacy-1"}
    legacy.update(legacy_overrides or {})
    manifest["legacy_registry_record"] = legacy
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rec_dir = repo / "studies" / "model_registry"; rec_dir.mkdir(parents=True, exist_ok=True)
    rec_path = rec_dir / f"{model_id}.json"
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    if commit:
        _commit_file(repo, f"studies/model_registry/{model_id}.json")
    return model_id


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"; r.mkdir()
    _git_init(r)
    return r


def test_legacy_committed_registry_pass(root: Path, repo: Path):
    model_id = _legacy_manifest_and_record(root, repo)
    evidence = ms.authenticate_model(model_id, model_root=root, repo_root=repo)
    assert evidence["identity_rule"] == ms.LEGACY_V1_COMMITTED_REGISTRY_RULE
    assert evidence["golden"]["status"] == "PASS"


def test_legacy_committed_registry_untracked_record_unverifiable(root: Path, repo: Path):
    model_id = _legacy_manifest_and_record(root, repo, commit=False)
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_UNVERIFIABLE"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)


def test_legacy_committed_registry_sha_mismatch(root: Path, repo: Path):
    model_id = _legacy_manifest_and_record(root, repo, record_overrides={"artifact_sha256": "0" * 64})
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)


def test_legacy_committed_registry_study_id_mismatch(root: Path, repo: Path):
    model_id = _legacy_manifest_and_record(root, repo, record_overrides={"study_id": "some_other_study"})
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)


def test_legacy_committed_registry_runtime_identity_mismatch(root: Path, repo: Path):
    model_id = _legacy_manifest_and_record(root, repo, legacy_overrides={"runtime_identity_sha256": "different"})
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)

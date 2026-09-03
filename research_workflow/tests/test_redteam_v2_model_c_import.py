"""Packet G -- Model C durable-store follow-up.

Model C's parent bundle (the frozen Family-A/B/C model bundle of the sealed V1 study
``clean_maturity_flip_model_rolling_productivity``) is shaped differently from the
``legacy_v1_committed_registry`` case Packet B added: ONE joblib file mapping arm ->
``{estimator, fit_identity_sha256}``, with NO per-model ``studies/model_registry/<id>.json``
record -- only a committed TRAIN freeze (``train_experiment_freeze.json``) that records
every arm's ``fit_identity_sha256`` and ordered feature surface.

These tests exercise the new ``legacy_v1_train_freeze`` identity rule
(``model_store._verify_legacy_v1_train_freeze``) and the ``migrate_train_freeze_bundle``
adapter (``model_migration.py``) against a synthetic bundle in a fresh tmp git repo --
never against the real study, which stays untouched.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from lightgbm import LGBMClassifier

from research.analysis.identity import canonical_sha256
from research_workflow import model_store as ms
from research_workflow.model_migration import migrate_train_freeze_bundle


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _git_init(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _commit(repo: Path, rel: str) -> None:
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"add {rel}")


FEATS_A = ["f0", "f1"]
FEATS_B = ["f0", "f1", "f2"]


def _train_frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(size=(n, 3)), columns=["f0", "f1", "f2"])


def _fit(cols: list[str], frame: pd.DataFrame):
    y = ((frame[cols[0]] + 0.5 * frame[cols[-1]]) > 0).astype(int)
    return LGBMClassifier(n_estimators=20, max_depth=3, num_leaves=8, verbosity=-1).fit(frame[cols], y)


def _build_repo(tmp_path: Path, *, study_id: str = "redteam_model_c",
                tamper_freeze_bytes: bool = False, commit_freeze: bool = True,
                arm_fit_identity_override: dict | None = None) -> tuple[Path, Path, Path, dict]:
    """A fresh tmp git repo carrying studies/<study_id>/artifacts/train_experiment_freeze.json
    (committed) plus a synthetic two-arm joblib bundle (LONG_A, LONG_B) built OUTSIDE the
    repo -- mirrors Model C's real layout: bundle bytes are gitignored, the freeze is not."""
    repo = tmp_path / "repo"; repo.mkdir(); _git_init(repo)
    study_dir = repo / "studies" / study_id / "artifacts"; study_dir.mkdir(parents=True)

    frame = _train_frame()
    est_a = _fit(FEATS_A, frame)
    est_b = _fit(FEATS_B, frame)
    fit_id_a = hashlib.sha256(b"fit-LONG_A").hexdigest()
    fit_id_b = hashlib.sha256(b"fit-LONG_B").hexdigest()
    overrides = arm_fit_identity_override or {}
    bundle = {
        "LONG_A": {"estimator": est_a, "fit_identity_sha256": overrides.get("LONG_A", fit_id_a)},
        "LONG_B": {"estimator": est_b, "fit_identity_sha256": overrides.get("LONG_B", fit_id_b)},
    }
    bundle_path = tmp_path / "bytes" / "train_fitted_models.joblib"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, bundle_path)

    freeze = {
        "partition": "train", "schema_version": 1, "study_id": study_id, "provenance": "TRAIN_ONLY",
        "feature_sets": {"A": FEATS_A, "B": FEATS_B},
        "preprocessing_hash": "pp-hash-1",
        "model_hashes": {"LONG_A": fit_id_a, "LONG_B": fit_id_b},
        "model_artifact": "train_fitted_models.joblib",
        "merged_dataset_identity_sha256": "merge-1", "target_contract_sha256": "target-1",
    }
    freeze["freeze_sha256"] = canonical_sha256({k: v for k, v in freeze.items() if k != "generated_at_utc"})
    freeze_path = study_dir / "train_experiment_freeze.json"
    if tamper_freeze_bytes:
        freeze_path.write_text(json.dumps(freeze) + "  ", encoding="utf-8")  # bytes != declared sha later
    else:
        freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    if commit_freeze:
        _commit(repo, f"studies/{study_id}/artifacts/train_experiment_freeze.json")
    return repo, freeze_path, bundle_path, freeze


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "model_root"


def test_migrate_and_authenticate_pass(tmp_path: Path, root: Path):
    repo, freeze_path, bundle_path, freeze = _build_repo(tmp_path)
    train_frame = _train_frame(n=300, seed=1)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=train_frame, model_root=root, golden_rows=64)
    assert report["migrated"] == 2 and not report["failed"]
    for arm in ("LONG_A", "LONG_B"):
        model_id = report["arms"][arm]["model_id"]
        evidence = ms.authenticate_model(model_id, model_root=root, repo_root=repo)
        assert evidence["identity_rule"] == ms.LEGACY_V1_TRAIN_FREEZE_RULE
        assert evidence["golden"]["status"] == "PASS"
        assert evidence["golden"]["max_abs_diff"] == 0.0


def test_score_equivalence_store_vs_legacy_bundle(tmp_path: Path, root: Path):
    repo, freeze_path, bundle_path, freeze = _build_repo(tmp_path)
    train_frame = _train_frame(n=300, seed=1)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=train_frame, model_root=root, golden_rows=64)
    legacy_bundle = joblib.load(bundle_path)
    for arm in ("LONG_A", "LONG_B"):
        model_id = report["arms"][arm]["model_id"]
        manifest = ms.read_manifest(model_id, root)
        mdir = ms.model_dir(model_id, root)
        frame = pd.read_parquet(mdir / manifest["golden"]["frame_path"])
        store_scores = ms.score(model_id, frame, model_root=root)
        cols = manifest["lineage"]["ordered_inputs"]
        legacy_scores = legacy_bundle[arm]["estimator"].predict_proba(frame[cols])[:, 1]
        assert float(np.max(np.abs(store_scores - legacy_scores))) == 0.0


def test_untracked_freeze_unverifiable(tmp_path: Path, root: Path):
    repo, freeze_path, bundle_path, freeze = _build_repo(tmp_path, commit_freeze=False)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=None, model_root=root, golden_rows=64)
    model_id = report["arms"]["LONG_A"]["model_id"]
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_UNVERIFIABLE"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)


def test_tampered_freeze_bytes_mismatch(tmp_path: Path, root: Path):
    repo, freeze_path, bundle_path, freeze = _build_repo(tmp_path)
    train_frame = _train_frame(n=300, seed=1)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=train_frame, model_root=root, golden_rows=64)
    model_id = report["arms"]["LONG_A"]["model_id"]
    freeze_path.write_text(freeze_path.read_text(encoding="utf-8") + "   ", encoding="utf-8")  # tamper after commit
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_MISMATCH"):
        ms.authenticate_model(model_id, model_root=root, repo_root=repo)


def test_bundle_arm_fit_identity_disagrees_with_freeze_fails_only_that_arm(tmp_path: Path, root: Path):
    repo, freeze_path, bundle_path, freeze = _build_repo(
        tmp_path, arm_fit_identity_override={"LONG_A": hashlib.sha256(b"tampered").hexdigest()})
    train_frame = _train_frame(n=300, seed=1)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=train_frame, model_root=root, golden_rows=64)
    assert report["migrated"] == 1 and len(report["failed"]) == 1
    assert report["failed"][0]["arm"] == "LONG_A"
    assert "BUNDLE_FREEZE_FIT_IDENTITY_MISMATCH" in report["failed"][0]["error"]
    assert "LONG_B" in report["arms"]


def test_model_id_distinct_from_v2_lineage_formula(tmp_path: Path, root: Path):
    """The legacy_v1_train_freeze id can never collide with a v2-fit id for the same
    bytes -- it hashes a different tuple (study_id, arm, fit_identity, freeze_sha256)."""
    repo, freeze_path, bundle_path, freeze = _build_repo(tmp_path)
    train_frame = _train_frame(n=300, seed=1)
    report = migrate_train_freeze_bundle(study_id="redteam_model_c", freeze_path=freeze_path,
                                         bundle_path=bundle_path, repo_root=repo,
                                         train_frame=train_frame, model_root=root, golden_rows=64)
    model_id = report["arms"]["LONG_A"]["model_id"]
    manifest = ms.read_manifest(model_id, root)
    v2_id = ms._recompute_v2_lineage_sha256(manifest)
    assert v2_id != model_id

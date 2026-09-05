"""Independent authentication of every representation a legacy record names.

A committed v1 registry record may name SEVERAL representations of one estimator, each with
its own recorded hash. They do not necessarily all still verify: the 180s parent's native
boosters were re-exported after its records were written, so `native_booster_sha256` matches
no byte state that exists, while `artifact_sha256` still matches its joblib exactly.

The migrator used to treat the native booster as authoritative WHENEVER the record named one,
so a stale secondary hash refused a perfectly sound model. The only ways out of that were bad:
rewrite the hash inside a closed study, or mint a second model identity. Neither is necessary
-- the record already contains a representation that authenticates.

Each representation is now verified independently, the first that verifies is accepted, and
BOTH the acceptance and every rejection (with expected vs observed) are persisted, so a
rejected representation is visible in the store rather than silently skipped.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from research_workflow import model_store as ms
from research_workflow.model_migration import _select_verified_representation, migrate_legacy_records

FEATURES = ["f0", "f1", "f2"]


class _Est:
    """Minimal picklable estimator: deterministic, no third-party model format needed."""

    def __init__(self, bias: float = 0.25):
        self.bias = bias

    def predict_proba(self, X):
        p = np.clip(self.bias + 0.1 * np.asarray(X, dtype=float).sum(axis=1) / max(len(FEATURES), 1), 0.01, 0.99)
        return np.column_stack([1 - p, p])


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _study_bytes(tmp_path: Path, *, arm: str = "C", booster_hash: str = "stale"):
    """A legacy study tree naming BOTH representations; the booster hash is stale by default."""
    studies = tmp_path / "studies"
    models = studies / "parent_study" / "artifacts" / "models"
    models.mkdir(parents=True)
    mid = "a" * 64
    jb = models / f"{mid}.joblib"
    joblib.dump({arm: {"estimator": _Est(), "fit_identity_sha256": "f" * 64}}, jb)
    bt = models / f"{mid}.booster.txt"
    bt.write_text("tree\nversion=v4\n(not a real booster; only its bytes matter here)\n", encoding="utf-8")
    rec = {
        "model_id": mid, "study_id": "parent_study", "model_role": arm, "model_family": "lightgbm",
        "artifact_path": f"parent_study/artifacts/models/{mid}.joblib", "artifact_sha256": _sha(jb),
        "native_booster_path": f"parent_study/artifacts/models/{mid}.booster.txt",
        "native_booster_sha256": ("0" * 64) if booster_hash == "stale" else _sha(bt),
        "ordered_model_inputs": FEATURES, "feature_contract_identity": "c" * 64,
        "preprocessing_identity": {"identity": "identity", "kind": "identity"},
        "target_identity": "t" * 64, "training_years": [2021], "hyperparameters": {},
        "runtime_identity_sha256": "r" * 64, "scientific_status": "UNASSESSED", "schema_version": 1,
    }
    reg = studies / "model_registry"
    reg.mkdir(parents=True)
    (reg / f"{mid}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return studies, reg, mid, rec


def _frame(n: int = 300):
    rng = np.random.default_rng(0)
    return pd.DataFrame(rng.normal(size=(n, len(FEATURES))), columns=FEATURES)


# --------------------------------------------------------------------------- selection
def test_a_stale_native_hash_falls_through_to_the_verified_joblib(tmp_path):
    studies, _, _, rec = _study_bytes(tmp_path)
    path, fmt, ev = _select_verified_representation(rec, studies)
    assert ev["accepted_representation"] == "joblib_artifact"
    assert fmt == "sklearn_pickle" and path.suffix == ".joblib"
    rejected = {r["representation"]: r for r in ev["rejected"]}
    assert rejected["native_booster"]["reason"] == "RECORDED_HASH_MISMATCH"
    assert rejected["native_booster"]["expected_sha256"] == "0" * 64
    assert rejected["native_booster"]["observed_sha256"] != "0" * 64


def test_the_native_representation_is_preferred_when_it_verifies(tmp_path):
    """Preference order is native-first; it is only overridden by an actual failure."""
    studies, _, _, rec = _study_bytes(tmp_path, booster_hash="fresh")
    _, fmt, ev = _select_verified_representation(rec, studies)
    assert ev["accepted_representation"] == "native_booster" and ev["rejected"] == [] and fmt is None


def test_migration_refuses_when_no_representation_verifies(tmp_path):
    studies, _, _, rec = _study_bytes(tmp_path)
    rec["artifact_sha256"] = "9" * 64                       # now BOTH are stale
    with pytest.raises(ms.ModelStoreError, match="LEGACY_NO_REPRESENTATION_VERIFIES"):
        _select_verified_representation(rec, studies)


def test_missing_bytes_are_reported_as_such_not_as_a_hash_mismatch(tmp_path):
    studies, _, mid, rec = _study_bytes(tmp_path)
    (studies / "parent_study" / "artifacts" / "models" / f"{mid}.booster.txt").unlink()
    _, _, ev = _select_verified_representation(rec, studies)
    assert {r["representation"]: r["reason"] for r in ev["rejected"]} == {"native_booster": "BYTES_MISSING"}


def test_a_record_naming_no_representation_is_refused(tmp_path):
    studies, _, _, rec = _study_bytes(tmp_path)
    rec.pop("artifact_path"); rec.pop("native_booster_path")
    with pytest.raises(ms.ModelStoreError, match="LEGACY_RECORD_NAMES_NO_REPRESENTATION"):
        _select_verified_representation(rec, studies)


# --------------------------------------------------------------------------- end to end
def test_migrated_joblib_representation_authenticates_and_scores(tmp_path):
    studies, reg, mid, _ = _study_bytes(tmp_path)
    store = tmp_path / "store"
    report = migrate_legacy_records(study_id="parent_study", registry_root=reg, bytes_root=studies,
                                    train_frame=_frame(), model_root=store,
                                    selected_ids={mid}, exports=())
    assert report["failed"] == [] and report["migrated"] == 1

    manifest = ms.read_manifest(mid, store)
    # canonical bytes are the RECORDED bytes, untouched -- that is what authenticates them
    assert manifest["canonical"]["format"] == "sklearn_pickle"
    assert manifest["canonical"]["byte_sha256"] == manifest["legacy_registry_record"]["artifact_sha256"]
    ra = manifest["legacy_registry_record"]["representation_authentication"]
    assert ra["accepted_representation"] == "joblib_artifact"
    assert [r["representation"] for r in ra["rejected"]] == ["native_booster"]

    # The accepted representation reproduces the golden frame EXACTLY -- the required result.
    golden = ms.validate_golden(mid, store)
    assert golden["status"] == "PASS" and golden["max_abs_diff"] == 0.0

    scored = ms.score(mid, _frame(5), model_root=store)
    assert len(scored) == 5 and np.isfinite(scored).all()


def test_a_synthetic_record_cannot_authenticate_because_it_is_not_committed(tmp_path):
    """Full authentication additionally requires the legacy record to be committed at git HEAD.
    A fixture record is untracked by construction, so it MUST fail closed here -- the real
    committed parent records are what exercise the authenticated path end to end."""
    studies, reg, mid, _ = _study_bytes(tmp_path)
    store = tmp_path / "store"
    migrate_legacy_records(study_id="parent_study", registry_root=reg, bytes_root=studies,
                           train_frame=_frame(), model_root=store, selected_ids={mid}, exports=())
    with pytest.raises(ms.ModelStoreError, match="MODEL_IDENTITY_UNVERIFIABLE"):
        ms.authenticate_model(mid, model_root=store, repo_root=tmp_path)


def test_the_bundle_arm_is_recorded_not_guessed(tmp_path):
    """The legacy joblib is an ARM BUNDLE. Unwrapping it by a recorded arm name is what lets
    the stored bytes stay identical to the bytes the committed record hashes."""
    studies, reg, mid, _ = _study_bytes(tmp_path, arm="C")
    store = tmp_path / "store"
    migrate_legacy_records(study_id="parent_study", registry_root=reg, bytes_root=studies,
                           train_frame=_frame(), model_root=store, selected_ids={mid}, exports=())
    manifest = ms.read_manifest(mid, store)
    assert manifest["legacy_registry_record"]["canonical_bundle_arm"] == "C"

    # A manifest naming an arm the bundle does not contain must fail closed, never guess.
    bad = dict(manifest)
    bad["legacy_registry_record"] = {**manifest["legacy_registry_record"], "canonical_bundle_arm": "NOPE"}
    bad["lineage"] = {**manifest["lineage"], "target_arm": "NOPE"}
    with pytest.raises(ms.ModelStoreError, match="CANONICAL_BUNDLE_ARM_ABSENT"):
        ms.load_canonical(bad, ms.model_dir(mid, store))

"""Red-team packet A / A3 -- legacy runtime must not accept a spoofed marker/seal file.

``research_workflow.policy.historical_authority`` used to grant v1 execution authority on
bare marker-FILE EXISTENCE. That let an attacker plant an empty or copied seal
(``mkdir studies/x && touch studies/x/artifacts/preexec_audit_seal.json``) and gain old
runtime execution. ``verify_historical_authority`` / ``assert_old_runtime_allowed`` now
require authenticated provenance: git-tracked artifacts, a self-consistent seal body, and
agreement with the committed frozen execution manifest.

These tests use a REAL tmp git repository (``git init`` + commit) so "tracked in git" is
genuinely exercised rather than assumed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from research_workflow.policy import OldRuntimePolicyError, assert_old_runtime_allowed, verify_historical_authority
from research_workflow.seal import seal_body_hash

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    return repo


def _valid_seal_and_manifest(study_id: str):
    """A minimal, internally self-consistent seal/manifest pair."""
    file_hashes = {"repo/some_governed_module.py": hashlib.sha256(b"module body").hexdigest()}
    composite = seal_body_hash({"file_hashes": file_hashes})
    seal = {
        "seal_id": f"preexec_seal_{study_id}_{composite[:16]}",
        "study_name": study_id,
        "seal_status": "LOCKED",
        "composite_seal_hash": composite,
        "file_hashes": file_hashes,
    }
    manifest = {"schema_version": 1, "frozen_execution_composite_sha256": composite}
    return seal, manifest


def _write_study(repo: Path, study_id: str, seal, manifest, *, commit: bool = True) -> Path:
    study = repo / "studies" / study_id
    (study / "artifacts").mkdir(parents=True, exist_ok=True)
    (study / "audit").mkdir(parents=True, exist_ok=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(seal), encoding="utf-8")
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if commit:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"add {study_id}")
    return study


# ---------------------------------------------------------------------------
# named attacks
# ---------------------------------------------------------------------------

def test_empty_fake_seal_rejected(tmp_path):
    repo = _init_repo(tmp_path)
    study = repo / "studies" / "x"
    (study / "artifacts").mkdir(parents=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "spoof")
    with pytest.raises(OldRuntimePolicyError):
        verify_historical_authority(study, repo_root=repo)


def test_copied_foreign_seal_rejected(tmp_path):
    """A valid seal belonging to study A, placed inside study B's directory."""
    repo = _init_repo(tmp_path)
    seal_a, manifest_a = _valid_seal_and_manifest("study_a")
    _write_study(repo, "study_a", seal_a, manifest_a)
    # Study B gets study A's seal verbatim (still says study_name=study_a) + its own manifest
    # recomputed to match (an attacker who controls the manifest too still cannot fix identity).
    _write_study(repo, "study_b", seal_a, manifest_a)
    with pytest.raises(OldRuntimePolicyError, match="HISTORICAL_SEAL_STUDY_MISMATCH"):
        verify_historical_authority(repo / "studies" / "study_b", repo_root=repo)


def test_stale_mismatched_seal_rejected(tmp_path):
    repo = _init_repo(tmp_path)
    seal, manifest = _valid_seal_and_manifest("study_c")
    manifest["frozen_execution_composite_sha256"] = "0" * 64  # diverged from the seal
    _write_study(repo, "study_c", seal, manifest)
    with pytest.raises(OldRuntimePolicyError, match="HISTORICAL_SEAL_STALE"):
        verify_historical_authority(repo / "studies" / "study_c", repo_root=repo)


def test_untracked_study_rejected(tmp_path):
    repo = _init_repo(tmp_path)
    seal, manifest = _valid_seal_and_manifest("study_d")
    _write_study(repo, "study_d", seal, manifest, commit=False)  # never `git add`/commit
    with pytest.raises(OldRuntimePolicyError, match="HISTORICAL_AUTHORITY_UNTRACKED"):
        verify_historical_authority(repo / "studies" / "study_d", repo_root=repo)


def test_legitimate_historical_study_passes():
    """Prove against a real committed historical study in THIS repo (read-only)."""
    candidates = subprocess.run(
        ["git", "ls-files", "studies/*/artifacts/preexec_audit_seal.json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert candidates, "expected at least one committed historical seal in this repo"
    picked = None
    for rel in candidates:
        study_dir = REPO_ROOT / Path(rel).parents[1]
        if (study_dir / "study.yaml").is_file() and not (study_dir / "compiled_plan.json").is_file():
            try:
                evidence = verify_historical_authority(study_dir, repo_root=REPO_ROOT)
            except OldRuntimePolicyError:
                continue
            picked = (study_dir, evidence)
            break
    assert picked is not None, "no committed v1 study passed authentication"
    study_dir, evidence = picked
    assert evidence["study_id"] == study_dir.name
    assert evidence["git_tracked"] is True
    assert evidence["seal_composite"] == evidence["manifest_composite"]
    result = assert_old_runtime_allowed(study_dir, repo_root=REPO_ROOT)
    assert result["platform"] == "v1_historical"


# ---------------------------------------------------------------------------
# adjacent bypass attempts
# ---------------------------------------------------------------------------

def test_seal_with_study_id_edited_rejected(tmp_path):
    """Seal body edited to claim a different study_id -> body hash still matches (only the
    identity field moved) but directory-identity match must still fail."""
    repo = _init_repo(tmp_path)
    seal, manifest = _valid_seal_and_manifest("study_e")
    seal["study_name"] = "study_e_renamed"
    _write_study(repo, "study_e", seal, manifest)
    with pytest.raises(OldRuntimePolicyError, match="HISTORICAL_SEAL_STUDY_MISMATCH"):
        verify_historical_authority(repo / "studies" / "study_e", repo_root=repo)


def test_seal_file_hashes_tampered_rejected(tmp_path):
    """file_hashes edited after composite_seal_hash was computed -> self-consistency fails."""
    repo = _init_repo(tmp_path)
    seal, manifest = _valid_seal_and_manifest("study_f")
    seal["file_hashes"]["repo/some_governed_module.py"] = "f" * 64
    _write_study(repo, "study_f", seal, manifest)
    with pytest.raises(OldRuntimePolicyError, match="HISTORICAL_SEAL_INVALID"):
        verify_historical_authority(repo / "studies" / "study_f", repo_root=repo)


def test_train_freeze_only_marker_without_seal_rejected(tmp_path):
    """A train_experiment_freeze.json marker alone (no valid seal) must not grant authority."""
    repo = _init_repo(tmp_path)
    study = repo / "studies" / "study_g"
    (study / "artifacts").mkdir(parents=True)
    (study / "artifacts" / "train_experiment_freeze.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "marker only")
    with pytest.raises(OldRuntimePolicyError):
        verify_historical_authority(study, repo_root=repo)


def test_assert_old_runtime_allowed_rejects_untracked_via_public_entrypoint(tmp_path):
    repo = _init_repo(tmp_path)
    study = repo / "studies" / "study_h"
    (study / "study.yaml").parent.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text("study:\n  id: study_h\n  type: flip_prediction\n", encoding="utf-8")
    seal, manifest = _valid_seal_and_manifest("study_h")
    _write_study(repo, "study_h", seal, manifest, commit=False)
    with pytest.raises(OldRuntimePolicyError):
        assert_old_runtime_allowed(study, repo_root=repo)

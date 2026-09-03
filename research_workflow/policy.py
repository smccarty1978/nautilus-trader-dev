"""Repository research policy constants and their enforcement helpers.

OLD_RUNTIME_POLICY = LEGACY_ONLY_FOR_NEW_RESEARCH (recorded 2026-09-02 at tag
baseline/2026-09-platform-v2-proven):

* no new study may target the old runtime (``research_workflow.generic_collector`` and the
  v1 ``study.yaml`` grammar);
* historical sealed studies keep their historical execution authority at their own commit;
* historical runtime implementations are not deleted and historical seals are never rewritten;
* no compatibility migration is required or performed.

Historical execution authority is granted on AUTHENTICATED provenance only (red-team packet
A3), never on bare marker-file existence: a study directory copied, hand-crafted, or
untracked can otherwise "borrow" another study's execution authority by planting an empty
or copied seal file. ``verify_historical_authority`` requires (1) the seal and the frozen
execution manifest are tracked in git at HEAD -- i.e. genuinely committed history, not a
disposable/untracked artifact; (2) the seal parses, is non-empty, and its recorded study
identity equals the directory name; (3) the seal's own ``composite_seal_hash`` is
self-consistent with its recorded ``file_hashes`` (``seal_body_hash``); (4) that composite
equals the composite recorded in the committed ``audit/frozen_execution_manifest.json``;
(5) if a ``study_closure.json`` is present, it must authenticate via
``research_workflow.study_closure.load_study_closure``.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

OLD_RUNTIME_POLICY = "LEGACY_ONLY_FOR_NEW_RESEARCH"
POLICY_RECORDED_AT = "baseline/2026-09-platform-v2-proven"

# A v1 study with any of these MAY hold historical execution authority; existence alone is
# only a signal that authenticity should be checked (see verify_historical_authority), not
# authority itself.
_HISTORICAL_AUTHORITY_MARKERS = (
    "artifacts/preexec_audit_seal.json",
    "audit/frozen_execution_manifest.json",
    "artifacts/study_closure.json",
    "artifacts/train_experiment_freeze.json",
)


class OldRuntimePolicyError(RuntimeError):
    pass


def historical_authority(study_dir: Path) -> list[str]:
    """Marker files present on disk. Existence only -- NOT a grant of authority.

    Kept for reporting/back-compat; ``verify_historical_authority`` is the actual gate.
    """
    study_dir = Path(study_dir)
    return [m for m in _HISTORICAL_AUTHORITY_MARKERS if (study_dir / m).is_file()]


def _git_tracked(repo_root: Path, rel_posix_path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_posix_path],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def verify_historical_authority(study_dir: Path, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Authenticate a v1 study's historical execution authority. Raises OldRuntimePolicyError.

    Returns an evidence dict on success:
    ``{study_id, seal_sha256, seal_composite, manifest_composite, git_tracked, markers}``.
    """
    import hashlib

    study_dir = Path(study_dir).resolve()
    repo_root = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    markers = historical_authority(study_dir)

    seal_path = study_dir / "artifacts" / "preexec_audit_seal.json"
    manifest_path = study_dir / "audit" / "frozen_execution_manifest.json"

    try:
        rel_seal = seal_path.relative_to(repo_root).as_posix()
        rel_manifest = manifest_path.relative_to(repo_root).as_posix()
    except ValueError:
        raise OldRuntimePolicyError(
            f"HISTORICAL_AUTHORITY_UNTRACKED: {study_dir} is not inside repo root {repo_root}"
        )

    if not seal_path.is_file() or not _git_tracked(repo_root, rel_seal):
        raise OldRuntimePolicyError(
            f"HISTORICAL_AUTHORITY_UNTRACKED: {rel_seal} is missing or not committed to git; "
            f"an untracked/spoofed seal cannot grant historical execution authority"
        )
    if not manifest_path.is_file() or not _git_tracked(repo_root, rel_manifest):
        raise OldRuntimePolicyError(
            f"HISTORICAL_AUTHORITY_UNTRACKED: {rel_manifest} is missing or not committed to git"
        )

    try:
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: cannot parse {rel_seal}: {exc}")
    if not isinstance(seal, dict) or not seal:
        raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: {rel_seal} is empty")
    study_name = seal.get("study_name") or seal.get("study_id")
    composite_seal_hash = seal.get("composite_seal_hash")
    file_hashes = seal.get("file_hashes")
    if not study_name or not composite_seal_hash or not isinstance(file_hashes, dict) or not file_hashes:
        raise OldRuntimePolicyError(
            f"HISTORICAL_SEAL_INVALID: {rel_seal} missing study identity, composite_seal_hash, or file_hashes"
        )
    if study_name != study_dir.name:
        raise OldRuntimePolicyError(
            f"HISTORICAL_SEAL_STUDY_MISMATCH: seal identity {study_name!r} != directory {study_dir.name!r}"
        )

    from research_workflow.seal import seal_body_hash
    recomputed = seal_body_hash(seal)
    if recomputed != composite_seal_hash:
        raise OldRuntimePolicyError(
            f"HISTORICAL_SEAL_INVALID: {rel_seal} composite_seal_hash does not match its own "
            f"recorded file_hashes (recomputed {recomputed[:12]} != recorded {str(composite_seal_hash)[:12]})"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: cannot parse {rel_manifest}: {exc}")
    manifest_composite = manifest.get("frozen_execution_composite_sha256") if isinstance(manifest, dict) else None
    if not manifest_composite or manifest_composite != composite_seal_hash:
        raise OldRuntimePolicyError(
            f"HISTORICAL_SEAL_STALE: seal composite {str(composite_seal_hash)[:12]} != frozen manifest "
            f"composite {str(manifest_composite)[:12]} ({rel_manifest})"
        )

    closure_path = study_dir / "artifacts" / "study_closure.json"
    if closure_path.is_file():
        rel_closure = closure_path.relative_to(repo_root).as_posix()
        if not _git_tracked(repo_root, rel_closure):
            raise OldRuntimePolicyError(
                f"HISTORICAL_AUTHORITY_UNTRACKED: {rel_closure} present but not committed to git"
            )
        from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
        try:
            load_study_closure(study_dir)
        except StudyClosureInvalid as exc:
            raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: study_closure.json failed authentication: {exc}")

    return {
        "study_id": study_dir.name,
        "seal_sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
        "seal_composite": composite_seal_hash,
        "manifest_composite": manifest_composite,
        "git_tracked": True,
        "markers": markers,
    }


def assert_old_runtime_allowed(study_dir: Path, repo_root: Optional[Path] = None) -> dict:
    """Raise unless ``study_dir`` is a Platform-v2 study or a v1 study with AUTHENTICATED
    historical execution authority (see ``verify_historical_authority``)."""
    from research_workflow.lifecycle_v2 import is_v2_study
    study_dir = Path(study_dir)
    if is_v2_study(study_dir):
        return {"platform": "v2", "policy": OLD_RUNTIME_POLICY}
    markers = historical_authority(study_dir)
    if not markers:
        raise OldRuntimePolicyError(
            f"OLD_RUNTIME_LEGACY_ONLY: {study_dir.name} is a v1 study without historical execution authority; "
            f"policy {OLD_RUNTIME_POLICY} ({POLICY_RECORDED_AT}) -- new research must be a Platform V2 study "
            f"(`python scripts/research.py study new <id>`; see WORKFLOW.md)")
    evidence = verify_historical_authority(study_dir, repo_root)
    return {"platform": "v1_historical", "policy": OLD_RUNTIME_POLICY, "authority_markers": markers, **evidence}


__all__ = ["OLD_RUNTIME_POLICY", "POLICY_RECORDED_AT", "OldRuntimePolicyError", "assert_old_runtime_allowed",
           "historical_authority", "verify_historical_authority"]

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

# ZERO_STUDY_PYTHON (red-team packet F2): a normal Platform-V2 study commits no executable
# Python at all -- the six-kind declarative grammar is the whole surface. Sanctioning an
# exception is a PLATFORM code change (an entry here), never a study-side declaration;
# study_id -> reason.
STUDY_PYTHON_EXCEPTIONS: Dict[str, str] = {}

_STUDY_PYTHON_IGNORED_DIRS = ("_work", "runs")


def scan_study_python(study_dir: Path) -> List[str]:
    """Every ``*.py``/``*.pyw``/``*.ipynb`` (case-insensitive extension) committed or
    untracked under ``study_dir``, except ``_work/`` and ``runs/``. Returns paths relative
    to ``study_dir`` as posix strings, sorted."""
    study_dir = Path(study_dir).resolve()
    found: set[str] = set()
    if study_dir.is_dir():
        for path in study_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(study_dir)
            if rel.parts and rel.parts[0] in _STUDY_PYTHON_IGNORED_DIRS:
                continue
            if path.suffix.lower() in (".py", ".pyw", ".ipynb"):
                found.add(rel.as_posix())
    return sorted(found)


class OldRuntimePolicyError(RuntimeError):
    pass


def historical_authority(study_dir: Path) -> list[str]:
    """Marker files present on disk. Existence only -- NOT a grant of authority.

    Kept for reporting/back-compat; ``verify_historical_authority`` is the actual gate.
    """
    study_dir = Path(study_dir)
    return [m for m in _HISTORICAL_AUTHORITY_MARKERS if (study_dir / m).is_file()]


def _git_tracked(repo_root: Path, rel_posix_path: str) -> bool:
    """Index-membership only (``git ls-files``). NOT a committed-authority check: a file
    that was ``git add``ed but never committed passes this. Kept only for callers that
    genuinely want index membership; every authority check in this module uses
    ``committed_blob``/``is_committed_identical`` instead (red-team finding C-A)."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_posix_path],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _head_identity(repo_root: Path) -> Dict[str, Optional[str]]:
    """The commit and branch a ``committed_blob``/``is_committed_identical`` check just
    resolved ``HEAD:<path>`` against. WARN-2: the trust boundary of every historical-authority
    grant in this module is *the checked-out repository history at this HEAD* -- a forged
    commit reached via detached HEAD, a linked ``git worktree``, or a re-pointed branch tip is
    indistinguishable from a reviewed commit unless the evidence names which commit vouched;
    this is recorded for audit, not enforced (a further ancestor-of-upstream check is out of
    scope here)."""
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True)
        head_sha = rev.stdout.strip() if rev.returncode == 0 else None
    except OSError:
        head_sha = None
    try:
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo_root), capture_output=True, text=True)
        branch = br.stdout.strip() if br.returncode == 0 else None
    except OSError:
        branch = None
    return {"head_sha": head_sha or None, "branch": branch or "HEAD"}


def committed_blob(repo_root: Path, rel_posix_path: str) -> Optional[bytes]:
    """The bytes of ``rel_posix_path`` as committed at HEAD, or ``None`` if that path does
    not exist at HEAD (untracked, staged-but-uncommitted, deleted, or committed only on a
    different branch/ref). Never reads the working tree."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"HEAD:{rel_posix_path}"],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return None
    sha = r.stdout.strip()
    if r.returncode != 0 or not sha:
        return None
    try:
        r2 = subprocess.run(
            ["git", "cat-file", "blob", sha],
            cwd=str(repo_root), capture_output=True,
        )
    except OSError:
        return None
    if r2.returncode != 0:
        return None
    return r2.stdout


def head_blob_git_sha(repo_root: Path, rel_posix_path: str) -> Optional[str]:
    """The git blob object id (SHA-1) of ``rel_posix_path`` at HEAD, or ``None`` if not
    committed there. Recorded alongside a ``sha256`` of the blob's bytes purely for audit
    traceability (which commit's object vouched) -- never used as the identity hash itself."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"HEAD:{rel_posix_path}"],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def is_committed_identical(repo_root: Path, path: Path) -> bool:
    """True iff ``path`` exists at HEAD in ``repo_root`` AND the current working-tree bytes
    are byte-identical to that HEAD blob. False for untracked, staged-only, deleted-at-HEAD,
    or committed-then-rewritten-in-the-worktree paths."""
    repo_root = Path(repo_root).resolve()
    path = Path(path)
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        return False
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"HEAD:{rel}"],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return False
    head_sha = head.stdout.strip()
    if head.returncode != 0 or not head_sha:
        return False
    if not path.is_file():
        return False
    try:
        wt = subprocess.run(
            ["git", "hash-object", str(path)],
            cwd=str(repo_root), capture_output=True, text=True,
        )
    except OSError:
        return False
    if wt.returncode != 0:
        return False
    return wt.stdout.strip() == head_sha


def require_committed_identical(repo_root: Path, path: Path, *, kind: str) -> bytes:
    """Raise ``OldRuntimePolicyError`` unless ``path`` is committed at HEAD *and* the
    working-tree bytes are unchanged since that commit; on success return the HEAD blob
    bytes (the authoritative bytes -- callers must parse these, not the working-tree file)."""
    repo_root = Path(repo_root).resolve()
    path = Path(path)
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        raise OldRuntimePolicyError(f"HISTORICAL_AUTHORITY_UNTRACKED: {path} is not inside repo root {repo_root}")
    blob = committed_blob(repo_root, rel)
    if blob is None:
        raise OldRuntimePolicyError(
            f"HISTORICAL_AUTHORITY_UNTRACKED: {rel} is missing or not committed to git at HEAD; "
            f"an untracked/staged-only/deleted-at-HEAD {kind} cannot grant historical execution authority"
        )
    if not is_committed_identical(repo_root, path):
        raise OldRuntimePolicyError(
            f"HISTORICAL_AUTHORITY_MODIFIED_IN_WORKTREE: {rel} was committed at HEAD but the working-tree "
            f"bytes of this {kind} differ from that commit; a committed record rewritten in the working "
            f"tree cannot grant historical execution authority"
        )
    return blob


def verify_historical_authority(study_dir: Path, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Authenticate a v1 study's historical execution authority. Raises OldRuntimePolicyError.

    Returns an evidence dict on success:
    ``{study_id, seal_sha256, seal_composite, manifest_composite, git_tracked, markers,
    head_sha, branch}``. Trust boundary (WARN-2): every check in this function resolves
    ``HEAD:<path>`` in *this checkout's* current history -- ``head_sha``/``branch`` name the
    exact commit that vouched, so a downstream reviewer can tell which commit granted it.
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

    # Authority binds to the HEAD blob, never to the index or the working tree (C-A): a
    # staged-but-uncommitted seal, or a genuinely committed seal rewritten in the worktree
    # after the commit, both fail here.
    seal_blob = require_committed_identical(repo_root, seal_path, kind="preexec audit seal")
    manifest_blob = require_committed_identical(repo_root, manifest_path, kind="frozen execution manifest")

    try:
        seal = json.loads(seal_blob.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
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
        manifest = json.loads(manifest_blob.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: cannot parse {rel_manifest}: {exc}")
    manifest_composite = manifest.get("frozen_execution_composite_sha256") if isinstance(manifest, dict) else None
    if not manifest_composite or manifest_composite != composite_seal_hash:
        raise OldRuntimePolicyError(
            f"HISTORICAL_SEAL_STALE: seal composite {str(composite_seal_hash)[:12]} != frozen manifest "
            f"composite {str(manifest_composite)[:12]} ({rel_manifest})"
        )

    closure_path = study_dir / "artifacts" / "study_closure.json"
    if closure_path.is_file():
        require_committed_identical(repo_root, closure_path, kind="study closure")
        from research_workflow.study_closure import StudyClosureInvalid, load_study_closure
        try:
            load_study_closure(study_dir)
        except StudyClosureInvalid as exc:
            raise OldRuntimePolicyError(f"HISTORICAL_SEAL_INVALID: study_closure.json failed authentication: {exc}")

    return {
        "study_id": study_dir.name,
        "seal_sha256": hashlib.sha256(seal_blob).hexdigest(),
        "seal_composite": composite_seal_hash,
        "manifest_composite": manifest_composite,
        "git_tracked": True,
        "markers": markers,
        **_head_identity(repo_root),
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
           "historical_authority", "verify_historical_authority", "STUDY_PYTHON_EXCEPTIONS", "scan_study_python",
           "committed_blob", "is_committed_identical", "require_committed_identical"]

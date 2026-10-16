"""Write-once OOS access latch: the first opening of the held-out period binds the study's evaluation identity.

Before this latch, a ``study.yaml`` edited after OOS had been opened re-sealed, re-froze, RE-COLLECTED the
held-out years and re-analysed them under the new rules (HV1 synthetic proof, N2: loosened thresholds flipped
the class to VALIDATED and overwrote the first-access OOS manifests). Nothing recorded that OOS had been seen.

The latch is two write-once artifacts in ``artifacts/`` (tracked with the study):

``oos_access_record.json``      written atomically (O_CREAT|O_EXCL) BEFORE the first held-out bar is read; it
                                carries the identity the opening was authorized under (plan, analysis spec,
                                execution composite, seal, authorization and year roles, dataset, TRAIN freeze
                                binding). Every later seal / freeze / oos / analyze compares the CURRENT identity
                                to it; any difference is refused (``OOS_IDENTITY_CONFLICT``). There is no reopen
                                path: an amended evaluation is a new study.
``oos_access_completion.json``  written once after the held-out partitions were collected and reconciled; it
                                pins their bytes. A later ``oos``/``analyze`` whose partitions differ (replaced,
                                deleted, re-collected) is refused (``OOS_EVIDENCE_ALTERED``) -- the held-out
                                period is never collected twice.

Refusals are fail-closed, typed (``code``) and also written to ``_work/controller/oos_access_refusal.json``.
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

RECORD_NAME = "oos_access_record.json"
COMPLETION_NAME = "oos_access_completion.json"
REFUSAL_NAME = "oos_access_refusal.json"
SCHEMA_VERSION = 1


class OOSAccessRefused(RuntimeError):
    """A typed, fail-closed refusal of an OOS-touching stage."""

    def __init__(self, code: str, detail: str, conflicts: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.conflicts = list(conflicts or [])


def refuse(code: str, detail: str) -> None:
    raise OOSAccessRefused(code, detail)


def _sha(obj: Any) -> str:
    from research.analysis.identity import canonical_sha256
    return canonical_sha256(obj)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_write_once(path: Path, what: str) -> Optional[Dict[str, Any]]:
    """None if absent; the verified payload if present; a refusal if present but unreadable or tampered."""
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OOSAccessRefused("OOS_ACCESS_RECORD_CORRUPT", f"{what} {path.name} is unreadable ({type(exc).__name__}); "
                               "the held-out period stays closed") from exc
    if not isinstance(rec, dict) or rec.get("record_sha256") != _sha({k: v for k, v in rec.items() if k != "record_sha256"}):
        raise OOSAccessRefused("OOS_ACCESS_RECORD_CORRUPT", f"{what} {path.name} does not hash to its recorded record_sha256")
    return rec


def _create_once(path: Path, body: Mapping[str, Any]) -> bool:
    """Atomic create-if-absent. True if this call created the file, False if it already existed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(body)
    payload["record_sha256"] = _sha(payload)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write((json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return True


def read_record(artifacts: Path) -> Optional[Dict[str, Any]]:
    return _read_write_once(Path(artifacts) / RECORD_NAME, "OOS access record")


def read_completion(artifacts: Path) -> Optional[Dict[str, Any]]:
    return _read_write_once(Path(artifacts) / COMPLETION_NAME, "OOS completion record")


def _conflicts(recorded: Mapping[str, Any], current: Mapping[str, Any], *, ignore: tuple = ()) -> List[Dict[str, Any]]:
    keys = sorted((set(recorded) | set(current)) - set(ignore))
    return [{"field": k, "recorded": recorded.get(k), "current": current.get(k)}
            for k in keys if json.dumps(recorded.get(k), sort_keys=True, default=str) != json.dumps(current.get(k), sort_keys=True, default=str)]


def check_identity(artifacts: Path, identity: Mapping[str, Any], *, stage: str, ignore: tuple = ()) -> Optional[Dict[str, Any]]:
    """Refuse when OOS has been opened under a different identity. Returns the record (None if never opened)."""
    rec = read_record(artifacts)
    if rec is None:
        return None
    diff = _conflicts(rec["identity"], identity, ignore=ignore)
    if diff:
        raise OOSAccessRefused("OOS_IDENTITY_CONFLICT",
                               f"{stage} refused: the held-out period was opened at {rec.get('opened_at_utc')} under a different "
                               f"evaluation identity ({', '.join(d['field'] for d in diff)} changed); an amended evaluation needs a new study",
                               diff)
    return rec


def open_access(artifacts: Path, identity: Mapping[str, Any], *, held_out_evidence_present: bool) -> Dict[str, Any]:
    """Record the first opening (atomically) or verify a resumed one. Call BEFORE reading any held-out bar."""
    artifacts = Path(artifacts)
    rec = check_identity(artifacts, identity, stage="oos")
    if rec is not None:
        return {**rec, "opening": "RESUMED_UNDER_RECORDED_IDENTITY"}
    if held_out_evidence_present:
        raise OOSAccessRefused("OOS_ACCESS_RECORD_MISSING",
                               "held-out partitions exist but no OOS access record does; the record was deleted or the "
                               "partitions were not produced by a recorded opening")
    body = {"schema_version": SCHEMA_VERSION, "identity": dict(identity), "identity_sha256": _sha(dict(identity)),
            "opened_at_utc": _now(), "opened_by": {"pid": os.getpid(), "host": socket.gethostname()}}
    if not _create_once(artifacts / RECORD_NAME, body):
        # Lost a race with a concurrent opener: its record is authoritative and must agree with ours.
        rec = check_identity(artifacts, identity, stage="oos")
        return {**(rec or {}), "opening": "RESUMED_UNDER_RECORDED_IDENTITY"}
    return {**read_record(artifacts), "opening": "FIRST_OPENING"}


def record_completion(artifacts: Path, identity_sha256: str, partitions: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Pin the held-out evidence once; a different set of bytes is never accepted as a replacement."""
    artifacts = Path(artifacts)
    body = {"schema_version": SCHEMA_VERSION, "identity_sha256": identity_sha256,
            "partitions": {str(k): dict(v) for k, v in sorted(partitions.items())}, "completed_at_utc": _now()}
    if not _create_once(artifacts / COMPLETION_NAME, body):
        verify_evidence(artifacts, identity_sha256, partitions)
    return read_completion(artifacts)


def verify_evidence(artifacts: Path, identity_sha256: str, partitions: Mapping[str, Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Refuse when the pinned held-out evidence was replaced, removed or re-collected. None if not yet pinned."""
    done = read_completion(artifacts)
    if done is None:
        return None
    current = {str(k): dict(v) for k, v in sorted(partitions.items())}
    diff = _conflicts(done["partitions"], current)
    if done.get("identity_sha256") != identity_sha256:
        diff.append({"field": "identity_sha256", "recorded": done.get("identity_sha256"), "current": identity_sha256})
    if diff:
        raise OOSAccessRefused("OOS_EVIDENCE_ALTERED",
                               f"the held-out partitions pinned at {done.get('completed_at_utc')} were replaced, removed or "
                               f"re-collected ({', '.join(d['field'] for d in diff)}); the held-out period is never collected twice",
                               diff)
    return done


def write_refusal(work: Path, stage: str, exc: OOSAccessRefused) -> Path:
    path = Path(work) / REFUSAL_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage, "code": exc.code, "detail": exc.detail, "conflicts": exc.conflicts,
                                "refused_at_utc": _now()}, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


__all__ = ["OOSAccessRefused", "refuse", "RECORD_NAME", "COMPLETION_NAME", "REFUSAL_NAME", "check_identity", "open_access",
           "read_record", "read_completion", "record_completion", "verify_evidence", "write_refusal"]

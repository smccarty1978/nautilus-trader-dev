"""Terminal ``STUDY_CLOSED`` lifecycle recognition.

A study is closed by writing a valid ``artifacts/study_closure.json``. Once present,
``WorkflowEngine.advance()`` reports ``terminal_state = STUDY_CLOSED`` and stops **before**
any TRAIN authorization / TRAIN execution / OOS authorization / OOS execution branch.

This module only *reads and validates* the closure artifact. It never writes it, never
rewrites seals or authorization metadata, and never infers reopening from artifact
absence. Reopening a closed study is out of scope until a governed reopen/revision
mechanism exists.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

CLOSURE_RELPATH = "artifacts/study_closure.json"
SUPPORTED_SCHEMA_VERSIONS = (1,)
_REQUIRED_FIELDS = ("schema_version", "study_id", "status", "outcome", "terminal_decision")


class StudyClosureInvalid(RuntimeError):
    """A closure artifact is present but malformed, mismatched, or not internally valid.

    Raised so a bad closure fails visibly rather than being silently ignored (which would
    let the workflow keep offering TRAIN/OOS actions against a study someone tried to close).
    """


def closure_artifact_sha256(study_dir: str | Path) -> Optional[str]:
    """Content identity of the closure artifact (CRLF-normalized, matching the seal system)."""
    p = Path(study_dir).resolve() / CLOSURE_RELPATH
    if not p.is_file():
        return None
    from scripts.resolve_execution_manifest import canonical_file_sha256

    return canonical_file_sha256(p)


def _validate_terminal_decision(study_dir: Path, terminal_decision: str) -> None:
    """If the study declares ``terminal_decisions``, the closure's decision must be one.

    Accepts an exact key (``P5``), an exact value (``NO_MEANINGFUL_SIGNAL``), or the
    ``KEY_VALUE`` concatenation (``P5_NO_MEANINGFUL_SIGNAL``). When no ``terminal_decisions``
    are declared, only the non-empty-string check (done by the caller) applies.
    """
    rd = study_dir / "research_decision.yaml"
    if not rd.is_file():
        return
    try:
        import yaml

        declared = (yaml.safe_load(rd.read_text(encoding="utf-8")) or {}).get("terminal_decisions") or {}
    except Exception:
        return
    if not isinstance(declared, dict) or not declared:
        return
    valid = set(map(str, declared.keys())) | {str(v) for v in declared.values()}
    valid |= {f"{k}_{v}" for k, v in declared.items()}
    if terminal_decision not in valid:
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_TERMINAL_DECISION_UNDECLARED: terminal_decision "
            f"{terminal_decision!r} is not one of the study's declared terminal_decisions "
            f"{sorted(declared)}"
        )


def load_study_closure(study_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Return the validated closure dict, ``None`` if no closure artifact exists.

    Raises :class:`StudyClosureInvalid` when the artifact is present but not a valid,
    matching, CLOSED closure record.
    """
    study_dir = Path(study_dir).resolve()
    p = study_dir / CLOSURE_RELPATH
    if not p.is_file():
        return None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StudyClosureInvalid(f"STUDY_CLOSURE_MALFORMED: {CLOSURE_RELPATH} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise StudyClosureInvalid("STUDY_CLOSURE_MALFORMED: top-level value is not a JSON object")

    missing = [k for k in _REQUIRED_FIELDS if k not in data]
    if missing:
        raise StudyClosureInvalid(f"STUDY_CLOSURE_MALFORMED: missing required field(s): {missing}")

    if data["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_MALFORMED: unsupported schema_version {data['schema_version']!r} "
            f"(supported: {list(SUPPORTED_SCHEMA_VERSIONS)})"
        )

    if data["status"] != "CLOSED":
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_NOT_CLOSED: status={data['status']!r}, expected 'CLOSED'. "
            "study_closure.json must only be created at actual closure."
        )

    expected_id = study_dir.name
    if data["study_id"] != expected_id:
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_STUDY_ID_MISMATCH: closure study_id={data['study_id']!r} "
            f"does not match study directory {expected_id!r}"
        )

    for field in ("outcome", "terminal_decision"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise StudyClosureInvalid(f"STUDY_CLOSURE_MALFORMED: {field!r} must be a non-empty string")

    _validate_terminal_decision(study_dir, data["terminal_decision"])
    return data


def closure_summary(study_dir: str | Path, closure: Dict[str, Any]) -> Dict[str, Any]:
    """The exact fields the workflow surfaces for a closed study -- no reinterpretation."""
    return {
        "study_id": closure["study_id"],
        "status": closure["status"],
        "outcome": closure["outcome"],
        "terminal_decision": closure["terminal_decision"],
        "closure_artifact_path": CLOSURE_RELPATH,
        "closure_artifact_sha256": closure_artifact_sha256(study_dir),
    }


__all__ = [
    "CLOSURE_RELPATH",
    "StudyClosureInvalid",
    "load_study_closure",
    "closure_summary",
    "closure_artifact_sha256",
]

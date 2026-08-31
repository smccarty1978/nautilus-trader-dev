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


def _authenticate_bound_evidence(study_dir: Path, data: Dict[str, Any]) -> None:
    bound = data.get("bound_evidence")
    if not isinstance(bound, dict) or not bound:
        return

    import hashlib

    # 1. Preexec audit seal
    if "preexec_seal_artifact_sha256" in bound:
        seal_path = study_dir / "artifacts" / "preexec_audit_seal.json"
        if not seal_path.is_file():
            raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISSING: artifacts/preexec_audit_seal.json missing")
        actual_sha = hashlib.sha256(seal_path.read_bytes()).hexdigest()
        if actual_sha != bound["preexec_seal_artifact_sha256"]:
            raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: preexec seal artifact sha mismatch")

    # 2. TRAIN freeze
    if "train_freeze_sha256" in bound:
        freeze_path = study_dir / "artifacts" / "train_experiment_freeze.json"
        if not freeze_path.is_file():
            raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISSING: artifacts/train_experiment_freeze.json missing")
        freeze_bytes = freeze_path.read_bytes()
        actual_sha = hashlib.sha256(freeze_bytes).hexdigest()
        try:
            freeze_data = json.loads(freeze_bytes.decode("utf-8"))
            internal_sha = freeze_data.get("freeze_sha256")
        except Exception:
            raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_CORRUPT: train_experiment_freeze.json unreadable")
        if bound["train_freeze_sha256"] not in {actual_sha, internal_sha}:
            raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: train freeze sha mismatch")

    # 3. Stage 16 analysis
    if "stage16_analysis" in bound:
        s16 = bound["stage16_analysis"]
        if isinstance(s16, dict):
            s16_path = study_dir / s16.get("path", "artifacts/experiment_analysis.json")
            if not s16_path.is_file():
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {s16.get('path')} missing")
            if s16.get("artifact_file_sha256"):
                if hashlib.sha256(s16_path.read_bytes()).hexdigest() != s16["artifact_file_sha256"]:
                    raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: stage16 analysis artifact file sha mismatch")
            from research_workflow.oos_analysis_lineage import classify_oos_analysis
            verdict = classify_oos_analysis(study_dir)
            if verdict is None or verdict.get("state") != "FRESH":
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_STALE: stage16 analysis is not FRESH: {verdict}")

    # 4. Stage 17 research decision
    if "stage17_research_decision" in bound:
        s17 = bound["stage17_research_decision"]
        if isinstance(s17, dict):
            s17_path = study_dir / s17.get("path", "artifacts/research_decision_stage17.json")
            if not s17_path.is_file():
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {s17.get('path')} missing")
            if s17.get("artifact_file_sha256"):
                if hashlib.sha256(s17_path.read_bytes()).hexdigest() != s17["artifact_file_sha256"]:
                    raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: stage17 decision artifact file sha mismatch")
            from research_workflow.oos_analysis_lineage import classify_stage17_decision
            verdict = classify_stage17_decision(study_dir)
            if verdict is not None and verdict.get("state") != "FRESH":
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_STALE: stage17 decision is not FRESH: {verdict}")

    # 5. OOS reconciliation and reconciled authority
    if "oos_lineage_reconciliation" in bound:
        rec = bound["oos_lineage_reconciliation"]
        if isinstance(rec, dict):
            rec_path = study_dir / rec.get("path", "artifacts/oos_lineage_reconciliation.json")
            if not rec_path.is_file():
                raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISSING: oos_lineage_reconciliation.json missing")
            if rec.get("artifact_file_sha256"):
                if hashlib.sha256(rec_path.read_bytes()).hexdigest() != rec["artifact_file_sha256"]:
                    raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: oos_lineage_reconciliation file sha mismatch")

    if "oos_reconciled_authority" in bound:
        rec_auth = bound["oos_reconciled_authority"]
        if isinstance(rec_auth, dict):
            rec_auth_path = study_dir / rec_auth.get("path", "artifacts/oos_reconciled_authority.json")
            if not rec_auth_path.is_file():
                raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISSING: oos_reconciled_authority.json missing")
            if rec_auth.get("artifact_file_sha256"):
                if hashlib.sha256(rec_auth_path.read_bytes()).hexdigest() != rec_auth["artifact_file_sha256"]:
                    raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: oos_reconciled_authority file sha mismatch")

    # 6. Final report
    if "final_report" in bound:
        fr = bound["final_report"]
        if isinstance(fr, dict):
            fr_path = study_dir / fr.get("path", "results/STUDY_REPORT.md")
            if not fr_path.is_file():
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {fr.get('path')} missing")
            if fr.get("sha256"):
                if hashlib.sha256(fr_path.read_bytes()).hexdigest() != fr["sha256"]:
                    raise StudyClosureInvalid("STUDY_CLOSURE_EVIDENCE_MISMATCH: final report sha mismatch")

    # 7. Model registry checks
    models_dict = data.get("models")
    if isinstance(models_dict, dict):
        repo_root = Path(__file__).resolve().parent.parent
        for role, m_info in models_dict.items():
            if isinstance(m_info, dict) and m_info.get("model_id"):
                mid = m_info["model_id"]
                reg_candidates = [
                    study_dir.parent / "model_registry" / f"{mid}.json",
                    study_dir / "model_registry" / f"{mid}.json",
                    repo_root / "studies" / "model_registry" / f"{mid}.json",
                ]
                reg_file = next((rc for rc in reg_candidates if rc.is_file()), None)
                if reg_file is None:
                    raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: model registry record missing for {mid}")
                try:
                    reg_body = json.loads(reg_file.read_text(encoding="utf-8"))
                except Exception:
                    raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_CORRUPT: model registry record unreadable for {mid}")
                art_rel = reg_body.get("artifact_path")
                if art_rel:
                    from research_workflow.oos_analysis_lineage import _resolve_relative_or_root
                    art_file = _resolve_relative_or_root(study_dir, art_rel)
                    if not art_file.is_file() or hashlib.sha256(art_file.read_bytes()).hexdigest() != reg_body.get("artifact_sha256"):
                        raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISMATCH: model artifact missing/corrupt for {mid}")


def load_study_closure(study_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Return the validated closure dict, ``None`` if no closure artifact exists.

    Raises :class:`StudyClosureInvalid` when the artifact is present but not a valid,
    matching, CLOSED closure record with authenticated terminal evidence.
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
    _authenticate_bound_evidence(study_dir, data)
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

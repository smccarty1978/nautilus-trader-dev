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

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

CLOSURE_RELPATH = "artifacts/study_closure.json"
SUPPORTED_SCHEMA_VERSIONS = (1,)
V2_FINAL_EVIDENCE = {
    "v2_analysis": "artifacts/experiment_analysis_v2.json",
    "v2_decision": "artifacts/analysis_decision.json",
}
V2_PLAN_RELPATH = "compiled_plan.json"
# Closures written before commit 5d3aad6a (the V2 final-evidence binding rule) that validate
# under the prior rule. Date-bounded and hash-pinned; see the record's ``note``.
GRANDFATHER_PATH = Path(__file__).resolve().parent / "study_closure_grandfather.json"
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


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise StudyClosureInvalid("STUDY_CLOSURE_MALFORMED: closed_at_utc must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyClosureInvalid(f"STUDY_CLOSURE_MALFORMED: unparseable timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_CORRUPT: {label} unreadable: {exc}") from exc
    if not isinstance(body, dict):
        raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_CORRUPT: {label} is not a JSON object")
    return body


def load_grandfather_record(path: Path = GRANDFATHER_PATH) -> Dict[str, Any]:
    """The recorded pre-``5d3aad6a`` closure exemptions. Every entry must predate the rule commit;
    an entry that does not is refused here, so the record can never exempt a later closure."""
    if not path.is_file():
        return {"closures": {}, "rule_commit_utc": None}
    record = _read_json(path, path.name)
    cutoff = _utc(record.get("rule_commit_utc"))
    for study_id, entry in (record.get("closures") or {}).items():
        if not isinstance(entry, dict) or _utc(entry.get("closed_at_utc")) >= cutoff:
            raise StudyClosureInvalid(
                f"STUDY_CLOSURE_GRANDFATHER_OUT_OF_BOUNDS: {study_id} in {path.name} is not strictly before "
                f"the rule commit ({record.get('rule_commit_utc')}); the exemption is date-bounded")
    return record


def _grandfathered_v2_evidence(study_dir: Path, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the exemption entry when this closure is one of the recorded pre-rule closures.

    ``None`` means no exemption applies (the caller raises the ordinary
    ``STUDY_CLOSURE_EVIDENCE_MISSING``). An entry that exists but whose closure or final evidence
    does not authenticate against the recorded hashes raises: the exemption relaxes only the
    *binding*, never the authentication -- the grandfathered evidence is pinned here instead.
    """
    record = load_grandfather_record()
    entry = (record.get("closures") or {}).get(study_dir.name)
    if not isinstance(entry, dict):
        return None
    cutoff = _utc(record.get("rule_commit_utc"))
    closed = data.get("closed_at_utc")
    if closed != entry.get("closed_at_utc") or _utc(closed) >= cutoff:
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_GRANDFATHER_OUT_OF_BOUNDS: {study_dir.name} closed_at_utc={closed!r} is not the "
            f"recorded pre-rule closure ({entry.get('closed_at_utc')!r}, rule {record.get('rule_commit_utc')})")
    from scripts.resolve_execution_manifest import canonical_file_sha256

    if canonical_file_sha256(study_dir / CLOSURE_RELPATH) != entry.get("closure_artifact_sha256"):
        raise StudyClosureInvalid(
            f"STUDY_CLOSURE_GRANDFATHER_MISMATCH: {study_dir.name} closure bytes differ from the recorded pre-rule closure")
    recorded = entry.get("final_evidence") or {}
    for rel in V2_FINAL_EVIDENCE.values():
        path = study_dir / rel
        if path.is_file():
            if not recorded.get(rel) or canonical_file_sha256(path) != recorded[rel]:
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISMATCH: {rel} (grandfathered final evidence)")
        elif recorded.get(rel):
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {rel} (grandfathered final evidence)")
    return entry


def _cited_evidence(decision: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """``{relpath: sha256-or-None}`` for every artifact an analysis decision cites."""
    cited: Dict[str, Optional[str]] = {}
    for item in decision.get("evidence") or []:
        if isinstance(item, str) and item.strip():
            cited[item.strip().replace("\\", "/")] = None
        elif isinstance(item, dict) and item.get("path"):
            sha = item.get("sha256") or item.get("artifact_file_sha256")
            cited[str(item["path"]).replace("\\", "/")] = sha if isinstance(sha, str) else None
    return cited


def _assert_v2_final_evidence_fresh(study_dir: Path, data: Dict[str, Any], bound: Dict[str, Any]) -> None:
    """Fresh means *produced from this plan and this TRAIN freeze*, not merely unchanged since closure.

    Byte authentication (done by the caller) cannot tell a stale-but-unmodified artifact from a
    current one. So: ``experiment_analysis_v2.json`` must record the ``plan_sha256`` the closure and
    the study's compiled plan carry, the bound TRAIN freeze must be of that same plan, and every
    model the analysis scored must be a model that freeze binds. ``analysis_decision.json`` must
    cite the analysis, and every cited artifact it hashed must still hash the same.
    """
    if "v2_analysis" not in bound and "v2_decision" not in bound:
        return
    plan_path = study_dir / V2_PLAN_RELPATH
    current_plan = _read_json(plan_path, V2_PLAN_RELPATH).get("plan_sha256") if plan_path.is_file() else None
    closure_plan = data.get("plan_sha256")

    if "v2_analysis" in bound:
        analysis_rel = V2_FINAL_EVIDENCE["v2_analysis"]
        analysis = _read_json(study_dir / analysis_rel, analysis_rel)
        produced = analysis.get("plan_sha256")
        binding = bound["v2_analysis"] if isinstance(bound["v2_analysis"], dict) else {}
        expected = {v for v in (closure_plan, current_plan, binding.get("plan_sha256")) if isinstance(v, str) and v}
        if expected and (len(expected) != 1 or produced not in expected):
            raise StudyClosureInvalid(
                f"STUDY_CLOSURE_EVIDENCE_STALE: {analysis_rel} was produced from plan {str(produced)[:12]!r} but the "
                f"closure/compiled plan is {[e[:12] for e in sorted(expected)]}; final evidence must come from this plan")
        freeze_path = study_dir / "artifacts" / "train_experiment_freeze.json"
        if "train_freeze_sha256" in bound and freeze_path.is_file():
            binding_freeze = binding.get("train_freeze_sha256")
            if binding_freeze and binding_freeze != bound["train_freeze_sha256"]:
                raise StudyClosureInvalid(
                    f"STUDY_CLOSURE_EVIDENCE_STALE: {analysis_rel} is bound to a different TRAIN freeze than the closure")
            freeze = _read_json(freeze_path, "train_experiment_freeze.json")
            if freeze.get("plan_sha256") and produced and freeze["plan_sha256"] != produced:
                raise StudyClosureInvalid(
                    f"STUDY_CLOSURE_EVIDENCE_STALE: the bound TRAIN freeze is of plan {str(freeze['plan_sha256'])[:12]!r}, "
                    f"{analysis_rel} of plan {str(produced)[:12]!r}")
            frozen_ids = ({str(v) for v in (freeze.get("model_hashes") or {}).values()}
                          | {str(v) for v in (freeze.get("model_canonical_sha256") or {}).values()})
            scored = {str(m.get("id") or m.get("model_id")) for key in ("frozen_models_oos", "train_metrics")
                      for m in (analysis.get(key) or []) if isinstance(m, dict) and (m.get("id") or m.get("model_id"))}
            if scored and not scored <= frozen_ids:
                raise StudyClosureInvalid(
                    f"STUDY_CLOSURE_EVIDENCE_STALE: {analysis_rel} scores model(s) {sorted(x[:12] for x in scored - frozen_ids)} "
                    f"that the bound TRAIN freeze does not bind; final evidence must come from this freeze")

    if "v2_decision" in bound:
        decision_rel = V2_FINAL_EVIDENCE["v2_decision"]
        decision = _read_json(study_dir / decision_rel, decision_rel)
        if decision.get("study_id") not in (None, study_dir.name):
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MALFORMED: {decision_rel} names study {decision.get('study_id')!r}")
        cited = _cited_evidence(decision)
        analysis_rel = V2_FINAL_EVIDENCE["v2_analysis"]
        if (study_dir / analysis_rel).is_file() and analysis_rel not in cited:
            raise StudyClosureInvalid(
                f"STUDY_CLOSURE_EVIDENCE_STALE: {decision_rel} does not cite {analysis_rel}; a decision must be about this study's final analysis")
        for rel, sha in cited.items():
            if sha is None:
                continue
            path = study_dir / rel
            if not path.is_file():
                raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {decision_rel} cites {rel}, which is absent")
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise StudyClosureInvalid(
                    f"STUDY_CLOSURE_EVIDENCE_STALE: {decision_rel} was decided on a different {rel} than the one on disk")


def _require_mandatory_bound_evidence(study_dir: Path, data: Dict[str, Any]) -> None:
    """A closure may be terminal only if ``bound_evidence`` binds the evidence that is
    mandatory for the lifecycle stage the study *actually reached* (proven by the stage's
    own artifact being present on disk).

    A study closed before any governed execution stage (no TRAIN freeze / analysis /
    decision / reconciliation artifact) carries no mandatory terminal evidence and is
    unaffected. Once TRAIN/OOS/Stage16/Stage17 was reached, a missing or empty
    ``bound_evidence`` -- or one that omits a stage it reached -- is
    ``STUDY_CLOSURE_INVALID`` (never a reopen: the workflow engine surfaces it as a
    terminal blocked state).
    """
    bound = data.get("bound_evidence")
    bound = bound if isinstance(bound, dict) else {}
    unbound = [rel for key, rel in V2_FINAL_EVIDENCE.items() if (study_dir / rel).is_file() and key not in bound]
    # A closure recorded in study_closure_grandfather.json (written before the binding rule,
    # date-bounded) validates under the prior rule; its final evidence is authenticated there.
    if unbound and _grandfathered_v2_evidence(study_dir, data) is None:
        raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: closure omits {unbound[0]}")
    art = study_dir / "artifacts"
    reached_train = (art / "train_experiment_freeze.json").is_file()
    reached_s16 = (art / "experiment_analysis.json").is_file()
    reached_s17 = (art / "research_decision_stage17.json").is_file()
    reached_recon = (art / "oos_lineage_reconciliation.json").is_file()
    reached_recon_auth = (art / "oos_reconciled_authority.json").is_file()
    if not (reached_train or reached_s16 or reached_s17 or reached_recon or reached_recon_auth):
        return

    bound = data.get("bound_evidence")
    bound = bound if isinstance(bound, dict) else {}

    required: list[tuple[str, tuple[str, ...]]] = []
    if reached_train:
        required.append(("TRAIN freeze", ("train_freeze_sha256",)))
        if (art / "preexec_audit_seal.json").is_file():
            required.append(("preexec seal", ("preexec_seal_artifact_sha256", "preexec_seal_composite_sha256")))
    if reached_s16:
        required.append(("Stage 16 analysis", ("stage16_analysis",)))
    if reached_s17:
        required.append(("Stage 17 decision", ("stage17_research_decision",)))
    if reached_recon:
        required.append(("OOS lineage reconciliation", ("oos_lineage_reconciliation",)))
    if reached_recon_auth:
        required.append(("OOS reconciled authority", ("oos_reconciled_authority",)))

    missing = [f"{label} (one of {list(keys)})" for label, keys in required
               if not any(k in bound for k in keys)]
    if not bound or missing:
        raise StudyClosureInvalid(
            "STUDY_CLOSURE_EVIDENCE_MISSING: closure omits mandatory terminal evidence for "
            f"the lifecycle stage(s) the study reached: {missing or ['bound_evidence is empty']}"
        )


def _authenticate_bound_evidence(study_dir: Path, data: Dict[str, Any]) -> None:
    _require_mandatory_bound_evidence(study_dir, data)

    bound = data.get("bound_evidence")
    if not isinstance(bound, dict) or not bound:
        return

    # V2 terminal evidence: exact paths and mandatory raw-byte hashes. A missing,
    # malformed or redirected binding must never authenticate an unrelated file.
    for key, rel in V2_FINAL_EVIDENCE.items():
        if key not in bound:
            continue
        evidence = bound[key]
        if not isinstance(evidence, dict) or evidence.get("path") != rel:
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MALFORMED: {key} must bind {rel}")
        expected = evidence.get("artifact_file_sha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MALFORMED: {key} requires a SHA-256")
        path = study_dir / rel
        if not path.is_file():
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISSING: {rel}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise StudyClosureInvalid(f"STUDY_CLOSURE_EVIDENCE_MISMATCH: {rel}")
    _assert_v2_final_evidence_fresh(study_dir, data, bound)

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
            if verdict is None or verdict.get("state") != "FRESH":
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
    "GRANDFATHER_PATH",
    "load_grandfather_record",
    "StudyClosureInvalid",
    "load_study_closure",
    "closure_summary",
    "closure_artifact_sha256",
]

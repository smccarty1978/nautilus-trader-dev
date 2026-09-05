"""Derive a study's position from ARTIFACTS (packet section 1, state principle: derive, do not invent).

Inputs, in precedence order: ``artifacts/study_closure.json``; the pending user-decision card (the only
supervisor-owned input); the writer lease; ``CAPABILITY_GAP_HANDOFF.json``; ``compiled_plan.json``; the
controller's persisted card ``_work/controller/status.json`` (honoured only while its fingerprints still
match ``study.yaml`` / ``compiled_plan.json``); ``_work/controller/run.lock``; ``audit/*status.json`` vs the
frozen composite; ``artifacts/analysis_decision.json``. Every input path and its sha256 is recorded in
``derived_from`` so a resume can prove what the decision was based on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from research_workflow.supervisor.packets import sha256_file
from research_workflow.supervisor.procs import pid_alive
from research_workflow.supervisor.state import read_json

PLATFORM_GAP_KINDS = ("MISSING_CAPABILITY", "UNSUPPORTED_COMPOSITION", "UNAVAILABLE_STREAM")
STUDY_SIDE_GAP_KINDS = ("INVALID_PARAMETERIZATION",)
SEMANTIC_GAP_KINDS = ("AMBIGUOUS_TEMPORAL_SEMANTICS", "SEMANTIC_DECISION_REQUIRED")
PRE_SEAL_STATES = ("NEEDS_COMPILE", "NEEDS_PREPARE", "NEEDS_READINESS", "NEEDS_PREFLIGHT", "NEEDS_TESTS", "READY_TO_SEAL")
EXEC_STATES = ("READY_TO_SMOKE", "READY_TO_COLLECT", "COLLECTION_RUNNING", "READY_TO_RECONCILE", "READY_TO_MERGE", "READY_TO_FIT",
               "READY_TO_FREEZE", "READY_TO_OOS", "READY_TO_ANALYZE")
STAGE_ORDER = ("compile", "prepare", "readiness", "preflight", "tests", "causal_audit", "contract_audit", "seal",
               "smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze", "close")
USER_INTERVENTION_CODES = ("SCIENTIFIC_SEMANTIC_DECISION_REQUIRED", "AUTHORIZATION_AMBIGUITY", "PROTECTED_OOS_AUTHORIZATION_REQUIRED",
                           "DATA_SAFETY_RISK", "CAUSAL_DEFINITION_AMBIGUOUS", "RESEARCH_CONTRACT_CONFLICT", "DESTRUCTIVE_ACTION_REQUIRES_APPROVAL",
                           "SUPERVISOR_ESCALATION_REQUIRED")
PHASE_OF = {"NO_SPEC": "A", "CAPABILITY_GAP": "A", "COMPILED": "B", "CONTROLLER_STEP": "B", "NEEDS_CAUSAL_AUDIT": "B", "NEEDS_CONTRACT_AUDIT": "B",
            "DETERMINISTIC_BLOCKER": "B", "AUDIT_BLOCKER": "B", "SEMANTIC_BLOCKER": "A", "READY_TO_EXECUTE": "C", "EXECUTION_NOT_AUTHORIZED": "C",
            "EXECUTION_BLOCKER": "C", "RUNNING": "C", "READY_FOR_ANALYSIS": "D", "ANALYSIS_DECIDED": "D", "STUDY_CLOSED": "D"}


def study_dir_of(state: Dict[str, Any]) -> Path:
    if state.get("study_dir"):
        return Path(state["study_dir"])
    return Path(state["study_worktree"]) / "studies" / state["study_id"]


def _lease_for(worktree: Path) -> Optional[Dict[str, Any]]:
    try:
        from research_workflow.workspace import read_leases
        wt = Path(worktree).resolve()
        return next((l for l in read_leases() if Path(str(l.get("worktree", ""))).resolve() == wt), None)
    except Exception:
        return None


def decision_resolves(decision: Dict[str, Any], gaps: List[Dict[str, Any]]) -> bool:
    """A semantic gap is resolved iff research_decision.yaml (terminal_decisions / autonomy_decisions) names it:
    by the gap detail's ``decision_key`` / ``policy`` / ``key``, or by the last segment of its ``where`` path."""
    keys = set((decision.get("terminal_decisions") or {}).keys()) | set((decision.get("autonomy_decisions") or {}).keys())
    if not keys:
        return False
    for g in gaps:
        detail = g.get("detail") or {}
        candidates = {str(detail.get(k)) for k in ("decision_key", "policy", "key") if detail.get(k)}
        where = str(g.get("where") or "")
        if where:
            candidates.add(where.split(".")[-1].split("[")[0])
        if not (candidates & keys):
            return False
    return True


def derive(state: Dict[str, Any], *, supervisor_identity: Dict[str, Any]) -> Dict[str, Any]:
    study = study_dir_of(state)
    wt = Path(state["study_worktree"])
    frm: Dict[str, Optional[str]] = {}

    def note(p: Path) -> Optional[str]:
        s = sha256_file(p)
        frm[str(p.relative_to(wt)).replace("\\", "/") if wt in p.parents else str(p)] = s
        return s

    out: Dict[str, Any] = {"code": None, "phase": None, "controller_state": None, "stage": None, "blocker_code": None, "gap_kinds": [], "gaps": [],
                           "evidence": {}, "derived_from": frm, "through": None, "handoff_sha256": None, "study_dir": str(study)}

    def done(code: str, **ev: Any) -> Dict[str, Any]:
        out["code"] = code; out["phase"] = PHASE_OF.get(code, out.get("phase")); out["evidence"].update(ev)
        return out

    closure = study / "artifacts" / "study_closure.json"
    if note(closure):
        return done("STUDY_CLOSED", closure=str(closure))
    ud = state.get("user_decision") or {}
    if ud and not ud.get("answered"):
        out["blocker_code"] = ud.get("code")
        return done("USER_DECISION_REQUIRED", decision_code=ud.get("code"), card=ud.get("card_path"))
    lease = _lease_for(wt)
    if lease and lease.get("state") == "live":
        from research_workflow.workspace import same_writer
        aw = state.get("active_worker") or {}
        if not same_writer(lease, supervisor_identity) and str(lease.get("owner_session_id")) != str(aw.get("session_id")):
            return done("WAIT_STUDY_LEASE", lease_owner=f"{lease.get('owner')} agent={lease.get('owner_agent')} session={lease.get('owner_session_id')}")
    handoff = study / "CAPABILITY_GAP_HANDOFF.json"
    plan = study / "compiled_plan.json"
    h_sha = note(handoff); p_sha = note(plan)
    note(study / "study.yaml"); note(study / "research_decision.yaml")
    if h_sha:
        out["handoff_sha256"] = h_sha
        superseded = h_sha in (state.get("consumed_handoffs") or [])
        if not superseded and plan.is_file() and plan.stat().st_mtime > handoff.stat().st_mtime:
            superseded = True
        if not superseded:
            doc = read_json(handoff)
            out["gaps"] = list(doc.get("gaps") or []); out["gap_kinds"] = sorted({str(g.get("kind")) for g in out["gaps"]} | set(doc.get("gap_kinds") or []))
            return done("CAPABILITY_GAP", handoff=str(handoff), topic=doc.get("proposed_chore_topic"), suggested_files=doc.get("suggested_platform_files") or [])
    if not p_sha:
        return done("NO_SPEC")
    work = study / "_work" / "controller"
    lock = work / "run.lock"
    lk = read_json(lock) if lock.is_file() else {}
    if lk and pid_alive(int(lk.get("pid") or 0)):
        note(lock)
        return done("RUNNING", pid=lk.get("pid"), through=lk.get("through"))
    card_path = work / "status.json"
    if not note(card_path):
        out["through"] = "seal"
        return done("COMPILED")
    card = read_json(card_path)
    fp = card.get("fingerprints") or {}
    try:
        from research_workflow.lifecycle_v2 import spec_sha256
        spec_now = spec_sha256(study)
    except Exception:
        spec_now = None
    out["controller_state"] = card.get("state"); out["stage"] = card.get("stage"); out["blocker_code"] = card.get("blocker_code")
    if card.get("dry_run") or (spec_now and fp.get("study_spec") != spec_now) or fp.get("compiled_plan") != p_sha:
        out["through"] = "seal"
        return done("COMPILED", card_stale=True)
    cstate = str(card.get("state") or ""); blocked = card.get("STATUS") == "BLOCKED"; bc = str(card.get("blocker_code") or "")
    stage = str(card.get("stage") or "")
    if cstate == "STUDY_CLOSED":
        return done("STUDY_CLOSED", closure=str(closure))
    if blocked:
        if bc == "CAPABILITY_BLOCKER":
            out["gaps"] = list(card.get("capability_gaps") or []); out["gap_kinds"] = sorted({str(g.get("kind")) for g in out["gaps"]})
            return done("CAPABILITY_GAP", source="controller_card")
        if bc == "STUDY_RUN_ALREADY_LIVE":
            return done("RUNNING", source="controller_card")
        if bc == "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT":
            return done("WAIT_STUDY_LEASE", source="controller_card")
        if bc == "EXECUTION_NOT_AUTHORIZED":
            return done("EXECUTION_NOT_AUTHORIZED")
        if bc in ("CAUSALITY_BLOCKER", "CONTRACT_BLOCKER"):
            return done("AUDIT_BLOCKER", stage=stage)
        if bc == "SEMANTIC_BLOCKER":
            return done("SEMANTIC_BLOCKER", stage=stage)
        if bc == "DATA_AUTH_BLOCKER":
            out["blocker_code"] = "PROTECTED_OOS_AUTHORIZATION_REQUIRED"
            return done("SEMANTIC_BLOCKER", stage=stage)
        if stage in STAGE_ORDER and STAGE_ORDER.index(stage) > STAGE_ORDER.index("seal"):
            return done("EXECUTION_BLOCKER", stage=stage)
        return done("DETERMINISTIC_BLOCKER", stage=stage)
    frozen = read_json(study / "audit" / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
    if cstate in ("NEEDS_CAUSAL_AUDIT", "NEEDS_CONTRACT_AUDIT"):
        status_name = "status.json" if cstate == "NEEDS_CAUSAL_AUDIT" else "contract_status.json"
        st = read_json(study / "audit" / status_name); note(study / "audit" / status_name)
        current = bool(frozen) and st.get("audited_execution_composite_sha256") == frozen
        if current and st.get("verdict") == "CLEAR":
            out["through"] = "seal"
            return done("CONTROLLER_STEP", audit_ingested=status_name)
        if current and st.get("verdict") in ("BLOCKED", "INCOMPLETE"):
            out["blocker_code"] = "CAUSALITY_BLOCKER" if cstate == "NEEDS_CAUSAL_AUDIT" else "CONTRACT_BLOCKER"
            return done("AUDIT_BLOCKER", stage=stage)
        return done(cstate, packet=card.get("artifact"), frozen_composite=frozen)
    if cstate in PRE_SEAL_STATES:
        out["through"] = "seal"
        return done("CONTROLLER_STEP")
    if cstate in EXEC_STATES:
        out["through"] = "analyze"
        return done("READY_TO_EXECUTE" if state.get("execute_authorized") else "EXECUTION_NOT_AUTHORIZED", controller_state=cstate)
    if cstate in ("READY_TO_CLOSE", "COMPLETE"):
        dec = study / "artifacts" / "analysis_decision.json"
        d = read_json(dec) if note(dec) else {}
        if d.get("outcome") and d.get("terminal_decision"):
            out["through"] = "close"
            return done("ANALYSIS_DECIDED", outcome=d.get("outcome"), terminal_decision=d.get("terminal_decision"))
        return done("READY_FOR_ANALYSIS")
    out["through"] = "seal"
    return done("CONTROLLER_STEP", unknown_controller_state=cstate)


__all__ = ["derive", "decision_resolves", "study_dir_of", "PLATFORM_GAP_KINDS", "STUDY_SIDE_GAP_KINDS", "SEMANTIC_GAP_KINDS", "USER_INTERVENTION_CODES",
           "PRE_SEAL_STATES", "EXEC_STATES", "STAGE_ORDER", "PHASE_OF"]

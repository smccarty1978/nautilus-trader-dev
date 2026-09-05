"""The supervisor tick loop (packet sections 2, 4, 5, 6, 7, 11).

One ``tick`` is one deterministic step: reap/consume the active worker or job, derive the study's position
from artifacts, route the typed state to exactly one action (launch a fresh worker, launch a detached
controller job, wait, or persist a typed user-decision card). Nothing here reasons about science; nothing
here runs a lifecycle stage itself -- the governed controller does, in its own detached process.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from research_workflow.supervisor import derive as D
from research_workflow.supervisor import packets as P
from research_workflow.supervisor import providers as PR
from research_workflow.supervisor import resources as R
from research_workflow.supervisor import state as S
from research_workflow.supervisor.procs import kill_tree, pid_alive, spawn_detached

MAX_ATTEMPTS = 2
DEFAULT_WORKER_TIMEOUT_S = 3600.0
DEFAULT_JOB_TIMEOUT_S = 6 * 3600.0
SEMANTIC_BLOCKER_CODES = ("SEMANTIC_BLOCKER", "PROTECTED_OOS_AUTHORIZATION_REQUIRED", "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED",
                          "CAUSAL_DEFINITION_AMBIGUOUS", "RESEARCH_CONTRACT_CONFLICT", "DATA_SAFETY_RISK")


class SupervisorError(RuntimeError):
    pass


def _git(args: Sequence[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SupervisorError(f"GIT_FAILED: git {' '.join(args)} in {cwd}: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def _yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _norm(p: str) -> str:
    return str(p).replace("\\", "/").strip().lstrip("./").rstrip("/")


def _within(path: str, surfaces: Sequence[str]) -> bool:
    n = _norm(path)
    for s in surfaces:
        s2 = _norm(s)
        if not s2:
            continue
        if n == s2 or n.startswith(s2 + "/"):
            return True
        if any(ch in s2 for ch in "*?[") and Path(n).match(s2):
            return True
    return False


class Supervisor:
    """One study's supervisor. Construct with an existing state (``Supervisor(study_id)``) or via ``start``/``adopt``."""

    def __init__(self, study_id: str) -> None:
        self.state = S.load_state(study_id)
        self.dir = S.study_state_dir(study_id)
        for sub in ("packets", "results", "logs"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self._bind_identity_env()

    # ------------------------------------------------------------------ identity
    def _bind_identity_env(self) -> None:
        """The supervisor process writes (study new, ws claim, chore claim, merges) as provider@supervisor-session."""
        os.environ["NT_RESEARCH_AGENT"] = str(self.state["provider"])
        os.environ["NT_RESEARCH_AGENT_SESSION"] = str(self.state["supervisor_session_id"])

    @property
    def identity(self) -> Dict[str, Any]:
        return _identity(self.state["provider"], self.state["supervisor_session_id"])

    @property
    def study_id(self) -> str:
        return str(self.state["study_id"])

    @property
    def study_dir(self) -> Path:
        return D.study_dir_of(self.state)

    @property
    def worktree(self) -> Path:
        return Path(self.state["study_worktree"])

    @property
    def repo_root(self) -> Path:
        return Path(self.state["repo_root"])

    @property
    def options(self) -> Dict[str, Any]:
        return self.state.setdefault("options", {})

    # ------------------------------------------------------------------ construction
    @classmethod
    def start(cls, *, question: Path, repo_root: Path, study_id: Optional[str] = None, provider: Optional[str] = None,
              execute_authorized: bool = False, options: Optional[Dict[str, Any]] = None) -> "Supervisor":
        provider = _resolve_provider(provider)
        question = Path(question).resolve()
        if not question.is_file():
            raise SupervisorError(f"QUESTION_FILE_MISSING: {question}")
        sid = study_id or _slug(question.stem)
        if (S.study_state_dir(sid) / "state.json").is_file():
            raise SupervisorError(f"SUPERVISOR_STATE_EXISTS: {sid} (use `supervise resume {sid}`)")
        session_id = str(uuid.uuid4())
        os.environ["NT_RESEARCH_AGENT"] = provider; os.environ["NT_RESEARCH_AGENT_SESSION"] = session_id
        from research_workflow.workspace import WorkspaceError, study_new
        try:
            card = study_new(sid, repo_root=Path(repo_root).resolve(), question_file=str(question))
        except WorkspaceError as exc:
            raise SupervisorError(str(exc)) from exc
        st = S.new_state(study_id=sid, question_path=str(question), question_sha256=P.sha256_file(question), platform_commit=card.get("base_commit"),
                         provider=provider, study_branch=card["branch"], study_worktree=card["worktree"], repo_root=str(Path(repo_root).resolve()),
                         execute_authorized=execute_authorized, supervisor_session_id=session_id, options=options)
        st["providers"] = {provider: PR.probe_provider(provider)}
        S.save_state(st)
        S.append_event(sid, "START", provider=provider, branch=card["branch"], worktree=card["worktree"], base_commit=card.get("base_commit"),
                       execute_authorized=execute_authorized, question_sha256=st["question_sha256"])
        return cls(sid)

    @classmethod
    def adopt(cls, *, study_dir: Path, repo_root: Path, provider: Optional[str] = None, execute_authorized: bool = False,
              options: Optional[Dict[str, Any]] = None, worktree: Optional[Path] = None) -> "Supervisor":
        """Create supervisor state for an EXISTING study by deriving its position; never recreates, rewrites or re-runs."""
        provider = _resolve_provider(provider)
        study_dir = Path(study_dir).resolve()
        if not (study_dir / "study.yaml").is_file():
            raise SupervisorError(f"STUDY_DIR_INVALID: {study_dir} has no study.yaml")
        sid = study_dir.name
        if (S.study_state_dir(sid) / "state.json").is_file():
            raise SupervisorError(f"SUPERVISOR_STATE_EXISTS: {sid} (use `supervise resume {sid}`)")
        top = _git(["rev-parse", "--show-toplevel"], study_dir).stdout.strip()
        wt = Path(worktree).resolve() if worktree else (Path(top).resolve() if top else study_dir.parents[1])
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], wt).stdout.strip() or None
        st = S.new_state(study_id=sid, question_path=None, question_sha256=None, platform_commit=_git(["rev-parse", "main"], Path(repo_root)).stdout.strip() or None,
                         provider=provider, study_branch=branch, study_worktree=str(wt), repo_root=str(Path(repo_root).resolve()),
                         execute_authorized=execute_authorized, options=options)
        st["adopted"] = True
        if worktree or not top or Path(top).resolve() != study_dir.parents[1].resolve():
            st["study_dir"] = str(study_dir)
        st["providers"] = {provider: PR.probe_provider(provider)}
        S.save_state(st)
        sup = cls(sid)
        d = D.derive(sup.state, supervisor_identity=sup.identity)
        sup.state["derived_state"] = d["code"]; sup.state["derived_from"] = d["derived_from"]; sup.state["current_phase"] = d["phase"]
        sup.state["next_action"] = sup._plan_only(d)
        S.save_state(sup.state)
        S.append_event(sid, "ADOPT", derived_state=d["code"], next_action=sup.state["next_action"], worktree=str(wt), branch=branch)
        return sup

    # ------------------------------------------------------------------ public verbs
    def status(self) -> Dict[str, Any]:
        st = self.state
        d = D.derive(st, supervisor_identity=self.identity)
        loop_pid = self._loop_pid()
        return {"study_id": self.study_id, "provider": st["provider"], "derived_state": d["code"], "phase": d["phase"], "controller_state": d.get("controller_state"),
                "blocker_code": d.get("blocker_code"), "persisted_state": st.get("derived_state"), "next_action": st.get("next_action"),
                "active_worker": _brief(st.get("active_worker")), "active_job": _brief(st.get("active_job")), "active_capability": st.get("active_capability"),
                "user_intervention_required": bool(st.get("user_intervention_required")), "user_decision": st.get("user_decision"),
                "attempts": st.get("attempts"), "counters": st.get("counters"), "terminal": bool(st.get("terminal")), "stopped": bool(st.get("stopped")),
                "loop_pid": loop_pid, "loop_alive": pid_alive(loop_pid or 0), "study_worktree": st["study_worktree"], "study_branch": st["study_branch"],
                "execute_authorized": st["execute_authorized"], "state_dir": str(self.dir), "slots": R.slot_status(), "updated_at_utc": st.get("updated_at_utc")}

    def stop(self) -> Dict[str, Any]:
        self.state["stopped"] = True
        pid = self._loop_pid()
        killed = kill_tree(pid) if pid and pid != os.getpid() else False
        S.save_state(self.state); S.append_event(self.study_id, "STOP", loop_pid=pid, loop_killed=killed)
        return {"study_id": self.study_id, "stopped": True, "loop_pid": pid, "loop_killed": killed,
                "note": "active worker/job processes are left to finish; their cards are consumed on resume"}

    def resume(self) -> Dict[str, Any]:
        self.state["stopped"] = False
        S.save_state(self.state); S.append_event(self.study_id, "RESUME")
        return self.tick()

    def decide(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        ud = self.state.get("user_decision")
        if not ud or ud.get("answered"):
            raise SupervisorError("NO_PENDING_USER_DECISION")
        code = ud["code"]
        applied: Dict[str, Any] = {"code": code}
        if code == "DESTRUCTIVE_ACTION_REQUIRES_APPROVAL":
            approve = bool(answer.get("approve"))
            cap = self.state.get("active_capability") or {}
            if approve and cap:
                cap["status"] = "approved"; applied["capability"] = cap.get("topic")
            elif cap:
                cap["status"] = "rejected"; self.state["terminal"] = True; applied["rejected"] = True
        elif code == "AUTHORIZATION_AMBIGUITY":
            self.state["execute_authorized"] = bool(answer.get("execute_authorized")); applied["execute_authorized"] = self.state["execute_authorized"]
            if not self.state["execute_authorized"]:
                self.state["terminal"] = True
        elif code == "SUPERVISOR_ESCALATION_REQUIRED":
            if answer.get("retry"):
                self.state["attempts"] = {}; self.state["blocker_streak"] = 0; applied["attempts_reset"] = True
            else:
                self.state["terminal"] = True; applied["terminal"] = True
        else:   # scientific answers live in the STUDY, never only in supervisor state
            n = int(self.state["counters"].get("user_interventions") or 1)
            dest = self.study_dir / "_work" / "handoff" / f"USER_DECISION_{n:02d}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps({"kind": "USER_DECISION_ANSWER", "code": code, "question": ud.get("question"), "answer": answer,
                                        "answered_at_utc": S.now_utc()}, indent=2, default=str) + "\n", encoding="utf-8")
            applied["study_file"] = str(dest)
            self.state["attempts"] = {k: v for k, v in (self.state.get("attempts") or {}).items() if not k.startswith("STUDY_DESIGN_COMPILE")}
            self.state.setdefault("user_answers", []).append(str(dest))
        ud["answered"] = True; ud["answer"] = answer; ud["answered_at_utc"] = S.now_utc()
        self.state["user_intervention_required"] = False; self.state["stopped"] = False
        S.save_state(self.state); S.append_event(self.study_id, "USER_DECISION_ANSWERED", **applied)
        return {"study_id": self.study_id, "applied": applied, "next": "supervise resume" if not self.state.get("terminal") else "terminal"}

    # ------------------------------------------------------------------ the tick
    def tick(self) -> Dict[str, Any]:
        st = self.state
        st["counters"]["ticks"] = int(st["counters"].get("ticks") or 0) + 1
        if st.get("stopped"):
            return self._card("STOPPED", "supervise resume <id>")
        if st.get("terminal"):
            return self._card("TERMINAL", st.get("next_action"))
        try:
            if st.get("active_worker"):
                r = self._reap_worker()
                if r is not None:
                    return r
            if st.get("active_job"):
                r = self._reap_job()
                if r is not None:
                    return r
            d = D.derive(st, supervisor_identity=self.identity)
            st["derived_state"] = d["code"]; st["derived_from"] = d["derived_from"]; st["current_phase"] = d["phase"] or st.get("current_phase")
            S.append_event(self.study_id, "DERIVED", code=d["code"], controller_state=d.get("controller_state"), blocker_code=d.get("blocker_code"), gap_kinds=d.get("gap_kinds"))
            return self._route(d)
        finally:
            S.save_state(st)

    def _card(self, action: str, next_action: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        st = self.state
        st["next_action"] = next_action or action
        card = {"study_id": self.study_id, "action": action, "derived_state": st.get("derived_state"), "phase": st.get("current_phase"),
                "next_action": st["next_action"], "active_worker": _brief(st.get("active_worker")), "active_job": _brief(st.get("active_job")),
                "user_intervention_required": bool(st.get("user_intervention_required")), "tick": st["counters"]["ticks"], **extra}
        return card

    # ------------------------------------------------------------------ routing
    def _route(self, d: Dict[str, Any]) -> Dict[str, Any]:
        code = d["code"]
        if code == "STUDY_CLOSED":
            return self._closed()
        if code == "USER_DECISION_REQUIRED":
            return self._card("USER_DECISION_REQUIRED", f"supervise decide {self.study_id} --answer <file>", code=d["evidence"].get("decision_code"), card=d["evidence"].get("card"))
        if code in ("WAIT_STUDY_LEASE", "RUNNING"):
            return self._card(code, "wait", **d["evidence"])
        if code == "NO_SPEC":
            return self._launch_design(reason="NO_SPEC")
        if code == "CAPABILITY_GAP":
            return self._route_gap(d)
        if code in ("COMPILED", "CONTROLLER_STEP"):
            return self._launch_job("seal", heavy=False)
        if code == "NEEDS_CAUSAL_AUDIT":
            return self._launch_audit("CAUSAL_AUDIT", d)
        if code == "NEEDS_CONTRACT_AUDIT":
            return self._launch_audit("CONTRACT_AUDIT", d)
        if code in ("DETERMINISTIC_BLOCKER", "AUDIT_BLOCKER"):
            return self._launch_repair(d)
        if code == "EXECUTION_BLOCKER":
            return self._launch_triage(d)
        if code == "SEMANTIC_BLOCKER":
            bc = d.get("blocker_code") or "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED"
            return self._user_decision(bc if bc in D.USER_INTERVENTION_CODES else "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED",
                                       f"the controller reported {bc} at stage {d['evidence'].get('stage')}; answer with the scientific decision", d)
        if code == "READY_TO_EXECUTE":
            return self._launch_job("analyze", heavy=True)
        if code == "EXECUTION_NOT_AUTHORIZED":
            return self._user_decision("AUTHORIZATION_AMBIGUITY", "the study is sealed (READY_TO_SMOKE) but the supervisor was started without --execute-authorized; "
                                       "answer {\"execute_authorized\": true} to run smoke..analyze, false to stop here", d)
        if code == "READY_FOR_ANALYSIS":
            return self._launch_analysis(d)
        if code == "ANALYSIS_DECIDED":
            return self._launch_job("close", heavy=False, closure=d["evidence"])
        return self._escalate(f"UNROUTED_STATE: {code}", d)

    def _plan_only(self, d: Dict[str, Any]) -> str:
        code = d["code"]
        table = {"NO_SPEC": "launch STUDY_DESIGN_COMPILE", "CAPABILITY_GAP": "capability flow / design", "COMPILED": "controller --through seal",
                 "CONTROLLER_STEP": "controller --through seal", "NEEDS_CAUSAL_AUDIT": "launch CAUSAL_AUDIT", "NEEDS_CONTRACT_AUDIT": "launch CONTRACT_AUDIT",
                 "DETERMINISTIC_BLOCKER": "launch DETERMINISTIC_REPAIR", "AUDIT_BLOCKER": "launch DETERMINISTIC_REPAIR", "EXECUTION_BLOCKER": "launch EXECUTION_TRIAGE",
                 "READY_TO_EXECUTE": "controller --through analyze (detached)", "EXECUTION_NOT_AUTHORIZED": "USER_DECISION AUTHORIZATION_AMBIGUITY",
                 "READY_FOR_ANALYSIS": "launch ANALYSIS_DECISION", "ANALYSIS_DECIDED": "controller --through close", "STUDY_CLOSED": "terminal",
                 "WAIT_STUDY_LEASE": "WAIT_STUDY_LEASE", "RUNNING": "wait", "SEMANTIC_BLOCKER": "USER_DECISION"}
        return table.get(code, code)

    # ------------------------------------------------------------------ gap routing / capability flow
    def _route_gap(self, d: Dict[str, Any]) -> Dict[str, Any]:
        kinds = set(d.get("gap_kinds") or [])
        cap = self.state.get("active_capability")
        if cap or (kinds & set(D.PLATFORM_GAP_KINDS)):
            return self._capability_step(d)
        key = f"STUDY_DESIGN_COMPILE:{d.get('handoff_sha256') or 'card'}"
        if kinds & set(D.SEMANTIC_GAP_KINDS):
            decision = _yaml(self.study_dir / "research_decision.yaml")
            semantic = [g for g in d.get("gaps") or [] if g.get("kind") in D.SEMANTIC_GAP_KINDS]
            if not D.decision_resolves(decision, semantic) or self._attempts(key) >= 1:
                return self._user_decision("SCIENTIFIC_SEMANTIC_DECISION_REQUIRED",
                                           "compile raised a semantic gap that research_decision.yaml does not resolve: " +
                                           "; ".join(f"{g.get('kind')} at {g.get('where')}: {g.get('message')}" for g in semantic), d)
        if self._attempts(key) >= MAX_ATTEMPTS:
            return self._escalate(f"design worker could not resolve the study-side gap after {MAX_ATTEMPTS} attempts", d)
        return self._launch_design(reason="STUDY_SIDE_GAP:" + ",".join(sorted(kinds)), attempt_key=key, gaps=d.get("gaps"))

    def _capability_step(self, d: Dict[str, Any]) -> Dict[str, Any]:
        st = self.state
        cap = st.get("active_capability")
        if cap is None:
            ev = d.get("evidence") or {}
            handoff = self.study_dir / "CAPABILITY_GAP_HANDOFF.json"
            if not handoff.is_file():   # the controller card reported the gap but no handoff exists yet: the design worker writes it via compile
                return self._launch_design(reason="CAPABILITY_GAP_WITHOUT_HANDOFF", attempt_key="STUDY_DESIGN_COMPILE:handoff")
            doc = S.read_json(handoff)
            topic = _slug(str(ev.get("topic") or doc.get("proposed_chore_topic") or f"{self.study_id}-gap"))
            paths = list(ev.get("suggested_files") or doc.get("suggested_platform_files") or ["research_workflow/grammar/compiler.py"])
            key = f"CAPABILITY:{d.get('handoff_sha256')}"
            if self._attempts(key) >= MAX_ATTEMPTS:
                return self._escalate(f"capability {topic} failed {MAX_ATTEMPTS} implementation attempts", d)
            from research_workflow.workspace import WorkspaceError, claim_chore
            try:
                claim = claim_chore(topic, repo_root=self.repo_root, write_paths=paths, semantic_surface=f"capability for study {self.study_id}: {', '.join(d.get('gap_kinds') or [])}",
                                    capability_ids=[str(g.get("closest")) for g in (doc.get("gaps") or []) if g.get("closest")], identity=self.identity)
            except WorkspaceError as exc:
                if "PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT" in str(exc):
                    S.append_event(self.study_id, "WAIT_CHORE", topic=topic, reason=str(exc)[:300])
                    return self._card("WAIT_CHORE", "wait for the other writer's chore claim to release", topic=topic)
                return self._escalate(f"chore claim failed: {exc}", d)
            branch = f"chore/{topic}"
            wt = Path(str(claim.get("worktree_expected") or claim.get("worktree") or (self.repo_root.parent / f"{self.repo_root.name}-{topic}")))
            lock = R.MainMergeLock(self.study_id, f"worktree_add:{branch}")
            with lock as ok:
                if not ok:
                    return self._card("WAIT_MERGE_LOCK", "wait", holder=_brief(lock.holder))
                if not wt.is_dir():
                    exists = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], self.repo_root).returncode == 0
                    _git(["worktree", "add", *([] if exists else ["-b", branch]), str(wt), *([branch] if exists else ["main"])], self.repo_root, check=True)
            cap = {"topic": topic, "chore_branch": branch, "chore_worktree": str(wt), "handoff_path": str(handoff), "handoff_sha256": d.get("handoff_sha256"),
                   "write_paths": paths, "status": "implementing", "attempt_key": key, "started_at_utc": S.now_utc(),
                   "base_commit": _git(["merge-base", "main", branch], self.repo_root).stdout.strip() or None}
            st["active_capability"] = cap
            S.append_event(self.study_id, "CAPABILITY_CLAIMED", **{k: cap[k] for k in ("topic", "chore_branch", "chore_worktree", "write_paths")})
        status = cap.get("status")
        if status in ("implementing", "implemented", "approved") and not st.get("active_worker"):
            # a capability merged while the supervisor was offline is detected from git, never from state:
            # the chore branch has commits of its own (beyond the main it branched from) and main contains all of them
            own = _git(["rev-list", "--count", f"{cap.get('base_commit') or 'main'}..{cap['chore_branch']}"], self.repo_root).stdout.strip()
            unmerged = _git(["rev-list", "--count", f"main..{cap['chore_branch']}"], self.repo_root).stdout.strip()
            if own.isdigit() and int(own) > 0 and unmerged == "0":
                cap["status"] = status = "merged"; cap["merged_commit"] = _git(["rev-parse", "main"], self.repo_root).stdout.strip(); cap["merged_offline"] = True
                S.append_event(self.study_id, "CAPABILITY_MERGED", topic=cap["topic"], detected_from_git=True, main_after=cap["merged_commit"])
        if status == "implementing":
            if st.get("active_worker"):
                return self._card("WAITING_WORKER", "wait")
            if self._attempts(cap["attempt_key"]) >= MAX_ATTEMPTS:
                return self._escalate(f"capability {cap['topic']} failed {MAX_ATTEMPTS} implementation attempts", d)
            return self._launch_capability_worker(cap, d)
        if status == "implemented":
            gate = self._merge_gate(cap)
            cap["merge_gate"] = gate
            if not gate["green"]:
                cap["status"] = "implementing"
                self._attempts(cap["attempt_key"], bump=True)
                S.append_event(self.study_id, "MERGE_GATE_RED", topic=cap["topic"], reasons=gate["reasons"])
                if self._attempts(cap["attempt_key"]) >= MAX_ATTEMPTS:
                    return self._escalate(f"capability {cap['topic']} is not mergeable: {gate['reasons']}", d)
                return self._card("MERGE_GATE_RED", "relaunch capability worker", reasons=gate["reasons"])
            if gate["policy"] == "auto_if_green":
                cap["status"] = "approved"
            else:
                return self._user_decision("DESTRUCTIVE_ACTION_REQUIRES_APPROVAL",
                                           f"merge chore/{cap['topic']} -> main (gate green: {gate['checks']}); research_decision.yaml does not declare "
                                           f"autonomy_decisions.platform_merge: auto_if_green; answer {{\"approve\": true|false}}", d)
        if cap.get("status") == "approved":
            return self._merge_capability(cap)
        if cap.get("status") == "merged":
            return self._finish_capability(cap)
        if cap.get("status") == "rejected":
            st["terminal"] = True
            return self._card("TERMINAL", "capability merge rejected by the user")
        return self._escalate(f"unknown capability status {status}", d)

    def _merge_gate(self, cap: Dict[str, Any]) -> Dict[str, Any]:
        reasons: List[str] = []; checks: Dict[str, Any] = {}
        card = S.read_json(Path(cap.get("result_path") or ""))
        checks["result_status"] = card.get("status")
        if card.get("status") != "DONE":
            reasons.append(f"result status {card.get('status')}")
        wt = Path(cap["chore_worktree"])
        diff = _git(["diff", "--name-only", f"main...{cap['chore_branch']}"], self.repo_root).stdout.split()
        outside = [f for f in diff if not _within(f, cap["write_paths"])]
        checks["diff_files"] = diff; checks["outside_write_surface"] = outside
        if outside:
            reasons.append(f"diff outside the claimed write surface: {outside}")
        if not diff:
            reasons.append("empty diff against main")
        tests = card.get("tests") or {}
        checks["test_delta_new_failures"] = tests.get("new_failures")
        if tests.get("new_failures") != 0:
            reasons.append(f"test_delta new_failures={tests.get('new_failures')!r} (must be 0)")
        head = _git(["rev-parse", cap["chore_branch"]], self.repo_root).stdout.strip()
        checks["chore_head"] = head; checks["card_head"] = card.get("head_commit")
        if card.get("head_commit") and head and card.get("head_commit") != head:
            reasons.append("chore branch moved after the result card was written")
        if _git(["status", "--porcelain", "--untracked-files=no"], wt).stdout.strip():
            reasons.append("chore worktree dirty (uncommitted changes)")
        cmd = self.options.get("merge_gate_cap_check", "default")
        if cmd == "default":
            cmd = [sys.executable, "scripts/research.py", "cap", "generate", "--check"]
        if cmd:
            r = subprocess.run(list(cmd), cwd=str(wt), capture_output=True, text=True, encoding="utf-8", errors="replace")
            checks["cap_generate_check"] = {"rc": r.returncode, "tail": (r.stdout or r.stderr)[-300:]}
            if r.returncode != 0:
                reasons.append("cap generate --check is not clean")
        else:
            checks["cap_generate_check"] = "skipped"
        decision = _yaml(self.study_dir / "research_decision.yaml")
        policy = str((decision.get("autonomy_decisions") or {}).get("platform_merge") or "approval_required")
        return {"green": not reasons, "reasons": reasons, "checks": checks, "policy": policy}

    def _merge_capability(self, cap: Dict[str, Any]) -> Dict[str, Any]:
        with R.MainMergeLock(self.study_id, f"merge:{cap['chore_branch']}") as ok:
            if not ok:
                S.append_event(self.study_id, "WAIT_MERGE_LOCK", operation="merge_capability")
                return self._card("WAIT_MERGE_LOCK", "wait")
            root = self.repo_root
            if _git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip() != "main":
                return self._escalate(f"canonical checkout {root} is not on main; cannot merge {cap['chore_branch']}", None)
            if _git(["status", "--porcelain", "--untracked-files=no"], root).stdout.strip():
                return self._escalate(f"canonical checkout {root} is dirty; cannot merge {cap['chore_branch']}", None)
            before = _git(["rev-parse", "main"], root).stdout.strip()
            r = _git(["merge", "--no-ff", cap["chore_branch"], "-m", f"merge(chore/{cap['topic']}): capability for study {self.study_id} (supervisor, gate green)"], root)
            if r.returncode != 0:
                _git(["merge", "--abort"], root)
                return self._escalate(f"merge of {cap['chore_branch']} into main failed: {(r.stderr or r.stdout)[:300]}", None)
            after = _git(["rev-parse", "main"], root).stdout.strip()
        cap["status"] = "merged"; cap["merged_commit"] = after; cap["main_before"] = before
        S.append_event(self.study_id, "CAPABILITY_MERGED", topic=cap["topic"], main_before=before, main_after=after)
        return self._card("CAPABILITY_MERGED", "release chore claim, merge main into study, relaunch design", main=after)

    def _finish_capability(self, cap: Dict[str, Any]) -> Dict[str, Any]:
        from research_workflow.workspace import WorkspaceError, release_chore
        try:
            release_chore(cap["topic"], identity=self.identity)
        except WorkspaceError as exc:
            S.append_event(self.study_id, "CHORE_RELEASE_SKIPPED", reason=str(exc)[:200])
        r = self._merge_main_into_study()
        if r is not None:
            return r
        self.state.setdefault("consumed_handoffs", []).append(cap.get("handoff_sha256"))
        self.state.setdefault("capability_history", []).append({k: cap.get(k) for k in ("topic", "chore_branch", "merged_commit", "handoff_sha256")})
        self.state["active_capability"] = None
        S.append_event(self.study_id, "CAPABILITY_COMPLETE", topic=cap["topic"])
        try:
            from research_workflow.handoff import write_session_handoff
            write_session_handoff(self.study_dir, "A", repo_root=self.repo_root, note=f"CAPABILITY_COMPLETE:{cap['topic']}")
        except Exception as exc:  # bookkeeping only
            S.append_event(self.study_id, "HANDOFF_WRITE_FAILED", error=str(exc)[:200])
        return self._card("CAPABILITY_COMPLETE", "launch STUDY_DESIGN_COMPILE", topic=cap["topic"])

    def _merge_main_into_study(self) -> Optional[Dict[str, Any]]:
        with R.MainMergeLock(self.study_id, "merge_main_into_study") as ok:
            if not ok:
                return self._card("WAIT_MERGE_LOCK", "wait")
            wt = self.worktree
            if _git(["status", "--porcelain", "--untracked-files=no"], wt).stdout.strip():
                return self._escalate(f"study worktree {wt} is dirty; cannot merge main into it", None)
            r = _git(["merge", "--no-ff", "main", "-m", f"merge(main): platform capability into study {self.study_id} (supervisor)"], wt)
            if r.returncode != 0:
                _git(["merge", "--abort"], wt)
                return self._escalate(f"merging main into the study worktree failed: {(r.stderr or r.stdout)[:300]}", None)
            S.append_event(self.study_id, "MAIN_MERGED_INTO_STUDY", head=_git(["rev-parse", "HEAD"], wt).stdout.strip())
        return None

    # ------------------------------------------------------------------ worker launches
    def _common_reads(self) -> List[str]:
        sid = self.study_id
        files = ["WORKFLOW.md (section N, then the section your task names)", "PLATFORM_STATE.json", f"studies/{sid}/research_decision.yaml", f"studies/{sid}/study.yaml"]
        for rel in (f"studies/{sid}/compiled_plan.json", f"studies/{sid}/_work/controller/status.json", f"studies/{sid}/_work/handoff/SESSION_HANDOFF.json",
                    f"studies/{sid}/CAPABILITY_GAP_HANDOFF.json"):
            if (self.worktree / rel).is_file():
                files.append(rel)
        for p in (self.state.get("user_answers") or []):
            files.append(str(p))
        hist = self.state.get("worker_history") or []
        if hist and hist[-1].get("result_path"):
            files.append(str(hist[-1]["result_path"]))
        return files

    def _launch_design(self, *, reason: str, attempt_key: Optional[str] = None, gaps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        key = attempt_key or "STUDY_DESIGN_COMPILE:default"
        if self._attempts(key) >= MAX_ATTEMPTS:
            return self._escalate(f"design worker exhausted {MAX_ATTEMPTS} attempts ({reason})", None)
        q = self.state.get("question_path")
        task = (f"PHASE A (WORKFLOW.md section N.2). Reason: {reason}. Produce a compiling study.yaml for the research question"
                f"{' in ' + q if q else ''} by composing REGISTERED primitives (`python scripts/research.py cap search/describe`; never guess ids). "
                f"Declare scientific decisions in research_decision.yaml (terminal_decisions / autonomy_decisions). Run "
                f"`python scripts/research.py study compile --study studies/{self.study_id}`. If it returns a CapabilityGap that needs platform work the CLI "
                f"has written CAPABILITY_GAP_HANDOFF.*: commit study.yaml + research_decision.yaml + the handoff and STOP (status BLOCKED, blocker_code CAPABILITY_GAP). "
                f"A study-side gap (INVALID_PARAMETERIZATION, AMBIGUOUS_TEMPORAL_SEMANTICS, SEMANTIC_DECISION_REQUIRED covered by research_decision.yaml) you fix and recompile. "
                f"Commit compiled_plan.json on success (status DONE). Never write research_workflow/, features/ or study Python.")
        if gaps:
            task += "\n\nGaps to resolve: " + json.dumps(gaps, default=str)[:2000]
        return self._launch_worker("STUDY_DESIGN_COMPILE", task=task, attempt_key=key,
                                   stop=["compiled_plan.json written (DONE)", "CAPABILITY_GAP_HANDOFF written (BLOCKED CAPABILITY_GAP)",
                                         "a semantic decision no declared policy resolves (BLOCKED SCIENTIFIC_SEMANTIC_DECISION_REQUIRED; do NOT decide it)"],
                                   extra={"reason": reason, "question_path": q})

    def _launch_capability_worker(self, cap: Dict[str, Any], d: Dict[str, Any]) -> Dict[str, Any]:
        task = (f"CAPABILITY_IMPLEMENTATION (WORKFLOW.md section N.1) on branch {cap['chore_branch']} in worktree {cap['chore_worktree']}. "
                f"Implement ONLY the capability described in {cap['handoff_path']} (gap kinds: {', '.join(d.get('gap_kinds') or [])}). Write only inside the claimed surface "
                f"{cap['write_paths']}. Add targeted tests; run `python scripts/test_delta.py <scopes>` (report new_failures in --tests-json); run "
                f"`python scripts/research.py cap generate --check`; run cap promotion when the capability flow requires it; COMMIT on the chore branch. "
                f"Do NOT merge to main (the supervisor's merge gate does). Do NOT touch studies/.")
        return self._launch_worker("CAPABILITY_IMPLEMENTATION", task=task, attempt_key=cap["attempt_key"], worktree_override=Path(cap["chore_worktree"]),
                                   stop=["capability implemented, tests green, committed (DONE)", "the handoff asks for a semantic decision (BLOCKED)"],
                                   extra={"handoff": cap["handoff_path"], "write_paths": cap["write_paths"], "chore_branch": cap["chore_branch"]},
                                   on_launch=lambda h: cap.update({"task_id": h["task_id"], "result_path": h["result_path"]}))

    def _launch_audit(self, session_type: str, d: Dict[str, Any]) -> Dict[str, Any]:
        kind = "causal" if session_type == "CAUSAL_AUDIT" else "contract"
        key = f"{session_type}:{d['evidence'].get('frozen_composite')}"
        if self._attempts(key) >= MAX_ATTEMPTS:
            return self._escalate(f"{session_type} worker failed {MAX_ATTEMPTS} times", d)
        task_id = self._new_task_id(session_type)
        report = self.dir / "results" / f"{task_id}.report.md"
        auditor = f"{P.ROLES[session_type]['role']}:{task_id}"
        task = (f"PHASE B {kind.upper()} AUDIT, READ-ONLY. Read the compact packet {d['evidence'].get('packet')} (never the whole repository) and audit it per your role file. "
                f"Write your report to {report} (NOT under studies/). End it with the AUDIT_SUMMARY_V2 block: "
                f"{{\"verdict\": CLEAR|BLOCKED, \"audit_type\": \"{kind}\", \"study\": \"{self.study_id}\", \"auditor\": \"{auditor}\", "
                f"\"audited_execution_composite_sha256\": \"{d['evidence'].get('frozen_composite')}\", \"critical\": n, \"warning\": n, \"note\": n}} between "
                f"<!-- AUDIT_SUMMARY_V2_START --> and <!-- AUDIT_SUMMARY_V2_END -->. Then write the result card with --report {report}. Mutate nothing in the study worktree.")
        return self._launch_worker(session_type, task=task, attempt_key=key, task_id=task_id, auditor=auditor,
                                   stop=["report written with a verdict (DONE)", "packet unreadable/incomplete (FAILED)"],
                                   extra={"audit_packet": d["evidence"].get("packet"), "report_path": str(report), "frozen_composite": d["evidence"].get("frozen_composite")})

    def _launch_repair(self, d: Dict[str, Any]) -> Dict[str, Any]:
        bc = d.get("blocker_code") or "DETERMINISTIC"
        key = f"DETERMINISTIC_REPAIR:{bc}:{d['evidence'].get('stage')}"
        if self._attempts(key) >= MAX_ATTEMPTS or self.state.get("blocker_streak", 0) >= MAX_ATTEMPTS:
            return self._escalate(f"blocker {bc} at {d['evidence'].get('stage')} persisted after independent repair attempts", d)
        task = (f"DETERMINISTIC_REPAIR (autonomy_decisions.deterministic_defect: auto_fix). The controller is BLOCKED with {bc} at stage {d['evidence'].get('stage')}. "
                f"Read studies/{self.study_id}/_work/controller/status.json, the failure packet it names, the stage log under _work/controller/logs/ and, for an audit blocker, "
                f"the audit report under studies/{self.study_id}/audit/. Trace to the FIRST broken stage. Repair a STUDY-SIDE defect (study.yaml, research_decision.yaml) and re-run the bounded "
                f"check (`python scripts/run_governed_study.py --study studies/{self.study_id} --through seal`). If the defect is in shared platform code, do NOT fix it here: "
                f"write the evidence and exit BLOCKED with blocker_code PLATFORM_DEFECT. Commit on the study branch.")
        return self._launch_worker("DETERMINISTIC_REPAIR", task=task, attempt_key=key,
                                   stop=["controller no longer BLOCKED on this code (DONE)", "platform defect (BLOCKED PLATFORM_DEFECT)"], extra={"blocker_code": bc, "stage": d["evidence"].get("stage")})

    def _launch_triage(self, d: Dict[str, Any]) -> Dict[str, Any]:
        key = f"EXECUTION_TRIAGE:{d.get('blocker_code')}:{d['evidence'].get('stage')}"
        if self._attempts(key) >= MAX_ATTEMPTS:
            return self._escalate(f"execution blocker at {d['evidence'].get('stage')} persisted after triage", d)
        task = (f"EXECUTION_TRIAGE, READ-ONLY. A post-seal controller stage ({d['evidence'].get('stage')}) failed. Read studies/{self.study_id}/_work/controller/status.json, "
                f"the failure packet, the stage log and receipts. Classify: transient/environmental (next_exact_action: rerun), study-side defect (next_state DETERMINISTIC_REPAIR), "
                f"platform defect (BLOCKED PLATFORM_DEFECT), or data-safety risk (BLOCKED DATA_SAFETY_RISK). Never re-run stages by hand.")
        return self._launch_worker("EXECUTION_TRIAGE", task=task, attempt_key=key, stop=["classification written (DONE)"], extra={"stage": d["evidence"].get("stage")})

    def _launch_analysis(self, d: Dict[str, Any]) -> Dict[str, Any]:
        key = "ANALYSIS_DECISION:default"
        if self._attempts(key) >= MAX_ATTEMPTS:
            return self._escalate("analysis worker failed twice", d)
        task = (f"PHASE D ANALYSIS_DECISION. Read the generated artifacts under studies/{self.study_id}/artifacts/ (experiment_analysis_v2.json, models, freeze) per your role file; "
                f"never fit, tune or re-run. Decide what they mean and write studies/{self.study_id}/artifacts/analysis_decision.json "
                f"{{\"outcome\": <short label>, \"terminal_decision\": <short label>, \"rationale\": ..., \"evidence\": [...]}} plus analysis_decision.md. "
                f"Commit them on the study branch. The supervisor closes the study with those two labels.")
        return self._launch_worker("ANALYSIS_DECISION", task=task, attempt_key=key, stop=["analysis_decision.json written and committed (DONE)"], extra={})

    def _launch_worker(self, session_type: str, *, task: str, attempt_key: str, stop: List[str], extra: Dict[str, Any], task_id: Optional[str] = None,
                       worktree_override: Optional[Path] = None, auditor: Optional[str] = None, on_launch=None) -> Dict[str, Any]:
        st = self.state
        if st.get("active_worker"):
            return self._card("WAITING_WORKER", "wait")
        role = P.ROLES[session_type]
        task_id = task_id or self._new_task_id(session_type)
        provider = str(st["provider"])
        probe = (st.get("providers") or {}).get(provider) or PR.probe_provider(provider)
        if provider not in PR.ATTENDED_PROVIDERS and provider != "scripted":
            need = "READ_ONLY_SUPPORTED" if role["read_only"] else "WRITE_SUPPORTED"
            if not (probe.get("AVAILABLE") and probe.get("HEADLESS_SUPPORTED") and probe.get(need)):
                return self._escalate(f"PROVIDER_CAPABILITY_UNAVAILABLE: {provider} lacks {need} (probe: {probe.get('error') or probe.get('flags')})", None)
        slot = R.acquire_slot("workers", max_slots=int(self.options.get("max_workers") or R.DEFAULT_MAX_WORKERS), study_id=self.study_id, task_id=task_id)
        if slot is None:
            S.append_event(self.study_id, "WAIT_RESOURCE", resource="workers", task_id=task_id)
            return self._card("WAIT_RESOURCE", "wait for a worker slot", kind="workers")
        worker_identity = _identity(provider, str(uuid.uuid4()))
        wt = Path(worktree_override or self.worktree)
        results_dir = self.dir / "results"
        result_path = results_dir / f"{task_id}.result.json"
        packet_path = self.dir / "packets" / f"{task_id}.md"
        body = P.build_packet(task_id=task_id, session_type=session_type, study_id=self.study_id, study_dir=self.study_dir, study_worktree=self.worktree,
                              repo_root=self.repo_root, provider=provider, identity=worker_identity, result_path=result_path, results_dir=results_dir, task=task,
                              read_files=self._common_reads() + ([role["role_file"]] if role["role_file"] else []), stop_conditions=stop, extra=extra,
                              worktree_override=worktree_override, auditor=auditor)
        P.render_packet(body, packet_path)
        size = packet_path.stat().st_size
        st["counters"]["max_packet_bytes"] = max(int(st["counters"].get("max_packet_bytes") or 0), size)
        lease_handoff = None
        if not role["read_only"] and worktree_override is None:
            lease_handoff = self._hand_lease_to(worker_identity)
        wt_status = _git(["status", "--porcelain"], wt).stdout if role["read_only"] else None
        try:
            handle = PR.launch_worker(provider, role=role["role"], worktree=wt, packet_path=packet_path, identity=worker_identity, result_path=result_path,
                                      read_only=bool(role["read_only"]), timeout_s=float(self.options.get("worker_timeout_s") or DEFAULT_WORKER_TIMEOUT_S),
                                      log_path=self.dir / "logs" / f"{task_id}.log", results_dir=results_dir, task_id=task_id, probe=probe,
                                      scripted_command=self.options.get("scripted_worker"))
        except PR.ProviderError as exc:
            R.release_slot(slot)
            if lease_handoff:
                self._take_lease_back(worker_identity)
            return self._escalate(str(exc), None)
        self._attempts(attempt_key, bump=True)
        aw = {"role": role["role"], "session_type": session_type, "task_id": task_id, "provider": provider, "session_id": worker_identity["session_id"],
              "pid": handle.pid, "started_at_utc": handle.started_at_utc, "packet_path": str(packet_path), "result_path": str(result_path),
              "deadline_utc": handle.deadline_utc, "attended": handle.attended, "attempt_key": attempt_key, "slot": str(slot), "read_only": bool(role["read_only"]),
              "worktree": str(wt), "worktree_status_before": wt_status, "lease_handoff": lease_handoff, "packet_bytes": size, "log_path": handle.log_path}
        st["active_worker"] = aw
        st["counters"]["workers_launched"] = int(st["counters"].get("workers_launched") or 0) + 1
        st["current_phase"] = role["phase"]
        if on_launch:
            on_launch(aw)
        S.append_event(self.study_id, "WORKER_LAUNCHED", task_id=task_id, session_type=session_type, session_id=aw["session_id"], pid=handle.pid, packet_bytes=size,
                       attended=handle.attended, worktree=str(wt))
        return self._card("WORKER_LAUNCHED", "wait for the result card", task_id=task_id, session_type=session_type, attended=handle.attended)

    # ------------------------------------------------------------------ jobs
    def _controller_command(self, through: str, closure: Optional[Dict[str, Any]]) -> List[str]:
        tmpl = self.state.get("controller_command") or self.options.get("controller_command")
        if tmpl:
            cmd = [str(t).replace("{study}", str(self.study_dir)).replace("{through}", through) for t in tmpl]
        else:
            cmd = [sys.executable, str(self.repo_root / "scripts" / "run_governed_study.py"), "--study", str(self.study_dir), "--through", through, "--json",
                   "--max-runtime", str(int(self.options.get("job_timeout_s") or DEFAULT_JOB_TIMEOUT_S))]
        if self.state.get("execute_authorized"):
            cmd.append("--execute-authorized")
        if closure and through == "close":
            cmd += ["--closure-outcome", str(closure.get("outcome")), "--closure-decision", str(closure.get("terminal_decision"))]
        return cmd

    def _launch_job(self, through: str, *, heavy: bool, closure: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        st = self.state
        if st.get("active_worker"):
            return self._card("WAITING_WORKER", "wait")
        key = f"JOB:{through}"
        if self._attempts(key) > MAX_ATTEMPTS * 3:   # a job that keeps ending without a fresh card is not a science problem
            return self._escalate(f"controller job --through {through} produced no fresh status card after repeated launches", None)
        slot = None
        if heavy:
            slot = R.acquire_slot("heavy", max_slots=int(self.options.get("max_heavy_jobs") or R.DEFAULT_MAX_HEAVY_JOBS), study_id=self.study_id, task_id=key)
            if slot is None:
                S.append_event(self.study_id, "WAIT_RESOURCE", resource="heavy", through=through)
                return self._card("WAIT_RESOURCE", "wait for a heavy-job slot", kind="heavy")
        cmd = self._controller_command(through, closure)
        n = int(st["counters"].get("jobs_launched") or 0) + 1
        log = self.dir / "logs" / f"job_{n:03d}_{through}.log"
        status_path = self.study_dir / "_work" / "controller" / "status.json"
        pid = spawn_detached(cmd, cwd=self.worktree, log_path=log, env={"NT_RESEARCH_AGENT": str(st["provider"]), "NT_RESEARCH_AGENT_SESSION": str(st["supervisor_session_id"])})
        self._attempts(key, bump=True)
        st["active_job"] = {"kind": "controller", "through": through, "pid": pid, "started_at_utc": S.now_utc(), "started_epoch": time.time(),
                            "expected_artifact": str(status_path), "heavy": heavy, "slot": str(slot) if slot else None, "log_path": str(log), "command": cmd,
                            "deadline_epoch": time.time() + float(self.options.get("job_timeout_s") or DEFAULT_JOB_TIMEOUT_S)}
        st["counters"]["jobs_launched"] = n
        S.append_event(self.study_id, "JOB_LAUNCHED", through=through, pid=pid, heavy=heavy, log=str(log))
        return self._card("JOB_LAUNCHED", "wait (no AI alive)", through=through, pid=pid, heavy=heavy)

    def _reap_job(self) -> Optional[Dict[str, Any]]:
        st = self.state
        job = st["active_job"]
        if pid_alive(int(job.get("pid") or 0)):
            if time.time() > float(job.get("deadline_epoch") or 1e18):
                kill_tree(int(job["pid"]))
                S.append_event(self.study_id, "JOB_TIMEOUT", through=job.get("through"), pid=job.get("pid"))
            else:
                assert st.get("active_worker") is None
                return self._card("WAITING_JOB", "wait (no AI alive)", through=job.get("through"), pid=job.get("pid"))
        R.release_slot(Path(job["slot"]) if job.get("slot") else None)
        card_path = Path(job["expected_artifact"])
        fresh = card_path.is_file() and card_path.stat().st_mtime >= float(job.get("started_epoch") or 0) - 1
        card = S.read_json(card_path) if fresh else {}
        st["last_completed_deterministic_artifact"] = {"path": str(card_path), "sha256": P.sha256_file(card_path), "fresh": fresh, "state": card.get("state"),
                                                       "STATUS": card.get("STATUS"), "blocker_code": card.get("blocker_code"), "through": job.get("through")}
        bc = card.get("blocker_code") if card.get("STATUS") == "BLOCKED" else None
        if bc and bc == st.get("last_blocker_code"):
            st["blocker_streak"] = int(st.get("blocker_streak") or 0) + 1
        else:
            st["blocker_streak"] = 1 if bc else 0
        st["last_blocker_code"] = bc
        if card.get("STATUS") == "OK" or not bc:
            st["attempts"][f"JOB:{job.get('through')}"] = 0
        st["active_job"] = None
        S.append_event(self.study_id, "JOB_FINISHED", through=job.get("through"), fresh_card=fresh, state=card.get("state"), STATUS=card.get("STATUS"), blocker_code=bc)
        return None

    # ------------------------------------------------------------------ worker reaping / consumption
    def _reap_worker(self) -> Optional[Dict[str, Any]]:
        st = self.state
        aw = st["active_worker"]
        p = PR.poll(aw)
        if p in ("running", "attended_waiting"):
            if datetime.now(timezone.utc) > datetime.fromisoformat(aw["deadline_utc"]):
                PR.kill(aw)
                self._finish_worker(aw, status="FAILED", reason="WORKER_TIMEOUT", card=None)
                return None
            return self._card("WAITING_WORKER", "wait", task_id=aw["task_id"], attended=aw.get("attended"))
        self._consume_result(aw)
        return None

    def _consume_result(self, aw: Dict[str, Any]) -> None:
        packet = P.read_packet(Path(aw["packet_path"]))
        result_path = Path(aw["result_path"])
        card = S.read_json(result_path) if result_path.is_file() else None
        if not card:
            self._finish_worker(aw, status="FAILED", reason="RESULT_CARD_MISSING", card=None)
            return
        wt = Path(aw["worktree"])
        ok, reason, field = P.validate_result(card, packet, current_contract_sha256=P.study_contract_sha256(self.study_dir) if aw.get("read_only") else None,
                                              current_plan_sha256=P.compiled_plan_sha256(self.study_dir) if aw.get("read_only") else None,
                                              current_branch=_git(["rev-parse", "--abbrev-ref", "HEAD"], wt).stdout.strip() or None)
        if not ok:
            self._finish_worker(aw, status="FAILED", reason=reason, card=card, field=field)
            return
        if aw.get("read_only") and (_git(["status", "--porcelain"], wt).stdout != (aw.get("worktree_status_before") or "")):
            self._finish_worker(aw, status="FAILED", reason="READ_ONLY_WORKER_MUTATED_WORKTREE", card=card)
            return
        status = card.get("status")
        stype = aw["session_type"]
        if status == "DONE":
            if stype in ("CAUSAL_AUDIT", "CONTRACT_AUDIT"):
                err = self._ingest_audit(aw, packet, card)
                if err:
                    self._finish_worker(aw, status="FAILED", reason=err, card=card)
                    return
            elif stype == "CAPABILITY_IMPLEMENTATION":
                cap = self.state.get("active_capability") or {}
                cap["status"] = "implemented"; cap["result_path"] = str(result_path)
            elif stype == "ANALYSIS_DECISION":
                dec = S.read_json(self.study_dir / "artifacts" / "analysis_decision.json")
                if not (dec.get("outcome") and dec.get("terminal_decision")):
                    self._finish_worker(aw, status="FAILED", reason="ANALYSIS_DECISION_MISSING", card=card)
                    return
            self._finish_worker(aw, status="DONE", reason=None, card=card)
            return
        bc = str(card.get("blocker_code") or "")
        if status == "BLOCKED" and (bc in SEMANTIC_BLOCKER_CODES or bc in D.USER_INTERVENTION_CODES):
            self._finish_worker(aw, status="BLOCKED", reason=bc, card=card)
            self._user_decision(bc if bc in D.USER_INTERVENTION_CODES else "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED",
                                f"worker {aw['task_id']} ({stype}) stopped: {bc}: {card.get('notes') or card.get('next_exact_action') or ''}", None)
            return
        if status == "BLOCKED" and bc == "CAPABILITY_GAP":
            self._finish_worker(aw, status="BLOCKED", reason=bc, card=card)   # the handoff on disk drives the next derive
            return
        if status == "BLOCKED" and bc == "PLATFORM_DEFECT":
            self._finish_worker(aw, status="BLOCKED", reason=bc, card=card)
            self._escalate(f"worker {aw['task_id']} reports a platform defect: {card.get('notes')}", None)
            return
        self._finish_worker(aw, status=status, reason=bc or status, card=card)

    def _finish_worker(self, aw: Dict[str, Any], *, status: str, reason: Optional[str], card: Optional[Dict[str, Any]], field: Optional[str] = None) -> None:
        st = self.state
        R.release_slot(Path(aw["slot"]) if aw.get("slot") else None)
        if aw.get("lease_handoff"):
            self._take_lease_back(_identity(aw["provider"], aw["session_id"]))
        rec = {"task_id": aw["task_id"], "session_type": aw["session_type"], "session_id": aw["session_id"], "status": status, "reason": reason, "field": field,
               "result_path": aw["result_path"] if card else None, "packet_bytes": aw.get("packet_bytes"), "started_at_utc": aw.get("started_at_utc"), "finished_at_utc": S.now_utc(),
               "commits": (card or {}).get("commits"), "changed_files": (card or {}).get("changed_files")}
        st.setdefault("worker_history", []).append(rec)
        if card:
            st.setdefault("consumed_results", []).append(aw["result_path"])
        st["active_worker"] = None
        S.append_event(self.study_id, "WORKER_FINISHED", **rec)
        if status == "FAILED" and self._attempts(aw["attempt_key"]) >= MAX_ATTEMPTS:
            self._escalate(f"worker {aw['session_type']} failed {MAX_ATTEMPTS} times (last: {reason})", None)

    def _ingest_audit(self, aw: Dict[str, Any], packet: Dict[str, Any], card: Dict[str, Any]) -> Optional[str]:
        """Packet section 11.C: copy the external report into the study (next free pass_NN / contract_pass_NN) and ingest it."""
        kind = "causal" if aw["session_type"] == "CAUSAL_AUDIT" else "contract"
        report = Path(str(card.get("report") or (packet.get("extra") or {}).get("report_path") or ""))
        if not report.is_file():
            return "AUDIT_REPORT_MISSING"
        if self.study_dir in report.resolve().parents:
            return "AUDIT_REPORT_INSIDE_STUDY (read-only auditors write outside studies/<id>)"
        audit_dir = self.study_dir / "audit"; audit_dir.mkdir(parents=True, exist_ok=True)
        prefix = "pass_" if kind == "causal" else "contract_pass_"
        n = 1
        while (audit_dir / f"{prefix}{n:02d}.md").exists():
            n += 1
        dest = audit_dir / f"{prefix}{n:02d}.md"
        shutil.copyfile(report, dest)
        try:
            from research_workflow.lifecycle_v2 import ingest_audit_report
            out = ingest_audit_report(self.study_dir, kind, dest, packet.get("auditor"))
        except Exception as exc:
            return f"AUDIT_INGEST_FAILED: {type(exc).__name__}: {str(exc)[:200]}"
        S.append_event(self.study_id, "AUDIT_INGESTED", audit_type=kind, report=str(dest), report_sha256=P.sha256_file(dest), verdict=out.get("verdict"), auditor=out.get("auditor"))
        return None

    # ------------------------------------------------------------------ leases
    def _hand_lease_to(self, worker_identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from research_workflow.workspace import WorkspaceError, claim_worktree, read_leases, release_lease, same_writer
        lease = next((l for l in read_leases() if l.get("study_id") == self.study_id), None)
        try:
            if lease and lease.get("state") == "live":
                if same_writer(lease, self.identity):
                    release_lease(self.study_id, owner=self.identity["owner"], identity=self.identity)
                elif not same_writer(lease, worker_identity):
                    return None   # foreign live lease: derive() reports WAIT_STUDY_LEASE before we get here
            claim_worktree(self.study_id, repo_root=self.repo_root, identity=worker_identity)
            return {"from": self.identity["session_id"], "to": worker_identity["session_id"]}
        except WorkspaceError as exc:
            S.append_event(self.study_id, "LEASE_HANDOFF_FAILED", error=str(exc)[:200])
            return None

    def _take_lease_back(self, worker_identity: Dict[str, Any]) -> None:
        from research_workflow.workspace import WorkspaceError, claim_worktree, read_leases, release_lease, same_writer
        try:
            lease = next((l for l in read_leases() if l.get("study_id") == self.study_id), None)
            if lease and lease.get("state") == "live" and same_writer(lease, worker_identity):
                release_lease(self.study_id, owner=worker_identity["owner"], identity=worker_identity)
            claim_worktree(self.study_id, repo_root=self.repo_root, identity=self.identity)
        except WorkspaceError as exc:
            S.append_event(self.study_id, "LEASE_TAKEBACK_FAILED", error=str(exc)[:200])

    # ------------------------------------------------------------------ terminal / intervention
    def _closed(self) -> Dict[str, Any]:
        st = self.state
        if not st.get("terminal"):
            try:
                from research_workflow.handoff import write_session_handoff
                write_session_handoff(self.study_dir, "D", repo_root=self.repo_root, note="SUPERVISOR_STUDY_CLOSED")
            except Exception as exc:
                S.append_event(self.study_id, "HANDOFF_WRITE_FAILED", error=str(exc)[:200])
            decision = _yaml(self.study_dir / "research_decision.yaml")
            merged = None
            if str((decision.get("autonomy_decisions") or {}).get("closed_study_merge") or "") == "auto_if_clean":
                merged = self._merge_closed_study()
            st["terminal"] = True; st["current_phase"] = "D"
            S.append_event(self.study_id, "STUDY_CLOSED", merged=merged)
            self._notify("Research supervisor", f"{self.study_id}: STUDY_CLOSED")
        return self._card("STUDY_CLOSED", f"git switch main && git merge --no-ff {st['study_branch']}  (WORKFLOW.md section M.6)", terminal=True)

    def _merge_closed_study(self) -> Optional[str]:
        with R.MainMergeLock(self.study_id, f"merge_closed_study:{self.state['study_branch']}") as ok:
            if not ok:
                return None
            root = self.repo_root
            if _git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip() != "main" or _git(["status", "--porcelain", "--untracked-files=no"], root).stdout.strip():
                return None
            if _git(["status", "--porcelain", "--untracked-files=no"], self.worktree).stdout.strip():
                return None
            r = _git(["merge", "--no-ff", self.state["study_branch"], "-m", f"merge(study/{self.study_id}): STUDY_CLOSED (supervisor)"], root)
            if r.returncode != 0:
                _git(["merge", "--abort"], root)
                return None
            return _git(["rev-parse", "main"], root).stdout.strip()

    def _user_decision(self, code: str, question: str, d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        st = self.state
        n = int(st["counters"].get("user_interventions") or 0) + 1
        st["counters"]["user_interventions"] = n
        card_path = self.dir / "results" / f"USER_DECISION_{n:02d}.json"
        doc = {"kind": "USER_DECISION_REQUIRED", "code": code, "study_id": self.study_id, "question": question, "derived": {k: (d or {}).get(k) for k in ("code", "evidence", "gap_kinds")},
               "answer_with": f"python scripts/research.py supervise decide {self.study_id} --answer <json file>", "raised_at_utc": S.now_utc()}
        S.atomic_write_json(card_path, doc)
        card_path.with_suffix(".md").write_text(f"# USER_DECISION_REQUIRED {code} -- {self.study_id}\n\n{question}\n\nAnswer: `{doc['answer_with']}`\n", encoding="utf-8")
        st["user_decision"] = {"code": code, "question": question, "card_path": str(card_path), "answered": False, "raised_at_utc": doc["raised_at_utc"]}
        st["user_intervention_required"] = True
        S.append_event(self.study_id, "USER_DECISION_REQUIRED", code=code, card=str(card_path))
        self._notify("Research supervisor: decision needed", f"{self.study_id}: {code}")
        return self._card("USER_DECISION_REQUIRED", f"supervise decide {self.study_id} --answer <file>", code=code, card=str(card_path))

    def _escalate(self, reason: str, d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return self._user_decision("SUPERVISOR_ESCALATION_REQUIRED", reason + " -- answer {\"retry\": true} to reset the attempt counters, anything else to stop", d)

    def _notify(self, title: str, message: str) -> None:
        if os.environ.get("NT_RESEARCH_SUPERVISOR_NO_TOAST") or not sys.platform.startswith("win") or self.options.get("toast") is False:
            return
        script = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  f"$n=$t.GetElementsByTagName('text');$n.Item(0).AppendChild($t.CreateTextNode('{title}'))|Out-Null;$n.Item(1).AppendChild($t.CreateTextNode('{message}'))|Out-Null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Research Supervisor').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # ------------------------------------------------------------------ helpers
    def _attempts(self, key: str, *, bump: bool = False) -> int:
        a = self.state.setdefault("attempts", {})
        if bump:
            a[key] = int(a.get(key) or 0) + 1
        return int(a.get(key) or 0)

    def _new_task_id(self, session_type: str) -> str:
        n = int(self.state["counters"].get("workers_launched") or 0) + 1
        return f"{n:03d}_{session_type.lower()}_{uuid.uuid4().hex[:8]}"

    def _loop_pid(self) -> Optional[int]:
        p = self.dir / "pid"
        try:
            return int(p.read_text(encoding="utf-8").strip()) if p.is_file() else None
        except ValueError:
            return None

    def write_loop_pid(self) -> None:
        (self.dir / "pid").write_text(str(os.getpid()), encoding="utf-8")

    def is_waiting(self, card: Dict[str, Any]) -> bool:
        return str(card.get("action", "")).startswith(("WAIT", "USER_DECISION", "STOPPED", "TERMINAL", "STUDY_CLOSED"))

    def is_settled(self) -> bool:
        return bool(self.state.get("terminal") or self.state.get("stopped") or self.state.get("user_intervention_required"))


# ---------------------------------------------------------------------- module helpers
def _identity(agent: str, session_id: str) -> Dict[str, Any]:
    """user@host exactly as research_workflow.workspace resolves it (so lease ownership compares equal), with the agent
    and session id the supervisor assigns."""
    from research_workflow.workspace import writer_identity
    base = writer_identity()
    return {"user": base["user"], "host": base["host"], "owner": base["owner"], "agent": str(agent), "session_id": str(session_id),
            "agent_source": "supervisor", "session_source": "supervisor"}


def _resolve_provider(provider: Optional[str]) -> str:
    if provider:
        p = str(provider).lower()
        if p not in PR.PROVIDERS:
            raise SupervisorError(f"UNKNOWN_PROVIDER: {provider} (expected one of {PR.PROVIDERS})")
        return p
    from research_workflow.workspace import writer_identity
    agent = str(writer_identity().get("agent") or "human")
    return agent if agent in PR.PROVIDERS else "human"


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", text.strip()).strip("_")
    return s[:60] or "study"


def _brief(obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not obj:
        return None
    keep = ("task_id", "session_type", "role", "session_id", "pid", "started_at_utc", "deadline_utc", "attended", "through", "heavy", "kind", "status", "study_id", "operation")
    return {k: obj.get(k) for k in keep if k in obj}


def run_loop(study_ids: Optional[Sequence[str]] = None, *, once: bool = False, min_sleep: float = 2.0, max_sleep: float = 60.0, max_ticks: Optional[int] = None) -> Dict[str, Any]:
    """The persistent loop: tick every supervised study, back off while everything waits, exit when all are settled."""
    ids = list(study_ids or S.list_study_ids())
    sups = {sid: Supervisor(sid) for sid in ids}
    for s in sups.values():
        s.write_loop_pid()
    sleep = min_sleep; ticks = 0; last: Dict[str, Any] = {}
    while True:
        progressed = False
        for sid, s in sups.items():
            if s.is_settled():
                continue
            card = s.tick(); last[sid] = card; ticks += 1
            if not s.is_waiting(card):
                progressed = True
        if once or (max_ticks and ticks >= max_ticks) or all(s.is_settled() for s in sups.values()):
            break
        sleep = min_sleep if progressed else min(max_sleep, sleep * 2)
        time.sleep(sleep)
    return {"studies": {sid: {"action": c.get("action"), "next_action": c.get("next_action"), "settled": sups[sid].is_settled()} for sid, c in last.items()}, "ticks": ticks}


__all__ = ["Supervisor", "SupervisorError", "run_loop", "MAX_ATTEMPTS"]

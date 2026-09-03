"""The governed controller for platform-v2 studies: same operator surface, same cards,
receipts and gates as :mod:`research_workflow.governed_controller`; the leaves are
:mod:`research_workflow.lifecycle_v2`.  ``research study run`` dispatches here whenever
the study is authored in the six-kind grammar."""
from __future__ import annotations

from datetime import datetime, timezone

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from research_workflow.controller_contracts import BlockerType, ControllerState
from research_workflow.governed_controller import (RECEIPT_STAGES, STAGE_ORDER, ControllerActions, GovernedStudyController, _STAGE_STATE, _json, _read, _sha)
from research_workflow.lifecycle_v2 import CapabilityGapBlocked, V2Lifecycle, V2Options, is_v2_study


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    except Exception:
        import os
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class V2StudyController(GovernedStudyController):
    def __init__(self, study: str | Path, *, options: Optional[V2Options] = None, owned_paths: tuple[str, ...] = (),
                 max_runtime: float = 600, stale_progress_timeout: float = 120, rss_limit_mb: float | None = None,
                 repo_root: Path | None = None) -> None:
        self.options = options or V2Options()
        lc = V2Lifecycle(Path(study), repo_root=(repo_root or Path(__file__).resolve().parents[1]), options=self.options)
        self.lifecycle = lc
        actions = ControllerActions(
            compile=lc.compile, prepare=lc.prepare, readiness=lc.readiness, preflight=lc.preflight, tests=lc.tests, seal=lc.seal,
            smoke=lc.smoke, collection=lc.collection, reconcile=lc.reconcile, merge=lc.merge, fit=lc.fit, freeze=lc.freeze,
            oos=lc.oos, analyze=lc.analyze, close=lc.close)
        # A v2 study owns its own directory: the CLI scaffolds it untracked and the lifecycle writes
        # compiled_plan.json / audit / artifacts / runs / _work under it. Everything else stays governed.
        owned = list(owned_paths)
        try:
            rel = Path(study).resolve().relative_to(lc.repo_root.resolve())
            if rel.parts and str(rel) not in owned:
                owned.append(str(rel).replace("\\", "/"))
        except ValueError:
            pass
        super().__init__(study, actions=actions, owned_paths=tuple(owned), max_runtime=max_runtime,
                         stale_progress_timeout=stale_progress_timeout, rss_limit_mb=rss_limit_mb, repo_root=repo_root)
        self.custom_actions = False
        self.artifact_trust_mode = "production"

    # -- identities ---------------------------------------------------------------
    def _fingerprints(self) -> dict[str, str | None]:
        return self.lifecycle.fingerprints()

    def _current_study_spec_sha256(self) -> str | None:
        from research_workflow.lifecycle_v2 import spec_sha256
        return spec_sha256(self.study)

    def _valid_resume_handoff(self, fp: dict[str, str | None]) -> dict[str, Any] | None:
        return None

    def _audit_current(self, path: Path, fp: dict[str, str | None]) -> bool:
        frozen = fp.get("execution_composite")
        st = _read(path)
        return bool(frozen and st.get("verdict") == "CLEAR" and st.get("audited_execution_composite_sha256") == frozen and fp.get("current_execution_composite") == frozen)

    def _fresh_stage(self, stage: str, fp: dict[str, str | None]) -> bool:
        # a compiled plan is current only if the spec is unchanged AND the closure it was compiled against
        # (host modules, compiler, bound providers) still hashes to the same composite
        plan_ok = bool(fp.get("compiled_plan") and fp.get("plan_spec_sha256") == fp.get("study_spec")
                       and fp.get("plan_closure_composite") and fp.get("plan_closure_composite") == fp.get("current_execution_composite"))
        closure_ok = bool(fp.get("execution_composite") and fp.get("execution_composite") == fp.get("current_execution_composite"))
        if stage == "compile":
            return plan_ok
        if not plan_ok:
            return False
        if stage == "prepare":
            return closure_ok and (self.study / "artifacts/experiment_authorization.json").is_file()
        if not closure_ok:
            return False
        if stage == "readiness":
            r = _read(self.study / "audit/readiness.json")
            return r.get("overall_status") == "PASS" and r.get("execution_composite_sha256") == fp.get("execution_composite")
        if stage == "preflight":
            p = _read(self.study / "audit/preflight.json")
            return p.get("status") == "CLEAR" and p.get("execution_composite_sha256") == fp.get("execution_composite")
        if stage == "tests":
            t = _read(self.work / "test_summary.json")
            return t.get("status") == "PASS" and t.get("execution_composite_sha256") == fp.get("execution_composite")
        if stage == "causal_audit":
            return self._audit_current(self.study / "audit/status.json", fp)
        if stage == "contract_audit":
            return self._audit_current(self.study / "audit/contract_status.json", fp)
        if stage == "seal":
            s = _read(self.study / "artifacts/preexec_audit_seal.json")
            return bool(s.get("composite_seal_hash") and s.get("execution_manifest_composite_sha256") == fp.get("execution_composite")
                        and self._audit_current(self.study / "audit/status.json", fp) and self._audit_current(self.study / "audit/contract_status.json", fp))
        if stage == "close":
            try:
                from research_workflow.study_closure import load_study_closure
                return load_study_closure(self.study) is not None
            except Exception:
                return False
        if stage in {"collection", "oos"}:
            return self._receipt_current(stage, fp, require_partitions=True)
        if stage in RECEIPT_STAGES:
            return self._receipt_current(stage, fp)
        return False

    def _packet(self, audit_type: str, fp: dict[str, str | None]) -> Path:
        from research_workflow.audit_packets_v2 import causal_packet, contract_packet
        from research_workflow.lifecycle_v2 import load_plan
        plan = load_plan(self.study)
        common = {"study_id": self.study.name, "execution_composite": fp.get("execution_composite") or "", "dirty_paths": self._worktree()["dirty_paths"],
                  "test_summary": _read(self.work / "test_summary.json")}
        packet = causal_packet(plan, **common) if audit_type == "causal" else contract_packet(plan, **common, seal=_read(self.study / "artifacts/preexec_audit_seal.json"))
        path = self.work / f"audit_packet_{audit_type}.json"
        _json(path, packet)
        return path

    def _acquire_run_lock(self) -> dict[str, Any] | None:
        """One live controller per study. A stale lock (dead pid) is replaced; a live one blocks."""
        import os
        lock = self.work / "run.lock"
        existing = _read(lock)
        pid = int(existing.get("pid") or 0)
        if pid and pid != os.getpid() and _pid_alive(pid):
            return {"pid": pid, "started_at_utc": existing.get("started_at_utc"), "through": existing.get("through")}
        _json(lock, {"pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).isoformat(), "through": self._through})
        return None

    def _release_run_lock(self) -> None:
        import os
        lock = self.work / "run.lock"
        if int(_read(lock).get("pid") or 0) == os.getpid():
            try:
                lock.unlink()
            except OSError:
                pass

    def run(self, *, through: str = "seal", inspect: bool = False, dry_run: bool = False) -> dict[str, Any]:
        if through not in STAGE_ORDER:
            raise ValueError(f"unknown --through {through}")
        self._through = through
        # STUDY_CLOSED is terminal and recognized before anything else: a valid closure is the authority
        try:
            from research_workflow.study_closure import load_study_closure
            closure = load_study_closure(self.study)
        except Exception:
            closure = None
        if closure is not None:
            card = self._card(ControllerState.STUDY_CLOSED, "close", last="close", dry_run=bool(inspect or dry_run))
            card["closure"] = {k: closure.get(k) for k in ("status", "outcome", "terminal_decision", "closed_at_utc")}
            return card
        if not (inspect or dry_run):
            live = self._acquire_run_lock()
            if live:
                card = self._card(ControllerState.NEEDS_COMPILE, "worktree", blocker=BlockerType.RUNTIME_FAILURE,
                                  reason=f"STUDY_RUN_ALREADY_LIVE: pid {live['pid']} started {live['started_at_utc']} (--through {live['through']}); one controller per study",
                                  last=None)
                card["blocker_code"] = "STUDY_RUN_ALREADY_LIVE"
                return card
        try:
            return self._run_locked(through=through, inspect=inspect, dry_run=dry_run)
        finally:
            if not (inspect or dry_run):
                self._release_run_lock()

    def _run_locked(self, *, through: str, inspect: bool, dry_run: bool) -> dict[str, Any]:
        # typed capability gaps are a first-class blocker, never a runtime failure
        fp = self._fingerprints()
        if not (inspect or dry_run) and not self._fresh_stage("compile", fp) and not self._worktree()["unsafe_dirty_paths"]:
            try:
                self.lifecycle.compile()
                self.ran.append("compile")
            except CapabilityGapBlocked as exc:
                card = self._card(ControllerState.NEEDS_COMPILE, "compile", blocker=BlockerType.CAPABILITY_BLOCKER,
                                  reason="typed capability gap(s): " + ", ".join(exc.report.get("kinds") or []), last=None,
                                  artifact=self.work / "capability_gap.json")
                card["capability_gaps"] = exc.report.get("gaps")
                _json(self.work / "status.json", card)
                return card
        return super().run(through=through, inspect=inspect, dry_run=dry_run)


def controller_for(study: str | Path, **kwargs: Any):
    """Pick the v2 controller for a grammar-v2 study, the v1 controller otherwise."""
    if is_v2_study(Path(study)):
        return V2StudyController(study, **kwargs)
    kwargs.pop("options", None)
    return GovernedStudyController(study, **kwargs)


__all__ = ["V2StudyController", "controller_for"]

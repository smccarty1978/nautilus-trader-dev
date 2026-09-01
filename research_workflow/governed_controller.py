"""Thin, resumable controller over the governed lifecycle; it never reviews its own audits."""
from __future__ import annotations

import hashlib
import contextlib
import io
import traceback
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from research_workflow.controller_contracts import AuditPacket, BlockerType, ControllerState, ControllerStatus, FailurePacket
from research_workflow.workflow_engine import WorkflowActions, WorkflowEngine, _clear, _read, _sha


STAGE_ORDER = ("compile", "prepare", "readiness", "preflight", "tests", "causal_audit", "contract_audit", "seal", "collection", "reconcile", "analyze")
_STAGE_STATE = {"compile": ControllerState.NEEDS_COMPILE, "prepare": ControllerState.NEEDS_PREPARE,
                "readiness": ControllerState.NEEDS_READINESS, "preflight": ControllerState.NEEDS_PREFLIGHT,
                "tests": ControllerState.NEEDS_TESTS,
                "causal_audit": ControllerState.NEEDS_CAUSAL_AUDIT, "contract_audit": ControllerState.NEEDS_CONTRACT_AUDIT,
                "seal": ControllerState.READY_TO_SEAL, "collection": ControllerState.READY_TO_COLLECT,
                "reconcile": ControllerState.READY_TO_RECONCILE, "analyze": ControllerState.READY_TO_ANALYZE}


def _json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class ControllerActions:
    """Injectable leaves; defaults reuse the canonical lifecycle implementation."""
    compile: Callable[[Path], Any] | None = None
    prepare: Callable[[Path], Any] | None = None
    readiness: Callable[[Path], Any] | None = None
    preflight: Callable[[Path], Any] | None = None
    tests: Callable[[Path], Any] | None = None
    seal: Callable[[Path], Any] | None = None
    collection: Callable[[Path], Any] | None = None
    reconcile: Callable[[Path], Any] | None = None
    analyze: Callable[[Path], Any] | None = None

    def __post_init__(self) -> None:
        leaves = WorkflowActions()
        if self.compile is None:
            from research_workflow.study_spec_compiler import compile_approved_request
            self.compile = lambda study: compile_approved_request(study, write=True)
        self.prepare = self.prepare or leaves.prepare
        self.readiness = self.readiness or leaves.readiness
        self.preflight = self.preflight or leaves.preflight
        if self.tests is None: self.tests = _materialize_preflight_tests
        self.seal = self.seal or leaves.seal


class GovernedStudyController:
    """Artifact-driven controller with closed states and no free-text transitions."""
    def __init__(self, study: str | Path, *, actions: ControllerActions | None = None,
                 owned_paths: tuple[str, ...] = (), max_runtime: float = 600, stale_progress_timeout: float = 120,
                 rss_limit_mb: float | None = None, repo_root: Path | None = None) -> None:
        self.study = Path(study).resolve()
        self.custom_actions = actions is not None
        self.artifact_trust_mode = "synthetic_test" if actions is not None and getattr(actions, "synthetic_test", False) else "production"
        self.actions = actions or ControllerActions()
        self.owned_paths = tuple(owned_paths)
        self.max_runtime, self.stale_progress_timeout, self.rss_limit_mb = max_runtime, stale_progress_timeout, rss_limit_mb
        self.work = self.study / "_work" / "controller"
        self.repo_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.ran: list[str] = []

    def _fingerprints(self) -> dict[str, str | None]:
        return WorkflowEngine(self.study, actions=WorkflowActions())._fingerprints()

    def run_subprocess(self, stage: str, command: list[str], *, progress_file: Path | None = None) -> dict[str, Any]:
        """Bounded verbose-child adapter. Child output is an artifact, never controller stdout."""
        from scripts.run_bounded_study import monitor_process
        status = self.work / "subprocess_status.json"
        # The standard monitor owns PID polling, progress timeout and RSS sampling.
        monitor_messages = io.StringIO()
        with contextlib.redirect_stdout(monitor_messages):
            monitor_process(command, self.max_runtime, self.stale_progress_timeout, progress_file, status,
                            rss_limit_mb=self.rss_limit_mb)
        result = _read(status)
        source = Path(str(result.get("log_file", "")))
        destination = self.work / "logs" / f"{stage}.log"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            destination.write_bytes(source.read_bytes())
        with destination.open("a", encoding="utf-8") as handle:
            handle.write("\n=== CONTROLLER MONITOR ===\n" + monitor_messages.getvalue())
        result.update({"stage": stage, "log_file": str(destination), "log_sha256": _sha(destination),
                       "tail": destination.read_text(encoding="utf-8", errors="replace")[-2000:] if destination.exists() else ""})
        _json(status, result)
        return result

    def _worktree(self) -> dict[str, Any]:
        root = self.repo_root
        result = subprocess.run(["git", "status", "--porcelain=v1", "-z"], cwd=root, text=True, capture_output=True, check=False)
        branch_result = subprocess.run(["git", "branch", "--show-current"], cwd=root, text=True, capture_output=True, check=False)
        head_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
        branch, head = branch_result.stdout.strip(), head_result.stdout.strip()
        root_resolved = root.resolve()
        dirty, unsafe = [], []
        if result.returncode or branch_result.returncode or head_result.returncode or not branch or not head:
            unsafe.append("git worktree identity unavailable")
        allowed = []
        for item in self.owned_paths:
            p = Path(item)
            if not item or p.is_absolute() or ".." in p.parts: unsafe.append(f"invalid owned path: {item}"); continue
            candidate = (root_resolved / p).resolve()
            if candidate == root_resolved or root_resolved not in candidate.parents: unsafe.append(f"owned path escapes root: {item}"); continue
            allowed.append(candidate)
        fields = result.stdout.split("\0")
        i = 0
        while i < len(fields):
            entry = fields[i]; i += 1
            if not entry: continue
            if len(entry) < 4 or entry[2] != " ": unsafe.append(f"unparseable porcelain: {entry!r}"); continue
            code, name = entry[:2], entry[3:]
            names = [name]
            if "R" in code or "C" in code:
                if i >= len(fields): unsafe.append(f"unparseable rename: {name}"); continue
                names.append(fields[i]); i += 1
            for name in names:
                dirty.append(name); p = Path(name)
                if p.is_absolute() or ".." in p.parts: unsafe.append(name); continue
                candidate = (root_resolved / p).resolve()
                if candidate != root_resolved and root_resolved not in candidate.parents: unsafe.append(name); continue
                if not any(candidate == a or a in candidate.parents for a in allowed): unsafe.append(name)
        return {"path": str(root_resolved), "branch": branch, "head": head, "dirty_paths": dirty, "unsafe_dirty_paths": unsafe}

    def _audit_current(self, path: Path, fp: dict[str, str | None]) -> bool:
        frozen = _read(self.study / "audit" / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        return bool(frozen and _clear(path) and _read(path).get("audited_execution_composite_sha256") == frozen and fp.get("current_execution_composite") == frozen)

    def _fresh_stage(self, stage: str, fp: dict[str, str | None]) -> bool:
        prior = _read(self.work / "status.json")
        mapping = {"approved_request": 1, "study_spec": 2, "compiled_study": 2, "execution_freeze": 2,
                   "execution_composite": 2, "current_execution_composite": 2, "active_feature_authority": 2,
                   "preflight": 4, "causal_status": 5, "contract_status": 6, "seal": 7}
        old = prior.get("fingerprints", {}) if prior else {}
        changed = [mapping[k] for k, value in fp.items() if old.get(k) is not None and old.get(k) != value and k in mapping]
        stale = min(changed) if changed else (0 if not prior else 99)
        compilation = _read(self.study / "artifacts/study_spec_compilation.json")
        if stage == "compile":
            if self.artifact_trust_mode == "synthetic_test": return (self.study / "compiled_study.json").is_file() and stale != 1
            return bool((self.study / "compiled_study.json").is_file() and compilation.get("request_sha256") == _sha(self.study / "research_decision.yaml") and stale not in {0, 1})
        if stage == "prepare":
            frozen = _read(self.study / "audit/frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
            return bool(stale > 2 and frozen and frozen == fp.get("current_execution_composite"))
        if stage == "readiness": return stale > 3 and _read(self.study / "audit/readiness.json").get("overall_status") == "PASS" and _read(self.study / "audit/readiness.json").get("execution_composite_sha256", fp.get("execution_composite")) == fp.get("execution_composite")
        if stage == "tests":
            t = _read(self.work / "test_summary.json"); return stale > 3 and t.get("status") == "PASS" and t.get("execution_composite_sha256") == fp.get("execution_composite")
        if stage == "preflight": return stale > 4 and _clear(self.study / "audit/preflight.json") and _read(self.study / "audit/preflight.json").get("execution_composite_sha256") == fp.get("execution_composite")
        if stage == "causal_audit": return stale > 5 and self._audit_current(self.study / "audit/status.json", fp)
        if stage == "contract_audit": return stale > 6 and self._audit_current(self.study / "audit/contract_status.json", fp)
        if stage == "seal":
            if stale <= 7: return False
            if self.artifact_trust_mode == "synthetic_test": return (self.study / "artifacts/preexec_audit_seal.json").is_file()
            try:
                from research_workflow.seal import verify_preexec_audit_seal
                verify_preexec_audit_seal(self.study); return True
            except Exception: return False
        if stage == "collection":
            return self._receipt_current("collection", fp, require_partitions=True)
        if stage == "reconcile": return stale > 8 and self._receipt_current("reconcile", fp)
        if stage == "analyze": return self._receipt_current("analyze", fp)
        return False

    def _receipt_current(self, stage: str, fp: dict[str, str | None], *, require_partitions: bool = False) -> bool:
        receipt = _read(self.work / "receipts" / f"{stage}.json")
        if not fp.get("execution_composite") or receipt.get("stage") != stage or receipt.get("status") != "PASS" or receipt.get("execution_composite_sha256") != fp.get("execution_composite"):
            return False
        outputs = receipt.get("outputs") or []
        if not outputs or any(not Path(x.get("path", "")).is_file() or _sha(Path(x["path"])) != x.get("sha256") for x in outputs): return False
        if require_partitions:
            partitions = receipt.get("partitions") or []
            return bool(partitions) and all(p.get("id") and p.get("status") == "PASS" for p in partitions)
        return True

    def _write_receipt(self, stage: str, result: Any, fp: dict[str, str | None]) -> None:
        if not fp.get("execution_composite") or not isinstance(result, dict) or result.get("status") not in {"PASS", "SUCCESS", "COMPLETED"}:
            raise RuntimeError(f"{stage.upper()}_OUTPUT_CONTRACT_INVALID")
        paths = result.get("output_artifacts") or result.get("outputs") or []
        paths = [paths] if isinstance(paths, (str, Path)) else paths
        outputs = [{"path": str(Path(p)), "sha256": _sha(Path(p))} for p in paths]
        if not outputs or any(not x["sha256"] for x in outputs): raise RuntimeError(f"{stage.upper()}_OUTPUT_CONTRACT_INVALID")
        partitions = [{**p, "status": "PASS"} if isinstance(p, dict) and p.get("status") in {"PASS", "SUCCESS", "COMPLETED"} else p for p in result.get("partitions", [])]
        if stage == "collection" and (not partitions or not all(isinstance(p, dict) and p.get("id") and p.get("status") in {"PASS", "SUCCESS", "COMPLETED"} for p in partitions)):
            raise RuntimeError("COLLECTION_PARTITION_CONTRACT_INVALID")
        log = self.work / "logs" / f"{stage}.log"
        _json(self.work / "receipts" / f"{stage}.json", {"schema_version": 1, "stage": stage, "status": "PASS", "execution_composite_sha256": fp.get("execution_composite"), "outputs": outputs, "partitions": partitions, "log": {"path": str(log), "sha256": _sha(log)} if log.is_file() else None})

    def _packet(self, audit_type: str, fp: dict[str, str | None]) -> Path:
        compiled = _read(self.study / "compiled_study.json")
        spec = compiled.get("spec", {})
        packet = AuditPacket(self.study.name, audit_type, fp.get("execution_composite"), fp.get("current_execution_composite"), {k: fp.get(k) for k in ("approved_request", "study_spec", "compiled_study", "execution_composite")}, {k: spec.get(k) for k in ("target", "population", "features", "chronology")}, self._worktree()["dirty_paths"], ["research_workflow/lifecycle.py", "research_workflow/workflow_engine.py", "research_workflow/forward_outcomes/guard.py"], ["completed bars only", "forward outcomes are labels", "assert_oos_open is the only OOS door"], _read(self.work / "test_summary.json"), {"path": str(self.study / "audit" / ("status.json" if audit_type == "causal" else "contract_status.json")), "sha256": _sha(self.study / "audit" / ("status.json" if audit_type == "causal" else "contract_status.json"))}).as_dict()
        packet["identity"] = hashlib.sha256(json.dumps({k:v for k,v in packet.items() if k != "identity"}, sort_keys=True, default=str).encode()).hexdigest()
        path = self.work / f"audit_packet_{audit_type}.json"; _json(path, packet); return path

    def _failure(self, state: ControllerState, blocker: BlockerType, reason: str, fp: dict[str, str | None], last: str | None) -> Path:
        packet = FailurePacket(self.study.name, state.value, blocker.value, reason, hashes=fp, last_successful_stage=last,
                               affected_artifacts=[str(self.study / "audit"), str(self.work / "status.json")], relevant_files=[str(self.study / "study.yaml")],
                               allowed_actions=(['submit independent audit'] if blocker in {BlockerType.CAUSALITY_BLOCKER, BlockerType.CONTRACT_BLOCKER} else ['repair deterministic artifact']),
                               deterministic_repair_possible=blocker == BlockerType.RUNTIME_FAILURE)
        data = packet.as_dict(); data["identity"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        path = self.work / "failure_packet.json"; _json(path, data); return path

    def _card(self, state: ControllerState, stage: str, *, artifact: Path | None = None, blocker: BlockerType | None = None,
              reason: str | None = None, dry_run: bool = False, last: str | None = None) -> dict[str, Any]:
        fp = self._fingerprints(); failure = self._failure(state, blocker, reason or "", fp, last) if blocker and not dry_run else None
        typed = ControllerStatus("BLOCKED" if blocker else "OK", state.value, stage, state.value, blocker.value if blocker else None, str(artifact) if artifact else None, _sha(artifact) if artifact else None, _read(self.work / "test_summary.json").get("counts", {}))
        card = {"STATUS": typed.status, "state": typed.state, "stage": typed.stage, "next_state": typed.next_state,
                "actions_executed": self.ran, "artifact": str(artifact) if artifact else None, "sha256": _sha(artifact) if artifact else None,
                "failure_packet": str(failure) if failure else None, "blocker_code": typed.blocker_code, "test_counts": typed.test_counts, "schema_version": typed.schema_version, "dry_run": dry_run, "fingerprints": fp,
                "worktree": self._worktree(), "updated_at": datetime.now(timezone.utc).isoformat()}
        if not dry_run: _json(self.work / "status.json", card); _json(self.work / "progress.json", {"stage": stage, "last_successful_stage": last, "actions": self.ran})
        return card

    def run(self, *, through: str = "seal", inspect: bool = False, dry_run: bool = False) -> dict[str, Any]:
        if through not in STAGE_ORDER: raise ValueError(f"unknown --through {through}")
        dry_run = bool(dry_run or inspect); fp = self._fingerprints(); safety = self._worktree()
        if safety["unsafe_dirty_paths"]:
            return self._card(ControllerState.NEEDS_COMPILE, "worktree", blocker=BlockerType.WORKTREE_CONTAMINATION,
                              reason="unowned dirty paths: " + ", ".join(safety["unsafe_dirty_paths"]), dry_run=dry_run)
        last = None
        for stage in STAGE_ORDER[:STAGE_ORDER.index(through) + 1]:
            fp = self._fingerprints()
            if self._fresh_stage(stage, fp): last = stage; continue
            state = _STAGE_STATE[stage]
            if inspect or dry_run:
                return self._card(state, stage, dry_run=True, last=last)
            if stage in {"causal_audit", "contract_audit"}:
                existing = self.study / "audit" / ("status.json" if stage == "causal_audit" else "contract_status.json")
                verdict = _read(existing).get("verdict", _read(existing).get("status"))
                if existing.is_file() and verdict in {"BLOCKED", "INCOMPLETE"} and _read(existing).get("audited_execution_composite_sha256") == fp.get("execution_composite"):
                    blocker = BlockerType.CAUSALITY_BLOCKER if stage == "causal_audit" else BlockerType.CONTRACT_BLOCKER
                    return self._card(state, stage, blocker=blocker, reason=f"current independent audit verdict={verdict}", last=last)
                path = self._packet("causal" if stage == "causal_audit" else "contract", fp)
                return self._card(state, stage, artifact=path, last=last)
            action = getattr(self.actions, stage)
            if action is None:
                return self._card(state, stage, blocker=BlockerType.CAPABILITY_BLOCKER,
                                  reason=f"no approved operation registered for {stage}", last=last)
            try:
                log = self.work / "logs" / f"{stage}.log"; log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as handle, contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
                    result = action(self.study)
                if stage in {"collection", "reconcile", "analyze"}: self._write_receipt(stage, result, fp)
                self.ran.append(stage)
            except Exception as exc:
                with (self.work / "logs" / f"{stage}.log").open("a", encoding="utf-8") as handle: traceback.print_exc(file=handle)
                return self._card(state, stage, blocker=BlockerType.RUNTIME_FAILURE, reason=f"{type(exc).__name__}: {exc}", last=last)
            last = stage
        if through in {"collection", "reconcile", "analyze"} and not self._fresh_stage(through, self._fingerprints()):
            return self._card(_STAGE_STATE[through], through, last=last)
        final_state = ControllerState.COMPLETE if through == "analyze" else ({"seal": ControllerState.READY_TO_COLLECT, "collection": ControllerState.READY_TO_RECONCILE, "reconcile": ControllerState.READY_TO_ANALYZE}.get(through, _STAGE_STATE[through]))
        return self._card(final_state, through, last=last)


def compact_card(card: dict[str, Any], *, as_json: bool = False) -> str:
    if as_json: return json.dumps({k: card.get(k) for k in ("STATUS", "state", "stage", "artifact", "sha256", "next_state", "failure_packet", "blocker_code", "test_counts")}, sort_keys=True)
    return " ".join(f"{k}={str(card.get(k) or '-')}" for k in ("STATUS", "state", "stage", "artifact", "sha256", "next_state", "blocker_code", "test_counts"))


def _materialize_preflight_tests(study: Path) -> dict[str, Any]:
    """Extract preflight's already-run canonical test check; never runs pytest again."""
    preflight = _read(study / "audit" / "preflight.json")
    outcome = (preflight.get("check_outcomes") or {}).get("CAUSAL_INVARIANTS")
    required = preflight.get("required_checks") or []
    composite = preflight.get("execution_composite_sha256")
    if preflight.get("diagnostic_mode") or not preflight.get("audit_ready") or "CAUSAL_INVARIANTS" not in required or outcome not in {"PASSED", "PASS"} or not composite:
        raise RuntimeError(f"PREFLIGHT_TEST_EVIDENCE_MISSING_OR_FAILED: outcome={outcome}")
    result = {"status": "PASS", "execution_composite_sha256": composite, "source": "audit/preflight.json"}
    _json(study / "_work/controller/test_summary.json", result); return result

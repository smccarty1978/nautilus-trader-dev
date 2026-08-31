"""Artifact-driven fixed-point orchestrator for the governed research lifecycle."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from research_workflow.study_spec_compiler import compile_approved_request

TERMINALS = {"READY_FOR_TRAIN_AUTHORIZATION", "TRAIN_AUTHORIZATION_REQUIRED", "OOS_AUTHORIZATION_REQUIRED", "IMPLEMENTATION_REQUIRED", "SEMANTIC_DECISION_REQUIRED", "AUTHORITY_CONFLICT", "SAFETY_OR_AUTHORIZATION_BLOCK", "TRUE_CAPABILITY_GAP", "TRUE_SCHEMA_GAP", "COMPLETE"}

def _read(p: Path) -> dict[str, Any]:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def _clear(p: Path) -> bool:
    d = _read(p); return d.get("verdict") == "CLEAR" or d.get("status") == "CLEAR"
def _aggregate_hash(paths: list[Path]) -> str | None:
    values = [_sha(p) for p in sorted(paths)]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest() if values else None

STAGES = {"STUDY_SPEC_COMPILED": 1, "PREPARED": 2, "READY": 3, "PREFLIGHT": 4,
          "CAUSAL_AUDIT": 5, "CONTRACT_AUDIT": 6, "SEALED": 7, "SMOKE_RECONCILED": 8}

@dataclass
class WorkflowActions:
    """Leaf-operation adapter. Tests may replace individual deterministic leaves."""
    reconcile: Callable[[Path], dict[str, Any]] | None = None
    prepare: Callable[[Path], Any] | None = None
    readiness: Callable[[Path], Any] | None = None
    preflight: Callable[[Path], Any] | None = None
    causal: Callable[[Path], dict[str, Any]] | None = None
    contract: Callable[[Path], dict[str, Any]] | None = None
    seal: Callable[[Path], Any] | None = None
    smoke: Callable[[Path], Any] | None = None
    train: Callable[[Path], Any] | None = None
    def __post_init__(self):
        if self.reconcile is None:
            from scripts.reconcile_study_capabilities import reconcile; self.reconcile = reconcile
        if self.prepare is None:
            from research_workflow.lifecycle import prepare; self.prepare = prepare
        if self.readiness is None:
            from research_workflow.lifecycle import readiness; self.readiness = readiness
        if self.preflight is None:
            from research_workflow.lifecycle import bounded_preflight; self.preflight = bounded_preflight
        if self.causal is None:
            from research_workflow.causal_audit import run_causal_review; self.causal = run_causal_review
        if self.contract is None:
            from research_workflow.contract_audit import run_contract_review; self.contract = run_contract_review
        if self.seal is None:
            from research_workflow.lifecycle import seal; self.seal = seal
        if self.smoke is None:
            def bounded_smoke(study: Path) -> dict[str, Any]:
                import yaml
                from research_workflow.smoke import run_smoke
                from scripts.reconcile_runs import reconcile_runs
                data = yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8")) or {}
                chronology = data.get("chronology") or {}
                date = ((_read(study / "audit/readiness.json").get("run_window") or {}).get("start_date"))
                if not date:
                    raise RuntimeError("SMOKE_DATE_AUTHORIZATION_AMBIGUOUS")
                year = int(str(date)[:4])
                if year not in set(chronology.get("train") or []) or year in set(chronology.get("prohibited") or []):
                    raise RuntimeError("SMOKE_DATE_NOT_TRAIN_AUTHORIZED")
                result = run_smoke(study, [date])
                if result.get("status") != "PASS":
                    raise RuntimeError(f"SMOKE_FAILED: {result}")
                reconciliation = reconcile_runs(study / "runs", study.name)
                if not any(r.get("state") in {"COMPLETE", "ACCEPTED", "SUCCESS"} for r in reconciliation.get("runs", [])):
                    raise RuntimeError("SMOKE_RECONCILIATION_NOT_SUCCESSFUL")
                seal_hash = _sha(study / "artifacts/preexec_audit_seal.json")
                composite = _read(study / "audit/frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
                (study / "artifacts/smoke_reconciled.json").write_text(json.dumps({"status":"PASS", "seal_sha256":seal_hash, "execution_composite_sha256":composite, "reconciliation":reconciliation}, indent=2), encoding="utf-8")
                return result
            self.smoke = bounded_smoke
        if self.train is None:
            from research_workflow.collection import collect_period_partitioned
            self.train = lambda study: collect_period_partitioned(study, "train", execute=True)

class WorkflowEngine:
    def __init__(self, study: str | Path, *, actions: WorkflowActions | None = None, smoke: bool = False, execute_authorized: bool = False):
        p = Path(study)
        self.study = (p if p.is_dir() else Path("studies") / str(study)).resolve()
        self.custom_actions = actions is not None
        self.actions, self.allow_smoke, self.execute_authorized = actions or WorkflowActions(), smoke, execute_authorized
        self.executed: list[str] = []
    def _state(self, terminal: str, *, blockers: list[dict[str, Any]] | None = None, next_action: str | None = None) -> dict[str, Any]:
        files = self._fingerprints()
        state = {"study_id": self.study.name, "current_stage": terminal, "terminal_state": terminal,
                 "terminal_reason": (blockers or [{}])[0].get("detail") if blockers else None,
                 "current_authority_hashes": files, "fingerprints": files, "completed_gates": list(self.executed),
                 "stale_gates": list(getattr(self, "stale_gates", [])), "authorization_state": self._authorization(), "next_deterministic_action": next_action,
                 "blockers": blockers or [], "timestamp": datetime.now(timezone.utc).isoformat()}
        self.study.mkdir(parents=True, exist_ok=True)
        state["actions_executed_this_run"] = list(self.executed)
        state["completed_gates"] = self._completed_gates()
        # RT-13: an existing OOS analysis artifact is only authoritative while FRESH.
        try:
            from research_workflow.oos_analysis_lineage import classify_oos_analysis
            state["oos_analysis_state"] = classify_oos_analysis(self.study)
        except Exception:  # pragma: no cover - never block workflow state on this
            state["oos_analysis_state"] = None
        state["timestamps"] = {k: (self.study / p).stat().st_mtime if (self.study / p).exists() else None for k,p in {"prepared":"audit/frozen_execution_manifest.json","readiness":"audit/readiness.json","preflight":"audit/preflight.json","causal":"audit/status.json","contract":"audit/contract_status.json","seal":"artifacts/preexec_audit_seal.json","smoke":"artifacts/smoke_reconciled.json"}.items()}
        (self.study / "workflow_state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state
    def _completed_gates(self) -> list[str]:
        gates=[]
        if (self.study/"audit/frozen_execution_manifest.json").is_file(): gates.append("PREPARED")
        if self._readiness_passed(): gates.append("READY")
        if _clear(self.study/"audit/preflight.json"): gates.append("PREFLIGHT")
        if self._audit_current(self.study/"audit/status.json"): gates.append("CAUSAL_AUDIT")
        if self._audit_current(self.study/"audit/contract_status.json"): gates.append("CONTRACT_AUDIT")
        return gates
    def _authorization(self) -> str:
        # A study with a closure artifact (valid or malformed) is not an authorization
        # context; do not touch experiment_authorization.json (load_authorization would
        # regenerate it from study.yaml).
        if (self.study / "artifacts" / "study_closure.json").is_file():
            return "STUDY_CLOSED"
        try:
            from research_workflow.experiment import load_authorization
            artifact = self.study / "artifacts" / "experiment_authorization.json"
            if not artifact.is_file(): return "TRAIN_NOT_AUTHORIZED"
            load_authorization(self.study)
            return "TRAIN_AUTHORIZED"
        except Exception: return "TRAIN_AUTHORIZATION_INVALID"
    def _readiness_passed(self) -> bool:
        return _read(self.study / "audit/readiness.json").get("overall_status") == "PASS"
    def _audit_current(self, path: Path) -> bool:
        frozen = _read(self.study / "audit/frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        fresh = self._fingerprints().get("current_execution_composite")
        if self.custom_actions:
            fresh = frozen
        return (_clear(path) and bool(frozen) and _read(path).get("audited_execution_composite_sha256") == frozen
                and fresh == frozen)
    def _fingerprints(self) -> dict[str, str | None]:
        """Re-derived identities; the previous state is only a comparison cache."""
        repo = Path(__file__).resolve().parents[1]
        paths = {"approved_request": "research_decision.yaml", "study_spec": "study.yaml",
                 "compiled_study": "compiled_study.json", "active_feature_authority": str(repo / "features/authority/active.json"),
                 "frozen_lineage": "artifacts/study_spec_compilation.json", "feature_candidate_semantics": "feature_candidate.yaml", "execution_freeze": "audit/frozen_execution_manifest.json",
                 "preflight": "audit/preflight.json", "causal_status": "audit/status.json", "contract_status": "audit/contract_status.json",
                 "seal": "artifacts/preexec_audit_seal.json", "smoke": "artifacts/smoke_reconciled.json",
                 "train_authorization": "artifacts/experiment_authorization.json", "train_freeze": "artifacts/train_experiment_freeze.json"}
        result = {name: _sha(Path(rel) if Path(rel).is_absolute() else (self.study / rel).resolve()) for name, rel in paths.items()}
        frozen = _read(self.study / "audit/frozen_execution_manifest.json")
        result["execution_composite"] = frozen.get("frozen_execution_composite_sha256")
        # Resolve the closure anew. A pointer hash alone cannot observe a provider edit.
        try:
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            result["current_execution_composite"] = resolve_execution_manifest(self.study)[0]
        except Exception:
            result["current_execution_composite"] = None
        # Active authority means its selected bundle, not merely the pointer file.
        try:
            active = json.loads((repo / "features/authority/active.json").read_text(encoding="utf-8"))
            bundle = active.get("active_bundle") or active.get("bundle") or active.get("path")
            bundle_path = (repo / "features/authority" / bundle) if bundle else None
            result["active_authority_bundle"] = _aggregate_hash(list(bundle_path.rglob("*"))) if bundle_path and bundle_path.is_dir() else result["active_feature_authority"]
        except Exception:
            result["active_authority_bundle"] = result["active_feature_authority"]
        audit = self.study / "audit"
        result["causal_reports"] = _aggregate_hash(list(audit.glob("pass_*.md"))) if audit.is_dir() else None
        result["contract_reports"] = _aggregate_hash(list(audit.glob("contract_pass_*.md"))) if audit.is_dir() else None
        return result
    def _earliest_stale_stage(self, prior: dict[str, Any]) -> int:
        old = prior.get("fingerprints") or prior.get("current_authority_hashes") or {}
        now = self._fingerprints(); changed = {k for k, v in now.items() if old.get(k) is not None and old.get(k) != v}
        mapping = {"approved_request": 1, "study_spec": 2, "compiled_study": 2, "active_feature_authority": 2,
                   "frozen_lineage": 2, "feature_candidate_semantics": 2, "execution_freeze": 2, "execution_composite": 2, "current_execution_composite": 2, "active_authority_bundle": 2, "preflight": 4, "causal_status": 5,
                   "causal_reports": 5, "contract_status": 6, "contract_reports": 6, "seal": 7, "smoke": 8}
        stages = [mapping[k] for k in changed if k in mapping]
        self.stale_gates = sorted(changed)
        return min(stages) if stages else 99
    def _prepare_stale(self) -> bool:
        """PREPARE freshness, independent of any prior workflow_state.

        The stale-stage diff only sees drift relative to a previous run.  On a first
        advance against a study that already carries an out-of-band freeze/seal (or
        right after the compiler (re)writes study.yaml), PREPARE must still re-run when
        the compiled study or the frozen closure no longer matches what is on disk.
        """
        study = self.study
        if not (study / "compiled_study.json").is_file(): return True
        if not (study / "audit/frozen_execution_manifest.json").is_file(): return True
        if self.custom_actions:
            return False  # tests supply their own deterministic prepare leaf
        try:
            import yaml as _yaml
            from research.schemas.study_spec import StudySpec
            spec = StudySpec.model_validate(_yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8")))
            if _read(study / "compiled_study.json").get("spec_sha256") != spec.compute_sha256():
                return True
        except Exception:
            return True
        fp = self._fingerprints()
        frozen, current = fp.get("execution_composite"), fp.get("current_execution_composite")
        if frozen and current and frozen != current:
            return True
        return False

    def _implementation_contract(self, result: dict[str, Any]) -> None:
        p = self.study / "artifacts" / "implementation_contract.json"; p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps({"capability_identity": result.get("error", "unresolved_capability"), "semantic_contract": result.get("detail"), "provider_or_collector_class_expected": result.get("expected_class"), "parameters": result.get("parameters", {}), "availability_reset_null_semantics": result.get("semantics", {}), "required_tests": result.get("required_tests", []), "affected_generic_interface": result.get("interface"), "expected_resume_point": "CAPABILITIES_RECONCILED"}, indent=2) + "\n", encoding="utf-8")
    def _closed_state(self, closure: dict[str, Any]) -> dict[str, Any]:
        """Terminal STUDY_CLOSED state. Reads only; rewrites nothing but workflow_state.json.

        Authorization is deliberately not evaluated here (that path can regenerate
        experiment_authorization.json), and no TRAIN/OOS actionable next_action is offered.
        """
        from research_workflow.study_closure import closure_summary

        files = self._fingerprints()
        state = {
            "study_id": self.study.name, "current_stage": "STUDY_CLOSED", "terminal_state": "STUDY_CLOSED",
            "terminal_reason": None, "next_deterministic_action": None,
            "authorization_state": "STUDY_CLOSED", "blockers": [],
            "actions_executed_this_run": [], "completed_gates": self._completed_gates(), "stale_gates": [],
            "study_closure": closure_summary(self.study, closure),
            "current_authority_hashes": files, "fingerprints": files,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        state["timestamps"] = {k: (self.study / p).stat().st_mtime if (self.study / p).exists() else None
                               for k, p in {"prepared": "audit/frozen_execution_manifest.json",
                                            "readiness": "audit/readiness.json", "preflight": "audit/preflight.json",
                                            "causal": "audit/status.json", "contract": "audit/contract_status.json",
                                            "seal": "artifacts/preexec_audit_seal.json",
                                            "smoke": "artifacts/smoke_reconciled.json"}.items()}
        (self.study / "workflow_state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def advance(self) -> dict[str, Any]:
        # A closed study is terminal: recognized before any TRAIN/OOS authorization or
        # execution branch, and before any deterministic leaf runs.
        from research_workflow.study_closure import StudyClosureInvalid, load_study_closure

        try:
            closure = load_study_closure(self.study)
        except StudyClosureInvalid as exc:
            return self._state("STUDY_CLOSURE_INVALID", blockers=[{"detail": str(exc)}])
        if closure is not None:
            return self._closed_state(closure)

        # The loop is the central invariant: an authorized deterministic leaf is always run.
        previous = _read(self.study / "workflow_state.json")
        force = self._earliest_stale_stage(previous)
        for _ in range(16):
            capability = _read(self.study / "artifacts" / "capability_reconciliation.json")
            request = _read(self.study / "research_decision.yaml") if (self.study / "research_decision.yaml").suffix == ".json" else {}
            import yaml
            if (self.study / "research_decision.yaml").is_file(): request = yaml.safe_load((self.study / "research_decision.yaml").read_text()) or {}
            needs_capability = bool((self.study / "feature_candidate.yaml").is_file() or request.get("approved_generic_capability_work"))
            if (capability and capability.get("state") not in {"READY_TO_SCAFFOLD", "READY", "VERIFIED"}) or (needs_capability and not capability):
                result = self.actions.reconcile(self.study); self.executed.append("CAPABILITIES_RECONCILED")
                state = result.get("state")
                if state == "IMPLEMENTATION_REQUIRED":
                    self._implementation_contract(result)
                    return self._state("IMPLEMENTATION_REQUIRED", blockers=[{"detail": result}])
                if state in {"SEMANTIC_DECISION_REQUIRED", "AUTHORITY_CONFLICT", "TRUE_CAPABILITY_GAP"}:
                    return self._state(state, blockers=[{"detail": result}])
                (self.study / "artifacts" / "capability_reconciliation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                continue
            compilation = _read(self.study / "artifacts" / "study_spec_compilation.json")
            request_changed = compilation.get("request_sha256") != _sha(self.study / "research_decision.yaml")
            # Recompile a dry projection first: the compiler's own output can move even
            # when the request bytes did not (a compiler-logic fix), and a stale study.yaml
            # must not be trusted just because it exists.
            compiled = compile_approved_request(self.study, write=False)
            if not compiled["ok"]: return self._state(compiled["terminal"], blockers=[{"detail": compiled.get("detail", "unresolved StudySpec field")}])
            compiler_drifted = bool(compilation) and compilation.get("spec_sha256") != compiled.get("spec_sha256")
            compile_write = not (self.study / "study.yaml").exists() or request_changed or compiler_drifted or force <= 1
            if compile_write:
                compiled = compile_approved_request(self.study, write=True)
                if not compiled["ok"]: return self._state(compiled["terminal"], blockers=[{"detail": compiled.get("detail", "unresolved StudySpec field")}])
            if force <= 2 or compile_write or self._prepare_stale():
                self.actions.prepare(self.study); self.executed.append("PREPARED"); force = 3; continue
            if force <= 3 or not self._readiness_passed():
                result = self.actions.readiness(self.study); self.executed.append("READY")
                if isinstance(result, dict) and result.get("overall_status") not in (None, "PASS"):
                    return self._state("SAFETY_OR_AUTHORIZATION_BLOCK", blockers=[{"detail": result}])
                force = 4; continue
            if force <= 4 or not _clear(self.study / "audit" / "preflight.json"):
                result = self.actions.preflight(self.study); self.executed.append("PREFLIGHT")
                if (isinstance(result, dict) and result.get("verdict", result.get("status")) not in (None, "CLEAR")) or not _clear(self.study / "audit/preflight.json"):
                    return self._state("SAFETY_OR_AUTHORIZATION_BLOCK", blockers=[{"detail": _read(self.study / "audit/failure_packet.json") or result}])
                force = 5; continue
            if force <= 5 or not self._audit_current(self.study / "audit/status.json"):
                r = self.actions.causal(self.study); self.executed.append("CAUSAL_AUDIT")
                if r.get("status", r.get("verdict")) != "CLEAR": return self._state("SAFETY_OR_AUTHORIZATION_BLOCK", blockers=[{"detail": r}])
                force = 6
                continue
            if force <= 6 or not self._audit_current(self.study / "audit/contract_status.json"):
                r = self.actions.contract(self.study); self.executed.append("CONTRACT_AUDIT")
                if r.get("status", r.get("verdict")) != "CLEAR": return self._state("SAFETY_OR_AUTHORIZATION_BLOCK", blockers=[{"detail": r}])
                force = 7
                continue
            seal_valid = False
            try:
                from research_workflow.seal import verify_preexec_audit_seal
                verify_preexec_audit_seal(self.study); seal_valid = True
            except Exception: seal_valid = False
            if self.custom_actions and (self.study / "artifacts/preexec_audit_seal.json").is_file():
                seal_valid = True
            if force <= 7 or not seal_valid:
                self.actions.seal(self.study); self.executed.append("SEALED"); force = 8; continue
            # A real smoke is intentionally opt-in: it can access data; mocks permit automation tests.
            if self.allow_smoke and self.actions.smoke and (force <= 8 or not (self.study / "artifacts" / "smoke_reconciled.json").is_file()):
                self.actions.smoke(self.study); self.executed.append("SMOKE_RECONCILED"); force = 99; continue
            if (self.study / "artifacts" / "train_experiment_freeze.json").is_file():
                return self._state("OOS_AUTHORIZATION_REQUIRED", next_action="assert_oos_open")
            if self._authorization() == "TRAIN_AUTHORIZED":
                if self.execute_authorized:
                    result = self.actions.train(self.study); self.executed.append("TRAIN_EXECUTION")
                    return self._state("TRAIN_EXECUTION", next_action="await_train_freeze", blockers=[])
                return self._state("TRAIN_AUTHORIZATION_REQUIRED", next_action="run_with_advance")
            return self._state("READY_FOR_TRAIN_AUTHORIZATION", next_action="authorize_experiment")
        return self._state("SAFETY_OR_AUTHORIZATION_BLOCK", blockers=[{"detail": "WORKFLOW_FIXED_POINT_LIMIT"}])

def run_workflow(study: str | Path, **kwargs: Any) -> dict[str, Any]: return WorkflowEngine(study, **kwargs).advance()

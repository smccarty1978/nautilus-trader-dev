"""Platform-v2 lifecycle leaves: the stage implementations the governed controller runs
for a study authored in the six-kind grammar.

Stages (same vocabulary as the v1 controller):
    compile -> prepare -> readiness -> preflight -> tests -> causal_audit -> contract_audit -> seal
    -> smoke -> collection -> reconcile -> merge -> fit -> freeze -> oos -> analyze -> close

Every leaf returns the controller's receipt contract ``{"status": "PASS", "outputs": [...]}``
(``partitions`` for collection/oos) and writes deterministic artifacts under the study.
Long work (collection partitions) runs in child processes with a progress heartbeat and
resumes from partition manifests.  Nothing here imports a study or the legacy collector.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
NS = 1_000_000_000
PLAN_NAME = "compiled_plan.json"
KEY = ("observation_ts", "regime_start_ns", "checkpoint_index")
# Run by the `tests` stage before a study may seal. Kept to fast, capability-level guarantees:
# the golden host fixture, the grammar/compiler, the host core, date-bounded partition
# authorization, and the analysis operations. The slower end-to-end controller runs
# (test_lifecycle_v2, test_declarative_analysis) stay repo tests.
PLATFORM_TESTS = ("research_workflow/tests/test_golden_fixture.py", "research_workflow/tests/test_grammar_v2.py",
                  "research_workflow/tests/test_host_core.py", "research_workflow/tests/test_chronology_windows.py",
                  "research/analysis/tests/test_diagnostic_ops.py",
                  "research_workflow/tests/test_train_provenance_attestation.py")

# Single source of truth for the deliverable each stage writes -- research_workflow.audit_packets_v2
# builds DELIVERABLES_BY_STAGE from this constant so the audit packet cannot silently name a
# different filename than the one the lifecycle actually writes (red-team packet F1). Values are
# paths relative to the study directory; a "<year>" placeholder marks a per-partition path.
DELIVERABLES = {
    "compile": ["compiled_plan.json"],
    "prepare": ["audit/frozen_execution_manifest.json", "artifacts/experiment_authorization.json"],
    "readiness": ["audit/readiness.json"],
    "preflight": ["audit/preflight.json"],
    "tests": ["_work/controller/test_summary.json"],
    "causal_audit": ["audit/status.json"],
    "contract_audit": ["audit/contract_status.json"],
    "seal": ["artifacts/preexec_audit_seal.json"],
    "smoke": ["artifacts/smoke_acceptance.json"],
    "collection": ["_work/controller/partitions/train/<year>/{candidates,observations}.parquet"],
    "reconcile": ["_work/controller/reconcile.json"],
    "merge": ["_work/controller/merged/{candidates,observations}.parquet", "_work/controller/merged/identity.json"],
    "fit": ["artifacts/experiment_models.json"],
    "freeze": ["artifacts/train_experiment_freeze.json"],
    "oos": ["_work/controller/partitions/oos/<year>/{candidates,observations}.parquet"],
    "analyze": ["artifacts/experiment_analysis_v2.json"],
    "close": ["artifacts/study_closure.json"],
}
# fit additionally writes artifacts/tuning_trials.json (+ tuning_optuna.db for the optuna sampler)
# when the plan declares a model.search_space; not a fixed filename, so callers that need it
# should check plan["model"].get("search_space") and add it themselves (see audit_packets_v2).
FIT_TUNING_DELIVERABLES = ["artifacts/tuning_trials.json"]


class CapabilityGapBlocked(RuntimeError):
    def __init__(self, report: Dict[str, Any]) -> None:
        super().__init__("CAPABILITY_GAP: " + ", ".join(report.get("kinds") or []))
        self.report = report


class LifecycleV2Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> Optional[str]:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _model_record_name(m: Mapping[str, Any]) -> str:
    """Stable key for one model record, across both shapes it is written in.

    Score mode writes ``name``; a multi-arm/multi-cell TRAIN fit writes ``arm``/``cell`` and no
    ``name`` (the model's own lineage calls that pair ``model_role``). freeze and oos key
    ``model_hashes`` / ``model_canonical_sha256`` by this name, so the two stages MUST derive it
    the same way or the freeze's canonical sha is unfindable at OOS.
    """
    if m.get("name"):
        return str(m["name"])
    if m.get("arm") or m.get("cell"):
        return f"{m.get('arm') or 'primary'}:{m.get('cell') or 'all'}"
    raise LifecycleV2Error(f"MODEL_RECORD_UNNAMED: model record has neither 'name' nor 'arm'/'cell': {sorted(m)}")


def _model_record_id(m: Mapping[str, Any]) -> str:
    """The model-store id of one record: score mode writes ``id``, a TRAIN fit writes ``model_id``."""
    mid = m.get("id") or m.get("model_id")
    if not mid:
        raise LifecycleV2Error(f"MODEL_RECORD_UNIDENTIFIED: model record has neither 'id' nor 'model_id': {sorted(m)}")
    return str(mid)


def spec_sha256(study: Path) -> Optional[str]:
    p = Path(study) / "study.yaml"
    if not p.is_file():
        return None
    from research_workflow.grammar.plan import canonical_json
    return hashlib.sha256(canonical_json(yaml.safe_load(p.read_text(encoding="utf-8")) or {}).encode("utf-8")).hexdigest()


def is_v2_study(study: Path) -> bool:
    p = Path(study) / "study.yaml"
    if not p.is_file():
        return False
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return isinstance(data, dict) and "streams" in data and not (isinstance(data.get("study"), dict) and data["study"].get("type"))


def load_plan(study: Path) -> Dict[str, Any]:
    plan = _read(Path(study) / PLAN_NAME)
    if not plan:
        raise LifecycleV2Error("COMPILED_PLAN_MISSING: run --through compile")
    return plan


def _strict_int_year(y: Any) -> int:
    """Normalize a requested year to ``int`` without ever truncating a fractional value.
    ``bool`` is rejected even though it is an ``int`` subclass (``True``/``False`` are not
    years). An integral float/str (``2023.0`` / ``"2023"``) normalizes to ``int``; a
    fractional float/str (``2023.5`` / ``"2023.5"``) raises rather than silently truncating."""
    if isinstance(y, bool):
        raise ValueError(f"{y!r} is a bool, not a year")
    if isinstance(y, int):
        return y
    if isinstance(y, float):
        if y.is_integer():
            return int(y)
        raise ValueError(f"{y!r} is not an integral year")
    if isinstance(y, str):
        try:
            f = float(y)
        except ValueError:
            raise ValueError(f"{y!r} is not a numeric year")
        if f.is_integer():
            return int(f)
        raise ValueError(f"{y!r} is not an integral year")
    raise ValueError(f"{y!r} is not a year")


def authorized_years(plan: Dict[str, Any], period: str, requested: Optional[Sequence[Any]], *,
                      authorization: Optional[Mapping[str, Any]] = None) -> List[int]:
    """Resolve the exact years a stage may execute against its authorized chronology role.

    ``period`` is ``"train"`` (collection/reconcile/merge/fit) or ``"oos"``/``"dev"``
    (oos/analyze; ``"dev"`` is an alias of ``"oos"``). The CLI may only NARROW the role's
    declared years, never expand them, and a prohibited year is never executable under
    either role. ``requested=None`` resolves to exactly the role's authorized years; an
    empty requested list is rejected outright (it is not "everything").

    If ``authorization`` (the parsed ``artifacts/experiment_authorization.json``) is
    supplied, its recorded train_years/oos_years/prohibited_years for this role must agree
    with the plan's chronology, or the authorization artifact is stale and the request is
    rejected -- a plan re-compiled after PREPARE wrote the authorization artifact must not
    silently execute against the old, unauthorized role years.
    """
    if period not in ("train", "oos", "dev"):
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: unknown period {period!r}")
    role = "train" if period == "train" else "dev"
    chron = plan.get("chronology") or {}
    try:
        role_years = sorted({int(y) for y in (chron.get(role) or [])})
    except (TypeError, ValueError) as exc:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: plan.chronology.{role} is malformed: {exc}")
    prohibited = {int(y) for y in (chron.get("prohibited") or [])}

    if authorization is not None:
        auth_role_key = "train_years" if role == "train" else "oos_years"
        auth_years = sorted({int(y) for y in (authorization.get(auth_role_key) or [])})
        auth_prohibited = {int(y) for y in (authorization.get("prohibited_years") or [])}
        if auth_years != role_years or auth_prohibited != prohibited:
            raise LifecycleV2Error(
                f"YEARS_NOT_AUTHORIZED: period={period} stale experiment_authorization.json "
                f"(plan.chronology.{role}={role_years}/prohibited={sorted(prohibited)} != "
                f"authorization.{auth_role_key}={auth_years}/prohibited_years={sorted(auth_prohibited)})")
        # A window narrows an authorized year to explicit dates. If the plan's windows and the
        # recorded authorization's windows disagree, the authorization artifact is stale against
        # a re-compiled plan and the run is refused rather than executed against the old dates.
        plan_windows = windows_identity((chron.get("windows") or []))
        auth_windows = sorted(str(w) for w in (authorization.get("partition_windows") or []))
        if auth_windows != plan_windows:
            raise LifecycleV2Error(
                f"WINDOWS_NOT_AUTHORIZED: stale experiment_authorization.json "
                f"(plan.chronology.windows={plan_windows} != authorization.partition_windows={auth_windows})")

    if requested is None:
        overlap = sorted(set(role_years) & prohibited)
        if overlap:
            raise LifecycleV2Error(
                f"YEARS_NOT_AUTHORIZED: role years intersect prohibited (period={period} role={role} "
                f"years={role_years} prohibited={sorted(prohibited)} overlap={overlap})")
        return role_years
    try:
        req = sorted({_strict_int_year(y) for y in requested})
    except ValueError as exc:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} non-integer year: {exc}")
    if not req:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} requested=[] authorized={role_years} prohibited={sorted(prohibited)}")
    if any(y in prohibited for y in req) or any(y not in role_years for y in req):
        raise LifecycleV2Error(
            f"YEARS_NOT_AUTHORIZED: period={period} requested={req} authorized={role_years} prohibited={sorted(prohibited)}")
    return req


def _merge_window_stats(stats: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-window run stats into one partition-level record.

    Numeric counters sum; anything structured (nested per-stream dicts, strings) is kept as the
    ordered per-window list so a merged partition never fabricates a single value for something
    that was actually measured once per window.
    """
    merged: Dict[str, Any] = {}
    for key in sorted({k for s in stats for k in s}):
        values = [s.get(key) for s in stats]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values if v is not None):
            merged[key] = sum(v for v in values if v is not None)
        else:
            merged[key] = values
    return merged


def partition_windows(plan: Dict[str, Any], year: int) -> List[Dict[str, Any]]:
    """The declared date-bounded windows for one role year, or [] when the year runs whole.

    ``chronology.windows`` narrows an already-authorized role year to explicit inclusive date
    ranges; a year with no declared window keeps whole-year behaviour.
    """
    return [w for w in ((plan.get("chronology") or {}).get("windows") or []) if int(w["year"]) == int(year)]


def authorized_windows(plan: Dict[str, Any], requested: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Resolve the windows a run may execute. ``requested`` (CLI ``--windows``) may only NARROW
    the declared set: an unknown window id is refused rather than executed."""
    declared = list((plan.get("chronology") or {}).get("windows") or [])
    if requested is None:
        return declared
    wanted = {str(w).strip().replace("..", "_") for w in requested}
    if not wanted:
        raise LifecycleV2Error("WINDOWS_NOT_AUTHORIZED: requested=[] is not 'everything'")
    known = {w["id"] for w in declared}
    unknown = sorted(wanted - known)
    if unknown:
        raise LifecycleV2Error(f"WINDOWS_NOT_AUTHORIZED: requested={unknown} declared={sorted(known)}")
    return [w for w in declared if w["id"] in wanted]


def windows_identity(windows: Sequence[Mapping[str, Any]]) -> List[str]:
    return sorted(f"{w['year']}:{w['start']}..{w['end']}" for w in windows)


@dataclass
class V2Options:
    execute: bool = False
    smoke_date: Optional[str] = None
    years: Optional[List[int]] = None
    windows: Optional[List[str]] = None
    closure: Optional[Dict[str, str]] = None
    studies_root: Optional[Path] = None
    datasets_dir: Optional[Path] = None
    extra_bindings: Optional[Mapping[str, Any]] = None
    bar_source: Optional[Callable[[str, str], Any]] = None      # test hook: (start_date, end_date) -> [BarView]
    session_table_spec: Optional[Mapping[str, Any]] = None      # test hook
    warmup_days: int = 5
    max_runtime: float = 6 * 3600
    progress_every_bars: int = 200_000
    in_process_partitions: bool = False
    # W-5: when set, every model-store call this lifecycle makes (fit/score/authenticate)
    # writes to and reads from THIS root instead of the operator's real durable store
    # (research_workflow.roots.resolve_model_root()). None preserves the configured root --
    # every non-test caller keeps writing to the real store exactly as before.
    model_root: Optional[Path] = None


class V2Lifecycle:
    def __init__(self, study: Path, *, repo_root: Path = REPO_ROOT, options: Optional[V2Options] = None) -> None:
        self.study = Path(study).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.opts = options or V2Options()
        self.work = self.study / "_work" / "controller"
        self.audit = self.study / "audit"
        self.artifacts = self.study / "artifacts"

    # -- identities ---------------------------------------------------------------
    def compile_outcome(self):
        from research_workflow.grammar import compile_study, load_spec
        return compile_study(load_spec(self.study), repo_root=self.repo_root, datasets_dir=self.opts.datasets_dir,
                             extra_bindings=self.opts.extra_bindings)

    def current_composite(self) -> Optional[str]:
        try:
            out = self.compile_outcome()
        except Exception:
            return None
        return out.plan.closure["composite_sha256"] if out.ok else None

    def fingerprints(self) -> Dict[str, Optional[str]]:
        plan = _read(self.study / PLAN_NAME)
        frozen = _read(self.audit / "frozen_execution_manifest.json")
        return {
            "study_spec": spec_sha256(self.study), "compiled_plan": _sha(self.study / PLAN_NAME),
            "plan_sha256": plan.get("plan_sha256"), "plan_spec_sha256": plan.get("spec_sha256"),
            "plan_closure_composite": (plan.get("closure") or {}).get("composite_sha256"),
            "execution_freeze": _sha(self.audit / "frozen_execution_manifest.json"),
            "execution_composite": frozen.get("frozen_execution_composite_sha256"),
            "current_execution_composite": self.current_composite(),
            "preflight": _sha(self.audit / "preflight.json"), "causal_status": _sha(self.audit / "status.json"),
            "contract_status": _sha(self.audit / "contract_status.json"), "seal": _sha(self.artifacts / "preexec_audit_seal.json"),
            "train_freeze": _sha(self.artifacts / "train_experiment_freeze.json"),
        }

    def _authorized_years(self, plan: Dict[str, Any], period: str, requested: Optional[Sequence[Any]] = None) -> List[int]:
        auth_path = self.artifacts / "experiment_authorization.json"
        authorization = _read(auth_path) if auth_path.is_file() else None
        return authorized_years(plan, period, requested, authorization=authorization)

    def _require_execute(self, stage: str) -> None:
        """Guard so a direct programmatic caller of a post-seal leaf (bypassing
        V2StudyController.run's EXECUTION_NOT_AUTHORIZED gate) cannot execute without
        --execute-authorized either."""
        if not self.opts.execute:
            raise LifecycleV2Error(f"EXECUTION_NOT_AUTHORIZED: {stage} requires --execute-authorized")

    def _zero_study_python(self) -> tuple[List[str], Optional[str]]:
        """R10 / ZERO_STUDY_PYTHON: any committed study-local executable Python (or notebook)
        is a reject unless the study id has a platform-sanctioned exception. Returns
        (python_files, exception_reason_or_None)."""
        from research_workflow.policy import STUDY_PYTHON_EXCEPTIONS, scan_study_python
        py_files = scan_study_python(self.study)
        return py_files, (STUDY_PYTHON_EXCEPTIONS.get(self.study.name) if py_files else None)

    def _seal_identities(self) -> Dict[str, str]:
        seal = _read(self.artifacts / "preexec_audit_seal.json")
        if not seal.get("composite_seal_hash"):
            raise LifecycleV2Error("PREEXEC_SEAL_MISSING")
        return {"composite_seal_hash": seal["composite_seal_hash"], "execution_manifest_sha256": seal.get("execution_manifest_composite_sha256")}

    # -- stages -------------------------------------------------------------------------
    def compile(self, study: Path | None = None) -> Dict[str, Any]:
        out = self.compile_outcome()
        if not out.ok:
            report = out.gaps.to_dict()
            _write(self.work / "capability_gap.json", report)
            raise CapabilityGapBlocked(report)
        path = out.plan.write(self.study / PLAN_NAME)
        card = out.plan.card()
        _write(self.artifacts / "compile_card.json", {**card, "written_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)], "card": card}

    def prepare(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        chron = plan["chronology"]
        auth_path = self.artifacts / "experiment_authorization.json"
        if chron.get("dev"):
            from research_workflow.experiment import authorize_experiment
            authorize_experiment(self.study, write=True)
        else:
            from research.analysis.identity import canonical_sha256
            body = {"schema_version": 1, "study_id": plan["study"]["id"], "study_path": f"studies/{self.study.name}",
                    "train_years": list(chron["train"]), "oos_years": [], "prohibited_years": list(chron.get("prohibited") or []),
                    "generated_at_utc": _now()}
            body["authorization_sha256"] = canonical_sha256({k: v for k, v in body.items() if k != "generated_at_utc"})
            _write(auth_path, body)
        # Date-bounded authorization is recorded next to the year roles for BOTH branches, so a
        # stale authorization (a plan re-compiled with different windows after PREPARE) is caught
        # by authorized_years() before any partition streams a bar.
        if chron.get("windows"):
            body = _read(auth_path)
            body["partition_windows"] = windows_identity(chron["windows"])
            _write(auth_path, body)
        frozen = {"schema_version": 2, "hash_algorithm": plan["closure"]["hash_algorithm"], "authority": "platform_v2_plan_closure",
                  "plan_sha256": plan["plan_sha256"], "spec_sha256": plan["spec_sha256"],
                  "frozen_execution_composite_sha256": plan["closure"]["composite_sha256"], "files": plan["closure"]["files"],
                  "file_count": plan["closure"]["file_count"], "stages": plan["closure"].get("stages") or {}, "generated_at_utc": _now()}
        path = _write(self.audit / "frozen_execution_manifest.json", frozen)
        return {"status": "PASS", "outputs": [str(path), str(auth_path)]}

    def readiness(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        checks: List[Dict[str, Any]] = []
        # R1 dataset identity + bytes (skipped only for an injected synthetic bar source)
        for sym, inst in plan["instruments"].items():
            if self.opts.bar_source is not None:
                checks.append({"id": f"R1_{sym}", "passed": True, "detail": "SYNTHETIC_BAR_SOURCE: no catalog to resolve"})
                continue
            try:
                from research_workflow.roots import resolve_dataset, verify_dataset_bytes
                r = resolve_dataset(inst["dataset_id"], self.repo_root)
                ok = (inst.get("dataset_digest") in (None, r.logical_digest))
                digest = verify_dataset_bytes(r.catalog_path, r.logical_digest)["logical_digest"] if r.logical_digest else None
                checks.append({"id": f"R1_{sym}", "passed": bool(ok and (digest is None or digest == r.logical_digest)),
                               "detail": f"{inst['dataset_id']} resolved via {r.resolution}; digest {str(r.logical_digest)[:12]} bytes verified"})
            except Exception as exc:
                checks.append({"id": f"R1_{sym}", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        from scripts.lint_host import HOST_DIR, lint_file
        findings = [f for p in sorted(HOST_DIR.glob("*.py")) for f in lint_file(p)]
        checks.append({"id": "R8_host_boundary_lint", "passed": not findings, "detail": f"{len(findings)} findings"})
        unbound = [b for b in plan["binding_proof"] if not b.get("bound")]
        checks.append({"id": "R5_binding_proof", "passed": not unbound, "detail": f"{len(plan['binding_proof'])} primitives bound; unbound={[b['id'] for b in unbound]}"})
        try:
            from research_workflow.sessions import build_session_table, resolve_calendar_session_spec
            raw_spec = dict(self.opts.session_table_spec or plan["session"])
            resolved_spec = resolve_calendar_session_spec(raw_spec, self.repo_root)
            build_session_table(resolved_spec)
            detail = {"kind": resolved_spec.get("kind"), "session": resolved_spec.get("session"),
                      "censor_session": resolved_spec.get("censor_session"), "reference_digest": resolved_spec.get("reference_digest"),
                      "window_count": len(resolved_spec.get("rows") or []) if resolved_spec.get("kind") == "calendar" else None,
                      "reference_row_counts": resolved_spec.get("reference_row_counts")}
            checks.append({"id": "R3_session_table", "passed": True, "detail": json.dumps(detail, default=str)})
        except Exception as exc:
            checks.append({"id": "R3_session_table", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        current = self.current_composite()
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        checks.append({"id": "R9_closure_current", "passed": bool(current and current == frozen), "detail": f"current={str(current)[:12]} frozen={str(frozen)[:12]}"})
        py_files, py_exception = self._zero_study_python()
        checks.append({"id": "R10_zero_study_python", "passed": not py_files or py_exception is not None,
                       "detail": json.dumps({"python_files": py_files, "exception": py_exception})})
        overall = all(c["passed"] for c in checks)
        path = _write(self.audit / "readiness.json", {"schema_version": 2, "overall_status": "PASS" if overall else "FAIL", "checks": checks,
                                                       "execution_composite_sha256": frozen, "plan_sha256": plan["plan_sha256"], "generated_at_utc": _now()})
        if not overall:
            raise LifecycleV2Error("READINESS_FAILED: " + "; ".join(c["id"] for c in checks if not c["passed"]))
        return {"status": "PASS", "outputs": [str(path)]}

    def preflight(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        outcomes: Dict[str, str] = {}
        outcomes["PLAN_BOUND_TO_SPEC"] = "PASSED" if plan.get("spec_sha256") == spec_sha256(self.study) else "FAILED"
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        outcomes["EXECUTION_MANIFEST"] = "PASSED" if frozen and frozen == self.current_composite() else "FAILED"
        from research_workflow.entry_references import resolve_entry_reference
        _, problem = resolve_entry_reference(plan["outcome"]["entry_reference"], plan["outcome"]["contract"])
        outcomes["ENTRY_REFERENCE_EXECUTABLE"] = "PASSED" if problem is None or plan["outcome"]["kernel"] == "flip" else "FAILED"
        from research_workflow.forward_outcomes.guard import find_outcome_columns
        leaked = find_outcome_columns(list(plan["columns"]["features"]) + [m["column"] for m in plan["columns"]["metadata"]])
        outcomes["FORWARD_OUTCOME_GUARD"] = "PASSED" if not leaked else "FAILED"
        model = plan.get("model") or {}
        outcomes["CHRONOLOGY_ROLE_TABLE"] = "PASSED" if (not model or (model.get("validation") or {}).get("year_role_table") is not None or model.get("validation") is None) else "FAILED"
        py_files, py_exception = self._zero_study_python()
        outcomes["ZERO_STUDY_PYTHON"] = "PASSED" if (not py_files or py_exception is not None) else f"FAILED: {py_files}"
        try:
            from research_workflow.host.predicate_eval import compile_predicate
            ef = {t["id"]: set(t.get("epoch_fields") or ()) for t in plan["trackers"]}
            if plan["population"].get("qualify"):
                compile_predicate(plan["population"]["qualify"]["ast"], epoch_fields=ef, allow_events=False)
            trig = plan["triggers"]
            if trig.get("kind") == "graph":
                for st in trig["states"].values():
                    compile_predicate(st["enter_when"]["ast"], epoch_fields=ef)
                    if st.get("expire_when"):
                        compile_predicate(st["expire_when"]["ast"], epoch_fields=ef)
                if trig.get("entry"):
                    compile_predicate(trig["entry"]["when"]["ast"], epoch_fields=ef)
            outcomes["PREDICATES_COMPILE"] = "PASSED"
        except Exception as exc:
            outcomes["PREDICATES_COMPILE"] = f"FAILED: {exc}"
        outcomes["CAUSAL_INVARIANTS"] = "PASSED" if all(v == "PASSED" for k, v in outcomes.items()) else "FAILED"
        ready = all(v == "PASSED" for v in outcomes.values())
        path = _write(self.audit / "preflight.json", {"schema_version": 2, "status": "CLEAR" if ready else "BLOCKED", "audit_ready": ready,
                                                       "check_outcomes": outcomes, "required_checks": list(outcomes), "execution_composite_sha256": frozen,
                                                       "plan_sha256": plan["plan_sha256"], "leaked_outcome_columns": leaked,
                                                       "study_python": {"python_files": py_files, "exception": py_exception}, "generated_at_utc": _now()})
        if not ready:
            raise LifecycleV2Error("PREFLIGHT_BLOCKED: " + ", ".join(k for k, v in outcomes.items() if v != "PASSED"))
        return {"status": "PASS", "outputs": [str(path)]}

    def tests(self, study: Path | None = None) -> Dict[str, Any]:
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        files = [str(self.repo_root / t) for t in PLATFORM_TESTS if (self.repo_root / t).is_file()]
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=str(self.repo_root),
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr)[-3000:]
        import re
        m = re.search(r"(\d+) passed", tail); f = re.search(r"(\d+) failed", tail)
        counts = {"passed": int(m.group(1)) if m else 0, "failed": int(f.group(1)) if f else 0}
        status = "PASS" if r.returncode == 0 else "FAIL"
        path = _write(self.work / "test_summary.json", {"status": status, "counts": counts, "files": files, "execution_composite_sha256": frozen, "tail": tail})
        if status != "PASS":
            raise LifecycleV2Error(f"PLATFORM_TESTS_FAILED: {counts}")
        return {"status": "PASS", "outputs": [str(path)]}

    def seal(self, study: Path | None = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        audits = {}
        for kind, name in (("causal", "status.json"), ("contract", "contract_status.json")):
            st = _read(self.audit / name)
            if st.get("verdict") != "CLEAR" or st.get("audited_execution_composite_sha256") != frozen:
                raise LifecycleV2Error(f"AUDIT_NOT_CLEAR_OR_STALE: {kind}")
            audits[kind] = {"auditor": st.get("auditor"), "report_sha256": st.get("audit_report_sha256"), "status_sha256": _sha(self.audit / name)}
        body = {"schema_version": 2, "platform": "v2", "study_id": plan["study"]["id"], "plan_sha256": plan["plan_sha256"],
                "execution_manifest_composite_sha256": frozen, "audits": audits, "registry_sha256": plan.get("registry_sha256"), "sealed_at_utc": _now()}
        body["composite_seal_hash"] = hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "sealed_at_utc"}, sort_keys=True).encode()).hexdigest()
        path = _write(self.artifacts / "preexec_audit_seal.json", body)
        return {"status": "PASS", "outputs": [str(path)]}

    # -- execution ----------------------------------------------------------------------------
    def _run_window(self, plan: Dict[str, Any], start: str, end: str, primary: tuple, *, progress: Optional[Path], ledger: bool = False) -> Dict[str, Any]:
        if self.opts.bar_source is not None:
            from research_workflow.host_runner import run_plan_on_bars
            from research_workflow.sessions import build_session_table, resolve_calendar_session_spec
            bars = self.opts.bar_source(start, end)
            table = build_session_table(resolve_calendar_session_spec(dict(self.opts.session_table_spec or plan["session"]), self.repo_root))
            ledger_rows: List[Dict[str, Any]] = [] if ledger else None
            run = run_plan_on_bars(plan, bars, session_table=table, primary_interval=primary, ledger=ledger_rows)
            run["dataset"] = {"dataset_id": "synthetic", "logical_digest": None, "bytes_verification": "SYNTHETIC"}
            run["ledger"] = ledger_rows
            return run
        from research_workflow.host_runner import run_plan_on_catalog
        return run_plan_on_catalog(plan, start_date=start, end_date=end, repo_root=self.repo_root, primary_interval=primary,
                                   warmup_days=self.opts.warmup_days, progress_path=progress, progress_every_bars=self.opts.progress_every_bars,
                                   session_table_spec=self.opts.session_table_spec, studies_root=self.opts.studies_root or (self.repo_root / "studies"), ledger=ledger)

    @staticmethod
    def _persist(run: Dict[str, Any], out_dir: Path, extra: Mapping[str, Any]) -> Dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        c, o = out_dir / "candidates.parquet", out_dir / "observations.parquet"
        run["candidates"].to_parquet(c, index=False)
        run["observations"].to_parquet(o, index=False)
        manifest = {**extra, "status": "PASS", "candidates_sha256": _sha(c), "observations_sha256": _sha(o),
                    "rows": {"candidates": int(len(run["candidates"])), "observations": int(len(run["observations"]))},
                    "stats": run["stats"], "elapsed_s": run["elapsed_s"], "dataset": run.get("dataset"), "written_at_utc": _now()}
        _write(out_dir / "manifest.json", manifest)
        return manifest

    def smoke(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("smoke")
        plan = load_plan(self.study)
        ids = self._seal_identities()
        date = self.opts.smoke_date or ((plan["chronology"].get("authorized_dates") or [None])[0])
        if not date:
            raise LifecycleV2Error("SMOKE_DATE_REQUIRED: pass --smoke-date or declare chronology.authorized_dates")
        import pandas as pd
        s, e = int(pd.Timestamp(f"{date} 00:00:00", tz="UTC").value), int(pd.Timestamp(f"{date} 23:59:59.999999999", tz="UTC").value)
        run_dir = self.study / "runs" / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self.study.name}_smoke"
        run = self._run_window(plan, date, date, (s, e), progress=self.work / "smoke.progress.json")
        manifest = self._persist(run, run_dir / "collection", {"kind": "smoke", "date": date, "plan_sha256": plan["plan_sha256"], **ids})
        cands, obs = run["candidates"], run["observations"]
        keys_c = set(map(tuple, cands[list(KEY)].itertuples(index=False, name=None))) if len(cands) else set()
        keys_o = set(map(tuple, obs[list(KEY)].itertuples(index=False, name=None))) if len(obs) else set()
        from research_workflow.forward_outcomes.guard import find_outcome_columns
        leaked = find_outcome_columns([c for c in cands.columns if c not in KEY])
        checks = {"candidates_nonempty": len(cands) > 0, "observation_per_candidate": keys_c == keys_o,
                  "no_outcome_columns_in_candidates": not leaked, "primary_window_respected": bool(len(cands) == 0 or (cands["observation_ts"].between(s, e).all())),
                  "pending_resolved_at_run_end": run["stats"].get("pending_at_end") == 0}
        accepted = all(checks.values())
        path = _write(self.artifacts / "smoke_acceptance.json", {"status": "ACCEPTED" if accepted else "REJECTED", "study_name": self.study.name, "date": date,
                                                                 "sealed_composite_sha256": ids["composite_seal_hash"], "execution_manifest_composite_sha256": ids["execution_manifest_sha256"],
                                                                 "run_dir": str(run_dir), "candidates_count_total": int(len(cands)), "observations_count_total": int(len(obs)),
                                                                 "checks": checks, "manifest": manifest, "validator": "research_workflow.lifecycle_v2", "generated_at_utc": _now()})
        if not accepted:
            raise LifecycleV2Error("SMOKE_REJECTED: " + ", ".join(k for k, v in checks.items() if not v))
        return {"status": "PASS", "outputs": [str(path), str(run_dir / "collection" / "candidates.parquet"), str(run_dir / "collection" / "observations.parquet")]}

    def _partition_bounds(self, plan: Dict[str, Any], year: int, period: str) -> Dict[str, Any]:
        """Whole-year bounds for one role year, with the outcome lookahead tail."""
        import pandas as pd
        years = set(plan["chronology"]["train"]) | set(plan["chronology"].get("dev") or [])
        horizon_ns = max([a["horizon_ns"] for a in plan["outcome"].get("arms") or []] + [((plan["outcome"].get("flip") or {}).get("horizon_ns") or 0)])
        primary_start, primary_end = f"{year}-01-01", f"{year}-12-31"
        end = pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) + pd.Timedelta(seconds=horizon_ns // NS)
        run_end = end.strftime("%Y-%m-%d") if end.year in years else primary_end
        s = int(pd.Timestamp(primary_start, tz="UTC").value)
        e = int((pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
        return {"id": f"{period}-{year}", "year": year, "period": period, "primary_start": primary_start, "primary_end": primary_end, "run_end": run_end, "primary_ns": (s, e)}

    def _window_bounds(self, plan: Dict[str, Any], window: Mapping[str, Any], period: str) -> Dict[str, Any]:
        """Bounds for one declared date window.

        The window is a HARD data boundary: unlike a whole-year partition there is no forward
        lookahead tail, because a tail would stream bars the study never authorized. Any candidate
        whose outcome cannot resolve inside the window is left pending, and ``run_partition``
        refuses the partition rather than silently censoring it -- an unresolved row is proof the
        declared window is too narrow for the declared outcome, which is a spec defect, not data.
        """
        import pandas as pd
        start, end = str(window["start"]), str(window["end"])
        s = int(pd.Timestamp(start, tz="UTC").value)
        e = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
        return {"id": f"{period}-{window['id']}", "year": int(window["year"]), "period": period, "window_id": str(window["id"]),
                "primary_start": start, "primary_end": end, "run_end": end, "primary_ns": (s, e)}

    def _partition_valid(self, out_dir: Path, plan_sha: str, seal: str) -> bool:
        m = _read(out_dir / "manifest.json")
        if not m or m.get("status") != "PASS" or m.get("plan_sha256") != plan_sha or m.get("composite_seal_hash") != seal:
            return False
        return _sha(out_dir / "candidates.parquet") == m.get("candidates_sha256") and _sha(out_dir / "observations.parquet") == m.get("observations_sha256")

    def run_partition(self, year: int, period: str, out_dir: Path, *, progress: Optional[Path] = None) -> Dict[str, Any]:
        """One partition for one role year.

        A year with declared ``chronology.windows`` runs one bounded sub-run per window and
        concatenates them into the single per-year partition every downstream stage already
        reads; a year with no window keeps the whole-year path unchanged.
        """
        import pandas as pd
        plan = load_plan(self.study)
        ids = self._seal_identities()
        windows = [w for w in authorized_windows(plan, self.opts.windows) if int(w["year"]) == int(year)]
        declared_for_year = partition_windows(plan, year)
        if declared_for_year and not windows:
            raise LifecycleV2Error(f"WINDOWS_NOT_AUTHORIZED: {period}-{year} declares windows but none were selected")
        if not declared_for_year:
            b = self._partition_bounds(plan, year, period)
            run = self._run_window(plan, b["primary_start"], b["run_end"], b["primary_ns"], progress=progress)
            return self._persist(run, out_dir, {"kind": "partition", **{k: v for k, v in b.items() if k != "primary_ns"},
                                                "windows": [], "plan_sha256": plan["plan_sha256"], **ids})
        runs, bounds = [], []
        for w in windows:
            b = self._window_bounds(plan, w, period)
            r = self._run_window(plan, b["primary_start"], b["run_end"], b["primary_ns"], progress=progress)
            pending = int((r.get("stats") or {}).get("pending_at_end") or 0)
            if pending:
                raise LifecycleV2Error(
                    f"WINDOW_OUTCOME_UNRESOLVED: {b['id']} left {pending} candidate(s) unresolved at the window "
                    f"boundary; the declared window cannot resolve the declared outcome")
            runs.append(r); bounds.append({k: v for k, v in b.items() if k != "primary_ns"})
        merged = {"candidates": pd.concat([r["candidates"] for r in runs], ignore_index=True),
                  "observations": pd.concat([r["observations"] for r in runs], ignore_index=True),
                  "stats": _merge_window_stats([r.get("stats") or {} for r in runs]),
                  "elapsed_s": sum(float(r.get("elapsed_s") or 0.0) for r in runs),
                  "dataset": runs[0].get("dataset")}
        digests = {json.dumps(r.get("dataset") or {}, sort_keys=True) for r in runs}
        if len(digests) > 1:
            raise LifecycleV2Error(f"WINDOW_DATASET_MISMATCH: {period}-{year} windows read different datasets")
        return self._persist(merged, out_dir, {
            "kind": "partition", "id": f"{period}-{year}", "year": int(year), "period": period,
            "primary_start": bounds[0]["primary_start"], "primary_end": bounds[-1]["primary_end"],
            "run_end": bounds[-1]["run_end"], "date_bounded": True,
            "windows": [{k: b[k] for k in ("id", "window_id", "primary_start", "primary_end")} for b in bounds],
            "window_rows": [int(len(r["candidates"])) for r in runs],
            "plan_sha256": plan["plan_sha256"], **ids})

    def _collect_period(self, period: str) -> Dict[str, Any]:
        plan = load_plan(self.study)
        ids = self._seal_identities()
        years = self._authorized_years(plan, period, self.opts.years)
        if not years:
            raise LifecycleV2Error(f"NO_YEARS_FOR_PERIOD: {period}")
        base = self.work / "partitions" / period
        partitions, outputs = [], []
        for year in years:
            out_dir = base / str(year)
            if not self._partition_valid(out_dir, plan["plan_sha256"], ids["composite_seal_hash"]):
                progress = out_dir / "progress.json"
                if self.opts.in_process_partitions or self.opts.bar_source is not None:
                    self.run_partition(int(year), period, out_dir, progress=progress)
                else:
                    cmd = [sys.executable, "-m", "research_workflow.lifecycle_v2", "partition", "--study", str(self.study), "--period", period,
                           "--year", str(year), "--out-dir", str(out_dir), "--progress", str(progress), "--repo-root", str(self.repo_root)]
                    if self.opts.studies_root:
                        cmd += ["--studies-root", str(self.opts.studies_root)]
                    if self.opts.windows:
                        cmd += ["--windows", ",".join(self.opts.windows)]
                    out_dir.mkdir(parents=True, exist_ok=True)
                    with open(out_dir / "child.log", "w", encoding="utf-8") as log:
                        r = subprocess.run(cmd, cwd=str(self.repo_root), stdout=log, stderr=subprocess.STDOUT, timeout=self.opts.max_runtime)
                    if r.returncode != 0 or not self._partition_valid(out_dir, plan["plan_sha256"], ids["composite_seal_hash"]):
                        raise LifecycleV2Error(f"PARTITION_FAILED: {period}-{year} (see {out_dir / 'child.log'})")
            m = _read(out_dir / "manifest.json")
            partitions.append({"id": m["id"], "year": int(year), "status": "PASS", "rows": m.get("rows"), "manifest": str(out_dir / "manifest.json")})
            outputs += [str(out_dir / "candidates.parquet"), str(out_dir / "observations.parquet")]
            _write(self.work / f"{period}_collection_progress.json", {"period": period, "completed": [p["id"] for p in partitions], "of": len(years), "updated_at_utc": _now()})
        return {"status": "PASS", "outputs": outputs, "partitions": partitions}

    def collection(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("collection")
        return self._collect_period("train")

    def reconcile(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("reconcile")
        import pandas as pd
        plan = load_plan(self.study)
        base = self.work / "partitions" / "train"
        years = self._authorized_years(plan, "train", self.opts.years)
        findings: List[str] = []
        schemas, digests, rows = [], set(), 0
        seen_keys = 0
        for y in years:
            d = base / str(y)
            m = _read(d / "manifest.json")
            if m.get("status") != "PASS":
                findings.append(f"partition {y} not PASS"); continue
            c = pd.read_parquet(d / "candidates.parquet"); o = pd.read_parquet(d / "observations.parquet")
            schemas.append((tuple(c.columns), tuple(o.columns)))
            if (m.get("dataset") or {}).get("logical_digest"):
                digests.add(m["dataset"]["logical_digest"])
            if len(c) != len(o):
                findings.append(f"partition {y}: candidates {len(c)} != observations {len(o)}")
            if len(c) and c.duplicated(list(KEY)).any():
                findings.append(f"partition {y}: duplicate candidate keys")
            if len(c) and not pd.to_datetime(c["observation_ts"], unit="ns", utc=True).dt.year.eq(int(y)).all():
                findings.append(f"partition {y}: rows outside the primary year")
            # A date-bounded year is only reconciled against its DECLARED windows: proving rows sit
            # inside the calendar year would not detect a partition that streamed unauthorized dates.
            declared = partition_windows(plan, int(y))
            if declared and len(c):
                ts = pd.to_datetime(c["observation_ts"], unit="ns", utc=True)
                inside = False
                for w in declared:
                    lo = pd.Timestamp(w["start"], tz="UTC")
                    hi = pd.Timestamp(w["end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                    inside = ((ts >= lo) & (ts <= hi)) if inside is False else (inside | ((ts >= lo) & (ts <= hi)))
                outside = int((~inside).sum())
                if outside:
                    findings.append(f"partition {y}: {outside} row(s) outside the declared windows "
                                    f"{[w['id'] for w in declared]}")
                if [str(x) for x in (m.get("windows") or [])] == []:
                    findings.append(f"partition {y}: manifest records no windows for a date-bounded year")
            rows += len(c); seen_keys += len(c)
        if len(set(schemas)) > 1:
            findings.append("partition output schema mismatch")
        if len(digests) > 1:
            findings.append(f"partitions read different dataset digests: {sorted(digests)}")
        path = _write(self.work / "reconcile.json", {"passed": not findings, "findings": findings, "years": list(years), "rows": rows,
                                                    "authority": "plan.chronology.train",
                                                    "partition_windows": windows_identity((plan.get("chronology") or {}).get("windows") or []),
                                                    "dataset_digests": sorted(digests),
                                                    "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                                                    "generated_at_utc": _now()})
        if findings:
            raise LifecycleV2Error("RECONCILE_FAILED: " + "; ".join(findings))
        return {"status": "PASS", "outputs": [str(path)]}

    def merge(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("merge")
        import pandas as pd
        from research.analysis.modeling import frame_content_identity
        plan = load_plan(self.study)
        years = self._authorized_years(plan, "train", self.opts.years)
        base = self.work / "partitions" / "train"
        cands = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years], ignore_index=True)
        obs = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years], ignore_index=True)
        if len(cands) and cands.duplicated(list(KEY)).any():
            raise LifecycleV2Error("MERGE_DUPLICATE_KEYS")
        cands = cands.sort_values(list(KEY), kind="mergesort").reset_index(drop=True)
        obs = obs.sort_values(list(KEY), kind="mergesort").reset_index(drop=True)
        out = self.work / "merged"; out.mkdir(parents=True, exist_ok=True)
        cands.to_parquet(out / "candidates.parquet", index=False); obs.to_parquet(out / "observations.parquet", index=False)
        ident = _write(out / "identity.json", {"candidates_identity": frame_content_identity(cands), "observations_identity": frame_content_identity(obs),
                                                "rows": int(len(cands)), "years": list(years), "authority": "plan.chronology.train", "plan_sha256": plan["plan_sha256"],
                                                "candidates_sha256": _sha(out / "candidates.parquet"), "observations_sha256": _sha(out / "observations.parquet"), "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(out / "candidates.parquet"), str(out / "observations.parquet"), str(ident)]}

    # -- modeling -------------------------------------------------------------------------------
    def _train_frame(self, plan: Dict[str, Any]):
        import pandas as pd
        merged = self.work / "merged"
        c = pd.read_parquet(merged / "candidates.parquet"); o = pd.read_parquet(merged / "observations.parquet")
        label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        frame = c.merge(o[list(KEY) + [label, "disposition"]], on=list(KEY), how="inner")
        frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
        return frame, label

    def fit(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("fit")
        plan = load_plan(self.study)
        model = plan.get("model")
        if not model:
            path = _write(self.artifacts / "fit_summary.json", {"status": "NO_MODEL_DECLARED", "plan_sha256": plan["plan_sha256"], "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)]}
        if model.get("mode") == "score":
            return self._fit_score_mode(plan, model)
        import numpy as np
        import pandas as pd

        from research.analysis.metrics import brier, pr_auc, roc_auc
        from research.analysis.modeling import _build_estimator, frame_content_identity
        from research_workflow.forward_outcomes.guard import assert_causal_feature_surface
        from research_workflow.model_store import GOLDEN_MIN_ROWS, ModelLineage, store_model
        frame, label = self._train_frame(plan)
        features = list(plan["columns"]["features"]) + list(plan["columns"].get("derived") or [])
        assert_causal_feature_surface(features, context="v2 fit feature surface")
        binary = frame[frame[label].isin([0, 1, 0.0, 1.0])].copy()
        family = str(model["family"]).split(".", 1)[-1]
        params = dict(model.get("params") or {})
        seed = int(params.pop("random_state", params.pop("seed", 42)))
        validation = model.get("validation") or {}
        tuning = [int(y) for y in (validation.get("tuning_years") or plan["chronology"]["train"])]
        final_years = [int(y) for y in (validation.get("final_train_validation_years") or [])]
        closure = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")

        def _fit(rows):
            est = _build_estimator(family, seed, params)
            est.fit(rows[features], rows[label].astype(int))
            return est

        def _metrics(est, rows):
            if rows.empty or rows[label].nunique() < 2:
                return {"n": int(len(rows)), "roc_auc": None, "pr_auc": None, "brier": None}
            s = est.predict_proba(rows[features])[:, 1]
            return {"n": int(len(rows)), "roc_auc": roc_auc(rows[label], s).to_dict().get("value"), "pr_auc": pr_auc(rows[label], s).to_dict().get("value"),
                    "brier": brier(rows[label], s).to_dict().get("value")}

        merge_identity = _read(self.work / "merged" / "identity.json").get("candidates_identity")
        tuning_report = None
        if model.get("search_space"):
            from research_workflow.tuning import tune
            tuning_report = tune(study_id=plan["study"]["id"], frame=binary, features=features, label=label, family=family, base_params=params, seed=seed,
                                 search_space=model["search_space"], validation=validation, artifacts_dir=self.artifacts,
                                 identities={"plan_sha256": plan["plan_sha256"], "population_identity": merge_identity, "execution_closure_composite": closure,
                                             "target_contract_sha256": hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                                             "feature_contract_sha256": hashlib.sha256(json.dumps(features).encode()).hexdigest(), "preprocessing_contract_sha256": "identity"})
            params = dict(tuning_report["selected"]["params"])
        # ---- arms x cells ---------------------------------------------------------------
        # An arm is a feature architecture; a cell is a population slice with its own fixed
        # hyperparameters. Each (arm, cell) is fit INDEPENDENTLY on the identical collected
        # population, which is what makes the comparison paired. A study that declares neither
        # keeps the historical single-model behaviour exactly.
        arms = [a for a in (model.get("arms") or []) if isinstance(a, dict)] or [
            {"id": "primary", "features": [], "params": {}, "baseline": True}]
        cells = list(model.get("cells") or []) or [{"id": "all", "subset": {}, "params": {}}]
        month_folds = list((validation or {}).get("month_folds") or [])
        if month_folds:
            ts = pd.to_datetime(binary["observation_ts"], unit="ns", utc=True)
            binary["_month"] = ts.dt.year.astype(str) + "-" + ts.dt.month.map("{:02d}".format)

        def _rows_for(cell):
            rows = binary
            for col, val in (cell.get("subset") or {}).items():
                if col not in rows.columns:
                    raise LifecycleV2Error(f"CELL_SUBSET_COLUMN_MISSING: cell {cell['id']!r} filters on {col!r}")
                rows = rows[rows[col] == val]
            return rows

        def _fit_cfg(rows, cols, cfg):
            est = _build_estimator(family, seed, cfg)
            est.fit(rows[cols], rows[label].astype(int))
            return est

        def _metrics_cfg(est, rows, cols):
            if rows.empty or rows[label].nunique() < 2:
                return {"n": int(len(rows)), "positives": int(rows[label].sum()) if len(rows) else 0,
                        "base_rate": None, "roc_auc": None, "pr_auc": None, "brier": None}
            s = est.predict_proba(rows[cols])[:, 1]
            base = float(rows[label].mean())
            pr = pr_auc(rows[label], s).to_dict().get("value")
            return {"n": int(len(rows)), "positives": int(rows[label].sum()), "base_rate": base,
                    "roc_auc": roc_auc(rows[label], s).to_dict().get("value"), "pr_auc": pr,
                    "pr_auc_over_base_rate": (pr / base if pr is not None and base else None),
                    "brier": brier(rows[label], s).to_dict().get("value"),
                    "unique_regimes": int(rows["regime_start_ns"].nunique()) if "regime_start_ns" in rows.columns else None}

        trained: List[Dict[str, Any]] = []
        for arm in arms:
            arm_cols = [f for f in (arm.get("features") or features)]
            missing = [c for c in arm_cols if c not in binary.columns]
            if missing:
                raise LifecycleV2Error(f"ARM_FEATURES_UNBOUND: arm {arm['id']!r} needs {missing}")
            assert_causal_feature_surface(arm_cols, context=f"v2 fit arm {arm['id']}")
            for cell in cells:
                cfg = {**params, **(cell.get("params") or {}), **(arm.get("params") or {})}
                cell_rows = _rows_for(cell)
                folds: List[Dict[str, Any]] = []
                if month_folds:
                    for f in month_folds:
                        fit_rows = cell_rows[cell_rows["_month"].isin(f["fit_months"])]
                        val_rows = cell_rows[cell_rows["_month"].isin(f["validation_months"])]
                        if fit_rows.empty or fit_rows[label].nunique() < 2:
                            folds.append({"fold": f["fold"], **{k: f[k] for k in ("fit_months", "validation_months")},
                                          "status": "SKIPPED_DEGENERATE_FIT_WINDOW", "metrics": None,
                                          "train_rows": int(len(fit_rows)),
                                          "train_unique_regimes": int(fit_rows["regime_start_ns"].nunique()) if "regime_start_ns" in fit_rows.columns else None})
                            continue
                        est = _fit_cfg(fit_rows, arm_cols, cfg)
                        # TRAIN-derived thresholds: quantiles of the FIT window's own score
                        # distribution, applied UNCHANGED to the validation window. Deriving
                        # them from the validation rows would be the leak this exists to avoid.
                        fit_scores = est.predict_proba(fit_rows[arm_cols])[:, 1]
                        thresholds = {q: float(np.quantile(fit_scores, p)) for q, p in (("p90", 0.90), ("p95", 0.95))}
                        m = _metrics_cfg(est, val_rows, arm_cols)
                        diag = {}
                        if not val_rows.empty:
                            vs = est.predict_proba(val_rows[arm_cols])[:, 1]
                            base = float(val_rows[label].mean()) if len(val_rows) else None
                            for q, thr in thresholds.items():
                                keep = vs >= thr
                                sel = val_rows[keep]
                                prec = float(sel[label].mean()) if len(sel) else None
                                diag[q] = {"threshold": thr, "retained_fraction": float(keep.mean()),
                                           "retained_n": int(keep.sum()), "precision": prec,
                                           "precision_lift_vs_base_rate": (prec / base if prec is not None and base else None)}
                        folds.append({"fold": f["fold"], **{k: f[k] for k in ("fit_months", "validation_months")},
                                      "status": "OK", "train_rows": int(len(fit_rows)),
                                      "train_unique_regimes": int(fit_rows["regime_start_ns"].nunique()) if "regime_start_ns" in fit_rows.columns else None,
                                      "metrics": m, "train_derived_thresholds": diag})
                else:
                    for i, y in enumerate(sorted(tuning)):
                        if i == 0:
                            continue
                        fit_years = [t for t in sorted(tuning) if t < y]
                        est = _fit_cfg(cell_rows[cell_rows["_year"].isin(fit_years)], arm_cols, cfg)
                        folds.append({"fold": f"fold_{y}", "fit_years": fit_years, "validation_year": y,
                                      "status": "OK", "metrics": _metrics_cfg(est, cell_rows[cell_rows["_year"] == y], arm_cols)})
                final_rows = cell_rows[cell_rows["_year"].isin(tuning)]
                if final_rows.empty or final_rows[label].nunique() < 2:
                    raise LifecycleV2Error(f"CELL_FINAL_FIT_DEGENERATE: arm {arm['id']!r} cell {cell['id']!r} has no fittable rows")
                final_est = _fit_cfg(final_rows, arm_cols, cfg)
                final_val = _metrics_cfg(final_est, cell_rows[cell_rows["_year"].isin(final_years)], arm_cols) if final_years else None
                direction = next((str(v) for k, v in (cell.get("subset") or {}).items() if "direction" in k), "both")
                lineage = ModelLineage(study_id=plan["study"]["id"], cell_id=cell["id"], direction=direction,
                                       target_arm=arm["id"], fold_id="final", config_id="C00", seed=seed, ordered_inputs=arm_cols,
                                       feature_contract_sha256=hashlib.sha256(json.dumps(arm_cols).encode()).hexdigest(),
                                       preprocessing_contract_sha256="identity",
                                       target_contract_sha256=hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                                       target_frame_identity=merge_identity, training_population_identity=merge_identity,
                                       train_years=sorted(tuning), validation_years=final_years, hyperparameters=cfg, family=family,
                                       closure_identities={"plan_closure": closure, "plan_sha256": plan["plan_sha256"]},
                                       model_role=f"{arm['id']}:{cell['id']}")
                mid = hashlib.sha256(json.dumps(lineage.__dict__, sort_keys=True, default=str).encode()).hexdigest()
                cell_metrics = {"folds": folds, "final_validation": final_val,
                                "tuning": (None if tuning_report is None else {k: tuning_report[k] for k in ("ledger", "sampler", "n_trials", "selected")})}
                manifest = store_model(model_id=mid, estimator=final_est, lineage=lineage, tier="registry", selection_status="selected",
                                       metrics=cell_metrics, golden_train_frame=final_rows[arm_cols],
                                       golden_rows=min(GOLDEN_MIN_ROWS, int(len(final_rows))), model_root=self.opts.model_root)
                trained.append({"arm": arm["id"], "cell": cell["id"], "baseline_arm": bool(arm.get("baseline")),
                                "model_id": mid, "features": arm_cols, "n_features": len(arm_cols),
                                # The cell's own population filter travels WITH the record: OOS must score
                                # each frozen cell on the identical slice it was fit on, and re-deriving that
                                # from the plan at OOS time would let a recompiled plan silently re-slice it.
                                "subset": dict(cell.get("subset") or {}),
                                "hyperparameters": cfg, "direction": direction,
                                "final_fit_rows": int(len(final_rows)),
                                "final_fit_unique_regimes": int(final_rows["regime_start_ns"].nunique()) if "regime_start_ns" in final_rows.columns else None,
                                "model_store_tier": manifest.get("tier"), "metrics": cell_metrics})

        paired = self._paired_arm_deltas(trained)
        references = self._score_models(self._train_frame_all_labels(plan), model.get("reference_models") or []) if model.get("reference_models") else []
        for r in references:
            assert_causal_feature_surface(r["inputs"], context=f"reference model {r['name']} inputs")
        single = trained[0] if len(trained) == 1 else None
        body = {"schema_version": 3, "plan_sha256": plan["plan_sha256"], "family": family, "label_column": label,
                "rows": {"total": int(len(frame)), "binary": int(len(binary))},
                "tuning_years": sorted(tuning), "final_train_validation_years": final_years,
                "fold_protocol": ("walk_forward_months" if month_folds else "expanding_years"),
                "month_folds": month_folds, "models": trained, "paired_deltas_vs_baseline_arm": paired,
                "reference_models": references, "new_models_trained": True,
                "training_population_identity": merge_identity, "generated_at_utc": _now()}
        if single is not None:
            # One arm, one cell: keep the schema-2 keys the freeze/analyze stages already read.
            body.update({"model_id": single["model_id"], "features": single["features"],
                         "hyperparameters": single["hyperparameters"], "metrics": single["metrics"],
                         "model_store_tier": single["model_store_tier"]})
        path = _write(self.artifacts / "experiment_models.json", body)
        return {"status": "PASS", "outputs": [str(path)]}

    @staticmethod
    def _paired_arm_deltas(trained: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Per-cell, per-fold metric deltas of every arm against the baseline arm.

        Paired on the IDENTICAL validation rows: same cell, same fold, same population. A
        pooled comparison would let one strong fold carry an arm; these are reported fold by
        fold with the sign counts, so a single-fold win is visible as one.
        """
        out: Dict[str, Any] = {}
        by_cell: Dict[str, List[Dict[str, Any]]] = {}
        for t in trained:
            by_cell.setdefault(t["cell"], []).append(t)
        for cell, entries in by_cell.items():
            base = next((e for e in entries if e["baseline_arm"]), None)
            if base is None or len(entries) < 2:
                continue
            base_folds = {f["fold"]: f for f in base["metrics"]["folds"]}
            cell_out: Dict[str, Any] = {"baseline_arm": base["arm"], "arms": {}}
            for e in entries:
                if e["arm"] == base["arm"]:
                    continue
                rows, deltas = [], {k: [] for k in ("roc_auc", "pr_auc_over_base_rate", "brier")}
                for f in e["metrics"]["folds"]:
                    b = base_folds.get(f["fold"])
                    if not b or not f.get("metrics") or not b.get("metrics"):
                        continue
                    if f["metrics"]["n"] != b["metrics"]["n"]:
                        # Not paired: a delta over different rows is not a comparison.
                        rows.append({"fold": f["fold"], "status": "UNPAIRED_ROW_COUNT_MISMATCH",
                                     "arm_n": f["metrics"]["n"], "baseline_n": b["metrics"]["n"]})
                        continue
                    d = {}
                    for k in deltas:
                        av, bv = f["metrics"].get(k), b["metrics"].get(k)
                        d[k] = (av - bv) if (av is not None and bv is not None) else None
                        if d[k] is not None:
                            deltas[k].append(d[k])
                    rows.append({"fold": f["fold"], "status": "OK", "n": f["metrics"]["n"], "delta": d})
                summary = {}
                for k, vals in deltas.items():
                    if not vals:
                        summary[k] = None
                        continue
                    s = sorted(vals)
                    n = len(s)
                    summary[k] = {"n_folds": n, "mean": sum(s) / n, "median": s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2,
                                  "p25": s[max(0, int(0.25 * (n - 1)))], "p75": s[min(n - 1, int(0.75 * (n - 1)))],
                                  "best": s[-1], "worst": s[0],
                                  "folds_positive": sum(1 for v in s if v > 0), "folds_negative": sum(1 for v in s if v < 0)}
                cell_out["arms"][e["arm"]] = {"per_fold": rows, "summary": summary}
            out[cell] = cell_out
        return out

    def _train_frame_all_labels(self, plan: Dict[str, Any], base: Path | None = None, years: List[int] | None = None):
        """Candidates joined with every observation column (all arms), for frozen-model scoring."""
        import pandas as pd
        if base is None:
            merged = self.work / "merged"
            c = pd.read_parquet(merged / "candidates.parquet"); o = pd.read_parquet(merged / "observations.parquet")
        else:
            c = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years or []], ignore_index=True)
            o = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years or []], ignore_index=True)
        dup = [col for col in o.columns if col in c.columns and col not in KEY]
        frame = c.merge(o.drop(columns=dup), on=list(KEY), how="inner")
        frame["_year"] = pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year
        return frame

    def _score_models(self, frame, models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score each frozen model on its declared subset; metrics per year plus a score digest for parity."""
        import hashlib as _h
        import numpy as np
        from research.analysis.metrics import brier, pr_auc, roc_auc
        from research_workflow.model_store import authenticate_model, read_manifest, score
        model_root = self.opts.model_root
        out = []
        for m in models:
            expect = dict(m.get("expect") or {})
            authentication = authenticate_model(m["id"], expect=expect or None, model_root=model_root)
            manifest = read_manifest(m["id"], model_root)
            inputs = list(manifest["lineage"]["ordered_inputs"])
            missing = [c for c in inputs if c not in frame.columns]
            if missing:
                raise LifecycleV2Error(f"MODEL_INPUTS_UNBOUND: {m['name']} needs {missing}")
            rows = frame
            for col, val in (m.get("subset") or {}).items():
                if col not in rows.columns:
                    raise LifecycleV2Error(f"MODEL_SUBSET_COLUMN_MISSING: {col}")
                rows = rows[rows[col] == val]
            label = m["label"]
            binary = rows[rows[label].isin([0, 1, 0.0, 1.0])]
            per_year = {}
            for y, part in binary.groupby("_year"):
                if part[label].nunique() < 2:
                    per_year[int(y)] = {"n": int(len(part)), "roc_auc": None, "pr_auc": None, "brier": None}
                    continue
                s = score(m["id"], part[inputs], model_root=model_root)
                per_year[int(y)] = {"n": int(len(part)), "positives": int(part[label].sum()), "roc_auc": roc_auc(part[label], s).to_dict().get("value"),
                                    "pr_auc": pr_auc(part[label], s).to_dict().get("value"), "brier": brier(part[label], s).to_dict().get("value"),
                                    "score_digest": _h.sha256(np.round(np.asarray(s, dtype=float), 10).tobytes()).hexdigest()}
            out.append({**m, "inputs": inputs, "lineage": {k: manifest["lineage"].get(k) for k in ("study_id", "cell_id", "direction", "target_arm", "train_years", "family")},
                        "rows_scored": int(len(binary)), "metrics_by_year": per_year,
                        "model_authentication": {k: authentication[k] for k in ("model_id", "identity_rule", "canonical_sha256", "feature_contract_sha256", "golden", "tier", "selection_status")}})
        return out

    def _fit_score_mode(self, plan: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        from research_workflow.forward_outcomes.guard import assert_causal_feature_surface
        frame = self._train_frame_all_labels(plan)
        scored = self._score_models(frame, model["models"])
        for m in scored:
            assert_causal_feature_surface(m["inputs"], context=f"frozen model {m['name']} inputs")
        merge_identity = _read(self.work / "merged" / "identity.json").get("candidates_identity")
        path = _write(self.artifacts / "experiment_models.json", {"schema_version": 2, "mode": "score", "plan_sha256": plan["plan_sha256"], "model_id": None,
                                                                   "reused_model_ids": [m["id"] for m in scored], "models": scored, "rows": {"total": int(len(frame))},
                                                                   "features": list(plan["columns"]["features"]), "training_population_identity": merge_identity,
                                                                   "model_authentication": [m["model_authentication"] for m in scored],
                                                                   "new_models_trained": False, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def freeze(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("freeze")
        from research_workflow.experiment import write_train_freeze
        plan = load_plan(self.study)
        # A study with no dev years has no protected OOS: there is no later stage whose access
        # this freeze would gate. Writing a normal TRAIN freeze would be a gate that vouches for
        # nothing, so the freeze records explicitly that no protected period exists. The stage
        # still produces its declared deliverable, so the deliverables contract is unchanged.
        if not (plan["chronology"].get("dev") or []):
            path = _write(self.artifacts / "train_experiment_freeze.json", {
                "schema_version": 1, "partition": "train", "platform": "v2",
                "status": "NO_PROTECTED_OOS", "protected_oos": False,
                "study_id": plan["study"]["id"], "plan_sha256": plan["plan_sha256"],
                "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                "feature_sets": {"primary": list(plan["columns"]["features"])}, "preprocessing_hash": "identity",
                "model_hashes": {}, "model_canonical_sha256": {}, "thresholds": {}, "deciles": {},
                "new_models_trained": False, "merge_identity": _read(self.work / "merged" / "identity.json"),
                "label_column": plan["outcome"].get("label_column"), "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)]}
        models = _read(self.artifacts / "experiment_models.json")
        ident = _read(self.work / "merged" / "identity.json")
        # W-1: bind the frozen record to the model's actual estimator BYTES, not only the
        # (lineage-derived) model_id -- a substituted estimator that refreshes its own
        # canonical/golden bytes under the unchanged model_id would otherwise authenticate
        # identically. model_canonical_sha256 keys by the same name as model_hashes.
        if models.get("model_id"):
            from research_workflow.model_store import read_manifest as _read_manifest
            manifest = _read_manifest(models["model_id"], self.opts.model_root)
            model_canonical_sha256 = {"primary": manifest.get("canonical", {}).get("byte_sha256")}
        elif models.get("mode") == "score":
            model_canonical_sha256 = {
                m["name"]: (m.get("model_authentication") or {}).get("canonical_sha256") for m in models.get("models") or []
            }
        else:
            # A multi-arm/multi-cell TRAIN fit: every (arm, cell) is its own stored model with its own
            # id, and the record carries no inline authentication block. Bind to the model store's
            # canonical BYTES exactly as the single-model branch does. Writing a null sha here instead
            # would leave a freeze that authenticates nothing while still reading as PASS.
            from research_workflow.model_store import read_manifest as _read_manifest
            model_canonical_sha256 = {}
            for m in models.get("models") or []:
                csha = (_read_manifest(_model_record_id(m), self.opts.model_root).get("canonical") or {}).get("byte_sha256")
                if not csha:
                    raise LifecycleV2Error(
                        f"FREEZE_CANONICAL_SHA_MISSING: model '{_model_record_name(m)}' has no canonical byte sha in the model store")
                model_canonical_sha256[_model_record_name(m)] = csha
        payload = {"partition": "train", "platform": "v2", "plan_sha256": plan["plan_sha256"],
                   "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                   "feature_sets": {"primary": list(plan["columns"]["features"])}, "preprocessing_hash": "identity",
                   "model_hashes": ({"primary": models["model_id"]} if models.get("model_id")
                                    else {_model_record_name(m): _model_record_id(m) for m in models.get("models") or []}),
                   "model_canonical_sha256": model_canonical_sha256,
                   "thresholds": {}, "deciles": {}, "new_models_trained": bool(models.get("model_id")),
                   "merge_identity": ident, "metrics": models.get("metrics"), "label_column": plan["outcome"].get("label_column")}
        path = write_train_freeze(self.study, payload)
        return {"status": "PASS", "outputs": [str(path)]}

    def oos(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("oos")
        plan = load_plan(self.study)
        # Nothing to open: a study that declared no dev years never had a protected period.
        # This is a receipt that the stage ran and found nothing authorized -- not a silent skip.
        if not (plan["chronology"].get("dev") or []):
            path = _write(self.work / "oos_no_protected_period.json", {
                "status": "NO_PROTECTED_OOS", "dev_years": [], "plan_sha256": plan["plan_sha256"],
                "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                "detail": "chronology.dev is empty; no protected out-of-sample period exists to open",
                "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)],
                    "partitions": [{"id": "oos-none", "status": "PASS", "rows": {"candidates": 0, "observations": 0}}]}
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        if self.current_composite() != frozen:
            raise LifecycleV2Error("TRAIN_CLOSURE_STALE: the plan closure changed after the TRAIN freeze")
        return self._collect_period("oos")

    def _declared_analysis(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Run the study's declared ``analysis:`` pipeline over its own collected frame.

        Steps run in declaration order (the compiler already proved the pipeline is a DAG and
        that every op is registered), each producing a frame that later steps may consume and a
        JSON-able payload. Only the artifacts the study DECLARED are written, so the analyze
        stage's deliverable set is knowable before execution and auditable after it.
        """
        import pandas as pd
        from research.analysis.diagnostic_ops import run_op
        from research.analysis.identity import canonical_sha256
        spec = plan["analysis"]
        if spec["source"] == "oos":
            from research_workflow.experiment import assert_oos_open
            assert_oos_open(self.study)
            base = self.work / "partitions" / "oos"
            years = [int(y) for y in self._authorized_years(plan, "oos", self.opts.years)]
            frame = self._train_frame_all_labels(plan, base, years)
        else:
            years = [int(y) for y in self._authorized_years(plan, "train", self.opts.years)]
            frame = self._train_frame_all_labels(plan)
        frames: Dict[str, Any] = {"frame": frame}
        extras: Dict[str, Any] = {}
        payloads: Dict[str, Any] = {}
        steps: List[Dict[str, Any]] = []
        for step in spec["steps"]:
            rows = frames[step["rows"]]
            inputs = {name: frames[ref] for name, ref in (step.get("inputs") or {}).items()}
            # Machine-local resolution only -- never part of the plan identity: where an operator
            # keeps their files is not a scientific fact. `study_dir`/`model_root` let a gate read
            # THIS study's own execution artifacts (e.g. the fitted arms of `fit`, which precedes
            # `analyze`) without the study having to declare a path to itself.
            result = run_op(step["op"], rows, inputs=inputs, params=step.get("params") or {},
                            context={"studies_root": str(self.opts.studies_root or (self.repo_root / "studies")),
                                     "study_dir": str(self.study), "artifacts_dir": str(self.artifacts),
                                     "model_root": (str(self.opts.model_root) if self.opts.model_root else None)})
            frames[step["id"]] = result["frame"]
            payloads[step["id"]] = result.get("payload") or {}
            if result.get("observations") is not None:
                extras[step["id"]] = result["observations"]
            steps.append({"id": step["id"], "op": step["op"], "rows_in": int(len(rows)), "rows_out": int(len(result["frame"]))})
        written = []
        for art in spec["artifacts"]:
            path = self.artifacts / art["name"]
            if art["kind"] == "json":
                _write(path, payloads.get(art["source"]) or {})
            elif art["kind"] == "frame":
                frames[art["source"]].to_parquet(path, index=False)
            else:
                if art["source"] not in extras:
                    raise LifecycleV2Error(f"ANALYSIS_ARTIFACT_UNAVAILABLE: step {art['source']!r} produced no observations frame")
                extras[art["source"]].to_parquet(path, index=False)
            written.append({"name": art["name"], "kind": art["kind"], "source": art["source"], "sha256": _sha(path)})
        lineage = {"source": spec["source"], "years": years, "rows": int(len(frame)),
                   "partition_windows": windows_identity((plan.get("chronology") or {}).get("windows") or []),
                   "plan_sha256": plan["plan_sha256"],
                   "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                   "ops": list(spec["ops"]), "steps": steps, "artifacts": written}
        lineage["analysis_identity_sha256"] = canonical_sha256(lineage)
        return {"declared_analysis": lineage, "payloads": payloads}

    def analyze(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("analyze")
        import pandas as pd
        plan = load_plan(self.study)
        # A study that declares an `analysis:` pipeline is analysed by it. Its own declared
        # source decides whether the protected OOS gate applies: a train-source diagnostic
        # never opens a dev year, so demanding assert_oos_open of it would be a gate that
        # cannot vouch for anything it actually did.
        if plan.get("analysis"):
            declared = self._declared_analysis(plan)
            analyze_name = Path(DELIVERABLES["analyze"][0]).name
            path = _write(self.artifacts / analyze_name, {"schema_version": 2, "contract": plan["outcome"]["contract"],
                                                          "plan_sha256": plan["plan_sha256"], "authority": f"plan.analysis.source={plan['analysis']['source']}",
                                                          **declared, "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)] + [str(self.artifacts / a["name"]) for a in plan["analysis"]["artifacts"]]}
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        base = self.work / "partitions" / "oos"
        years = self._authorized_years(plan, "oos", self.opts.years)
        c = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years], ignore_index=True)
        o = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years], ignore_index=True)
        frame = c.merge(o[list(KEY) + [label, "disposition"]], on=list(KEY), how="inner")
        summary: Dict[str, Any] = {"rows": int(len(frame)), "dispositions": frame["disposition"].value_counts().to_dict()}
        models = _read(self.artifacts / "experiment_models.json")
        # WARN-1: OOS scoring must be bound to the model bytes the TRAIN freeze committed to,
        # not merely to the (lineage-derived) model_id -- a post-freeze estimator substitution
        # that refreshes its own canonical/golden bytes under the unchanged model_id would
        # otherwise re-authenticate and score silently. Read the freeze's own recorded
        # canonical shas and pass them as `expect.canonical_sha256`.
        freeze_path = self.artifacts / "train_experiment_freeze.json"
        if not freeze_path.is_file():
            raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: no TRAIN freeze found for study '{plan['study']['id']}'")
        freeze_canonical = _read(freeze_path).get("model_canonical_sha256") or {}
        if models.get("mode") == "score":
            bound_models = []
            for m in models["models"]:
                csha = freeze_canonical.get(m["name"])
                if not csha:
                    raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: model '{m['name']}' has no TRAIN freeze canonical sha")
                expect = dict(m.get("expect") or {})
                expect["canonical_sha256"] = csha
                bound_models.append({**m, "expect": expect})
            summary["frozen_models_oos"] = self._score_models(self._train_frame_all_labels(plan, base, [int(y) for y in years]), bound_models)
            summary["train_metrics"] = [{k: m[k] for k in ("name", "id", "metrics_by_year")} for m in models["models"]]
        elif models.get("model_id"):
            from research.analysis.metrics import brier, pr_auc, roc_auc
            from research_workflow.model_store import authenticate_model, score
            csha = freeze_canonical.get("primary")
            if not csha:
                raise LifecycleV2Error("FREEZE_CANONICAL_SHA_MISSING: no primary canonical sha in TRAIN freeze")
            authentication = authenticate_model(models["model_id"], expect={"study_id": plan["study"]["id"], "canonical_sha256": csha}, model_root=self.opts.model_root)
            binary = frame[frame[label].isin([0, 1, 0.0, 1.0])]
            s = score(models["model_id"], binary[models["features"]], model_root=self.opts.model_root)
            summary["oos_metrics"] = {"n": int(len(binary)), "roc_auc": roc_auc(binary[label], s).to_dict().get("value"),
                                      "pr_auc": pr_auc(binary[label], s).to_dict().get("value"), "brier": brier(binary[label], s).to_dict().get("value")}
            summary["train_metrics"] = models.get("metrics")
            summary["model_authentication"] = {k: authentication[k] for k in ("model_id", "identity_rule", "canonical_sha256", "feature_contract_sha256", "golden", "tier", "selection_status")}
        elif models.get("models"):
            # A multi-arm/multi-cell frozen fit. Score every trained cell on its OWN declared subset,
            # each bound to the canonical bytes the TRAIN freeze committed to (WARN-1), so a post-freeze
            # estimator substitution cannot re-authenticate under the unchanged model_id. Without this
            # branch the stage fell through every case and wrote an analysis carrying no OOS metric at
            # all -- a deliverable that reads as PASS while vouching for nothing.
            bound_models = []
            for m in models["models"]:
                nm = _model_record_name(m)
                csha = freeze_canonical.get(nm)
                if not csha:
                    raise LifecycleV2Error(f"FREEZE_CANONICAL_SHA_MISSING: model '{nm}' has no TRAIN freeze canonical sha")
                bound_models.append({"name": nm, "id": _model_record_id(m), "subset": dict(m.get("subset") or {}),
                                     "label": label, "expect": {"study_id": plan["study"]["id"], "canonical_sha256": csha}})
            summary["frozen_models_oos"] = self._score_models(self._train_frame_all_labels(plan, base, [int(y) for y in years]), bound_models)
            summary["train_metrics"] = [{"name": _model_record_name(m), "id": _model_record_id(m),
                                         "direction": m.get("direction"), "subset": dict(m.get("subset") or {}),
                                         "metrics": m.get("metrics")} for m in models["models"]]
        elif models:
            # An experiment_models.json that exists but matches no scorable shape must fail loudly:
            # falling through silently is what produced an OOS deliverable with no metrics.
            raise LifecycleV2Error(
                f"OOS_MODEL_RECORDS_UNRECOGNISED: experiment_models.json (mode={models.get('mode')!r}) carries no scorable models")
        analyze_name = Path(DELIVERABLES["analyze"][0]).name
        path = _write(self.artifacts / analyze_name, {"schema_version": 2, "contract": plan["outcome"]["contract"], "plan_sha256": plan["plan_sha256"],
                                                                        "oos_years": list(years), "authority": "plan.chronology.dev", **summary, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def close(self, study: Path | None = None) -> Dict[str, Any]:
        self._require_execute("close")
        closure = self.opts.closure or {}
        if not closure.get("outcome") or not closure.get("terminal_decision"):
            raise LifecycleV2Error("CLOSURE_DECISION_REQUIRED: --closure-outcome and --closure-decision")
        seal_path = self.artifacts / "preexec_audit_seal.json"
        seal = _read(seal_path)
        bound: Dict[str, Any] = {"preexec_seal_artifact_sha256": _sha(seal_path), "preexec_seal_composite_sha256": seal.get("composite_seal_hash")}
        freeze = self.artifacts / "train_experiment_freeze.json"
        if freeze.is_file():
            bound["train_freeze_sha256"] = _read(freeze).get("freeze_sha256") or _sha(freeze)
        body = {"schema_version": 1, "study_id": self.study.name, "status": "CLOSED", "outcome": str(closure["outcome"]), "terminal_decision": str(closure["terminal_decision"]),
                "platform": "v2", "plan_sha256": load_plan(self.study).get("plan_sha256"), "closed_at_utc": _now(), "bound_evidence": bound}
        # DEV-08: validate BEFORE the closure persists, and never leave a rejected closure on disk -- a rejected
        # closure that remained was later honoured as the study's terminal authority.
        from research_workflow.study_closure import _validate_terminal_decision, load_study_closure
        _validate_terminal_decision(self.study, body["terminal_decision"])
        target = self.artifacts / "study_closure.json"
        path = _write(target, body)
        try:
            load_study_closure(self.study)
        except Exception:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return {"status": "PASS", "outputs": [str(path)]}


# --------------------------------------------------------------------------- #
# audit ingestion (v2)
# --------------------------------------------------------------------------- #
def ingest_audit_report(study: Path, audit_type: str, report: Path, author: Optional[str] = None) -> Dict[str, Any]:
    from scripts.run_preexec_audits import _extract_v2_summary
    study = Path(study).resolve(); report = Path(report).resolve()
    text = report.read_text(encoding="utf-8")
    summary = _extract_v2_summary(text, report, expected_audit_type=audit_type)
    frozen = _read(study / "audit" / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
    if summary.get("study") != study.name:
        raise LifecycleV2Error(f"AUDIT_STUDY_MISMATCH: {summary.get('study')} != {study.name}")
    if summary.get("audited_execution_composite_sha256") != frozen:
        raise LifecycleV2Error("AUDIT_COMPOSITE_STALE: the report names a composite that is not the frozen plan closure")
    auditor = summary.get("auditor") or author
    if not auditor:
        raise LifecycleV2Error("AUDITOR_REQUIRED")
    other = _read(study / "audit" / ("contract_status.json" if audit_type == "causal" else "status.json"))
    if other.get("auditor") and other.get("auditor") == auditor:
        raise LifecycleV2Error("AUDITOR_ROLE_REUSE: causal and contract auditors must be distinct identities")
    name = "status.json" if audit_type == "causal" else "contract_status.json"
    counts = {k: int(summary.get(k, 0) or 0) for k in ("critical", "warning", "note")}
    verdict = summary["verdict"]
    if verdict == "CLEAR" and counts["critical"] > 0:
        verdict = "BLOCKED"
    body = {"audit_type": audit_type, "auditor": auditor, "verdict": verdict, **counts, "audited_execution_composite_sha256": frozen,
            "audit_report_sha256": _sha(report), "audit_report_path": str(report.relative_to(study)) if study in report.parents else str(report),
            "derived_by_parser": "research_workflow.lifecycle_v2.ingest_audit_report", "platform": "v2", "issued_at_utc": _now()}
    path = _write(study / "audit" / name, body)
    return {"STATUS": "OK" if verdict == "CLEAR" else "BLOCKED", "status_path": str(path), **{k: body[k] for k in ("audit_type", "auditor", "verdict", "critical", "warning", "note")}}


# --------------------------------------------------------------------------- #
# child entry point (partitions)
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("partition")
    p.add_argument("--study", required=True); p.add_argument("--period", required=True); p.add_argument("--year", type=int, required=True)
    p.add_argument("--out-dir", required=True); p.add_argument("--progress"); p.add_argument("--repo-root"); p.add_argument("--studies-root")
    p.add_argument("--windows", help="comma-separated declared window ids/ranges this child may execute")
    ns = ap.parse_args(argv)
    if ns.cmd == "partition":
        opts = V2Options(studies_root=Path(ns.studies_root) if ns.studies_root else None,
                         windows=[w for w in (ns.windows or "").split(",") if w.strip()] or None)
        lc = V2Lifecycle(Path(ns.study), repo_root=Path(ns.repo_root) if ns.repo_root else REPO_ROOT, options=opts)
        manifest = lc.run_partition(ns.year, ns.period, Path(ns.out_dir), progress=Path(ns.progress) if ns.progress else None)
        print(json.dumps({"STATUS": "OK", "partition": manifest.get("id"), "rows": manifest.get("rows")}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

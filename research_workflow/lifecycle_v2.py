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
PLATFORM_TESTS = ("research_workflow/tests/test_golden_fixture.py", "research_workflow/tests/test_grammar_v2.py",
                  "research_workflow/tests/test_host_core.py")


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

    if requested is None:
        return role_years
    try:
        req = sorted({int(y) for y in requested})
    except (TypeError, ValueError) as exc:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} requested years malformed: {exc}")
    if not req:
        raise LifecycleV2Error(f"YEARS_NOT_AUTHORIZED: period={period} requested=[] authorized={role_years} prohibited={sorted(prohibited)}")
    if any(y in prohibited for y in req) or any(y not in role_years for y in req):
        raise LifecycleV2Error(
            f"YEARS_NOT_AUTHORIZED: period={period} requested={req} authorized={role_years} prohibited={sorted(prohibited)}")
    return req


@dataclass
class V2Options:
    execute: bool = False
    smoke_date: Optional[str] = None
    years: Optional[List[int]] = None
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
                                                       "plan_sha256": plan["plan_sha256"], "leaked_outcome_columns": leaked, "generated_at_utc": _now()})
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
        import pandas as pd
        years = set(plan["chronology"]["train"]) | set(plan["chronology"].get("dev") or [])
        horizon_ns = max([a["horizon_ns"] for a in plan["outcome"].get("arms") or []] + [((plan["outcome"].get("flip") or {}).get("horizon_ns") or 0)])
        primary_start, primary_end = f"{year}-01-01", f"{year}-12-31"
        end = pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) + pd.Timedelta(seconds=horizon_ns // NS)
        run_end = end.strftime("%Y-%m-%d") if end.year in years else primary_end
        s = int(pd.Timestamp(primary_start, tz="UTC").value)
        e = int((pd.Timestamp(primary_end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).value)
        return {"id": f"{period}-{year}", "year": year, "period": period, "primary_start": primary_start, "primary_end": primary_end, "run_end": run_end, "primary_ns": (s, e)}

    def _partition_valid(self, out_dir: Path, plan_sha: str, seal: str) -> bool:
        m = _read(out_dir / "manifest.json")
        if not m or m.get("status") != "PASS" or m.get("plan_sha256") != plan_sha or m.get("composite_seal_hash") != seal:
            return False
        return _sha(out_dir / "candidates.parquet") == m.get("candidates_sha256") and _sha(out_dir / "observations.parquet") == m.get("observations_sha256")

    def run_partition(self, year: int, period: str, out_dir: Path, *, progress: Optional[Path] = None) -> Dict[str, Any]:
        plan = load_plan(self.study)
        ids = self._seal_identities()
        b = self._partition_bounds(plan, year, period)
        run = self._run_window(plan, b["primary_start"], b["run_end"], b["primary_ns"], progress=progress)
        return self._persist(run, out_dir, {"kind": "partition", **{k: v for k, v in b.items() if k != "primary_ns"}, "plan_sha256": plan["plan_sha256"], **ids})

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
        return self._collect_period("train")

    def reconcile(self, study: Path | None = None) -> Dict[str, Any]:
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
            rows += len(c); seen_keys += len(c)
        if len(set(schemas)) > 1:
            findings.append("partition output schema mismatch")
        if len(digests) > 1:
            findings.append(f"partitions read different dataset digests: {sorted(digests)}")
        path = _write(self.work / "reconcile.json", {"passed": not findings, "findings": findings, "years": list(years), "rows": rows,
                                                    "authority": "plan.chronology.train", "dataset_digests": sorted(digests),
                                                    "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                                                    "generated_at_utc": _now()})
        if findings:
            raise LifecycleV2Error("RECONCILE_FAILED: " + "; ".join(findings))
        return {"status": "PASS", "outputs": [str(path)]}

    def merge(self, study: Path | None = None) -> Dict[str, Any]:
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
        plan = load_plan(self.study)
        model = plan.get("model")
        if not model:
            path = _write(self.artifacts / "fit_summary.json", {"status": "NO_MODEL_DECLARED", "plan_sha256": plan["plan_sha256"], "generated_at_utc": _now()})
            return {"status": "PASS", "outputs": [str(path)]}
        if model.get("mode") == "score":
            return self._fit_score_mode(plan, model)
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
                                 identities={"plan_sha256": plan["plan_sha256"], "population_identity": merge_identity,
                                             "target_contract_sha256": hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                                             "feature_contract_sha256": hashlib.sha256(json.dumps(features).encode()).hexdigest(), "preprocessing_contract_sha256": "identity"})
            params = dict(tuning_report["selected"]["params"])
        folds = []
        for i, y in enumerate(sorted(tuning)):
            if i == 0:
                continue
            fit_years = [t for t in sorted(tuning) if t < y]
            est = _fit(binary[binary["_year"].isin(fit_years)])
            folds.append({"fold": f"fold_{y}", "fit_years": fit_years, "validation_year": y, "metrics": _metrics(est, binary[binary["_year"] == y])})
        final_est = _fit(binary[binary["_year"].isin(tuning)])
        final_val = _metrics(final_est, binary[binary["_year"].isin(final_years)]) if final_years else None
        lineage = ModelLineage(study_id=plan["study"]["id"], cell_id="primary", direction="both", target_arm=plan["outcome"].get("primary_arm") or plan["outcome"]["kernel"],
                               fold_id="final", config_id="C00", seed=seed, ordered_inputs=features, feature_contract_sha256=hashlib.sha256(json.dumps(features).encode()).hexdigest(),
                               preprocessing_contract_sha256="identity", target_contract_sha256=hashlib.sha256(json.dumps(plan["outcome"], sort_keys=True, default=str).encode()).hexdigest(),
                               target_frame_identity=merge_identity, training_population_identity=merge_identity, train_years=sorted(tuning), validation_years=final_years,
                               hyperparameters=params, family=family, closure_identities={"plan_closure": closure, "plan_sha256": plan["plan_sha256"]}, model_role="primary")
        model_id = hashlib.sha256(json.dumps(lineage.__dict__, sort_keys=True, default=str).encode()).hexdigest()
        metrics = {"folds": folds, "final_validation": final_val, "tuning": (None if tuning_report is None else {k: tuning_report[k] for k in ("ledger", "sampler", "n_trials", "selected")})}
        manifest = store_model(model_id=model_id, estimator=final_est, lineage=lineage, tier="registry", selection_status="selected", metrics=metrics,
                               golden_train_frame=binary[features], golden_rows=min(GOLDEN_MIN_ROWS, int(len(binary))))
        path = _write(self.artifacts / "experiment_models.json", {"schema_version": 2, "plan_sha256": plan["plan_sha256"], "family": family, "hyperparameters": params,
                                                                   "features": features, "label_column": label, "rows": {"total": int(len(frame)), "binary": int(len(binary))},
                                                                   "tuning_years": sorted(tuning), "final_train_validation_years": final_years, "metrics": metrics,
                                                                   "model_id": model_id, "model_store_tier": manifest.get("tier"), "training_population_identity": merge_identity, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

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

    @staticmethod
    def _score_models(frame, models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score each frozen model on its declared subset; metrics per year plus a score digest for parity."""
        import hashlib as _h
        import numpy as np
        from research.analysis.metrics import brier, pr_auc, roc_auc
        from research_workflow.model_store import read_manifest, score
        out = []
        for m in models:
            manifest = read_manifest(m["id"])
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
                s = score(m["id"], part[inputs])
                per_year[int(y)] = {"n": int(len(part)), "positives": int(part[label].sum()), "roc_auc": roc_auc(part[label], s).to_dict().get("value"),
                                    "pr_auc": pr_auc(part[label], s).to_dict().get("value"), "brier": brier(part[label], s).to_dict().get("value"),
                                    "score_digest": _h.sha256(np.round(np.asarray(s, dtype=float), 10).tobytes()).hexdigest()}
            out.append({**m, "inputs": inputs, "lineage": {k: manifest["lineage"].get(k) for k in ("study_id", "cell_id", "direction", "target_arm", "train_years", "family")},
                        "rows_scored": int(len(binary)), "metrics_by_year": per_year})
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
                                                                   "new_models_trained": False, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def freeze(self, study: Path | None = None) -> Dict[str, Any]:
        from research_workflow.experiment import write_train_freeze
        plan = load_plan(self.study)
        models = _read(self.artifacts / "experiment_models.json")
        ident = _read(self.work / "merged" / "identity.json")
        payload = {"partition": "train", "platform": "v2", "plan_sha256": plan["plan_sha256"],
                   "execution_composite_sha256": _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256"),
                   "feature_sets": {"primary": list(plan["columns"]["features"])}, "preprocessing_hash": "identity",
                   "model_hashes": ({"primary": models["model_id"]} if models.get("model_id") else {m["name"]: m["id"] for m in models.get("models") or []}),
                   "thresholds": {}, "deciles": {}, "new_models_trained": bool(models.get("model_id")),
                   "merge_identity": ident, "metrics": models.get("metrics"), "label_column": plan["outcome"].get("label_column")}
        path = write_train_freeze(self.study, payload)
        return {"status": "PASS", "outputs": [str(path)]}

    def oos(self, study: Path | None = None) -> Dict[str, Any]:
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        frozen = _read(self.audit / "frozen_execution_manifest.json").get("frozen_execution_composite_sha256")
        if self.current_composite() != frozen:
            raise LifecycleV2Error("TRAIN_CLOSURE_STALE: the plan closure changed after the TRAIN freeze")
        return self._collect_period("oos")

    def analyze(self, study: Path | None = None) -> Dict[str, Any]:
        import pandas as pd
        from research_workflow.experiment import assert_oos_open
        assert_oos_open(self.study)
        plan = load_plan(self.study)
        label = plan["outcome"].get("label_column") or "target_flip_within_horizon"
        base = self.work / "partitions" / "oos"
        years = self._authorized_years(plan, "oos", self.opts.years)
        c = pd.concat([pd.read_parquet(base / str(y) / "candidates.parquet") for y in years], ignore_index=True)
        o = pd.concat([pd.read_parquet(base / str(y) / "observations.parquet") for y in years], ignore_index=True)
        frame = c.merge(o[list(KEY) + [label, "disposition"]], on=list(KEY), how="inner")
        summary: Dict[str, Any] = {"rows": int(len(frame)), "dispositions": frame["disposition"].value_counts().to_dict()}
        models = _read(self.artifacts / "experiment_models.json")
        if models.get("mode") == "score":
            summary["frozen_models_oos"] = self._score_models(self._train_frame_all_labels(plan, base, [int(y) for y in years]), models["models"])
            summary["train_metrics"] = [{k: m[k] for k in ("name", "id", "metrics_by_year")} for m in models["models"]]
        elif models.get("model_id"):
            from research.analysis.metrics import brier, pr_auc, roc_auc
            from research_workflow.model_store import score
            binary = frame[frame[label].isin([0, 1, 0.0, 1.0])]
            s = score(models["model_id"], binary[models["features"]])
            summary["oos_metrics"] = {"n": int(len(binary)), "roc_auc": roc_auc(binary[label], s).to_dict().get("value"),
                                      "pr_auc": pr_auc(binary[label], s).to_dict().get("value"), "brier": brier(binary[label], s).to_dict().get("value")}
            summary["train_metrics"] = models.get("metrics")
        path = _write(self.artifacts / "experiment_analysis_v2.json", {"schema_version": 2, "contract": plan["outcome"]["contract"], "plan_sha256": plan["plan_sha256"],
                                                                        "oos_years": list(years), "authority": "plan.chronology.dev", **summary, "generated_at_utc": _now()})
        return {"status": "PASS", "outputs": [str(path)]}

    def close(self, study: Path | None = None) -> Dict[str, Any]:
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
        path = _write(self.artifacts / "study_closure.json", body)
        from research_workflow.study_closure import load_study_closure
        load_study_closure(self.study)
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
    ns = ap.parse_args(argv)
    if ns.cmd == "partition":
        opts = V2Options(studies_root=Path(ns.studies_root) if ns.studies_root else None)
        lc = V2Lifecycle(Path(ns.study), repo_root=Path(ns.repo_root) if ns.repo_root else REPO_ROOT, options=opts)
        manifest = lc.run_partition(ns.year, ns.period, Path(ns.out_dir), progress=Path(ns.progress) if ns.progress else None)
        print(json.dumps({"STATUS": "OK", "partition": manifest.get("id"), "rows": manifest.get("rows")}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

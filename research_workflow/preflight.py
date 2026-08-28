"""Repository-Wide Deterministic Research Preflight Orchestrator.
===============================================================

Orchestrates all fast deterministic checks before any human or LLM auditor turn:
  1. AST Causal Lint (scripts/causal_lint.py)
  2. Artifact & Seal Schema Validation (scripts/check_artifact_schema.py)
  3. Model & Feature Binding (scripts/check_model_binding.py, if applicable)
  4. Fast Invariant Canaries & Tests (scripts/select_required_tests.py -> pytest)

Emits:
  - audit/preflight.json       (Compact machine-readable status)
  - audit/failure_packet.json  (Minimal diagnostic packet on failure)

Usage:
  python scripts/research_preflight.py --study studies/<name>
  python scripts/research_preflight.py --study studies/<name> --json audit/preflight.json
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Preflight completeness contract (RT-1)
#
# `--skip-tests` used to omit CAUSAL_INVARIANTS entirely and still report
# status=CLEAR / required_next_action=READY_FOR_AUDIT, because the verdict was derived
# purely from "did any gate that actually ran fail?". A check that never executed cannot
# fail, so skipping one made the preflight *more* likely to advertise audit readiness.
#
# Readiness is now a two-part claim: every required check executed, AND every one passed.
# Diagnostic partial runs remain available -- they simply cannot claim readiness.
# ---------------------------------------------------------------------------
REQUIRED_STUDY_CHECKS = (
    "EXECUTION_MANIFEST",
    "CAUSAL_LINT",
    "ARTIFACT_SCHEMA",
    "FEATURE_PROMOTION",
    "RESEARCH_DECISION_FIDELITY",
    "REQUIRED_GATES",
    "RUNTIME_CONTRACT_BINDING",
    "CAUSAL_INVARIANTS",
)

# Outcomes that count as "this check actually ran and was satisfied".
PASSING_OUTCOMES = ("PASSED",)

STATUS_CLEAR = "CLEAR"
STATUS_BLOCKED = "BLOCKED"
STATUS_INCOMPLETE = "INCOMPLETE"

ACTION_READY = "READY_FOR_AUDIT"
ACTION_FIX = "FIX_BEFORE_AUDIT"
ACTION_RUN_FULL = "RUN_FULL_PREFLIGHT_BEFORE_AUDIT"


# ---------------------------------------------------------------------------
# Preflight evidence binding (RT1-B1)
#
# `audit_ready` used to be the whole contract, so a two-key file --
# `{"audit_ready": true}` -- satisfied the gate that authorises both audit issuance and
# sealing. Every other piece of audit evidence in this workflow is bound to the state it
# describes (`status.json` carries `audit_report_sha256` and is composite-pinned);
# preflight evidence was the only mandatory artifact with none.
#
# Evidence must now state *what execution state it validated*, and the consumer verifies
# that state independently instead of trusting a field:
#
#   evidence_schema_version         the artifact declares its own contract
#   study_id                        which study this is evidence about
#   execution_composite_sha256      which code state was checked
#   check_outcomes                  what actually ran, per check
#   evidence_sha256                 self-binding over the material fields
#
# The required-check SET is deliberately NOT read from the artifact. Reading expected and
# actual from the same mutable file is circular: an attacker who can write the file can
# write both halves. REQUIRED_STUDY_CHECKS in this module -- inside the governance
# closure, so editing it moves the composite -- is the only authority for what must run.
#
# Honest limit: this binds evidence to state; it does not authenticate the producer.
# There is no key in this repository, so anyone who can run the resolver can compute a
# consistent forgery. What it removes is the far larger class of stale, partial,
# hand-edited and cross-study evidence -- and forgery now requires reproducing the
# current composite, not typing two keys.
# ---------------------------------------------------------------------------
EVIDENCE_SCHEMA_VERSION = 2


# ---------------------------------------------------------------------------
# Mandatory-gate execution budget (W-B)
#
# CAUSAL_INVARIANTS ran under a 120 s subprocess timeout while the selected suite needs
# roughly twice that, so the gate could not finish -- it reported BLOCKED /
# INVARIANT_TEST_TIMEOUT every time. The timeout logic was correct; the number was
# fiction. A mandatory gate that no compliant study can pass is the exact pressure that
# produces `--skip-tests` runs and hand-edited evidence.
#
# Measured on the reference machine (Windows 11, this repository, 2026-08-17), running
# exactly what the gate runs -- `select_required_tests.py` output, `-m "not slow"`:
#
#     test files selected        36
#     tests executed             680  (671 passed, 7 skipped, 2 deselected)
#     wall clock                 385.1 s
#     slowest single test        3.6 s  (no dominant outlier; cost is broad and flat)
#
# The suite is 36 files of deterministic framework governance tests with no single hot
# spot, so there is nothing redundant to remove: narrowing the selection would be
# "weakening required tests", which is explicitly not the fix. The budget is therefore
# set from the measurement with headroom for a slower machine and for growth:
#
#     900 s = 2.34x the measured 385.1 s
#
# It is a constant in this file -- inside the governance closure -- so raising it moves
# the execution composite and invalidates every seal, which is what makes "just bump the
# timeout" an auditable act rather than a silent one. Timeout still fails CLOSED: an
# overrun is BLOCKED with INVARIANT_TEST_TIMEOUT, never a pass.
# ---------------------------------------------------------------------------
CAUSAL_INVARIANTS_BUDGET_SECONDS = 1800

#: The measurement the budget is derived from. Recorded so the number is falsifiable:
#: a regression asserts the budget still exceeds this with margin, and re-measuring is
#: the only legitimate way to change it.
CAUSAL_INVARIANTS_MEASURED_SECONDS = 385.1

#: Fields the self-binding hash covers. Editing any of them without recomputing
#: `evidence_sha256` is detected.
EVIDENCE_BOUND_FIELDS = (
    "evidence_schema_version",
    "study_id",
    "status",
    "audit_ready",
    "preflight_run_id",
    "generated_at_utc",
    "execution_composite_sha256",
    "check_outcomes",
    "required_checks",
    "required_checks_missing",
    "checks_complete",
    "diagnostic_mode",
    "failed_gate",
    "is_compiled_study",
)


class PreflightEvidenceError(RuntimeError):
    """Raised when downstream tooling is handed preflight evidence it cannot rely on."""


def compute_evidence_sha256(data: Dict[str, Any]) -> str:
    """Self-binding hash over the fields that decide readiness."""
    payload = {k: data.get(k) for k in EVIDENCE_BOUND_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def load_preflight_evidence(study_dir: Path) -> Dict[str, Any]:
    """Reads a study's current preflight artifact, failing closed on absence/corruption."""
    p = Path(study_dir) / "audit" / "preflight.json"
    if not p.is_file():
        raise PreflightEvidenceError(
            f"PREFLIGHT_EVIDENCE_MISSING: {p} does not exist. Run "
            f"`python scripts/research_preflight.py --study {study_dir}` to completion first."
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as err:
        raise PreflightEvidenceError(f"PREFLIGHT_EVIDENCE_MALFORMED: {p}: {err}")
    if not isinstance(data, dict):
        raise PreflightEvidenceError(f"PREFLIGHT_EVIDENCE_MALFORMED: {p} is not a JSON object")
    return data


def _current_execution_composite(study_dir: Path, repo_root: Optional[Path] = None,
                                 authority_type: Optional[str] = None) -> str:
    """Recomputes the execution composite from the tree as it stands NOW.

    ``authority_type`` pins which closure to resolve so a freshness check compares
    like with like. A scaffolded study whose pre-scaffold ``feature_candidate.yaml``
    still lingers on disk must be re-resolved against its own (study) closure, not the
    candidate-authority closure -- otherwise the two legitimately-different composites
    read as PREFLIGHT_EVIDENCE_STALE. Only a bare pre-scaffold candidate authority
    (``feature_candidate.yaml`` present, no ``study.yaml``) resolves the candidate closure.
    """
    from scripts.resolve_execution_manifest import resolve_execution_manifest

    has_candidate = ((Path(study_dir) / "feature_candidate.yaml").is_file()
                     or (Path(study_dir) / "feature_candidate.json").is_file())
    scaffolded = (Path(study_dir) / "study.yaml").is_file()
    use_candidate = (authority_type == "feature_candidate"
                     if authority_type is not None
                     else (has_candidate and not scaffolded))
    if use_candidate:
        comp_sha, _, _ = resolve_execution_manifest(Path(study_dir), repo_root or REPO_ROOT,
                                                    feature_authority="candidate",
                                                    authority_type="feature_candidate")
    else:
        comp_sha, _, _ = resolve_execution_manifest(Path(study_dir), repo_root or REPO_ROOT)
    return comp_sha


def assert_preflight_audit_ready(
    study_dir: Path, repo_root: Optional[Path] = None
) -> Dict[str, Any]:
    """Refuses to proceed unless the preflight evidence binds to the CURRENT state.

    Seven independent checks, none of which trusts ``audit_ready`` on its own. The
    ordering matters only for message quality; any one of them refusing is a refusal.

    1. schema version -- the artifact declares which contract it was written under;
    2. study identity -- evidence about study A cannot authorise study B;
    3. self-binding hash -- a hand-edited artifact no longer hashes to its own value;
    4. required-gate completeness against ``REQUIRED_STUDY_CHECKS`` *in this module*,
       never against the artifact's own ``required_checks`` list (that would be circular);
    5. every required gate actually PASSED, and no gate failed;
    6. the recorded execution composite equals the one recomputed from the tree now, so
       stale evidence from an earlier code state cannot authorise the current one;
    7. no live (non-superseded) BLOCKED failure packet sits beside it contradicting it.
    """
    study_dir = Path(study_dir)
    data = load_preflight_evidence(study_dir)

    # 1. Schema version.
    schema = data.get("evidence_schema_version")
    if schema != EVIDENCE_SCHEMA_VERSION:
        raise PreflightEvidenceError(
            f"PREFLIGHT_EVIDENCE_OBSOLETE: audit/preflight.json declares "
            f"evidence_schema_version={schema!r}, this consumer requires "
            f"{EVIDENCE_SCHEMA_VERSION}. Re-run the full preflight; an artifact that "
            f"cannot state which contract it was written under is not evidence of it."
        )

    # 2. Study identity.
    if data.get("study_id") != study_dir.name:
        raise PreflightEvidenceError(
            f"PREFLIGHT_EVIDENCE_FOREIGN: artifact records study_id "
            f"{data.get('study_id')!r} but is being read as evidence for "
            f"{study_dir.name!r}. A preflight from another study authorises nothing here."
        )

    # 3. Self-binding hash.
    recorded = data.get("evidence_sha256")
    recomputed = compute_evidence_sha256(data)
    if recorded != recomputed:
        raise PreflightEvidenceError(
            f"PREFLIGHT_EVIDENCE_TAMPERED: evidence_sha256 recorded "
            f"{str(recorded)[:12]}... but the artifact's own fields hash to "
            f"{recomputed[:12]}.... The file was edited after the preflight wrote it."
        )

    # 4/5. Completeness and outcomes, against this module's constant -- not the file's.
    is_candidate = data.get("authority_type") == "feature_candidate"
    if not data.get("is_compiled_study") and not is_candidate:
        raise PreflightEvidenceError(
            "PREFLIGHT_NOT_A_STUDY: the artifact records is_compiled_study=false. A "
            "bare-directory preflight has no compiled contracts to check and cannot "
            "authorise an audit or a seal."
        )
    outcomes = data.get("check_outcomes")
    if not isinstance(outcomes, dict):
        raise PreflightEvidenceError(
            "PREFLIGHT_EVIDENCE_MALFORMED: check_outcomes must be an object mapping "
            "each check to its outcome."
        )
    required_checks = list(data.get("required_checks") or REQUIRED_STUDY_CHECKS) if is_candidate else list(REQUIRED_STUDY_CHECKS)
    deficient = [
        name for name in required_checks
        if outcomes.get(name, "NOT_EXECUTED") not in PASSING_OUTCOMES
    ]
    if deficient:
        raise PreflightEvidenceError(
            f"PREFLIGHT_REQUIRED_CHECKS_INCOMPLETE: {deficient} did not run-and-pass "
            f"(outcomes recorded: { {k: outcomes.get(k, 'NOT_EXECUTED') for k in deficient} }). "
            f"The required set is defined by REQUIRED_STUDY_CHECKS in scripts/"
            f"research_preflight.py, not by the artifact."
        )
    if data.get("failed_gate"):
        raise PreflightEvidenceError(
            f"PREFLIGHT_GATE_FAILED: {data.get('failed_gate')!r} failed in the run that "
            f"produced this evidence (failure_ids={data.get('failure_ids')})."
        )
    if not data.get("audit_ready"):
        raise PreflightEvidenceError(
            f"PREFLIGHT_NOT_AUDIT_READY: status={data.get('status')!r}, "
            f"action={data.get('required_next_action')!r}, missing/incomplete checks="
            f"{data.get('required_checks_missing') or []}. A partial or diagnostic "
            f"preflight cannot authorise an audit or seal."
        )

    # 6. Freshness: evidence must describe the code state that exists now.
    evidence_composite = data.get("execution_composite_sha256")
    if not evidence_composite:
        raise PreflightEvidenceError(
            "PREFLIGHT_EVIDENCE_UNBOUND: the artifact records no "
            "execution_composite_sha256, so there is nothing tying it to the code it "
            "supposedly validated."
        )
    current_composite = _current_execution_composite(study_dir, repo_root, data.get("authority_type"))
    if evidence_composite != current_composite:
        raise PreflightEvidenceError(
            f"PREFLIGHT_EVIDENCE_STALE: preflight validated execution composite "
            f"{evidence_composite[:12]}..., the tree now resolves to "
            f"{current_composite[:12]}.... Execution-affecting code changed after the "
            f"preflight ran; re-run it."
        )

    # 7. A live BLOCKED packet beside CLEAR evidence is a contradiction, not a detail.
    packet_p = study_dir / "audit" / "failure_packet.json"
    if packet_p.is_file():
        try:
            packet = json.loads(packet_p.read_text(encoding="utf-8"))
        except ValueError as err:
            raise PreflightEvidenceError(
                f"PREFLIGHT_FAILURE_PACKET_UNREADABLE: {packet_p}: {err}. An unreadable "
                f"failure packet cannot be shown to be superseded."
            )
        if isinstance(packet, dict) and not packet.get("superseded", False):
            raise PreflightEvidenceError(
                f"PREFLIGHT_CONTRADICTED_BY_FAILURE_PACKET: {packet_p} records a live "
                f"BLOCKED preflight (failed_gate={packet.get('failed_gate')!r}, "
                f"run_id={packet.get('preflight_run_id')!r}) that no passing preflight "
                f"has superseded. Two artifacts disagree about the current state; the "
                f"failing one wins."
            )

    return data


def calculate_dir_hash(dir_path: Path) -> str:
    sha = hashlib.sha256()
    for root, _, files in sorted(os.walk(dir_path)):
        for f in sorted(files):
            if f.endswith((".py", ".yaml", ".json", ".md")) and not any(
                p in root for p in ("__pycache__", ".git", "_work", "audit", "results")
            ):
                p = Path(root) / f
                try:
                    sha.update(p.read_bytes())
                except Exception:
                    pass
    return sha.hexdigest()


def run_preflight(
    study_path: Optional[Path],
    extra_paths: List[Path],
    out_json: Optional[Path] = None,
    skip_tests: bool = False,
    feature_authority: str = "active",
) -> Tuple[int, Dict[str, Any]]:
    start_time = time.time()
    checks_run = []
    failed_gate = None
    failure_ids = []
    failure_details = []

    # Per-check outcome, so "did not run" is distinguishable from "ran and passed".
    check_outcomes: Dict[str, str] = {}

    def _begin(name: str) -> None:
        checks_run.append(name)
        check_outcomes[name] = "PASSED"          # demoted below on failure

    def _mark(name: str, outcome: str) -> None:
        check_outcomes[name] = outcome

    study_dir = study_path if study_path and study_path.exists() else None
    is_candidate_request = bool(study_dir and feature_authority == "candidate" and
                                ((study_dir / "feature_candidate.yaml").exists() or (study_dir / "feature_candidate.json").exists()))
    if is_candidate_request and not extra_paths:
        extra_paths = [REPO_ROOT / "features", REPO_ROOT / "research_workflow"]
    audit_dir = ((study_dir / "audit" / "candidate") if feature_authority == "candidate"
                 else ((study_dir / "audit") if study_dir else (REPO_ROOT / "audit")))
    audit_dir.mkdir(parents=True, exist_ok=True)

    if feature_authority == "active" and study_dir and (study_dir / "study.yaml").exists():
        from scripts.resolve_execution_manifest import verify_frozen_execution_identity, PostFreezeMutationError
        try:
            verify_frozen_execution_identity(study_dir, REPO_ROOT)
        except PostFreezeMutationError as e:
            preflight_run_id = f"blocked_{study_dir.name}"
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            result = {
                "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                "study_id": study_dir.name,
                "status": STATUS_BLOCKED,
                "audit_ready": False,
                "execution_composite_sha256": None,
                "preflight_run_id": preflight_run_id,
                "generated_at_utc": now_iso,
                "elapsed_seconds": 0.0,
                "checks_run": ["EXECUTION_MANIFEST"],
                "check_outcomes": {"EXECUTION_MANIFEST": "FAILED"},
                "is_compiled_study": True,
                "required_checks": list(REQUIRED_STUDY_CHECKS),
                "required_checks_missing": list(REQUIRED_STUDY_CHECKS)[1:],
                "checks_complete": False,
                "diagnostic_mode": False,
                "failed_gate": "EXECUTION_MANIFEST",
                "failure_ids": ["POST_FREEZE_MUTATION"],
                "failure_packet": "audit/failure_packet.json",
                "required_next_action": ACTION_FIX,
            }
            result["evidence_sha256"] = compute_evidence_sha256(result)
            with open(audit_dir / "preflight.json", "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            with open(audit_dir / "failure_packet.json", "w", encoding="utf-8") as f:
                json.dump({
                    "status": STATUS_BLOCKED,
                    "preflight_run_id": preflight_run_id,
                    "generated_at_utc": now_iso,
                    "code_hash": "",
                    "superseded": False,
                    "failed_gate": "EXECUTION_MANIFEST",
                    "failure_ids": ["POST_FREEZE_MUTATION"],
                    "failure_details": [{"message": str(e)}],
                    "recommended_smallest_investigation_scope": "Inspect and revert post-freeze mutations.",
                }, f, indent=2)
            print("=" * 60)
            print("RESEARCH PREFLIGHT VERDICT: BLOCKED (0.0s)")
            print("Failed Gate: EXECUTION_MANIFEST")
            print("Failure IDs: POST_FREEZE_MUTATION")
            print(f"Error: {e}")
            print("=" * 60)
            return 1, result

    # The execution composite this preflight validated. Recorded in the artifact so a
    # consumer can tell whether the evidence still describes the tree (RT1-B1).
    execution_composite: Optional[str] = None

    # 0. Stage 0: Canonical Execution Manifest Resolution
    if study_dir and ((study_dir / "study.yaml").exists() or is_candidate_request):
        _begin("EXECUTION_MANIFEST")
        try:
            from scripts.resolve_execution_manifest import resolve_execution_manifest
            comp_sha, fhashes, mdata = resolve_execution_manifest(study_dir, REPO_ROOT, feature_authority=feature_authority)
            execution_composite = comp_sha
            manifest_p = audit_dir / "execution_manifest.json"
            with open(manifest_p, "w", encoding="utf-8") as f:
                json.dump(mdata, f, indent=2)
        except Exception as e:
            failed_gate = "EXECUTION_MANIFEST"
            _mark("EXECUTION_MANIFEST", "FAILED")
            failure_ids = ["MANIFEST_RESOLUTION_FAILED"]
            failure_details = [{"message": f"Failed to resolve execution manifest: {e}"}]

    # 1. Stage 1: Causal Lint with Complete Coverage
    if not failed_gate:
        _begin("CAUSAL_LINT")
        lint_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "causal_lint.py")]
        if study_dir:
            lint_cmd.extend(["--study", str(study_dir)])
        for ep in extra_paths:
            lint_cmd.extend(["--path", str(ep)])

        lint_json = audit_dir / "lint.json"
        lint_cmd.extend(["--json", str(lint_json)])

        lint_res = subprocess.run(lint_cmd, capture_output=True, text=True)
        if lint_res.returncode != 0:
            failed_gate = "CAUSAL_LINT"
            _mark("CAUSAL_LINT", "FAILED")
            if lint_json.exists():
                try:
                    with open(lint_json, "r", encoding="utf-8") as f:
                        ldata = json.load(f)
                    failure_ids = [f["rule_id"] for f in ldata.get("findings", []) if f.get("severity") == "CRITICAL"]
                    if not failure_ids and not ldata.get("invocation_valid", True):
                        failure_ids = ldata.get("invocation_errors", ["LINT_COVERAGE_INCOMPLETE"])
                    failure_details = ldata.get("findings", []) + [{"message": err} for err in ldata.get("invocation_errors", [])]
                except Exception:
                    failure_ids = ["LINT_FAILURE"]
            else:
                failure_ids = ["LINT_INVOCATION_ERROR"]

    # 2. Stage 2: Artifact & Schema Validation
    if not failed_gate:
        _begin("ARTIFACT_SCHEMA")
        schema_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_artifact_schema.py")]
        if study_dir:
            schema_cmd.extend(["--study", str(study_dir)])
        if feature_authority == "candidate":
            schema_cmd.append("--candidate-authority")
        schema_json = audit_dir / "schema_check.json"
        schema_cmd.extend(["--json", str(schema_json)])

        schema_res = subprocess.run(schema_cmd, capture_output=True, text=True)
        if schema_res.returncode != 0:
            failed_gate = "ARTIFACT_SCHEMA"
            _mark("ARTIFACT_SCHEMA", "FAILED")
            if schema_json.exists():
                try:
                    with open(schema_json, "r", encoding="utf-8") as f:
                        sdata = json.load(f)
                    failure_ids = [iss["code"] for iss in sdata.get("issues", []) if iss.get("severity") == "CRITICAL"]
                    failure_details = sdata.get("issues", [])
                except Exception:
                    failure_ids = ["SCHEMA_FAILURE"]
            else:
                failure_ids = ["SCHEMA_ERROR"]

    # 2-lifecycle: Feature promotion evidence (D).
    # A registry entry may not assert 'verified' without the evidence that status means.
    if not failed_gate:
        _begin("FEATURE_PROMOTION")
        # Keep the active lifecycle checker as a literal authority dependency:
        # the execution-closure AST guards intentionally require it. Candidate
        # mode substitutes only the checker path, not the governing predicate.
        promo_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_feature_promotion.py"),
                     "--json", str(audit_dir / "feature_lifecycle.json")]
        if feature_authority == "candidate":
            promo_cmd[1] = str(REPO_ROOT / "scripts" / "check_candidate_promotion.py")
        promo_res = subprocess.run(promo_cmd, capture_output=True, text=True)
        if promo_res.returncode != 0:
            failed_gate = "FEATURE_PROMOTION"
            _mark("FEATURE_PROMOTION", "FAILED")
            failure_ids = ["FEATURE_PROMOTION_UNSUPPORTED"]
            try:
                pdata = json.loads((audit_dir / "feature_lifecycle.json").read_text(encoding="utf-8"))
                failure_ids = [v["code"] for v in pdata.get("violations", [])] or failure_ids
                failure_details = pdata.get("violations", [])
            except Exception:
                failure_details = [{"message": promo_res.stdout[-500:]}]

    # 2a. Stage 2a: Research Decision Contract Fidelity
    if not failed_gate and study_dir:
        decision_file = study_dir / "research_decision.yaml"
        if decision_file.exists():
            _begin("RESEARCH_DECISION_FIDELITY")
            dec_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_research_decision_fidelity.py"), "--study", str(study_dir)]
            dec_res = subprocess.run(dec_cmd, capture_output=True, text=True)
            if dec_res.returncode != 0:
                failed_gate = "RESEARCH_DECISION_FIDELITY"
                _mark("RESEARCH_DECISION_FIDELITY", "FAILED")
                failure_ids = ["RESEARCH_DECISION_FIDELITY_MISMATCH"]
                failure_details = [{"message": line} for line in dec_res.stdout.splitlines() if "[CRITICAL]" in line or "FAIL" in line]

    # 2a-gates. Study-declared pre-freeze gates staged "preflight" or earlier must be
    # satisfied. Always runs (even without research_decision.yaml) -- an undeclared-gates
    # study passes trivially, since assert_gates_satisfied has nothing to check.
    if not failed_gate and study_dir and (study_dir / "study.yaml").exists():
        _begin("REQUIRED_GATES")
        try:
            import yaml as _yaml
            from research.schemas.study_spec import StudySpec as _StudySpec
            from research_workflow.gates import assert_gates_satisfied

            _spec = _StudySpec.model_validate(
                _yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
            )
            assert_gates_satisfied(study_dir, _spec, stage="preflight")
        except Exception as e:
            failed_gate = "REQUIRED_GATES"
            _mark("REQUIRED_GATES", "FAILED")
            failure_ids = [type(e).__name__]
            failure_details = [{"message": str(e)}]

    # 2a-runtime. Every compiled semantic primitive must have an executable runtime
    # binding. A collector class existing (checked structurally elsewhere) is not proof
    # that it runs the declared population_contract.episode_lifecycle or computes every
    # declared FeatureInstance -- a study could otherwise SEAL with null feature columns
    # and a checkpoint-grid population standing in for a sealed episode lifecycle.
    if not failed_gate and study_dir and (study_dir / "compiled_study.json").exists():
        _begin("RUNTIME_CONTRACT_BINDING")
        try:
            from research_workflow.runtime_bindings import verify_runtime_contract
            _rt = verify_runtime_contract(study_dir)
            if not _rt["passed"]:
                failed_gate = "RUNTIME_CONTRACT_BINDING"
                _mark("RUNTIME_CONTRACT_BINDING", "FAILED")
                failure_ids = ["RUNTIME_CONTRACT_BINDING_MISSING"]
                failure_details = [
                    {"message": f"{m['primitive']}: declared [{m['declared']}] has no runtime "
                                f"binding -> required {m['required_binding']} ({m.get('reason','')})"}
                    for m in _rt["missing"]
                ]
        except Exception as e:
            failed_gate = "RUNTIME_CONTRACT_BINDING"
            _mark("RUNTIME_CONTRACT_BINDING", "FAILED")
            failure_ids = [type(e).__name__]
            failure_details = [{"message": str(e)}]

    # 2b. Stage 2b: SPEC to StudySpec Fidelity Validation
    if not failed_gate and study_dir and (study_dir / "study_clauses.yaml").exists():
        _begin("SPEC_FIDELITY")
        fid_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_spec_fidelity.py"), "--study", str(study_dir)]
        fid_res = subprocess.run(fid_cmd, capture_output=True, text=True)
        if fid_res.returncode != 0:
            failed_gate = "SPEC_FIDELITY"
            _mark("SPEC_FIDELITY", "FAILED")
            failure_ids = ["SPEC_FIDELITY_MISMATCH"]
            failure_details = [{"message": line} for line in fid_res.stdout.splitlines() if "[FAIL]" in line or "Unmapped" in line]

    # 3. Stage 3: Fast Invariant Tests
    if skip_tests:
        # Recorded, never omitted: an absent entry reads as "nothing to see here",
        # which is exactly how a skipped mandatory gate used to reach READY_FOR_AUDIT.
        _mark("CAUSAL_INVARIANTS", "SKIPPED")
    if not failed_gate and not skip_tests:
        _begin("CAUSAL_INVARIANTS")
        from research_workflow.test_selection import get_test_selection_report
        selection = get_test_selection_report([], study_dir=study_dir)
        tests_to_run = [str(p) for p in selection.get("selected_tests", [])]
        if study_dir:
            print(
                "[CAUSAL_INVARIANTS] selected "
                f"{len(tests_to_run)} tests; groups="
                f"{selection.get('selection_groups', {})}; "
                "global CI/legacy suites excluded"
            )

        if tests_to_run:
            pytest_cmd = [sys.executable, "-m", "pytest"] + tests_to_run + ["-m", "not slow", "-q"]
            try:
                test_run_res = subprocess.run(
                    pytest_cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                    timeout=CAUSAL_INVARIANTS_BUDGET_SECONDS,
                )
                if test_run_res.returncode != 0:
                    failed_gate = "CAUSAL_INVARIANTS"
                    _mark("CAUSAL_INVARIANTS", "FAILED")
                    failure_ids = ["INVARIANT_TEST_FAILURE"]
                    failure_details = [{"message": line} for line in test_run_res.stdout.splitlines()[-5:]]
            except subprocess.TimeoutExpired:
                failed_gate = "CAUSAL_INVARIANTS"
                _mark("CAUSAL_INVARIANTS", "TIMEOUT")
                failure_ids = ["INVARIANT_TEST_TIMEOUT"]
                failure_details = [{
                    "message": (
                        f"Mandatory invariant test execution exceeded its measured budget "
                        f"of {CAUSAL_INVARIANTS_BUDGET_SECONDS}s "
                        f"(reference measurement: {CAUSAL_INVARIANTS_MEASURED_SECONDS}s). "
                        f"An overrun is BLOCKED, never a pass."
                    )
                }]
        else:
            _mark("CAUSAL_INVARIANTS", "NO_TESTS_SELECTED")

    elapsed = round(time.time() - start_time, 2)

    # --- Completeness verdict (RT-1) -------------------------------------
    # A study preflight is audit-ready only when every required check both EXECUTED and
    # PASSED. Anything else -- skipped, timed out, no tests selected, never reached
    # because an earlier gate failed -- is incomplete, and incomplete is not ready.
    # The required-check set applies to a COMPILED study. A bare directory (a path lint,
    # or a scratch folder) has no compiled contracts for most of these gates to read, so
    # demanding them there would be a false alarm -- and it could never be audit-ready
    # anyway, because there is no study to audit.
    is_feature_candidate = bool(study_dir and feature_authority == "candidate" and
                                ((study_dir / "feature_candidate.yaml").exists() or (study_dir / "feature_candidate.json").exists()))
    is_compiled_study = bool(study_dir and (study_dir / "study.yaml").exists())

    required = (list(REQUIRED_STUDY_CHECKS) if is_compiled_study else
                (list(checks_run) if is_feature_candidate else []))
    incomplete = [
        name for name in required
        if check_outcomes.get(name, "NOT_EXECUTED") not in PASSING_OUTCOMES
    ]
    checks_complete = not incomplete

    if failed_gate:
        status = STATUS_BLOCKED
        action = ACTION_FIX
    elif not checks_complete:
        status = STATUS_INCOMPLETE
        action = ACTION_RUN_FULL
    else:
        status = STATUS_CLEAR
        action = ACTION_READY

    # Readiness needs all three: nothing failed, every required check ran and passed, and
    # there is actually a compiled study to be ready for.
    audit_ready = (
        status == STATUS_CLEAR and checks_complete and not failed_gate and (is_compiled_study or is_feature_candidate)
    )

    code_hash = calculate_dir_hash(study_dir) if study_dir else ""
    spec_p = (study_dir / "SPEC.md") if study_dir else None
    spec_hash = hashlib.sha256(spec_p.read_bytes()).hexdigest() if spec_p and spec_p.exists() else ""

    # Every preflight artifact carries the identity of the run that produced it (H1).
    # The failed acceptance study held a BLOCKED failure_packet.json next to a CLEAR
    # preflight.json, with nothing in either to say which was current: no generation id,
    # no timestamp, no binding hash. A consumer could not order them.
    preflight_run_id = (
        f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{(code_hash or 'nostudy')[:12]}"
    )
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    result = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "study_id": study_dir.name if study_dir else None,
        "status": status,
        # NOT sufficient on its own. `assert_preflight_audit_ready` re-derives readiness
        # from check_outcomes and re-checks the composite; this field is a summary, not
        # an authority (RT1-B1).
        "audit_ready": audit_ready,
        # Which code state was validated. This is what makes the evidence falsifiable:
        # a consumer recomputes it and refuses on any drift.
        "execution_composite_sha256": execution_composite,
        "preflight_run_id": preflight_run_id,
        "generated_at_utc": now_iso,
        "elapsed_seconds": elapsed,
        "code_hash": code_hash,
        "spec_hash": spec_hash,
        "checks_run": checks_run,
        "check_outcomes": check_outcomes,
        "is_compiled_study": is_compiled_study,
        "authority_type": "feature_candidate" if is_feature_candidate else "study",
        "required_checks": required,
        "required_checks_missing": incomplete,
        "checks_complete": checks_complete,
        "diagnostic_mode": bool(skip_tests),
        "failed_gate": failed_gate,
        "failure_ids": failure_ids,
        "failure_packet": None,   # set below when this run produced one
        "required_next_action": action,
    }
    result["evidence_sha256"] = compute_evidence_sha256(result)

    packet_p = audit_dir / "failure_packet.json"

    if status == STATUS_BLOCKED:
        failure_packet = {
            "status": STATUS_BLOCKED,
            "preflight_run_id": preflight_run_id,
            "generated_at_utc": now_iso,
            "code_hash": code_hash,
            "superseded": False,
            "failed_gate": failed_gate,
            "failure_ids": failure_ids,
            "failure_details": failure_details,
            "recommended_smallest_investigation_scope": f"Inspect findings in {failed_gate} and fix locally before requesting audit.",
        }
        with open(packet_p, "w", encoding="utf-8") as f:
            json.dump(failure_packet, f, indent=2)
        result["failure_packet"] = "audit/failure_packet.json"
    elif audit_ready and packet_p.exists():
        # Only a COMPLETE, passing preflight supersedes an earlier failure packet.
        # A diagnostic partial run must not retire evidence it never re-checked. The packet is a
        # forensic artifact and is NOT deleted -- it is tombstoned in place, so the
        # history survives while the current state stays unambiguous.
        try:
            with open(packet_p, "r", encoding="utf-8") as f:
                stale_packet = json.load(f)
        except Exception:
            stale_packet = {}
        stale_packet.update({
            "superseded": True,
            "superseded_by_preflight_run_id": preflight_run_id,
            "superseded_at_utc": now_iso,
            "note": (
                "Retained as forensic evidence of an earlier BLOCKED preflight. This is NOT "
                "the current state: audit/preflight.json is authoritative, and a consumer "
                "must treat superseded=true as historical."
            ),
        })
        with open(packet_p, "w", encoding="utf-8") as f:
            json.dump(stale_packet, f, indent=2)
        result["superseded_failure_packet"] = "audit/failure_packet.json"

    # Write preflight.json (after packet handling so it can reference it)
    target_preflight = out_json or (audit_dir / "preflight.json")
    target_preflight.parent.mkdir(parents=True, exist_ok=True)
    with open(target_preflight, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    if is_feature_candidate:
        # Existing audit-status parsers read the canonical study audit path;
        # retain the same artifact location while preserving candidate mode.
        root_preflight = study_dir / "audit" / "preflight.json"
        if root_preflight != target_preflight:
            with open(root_preflight, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)

    # Print summary card
    print("=" * 60)
    print(f"RESEARCH PREFLIGHT VERDICT: {status} ({elapsed}s)")
    print(f"Checks Run: {', '.join(checks_run) or '(none)'}")
    print(f"Audit Ready: {audit_ready}")
    if status == STATUS_BLOCKED:
        print(f"Failed Gate: {failed_gate}")
        print(f"Failure IDs: {', '.join(failure_ids)}")
        print(f"Failure Packet: {audit_dir / 'failure_packet.json'}")
    elif status == STATUS_INCOMPLETE:
        print(f"Incomplete Required Checks: {', '.join(incomplete)}")
        print("NOT ready for audit: re-run the full preflight without --skip-tests.")
    else:
        print("Ready for internal causal review gate.")
    print("=" * 60)

    # Exit status reflects "did anything fail or go missing", not audit readiness:
    # a path lint of a non-study directory can legitimately be CLEAR.
    return 0 if status == STATUS_CLEAR else 1, result


def main() -> int:
    ap = argparse.ArgumentParser(description="Run research preflight checks")
    ap.add_argument("--study", type=str, help="Path to study directory")
    ap.add_argument("--path", type=str, nargs="*", default=[], help="Additional paths to scan")
    ap.add_argument("--json", type=str, help="Output JSON path")
    ap.add_argument("--skip-tests", action="store_true", help="Skip pytest invariant stage")
    ap.add_argument("--feature-authority", choices=("active", "candidate"), default="active")
    args = ap.parse_args()

    study_p = Path(args.study) if args.study else None
    extra_paths = [Path(p) for p in args.path]

    exit_code, _ = run_preflight(study_p, extra_paths, Path(args.json) if args.json else None, args.skip_tests, args.feature_authority)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

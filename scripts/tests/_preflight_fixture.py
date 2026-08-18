"""Shared test helper: plant an audit-ready preflight artifact (RT-1).

Audit issuance and seal generation now refuse to proceed unless the study's
`audit/preflight.json` reports `audit_ready: true` -- a diagnostic `--skip-tests` run has
no failing gate and used to be indistinguishable from a full pass.

Tests that exercise *downstream* mechanics (seal tampering, smoke gating, stale-composite
detection) are not testing the preflight, and running a real full preflight inside each of
them would be slow and would couple unrelated gates together. They plant a compliant
artifact instead, exactly as `_plant_compliant_audit_reports` plants compliant audit
reports for the same reason.

This is a fixture, not a bypass: the production paths still consult the artifact, and
`scripts/tests/test_rt_blockers.py` drives the real CLI to prove a genuine `--skip-tests`
run is refused.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from scripts.research_preflight import (
    EVIDENCE_SCHEMA_VERSION,
    REQUIRED_STUDY_CHECKS,
    compute_evidence_sha256,
)
from scripts.resolve_execution_manifest import resolve_execution_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def plant_audit_ready_preflight(study_dir: Path, repo_root: Path | None = None) -> Path:
    """Writes a complete, passing, *bound* preflight artifact into ``study_dir/audit``.

    RT1-B1: preflight evidence must bind to the execution state it validated, so the
    fixture resolves the study's real composite rather than asserting readiness in the
    abstract. A fixture that could skip the binding would be a bypass, not a fixture --
    the same hand-written artifact the Red Team fed the gate.
    """
    study_dir = Path(study_dir)
    audit = study_dir / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    p = audit / "preflight.json"

    composite, _, _ = resolve_execution_manifest(study_dir, Path(repo_root or REPO_ROOT))

    result = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "study_id": study_dir.name,
        "status": "CLEAR",
        "audit_ready": True,
        "execution_composite_sha256": composite,
        "preflight_run_id": "test-fixture",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checks_run": list(REQUIRED_STUDY_CHECKS),
        "check_outcomes": {c: "PASSED" for c in REQUIRED_STUDY_CHECKS},
        "is_compiled_study": True,
        "required_checks": list(REQUIRED_STUDY_CHECKS),
        "required_checks_missing": [],
        "checks_complete": True,
        "diagnostic_mode": False,
        "failed_gate": None,
        "failure_ids": [],
        "required_next_action": "READY_FOR_AUDIT",
        "planted_by": "scripts/tests/_preflight_fixture.py",
    }
    result["evidence_sha256"] = compute_evidence_sha256(result)
    p.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # A passing preflight supersedes any earlier failure packet, exactly as the real one
    # does. Left live, it would (correctly) contradict this evidence.
    packet = audit / "failure_packet.json"
    if packet.is_file():
        try:
            data = json.loads(packet.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        data["superseded"] = True
        data["superseded_by_preflight_run_id"] = "test-fixture"
        packet.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return p

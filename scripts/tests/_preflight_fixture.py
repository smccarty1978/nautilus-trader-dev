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

from scripts.research_preflight import REQUIRED_STUDY_CHECKS


def plant_audit_ready_preflight(study_dir: Path) -> Path:
    """Writes a complete, passing preflight artifact into ``study_dir/audit``."""
    audit = Path(study_dir) / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    p = audit / "preflight.json"
    p.write_text(
        json.dumps({
            "status": "CLEAR",
            "audit_ready": True,
            "preflight_run_id": "test-fixture",
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "checks_run": list(REQUIRED_STUDY_CHECKS),
            "check_outcomes": {c: "PASSED" for c in REQUIRED_STUDY_CHECKS},
            "required_checks": list(REQUIRED_STUDY_CHECKS),
            "required_checks_missing": [],
            "checks_complete": True,
            "diagnostic_mode": False,
            "failed_gate": None,
            "failure_ids": [],
            "required_next_action": "READY_FOR_AUDIT",
            "planted_by": "scripts/tests/_preflight_fixture.py",
        }, indent=2),
        encoding="utf-8",
    )
    return p

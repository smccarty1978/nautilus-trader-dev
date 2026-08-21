"""Audit-lineage isolation for the test suite (RT-3 / RT3-B1).

The durable anchor is keyed by study *name* and lives outside the study directory, so
`rm -rf studies/<id>/audit/` cannot erase a study's audit history. Scratch studies in
this suite are often named after the study they were copied from, so without isolation
one test's anchor is correctly reported as a lineage reset of the next test's ledger --
a true positive about a false situation.

Isolation is now structural rather than configured: `_lineage_path` anchors a study that
lies OUTSIDE the repository beside itself, and every scratch study lives under a unique
`tmp_path`. Nothing needs to be set, nothing can be forgotten, and -- unlike the previous
`NT_AUDIT_LINEAGE_DIR` environment variable -- the mechanism does not exist as a way to
relocate a real study's anchor, in this process or in a subprocess.

This fixture asserts that isolation holds instead of creating it: a test that anchors a
scratch study inside the repository is polluting `audit_lineage/`, which is exactly what
the subprocess-driven CLI tests silently did while the override was an env var.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_ANCHOR_DIR = REPO_ROOT / "audit_lineage"


@pytest.fixture(autouse=True)
def _no_test_may_touch_live_audit_lineage():
    """Fails any test that writes or deletes a real anchor in `audit_lineage/`."""
    def snapshot() -> dict:
        if not LIVE_ANCHOR_DIR.is_dir():
            return {}
        return {p.name: p.read_bytes() for p in LIVE_ANCHOR_DIR.glob("*.json")}

    before = snapshot()
    yield
    after = snapshot()
    assert after == before, (
        "a test modified the repository's durable audit lineage: "
        f"added={sorted(set(after) - set(before))}, "
        f"removed={sorted(set(before) - set(after))}, "
        f"changed={sorted(k for k in set(after) & set(before) if after[k] != before[k])}. "
        "Scratch studies must live under tmp_path so they anchor beside themselves."
    )

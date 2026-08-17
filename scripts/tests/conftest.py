"""Test isolation for the durable audit lineage anchor (RT-3).

The anchor is keyed by study *name* and deliberately lives outside the study directory,
so `rm -rf studies/<id>/audit/` cannot erase a study's audit history. Scratch studies in
this suite are very often all named `study`, so without isolation one test's anchor is
correctly reported as a lineage reset of the next test's empty ledger -- a true positive
about a false situation.

Redirecting the anchor per test keeps every production code path intact: the anchor is
still written, still read, still integrity-checked. Only its directory moves.
"""

from __future__ import annotations

import pytest

from scripts.run_preexec_audits import LINEAGE_DIR_ENV


@pytest.fixture(autouse=True)
def _isolated_audit_lineage(tmp_path_factory, monkeypatch):
    lineage_dir = tmp_path_factory.mktemp("audit_lineage")
    monkeypatch.setenv(LINEAGE_DIR_ENV, str(lineage_dir))
    yield lineage_dir

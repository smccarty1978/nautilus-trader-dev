"""The acceptance rule itself.

The failure mode worth guarding against is a report that reads ACCEPTED because
a check never ran. Absence of evidence must never be recorded as evidence of
correctness, so every one of these asserts that a missing or failing artifact
degrades the verdict.
"""
from __future__ import annotations

import pytest

from studies.regime_complete_canonical_store.implementation.build_report import (
    determine_verdict,
)

PASS = {"verdict": "PASS"}
FAIL = {"verdict": "FAIL"}
RECONCILED = {"all_reconciled": True}
NOT_RECONCILED = {"all_reconciled": False}


def test_all_checks_passing_accepts():
    verdict, limitations = determine_verdict(PASS, PASS, RECONCILED)
    assert verdict == "ACCEPTED"
    assert limitations == []


@pytest.mark.parametrize(
    "parity,audit,consolidation",
    [
        (None, PASS, RECONCILED),
        (PASS, None, RECONCILED),
        (PASS, PASS, None),
        (None, None, None),
    ],
)
def test_a_missing_artifact_is_never_an_acceptance(parity, audit, consolidation):
    verdict, limitations = determine_verdict(parity, audit, consolidation)
    assert verdict == "REJECTED"
    assert any("absent" in item for item in limitations)


def test_failed_backward_parity_rejects():
    verdict, limitations = determine_verdict(FAIL, PASS, RECONCILED)
    assert verdict == "REJECTED"
    assert any("parity" in item for item in limitations)


def test_failed_independent_audit_downgrades_to_conditional():
    """Parity and reconciliation hold, but an independent recomputation
    disagrees somewhere -- reportable, not acceptable as-is."""
    verdict, limitations = determine_verdict(PASS, FAIL, RECONCILED)
    assert verdict == "CONDITIONAL"
    assert any("independent audit" in item for item in limitations)


def test_unreconciled_row_counts_reject():
    verdict, limitations = determine_verdict(PASS, PASS, NOT_RECONCILED)
    assert verdict == "REJECTED"
    assert any("reconcile" in item for item in limitations)


def test_every_non_accepted_verdict_states_a_reason():
    for parity in (PASS, FAIL, None):
        for audit in (PASS, FAIL, None):
            for consolidation in (RECONCILED, NOT_RECONCILED, None):
                verdict, limitations = determine_verdict(parity, audit, consolidation)
                if verdict != "ACCEPTED":
                    assert limitations, (
                        f"{verdict} with no stated reason for "
                        f"{parity}/{audit}/{consolidation}"
                    )


def test_acceptance_requires_all_three_simultaneously():
    """No two passing checks may carry a third that is failing or absent."""
    for parity in (PASS, FAIL, None):
        for audit in (PASS, FAIL, None):
            for consolidation in (RECONCILED, NOT_RECONCILED, None):
                accepted = determine_verdict(parity, audit, consolidation)[0] == "ACCEPTED"
                expected = (
                    parity == PASS and audit == PASS and consolidation == RECONCILED
                )
                assert accepted == expected

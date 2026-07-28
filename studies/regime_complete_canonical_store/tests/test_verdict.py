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
GATE_CLEAN = {"critical": 0, "verdict": "PASS", "pass": 1}
GATE_CRITICAL = {"critical": 3, "verdict": "BLOCKED", "pass": 1}


def test_all_checks_passing_accepts():
    verdict, limitations = determine_verdict(
        PASS, PASS, RECONCILED, GATE_CLEAN, GATE_CLEAN
    )
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
    """Parity, reconciliation, and both gates hold, but an independent
    recomputation disagrees somewhere -- reportable, not acceptable as-is."""
    verdict, limitations = determine_verdict(
        PASS, FAIL, RECONCILED, GATE_CLEAN, GATE_CLEAN
    )
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


def test_acceptance_requires_all_five_simultaneously():
    """No four passing checks may carry a fifth that is failing or absent.

    Exhaustive over parity, the independent audit, reconciliation, and both
    mandatory agent gates -- 108 combinations, exactly one of which accepts.
    """
    accepted_count = 0
    for parity in (PASS, FAIL, None):
        for audit in (PASS, FAIL, None):
            for consolidation in (RECONCILED, NOT_RECONCILED, None):
                for lookahead in (GATE_CLEAN, GATE_CRITICAL, None):
                    for contract in (GATE_CLEAN, GATE_CRITICAL, None):
                        verdict = determine_verdict(
                            parity, audit, consolidation, lookahead, contract
                        )[0]
                        expected = (
                            parity == PASS
                            and audit == PASS
                            and consolidation == RECONCILED
                            and lookahead == GATE_CLEAN
                            and contract == GATE_CLEAN
                        )
                        assert (verdict == "ACCEPTED") == expected
                        accepted_count += verdict == "ACCEPTED"
    assert accepted_count == 1, "exactly one combination may accept"


# --------------------------------------------------- mandatory agent gates


def test_acceptance_requires_both_agent_gates():
    """An earlier revision computed ACCEPTED without reading the gates, so a
    BLOCKED contract-checker could sit beside an ACCEPTED report."""
    verdict, _ = determine_verdict(PASS, PASS, RECONCILED, GATE_CLEAN, GATE_CLEAN)
    assert verdict == "ACCEPTED"


@pytest.mark.parametrize(
    "lookahead,contract",
    [(None, GATE_CLEAN), (GATE_CLEAN, None), (None, None)],
)
def test_an_unrun_agent_gate_is_never_an_acceptance(lookahead, contract):
    verdict, limitations = determine_verdict(
        PASS, PASS, RECONCILED, lookahead, contract
    )
    assert verdict == "REJECTED"
    assert any("has not been run" in item for item in limitations)


@pytest.mark.parametrize(
    "lookahead,contract",
    [(GATE_CRITICAL, GATE_CLEAN), (GATE_CLEAN, GATE_CRITICAL)],
)
def test_critical_agent_findings_block_acceptance(lookahead, contract):
    verdict, limitations = determine_verdict(
        PASS, PASS, RECONCILED, lookahead, contract
    )
    assert verdict != "ACCEPTED"
    assert any("CRITICAL" in item for item in limitations)


def test_legacy_three_argument_call_can_no_longer_accept():
    """Calling without the gates must not yield ACCEPTED by omission."""
    verdict, limitations = determine_verdict(PASS, PASS, RECONCILED)
    assert verdict == "REJECTED"
    assert len(limitations) == 2

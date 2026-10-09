"""Tests for recovery outcome kernel in research_workflow/host/outcomes.py."""
import pytest
from unittest.mock import MagicMock

from research_workflow.host.interfaces import BarView, NS
from research_workflow.host.outcomes import (
    LabelOutcomeContract,
    LabelOutcomeKernel,
    compile_outcome_contract,
    POSITIVE,
    NEGATIVE,
    CENSORED,
)


def _mock_bar(ts_event: int, ts_init: int, open_: float, high: float, low: float, close: float, stream: str = "completed_1m"):
    return BarView(
        stream=stream,
        ts_event=ts_event,
        ts_init=ts_init,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_recovery_outcome_contract_compilation():
    plan = {
        "contract": "label",
        "kernel": "recovery",
        "direction": "const:0",
        "reference": "const:15000.0",
        "entry_reference": "next_bar_open",
        "session_end_rule": "truncate",
        "horizon_end_rule": "strict",
        "arms": [
            {"id": "m25", "favorable_atr": 0.25, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m25"},
            {"id": "m50", "favorable_atr": 0.50, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m50"},
            {"id": "m75", "favorable_atr": 0.75, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m75"},
            {"id": "m100", "favorable_atr": 1.00, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m100"},
        ],
        "primary_arm": "m100",
    }
    contract = compile_outcome_contract(plan)
    assert contract.kernel == "recovery"
    assert contract.reference_ref == "const:15000.0"
    assert len(contract.arms) == 4
    assert contract.primary_arm == "m100"


def test_recovery_outcome_long_recovery_touches():
    # Displaced BELOW anchor: anchor = 15000.0, decision price = 14900.0 (displacement = -100 pts)
    # Recovery direction = +1 (long)
    # Milestones:
    # m25: 14900 + 0.25 * 100 = 14925.0
    # m50: 14900 + 0.50 * 100 = 14950.0
    # m75: 14900 + 0.75 * 100 = 14975.0
    # m100: 15000.0
    plan = {
        "contract": "label",
        "kernel": "recovery",
        "direction": "const:0",
        "reference": "const:15000.0",
        "entry_reference": "next_bar_open",
        "session_end_rule": "truncate",
        "horizon_end_rule": "strict",
        "arms": [
            {"id": "m25", "favorable_atr": 0.25, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m25"},
            {"id": "m50", "favorable_atr": 0.50, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m50"},
            {"id": "m75", "favorable_atr": 0.75, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m75"},
            {"id": "m100", "favorable_atr": 1.00, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m100"},
        ],
        "primary_arm": "m100",
    }
    contract = compile_outcome_contract(plan)
    session_table = MagicMock()
    session_table.session_close.return_value = 100_000 * NS

    kernel = LabelOutcomeKernel(contract, session_table)

    T = 1000 * NS
    identity = {"observation_ts": T, "regime_start_ns": 0, "checkpoint_index": 0}
    kernel.open(identity, T, direction=0, atr=None, reference_price=15000.0, decision_price=14900.0)

    # Next bar opens at 14905, high 14930 (reaches m25: 14925), low 14900, close 14920
    b1 = _mock_bar(T, T + 60 * NS, open_=14905.0, high=14930.0, low=14900.0, close=14920.0)
    kernel.on_bar(b1)

    p = kernel.pending[0]
    assert p.arm_state[0] == POSITIVE  # m25 hit
    assert p.arm_state[1] is None      # m50 not hit yet

    # Second bar: high reaches 14960 (reaches m50: 14950)
    b2 = _mock_bar(T + 60 * NS, T + 120 * NS, open_=14920.0, high=14960.0, low=14915.0, close=14955.0)
    kernel.on_bar(b2)
    assert p.arm_state[1] == POSITIVE  # m50 hit
    assert p.arm_state[2] is None      # m75 not hit yet

    # Third bar: high reaches 15005.0 (reaches m75: 14975 and m100: 15000)
    b3 = _mock_bar(T + 120 * NS, T + 180 * NS, open_=14955.0, high=15005.0, low=14950.0, close=15002.0)
    kernel.on_bar(b3)

    assert p.arm_state[2] == POSITIVE  # m75 hit
    assert p.arm_state[3] == POSITIVE  # m100 hit

    # Check drained rows
    rows = kernel.drain_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["m25_label"] == 1.0
    assert row["m50_label"] == 1.0
    assert row["m75_label"] == 1.0
    assert row["m100_label"] == 1.0
    assert row["target_flip_within_horizon"] == 1
    assert row["disposition"] == "LABELED_POSITIVE"


def test_recovery_outcome_short_recovery_touches():
    # Displaced ABOVE anchor: anchor = 15000.0, decision price = 15100.0 (displacement = +100 pts)
    # Recovery direction = -1 (short)
    # Milestones:
    # m25: 15100 - 25 = 15075.0
    # m50: 15100 - 50 = 15050.0
    # m75: 15100 - 75 = 15025.0
    # m100: 15000.0
    plan = {
        "contract": "label",
        "kernel": "recovery",
        "direction": "const:0",
        "reference": "const:15000.0",
        "entry_reference": "next_bar_open",
        "session_end_rule": "truncate",
        "horizon_end_rule": "strict",
        "arms": [
            {"id": "m25", "favorable_atr": 0.25, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m25"},
            {"id": "m50", "favorable_atr": 0.50, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m50"},
            {"id": "m75", "favorable_atr": 0.75, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m75"},
            {"id": "m100", "favorable_atr": 1.00, "adverse_atr": 0.0, "horizon_ns": 3600 * NS, "expiry": "censor", "prefix": "m100"},
        ],
        "primary_arm": "m100",
    }
    contract = compile_outcome_contract(plan)
    session_table = MagicMock()
    session_table.session_close.return_value = 100_000 * NS

    kernel = LabelOutcomeKernel(contract, session_table)

    T = 1000 * NS
    identity = {"observation_ts": T, "regime_start_ns": 0, "checkpoint_index": 0}
    kernel.open(identity, T, direction=0, atr=None, reference_price=15000.0, decision_price=15100.0)

    # Next bar: low reaches 15060 (hits m25: 15075)
    b1 = _mock_bar(T, T + 60 * NS, open_=15095.0, high=15105.0, low=15060.0, close=15070.0)
    kernel.on_bar(b1)

    p = kernel.pending[0]
    assert p.arm_state[0] == POSITIVE  # m25 hit
    assert p.arm_state[1] is None      # m50 not hit yet

    # Second bar: low reaches 14990 (hits m50, m75, and m100)
    b2 = _mock_bar(T + 60 * NS, T + 120 * NS, open_=15070.0, high=15075.0, low=14990.0, close=15000.0)
    kernel.on_bar(b2)

    assert p.arm_state[1] == POSITIVE
    assert p.arm_state[2] == POSITIVE
    assert p.arm_state[3] == POSITIVE

    rows = kernel.drain_rows()
    assert len(rows) == 1
    assert rows[0]["m100_label"] == 1.0

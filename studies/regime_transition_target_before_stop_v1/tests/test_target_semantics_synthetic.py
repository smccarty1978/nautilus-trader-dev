"""Synthetic Target Semantics & Parity Tests for Study 2.
======================================================
Study: regime_transition_target_before_stop_v1
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from research_workflow.target_runtime import (
    OrderedBarrierTargetRuntime,
    TargetResult,
    TargetRuntimeError,
    POSITIVE,
    NEGATIVE,
    CENSORED,
)
from research_workflow.target_replay_oracle import replay, SUPPORTED_ATR_SOURCE

STUDY_DIR = Path(__file__).resolve().parents[1]
NS = 1_000_000_000


@pytest.fixture
def target_contract():
    path = STUDY_DIR / "config" / "target_contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_three_barrier_arms_bound_in_contract(target_contract):
    """Verifies that all three predeclared stop arms are bound under the forward outcome spec."""
    fos = target_contract.get("required_forward_outcomes", [])
    assert len(fos) == 1
    fo = fos[0]
    assert fo["atr_source"] == SUPPORTED_ATR_SOURCE
    assert fo["atr_frozen_at"] == "decision_ts"
    assert fo["entry_reference"] == "next_bar_open"
    assert fo["session_end_censoring"] is True
    assert fo.get("max_gap_seconds") is None

    barriers = fo.get("ordered_barriers", [])
    assert len(barriers) == 3
    barrier_map = {b["id"]: b for b in barriers}

    assert "barrier_tp_1_0_sl_0_5" in barrier_map
    assert barrier_map["barrier_tp_1_0_sl_0_5"]["favorable_atr"] == 1.0
    assert barrier_map["barrier_tp_1_0_sl_0_5"]["adverse_atr"] == 0.5

    assert "barrier_tp_1_0_sl_1_0" in barrier_map
    assert barrier_map["barrier_tp_1_0_sl_1_0"]["favorable_atr"] == 1.0
    assert barrier_map["barrier_tp_1_0_sl_1_0"]["adverse_atr"] == 1.0

    assert "barrier_tp_1_0_sl_1_5" in barrier_map
    assert barrier_map["barrier_tp_1_0_sl_1_5"]["favorable_atr"] == 1.0
    assert barrier_map["barrier_tp_1_0_sl_1_5"]["adverse_atr"] == 1.5


@pytest.mark.parametrize("favorable_atr,adverse_atr", [(1.0, 0.5), (1.0, 1.0), (1.0, 1.5)])
@pytest.mark.parametrize("direction", [1, -1])
def test_synthetic_ordered_barrier_favorable_first(target_contract, favorable_atr, adverse_atr, direction):
    """Proves positive label when favorable barrier is reached first."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "direction": direction,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": favorable_atr,
        "adverse_atr": adverse_atr,
        "horizon_seconds": 300,
        "session_close_ts": T + 10_000 * NS,
        "max_gap_seconds": 1,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)

    # Bar 1: entry bar
    entry_open = 20_000.0
    bar1 = {"ts": T + 1 * NS, "open": entry_open, "high": entry_open + 1.0, "low": entry_open - 1.0, "gap": False}
    runtime.ingest_bar(pending, bar1)

    # Bar 2: price moves in favorable direction
    fav_target = entry_open + direction * favorable_atr * 10.0
    if direction > 0:
        bar2 = {"ts": T + 2 * NS, "open": entry_open + 2.0, "high": fav_target + 1.0, "low": entry_open - 1.0, "gap": False}
    else:
        bar2 = {"ts": T + 2 * NS, "open": entry_open - 2.0, "high": entry_open + 1.0, "low": fav_target - 1.0, "gap": False}

    runtime.ingest_bar(pending, bar2)
    res = runtime.terminal(pending, final=False)
    assert res.disposition == POSITIVE
    assert res.label == 1

    # Independent replay validation
    oracle_res = replay(
        {"primitive": "ordered_barrier", "required_forward_outcomes": [
            {"ordered_barriers": [{"favorable_atr": favorable_atr, "adverse_atr": adverse_atr, "horizon_seconds": 300}],
             "entry_reference": "next_bar_open", "atr_source": SUPPORTED_ATR_SOURCE, "max_gap_seconds": 1}
        ]},
        cand,
        [bar1, bar2],
    )
    assert oracle_res["disposition"] == "POSITIVE"
    assert oracle_res["label"] == 1


@pytest.mark.parametrize("favorable_atr,adverse_atr", [(1.0, 0.5), (1.0, 1.0), (1.0, 1.5)])
@pytest.mark.parametrize("direction", [1, -1])
def test_synthetic_ordered_barrier_adverse_first(target_contract, favorable_atr, adverse_atr, direction):
    """Proves negative label when adverse barrier is reached first."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "direction": direction,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": favorable_atr,
        "adverse_atr": adverse_atr,
        "horizon_seconds": 300,
        "session_close_ts": T + 10_000 * NS,
        "max_gap_seconds": 1,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)

    entry_open = 20_000.0
    bar1 = {"ts": T + 1 * NS, "open": entry_open, "high": entry_open + 1.0, "low": entry_open - 1.0, "gap": False}
    runtime.ingest_bar(pending, bar1)

    adv_target = entry_open - direction * adverse_atr * 10.0
    if direction > 0:
        bar2 = {"ts": T + 2 * NS, "open": entry_open - 2.0, "high": entry_open + 1.0, "low": adv_target - 1.0, "gap": False}
    else:
        bar2 = {"ts": T + 2 * NS, "open": entry_open + 2.0, "high": adv_target + 1.0, "low": entry_open - 1.0, "gap": False}

    runtime.ingest_bar(pending, bar2)
    res = runtime.terminal(pending, final=False)
    assert res.disposition == NEGATIVE
    assert res.label == 0


def test_same_bar_ambiguity_test():
    """Proves AMBIGUOUS_SAME_BAR_TOUCH censoring when both barriers touched in the same bar."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "direction": 1,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "session_close_ts": T + 10_000 * NS,
        "max_gap_seconds": 1,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)
    entry_open = 20_000.0
    bar1 = {"ts": T + 1 * NS, "open": entry_open, "high": entry_open + 0.5, "low": entry_open - 0.5, "gap": False}
    runtime.ingest_bar(pending, bar1)

    # Bar 2 touches both +10 (20010) and -10 (19990)
    bar2 = {"ts": T + 2 * NS, "open": entry_open, "high": 20_015.0, "low": 19_985.0, "gap": False}
    runtime.ingest_bar(pending, bar2)

    res = runtime.terminal(pending, final=False)
    assert res.disposition == CENSORED
    assert res.label is None
    assert res.censor_reason == "AMBIGUOUS_SAME_BAR_TOUCH"


def test_session_end_censoring_test():
    """Proves SESSION_END censoring when horizon extends past session close."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    session_close = T + 100 * NS  # session ends in 100s, horizon is 300s
    cand = {
        "observation_ts": T,
        "direction": 1,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "session_close_ts": session_close,
        "max_gap_seconds": 1,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)
    bar1 = {"ts": T + 1 * NS, "open": 20_000.0, "high": 20_001.0, "low": 19_999.0, "gap": False}
    runtime.ingest_bar(pending, bar1)

    res = runtime.terminal(pending, final=False)
    assert res.disposition == CENSORED
    assert res.label is None
    assert res.censor_reason == "SESSION_END"


@pytest.mark.parametrize("delta_seconds", [1, 2, 3])
def test_sparse_stream_deltas_remain_observable(delta_seconds):
    """Proves 1s, 2s, and 3s inter-bar deltas on sparse LAST stream remain observable."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "direction": 1,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "session_close_ts": T + 10_000 * NS,
        "max_gap_seconds": None,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)
    bar1 = {"ts": T + 1 * NS, "open": 20_000.0, "high": 20_001.0, "low": 19_999.0, "gap": False}
    runtime.ingest_bar(pending, bar1)

    # Bar 2 arrives delta_seconds later with favorable touch
    bar2 = {
        "ts": T + 1 * NS + delta_seconds * NS,
        "open": 20_005.0,
        "high": 20_015.0,
        "low": 20_000.0,
        "gap": False,
    }
    runtime.ingest_bar(pending, bar2)

    res = runtime.terminal(pending, final=False)
    assert res.disposition == POSITIVE
    assert res.label == 1


def test_explicit_source_continuity_failure_censored():
    """Proves explicit source continuity failure (gap=True flag) triggers GAP censoring."""
    runtime = OrderedBarrierTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "direction": 1,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "session_close_ts": T + 10_000 * NS,
        "max_gap_seconds": None,
        "entry_reference": "next_bar_open",
    }
    pending = runtime.open_pending(cand)
    bar1 = {"ts": T + 1 * NS, "open": 20_000.0, "high": 20_001.0, "low": 19_999.0, "gap": False}
    runtime.ingest_bar(pending, bar1)

    # Bar 2 carries explicit gap=True flag
    bar2 = {"ts": T + 2 * NS, "open": 20_001.0, "high": 20_002.0, "low": 20_000.0, "gap": True}
    runtime.ingest_bar(pending, bar2)

    res = runtime.terminal(pending, final=False)
    assert res.disposition == CENSORED
    assert res.label is None
    assert res.censor_reason == "GAP"


def test_wrong_barrier_identity_injection_caught():
    """Proves runtime catches mismatched barrier / forward outcome identity binding."""
    runtime = OrderedBarrierTargetRuntime(
        binding={"forward_outcome_id": "target_before_stop_300s", "barrier_id": "barrier_tp_1_0_sl_1_0"}
    )
    cand = {
        "observation_ts": 1_000 * NS,
        "direction": 1,
        "atr": 10.0,
        "atr_source": SUPPORTED_ATR_SOURCE,
        "forward_outcome_id": "target_before_stop_300s",
        "barrier_id": "wrong_barrier_id",
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "entry_reference": "next_bar_open",
    }
    with pytest.raises(TargetRuntimeError, match="ORDERED_BARRIER_IDENTITY_BINDING_MISMATCH"):
        runtime.open_pending(cand)


def test_unsupported_ATR_source_rejected():
    """Proves runtime rejects unauthorized ATR source names."""
    runtime = OrderedBarrierTargetRuntime(binding={"atr_source": SUPPORTED_ATR_SOURCE})
    cand = {
        "observation_ts": 1_000 * NS,
        "direction": 1,
        "atr": 10.0,
        "atr_source": "unauthorized_sma_atr_source",
        "favorable_atr": 1.0,
        "adverse_atr": 1.0,
        "horizon_seconds": 300,
        "entry_reference": "next_bar_open",
    }
    with pytest.raises(TargetRuntimeError, match="TARGET_ATR_SOURCE_BINDING_MISMATCH"):
        runtime.open_pending(cand)

    # Replay oracle rejection
    oracle_res = replay(
        {"primitive": "ordered_barrier", "required_forward_outcomes": [
            {"ordered_barriers": [{"favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 300}],
             "entry_reference": "next_bar_open", "atr_source": SUPPORTED_ATR_SOURCE}
        ]},
        cand,
        [{"ts": 1_001 * NS, "open": 20000.0, "high": 20001.0, "low": 19999.0, "gap": False}],
    )
    assert oracle_res["disposition"] == "CENSORED"
    assert oracle_res["censor_reason"] == "ATR_SOURCE_BINDING"


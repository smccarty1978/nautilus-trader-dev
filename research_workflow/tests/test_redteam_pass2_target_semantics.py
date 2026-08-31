"""Pass-2 target semantics: child ownership and exact executable bindings."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from research.engines.target_engine import compile_target_contract
from research.schemas.study_spec import TargetSpec
from research_workflow.target_expression import compile_target_expression
from research_workflow.target_runtime import NS, resolve_target_runtime, validate_target_parity


ATR = "latest_causally_completed_1m_wilder_atr_14_available_at_T"


def _two_barriers(*, logic="AND", a_session=True, b_session=False, a_gap=1, b_gap=10):
    return {
        "primitive": "composite", "condition_logic": logic, "horizon_seconds": 10,
        "conditions": [
            {"id": "a", "kind": "ordered_barrier", "forward_outcome_id": "a_fo", "barrier_id": "a"},
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "b_fo", "barrier_id": "b"},
        ],
        "required_forward_outcomes": [
            {"id": "a_fo", "entry_reference": "next_bar_open", "horizon_seconds": 1,
             "session_end_censoring": a_session, "max_gap_seconds": a_gap,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "a", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 1}]},
            {"id": "b_fo", "entry_reference": "next_bar_open", "horizon_seconds": 10,
             "session_end_censoring": b_session, "max_gap_seconds": b_gap,
             "atr_source": ATR, "atr_frozen_at": "decision_ts",
             "ordered_barriers": [{"id": "b", "favorable_atr": 100., "adverse_atr": 100., "horizon_seconds": 10}]},
        ],
    }


@pytest.mark.parametrize("logic", ["AND", "OR"])
def test_child_session_policy_is_not_overridden_by_composite_convenience(logic):
    rt = resolve_target_runtime(_two_barriers(logic=logic))
    p = rt.open_pending({"observation_ts": 0, "regime_direction": 1, "atr": 1.,
                         "atr_source": ATR, "session_close_ts": 5 * NS})
    assert p["children"]["a"]["session_close_ts"] == 5 * NS
    assert p["children"]["b"]["session_close_ts"] is None
    with pytest.raises(ValidationError, match="COMPOSITE_SESSION_POLICY_MUST_BE_CHILD_OWNED"):
        TargetSpec.model_validate({"type": "composite", "session_end_censoring": True,
                                   "required_forward_outcomes": [{"id": "x", "horizon_seconds": 1}]})


@pytest.mark.parametrize("logic", ["AND", "OR"])
def test_mixed_child_gap_thresholds_are_independent_and_old_shared_gap_fails_parity(logic):
    contract = _two_barriers(logic=logic, a_session=False, b_session=False, a_gap=1, b_gap=10)
    rt = resolve_target_runtime(contract)
    p = rt.open_pending({"observation_ts": 0, "regime_direction": 1, "atr": 1., "atr_source": ATR})
    # Child A expires before the five-second raw gap; B remains observable under 10s.
    tape = [
        {"ts": NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 6 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
        {"ts": 11 * NS, "open": 100., "high": 100.1, "low": 99.9, "gap": False},
    ]
    for event in tape:
        rt.ingest_bar(p, event)
    result = rt.terminal(p, final=True, now_ts=11 * NS)
    assert (result.disposition, result.label) == ("NEGATIVE", 0)
    row = rt.parity_row(p, {"disposition": result.disposition, "label": result.label,
                            "censor_reason": result.censor_reason})
    assert validate_target_parity(contract, [row])["passed"]
    # Deliberately reintroduce the old min-gap collector defect: B sees a synthetic
    # shared gap at 6s and becomes censored.  Independent raw-tape replay rejects it.
    bad = dict(row)
    bad["actual"] = {"disposition": "CENSORED", "label": None, "censor_reason": "GAP"}
    assert not validate_target_parity(contract, [bad])["passed"]


@pytest.mark.parametrize("value,valid", [(None, True), (0, False), (-1, False), (12, True)])
def test_horizons_are_none_only_defaulted_and_nonpositive_rejected(value, valid):
    payload = {"type": "flip", "horizon_seconds": value}
    if valid:
        got = TargetSpec.model_validate(payload)
        assert got.horizon_seconds == value
    else:
        with pytest.raises(ValidationError):
            TargetSpec.model_validate(payload)
    for field in ("horizon_seconds", "max_tracking_seconds"):
        fo = {"id": "fo", "horizon_seconds": 10}
        if field == "horizon_seconds": fo[field] = value
        else: fo[field] = value
        if value is None and field == "horizon_seconds":
            continue
        if value is not None and value <= 0:
            with pytest.raises(ValidationError): TargetSpec.model_validate({"type": "composite", "required_forward_outcomes": [fo]})


def test_single_ordered_barrier_binds_referenced_identity_not_list_position():
    target = TargetSpec.model_validate({"type": "composite", "conditions": [
        {"id": "picked", "kind": "ordered_barrier", "forward_outcome_id": "fo", "barrier_id": "second"}],
        "required_forward_outcomes": [{"id": "fo", "horizon_seconds": 10, "atr_source": ATR,
        "atr_frozen_at": "decision_ts", "ordered_barriers": [
            {"id": "first", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 10},
            {"id": "second", "favorable_atr": 2., "adverse_atr": 3., "horizon_seconds": 9}]}]})
    contract = compile_target_contract(target)
    leaf = compile_target_expression(contract).leaves()[0]
    assert leaf.params["barrier_id"] == "second"
    assert (leaf.params["favorable_atr"], leaf.params["adverse_atr"], leaf.params["horizon_seconds"]) == (2., 3., 9)


def test_closed_confirmation_and_atr_source_reject_unknown_behavior():
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({"type": "flip", "confirmation": {"mode": "bar_close", "unknown": 1}})
    with pytest.raises(ValidationError):
        TargetSpec.model_validate({"type": "composite", "required_forward_outcomes": [{
            "id": "fo", "horizon_seconds": 10, "atr_source": "arbitrary", "atr_frozen_at": "decision_ts",
            "ordered_barriers": [{"id": "b", "favorable_atr": 1., "adverse_atr": 1., "horizon_seconds": 10}]}]})


def test_preflight_atr_binding_is_independent_and_fails_closed():
    from research_workflow.preflight import PreflightEvidenceError, verify_target_atr_source_binding
    contract = _two_barriers()
    assert verify_target_atr_source_binding(contract)["passed"]
    contract["required_forward_outcomes"][0]["atr_source"] = "wrong"
    with pytest.raises(PreflightEvidenceError, match="TARGET_ATR_SOURCE_BINDING_INVALID"):
        verify_target_atr_source_binding(contract)

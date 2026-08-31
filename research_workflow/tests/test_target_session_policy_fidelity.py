"""RT-02 -- an authored session_end_censoring value must execute as authored.

Before this fix ``target_engine.compile_target_contract`` hard-coded
``censoring_policy.session_end_censoring = True`` regardless of the study. A plain flip
target had no field to author it at all; a composite / ordered-barrier target authored it
per forward-outcome but the collector-global value the collector actually reads was still
a hard-coded ``True``. So ``session_end_censoring = false`` executed as ``true``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from research.engines.target_engine import (
    compile_target_contract,
    resolve_session_end_censoring,
)
from research.schemas.study_spec import StudySpec, TargetSpec
from research_workflow.target_runtime import CENSORED, NEGATIVE, FlipTargetRuntime

NS = 1_000_000_000


# --------------------------------------------------------------------------- #
# 1. resolution: authored value wins, historical default preserved
# --------------------------------------------------------------------------- #
def test_plain_flip_default_is_true_historical():
    ts = TargetSpec.model_validate({"type": "flip", "horizon_seconds": 300})
    assert resolve_session_end_censoring(ts) is True
    tc = compile_target_contract(ts)
    assert tc["session_end_censoring"] is True
    assert tc["censoring_policy"]["session_end_censoring"] is True


def test_plain_flip_authored_false_is_false():
    ts = TargetSpec.model_validate(
        {"type": "flip", "horizon_seconds": 300, "session_end_censoring": False}
    )
    assert resolve_session_end_censoring(ts) is False
    tc = compile_target_contract(ts)
    assert tc["session_end_censoring"] is False
    assert tc["censoring_policy"]["session_end_censoring"] is False


def test_plain_flip_authored_true_is_true():
    ts = TargetSpec.model_validate(
        {"type": "flip", "horizon_seconds": 300, "session_end_censoring": True}
    )
    tc = compile_target_contract(ts)
    assert tc["session_end_censoring"] is True


def test_composite_derives_from_forward_outcomes():
    base = {
        "type": "composite",
        "condition_logic": "AND",
        "conditions": [
            {"id": "b", "kind": "ordered_barrier", "forward_outcome_id": "fo", "barrier_id": "bar"},
            {"id": "f", "kind": "flip"},
        ],
        "required_forward_outcomes": [
            {
                "id": "fo",
                "horizon_seconds": 300,
                "entry_reference": "next_bar_open",
                    "atr_source": "latest_causally_completed_1m_wilder_atr_14_available_at_T",
                "atr_frozen_at": "decision_ts",
                "ordered_barriers": [
                    {"id": "bar", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 300}
                ],
            }
        ],
    }
    false_fo = json.loads(json.dumps(base))
    false_fo["required_forward_outcomes"][0]["session_end_censoring"] = False
    assert compile_target_contract(TargetSpec.model_validate(false_fo))["session_end_censoring"] is False

    true_fo = json.loads(json.dumps(base))
    true_fo["required_forward_outcomes"][0]["session_end_censoring"] = True
    assert compile_target_contract(TargetSpec.model_validate(true_fo))["session_end_censoring"] is True


# --------------------------------------------------------------------------- #
# 2. hash neutrality: unset field never stales an existing study
# --------------------------------------------------------------------------- #
def test_unset_field_is_hash_neutral():
    base = {
        "study": {"id": "s", "type": "flip_prediction", "description": "d"},
        "instrument": {"symbol": "NQ", "venue": "XCME"},
        "population": {"type": "regime_state"},
        "target": {"type": "flip", "horizon_seconds": 300},
        "features": {"source": "canonical_verified_definition_universe"},
        "chronology": {"train": [2021], "dev": [2022], "prohibited": [2025, 2026]},
        "execution": {"runtime": "nautilustrader"},
    }
    without = StudySpec.model_validate(base).compute_sha256()
    base["target"]["session_end_censoring"] = None
    assert StudySpec.model_validate(base).compute_sha256() == without
    base["target"]["session_end_censoring"] = False
    assert StudySpec.model_validate(base).compute_sha256() != without


# --------------------------------------------------------------------------- #
# 3. the value the collector actually binds tracks the contract (no hard default)
# --------------------------------------------------------------------------- #
class _CfgCls:
    session_end_censoring = True
    session = "RTH"
    target_contract = {}


def _kwargs_for(contract):
    from backtests.nt_runtime.modes.collect import build_collector_config_kwargs

    strategy_binding = SimpleNamespace(config_cls=_CfgCls)
    spec = SimpleNamespace(
        population=SimpleNamespace(session="RTH", prevailing_regime=None, qualification=None),
        target=SimpleNamespace(direction=None, horizon_seconds=300),
        features=SimpleNamespace(metadata_columns=None, feature_list=None, derived_inputs=None),
    )
    study_data = SimpleNamespace(contracts={"target_contract": contract}, study_dir=None)
    data_plan = SimpleNamespace(instrument_id="X", bar_type_1s="1s", bar_type_1m="1m")
    return build_collector_config_kwargs(strategy_binding, spec, study_data, data_plan)


def test_collector_kwarg_is_false_when_contract_says_false():
    kw = _kwargs_for({"primitive": "flip_within_horizon", "session_end_censoring": False,
                      "censoring_policy": {"session_end_censoring": False}})
    assert kw["session_end_censoring"] is False


def test_collector_kwarg_is_true_when_contract_says_true():
    kw = _kwargs_for({"primitive": "flip_within_horizon", "session_end_censoring": True,
                      "censoring_policy": {"session_end_censoring": True}})
    assert kw["session_end_censoring"] is True


def test_collector_kwarg_falls_back_to_censoring_policy_for_legacy_contract():
    # A contract compiled before the top-level key existed.
    kw = _kwargs_for({"censoring_policy": {"session_end_censoring": False}})
    assert kw["session_end_censoring"] is False


# --------------------------------------------------------------------------- #
# 4. end-to-end: authored false does not censor at session end
# --------------------------------------------------------------------------- #
def _flip_pending(*, session_close_ts):
    rt = FlipTargetRuntime()
    T = 1_000 * NS
    cand = {
        "observation_ts": T,
        "horizon_seconds": 300,
        "regime_direction": 1,
        "session_close_ts": session_close_ts,
    }
    return rt, rt.open_pending(cand)


def test_flip_runtime_does_not_censor_when_session_close_absent():
    """session_end_censoring=false -> collector passes session_close_ts=None ->
    a candidate whose horizon runs past the (would-be) session close is labeled, not
    censored."""
    rt, pending = _flip_pending(session_close_ts=None)
    res = rt.terminal(pending, final=True)
    assert res.disposition == NEGATIVE


def test_flip_runtime_censors_when_session_close_present_and_exceeded():
    T = 1_000 * NS
    rt, pending = _flip_pending(session_close_ts=T + 100 * NS)  # closes before the 300s horizon
    res = rt.terminal(pending, final=True)
    assert res.disposition == CENSORED
    assert res.censor_reason == "SESSION_END"

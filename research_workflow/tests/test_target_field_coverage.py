"""RT-05 -- an accepted target semantic field is executed by the runtime or rejected.

The compiler accepts semantic fields (confirmation, atr_source, atr_frozen_at,
bar_inclusion, ...) that a runtime may not implement. Before this fix a non-default
authored value was silently ignored. Now
``target_runtime.assert_target_semantic_field_coverage`` fails closed
(``TARGET_SEMANTIC_FIELD_UNSUPPORTED``) for any non-default field the resolved runtime
neither consumes nor records as provenance-only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_workflow.target_runtime import (
    TargetRuntimeError,
    assert_target_semantic_field_coverage,
)

REPO = Path(__file__).resolve().parents[2]


def _ob_contract(**fo_over):
    fo = {
        "id": "fo", "horizon_seconds": 300, "entry_reference": "next_bar_open",
        "bar_inclusion": "fully_forward", "session_end_censoring": True,
        "atr_source": "prior_1m_atr", "atr_frozen_at": "decision_ts",
        "ordered_barriers": [{"id": "b", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 300}],
    }
    fo.update(fo_over)
    return {
        "primitive": "ordered_barrier",
        "confirmation": {"mode": "bar_close", "confirmation_bars": 1},
        "required_forward_outcomes": [fo],
    }


# --------------------------------------------------------------------------- #
# passing cases
# --------------------------------------------------------------------------- #
def test_default_flip_contract_passes():
    r = assert_target_semantic_field_coverage(
        {"primitive": "flip_within_horizon", "horizon_seconds": 300,
         "confirmation": {"mode": "bar_close", "confirmation_bars": 1}}
    )
    assert r["passed"]


def test_completed_1m_bar_confirmation_is_supported():
    # The regime flip IS a completed-1m-bar event confirmed over one bar.
    assert assert_target_semantic_field_coverage(
        {"primitive": "flip_within_horizon", "horizon_seconds": 180,
         "confirmation": {"mode": "completed_1m_bar", "confirmation_bars": 1}}
    )["passed"]


def test_ordered_barrier_atr_provenance_is_allowed():
    assert assert_target_semantic_field_coverage(_ob_contract())["passed"]


@pytest.mark.parametrize("study_id", ["clean_maturity_flip_model_180s_horizon", "workflow_canary_ordered_barrier_v1"])
def test_real_compiled_contracts_pass(study_id):
    cf = REPO / "studies" / study_id / "compiled_study.json"
    if not cf.is_file():
        pytest.skip(study_id)
    tc = (json.loads(cf.read_text()).get("contracts") or {}).get("target_contract") or {}
    assert assert_target_semantic_field_coverage(tc)["passed"]


# --------------------------------------------------------------------------- #
# rejection cases -- the field cannot be silently ignored
# --------------------------------------------------------------------------- #
def test_multi_bar_confirmation_rejected():
    with pytest.raises(TargetRuntimeError, match="TARGET_SEMANTIC_FIELD_UNSUPPORTED"):
        assert_target_semantic_field_coverage(
            {"primitive": "flip_within_horizon", "horizon_seconds": 300,
             "confirmation": {"mode": "bar_close", "confirmation_bars": 3}}
        )


def test_exotic_confirmation_mode_rejected():
    with pytest.raises(TargetRuntimeError, match="confirmation"):
        assert_target_semantic_field_coverage(
            {"primitive": "flip_within_horizon", "horizon_seconds": 300,
             "confirmation": {"mode": "tick", "confirmation_bars": 1}}
        )


def test_non_default_bar_inclusion_rejected():
    with pytest.raises(TargetRuntimeError, match="bar_inclusion"):
        assert_target_semantic_field_coverage(_ob_contract(bar_inclusion="close_after_entry"))


def test_unsupported_entry_reference_rejected():
    with pytest.raises(TargetRuntimeError, match="entry_reference"):
        assert_target_semantic_field_coverage(_ob_contract(entry_reference="decision_close"))


def test_confirmation_on_ordered_barrier_target_rejected_when_non_default():
    c = _ob_contract()
    c["confirmation"] = {"mode": "completed_1m_bar", "confirmation_bars": 1}
    with pytest.raises(TargetRuntimeError, match="confirmation"):
        assert_target_semantic_field_coverage(c)

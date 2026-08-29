"""Pure single-primitive ordered_barrier regression fixture.

Locks the already-correct primitive ``OrderedBarrierTargetRuntime`` path so future
composite-target work cannot silently change it:

  * a single ``ordered_barrier`` condition compiles to ``primitive: "ordered_barrier"``
    (NEVER ``composite``);
  * it resolves to ``OrderedBarrierTargetRuntime``, not ``CompositeTargetRuntime``;
  * the runtime, the collector machinery and the independent replay oracle still agree
    on SUCCESS / FAILURE / TIMEOUT / AMBIGUOUS / SESSION_END, with the entry reference
    resolved from the tape's ``next_bar_open``.

The broad behavioural matrix lives in ``test_ordered_barrier_entry_reference.py``; this
file is the deliberately small "did composite work break the primitive?" tripwire.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from research.engines.target_engine import compile_target_contract
from research.schemas.study_spec import StudySpec
from research_workflow.target_runtime import (
    NS,
    OrderedBarrierTargetRuntime,
    resolve_target_runtime,
    validate_target_parity,
)

T0 = int(pd.Timestamp("2023-03-03 10:00:00", tz="America/Chicago").tz_convert("UTC").value)
HORIZON = 60

_BASE = dict(
    study={"id": "sp_ob", "type": "flip_prediction", "description": "d"},
    instrument={"symbol": "NQ"},
    population={"prevailing_regime": "bearish"},
)
_TARGET = {
    "type": "composite",
    "decision_reference": "decision_ts",
    "conditions": [{
        "id": "ob", "kind": "ordered_barrier",
        "forward_outcome_id": "fo", "barrier_id": "b",
    }],
    "required_forward_outcomes": [{
        "id": "fo", "entry_reference": "next_bar_open",
        "horizon_seconds": HORIZON, "max_tracking_seconds": HORIZON, "max_gap_seconds": 1,
        "session_end_censoring": True,
        "atr_source": "latest_causally_completed_1m_wilder_atr_14_available_at_T",
        "atr_frozen_at": "decision_ts",
        "ordered_barriers": [{
            "id": "b", "favorable_atr": 0.25, "adverse_atr": 0.25, "horizon_seconds": HORIZON,
        }],
    }],
}


def _contract():
    spec = StudySpec.model_validate(dict(_BASE, target=_TARGET))
    return compile_target_contract(spec.target)


def test_single_ordered_barrier_condition_compiles_to_primitive_not_composite():
    tc = _contract()
    assert tc["primitive"] == "ordered_barrier"
    assert "condition_logic" in tc and tc["condition_logic"] is None


def test_single_ordered_barrier_resolves_to_ordered_barrier_runtime():
    rt = resolve_target_runtime(_contract())
    assert isinstance(rt, OrderedBarrierTargetRuntime)
    assert rt.primitive == "ordered_barrier"


def _collector():
    from research_workflow.generic_collector import FlipPredictionCollector

    obj = FlipPredictionCollector.__new__(FlipPredictionCollector)
    tc = _contract()
    obj.cfg = SimpleNamespace(horizon_seconds=HORIZON, session="RTH",
                              session_end_censoring=True, target_contract=tc)
    obj._benchmark_mode = ""
    obj._target_primitive = "ordered_barrier"
    obj._target_runtime = resolve_target_runtime(tc)
    obj._ordered_barrier = {"favorable_atr": 0.25, "adverse_atr": 0.25, "horizon_seconds": HORIZON}
    obj._ordered_barrier_entry_reference = "next_bar_open"
    obj._ordered_barrier_max_gap_seconds = 1
    obj.active_regime_dir = 1
    obj.pending_candidates = []
    obj.observations_log = []
    obj._next_pending_horizon_ns = None
    return obj


def test_primitive_collector_runtime_and_oracle_still_agree_on_success():
    obj = _collector()
    obj._track_pending({"observation_ts": T0, "regime_start_ns": T0 - 300 * NS,
                        "regime_direction": 1, "checkpoint_index": 3, "target_frozen_atr": 10.0}, T0)
    bars = [(T0 + 1 * NS, 20000.0, 20001.0, 19999.0),
            (T0 + 2 * NS, 20001.0, 20003.0, 20000.5)]
    for ts, o, h, l in bars:
        obj._resolve_ordered_barriers({"ts": ts, "open": o, "high": h, "low": l, "gap": False}, now_ts=ts)
    obj._resolve_ordered_barriers(None, now_ts=bars[-1][0], final=True)
    obs = obj.observations_log[-1]
    assert obs["disposition"] == "LABELED_POSITIVE"

    tape = [{"ts": ts, "open": o, "high": h, "low": l, "gap": False} for ts, o, h, l in bars]
    report = validate_target_parity(_contract(), [{
        "candidate": {"observation_ts": T0, "session_close_ts": None, "atr": 10.0, "direction": 1},
        "events": tape,
        "actual": {"disposition": obs["disposition"], "label": obs["target_flip_within_horizon"],
                   "censor_reason": obs["censor_reason"]},
    }])
    assert report["passed"], report["examples"]
    assert report["primitive"] == "ordered_barrier"


def test_primitive_timeout_is_negative_not_censored():
    obj = _collector()
    obj._track_pending({"observation_ts": T0, "regime_start_ns": T0 - 300 * NS,
                        "regime_direction": 1, "checkpoint_index": 3, "target_frozen_atr": 10.0}, T0)
    bars = [(T0 + s * NS, 20000.0, 20000.4, 19999.6) for s in range(1, HORIZON + 2)]
    for ts, o, h, l in bars:
        obj._resolve_ordered_barriers({"ts": ts, "open": o, "high": h, "low": l, "gap": False}, now_ts=ts)
    obj._resolve_ordered_barriers(None, now_ts=bars[-1][0], final=True)
    obs = obj.observations_log[-1]
    assert obs["disposition"] == "LABELED_NEGATIVE"
    assert obs["censor_reason"] is None

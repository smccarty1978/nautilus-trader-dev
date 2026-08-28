"""Ordered-barrier target execution is population-agnostic and faithful to the contract.

Regression coverage for the defect the workflow canary exposed: the ordered-barrier
``TargetRuntime`` was only reachable from the ``episode_lifecycle`` population path,
because ``_track_pending`` required the population candidate builder to pre-populate a
target-specific ``entry_price``.  The contract declares ``entry_reference = next_bar_open``,
so the execution price must be resolved by the ``TargetRuntime`` from the causal 1s tape --
the OPEN of the first bar strictly after the decision T -- identically for every
population type, with the barrier ATR frozen at T.

These tests drive the runtime, the independent replay oracle, and the collector's
ordered-barrier machinery directly with synthetic timestamps (no BacktestEngine).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_workflow.target_runtime import (
    NS,
    resolve_target_runtime,
    validate_target_parity,
)
from research_workflow.target_replay_oracle import replay

HORIZON = 60

import pandas as pd
# A realistic mid-RTH decision timestamp so session_close_ns() is well-defined.
T0 = int(pd.Timestamp("2023-03-03 10:00:00", tz="America/Chicago").tz_convert("UTC").value)


def _contract(favorable=0.25, adverse=0.25, horizon=HORIZON, session_end_censoring=True, max_gap=1):
    return {
        "primitive": "ordered_barrier",
        "required_forward_outcomes": [{
            "id": "fo",
            "entry_reference": "next_bar_open",
            "horizon_seconds": horizon,
            "session_end_censoring": session_end_censoring,
            "max_gap_seconds": max_gap,
            "ordered_barriers": [{
                "id": "b", "favorable_atr": favorable, "adverse_atr": adverse,
                "horizon_seconds": horizon,
            }],
        }],
    }


def _collector(*, direction=1, session_end_censoring=True, session="RTH", horizon=HORIZON):
    """A bare collector shell exercising only the ordered-barrier disposition machinery."""
    from research_workflow.generic_collector import FlipPredictionCollector

    obj = FlipPredictionCollector.__new__(FlipPredictionCollector)
    obj.cfg = SimpleNamespace(horizon_seconds=horizon, session=session,
                              session_end_censoring=session_end_censoring, target_contract={})
    obj._benchmark_mode = ""
    obj._target_primitive = "ordered_barrier"
    obj._target_runtime = resolve_target_runtime({"primitive": "ordered_barrier"})
    obj._ordered_barrier = {"favorable_atr": 0.25, "adverse_atr": 0.25, "horizon_seconds": horizon}
    obj._ordered_barrier_entry_reference = "next_bar_open"
    obj._ordered_barrier_max_gap_seconds = 1
    obj.active_regime_dir = direction
    obj.pending_candidates = []
    obj.observations_log = []
    obj._next_pending_horizon_ns = None
    return obj


def _run(obj, T, bars, *, direction=1):
    """Feed (ts, open, high, low) bars; return the single emitted observation.

    Stashes the emitted candidate's retained event tape on ``obj._emitted_tape``.
    """
    orig = obj._emit_observation

    def _cap(cand, disp, flip_ts, censor_reason=None, censored_at_ts=None):
        obj._emitted_tape = [dict(e) for e in cand.get("events", ())]
        return orig(cand, disp, flip_ts, censor_reason, censored_at_ts)

    obj._emit_observation = _cap
    for ts, o, h, l in bars:
        obj._resolve_ordered_barriers({"ts": ts, "open": o, "high": h, "low": l, "gap": False},
                                      now_ts=ts)
    obj._resolve_ordered_barriers(None, now_ts=bars[-1][0], final=True)
    return obj.observations_log[-1] if obj.observations_log else None


def _checkpoint_cand(T, atr=10.0, direction=1):
    return {"observation_ts": T, "regime_start_ns": T - 300 * NS, "regime_direction": direction,
            "checkpoint_index": 3, "close": 20000.0, "atr": atr}


def _episode_cand(T, atr=10.0, direction=1):
    # Episode row: candidate-time ATR under the episode key names, NO entry_price.
    return {"observation_ts": T, "regime_start_ns": T - 300 * NS, "regime_direction": direction,
            "checkpoint_index": 3, "atr_t": atr, "target_frozen_atr": atr}


# ---------------------------------------------------------------------------
# 1 + 4: checkpoint_grid reaches a resolved observation; close is NOT the entry
# ---------------------------------------------------------------------------
def test_1_checkpoint_grid_ordered_barrier_reaches_a_resolved_observation():
    obj = _collector()
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    # entry = open of the first bar after T = 20000; +0.25 ATR = 20002.5 favorable.
    obs = _run(obj, T, [
        (T + 1 * NS, 20000.0, 20001.0, 19999.0),
        (T + 2 * NS, 20001.0, 20003.0, 20000.5),   # high 20003 >= 20002.5 -> SUCCESS
    ])
    assert obs is not None
    assert obs["disposition"] == "LABELED_POSITIVE"
    assert obs["target_flip_within_horizon"] == 1


def test_4_candidate_close_is_not_substituted_for_next_bar_open():
    obj = _collector()
    T = T0
    # candidate close is 20000 but the next bar opens at 19990: entry must be 19990,
    # so +0.25*10 = 19992.5 favorable is hit by a bar the close-based entry would miss.
    cand = _checkpoint_cand(T, atr=10.0)
    cand["close"] = 20000.0
    obj._track_pending(cand, T)
    obs = _run(obj, T, [
        (T + 1 * NS, 19990.0, 19992.9, 19989.0),   # high 19992.9 >= 19992.5 (entry 19990) -> SUCCESS
    ])
    assert obs["disposition"] == "LABELED_POSITIVE"
    # A close-based entry (20000) would need 20002.5 -- never reached -> would be negative.


# ---------------------------------------------------------------------------
# 2 + 12: episode_lifecycle uses the SAME semantics; population type is irrelevant
# ---------------------------------------------------------------------------
def test_2_and_12_population_type_does_not_change_target_semantics():
    T = T0
    bars = [
        (T + 1 * NS, 20000.0, 20001.0, 19999.0),
        (T + 2 * NS, 20001.0, 20002.0, 19997.4),   # low 19997.4 <= 19997.5 -> FAILURE (adverse)
    ]
    cg = _collector(); cg._track_pending(_checkpoint_cand(T, atr=10.0), T)
    ep = _collector(); ep._track_pending(_episode_cand(T, atr=10.0), T)
    obs_cg = _run(cg, T, bars)
    obs_ep = _run(ep, T, bars)
    assert obs_cg["disposition"] == obs_ep["disposition"] == "LABELED_NEGATIVE"
    assert obs_cg["target_flip_within_horizon"] == obs_ep["target_flip_within_horizon"] == 0
    assert obs_cg["resolved_at_ts"] == obs_ep["resolved_at_ts"]


# ---------------------------------------------------------------------------
# 3: next_bar_open is strictly after T
# ---------------------------------------------------------------------------
def test_3_entry_reference_bar_is_strictly_after_T():
    obj = _collector()
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    # A bar stamped exactly at T must not resolve the entry.
    obj._resolve_ordered_barriers({"ts": T, "open": 19000.0, "high": 30000.0, "low": 10000.0, "gap": False},
                                  now_ts=T)
    pend = obj.pending_candidates[0]
    assert pend["entry_resolved"] is False
    assert pend["entry_price"] is None
    # The next bar (strictly after T) sets the entry from its OPEN.
    obj._resolve_ordered_barriers({"ts": T + 1 * NS, "open": 20000.0, "high": 20000.5, "low": 19999.5, "gap": False},
                                  now_ts=T + 1 * NS)
    assert pend["entry_resolved"] is True
    assert pend["entry_price"] == 20000.0
    assert pend["entry_ts"] == T          # open instant == close-stamp - 1s bar duration
    assert pend["horizon_end_ts"] == T + HORIZON * NS
    # The retained event tape carries `open` so an independent replay can re-derive the
    # entry reference without reading any runtime-internal field.
    assert pend["events"][0]["open"] == 20000.0


# ---------------------------------------------------------------------------
# 5: ATR frozen at T, not at entry-reference time
# ---------------------------------------------------------------------------
def test_5_atr_is_frozen_at_T_not_at_entry_reference_time():
    obj = _collector()
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    pend = obj.pending_candidates[0]
    assert pend["atr"] == 10.0
    # Later bars cannot change the frozen ATR; barrier distance stays 0.25 * 10 = 2.5.
    obj._resolve_ordered_barriers({"ts": T + 1 * NS, "open": 20000.0, "high": 20002.4, "low": 19999.0, "gap": False},
                                  now_ts=T + 1 * NS)
    assert pend["atr"] == 10.0
    assert obj.observations_log == []     # 20002.4 < 20002.5, no touch yet


def test_5b_nonpositive_frozen_atr_fails_closed():
    obj = _collector()
    T = T0
    with pytest.raises(RuntimeError):
        obj._track_pending(_checkpoint_cand(T, atr=0.0), T)


def test_5c_target_atr_is_the_T_frozen_value_not_the_feature_normalization_atr():
    """Checkpoint rows carry both `atr` (regime-start, feature normalization) and
    `target_frozen_atr` (latest completed 1m ATR at T).  The barrier must use the
    latter -- the same target-time state the episode path supplies."""
    obj = _collector()
    T = T0
    cand = _checkpoint_cand(T, atr=99.0)          # feature-normalization ATR (regime start)
    cand["target_frozen_atr"] = 10.0             # ATR-at-T -> barrier half-width 0.25*10 = 2.5
    obj._track_pending(cand, T)
    assert obj.pending_candidates[0]["atr"] == 10.0
    obs = _run(obj, T, [(T + 1 * NS, 20000.0, 20002.5, 19999.0)])
    assert obs["disposition"] == "LABELED_POSITIVE"   # would be far from a 0.25*99 barrier


# ---------------------------------------------------------------------------
# 6 + 7: LONG and SHORT favorable/adverse orientation
# ---------------------------------------------------------------------------
def test_6_long_orientation():
    obj = _collector(direction=1)
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0, direction=1), T)
    # LONG: favorable = up. entry 20000, +2.5 = 20002.5.
    obs = _run(obj, T, [(T + 1 * NS, 20000.0, 20002.5, 19999.0)])
    assert obs["disposition"] == "LABELED_POSITIVE"


def test_7_short_orientation():
    obj = _collector(direction=-1)
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0, direction=-1), T)
    # SHORT: favorable = down. entry 20000, -2.5 = 19997.5.
    obs = _run(obj, T, [(T + 1 * NS, 20000.0, 20001.0, 19997.5)])
    assert obs["disposition"] == "LABELED_POSITIVE"
    # And an UP move is the adverse side for a short.
    obj2 = _collector(direction=-1)
    obj2._track_pending(_checkpoint_cand(T, atr=10.0, direction=-1), T)
    obs2 = _run(obj2, T, [(T + 1 * NS, 20000.0, 20002.5, 19999.0)])
    assert obs2["disposition"] == "LABELED_NEGATIVE"


# ---------------------------------------------------------------------------
# 8: timeout
# ---------------------------------------------------------------------------
def test_8_timeout_when_neither_barrier_is_touched():
    obj = _collector()
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    bars = [(T + s * NS, 20000.0, 20000.5, 19999.5) for s in range(1, HORIZON + 2)]
    obs = _run(obj, T, bars)
    assert obs["disposition"] == "LABELED_NEGATIVE"
    assert obs["target_flip_within_horizon"] == 0
    assert obs["censor_reason"] is None


# ---------------------------------------------------------------------------
# 9: session-end censoring
# ---------------------------------------------------------------------------
def test_9_session_end_censoring():
    import pandas as pd
    from research_workflow.generic_collector import session_close_ns

    obj = _collector(session="RTH", session_end_censoring=True)
    close = session_close_ns(int(pd.Timestamp("2023-03-03 10:00", tz="America/Chicago").tz_convert("UTC").value), "RTH")
    T = close - 30 * NS      # horizon (60s) reaches 30s past the RTH close
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    obs = _run(obj, T, [(T + s * NS, 20000.0, 20000.2, 19999.8) for s in range(1, 40)])
    assert obs["disposition"] == "CENSORED"
    assert obs["censor_reason"] == "SESSION_END"
    assert obs["target_flip_within_horizon"] is None


def test_9b_horizon_that_fits_before_close_is_labeled_not_censored():
    import pandas as pd
    from research_workflow.generic_collector import session_close_ns

    obj = _collector(session="RTH", session_end_censoring=True)
    close = session_close_ns(int(pd.Timestamp("2023-03-03 10:00", tz="America/Chicago").tz_convert("UTC").value), "RTH")
    T = close - 5 * 60 * NS
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    obs = _run(obj, T, [(T + s * NS, 20000.0, 20000.2, 19999.8) for s in range(1, HORIZON + 2)])
    assert obs["disposition"] == "LABELED_NEGATIVE"


# ---------------------------------------------------------------------------
# 10: exact horizon behavior
# ---------------------------------------------------------------------------
def test_10c_horizon_is_the_compiled_barrier_horizon_not_cfg_fallback():
    """`cfg.horizon_seconds` falls back to 300 when the target declares no top-level
    horizon; the ordered-barrier deadline must come from the barrier's own
    `horizon_seconds` (60 here), not that fallback."""
    obj = _collector(session_end_censoring=False, horizon=HORIZON)
    obj.cfg.horizon_seconds = 300                      # the build_collector_config_kwargs fallback
    obj._ordered_barrier["horizon_seconds"] = HORIZON  # the compiled barrier
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    obj._resolve_ordered_barriers({"ts": T + 1 * NS, "open": 20000.0, "high": 20000.1,
                                   "low": 19999.9, "gap": False}, now_ts=T + 1 * NS)
    assert obj.pending_candidates[0]["horizon_end_ts"] == T + HORIZON * NS


def test_10_touch_exactly_on_the_horizon_boundary_is_a_touch():
    obj = _collector(session_end_censoring=False)
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    # entry_ts == T, horizon_end == T + 60s. A touch on the bar closing exactly at
    # horizon_end counts.
    bars = [(T + s * NS, 20000.0, 20000.5, 19999.5) for s in range(1, HORIZON)]
    bars.append((T + HORIZON * NS, 20000.0, 20002.5, 19999.0))
    obs = _run(obj, T, bars)
    assert obs["disposition"] == "LABELED_POSITIVE"
    assert obs["resolved_at_ts"] == T + HORIZON * NS


def test_10b_touch_one_second_past_the_horizon_does_not_count():
    obj = _collector(session_end_censoring=False)
    T = T0
    obj._track_pending(_checkpoint_cand(T, atr=10.0), T)
    bars = [(T + s * NS, 20000.0, 20000.5, 19999.5) for s in range(1, HORIZON + 1)]
    bars.append((T + (HORIZON + 1) * NS, 20000.0, 25000.0, 15000.0))   # huge, but too late
    obs = _run(obj, T, bars)
    assert obs["disposition"] == "LABELED_NEGATIVE"


# ---------------------------------------------------------------------------
# 11: runtime vs independent replay oracle -- zero mismatches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("scenario", ["success", "failure", "timeout"])
def test_11_runtime_matches_independent_replay_oracle(direction, scenario):
    contract = _contract()
    T = T0
    obj = _collector(direction=direction, session_end_censoring=True)
    obj._track_pending(_checkpoint_cand(T, atr=10.0, direction=direction), T)

    up = {"success": 20002.5, "failure": 20000.5, "timeout": 20000.5}[scenario]
    dn = {"success": 19999.5, "failure": 19997.5, "timeout": 19999.5}[scenario]
    if direction < 0:
        up, dn = ({"success": 20000.5, "failure": 20002.5, "timeout": 20000.5}[scenario],
                  {"success": 19997.5, "failure": 19999.5, "timeout": 19999.5}[scenario])
    bars = [(T + s * NS, 20000.0, up if s == 2 else 20000.4, dn if s == 2 else 19999.6)
            for s in range(1, HORIZON + 2)]
    obs = _run(obj, T, bars)

    pend_events = [{"ts": ts, "open": o, "high": h, "low": l, "gap": False} for ts, o, h, l in bars]
    candidate = {"observation_ts": T, "session_close_ts": None, "atr": 10.0, "direction": direction}
    report = validate_target_parity(contract, [{
        "candidate": candidate, "events": pend_events,
        "actual": {"disposition": obs["disposition"], "label": obs["target_flip_within_horizon"],
                   "censor_reason": obs["censor_reason"]},
    }])
    assert report["disposition_mismatches"] == 0
    assert report["binary_label_mismatches"] == 0
    assert report["censoring_mismatches"] == 0
    assert report["passed"]

    # And the oracle replays cleanly straight off the collector's OWN retained event
    # tape (which carries `open`) -- no hand-built event list, no runtime-internal field.
    from research_workflow.target_runtime import _norm_disposition
    oracle = replay(contract, {"observation_ts": T, "session_close_ts": None,
                               "atr": 10.0, "direction": direction}, obj._emitted_tape)
    assert obj._emitted_tape and all("open" in e for e in obj._emitted_tape)
    assert _norm_disposition(oracle["disposition"]) == _norm_disposition(obs["disposition"])


def test_11b_oracle_is_independent_of_pre_populated_entry_price():
    """The oracle derives entry from the tape and ignores a misleading entry_price."""
    contract = _contract()
    T = 0
    events = [{"ts": 1 * NS, "open": 20000.0, "high": 20002.5, "low": 19999.0, "gap": False}]
    # a wrong pre-populated entry_price must not change the oracle's answer
    good = replay(contract, {"observation_ts": T, "session_close_ts": None, "atr": 10.0,
                             "direction": 1, "entry_price": 999999.0}, events)
    assert good["disposition"] == "POSITIVE"

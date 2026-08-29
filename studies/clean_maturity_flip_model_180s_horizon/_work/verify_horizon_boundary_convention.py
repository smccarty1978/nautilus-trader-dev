"""Freeze the 180s flip-horizon boundary convention for this study.

Researcher requirement (2026-08-29 authorization): the collector's live labeling path,
`FlipTargetRuntime`, and the independent replay oracle must agree exactly on whether a
prevailing-1m-regime flip whose confirmation lands at exactly T + 180s is POSITIVE
(within horizon) or NEGATIVE (outside). A disagreement is a target-semantic blocker.

Established convention: the horizon upper bound is INCLUSIVE.
    flip at ts == T + 180s      -> POSITIVE
    flip at ts == T + 180s + 1s -> NEGATIVE / outside
"""
from __future__ import annotations

NS = 1_000_000_000
HORIZON_S = 180
T = 1_000 * NS
END = T + HORIZON_S * NS  # inclusive horizon endpoint


def _flip_events(flip_ts: int):
    return [{"ts": flip_ts, "direction": -1}]


def test_flip_target_runtime_legacy_boundary_inclusive():
    from research_workflow.target_runtime import FlipTargetRuntime, POSITIVE, NEGATIVE

    rt = FlipTargetRuntime()
    cand = {"observation_ts": T, "horizon_end_ts": END, "session_close_ts": None}

    at_end = rt.terminal(cand, [{"ts": END, "flip": True}], final=True)
    assert at_end.disposition == POSITIVE, at_end

    past_end = rt.terminal(cand, [{"ts": END + NS, "flip": True}], final=True)
    assert past_end.disposition == NEGATIVE, past_end


def test_replay_oracle_flip_condition_boundary_inclusive():
    from research_workflow.target_replay_oracle import _replay_flip_condition

    contract = {"direction": "opposite", "horizon_seconds": HORIZON_S,
                "required_forward_outcomes": []}
    cond = {"kind": "flip", "horizon_seconds": HORIZON_S, "direction": "opposite"}
    candidate = {"observation_ts": T, "regime_direction": 1, "session_close_ts": None}
    tape = [{"ts": T}, {"ts": END}, {"ts": END + NS}]

    at_end = _replay_flip_condition(contract, cond, candidate, _flip_events(END), tape)
    assert at_end["disposition"] == "POSITIVE", at_end

    past_end = _replay_flip_condition(contract, cond, candidate, _flip_events(END + NS), tape)
    assert past_end["disposition"] == "NEGATIVE", past_end


def test_collector_sweep_holds_coincident_horizon_end_flip():
    """The live inline path holds a candidate whose horizon ends exactly at now_ts for
    one more tick so a coincident 1m flip (dispatched after the same-timestamp 1s bar)
    still lands POSITIVE -- i.e. inclusive. `final=True` (run end) then resolves NEGATIVE.
    """
    import inspect
    from research_workflow import generic_collector

    src = inspect.getsource(generic_collector.GenericStudyCollector._sweep_elapsed_horizons)
    # The load-bearing inclusive guard (causal audit pass 01, parent study):
    assert "horizon_end == now_ts and not final" in src
    assert "horizon_end > now_ts" in src

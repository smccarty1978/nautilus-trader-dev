"""RT-07 -- bare flip_within_horizon parity uses an INDEPENDENT oracle.

``validate_target_parity`` used ``FlipTargetRuntime.terminal()`` as the expected result
for a bare flip target -- the runtime scoring itself. It now routes bare flip through
``target_replay_oracle.replay_expression`` -> ``_replay_flip_condition``, the same
deliberately-separate implementation a composite flip child is checked against. A defect
injected into the runtime is therefore caught.
"""
from __future__ import annotations

import pytest

from research_workflow.target_runtime import (
    CENSORED,
    NEGATIVE,
    POSITIVE,
    FlipTargetRuntime,
    TargetResult,
    validate_target_parity,
)
from research_workflow.target_replay_oracle import replay_expression

NS = 1_000_000_000
CONTRACT = {"primitive": "flip_within_horizon", "horizon_seconds": 300, "direction": None}


def _resolved(*, flips=(), tape=(), session_close_ts=None, prevailing=1, final=True):
    rt = FlipTargetRuntime()
    T = 1000 * NS
    p = rt.open_pending({
        "observation_ts": T, "horizon_seconds": 300, "regime_direction": prevailing,
        "target_direction_role": "opposite", "session_close_ts": session_close_ts,
    })
    for b in tape:
        rt.ingest_bar(p, b)
    for f in flips:
        rt.ingest_flip(p, f)
    p["tape"] = list(tape)
    res = rt.terminal(p, final=final)
    row = rt.parity_row(p, {"disposition": res.disposition, "label": res.label,
                            "censor_reason": res.censor_reason})
    return rt, p, res, row


# --------------------------------------------------------------------------- #
# the oracle agrees with a correct runtime, for each disposition
# --------------------------------------------------------------------------- #
def test_positive_agrees():
    _, _, res, row = _resolved(flips=[{"ts": 1000 * NS + 100 * NS, "direction": -1}])
    assert res.disposition == POSITIVE
    assert validate_target_parity(CONTRACT, [row])["passed"]


def test_negative_agrees():
    _, _, res, row = _resolved(tape=[{"ts": 1000 * NS + 300 * NS}])
    assert res.disposition == NEGATIVE
    assert validate_target_parity(CONTRACT, [row])["passed"]


def test_session_end_censor_agrees():
    _, _, res, row = _resolved(session_close_ts=1000 * NS + 100 * NS)
    assert res.disposition == CENSORED
    assert validate_target_parity(CONTRACT, [row])["passed"]


# --------------------------------------------------------------------------- #
# the oracle is genuinely independent -- a corrupted runtime is caught
# --------------------------------------------------------------------------- #
def test_corrupted_runtime_flip_window_is_detected(monkeypatch):
    """Runtime ignores the flip entirely -> says NEGATIVE. Independent oracle still
    sees the in-window flip -> POSITIVE. validate_target_parity must flag it."""
    _, pending, _, _ = _resolved(flips=[{"ts": 1000 * NS + 100 * NS, "direction": -1}])

    def _broken(pending, *, final):  # noqa: ARG001 - signature match
        return TargetResult(NEGATIVE, 0, int(pending["horizon_end_ts"]))

    monkeypatch.setattr(FlipTargetRuntime, "_terminal_pending", staticmethod(_broken))
    rt = FlipTargetRuntime()
    bad = rt.terminal(pending, final=True)
    assert bad.disposition == NEGATIVE  # the corruption took effect
    row = rt.parity_row(pending, {"disposition": bad.disposition, "label": bad.label,
                                  "censor_reason": bad.censor_reason})

    report = validate_target_parity(CONTRACT, [row])
    assert not report["passed"]
    assert report["disposition_mismatches"] == 1
    assert report["binary_label_mismatches"] == 1
    assert report["examples"][0]["expected"]["disposition"] == POSITIVE


def test_corrupted_runtime_ignoring_session_close_is_detected(monkeypatch):
    _, pending, _, _ = _resolved(session_close_ts=1000 * NS + 100 * NS)

    def _broken(pending, *, final):  # noqa: ARG001
        return TargetResult(NEGATIVE, 0, int(pending["horizon_end_ts"]))

    monkeypatch.setattr(FlipTargetRuntime, "_terminal_pending", staticmethod(_broken))
    rt = FlipTargetRuntime()
    bad = rt.terminal(pending, final=True)
    row = rt.parity_row(pending, {"disposition": bad.disposition, "label": bad.label,
                                  "censor_reason": bad.censor_reason})
    report = validate_target_parity(CONTRACT, [row])
    assert not report["passed"]
    assert report["censoring_mismatches"] == 1


def test_validator_bare_flip_branch_does_not_call_flip_runtime_terminal(monkeypatch):
    """Direct proof the oracle side no longer routes through FlipTargetRuntime.terminal."""
    calls = []
    real_terminal = FlipTargetRuntime.terminal

    def _spy(self, *a, **k):
        calls.append(1)
        return real_terminal(self, *a, **k)

    monkeypatch.setattr(FlipTargetRuntime, "terminal", _spy)
    _, _, _, row = _resolved(flips=[{"ts": 1000 * NS + 50 * NS, "direction": -1}])
    calls.clear()
    validate_target_parity(CONTRACT, [row])
    assert calls == [], "validate_target_parity still calls FlipTargetRuntime.terminal for the oracle"

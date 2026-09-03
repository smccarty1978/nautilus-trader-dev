"""Repair packet D / D3: gap validity must be adjudicated BEFORE any post-horizon bar is
accepted as a resolution observation under ``horizon_end_rule: first_bar_at_or_after``.
Resolution precedence at every bar (in-horizon or the first post-horizon bar) is:
SESSION_END > GAP > BARRIER_TOUCH (same-bar rule) > HORIZON_EXPIRY.

Both the kernel (research_workflow.host.outcomes.LabelOutcomeKernel) and the independent
oracle (research_workflow.target_replay_oracle.replay) are exercised against the same
sparse-tape fixtures, mirroring the parity pattern in test_host_core.py."""
from __future__ import annotations

import pytest

from research_workflow.host.interfaces import NS, BarView
from research_workflow.host.outcomes import LabelOutcomeContract, LabelOutcomeKernel
from research_workflow.target_replay_oracle import replay

T = 1000 * NS


class _Sessions:
    def __init__(self, close=None):
        self.close = close

    def in_session(self, ts):
        return True

    def session_close(self, ts):
        return self.close


def _kernel_contract(*, max_gap_ns, close=None, horizon_end_rule="first_bar_at_or_after"):
    return LabelOutcomeContract.from_plan({
        "contract": "label", "kernel": "barrier", "direction": "d", "atr": "a", "entry_reference": "next_bar_open",
        "session_end_censoring": close is not None, "max_gap_ns": max_gap_ns, "same_bar_rule": "ambiguous_censor",
        "horizon_end_rule": horizon_end_rule,
        "arms": [{"id": "x", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_ns": 10 * NS, "expiry": "censor", "prefix": "x"}],
        "primary_arm": "x",
    })


def _oracle_contract(*, max_gap_seconds, horizon_end_rule="first_bar_at_or_after"):
    return {"primitive": "ordered_barrier", "required_forward_outcomes": [{
        "id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": max_gap_seconds is not None or True,
        "max_gap_seconds": max_gap_seconds,
        "ordered_barriers": [{"id": "b", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 10,
                              "horizon_expiry_policy": "censor", "horizon_end_rule": horizon_end_rule}],
    }]}


def _run_kernel(contract, close, tape, gap_flag_ts=None):
    kernel = LabelOutcomeKernel(contract, _Sessions(close))
    kernel.open({"observation_ts": T, "regime_start_ns": 0, "checkpoint_index": 0}, T, 1, 1.0)
    for k, hi, lo in tape:
        kernel.on_bar(BarView("s", T + (k - 1) * NS, T + k * NS, 100.0, hi, lo, 100.2, 1.0))
    kernel.finalize(T + (tape[-1][0] + 10) * NS)
    row = kernel.drain_rows()[0]
    return row["disposition"].replace("LABELED_", ""), row["censor_reason"]


def _run_oracle(contract, close, tape):
    events = [{"ts": T + k * NS, "open": 100.0, "high": hi, "low": lo, "close": 100.2, "gap": False} for k, hi, lo in tape]
    o = replay(contract, {"observation_ts": T, "atr": 1.0, "direction": 1, "session_close_ts": close}, events)
    return o["disposition"], o["censor_reason"]


# (a) post-horizon bar beyond max_gap touching favorable -> CENSORED GAP in both kernel and oracle,
# not the POSITIVE the barrier touch would otherwise yield.
def test_post_horizon_bar_beyond_max_gap_is_censored_gap_not_a_touch():
    # in-horizon bars present through k=5 (prev accepted ts = T+5); horizon end = T+10; next bar at
    # k=16 (gap of 11s from T+5, exceeds max_gap=5s) touches the favorable barrier (high >= 101.0).
    tape = [(k, 100.5, 99.5) for k in range(1, 6)] + [(16, 101.5, 99.5)]
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape)
    assert kc == ("CENSORED", "GAP"), kc
    assert oc == ("CENSORED", "GAP"), oc
    assert kc == oc


# (b) same bar within max_gap -> the touch is accepted -> POSITIVE in both.
def test_post_horizon_bar_within_max_gap_resolves_as_a_touch():
    tape = [(k, 100.5, 99.5) for k in range(1, 9)] + [(11, 101.5, 99.5)]   # gap of 3s from T+8, within max_gap=5s
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape)
    assert kc == ("POSITIVE", None), kc
    assert oc == ("POSITIVE", None), oc
    assert kc == oc


# (c) strict rule is unaffected: no post-horizon bar is ever evaluated for a touch regardless of gap.
def test_strict_rule_unaffected_by_gap_precedence_change():
    tape = [(k, 100.5, 99.5) for k in range(1, 6)] + [(16, 101.5, 99.5)]
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS, horizon_end_rule="strict"), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5, horizon_end_rule="strict"), None, tape)
    assert kc == ("CENSORED", "TIMEOUT"), kc
    assert oc == ("CENSORED", "TIMEOUT"), oc


# (d) session_end beats gap when both conditions hold on the same bar: the bar is never evaluated
# as a GAP resolution (or a barrier touch) once it is past the censoring session's close -- the
# existing session-close precedence (checked first in the past_end branch) must not regress to a
# GAP censor now that gap-checking has been added to that branch.
def test_session_end_takes_precedence_over_gap():
    # close is AFTER the horizon end (T+10) so the arm is not resolved SESSION_END at entry; the
    # post-horizon bar at k=16 is both a gap (11s > max_gap=5s) and past session close (close=T+12).
    close = T + 12 * NS
    tape = [(k, 100.5, 99.5) for k in range(1, 6)] + [(16, 101.5, 99.5)]  # both a gap AND past session close
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS, close=close), close, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), close, tape)
    assert kc[1] != "GAP", kc
    assert oc[1] != "GAP", oc
    assert kc == ("CENSORED", "TIMEOUT"), kc
    assert oc == ("CENSORED", "TIMEOUT"), oc


# (e) max_gap None -> unchanged behavior (a distant post-horizon bar is still evaluated for a touch).
def test_max_gap_none_unchanged():
    tape = [(k, 100.5, 99.5) for k in range(1, 6)] + [(16, 101.5, 99.5)]
    kc = _run_kernel(_kernel_contract(max_gap_ns=None), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=None), None, tape)
    assert kc == ("POSITIVE", None), kc
    assert oc == ("POSITIVE", None), oc


# (f) adjacent bypass: gap exactly == max_gap_ns is NOT a gap (strict >); max_gap_ns+1 IS a gap.
def test_adjacent_bypass_strict_greater_than():
    max_gap_ns = 5 * NS
    tape_exact = [(1, 100.5, 99.5)] + [(1 + 5, 101.5, 99.5)]     # prev_ts=T+1, next at T+6: gap==5s exactly
    kc_exact = _run_kernel(_kernel_contract(max_gap_ns=max_gap_ns), None, tape_exact)
    oc_exact = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape_exact)
    assert kc_exact == ("POSITIVE", None), kc_exact
    assert oc_exact == ("POSITIVE", None), oc_exact

    tape_over = [(1, 100.5, 99.5)] + [(1 + 6, 101.5, 99.5)]      # gap==6s: exceeds max_gap
    kc_over = _run_kernel(_kernel_contract(max_gap_ns=max_gap_ns), None, tape_over)
    oc_over = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape_over)
    assert kc_over == ("CENSORED", "GAP"), kc_over
    assert oc_over == ("CENSORED", "GAP"), oc_over

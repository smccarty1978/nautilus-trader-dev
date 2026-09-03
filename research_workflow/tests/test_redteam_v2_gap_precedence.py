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


# (d) session_end beats gap (and beats horizon_expiry) when the first bar the tape offers past
# the horizon end is already past the censoring session's close: the bar is never evaluated as a
# GAP resolution (or a barrier touch), and the arm never falls through to its horizon_expiry_policy
# -- resolution precedence is SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY.
def test_session_end_takes_precedence_over_gap():
    # close is AFTER the horizon end (T+10) so the arm is not resolved SESSION_END at entry; the
    # post-horizon bar at k=16 is both a gap (11s > max_gap=5s) and past session close (close=T+12).
    close = T + 12 * NS
    tape = [(k, 100.5, 99.5) for k in range(1, 6)] + [(16, 101.5, 99.5)]  # both a gap AND past session close
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS, close=close), close, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), close, tape)
    assert kc[1] != "GAP", kc
    assert oc[1] != "GAP", oc
    assert kc == ("CENSORED", "SESSION_END"), kc
    assert oc == ("CENSORED", "SESSION_END"), oc


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


# --- C9/G2 regression: expiry:"negative" must never manufacture a directional label out of a
# session-boundary data gap. Resolution precedence is SESSION_END > GAP > BARRIER_TOUCH >
# HORIZON_EXPIRY: when the first bar the tape offers after the horizon end is already past the
# censoring session's close, that is SESSION_END, never a HORIZON_EXPIRY-driven NEGATIVE.

def _kernel_contract_expiry(*, max_gap_ns, close, horizon_end_rule, expiry):
    return LabelOutcomeContract.from_plan({
        "contract": "label", "kernel": "barrier", "direction": "d", "atr": "a", "entry_reference": "next_bar_open",
        "session_end_censoring": close is not None, "max_gap_ns": max_gap_ns, "same_bar_rule": "ambiguous_censor",
        "horizon_end_rule": horizon_end_rule,
        "arms": [{"id": "x", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_ns": 10 * NS, "expiry": expiry, "prefix": "x"}],
        "primary_arm": "x",
    })


def _oracle_contract_expiry(*, max_gap_seconds, horizon_end_rule, expiry):
    return {"primitive": "ordered_barrier", "required_forward_outcomes": [{
        "id": "fo", "entry_reference": "next_bar_open", "session_end_censoring": True,
        "max_gap_seconds": max_gap_seconds,
        "ordered_barriers": [{"id": "b", "favorable_atr": 1.0, "adverse_atr": 1.0, "horizon_seconds": 10,
                              "horizon_expiry_policy": expiry, "horizon_end_rule": horizon_end_rule}],
    }]}


def test_expiry_negative_first_bar_at_or_after_session_gap_is_censored_not_negative():
    # horizon end = T+10 = session close; no bar exists between T+10 and the close (the tape has a
    # gap through T+9, then the next bar is far past both the horizon end AND the session close).
    # expiry:"negative" must NOT manufacture a NEGATIVE label from zero post-horizon observation --
    # this is a SESSION_END/data-gap condition, not a HORIZON_EXPIRY.
    close = T + 10 * NS
    tape = [(k, 100.5, 99.5) for k in range(1, 10)] + [(18000, 100.5, 99.0)]  # far bar never observed in-session
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=None, close=close, horizon_end_rule="first_bar_at_or_after", expiry="negative"), close, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=None, horizon_end_rule="first_bar_at_or_after", expiry="negative"), close, tape)
    assert kc == ("CENSORED", "SESSION_END"), kc
    assert oc == ("CENSORED", "SESSION_END"), oc
    assert kc == oc


def test_expiry_negative_strict_rule_horizon_elapsed_in_session_is_still_negative():
    # Control: strict horizon_end_rule, expiry:"negative", horizon fully elapsed WITH in-session
    # bars observed and no barrier touched -- this is a genuine HORIZON_EXPIRY and must still
    # resolve NEGATIVE (the fix must not regress the unambiguous case).
    close = T + 1000 * NS  # far past the horizon end -- no session boundary involved
    tape = [(k, 100.5, 99.5) for k in range(1, 12)]  # never touches favorable(101) or adverse(99)
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=None, close=close, horizon_end_rule="strict", expiry="negative"), close, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=None, horizon_end_rule="strict", expiry="negative"), close, tape)
    assert kc == ("NEGATIVE", None), kc
    assert oc == ("NEGATIVE", None), oc
    assert kc == oc


def test_entry_bar_itself_beyond_session_close_is_censored_session_end():
    # The very first (entry / next_bar_open) bar already lies beyond the session close -- the arm
    # must resolve CENSORED/SESSION_END at entry, in both kernel and oracle, never HORIZON_EXPIRY.
    close = T + 1 * NS  # close is essentially at T; the first bar after T is already past it
    tape = [(5, 100.5, 99.5)]  # entry bar itself is far past `close`
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=None, close=close, horizon_end_rule="first_bar_at_or_after", expiry="negative"), close, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=None, horizon_end_rule="first_bar_at_or_after", expiry="negative"), close, tape)
    assert kc == ("CENSORED", "SESSION_END"), kc
    assert oc == ("CENSORED", "SESSION_END"), oc
    assert kc == oc


def test_v2_host_path_never_routes_to_legacy_composite_replay():
    """Guard: the V2 grammar-compiled outcome contract (arms+flip, served by
    research_workflow.host.outcomes.LabelOutcomeKernel and target_replay_oracle.replay) must never
    reach the legacy V1 composite path (_replay_ordered_barrier_condition / replay_expression),
    which lacks the first_bar_at_or_after / gap-precedence fix and is frozen for V1 studies."""
    import inspect
    import research_workflow.host.outcomes as outcomes_mod
    import research_workflow.target_replay_oracle as oracle_mod

    source = inspect.getsource(outcomes_mod)
    assert "_replay_ordered_barrier_condition" not in source
    assert "replay_expression" not in source

    replay_source = inspect.getsource(oracle_mod.replay)
    assert "_replay_ordered_barrier_condition" not in replay_source
    assert "replay_expression" not in replay_source


# --- C-B (adversarial pass 02): `strict` was bypassing GAP/SESSION_END precedence at the
# horizon end, manufacturing a directional/expiry label from an unobserved gap that straddles
# the horizon boundary. These extend the D3 fixtures above to the previously-uncovered
# `strict` branch, plus the oracle DATA_END and entry-gap (N-3) semantics.

def test_strict_gap_straddling_horizon_end_is_censored_gap_expiry_negative():
    # prev accepted ts = T+1; horizon end = T+10 (unobserved span end-prev_ts=9s > max_gap=5s);
    # next observed bar is far past (k=16). `strict` never looks at that bar's OHLC, but the
    # unobserved span itself must still resolve GAP, not a manufactured NEGATIVE.
    tape = [(1, 100.5, 99.5), (16, 101.5, 99.5)]
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=5 * NS, close=None, horizon_end_rule="strict", expiry="negative"), None, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=5, horizon_end_rule="strict", expiry="negative"), None, tape)
    assert kc == ("CENSORED", "GAP"), kc
    assert oc == ("CENSORED", "GAP"), oc
    assert kc == oc


def test_strict_gap_straddling_horizon_end_is_censored_gap_not_timeout_expiry_censor():
    tape = [(1, 100.5, 99.5), (16, 101.5, 99.5)]
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=5 * NS, close=None, horizon_end_rule="strict", expiry="censor"), None, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=5, horizon_end_rule="strict", expiry="censor"), None, tape)
    assert kc == ("CENSORED", "GAP"), kc
    assert oc == ("CENSORED", "GAP"), oc
    assert kc != ("CENSORED", "TIMEOUT")
    assert kc == oc


def test_strict_bar_within_max_gap_of_horizon_end_expiry_unchanged():
    # prev accepted ts = T+8, within max_gap=5s of horizon end T+10 (end-prev_ts=2s); the actual
    # next observed bar is much later (k=50, ts-prev_ts=42s) -- irrelevant post-horizon gap.
    # `strict` must judge the horizon-boundary observation, not the raw bar-to-bar distance:
    # expiry policy (TIMEOUT) applies unchanged, not GAP.
    tape = [(k, 100.5, 99.5) for k in range(1, 9)] + [(50, 100.5, 99.5)]
    kc = _run_kernel(_kernel_contract_expiry(max_gap_ns=5 * NS, close=None, horizon_end_rule="strict", expiry="censor"), None, tape)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=5, horizon_end_rule="strict", expiry="censor"), None, tape)
    assert kc == ("CENSORED", "TIMEOUT"), kc
    assert oc == ("CENSORED", "TIMEOUT"), oc
    assert kc == oc


def test_oracle_data_end_before_horizon_never_manufactures_a_label():
    # W-2: the tape ends (no event ever reaches horizon_end_ts) -- the oracle must censor
    # DATA_END, never fall through to horizon_expiry_policy and manufacture NEGATIVE/TIMEOUT.
    tape = [(k, 100.5, 99.5) for k in range(1, 6)]   # never reaches horizon end (T+10)
    oc = _run_oracle(_oracle_contract_expiry(max_gap_seconds=None, horizon_end_rule="strict", expiry="negative"), None, tape)
    assert oc == ("CENSORED", "DATA_END"), oc
    oc_far = _run_oracle(_oracle_contract_expiry(max_gap_seconds=None, horizon_end_rule="first_bar_at_or_after", expiry="negative"), None, tape)
    assert oc_far == ("CENSORED", "DATA_END"), oc_far


def test_entry_gap_beyond_max_gap_is_censored_gap_not_a_stale_entry():
    # N-3: the entry observation (next_bar_open) is subject to the same gap rule as any other
    # -- an execution reference more than max_gap after T is a stale price, never a fill.
    tape = [(20, 100.5, 99.5)]   # first bar after T arrives 19s late; max_gap=5s
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape)
    assert kc == ("CENSORED", "GAP"), kc
    assert oc == ("CENSORED", "GAP"), oc
    assert kc == oc


def test_entry_gap_exactly_max_gap_is_not_a_gap():
    # entry_ts - T == max_gap exactly (strict `>`, not `>=`) -- must not be treated as a gap.
    tape = [(6, 100.5, 99.5)]    # entry_ts = T+5s == max_gap=5s
    kc = _run_kernel(_kernel_contract(max_gap_ns=5 * NS), None, tape)
    oc = _run_oracle(_oracle_contract(max_gap_seconds=5), None, tape)
    assert kc[1] != "GAP", kc
    assert oc[1] != "GAP", oc

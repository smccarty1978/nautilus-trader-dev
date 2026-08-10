"""Deterministic tests for the causal contract, on synthetic bars.

These do not touch the canonical store. They pin the properties that the study's
conclusions rest on, so a refactor cannot silently break them.
"""
from __future__ import annotations

import numpy as np
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    MarketData, RegimeIndex, NS,
)
from studies.top10_fast_confirm_runner_path.analysis.phases import auc
from studies.top10_fast_confirm_runner_path.implementation.engine import (
    FAST_CUTOFF_S, cohort_of, prepare, runner_bucket, walk,
)

T0 = 1_600_000_000 * NS


def _market(closes, *, highs=None, lows=None, opens=None, n_day=None):
    n = len(closes)
    c = np.asarray(closes, dtype=float)
    return MarketData(
        ts=T0 + np.arange(n, dtype=np.int64) * NS,
        open_=np.asarray(opens if opens is not None else c, dtype=float),
        high=np.asarray(highs if highs is not None else c, dtype=float),
        low=np.asarray(lows if lows is not None else c, dtype=float),
        close=c,
        day_close_ns=np.full(n, T0 + (n_day if n_day is not None else n) * NS,
                             dtype=np.int64),
    )


def _trade(**kw):
    base = {"regime_id": "RGM_test", "direction": 1, "side": "LONG",
            "entry_year": 2023, "terminal_label": "FINAL_FLIP_EXIT_WINNER",
            "entry_ns": T0, "entry_price": 100.0, "entry_atr": 1.0,
            "confirm_ns": T0 + 10 * NS}
    return base | kw


# ------------------------------------------------------ cohort classification

@pytest.mark.parametrize("secs,expected", [
    (0, "FAST_0_60"), (60, "FAST_0_60"), (60.5, "FAST_61_120"),
    (120, "FAST_61_120"), (121, "SLOW_121_300"), (300, "SLOW_121_300"),
    (301, "VERY_SLOW_GT300"),
])
def test_cohort_edges_are_half_open_and_exact(secs, expected):
    assert cohort_of(int(secs * NS)) == expected


def test_exact_120s_boundary_is_fast():
    """The defect that motivated integer-ns classification.

    Float seconds render an exact 120s gap as 120.00000000000001 in polars,
    which silently drops the boundary trades out of the primary population.
    """
    dt = 120 * NS
    assert dt <= FAST_CUTOFF_S * NS
    assert cohort_of(dt) == "FAST_61_120"


def test_runner_buckets_partition():
    assert runner_bucket(0.5) == "R0"
    assert runner_bucket(1.0) == "R1"
    assert runner_bucket(2.0) == "R2"
    assert runner_bucket(3.0) == "R3"
    assert runner_bucket(99.0) == "R3"


# ---------------------------------------------------------- causal fill rule

def test_trigger_fills_at_following_bar_open_not_trigger_price():
    closes = [100.0] * 6
    # entry is at T0, so the window starts at ABSOLUTE bar 1; window bar i is
    # absolute bar 1+i and its causal fill bar is absolute 2+i.
    opens = [100.0, 100.0, 100.0, 100.0, 105.0, 100.0]
    m = _market(closes, opens=opens)
    regimes = RegimeIndex(start_ns=np.array([T0 + 5 * NS]), direction=np.array([-1]))
    w = prepare(m, regimes, _trade(confirm_ns=T0 + 1 * NS))
    assert w is not None and w.start == 1
    # a trigger seen on window bar 2 fills at absolute bar 4's OPEN (105)
    assert w.realise(2, True) == pytest.approx(5.0)
    # ... and never at its own close, which is 100
    assert w.realise(2, False) == pytest.approx(0.0)


def test_policy_can_never_exit_after_the_natural_terminal():
    """The 1.00 ATR stop stays live in every policy (SPEC D1)."""
    closes = [100.0, 100.0, 98.9, 98.9, 101.0, 101.0]
    m = _market(closes)
    regimes = RegimeIndex(start_ns=np.array([T0 + 20 * NS]), direction=np.array([-1]))
    w = prepare(m, regimes, _trade(confirm_ns=T0 + 1 * NS))
    assert w.stop_i >= 0                      # 1.1 pt adverse on a 1.0 ATR stop
    assert w.nat_i == w.stop_i
    assert w.nat_kind == "STOP"
    assert w.nat_i <= w.unc_i


# ------------------------------------------------ landmark state is causal

def test_landmark_state_ignores_bars_after_the_landmark():
    """A huge favorable spike AFTER the landmark must not change its state."""
    base = [100.0] * 40
    m1 = _market(base)
    spiked = list(base)
    spiked[30:] = [200.0] * 10
    m2 = _market(spiked, highs=spiked)
    regimes = RegimeIndex(start_ns=np.array([T0 + 60 * NS]), direction=np.array([-1]))
    tr = _trade(confirm_ns=T0 + 1 * NS)
    s1 = {s["landmark_s"]: s for s in walk(m1, regimes, tr)[1]}
    s2 = {s["landmark_s"]: s for s in walk(m2, regimes, tr)[1]}
    for L in (5, 10, 15, 20):                 # landmarks strictly before the spike
        for k in ("ret_from_entry", "run_mfe_entry", "dd_from_run_max",
                  "mfe_since_confirm", "n_new_extremes"):
            assert s1[L][k] == pytest.approx(s2[L][k]), f"L={L} {k} saw the future"


def test_landmarks_are_strictly_after_confirmation():
    m = _market([100.0] * 60)
    regimes = RegimeIndex(start_ns=np.array([T0 + 90 * NS]), direction=np.array([-1]))
    tr = _trade(confirm_ns=T0 + 10 * NS)
    _, states = walk(m, regimes, tr)
    for s in states:
        assert s["landmark_ns"] > tr["confirm_ns"]


def test_eventual_maxmfe_is_unconstrained_by_the_stop():
    """Post-confirm geometry must not be censored by a live stop (NO CENSORING)."""
    # dips 1.1 ATR adverse (stopping the trade) then runs 4 ATR favorable
    closes = [100.0, 98.9, 99.0, 101.0, 104.0, 104.0]
    highs = [100.0, 100.0, 100.0, 101.0, 104.0, 104.0]
    lows = [100.0, 98.9, 99.0, 101.0, 104.0, 104.0]
    m = _market(closes, highs=highs, lows=lows)
    regimes = RegimeIndex(start_ns=np.array([T0 + 20 * NS]), direction=np.array([-1]))
    t, _ = walk(m, regimes, _trade(confirm_ns=T0 + 1 * NS))
    assert t["natural_kind"] == "STOP"
    assert t["natural_max_mfe_atr"] < 1.0            # stop truncates this one
    assert t["eventual_max_mfe_atr"] == pytest.approx(4.0)   # unconstrained does not


# --------------------------------------------------------------------- AUC

def test_auc_is_correct_and_tie_corrected():
    assert auc(np.array([1.0, 2.0, 3.0, 4.0]), np.array([0, 0, 1, 1])) == 1.0
    assert auc(np.array([4.0, 3.0, 2.0, 1.0]), np.array([0, 0, 1, 1])) == 0.0
    assert auc(np.array([1.0, 1.0, 1.0, 1.0]), np.array([0, 0, 1, 1])) == 0.5
    assert auc(np.array([1.0, 2.0]), np.array([1, 1])) is None


def test_auc_ignores_non_finite_scores():
    s = np.array([1.0, np.nan, 3.0, 4.0])
    assert auc(s, np.array([0, 0, 1, 1])) == 1.0

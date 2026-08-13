"""Two genuinely new causal surfaces in this study, both tested here:

1. `Regime5m.age_seconds_at`/`age_bars_at`/`flip_ts_at` called at
   `walk_a_confirm_ns` (a new timestamp) never resolve a flip after the
   decision instant (SPEC section 3).
2. The Phase 6 opportunity-capture-curve time-to-threshold scan (SPEC
   section 4, Phase 6) -- new derived logic, verified against toy trades
   with known answers.
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from studies.p90_5m_regime_context.implementation import regime_5m as R5M
from studies.post_confirm_5m_forward_opportunity.implementation import join as J
from studies.post_confirm_5m_forward_opportunity.implementation.analysis import (
    time_to_threshold_single_trade,
)


# ------------------------------------------------ causality: Regime5m at confirm

@pytest.fixture(scope="module")
def r5m():
    return R5M.load()


@pytest.fixture(scope="module")
def confirmation_state() -> pl.DataFrame:
    from studies.post_confirm_5m_forward_opportunity.implementation.lineage import (
        load_arms, load_classification, load_panel_trade_ids,
    )
    arms = load_arms()
    classification = load_classification()
    panel_ids = load_panel_trade_ids()
    r5m_ = R5M.load()
    return J.build_confirmation_state(arms, classification, r5m_, panel_ids)


def test_age_at_confirm_never_reads_a_flip_after_the_decision(r5m, confirmation_state):
    """flip_ts_at(walk_a_confirm_ns) must never exceed walk_a_confirm_ns itself."""
    confirm_ns = confirmation_state["walk_a_confirm_ns"].to_numpy()
    flip_ts = r5m.flip_ts_at(confirm_ns)
    initialised = flip_ts >= 0
    assert initialised.sum() > 0
    assert (flip_ts[initialised] <= confirm_ns[initialised]).all(), (
        "at least one flip_ts_at(confirm_ns) resolved a flip AFTER confirm_ns -- "
        "causal boundary violated at the new call site")


def test_age_seconds_matches_confirm_minus_flip_ts(r5m, confirmation_state):
    confirm_ns = confirmation_state["walk_a_confirm_ns"].to_numpy()
    age_s = confirmation_state["regime_age_s_at_confirm"].to_numpy()
    flip_ts = r5m.flip_ts_at(confirm_ns)
    initialised = flip_ts >= 0
    expected = (confirm_ns[initialised] - flip_ts[initialised]) / R5M.NS
    np.testing.assert_allclose(age_s[initialised], expected)


def test_uninitialised_rows_disclosed_not_negative(confirmation_state):
    age_s = confirmation_state["regime_age_s_at_confirm"].to_numpy()
    finite = age_s[~np.isnan(age_s)]
    assert (finite >= 0).all()


def test_age_at_confirm_is_a_different_call_site_than_at_p90(confirmation_state):
    """Sanity: the new confirm-time age is not simply a copy of the at-P90 age
    (they are computed at different timestamps and should usually differ)."""
    at_p90 = confirmation_state["regime_age_s_at_p90"].to_numpy()
    at_confirm = confirmation_state["regime_age_s_at_confirm"].to_numpy()
    both_finite = ~np.isnan(at_p90) & ~np.isnan(at_confirm)
    assert both_finite.sum() > 0
    assert not np.allclose(at_p90[both_finite], at_confirm[both_finite])


# ------------------------------------------------ Phase 6 capture-curve logic

def test_capture_curve_monotonic_trade_crosses_all_thresholds():
    offsets = np.array([15, 30, 45, 60], dtype=float)
    fractions = np.array([0.1, 0.3, 0.6, 0.9], dtype=float)
    result = time_to_threshold_single_trade(offsets, fractions, (0.25, 0.50, 0.75, 0.90))
    assert result[0.25] == 30
    assert result[0.50] == 45
    assert result[0.75] == 60
    assert result[0.90] == 60  # exact-equality boundary is inclusive (>=)


def test_capture_curve_never_reaches_threshold_is_none():
    offsets = np.array([15, 30], dtype=float)
    fractions = np.array([0.05, 0.10], dtype=float)
    result = time_to_threshold_single_trade(offsets, fractions, (0.25, 0.50))
    assert result[0.25] is None
    assert result[0.50] is None


def test_capture_curve_first_crossing_not_last():
    """If a trade oscillates above and below a threshold, the FIRST crossing
    is reported, not the last or the max."""
    offsets = np.array([15, 30, 45, 60], dtype=float)
    fractions = np.array([0.20, 0.30, 0.20, 0.40], dtype=float)
    result = time_to_threshold_single_trade(offsets, fractions, (0.25,))
    assert result[0.25] == 30


def test_capture_curve_empty_trade_is_none():
    result = time_to_threshold_single_trade(
        np.array([], dtype=float), np.array([], dtype=float), (0.25, 0.50))
    assert result[0.25] is None
    assert result[0.50] is None

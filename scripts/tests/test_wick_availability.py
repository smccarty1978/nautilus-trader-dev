"""Availability / null semantics for the 1m wick imbalance feature (Finding C2).

``WickTracker.calculate()`` used to return ``0.0`` before any completed 1m bar existed.
That made three states indistinguishable in the emitted surface. The four cases below are
the whole point of the fix: exactly one of them is *unavailable*, and the other three are
real observations whose values the frozen formula defines.

The formula itself is unchanged and is not under test here beyond its stated definition.
"""

from __future__ import annotations

import pytest

from features.registry import FEATURE_REGISTRY
from features.trackers.wick import WickTracker, compute_wick_imbalance

FEATURE = "latest_1m_wick_imbalance"


# ---------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------

def test_1_no_completed_1m_bar_is_unavailable_not_zero():
    """C2.1 -- unavailable must be None. This is the state that used to read 0.0."""
    t = WickTracker()
    assert t.is_available is False
    assert t.calculate()[FEATURE] is None


def test_2_completed_zero_range_bar_is_a_real_zero():
    """C2.2 -- high == low is a real observation the formula defines as 0.0."""
    t = WickTracker()
    t.update(open_px=100.0, high=100.0, low=100.0, close=100.0)
    assert t.is_available is True
    assert t.calculate()[FEATURE] == 0.0


def test_3_completed_balanced_wick_bar_is_a_real_zero():
    """C2.3 -- equal upper and lower wicks are also a real 0.0."""
    t = WickTracker()
    # open == close at the midpoint: upper wick == lower wick == 1.0
    t.update(open_px=100.0, high=101.0, low=99.0, close=100.0)
    assert t.is_available is True
    assert t.calculate()[FEATURE] == pytest.approx(0.0)


def test_4_ordinary_asymmetric_bar_is_non_zero():
    """C2.4 -- an upper-dominant bar is positive; a lower-dominant bar is negative."""
    upper = WickTracker()
    upper.update(open_px=99.0, high=102.0, low=98.5, close=99.5)
    v_upper = upper.calculate()[FEATURE]
    assert v_upper > 0.0

    lower = WickTracker()
    lower.update(open_px=101.0, high=101.5, low=98.0, close=100.5)
    v_lower = lower.calculate()[FEATURE]
    assert v_lower < 0.0


def test_the_four_states_are_mutually_distinguishable():
    """The conflation the fix removes: state 1 must not equal states 2/3."""
    unavailable = WickTracker().calculate()[FEATURE]

    zero_range = WickTracker()
    zero_range.update(100.0, 100.0, 100.0, 100.0)

    balanced = WickTracker()
    balanced.update(100.0, 101.0, 99.0, 100.0)

    assert unavailable is None
    assert zero_range.calculate()[FEATURE] is not None
    assert balanced.calculate()[FEATURE] is not None


# ---------------------------------------------------------------------------
# Availability is a property of observation, not of value
# ---------------------------------------------------------------------------

def test_availability_flips_on_first_completed_bar_and_stays_available():
    t = WickTracker()
    assert t.calculate()[FEATURE] is None
    t.update(100.0, 101.0, 99.0, 100.8)
    assert t.calculate()[FEATURE] is not None
    # A subsequent degenerate bar does not make the feature unavailable again.
    t.update(100.0, 100.0, 100.0, 100.0)
    assert t.is_available is True
    assert t.calculate()[FEATURE] == 0.0


def test_tracker_reports_the_latest_completed_bar():
    t = WickTracker()
    t.update(99.0, 102.0, 98.5, 99.5)
    first = t.calculate()[FEATURE]
    t.update(101.0, 101.5, 98.0, 100.5)
    second = t.calculate()[FEATURE]
    assert first != second
    assert second == pytest.approx(compute_wick_imbalance(101.0, 101.5, 98.0, 100.5))


# ---------------------------------------------------------------------------
# Registry agreement
# ---------------------------------------------------------------------------

def test_registry_declares_a_null_policy_that_permits_unavailability():
    """The tracker may only return None because the contract allows it."""
    fdef = FEATURE_REGISTRY[FEATURE]
    assert fdef.null_policy == "allow", (
        "the tracker returns None while unavailable, which requires null_policy='allow'"
    )
    assert fdef.source_timeframe == "1m"
    assert fdef.update_anchor == "completed_1m_bar"
    assert fdef.warmup == 1, "one completed 1m bar is the declared warmup"


def test_unavailable_value_cannot_be_consumed_as_a_number():
    """A qualifying candidate cannot silently treat 'unavailable' as a magnitude.

    ``None`` refuses arithmetic; ``0.0`` would have compared as an ordinary balanced
    reading against any threshold a study applied.
    """
    val = WickTracker().calculate()[FEATURE]
    with pytest.raises(TypeError):
        _ = val > 0.5

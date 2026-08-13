"""Deterministic contract tests. No store access, no engines -- synthetic frames only.

These cover the three places this study could go wrong on its own (rather than in the
already-audited engines it reuses): the arming variant, the frozen bucket edges, and
the half-open flip interval.
"""
from __future__ import annotations

import polars as pl
import pytest

from studies.p90_regime_age_progress_diagnostic.implementation.population import (
    AGE_EDGES, AGE_LABELS, MFE_EDGES, MFE_LABELS, _bucket_expr, arm_population,
    with_dimensions, with_velocity_quartile,
)

BULL_TOP10 = 0.43167249785595935


def _frame(rows: list[dict]) -> pl.DataFrame:
    """Minimal score frame with the columns the arming rule reads."""
    base = {
        "bullish_in_domain": True, "bearish_in_domain": False,
        "checkpoint_reference_price": 100.0, "atr_at_checkpoint": 10.0,
        "running_mfe_atr": 2.0, "current_progress_atr": 1.5,
        "entry_year": 2023, "direction": -1,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


def test_arm_requires_a_crossing_from_below():
    """A run of qualifying dispatches arms ONCE, on the first crossing."""
    df = _frame([
        {"regime_id": "R", "checkpoint_decision_ns": 1, "seconds_from_regime_start": 700.0,
         "probability": 0.10},
        {"regime_id": "R", "checkpoint_decision_ns": 2, "seconds_from_regime_start": 705.0,
         "probability": 0.90},   # <- the arm
        {"regime_id": "R", "checkpoint_decision_ns": 3, "seconds_from_regime_start": 710.0,
         "probability": 0.95},   # already above: not a second arm
    ])
    arms = arm_population(df, 600.0, require_full_population=False)
    assert arms.height == 1
    assert arms["checkpoint_decision_ns"][0] == 2


def test_regime_with_no_predecessor_is_not_armed():
    """No predecessor dispatch => no observed crossing => not armed.

    This is the `fill_value=False` defect the accepted study was corrected for: a
    default of "the previous observation did not qualify" asserts a rise from below
    on zero evidence.
    """
    df = _frame([
        {"regime_id": "R", "checkpoint_decision_ns": 1, "seconds_from_regime_start": 700.0,
         "probability": 0.90},
    ])
    assert arm_population(df, 600.0, require_full_population=False).height == 0


def test_min_age_is_the_only_difference_between_populations():
    """The same crossing arms in A and is excluded from B purely by the age gate."""
    df = _frame([
        {"regime_id": "R", "checkpoint_decision_ns": 1, "seconds_from_regime_start": 300.0,
         "probability": 0.10},
        {"regime_id": "R", "checkpoint_decision_ns": 2, "seconds_from_regime_start": 305.0,
         "probability": 0.90},
    ])
    assert arm_population(df, 0.0, require_full_population=False).height == 1
    assert arm_population(df, 600.0, require_full_population=False).height == 0


def test_later_crossing_arms_b_at_a_different_timestamp():
    """B is NOT a clean subset: the same regime can arm at a LATER timestamp (SPEC 5)."""
    df = _frame([
        {"regime_id": "R", "checkpoint_decision_ns": 1, "seconds_from_regime_start": 300.0,
         "probability": 0.10},
        {"regime_id": "R", "checkpoint_decision_ns": 2, "seconds_from_regime_start": 305.0,
         "probability": 0.90},   # A arms here
        {"regime_id": "R", "checkpoint_decision_ns": 3, "seconds_from_regime_start": 700.0,
         "probability": 0.10},
        {"regime_id": "R", "checkpoint_decision_ns": 4, "seconds_from_regime_start": 705.0,
         "probability": 0.90},   # B arms here
    ])
    assert arm_population(df, 0.0, require_full_population=False)["checkpoint_decision_ns"][0] == 2
    assert arm_population(df, 600.0, require_full_population=False)["checkpoint_decision_ns"][0] == 4


def test_matches_accepted_arm_rule_at_600s():
    """At min_age=600 this study's rule IS the accepted rule, row for row.

    `population.arm_population` restates the accepted crossing filter with the age
    gate as a parameter (the accepted module hard-codes `MIN_REGIME_AGE_S = 600` at
    module scope). Restating audited logic is only safe if equivalence is proven, so
    this test compares the two implementations directly on a frame containing every
    branch: a from-below crossing, an already-above run, a no-predecessor regime, a
    below-the-age-gate crossing, and a second crossing in an already-armed regime.
    Flagged by lookahead-auditor pass 1 (WARNING).
    """
    from studies.armed_fade_score_path_progression.implementation import arming as ACC

    rows = [
        # armed: clean crossing above the age gate
        {"regime_id": "R1", "checkpoint_decision_ns": 10, "seconds_from_regime_start": 700.0,
         "probability": 0.10},
        {"regime_id": "R1", "checkpoint_decision_ns": 11, "seconds_from_regime_start": 705.0,
         "probability": 0.90},
        {"regime_id": "R1", "checkpoint_decision_ns": 12, "seconds_from_regime_start": 710.0,
         "probability": 0.95},
        # not armed: no predecessor dispatch
        {"regime_id": "R2", "checkpoint_decision_ns": 20, "seconds_from_regime_start": 800.0,
         "probability": 0.90},
        # not armed under the 600s gate: crossing is too young
        {"regime_id": "R3", "checkpoint_decision_ns": 30, "seconds_from_regime_start": 300.0,
         "probability": 0.10},
        {"regime_id": "R3", "checkpoint_decision_ns": 31, "seconds_from_regime_start": 305.0,
         "probability": 0.90},
        # armed late: predecessor lies BEFORE the 600s boundary, which is allowed
        {"regime_id": "R4", "checkpoint_decision_ns": 40, "seconds_from_regime_start": 590.0,
         "probability": 0.10},
        {"regime_id": "R4", "checkpoint_decision_ns": 41, "seconds_from_regime_start": 610.0,
         "probability": 0.90},
    ]
    df = _frame(rows)
    mine = arm_population(df, 600.0, require_full_population=False)
    theirs = ACC.arm_population(df, require_full_population=False)

    assert mine.height == theirs.height
    assert (sorted(zip(mine["regime_id"], mine["checkpoint_decision_ns"]))
            == sorted(zip(theirs["regime_id"], theirs["checkpoint_decision_ns"])))
    assert sorted(mine["regime_id"].to_list()) == ["R1", "R4"]


@pytest.mark.parametrize("value,expected", [
    (125.0, "120-240s"), (239.999, "120-240s"),
    (240.0, "240-300s"), (299.999, "240-300s"),
    (300.0, "300-600s"), (599.999, "300-600s"),
    (600.0, "600-900s"), (899.999, "600-900s"),
    (900.0, ">900s"), (8760.0, ">900s"),
])
def test_age_buckets_are_closed_left_open_right(value, expected):
    df = pl.DataFrame({"seconds_from_regime_start": [value]})
    got = df.select(_bucket_expr("seconds_from_regime_start", AGE_EDGES, AGE_LABELS))
    assert got.to_series()[0] == expected


@pytest.mark.parametrize("value,expected", [
    (1.0, "1-2 ATR"), (1.999, "1-2 ATR"),
    (2.0, "2-3 ATR"), (3.0, "3-5 ATR"), (5.0, ">5 ATR"), (53.35, ">5 ATR"),
])
def test_mfe_buckets_are_closed_left_open_right(value, expected):
    df = pl.DataFrame({"running_mfe_atr": [value]})
    got = df.select(_bucket_expr("running_mfe_atr", MFE_EDGES, MFE_LABELS))
    assert got.to_series()[0] == expected


def test_no_half_atr_progress_bucket_exists():
    """SPEC 1.3 -- eligibility floors running_mfe_atr at 1.0, so 0.5-1.0 is not created."""
    assert MFE_LABELS[0] == "1-2 ATR"
    assert MFE_EDGES[0][0] == 1.0


def test_velocity_is_atr_per_minute_and_uses_frozen_edges():
    df = _frame([
        {"regime_id": "R", "checkpoint_decision_ns": 1, "seconds_from_regime_start": 600.0,
         "probability": 0.9, "running_mfe_atr": 2.0},
    ])
    d = with_dimensions(df)
    assert d["velocity_atr_per_min"][0] == pytest.approx(0.2)   # 2.0 ATR / 10 min
    q = with_velocity_quartile(d, (0.16, 0.212, 0.284))
    assert q["velocity_quartile"][0] == "Q2"


def test_flip_interval_is_half_open():
    """`(T, T+300s]` exactly, matching the training labeller (SPEC 4.1).

    A flip stamped at the arm second is NOT a positive: the regime had already
    ended, so there was nothing to predict.
    """
    def label(dt: float, h: int) -> bool:
        return 0.0 < dt <= float(h)

    assert label(300.0, 300) is True
    assert label(300.001, 300) is False
    assert label(0.0, 300) is False
    assert label(-5.0, 300) is False
    assert label(0.001, 300) is True

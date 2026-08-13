"""Deterministic tests for arm detection and score-path shape classification."""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS
from studies.armed_fade_score_path_progression.implementation.arming import (
    MONOTONIC_PROGRESS,
    OSCILLATING,
    RETREAT_NO_RECOVERY,
    RETREAT_REEXPANSION,
    TOP10_ONLY,
    PostArmScores,
    arm_population,
    classify_shape,
    consecutive_run_at_arm,
    level_reaches,
    reexpansion_index,
    with_level_flags,
)

NS = 1_000_000_000
BULL_10, _ = THRESHOLDS["top_10"]
BULL_5, _ = THRESHOLDS["top_5"]
BULL_2_5, _ = THRESHOLDS["top_2_5"]
BULL_1, _ = THRESHOLDS["top_1"]


def make_scored(rows):
    """rows: (regime_id, second_offset, probability, age_s)."""
    return pl.DataFrame(
        {
            "regime_id": [r[0] for r in rows],
            "checkpoint_decision_ns": [int(r[1] * NS) for r in rows],
            "probability": [float(r[2]) for r in rows],
            "seconds_from_regime_start": [float(r[3]) for r in rows],
            "bullish_in_domain": [True] * len(rows),
            "bearish_in_domain": [False] * len(rows),
        }
    ).sort("checkpoint_decision_ns")


def test_arm_requires_a_crossing_from_below():
    # R1 crosses from below after 600s -> armed.
    # R2 is already above at its first post-600s dispatch -> not armed. This is
    # the entire 8,988 vs 8,953 delta against the predecessor's rule.
    scored = make_scored([
        ("R1", 0, 0.10, 595),
        ("R1", 5, BULL_10 + 0.01, 605),
        ("R2", 0, BULL_10 + 0.01, 595),
        ("R2", 5, BULL_10 + 0.02, 605),
    ])
    armed = arm_population(scored, require_full_population=False)
    assert armed["regime_id"].to_list() == ["R1"]


def test_arm_rejects_crossings_before_the_age_gate():
    scored = make_scored([
        ("R1", 0, 0.10, 100),
        ("R1", 5, BULL_10 + 0.01, 110),   # crossing, but too young
        ("R1", 10, 0.10, 115),
        ("R1", 15, BULL_10 + 0.01, 605),  # the real arm
    ])
    armed = arm_population(scored, require_full_population=False)
    assert armed.height == 1
    assert armed["checkpoint_decision_ns"].item() == 15 * NS


def test_only_one_arm_per_regime():
    scored = make_scored([
        ("R1", 0, 0.10, 595),
        ("R1", 5, BULL_10 + 0.01, 605),
        ("R1", 10, 0.10, 610),
        ("R1", 15, BULL_10 + 0.01, 615),  # a second crossing, not a second arm
    ])
    assert arm_population(scored, require_full_population=False).height == 1


def test_age_gate_is_strictly_greater_than_600():
    scored = make_scored([
        ("R1", 0, 0.10, 590),
        ("R1", 5, BULL_10 + 0.01, 600.0),
    ])
    assert arm_population(scored, require_full_population=False).height == 0


def test_first_ever_dispatch_already_above_is_not_an_arm():
    # No predecessor exists, so no crossing was ever observed. Accepting this
    # would assert a rise from below on zero evidence -- the defect that
    # `shift(1, fill_value=False)` silently introduced, found by
    # lookahead-auditor pass 1.
    scored = make_scored([
        ("R1", 0, BULL_10 + 0.01, 605),
        ("R1", 5, BULL_10 + 0.02, 610),
    ])
    assert arm_population(scored, require_full_population=False).height == 0


def test_unscored_dispatch_is_not_a_predecessor_observation():
    # The model declined to score at t=5. The last thing a live trader saw was
    # the sub-threshold score at t=0, so the t=10 crossing IS a crossing from
    # below. Letting the null stand in as the predecessor would reject it.
    rows = [("R1", 0, 0.10, 595), ("R1", 5, None, 600), ("R1", 10, BULL_10 + 0.01, 605)]
    scored = pl.DataFrame({
        "regime_id": [r[0] for r in rows],
        "checkpoint_decision_ns": [int(r[1] * NS) for r in rows],
        "probability": [r[2] for r in rows],
        "seconds_from_regime_start": [float(r[3]) for r in rows],
        "bullish_in_domain": [True] * len(rows),
        "bearish_in_domain": [False] * len(rows),
    }).sort("checkpoint_decision_ns")

    with_nulls = arm_population(scored, require_full_population=False)
    assert with_nulls.height == 0, "null predecessor wrongly blocks the crossing"

    observations = scored.filter(pl.col("probability").is_not_null())
    armed = arm_population(observations, require_full_population=False)
    assert armed.height == 1
    assert armed["checkpoint_decision_ns"].item() == 10 * NS


def test_null_probability_would_nan_poison_the_running_peak():
    # Documents why the filter is numerical as well as causal: a single null
    # renders as NaN and propagates through every running maximum downstream.
    assert np.isnan(np.maximum.accumulate(np.array([0.5, np.nan, 0.6]))[-1])


def test_arming_refuses_a_partial_year_population():
    # A year filter applied before arming drops the predecessor dispatch at each
    # year boundary and manufactures phantom crossings.
    scored = make_scored(
        [("R1", 0, 0.10, 595), ("R1", 5, BULL_10 + 0.01, 605)]
    ).with_columns(entry_year=pl.lit(2021))
    with pytest.raises(ValueError, match="full 2021-2025"):
        arm_population(scored)


def make_obs(probs):
    n = len(probs)
    p = np.asarray(probs, dtype=float)
    q = {
        "top_10": p >= BULL_10,
        "top_5": p >= BULL_5,
        "top_2_5": p >= BULL_2_5,
        "top_1": p >= BULL_1,
    }
    band = sum(v.astype(np.int8) for v in q.values())
    return PostArmScores(
        ns=np.arange(n, dtype=np.int64) * 5 * NS,
        probability=p,
        price=np.full(n, 100.0),
        atr=np.full(n, 1.0),
        progress_atr=np.full(n, 1.0),
        band=band,
        qualifies=q,
    )


def test_multi_level_jump_stamps_one_timestamp():
    # One dispatch jumps Top-10 straight past Top-1: every level shares its index,
    # so the elapsed interval between levels is exactly 0, never negative.
    obs = make_obs([BULL_10 + 0.001, BULL_1 + 0.01])
    reaches = level_reaches(obs)
    assert reaches["top_5"] == reaches["top_2_5"] == reaches["top_1"] == 1
    assert obs.ns[reaches["top_1"]] == obs.ns[reaches["top_5"]]


@pytest.mark.parametrize(
    "probs, expected",
    [
        # Never reaches Top-5 -> depth class wins outright.
        ([BULL_10 + 0.001, BULL_10 + 0.002, BULL_10 + 0.001], TOP10_ONLY),
        # Rises through Top-5 without a >= 0.05 retreat.
        ([BULL_10 + 0.001, BULL_5 + 0.01, BULL_5 + 0.03], MONOTONIC_PROGRESS),
        # Peaks, drops 0.06, never sets a new high.
        ([BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 - 0.01, BULL_5 - 0.02],
         RETREAT_NO_RECOVERY),
        # Peaks, drops 0.06, then exceeds the prior peak -> one cycle.
        ([BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 - 0.01, BULL_5 + 0.10],
         RETREAT_REEXPANSION),
        # Two full retreat -> new-high cycles.
        ([BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 - 0.01, BULL_5 + 0.10,
          BULL_5 + 0.02, BULL_5 + 0.20], OSCILLATING),
    ],
)
def test_every_shape_class_is_reachable(probs, expected):
    obs = make_obs(probs)
    got = classify_shape(obs, len(probs) - 1, 0.05)
    assert got["shape_class"] == expected


def test_shape_respects_the_terminal_bound():
    # The re-expansion happens after the terminal event, so it must not be seen.
    probs = [BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 - 0.01, BULL_5 + 0.10]
    obs = make_obs(probs)
    assert classify_shape(obs, 2, 0.05)["shape_class"] == RETREAT_NO_RECOVERY
    assert classify_shape(obs, 3, 0.05)["shape_class"] == RETREAT_REEXPANSION


def test_reexpansion_index_points_at_the_new_high():
    obs = make_obs([BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 - 0.01, BULL_5 + 0.10])
    assert reexpansion_index(obs, 3, 0.05) == 3
    assert reexpansion_index(obs, 2, 0.05) == -1


def test_retreat_definitions_are_not_interchangeable():
    # A 0.04 dip is a retreat at r = 0.03 and not at r = 0.05. Reporting both is
    # the point: the class is sensitive to a parameter that was never tuned.
    obs = make_obs([BULL_10 + 0.001, BULL_5 + 0.05, BULL_5 + 0.01, BULL_5 + 0.02])
    assert classify_shape(obs, 3, 0.03)["had_retreat"] is True
    assert classify_shape(obs, 3, 0.05)["had_retreat"] is False


def test_consecutive_run_counts_true_dispatches():
    obs = make_obs([BULL_10 + 0.001, BULL_10 + 0.002, 0.10, BULL_10 + 0.001])
    assert consecutive_run_at_arm(obs, "top_10", 3) == 2


def test_band_index_is_monotone_in_probability():
    obs = make_obs([0.10, BULL_10 + 0.001, BULL_5 + 0.001, BULL_2_5 + 0.001, BULL_1 + 0.001])
    assert obs.band.tolist() == [0, 1, 2, 3, 4]


def test_with_level_flags_uses_direction_specific_thresholds():
    bull_10, bear_10 = THRESHOLDS["top_10"]
    # A probability between the two contracts qualifies for one model only.
    mid = (bull_10 + bear_10) / 2
    df = pl.DataFrame({
        "probability": [mid, mid],
        "bullish_in_domain": [True, False],
        "bearish_in_domain": [False, True],
    })
    flagged = with_level_flags(df)
    assert flagged["q_top_10"].to_list() == [mid >= bull_10, mid >= bear_10]

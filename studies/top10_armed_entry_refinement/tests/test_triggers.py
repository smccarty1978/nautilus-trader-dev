"""Deterministic tests for the trigger primitives, on synthetic score frames."""
from __future__ import annotations

import polars as pl
import pytest

from studies.top10_armed_entry_refinement.implementation.candidates import (
    first_firings, with_reexpansion,
)
from studies.top10_armed_entry_refinement.implementation.paths import (
    INTERP_L1, INTERP_L2, LEVELS,
)

NS = 1_000_000_000
B10, B5 = LEVELS["top_10"][0], LEVELS["top_5"][0]


def frame(scores):
    n = len(scores)
    d = pl.DataFrame({
        "regime_id": ["R"] * n,
        "checkpoint_decision_ns": [i * 5 * NS for i in range(n)],
        "score": [float(s) for s in scores],
        "bullish_in_domain": [True] * n,
        "bearish_in_domain": [False] * n,
        "direction": [-1] * n,
        "side": ["SHORT"] * n,
        "entry_year": [2023] * n,
        "checkpoint_reference_price": [100.0] * n,
        "atr_at_checkpoint": [1.0] * n,
        "arm_ns": [0] * n,
        "arm_price": [100.0] * n,
        "arm_atr": [1.0] * n,
        "arm_score": [float(scores[0])] * n,
        "arm_outcome": ["SUCCESS"] * n,
        "arm_stop_ns": [None] * n,
    }).with_columns(
        obs_index=pl.int_range(pl.len()),
        score_running_max=pl.col("score").cum_max(),
        delta_from_arm=(pl.col("score") - pl.col("arm_score")),
    )
    # Streak counted the way paths.py counts it: qualifying observations within
    # a run-group, never row positions.
    grp = (~(pl.col("score") >= B10)).cast(pl.Int32).cum_sum()
    return d.with_columns(grp=grp).with_columns(
        consec_top_10=(pl.col("score") >= B10).cast(pl.Int32).cum_sum().over("grp"),
    )


def test_consecutive_streak_resets_and_is_not_off_by_one():
    # qualify, qualify, MISS, qualify -> the post-miss streak must read 1, not 2.
    f = frame([B10 + 0.01, B10 + 0.02, B10 - 0.05, B10 + 0.01])
    assert f["consec_top_10"].to_list() == [1, 2, 0, 1]


def test_persistence_trigger_fires_on_the_second_qualifying_dispatch():
    f = frame([B10 + 0.01, B10 + 0.02, B10 + 0.03])
    e = first_firings(f, "B1", pl.col("consec_top_10") >= 2)
    assert e.height == 1
    assert e["entry_ns"].item() == 5 * NS
    assert e["seconds_arm_to_entry"].item() == pytest.approx(5.0)


def test_reexpansion_cannot_fire_on_the_bar_that_sets_the_peak():
    # rise to a peak, retreat 0.06, then exceed the prior peak.
    f = with_reexpansion(frame([B10 + 0.01, B10 + 0.10, B10 + 0.04, B10 + 0.12]), 0.05)
    flags = f["reexpanded_0_05"].to_list()
    assert flags[1] is False, "the peak bar itself is not a re-expansion"
    assert flags[2] is False, "the retreat bar is not a re-expansion"
    assert flags[3] is True


def test_reexpansion_requires_a_retreat_first():
    # monotone rise: never a re-expansion, however far it runs.
    f = with_reexpansion(frame([B10 + 0.01, B10 + 0.05, B10 + 0.20]), 0.05)
    assert not any(f["reexpanded_0_05"].to_list())


def test_interpolated_levels_sit_strictly_between_the_frozen_contracts():
    for i in (0, 1):
        assert LEVELS["top_10"][i] < INTERP_L1[i] < INTERP_L2[i] < LEVELS["top_5"][i]


def test_trigger_takes_the_first_qualifying_dispatch_only():
    f = frame([B10 + 0.01, B5 + 0.01, B5 + 0.05])
    e = first_firings(f, "A", pl.col("score") >= B5)
    assert e.height == 1
    assert e["entry_ns"].item() == 5 * NS


def test_no_trigger_yields_no_entry():
    f = frame([B10 + 0.01, B10 + 0.02])
    assert first_firings(f, "X", pl.col("score") >= B5).height == 0

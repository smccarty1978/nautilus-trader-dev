"""Hand-computed tests for the corrected primary label, run BEFORE the full
6-year pipeline (per the project's pre-execution-audit-gate standing rule).

The single most important case: a row where Policy A's hypothetical trade
hit the 1.25xATR pre-alignment stop (hit_pre_alignment_stop=True) but the
regime's TRUE confirmed flip still lands within 300s. The old (buggy)
age-gate study computed bearish_flip_within_300s = aligned, which is False
in this exact case (Policy A's simulation exits early on the stop-touch
and never gets to report alignment). The corrected label must be True.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from phase0_prepare_data import build_labels  # noqa: E402

NS = 1_000_000_000


def base_row(**overrides) -> dict:
    row = {
        "confirm_flip_ns": 1_700_000_000 * NS,
        "observation_time": 1_700_000_000 * NS,
        "hit_pre_alignment_stop": False,
        "atr_at_entry": 10.0,
        "post_flip_mfe_points_300s": 5.0,
        "post_flip_mfe_points_600s": 15.0,
    }
    row.update(overrides)
    return row


def make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_stop_hit_but_true_flip_within_300s_is_positive():
    """The core regression case: stopped out AND flips within 300s ->
    primary label must be True (this is exactly what the old aligned-based
    label got wrong)."""
    df = make_df([base_row(
        confirm_flip_ns=1_700_000_250 * NS,   # flip 250s after observation
        observation_time=1_700_000_000 * NS,
        hit_pre_alignment_stop=True,          # Policy A stopped out first
    )])
    out = build_labels(df)
    assert bool(out.loc[0, "bearish_regime_flip_within_300s"]) is True
    assert bool(out.loc[0, "no_flip_before_timeout"]) is False


def test_no_flip_within_300s_is_negative():
    df = make_df([base_row(
        confirm_flip_ns=1_700_000_450 * NS,   # flip 450s after observation
        observation_time=1_700_000_000 * NS,
        hit_pre_alignment_stop=False,
    )])
    out = build_labels(df)
    assert bool(out.loc[0, "bearish_regime_flip_within_300s"]) is False
    assert bool(out.loc[0, "no_flip_before_timeout"]) is True
    assert bool(out.loc[0, "bearish_flip_within_600s"]) is True


def test_exact_300s_boundary_is_inclusive():
    df = make_df([base_row(
        confirm_flip_ns=1_700_000_300 * NS,
        observation_time=1_700_000_000 * NS,
    )])
    out = build_labels(df)
    assert bool(out.loc[0, "bearish_regime_flip_within_300s"]) is True


def test_time_to_bearish_flip_s_arithmetic():
    df = make_df([base_row(
        confirm_flip_ns=1_700_000_123 * NS,
        observation_time=1_700_000_000 * NS,
    )])
    out = build_labels(df)
    assert out.loc[0, "time_to_bearish_flip_s"] == 123.0


def test_followthrough_requires_flip_and_1atr_mfe():
    flipped_strong = base_row(
        confirm_flip_ns=1_700_000_100 * NS, observation_time=1_700_000_000 * NS,
        post_flip_mfe_points_300s=15.0, atr_at_entry=10.0)  # 1.5 ATR >= 1.0
    flipped_weak = base_row(
        confirm_flip_ns=1_700_000_100 * NS, observation_time=1_700_000_000 * NS,
        post_flip_mfe_points_300s=5.0, atr_at_entry=10.0)   # 0.5 ATR < 1.0
    no_flip = base_row(
        confirm_flip_ns=1_700_000_450 * NS, observation_time=1_700_000_000 * NS,
        post_flip_mfe_points_300s=50.0, atr_at_entry=10.0)  # irrelevant, no flip
    out = build_labels(make_df([flipped_strong, flipped_weak, no_flip]))
    assert bool(out.loc[0, "bearish_flip_within_300s_and_followthrough_1A"]) is True
    assert float(out.loc[1, "bearish_flip_within_300s_and_followthrough_1A"]) == 0.0
    assert float(out.loc[2, "bearish_flip_within_300s_and_followthrough_1A"]) == 0.0


def test_censored_post_flip_mfe_stays_nan_not_false():
    """A flip occurred but post-flip MFE is unavailable (e.g. raw data
    censored near year-end) -- followthrough must stay NaN, never silently
    become False (NaN >= 1.0 == False is the bug this guards against)."""
    df = make_df([base_row(
        confirm_flip_ns=1_700_000_100 * NS, observation_time=1_700_000_000 * NS,
        post_flip_mfe_points_300s=np.nan,
    )])
    out = build_labels(df)
    assert pd.isna(out.loc[0, "bearish_flip_within_300s_and_followthrough_1A"])


def test_adverse_move_label_reuses_hit_pre_alignment_stop_directly():
    df = make_df([
        base_row(hit_pre_alignment_stop=True),
        base_row(hit_pre_alignment_stop=False),
    ])
    out = build_labels(df)
    assert bool(out.loc[0, "adverse_move_1p25A_before_bearish_flip"]) is True
    assert bool(out.loc[1, "adverse_move_1p25A_before_bearish_flip"]) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

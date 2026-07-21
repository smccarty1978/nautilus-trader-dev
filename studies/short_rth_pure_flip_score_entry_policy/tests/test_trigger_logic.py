"""Hand-computed tests for trigger_logic.py, run BEFORE the full grid
(per project pre-execution-audit standing rule)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from trigger_logic import (add_persistence_flag, add_prev_score,  # noqa: E402
                          add_score_lookback, build_trigger_flags)

NS = 1_000_000_000
REGIME = 1_700_000_000 * NS


def cp(t_offset_s: float, score: float, regime=REGIME) -> dict:
    return {"regime_start_ns": regime, "observation_time": regime + int(t_offset_s * NS), "score": score}


def test_prev_score_is_positional_not_time_based():
    """A regime with a gap: checkpoints at 0s, 5s, 20s (gap). prev_score at
    20s must be the 5s row's score (the actual predecessor), not NaN just
    because the gap isn't exactly 5s."""
    df = pd.DataFrame([cp(0, 0.1), cp(5, 0.2), cp(20, 0.3)])
    out = add_prev_score(df, "score")
    row_20 = out[out.observation_time == REGIME + 20 * NS].iloc[0]
    assert row_20["prev_score"] == 0.2
    row_0 = out[out.observation_time == REGIME].iloc[0]
    assert pd.isna(row_0["prev_score"])


def test_score_lookback_exact_match_only():
    """30s lookback must return NaN if no checkpoint exists at exactly
    -30s, even if one exists nearby (e.g. -25s) -- never silently
    approximate."""
    df = pd.DataFrame([cp(0, 0.1), cp(25, 0.2), cp(30, 0.3), cp(60, 0.4)])
    out = add_score_lookback(df, "score", 30, "look30")
    row_60 = out[out.observation_time == REGIME + 60 * NS].iloc[0]
    assert row_60["look30"] == 0.3  # exact match at 30s
    row_30 = out[out.observation_time == REGIME + 30 * NS].iloc[0]
    assert row_30["look30"] == 0.1  # 30s row looks back 30s to the 0s row, which exists
    row_25 = out[out.observation_time == REGIME + 25 * NS].iloc[0]
    assert pd.isna(row_25["look30"])  # would need -5s, doesn't exist


def test_persistence_requires_all_checkpoints_above_and_min_count():
    """Score above threshold at 0s, 15s, 30s (all >= 0.5) -> persistent at
    30s over a 30s window. A dip below threshold at 25s must break it."""
    df_ok = pd.DataFrame([cp(0, 0.6), cp(15, 0.7), cp(30, 0.55)])
    out_ok = add_persistence_flag(df_ok, "score", 0.5, 30, "persist30", min_checkpoints=2)
    assert bool(out_ok.iloc[-1]["persist30"]) is True

    df_dip = pd.DataFrame([cp(0, 0.6), cp(15, 0.3), cp(30, 0.55)])
    out_dip = add_persistence_flag(df_dip, "score", 0.5, 30, "persist30", min_checkpoints=2)
    assert bool(out_dip.iloc[-1]["persist30"]) is False


def test_persistence_single_isolated_checkpoint_does_not_qualify():
    """A single checkpoint far from any neighbor (data gap) must NOT count
    as persistent, even though its own score clears the threshold --
    min_checkpoints guards against this."""
    df = pd.DataFrame([cp(0, 0.9), cp(1000, 0.9)])  # huge gap
    out = add_persistence_flag(df, "score", 0.5, 30, "persist30", min_checkpoints=2)
    last = out.iloc[-1]
    assert bool(last["persist30"]) is False


def test_build_trigger_flags_family_a_matches_simple_threshold():
    df = pd.DataFrame([cp(0, 0.3), cp(5, 0.6), cp(10, 0.9)])
    cutoffs = {"top20": 0.5, "top15": 0.6, "top10": 0.7, "top5": 0.8, "top2.5": 0.85}
    out = build_trigger_flags(df, "score", cutoffs)
    assert list(out["trig_A_top20"]) == [False, True, True]
    assert list(out["trig_A_top5"]) == [False, False, True]


def test_build_trigger_flags_family_b_only_fires_on_fresh_crossing():
    """Regime starts already above threshold (0.9) -- Family B must NOT
    fire on the first row (no prior to cross from below), only on a later
    row that genuinely crosses up from below."""
    df = pd.DataFrame([cp(0, 0.9), cp(5, 0.85), cp(10, 0.3), cp(15, 0.9)])
    cutoffs = {"top20": 0.5, "top15": 0.6, "top10": 0.7, "top5": 0.8, "top2.5": 0.85}
    out = build_trigger_flags(df, "score", cutoffs)
    assert list(out["trig_B_top20"]) == [False, False, False, True]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

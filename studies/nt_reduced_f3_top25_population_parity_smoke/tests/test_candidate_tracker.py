"""Hand-computed tests for candidate_tracker.py's established-regime filter,
BEFORE wiring into the NT Strategy (per project pre-execution-test discipline).

IMPORTANT semantics (corrected via real-data cross-validation against
`prepared_2025.parquet`'s stored `running_mfe_atr`/`running_mae_atr` -- an
earlier version of this file assumed MFE/MAE were measured for the SHORT
entry's own direction; they are not): `running_mfe_atr`/`running_mae_atr`/
`current_pnl` measure the ESTABLISHED (prevailing, direction=+1, bullish)
regime's OWN favorable/adverse excursion -- a gauge of how extended the
trend being faded is, unrelated to the eventual short entry's own P&L
direction. MFE grows when price makes a NEW HIGH above flip_close; MAE grows
when price pulls back BELOW flip_close.
"""
from __future__ import annotations

import sys
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1] / "implementation"
if str(IMPL) not in sys.path:
    sys.path.insert(0, str(IMPL))

import pytest  # noqa: E402
from candidate_tracker import CandidateTracker, RegimeCandidateState, is_rth_minute_of_day  # noqa: E402

NS = 1_000_000_000


def make_bars():
    """flip at ts=0, flip_close=100.0, atr=1.0.
    t=5: high=105 -> mfe=5.0, first extreme (count=1, last_extreme_ts=5s)
    t=6..129: flat at high=105
    t=130: high=106 -> mfe=6.0, second extreme (gap=125s>=120s, count=2)
    Checkpoint grid: T=5,10,...,130,... (checkpoint_index = T/5 - 1)
    """
    bars = {}
    for t in range(1, 201):
        bars[t] = {"high": 100.0, "low": 100.0, "close": 100.0}
    bars[5] = {"high": 105.0, "low": 100.0, "close": 105.0}
    for t in range(6, 130):
        bars[t] = {"high": 105.0, "low": 100.0, "close": 105.0}
    bars[130] = {"high": 106.0, "low": 100.0, "close": 106.0}
    for t in range(131, 201):
        bars[t] = {"high": 106.0, "low": 100.0, "close": 106.0}
    return bars


def run_tracker(bars, minute_of_day=600):  # 600 = 10:00, well inside RTH
    emitted = []
    tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 201):
        b = bars[t]
        tracker.on_1s_bar(ts_ns=t * NS, high=b["high"], low=b["low"], close=b["close"],
                          minute_of_day=minute_of_day)
    return emitted, tracker


def test_progress_gate_blocks_before_second_extreme():
    emitted, _ = run_tracker(make_bars())
    by_idx = {e["checkpoint_index"]: e for e in emitted}
    cp24 = by_idx[24]  # T=125s
    assert cp24["observation_time_ns"] == 125 * NS
    assert cp24["regime_age_s"] == pytest.approx(125.0)
    assert cp24["running_mfe_atr"] == pytest.approx(5.0)
    assert cp24["new_progress_windows"] == 1
    assert cp24["established_regime_gate"] is False
    assert cp24["suppression_reason"] == "established_regime_gate_fail"


def test_established_true_once_all_four_gates_pass():
    """Checkpoint evaluation uses state through the LAST BAR STRICTLY BEFORE
    T (matching build_weakness_atlas.py:96-112's "last completed bar has
    ts_event strictly before cp_ts" rule, confirmed via real-data cross-
    validation) -- so the t=130 bar that sets the second MFE extreme is not
    reflected until the NEXT checkpoint, T=135 (index 26), not T=130 (index 25)."""
    emitted, _ = run_tracker(make_bars())
    by_idx = {e["checkpoint_index"]: e for e in emitted}
    cp25 = by_idx[25]  # T=130s -- still sees only the FIRST extreme (bar 130 not yet folded in)
    assert cp25["running_mfe_atr"] == pytest.approx(5.0)
    assert cp25["new_progress_windows"] == 1
    assert cp25["established_regime_gate"] is False

    cp26 = by_idx[26]  # T=135s
    assert cp26["observation_time_ns"] == 135 * NS
    assert cp26["regime_age_s"] == pytest.approx(135.0)
    assert cp26["running_mfe_atr"] == pytest.approx(6.0)
    assert cp26["running_mae_atr"] == pytest.approx(0.0)
    assert cp26["new_progress_windows"] == 2
    assert cp26["current_pnl_atr"] == pytest.approx(6.0)  # (106-100)/1.0
    assert cp26["retained_mfe_ratio"] == pytest.approx(1.0)
    assert cp26["established_regime_gate"] is True
    assert cp26["suppression_reason"] is None


def test_age_gate_blocks_early_checkpoints():
    emitted, _ = run_tracker(make_bars())
    by_idx = {e["checkpoint_index"]: e for e in emitted}
    cp0 = by_idx[0]  # T=5s
    assert cp0["regime_age_s"] == pytest.approx(5.0)
    assert cp0["established_regime_gate"] is False


def test_mfe_gate_blocks_when_excursion_too_small():
    bars = {t: {"high": 100.1, "low": 100.0, "close": 100.1} for t in range(1, 201)}
    emitted, _ = run_tracker(bars)
    by_idx = {e["checkpoint_index"]: e for e in emitted}
    cp25 = by_idx[25]
    assert cp25["running_mfe_atr"] == pytest.approx(0.1)
    assert cp25["established_regime_gate"] is False


def test_retained_ratio_gate_blocks_after_giveback():
    bars = make_bars()
    # After the second extreme at t=130 (high=106), let price fully retrace to
    # flip_close (100) by t=135 -- mfe stays 6.0 (running max), but current
    # pnl at a later checkpoint should collapse toward 0, failing retained>=0.5.
    for t in range(131, 145):
        bars[t] = {"high": 106.0, "low": 100.0, "close": 100.0}
    emitted, _ = run_tracker(bars)
    by_idx = {e["checkpoint_index"]: e for e in emitted}
    cp27 = by_idx[27]  # T=140s
    assert cp27["running_mfe_atr"] == pytest.approx(6.0)  # running max unaffected by retrace
    assert cp27["current_pnl_atr"] == pytest.approx(0.0)  # (100-100)/1.0
    assert cp27["retained_mfe_ratio"] == pytest.approx(0.0)
    assert cp27["established_regime_gate"] is False
    assert cp27["suppression_reason"] == "established_regime_gate_fail"


def test_regime_close_stops_further_checkpoints():
    emitted = []
    tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 51):
        tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)
    n_before_close = len(emitted)
    assert n_before_close == 10  # T=5,10,...,50
    # opposing flip closes the regime
    tracker.on_regime_flip(ts_ns=51 * NS, new_direction=-1, flip_close=105.0, atr_val=1.0)
    for t in range(52, 100):
        tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=105.0, close=105.0, minute_of_day=600)
    assert len(emitted) == n_before_close  # no new candidates after close


def test_only_bullish_regime_produces_candidates():
    emitted = []
    tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=-1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 200):
        tracker.on_1s_bar(ts_ns=t * NS, high=105.0, low=100.0, close=105.0, minute_of_day=600)
    assert emitted == []


def test_timeout_stops_checkpoint_generation_at_1800s():
    emitted = []
    tracker = CandidateTracker(on_candidate=emitted.append, is_rth_fn=is_rth_minute_of_day)
    tracker.on_regime_flip(ts_ns=0, new_direction=1, flip_close=100.0, atr_val=1.0)
    for t in range(1, 1900):
        tracker.on_1s_bar(ts_ns=t * NS, high=110.0, low=100.0, close=110.0, minute_of_day=600)
    last_ts = max(e["observation_time_ns"] for e in emitted)
    assert last_ts < 1800 * NS
    assert last_ts == 1795 * NS  # last grid point strictly before timeout


def test_checkpoint_index_matches_offline_grid_convention():
    """checkpoint_index = round((T - flip_ts)/5s) - 1, confirmed against the
    real prepared_2025.parquet population this session (100% of rows exactly
    on the 5s grid)."""
    emitted, _ = run_tracker(make_bars())
    for e in emitted:
        expected_idx = round(e["observation_time_ns"] / (5 * NS)) - 1
        assert e["checkpoint_index"] == expected_idx


def test_atr_val_frozen_at_flip_and_exposed_on_every_checkpoint():
    """Regression guard for a real bug found during reconciliation:
    strategy.py's _on_candidate was independently re-reading a live,
    continuously-updating self._engine.atr per-checkpoint (for the logged
    atr_at_entry field, the feature vector, AND stop sizing) instead of the
    frozen atr_val this tracker uses internally for running_mfe_atr/
    running_mae_atr/current_pnl_atr. Back-calculating the offline
    reference's true atr from mfe_points/running_mfe_atr confirmed it is a
    single constant per regime (entry_surface.py enforces this upstream
    with a hard nunique()==1 assertion) -- so every emitted candidate must
    expose that same frozen value, unchanged across the whole regime."""
    emitted, _ = run_tracker(make_bars())
    assert emitted, "expected at least one emitted candidate"
    atr_vals = {e["atr_val"] for e in emitted}
    assert atr_vals == {1.0}, f"atr_val must be frozen at the flip-time value for every checkpoint, got {atr_vals}"


def test_is_rth_minute_boundaries():
    assert is_rth_minute_of_day(8 * 60 + 30) is True
    assert is_rth_minute_of_day(8 * 60 + 29) is False
    assert is_rth_minute_of_day(15 * 60 - 1) is True
    assert is_rth_minute_of_day(15 * 60) is False

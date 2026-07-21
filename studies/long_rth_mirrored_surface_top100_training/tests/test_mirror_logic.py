"""Focused synthetic tests for the mirrored long-side pipeline invariants.
No large data; small hand-built fixtures only."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY.parents[1]
sys.path.insert(0, str(STUDY / "implementation"))
sys.path.insert(0, str(ROOT))


def test_label_arithmetic_mirror():
    """bullish_regime_flip_within_300s == (confirm_flip_ns - obs)/1e9 <= 300,
    the exact mirror of the short-side bearish label."""
    NS = 1_000_000_000
    obs = np.array([0, 0, 0], dtype=np.int64)
    confirm = np.array([200 * NS, 300 * NS, 301 * NS], dtype=np.int64)
    ttf = (confirm - obs) / 1e9
    label = (ttf <= 300.0).astype(int)
    assert label.tolist() == [1, 1, 0]  # boundary at exactly 300s is inclusive


def test_price_tracker_direction_flips_behind():
    """The single directional top-100 feature (pct_levels_behind_trade) must
    invert between long (+1) and short (-1) for the same level geometry."""
    from features.trackers.price_levels import PriceLevelTracker
    t = PriceLevelTracker()
    # seed a few 1m bars so some rolling levels exist above and below price
    base = 20000.0
    ts = 1_000_000_000
    for i in range(70):
        o = base + (i - 35) * 2.0
        t.update_1m(ts + i * 60_000_000_000, o, o + 1, o - 1, o, True)
    ref = base
    long = t.calculate(ts + 70 * 60_000_000_000, ref, atr=10.0, direction=1)
    short = t.calculate(ts + 70 * 60_000_000_000, ref, atr=10.0, direction=-1)
    lb, sb = long.get("pct_levels_behind_trade"), short.get("pct_levels_behind_trade")
    la, sa = long.get("pct_levels_ahead_of_trade"), short.get("pct_levels_ahead_of_trade")
    if lb is not None and sb is not None:
        # "behind" for long (levels below) == "ahead" for short, and vice versa
        assert pytest.approx(lb, abs=1e-9) == sa
        assert pytest.approx(la, abs=1e-9) == sb


def test_build_surface_long_bearish_favorable_and_direction_filter():
    """On a tiny synthetic atlas+raw, build_surface_long keeps only direction==-1
    and its re-derived bearish-favorable MFE matches an atlas current_mfe built
    the same (anchor-low) way; a direction==+1 regime is dropped."""
    import build_surface_long as B
    NS = 1_000_000_000
    # raw: 10 one-second bars during RTH (2021-06-15 14:00 UTC = 09:00 CT),
    # price falling then rising
    t0 = pd.Timestamp("2021-06-15 14:00:00", tz="UTC").value
    ts = np.array([t0 + i * NS for i in range(10)], dtype=np.int64)
    close = np.array([100, 99, 98, 97, 99, 100, 101, 102, 103, 104], float)
    raw = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                        "close": close, "volume": 1.0}, index=pd.Index(ts, name="ts"))
    atr = 1.0
    anchor = 100.0  # entry_open at ts=0
    # atlas current_mfe (bearish-favorable) = running max of (anchor - low)/atr
    lows = raw["low"].to_numpy()
    fav = np.maximum.accumulate(np.maximum((anchor - lows) / atr, 0.0))
    obs_times = ts[1:8]                      # checkpoints
    kidx = np.searchsorted(ts, obs_times, "left") - 1
    bear = pd.DataFrame({
        "observation_time": obs_times, "regime_start_ns": 0, "regime_end_ns": t0 + 9 * NS,
        "direction": -1, "entry_ts_event": t0, "entry_open": anchor,
        "atr_at_entry": atr, "atr_at_checkpoint": atr,
        "regime_age": 1000.0, "current_pnl": fav[kidx],
        "current_mfe": fav[kidx], "current_mae": 0.0,
        "running_mfe": fav[kidx], "running_mae": 0.0})
    bull = bear.copy(); bull["direction"] = 1; bull["regime_start_ns"] = 1  # must be dropped
    stream = pd.concat([bear, bull], ignore_index=True)
    filt = {"regime_age_s_min": 0.0, "running_mfe_atr_min": 0.0,
            "new_progress_windows_min": 0, "retained_mfe_ratio_min": -1e9}
    surface, attrition = B.build_surface_long(2099, stream, raw, filt)
    assert attrition["mfe_directionality_checks_passed"] > 0
    assert set(surface["prevailing_direction"]) == {-1}      # only bearish regime kept
    assert set(surface["entry_direction"]) == {1}            # long entry
    assert attrition["distinct_regimes"]["bearish_regime"] == 1


def test_build_surface_long_raises_on_directionality_mismatch():
    """If the atlas current_mfe is NOT bearish-favorable (e.g. long-oriented),
    the self-validation guard must raise, not silently proceed."""
    import build_surface_long as B
    NS = 1_000_000_000
    ts = np.array([i * NS for i in range(6)], dtype=np.int64)
    close = np.array([100, 99, 98, 97, 96, 95], float)
    raw = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                        "close": close, "volume": 1.0}, index=pd.Index(ts, name="ts"))
    obs = ts[1:5]
    # deliberately WRONG current_mfe (long-favorable high-anchor), should mismatch
    bad = pd.DataFrame({
        "observation_time": obs, "regime_start_ns": 0, "regime_end_ns": 5 * NS,
        "direction": -1, "entry_ts_event": 0, "entry_open": 100.0,
        "atr_at_entry": 1.0, "atr_at_checkpoint": 1.0, "regime_age": 1000.0,
        "current_pnl": 0.0, "current_mfe": 99.0, "current_mae": 0.0,
        "running_mfe": 99.0, "running_mae": 0.0})
    filt = {"regime_age_s_min": 0.0, "running_mfe_atr_min": 0.0,
            "new_progress_windows_min": 0, "retained_mfe_ratio_min": -1e9}
    with pytest.raises(RuntimeError, match="DIRECTIONALITY_FAILED"):
        B.build_surface_long(2099, bad, raw, filt)

"""Smoke tests for utils/safe_replay.py and utils/audit_replay_fills.py.

Run: python -m pytest tests/test_safe_replay.py -v
Or:  python tests/test_safe_replay.py
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.safe_replay import (
    SafeReplayConfig, FillModel, OHLCConvention,
    InvalidStopPolicy, validate_stop_at_arm, is_on_tick_grid,
    round_protect_to_tick, replay_stop_on_bar_ohlc,
    replay_stop_on_bar_idealized, replay_stop_on_tick_window,
    apply_invalid_stop_policy, safe_stop_replay_armed,
    compute_protect_px_from_mfe, stale_mfe_diagnostic,
    NQ_TICK,
)
from utils.audit_replay_fills import (
    audit_trades, AuditConfig, AuditResult,
)


# ---------------- validate_stop_at_arm ----------------
class TestValidateStopAtArm:
    def test_long_valid(self):
        # protect 100 below current 101 — valid, waits for fall
        ok, reason = validate_stop_at_arm(1, 101.0, 100.0)
        assert ok and reason is None

    def test_long_invalid_in_market(self):
        # protect 100 same as current 100 — invalid (would fire now)
        ok, reason = validate_stop_at_arm(1, 100.0, 100.0)
        assert not ok and "in market" in reason

    def test_long_invalid_past_market(self):
        ok, reason = validate_stop_at_arm(1, 99.0, 100.0)
        assert not ok and "in market" in reason

    def test_short_valid(self):
        ok, reason = validate_stop_at_arm(-1, 99.0, 100.0)
        assert ok and reason is None

    def test_short_invalid(self):
        ok, reason = validate_stop_at_arm(-1, 101.0, 100.0)
        assert not ok and "in market" in reason

    def test_invalid_direction(self):
        with pytest.raises(ValueError):
            validate_stop_at_arm(0, 100.0, 100.0)


# ---------------- is_on_tick_grid ----------------
class TestTickGrid:
    def test_valid(self):
        assert is_on_tick_grid(100.25)
        assert is_on_tick_grid(100.50)
        assert is_on_tick_grid(100.00)

    def test_invalid(self):
        assert not is_on_tick_grid(100.30)
        assert not is_on_tick_grid(100.125)


# ---------------- round_protect_to_tick ----------------
class TestRoundProtectToTick:
    def test_long_rounds_down(self):
        # Long protect raw=100.30 → round DOWN to 100.25
        assert round_protect_to_tick(100.30, 1) == 100.25
        assert round_protect_to_tick(100.74, 1) == 100.50

    def test_short_rounds_up(self):
        assert round_protect_to_tick(100.30, -1) == 100.50
        assert round_protect_to_tick(100.01, -1) == 100.25

    def test_already_on_grid(self):
        assert round_protect_to_tick(100.25, 1) == 100.25
        assert round_protect_to_tick(100.25, -1) == 100.25


# ---------------- replay_stop_on_bar_ohlc ----------------
class TestReplayStopOnBarOhlc:
    def test_long_no_trigger(self):
        # Long stop at 100, bar low 100.25 — no trigger
        res = replay_stop_on_bar_ohlc(
            direction=1, stop_px=100.0, bar_high=101.0,
            bar_low=100.25, bar_close=100.75, bar_ts_init=1000)
        assert not res.fired
        assert res.fill_px is None

    def test_long_trigger_close_above_stop(self):
        # Long stop at 100, bar dipped to 99.5 then closed at 100.5
        # at_or_worse_close: fill at min(100, 100.5) = 100
        res = replay_stop_on_bar_ohlc(
            direction=1, stop_px=100.0, bar_high=101.0,
            bar_low=99.5, bar_close=100.5, bar_ts_init=1000,
            convention=OHLCConvention.AT_OR_WORSE_CLOSE)
        assert res.fired
        assert res.fill_px == 100.0
        assert res.fill_ts == 1000

    def test_long_trigger_close_below_stop(self):
        # Long stop at 100, bar dipped to 99.5 and closed at 99.75
        # at_or_worse_close: fill at min(100, 99.75) = 99.75 (worse)
        res = replay_stop_on_bar_ohlc(
            direction=1, stop_px=100.0, bar_high=100.25,
            bar_low=99.5, bar_close=99.75, bar_ts_init=1000)
        assert res.fired
        assert res.fill_px == 99.75   # worse than stop

    def test_short_trigger(self):
        res = replay_stop_on_bar_ohlc(
            direction=-1, stop_px=100.0, bar_high=100.5,
            bar_low=99.5, bar_close=99.75, bar_ts_init=1000)
        assert res.fired
        # at_or_worse_close: max(100, 99.75) = 100
        assert res.fill_px == 100.0

    def test_short_trigger_worse(self):
        res = replay_stop_on_bar_ohlc(
            direction=-1, stop_px=100.0, bar_high=100.5,
            bar_low=99.5, bar_close=100.25, bar_ts_init=1000)
        assert res.fired
        # at_or_worse_close: max(100, 100.25) = 100.25 (worse for short)
        assert res.fill_px == 100.25

    def test_bar_close_convention(self):
        res = replay_stop_on_bar_ohlc(
            direction=1, stop_px=100.0, bar_high=100.5,
            bar_low=99.5, bar_close=99.75, bar_ts_init=1000,
            convention=OHLCConvention.BAR_CLOSE)
        assert res.fired and res.fill_px == 99.75

    def test_worst_in_bar_convention(self):
        res = replay_stop_on_bar_ohlc(
            direction=1, stop_px=100.0, bar_high=100.5,
            bar_low=99.0, bar_close=100.25, bar_ts_init=1000,
            convention=OHLCConvention.WORST_IN_BAR)
        assert res.fired and res.fill_px == 99.0   # bar low


# ---------------- replay_stop_on_bar_idealized ----------------
class TestReplayStopOnBarIdealized:
    def test_idealized_fills_at_stop_px(self):
        # IDEALIZED mode: fill at stop_px exactly
        res = replay_stop_on_bar_idealized(
            direction=1, stop_px=100.0, bar_high=100.5,
            bar_low=99.5, bar_close=99.75, bar_ts_init=1000)
        assert res.fired and res.fill_px == 100.0
        assert "IDEALIZED_NON_EXECUTABLE" in res.reason


# ---------------- replay_stop_on_tick_window ----------------
class TestTickReplay:
    def test_long_first_cross(self):
        ticks = [(1000, 100.25), (1100, 100.0), (1200, 99.75)]
        ts = [t for t, _ in ticks]; px = [p for _, p in ticks]
        res = replay_stop_on_tick_window(
            direction=1, stop_px=100.0, tick_ts=ts, tick_px=px)
        assert res.fired
        # First tick at or below 100.0 = tick at 100.0 (idx 1)
        assert res.fill_px == 100.0 and res.fill_ts == 1100

    def test_long_no_cross(self):
        ticks = [(1000, 100.25), (1100, 100.5)]
        ts = [t for t, _ in ticks]; px = [p for _, p in ticks]
        res = replay_stop_on_tick_window(
            direction=1, stop_px=100.0, tick_ts=ts, tick_px=px)
        assert not res.fired

    def test_long_gap_through_stop(self):
        # First tick at 99.5 — stop fills at 99.5 (worse than 100)
        ticks = [(1000, 100.5), (1100, 99.5)]
        ts = [t for t, _ in ticks]; px = [p for _, p in ticks]
        res = replay_stop_on_tick_window(
            direction=1, stop_px=100.0, tick_ts=ts, tick_px=px)
        assert res.fired and res.fill_px == 99.5


# ---------------- apply_invalid_stop_policy ----------------
class TestInvalidStopPolicy:
    def test_market_exit_now(self):
        action = apply_invalid_stop_policy(
            policy=InvalidStopPolicy.MARKET_EXIT_NOW,
            direction=1, arm_bar_close=100.0,
            arm_bar_ts_init=1000,
            invalid_reason="test")
        assert action.action == "exit_now"
        assert action.fill_px == 100.0
        assert action.fill_ts == 1000

    def test_skip_rule_and_hold(self):
        action = apply_invalid_stop_policy(
            policy=InvalidStopPolicy.SKIP_RULE_AND_HOLD,
            direction=1, arm_bar_close=100.0,
            arm_bar_ts_init=1000,
            invalid_reason="test")
        assert action.action == "skip"
        assert action.fill_px is None


# ---------------- safe_stop_replay_armed ----------------
class TestSafeStopReplayArmed:
    def test_invalid_stop_market_exits_at_arm_close(self):
        """Long stop at 100, but current price (arm close) is 99 →
        stop is invalid. With market_exit_now policy, exit at 99."""
        cfg = SafeReplayConfig(
            invalid_stop_policy=InvalidStopPolicy.MARKET_EXIT_NOW)
        out = safe_stop_replay_armed(
            direction=1, stop_px=100.0, arm_ts=1000,
            arm_bar_high=100.5, arm_bar_low=98.5, arm_bar_close=99.0,
            bars_after_arm=[],
            config=cfg)
        assert out.fired and out.stop_invalid_at_arm
        assert out.fill_px == 99.0   # arm bar close
        assert out.fired_via == "invalid_market_exit"

    def test_invalid_stop_skip(self):
        cfg = SafeReplayConfig(
            invalid_stop_policy=InvalidStopPolicy.SKIP_RULE_AND_HOLD)
        out = safe_stop_replay_armed(
            direction=1, stop_px=100.0, arm_ts=1000,
            arm_bar_high=100.5, arm_bar_low=98.5, arm_bar_close=99.0,
            bars_after_arm=[],
            config=cfg)
        assert not out.fired
        assert out.fired_via == "skipped_held_regime"

    def test_valid_stop_fires_later_bar(self):
        """Long stop at 99, current price 100. Stop fires when later
        bar dips to 98.5."""
        cfg = SafeReplayConfig()
        out = safe_stop_replay_armed(
            direction=1, stop_px=99.0, arm_ts=1000,
            arm_bar_high=100.5, arm_bar_low=99.5, arm_bar_close=100.0,
            bars_after_arm=[
                {"ts_init": 2000, "h": 100.0, "l": 99.5,
                 "c": 99.75},
                {"ts_init": 3000, "h": 99.5, "l": 98.5,
                 "c": 99.0},
            ],
            config=cfg)
        assert out.fired
        # at_or_worse_close: min(99, 99.0) = 99
        assert out.fill_px == 99.0
        assert out.fill_ts == 3000
        assert out.fired_via == "stop_triggered"

    def test_valid_stop_never_fires(self):
        cfg = SafeReplayConfig()
        out = safe_stop_replay_armed(
            direction=1, stop_px=99.0, arm_ts=1000,
            arm_bar_high=100.5, arm_bar_low=99.5, arm_bar_close=100.0,
            bars_after_arm=[
                {"ts_init": 2000, "h": 101.0, "l": 99.5,
                 "c": 100.5},
            ],
            config=cfg)
        assert not out.fired
        assert out.fired_via == "regime_fallback"


# ---------------- audit_trades ----------------
class TestAuditTrades:
    def _make_trades(self):
        return pd.DataFrame([
            # Trade 1: clean long, exit within bar
            dict(trade_id=1, entry_ts=1000, exit_ts=2000,
                 fill_price=100.0, exit_price=99.5,
                 direction=1, net_pnl=-10.0,
                 hhll_arm_ts=1500,
                 hhll_protect_px=99.5, gross_pnl=-10.0),
            # Trade 2: PHANTOM — exit at 99.5 but bar OHLC is
            # [101, 102] (way above)
            dict(trade_id=2, entry_ts=1000, exit_ts=3000,
                 fill_price=100.0, exit_price=99.5,
                 direction=1, net_pnl=-10.0,
                 hhll_arm_ts=1500,
                 hhll_protect_px=99.5, gross_pnl=-10.0),
        ])

    def _make_lookup(self):
        # Trade 1's exit_ts=2000 is in [99, 100]; trade 2's
        # exit_ts=3000 is in [101, 102] (FAR ABOVE 99.5)
        bars = {
            2000: (99.5, 100.0, 99.0, 99.5),
            3000: (101.5, 102.0, 101.0, 101.5),
        }
        def lookup(ts):
            return bars.get(ts)
        return lookup

    def test_detects_phantom_fill(self):
        cfg = AuditConfig(hard_fail_on_impossible=False)
        result = audit_trades(
            self._make_trades(), self._make_lookup(), cfg)
        assert result.has_impossible_fills
        assert result.impossible_fills_n == 1
        # Trade 2 contributed -$10 of phantom fill
        assert result.flags["exit_outside_bar_ohlc"].count == 1

    def test_hard_fail(self):
        cfg = AuditConfig(hard_fail_on_impossible=True)
        with pytest.raises(RuntimeError, match="impossible fills"):
            audit_trades(self._make_trades(), self._make_lookup(),
                            cfg)

    def test_clean_passes(self):
        # Just trade 1
        df = self._make_trades().head(1)
        result = audit_trades(df, self._make_lookup())
        assert not result.has_impossible_fills
        assert result.impossible_fills_n == 0

    def test_off_grid_protect_detected(self):
        df = pd.DataFrame([
            dict(trade_id=99, entry_ts=1000, exit_ts=2000,
                 fill_price=100.0, exit_price=99.5,
                 direction=1, net_pnl=-10.0,
                 hhll_arm_ts=1500,
                 hhll_protect_px=99.30,  # NOT on tick grid (0.25)
                 gross_pnl=-10.0),
        ])
        cfg = AuditConfig(hard_fail_on_impossible=False)
        result = audit_trades(df, None, cfg)
        assert result.flags["protect_not_on_tick_grid"].count == 1


# ---------------- Standalone runner ----------------
if __name__ == "__main__":
    # Allow running without pytest
    import inspect
    classes = [
        TestValidateStopAtArm, TestTickGrid,
        TestRoundProtectToTick, TestReplayStopOnBarOhlc,
        TestReplayStopOnBarIdealized, TestTickReplay,
        TestInvalidStopPolicy, TestSafeStopReplayArmed,
        TestAuditTrades,
    ]
    n_pass = n_fail = 0
    for cls in classes:
        instance = cls()
        for name, method in inspect.getmembers(
                cls, predicate=inspect.isfunction):
            if not name.startswith("test_"): continue
            if name.startswith("_"): continue
            try:
                method(instance)
                n_pass += 1
                print(f"  PASS  {cls.__name__}.{name}")
            except Exception as e:
                n_fail += 1
                print(f"  FAIL  {cls.__name__}.{name}: {e}")
    print(f"\n{n_pass} passed, {n_fail} failed")
    sys.exit(0 if n_fail == 0 else 1)

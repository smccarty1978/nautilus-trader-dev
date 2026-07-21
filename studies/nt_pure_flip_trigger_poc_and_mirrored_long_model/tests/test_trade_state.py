"""Hand-computed tests for phase2/trade_state.py, run BEFORE wiring into the
NT Strategy (per project pre-execution-audit standing rule)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "phase2"))
from trade_state import (  # noqa: E402
    FlipTradeState, favorable_adverse_points, realized_favorable_atr, unrealized_pnl,
)


def test_short_stop_price_is_above_entry():
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    assert t.stop_px == pytest.approx(112.5)


def test_long_stop_price_is_below_entry():
    t = FlipTradeState(entry_direction=1, entry_px=100.0, atr=10.0)
    assert t.stop_px == pytest.approx(87.5)


def test_short_stop_touches_on_bar_high_at_or_above():
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    assert t.stop_would_touch(high=112.5, low=105.0) is True
    assert t.stop_would_touch(high=112.4, low=105.0) is False


def test_long_stop_touches_on_bar_low_at_or_below():
    t = FlipTradeState(entry_direction=1, entry_px=100.0, atr=10.0)
    assert t.stop_would_touch(high=95.0, low=87.5) is True
    assert t.stop_would_touch(high=95.0, low=87.6) is False


def test_no_timeout_bearish_flip_confirmed_arbitrarily_late():
    """Core requirement: no confirmation deadline -- a bearish flip 10,000s
    after entry must still be accepted (unlike the old Policy A timeout)."""
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    result = t.on_regime_update(new_regime=-1, ts=10_000 * 1_000_000_000)
    assert result is None  # confirmation itself is not an exit signal
    assert t.bearish_flip_confirmed is True


def test_bullish_regime_before_bearish_flip_does_not_exit():
    """The regime must go bearish FIRST (confirming the short thesis)
    before any bullish flip counts as the opposing-flip exit -- a bullish
    'flip' before bearish confirmation is not meaningful (the position
    entered short into an already-bullish regime; only after the regime
    has genuinely turned bearish does the NEXT bullish turn exit)."""
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    result = t.on_regime_update(new_regime=1, ts=100 * 1_000_000_000)
    assert result is None
    assert t.bearish_flip_confirmed is False


def test_opposing_flip_exit_only_fires_after_bearish_confirmed():
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    assert t.on_regime_update(new_regime=-1, ts=100 * 1_000_000_000) is None
    assert t.bearish_flip_confirmed is True
    result = t.on_regime_update(new_regime=1, ts=500 * 1_000_000_000)
    assert result == "opposing_flip_exit"


def test_stop_reason_labels_before_vs_after_bearish_flip():
    t1 = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    assert t1.on_stop_touch() == "fixed_stop_before_bearish_flip"

    t2 = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    t2.on_regime_update(new_regime=-1, ts=100 * 1_000_000_000)
    assert t2.on_stop_touch() == "fixed_stop_after_bearish_flip"


def test_stop_never_moves_regardless_of_bearish_flip():
    """Unlike Policy A, the stop is NEVER swapped/moved -- confirm the
    stop_px value is identical before and after bearish-flip confirmation."""
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    stop_before = t.stop_px
    t.on_regime_update(new_regime=-1, ts=100 * 1_000_000_000)
    assert t.stop_px == stop_before == pytest.approx(112.5)


def test_mirrored_long_thesis_is_bullish_flip_then_bearish_exit():
    """Long (mirrored) population: thesis is a BULLISH flip from a
    currently-bearish regime; opposing exit is the following BEARISH flip."""
    t = FlipTradeState(entry_direction=1, entry_px=100.0, atr=10.0)
    assert t.on_regime_update(new_regime=1, ts=100 * 1_000_000_000) is None
    assert t.bearish_flip_confirmed is True  # name is short-population-centric; means "thesis confirmed"
    result = t.on_regime_update(new_regime=-1, ts=500 * 1_000_000_000)
    assert result == "opposing_flip_exit"


def test_calling_after_closed_raises():
    t = FlipTradeState(entry_direction=-1, entry_px=100.0, atr=10.0)
    t.closed = True
    with pytest.raises(RuntimeError):
        t.on_regime_update(new_regime=-1, ts=0)
    with pytest.raises(RuntimeError):
        t.on_stop_touch()


def test_invalid_direction_raises():
    with pytest.raises(ValueError):
        FlipTradeState(entry_direction=0, entry_px=100.0, atr=10.0)


def test_non_positive_atr_raises():
    with pytest.raises(ValueError):
        FlipTradeState(entry_direction=-1, entry_px=100.0, atr=0.0)


def test_favorable_adverse_points_short():
    fav, adv = favorable_adverse_points(-1, entry_px=100.0, high=103.0, low=95.0)
    assert fav == pytest.approx(5.0)   # entry - low, price fell = favorable
    assert adv == pytest.approx(3.0)   # high - entry, price rose = adverse


def test_favorable_adverse_points_long():
    fav, adv = favorable_adverse_points(1, entry_px=100.0, high=106.0, low=98.0)
    assert fav == pytest.approx(6.0)   # high - entry, price rose = favorable
    assert adv == pytest.approx(2.0)   # entry - low, price fell = adverse


def test_favorable_adverse_points_never_negative():
    """Entry price itself outside the bar's range (can happen at the very
    entry bar) must still floor at 0, not go negative."""
    fav, adv = favorable_adverse_points(-1, entry_px=100.0, high=99.0, low=98.0)
    assert fav >= 0.0 and adv >= 0.0


def test_unrealized_pnl_short_price_falls_is_profit():
    pnl = unrealized_pnl(-1, entry_px=100.0, close=95.0, multiplier=20.0)
    assert pnl == pytest.approx(100.0)   # (100-95)*20, positive = profitable short


def test_unrealized_pnl_short_price_rises_is_loss():
    pnl = unrealized_pnl(-1, entry_px=100.0, close=105.0, multiplier=20.0)
    assert pnl == pytest.approx(-100.0)


def test_unrealized_pnl_long_price_rises_is_profit():
    pnl = unrealized_pnl(1, entry_px=100.0, close=105.0, multiplier=20.0)
    assert pnl == pytest.approx(100.0)


def test_realized_favorable_atr_short():
    # short, exit at 90 (favorable, price fell 10pts), atr=10 -> 1.0 ATR
    assert realized_favorable_atr(-1, entry_px=100.0, exit_px=90.0, atr=10.0) == pytest.approx(1.0)
    # short, exit at 110 (adverse) -> floors at 0
    assert realized_favorable_atr(-1, entry_px=100.0, exit_px=110.0, atr=10.0) == pytest.approx(0.0)


def test_realized_favorable_atr_long():
    assert realized_favorable_atr(1, entry_px=100.0, exit_px=110.0, atr=10.0) == pytest.approx(1.0)
    assert realized_favorable_atr(1, entry_px=100.0, exit_px=90.0, atr=10.0) == pytest.approx(0.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

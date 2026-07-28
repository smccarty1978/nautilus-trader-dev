"""Session containment — the property that failed silently.

Only RTH bars are loaded, so array index i+1 after 14:59:59 is the *next
session's* 08:30:00. A horizon lookup alone runs straight through the overnight
gap. The first version of the engine did exactly that: one 2022-11-09 trade
exited at 2022-11-10 08:30 for +515 points (+41.6 ATR), which was the entire
positive expectancy of the discovery set.

Nothing about that trade looked wrong in aggregate — the outcome code said
SCORE_EXIT, MFE was internally consistent, and no assertion tripped. Only the
per-trade timestamps reveal it, which is what these tests check.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    ExitPolicy,
    MarketData,
    RegimeIndex,
    simulate,
)

CT = ZoneInfo("America/Chicago")
NS = 1_000_000_000


def _ns(y, m, d, hh, mm, ss=0) -> int:
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=CT).timestamp()) * NS


def _two_session_market() -> MarketData:
    """Two RTH sessions with a large overnight gap between them."""
    ts, o, h, l, c, dc = [], [], [], [], [], []
    for day, base in ((9, 10_000.0), (10, 10_500.0)):   # +500 pt gap overnight
        close_ns = _ns(2022, 11, day, 15, 0)
        for sec in range(0, 3600):                      # 08:30:00 .. 09:29:59
            t = _ns(2022, 11, day, 8, 30) + sec * NS
            price = base + sec * 0.01
            ts.append(t); o.append(price); h.append(price + 0.5)
            l.append(price - 0.5); c.append(price); dc.append(close_ns)
    return MarketData(
        ts=np.array(ts, dtype=np.int64),
        open_=np.array(o), high=np.array(h), low=np.array(l), close=np.array(c),
        day_close_ns=np.array(dc, dtype=np.int64),
    )


def _no_flips() -> RegimeIndex:
    """No regime event inside the fixture, so only the session bound can exit."""
    return RegimeIndex(
        start_ns=np.array([_ns(2022, 11, 1, 9, 0)], dtype=np.int64),
        direction=np.array([1], dtype=np.int64),
    )


@pytest.fixture
def market() -> MarketData:
    return _two_session_market()


def test_a_trade_never_exits_in_a_later_session(market: MarketData):
    entry = _ns(2022, 11, 9, 9, 0)
    t = simulate(market, _no_flips(), entry, 1, 10_001.8, 10.0,
                 ExitPolicy(stop_atr=None))
    assert t.exit_ns is not None
    assert t.exit_ns < _ns(2022, 11, 9, 15, 0), "exit crossed the session close"
    exit_day = datetime.fromtimestamp(t.exit_ns / 1e9, tz=timezone.utc).astimezone(CT).day
    assert exit_day == 9


def test_the_overnight_gap_is_never_captured(market: MarketData):
    """The regression itself: +500 points sit across the gap. A trade entered
    late in session one must not collect any of it."""
    entry = _ns(2022, 11, 9, 9, 29, 0)
    t = simulate(market, _no_flips(), entry, 1, 10_035.0, 10.0,
                 ExitPolicy(stop_atr=None))
    assert t.gross_atr < 1.0, (
        f"captured the overnight gap: {t.gross_atr:+.2f} ATR"
    )


def test_a_trigger_on_the_final_bar_does_not_fill_next_session(market: MarketData):
    """No next open exists inside the session; the next array element belongs to
    tomorrow. Such a trade closes at the session close, never at tomorrow's open."""
    entry = _ns(2022, 11, 9, 9, 29, 50)
    t = simulate(market, _no_flips(), entry, 1, 10_035.0, 0.5,
                 ExitPolicy(stop_atr=0.1, target_atr=0.1))
    assert t.exit_ns is None or t.exit_ns < _ns(2022, 11, 9, 15, 0)
    if t.exit_price is not None:
        assert t.exit_price < 10_100.0, "filled against the next session's open"


def test_mfe_cannot_exceed_the_session_range(market: MarketData):
    entry = _ns(2022, 11, 9, 8, 35)
    t = simulate(market, _no_flips(), entry, 1, 10_003.0, 1.0,
                 ExitPolicy(stop_atr=None))
    session_high = market.high[:3600].max()
    assert t.mfe_atr <= (session_high - 10_003.0) / 1.0 + 1e-9


def test_every_entry_in_a_session_stays_contained(market: MarketData):
    """Sweep entries across the session; none may escape it."""
    regimes = _no_flips()
    close_ns = _ns(2022, 11, 9, 15, 0)
    for sec in range(0, 3600, 137):
        entry = _ns(2022, 11, 9, 8, 30) + sec * NS
        t = simulate(market, regimes, entry, 1, 10_000.0 + sec * 0.01, 10.0,
                     ExitPolicy(stop_atr=1.0))
        if t.exit_ns is not None:
            assert t.exit_ns < close_ns, f"entry at +{sec}s escaped its session"


def test_short_side_is_contained_too(market: MarketData):
    entry = _ns(2022, 11, 9, 9, 29, 0)
    t = simulate(market, _no_flips(), entry, -1, 10_035.0, 10.0,
                 ExitPolicy(stop_atr=None))
    assert t.exit_ns < _ns(2022, 11, 9, 15, 0)
    assert abs(t.gross_atr) < 1.0


# ------------------------------------------------------- breakeven mechanics

def _v_shaped_market() -> MarketData:
    """Price rises 20 points, then falls back through entry and beyond.

    A correct breakeven exit closes on the way back down at entry. A tautological
    one closes one bar after arming, near the high.
    """
    close_ns = _ns(2022, 11, 9, 15, 0)
    ts, o, h, l, c, dc = [], [], [], [], [], []
    for sec in range(600):
        t = _ns(2022, 11, 9, 8, 30) + sec * NS
        price = 10_000.0 + (sec * 0.1 if sec < 200 else 20.0 - (sec - 200) * 0.1)
        ts.append(t); o.append(price); h.append(price + 0.25)
        l.append(price - 0.25); c.append(price); dc.append(close_ns)
    return MarketData(
        ts=np.array(ts, dtype=np.int64), open_=np.array(o), high=np.array(h),
        low=np.array(l), close=np.array(c), day_close_ns=np.array(dc, dtype=np.int64),
    )


def test_breakeven_does_not_close_one_bar_after_arming():
    """Regression: `run_mae >= 0` is a tautology (running max floored at zero),
    so every armed trade closed one bar after arming regardless of price."""
    market = _v_shaped_market()
    entry = _ns(2022, 11, 9, 8, 30)
    t = simulate(market, _no_flips(), entry, 1, 10_000.0, 10.0,
                 ExitPolicy(stop_atr=None, breakeven_at_atr=0.5))
    held = t.bars
    assert held > 60, (
        f"closed after only {held} bars — breakeven armed at 0.5 ATR (5 pts, "
        f"~50 bars) and should hold until price returns to entry (~bar 400)"
    )


def test_breakeven_closes_when_price_returns_to_entry():
    market = _v_shaped_market()
    entry = _ns(2022, 11, 9, 8, 30)
    t = simulate(market, _no_flips(), entry, 1, 10_000.0, 10.0,
                 ExitPolicy(stop_atr=None, breakeven_at_atr=0.5))
    assert t.exit_price is not None
    assert abs(t.exit_price - 10_000.0) < 2.0, (
        f"breakeven exit filled at {t.exit_price}, not near entry 10000"
    )
    assert t.mfe_atr > 1.0, "fixture must actually reach the arming level"


def test_unarmed_breakeven_never_triggers():
    """A trade that never reaches the arming MFE must be unaffected."""
    market = _v_shaped_market()
    entry = _ns(2022, 11, 9, 8, 30)
    a = simulate(market, _no_flips(), entry, 1, 10_000.0, 10.0,
                 ExitPolicy(stop_atr=None))
    b = simulate(market, _no_flips(), entry, 1, 10_000.0, 10.0,
                 ExitPolicy(stop_atr=None, breakeven_at_atr=100.0))
    assert (a.exit_ns, a.exit_price) == (b.exit_ns, b.exit_price)


# --------------------------------------------- lifecycle boundary resolution

def test_a_flip_stamped_at_the_entry_second_is_the_next_flip():
    """A 1s checkpoint at ts_init T is dispatched before the 1m bar at T, so a
    regime flip stamped T is in the trade's future.

    Searching strictly after skipped it and matched a far later regime of the
    same direction, mislabelling the opposing regime in between as the exit.
    """
    entry = _ns(2021, 3, 30, 9, 53)
    regimes = RegimeIndex(
        start_ns=np.array([
            _ns(2021, 3, 30, 9, 27),   # +1  entry's own regime
            _ns(2021, 3, 30, 9, 53),   # -1  confirm, same second as entry
            _ns(2021, 3, 30, 10, 0),   # +1  opposing exit
            _ns(2021, 3, 30, 10, 21),  # -1
        ], dtype=np.int64),
        direction=np.array([1, -1, 1, -1], dtype=np.int64),
    )
    # SHORT fade: confirm is the -1 flip, exit is the following +1 flip.
    assert regimes.next_start_after(entry, -1) == _ns(2021, 3, 30, 9, 53)
    assert regimes.next_start_after(entry, 1) == _ns(2021, 3, 30, 10, 0)


def test_confirm_precedes_the_opposing_exit_at_a_boundary_entry():
    """The ordering that was inverted: confirm must not resolve after the exit."""
    entry = _ns(2021, 3, 30, 9, 53)
    regimes = RegimeIndex(
        start_ns=np.array([
            _ns(2021, 3, 30, 9, 27), _ns(2021, 3, 30, 9, 53),
            _ns(2021, 3, 30, 10, 0), _ns(2021, 3, 30, 10, 21),
        ], dtype=np.int64),
        direction=np.array([1, -1, 1, -1], dtype=np.int64),
    )
    confirm = regimes.next_start_after(entry, -1)
    opposing = regimes.next_start_after(entry, 1)
    assert confirm < opposing, "confirm flip must precede the opposing exit"


def test_strict_mode_still_available_and_differs_at_the_boundary():
    entry = _ns(2021, 3, 30, 9, 53)
    regimes = RegimeIndex(
        start_ns=np.array([_ns(2021, 3, 30, 9, 53), _ns(2021, 3, 30, 10, 21)],
                          dtype=np.int64),
        direction=np.array([-1, -1], dtype=np.int64),
    )
    assert regimes.next_start_after(entry, -1, inclusive=True) == entry
    assert regimes.next_start_after(entry, -1, inclusive=False) == _ns(2021, 3, 30, 10, 21)


def test_non_boundary_entries_are_unaffected():
    """Away from a boundary the two modes must agree, so the fix cannot shift
    the 98% of trades that never sat on a flip second."""
    regimes = RegimeIndex(
        start_ns=np.array([_ns(2021, 3, 30, 9, 27), _ns(2021, 3, 30, 10, 0)],
                          dtype=np.int64),
        direction=np.array([1, -1], dtype=np.int64),
    )
    entry = _ns(2021, 3, 30, 9, 40)
    for d in (1, -1):
        assert (regimes.next_start_after(entry, d, inclusive=True)
                == regimes.next_start_after(entry, d, inclusive=False))

"""Unit tests for NQ Fair Pricing trackers:
- tracker.candle.displacement_1m (DisplacementCandleBinding)
- tracker.structure.bos_1m (StructureBosBinding)
"""
from __future__ import annotations

import pytest

from features.trackers.base import BarView, EpochView
from features.trackers.displacement_candle import DisplacementCandleBinding
from features.trackers.structure_bos import StructureBosBinding


def _make_bar(
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    ts_init: int,
    volume: float = 100.0,
) -> BarView:
    return BarView(
        stream="bars",
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=volume,
        ts_init=ts_init,
        ts_event=ts_init - 60_000_000_000,
    )


class DummyAnchorTracker:
    def __init__(self, anchor: float):
        self.anchor = anchor

    def epoch_value(self, name: str, epoch: EpochView) -> float:
        if name == "rth_open":
            return self.anchor
        raise KeyError(name)


def test_displacement_candle_bullish_and_bearish():
    binding = DisplacementCandleBinding(params={}, inputs={"bars": "stream"})

    # Bar 0: Warmup bar (bearish, small)
    # Open: 100, High: 102, Low: 98, Close: 99 (body = -1)
    b0 = _make_bar(100.0, 102.0, 98.0, 99.0, ts_init=1_000_000_000)
    binding.on_bar("bars", b0)
    assert binding.is_displacement == 0

    # Bar 1: Bullish displacement relative to Bar 0
    # Prior was bearish (body -1, high 102).
    # Current is bullish: Open: 99, High: 105, Low: 99, Close: 103 (body = +4 > 1, close 103 > prior high 102)
    b1 = _make_bar(99.0, 105.0, 99.0, 103.0, ts_init=2_000_000_000)
    binding.on_bar("bars", b1)
    assert binding.is_displacement == 1
    assert binding.displacement_dir == 1

    # Anchor at 110 (price 103 is below anchor -> bullish is toward anchor)
    anchor_tracker = DummyAnchorTracker(110.0)
    epoch = EpochView(
        T=2_000_000_000,
        price=103.0,
        bar=b1,
        trackers={"rth_open": anchor_tracker},
    )
    assert binding.epoch_value("is_displacement", epoch) == 1
    assert binding.epoch_value("displacement_dir", epoch) == 1
    assert binding.epoch_value("toward_anchor", epoch) == 1
    assert binding.epoch_value("signal", epoch) == 1
    assert binding.epoch_value("signal_dir", epoch) == 1

    # If anchor is at 100 (price 103 is above anchor -> bullish is away from anchor)
    anchor_tracker_below = DummyAnchorTracker(100.0)
    epoch_away = EpochView(
        T=2_000_000_000,
        price=103.0,
        bar=b1,
        trackers={"rth_open": anchor_tracker_below},
    )
    assert binding.epoch_value("toward_anchor", epoch_away) == 0
    assert binding.epoch_value("signal", epoch_away) == 0

    # Bar 2: Bearish displacement relative to Bar 1
    # Prior was bullish (body +4, low 99).
    # Current is bearish: Open: 103, High: 103.5, Low: 97, Close: 98 (body = -5 > 4, close 98 < prior low 99)
    b2 = _make_bar(103.0, 103.5, 97.0, 98.0, ts_init=3_000_000_000)
    binding.on_bar("bars", b2)
    assert binding.is_displacement == 1
    assert binding.displacement_dir == -1

    # Price 98, anchor at 105 (price 98 < anchor -> bearish displacement moves AWAY from anchor)
    epoch_bearish_away = EpochView(
        T=3_000_000_000,
        price=98.0,
        bar=b2,
        trackers={"rth_open": DummyAnchorTracker(105.0)},
    )
    assert binding.epoch_value("toward_anchor", epoch_bearish_away) == 0

    # Price 98, anchor at 90 (price 98 > anchor -> bearish displacement moves TOWARD anchor)
    epoch_bearish_toward = EpochView(
        T=3_000_000_000,
        price=98.0,
        bar=b2,
        trackers={"rth_open": DummyAnchorTracker(90.0)},
    )
    assert binding.epoch_value("toward_anchor", epoch_bearish_toward) == 1
    assert binding.epoch_value("signal", epoch_bearish_toward) == 1
    assert binding.epoch_value("signal_dir", epoch_bearish_toward) == -1


def test_displacement_candle_rejection_rules():
    binding = DisplacementCandleBinding(params={}, inputs={"bars": "stream"})

    # Case A: Same color
    b0 = _make_bar(100.0, 105.0, 99.0, 102.0, ts_init=1_000_000_000)  # Bullish
    b1 = _make_bar(102.0, 108.0, 101.0, 106.0, ts_init=2_000_000_000)  # Bullish
    binding.on_bar("bars", b0)
    binding.on_bar("bars", b1)
    assert binding.is_displacement == 0

    # Case B: Opposite color but body does not expand
    # b1 body was +4. b2 is bearish, body = -3 (| -3 | < 4)
    b2 = _make_bar(106.0, 107.0, 100.0, 103.0, ts_init=3_000_000_000)
    binding.on_bar("bars", b2)
    assert binding.is_displacement == 0

    # Case C: Opposite color, body expands, but fails to break prior wick extreme
    # b2 body was -3, low was 100.
    # b3 is bullish: open 103, close 107 (body +4 > 3). But b2 high was 107! Close is 107 (not > 107).
    b3 = _make_bar(103.0, 107.5, 102.5, 107.0, ts_init=4_000_000_000)
    binding.on_bar("bars", b3)
    assert binding.is_displacement == 0


def test_structure_bos_swing_high_and_low():
    bos = StructureBosBinding(params={}, inputs={"bars": "stream"})

    # Construct 3-bar swing high:
    # Bar 0 (t=1): High = 100, Low = 90, Close = 95
    # Bar 1 (t=2): High = 110, Low = 94, Close = 105 (Peak!)
    # Bar 2 (t=3): High = 105, Low = 92, Close = 96 (Confirmed swing high at Bar 1: price 110, confirmed at t=3)
    b0 = _make_bar(92.0, 100.0, 90.0, 95.0, ts_init=1_000_000_000)
    b1 = _make_bar(95.0, 110.0, 94.0, 105.0, ts_init=2_000_000_000)
    b2 = _make_bar(105.0, 105.0, 92.0, 96.0, ts_init=3_000_000_000)

    bos.on_bar("bars", b0)
    bos.on_bar("bars", b1)
    bos.on_bar("bars", b2)

    assert bos.is_bos == 0
    assert bos.active_swing_high == (110.0, 2_000_000_000, 3_000_000_000)

    # Bar 3 (t=4): Does not break 110 (Close = 108)
    b3 = _make_bar(96.0, 109.0, 95.0, 108.0, ts_init=4_000_000_000)
    bos.on_bar("bars", b3)
    assert bos.is_bos == 0

    # Bar 4 (t=5): Breaks 110 (Close = 112) -> Bullish BOS!
    b4 = _make_bar(108.0, 115.0, 107.0, 112.0, ts_init=5_000_000_000)
    bos.on_bar("bars", b4)
    assert bos.is_bos == 1
    assert bos.bos_dir == 1
    assert bos.last_pivot_price == 110.0
    assert bos.last_pivot_ts == 2_000_000_000
    assert bos.active_swing_high is None  # Consumed

    # Test anchor direction
    # Bullish BOS at 112. If anchor is 120 -> toward anchor!
    epoch_toward = EpochView(
        T=5_000_000_000,
        price=112.0,
        bar=b4,
        trackers={"rth_open": DummyAnchorTracker(120.0)},
    )
    assert bos.epoch_value("toward_anchor", epoch_toward) == 1
    assert bos.epoch_value("signal", epoch_toward) == 1
    assert bos.epoch_value("signal_dir", epoch_toward) == 1

    # Now test swing low formation and break:
    # Bar 5 (t=6): Low = 100
    # Bar 6 (t=7): Low = 90 (Trough!)
    # Bar 7 (t=8): Low = 95 (Confirmed swing low at Bar 6: price 90, confirmed at t=8)
    b5 = _make_bar(112.0, 113.0, 100.0, 102.0, ts_init=6_000_000_000)
    b6 = _make_bar(102.0, 103.0, 90.0, 92.0, ts_init=7_000_000_000)
    b7 = _make_bar(92.0, 98.0, 95.0, 97.0, ts_init=8_000_000_000)
    bos.on_bar("bars", b5)
    bos.on_bar("bars", b6)
    bos.on_bar("bars", b7)
    assert bos.is_bos == 0
    assert bos.active_swing_low == (90.0, 7_000_000_000, 8_000_000_000)

    # Bar 8 (t=9): Breaks 90 with close 88 -> Bearish BOS!
    b8 = _make_bar(97.0, 97.0, 85.0, 88.0, ts_init=9_000_000_000)
    bos.on_bar("bars", b8)
    assert bos.is_bos == 1
    assert bos.bos_dir == -1
    assert bos.last_pivot_price == 90.0
    assert bos.last_pivot_ts == 7_000_000_000

    # Bearish BOS at 88. If anchor is 80 (price 88 > 80) -> toward anchor!
    epoch_bearish_toward = EpochView(
        T=9_000_000_000,
        price=88.0,
        bar=b8,
        trackers={"rth_open": DummyAnchorTracker(80.0)},
    )
    assert bos.epoch_value("toward_anchor", epoch_bearish_toward) == 1
    assert bos.epoch_value("signal", epoch_bearish_toward) == 1
    assert bos.epoch_value("signal_dir", epoch_bearish_toward) == -1

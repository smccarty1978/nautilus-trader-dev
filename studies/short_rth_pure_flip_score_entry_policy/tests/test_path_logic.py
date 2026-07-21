"""Hand-computed tests for path_logic.py, run BEFORE applying it to the
selected trigger's real trades (per project pre-execution-audit rule)."""
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from path_logic import align_open_price, post_flip_giveback_atr, scan_trade_path  # noqa: E402

NS = 1_000_000_000


def make_bars(n: int, start_ts: int = 1_700_000_000, opens=None, highs=None, lows=None):
    ts = np.array([start_ts + i for i in range(n)], dtype=np.int64) * NS
    opens = np.array(opens if opens is not None else [100.0] * n)
    highs = np.array(highs if highs is not None else [100.0] * n)
    lows = np.array(lows if lows is not None else [100.0] * n)
    return ts, opens, highs, lows


def test_short_trade_favorable_excursion_is_price_falling():
    """Short entry at 100, price falls to 90 (favorable), ATR=10 ->
    max favorable excursion = 1.0 ATR."""
    ts, opens, highs, lows = make_bars(5, opens=[100, 98, 95, 92, 90],
                                       highs=[100, 98, 95, 92, 90], lows=[100, 98, 95, 90, 90])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=-1, atr=10.0)
    assert out["max_favorable_excursion_atr"] == pytest.approx(1.0)


def test_short_trade_adverse_excursion_is_price_rising():
    """Short entry at 100, price rises to 105 (adverse), ATR=10 ->
    max adverse excursion = 0.5 ATR."""
    ts, opens, highs, lows = make_bars(3, opens=[100, 103, 105],
                                       highs=[100, 103, 105], lows=[100, 103, 105])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=-1, atr=10.0)
    assert out["max_adverse_excursion_atr_to_exit"] == pytest.approx(0.5)


def test_ever_up_thresholds_use_running_max_not_final_value():
    """Price dips favorably to 0.8 ATR then reverses back near entry by
    exit -- ever_up_atr[0.75] must still be True (peak, not final)."""
    ts, opens, highs, lows = make_bars(4, opens=[100, 92, 100.5, 100.5],
                                       highs=[100, 92, 100.5, 100.5], lows=[100, 92, 100.5, 100.5])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=-1, atr=10.0)
    assert out["ever_up_atr"][0.75] is True
    assert out["ever_up_atr"][1.00] is False


def test_max_adverse_before_flip_excludes_bar_at_flip_ts():
    """Adverse excursion before flip must stop strictly before flip_ts --
    a price spike exactly AT flip_ts must not count."""
    ts, opens, highs, lows = make_bars(4, opens=[100, 101, 101, 120],
                                       highs=[100, 101, 101, 120], lows=[100, 101, 101, 120])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=-1, atr=10.0, flip_ts=ts[3])
    # bars before flip_ts (index 3) are indices 0,1,2 -> highs [100,101,101]
    assert out["max_adverse_excursion_atr_before_flip"] == pytest.approx(0.1)


def test_long_trade_favorable_excursion_is_price_rising():
    """direction=1 (long) branch, exercised explicitly -- this population
    never uses it, but the code carries it and it must not be silently
    wrong (this is exactly the untested-branch pattern that caused the
    precedent bug in build_weakness_atlas.compute_running_excursions)."""
    ts, opens, highs, lows = make_bars(3, opens=[100, 105, 110], highs=[100, 105, 110], lows=[100, 105, 110])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=1, atr=10.0)
    assert out["max_favorable_excursion_atr"] == pytest.approx(1.0)


def test_long_trade_adverse_excursion_is_price_falling():
    ts, opens, highs, lows = make_bars(3, opens=[100, 97, 95], highs=[100, 97, 95], lows=[100, 97, 95])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=1, atr=10.0)
    assert out["max_adverse_excursion_atr_to_exit"] == pytest.approx(0.5)


def test_long_post_flip_giveback():
    giveback = post_flip_giveback_atr(direction=1, align_open=100.0, exit_px=103.0,
                                      atr=10.0, post_align_mfe_atr=1.0)
    assert giveback == pytest.approx(0.7)


def test_flip_ts_beyond_available_data_returns_nan_not_truncated():
    """A flip_ts beyond the last available raw bar (e.g. next calendar
    year's data not loaded) must return NaN, never silently compute over a
    truncated window."""
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102], highs=[100, 101, 102], lows=[100, 101, 102])
    out = scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                          exit_ts=ts[-1], direction=-1, atr=10.0, flip_ts=ts[-1] + 1000 * NS)
    assert np.isnan(out["max_adverse_excursion_atr_before_flip"])


def test_exit_ts_beyond_available_data_raises():
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102], highs=[100, 101, 102], lows=[100, 101, 102])
    with pytest.raises(RuntimeError):
        scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                        exit_ts=ts[-1] + 1000 * NS, direction=-1, atr=10.0)


def test_exit_ts_not_on_grid_raises():
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102], highs=[100, 101, 102], lows=[100, 101, 102])
    with pytest.raises(RuntimeError):
        scan_trade_path(ts, opens, highs, lows, entry_ts=ts[0], entry_px=100.0,
                        exit_ts=ts[1] + 1, direction=-1, atr=10.0)


def test_align_open_price_exact_match():
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102])
    assert align_open_price(ts, opens, ts[1]) == 101.0


def test_align_open_price_falls_back_to_first_bar_at_or_after_a_data_gap():
    """Real raw data has occasional single-second gaps (a quiet second
    with no trade) -- align_open_price must fall back to the next
    available bar, matching entry_surface.build_surface's own established
    fill convention, not raise on the (legitimate) missing exact tick."""
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102])
    assert align_open_price(ts, opens, ts[1] + 1) == 102.0  # falls to the ts[2] bar


def test_align_open_price_beyond_available_data_raises():
    ts, opens, highs, lows = make_bars(3, opens=[100, 101, 102])
    with pytest.raises(RuntimeError):
        align_open_price(ts, opens, ts[-1] + 1000 * NS)


def test_post_flip_giveback_positive_when_peak_exceeds_realized():
    # short: align_open=100, peak favorable 1.0 ATR (atr=10 -> price 90),
    # but exit realized only 0.3 ATR (exit_px=97) -> giveback = 0.7
    giveback = post_flip_giveback_atr(direction=-1, align_open=100.0, exit_px=97.0,
                                      atr=10.0, post_align_mfe_atr=1.0)
    assert giveback == pytest.approx(0.7)


def test_post_flip_giveback_zero_when_exit_is_adverse_not_favorable():
    # short: exit_px above align_open (adverse) -> realized floors at 0, all giveback
    giveback = post_flip_giveback_atr(direction=-1, align_open=100.0, exit_px=105.0,
                                      atr=10.0, post_align_mfe_atr=0.8)
    assert giveback == pytest.approx(0.8)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

"""Deterministic tests for the excursion math, on synthetic bars.

Synthetic rather than sampled: the properties under test -- direction mirroring,
the difference between the two giveback methods, and landmarks already held at
confirmation -- are exactly the ones a spot check on real data would miss.
"""
from __future__ import annotations

import numpy as np
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    MarketData, RegimeIndex,
)
from studies.confirmation_economics_excursion_map.implementation.panel import walk

NS = 1_000_000_000


def market(highs, lows, closes=None, opens=None):
    n = len(highs)
    ts = np.arange(n, dtype=np.int64) * NS
    cl = np.asarray(closes if closes is not None else highs, dtype=float)
    op = np.asarray(opens if opens is not None else highs, dtype=float)
    return MarketData(ts=ts, open_=op, high=np.asarray(highs, float),
                      low=np.asarray(lows, float), close=cl,
                      day_close_ns=np.full(n, ts[-1], dtype=np.int64))


def regimes(pairs):
    return RegimeIndex(start_ns=np.asarray([p[0] for p in pairs], dtype=np.int64),
                       direction=np.asarray([p[1] for p in pairs], dtype=np.int64))


def row(direction=1, price=100.0, atr=1.0):
    return {"regime_id": "R", "population": "test", "direction": direction,
            "entry_year": 2023, "checkpoint_decision_ns": 0,
            "checkpoint_reference_price": price, "atr_at_checkpoint": atr,
            "seconds_from_regime_start": 900.0, "probability": 0.6}


def test_confirmation_economics_uses_the_confirm_bar_close():
    # LONG. Confirms at bar 2 whose close is 100.5 -> +0.5 ATR at confirmation,
    # but the bar high reached 101.0, so MFE-to-confirm is +1.0.
    m = market(highs=[100.2, 100.6, 101.0, 101.0, 101.0],
               lows=[99.8, 99.9, 100.3, 100.3, 100.3],
               closes=[100.0, 100.4, 100.5, 100.8, 100.8])
    r = regimes([(2 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["confirmed"] is True
    assert w["return_at_confirm_atr"] == pytest.approx(0.5)
    assert w["mfe_to_confirm_atr"] == pytest.approx(1.0)
    assert w["giveback_at_confirm_atr"] == pytest.approx(0.5)
    assert w["confirm_close_price"] == pytest.approx(100.5)


def test_long_and_short_mirror_exactly():
    m_long = market(highs=[101.0, 102.0, 103.0], lows=[99.5, 100.5, 101.5],
                    closes=[100.5, 101.5, 102.5])
    # Mirror around 100: high <-> low reflected.
    m_short = market(highs=[100.5, 99.5, 98.5], lows=[99.0, 98.0, 97.0],
                     closes=[99.5, 98.5, 97.5])
    r_long = regimes([(1 * NS, 1), (9 * NS, -1)])
    r_short = regimes([(1 * NS, -1), (9 * NS, 1)])

    a = walk(m_long, r_long, row(direction=1), "unconstrained")
    b = walk(m_short, r_short, row(direction=-1), "unconstrained")
    for k in ("return_at_confirm_atr", "mfe_to_confirm_atr", "mae_to_confirm_atr",
              "eventual_mfe_atr", "max_adverse_from_confirm_atr"):
        assert a[k] == pytest.approx(b[k]), k


# NOTE on bar accounting in these tests: the measurement window opens on the bar
# STRICTLY AFTER the entry timestamp, so market bar 0 is never in it. Every case
# below therefore confirms at bar 1 and puts the interesting price action at bars
# 2+. Getting this wrong is easy and was the cause of three false failures while
# these tests were being written.

def test_two_giveback_methods_differ_and_both_are_right():
    # Confirms at bar 1, close 100.0 -> mark 0. Runs to +2.0 at bar 2, then the
    # worst subsequent level is +0.5.
    #   Method A (from confirmation close): the path never goes BELOW the confirm
    #     close, so adverse-from-confirm is 0.
    #   Method B (from running extreme): peaked +2.0, fell to +0.5 -> 1.5.
    m = market(highs=[100.0, 100.0, 102.0, 100.6],
               lows=[100.0, 100.0, 100.5, 100.5],
               closes=[100.0, 100.0, 101.5, 100.5])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["return_at_confirm_atr"] == pytest.approx(0.0)
    assert w["max_adverse_from_confirm_atr"] == pytest.approx(0.0)
    assert w["max_giveback_from_extreme_atr"] == pytest.approx(1.5)


def test_giveback_not_overstated_when_bar_low_is_above_entry():
    # Regression: flooring the bar's worst level at zero would report giveback of
    # 2.0 here instead of the correct 1.6, because the pullback low (100.4) is
    # still ABOVE the entry price.
    m = market(highs=[100.0, 100.0, 102.0, 100.5],
               lows=[100.0, 100.0, 100.4, 100.4],
               closes=[100.0, 100.0, 101.0, 100.4])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")
    assert w["max_giveback_from_extreme_atr"] == pytest.approx(1.6)


def test_landmark_already_held_at_confirmation_is_excluded():
    # MFE reaches +1.0 BEFORE the flip, which confirms at bar 2.
    m = market(highs=[101.0, 101.0, 100.6, 100.7], lows=[99.9, 99.9, 100.2, 100.2],
               closes=[100.8, 100.9, 100.5, 100.6])
    r = regimes([(2 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["lmp1_00_already_at_confirm"] is True
    assert w["lmp1_00_reached_after_confirm"] is False
    assert w["lmp1_00_adverse_from_confirm_atr"] is None


def test_landmark_first_touch_is_causal_and_retrace_precedes_it():
    # Confirms at bar 1 (mark 0). Dips 0.4 ATR below the confirm close at bar 2,
    # then runs to +1.6 at bar 3.
    m = market(highs=[100.0, 100.0, 99.8, 101.6],
               lows=[100.0, 100.0, 99.6, 99.8],
               closes=[100.0, 100.0, 99.7, 101.5])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["lmp1_50_reached_after_confirm"] is True
    # The 0.4 ATR dip happened before the landmark, so it must be captured.
    assert w["lmp1_50_adverse_from_confirm_atr"] == pytest.approx(0.4)
    assert w["lmp1_50_ns"] == 3 * NS
    # ... and a landmark never reached carries no retrace at all.
    assert w["lmp3_00_reached_after_confirm"] is False
    assert w["lmp3_00_adverse_from_confirm_atr"] is None


def test_constrained_mode_truncates_at_the_stop_and_unconstrained_does_not():
    # Confirms at bar 0, then collapses through the 1 ATR entry stop at bar 2,
    # then recovers hard. Constrained must not see the recovery.
    m = market(highs=[100.1, 100.0, 99.5, 104.0], lows=[100.0, 99.5, 98.9, 99.0],
               closes=[100.0, 99.6, 99.0, 103.5])
    r = regimes([(0, 1), (9 * NS, -1)])
    c = walk(m, r, row(direction=1), "constrained")
    u = walk(m, r, row(direction=1), "unconstrained")

    assert c["terminal_label_constrained"] == "CONFIRMED_THEN_STOPPED"
    assert c["eventual_mfe_atr"] < 1.0
    assert u["eventual_mfe_atr"] == pytest.approx(4.0)
    # The canonical label rides on both rows so grouping works in either mode.
    assert u["terminal_label_constrained"] == "CONFIRMED_THEN_STOPPED"


def test_floor_only_placeable_below_current_open_profit():
    # Confirms at bar 1, close 100.5 -> mark +0.5 ATR, so a +0.75 floor is not
    # placeable (it would already be through the market) and +0.25 is.
    m = market(highs=[100.0, 100.6, 100.7, 100.8],
               lows=[100.0, 100.4, 100.0, 99.0],
               closes=[100.0, 100.5, 100.2, 99.2])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["return_at_confirm_atr"] == pytest.approx(0.5)

    assert w["floorp0_75_placeable"] is False
    assert w["floorp0_75_touched"] is None
    assert w["floorp0_25_placeable"] is True
    assert w["floorp0_25_touched"] is True


def test_same_bar_stop_and_confirm_is_flagged_ambiguous():
    m = market(highs=[100.1, 100.1], lows=[100.0, 98.9], closes=[100.0, 99.0])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "constrained")
    assert w["ambiguous_stop_confirm"] is True
    assert w["terminal_label_constrained"] == "STOPPED_BEFORE_CONFIRM"


def test_invalid_atr_is_dropped_not_silently_zeroed():
    m = market(highs=[100.1] * 3, lows=[99.9] * 3)
    r = regimes([(1 * NS, 1)])
    for atr in (0.0, -1.0, float("nan")):
        assert walk(m, r, row(atr=atr), "unconstrained") is None


def test_transition_clock_resets_at_confirmation_when_landmark_already_held():
    # Regression for lookahead-auditor pass 1 CRITICAL 1. MFE is already +1.5 ATR
    # at the flip; the path then pulls back hard before running to +2.0. The
    # transition giveback must include that pullback, which it does only if the
    # clock resets at confirmation rather than at the later re-touch of +1.5.
    m = market(highs=[100.0, 101.5, 100.2, 101.6, 102.1],
               lows=[100.0, 100.4, 100.1, 100.3, 101.0],
               closes=[100.0, 101.4, 100.2, 101.5, 102.0])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    w = walk(m, r, row(direction=1), "unconstrained")

    assert w["lmp1_50_already_at_confirm"] is True
    assert w["trans_p1_50_to_p2_00_eligible"] is True
    assert w["trans_p1_50_to_p2_00_reached"] is True
    # Extreme 1.5 at confirmation, worst subsequent low 100.1 -> mark +0.1,
    # so the giveback before +2.0 is 1.4. Starting the clock at the re-touch
    # would have reported ~0.
    assert w["trans_p1_50_to_p2_00_giveback_atr"] == pytest.approx(1.4)


def test_landmark_on_the_stop_bar_is_ambiguous_and_not_credited():
    # Regression for pass 1 CRITICAL 2. Bar 3 both reaches +1.5 and breaches the
    # 1 ATR entry stop. Ordering is unknowable from OHLC, so the conservative
    # bound refuses the landmark and flags it.
    m = market(highs=[100.0, 100.0, 100.1, 101.6],
               lows=[100.0, 100.0, 99.9, 98.9],
               closes=[100.0, 100.0, 100.0, 99.0])
    r = regimes([(1 * NS, 1), (9 * NS, -1)])
    c = walk(m, r, row(direction=1), "constrained")

    assert c["lmp1_50_ambiguous_with_stop"] is True
    assert c["lmp1_50_reached_after_confirm"] is False
    assert c["n_ambiguous_stop_landmark"] >= 1
    assert c["has_same_bar_ambiguity"] is True

    # Unconstrained mode has no stop in force, so there is no collision at all.
    u = walk(m, r, row(direction=1), "unconstrained")
    assert u["lmp1_50_ambiguous_with_stop"] is False
    assert u["lmp1_50_reached_after_confirm"] is True


def test_stopped_before_confirmation_yields_no_confirmation_economics():
    # The stop fires at bar 2, the flip only lands at bar 3. Neither mode may
    # report confirmation economics: unconstrained removes the stop only AFTER
    # confirmation, which this trade never reached.
    m = market(highs=[100.0, 100.0, 99.5, 101.0],
               lows=[100.0, 99.8, 98.9, 100.0],
               closes=[100.0, 99.9, 99.0, 100.9])
    r = regimes([(3 * NS, 1), (9 * NS, -1)])
    for mode in ("constrained", "unconstrained"):
        w = walk(m, r, row(direction=1), mode)
        assert w["terminal_label_constrained"] == "STOPPED_BEFORE_CONFIRM"
        assert w["confirmed"] is False
        assert w["measurable_post_confirm"] is False
        assert "return_at_confirm_atr" not in w

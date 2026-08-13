"""Executable coverage for the conditional rule and the verdict logic.

`lookahead-auditor` pass 2 referred the absence of these: the study's gates run
only on the full 8,950-arm population, which proves the aggregate but cannot
demonstrate the *mechanics* on a case whose answer is known by construction.
These tests use synthetic paths where the correct behaviour is arithmetic.

The FULL-lifecycle parity claim is NOT retested here -- gate V2 already checks it
against the accepted `walks.py::continuation_label` on every one of the 8,950
arms, which is a stronger statement than any fixture.
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    MarketData, RegimeIndex,
)
from studies.p90_5s_regime_impulse.implementation.regime_5s import Regime5s
from studies.p90_conditional_losing_5s_exit.implementation.policy import (
    FINAL_FLIP_EXIT_LOSER, FINAL_FLIP_EXIT_WINNER, LOSING_5S_FLIP_EXIT,
    STOPPED_BEFORE_CONFIRM, adverse_flip_times, simulate,
)
from studies.p90_conditional_losing_5s_exit.implementation.validate import (
    determine_verdict,
)

NS = 1_000_000_000
T0 = 1_600_000_000 * NS          # an arbitrary 5s-aligned origin
DAY_CLOSE = T0 + 3600 * NS


def market_from(closes: list[float], highs=None, lows=None) -> MarketData:
    """1s bars at T0+1s, T0+2s, ... with open == previous close."""
    n = len(closes)
    ts = np.array([T0 + (i + 1) * NS for i in range(n)], dtype=np.int64)
    close = np.array(closes, dtype=float)
    open_ = np.concatenate([[closes[0]], close[:-1]])
    high = np.array(highs if highs is not None else np.maximum(open_, close), dtype=float)
    low = np.array(lows if lows is not None else np.minimum(open_, close), dtype=float)
    return MarketData(ts=ts, open_=open_, high=high, low=low, close=close,
                      day_close_ns=np.full(n, DAY_CLOSE, dtype=np.int64))


def regimes_none() -> RegimeIndex:
    """No further regime starts -- isolates the rule from lifecycle exits."""
    return RegimeIndex(start_ns=np.array([], dtype=np.int64),
                       direction=np.array([], dtype=np.int64))


def r5_with(flips: list[tuple[int, int]]) -> Regime5s:
    return Regime5s(pl.DataFrame(
        {"close_ts": [f[0] for f in flips], "regime": [f[1] for f in flips]},
        schema={"close_ts": pl.Int64, "regime": pl.Int8}))


def run(closes, flips, *, direction=-1, stop=1.00, conditional=True, **kw):
    return simulate(market_from(closes), regimes_none(), r5_with(flips),
                    T0, direction, atr=1.0, stop_atr=stop,
                    conditional=conditional, **kw)


# ------------------------------------------------------- the frozen threshold


# `market_from` sets open_[0] == closes[0], and entry fills at that open, so the
# FIRST close is the entry price and everything after it is the trade's P&L.
# Excursions are kept at 0.5 ATR so the 1.00 ATR stop never fires and the
# conditional rule is tested in isolation. (At 1.0 the stop resolves first,
# which is correct behaviour but tests something else.)
IN_PROFIT_SHORT = [100.0] + [99.5] * 9     # short entered at 100, price fell 0.5
LOSING_SHORT = [100.0] + [100.5] * 9       # short entered at 100, price rose 0.5


def test_ignores_adverse_flip_while_at_or_above_entry():
    """A SHORT in profit must survive an adverse flip. This is the hypothesis."""
    res = run(IN_PROFIT_SHORT, flips=[(T0 + 5 * NS, +1)])
    assert res["outcome"] != LOSING_5S_FLIP_EXIT
    assert res["n_adverse_flips"] == 1
    assert res["n_losing_flips"] == 0


def test_exits_on_adverse_flip_while_below_entry():
    res = run(LOSING_SHORT, flips=[(T0 + 5 * NS, +1)])
    assert res["outcome"] == LOSING_5S_FLIP_EXIT
    assert res["fired_flip_number"] == 1
    assert res["return_at_fire_atr"] < 0


def test_threshold_is_strict_zero_not_a_band():
    """current_return_atr == 0 is NOT losing -- the frozen rule is `< 0`."""
    res = run([100.0] * 10, flips=[(T0 + 5 * NS, +1)])
    assert res["outcome"] != LOSING_5S_FLIP_EXIT
    assert res["n_losing_flips"] == 0


def test_long_side_is_mirrored():
    # LONG entered at 100, price falls -> losing at the adverse (bearish) flip
    res = run(IN_PROFIT_SHORT, flips=[(T0 + 5 * NS, -1)], direction=+1)
    assert res["outcome"] == LOSING_5S_FLIP_EXIT
    res_ok = run(LOSING_SHORT, flips=[(T0 + 5 * NS, -1)], direction=+1)
    assert res_ok["outcome"] != LOSING_5S_FLIP_EXIT


# ---------------------------------------------------------- repeated flips


def test_tolerates_profitable_flips_then_fires_on_the_first_losing_one():
    """The brief's worked example: ignore, ignore, then exit."""
    # entry 100; index 4 -> 99.5 (+0.5), index 14 -> 99.75 (+0.25), index 24 -> 100.5 (-0.5)
    closes = [100.0] + [99.5] * 9 + [99.75] * 10 + [100.5] * 10
    flips = [(T0 + 5 * NS, +1), (T0 + 10 * NS, -1),      # flip 1: +1.0, ignore
             (T0 + 15 * NS, +1), (T0 + 20 * NS, -1),     # flip 2: +0.5, ignore
             (T0 + 25 * NS, +1)]                          # flip 3: -1.0, EXIT
    res = run(closes, flips)
    assert res["outcome"] == LOSING_5S_FLIP_EXIT
    assert res["n_adverse_flips"] == 3
    assert res["fired_flip_number"] == 3, "must fire on the THIRD adverse flip"
    assert res["exit_ns"] == T0 + 26 * NS


def test_fires_on_the_first_losing_flip_not_a_later_one():
    closes = [100.0] + [100.5] * 20
    flips = [(T0 + 5 * NS, +1), (T0 + 10 * NS, -1), (T0 + 15 * NS, +1)]
    res = run(closes, flips)
    assert res["fired_flip_number"] == 1


def test_adverse_flip_times_selects_only_counter_direction_buckets():
    r5 = r5_with([(T0 + 5 * NS, +1), (T0 + 10 * NS, -1), (T0 + 15 * NS, +1)])
    got = adverse_flip_times(r5, T0, T0 + 30 * NS, direction=-1)
    assert got.tolist() == [T0 + 5 * NS, T0 + 15 * NS]


# ------------------------------------------------------------- causal fills


def test_conditional_exit_fills_strictly_after_the_flip_becomes_known():
    res = run(LOSING_SHORT, flips=[(T0 + 5 * NS, +1)])
    assert res["exit_ns"] > T0 + 5 * NS, "fill must post-date the flip's close_ts"
    assert res["exit_ns"] == T0 + 6 * NS, "fill is the very next 1s bar"


def test_entry_fills_after_the_decision_not_at_it():
    res = run(LOSING_SHORT, flips=[(T0 + 5 * NS, +1)])
    assert res["entry_ns"] > T0
    assert res["entry_ns"] == T0 + NS


def test_stop_trigger_price_is_never_credited():
    """Stop fills at the NEXT bar's open, which may be worse than the level."""
    closes = [100.0, 100.0, 102.0, 105.0, 105.0]
    res = run(closes, flips=[], stop=1.00, conditional=False)
    assert res["outcome"] == STOPPED_BEFORE_CONFIRM
    # triggered on the 102.0 bar; filled at the next bar's open (102.0 -> 105.0)
    assert res["exit_price"] == pytest.approx(102.0)
    assert res["gross_atr"] < -1.0, "adverse fill worse than the 1.00 ATR level"


def test_stop_wins_a_same_bar_collision_with_the_conditional_exit():
    """SPEC 4.3: ties resolve adversely."""
    closes = [100.0, 100.0, 100.0, 100.0, 102.0, 102.0, 102.0]
    # flip at T0+5s -> mark bar is index 4 (path_init_ns == T0+5s), price 102
    res = run(closes, flips=[(T0 + 5 * NS, +1)], stop=1.00)
    assert res["outcome"] == STOPPED_BEFORE_CONFIRM
    assert res["ambiguous"] is True


# -------------------------------------------------------- baseline isolation


def test_baseline_never_emits_the_conditional_label():
    res = run(LOSING_SHORT, flips=[(T0 + 5 * NS, +1)], conditional=False)
    assert res["outcome"] != LOSING_5S_FLIP_EXIT
    assert res["n_adverse_flips"] == 1, "flips are still COUNTED for Phase 1"


def test_a_flip_with_no_exactly_timestamped_bar_is_dropped_not_snapped():
    """NOTE N2: exact `path_init_ns == close_ts` matching, the safe choice."""
    res = run(LOSING_SHORT[:3], flips=[(T0 + 50 * NS, +1)])   # beyond the feed
    assert res["n_adverse_flips"] == 0
    assert res["outcome"] != LOSING_5S_FLIP_EXIT


# ------------------------------------------------------------ path landmarks


def test_adverse_landmarks_record_first_reach_of_each_level():
    closes = [100.0, 100.5, 100.8, 101.5, 101.5]
    res = run(closes, flips=[], stop=5.0, conditional=False)
    assert res["adverse_075_ns"] == T0 + 3 * NS   # first bar with MAE >= 0.75
    assert res["adverse_100_ns"] == T0 + 4 * NS   # first bar with MAE >= 1.00


def test_landmarks_are_none_when_the_level_is_never_reached():
    res = run([99.0] * 5, flips=[], stop=5.0, conditional=False)
    assert res["adverse_075_ns"] is None
    assert res["adverse_100_ns"] is None


# ------------------------------------------------------------ placebo counts


def test_placebo_counts_unreachable_draws_rather_than_dropping_them():
    """`p_unreached` is only computable if the drops are counted."""
    res = run(LOSING_SHORT[:5], flips=[], conditional=True,
              placebo_times_s=np.array([2.0, 3.0, 900.0, 1000.0]))
    assert res["n_placebo_candidates"] == 4
    assert res["n_placebo_unreached"] == 2, "the two far-future draws"


def test_placebo_times_are_anchored_on_entry_not_the_arm():
    """NOTE N1: the pool is measured from entry_ns, so the draws must be too."""
    res = run(LOSING_SHORT, flips=[], conditional=True,
              placebo_times_s=np.array([4.0]))
    # entry_ns == T0 + 1s, so tau=4s lands at T0+5s and fills at T0+6s.
    # Anchored on arm_ns it would have landed at T0+4s and filled at T0+5s.
    assert res["exit_ns"] == T0 + 6 * NS


# --------------------------------------------------------------- verdict logic


def _verdict(delta, excludes_zero, beats_placebo, years=5, interception=0.9):
    gates = [{"gate": "V1", "pass": True}]
    econ = {"COND_1.00": {"max_dd_atr": 1.0}, "BASELINE_1.00": {"max_dd_atr": 2.0},
            "COND_0.75": {"max_dd_atr": 9.0}, "BASELINE_0.75": {"max_dd_atr": 1.0}}
    deltas = {"COND_1.00": {"delta_per_arm": delta, "delta_ci_low": -1.0,
                            "delta_ci_high": 1.0,
                            "delta_ci_excludes_zero": excludes_zero},
              "COND_0.75": {"delta_per_arm": delta - 1, "delta_ci_low": -1.0,
                            "delta_ci_high": 1.0, "delta_ci_excludes_zero": False}}
    harvest = pl.DataFrame([{"policy": "COND_1.00", "interception_pct": interception}])
    conf = pl.DataFrame([{"group": "ALL", "ppv": 0.66, "prevalence": 0.48}])
    by_year = pl.concat([
        pl.DataFrame([{"policy": "COND_1.00", "entry_year": y,
                       "exp_per_arm_net": 1.0 if i < years else -1.0}
                      for i, y in enumerate(range(2021, 2026))]),
        pl.DataFrame([{"policy": "BASELINE_1.00", "entry_year": y,
                       "exp_per_arm_net": 0.0} for y in range(2021, 2026)])])
    by_side = pl.concat([
        pl.DataFrame([{"policy": "COND_1.00", "side": s, "exp_per_arm_net": 1.0}
                      for s in ("LONG", "SHORT")]),
        pl.DataFrame([{"policy": "BASELINE_1.00", "side": s, "exp_per_arm_net": 0.0}
                      for s in ("LONG", "SHORT")])])
    placebo = {"delta_per_arm": -1.0 if beats_placebo else -0.001,
               "delta_ci_excludes_zero": beats_placebo}
    return determine_verdict(gates=gates, econ=econ, deltas=deltas,
                             harvest=harvest, destruction=pl.DataFrame(),
                             confusion=conf, by_year=by_year, by_side=by_side,
                             placebo_delta=placebo)["verdict"]


def test_positive_point_estimate_with_a_ci_spanning_zero_is_not_an_improvement():
    """The SPEC 8.2 amendment. This is the case that produced the real G4."""
    assert _verdict(delta=0.004, excludes_zero=False, beats_placebo=False) \
        == "G4_NO_USEFUL_EDGE"


def test_g2_requires_the_loss_state_rule_to_actually_pay():
    assert _verdict(delta=1.0, excludes_zero=True, beats_placebo=False) \
        == "G2_LOSS_STATE_WORKS_5S_FLIP_DOES_NOT"


def test_g3_is_unreachable_while_the_placebo_is_unbeaten():
    """Documented in SPEC 8.2: the placebo governs attribution."""
    assert _verdict(delta=-1.0, excludes_zero=False, beats_placebo=False,
                    interception=0.99) == "G4_NO_USEFUL_EDGE"


def test_g3_becomes_reachable_once_the_placebo_is_beaten():
    assert _verdict(delta=-1.0, excludes_zero=False, beats_placebo=True,
                    interception=0.99) == "G3_5S_INFORMATIVE_THRESHOLD_TOO_CRUDE"


def test_g1_needs_every_condition_including_the_placebo():
    assert _verdict(delta=1.0, excludes_zero=True, beats_placebo=True) \
        == "G1_CONDITIONAL_5S_FAILURE_EXIT_WORKS"


def test_a_failed_gate_aborts_regardless_of_economics():
    out = determine_verdict(
        gates=[{"gate": "V1", "pass": False}], econ={}, deltas={},
        harvest=pl.DataFrame(), destruction=pl.DataFrame(),
        confusion=pl.DataFrame(), by_year=pl.DataFrame(),
        by_side=pl.DataFrame(), placebo_delta={})
    assert out["verdict"] == "ABORT_LINEAGE_FAILURE"

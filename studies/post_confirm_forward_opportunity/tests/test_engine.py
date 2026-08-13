"""Deterministic tests on synthetic windows.

These exist to pin the causal boundary and the race resolution against
hand-computed paths, so a refactor that silently widens either one fails here
rather than in an audit six phases later.
"""
from __future__ import annotations

import numpy as np
import pytest

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from studies.post_confirm_forward_opportunity.analysis.buckets import bucketize
from studies.post_confirm_forward_opportunity.implementation.engine import (
    ADVERSE, DENSE_OFFSETS_S, FAVORABLE, REQUIRED_OFFSETS_S, SPARSE_OFFSETS_S,
    TradeForward, UNRESOLVED, _touch, tag,
)


class FakeMarket:
    def __init__(self, n, close_ns):
        self.n = n
        self.open_ = np.zeros(n)
        self.day_close_ns = np.full(n, close_ns)


class FakeWindow:
    """Minimal stand-in exposing exactly what TradeForward reads."""

    def __init__(self, bar_hi, bar_lo, mark, ci, nat_i, unc_i, t0=0):
        n = len(mark)
        self.bar_hi = np.array(bar_hi, dtype=float)
        self.bar_lo = np.array(bar_lo, dtype=float)
        self.mark = np.array(mark, dtype=float)
        self.ts = np.arange(n, dtype=np.int64) * NS + t0
        self.run_mfe = np.maximum.accumulate(np.maximum(self.bar_hi, 0.0))
        self.run_mae = np.maximum.accumulate(np.maximum(-self.bar_lo, 0.0))
        prev = np.concatenate(([-np.inf], self.run_mfe[:-1]))
        self.new_ext = self.bar_hi > prev
        self.last_ext = np.maximum.accumulate(
            np.where(self.new_ext, np.arange(n), -1))
        self.ci, self.nat_i, self.unc_i = ci, nat_i, unc_i
        self.nat_fill_next = False
        self.nat_kind, self.unc_kind = "OPPOSING_FLIP", "OPPOSING_FLIP"
        self.confirm_ns = int(self.ts[ci])
        self.atr, self.d, self.px, self.start = 1.0, 1, 100.0, 0
        self.market = FakeMarket(n, int(self.ts[-1]) + NS)

    def realise(self, i, fill_next):        # mark-to-close; fills tested elsewhere
        return float(self.mark[i])

    def index_at_offset(self, seconds):
        hit = np.flatnonzero(self.ts >= self.confirm_ns + int(seconds) * NS)
        return int(hit[0]) if hit.size else -1


def _fwd(w):
    return TradeForward(w, {"regime_id": "T", "entry_year": 2021, "side": "LONG"})


# ------------------------------------------------------------------ grid

def test_dense_grid_is_exactly_the_frozen_forty_offsets():
    assert DENSE_OFFSETS_S == tuple(range(15, 601, 15))
    assert len(DENSE_OFFSETS_S) == 40


def test_every_required_offset_is_a_member_of_the_dense_grid():
    for L in REQUIRED_OFFSETS_S:
        assert L in DENSE_OFFSETS_S


def test_sparse_offsets_are_all_beyond_the_dense_horizon():
    assert all(L > max(DENSE_OFFSETS_S) for L in SPARSE_OFFSETS_S)


# ---------------------------------------------------------------- _touch

def test_touch_returns_first_index_at_or_above_threshold():
    assert _touch(np.array([0.0, 0.3, 0.7, 1.2]), 0.5) == 2
    assert _touch(np.array([0.0, 0.3, 0.7, 1.2]), 0.3) == 1


def test_touch_returns_minus_one_when_never_reached():
    assert _touch(np.array([0.0, 0.1]), 5.0) == -1


# -------------------------------------------------------- causal boundary

def test_state_at_observation_ignores_every_later_bar():
    """The defining invariant: mutating the future cannot move the state."""
    hi = [0.0, 0.5, 0.9, 0.4, 0.2, 0.1]
    lo = [0.0, -0.1, 0.2, -0.3, -0.5, -0.6]
    mk = [0.0, 0.4, 0.8, 0.1, -0.2, -0.4]
    a = _fwd(FakeWindow(hi, lo, mk, ci=1, nat_i=5, unc_i=5)).state_at(3)
    hi2 = hi[:4] + [99.0, 99.0]
    lo2 = lo[:4] + [-99.0, -99.0]
    mk2 = mk[:4] + [99.0, -99.0]
    b = _fwd(FakeWindow(hi2, lo2, mk2, ci=1, nat_i=5, unc_i=5)).state_at(3)
    assert a == b


def test_forward_labels_ignore_the_observation_bar_and_everything_before():
    hi = [0.0, 0.5, 0.9, 0.4, 1.6, 1.7]
    lo = [0.0, -0.1, 0.2, -0.3, -0.5, -0.6]
    mk = [0.0, 0.4, 0.8, 0.1, 1.5, 1.6]
    a = _fwd(FakeWindow(hi, lo, mk, ci=1, nat_i=5, unc_i=5)).forward_at(3)
    # rewrite the entire past; only mark[j] is a legitimate shared reference
    hi2 = [9.0, 9.0, 9.0, 0.4, 1.6, 1.7]
    lo2 = [-9.0, -9.0, -9.0, -0.3, -0.5, -0.6]
    b = _fwd(FakeWindow(hi2, lo2, mk, ci=1, nat_i=5, unc_i=5)).forward_at(3)
    for k in ("forward_mfe_atr", "forward_mae_atr", "race_0_5_before_0_5",
              "time_to_forward_mfe_s"):
        assert a[k] == b[k], k


def test_another_favorable_extreme_is_relative_to_running_max_not_current_price():
    # forward high 0.9 never exceeds the running max of 1.0 already set at bar 1
    w = FakeWindow(bar_hi=[0.0, 1.0, 0.3, 0.9], bar_lo=[0.0, 0.5, 0.0, 0.4],
                   mark=[0.0, 0.9, 0.2, 0.8], ci=1, nat_i=3, unc_i=3)
    assert _fwd(w).forward_at(2)["another_favorable_extreme"] is False


# ---------------------------------------------------------------- races

def test_favorable_wins_when_it_touches_first():
    w = FakeWindow(bar_hi=[0.0, 0.0, 0.6, 0.6], bar_lo=[0.0, 0.0, 0.0, -0.6],
                   mark=[0.0, 0.0, 0.5, 0.0], ci=0, nat_i=3, unc_i=3)
    assert _fwd(w).forward_at(1)["race_0_5_before_0_5"] == FAVORABLE


def test_adverse_wins_when_it_touches_first():
    w = FakeWindow(bar_hi=[0.0, 0.0, 0.0, 0.6], bar_lo=[0.0, 0.0, -0.6, -0.6],
                   mark=[0.0, 0.0, -0.5, 0.5], ci=0, nat_i=3, unc_i=3)
    assert _fwd(w).forward_at(1)["race_0_5_before_0_5"] == ADVERSE


def test_same_bar_collision_resolves_adverse_and_is_flagged():
    w = FakeWindow(bar_hi=[0.0, 0.0, 0.6], bar_lo=[0.0, 0.0, -0.6],
                   mark=[0.0, 0.0, 0.0], ci=0, nat_i=2, unc_i=2)
    r = _fwd(w).forward_at(1)
    assert r["race_0_5_before_0_5"] == ADVERSE
    assert r["race_0_5_before_0_5_ambiguous"] is True


def test_race_is_unresolved_when_neither_barrier_is_hit_before_the_terminal():
    w = FakeWindow(bar_hi=[0.0, 0.0, 0.1], bar_lo=[0.0, 0.0, -0.1],
                   mark=[0.0, 0.0, 0.0], ci=0, nat_i=2, unc_i=2)
    r = _fwd(w).forward_at(1)
    assert r["race_0_5_before_0_5"] == UNRESOLVED
    assert r["race_0_5_before_0_5_ambiguous"] is False


def test_barriers_are_relative_to_current_price_not_to_entry():
    """At mark +2.0, a move to +2.4 is NOT a +0.5 favorable touch.

    Entry-relative excursion of 2.4 ATR is large; relative to the observation
    price it is 0.4 and resolves nothing. A drop to 1.6 is likewise only 0.4
    adverse. Both barriers sit outside the bar, so the race is UNRESOLVED.
    """
    w = FakeWindow(bar_hi=[0.0, 2.0, 2.4], bar_lo=[0.0, 1.9, 1.6],
                   mark=[0.0, 2.0, 2.4], ci=0, nat_i=2, unc_i=2)
    r = _fwd(w).forward_at(1)
    assert r["race_0_5_before_0_5"] == UNRESOLVED
    assert r["secs_to_up_0_5"] is None
    assert r["secs_to_dn_0_5"] is None


def test_terminal_observation_yields_no_forward_bars():
    w = FakeWindow(bar_hi=[0.0, 0.5], bar_lo=[0.0, -0.5], mark=[0.0, 0.3],
                   ci=0, nat_i=1, unc_i=1)
    r = _fwd(w).forward_at(1)
    assert r["has_forward_bars"] is False
    assert r["forward_mfe_atr"] == 0.0
    assert r["race_0_5_before_0_5"] == UNRESOLVED


# ----------------------------------------------------------- economics

def test_continuation_value_plus_exit_now_reconstructs_the_natural_return():
    w = FakeWindow(bar_hi=[0.0, 0.8, 1.4, 1.4], bar_lo=[0.0, -0.2, 0.3, -0.1],
                   mark=[0.0, 0.7, 1.2, 0.4], ci=1, nat_i=3, unc_i=3)
    f = _fwd(w)
    e = f.economics_at(2)
    assert e["cv_stop_live_atr"] + e["exit_now_fill_atr"] == pytest.approx(
        e["natural_return_stop_live_atr"])


def test_continuation_value_is_null_once_the_stop_live_terminal_has_passed():
    w = FakeWindow(bar_hi=[0.0, 0.8, 1.4, 1.4], bar_lo=[0.0, -0.2, 0.3, -0.1],
                   mark=[0.0, 0.7, 1.2, 0.4], ci=1, nat_i=2, unc_i=3)
    e = _fwd(w).economics_at(3)
    assert e["cv_stop_live_atr"] is None
    assert e["cv_unconstrained_atr"] is not None


# ------------------------------------------------------------- stall

def test_stall_clock_anchors_at_confirmation_until_a_post_confirm_extreme():
    # the only new extreme is at bar 1, which is BEFORE confirmation at bar 2
    w = FakeWindow(bar_hi=[0.0, 1.0, 0.2, 0.3], bar_lo=[0.0, 0.5, 0.0, 0.1],
                   mark=[0.0, 0.9, 0.1, 0.2], ci=2, nat_i=3, unc_i=3)
    s = _fwd(w).state_at(3)
    assert s["stall_armed"] is False
    assert s["seconds_since_last_favorable_extreme"] == 1.0     # from ci, not bar 1
    assert s["seconds_since_last_extreme_from_any"] == 2.0      # from bar 1


def test_stall_clock_runs_from_a_genuine_post_confirm_extreme_once_armed():
    w = FakeWindow(bar_hi=[0.0, 0.2, 1.0, 0.3, 0.4], bar_lo=[0.0] * 5,
                   mark=[0.0, 0.1, 0.9, 0.2, 0.3], ci=1, nat_i=4, unc_i=4)
    s = _fwd(w).state_at(4)
    assert s["stall_armed"] is True
    assert s["seconds_since_last_favorable_extreme"] == 2.0


# ------------------------------------------------------------ buckets

@pytest.mark.parametrize("value,expected", [
    (15.0, "0-15"), (15.5, "16-30"), (30.0, "16-30"),
    (90.0, "61-90"), (90.5, "91-120"), (120.0, "91-120"), (121.0, ">120"),
])
def test_stall_bucket_edges_belong_to_the_lower_bucket(value, expected):
    import polars as pl
    from studies.post_confirm_forward_opportunity.analysis.buckets import STALL_BUCKETS
    df = pl.DataFrame({"x": [value]}).with_columns(
        bucketize("x", STALL_BUCKETS, "b"))
    assert df["b"][0] == expected


def test_tag_matches_the_column_naming_used_by_the_race_fields():
    assert tag(0.25) == "0_25" and tag(0.5) == "0_5" and tag(1.0) == "1_0"

"""tracker.price_level.failed_breakout -- causal contract.

Layers:

* GOLDEN: hand-derived episode scenarios driven through ``step`` with explicit level inputs (every expected
  number is written out below);
* the binding through ``on_bar`` on real CT clock times: level finality (overnight / opening range usable only
  from the bar after the provider publishes them), session resets, no-lookahead;
* parity: a TEST-ONLY oracle that rebuilds the levels from the raw 1m tape (its own trading-day grouping, own RTH
  clock) and finds failed breakouts by FORWARD SCAN, compared event by event with the binding on a multi-day tape;
* integration: compile_study -> HostCore with ``outcome.stop_reference: fb.stop_reference_price`` and
  ``unit: structural`` arms: every candidate is an oracle event at its own bar close, the stop is the frozen sweep
  extreme moved by the buffer and tick-rounded away from the next-bar-open entry.

``python -m features.tests.test_price_level_failed_breakout --write-parity <json>`` writes the parity artifact.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pytest
import yaml

from features.trackers.price_level_failed_breakout import (
    ACCEPTED, ARMED, BREACHED, DEFAULT_LEVELS, FIELDS, UNARMED, UNAVAILABLE, PriceLevelFailedBreakoutBinding,
)
from research_workflow.host.interfaces import BarView

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
M = 60 * NS
CAP = "tracker.price_level.failed_breakout"
CT = ZoneInfo("America/Chicago")


def _ts(y, mo, d, h, mi) -> int:
    """UTC ns of a Chicago wall-clock minute."""
    return int(datetime(y, mo, d, h, mi, tzinfo=CT).timestamp()) * NS


def _bar(open_ts: int, o: float, h: float, l: float, c: float) -> BarView:
    return BarView("1m", open_ts, open_ts + M, o, h, l, c, 1.0)


# =========================================================================== GOLDEN (step with explicit levels)
S = _ts(2030, 1, 8, 10, 0)          # an RTH minute (10:00 CT); step() itself never reads the clock


def _b(i: int, o, h, l, c) -> BarView:
    return _bar(S + i * M, o, h, l, c)


def _fb(**params) -> PriceLevelFailedBreakoutBinding:
    return PriceLevelFailedBreakoutBinding(params, {"bars": "1m"})


def _run_steps(fb, rows, known, prev_close):
    """rows: [(i, o, h, l, c)]; returns the primary-field dict after each bar."""
    out = []
    for i, o, h, l, c in rows:
        fb.step(_b(i, o, h, l, c), known, prev_close, is_rth=True)
        out.append({f: getattr(fb, f) for f in FIELDS})
        prev_close = c
    return out


def test_resistance_same_bar_sweep_and_close_back():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.5, 100.75, 99.25, 99.75)], {"pdh": 100.0}, 99.5)[0]
    assert (r["event"], r["event_dir"], r["breach_dir"], r["event_level"], r["event_level_price"]) == (1, -1, 1, "pdh", 100.0)
    assert (r["stop_reference_price"], r["episode_extreme"], r["episode_bars"]) == (100.75, 100.75, 1)
    assert (r["episode_start_ts"], r["event_ts"], r["event_seq_level"], r["n_levels_fired"]) == (S, S + M, 1, 1)
    assert fb._episodes["pdh"].state == ARMED                     # the failure close re-arms


def test_support_is_the_mirror():
    fb = _fb()
    r = _run_steps(fb, [(0, 100.5, 100.75, 99.25, 100.25)], {"pdl": 100.0}, 100.5)[0]
    assert (r["event"], r["event_dir"], r["breach_dir"], r["event_level"], r["stop_reference_price"]) == (1, 1, -1, "pdl", 99.25)


def test_multi_bar_episode_extreme_includes_every_bar_and_the_failure_bar():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.75, 101.0, 99.75, 100.5),       # breach, holds above
                        (1, 100.5, 101.5, 100.25, 100.25),     # new high, still above
                        (2, 100.25, 101.75, 99.5, 99.75)],     # failure bar makes the extreme
                   {"pdh": 100.0}, 99.75)
    assert [x["event"] for x in r] == [0, 0, 1]
    assert fb._episodes["pdh"].state == ARMED
    assert (r[2]["stop_reference_price"], r[2]["episode_bars"], r[2]["episode_start_ts"]) == (101.75, 3, S)


def test_minimum_breach_is_required_to_start_an_episode():
    fb = _fb()                                                    # min_breach 0.5
    r = _run_steps(fb, [(0, 99.75, 100.25, 99.5, 99.75),         # only 0.25 above: no episode
                        (1, 99.75, 100.5, 99.5, 99.75)],          # exactly 0.5: same-bar sweep
                   {"pdh": 100.0}, 99.75)
    assert [x["event"] for x in r] == [0, 1]


def test_close_exactly_at_the_level_is_not_a_failure():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.75, 100.75, 99.75, 100.0)], {"pdh": 100.0}, 99.75)[0]
    assert r["event"] == 0 and fb._episodes["pdh"].state == BREACHED


def test_failure_at_the_deadline_counts_and_one_minute_later_is_accepted():
    rows = [(0, 99.75, 100.75, 99.75, 100.5)] + [(i, 100.5, 100.75, 100.25, 100.5) for i in (1, 2, 3)]
    fb = _fb()
    r = _run_steps(fb, rows + [(4, 100.5, 100.75, 99.5, 99.75)], {"pdh": 100.0}, 99.75)   # closes at S+5m
    assert r[-1]["event"] == 1 and r[-1]["episode_bars"] == 5
    fb = _fb()
    r = _run_steps(fb, rows + [(4, 100.5, 100.75, 100.25, 100.5),                         # holds at the deadline
                               (5, 100.5, 100.75, 99.5, 99.75),                          # back below: too late
                               (6, 99.75, 100.75, 99.5, 99.75)],                         # re-armed: a new sweep
                   {"pdh": 100.0}, 99.75)
    assert [x["event"] for x in r] == [0, 0, 0, 0, 0, 0, 1]
    assert (r[-1]["stop_reference_price"], r[-1]["episode_start_ts"], r[-1]["event_seq_level"]) == (100.75, S + 6 * M, 1)


def test_a_missing_minute_cannot_extend_an_episode():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.75, 100.75, 99.75, 100.5),
                        (6, 100.5, 100.75, 99.5, 99.75)],         # first bar after the gap closes past the deadline
                   {"pdh": 100.0}, 99.75)
    assert [x["event"] for x in r] == [0, 0]
    assert fb._episodes["pdh"].state == UNARMED or fb._episodes["pdh"].state == ACCEPTED


def test_repeated_breaches_each_fire_and_count():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.75, 100.75, 99.5, 99.75), (1, 99.75, 101.0, 99.5, 99.5), (2, 99.5, 99.75, 99.0, 99.25),
                        (3, 99.25, 100.5, 99.0, 99.0)], {"pdh": 100.0}, 99.75)
    assert [(x["event"], x["event_seq_level"], x["stop_reference_price"]) for x in r] == \
        [(1, 1, 100.75), (1, 2, 101.0), (0, None, None), (1, 3, 100.5)]


def test_a_level_first_seen_from_beyond_is_not_armed_until_a_close_back():
    fb = _fb()
    r = _run_steps(fb, [(0, 100.5, 101.0, 99.0, 99.0),           # prev close 100.5 above: not armed
                        (1, 99.0, 100.75, 98.75, 99.5)],          # prev close 99.0: armed, sweeps, fails
                   {"pdh": 100.0}, 100.5)
    assert [x["event"] for x in r] == [0, 1]


def test_missing_and_unfinished_levels_never_start_or_continue_an_episode():
    fb = _fb()
    fb.step(_b(0, 99.75, 100.75, 99.75, 100.5), {"pdh": 100.0}, 99.75, is_rth=True)
    assert fb._episodes["pdh"].state == BREACHED
    fb.step(_b(1, 100.5, 100.75, 99.5, 99.75), {"pdh": None}, 100.5, is_rth=True)        # level withdrawn
    assert fb.event == 0 and fb._episodes["pdh"].state == UNAVAILABLE
    fb.step(_b(2, 99.75, 100.75, 99.5, 99.75), {"pdh": float("nan")}, 99.75, is_rth=True)
    assert fb.event == 0 and fb._episodes["pdh"].state == UNAVAILABLE


def test_a_level_that_moves_under_an_episode_aborts_it():
    fb = _fb()
    fb.step(_b(0, 99.75, 100.75, 99.75, 100.5), {"pdh": 100.0}, 99.75, is_rth=True)
    fb.step(_b(1, 100.5, 100.75, 99.5, 99.75), {"pdh": 100.25}, 100.5, is_rth=True)      # new level, prev close above
    assert fb.event == 0 and fb._episodes["pdh"].state == UNARMED


def test_simultaneous_same_direction_failures_use_the_declared_priority():
    known = {"pdh": 100.0, "onh": 100.25, "orh": 99.75}
    fb = _fb()
    r = _run_steps(fb, [(0, 99.5, 101.0, 99.25, 99.5)], known, 99.5)[0]
    assert (r["event_level"], r["stop_reference_price"], r["n_levels_fired"]) == ("pdh", 101.0, 3)
    assert (r["pdh_event"], r["onh_event"], r["orh_event"]) == (1, 1, 1)
    fb = _fb(levels=["orh", "onh", "pdh"])
    r = _run_steps(fb, [(0, 99.5, 101.0, 99.25, 99.5)], known, 99.5)[0]
    assert (r["event_level"], r["event_level_price"]) == ("orh", 99.75)


def test_opposite_direction_failures_on_one_bar_are_a_conflict_not_an_event():
    fb = _fb()
    r = _run_steps(fb, [(0, 99.5, 100.75, 98.25, 99.5)], {"pdh": 100.0, "pdl": 99.0}, 99.5)[0]
    assert (r["event"], r["conflict"], r["n_levels_fired"], r["stop_reference_price"]) == (0, 1, 2, None)
    assert (r["pdh_event"], r["pdl_event"]) == (1, 1)


def test_untracked_levels_are_ignored():
    fb = _fb(levels=["orh", "orl"])
    r = _run_steps(fb, [(0, 99.5, 100.75, 99.25, 99.75)], {"pdh": 100.0}, 99.5)[0]
    assert r["event"] == 0 and r["pdh_event"] == 0


@pytest.mark.parametrize("params", [{"levels": []}, {"levels": ["pdh", "pdh"]}, {"levels": ["vwap"]},
                                    {"min_breach_points": 0}, {"max_episode_minutes": 0}, {"max_episode_minutes": 2.5}])
def test_invalid_parameters_are_refused(params):
    with pytest.raises(ValueError):
        _fb(**params)


# =========================================================================== on_bar: finality, sessions, clock
def _day(y, mo, d, *, pre: List[Tuple[float, float, float, float]], rth: List[Tuple[float, float, float, float]],
         prev_day: Optional[Tuple[int, int, int]] = None) -> List[BarView]:
    """Bars of one trading day: ``pre`` minutes from 17:00 CT of the previous calendar day, ``rth`` from 08:30 CT."""
    py, pm, pd_ = prev_day or (y, mo, d - 1)
    t = _ts(py, pm, pd_, 17, 0)
    out = [_bar(t + i * M, *x) for i, x in enumerate(pre)]
    t = _ts(y, mo, d, 8, 30)
    return out + [_bar(t + i * M, *x) for i, x in enumerate(rth)]


def _feed(fb, bars):
    trail = []
    for b in bars:
        fb.on_bar("bars", b)
        trail.append({f: getattr(fb, f) for f in FIELDS})
    return trail


def test_overnight_level_is_usable_only_after_the_first_rth_bar_publishes_it():
    # previous trading day (for a PDH far away) + overnight with high 100
    day1 = _day(2030, 1, 7, pre=[(90, 91, 89, 90)] * 3, rth=[(90, 92, 88, 90)] * 3, prev_day=(2030, 1, 6))
    day2 = _day(2030, 1, 8, pre=[(98, 100, 97, 99)] + [(99, 99.5, 98.5, 99)] * 3,
                rth=[(99, 100.75, 98.75, 99.5),            # 08:30-08:31 sweeps ONH: ONH not final yet
                     (99.5, 100.75, 99.0, 99.5)])           # 08:31-08:32: ONH final since 08:31 -> event
    fb = _fb()
    tr = _feed(fb, day1 + day2)
    assert tr[-2]["event"] == 0 and tr[-2]["onh_price"] == 100.0       # published at 08:31, usable from 08:31
    assert (tr[-1]["event"], tr[-1]["event_level"], tr[-1]["stop_reference_price"]) == (1, "onh", 100.75)
    assert tr[-1]["event_ts"] == _ts(2030, 1, 8, 8, 32)
    assert tr[-1]["pdh_price"] == 92.0                                  # the prior trading day's high


def test_opening_range_is_usable_only_after_its_final_bar():
    flat = (99.0, 99.5, 98.5, 99.0)
    rth = [(99.0, 100.0, 98.5, 99.0)] + [flat] * 29          # 08:30..09:00 bars -> ORH 100.0
    rth += [(99.0, 100.75, 98.75, 99.5)]                      # 09:00-09:01 closes at OR final instant: not usable
    rth += [(99.5, 100.75, 99.0, 99.5)]                       # 09:01-09:02: usable -> event
    bars = _day(2030, 1, 8, pre=[(99, 99.5, 98.5, 99)] * 2, rth=rth)
    fb = _fb(levels=["orh"])
    tr = _feed(fb, bars)
    assert tr[-3]["orh_available"] == 0 and tr[-2]["orh_available"] == 1 and tr[-2]["orh_price"] == 100.0
    assert tr[-2]["event"] == 0
    assert (tr[-1]["event"], tr[-1]["event_level"], tr[-1]["stop_reference_price"]) == (1, "orh", 100.75)


def test_first_rth_bar_arms_from_the_last_pre_rth_close():
    """Declared reset_policy: the reset clears state, not the arming input -- the first RTH bar arms on the last
    pre-RTH close. Prior-day high 92 (day 1); pre-RTH closes 91 (armed) vs 93 (not armed)."""
    day1 = _day(2030, 1, 7, pre=[(90, 91, 89, 90)] * 3, rth=[(90, 92, 88, 90)] * 3, prev_day=(2030, 1, 6))
    for pre_close, expect in ((91.0, 1), (93.0, 0)):
        day2 = _day(2030, 1, 8, pre=[(91, 91.5, 90.5, 91), (91, 93.5, 90.5, pre_close)],
                    rth=[(pre_close, 92.75, 90.75, 91.5)])          # sweeps PDH by 0.75, closes back below
        tr = _feed(_fb(levels=["pdh"]), day1 + day2)
        assert tr[-1]["event"] == expect, (pre_close, tr[-1])
        if expect:
            assert (tr[-1]["stop_reference_price"], tr[-1]["episode_start_ts"]) == (92.75, _ts(2030, 1, 8, 8, 30))


def test_episodes_do_not_survive_the_rth_close_or_the_next_session():
    pre = [(98, 100, 97, 99)] * 2
    rth_close = _ts(2030, 1, 8, 15, 14)
    bars = _day(2030, 1, 8, pre=pre, rth=[(99, 99.5, 98.5, 99)])
    bars += [_bar(rth_close, 99.0, 100.75, 99.0, 100.5),              # 15:14-15:15 RTH: breach ONH, holds
             _bar(rth_close + M, 100.5, 100.75, 99.0, 99.5)]           # 15:15-15:16 ETH: closes back -> nothing
    fb = _fb()
    tr = _feed(fb, bars)
    assert tr[-2]["onh_state"] == BREACHED and tr[-1]["event"] == 0 and tr[-1]["onh_state"] == UNAVAILABLE


def test_levels_equal_the_provider_snapshot():
    """The binding's level prices are the canonical provider's published <name>_price values at every bar close."""
    from features.trackers.generic_price_levels import GenericPriceLevelProvider
    from features.trackers.price_level_failed_breakout import LEVELS
    from utils.session_boundaries import is_rth_completed_bar_1m
    fb, ref = _fb(), GenericPriceLevelProvider()
    for b in _tape(days=3, seed=3):
        fb.on_bar("bars", b)
        ref.update_completed_bar(ts_avail=b.ts_init, open_px=b.open, high=b.high, low=b.low, close=b.close,
                                 is_rth=is_rth_completed_bar_1m(b.ts_init))
        snap = ref.snapshot(observation_ts=b.ts_init, reference_price=b.close, atr=0.0)
        assert {lvl: getattr(fb, f"{lvl}_price") for lvl in LEVELS} == {lvl: snap[f"{n}_price"] for lvl, (n, _s) in LEVELS.items()}


def test_fields_at_T_do_not_depend_on_later_bars():
    bars = _tape(days=3, seed=7)
    fb = _fb()
    full = _feed(fb, bars)
    rng = random.Random(99)
    for k in (400, 1700, 2900):
        alt = list(bars[:k + 1])
        px = alt[-1].close
        for b in bars[k + 1:]:                                       # an unrelated future
            c = px + rng.choice((-2.0, -1.0, 1.0, 2.0))
            alt.append(_bar(b.ts_event, px, max(px, c) + 0.5, min(px, c) - 0.5, c))
            px = c
        fb2 = _fb()
        part = _feed(fb2, alt)
        assert part[:k + 1] == full[:k + 1]


# =========================================================================== parity: test-only forward-scan oracle
def _tape(*, days: int, seed: int) -> List[BarView]:
    """Globex-like 1m tape from Sun 2030-01-06 17:00 CT: daily 16:00-17:00 CT halt, weekend closure, 0.25 ticks.
    A slow sinusoid + mean-reverting noise keeps price near prior levels so they get swept often."""
    rng = random.Random(seed)
    out: List[BarView] = []
    t = _ts(2030, 1, 6, 17, 0)
    end = t + days * 86400 * NS
    px, i = 20000.0, 0
    while t < end:
        lt = datetime.fromtimestamp(t / NS, tz=CT)
        halted = lt.hour == 16 or lt.weekday() == 5 or (lt.weekday() == 4 and lt.hour >= 16) or (lt.weekday() == 6 and lt.hour < 17)
        if not halted:
            target = 20000 + 40 * math.sin(2 * math.pi * i / 1700) + 12 * math.sin(2 * math.pi * i / 97)
            step = (target - px) * 0.08 + rng.gauss(0.0, 2.0)
            c = round((px + step) * 4) / 4
            h = max(px, c) + round(rng.random() * 6) / 4
            l = min(px, c) - round(rng.random() * 6) / 4
            out.append(_bar(t, px, h, l, c))
            px, i = c, i + 1
        t += M
    return out


def _is_rth(close_ts: int) -> bool:
    lt = datetime.fromtimestamp(close_ts / NS, tz=CT)
    mins = lt.hour * 60 + lt.minute + lt.second / 60.0
    return 8 * 60 + 30 < mins <= 15 * 60 + 15


def _tday(close_ts: int) -> str:
    lt = datetime.fromtimestamp(close_ts / NS, tz=CT)
    return (lt.date() + timedelta(days=1 if lt.hour >= 17 else 0)).isoformat()


def _oracle_levels(bars: List[BarView]) -> Dict[str, Dict[str, Tuple[Optional[float], Optional[int]]]]:
    """{trading_day: {lvl: (price, usable_from_open_ts)}} from the raw tape (a level is usable by a bar whose open
    is at or after the close of the bar that completed it)."""
    days: Dict[str, List[BarView]] = {}
    for b in bars:
        days.setdefault(_tday(b.ts_init), []).append(b)
    keys = sorted(days)
    out: Dict[str, Dict[str, Tuple[Optional[float], Optional[int]]]] = {}
    for n, k in enumerate(keys):
        ds = days[k]
        lv: Dict[str, Tuple[Optional[float], Optional[int]]] = {}
        if n > 0:
            prev = days[keys[n - 1]]
            first_ts = ds[0].ts_init                                   # PD is published at the day's first bar
            lv["pdh"] = (max(b.high for b in prev), first_ts)
            lv["pdl"] = (min(b.low for b in prev), first_ts)
        rth = [b for b in ds if _is_rth(b.ts_init)]
        if rth:
            first = rth[0].ts_init
            pre = [b for b in ds if b.ts_init < first and not _is_rth(b.ts_init)]
            if pre:
                lv["onh"] = (max(b.high for b in pre), first)
                lv["onl"] = (min(b.low for b in pre), first)
            orb = [b for b in rth if b.ts_init - first < 1800 * NS]
            fin = [b for b in rth if b.ts_init - first >= 1800 * NS]
            if orb and fin:
                lv["orh"] = (max(b.high for b in orb), fin[0].ts_init)
                lv["orl"] = (min(b.low for b in orb), fin[0].ts_init)
        out[k] = lv
    return out


def _oracle_events(bars: List[BarView], *, min_breach=0.5, max_minutes=5, levels=DEFAULT_LEVELS) -> List[Dict[str, Any]]:
    """Per-level failed breakouts by forward scan within each RTH session (contiguous RTH bars of one trading day)."""
    side_of = {"pdh": 1, "onh": 1, "orh": 1, "pdl": -1, "onl": -1, "orl": -1}
    lv_by_day = _oracle_levels(bars)
    idx = {id(b): n for n, b in enumerate(bars)}
    sessions: Dict[str, List[BarView]] = {}
    for b in bars:
        if _is_rth(b.ts_init):
            sessions.setdefault(_tday(b.ts_init), []).append(b)
    events: List[Dict[str, Any]] = []
    for day, rth in sessions.items():
        for lvl in levels:
            if lvl not in lv_by_day[day]:
                continue
            L, usable_from = lv_by_day[day][lvl]
            side = side_of[lvl]
            armed, i = False, 0
            while i < len(rth):
                b = rth[i]
                if b.ts_event < usable_from:
                    i += 1
                    continue
                n = idx[id(b)]
                prev_close = bars[n - 1].close if n > 0 else None
                if not armed and prev_close is not None and side * (prev_close - L) <= 0:
                    armed = True
                probe = b.high if side > 0 else b.low
                if not (armed and side * (probe - L) >= min_breach):
                    i += 1
                    continue
                start, ext, j, fired = b.ts_event, probe, i, None
                deadline = start + max_minutes * M
                while j < len(rth) and rth[j].ts_init <= deadline:
                    pj = rth[j].high if side > 0 else rth[j].low
                    ext = max(ext, pj) if side > 0 else min(ext, pj)
                    if side * (rth[j].close - L) < 0:
                        fired = j
                        break
                    j += 1
                if fired is not None:
                    events.append({"ts": rth[fired].ts_init, "level": lvl, "level_price": L, "dir": -side,
                                   "start_ts": start, "bars": fired - i + 1, "stop": ext})
                    armed, i = True, fired + 1
                else:
                    armed, i = False, j
    seq: Dict[Tuple[str, str], int] = {}
    for e in sorted(events, key=lambda e: e["ts"]):
        key = (_tday(e["ts"]), e["level"])
        seq[key] = seq.get(key, 0) + 1
        e["seq"] = seq[key]
    return sorted(events, key=lambda e: (e["ts"], levels.index(e["level"])))


def _primary(events: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    by_ts: Dict[int, List[Dict[str, Any]]] = {}
    for e in events:
        by_ts.setdefault(e["ts"], []).append(e)
    out = {}
    for ts, es in by_ts.items():
        if len({e["dir"] for e in es}) == 1:
            out[ts] = dict(es[0], n=len(es))
    return out


def _binding_events(bars: List[BarView], **params):
    fb = _fb(**params)
    per_level, primary, conflicts = [], {}, 0
    for b in bars:
        fb.on_bar("bars", b)
        for lvl in DEFAULT_LEVELS:
            if getattr(fb, f"{lvl}_event"):
                per_level.append((b.ts_init, lvl, getattr(fb, f"{lvl}_episode_extreme")))
        if fb.event:
            primary[b.ts_init] = {"ts": fb.event_ts, "level": fb.event_level, "level_price": fb.event_level_price,
                                  "dir": fb.event_dir, "start_ts": fb.episode_start_ts, "bars": fb.episode_bars,
                                  "stop": fb.stop_reference_price, "seq": fb.event_seq_level, "n": fb.n_levels_fired}
        conflicts += int(fb.conflict)
    return per_level, primary, conflicts


def _parity(days: int, seed: int) -> Dict[str, Any]:
    bars = _tape(days=days, seed=seed)
    oracle = _oracle_events(bars)
    per_level, primary, conflicts = _binding_events(bars)
    o_levels = [(e["ts"], e["level"], e["stop"]) for e in oracle]
    o_primary = _primary(oracle)
    mism = sum(1 for x, y in zip(o_levels, per_level) if x != y) + abs(len(o_levels) - len(per_level))
    pmism = sum(1 for ts in set(o_primary) | set(primary) if o_primary.get(ts) != primary.get(ts))
    by_level = {lvl: sum(1 for e in oracle if e["level"] == lvl) for lvl in DEFAULT_LEVELS}
    return {"bars": len(bars), "rth_bars": sum(1 for b in bars if _is_rth(b.ts_init)), "level_events": len(oracle),
            "primary_events": len(primary), "conflict_bars": conflicts, "by_level": by_level,
            "same_bar_sweeps": sum(1 for e in oracle if e["bars"] == 1),
            "multi_bar_episodes": sum(1 for e in oracle if e["bars"] > 1),
            "repeat_events": sum(1 for e in oracle if e["seq"] > 1),
            "multi_level_bars": sum(1 for e in primary.values() if e["n"] > 1),
            "level_mismatches": mism, "primary_mismatches": pmism,
            "events_sha256": hashlib.sha256(json.dumps(sorted(primary.items()), default=str).encode()).hexdigest()}


@pytest.mark.parametrize("seed", [3, 11])
def test_binding_matches_the_forward_scan_oracle(seed):
    p = _parity(days=8, seed=seed)
    assert p["level_mismatches"] == 0 and p["primary_mismatches"] == 0, p
    # the tape must actually exercise the contract
    assert p["same_bar_sweeps"] > 0 and p["multi_bar_episodes"] > 0 and p["repeat_events"] > 0, p


def test_parity_tapes_exercise_every_level():
    seen = {lvl: sum(_parity(days=8, seed=s)["by_level"][lvl] for s in (3, 11)) for lvl in DEFAULT_LEVELS}
    assert all(n > 0 for n in seen.values()), seen


# =========================================================================== integration: compile -> HostCore
def _registry() -> Dict[str, Any]:
    from research_workflow.capabilities import load_registry
    reg = copy.deepcopy(load_registry())
    for e in reg.get("kinds", {}).get("trackers", []):
        if e.get("id") == CAP and e.get("status") == "candidate":
            e["status"] = "verified"
    return reg


def _spec() -> Dict[str, Any]:
    return {
        "study": {"id": "fb_e2e", "tier": 2, "question": "failed_breakout -> structural stop end-to-end"},
        "streams": [{"dataset": "SYN_A", "timeframes": ["1m"]}],
        "context": {"fb": {"tracker": "price_level.failed_breakout", "bars": "1m"}},
        "population": {"session": "RTH", "cadence": "completed_1m", "qualify": "fb.event == 1", "direction": "fb.event_dir"},
        "triggers": "every_candidate",
        "features": {"host": "synthetic", "metadata": {"fb_level": "fb.event_level", "fb_stop": "fb.stop_reference_price",
                                                        "fb_level_price": "fb.event_level_price", "fb_start": "fb.episode_start_ts"}},
        "outcome": {"kind": "label", "entry_reference": "next_bar_open", "direction": "fb.event_dir",
                    "stop_reference": "fb.stop_reference_price", "same_bar_rule": "adverse_first", "horizon": "3600s",
                    "session_end": "truncate", "max_gap": "300s",
                    "barrier": {"primary": "r1", "expiry": "censor", "arms": [
                        {"id": "r1", "unit": "structural", "reward_risk": 1.0, "stop_buffer_points": 0.25, "tick_size": 0.25, "prefix": "r1"},
                        {"id": "r2", "unit": "structural", "reward_risk": 2.0, "stop_buffer_points": 0.25, "tick_size": 0.25, "prefix": "r2"}]}},
        "chronology": {"train": [2030], "dev": [], "prohibited": []},
        "model": "none",
    }


def _compile(tmp: Path, body: Dict[str, Any], bars: List[BarView]):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    ds = tmp / "datasets"
    ds.mkdir(parents=True, exist_ok=True)
    for p in (GOLDEN / "datasets").glob("*.yaml"):
        shutil.copy2(p, ds / p.name)
    a = yaml.safe_load((ds / "SYN_A.yaml").read_text(encoding="utf-8"))
    a["reference_tables"] = ["sessions"]
    iso = lambda ns: datetime.fromtimestamp(ns / NS, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a["coverage"] = {"start": iso(bars[0].ts_event), "end": iso(bars[-1].ts_init)}
    (ds / "SYN_A.yaml").write_text(yaml.safe_dump(a, sort_keys=False), encoding="utf-8")
    study = tmp / "studies" / body["study"]["id"]
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, registry=_registry(), datasets_dir=ds, extra_bindings=dict(SYNTHETIC_BINDINGS))
    assert out.ok, out.card()
    return out.plan.to_dict()


def _session_table(bars: List[BarView]):
    """RTH rows = the tracker's RTH clock (08:30-15:15 CT) on every tape day; TRADING_DAY = Globex days."""
    from research_workflow.sessions import TRADING_DAY, build_session_table
    days = sorted({_tday(b.ts_init) for b in bars})
    rth, td = [], []
    for d in days:
        y, mo, dd = (int(x) for x in d.split("-"))
        rth.append((_ts(y, mo, dd, 8, 30), _ts(y, mo, dd, 15, 15)))
        prev = datetime(y, mo, dd) - timedelta(days=1)
        td.append((_ts(prev.year, prev.month, prev.day, 17, 0), _ts(y, mo, dd, 16, 0)))
    return build_session_table({"kind": "calendar", "session": "RTH", "rows": rth, "rows_by_session": {"RTH": rth, TRADING_DAY: td}})


def _round_away(px: float, side_up: bool) -> float:
    q = px / 0.25
    return (math.ceil(q - 1e-9) if side_up else math.floor(q + 1e-9)) * 0.25


def test_end_to_end_events_feed_the_structural_stop_at_T(tmp_path):
    from research_workflow.host.strategy import HostCore
    from research_workflow.host_runner import sort_bars_causal
    bars = _tape(days=4, seed=5)
    plan = _compile(tmp_path, _spec(), bars)
    key = plan["streams"][0]["key"]
    core = HostCore(plan, session_table=_session_table(bars))
    rk = [BarView(key, b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    for b in sort_bars_causal(rk, {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}):
        core.ingest(b)
    candidates, obs = core.finalize()
    assert len(candidates) == len(obs)
    rows = candidates.merge(obs.drop(columns=["regime_start_ns", "checkpoint_index"]), on="observation_ts").to_dict("records")
    oracle = _primary(_oracle_events(bars))
    next_open = {b.ts_event: b.open for b in bars}
    assert rows, "no candidates"
    seen = 0
    for r in rows:
        T = int(r["observation_ts"])
        e = oracle.get(T)
        assert e is not None, (T, r)                                   # every candidate is an oracle event AT ITS OWN close
        assert int(r["regime_direction"]) == e["dir"]                  # outcome direction = fb.event_dir
        assert (r["fb_level"], r["fb_stop"], r["fb_level_price"], r["fb_start"]) == (e["level"], e["stop"], e["level_price"], e["start_ts"])
        d = e["dir"]
        if r.get("r1_censor_reason") in ("GAP", "ENTRY_PAST_CUTOFF", "SESSION_END") and r.get("r1_stop_price") is None:
            continue
        stop = _round_away(e["stop"] + 0.25 * (1 if d < 0 else -1), side_up=(d < 0))
        if r.get("r1_stop_price") is not None:
            assert r["r1_stop_price"] == stop, (r, e)
            entry = next_open[T]                                       # the next bar's open, strictly after T
            risk = d * (entry - stop)
            if r.get("r1_risk_points") is not None:
                assert abs(r["r1_risk_points"] - risk) < 1e-9
                assert r["r2_target_price"] == _round_away(entry + d * 2.0 * risk, side_up=(d > 0))
                seen += 1
            else:
                assert r["r1_censor_reason"] in ("STRUCTURAL_STOP_WRONG_SIDE", "STRUCTURAL_STOP_ZERO_RISK")
    rth_events = [ts for ts in oracle if _is_rth(ts)]
    assert len(rows) == len(rth_events), (len(rows), len(rth_events))
    assert seen > 0


# --------------------------------------------------------------------------- parity artifact
def build_parity_artifact() -> Dict[str, Any]:
    return {"capability": CAP,
            "fixture": "synthetic 8-day Globex-like 1m tape (features/tests/test_price_level_failed_breakout.py::_tape)",
            "oracle": "test-only forward-scan oracle (_oracle_events): own trading-day grouping, own CT RTH clock, own level "
                      "rebuild from the raw tape; compared per level (every failure) and per bar (primary event)",
            "runtime_path": "PriceLevelFailedBreakoutBinding.on_bar (GenericPriceLevelProvider levels)",
            "scenarios": {f"seed_{s}": _parity(days=8, seed=s) for s in (3, 11)},
            "passed": True}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write-parity":
        art = build_parity_artifact()
        art["passed"] = all(v["level_mismatches"] == 0 and v["primary_mismatches"] == 0 for v in art["scenarios"].values())
        Path(sys.argv[2]).write_text(json.dumps(art, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"passed": art["passed"]}))

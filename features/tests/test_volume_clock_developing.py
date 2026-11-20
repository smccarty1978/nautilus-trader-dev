"""tracker.volume_clock.developing -- synthetic, hand-calculated and brute-force tests.

* hand-calculated developing states: constant / accelerating / decelerating consumption, advancing / stalling /
  reversing prices, partial completion, threshold crossings, overshoot and collapsed bars, zero-volume seconds,
  missing seconds, session reset and the truncated (residual) bar, rolling-window warmup, and the observation
  that coincides with a completion;
* calibration and classification (FULL / SHORT_RTH / HOLIDAY_ABBREV / NO_RTH, ROLL_TRANSITION, pre-roll window);
* causal integrity: prefix invariance (every state of a truncated replay equals the long replay's state at the
  same row, events included) and future perturbation (changing later rows never changes an earlier state);
* independent brute-force references for the bar construction, the developing state and every rolling control;
* VC / TC control parity (same rows, same denominator, same instant);
* bounded memory; input refusals;
* integration: compile_study -> HostCore, an epoch at T reads the state after the row closing at T.

The historical Stage C parity (210,163 bars, 193,314 primary) is scripts/parity/volume_clock_developing_parity.py ->
artifacts/parity/volume_clock_developing.json.
"""
from __future__ import annotations

import copy
import math
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import yaml

from features.trackers import volume_clock_developing as M
from features.trackers.volume_clock_developing import (
    FIELDS, FULL, HOLIDAY_ABBREV, NO_RTH, ROLL_TRANSITION, SHORT_RTH, RthSession, VolumeClockDevelopingBinding,
    VolumeClockKernel, build_calendar, classify_rth)
from research_workflow.host.interfaces import BarView

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
MIN = 60 * NS
DAY = 86_400 * NS
CT = ZoneInfo("America/Chicago")
CAP = "tracker.volume_clock.developing"
BASE = 1_893_456_000 * NS            # 2030-01-01T00:00Z; synthetic sessions are spaced one day apart


# =========================================================================================== helpers
def _sessions(n: int, cls: Optional[Dict[int, str]] = None, pre_roll=()) -> List[RthSession]:
    cls = cls or {}
    out = []
    for i in range(n):
        a = BASE + i * DAY
        c = cls.get(i, FULL)
        e = a + (225 if c == SHORT_RTH else 405) * MIN
        out.append(RthSession(f"2030-01-{i + 1:02d}", a, e, c, i in pre_roll))
    return out


def _push(k: VolumeClockKernel, te: int, v: float, c: float = 100.0, o: Optional[float] = None,
          h: Optional[float] = None, l: Optional[float] = None):
    o = c if o is None else o
    h = max(o, c) if h is None else h
    l = min(o, c) if l is None else l
    k.push(te, te + NS, o, h, l, c, v)
    return dict(k.state), k.drain()


def _warm(k: VolumeClockKernel, cal: List[RthSession], n: int = 5, per_minute: int = 10, price: float = 100.0) -> None:
    """n sessions with one row per minute of per_minute contracts -> T = per_minute, r_exp = per_minute / 60."""
    for s in cal[:n]:
        for m in range(405 if s.cls != SHORT_RTH else 225):
            _push(k, s.start_ns + m * MIN, per_minute, price)
    k.drain()


def _kernel(n_sessions: int = 8, **kw) -> Tuple[VolumeClockKernel, List[RthSession]]:
    cal = _sessions(n_sessions)
    k = VolumeClockKernel(cal, **kw)
    _warm(k, cal)
    return k, cal


def _ev(events, name):
    return [p for n, p in events if n == name]


# =========================================================================================== calibration / calendar
def test_calibration_hand_values():
    k, cal = _kernel()
    S = cal[5].start_ns
    st, ev = _push(k, S, 2, 100.0)
    opened = _ev(ev, "session_opened")[0]
    assert opened["calibrated"] and opened["T"] == 10 and opened["target_exact"] == 10.0
    assert opened["cal_source_dates"] == ",".join(s.date for s in cal[:5])
    assert st["T"] == 10 and st["calibrated"] is True and st["calibration_history_n"] == 5
    assert st["r_exp"] == pytest.approx(10 / 60, abs=0) and st["tod_minute"] == 0


def test_calibration_uses_last_five_eligible_unrounded_mean():
    cal = _sessions(8)
    k = VolumeClockKernel(cal)
    vols = [9999, 4000, 4100, 4200, 4300, 4401]
    for s, v in zip(cal[:6], vols):
        _push(k, s.start_ns, v)
    st, ev = _push(k, cal[6].start_ns, 1)
    ex = float(np.mean(np.asarray(vols[1:], dtype=np.float64))) / 405
    assert st["target_exact"] == ex and st["T"] == math.ceil(ex) == 11
    assert st["cal_source_dates"] == ",".join(s.date for s in cal[1:6])


def test_scale_k_multiplies_the_unrounded_target():
    cal = _sessions(7)
    k = VolumeClockKernel(cal, scale_k=5)
    _warm(k, cal)
    st, _ = _push(k, cal[5].start_ns, 1)
    assert st["target_exact"] == 50.0 and st["T"] == 50
    assert st["r_exp"] == pytest.approx(10 / 60, abs=0)      # the expected rate does not scale with k


def test_uncalibrated_before_five_eligible_sessions():
    cal = _sessions(6)
    k = VolumeClockKernel(cal)
    _warm(k, cal, n=4)
    st, ev = _push(k, cal[4].start_ns, 5)
    assert st["in_rth"] is True and st["calibrated"] is False and st["frac"] is None and st["rv_15s"] is None
    assert _ev(ev, "session_opened")[0]["calibrated"] is False


def test_classify_rth_from_the_schedule():
    def ct(h, m):
        return int(datetime(2030, 1, 8, h, m, tzinfo=CT).timestamp()) * NS
    assert classify_rth("2030-01-08", ct(16, 0))[0] == FULL
    cls, a, e = classify_rth("2030-01-08", ct(12, 15))
    assert cls == SHORT_RTH and e == ct(12, 15) and a == ct(8, 30)
    assert classify_rth("2030-01-08", ct(12, 0))[0] == HOLIDAY_ABBREV
    assert classify_rth("2030-01-08", ct(8, 0))[0] == NO_RTH
    cls, a, e = classify_rth("2030-01-08", ct(15, 15))
    assert cls == FULL and (e - a) == 405 * MIN


def test_build_calendar_pre_roll_window_and_no_rth_drop():
    days = [f"2030-01-{d:02d}" for d in range(7, 17)]
    closes = [int(datetime(2030, 1, int(d[-2:]), 16, 0, tzinfo=CT).timestamp()) * NS for d in days]
    closes[1] = int(datetime(2030, 1, 8, 8, 0, tzinfo=CT).timestamp()) * NS       # NO_RTH -> dropped
    cal = build_calendar(days, closes, roll_dates=[days[8]])
    assert days[1] not in [s.date for s in cal]
    assert {s.date for s in cal if s.pre_roll} == set(days[3:8]) - {days[1]}


def test_roll_transition_is_built_but_not_eligible():
    cal = _sessions(16, pre_roll={12, 13})
    k = VolumeClockKernel(cal)
    _warm(k, cal, n=12)                       # 12 eligible sessions, 4050 each
    _push(k, cal[12].start_ns, 2000)          # pre-roll, ratio 0.49 < 0.75 -> ROLL_TRANSITION
    st, ev = _push(k, cal[13].start_ns, 4000)  # closes 12; 13 is pre-roll, ratio 0.99 -> stays FULL
    closed = _ev(ev, "session_closed")[0]
    assert closed["rth_class"] == ROLL_TRANSITION and closed["calibrated"] is True and closed["n_bars"] == 200
    assert st["calibrated"] and cal[12].date not in st["cal_source_dates"]
    st, ev = _push(k, cal[14].start_ns, 1)
    assert _ev(ev, "session_closed")[0]["rth_class"] == FULL
    assert st["cal_source_dates"].split(",")[-1] == cal[13].date and cal[12].date not in st["cal_source_dates"]


def test_short_rth_built_and_holiday_abbrev_never_built():
    cal = _sessions(8, cls={5: SHORT_RTH, 6: HOLIDAY_ABBREV})
    k = VolumeClockKernel(cal)
    _warm(k, cal)
    st, _ = _push(k, cal[5].start_ns, 4)
    assert st["calibrated"] and st["rth_class"] == SHORT_RTH and st["frac"] == 0.4
    st, ev = _push(k, cal[6].start_ns, 4)
    assert _ev(ev, "session_closed")[0]["rth_class"] == SHORT_RTH
    assert st["in_rth"] and st["calibrated"] is False and st["frac"] is None
    st, ev = _push(k, cal[7].start_ns, 4)
    assert _ev(ev, "session_closed")[0]["rth_class"] == HOLIDAY_ABBREV
    assert st["cal_source_dates"] == ",".join(s.date for s in cal[:5])     # neither SHORT_RTH nor HOLIDAY_ABBREV eligible


# =========================================================================================== hand-calculated developing states
def test_constant_consumption_advancing_price_and_completion_epoch():
    k, cal = _kernel()
    S = cal[5].start_ns
    states, events = [], []
    for i in range(20):                                   # 2 contracts per second, price +0.25 per second
        st, ev = _push(k, S + i * NS, 2, 100.0 + 0.25 * i)
        states.append(st)
        events.append(ev)
    st = states[2]                                        # t = S + 3 s
    assert (st["consumed"], st["frac"], st["n_completed"], st["bar_seq"], st["elapsed_s"]) == (6, 0.6, 0, 1, 3)
    assert (st["bar_open_price"], st["bar_high"], st["bar_low"], st["bar_start_ts"]) == (100.0, 100.5, 100.0, S)
    assert st["rate_since_open"] == 2.0 and st["rate_last_10s"] == 2.0 and st["internal_contracts"] == 6
    assert st["session_elapsed_s"] == 3 and st["secs_left"] == 405 * 60 - 3
    assert st["d60_points"] == 0.5 and st["dir_d60"] == 1           # P(t-60) = the previous session's last close (100)
    # checkpoints: frac .2, .4, .6, .8 at rows 0..3 -> K25 row 1, K50 row 2, K75 row 3, one each
    assert [s["k25_crossed"] for s in states[:4]] == [0, 1, 0, 0]
    assert [s["k50_crossed"] for s in states[:4]] == [0, 0, 1, 0]
    assert [s["k75_developing"] for s in states[:4]] == [0, 0, 0, 1] and not any(s["multi_cross"] for s in states[:4])
    # completion row 4 (cum 10): the epoch at t = S + 5 s already sees bar 1 complete and bar 2 developing
    st = states[4]
    done = _ev(events[4], "bar_completed")
    assert len(done) == 1 and done[0] == {"session_date": cal[5].date, "bar_seq": 1, "T": 10, "end_ts": S + 4 * NS,
                                          "avail_ts": S + 5 * NS, "start_ts": S, "dur_raw": 5, "duration_s": 5,
                                          "cum_session_contracts": 10, "collapsed": False, "open": 100.0, "high": 101.0,
                                          "low": 100.0, "close": 101.0}
    assert (st["n_completed"], st["bar_seq"], st["consumed"], st["frac"], st["elapsed_s"], st["carry_contracts"]) == (1, 2, 0, 0.0, 0, 0)
    assert (st["bar_open_price"], st["bar_high"], st["bar_low"], st["bar_start_ts"]) == (101.0, 101.0, 101.0, None)
    assert st["rate_since_open"] is None and st["rate_last_10s"] is None
    assert (st["bar_origin_ts"], st["prev_bar_avail_ts"], st["prev_bar_duration_s"]) == (S + 5 * NS, S + 5 * NS, 5)
    st = states[6]                                        # t = S + 7 s, bar 2 started at row 5
    assert (st["consumed"], st["elapsed_s"], st["rate_since_open"], st["bar_start_ts"], st["bar_high"]) == (4, 2, 2.0, S + 5 * NS, 101.5)
    # rolling warmup: vol_15s first defined at t = S + 15 s (row 14)
    assert states[13]["vol_15s"] is None and states[13]["rv_15s"] is None and states[13]["vol_300s"] is None
    assert states[14]["vol_15s"] == 30 and states[14]["rv_15s"] == pytest.approx(30 / (15 * 10 / 60), rel=1e-15)
    assert states[19]["vol_15s"] == 30 and states[19]["vol_30s"] is None


@pytest.mark.parametrize("profile,last10,since_open", [("accelerating", 7.5, 6.5), ("decelerating", 5.5, 6.5)])
def test_accelerating_and_decelerating_consumption(profile, last10, since_open):
    cal = _sessions(7)
    k = VolumeClockKernel(cal)
    _warm(k, cal, per_minute=100)                         # T = 100
    S = cal[5].start_ns
    vols = list(range(1, 13)) if profile == "accelerating" else list(range(12, 0, -1))
    for i, v in enumerate(vols):
        st, _ = _push(k, S + i * NS, v)
    assert st["consumed"] == 78 and st["elapsed_s"] == 12
    assert st["rate_since_open"] == since_open and st["rate_last_10s"] == last10
    assert st["rate_last_15s"] == since_open and st["rate_last_30s"] == since_open      # window capped at elapsed


def test_stalling_and_reversing_price_extremes():
    k, cal = _kernel()
    S = cal[5].start_ns
    path = [100.0, 101.0, 102.0, 102.0, 102.0, 101.0, 99.5]   # advance, stall, reverse
    for i, p in enumerate(path):
        st, _ = _push(k, S + i * NS, 1, p, o=path[i - 1] if i else p)
    assert (st["bar_open_price"], st["bar_high"], st["bar_low"], st["last_close"]) == (100.0, 102.0, 99.5, 99.5)
    assert st["consumed"] == 7 and st["frac"] == 0.7


def test_overshoot_collapsed_bars_carry_and_multi_cross():
    k, cal = _kernel()
    S = cal[5].start_ns
    st0, ev0 = _push(k, S, 8, 100.0)                      # frac .8 -> K25, K50, K75 in one row
    assert (st0["k25_crossed"], st0["k50_crossed"], st0["k75_crossed"], st0["multi_cross"]) == (1, 1, 1, 1)
    assert st0["k75_developing"] == 1 and all(c["multi_cross"] for c in _ev(ev0, "checkpoint"))
    st1, ev1 = _push(k, S + NS, 13, 101.0, o=100.0, h=101.5, l=99.75)   # cum 21: bar 1 and bar 2 complete, carry 1
    done = _ev(ev1, "bar_completed")
    assert [d["bar_seq"] for d in done] == [1, 2]
    b1, b2 = done
    assert (b1["start_ts"], b1["end_ts"], b1["avail_ts"], b1["dur_raw"], b1["collapsed"]) == (S, S + NS, S + 2 * NS, 2, False)
    assert (b1["open"], b1["high"], b1["low"], b1["close"]) == (100.0, 101.5, 99.75, 101.0)
    assert (b2["start_ts"], b2["end_ts"], b2["dur_raw"], b2["duration_s"], b2["collapsed"], b2["open"]) == (S + NS, S + NS, 0, 1, True, None)
    cps = _ev(ev1, "checkpoint")
    assert [(c["bar_seq"], c["level"], c["collapsed"]) for c in cps] == [(2, 0.25, True), (2, 0.5, True), (2, 0.75, True)]
    assert (st1["n_completed"], st1["consumed"], st1["carry_contracts"], st1["internal_contracts"], st1["elapsed_s"]) == (2, 1, 1, 0, 0)
    assert (st1["bar_open_price"], st1["bar_high"], st1["bar_low"], st1["bar_start_ts"]) == (101.0, 101.5, 99.75, S + NS)
    assert st1["k25_crossed"] == 1 and st1["k25_developing"] == 0 and st1["multi_cross"] == 1
    st2, _ = _push(k, S + 2 * NS, 2, 101.25)              # cum 23: bar 3 frac .3 -> K25 by the developing bar
    assert (st2["consumed"], st2["k25_crossed"], st2["k25_developing"], st2["elapsed_s"], st2["internal_contracts"]) == (3, 1, 1, 1, 2)
    assert st2["rate_since_open"] == 2.0
    st3, ev3 = _push(k, S + 3 * NS, 9, 101.5)             # cum 32: bar 3 completes (K50, K75 in the completing row), carry 2
    b3 = _ev(ev3, "bar_completed")[0]
    assert (b3["bar_seq"], b3["start_ts"], b3["end_ts"], b3["avail_ts"], b3["dur_raw"]) == (3, S + NS, S + 3 * NS, S + 4 * NS, 2)
    assert (b3["open"], b3["high"], b3["low"], b3["close"]) == (101.0, 101.5, 99.75, 101.5)
    c3 = _ev(ev3, "checkpoint")
    assert [(c["bar_seq"], c["level"], c["completed_in_row"]) for c in c3] == [(3, 0.5, True), (3, 0.75, True)]
    assert (st3["k50_crossed"], st3["k50_developing"], st3["consumed"], st3["carry_contracts"]) == (1, 0, 2, 2)


def test_zero_volume_seconds_and_bar_one_open():
    k, cal = _kernel()
    S = cal[5].start_ns
    st, _ = _push(k, S, 0, 99.0)                          # no contract: bar 1 not started
    assert (st["consumed"], st["bar_open_price"], st["bar_high"], st["bar_start_ts"]) == (0, None, None, None)
    assert st["k25_crossed"] == 0 and st["calibrated"] is True
    st, _ = _push(k, S + NS, 3, 100.0)                    # first contract: open = this row's open
    assert (st["bar_open_price"], st["bar_start_ts"], st["bar_low"]) == (100.0, S + NS, 100.0)
    st, _ = _push(k, S + 2 * NS, 0, 98.0)                 # zero-volume row after the start: its range counts
    assert (st["consumed"], st["bar_low"], st["rate_since_open"]) == (3, 98.0, 1.0)


def test_missing_seconds_are_wall_clock():
    k, cal = _kernel()
    S = cal[5].start_ns
    _push(k, S, 4)
    st, _ = _push(k, S + 30 * NS, 5)                      # 29 missing seconds
    assert st["elapsed_s"] == 31 and st["consumed"] == 9
    assert st["vol_15s"] == 5 and st["vol_30s"] == 5      # (t-30s, t] excludes the row closing at S+1s
    assert st["rate_last_10s"] == 0.5 and st["rate_last_30s"] == 5 / 30


def test_session_reset_and_truncated_residual_bar():
    k, cal = _kernel()
    S = cal[5].start_ns
    _push(k, S, 27)                                       # 2 bars + residual 7
    st, ev = _push(k, cal[5].end_ns + 5 * NS, 1)          # first row after RTH end closes the session
    closed = _ev(ev, "session_closed")[0]
    assert (closed["n_bars"], closed["residual_contracts"], closed["rth_volume"], closed["T"]) == (2, 7, 27, 10)
    assert st["in_rth"] is False and st["calibrated"] is False and st["frac"] is None and st["n_completed"] is None
    assert st["last_close"] == 100.0                      # the price reference continues outside RTH
    st, ev = _push(k, cal[6].start_ns, 3)                 # next session: fresh developing state
    assert (st["n_completed"], st["consumed"], st["bar_seq"], st["elapsed_s"], st["carry_contracts"]) == (0, 3, 1, 1, 0)
    assert st["vol_15s"] is None


def test_observation_coinciding_with_completion_with_carry():
    k, cal = _kernel()
    S = cal[5].start_ns
    _push(k, S, 6)
    st, ev = _push(k, S + NS, 7)                          # cum 13 at t = S + 2 s: bar 1 completes, carry 3
    assert _ev(ev, "bar_completed")[0]["avail_ts"] == S + 2 * NS
    assert (st["n_completed"], st["consumed"], st["frac"], st["carry_contracts"], st["elapsed_s"]) == (1, 3, 0.3, 3, 0)
    # bar 1 crossed K25/K50 in row 0 (frac .6); row 1: bar 1 crosses K75 while completing, bar 2's carry crosses K25
    assert (st["k25_crossed"], st["k25_developing"], st["k75_crossed"], st["k75_developing"], st["multi_cross"]) == (1, 1, 1, 0, 1)
    assert st["rate_since_open"] is None and st["bar_origin_ts"] == S + 2 * NS


# =========================================================================================== random streams, references
def _random_stream(seed: int, n_sessions: int = 9, rows_per_session: int = 900) -> Tuple[List[RthSession], List[tuple]]:
    rng = random.Random(seed)
    cal = _sessions(n_sessions, pre_roll={7})
    rows = []
    for si, s in enumerate(cal):
        t = s.start_ns - 120 * NS                         # some pre-RTH rows (price reference continuity)
        px = 100.0 + si
        while t < s.start_ns:
            rows.append((t, px, px, px, px, rng.randint(0, 5)))
            t += rng.choice([1, 1, 2, 7]) * NS
        t = s.start_ns + rng.choice([0, 0, 3]) * NS
        for _ in range(rows_per_session):
            v = rng.choice([0, 1, 2, 3, 5, 8, 13, 40, 90]) if si >= 5 else rng.randint(1, 60)
            o = px
            px = round((px + rng.choice([-0.5, -0.25, 0, 0, 0.25, 0.5])) * 4) / 4
            h, l = max(o, px) + rng.choice([0, 0.25]), min(o, px) - rng.choice([0, 0.25])
            rows.append((t, o, h, l, px, v))
            t += rng.choice([1, 1, 1, 2, 5, 31]) * NS
            if t >= s.end_ns:
                break
        rows.append((s.end_ns + 10 * NS, px, px, px, px, 1))   # post-RTH row
    return cal, rows


def _run(cal, rows):
    k = VolumeClockKernel(cal)
    states, events = [], []
    for te, o, h, l, c, v in rows:
        k.push(te, te + NS, o, h, l, c, v)
        states.append(dict(k.state))
        events.append(k.drain())
    return states, events


@pytest.mark.parametrize("seed", [1, 7, 23])
def test_prefix_invariance(seed):
    cal, rows = _random_stream(seed)
    full_s, full_e = _run(cal, rows)
    rng = random.Random(seed + 1000)
    cuts = sorted(rng.sample(range(1, len(rows)), 25)) + [len(rows)]
    for cut in cuts:
        s, e = _run(cal, rows[:cut])
        assert s == full_s[:cut], cut
        assert e == full_e[:cut], cut


@pytest.mark.parametrize("seed", [2, 11])
def test_future_perturbation_never_changes_the_past(seed):
    cal, rows = _random_stream(seed)
    base_s, base_e = _run(cal, rows)
    rng = random.Random(seed)
    for _ in range(6):
        cut = rng.randrange(len(rows) // 3, len(rows) - 1)
        pert = list(rows[:cut])
        for te, o, h, l, c, v in rows[cut:]:
            d = rng.choice([-3.0, 0.0, 2.5])
            pert.append((te, o + d, h + d + 1, l + d - 1, c + d, v * rng.choice([0, 1, 3])))
        s, e = _run(cal, pert)
        assert s[:cut] == base_s[:cut] and e[:cut] == base_e[:cut]


def _brute_reference(cal, rows):
    """Naive per-row recomputation from scratch: no shared code with the kernel."""
    out = {}
    elig: List[Tuple[str, int, np.ndarray]] = []
    by_sess: Dict[int, List[tuple]] = {}
    for r in rows:
        for i, s in enumerate(cal):
            if s.start_ns <= r[0] < s.end_ns:
                by_sess.setdefault(i, []).append(r)
    all_ti = np.array([r[0] + NS for r in rows])
    all_c = np.array([r[4] for r in rows])
    for i, s in enumerate(cal):
        rr = by_sess.get(i, [])
        if not rr:
            continue
        calibrated = len(elig) >= 5
        if calibrated:
            src = elig[-5:]
            ex = float(np.mean(np.asarray([x[1] for x in src], dtype=np.float64))) / 405
            T = math.ceil(ex)
            rexp = np.mean(np.vstack([x[2] for x in src]).astype(float), axis=0) / 60.0
            ti = np.array([r[0] + NS for r in rr])
            v = np.array([r[5] for r in rr], dtype=np.int64)
            C = np.cumsum(v)
            for j, r in enumerate(rr):
                t = r[0] + NS
                n = int(C[j] // T)
                # completion rows of bars 1..n
                comp = [int(np.searchsorted(C, b * T, side="left")) for b in range(1, n + 1)]
                origin = int(ti[comp[-1]]) if n else s.start_ns
                cum_origin = int(C[comp[-1]]) if n else 0
                st_row = int(np.searchsorted(C, n * T + 1, side="left"))      # row holding contract nT+1
                if n:
                    bo = rr[comp[-1]][4]
                else:
                    fv = int(np.searchsorted(C, 1, side="left"))
                    bo = rr[fv][1] if fv <= j else None
                if bo is not None and st_row <= j:
                    hi = max(bo, max(x[2] for x in rr[st_row:j + 1]))
                    lo = min(bo, min(x[3] for x in rr[st_row:j + 1]))
                else:
                    hi = lo = bo
                el = (t - origin) // NS
                d = {"consumed": int(C[j]) - n * T, "n_completed": n, "elapsed_s": el, "bar_open_price": bo,
                     "bar_high": hi, "bar_low": lo, "carry_contracts": (cum_origin - n * T) if n else 0}
                m = (t - NS - s.start_ns) // MIN
                d["r_exp"] = float(rexp[m])
                for w in (15, 30, 60, 120, 300):
                    if t - w * NS >= s.start_ns:
                        vw = int(sum(x[5] for x in rr if t - w * NS < x[0] + NS <= t))
                        d[f"vol_{w}s"] = vw
                        d[f"rv_{w}s"] = vw / (w * d["r_exp"]) if d["r_exp"] > 0 else None
                    else:
                        d[f"vol_{w}s"] = None
                for w in (10, 15, 30):
                    if el > 0:
                        ww = min(w, el)
                        d[f"rate_last_{w}s"] = sum(x[5] for x in rr if t - ww * NS < x[0] + NS <= t) / ww
                    else:
                        d[f"rate_last_{w}s"] = None
                k60 = int(np.searchsorted(all_ti, t - 60 * NS, side="right")) - 1
                d["d60_points"] = (r[4] - all_c[k60]) if k60 >= 0 else None
                out[(i, j)] = d
        vol = sum(r[5] for r in rr)
        cls = s.cls
        prior = [x[1] for x in elig][-20:]
        if cls == FULL and s.pre_roll and len(elig) >= 10 and vol / float(np.median(prior)) < 0.75:
            cls = ROLL_TRANSITION
        if cls == FULL:
            prof = np.zeros(405, dtype=np.int64)
            for r in rr:
                prof[(r[0] - s.start_ns) // MIN] += r[5]
            elig.append((s.date, vol, prof))
    return out, by_sess


@pytest.mark.parametrize("seed", [3, 19])
def test_developing_and_rolling_fields_equal_a_brute_force_reference(seed):
    cal, rows = _random_stream(seed)
    states, _ = _run(cal, rows)
    ref, by_sess = _brute_reference(cal, rows)
    pos = {r[0]: idx for idx, r in enumerate(rows)}
    checked = 0
    for (i, j), d in ref.items():
        st = states[pos[by_sess[i][j][0]]]
        for f, val in d.items():
            got = st[f]
            if isinstance(val, float) and got is not None:
                assert got == pytest.approx(val, rel=1e-12, abs=1e-12), (i, j, f)
            else:
                assert got == val, (i, j, f, got, val)
        checked += 1
    assert checked > 2000


@pytest.mark.parametrize("seed", [5, 31])
def test_completed_bars_and_conservation_equal_a_brute_force_construction(seed):
    cal, rows = _random_stream(seed)
    _, events = _run(cal, rows)
    done = [p for ev in events for n, p in ev if n == "bar_completed"]
    closed = [p for ev in events for n, p in ev if n == "session_closed"]
    _, by_sess = _brute_reference(cal, rows)
    for rec in closed:
        if not rec["calibrated"]:
            continue
        i = [s.date for s in cal].index(rec["session_date"])
        rr = by_sess[i]
        C = np.cumsum([r[5] for r in rr])
        T = rec["T"]
        nb = int(C[-1] // T)
        mine = [d for d in done if d["session_date"] == rec["session_date"]]
        assert rec["n_bars"] == nb == len(mine)
        assert rec["n_bars"] * T + rec["residual_contracts"] == rec["rth_volume"] == int(C[-1])
        prev = cal[i].start_ns
        for b, d in enumerate(mine, start=1):
            e = int(np.searchsorted(C, b * T, side="left"))
            assert d["end_ts"] == rr[e][0] and d["avail_ts"] == rr[e][0] + NS and d["cum_session_contracts"] == b * T
            assert d["dur_raw"] == (rr[e][0] + NS - prev) // NS
            assert d["collapsed"] == (b > 1 and int(np.searchsorted(C, (b - 1) * T, side="left")) == e)
            prev = rr[e][0] + NS


def test_vc_and_tc_read_the_same_rows_at_the_same_instant():
    """With no carry, a developing bar that has run exactly w seconds has consumed exactly vol_<w>s, and
    rate_last_<w>s * w == vol_<w>s: one cumulative series, one clock, one denominator for both blocks."""
    cal = _sessions(7)
    k = VolumeClockKernel(cal)
    _warm(k, cal, per_minute=1000)                        # T = 1000: no completion in this test
    S = cal[5].start_ns
    rng = random.Random(0)
    for i in range(40):
        st, _ = _push(k, S + i * NS, rng.randint(0, 9))
        t = S + (i + 1) * NS
        for w in (15, 30):
            if st[f"vol_{w}s"] is not None:
                assert st[f"rate_last_{w}s"] * w == pytest.approx(st[f"vol_{w}s"], abs=1e-9)
        if st["elapsed_s"] in (15, 30):
            assert st["consumed"] == st[f"vol_{st['elapsed_s']}s"]
        assert st["rv_15s"] is None or st["rv_15s"] == st["vol_15s"] / (15 * st["r_exp"])
        assert st["session_elapsed_s"] == (t - S) // NS


def test_memory_is_bounded_on_a_long_stream():
    cal = _sessions(26)
    k = VolumeClockKernel(cal)
    peak_px = peak_cum = 0
    for s in cal:
        for i in range(0, 6000):
            k.push(s.start_ns + i * NS, s.start_ns + (i + 1) * NS, 100.0, 100.0, 100.0, 100.0, 7)
            if i % 500 == 0:
                k.drain()
                k.closed_sessions.clear()
            peak_px, peak_cum = max(peak_px, len(k._px.ts)), max(peak_cum, len(k._cum.ts))
    assert peak_px <= 4096 + 62 and peak_cum <= 4096 + 302
    assert len(k._px) <= 62 and len(k._cum) <= 302
    assert len(k.elig_vol) == 20 and len(k.elig_dates) == 5 and len(k.elig_prof) == 5 and k.n_elig == 25


def test_input_refusals():
    k, cal = _kernel()
    S = cal[5].start_ns
    with pytest.raises(ValueError, match="1-second"):
        k.push(S, S + 60 * NS, 1, 1, 1, 1, 1)
    k.push(S, S + NS, 1, 1, 1, 1, 1)
    with pytest.raises(ValueError, match="increasing"):
        k.push(S, S + NS, 1, 1, 1, 1, 1)
    with pytest.raises(ValueError, match="integer"):
        k.push(S + NS, S + 2 * NS, 1, 1, 1, 1, 1.5)
    with pytest.raises(ValueError):
        VolumeClockKernel(cal, scale_k=0)


def test_binding_declares_the_proposal_fields_and_events():
    prop = yaml.safe_load((ROOT / "research_workflow/capabilities/proposals/tracker.volume_clock.developing.yaml").read_text(encoding="utf-8"))
    assert tuple(prop["fields"]) == FIELDS == VolumeClockDevelopingBinding.FIELDS
    assert tuple(prop["events"]) == VolumeClockDevelopingBinding.EVENTS
    assert set(prop["parameters"]) == set(VolumeClockDevelopingBinding.PARAMS)


# =========================================================================================== integration: compile -> HostCore
def _ct(day: datetime, h: int, m: int) -> int:
    return int(datetime(day.year, day.month, day.day, h, m, tzinfo=CT).timestamp()) * NS


def _e2e_calendar_and_bars():
    days = [datetime(2030, 1, 7) + timedelta(days=i) for i in range(7)]
    cal = [RthSession(d.date().isoformat(), _ct(d, 8, 30), _ct(d, 15, 15), FULL, False) for d in days]
    rng = random.Random(4)
    bars: List[BarView] = []
    for d, s in zip(days, cal):
        px = 100.0
        if s is cal[-1]:
            t = s.start_ns
            while t < s.start_ns + 900 * NS:
                o = px
                px += rng.choice([-0.25, 0.0, 0.25])
                bars.append(BarView("1s", t, t + NS, o, max(o, px), min(o, px), px, float(rng.choice([0, 1, 4, 9, 30]))))
                t += rng.choice([1, 1, 2, 4]) * NS
        else:
            for m in range(405):
                t = s.start_ns + m * MIN
                bars.append(BarView("1s", t, t + NS, px, px, px, px, 10.0))
    return cal, bars


def _registry() -> Dict[str, Any]:
    from research_workflow.capabilities import load_registry
    reg = copy.deepcopy(load_registry())
    for e in reg.get("kinds", {}).get("trackers", []):
        if e.get("id") == CAP and e.get("status") == "candidate":
            e["status"] = "verified"
    return reg


def _session_table(bars: List[BarView]):
    from research_workflow.sessions import TRADING_DAY, build_session_table
    days = sorted({datetime.fromtimestamp(b.ts_init / NS, tz=CT).date() for b in bars})
    rth = [(_ct(datetime(d.year, d.month, d.day), 8, 30), _ct(datetime(d.year, d.month, d.day), 15, 15)) for d in days]
    td = [(_ct(datetime(d.year, d.month, d.day) - timedelta(days=1), 17, 0), _ct(datetime(d.year, d.month, d.day), 16, 0)) for d in days]
    return build_session_table({"kind": "calendar", "session": "RTH", "rows": rth, "rows_by_session": {"RTH": rth, TRADING_DAY: td}})


def test_end_to_end_epoch_at_T_reads_the_row_closing_at_T(tmp_path, monkeypatch):
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.host.strategy import HostCore
    from research_workflow.host_runner import sort_bars_causal
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    cal, bars = _e2e_calendar_and_bars()
    monkeypatch.setattr(M, "load_calendar", lambda dataset: tuple(cal))
    spec = {
        "study": {"id": "vcd_e2e", "tier": 2, "question": "developing volume clock end-to-end"},
        "streams": [{"dataset": "SYN_A", "timeframes": ["1s"]}],
        "context": {"vc": {"tracker": "volume_clock.developing", "bars": "1s", "dataset": "SYN_A"}},
        "population": {"session": "RTH", "qualify": "vc.calibrated", "direction": "vc.dir_d60"},
        "triggers": "every_candidate",
        "features": {"host": "synthetic", "metadata": {
            "vc_frac": "vc.frac", "vc_n": "vc.n_completed", "vc_elapsed": "vc.elapsed_s", "vc_cum": "vc.cum_volume",
            "vc_carry": "vc.carry_contracts", "tc_vol15": "vc.vol_15s", "tc_rv30": "vc.rv_30s", "vc_k50": "vc.k50_crossed"}},
        "outcome": "none",
        "chronology": {"train": [2030], "dev": [], "prohibited": []},
        "model": "none",
    }
    ds = tmp_path / "datasets"
    ds.mkdir()
    for p in (GOLDEN / "datasets").glob("*.yaml"):
        shutil.copy2(p, ds / p.name)
    a = yaml.safe_load((ds / "SYN_A.yaml").read_text(encoding="utf-8"))
    iso = lambda ns: datetime.fromtimestamp(ns / NS, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    a["coverage"] = {"start": iso(bars[0].ts_event), "end": iso(bars[-1].ts_init)}
    (ds / "SYN_A.yaml").write_text(yaml.safe_dump(a, sort_keys=False), encoding="utf-8")
    study = tmp_path / "studies" / "vcd_e2e"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(study), repo_root=ROOT, registry=_registry(), datasets_dir=ds, extra_bindings=dict(SYNTHETIC_BINDINGS))
    assert out.ok, out.card()
    plan = out.plan.to_dict()
    key = plan["streams"][0]["key"]
    core = HostCore(plan, session_table=_session_table(bars))
    rk = [BarView(key, b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    for b in sort_bars_causal(rk, {s["key"]: int(s["duration_ns"]) for s in plan["streams"]}):
        core.ingest(b)
    candidates, obs = core.finalize()
    # reference: the kernel's state right after the row CLOSING at T
    k = VolumeClockKernel(cal)
    after: Dict[int, Dict[str, Any]] = {}
    for b in bars:
        k.push(b.ts_event, b.ts_init, b.open, b.high, b.low, b.close, b.volume)
        after[b.ts_init] = dict(k.state)
    rows = candidates.to_dict("records")
    assert len(rows) > 300
    n_completion_epochs = 0
    for r in rows:
        T = int(r["observation_ts"])
        st = after[T]
        assert st["calibrated"]
        assert (r["vc_frac"], r["vc_n"], r["vc_elapsed"], r["vc_cum"], r["vc_carry"], r["vc_k50"]) == \
            (st["frac"], st["n_completed"], st["elapsed_s"], st["cum_volume"], st["carry_contracts"], st["k50_crossed"])
        assert (r["tc_vol15"] if r["tc_vol15"] == r["tc_vol15"] else None) == st["vol_15s"]
        n_completion_epochs += int(st["elapsed_s"] == 0 and st["n_completed"] > 0)
    assert n_completion_epochs > 0                          # completion rows are observed with the new bar developing

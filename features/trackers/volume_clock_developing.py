"""tracker.volume_clock.developing -- the session-calibrated volume clock, observed while each bar DEVELOPS.

Input: completed native 1-second bars (``ts_event`` = second open, ``ts_init`` = second close = availability).
The full contract is the proposal ``research_workflow/capabilities/proposals/tracker.volume_clock.developing.yaml``.
In short:

* Session table: the dataset's Globex ``sessions`` reference table (schedule columns only: ``session_date``,
  ``close_ns``) and ``rolls`` table. RTH = 08:30-15:15 CT on ``session_date``; classes FULL / SHORT_RTH (close
  12:15 CT, RTH 08:30-close) / HOLIDAY_ABBREV / NO_RTH exactly as the frozen vc_v1 contract
  (research/nq_adaptive_volume_clock, VOLUME_CLOCK_CONTRACT_FROZEN.md sections 2-3).
* Calibration of session D (FULL or SHORT_RTH, at its first RTH row): the five most recent ELIGIBLE (final class
  FULL) sessions strictly before D; ``target_exact = scale_k * mean(volumes) / 405``; ``T = ceil(target_exact)``.
  A finished FULL session becomes ROLL_TRANSITION (and is NOT eligible) when it lies in the 5 Globex sessions before
  a roll date and its RTH volume is < 0.75 x the median of the last 20 eligible volumes (>= 10 required). D's own
  volume only decides D's eligibility for LATER sessions (known at D's close).
* Bars (the vc_v1 construction): bar n is the contract interval ((n-1)T, nT] of the session's cumulative RTH volume.
  It completes in the source second e whose cumulative volume first reaches nT; it is available at that second's
  close (``avail_ts = end_ts + 1 s``). The surplus of the completing second (the carry) belongs to the next bar.
  Several completions in one second are collapsed bars. The session residual (< T) never completes.
* Developing state after the row closing at t (= the observation at t, completions in that row included):
  ``consumed = cum_volume - n_completed * T``, ``frac = consumed / T`` in [0, 1); ``elapsed_s`` from the previous
  completion's availability (the RTH open for bar 1); ``bar_open_price`` = previous bar close (bar 1: open of the
  first RTH row with volume); running ``bar_high`` / ``bar_low`` over the bar's rows and its open.
* Expected rate: ``r_exp(t)`` = mean volume of minute m(t) over the five calibration sessions / 60 (contracts per
  second), m(t) = the RTH minute holding the second [t - 1 s, t). Identity: mean_m r_exp * 60 = target_exact / scale_k.
* Rolling time-clock controls from the SAME rows and the SAME denominator: ``vol_<w>s`` = RTH volume of rows with
  ts_init in (t - w, t]; ``rv_<w>s = vol_<w>s / (w * r_exp(t))``; null until t - w >= the RTH open.

Nothing reads a later row: every field at t is a function of rows with ``ts_init <= t`` and of the schedule tables.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np

from features.trackers.base import REQUIRED, BarView, BaseBinding, EmittedEvent, EpochView

NS = 1_000_000_000
MIN_NS = 60 * NS
CT = ZoneInfo("America/Chicago")
RTH_START_HMS, RTH_END_HMS = (8, 30, 0), (15, 15, 0)
SHORT_CLOSE_HHMM = "12:15"
FULL_RTH_MIN = 405
N_CAL = 5
ROLL_WINDOW, ROLL_RATIO, ROLL_MED_N, ROLL_MED_MIN = 5, 0.75, 20, 10
FULL, SHORT_RTH, HOLIDAY_ABBREV, NO_RTH, ROLL_TRANSITION = "FULL", "SHORT_RTH", "HOLIDAY_ABBREV", "NO_RTH", "ROLL_TRANSITION"
BUILD_CLASSES = (FULL, SHORT_RTH)          # classes known at the open that build bars (ROLL_TRANSITION is a FULL session)

DEFAULT_RV_WINDOWS = (15, 30, 60, 120, 300)
DEFAULT_RATE_WINDOWS = (10, 15, 30)
DEFAULT_CHECKPOINTS = (0.25, 0.50, 0.75)
DIR_WINDOW_S = 60


# =========================================================================================== calendar
@dataclass(frozen=True)
class RthSession:
    date: str
    start_ns: int
    end_ns: int
    cls: str            # FULL / SHORT_RTH / HOLIDAY_ABBREV (NO_RTH sessions are not listed)
    pre_roll: bool      # one of the ROLL_WINDOW Globex sessions before a roll session


def _ct_ns(day: str, hms: Tuple[int, int, int]) -> int:
    y, m, d = (int(x) for x in day.split("-"))
    return int(datetime(y, m, d, *hms, tzinfo=CT).timestamp()) * NS


def classify_rth(day: str, close_ns: int) -> Tuple[str, int, int]:
    """(class, rth_start_ns, rth_end_ns) of one Globex session from its scheduled close (vc_v1 section 2)."""
    a, e = _ct_ns(day, RTH_START_HMS), _ct_ns(day, RTH_END_HMS)
    if close_ns <= a:
        return NO_RTH, a, a
    if close_ns >= e:
        return FULL, a, e
    hhmm = datetime.fromtimestamp(close_ns / NS, tz=CT).strftime("%H:%M")
    return (SHORT_RTH if hhmm == SHORT_CLOSE_HHMM else HOLIDAY_ABBREV), a, int(close_ns)


def build_calendar(session_dates: Sequence[str], close_ns: Sequence[int], roll_dates: Sequence[str]) -> List[RthSession]:
    """RTH sessions from schedule columns only (never the tape-derived coverage columns)."""
    dates = [str(d) for d in session_dates]
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    dates = [dates[i] for i in order]
    closes = [int(close_ns[i]) for i in order]
    pre_roll = set()
    pos = {d: i for i, d in enumerate(dates)}
    for rd in roll_dates:
        i = pos.get(str(rd))
        if i is not None:
            pre_roll.update(dates[max(0, i - ROLL_WINDOW):i])
    out = []
    for d, c in zip(dates, closes):
        cls, a, e = classify_rth(d, c)
        if cls != NO_RTH:
            out.append(RthSession(d, a, e, cls, d in pre_roll))
    return out


@lru_cache(maxsize=4)
def load_calendar(dataset: str) -> Tuple[RthSession, ...]:
    """RTH calendar from the dataset's hash-verified reference tables (schedule columns only)."""
    from pathlib import Path

    from research_workflow import dataset_v2
    from research_workflow.roots import resolve_dataset

    repo = Path(__file__).resolve().parents[2]
    resolved = resolve_dataset(dataset, repo)
    t = dataset_v2.load_reference_tables(resolved.catalog_path, ["sessions", "rolls"])
    s, r = t["sessions"], t["rolls"]
    return tuple(build_calendar(s.session_date.astype(str).tolist(), s.close_ns.astype("int64").tolist(),
                                r.session_date.astype(str).tolist()))


# =========================================================================================== small causal buffers
class _Series:
    """Append-only (ts, value) series with a moving head: bounded to the longest lookback (plus one older row)."""
    __slots__ = ("ts", "val", "head", "keep_ns")

    def __init__(self, keep_ns: int) -> None:
        self.ts: List[int] = []
        self.val: List[float] = []
        self.head = 0
        self.keep_ns = keep_ns

    def clear(self) -> None:
        self.ts, self.val, self.head = [], [], 0

    def push(self, ts: int, v: float) -> None:
        self.ts.append(ts)
        self.val.append(v)
        # retain exactly one row at or before ts - keep_ns (the value "as of" the oldest lookback instant)
        lim = ts - self.keep_ns
        while self.head + 1 < len(self.ts) and self.ts[self.head + 1] <= lim:
            self.head += 1
        if self.head > 4096:
            del self.ts[:self.head], self.val[:self.head]
            self.head = 0

    def asof(self, x: int) -> Optional[float]:
        """Value of the last row with ts <= x, or None when no retained row is that old."""
        i = bisect.bisect_right(self.ts, x, lo=self.head) - 1
        return self.val[i] if i >= self.head else None

    def __len__(self) -> int:
        return len(self.ts) - self.head


# =========================================================================================== kernel
class VolumeClockKernel:
    """Pure streaming kernel (no host, no I/O). ``push`` one completed 1s row at a time in ts order."""

    def __init__(self, calendar: Sequence[RthSession], scale_k: int = 1, rv_windows: Sequence[int] = DEFAULT_RV_WINDOWS,
                 rate_windows: Sequence[int] = DEFAULT_RATE_WINDOWS, checkpoints: Sequence[float] = DEFAULT_CHECKPOINTS) -> None:
        if int(scale_k) != scale_k or scale_k < 1:
            raise ValueError("scale_k must be a positive integer")
        self.k = int(scale_k)
        self.rv_windows = tuple(int(w) for w in rv_windows)
        self.rate_windows = tuple(int(w) for w in rate_windows)
        self.checkpoints = tuple(float(q) for q in checkpoints)
        if any(w <= 0 for w in self.rv_windows + self.rate_windows) or any(not 0 < q < 1 for q in self.checkpoints):
            raise ValueError("windows must be positive seconds and checkpoints in (0, 1)")
        if list(self.checkpoints) != sorted(set(self.checkpoints)):
            raise ValueError("checkpoints must be strictly increasing")
        self.cal = sorted(calendar, key=lambda s: s.start_ns)
        self._si = 0
        # history (bounded): the last 20 eligible volumes; the last 5 eligible dates and minute profiles
        self.elig_vol: List[int] = []
        self.elig_dates: List[str] = []
        self.elig_prof: List[np.ndarray] = []
        self.n_elig = 0
        self._px = _Series(DIR_WINDOW_S * NS)
        self._cum = _Series(max(self.rv_windows + self.rate_windows) * NS)
        self._last_ts_event: Optional[int] = None
        self.sess: Optional[Dict[str, Any]] = None
        self.events: List[Tuple[str, Dict[str, Any]]] = []
        self.closed_sessions: List[Dict[str, Any]] = []   # drained by the caller; bounded by the caller
        self.state: Dict[str, Any] = {}
        self._publish_idle(None, None)

    # ------------------------------------------------------------------------------------------ sessions
    def _route(self, ts_event: int) -> Optional[RthSession]:
        while self._si < len(self.cal) and self.cal[self._si].end_ns <= ts_event:
            self._si += 1
        if self._si < len(self.cal) and self.cal[self._si].start_ns <= ts_event:
            return self.cal[self._si]
        return None

    def _open_session(self, rs: RthSession) -> None:
        n_min = max(1, (rs.end_ns - rs.start_ns + MIN_NS - 1) // MIN_NS)
        s: Dict[str, Any] = {"rs": rs, "volume": 0, "rows": 0, "minute_vol": np.zeros(n_min, dtype=np.int64),
                             "calibrated": False, "T": None, "target_exact": None, "r_exp": None, "cal_dates": None}
        if rs.cls in BUILD_CLASSES and self.n_elig >= N_CAL:
            src = self.elig_vol[-N_CAL:]
            base = float(np.mean(np.asarray(src, dtype=np.float64)))
            ex = self.k * (base / FULL_RTH_MIN)
            prof = np.mean(np.vstack(self.elig_prof[-N_CAL:]).astype(np.float64), axis=0) / 60.0
            s.update(calibrated=True, T=int(math.ceil(ex)), target_exact=ex, r_exp=prof, cal_dates=",".join(self.elig_dates[-N_CAL:]),
                     baseline_volume=base)
        # developing-bar state
        s.update(n_done=0, cum=0, cum_origin=0, origin=rs.start_ns, bar_open=None, bar_start=None, hi=None, lo=None, carry=0,
                 crossed=set(), prev_dur=None, prev_avail=None, last_close=None)
        self._cum.clear()
        self.sess = s
        self.events.append(("session_opened", {"session_date": rs.date, "rth_class": rs.cls, "rth_start_ns": rs.start_ns,
                                               "rth_end_ns": rs.end_ns, "calibrated": s["calibrated"], "T": s["T"],
                                               "target_exact": s["target_exact"], "cal_source_dates": s["cal_dates"]}))

    def _close_session(self) -> None:
        s, self.sess = self.sess, None
        if s is None:
            return
        rs: RthSession = s["rs"]
        cls = rs.cls
        med = float(np.median(self.elig_vol[-ROLL_MED_N:])) if len(self.elig_vol) >= ROLL_MED_MIN else math.nan
        ratio = s["volume"] / med if math.isfinite(med) and med > 0 else math.nan
        if cls == FULL and rs.pre_roll and math.isfinite(ratio) and ratio < ROLL_RATIO:
            cls = ROLL_TRANSITION
        rec = {"session_date": rs.date, "rth_class": cls, "rth_volume": int(s["volume"]), "native_rows": int(s["rows"]),
               "roll_ratio_med20": ratio, "calibrated": s["calibrated"], "T": s["T"], "target_exact": s["target_exact"],
               "cal_source_dates": s["cal_dates"], "n_bars": int(s["n_done"]) if s["calibrated"] else 0,
               "residual_contracts": int(s["cum"] - s["n_done"] * s["T"]) if s["calibrated"] else None}
        if cls == FULL:                         # appended after D is finished: D never calibrates itself
            self.elig_vol.append(int(s["volume"]))
            self.elig_dates.append(rs.date)
            self.elig_prof.append(s["minute_vol"][:FULL_RTH_MIN].copy())
            self.n_elig += 1
            del self.elig_vol[:-ROLL_MED_N], self.elig_dates[:-N_CAL], self.elig_prof[:-N_CAL]
        self.events.append(("session_closed", rec))
        self.closed_sessions.append(rec)

    # ------------------------------------------------------------------------------------------ main step
    def push(self, ts_event: int, ts_init: int, o: float, h: float, l: float, c: float, v: float) -> None:
        if ts_init - ts_event != NS:
            raise ValueError(f"tracker.volume_clock.developing consumes 1-second bars (got duration {ts_init - ts_event} ns)")
        if self._last_ts_event is not None and ts_event <= self._last_ts_event:
            raise ValueError(f"rows must arrive in strictly increasing ts_event order ({ts_event} after {self._last_ts_event})")
        self._last_ts_event = ts_event
        vol = int(round(v))
        if vol != v or vol < 0:
            raise ValueError(f"volume must be a non-negative integer (got {v!r})")
        self._px.push(ts_init, float(c))
        rs = self._route(ts_event)
        if self.sess is not None and (rs is None or rs is not self.sess["rs"]):
            self._close_session()
        if rs is None:
            self._publish_idle(ts_init, None)
            return
        if self.sess is None:
            self._open_session(rs)
        s = self.sess
        s["volume"] += vol
        s["rows"] += 1
        m = (ts_event - rs.start_ns) // MIN_NS
        s["minute_vol"][m] += vol
        if not s["calibrated"]:
            self._publish_idle(ts_init, s)
            return
        self._develop(s, ts_event, ts_init, float(o), float(h), float(l), float(c), vol)
        self._publish(ts_init, s)

    def _develop(self, s: Dict[str, Any], ts_event: int, t: int, o: float, h: float, l: float, c: float, vol: int) -> None:
        T = s["T"]
        cum0 = s["cum"]
        cum = cum0 + vol
        s["cum"] = cum
        self._cum.push(t, cum)
        n0, n1 = s["n_done"], cum // T
        if vol > 0 and s["bar_start"] is None:          # the row's first contract belongs to the developing bar
            s["bar_start"] = ts_event
            if s["bar_open"] is None:                    # bar 1: the open of the first RTH row with volume
                s["bar_open"] = o
                s["hi"] = s["lo"] = o
        if s["bar_start"] is not None:
            s["hi"], s["lo"] = max(s["hi"], h), min(s["lo"], l)
        s["last_close"] = c
        crossings: List[Dict[str, Any]] = []
        # checkpoints of the bar developing at the START of this row (completing or not)
        frac_now = min(cum - n0 * T, T) / T
        cur_seq = n0 + 1
        for q in self.checkpoints:
            if q not in s["crossed"] and frac_now >= q:
                s["crossed"].add(q)
                crossings.append({"bar_seq": cur_seq, "level": q, "completed_in_row": n1 > n0, "collapsed": False})
        for j in range(n0 + 1, n1 + 1):
            collapsed = j > n0 + 1
            if collapsed:                                 # completes in the same second as bar j-1: no developing state
                for q in self.checkpoints:
                    crossings.append({"bar_seq": j, "level": q, "completed_in_row": True, "collapsed": True})
            prev_avail = s["origin"]
            dur_raw = (t - prev_avail) // NS
            payload = {"session_date": s["rs"].date, "bar_seq": j, "T": T, "end_ts": ts_event, "avail_ts": t,
                       "start_ts": ts_event if collapsed else s["bar_start"], "dur_raw": int(dur_raw),
                       "duration_s": int(max(dur_raw, 1)), "cum_session_contracts": j * T, "collapsed": collapsed,
                       "open": None if collapsed else s["bar_open"], "high": None if collapsed else max(s["hi"], s["bar_open"]),
                       "low": None if collapsed else min(s["lo"], s["bar_open"]), "close": None if collapsed else c}
            self.events.append(("bar_completed", payload))
            s["origin"] = t
            s["cum_origin"] = cum
            s["prev_dur"] = int(max(dur_raw, 1))
            s["prev_avail"] = t
        if n1 > n0:                                       # the next bar opens at this row's close, with the carry
            s["n_done"] = n1
            carry = cum - n1 * T
            s["carry"] = carry
            s["bar_open"] = c
            s["crossed"] = set()
            if carry > 0:
                s["bar_start"], s["hi"], s["lo"] = ts_event, max(h, c), min(l, c)
                for q in self.checkpoints:
                    if carry / T >= q:
                        s["crossed"].add(q)
                        crossings.append({"bar_seq": n1 + 1, "level": q, "completed_in_row": False, "collapsed": False})
            else:
                s["bar_start"], s["hi"], s["lo"] = None, c, c
        multi = len(crossings) > 1
        for x in crossings:
            x.update(session_date=s["rs"].date, ts=t, multi_cross=multi)
            self.events.append(("checkpoint", x))
        s["row_crossings"] = crossings

    # ------------------------------------------------------------------------------------------ published fields
    def _base_fields(self, t: Optional[int], s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        st: Dict[str, Any] = dict.fromkeys(FIELDS)
        st["calibration_history_n"] = self.n_elig
        st["roll_rule_ready"] = len(self.elig_vol) >= ROLL_MED_MIN
        st["calibrated"] = False
        st["in_rth"] = s is not None
        if t is not None:
            st["last_close"] = self._px.asof(t)
            p60 = self._px.asof(t - DIR_WINDOW_S * NS)
            if st["last_close"] is not None and p60 is not None:
                d = st["last_close"] - p60
                st["d60_points"] = d
                st["dir_d60"] = 1 if d > 0 else (-1 if d < 0 else 0)
        if s is not None and t is not None:
            rs = s["rs"]
            st.update(session_date=rs.date, rth_class=rs.cls, session_open_ns=rs.start_ns, session_close_ns=rs.end_ns,
                      session_elapsed_s=(t - rs.start_ns) // NS, secs_left=(rs.end_ns - t) // NS)
        for q in self.checkpoints:
            st[_cp_name(q, "crossed")] = 0
            st[_cp_name(q, "developing")] = 0
        st["multi_cross"] = 0
        return st

    def _publish_idle(self, t: Optional[int], s: Optional[Dict[str, Any]]) -> None:
        self.state = self._base_fields(t, s)

    def _publish(self, t: int, s: Dict[str, Any]) -> None:
        st = self._base_fields(t, s)
        T = s["T"]
        consumed = s["cum"] - s["n_done"] * T
        elapsed = (t - s["origin"]) // NS
        st.update(calibrated=True, T=T, target_exact=s["target_exact"], cal_source_dates=s["cal_dates"],
                  cum_volume=s["cum"], n_completed=s["n_done"], bar_seq=s["n_done"] + 1, consumed=consumed, frac=consumed / T,
                  carry_contracts=s["carry"], elapsed_s=elapsed, bar_origin_ts=s["origin"], bar_start_ts=s["bar_start"],
                  bar_open_price=s["bar_open"], prev_bar_duration_s=s["prev_dur"], prev_bar_avail_ts=s["prev_avail"])
        if s["bar_open"] is not None:
            st["bar_high"] = max(s["hi"], s["bar_open"])
            st["bar_low"] = min(s["lo"], s["bar_open"])
        # bar-internal rates: contracts after the bar origin (the carry sits AT the origin and is excluded)
        internal = s["cum"] - s["cum_origin"]
        st["internal_contracts"] = internal
        if elapsed > 0:
            st["rate_since_open"] = internal / elapsed
            for w in self.rate_windows:
                ww = min(w, elapsed)
                base = self._cum.asof(t - ww * NS)
                st[f"rate_last_{w}s"] = (s["cum"] - (base or 0)) / ww
        # expected rate and rolling time-clock volume (same rows, same denominator)
        rs = s["rs"]
        m = (t - NS - rs.start_ns) // MIN_NS
        r = float(s["r_exp"][m]) if 0 <= m < len(s["r_exp"]) else None
        st["tod_minute"] = int(m)
        st["r_exp"] = r
        for w in self.rv_windows:
            if t - w * NS >= rs.start_ns:
                base = self._cum.asof(t - w * NS)
                vw = s["cum"] - (base or 0)
                st[f"vol_{w}s"] = vw
                st[f"rv_{w}s"] = (vw / (w * r)) if r is not None and r > 0 else None
        cr = s.get("row_crossings") or []
        for x in cr:
            q = x["level"]
            st[_cp_name(q, "crossed")] += 1
            if not x["completed_in_row"]:
                st[_cp_name(q, "developing")] = 1
        st["multi_cross"] = int(len(cr) > 1)
        s["row_crossings"] = []
        self.state = st

    def drain(self) -> List[Tuple[str, Dict[str, Any]]]:
        out, self.events = self.events, []
        return out


def _cp_name(q: float, what: str) -> str:
    return f"k{int(round(q * 100)):02d}_{what}"


# =========================================================================================== field list
_STATIC_FIELDS = (
    "in_rth", "session_date", "rth_class", "session_open_ns", "session_close_ns", "session_elapsed_s", "secs_left",
    "calibrated", "calibration_history_n", "roll_rule_ready", "T", "target_exact", "cal_source_dates",
    "cum_volume", "n_completed", "bar_seq", "consumed", "frac", "carry_contracts", "internal_contracts", "elapsed_s",
    "bar_origin_ts", "bar_start_ts", "bar_open_price", "bar_high", "bar_low", "prev_bar_duration_s", "prev_bar_avail_ts",
    "rate_since_open", "tod_minute", "r_exp", "last_close", "d60_points", "dir_d60", "multi_cross",
)


def _fields(rv_windows=DEFAULT_RV_WINDOWS, rate_windows=DEFAULT_RATE_WINDOWS, checkpoints=DEFAULT_CHECKPOINTS) -> tuple:
    return (_STATIC_FIELDS + tuple(f"rate_last_{w}s" for w in rate_windows) + tuple(f"vol_{w}s" for w in rv_windows)
            + tuple(f"rv_{w}s" for w in rv_windows)
            + tuple(_cp_name(q, x) for q in checkpoints for x in ("crossed", "developing")))


FIELDS = _fields()


# =========================================================================================== host binding
class VolumeClockDevelopingBinding(BaseBinding):
    CAPABILITY = "tracker.volume_clock.developing"
    PARAMS = {"dataset": REQUIRED, "scale_k": 1}
    INPUTS = {"bars": "stream"}
    FIELDS = FIELDS
    EVENTS = ("session_opened", "session_closed", "bar_completed", "checkpoint")
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        cal = load_calendar(str(self.params["dataset"]))
        self.kernel = VolumeClockKernel(cal, scale_k=int(self.params["scale_k"]))
        self._apply()

    def _apply(self) -> None:   # fields are served from the kernel state (see __getattr__); nothing to copy
        return None

    def __getattr__(self, name: str) -> Any:
        kernel = self.__dict__.get("kernel")
        if kernel is not None and name in kernel.state:
            return kernel.state[name]
        raise AttributeError(name)

    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key != "bars":
            return
        self.kernel.push(int(bar.ts_event), int(bar.ts_init), bar.open, bar.high, bar.low, bar.close, bar.volume)
        self._apply()
        for name, payload in self.kernel.drain():
            self.emit(name, payload)
        self.kernel.closed_sessions.clear()

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        return None

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        raise KeyError(name)


__all__ = ["VolumeClockDevelopingBinding", "VolumeClockKernel", "RthSession", "build_calendar", "classify_rth",
           "load_calendar", "FIELDS"]

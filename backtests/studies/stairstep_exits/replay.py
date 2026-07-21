"""Streaming stair-step exit replay.

One pass over 1s bars. Reuses the vetted causal stack (registry + aggregator +
regime_engine) for 1m & 5s regime — SAME flip / bar1 detection as the flip-truth
collector. For each detected entry (A raw, B bar1-confirmed) it opens ALL exit
versions concurrently on the same entry and replays them bar-by-bar to the next
opposite 1m flip (the universal backstop). Records one row per (entry, version).

Causal: decision_ts = bar.ts_init; all regime/SMA/swing state comes from
COMPLETED bars only (registry close_ts <= decision_ts). Stop migrations stage to
the next 1s bar (handled inside VersionTrade).
"""
from __future__ import annotations
from collections import deque
from pathlib import Path
import sys

import pandas as pd
import pytz

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from collectors.collector_v2.registry import CompletedBarRegistry  # noqa: E402
from collectors.collector_v2.aggregator import TimeframeAggregator  # noqa: E402
from collectors.collector_v2.regime_engine import RegimeStateEngine  # noqa: E402
from studies.stairstep_exits.exit_versions import (  # noqa: E402
    VersionTrade, EXIT_VERSIONS,
)

CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000
TICK = 0.25
TFS = ("5s", "1m")
RTH_START_MIN = 510
RTH_END_MIN = 900
ATR_PERIOD = 14  # for the entry ATR (Wilder, 1m) — from registry


class StairStepReplay:
    def __init__(self, versions=None):
        self.versions = versions or list(EXIT_VERSIONS.keys())
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._eng = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(
            on_bucket_closed=lambda tf, b: self._eng[tf].on_bar_closed(b),
            timeframes=TFS)

        self._last_1m = 0
        self._last_5s = 0
        self._prev_1m = 0
        self._pending_bar1 = None

        # SMA13 + last-3 swing on each clock
        self._sma1 = deque(maxlen=13); self._sma1_sum = 0.0
        self._sma5 = deque(maxlen=13); self._sma5_sum = 0.0
        self._low3_1m = deque(maxlen=3); self._high3_1m = deque(maxlen=3)
        self._low3_5s = deque(maxlen=3); self._high3_5s = deque(maxlen=3)

        self._open: list[VersionTrade] = []
        self._open_meta: dict[int, dict] = {}   # entry_id -> entry meta
        self._entry_seq = 0
        self.records: list[dict] = []

        self._n_1m = 0  # warmup gate (need ATR + SMA warm)

    # ------------------------------------------------------------------
    def _sma(self, buf, s):
        return (s / len(buf)) if len(buf) == 13 else None

    def _push_sma(self, buf, holder_name, val):
        buf_sum = getattr(self, holder_name)
        if len(buf) == 13:
            buf_sum -= buf[0]
        buf.append(val)
        buf_sum += val
        setattr(self, holder_name, buf_sum)

    def _open_entry(self, pop, d, entry_px, entry_ts, s1m, cat_px):
        atr = s1m.atr
        # Skip entries before ATR is available (pre-warmup, in the lead-in
        # window). These are NaN-ATR and would be dropped by the warmed_up
        # filter regardless; opening them would divide by NaN.
        if atr is None or atr != atr or atr <= 0:
            return
        warmed = (self._n_1m >= 50 and atr is not None and atr == atr)
        ct = pd.Timestamp(int(entry_ts), tz="UTC").tz_convert(CT)
        minct = ct.hour * 60 + ct.minute
        self._entry_seq += 1
        eid = self._entry_seq
        self._open_meta[eid] = {
            "entry_id": eid, "population": pop, "direction": d,
            "entry_ts": entry_ts, "entry_px": entry_px, "atr_at_entry": atr,
            "rth_flag": bool(RTH_START_MIN <= minct < RTH_END_MIN),
            "warmed_up": bool(warmed), "year": ct.year,
        }
        for vid in self.versions:
            spec = EXIT_VERSIONS[vid]
            tr = VersionTrade(vid, spec, d, entry_px, atr, entry_ts, TICK,
                              cat_px=(cat_px if spec.get("cat_stop") else None))
            tr.entry_id = eid
            self._open.append(tr)

    def _record(self, tr):
        meta = self._open_meta[tr.entry_id]
        row = dict(meta)
        row.update(tr.record())
        self.records.append(row)

    def _close_all(self, ts, px, reason):
        for tr in self._open:
            tr.regime_exit(ts, px)
            self._record(tr)
        self._open = []

    # ------------------------------------------------------------------
    def on_bar(self, o, h, l, c, v, tse, tsi):
        self._agg.on_1s_bar(int(tse), o, h, l, c, v)
        s1m = self._reg.get("1m"); s5 = self._reg.get("5s")
        reg5 = s5.regime if s5 is not None else 0

        closed_5s = s5 is not None and s5.close_ts != self._last_5s
        closed_1m = s1m is not None and s1m.close_ts != self._last_1m

        if closed_5s:
            self._last_5s = s5.close_ts
            self._push_sma(self._sma5, "_sma5_sum", s5.close)
            self._low3_5s.append(s5.low); self._high3_5s.append(s5.high)
        if closed_1m:
            self._last_1m = s1m.close_ts
            self._n_1m += 1
            self._push_sma(self._sma1, "_sma1_sum", s1m.close)
            self._low3_1m.append(s1m.low); self._high3_1m.append(s1m.high)

        # --- flip / entry detection (1m close) ---
        new_entries = []
        if closed_1m:
            regime = s1m.regime; prev = self._prev_1m
            flipped = (regime != prev and regime != 0)
            if flipped:
                # old regime ends: exit all open trades at flip bar close.
                # exit_ts = the flip bar's CLOSE time (not the +1s trigger bar
                # ts_init) so hold_s and RTH-at-exit are exact. [audit W2]
                self._close_all(int(s1m.close_ts), s1m.close, "regime")
                new_entries.append(("A", regime, s1m.open))  # cat=flip-bar open
                self._pending_bar1 = {
                    "dir": regime, "flip_h": s1m.high, "flip_l": s1m.low,
                    "flip_close_ts": s1m.close_ts}
            else:
                pb = self._pending_bar1
                if pb and s1m.open_ts == pb["flip_close_ts"] and regime == pb["dir"]:
                    if regime == 1:
                        conf = (s1m.high > pb["flip_h"] and s1m.close > s1m.open)
                    else:
                        conf = (s1m.low < pb["flip_l"] and s1m.close < s1m.open)
                    if conf:
                        new_entries.append(("B", regime, None))
                    self._pending_bar1 = None
                elif pb and s1m.open_ts > pb["flip_close_ts"]:
                    self._pending_bar1 = None
            self._prev_1m = regime

        # open new entries at THIS 1s bar's open (first bar after the decision)
        for pop, d, cat in new_entries:
            self._open_entry(pop, d, o, int(tsi), s1m, cat)

        # --- per-1s update for all open trades ---
        if self._open:
            still = []
            for tr in self._open:
                tr.on_1s(int(tsi), o, h, l, c, (s1m.regime if s1m else 0),
                         tr.d * reg5)
                if tr.exited:
                    self._record(tr)
                else:
                    still.append(tr)
            self._open = still

        # --- clock migrations (after on_1s; stage for next bar) ---
        if closed_1m and self._open:
            sma1 = self._sma(self._sma1, self._sma1_sum)
            l3 = list(self._low3_1m); h3 = list(self._high3_1m)
            for tr in self._open:
                if tr.spec.get("clock") == "1m":
                    tr.on_clock(int(tsi), l3, h3, sma1, c)
        if closed_5s and self._open:
            sma5 = self._sma(self._sma5, self._sma5_sum)
            l3 = list(self._low3_5s); h3 = list(self._high3_5s)
            for tr in self._open:
                if tr.spec.get("clock") == "5s":
                    tr.on_clock(int(tsi), l3, h3, sma5, c)

    def finalize(self):
        # close any still-open trades at last seen 1m close
        s1m = self._reg.get("1m")
        if s1m is not None and self._open:
            for tr in self._open:
                tr.force_exit(s1m.close_ts, s1m.close)
                self._record(tr)
        self._open = []

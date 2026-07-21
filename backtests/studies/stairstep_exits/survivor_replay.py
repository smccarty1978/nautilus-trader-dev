"""Raw-Flip / Bar1 Survivor & Add-On forward-expectancy replay.

V0_regime probe (the exit that best preserves the runner tail). For every trade
we record, at the FIRST occurrence of each causal survivor state, the price at
that moment and then the FORWARD path from that price to the V0 regime exit. The
add-on contract's economics are measured PURELY FORWARD from the state (entry =
price-at-state, exit = forward path) — never crediting the probe's prior move.

Survivor states (all causal, first-occurrence):
  TIME:     alive at +30/60/90/120/180s        price = 1s close at that time
  PROGRESS: reached +0.25/0.50/0.75/1.0/1.5 ATR price = entry + X*ATR (limit)
  PATH:     gate_pass (survived +30s net<0&5s-opp cut AND net>=0 at +60s)
            no5s_opp_90 (alive at +90s, no 5s-opposed in first 90s)
            pos_path_eff (alive +60s, dir path efficiency > 0)
            mfe_gt_mae  (alive +60s, running MFE > running MAE)

Causal: decision_ts = ts_init; regime/5s from registry completed bars; forward
extremes accumulate only over [t_state, exit]. No future inspection.
"""
from __future__ import annotations
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

CT = pytz.timezone("America/Chicago")
NS = 1_000_000_000
TICK = 0.25
TFS = ("5s", "1m")
RTH_START_MIN = 510; RTH_END_MIN = 900

TIME_STATES = [("alive_30", 30), ("alive_60", 60), ("alive_90", 90),
               ("alive_120", 120), ("alive_180", 180)]
PROG_STATES = [("reach_0p25", 0.25), ("reach_0p50", 0.50), ("reach_0p75", 0.75),
               ("reach_1p00", 1.0), ("reach_1p50", 1.5)]
PATH_STATES = ["gate_pass", "no5s_opp_90", "pos_path_eff", "mfe_gt_mae"]
ALL_STATES = [s for s, _ in TIME_STATES] + [s for s, _ in PROG_STATES] + PATH_STATES


class SurvivorTrade:
    def __init__(self, pop, d, entry_px, atr, entry_ts):
        self.pop = pop; self.d = d; self.ep = entry_px; self.atr = atr
        self.entry_ts = entry_ts
        self.exited = False; self.exit_px = None; self.exit_ts = None
        self.run_mfe = -1e18; self.run_mae = -1e18
        self.cum_abs = 0.0; self.prev_c = entry_px
        # gate / 5s tracking
        self._g30_done = False; self._g60_done = False; self._cut30 = False
        self._any5s_opp_90 = False
        # per-state record: reached, t, pS, fwd_high, fwd_low
        self.st = {s: dict(reached=False, t=None, pS=None, fh=-1e18, fl=1e18)
                   for s in ALL_STATES}

    def _hit(self, name, ts, pS, h, l):
        s = self.st[name]
        if not s["reached"]:
            s["reached"] = True
            s["t"] = (ts - self.entry_ts) / NS
            s["pS"] = pS
            s["fh"] = h; s["fl"] = l

    def on_1s(self, ts, o, h, l, c, align5s):
        if self.exited:
            return
        d = self.ep; dirn = self.d; atr = self.atr
        # running mfe/mae
        if dirn == 1:
            mfe = h - self.ep; mae = self.ep - l
        else:
            mfe = self.ep - l; mae = h - self.ep
        if mfe > self.run_mfe: self.run_mfe = mfe
        if mae > self.run_mae: self.run_mae = mae
        self.cum_abs += abs(c - self.prev_c); self.prev_c = c
        dt = (ts - self.entry_ts) / NS
        if dt <= 90 and align5s == -1:
            self._any5s_opp_90 = True

        # update forward extremes for already-reached states
        for s in self.st.values():
            if s["reached"]:
                if h > s["fh"]: s["fh"] = h
                if l < s["fl"]: s["fl"] = l

        # TIME states (price = current close, trade alive)
        for name, T in TIME_STATES:
            if not self.st[name]["reached"] and dt >= T:
                self._hit(name, ts, c, h, l)
        # PROGRESS states (price = entry + X*ATR limit level)
        if atr > 0:
            mfe_atr = self.run_mfe / atr
            for name, X in PROG_STATES:
                if not self.st[name]["reached"] and mfe_atr >= X:
                    self._hit(name, ts, self.ep + dirn * X * atr, h, l)
        # PATH states
        net = dirn * (c - self.ep)
        if not self._g30_done and dt >= 30:
            self._g30_done = True
            if net < 0 and align5s == -1:
                self._cut30 = True
        if not self._g60_done and dt >= 60:
            self._g60_done = True
            if not self._cut30 and net >= 0:
                self._hit("gate_pass", ts, c, h, l)
            eff = (dirn * (c - self.ep) / self.cum_abs) if self.cum_abs > 0 else 0.0
            if eff > 0:
                self._hit("pos_path_eff", ts, c, h, l)
            if self.run_mfe > self.run_mae:
                self._hit("mfe_gt_mae", ts, c, h, l)
        if not self.st["no5s_opp_90"]["reached"] and dt >= 90:
            if not self._any5s_opp_90:
                self._hit("no5s_opp_90", ts, c, h, l)

    def regime_exit(self, ts, px):
        if self.exited:
            return
        self.exited = True; self.exit_px = px; self.exit_ts = ts
        # final forward-extreme update with exit bar already done via on_1s

    def record(self):
        row = dict(population=self.pop, direction=self.d, entry_px=self.ep,
                   atr_at_entry=self.atr, entry_ts=self.entry_ts,
                   exit_px=self.exit_px, exit_ts=self.exit_ts,
                   probe_term_pts=self.d * (self.exit_px - self.ep),
                   hold_s=(self.exit_ts - self.entry_ts) / NS,
                   run_mfe_pts=max(self.run_mfe, 0.0))
        for name in ALL_STATES:
            s = self.st[name]
            row[f"{name}_reached"] = s["reached"]
            row[f"{name}_t"] = s["t"]
            row[f"{name}_pS"] = s["pS"]
            if s["reached"]:
                fwd_mfe = (s["fh"] - s["pS"]) if self.d == 1 else (s["pS"] - s["fl"])
                fwd_mae = (s["pS"] - s["fl"]) if self.d == 1 else (s["fh"] - s["pS"])
                fwd_term = self.d * (self.exit_px - s["pS"])
                row[f"{name}_fwd_mfe"] = fwd_mfe
                row[f"{name}_fwd_mae"] = fwd_mae
                row[f"{name}_fwd_term"] = fwd_term
            else:
                row[f"{name}_fwd_mfe"] = None
                row[f"{name}_fwd_mae"] = None
                row[f"{name}_fwd_term"] = None
        return row


class SurvivorReplay:
    def __init__(self):
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._eng = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(
            on_bucket_closed=lambda tf, b: self._eng[tf].on_bar_closed(b),
            timeframes=TFS)
        self._last_1m = 0; self._prev_1m = 0; self._pending_bar1 = None
        self._n_1m = 0
        self._open = []   # list of (SurvivorTrade,)
        self.records = []

    def _open_entry(self, pop, d, entry_px, entry_ts, s1m):
        atr = s1m.atr
        if atr is None or atr != atr or atr <= 0:
            return
        warmed = self._n_1m >= 50
        ct = pd.Timestamp(int(entry_ts), tz="UTC").tz_convert(CT)
        minct = ct.hour * 60 + ct.minute
        tr = SurvivorTrade(pop, d, entry_px, atr, int(entry_ts))
        tr.rth = bool(RTH_START_MIN <= minct < RTH_END_MIN)
        tr.year = ct.year; tr.warmed = bool(warmed)
        self._open.append(tr)

    def _close_all(self, ts, px):
        for tr in self._open:
            tr.regime_exit(ts, px)
            r = tr.record(); r["rth_flag"] = tr.rth; r["year"] = tr.year
            r["warmed_up"] = tr.warmed
            self.records.append(r)
        self._open = []

    def on_bar(self, o, h, l, c, v, tse, tsi):
        self._agg.on_1s_bar(int(tse), o, h, l, c, v)
        s1m = self._reg.get("1m"); s5 = self._reg.get("5s")
        reg5 = s5.regime if s5 is not None else 0
        closed_1m = s1m is not None and s1m.close_ts != self._last_1m
        new_entries = []
        if closed_1m:
            self._last_1m = s1m.close_ts; self._n_1m += 1
            regime = s1m.regime; prev = self._prev_1m
            flipped = (regime != prev and regime != 0)
            if flipped:
                self._close_all(int(s1m.close_ts), s1m.close)
                new_entries.append(("A", regime))
                self._pending_bar1 = {"dir": regime, "flip_h": s1m.high,
                                      "flip_l": s1m.low, "flip_close_ts": s1m.close_ts}
            else:
                pb = self._pending_bar1
                if pb and s1m.open_ts == pb["flip_close_ts"] and regime == pb["dir"]:
                    conf = ((s1m.high > pb["flip_h"] and s1m.close > s1m.open)
                            if regime == 1 else
                            (s1m.low < pb["flip_l"] and s1m.close < s1m.open))
                    if conf:
                        new_entries.append(("B", regime))
                    self._pending_bar1 = None
                elif pb and s1m.open_ts > pb["flip_close_ts"]:
                    self._pending_bar1 = None
            self._prev_1m = regime
        for pop, d in new_entries:
            self._open_entry(pop, d, o, int(tsi), s1m)
        if self._open:
            for tr in self._open:
                tr.on_1s(int(tsi), o, h, l, c, tr.d * reg5)

    def finalize(self):
        s1m = self._reg.get("1m")
        if s1m is not None and self._open:
            self._close_all(int(s1m.close_ts), s1m.close)
        self._open = []

"""RegimeFlipTruthCollector — research-mode NT strategy (NO ORDERS).

Builds a clean event dataset answering: which 1m regime flips become clean,
persistent trends vs fakeouts, and can we recognize them early.

This collector does NOT trade. It is strictly truth collection:
  - detect 1m regime flips from the CAUSAL CompletedBarRegistry
  - emit TWO event populations per regime:
      A: raw flip          -> "entry" at the flip 1m bar's CLOSE
      B: bar1-confirmed    -> "entry" at bar1's CLOSE (HH/LL + directional close)
  - track each event's path on 1s bars from entry to the NEXT OPPOSITE 1m flip
  - compute MFE/MAE/terminal PnL, path milestones, clean-trend labels
  - snapshot rich entry features (MTF regime, MA/BB/Keltner, vol, volume,
    velocity, prior-regime context)
  - emit early-evolution checkpoints (entry, +30/60/90/120/180s, Bar2/3/5)

CAUSALITY INVARIANTS (why this has no look-ahead):
  1. decision_ts = bar.ts_init ALWAYS (never ts_event). For 1s bars,
     ts_init = ts_event + 1s, i.e. the bar has physically closed.
  2. All multi-timeframe regime/ATR/EMA state is read ONLY from
     CompletedBarRegistry, whose hard invariant is close_ts <= decision_ts.
     registry.audit_provenance(decision_ts) is called before every snapshot;
     a violation raises and kills the backtest (fail-fast).
  3. The aggregator closes a bucket only when a 1s bar of the NEXT bucket
     arrives, so no in-progress bar is ever read.
  4. Entry is at a 1m boundary (flip close / bar1 close); path MFE/MAE is
     tracked over 1s bars with ts_event >= entry_ts, all of which arrive in
     LATER on_bar calls. There is no first-minute blind spot (entry == the
     bar boundary, not "the next 1s after a signal").
  5. Structural indicators (indicators.py) are recursive/deque streaming over
     completed 1m bars; the feature engine is update()'d with the flip/bar1
     bar BEFORE its features are snapshotted, so features include the bar that
     defines the entry and nothing after it.
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

from nautilus_trader.config import StrategyConfig          # noqa: E402
from nautilus_trader.trading.strategy import Strategy        # noqa: E402

from collectors.collector_v2.registry import (               # noqa: E402
    CompletedBarRegistry, CompletedBarState,
)
from collectors.collector_v2.aggregator import (             # noqa: E402
    TimeframeAggregator,
)
from collectors.collector_v2.regime_engine import (          # noqa: E402
    RegimeStateEngine,
)
from studies.regime_flip_truth.indicators import (           # noqa: E402
    OneMinuteFeatureEngine, SessionVWAP, _Regime,
)

CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000

# Timeframes for MTF regime context. 1m is the entry timeframe.
TFS = ("5s", "30s", "1m", "5m")

# Path milestones (ATR units).
MILESTONES = (0.5, 1.0, 2.0, 3.0)
MAE_BEFORE = (0.5, 1.0, 2.0)
# Adverse-excursion threshold crossing times to record (ATR units).
MAE_THRESH = (0.5, 0.75, 1.0)

# Checkpoint offsets from entry (ns). BarN = N 1m bars after entry (entry is a
# 1m boundary, so BarN offset = N*60s).
CHECKPOINTS = [
    ("entry", 0),
    ("+30s", 30 * NS_PER_S),
    ("+60s", 60 * NS_PER_S),
    ("+90s", 90 * NS_PER_S),
    ("+120s", 120 * NS_PER_S),
    ("+180s", 180 * NS_PER_S),
    ("Bar2", 2 * 60 * NS_PER_S),
    ("Bar3", 3 * 60 * NS_PER_S),
    ("Bar5", 5 * 60 * NS_PER_S),
]

RTH_START_MIN = 510   # 08:30 CT
RTH_END_MIN = 900     # 15:00 CT


class RegimeFlipTruthConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1s: str
    output_dir: str = ""


class RegimeFlipTruthCollector(Strategy):

    def __init__(self, config: RegimeFlipTruthConfig):
        super().__init__(config)
        self._cfg = config

        # --- Causal MTF stack (5s-inclusive; collector_v2 default untouched) ---
        self._registry = CompletedBarRegistry(supported_timeframes=TFS)
        self._engines = {tf: RegimeStateEngine(tf, self._registry) for tf in TFS}
        self._aggregator = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed, timeframes=TFS)

        # --- Structural indicators on 1m closes + session VWAP on 1s ---
        self._feat = OneMinuteFeatureEngine()
        self._vwap = SessionVWAP()

        # --- Flip / event state ---
        self._last_seen_1m_close_ts = 0
        self._prev_1m_regime = 0
        # pending bar1 confirmation: {dir, flip_h, flip_l, flip_close_ts}
        self._pending_bar1: dict | None = None
        # open events (<=2: one A + optionally one B for the current regime)
        self._open: list[dict] = []
        # prior-regime context handed to each new event's snapshot
        self._prior = _Regime()
        # flip timestamps for flip-density features
        self._flip_ts_hist: deque[int] = deque(maxlen=4096)
        self._prev_flip_close_ts: int | None = None

        # 1s buffer for sub-minute (30s) returns at entry
        self._recent_1s: deque = deque(maxlen=400)

        self._event_seq = 0

        # outputs
        self.events: list[dict] = []
        self.checkpoints: list[dict] = []

        self._diag = {
            "1s_bars": 0,
            "1m_closes": 0,
            "flips": 0,
            "events_A": 0,
            "events_B": 0,
            "bar1_confirmed": 0,
            "bar1_rejected": 0,
            "events_resolved": 0,
        }

    # ---- Subscriptions ----
    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ---- aggregator -> engine bridge ----
    def _on_bucket_closed(self, tf: str, completed):
        self._engines[tf].on_bar_closed(completed)

    # ---- main 1s loop ----
    def on_bar(self, bar):
        if str(bar.bar_type) != self._cfg.bar_type_1s:
            return
        decision_ts = int(bar.ts_init)
        o = float(bar.open); h = float(bar.high)
        l = float(bar.low); c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # (1) buffer the closed 1s bar (for 30s entry return; the 30s lookup
        #     filters ts_event <= entry_ts - 30s so the triggering bar, even
        #     though buffered here, never enters an entry computation).
        self._recent_1s.append({"ts_event": int(bar.ts_event),
                                "ts_init": decision_ts, "c": c})
        self._diag["1s_bars"] += 1

        # (2) feed aggregator -> may close 5s/30s/1m/5m buckets -> registry
        self._aggregator.on_1s_bar(int(bar.ts_event), o, h, l, c, v)

        # (3) did the 1m registry state advance? -> a 1m bar just closed.
        #     Entry snapshots fire INSIDE _on_1m_close. They must read VWAP
        #     as-of the entry boundary (entry_ts), which EXCLUDES this
        #     triggering 1s bar (it closes at decision_ts = entry_ts + 1s).
        #     Hence VWAP is updated AFTER this block. [audit W1]
        s_1m = self._registry.get("1m")
        if s_1m is not None and s_1m.close_ts != self._last_seen_1m_close_ts:
            self._last_seen_1m_close_ts = s_1m.close_ts
            self._on_1m_close(decision_ts, s_1m)

        # (4) NOW fold this 1s bar into the session VWAP. It has closed at
        #     decision_ts, so downstream path checkpoints (step 5) correctly
        #     see it; the entry snapshot above correctly did not.
        self._vwap.update_1s(decision_ts, h, l, c, v)

        # (5) update open events' path with THIS 1s bar (causal: closed)
        if self._open:
            for ev in self._open:
                self._update_path(ev, int(bar.ts_event), h, l, c, decision_ts)

    # ------------------------------------------------------------------
    # 1m close: update features, detect flip, manage events
    # ------------------------------------------------------------------
    def _on_1m_close(self, decision_ts: int, s_1m: CompletedBarState):
        self._diag["1m_closes"] += 1

        # (A) advance structural indicators with the just-closed 1m bar FIRST,
        #     so any snapshot below reflects this bar (inclusive) and nothing
        #     after it.
        self._feat.update(s_1m.open, s_1m.high, s_1m.low, s_1m.close,
                          s_1m.volume)
        self._feat.push_atr(s_1m.atr)

        regime = s_1m.regime
        prev = self._prev_1m_regime
        flipped = (regime != prev and regime != 0)

        # (B) resolve any open events first IF this is an opposite-flip bar.
        if flipped and self._open:
            self._resolve_open_events(decision_ts, s_1m)

        if flipped:
            self._diag["flips"] += 1
            # prior-regime context = the regime that just ended
            self._update_prior_context(s_1m)
            self._flip_ts_hist.append(s_1m.close_ts)
            # create Population A event at this flip bar's close
            self._open_event("A", decision_ts, s_1m, regime,
                             entry_px=s_1m.close, flip_close_ts=s_1m.close_ts,
                             flip_px=s_1m.close)
            self._diag["events_A"] += 1
            # arm bar1 confirmation for the NEXT 1m bar
            self._pending_bar1 = {
                "dir": regime,
                "flip_h": s_1m.high,
                "flip_l": s_1m.low,
                "flip_close_ts": s_1m.close_ts,
                "flip_px": s_1m.close,
            }
            self._prev_flip_close_ts = s_1m.close_ts
        else:
            # not a flip — maybe this is bar1 (the bar immediately after a flip)
            if (self._pending_bar1 is not None
                    and s_1m.open_ts == self._pending_bar1["flip_close_ts"]
                    and regime == self._pending_bar1["dir"]):
                self._check_bar1(decision_ts, s_1m)
                self._pending_bar1 = None
            elif (self._pending_bar1 is not None
                  and s_1m.open_ts > self._pending_bar1["flip_close_ts"]):
                # missed bar1 (data gap) — disarm without confirming
                self._pending_bar1 = None

        self._prev_1m_regime = regime

    def _check_bar1(self, decision_ts: int, s_1m: CompletedBarState):
        d = self._pending_bar1["dir"]
        fh = self._pending_bar1["flip_h"]
        fl = self._pending_bar1["flip_l"]
        if d == 1:
            confirmed = (s_1m.high > fh and s_1m.close > s_1m.open)
        else:
            confirmed = (s_1m.low < fl and s_1m.close < s_1m.open)
        # cross-link: backfill the open Population A event's bar1_confirmed
        for ev in self._open:
            if ev["population"] == "A" and ev["direction"] == d:
                ev["bar1_confirmed"] = bool(confirmed)
        if confirmed:
            self._diag["bar1_confirmed"] += 1
            self._diag["events_B"] += 1
            self._open_event("B", decision_ts, s_1m, d,
                             entry_px=s_1m.close,
                             flip_close_ts=self._pending_bar1["flip_close_ts"],
                             flip_px=self._pending_bar1["flip_px"])
        else:
            self._diag["bar1_rejected"] += 1

    # ------------------------------------------------------------------
    # event lifecycle
    # ------------------------------------------------------------------
    def _open_event(self, population: str, decision_ts: int,
                    s_1m: CompletedBarState, direction: int,
                    entry_px: float, flip_close_ts: int, flip_px: float):
        # air-gap: assert all registry TF states are causal at decision_ts
        self._registry.audit_provenance(decision_ts)

        atr = s_1m.atr
        entry_ts = s_1m.close_ts  # 1m bar close (entry moment)
        self._event_seq += 1
        feats = self._feat.snapshot(direction, atr, self._prior)
        feats.update(self._mtf_context(direction))
        feats.update(self._entry_micro(direction, atr, entry_px, entry_ts))

        # Confirm/entry-bar shape (s_1m = flip bar for A, bar1 for B; CLOSED).
        # All causal — read from the just-closed bar that defines the entry.
        a = atr if (atr and atr == atr and atr > 0) else float("nan")
        rng = s_1m.high - s_1m.low
        body = abs(s_1m.close - s_1m.open)
        if rng > 0:
            close_loc = ((s_1m.close - s_1m.low) / rng if direction == 1
                         else (s_1m.high - s_1m.close) / rng)
        else:
            close_loc = float("nan")
        confirm_range_atr = rng / a if a == a else float("nan")
        confirm_body_atr = body / a if a == a else float("nan")
        # gap from flip close to entry (0 for A; for B = bar1 extension beyond
        # the flip bar in the trade direction), ATR-normalized
        gap_atr = (direction * (entry_px - flip_px) / a) if a == a else float("nan")

        ct = pd.Timestamp(int(entry_ts), tz="UTC").tz_convert(CT)
        min_ct = ct.hour * 60 + ct.minute
        rth = (RTH_START_MIN <= min_ct < RTH_END_MIN)

        ev = {
            "event_id": self._event_seq,
            "population": population,
            "direction": direction,
            "entry_ts": entry_ts,
            "entry_px": entry_px,
            "atr_at_entry": atr,
            "flip_close_ts": flip_close_ts,
            "time_since_flip_s": (entry_ts - flip_close_ts) / NS_PER_S,
            "rth_flag": bool(rth),
            "entry_ct": ct.strftime("%Y-%m-%d %H:%M:%S"),
            "bar1_confirmed": (True if population == "B" else None),
            "warmed_up": bool(self._feat.n_bars >= 50
                              and atr is not None and atr == atr),
            # confirm/entry-bar shape
            "confirm_bar_range_atr": confirm_range_atr,
            "confirm_bar_body_atr": confirm_body_atr,
            "close_loc_in_confirm_bar": close_loc,
            "gap_flip_to_entry_atr": gap_atr,
            "features": feats,
            # --- live path accumulators (causal, updated on 1s bars) ---
            "_entry_1m_close_ts": entry_ts,
            "running_mfe": -1e18,
            "running_mae": -1e18,
            "_max_high": -1e18,
            "_min_low": 1e18,
            "_hh_count": 0,
            "_ll_count": 0,
            "_t_last_new_mfe": entry_ts,
            "_t_running_mae": entry_ts,     # time of current max MAE
            "_cum_abs_move": 0.0,
            "_prev_path_close": entry_px,
            "_n_path_bars": 0,
            "reached": {m: False for m in MILESTONES},
            "mae_before": {m: float("nan") for m in MAE_BEFORE},
            # seconds from entry to first touch of each MFE milestone (causal:
            # stamped with decision_ts at the crossing bar). NaN if never hit.
            "t_reach": {m: float("nan") for m in MILESTONES},
            # seconds to first touch of each adverse (MAE) threshold
            "t_mae": {m: float("nan") for m in MAE_THRESH},
            "_mae_reached": {m: False for m in MAE_THRESH},
            # time of the max-MAE that occurred BEFORE the +2 ATR MFE touch
            "t_max_mae_before_2atr": float("nan"),
            # 5s / 30s regime path: first time the regime turns OPPOSED to the
            # trade direction, and how many times it flips in the first 90s
            # (churn). Seeded with the regime in force at entry. Causal: read
            # from the registry (close_ts <= decision_ts always).
            "t_first_5s_opposed": float("nan"),
            "t_first_30s_opposed": float("nan"),
            "_n_5s_flips_90s": 0,
            "_n_30s_flips_90s": 0,
            "_prev_5s": self._reg_now("5s"),
            "_prev_30s": self._reg_now("30s"),
            "_ckpt_done": set(),
        }
        self._open.append(ev)
        # emit the entry checkpoint immediately
        self._emit_checkpoint(ev, "entry", entry_ts, reached=True)
        ev["_ckpt_done"].add("entry")

    def _update_path(self, ev: dict, ts_event: int, h: float, l: float,
                     c: float, decision_ts: int):
        if ts_event < ev["entry_ts"]:
            return  # bar predates entry — not part of this event's path
        # Runtime air-gap for the path-path regime reads below (symmetric with
        # the entry path's check) — fail fast if any TF state is non-causal.
        self._registry.audit_provenance(decision_ts)
        d = ev["direction"]
        ep = ev["entry_px"]
        atr = ev["atr_at_entry"]
        a = atr if (atr and atr == atr and atr > 0) else float("nan")

        # running MFE / MAE in price points
        if d == 1:
            mfe = h - ep
            mae = ep - l
        else:
            mfe = ep - l
            mae = h - ep
        if mfe > ev["running_mfe"]:
            ev["running_mfe"] = mfe
            ev["_t_last_new_mfe"] = decision_ts
        if mae > ev["running_mae"]:
            ev["running_mae"] = mae
            ev["_t_running_mae"] = decision_ts

        # 5s / 30s regime path: first opposed time + churn count in first 90s.
        # Causal — _reg_now reads the last CLOSED bar's regime.
        within90 = (decision_ts - ev["entry_ts"]) <= 90 * NS_PER_S
        for tf, tkey, pkey, nkey in (
                ("5s", "t_first_5s_opposed", "_prev_5s", "_n_5s_flips_90s"),
                ("30s", "t_first_30s_opposed", "_prev_30s", "_n_30s_flips_90s")):
            r = self._reg_now(tf)
            if r == -d and ev[tkey] != ev[tkey]:   # opposed & not yet recorded
                ev[tkey] = (decision_ts - ev["entry_ts"]) / NS_PER_S
            if within90 and r != 0 and r != ev[pkey]:
                ev[nkey] += 1
                ev[pkey] = r

        # HH / LL counts (raw new extremes on 1s highs/lows)
        if h > ev["_max_high"]:
            ev["_max_high"] = h
            ev["_hh_count"] += 1
        if l < ev["_min_low"]:
            ev["_min_low"] = l
            ev["_ll_count"] += 1

        # path length (for efficiency) on 1s closes
        ev["_cum_abs_move"] += abs(c - ev["_prev_path_close"])
        ev["_prev_path_close"] = c
        ev["_n_path_bars"] += 1

        # path milestones (favorable MFE in ATR)
        if a == a:
            cur_mfe_atr = ev["running_mfe"] / a
            cur_mae_atr = ev["running_mae"] / a
            for m in MILESTONES:
                if not ev["reached"][m] and cur_mfe_atr >= m:
                    ev["reached"][m] = True
                    ev["t_reach"][m] = (decision_ts - ev["entry_ts"]) / NS_PER_S
                    if m in ev["mae_before"]:
                        ev["mae_before"][m] = cur_mae_atr
                    # freeze the TIME of the worst adverse excursion seen up to
                    # the first +2 ATR touch (for DD-location analysis)
                    if m == 2.0:
                        ev["t_max_mae_before_2atr"] = (
                            ev["_t_running_mae"] - ev["entry_ts"]) / NS_PER_S
            # adverse-excursion threshold crossing times (1s-precise)
            for am in MAE_THRESH:
                if not ev["_mae_reached"][am] and cur_mae_atr >= am:
                    ev["_mae_reached"][am] = True
                    ev["t_mae"][am] = (decision_ts - ev["entry_ts"]) / NS_PER_S

        # time/bar checkpoints. Trigger on decision_ts (= bar CLOSE time), so
        # "+30s" fires on the bar that closes exactly at entry_ts+30s and the
        # recorded ts equals that landmark. Running MFE/MAE/etc. above already
        # include this bar (closed at decision_ts), so the snapshot is the true
        # state as-of the landmark. [audit W2]
        for label, off in CHECKPOINTS:
            if label in ev["_ckpt_done"]:
                continue
            if decision_ts >= ev["entry_ts"] + off:
                self._emit_checkpoint(ev, label, decision_ts, reached=True,
                                      cur_close=c)
                ev["_ckpt_done"].add(label)

    def _resolve_open_events(self, decision_ts: int, flip_1m: CompletedBarState):
        """Opposite flip detected -> terminate every open event at the flip
        bar's close (regime end)."""
        terminal_px = flip_1m.close
        terminal_ts = flip_1m.close_ts
        for ev in self._open:
            self._finalize(ev, terminal_px, terminal_ts, decision_ts,
                           reason="regime_flip")
        self._open = []

    def on_stop(self):
        # finalize any still-open events at the last seen price (unresolved)
        s_1m = self._registry.get("1m")
        if s_1m is not None:
            for ev in self._open:
                self._finalize(ev, s_1m.close, s_1m.close_ts, s_1m.close_ts,
                               reason="end_of_data")
        self._open = []

    def _finalize(self, ev: dict, terminal_px: float, terminal_ts: int,
                  decision_ts: int, reason: str):
        d = ev["direction"]
        ep = ev["entry_px"]
        atr = ev["atr_at_entry"]
        a = atr if (atr and atr == atr and atr > 0) else float("nan")

        mfe_pts = max(ev["running_mfe"], -1e17)
        mae_pts = max(ev["running_mae"], -1e17)
        if mfe_pts < -1e16:
            mfe_pts = 0.0
        if mae_pts < -1e16:
            mae_pts = 0.0
        term_pnl_pts = d * (terminal_px - ep)
        dur_s = (terminal_ts - ev["entry_ts"]) / NS_PER_S
        dur_bars = int(round((terminal_ts - ev["entry_ts"]) / (60 * NS_PER_S)))

        mfe_atr = mfe_pts / a if a == a else float("nan")
        mae_atr = mae_pts / a if a == a else float("nan")
        term_pnl_atr = term_pnl_pts / a if a == a else float("nan")

        # clean-trend labels
        clean_a = bool(mfe_atr >= 2.0 and mae_atr <= 0.75) if mfe_atr == mfe_atr else False
        clean_b = bool(mfe_atr >= 3.0 and mae_atr <= 1.0) if mfe_atr == mfe_atr else False
        persistent = bool(dur_bars >= 15)
        elite = bool(persistent and mfe_atr >= 2.0 and mae_atr <= 0.75) \
            if mfe_atr == mfe_atr else False

        row = {
            "event_id": ev["event_id"],
            "population": ev["population"],
            "direction": ev["direction"],
            "entry_ts": ev["entry_ts"],
            "entry_px": ev["entry_px"],
            "atr_at_entry": ev["atr_at_entry"],
            "entry_ct": ev["entry_ct"],
            "rth_flag": ev["rth_flag"],
            "time_since_flip_s": ev["time_since_flip_s"],
            "bar1_confirmed": ev["bar1_confirmed"],
            "warmed_up": ev["warmed_up"],
            "exit_reason": reason,
            "terminal_ts": terminal_ts,
            "terminal_px": terminal_px,
            # outcomes
            "mfe_pts": mfe_pts,
            "mae_pts": mae_pts,
            "mfe_atr": mfe_atr,
            "mae_atr": mae_atr,
            "terminal_pnl_pts": term_pnl_pts,
            "terminal_pnl_atr": term_pnl_atr,
            "regime_duration_s": dur_s,
            "regime_duration_bars": dur_bars,
            "n_path_bars": ev["_n_path_bars"],
            # confirm/entry-bar shape (Study 3)
            "confirm_bar_range_atr": ev["confirm_bar_range_atr"],
            "confirm_bar_body_atr": ev["confirm_bar_body_atr"],
            "close_loc_in_confirm_bar": ev["close_loc_in_confirm_bar"],
            "gap_flip_to_entry_atr": ev["gap_flip_to_entry_atr"],
            # milestones
            **{f"reached_{str(m).replace('.', '_')}_atr": bool(ev["reached"][m])
               for m in MILESTONES},
            **{f"mae_before_{str(m).replace('.', '_')}_atr": ev["mae_before"][m]
               for m in MAE_BEFORE},
            **{f"t_reach_{str(m).replace('.', '_')}_atr_s": ev["t_reach"][m]
               for m in MILESTONES},
            # adverse-excursion timing (Study 1 & 2)
            **{f"t_mae_{str(m).replace('.', '_')}_atr_s": ev["t_mae"][m]
               for m in MAE_THRESH},
            "t_max_mae_s": (ev["_t_running_mae"] - ev["entry_ts"]) / NS_PER_S,
            "t_max_mae_before_2atr_s": ev["t_max_mae_before_2atr"],
            # 5s / 30s regime path (Study: quicker cut signal)
            "t_first_5s_opposed_s": ev["t_first_5s_opposed"],
            "t_first_30s_opposed_s": ev["t_first_30s_opposed"],
            "n_5s_flips_first90s": ev["_n_5s_flips_90s"],
            "n_30s_flips_first90s": ev["_n_30s_flips_90s"],
            # labels
            "clean_trend_a": clean_a,
            "clean_trend_b": clean_b,
            "persistent_trend": persistent,
            "elite_trend": elite,
        }
        # flatten features
        for k, val in ev["features"].items():
            row[f"feat_{k}"] = val
        self.events.append(row)
        self._diag["events_resolved"] += 1

        # emit any remaining (unreached) checkpoints, frozen at terminal
        for label, off in CHECKPOINTS:
            if label not in ev["_ckpt_done"]:
                self._emit_checkpoint(ev, label, terminal_ts, reached=False,
                                      cur_close=terminal_px)
                ev["_ckpt_done"].add(label)

    # ------------------------------------------------------------------
    # snapshots / context
    # ------------------------------------------------------------------
    def _emit_checkpoint(self, ev: dict, label: str, ts: int, reached: bool,
                         cur_close: float | None = None):
        atr = ev["atr_at_entry"]
        a = atr if (atr and atr == atr and atr > 0) else float("nan")
        d = ev["direction"]
        ep = ev["entry_px"]
        mfe = ev["running_mfe"] if ev["running_mfe"] > -1e16 else 0.0
        mae = ev["running_mae"] if ev["running_mae"] > -1e16 else 0.0
        c = cur_close if cur_close is not None else ep
        cur_pnl_pts = d * (c - ep)
        # distances at checkpoint
        vwap = self._vwap.value
        ema13 = self._feat._emas[13].value
        dist_vwap = (d * (c - vwap) / a) if (vwap is not None and a == a) else float("nan")
        dist_ema13 = (d * (c - ema13) / a) if (ema13 is not None and a == a) else float("nan")
        stall_s = (ts - ev["_t_last_new_mfe"]) / NS_PER_S
        eff = (d * (c - ep) / ev["_cum_abs_move"]) if ev["_cum_abs_move"] > 0 else float("nan")

        self.checkpoints.append({
            "event_id": ev["event_id"],
            "population": ev["population"],
            "direction": ev["direction"],
            "checkpoint": label,
            "ts": ts,
            "reached": bool(reached),
            "cur_mfe_atr": (mfe / a) if a == a else float("nan"),
            "cur_mae_atr": (mae / a) if a == a else float("nan"),
            "cur_pnl_atr": (cur_pnl_pts / a) if a == a else float("nan"),
            "stall_s": stall_s,
            "hh_count": ev["_hh_count"],
            "ll_count": ev["_ll_count"],
            "dist_from_vwap_atr": dist_vwap,
            "dist_from_ema13_atr": dist_ema13,
            "path_efficiency": eff,
            "n_path_bars": ev["_n_path_bars"],
            # current MTF regime alignment (+1 aligned / -1 opposed / 0 neutral)
            "align_5s": d * self._reg_now("5s"),
            "align_30s": d * self._reg_now("30s"),
        })

    def _reg_now(self, tf: str) -> int:
        """Current (causal) regime for a timeframe: the last CLOSED bar's
        regime from the registry (close_ts <= decision_ts by invariant)."""
        st = self._registry.get(tf)
        return st.regime if st is not None else 0

    def _mtf_context(self, direction: int) -> dict:
        out = {}
        for tf in TFS:
            st = self._registry.get(tf)
            r = st.regime if st is not None else 0
            out[f"regime_{tf}"] = r
            if r == 0:
                align = "neutral"
            elif r == direction:
                align = "aligned"
            else:
                align = "opposed"
            out[f"align_{tf}"] = align
        return out

    def _entry_micro(self, direction: int, atr: float, entry_px: float,
                     entry_ts: int) -> dict:
        a = atr if (atr and atr == atr and atr > 0) else float("nan")
        # 30s return from the 1s buffer (close 30s before entry)
        target = entry_ts - 30 * NS_PER_S
        c_30s_ago = None
        for b in reversed(self._recent_1s):
            if b["ts_event"] <= target:
                c_30s_ago = b["c"]
                break
        ret_30s = (direction * (entry_px - c_30s_ago) / a) \
            if (c_30s_ago is not None and a == a) else float("nan")
        # VWAP distance at entry
        vwap = self._vwap.value
        sigma = self._vwap.sigma
        dist_vwap = (direction * (entry_px - vwap) / a) \
            if (vwap is not None and a == a) else float("nan")
        vwap_z = ((entry_px - vwap) / sigma) \
            if (vwap is not None and sigma is not None and sigma > 0) else float("nan")
        # flip density
        now = entry_ts
        flips_30m = sum(1 for t in self._flip_ts_hist
                        if now - 30 * 60 * NS_PER_S <= t <= now)
        flips_60m = sum(1 for t in self._flip_ts_hist
                        if now - 60 * 60 * NS_PER_S <= t <= now)
        tsf = ((now - self._prev_flip_close_ts) / NS_PER_S
               if self._prev_flip_close_ts is not None else float("nan"))
        return {
            "ret_30s_atr": ret_30s,
            "dist_from_vwap_atr": dist_vwap,
            "vwap_z": vwap_z,
            "flips_last_30m": flips_30m,
            "flips_last_60m": flips_60m,
            "time_since_prev_flip_s": tsf,
        }

    def _update_prior_context(self, flip_1m: CompletedBarState):
        """When a flip occurs, the regime that just ended is summarized by the
        open Population A event for that regime (entered at its start). Capture
        its terminal MFE/MAE/duration as prior-regime context for the new
        event. Called AFTER _resolve_open_events, so self.events has the just-
        finalized rows."""
        prior_a = None
        for row in reversed(self.events):
            if row["population"] == "A":
                prior_a = row
                break
        if prior_a is not None:
            self._prior = _Regime(
                prior_regime_duration_bars=float(prior_a["regime_duration_bars"]),
                prior_regime_duration_s=float(prior_a["regime_duration_s"]),
                prior_regime_mfe_atr=float(prior_a["mfe_atr"]),
                prior_regime_mae_atr=float(prior_a["mae_atr"]),
            )
        else:
            self._prior = _Regime()

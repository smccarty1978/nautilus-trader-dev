"""NT strategy: Trigger C entry + fixed ATR initial stop + profit lock.

Entry: 5s regime realignment + 50% pullback reclaim (Trigger C).
Exit:
  - initial_stop: fixed ATR stop from entry price (fires on 1s bar low/high)
  - lock_floor  : once MFE >= lock_at_atr, stop updated to entry + lock_floor_atr
  - regime_flip : 1m regime flips direction, market exit immediately

Stop is monitored on every 1s bar (bar.low/high), not just 5s closes.
With bar_execution=True the exit market order fills at the NEXT 1s bar open.

Universe: hC >= hc_floor, Healthy or HH-HardStall, bar 8+ complete.
"""
from __future__ import annotations
import math
import sys
from collections import deque
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket

# ── Constants ──────────────────────────────────────────────────────────────────
MULT        = 20.0
COMM        = 4.06
NS_PER_MIN  = 60_000_000_000
IS_STALL_P33 = 0.044
IS_STALL_P67 = 0.304

CHECKPOINTS = [0.25, 0.50, 1.00, 1.50, 2.00]
CK_KEYS     = [f"{int(c * 100):03d}" for c in CHECKPOINTS]


def _state_cat(hc_val: float, state_raw: str) -> str:
    if state_raw == "Healthy":   return "Healthy"
    if state_raw == "DETER":     return "DETER"
    if state_raw in ("HardStall", "SoftStall"):
        if hc_val >= IS_STALL_P67: return "HH-HardStall"
        if hc_val >= IS_STALL_P33: return "MH-HardStall"
        return "LH-HardStall"
    return "Other"


# ── 1m regime engine (identical to collector_triggers.py) ─────────────────────

class _1mRegimeEngine:
    ALPHA3 = 2.0 / (3 + 1)
    ALPHA9 = 2.0 / (9 + 1)
    ATR_PERIOD = 14

    def __init__(self) -> None:
        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._atr_warmup: list[float] = []
        self._atr: Optional[float] = None
        self.regime: int = 0
        self.bars_in_regime: int = 0

    @property
    def atr(self) -> Optional[float]: return self._atr
    @property
    def ema3_h(self) -> Optional[float]: return self._ema3_h
    @property
    def ema9_h(self) -> Optional[float]: return self._ema9_h
    @property
    def ema3_l(self) -> Optional[float]: return self._ema3_l
    @property
    def ema9_l(self) -> Optional[float]: return self._ema9_l

    def update(self, bucket: _OpenBucket) -> None:
        h, l, c = bucket.high, bucket.low, bucket.close
        if self._ema3_h is None:
            self._ema3_h = h; self._ema9_h = h
            self._ema3_l = l; self._ema9_l = l
        else:
            a3, a9 = self.ALPHA3, self.ALPHA9
            self._ema3_h = a3 * h + (1 - a3) * self._ema3_h
            self._ema9_h = a9 * h + (1 - a9) * self._ema9_h
            self._ema3_l = a3 * l + (1 - a3) * self._ema3_l
            self._ema9_l = a9 * l + (1 - a9) * self._ema9_l

        tr = (h - l) if self._prev_close is None else max(
            h - l, abs(h - self._prev_close), abs(l - self._prev_close)
        )
        self._prev_close = c
        if self._atr is None:
            self._atr_warmup.append(tr)
            if len(self._atr_warmup) == self.ATR_PERIOD:
                self._atr = sum(self._atr_warmup) / self.ATR_PERIOD
                self._atr_warmup = []
        else:
            self._atr = (self._atr * (self.ATR_PERIOD - 1) + tr) / self.ATR_PERIOD

        new = self.regime
        if c > self._ema3_h and c > self._ema9_h: new = 1
        elif c < self._ema3_l and c < self._ema9_l: new = -1
        if new != 0 and new != self.regime:
            self.bars_in_regime = 1; self.regime = new
        elif new != 0:
            self.bars_in_regime += 1


# ── 5s regime engine ──────────────────────────────────────────────────────────

class _5sRegimeEngine:
    ALPHA3 = 2.0 / (3 + 1)
    ALPHA9 = 2.0 / (9 + 1)
    ATR_PERIOD = 14

    def __init__(self) -> None:
        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._atr_warmup: list[float] = []
        self._atr: Optional[float] = None
        self.regime: int = 0

    def update(self, h: float, l: float, c: float) -> None:
        if self._ema3_h is None:
            self._ema3_h = h; self._ema9_h = h
            self._ema3_l = l; self._ema9_l = l
        else:
            a3, a9 = self.ALPHA3, self.ALPHA9
            self._ema3_h = a3 * h + (1 - a3) * self._ema3_h
            self._ema9_h = a9 * h + (1 - a9) * self._ema9_h
            self._ema3_l = a3 * l + (1 - a3) * self._ema3_l
            self._ema9_l = a9 * l + (1 - a9) * self._ema9_l

        tr = (h - l) if self._prev_close is None else max(
            h - l, abs(h - self._prev_close), abs(l - self._prev_close)
        )
        self._prev_close = c
        if self._atr is None:
            self._atr_warmup.append(tr)
            if len(self._atr_warmup) == self.ATR_PERIOD:
                self._atr = sum(self._atr_warmup) / self.ATR_PERIOD
                self._atr_warmup = []
        else:
            self._atr = (self._atr * (self.ATR_PERIOD - 1) + tr) / self.ATR_PERIOD

        new = self.regime
        if self._ema3_h is not None and c > self._ema3_h and c > self._ema9_h:
            new = 1
        elif self._ema3_l is not None and c < self._ema3_l and c < self._ema9_l:
            new = -1
        if new != 0:
            self.regime = new


# ── Config ────────────────────────────────────────────────────────────────────

class CLockConfig(StrategyConfig, frozen=True):
    instrument_id:    str   = "NQ.XCME"
    bar_type_1s:      str   = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    initial_stop_atr: float = 0.50   # fixed ATR stop from entry price
    lock_at_atr:      float = 1.00   # MFE level that arms the profit lock
    lock_floor_atr:   float = 0.25   # minimum ATR profit once locked
    hc_floor:         float = 0.50
    trade_size:       int   = 1
    hc_mapping_path:  str   = (
        "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
    )
    # Trigger-bar quality filter applied at entry signal time.
    # "none"          — no additional filter (baseline)
    # "dir_close"     — long: close > open; short: close < open
    # "min_body25"    — body >= 25% of bar range
    # "strong_close"  — long: close in top 40% of range; short: bottom 40%
    # "dir_body25"    — dir_close AND min_body25
    bar_filter: str = "none"
    # Minimum pullback depth (in ATR units, measured from running extreme to
    # pb_worst_close) required before Trigger C can fire. 0.0 = no minimum.
    min_pb_depth_atr: float = 0.0


# ── Strategy ──────────────────────────────────────────────────────────────────

class CLockStrategy(Strategy):
    """Trigger C entry with fixed ATR initial stop and profit lock."""

    def __init__(self, cfg: CLockConfig) -> None:
        super().__init__(cfg)
        self._cfg = cfg

    def on_start(self) -> None:
        self._inst_id = InstrumentId.from_str(self._cfg.instrument_id)

        p = Path(self._cfg.hc_mapping_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        df = pd.read_parquet(p)
        self._hc_map: dict[tuple, tuple] = {
            (int(r.regime_start_ts), int(r.bars_in_regime)): (r.hC, r.state)
            for r in df.itertuples(index=False)
        }

        self._1m_eng = _1mRegimeEngine()
        self._5s_eng = _5sRegimeEngine()
        self._agg    = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=("1m", "5s"),
        )
        self._atr_hist: deque = deque(maxlen=60)

        # 1m regime state
        self._prev_regime: int   = 0
        self._in_regime:   bool  = False
        self._rs_ts:       int   = 0
        self._dir:         int   = 0
        self._atr_base:    float = 0.0
        self._hC_val:      float = float("nan")
        self._hC_vel:      float = float("nan")
        self._state_str:   str   = ""
        self._run_ext:     float = 0.0
        self._peak_ts:     int   = 0

        # Regime entry tracking
        self._watching:      bool = False
        self._pb_count:      int  = 0
        self._need_new_peak: bool = False

        # Pullback state
        self._pb_active:          bool  = False
        self._pb_sl:              float = 0.0    # deepest pullback close (structural low/high)
        self._pb_start_ts:        int   = 0
        self._pb_depth_at_trigger: float = 0.0
        self._max_pb_depth:       float = 0.0    # max depth reached (peak→worst_close)/atr
        self._pb_worst_close:     float = 0.0    # most adverse 5s close
        self._5s_regime_cur:      int   = 0
        self._5s_went_against:    bool  = False

        # Order / position
        self._entry_submitted: bool         = False
        self._in_position:     bool         = False
        self._exit_submitted:  bool         = False
        self._entry_oid:       Optional[str] = None
        self._exit_oid:        Optional[str] = None
        self._entry_px:        float = 0.0
        self._entry_ts:        int   = 0
        self._sl_px:           float = 0.0   # current stop price (updated when lock arms)
        self._lock_armed:      bool  = False
        self._exit_reason:     str   = ""

        self._obs: Optional[dict] = None
        self.obs_log: list[dict]  = []

        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ── 1s bar handler ────────────────────────────────────────────────────────

    def on_bar(self, bar: Bar) -> None:
        self._agg.on_1s_bar(
            int(bar.ts_init),
            float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), float(bar.volume),
        )

        if not (self._in_position and self._obs is not None):
            return

        h   = float(bar.high)
        l   = float(bar.low)
        ts  = int(bar.ts_init)
        d   = self._obs["direction"]   # W-FLIP safe: snapshot at entry fill
        atr = self._atr_base
        px  = self._entry_px
        obs = self._obs

        if atr <= 0:
            return

        mfe = (h - px) / atr if d == 1 else (px - l) / atr
        mae = (px - l) / atr if d == 1 else (h - px) / atr
        obs["max_mfe_atr"] = max(obs["max_mfe_atr"], mfe)
        obs["max_mae_atr"] = max(obs["max_mae_atr"], mae)

        for ck, key in zip(CHECKPOINTS, CK_KEYS):
            if not obs[f"did_{key}"] and mfe >= ck:
                obs[f"did_{key}"] = True
                obs[f"ts_{key}"]  = ts

        if obs["did_050"] and not obs["after_050_revisit_entry"]:
            if (d == 1 and l <= px) or (d == -1 and h >= px):
                obs["after_050_revisit_entry"] = True

        if self._exit_submitted:
            return

        # ── Lock management (before stop check) ───────────────────────────────
        if not self._lock_armed and mfe >= self._cfg.lock_at_atr:
            self._lock_armed     = True
            obs["lock_armed"]    = True
            obs["lock_armed_ts"] = ts
            obs["mfe_at_lock"]   = mfe
            if d == 1:
                self._sl_px = px + self._cfg.lock_floor_atr * atr
            else:
                self._sl_px = px - self._cfg.lock_floor_atr * atr

        # ── Stop check (initial_stop OR lock_floor) ────────────────────────────
        stop_hit = (d == 1 and l <= self._sl_px) or (d == -1 and h >= self._sl_px)
        if stop_hit:
            reason = "lock_floor" if self._lock_armed else "initial_stop"
            self._submit_exit(reason)

    # ── Aggregator dispatch ────────────────────────────────────────────────────

    def _on_bucket_closed(self, tf: str, bucket: _OpenBucket) -> None:
        if tf == "1m":
            self._on_1m_close(bucket)
        elif tf == "5s":
            self._on_5s_close(bucket)

    # ── 1m close ──────────────────────────────────────────────────────────────

    def _on_1m_close(self, bucket: _OpenBucket) -> None:
        prev = self._prev_regime
        self._1m_eng.update(bucket)
        cur = self._1m_eng.regime

        atr_now = self._1m_eng.atr
        if atr_now and atr_now > 0:
            self._atr_hist.append(atr_now)

        flipped = cur != prev and cur != 0 and prev != 0

        if flipped:
            if self._in_position or self._entry_submitted:
                self._submit_exit("regime_flip")

            self._in_regime = True
            self._rs_ts     = bucket.close_ts
            self._dir       = cur
            cur_atr = atr_now if (atr_now and atr_now > 0) else 1.0
            roll    = sum(self._atr_hist) / len(self._atr_hist) if self._atr_hist else cur_atr
            self._atr_base  = max(cur_atr, 0.5 * roll)
            self._run_ext   = bucket.close
            self._peak_ts   = bucket.close_ts

            self._watching      = False
            self._pb_count      = 0
            self._need_new_peak = False
            self._pb_active     = False
            self._pb_sl         = 0.0
            self._hC_val        = float("nan")
            self._hC_vel        = float("nan")
            self._state_str     = ""
            self._reset_pb()

            self._5s_eng        = _5sRegimeEngine()
            self._5s_regime_cur = 0

        elif cur != 0 and self._in_regime:
            if cur == 1 and bucket.close > self._run_ext:
                self._run_ext = bucket.close; self._peak_ts = bucket.close_ts
            elif cur == -1 and bucket.close < self._run_ext:
                self._run_ext = bucket.close; self._peak_ts = bucket.close_ts

        # Bar-8 qualification gate
        if (cur != 0 and not self._watching
                and not self._in_position and not self._entry_submitted
                and self._1m_eng.bars_in_regime == 9
                and self._rs_ts > 0 and self._1m_eng.atr is not None):
            e9 = self._hc_map.get((self._rs_ts, 9))
            if e9 is not None:
                hc9, state_raw = e9
                if not math.isnan(hc9) and hc9 >= self._cfg.hc_floor:
                    sc = _state_cat(hc9, state_raw)
                    if sc in ("Healthy", "HH-HardStall"):
                        e7  = self._hc_map.get((self._rs_ts, 8))
                        vel = (hc9 - e7[0]) if (e7 and not math.isnan(e7[0])) else float("nan")
                        self._hC_val    = hc9
                        self._hC_vel    = vel
                        self._state_str = sc
                        self._watching  = True

        self._prev_regime = cur

    # ── 5s close: Trigger C detection ─────────────────────────────────────────

    def _on_5s_close(self, bucket: _OpenBucket) -> None:
        if not self._in_regime and not self._in_position:
            return

        ts  = bucket.close_ts
        c   = bucket.close
        o   = bucket.open
        h   = bucket.high
        l   = bucket.low
        d   = self._dir
        atr = self._atr_base

        # Update 5s regime
        self._5s_eng.update(h, l, c)
        prev_5s             = self._5s_regime_cur
        self._5s_regime_cur = self._5s_eng.regime

        # Update 1m running extreme
        if self._in_regime:
            if d == 1 and c > self._run_ext:
                self._run_ext = c; self._peak_ts = ts
                if self._need_new_peak:
                    self._need_new_peak = False; self._reset_pb()
            elif d == -1 and c < self._run_ext:
                self._run_ext = c; self._peak_ts = ts
                if self._need_new_peak:
                    self._need_new_peak = False; self._reset_pb()

        # (Stop is now monitored on 1s bars in on_bar, not here)

        if not self._watching or self._in_position or self._entry_submitted:
            return
        if self._need_new_peak or atr <= 0:
            return

        # Pullback depth from running extreme
        pb_depth = (self._run_ext - c) / atr if d == 1 else (c - self._run_ext) / atr

        if pb_depth > 0:
            if not self._pb_active:
                self._pb_active       = True
                self._pb_sl           = c
                self._pb_start_ts     = ts
                self._pb_worst_close  = c
                self._5s_went_against = False
            else:
                if (d == 1 and c < self._pb_sl) or (d == -1 and c > self._pb_sl):
                    self._pb_sl = c
                if d == 1 and c < self._pb_worst_close:
                    self._pb_worst_close = c
                elif d == -1 and c > self._pb_worst_close:
                    self._pb_worst_close = c

            adverse_5s = (d == 1 and self._5s_regime_cur == -1) or \
                         (d == -1 and self._5s_regime_cur == 1)
            if adverse_5s:
                self._5s_went_against = True
        else:
            if self._pb_active:
                self._reset_pb()

        if not self._pb_active:
            return

        # Trigger C: 5s just realigned + 50% pullback reclaim
        just_realigned = (
            (d == 1 and prev_5s != 1 and self._5s_regime_cur == 1 and self._5s_went_against)
            or (d == -1 and prev_5s != -1 and self._5s_regime_cur == -1 and self._5s_went_against)
        )
        if just_realigned:
            mid = 0.5 * (self._pb_worst_close + self._run_ext)
            trigger_fires = (d == 1 and c >= mid) or (d == -1 and c <= mid)
            if trigger_fires:
                max_depth = (
                    (self._run_ext - self._pb_worst_close) / atr if d == 1
                    else (self._pb_worst_close - self._run_ext) / atr
                )
                passes = (
                    self._passes_bar_filter(bucket, d)
                    and max_depth >= self._cfg.min_pb_depth_atr
                )
                if passes:
                    self._pb_depth_at_trigger = pb_depth
                    self._max_pb_depth        = max_depth
                    self._submit_entry()
                else:
                    self._reset_pb()  # close episode; no second-realignment retry

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _passes_bar_filter(self, bucket: _OpenBucket, d: int) -> bool:
        bf = self._cfg.bar_filter
        if bf == "none":
            return True
        o, h, l, c = bucket.open, bucket.high, bucket.low, bucket.close
        rng  = h - l
        body = abs(c - o)
        if bf == "dir_close":
            return (d == 1 and c > o) or (d == -1 and c < o)
        if bf == "min_body25":
            return rng > 0 and body >= 0.25 * rng
        if bf == "strong_close":
            if rng <= 0:
                return False  # doji — no clear close location
            return (d == 1 and c >= l + 0.60 * rng) or (d == -1 and c <= l + 0.40 * rng)
        if bf == "dir_body25":
            dir_ok  = (d == 1 and c > o) or (d == -1 and c < o)
            body_ok = rng > 0 and body >= 0.25 * rng
            return dir_ok and body_ok
        return True  # unknown filter — pass through

    def _reset_pb(self) -> None:
        self._pb_active          = False
        self._pb_sl              = 0.0
        self._pb_start_ts        = 0
        self._pb_worst_close     = 0.0
        self._5s_went_against    = False

    def _submit_entry(self) -> None:
        if self._entry_submitted or self._in_position:
            return
        side = OrderSide.BUY if self._dir == 1 else OrderSide.SELL
        o = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self._entry_oid       = o.client_order_id.value
        self._entry_submitted = True
        self.submit_order(o)

    def _submit_exit(self, reason: str) -> None:
        if self._exit_submitted:
            return
        if not (self._in_position or self._entry_submitted):
            return
        self._exit_reason    = reason
        self._exit_submitted = True
        side = OrderSide.SELL if self._dir == 1 else OrderSide.BUY
        o = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._exit_oid = o.client_order_id.value
        self.submit_order(o)

    # ── Fill events ───────────────────────────────────────────────────────────

    def on_order_filled(self, event) -> None:
        cid = event.client_order_id.value

        if cid == self._entry_oid:
            self._entry_px        = float(event.last_px)
            self._entry_ts        = int(event.ts_event)
            self._in_position     = True
            self._entry_submitted = False
            self._lock_armed      = False

            atr  = self._atr_base
            d    = self._dir
            px   = self._entry_px

            # Fixed ATR stop (not structural pullback extreme)
            if d == 1:
                self._sl_px = px - self._cfg.initial_stop_atr * atr
            else:
                self._sl_px = px + self._cfg.initial_stop_atr * atr

            e3  = self._1m_eng.ema3_h if d == 1 else self._1m_eng.ema3_l
            e9  = self._1m_eng.ema9_h if d == 1 else self._1m_eng.ema9_l
            ema3_dist = d * (px - e3) / atr if (e3 and atr > 0) else float("nan")
            ema9_dist = d * (px - e9) / atr if (e9 and atr > 0) else float("nan")
            bir       = (self._entry_ts - self._rs_ts) // NS_PER_MIN

            atr_pct = float("nan")
            if self._atr_hist:
                hist    = list(self._atr_hist)
                atr_pct = sum(1 for a in hist if a <= atr) / len(hist)

            self._pb_count += 1

            self._obs = {
                "regime_start_ts":   self._rs_ts,
                "pullback_id":       self._pb_count,
                "direction":         d,
                "entry_ts":          self._entry_ts,
                "entry_px":          px,
                "initial_stop_px":   self._sl_px,
                "atr_base":          atr,
                "hC":                self._hC_val,
                "hC_velocity":       self._hC_vel,
                "state":             self._state_str,
                "bars_into_regime":  bir,
                "regime_age_s":      (self._entry_ts - self._rs_ts) / 1e9,
                "pb_depth_atr":      self._pb_depth_at_trigger,
                "max_pb_depth_atr":  self._max_pb_depth,
                "pb_duration_s":     (self._entry_ts - self._pb_start_ts) / 1e9,
                "peak_px":           self._run_ext,
                "initial_stop_atr":  self._cfg.initial_stop_atr,
                "lock_at_atr":       self._cfg.lock_at_atr,
                "lock_floor_atr":    self._cfg.lock_floor_atr,
                "ema3_dist_atr":     ema3_dist,
                "ema9_dist_atr":     ema9_dist,
                "atr_pct":           atr_pct,
                **{f"did_{k}": False for k in CK_KEYS},
                **{f"ts_{k}":  None  for k in CK_KEYS},
                "after_050_revisit_entry": False,
                "lock_armed":        False,
                "lock_armed_ts":     None,
                "mfe_at_lock":       float("nan"),
                "max_mfe_atr":       0.0,
                "max_mae_atr":       0.0,
                "exit_ts":           None,
                "exit_px":           None,
                "exit_reason":       None,
                "hold_s":            None,
                "pnl":               None,
            }

        elif cid == self._exit_oid:
            exit_px = float(event.last_px)
            exit_ts = int(event.ts_event)
            hold_s  = (exit_ts - self._entry_ts) / 1e9

            if self._obs is not None:
                pnl = (exit_px - self._entry_px) * self._obs["direction"] * MULT - COMM
                self._obs.update({
                    "exit_ts":     exit_ts,
                    "exit_px":     exit_px,
                    "exit_reason": self._exit_reason,
                    "hold_s":      hold_s,
                    "pnl":         pnl,
                })
                self.obs_log.append(self._obs)

            self._in_position    = False
            self._exit_submitted = False
            self._entry_oid      = None
            self._exit_oid       = None
            self._obs            = None
            self._pb_active      = False
            self._pb_sl          = 0.0

            # Require new peak after any stop exit (matches collector behavior);
            # regime_flip exits allow immediate re-entry into the new regime
            if self._exit_reason in ("initial_stop", "lock_floor"):
                self._need_new_peak = True

    def on_order_rejected(self, event) -> None:
        self.log.warning(f"Order rejected: {event}")

    def on_stop(self) -> None:
        self.log.info(f"CLockStrategy: {len(self.obs_log)} observations")

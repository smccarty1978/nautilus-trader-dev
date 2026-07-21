"""Compression VWAP Launchpad — Long-Only

Signal rules (identical to the validated 863-trade scanner):
  1. 1-minute regime flip to +1 (EMA3/EMA9 of highs/lows).
  2. Rolling 30-bar total excursion < 22 pts  (low-excursion / compressed).
  3. RTH only: 09:30–16:00 ET.
  4. Session-anchored VWAP (CME Globex anchor: 17:00 CT reset).
     Vol-weighted typical = (h+l+c)/3, sigma = vol-weighted stdev.
     VWAP cumulative is updated AFTER the 1m-close gate check so the
     value at decision time T is causal (excludes the 1s bar
     [T, T+1s) which only completes at T+1s).
  5. 1m close inside VWAP Band 1 (abs_dist < 1.0 * vwap_std).
  6. Expanding away from VWAP (close > VWAP).

Execution — 2-lot runner:
  • Entry  : Market order, 2 lots, FOK on next 1s open.
  • SL     : Stop-market 2 lots at Entry − 1.0 ATR (−1 tick slippage is
             applied analytically in the PnL calculation, not as a separate
             order, because Nautilus fills stops at the trigger price).
  • T1     : Limit 1 lot at Entry + 1.0 ATR.
             On fill → cancel 2-lot SL, replace with 1-lot SL at BE.
  • T2     : Limit 1 lot at Entry + 2.0 ATR.
             On fill → cancel BE SL (position now flat).
  • Fallback: If position is still open after 2 hours the strategy exits at
             market on the next 1m close (rare guard).
"""
from __future__ import annotations

import math
from collections import deque
from datetime import time as dtime, date, timedelta, timezone, datetime

import pytz

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, TriggerType
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

# ── constants ──────────────────────────────────────────────────────────────
NS_PER_S       = 1_000_000_000
NQ_MULT        = 20.0
COMM_RT        = 5.0          # $5 round-trip commission (2 sides × $2.50)
ATR_PERIOD     = 14
ALPHA_EMA3     = 0.5          # span-3  EMA alpha
ALPHA_EMA9     = 0.2          # span-9  EMA alpha
EXCURSION_CAP  = 22.0         # low-excursion threshold (pts) — default; configurable via config
MAX_HOLD_NS    = 2 * 3600 * NS_PER_S   # 2-hour hard exit guard
_ET            = pytz.timezone("America/New_York")
_CT            = pytz.timezone("America/Chicago")
_RTH_START     = dtime(9, 30)
_RTH_END       = dtime(16, 0)


# ── helpers ─────────────────────────────────────────────────────────────────
def _ema(prev, x, alpha):
    return x if prev is None else alpha * x + (1.0 - alpha) * prev


def _to_et(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / NS_PER_S, tz=timezone.utc).astimezone(_ET)


def _to_session_date(ns: int) -> date:
    ct = datetime.fromtimestamp(ns / NS_PER_S, tz=timezone.utc).astimezone(_CT)
    if ct.hour >= 17:
        return ct.date() + timedelta(days=1)
    return ct.date()


def _tick_round(val: float) -> float:
    """Round to nearest 0.25 (NQ tick)."""
    return round(val * 4) / 4.0


# ── 1-minute incremental state ───────────────────────────────────────────────
class TF1m:
    """Incremental 1-minute OHLCV aggregator + EMA regime + Wilder ATR-14."""

    def __init__(self):
        self._period = 60 * NS_PER_S
        self._bin    = None
        self._o = self._h = self._l = self._c = None
        self._v = 0.0

        self.ema3_h = self.ema9_h = None
        self.ema3_l = self.ema9_l = None
        self.close  = None
        self.atr    = None
        self.regime = 0
        self.regime_flipped = False

        self._prev_c  = None
        self._tr_seed = []

    def update(self, ts, o, h, l, c, v):
        """Feed a 1-second bar. Returns closed 1-minute dict or None."""
        # Subtract 1 nanosecond before flooring to handle close-time semantics (Rule A1)
        b      = ((ts - 1) // self._period) * self._period
        closed = None

        if self._bin is None:
            self._bin = b
        elif b != self._bin:
            closed = dict(ts_event=self._bin,
                          open=self._o, high=self._h,
                          low=self._l,  close=self._c,
                          volume=self._v)
            self._fold(closed)
            self._bin = b
            self._o = self._h = self._l = self._c = None
            self._v = 0.0

        if self._o is None:
            self._o, self._h, self._l, self._c = o, h, l, c
        else:
            self._h = max(self._h, h)
            self._l = min(self._l, l)
            self._c = c
        self._v += v
        return closed

    def _fold(self, bk):
        h, l, c = bk["high"], bk["low"], bk["close"]

        # Wilder ATR-14
        tr = (h - l) if self._prev_c is None else max(
            h - l, abs(h - self._prev_c), abs(l - self._prev_c))
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) == ATR_PERIOD:
                self.atr = sum(self._tr_seed) / ATR_PERIOD
        else:
            self.atr = (self.atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        self._prev_c = c

        # EMAs of high / low
        self.ema3_h = _ema(self.ema3_h, h, ALPHA_EMA3)
        self.ema9_h = _ema(self.ema9_h, h, ALPHA_EMA9)
        self.ema3_l = _ema(self.ema3_l, l, ALPHA_EMA3)
        self.ema9_l = _ema(self.ema9_l, l, ALPHA_EMA9)
        self.close  = c

        prev = self.regime
        if   c > self.ema3_h and c > self.ema9_h: self.regime =  1
        elif c < self.ema3_l and c < self.ema9_l: self.regime = -1
        self.regime_flipped = (self.regime != prev)

    @property
    def warm(self): return self.atr is not None and self.atr > 0


# ── config ───────────────────────────────────────────────────────────────────
class CompressionLaunchpadLongConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s:   str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    position_size: int = 2   # 2-lot runner
    excursion_cap: float = EXCURSION_CAP  # low-excursion threshold (pts)
    excursion_window: int = 30            # rolling 1m bar window for tot_exc


# ── strategy ─────────────────────────────────────────────────────────────────
class CompressionLaunchpadLongStrategy(Strategy):

    def __init__(self, config: CompressionLaunchpadLongConfig):
        super().__init__(config)
        self._cfg     = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # Timeframe state
        self._tf1m        = TF1m()
        self._window_30m  = deque()    # last 30 closed 1m bars

        # Globex Session VWAP accumulators (reset at 17:00 Chicago time)
        # Matches study: typical = (h+l+c)/3, vwap = cum(typical*v)/cum(v)
        # sigma = sqrt(cum(v*typical^2)/cum(v) - vwap^2)
        self._vwap_session_date = None
        self._vwap_cum_pv       = 0.0   # cumulative typical * volume
        self._vwap_cum_p2v      = 0.0   # cumulative typical^2 * volume
        self._vwap_cum_v        = 0.0   # cumulative volume

        # Active trade bookkeeping
        self._pending_entry = None     # client_order_id of open entry order
        self._entry_px      = None
        self._entry_atr     = None
        self._entry_ts      = None     # ns timestamp of entry decision
        self._sl_id         = None
        self._t1_id         = None
        self._t2_id         = None
        self._t1_filled     = False

        # Recorded trades for post-run analysis
        self.all_trades: list[dict] = []

        # Diagnostic counters
        self._diag = {
            "1m_closes": 0,
            "gate_not_warm": 0,
            "gate_not_long_flip": 0,
            "gate_not_rth": 0,
            "gate_window_short": 0,
            "gate_excursion_high": 0,
            "gate_no_vwap": 0,
            "gate_outside_band1": 0,
            "gate_toward_vwap": 0,
            "signals_fired": 0,
        }

    # ── lifecycle ─────────────────────────────────────────────────────────
    def on_start(self):
        self._bar_type = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bar_type)

    # ── bar handler ───────────────────────────────────────────────────────
    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bar_type:
            return

        # Rule A1: Use bar.ts_init (close time) instead of ts_event (open time)
        ts = bar.ts_init
        o, h, l, c, v = (float(bar.open), float(bar.high),
                         float(bar.low),  float(bar.close), float(bar.volume))

        et = _to_et(ts)
        is_rth = _RTH_START <= et.time() < _RTH_END

        # ── 1. Hard 2-hour position guard ─────────────────────────────
        if (self._entry_ts is not None
                and ts - self._entry_ts >= MAX_HOLD_NS
                and not self.portfolio.is_flat(self._inst_id)):
            self._exit_all_market("max_hold")

        # ── 2. Feed 1m timeframe, act on close ────────────────────────
        closed = self._tf1m.update(ts, o, h, l, c, v)
        if closed is not None:
            self._window_30m.append(closed)
            if len(self._window_30m) > self._cfg.excursion_window:
                self._window_30m.popleft()

            if self.portfolio.is_flat(self._inst_id) and self._pending_entry is None:
                self._check_entry(closed, ts, is_rth)

        # ── 3. Update session VWAP accumulators (reset at 17:00 Chicago time) ──
        # Update is performed AFTER signal evaluation to completely resolve contemporaneous leak.
        # Session boundary check is also deferred to avoid clearing VWAP before evaluating the boundary bar.
        sd = _to_session_date(ts)
        if self._vwap_session_date is None or sd != self._vwap_session_date:
            self._vwap_session_date = sd
            self._vwap_cum_pv       = 0.0
            self._vwap_cum_p2v      = 0.0
            self._vwap_cum_v        = 0.0

        if v > 0:
            p = (h + l + c) / 3.0
            self._vwap_cum_pv  += p * v
            self._vwap_cum_p2v += p * p * v
            self._vwap_cum_v   += v

    # ── signal evaluation ─────────────────────────────────────────────────
    def _check_entry(self, closed_1m: dict, ts: int, is_rth: bool):
        tf = self._tf1m
        self._diag["1m_closes"] += 1

        # Gate 1: indicators must be warm
        if not tf.warm:
            self._diag["gate_not_warm"] += 1
            return

        # Gate 2: must be a long flip
        if not tf.regime_flipped or tf.regime != 1:
            self._diag["gate_not_long_flip"] += 1
            return

        # Gate 3: RTH only
        if not is_rth:
            self._diag["gate_not_rth"] += 1
            return

        # Gate 4: need full window of bars
        if len(self._window_30m) < self._cfg.excursion_window:
            self._diag["gate_window_short"] += 1
            return

        # Gate 5: low excursion (< cap pts over rolling window)
        h_max = max(b["high"] for b in self._window_30m)
        l_min = min(b["low"]  for b in self._window_30m)
        anchor = self._window_30m[0]["open"]
        total_exc = (h_max - anchor) + (anchor - l_min)
        if total_exc >= self._cfg.excursion_cap:
            self._diag["gate_excursion_high"] += 1
            return

        # Gate 6: VWAP context (matches scanner cell near-away: |z| < 1.0 and z_dir > 0)
        if self._vwap_cum_v <= 0:
            self._diag["gate_no_vwap"] += 1
            return
        vwap = self._vwap_cum_pv / self._vwap_cum_v
        var = (self._vwap_cum_p2v / self._vwap_cum_v) - (vwap * vwap)
        vwap_std = math.sqrt(max(var, 0.0))

        c1m      = closed_1m["close"]
        dist     = c1m - vwap
        abs_dist = abs(dist)

        if vwap_std <= 0:
            self._diag["gate_outside_band1"] += 1
            return

        # Scanner "Launchpad" = Inside Band 1 (|z| < 1.0)
        if abs_dist >= 1.0 * vwap_std:
            self._diag["gate_outside_band1"] += 1
            return

        # Expanding away from VWAP upward
        if dist <= 0:
            self._diag["gate_toward_vwap"] += 1
            return

        # ── All gates passed — submit entry ───────────────────────────
        self._diag["signals_fired"] += 1
        self._entry_atr = tf.atr
        # Match study signal_time exactly (close time of the closed 1m bar)
        self._entry_ts  = closed_1m["ts_event"] + 60 * NS_PER_S
        self._t1_filled = False

        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(self._cfg.position_size),
            time_in_force=TimeInForce.FOK,
        )
        self._pending_entry = order.client_order_id.value
        self.submit_order(order)
        self.log.info(
            f"ENTRY signal | c={c1m:.2f} vwap={vwap:.2f} "
            f"std={vwap_std:.2f} dist={dist:.2f} atr={tf.atr:.2f}"
        )

    # ── fill handler ──────────────────────────────────────────────────────
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px  = float(event.last_px)

        # ── Entry filled → bracket ────────────────────────────────────
        if cid == self._pending_entry:
            self._pending_entry = None
            self._entry_px      = px
            atr = self._entry_atr

            sl_px = _tick_round(px - atr)
            t1_px = _tick_round(px + atr)
            t2_px = _tick_round(px + 2.0 * atr)

            # Initial stop-loss: 2 lots
            sl_ord = self.order_factory.stop_market(
                instrument_id=self._inst_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(2),
                trigger_price=Price(sl_px, 2),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self._sl_id = sl_ord.client_order_id.value
            self.submit_order(sl_ord)

            # T1: 1 lot at +1 ATR
            t1_ord = self.order_factory.limit(
                instrument_id=self._inst_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                price=Price(t1_px, 2),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self._t1_id = t1_ord.client_order_id.value
            self.submit_order(t1_ord)

            # T2: 1 lot at +2 ATR
            t2_ord = self.order_factory.limit(
                instrument_id=self._inst_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                price=Price(t2_px, 2),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self._t2_id = t2_ord.client_order_id.value
            self.submit_order(t2_ord)

            self.log.info(
                f"ENTRY FILLED {px:.2f} | SL={sl_px:.2f} T1={t1_px:.2f} T2={t2_px:.2f}"
            )

        # ── T1 filled → cancel 2-lot SL, replace with 1-lot BE SL ───
        elif cid == self._t1_id:
            self._t1_id     = None
            self._t1_filled = True
            self.log.info(f"T1 FILLED {px:.2f} — moving SL to BE")

            # Cancel original 2-lot SL
            if self._sl_id:
                sl_order = self.cache.order(ClientOrderId(self._sl_id))
                if sl_order is not None and not sl_order.is_closed:
                    self.cancel_order(sl_order)
                self._sl_id = None

            # Submit 1-lot BE stop
            be_px  = _tick_round(self._entry_px)
            be_ord = self.order_factory.stop_market(
                instrument_id=self._inst_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_int(1),
                trigger_price=Price(be_px, 2),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self._sl_id = be_ord.client_order_id.value
            self.submit_order(be_ord)
            self.log.info(f"BE stop placed at {be_px:.2f}")

        # ── T2 filled → cancel BE SL, trade complete ───────────────
        elif cid == self._t2_id:
            self._t2_id = None
            self.log.info(f"T2 FILLED {px:.2f} — trade complete")
            if self._sl_id:
                sl_order = self.cache.order(ClientOrderId(self._sl_id))
                if sl_order is not None and not sl_order.is_closed:
                    self.cancel_order(sl_order)
                self._sl_id = None
            self._record_trade("T2")

        # ── SL filled → cancel resting targets ────────────────────
        elif cid == self._sl_id:
            self._sl_id = None
            reason = "SL_after_T1" if self._t1_filled else "SL"
            self.log.info(f"{reason} FILLED {px:.2f}")
            for oid_attr in ("_t1_id", "_t2_id"):
                oid = getattr(self, oid_attr)
                if oid:
                    o = self.cache.order(ClientOrderId(oid))
                    if o is not None and not o.is_closed:
                        self.cancel_order(o)
                    setattr(self, oid_attr, None)
            self._record_trade(reason)

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
            self.log.warning(f"Entry rejected: {event}")

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
            self.log.warning(f"Entry cancelled: {event}")

    def on_order_expired(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
            self.log.warning(f"Entry expired: {event}")

    # ── market exit helper (max-hold guard) ───────────────────────────────
    def _exit_all_market(self, reason: str):
        self.log.warning(f"Hard exit triggered: {reason}")
        qty = 1 if self._t1_filled else self._cfg.position_size
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_int(qty),
            time_in_force=TimeInForce.FOK,
            reduce_only=True,
        )
        self.submit_order(order)
        for oid_attr in ("_sl_id", "_t1_id", "_t2_id"):
            oid = getattr(self, oid_attr)
            if oid:
                o = self.cache.order(ClientOrderId(oid))
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
                setattr(self, oid_attr, None)
        self._record_trade(reason)

    # ── trade recording ───────────────────────────────────────────────────
    def _record_trade(self, reason: str):
        """Snapshot current position economics and stash for analysis."""
        self.all_trades.append({
            "entry_ts":  self._entry_ts,
            "entry_px":  self._entry_px,
            "entry_atr": self._entry_atr,
            "exit_reason": reason,
            "t1_filled": self._t1_filled,
        })
        # Reset state
        self._entry_px  = None
        self._entry_atr = None
        self._entry_ts  = None
        self._t1_filled = False

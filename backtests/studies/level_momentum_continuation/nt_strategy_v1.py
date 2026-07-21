"""NT Strategy: Level Momentum Continuation v1.

DESIGN
------
Trigger: Goldilocks bullish-bar breakout (1m close)
  - prev_close < L AND cur_close > L (long, invert short)
  - cur_open <= L (long: bar opened at/below level)
  - L < cur_close < midpoint (Goldilocks zone)
  - cur_close > cur_open (bullish bar; invert short)
  - EMA13 filter: cur_close > EMA13 (long), cur_close < EMA13 (short)
  - Valid groups: A (25pt), B (14-15pt), C (10-11pt)

C1: 1 contract market entry, prior_level SL (stop_market), full PT (limit)
  PT = next_level - 2.5
  SL = prior_level (level one prior in sequence)

C2 (v-recovery add-on):
  - On 1s bars, track running MAE since C1 fill
  - Detect dip below breach (low < L for long)
  - On 1m bars, detect re-cross (close > L) AFTER dip
  - Apply MAE >= 3 filter at re-cross
  - If all conditions met AND C1 still open: add 1 more contract at market
  - C2 fill -> upgrade bracket from qty=1 to qty=2 at same prices
  - Same exits as C1

Skip-while-open: don't enter new C1 if any contract is still open.
RTH only (8:30-15:00 CT entries; trades can hold to EOD 16:00 CT).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytz
from datetime import time as dt_time

from collections import deque

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators import ExponentialMovingAverage

# Filter A: RegimeIndicatorsV2 alignment (3/9 EMAs of H/L/C)
from indicators.regime.indicator_v2 import RegimeIndicatorsV2

CT = pytz.timezone("America/Chicago")
NQ_TICK = 0.25

# Goldilocks levels
LEVELS = (0.0, 11.0, 25.0, 50.0, 75.0, 90.0)
HANDLE = 100.0
TARGET_BUFFER = 2.5

NEXT_UP = {0.0: 11.0, 11.0: 25.0, 25.0: 50.0, 50.0: 75.0, 75.0: 90.0,
           90.0: 100.0}
PRIOR_UP = {0.0: -10.0, 11.0: 0.0, 25.0: 11.0, 50.0: 25.0,
            75.0: 50.0, 90.0: 75.0}
NEXT_DN = {0.0: -10.0, 11.0: 0.0, 25.0: 11.0, 50.0: 25.0,
           75.0: 50.0, 90.0: 75.0}
PRIOR_DN = {0.0: 11.0, 11.0: 25.0, 25.0: 50.0, 50.0: 75.0,
            75.0: 90.0, 90.0: 100.0}

# Group assignments: gap to next level
GROUP_A_GAPS = {25, 50}     # 25-pt gaps (e.g., 25->50, 50->75)
GROUP_B_GAPS = {11, 75}     # 14/15-pt gaps (11->25, 75->90)
GROUP_C_GAPS = {0, 90}      # 10/11-pt gaps (0->11, 90->00)


def absolute_levels_in_range(low: float, high: float):
    h_lo = int(low // HANDLE); h_hi = int(high // HANDLE)
    out = []
    for h in range(h_lo, h_hi + 2):
        base = h * HANDLE
        for off in LEVELS:
            p = base + off
            if low <= p <= high:
                out.append(p)
    return out


def offset_of(level: float) -> float:
    h = int(level // HANDLE)
    return level - h * HANDLE


def assign_group(level: float, direction: int) -> str | None:
    """Assign group based on the BREACH level offset."""
    off = round(offset_of(level), 1)
    if off in (25.0, 50.0):
        return "A_25pt"
    if direction == 1:
        if off in (11.0, 75.0):
            return "B_14_15pt"
        if off in (0.0, 90.0):
            return "C_10_11pt"
    else:
        if off in (25.0, 90.0):
            return "B_14_15pt"
        if off in (11.0, 0.0):
            return "C_10_11pt"
    return None


def detect_goldilocks_trigger(prev_close, cur_open, cur_close):
    """Return (direction, breach_L, target, prior_sl_level, group) if
    a valid bullish-bar Goldilocks trigger fires at this 1m bar.
    Multi-level breach: take latest qualifying.
    """
    if cur_close == prev_close:
        return None
    # Bullish-bar requirement
    if cur_close > cur_open:
        d = 1
    elif cur_close < cur_open:
        d = -1
    else:
        return None
    # Direction must match breach direction
    if d == 1 and cur_close <= prev_close:
        return None
    if d == -1 and cur_close >= prev_close:
        return None

    if d == 1:
        lo, hi = prev_close, cur_close
    else:
        lo, hi = cur_close, prev_close
    levels = absolute_levels_in_range(lo, hi)
    if d == 1:
        breached = sorted([L for L in levels
                            if prev_close < L and cur_close > L],
                           reverse=True)
    else:
        breached = sorted([L for L in levels
                            if prev_close > L and cur_close < L])
    if not breached:
        return None

    for L in breached:
        if d == 1:
            # next level above L
            h = int(L // HANDLE); off = L - h * HANDLE
            Y = h * HANDLE + NEXT_UP.get(off, off + 11.0)
            target = Y - TARGET_BUFFER
            midpoint = (L + target) / 2.0
            if not (L < cur_close < midpoint):
                continue
            if not (cur_open <= L):
                continue
            prior = h * HANDLE + PRIOR_UP.get(off, off - 11.0)
        else:
            h = int(L // HANDLE); off = L - h * HANDLE
            Y = h * HANDLE + NEXT_DN.get(off, off - 11.0)
            target = Y + TARGET_BUFFER
            midpoint = (L + target) / 2.0
            if not (midpoint < cur_close < L):
                continue
            if not (cur_open >= L):
                continue
            prior = h * HANDLE + PRIOR_DN.get(off, off + 11.0)
        grp = assign_group(L, d)
        if grp is None:
            continue
        return {
            "direction": d, "breach_level": L,
            "target": target, "prior_sl": prior,
            "group": grp, "next_level": Y, "midpoint": midpoint,
        }
    return None


# ---------------- Strategy ----------------

class LevelMomentumLiveConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    ema_period: int = 13
    mae_min: float = 3.0
    rth_start_min: int = 510    # 8:30 CT
    rth_end_min: int = 900      # 15:00 CT (last entry minute)
    eod_flat_min: int = 960     # 16:00 CT (force flat)
    enable_groups: tuple = ("A_25pt", "B_14_15pt", "C_10_11pt")
    # NEW: per-group entry-bucket filter (sweet spots from 1s study)
    bucket_filter_enabled: bool = False
    # NEW: disable v-recovery add-on (1-contract clean baseline)
    disable_v_recovery: bool = False
    # NEW: filter A — RegimeIndicatorsV2 alignment (long requires
    # regime=+1, short requires regime=-1)
    regime_filter_v2: bool = False
    regime_short_period: int = 3
    regime_long_period: int = 9
    # NEW: filter D — EMA13 trend (long requires ema_now > ema_lookback,
    # short requires <)
    ema_trend_filter: bool = False
    ema_trend_lookback: int = 5


# Sweet-spot entry buckets per group (progress_to_target fraction)
# Found in entry_location_buckets study (1s sim, 2024+2025 stable both yr)
SWEET_BUCKETS = {
    "A_25pt": (0.10, 0.20),
    "B_14_15pt": (0.10, 0.20),
    "C_10_11pt": (0.20, 0.30),
}


class LevelMomentumLiveStrategy(Strategy):
    def __init__(self, config: LevelMomentumLiveConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._bt_1m = BarType.from_str(config.bar_type_1m)
        self._bt_1s = BarType.from_str(config.bar_type_1s)
        self.ema = ExponentialMovingAverage(config.ema_period)
        self.ema_period = config.ema_period
        self.mae_min = config.mae_min
        self.rth_start_min = config.rth_start_min
        self.rth_end_min = config.rth_end_min
        self.eod_flat_min = config.eod_flat_min
        self.enable_groups = set(config.enable_groups)
        self.bucket_filter_enabled = config.bucket_filter_enabled
        self.disable_v_recovery = config.disable_v_recovery
        # Regime filters (A and D)
        self.regime_filter_v2 = config.regime_filter_v2
        self.ema_trend_filter = config.ema_trend_filter
        self.ema_trend_lookback = config.ema_trend_lookback
        if self.regime_filter_v2:
            self.regime_v2 = RegimeIndicatorsV2(
                short_period=config.regime_short_period,
                long_period=config.regime_long_period,
            )
        else:
            self.regime_v2 = None
        # Deque holds the last (lookback+1) EMA13 values for trend test
        self._ema_history = deque(maxlen=config.ema_trend_lookback + 1)

        # 1m bar tracking
        self._prev_close = None

        # Trade state
        # state: FLAT | C1_PENDING | C1_OPEN | C2_PENDING | C1C2_OPEN |
        #        FLATTENING
        self._state = "FLAT"
        self._direction = 0
        self._breach_level = None
        self._target = None
        self._prior_sl = None
        self._group = None

        # Entry tracking
        self._c1_entry_oid = None
        self._c2_entry_oid = None
        self._c1_fill_px = None
        self._c1_fill_ts = None
        self._c2_fill_px = None
        self._c2_fill_ts = None
        self._c1_filled = False
        self._c2_filled = False

        # Bracket orders
        self._pt_oid = None
        self._sl_oid = None
        self._flat_oid = None

        # V-recovery state
        self._has_dipped = False
        self._max_mae = 0.0

        # Skip-while-open: any pos open
        # (state != FLAT)

        # Trade log
        self._trades = []
        self._cur_trade = None
        self._eod_today = None
        self._eod_flat_triggered = False

    def on_start(self):
        self.subscribe_bars(self._bt_1m)
        self.subscribe_bars(self._bt_1s)
        self.register_indicator_for_bars(self._bt_1m, self.ema)

    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1m:
            self._on_1m_bar(bar)
        elif bar.bar_type == self._bt_1s:
            self._on_1s_bar(bar)

    # ---------------- Helpers ----------------

    def _ts_ct(self, ts_ns):
        return pd.Timestamp(ts_ns, unit="ns", tz="UTC").astimezone(CT)

    def _is_rth(self, ts_ns):
        ct = self._ts_ct(ts_ns)
        if ct.weekday() >= 5: return False
        ct_min = ct.hour * 60 + ct.minute
        return self.rth_start_min <= ct_min < self.rth_end_min

    def _ct_minute(self, ts_ns):
        ct = self._ts_ct(ts_ns)
        return ct.hour * 60 + ct.minute

    def _px(self, price):
        ticks = round(price / NQ_TICK)
        return f"{ticks * NQ_TICK:.2f}"

    # ---------------- 1m bar processing ----------------

    def _on_1m_bar(self, bar: Bar):
        cur_open = float(bar.open)
        cur_close = float(bar.close)

        # Update EMA via indicator (auto)
        if not self.ema.initialized:
            self._prev_close = cur_close
            return

        # Update regime filter A (causal — bar has closed by callback).
        # Done BEFORE the EOD early-return so the regime/deque stay in
        # sync with NT's auto-updated EMA across day boundaries.
        if self.regime_v2 is not None:
            self.regime_v2.update(bar)

        # Update EMA13 history for filter D (push current EMA value)
        self._ema_history.append(self.ema.value)

        # Check EOD flat (during current session)
        ct_min = self._ct_minute(bar.ts_event)
        if (self._state in ("C1_OPEN", "C1C2_OPEN", "C2_PENDING")
                and ct_min >= self.eod_flat_min and not self._eod_flat_triggered):
            self._flatten_at_market("eod")
            self._eod_flat_triggered = True
            self._prev_close = cur_close
            return
        # Reset eod flag at start of new day
        if ct_min < 60 and self._eod_flat_triggered:
            self._eod_flat_triggered = False

        # Detect new trigger ONLY if FLAT and in RTH
        if (self._state == "FLAT" and self._prev_close is not None
                and self._is_rth(bar.ts_event)):
            tr = detect_goldilocks_trigger(
                self._prev_close, cur_open, cur_close)
            if tr is not None and tr["group"] in self.enable_groups:
                # Apply EMA13 filter
                ema_val = self.ema.value
                ema_pass = (
                    (tr["direction"] == 1 and cur_close > ema_val)
                    or (tr["direction"] == -1 and cur_close < ema_val))
                # Filter A: RegimeIndicatorsV2 alignment
                regime_pass = True
                if self.regime_filter_v2 and self.regime_v2 is not None:
                    if tr["direction"] == 1:
                        regime_pass = (self.regime_v2.regime == 1)
                    else:
                        regime_pass = (self.regime_v2.regime == -1)

                # Filter D: EMA13 trend (current vs N bars ago)
                ema_trend_pass = True
                if self.ema_trend_filter:
                    if len(self._ema_history) < self.ema_trend_lookback + 1:
                        ema_trend_pass = False
                    else:
                        ema_now = self._ema_history[-1]
                        ema_then = self._ema_history[0]
                        if tr["direction"] == 1:
                            ema_trend_pass = (ema_now > ema_then)
                        else:
                            ema_trend_pass = (ema_now < ema_then)

                if ema_pass and regime_pass and ema_trend_pass:
                    # NEW: bucket filter (entry-location sweet spot)
                    bucket_pass = True
                    if self.bucket_filter_enabled:
                        L = tr["breach_level"]
                        target = tr["target"]
                        if tr["direction"] == 1:
                            dist_to_pt = target - L
                            progress = (cur_close - L) / dist_to_pt
                        else:
                            dist_to_pt = L - target
                            progress = (L - cur_close) / dist_to_pt
                        sweet = SWEET_BUCKETS.get(tr["group"])
                        if (sweet is None
                                or not (sweet[0] <= progress < sweet[1])):
                            bucket_pass = False
                    if bucket_pass:
                        self._submit_c1_entry(tr)

        # If C1 is open and v-recovery may fire, check this 1m close
        # (skip if v-recovery disabled per config)
        elif (self._state == "C1_OPEN" and self._c1_filled
                and not self._c2_filled and self._has_dipped
                and self._max_mae >= self.mae_min
                and not self.disable_v_recovery):
            # Re-cross check
            if ((self._direction == 1 and cur_close > self._breach_level)
                    or (self._direction == -1 and cur_close < self._breach_level)):
                self._submit_c2_entry()

        self._prev_close = cur_close

    # ---------------- 1s bar processing ----------------

    def _on_1s_bar(self, bar: Bar):
        # Update running MAE for v-recovery (only if C1 filled, not yet C2)
        if not self._c1_filled or self._c2_filled:
            return
        l = float(bar.low); h = float(bar.high)
        if self._direction == 1:
            cur_mae = self._c1_fill_px - l
            if not self._has_dipped and l < self._breach_level:
                self._has_dipped = True
        else:
            cur_mae = h - self._c1_fill_px
            if not self._has_dipped and h > self._breach_level:
                self._has_dipped = True
        if cur_mae > self._max_mae:
            self._max_mae = cur_mae

    # ---------------- Order submission ----------------

    def _submit_c1_entry(self, tr):
        side = OrderSide.BUY if tr["direction"] == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
        )
        self._c1_entry_oid = order.client_order_id
        self._direction = tr["direction"]
        self._breach_level = float(tr["breach_level"])
        self._target = float(tr["target"])
        self._prior_sl = float(tr["prior_sl"])
        self._group = tr["group"]
        self._has_dipped = False
        self._max_mae = 0.0
        self._c1_filled = False
        self._c2_filled = False
        self._state = "C1_PENDING"
        self.submit_order(order)

    def _submit_brackets(self, qty: int):
        """Submit fresh PT (limit) and SL (stop_market) orders for total qty."""
        # Cancel existing first
        for oid in (self._pt_oid, self._sl_oid):
            if oid is not None:
                o = self.cache.order(oid)
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
        self._pt_oid = None
        self._sl_oid = None

        close_side = (OrderSide.SELL if self._direction == 1
                      else OrderSide.BUY)
        pt = self.order_factory.limit(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(qty),
            price=Price.from_str(self._px(self._target)),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        sl = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(qty),
            trigger_price=Price.from_str(self._px(self._prior_sl)),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._pt_oid = pt.client_order_id
        self._sl_oid = sl.client_order_id
        self.submit_order(pt)
        self.submit_order(sl)

    def _submit_c2_entry(self):
        # Cancel existing brackets first
        for oid in (self._pt_oid, self._sl_oid):
            if oid is not None:
                o = self.cache.order(oid)
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
        self._pt_oid = None
        self._sl_oid = None

        side = OrderSide.BUY if self._direction == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.GTC,
        )
        self._c2_entry_oid = order.client_order_id
        self._state = "C2_PENDING"
        self.submit_order(order)

    def _flatten_at_market(self, reason):
        """Cancel brackets, submit market close for any open position."""
        for oid in (self._pt_oid, self._sl_oid):
            if oid is not None:
                o = self.cache.order(oid)
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
        self._pt_oid = None
        self._sl_oid = None
        # Determine current open qty
        net_qty = 0
        if self._c1_filled: net_qty += 1
        if self._c2_filled: net_qty += 1
        if net_qty == 0:
            self._state = "FLAT"
            self._reset_state()
            return
        close_side = (OrderSide.SELL if self._direction == 1
                      else OrderSide.BUY)
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(net_qty),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._flat_oid = order.client_order_id
        self._flat_reason = reason
        self._state = "FLATTENING"
        self.submit_order(order)

    # ---------------- Event handlers ----------------

    def on_order_filled(self, event):
        coid = event.client_order_id
        ts = event.ts_event
        px = float(event.last_px)
        qty_filled = float(event.last_qty)

        if self._c1_entry_oid is not None and coid == self._c1_entry_oid:
            self._c1_filled = True
            self._c1_fill_px = px
            self._c1_fill_ts = ts
            self._c1_entry_oid = None
            self._state = "C1_OPEN"
            self._cur_trade = {
                "c1_fill_ts": ts, "c1_fill_px": px,
                "direction": self._direction,
                "breach_level": self._breach_level,
                "target": self._target,
                "prior_sl": self._prior_sl,
                "group": self._group,
                "c2_fill_ts": None, "c2_fill_px": None,
                "exit_ts": None, "exit_px": None,
                "exit_reason": None,
            }
            self._submit_brackets(qty=1)
        elif self._c2_entry_oid is not None and coid == self._c2_entry_oid:
            self._c2_filled = True
            self._c2_fill_px = px
            self._c2_fill_ts = ts
            self._c2_entry_oid = None
            self._state = "C1C2_OPEN"
            if self._cur_trade:
                self._cur_trade["c2_fill_ts"] = ts
                self._cur_trade["c2_fill_px"] = px
            self._submit_brackets(qty=2)
        elif self._pt_oid is not None and coid == self._pt_oid:
            self._on_exit_filled(event, "win")
        elif self._sl_oid is not None and coid == self._sl_oid:
            self._on_exit_filled(event, "loss")
        elif self._flat_oid is not None and coid == self._flat_oid:
            self._on_exit_filled(event, getattr(self, "_flat_reason", "flat"))

    def _on_exit_filled(self, event, reason):
        # The exit order may fill in pieces; assume single fill closes all
        exit_px = float(event.last_px)
        ts = event.ts_event
        if self._cur_trade:
            self._cur_trade["exit_ts"] = ts
            self._cur_trade["exit_px"] = exit_px
            self._cur_trade["exit_reason"] = reason
            # Compute PnL
            d = self._cur_trade["direction"]
            c1_pnl_pts = (exit_px - self._cur_trade["c1_fill_px"]) * d
            c2_pnl_pts = 0.0
            if self._cur_trade["c2_fill_px"] is not None:
                c2_pnl_pts = (exit_px - self._cur_trade["c2_fill_px"]) * d
            self._cur_trade["c1_pnl_pts"] = c1_pnl_pts
            self._cur_trade["c2_pnl_pts"] = c2_pnl_pts
            self._cur_trade["total_pnl_pts"] = c1_pnl_pts + c2_pnl_pts
            self._cur_trade["c2_added"] = (
                self._cur_trade["c2_fill_px"] is not None)
            self._trades.append(self._cur_trade)
        # Cancel any other still-open exit orders
        for oid in (self._pt_oid, self._sl_oid, self._flat_oid):
            if oid is not None and oid != event.client_order_id:
                o = self.cache.order(oid)
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
        self._reset_state()

    def _reset_state(self):
        self._state = "FLAT"
        self._direction = 0
        self._breach_level = None
        self._target = None
        self._prior_sl = None
        self._group = None
        self._c1_entry_oid = None
        self._c2_entry_oid = None
        self._pt_oid = None
        self._sl_oid = None
        self._flat_oid = None
        self._c1_filled = False
        self._c2_filled = False
        self._c1_fill_px = None
        self._c2_fill_px = None
        self._c1_fill_ts = None
        self._c2_fill_ts = None
        self._has_dipped = False
        self._max_mae = 0.0
        self._cur_trade = None

    def on_order_rejected(self, event):
        coid = event.client_order_id
        if self._c1_entry_oid is not None and coid == self._c1_entry_oid:
            self._reset_state()
        elif self._c2_entry_oid is not None and coid == self._c2_entry_oid:
            # C2 rejected — keep C1 alive, restore brackets
            self._c2_entry_oid = None
            self._submit_brackets(qty=1)
            self._state = "C1_OPEN"
            # Mark v-recovery as "tried" so we don't re-fire
            self._max_mae = -1.0   # disable further attempts

    def on_stop(self):
        # Cancel all live orders
        for oid in (self._c1_entry_oid, self._c2_entry_oid,
                    self._pt_oid, self._sl_oid, self._flat_oid):
            if oid is not None:
                o = self.cache.order(oid)
                if o is not None and not o.is_closed:
                    try: self.cancel_order(o)
                    except Exception: pass

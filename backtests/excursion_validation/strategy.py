from __future__ import annotations
import math
from collections import deque
from datetime import timedelta
import numpy as np

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.core.datetime import dt_to_unix_nanos

from backtests.excursion_validation.config import ExcursionValidationConfig

NS_PER_S = 1_000_000_000
NQ_MULT = 20.0
COMMISSION_PER_SIDE = 2.5

ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2
ATR_PERIOD = 14

def _ema_update(prev, x, alpha):
    if prev is None:
        return x
    return alpha * x + (1.0 - alpha) * prev

def _to_ct(ns: int):
    import pandas as pd
    return pd.Timestamp(ns, unit='ns', tz='UTC').tz_convert('America/Chicago')

class TimeframeState:
    def __init__(self, period_s: int):
        self.period_ns = period_s * NS_PER_S
        self._cur_bin = None
        self._o = self._h = self._l = self._c = None
        self._v = 0.0
        
        self.ema3_h = None
        self.ema9_h = None
        self.ema3_l = None
        self.ema9_l = None
        self.close = None
        self.atr = None
        self.regime = 0
        self.n_closed = 0
        
        self._prev_close = None
        self._tr_seed = []
        self.regime_flipped = False

    def add_1s_bar(self, ts_event_ns, o, h, l, c, v):
        b = (ts_event_ns // self.period_ns) * self.period_ns
        closed = None
        if self._cur_bin is None:
            self._cur_bin = b
        elif b != self._cur_bin:
            closed = {
                "ts_event": self._cur_bin,
                "open": self._o, "high": self._h,
                "low": self._l, "close": self._c,
                "volume": self._v,
            }
            self._fold_closed_bucket(closed)
            self._cur_bin = b
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

    def _fold_closed_bucket(self, bk):
        h, l, c = bk["high"], bk["low"], bk["close"]

        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
            
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) == ATR_PERIOD:
                self.atr = sum(self._tr_seed) / ATR_PERIOD
        else:
            self.atr = (self.atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        self._prev_close = c

        self.ema3_h = _ema_update(self.ema3_h, h, ALPHA_EMA3)
        self.ema9_h = _ema_update(self.ema9_h, h, ALPHA_EMA9)
        self.ema3_l = _ema_update(self.ema3_l, l, ALPHA_EMA3)
        self.ema9_l = _ema_update(self.ema9_l, l, ALPHA_EMA9)
        self.close = c

        prev_regime = self.regime
        if c > self.ema3_h and c > self.ema9_h:
            self.regime = 1
        elif c < self.ema3_l and c < self.ema9_l:
            self.regime = -1
            
        self.regime_flipped = self.regime != prev_regime
        self.n_closed += 1

    @property
    def atr_warm(self) -> bool:
        return self.atr is not None and self.atr > 0


class ExcursionValidationStrategy(Strategy):
    def __init__(self, config: ExcursionValidationConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        
        self._tf1m = TimeframeState(60)
        self._30m_window = deque()
        
        self._open_trade = None
        self._pending_entry_cid = None
        self._pending_exit_cid = None
        
        self.all_trades = []

    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bt_1s)
        self.log.info("ExcursionValidationStrategy started.")

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bt_1s:
            return
            
        ts = bar.ts_event
        o, h, l, c, v = float(bar.open), float(bar.high), float(bar.low), float(bar.close), float(bar.volume)
        
        # Check exits
        trade = self._open_trade
        if trade is not None and trade["entry_fill_price"] is not None and self._pending_exit_cid is None:
            d = trade["direction"]
            px = trade["entry_fill_price"]
            atr = trade["atr_at_signal"]
            
            if d == 1:
                target = px + atr
                stop = px - atr
                hit_target = h >= target
                hit_stop = l <= stop
            else:
                target = px - atr
                stop = px + atr
                hit_target = l <= target
                hit_stop = h >= stop

            reason = None
            if hit_target and hit_stop:
                reason = "stop" # Conservative tie-break
            elif hit_target:
                reason = "target"
            elif hit_stop:
                reason = "stop"

            if reason is not None:
                self._submit_exit(trade, reason, ts)

        closed_1m = self._tf1m.add_1s_bar(ts, o, h, l, c, v)
        if closed_1m is not None:
            self._30m_window.append(closed_1m)
            if len(self._30m_window) > 30:
                self._30m_window.popleft()
                
            self._on_1m_close(closed_1m)

    def _submit_exit(self, trade, reason, ts):
        trade["exit_reason"] = reason
        d = trade["direction"]
        exit_side = OrderSide.SELL if d == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=Quantity.from_int(self._cfg.position_size),
            time_in_force=TimeInForce.FOK,
        )
        self._pending_exit_cid = order.client_order_id.value
        self.submit_order(order)

    def _on_1m_close(self, closed_1m):
        # We only consider entering if flat
        if self._open_trade is not None or self._pending_entry_cid is not None:
            return
            
        if not self._tf1m.regime_flipped:
            return
            
        if self._tf1m.regime == 0:
            return
            
        if not self._tf1m.atr_warm or len(self._30m_window) < 30:
            return
            
        ct = _to_ct(closed_1m["ts_event"])
        minute_ct = ct.hour * 60 + ct.minute
        if not (510 <= minute_ct < 900): # RTH
            return

        direction = self._tf1m.regime
        anchor_open = self._30m_window[0]["open"]
        h_max = max(b["high"] for b in self._30m_window)
        l_min = min(b["low"] for b in self._30m_window)
        
        if direction == 1:
            mfe = h_max - anchor_open
            mae = anchor_open - l_min
        else:
            mfe = anchor_open - l_min
            mae = h_max - anchor_open
            
        total_exc = mfe + mae
        if total_exc < 22:
            exc_bkt = "low"
        elif total_exc < 41.75:
            exc_bkt = "mid"
        else:
            exc_bkt = "high"

        # Submit market entry
        side = OrderSide.BUY if direction == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.position_size),
            time_in_force=TimeInForce.FOK,
        )
        self._pending_entry_cid = order.client_order_id.value
        
        self._open_trade = {
            "entry_ts": closed_1m["ts_event"] + 60_000_000_000, # decision time
            "direction": direction,
            "atr_at_signal": self._tf1m.atr,
            "total_excursion_slow": total_exc,
            "excursion_bkt": exc_bkt,
            "entry_fill_price": None,
            "exit_fill_price": None,
            "exit_reason": None
        }
        self.submit_order(order)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        trade = self._open_trade
        if trade is None:
            return
            
        px = float(event.last_px)
            
        if cid == self._pending_entry_cid:
            self._pending_entry_cid = None
            trade["entry_fill_price"] = px
            
        elif cid == self._pending_exit_cid:
            self._pending_exit_cid = None
            trade["exit_fill_price"] = px
            trade["exit_ts"] = event.ts_event
            self._finalize_trade(trade)

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry_cid:
            self._pending_entry_cid = None
            self._open_trade = None
        elif cid == self._pending_exit_cid:
            self._pending_exit_cid = None
            self._open_trade["exit_reason"] = None

    def _finalize_trade(self, trade):
        entry = trade["entry_fill_price"]
        exit_px = trade["exit_fill_price"]
        d = trade["direction"]
        pnl_pts = (exit_px - entry) * d
        gross = pnl_pts * NQ_MULT
        net = gross - 2.0 * COMMISSION_PER_SIDE
        
        self.all_trades.append({
            "entry_ts": trade["entry_ts"],
            "exit_ts": trade["exit_ts"],
            "direction": d,
            "atr_at_signal": trade["atr_at_signal"],
            "total_excursion_slow": trade["total_excursion_slow"],
            "excursion_bkt": trade["excursion_bkt"],
            "entry_fill_price": entry,
            "exit_fill_price": exit_px,
            "exit_reason": trade["exit_reason"],
            "pnl_pts": pnl_pts,
            "gross_pnl": gross,
            "net_pnl": net,
        })
        self._open_trade = None

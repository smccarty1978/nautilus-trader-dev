"""V_A momentum-confirm strategy + 5m regime alignment gate.

Extends momentum_confirm_v1.nt_strategy.MomentumConfirmStrategy
(mode='1m_momentum') with a single additional gate:

  At confirmation time, the current 5m regime (from a separate
  SimpleRegimeTracker) must match the 1m flip direction. If not
  aligned, the trade is dropped (no pending entry scheduled).

5m bars are aggregated from 1m bars internally (catalog has no 5m).
A 5m bucket completes when the next 1m bar arrives in a new bucket.
The 5m regime is updated only on bucket completion (causal).

Subscribes to: 1m bars, 1s bars.
Hold-to-regime-exit on opposing 1m flip.
"""

from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd
import pytz

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

CT = pytz.timezone("America/Chicago")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


class MomentumConfirm5mConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    rth_only: bool = True
    rth_start_min: int = 510
    rth_end_min: int = 900
    position_size: int = 1
    require_5m_aligned: bool = True
    output_dir: str = ""


class MomentumConfirm5mStrategy(Strategy):

    def __init__(self, config: MomentumConfirm5mConfig):
        super().__init__(config)
        self._cfg = config

        # 1m regime tracker
        self._regime_1m = 0
        self._ema3_h_1m = self._ema9_h_1m = None
        self._ema3_l_1m = self._ema9_l_1m = None

        # 5m regime tracker (separate)
        self._regime_5m = 0
        self._ema3_h_5m = self._ema9_h_5m = None
        self._ema3_l_5m = self._ema9_l_5m = None

        self._alpha3 = 2.0 / (3 + 1)
        self._alpha9 = 2.0 / (9 + 1)

        self._flip_bar = None
        self._pending_entry = None
        self._trade = None
        self._trade_log = []

        # 5m bucket aggregation from 1m bars
        # bucket_start_minute = (minute_of_day // 5) * 5
        self._cur_5m_bucket = None  # {bucket_start_min, h, l, o, c, day_id}

        self._diag = {
            "flips_1m": 0,
            "rth_signals": 0,
            "confirmations_passed_hhll_mom": 0,
            "rejected_5m_misaligned": 0,
            "entries_filled": 0,
            "regime_exits": 0,
            "regime_flip_pre_fill_cancelled": 0,
            "5m_buckets_completed": 0,
            "1m_bars_seen": 0,
        }

    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1m))
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s(bar)
        elif bt == self._cfg.bar_type_1m:
            self._on_1m(bar)

    def _is_rth(self, ts_ns: int) -> bool:
        if not self._cfg.rth_only:
            return True
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _close_5m_bucket(self):
        """Close current 5m bucket and update 5m regime tracker."""
        if self._cur_5m_bucket is None:
            return
        b = self._cur_5m_bucket
        h, l, c = b["h"], b["l"], b["c"]
        if self._ema3_h_5m is None:
            self._ema3_h_5m = h; self._ema9_h_5m = h
            self._ema3_l_5m = l; self._ema9_l_5m = l
        else:
            self._ema3_h_5m = (self._alpha3 * h
                                 + (1 - self._alpha3) * self._ema3_h_5m)
            self._ema9_h_5m = (self._alpha9 * h
                                 + (1 - self._alpha9) * self._ema9_h_5m)
            self._ema3_l_5m = (self._alpha3 * l
                                 + (1 - self._alpha3) * self._ema3_l_5m)
            self._ema9_l_5m = (self._alpha9 * l
                                 + (1 - self._alpha9) * self._ema9_l_5m)
        new_regime = self._regime_5m
        if c > self._ema3_h_5m and c > self._ema9_h_5m:
            new_regime = 1
        elif c < self._ema3_l_5m and c < self._ema9_l_5m:
            new_regime = -1
        if new_regime != 0:
            self._regime_5m = new_regime
        self._diag["5m_buckets_completed"] += 1

    def _aggregate_to_5m(self, bar):
        """Aggregate 1m bar into current 5m bucket. When the bar
        belongs to a new bucket, close the previous one (which
        triggers regime update)."""
        h = float(bar.high); l = float(bar.low)
        o = float(bar.open); c = float(bar.close)
        # Bucket key from ts_event (1m bar OPEN time, UTC ns)
        ts_event_ns = int(bar.ts_event)
        # 5m bucket = floor(ts_event / 5min)
        bucket_id = ts_event_ns // (5 * 60 * int(1e9))
        if (self._cur_5m_bucket is not None
                and bucket_id != self._cur_5m_bucket["bucket_id"]):
            # New bucket arrived → close previous
            self._close_5m_bucket()
            self._cur_5m_bucket = None
        if self._cur_5m_bucket is None:
            self._cur_5m_bucket = {
                "bucket_id": bucket_id,
                "o": o, "h": h, "l": l, "c": c,
            }
        else:
            self._cur_5m_bucket["h"] = max(
                self._cur_5m_bucket["h"], h)
            self._cur_5m_bucket["l"] = min(
                self._cur_5m_bucket["l"], l)
            self._cur_5m_bucket["c"] = c

    def _on_1m(self, bar):
        self._diag["1m_bars_seen"] += 1
        # Aggregate to 5m FIRST. If this 1m bar starts a new bucket,
        # the previous bucket completes here and updates 5m regime
        # BEFORE we evaluate any 1m confirmation/entry logic on this
        # bar. This matches the offline aggregation semantics
        # (5m regime = state of most recently closed 5m bar).
        self._aggregate_to_5m(bar)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        o = float(bar.open)

        if self._ema3_h_1m is None:
            self._ema3_h_1m = h; self._ema9_h_1m = h
            self._ema3_l_1m = l; self._ema9_l_1m = l
        else:
            self._ema3_h_1m = (self._alpha3 * h
                                 + (1 - self._alpha3) * self._ema3_h_1m)
            self._ema9_h_1m = (self._alpha9 * h
                                 + (1 - self._alpha9) * self._ema9_h_1m)
            self._ema3_l_1m = (self._alpha3 * l
                                 + (1 - self._alpha3) * self._ema3_l_1m)
            self._ema9_l_1m = (self._alpha9 * l
                                 + (1 - self._alpha9) * self._ema9_l_1m)

        new_regime = self._regime_1m
        if c > self._ema3_h_1m and c > self._ema9_h_1m:
            new_regime = 1
        elif c < self._ema3_l_1m and c < self._ema9_l_1m:
            new_regime = -1
        flipped = (new_regime != 0 and self._regime_1m != 0
                     and new_regime != self._regime_1m)

        # ---------- bar+1 confirmation check (1m_momentum mode) ----
        if (self._flip_bar is not None
                and bar.ts_event > self._flip_bar["flip_ts_event"]
                and not flipped):
            d = self._flip_bar["direction"]
            if d == 1:
                hhll_ok = h > self._flip_bar["flip_h"]
                mom_ok = c > o
            else:
                hhll_ok = l < self._flip_bar["flip_l"]
                mom_ok = c < o
            if hhll_ok and mom_ok:
                self._diag["confirmations_passed_hhll_mom"] += 1
                # 5m alignment gate
                if (self._cfg.require_5m_aligned
                        and self._regime_5m != d):
                    self._diag["rejected_5m_misaligned"] += 1
                else:
                    fill_ts = bar.ts_init + 30 * int(1e9)
                    self._pending_entry = {
                        "fill_ts": int(fill_ts),
                        "direction": d}
            self._flip_bar = None

        # ---------- Exit on opposing regime flip ----------
        if flipped:
            if (self._trade is not None
                    and new_regime != self._trade["direction"]):
                self._submit_exit()
                self._diag["regime_exits"] += 1
            if (self._pending_entry is not None
                    and new_regime != self._pending_entry["direction"]):
                self._pending_entry = None
                self._diag["regime_flip_pre_fill_cancelled"] += 1

        # ---------- Detect new flip ----------
        if flipped:
            self._diag["flips_1m"] += 1
            if self._is_rth(int(bar.ts_event)):
                self._diag["rth_signals"] += 1
                self._flip_bar = {
                    "flip_ts_event": int(bar.ts_event),
                    "flip_ts_init": int(bar.ts_init),
                    "flip_h": h, "flip_l": l,
                    "direction": int(new_regime),
                }

        if new_regime != 0:
            self._regime_1m = new_regime

    def _on_1s(self, bar):
        ts = int(bar.ts_event)
        if (self._pending_entry is not None and self._trade is None
                and ts >= self._pending_entry["fill_ts"] - int(1e9)):
            self._submit_entry()

    def _submit_entry(self):
        d = self._pending_entry["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK)
        self._trade = {
            "direction": d,
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
        }
        self._pending_entry = None
        self.submit_order(order)

    def _submit_exit(self):
        if self._trade is None:
            return
        if self._trade.get("exit_order_id") is not None:
            return
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True)
        self._trade["exit_order_id"] = order.client_order_id.value
        self.submit_order(order)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        if self._trade is None:
            return
        if cid == self._trade.get("entry_order_id"):
            self._trade["fill_price"] = float(event.last_px)
            self._trade["entry_ts"] = int(event.ts_event)
            self._diag["entries_filled"] += 1
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            self._finalize_trade()

    def _finalize_trade(self):
        t = self._trade
        d = t["direction"]
        ep = t["fill_price"]
        ex = t["exit_price"]
        gross = (ex - ep) * d * NQ_MULT
        cost = COMMISSION + TICK_COST
        net = gross - cost
        t["gross_pnl"] = gross
        t["net_pnl"] = net
        t["hold_s"] = (t["exit_ts"] - t["entry_ts"]) / 1e9
        self._trade_log.append(dict(t))
        self._trade = None

    def on_stop(self):
        super().on_stop()
        self.log.info(f"Diag: {self._diag}")
        if self._cfg.output_dir:
            Path(self._cfg.output_dir).mkdir(parents=True,
                                                exist_ok=True)
            df = pd.DataFrame(self._trade_log)
            df.to_parquet(
                Path(self._cfg.output_dir) / "nt_trades.parquet",
                index=False)

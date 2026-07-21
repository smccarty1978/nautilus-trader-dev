"""NT runtime — momentum-confirmation regime-exit strategy.

Two modes:
  - "1m_momentum": bar+1 makes HH/LL + closes in regime direction
  - "30s_momentum": first 30s after flip makes HH/LL + closes in
                     regime direction

Hold to opposing 1m regime flip. Exit at next 1s bar after detection.
"""

from __future__ import annotations
from collections import deque
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


class MomentumConfirmConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    mode: str = "1m_momentum"  # or "30s_momentum"
    rth_only: bool = True
    rth_start_min: int = 510
    rth_end_min: int = 900
    position_size: int = 1
    output_dir: str = ""


class MomentumConfirmStrategy(Strategy):

    def __init__(self, config: MomentumConfirmConfig):
        super().__init__(config)
        self._cfg = config

        # 1m regime tracker (EMA3/EMA9 of H/L)
        self._regime = 0
        self._ema3_h = self._ema9_h = None
        self._ema3_l = self._ema9_l = None
        self._alpha3 = 2.0 / (3 + 1)
        self._alpha9 = 2.0 / (9 + 1)

        # Pending flip awaiting confirmation
        # {flip_ts_event, flip_ts_init, flip_h, flip_l, direction}
        self._flip_bar = None
        # 30s window accumulator (V_B only): {o, h, l, c}
        self._acc_30s = None

        # Pending entry: {fill_ts, direction}
        self._pending_entry = None

        # Open trade
        self._trade = None

        self._trade_log = []
        self._diag = {
            "flips_detected": 0,
            "rth_signals_observed": 0,
            "confirmations": 0,
            "entries_filled": 0,
            "regime_exits": 0,
            "regime_flip_pre_fill_cancelled": 0,
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

    def _on_1m(self, bar):
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        o = float(bar.open)

        # Update EMAs
        if self._ema3_h is None:
            self._ema3_h = h; self._ema9_h = h
            self._ema3_l = l; self._ema9_l = l
        else:
            self._ema3_h = (self._alpha3 * h
                              + (1 - self._alpha3) * self._ema3_h)
            self._ema9_h = (self._alpha9 * h
                              + (1 - self._alpha9) * self._ema9_h)
            self._ema3_l = (self._alpha3 * l
                              + (1 - self._alpha3) * self._ema3_l)
            self._ema9_l = (self._alpha9 * l
                              + (1 - self._alpha9) * self._ema9_l)

        new_regime = self._regime
        if c > self._ema3_h and c > self._ema9_h:
            new_regime = 1
        elif c < self._ema3_l and c < self._ema9_l:
            new_regime = -1
        flipped = (new_regime != 0 and self._regime != 0
                     and new_regime != self._regime)

        # ---------- V_A bar+1 confirmation check ----------
        # Triggered when this 1m bar IS bar+1 of a recent flip (and
        # not itself a flip).
        if (self._cfg.mode == "1m_momentum"
                and self._flip_bar is not None
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
                # Schedule entry for bar+1 close + 30s
                fill_ts = bar.ts_init + 30 * int(1e9)
                self._pending_entry = {
                    "fill_ts": int(fill_ts),
                    "direction": d}
                self._diag["confirmations"] += 1
            self._flip_bar = None  # done watching either way

        # ---------- Exit on opposing regime flip ----------
        if flipped:
            # If in position and new regime opposes, exit
            if self._trade is not None and new_regime != self._trade[
                "direction"]:
                self._submit_exit()
                self._diag["regime_exits"] += 1
            # Cancel pending entry if regime flipped against it
            if (self._pending_entry is not None
                    and new_regime != self._pending_entry["direction"]):
                self._pending_entry = None
                self._diag["regime_flip_pre_fill_cancelled"] += 1

        # ---------- Detect new flip ----------
        if flipped:
            self._diag["flips_detected"] += 1
            in_rth = self._is_rth(int(bar.ts_event))
            if in_rth:
                self._diag["rth_signals_observed"] += 1
                self._flip_bar = {
                    "flip_ts_event": int(bar.ts_event),
                    "flip_ts_init": int(bar.ts_init),
                    "flip_h": h, "flip_l": l,
                    "direction": int(new_regime),
                }
                self._acc_30s = None  # reset

        if new_regime != 0:
            self._regime = new_regime

    def _on_1s(self, bar):
        ts = int(bar.ts_event)

        # ----- V_B 30s window accumulation + confirmation -----
        if (self._cfg.mode == "30s_momentum"
                and self._flip_bar is not None
                and ts >= self._flip_bar["flip_ts_init"]):
            window_end = (self._flip_bar["flip_ts_init"]
                            + 30 * int(1e9))
            if ts < window_end:
                if self._acc_30s is None:
                    self._acc_30s = {
                        "o": float(bar.open),
                        "h": float(bar.high),
                        "l": float(bar.low),
                        "c": float(bar.close)}
                else:
                    self._acc_30s["h"] = max(
                        self._acc_30s["h"], float(bar.high))
                    self._acc_30s["l"] = min(
                        self._acc_30s["l"], float(bar.low))
                    self._acc_30s["c"] = float(bar.close)
            else:
                # Window ended (this bar is at or past window_end)
                if self._acc_30s is not None:
                    d = self._flip_bar["direction"]
                    if d == 1:
                        hhll_ok = (self._acc_30s["h"]
                                     > self._flip_bar["flip_h"])
                        mom_ok = (self._acc_30s["c"]
                                    > self._acc_30s["o"])
                    else:
                        hhll_ok = (self._acc_30s["l"]
                                     < self._flip_bar["flip_l"])
                        mom_ok = (self._acc_30s["c"]
                                    < self._acc_30s["o"])
                    if hhll_ok and mom_ok:
                        fill_ts = (self._flip_bar["flip_ts_init"]
                                     + 60 * int(1e9))
                        self._pending_entry = {
                            "fill_ts": int(fill_ts),
                            "direction": d}
                        self._diag["confirmations"] += 1
                self._flip_bar = None
                self._acc_30s = None

        # ----- Submit pending entry 1s before fill_ts -----
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
        cost = COMMISSION + TICK_COST  # 1-tick exit slip (regime exit)
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

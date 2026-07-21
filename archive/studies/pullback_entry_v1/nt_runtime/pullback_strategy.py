"""NT runtime-style pullback strategy.

Implements the offline pullback rule end-to-end in NT's event loop:

  - HH/LL-confirmed 1m regime
  - wait for first 1.0 ATR pullback (intra-minute via 1s bars)
  - decision at next 30s-checkpoint anchored at signal_time
  - market entry at decision + 30s
  - bracket: PT 1.0 ATR / SL 0.75 ATR
  - exit on PT, SL, opposing 1m regime flip, or 30-min cap

Internal regime tracker matches `SimpleRegimeTracker` from
hmm_pipeline (EMA3/EMA9 of H/L). ATR uses Wilder smoothing on 1m TR.
"""

from __future__ import annotations
from collections import deque
from pathlib import Path
import sys

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

import pytz

CT = pytz.timezone("America/Chicago")


class PullbackStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    pullback_threshold_atr: float = 1.0
    pt_atr_mult: float = 1.0
    sl_atr_mult: float = 0.75
    fill_delay_ns: int = 30_000_000_000
    decision_anchor_s: int = 30
    rth_only: bool = True
    rth_start_min: int = 510   # 08:30 CT
    rth_end_min: int = 900     # 15:00 CT
    max_hold_s: int = 1800
    position_size: int = 1
    atr_period: int = 14
    output_dir: str = ""


class PullbackStrategy(Strategy):
    """Live-style runtime: pullback rule in NT event loop."""

    def __init__(self, config: PullbackStrategyConfig):
        super().__init__(config)
        self._cfg = config

        # ------ Regime tracker state (1m) -----
        self._regime = 0
        self._ema3_h = self._ema9_h = None
        self._ema3_l = self._ema9_l = None
        self._alpha3 = 2.0 / (3 + 1)
        self._alpha9 = 2.0 / (9 + 1)

        # ------ ATR state (1m, Wilder) -----
        self._tr_buf: deque = deque()  # for warmup
        self._atr = float("nan")
        self._prev_close = None

        # Last-seen flip bar for HH/LL confirmation tracking
        # _flip_bar = {"ts_event", "h", "l", "direction"}
        self._flip_bar = None

        # Once HH/LL confirmed, populate signal state
        # signal_time, signal_price, signal_atr, signal_direction
        self._signal_time = None
        self._signal_price = None
        self._signal_atr = None
        self._signal_direction = 0

        # Pullback tracking (running peak, threshold cross)
        self._running_peak = None
        self._pullback_armed = False  # entry already scheduled?

        # Pending entry: {fill_ts, direction, atr, signal_time}
        self._pending_entry = None

        # Single open trade
        self._trade = None  # {direction, entry_price, atr,
                            #  pt_id, sl_id, entry_id, ...}

        # Trade log
        self._trade_log = []
        self._diag = {
            "flips_detected": 0,
            "hhll_confirmations": 0,
            "rth_signals": 0,
            "pullbacks_armed": 0,
            "entries_queued": 0,
            "entries_filled": 0,
            "pt_exits": 0,
            "sl_exits": 0,
            "regime_exits": 0,
            "timeout_exits": 0,
        }

    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1m))
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ------ Bar dispatch -----
    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s_bar(bar)
        elif bt == self._cfg.bar_type_1m:
            self._on_1m_bar(bar)

    # ------ 1m bar: regime + ATR + HH/LL confirmation -----
    def _on_1m_bar(self, bar):
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)

        # ATR Wilder
        if self._prev_close is not None:
            tr = max(h - l, abs(h - self._prev_close),
                     abs(l - self._prev_close))
        else:
            tr = h - l
        self._tr_buf.append(tr)
        if len(self._tr_buf) >= self._cfg.atr_period:
            if len(self._tr_buf) == self._cfg.atr_period:
                self._atr = sum(self._tr_buf) / self._cfg.atr_period
            else:
                self._atr = ((self._atr * (self._cfg.atr_period - 1)
                               + tr) / self._cfg.atr_period)
        self._prev_close = c

        # Update EMAs
        if self._ema3_h is None:
            self._ema3_h = h
            self._ema9_h = h
            self._ema3_l = l
            self._ema9_l = l
        else:
            self._ema3_h = (self._alpha3 * h
                              + (1 - self._alpha3) * self._ema3_h)
            self._ema9_h = (self._alpha9 * h
                              + (1 - self._alpha9) * self._ema9_h)
            self._ema3_l = (self._alpha3 * l
                              + (1 - self._alpha3) * self._ema3_l)
            self._ema9_l = (self._alpha9 * l
                              + (1 - self._alpha9) * self._ema9_l)

        # Compute new regime
        new_regime = self._regime
        if c > self._ema3_h and c > self._ema9_h:
            new_regime = 1
        elif c < self._ema3_l and c < self._ema9_l:
            new_regime = -1

        flipped = (new_regime != 0 and self._regime != 0
                     and new_regime != self._regime)

        # ----- Detect bar+1 BEFORE applying flip (this bar may be bar+1) -----
        if (self._flip_bar is not None
                and bar.ts_event > self._flip_bar["ts_event"]
                and not self._pullback_armed
                and self._signal_time is None):
            # This is the next 1m bar after the flip = bar+1
            d = self._flip_bar["direction"]
            confirmed = False
            if d == 1 and h > self._flip_bar["h"]:
                confirmed = True
            elif d == -1 and l < self._flip_bar["l"]:
                confirmed = True

            if confirmed:
                # RTH check on the FLIP bar (when signal originated)
                if self._is_rth(self._flip_bar["ts_event"]):
                    self._signal_time = bar.ts_init
                    self._signal_price = c
                    self._signal_atr = self._atr
                    self._signal_direction = d
                    self._running_peak = None
                    self._diag["hhll_confirmations"] += 1
                    self._diag["rth_signals"] += 1
                else:
                    # Non-RTH — clear flip bar, no entry
                    self._flip_bar = None
            else:
                # Not confirmed; this regime is dead
                self._flip_bar = None

        # ----- Handle regime flip (after HH/LL check above) -----
        if flipped:
            self._diag["flips_detected"] += 1
            # Close open position via regime exit
            if self._trade is not None:
                self._exit_position("regime", reason="regime_flip")
            # Cancel any pending entry
            if self._pending_entry is not None:
                self._pending_entry = None
            # Reset signal state
            self._signal_time = None
            self._signal_price = None
            self._signal_atr = None
            self._signal_direction = 0
            self._running_peak = None
            self._pullback_armed = False

            # Set new flip bar — wait for next bar to check HH/LL
            self._flip_bar = {
                "ts_event": int(bar.ts_event),
                "h": h, "l": l,
                "direction": int(new_regime),
            }

        # Sticky regime update
        if new_regime != 0:
            self._regime = new_regime

    # ------ 1s bar: pullback + entry/exit management -----
    def _on_1s_bar(self, bar):
        ts = int(bar.ts_event)
        h = float(bar.high)
        l = float(bar.low)
        op = float(bar.open)
        cl = float(bar.close)

        # ----- Open position: check PT/SL intra-bar -----
        # Skip if entry order not yet filled (pt_level set in
        # on_order_filled).
        if (self._trade is not None
                and self._trade.get("pt_level") is not None
                and self._trade.get("exit_order_id") is None):
            d = self._trade["direction"]
            pt = self._trade["pt_level"]
            sl = self._trade["sl_level"]
            held_s = (ts - self._trade["entry_ts"]) / 1e9
            if d == 1:
                if h >= pt:
                    self._exit_position("pt", price=pt)
                    return
                if l <= sl:
                    self._exit_position("sl", price=sl)
                    return
            else:
                if l <= pt:
                    self._exit_position("pt", price=pt)
                    return
                if h >= sl:
                    self._exit_position("sl", price=sl)
                    return
            if held_s >= self._cfg.max_hold_s:
                self._exit_position("timeout", price=cl)
                return

        # ----- Pending entry: submit ONE BAR EARLY so NT fills at
        # target fill_ts (next bar open). Matches collector's
        # "fill_price = bar.open at fill_ts" convention.
        if self._pending_entry is not None:
            if ts >= self._pending_entry["fill_ts"] - 1_000_000_000:
                self._submit_entry(ts)
                return

        # ----- Watching pullback (signal active, no pending/open trade) -----
        if (self._signal_time is None or self._pullback_armed
                or self._pending_entry is not None
                or self._trade is not None):
            return
        if ts < self._signal_time:
            return

        d = self._signal_direction
        atr = self._signal_atr
        if not atr or atr <= 0:
            return

        # Update running peak
        if d == 1:
            if self._running_peak is None or h > self._running_peak:
                self._running_peak = h
            pullback_depth = (self._running_peak - l) / atr
        else:
            if self._running_peak is None or l < self._running_peak:
                self._running_peak = l
            pullback_depth = (h - self._running_peak) / atr

        if pullback_depth < self._cfg.pullback_threshold_atr:
            return

        # Pullback hit — schedule entry at next 30s checkpoint
        elapsed = (ts - self._signal_time) // int(1e9)
        anchor = self._cfg.decision_anchor_s
        decision_offset_s = ((elapsed + anchor - 1) // anchor) * anchor
        if decision_offset_s == 0:
            decision_offset_s = anchor
        decision_ts = self._signal_time + decision_offset_s * int(1e9)
        fill_ts = decision_ts + self._cfg.fill_delay_ns

        self._pending_entry = {
            "decision_ts": int(decision_ts),
            "fill_ts": int(fill_ts),
            "direction": d,
            "atr": atr,
            "signal_time": int(self._signal_time),
            "signal_price": self._signal_price,
            "pullback_depth_at_arm": float(pullback_depth),
            "running_peak_at_arm": float(self._running_peak),
            "armed_ts": ts,
        }
        self._pullback_armed = True
        self._diag["pullbacks_armed"] += 1
        self._diag["entries_queued"] += 1

    # ------ Submit market entry one bar before target fill_ts -----
    def _submit_entry(self, submit_ts: int):
        pe = self._pending_entry
        d = pe["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
        )
        # PT/SL levels computed in on_order_filled from ACTUAL fill
        atr = pe["atr"]
        self._trade = {
            "direction": d,
            "atr": atr,
            "actual_fill_price": None,
            "actual_fill_ts": None,
            "submit_ts": submit_ts,
            "target_fill_ts": pe["fill_ts"],
            "pt_level": None,
            "sl_level": None,
            "decision_ts": pe["decision_ts"],
            "signal_time": pe["signal_time"],
            "pullback_depth_at_arm": pe["pullback_depth_at_arm"],
            "exit_reason": None,
            "expected_exit_price": None,
            "actual_exit_price": None,
            "exit_ts": None,
            "entry_ts": None,
            "entry_order_id": order.client_order_id.value,
            "exit_order_id": None,
        }
        self._pending_entry = None
        self.submit_order(order)

    # ------ Exit position -----
    def _exit_position(self, exit_kind: str, price: float = None,
                          reason: str = None):
        if self._trade is None:
            return
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True,
        )
        self._trade["exit_reason"] = exit_kind
        self._trade["exit_order_id"] = order.client_order_id.value
        self._trade["expected_exit_price"] = price
        # Diag
        if exit_kind == "pt":
            self._diag["pt_exits"] += 1
        elif exit_kind == "sl":
            self._diag["sl_exits"] += 1
        elif exit_kind == "regime":
            self._diag["regime_exits"] += 1
        elif exit_kind == "timeout":
            self._diag["timeout_exits"] += 1
        self.submit_order(order)

    # ------ Order fill dispatch -----
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        if self._trade is None:
            return
        if cid == self._trade.get("entry_order_id"):
            actual_fill = float(event.last_px)
            self._trade["actual_fill_price"] = actual_fill
            self._trade["actual_fill_ts"] = int(event.ts_event)
            self._trade["entry_ts"] = int(event.ts_event)
            # Compute brackets from ACTUAL fill (matches collector
            # which uses bar.open at fill_ts as the base)
            d = self._trade["direction"]
            atr = self._trade["atr"]
            self._trade["pt_level"] = (
                actual_fill + d * self._cfg.pt_atr_mult * atr)
            self._trade["sl_level"] = (
                actual_fill - d * self._cfg.sl_atr_mult * atr)
            self._diag["entries_filled"] += 1
        elif cid == self._trade.get("exit_order_id"):
            self._trade["actual_exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            self._finalize_trade()

    def _finalize_trade(self):
        t = self._trade
        d = t["direction"]
        ep = t["actual_fill_price"]
        ex_actual = t["actual_exit_price"]
        ex_expected = t["expected_exit_price"]
        # Realized PnL uses ACTUAL NT fill prices (real venue match)
        gross_actual = (ex_actual - ep) * d * 20.0
        # Reference PnL uses EXPECTED exit prices (bracket level
        # or close at regime/timeout) — for collector comparison
        gross_ref = (ex_expected - ep) * d * 20.0 if ex_expected else None
        # Cost model: $5 comm + 1-tick exit slip ($5); SL = 2-tick ($10)
        cost = 5.0 + (10.0 if t["exit_reason"] == "sl" else 5.0)
        t["gross_pnl_actual"] = gross_actual
        t["net_pnl_actual"] = gross_actual - cost
        t["gross_pnl_ref"] = gross_ref
        t["net_pnl_ref"] = (gross_ref - cost) if gross_ref is not None else None
        t["exit_slippage_dollars"] = (
            (ex_actual - ex_expected) * d * 20.0
            if ex_expected is not None else 0.0)
        t["fill_slippage_dollars"] = 0.0  # NT fills at target bar open
        self._trade_log.append(dict(t))
        self._trade = None

    def on_stop(self):
        super().on_stop()
        self.log.info(f"Diag: {self._diag}")
        if self._cfg.output_dir:
            Path(self._cfg.output_dir).mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame(self._trade_log)
            df.to_parquet(
                Path(self._cfg.output_dir) / "nt_trades.parquet",
                index=False)
            self.log.info(f"Wrote {len(df)} trades to "
                           f"{self._cfg.output_dir}")

    # ------ helpers -----
    def _is_rth(self, ts_ns: int) -> bool:
        if not self._cfg.rth_only:
            return True
        ct_dt = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct_dt.hour * 60 + ct_dt.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

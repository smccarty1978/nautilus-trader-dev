"""Schedule-driven bracket strategy for v2 good-entry NT backtest.

The strategy is deliberately "dumb" — it does NOT recompute features or
run the ML model at runtime. It replays a pre-built trade schedule
that was generated offline by filtering the Phase 3 Huber model's
top-10% RTH-Short × 180-300s cell.

Execution model:
  - Entry: market order at the scheduled entry_ts_ns (fills at next
    1s bar under `bar_execution=True`)
  - Bracket: 1 ATR PT (limit) + 1 ATR SL (stop) placed immediately
    after entry fills
  - Regime-flip cancel: at the scheduled regime_exit_ts_ns, cancel
    the outstanding bracket and close the position at market
"""

from __future__ import annotations
from pathlib import Path

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy


class BracketScheduleConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    schedule_path: str = ""  # required per-run
    pt_atr_mult: float = 1.0
    sl_atr_mult: float = 1.0
    position_size: int = 1
    # Skip new entries if any existing trade is still open.
    # Matches realistic single-contract execution discipline and
    # prevents NETTING OMS from stacking positions when scheduled
    # trades overlap.
    single_position: bool = True


class BracketScheduleStrategy(Strategy):
    """Replays a pre-built trade schedule with 1 ATR PT/SL bracket.

    State: each open trade is tracked by a dict keyed on entry's
    client_order_id (str). The dict also maps the bracket order IDs
    back to the trade so fills can be dispatched.
    """

    def __init__(self, config: BracketScheduleConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        sched = pd.read_parquet(config.schedule_path)
        sched = sched.sort_values("entry_ts_ns").reset_index(drop=True)
        self._schedule = sched
        self._next_idx = 0

        # Map of active trades keyed by entry_client_order_id (str).
        # On entry fill, we add pt_id/sl_id keys.
        self._trades: dict[str, dict] = {}
        # Order-ID → entry-ID reverse lookup (for dispatching bracket
        # fills back to the trade)
        self._order_to_trade: dict[str, str] = {}
        # Exit timestamp → entry-ID (so we can look up which trade to
        # close on regime-flip)
        self._exit_ts_to_entry: dict[int, str] = {}

        self._diag = {
            "entries_submitted": 0,
            "entries_filled": 0,
            "brackets_placed": 0,
            "pt_hits": 0,
            "sl_hits": 0,
            "regime_exits": 0,
            "orphan_entries": 0,
            "skipped_single_position": 0,
        }
        # Count of currently-open trades (filled entry, no exit yet)
        self._open_count = 0

    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bt_1s)
        n = len(self._schedule)
        if n:
            self.log.info(
                f"Schedule loaded: {n} entries, "
                f"{pd.Timestamp(int(self._schedule['entry_ts_ns'].iloc[0]), unit='ns')} "
                f"to {pd.Timestamp(int(self._schedule['entry_ts_ns'].iloc[-1]), unit='ns')}")

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bt_1s:
            return
        ts = bar.ts_event

        # Fire scheduled entries whose entry_ts_ns has been reached
        while (self._next_idx < len(self._schedule)
                and int(self._schedule["entry_ts_ns"].iloc[
                    self._next_idx]) <= ts):
            row = self._schedule.iloc[self._next_idx]
            self._next_idx += 1
            if int(row["entry_ts_ns"]) < ts:
                self._diag["orphan_entries"] += 1
                continue
            self._submit_entry(row)

        # Fire scheduled regime-flip exits
        entry_id = self._exit_ts_to_entry.get(ts)
        if entry_id is not None:
            self._regime_exit_close(entry_id)

    def _submit_entry(self, row: pd.Series):
        if self._cfg.single_position and self._open_count > 0:
            self._diag["skipped_single_position"] += 1
            return
        direction = int(row["direction"])
        side = OrderSide.BUY if direction == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)

        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
        )
        cid = order.client_order_id.value

        trade = {
            "direction": direction,
            "atr_at_signal": float(row["atr_at_signal"]),
            "expected_fill_price": float(row["expected_fill_price"]),
            "regime_exit_price": float(row["regime_exit_price"]),
            "entry_ts_ns": int(row["entry_ts_ns"]),
            "regime_exit_ts_ns": int(row["regime_exit_ts_ns"]),
            "event_id": int(row["event_id"]),
            "checkpoint_s": int(row["checkpoint_s"]),
            "score": float(row["score"]),
            "entry_fill_price": None,
            "pt_id": None,
            "sl_id": None,
            "exit_reason": None,
        }
        self._trades[cid] = trade
        self._order_to_trade[cid] = cid
        self._exit_ts_to_entry[trade["regime_exit_ts_ns"]] = cid
        self.submit_order(order)
        self._diag["entries_submitted"] += 1

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        entry_id = self._order_to_trade.get(cid)
        if entry_id is None:
            return
        trade = self._trades.get(entry_id)
        if trade is None:
            return

        if cid == entry_id:
            # Entry just filled — place bracket
            trade["entry_fill_price"] = float(event.last_px)
            self._diag["entries_filled"] += 1
            self._open_count += 1
            self._place_bracket(entry_id, trade)
        elif cid == trade["pt_id"]:
            trade["exit_reason"] = "pt"
            self._diag["pt_hits"] += 1
            self._open_count = max(0, self._open_count - 1)
            self._on_trade_closed(entry_id)
        elif cid == trade["sl_id"]:
            trade["exit_reason"] = "sl"
            self._diag["sl_hits"] += 1
            self._open_count = max(0, self._open_count - 1)
            self._on_trade_closed(entry_id)

    def _place_bracket(self, entry_id: str, trade: dict):
        inst = self.cache.instrument(self._inst_id)
        if inst is None:
            self.log.error("Instrument missing, cannot place bracket")
            return
        direction = trade["direction"]
        atr = trade["atr_at_signal"]
        ep = trade["entry_fill_price"]

        pt_raw = ep + direction * self._cfg.pt_atr_mult * atr
        sl_raw = ep - direction * self._cfg.sl_atr_mult * atr
        tick = float(inst.price_increment)
        pt_snap = round(pt_raw / tick) * tick
        sl_snap = round(sl_raw / tick) * tick

        exit_side = OrderSide.SELL if direction == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)

        pt = self.order_factory.limit(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=qty,
            price=Price(pt_snap, inst.price_precision),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        sl = self.order_factory.stop_market(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=qty,
            trigger_price=Price(sl_snap, inst.price_precision),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        trade["pt_id"] = pt.client_order_id.value
        trade["sl_id"] = sl.client_order_id.value
        self._order_to_trade[trade["pt_id"]] = entry_id
        self._order_to_trade[trade["sl_id"]] = entry_id

        self.submit_order(pt)
        self.submit_order(sl)
        self._diag["brackets_placed"] += 1

    def _regime_exit_close(self, entry_id: str):
        trade = self._trades.get(entry_id)
        if trade is None:
            return
        if trade.get("exit_reason") is not None:
            # Already closed by PT/SL
            return
        if trade["entry_fill_price"] is None:
            # Never filled — nothing to close
            return
        # Cancel pending bracket + market-close the position
        self.cancel_all_orders(self._inst_id)
        self.close_all_positions(self._inst_id)
        trade["exit_reason"] = "regime_exit"
        self._diag["regime_exits"] += 1
        self._open_count = max(0, self._open_count - 1)
        self._on_trade_closed(entry_id)

    def _on_trade_closed(self, entry_id: str):
        trade = self._trades.get(entry_id)
        if trade is None:
            return
        # Cancel any leftover orders
        self.cancel_all_orders(self._inst_id)
        # Keep trade record in _trades for post-run analysis

    def on_order_rejected(self, event):
        self.log.warning(f"Order rejected: {event.reason if hasattr(event, 'reason') else event}")

    def on_stop(self):
        self.log.info(f"Diag: {self._diag}")
        # Expose trades list on the instance for post-run extraction
        self.all_trades = list(self._trades.values())

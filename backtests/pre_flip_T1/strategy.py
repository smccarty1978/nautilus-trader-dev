"""Schedule-driven NT strategy for pre-flip T-1 backtest.

Reads a pre-built schedule (entry_ts_ns, exit_ts_ns, direction) and
executes market-in / market-out trades as the BacktestEngine streams
1s bars chronologically.

Execution model:
  - On each 1s bar arrival (on_bar):
    - Submit market-entry orders for any scheduled entries whose
      entry_ts_ns <= bar.ts_event (fills at this bar's OPEN under
      bar_execution=True)
    - Submit market-exit orders for any open trades whose
      exit_ts_ns <= bar.ts_event
  - Each trade is tracked by entry's client_order_id.
  - Optional: single_position discipline (skip new entries while
    another trade is still open). Defaults True for realistic
    single-contract execution.

No PT/SL brackets, no regime-flip detection (the schedule encodes the
exit timing). Strategy is "dumb" — just plays the schedule under real
bar-driven matching.
"""
from __future__ import annotations
from pathlib import Path

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class PreFlipScheduleConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    schedule_path: str = ""    # required per-run
    position_size: int = 1
    single_position: bool = True


class PreFlipScheduleStrategy(Strategy):
    """Replays a pre-built market-in / market-out schedule."""

    def __init__(self, config: PreFlipScheduleConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        sched = pd.read_parquet(config.schedule_path)
        sched = sched.sort_values("entry_ts_ns").reset_index(drop=True)
        self._schedule = sched
        self._next_idx = 0
        # Active trades: keyed by entry client_order_id
        self._trades: dict[str, dict] = {}
        # exit_ts → entry_id for fast exit scheduling
        self._exit_ts_to_entry: dict[int, str] = {}
        # exit_order_id → entry_id (so on_order_filled can dispatch)
        self._order_to_trade: dict[str, str] = {}
        # Trades whose exit_ts has passed but they're still open
        # (= got filled, awaiting exit submission)
        self._pending_exits: list[str] = []

        self._diag = {
            "entries_submitted": 0,
            "entries_filled": 0,
            "exits_submitted": 0,
            "exits_filled": 0,
            "orphan_entries": 0,
            "skipped_single_position": 0,
            "skipped_no_fill_before_exit": 0,
        }
        self._open_count = 0

    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bt_1s)
        n = len(self._schedule)
        if n:
            self.log.info(
                f"Schedule loaded: {n} trades "
                f"({pd.Timestamp(int(self._schedule['entry_ts_ns'].iloc[0]), unit='ns')} "
                f".. {pd.Timestamp(int(self._schedule['entry_ts_ns'].iloc[-1]), unit='ns')})")

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bt_1s:
            return
        ts = bar.ts_event

        # 1. Fire scheduled exits for trades whose exit_ts <= bar.ts_event
        #    (and which have been filled — i.e., are actually open)
        for entry_id in list(self._trades.keys()):
            trade = self._trades[entry_id]
            if trade.get("exit_submitted") or trade.get("exit_filled"):
                continue
            if trade.get("entry_fill_price") is None:
                # Entry not filled yet; can't exit
                if int(trade["exit_ts_ns"]) <= ts:
                    # Exit time has passed but never filled — orphan exit
                    self._diag["skipped_no_fill_before_exit"] += 1
                    trade["exit_submitted"] = True
                    trade["exit_filled"] = False
                continue
            if int(trade["exit_ts_ns"]) <= ts:
                self._submit_exit(entry_id, trade)

        # 2. Fire scheduled entries
        while (self._next_idx < len(self._schedule)
                and int(self._schedule["entry_ts_ns"].iloc[
                    self._next_idx]) <= ts):
            row = self._schedule.iloc[self._next_idx]
            self._next_idx += 1
            if int(row["entry_ts_ns"]) < ts:
                self._diag["orphan_entries"] += 1
                continue
            self._submit_entry(row)

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
            "atr_at_signal": float(row["atr_at_signal"])
                if not pd.isna(row["atr_at_signal"]) else 0.0,
            "p_score": float(row.get("p_score", 0.0)),
            "label": int(row.get("label", 0)),
            "is_va_confirm": bool(row.get("is_va_confirm", False)),
            "entry_ts_ns": int(row["entry_ts_ns"]),
            "exit_ts_ns": int(row["exit_ts_ns"]),
            "entry_fill_price": None,
            "exit_fill_price": None,
            "exit_order_id": None,
            "exit_submitted": False,
            "exit_filled": False,
        }
        self._trades[cid] = trade
        self._order_to_trade[cid] = cid
        self.submit_order(order)
        self._diag["entries_submitted"] += 1

    def _submit_exit(self, entry_id: str, trade: dict):
        direction = trade["direction"]
        exit_side = OrderSide.SELL if direction == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True,
        )
        eid = order.client_order_id.value
        trade["exit_order_id"] = eid
        trade["exit_submitted"] = True
        self._order_to_trade[eid] = entry_id
        self.submit_order(order)
        self._diag["exits_submitted"] += 1

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        entry_id = self._order_to_trade.get(cid)
        if entry_id is None:
            return
        trade = self._trades.get(entry_id)
        if trade is None:
            return
        if cid == entry_id:
            trade["entry_fill_price"] = float(event.last_px)
            self._diag["entries_filled"] += 1
            self._open_count += 1
        elif cid == trade.get("exit_order_id"):
            trade["exit_fill_price"] = float(event.last_px)
            trade["exit_filled"] = True
            self._diag["exits_filled"] += 1
            self._open_count = max(0, self._open_count - 1)

    def on_order_rejected(self, event):
        reason = getattr(event, "reason", str(event))
        self.log.warning(f"Order rejected: {reason}")

    def on_stop(self):
        self.log.info(f"Diag: {self._diag}")
        # Expose trades for post-run extraction
        self.all_trades = list(self._trades.values())

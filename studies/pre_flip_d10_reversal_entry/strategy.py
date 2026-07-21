from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from studies._shared_exit_mgmt.base_strategy import (
    ExitManagementBaseConfig,
    ExitManagementBaseStrategy,
)


class PreFlipD10Config(ExitManagementBaseConfig, frozen=True):
    policy: str = "P0"
    stop_atr_mult: float = 1.0
    official_start_ns: int = 0
    official_end_ns: int = 0
    # (causal_available_ts, direction, regime_start_ts, score, threshold)
    d10_events: tuple[tuple[int, int, int, float, float], ...] = ()
    # Placebo entries use exactly the same event contract.
    placebo_events: tuple[tuple[int, int, int, float, float], ...] = ()


class PreFlipD10Strategy(ExitManagementBaseStrategy):
    """Event-driven P0-P4 execution with fill-anchored fixed stops."""

    def __init__(self, config: PreFlipD10Config):
        super().__init__(config)
        self._cfg = config
        raw = config.placebo_events if config.policy.startswith("P4") else config.d10_events
        self._d10_by_ts: dict[int, list[tuple]] = {}
        for event in raw:
            self._d10_by_ts.setdefault(int(event[0]), []).append(event)
        self._attempted_origin_regimes: set[int] = set()
        self._current_regime_id: int | None = None
        self._current_regime_direction: int = 0
        self._seen_regimes: dict[int, int] = {}
        self._same_timestamp_audit: list[dict] = []
        self._entry_timing_audit: list[dict] = []
        self._score_regime_audit: list[dict] = []
        self._last_flip_decision_ts: int | None = None
        self._diag.update({
            "d10_events_seen": 0, "d10_entries_scheduled": 0,
            "d10_exits": 0, "stop_before_flip": 0, "stop_after_flip": 0,
            "data_end_censored": 0,
        })

    def _on_1s_bar(self, bar):
        decision_ts = int(bar.ts_init)
        # Base order is deliberate: bar OHLC stop handling occurs before D10,
        # and the 1m bucket/regime update occurs before checkpoint lookup.
        super()._on_1s_bar(bar)
        for event in self._d10_by_ts.get(decision_ts, ()):
            self._process_d10(event, decision_ts)
        if (self._trade is not None and self._trade.get("pending_exit_reason")
                and not self._trade.get("stop_cancel_pending")):
            self._submit_exit(self._trade["pending_exit_reason"])

    def _process_d10(self, event, decision_ts: int):
        _, old_direction, event_regime_id, score, threshold = event
        self._diag["d10_events_seen"] += 1
        identity_ok = self._seen_regimes.get(int(event_regime_id)) == int(old_direction)
        self._score_regime_audit.append({
            "trade_id": self._trade.get("trade_id") if self._trade else None,
            "entry_regime_id": int(event_regime_id),
            "confirmed_regime_id": (self._trade or {}).get("confirmed_regime_id"),
            "d10_regime_id": int(event_regime_id), "pass": bool(identity_ok),
            "reason": "checkpoint_regime_direction_identity",
            "score_available_ts": int(decision_ts),
            "score_observation_time": int(decision_ts - 1_000_000_000),
        })
        if not identity_ok:
            self._halt("frozen score event does not match an NT-observed regime/direction")
            raise RuntimeError("score/regime identity audit failure")
        same_flip = self._last_flip_decision_ts == decision_ts
        if same_flip:
            self._same_timestamp_audit.append({
                "trade_id": self._trade.get("trade_id") if self._trade else None,
                "regime_id": int(event_regime_id),
                "score_observation_time": decision_ts - 1_000_000_000,
                "score_value": float(score), "D10_threshold": float(threshold),
                "regime_flip_time": decision_ts,
                "callback_ordering": "1m_regime_update_before_score_lookup",
                "chosen_exit_reason": (self._trade or {}).get("exit_reason", "none"),
                "exit_price": (self._trade or {}).get("exit_price"),
            })

        if self._trade is not None and self._trade.get("entry_ts") is not None:
            t = self._trade
            if (self._cfg.policy in ("P2", "P3", "P4B")
                    and t.get("confirmed")
                    and int(event_regime_id) == int(t["confirmed_regime_id"])
                    and decision_ts > int(t["entry_ts"])):
                self._score_regime_audit.append({
                    "trade_id": t["trade_id"], "entry_regime_id": t.get("origin_regime_id"),
                    "confirmed_regime_id": t.get("confirmed_regime_id"),
                    "d10_regime_id": int(event_regime_id), "pass": True,
                })
                self._submit_exit("d10_exit")
                self._diag["d10_exits"] += 1
            return

        if self._cfg.policy not in ("P1", "P3", "P4A", "P4B"):
            return
        if not (self._cfg.official_start_ns <= decision_ts <= self._cfg.official_end_ns):
            return
        if int(event_regime_id) in self._attempted_origin_regimes:
            return
        # Fail closed if the independent NT regime state does not agree with
        # the frozen score event's originating regime and direction.
        if (self._current_regime_id != int(event_regime_id)
                or self._current_regime_direction != int(old_direction)):
            self._score_regime_audit.append({
                "trade_id": None, "entry_regime_id": int(event_regime_id),
                "confirmed_regime_id": None, "d10_regime_id": int(event_regime_id),
                "pass": False, "reason": "NT_regime_mismatch_at_entry",
            })
            return
        s = self._registry.get("1m")
        atr = float(s.atr) if s is not None and s.atr is not None else float("nan")
        self._attempted_origin_regimes.add(int(event_regime_id))
        self._schedule_entry(-int(old_direction), decision_ts, atr, int(event_regime_id))
        if self._pending_entry is not None:
            self._pending_entry["origin_regime_id"] = int(event_regime_id)
            self._pending_entry["score"] = float(score)
            self._pending_entry["threshold"] = float(threshold)
            self._diag["d10_entries_scheduled"] += 1
            # The base callback's submission phase has already passed. Submit
            # now, in this same causal callback, so D10 and flip entries both
            # fill at the immediately following executable 1s open.
            self._submit_entry()

    def _schedule_entry(self, direction, decision_ts, atr_at_signal, regime_start_ts):
        super()._schedule_entry(direction, decision_ts, atr_at_signal, regime_start_ts)
        if self._pending_entry is not None:
            self._pending_entry["origin_regime_id"] = int(regime_start_ts)

    def _submit_entry(self):
        pending = dict(self._pending_entry) if self._pending_entry else None
        super()._submit_entry()
        if self._trade is not None and pending is not None:
            self._trade.update({
                "policy": self._cfg.policy,
                "stop_atr_mult": float(self._cfg.stop_atr_mult),
                "origin_regime_id": int(pending["origin_regime_id"]),
                "confirmed": self._cfg.policy in ("P0", "P2"),
                "confirmed_regime_id": (int(pending["origin_regime_id"])
                                         if self._cfg.policy in ("P0", "P2") else None),
                "confirmation_ts": (int(pending["decision_ts"])
                                    if self._cfg.policy in ("P0", "P2") else None),
                "confirmation_price": None,
                "pre_flip_mae_points": 0.0,
                "score_at_entry": pending.get("score"),
                "entry_submit_ts": int(pending["decision_ts"]),
                "stop_order_id": None,
                "stop_cancel_pending": False,
                "pending_exit_reason": None,
                "stop_trigger_ts": None,
                "stop_trigger_price": None,
            })

    def _handle_regular_fill(self, event):
        t = self._trade
        is_entry = t is not None and event.client_order_id.value == t.get("entry_order_id")
        is_exit = t is not None and event.client_order_id.value == t.get("exit_order_id")
        snapshot = dict(t) if is_exit else None
        super().on_order_filled(event)
        if is_entry and self._trade is not None:
            raw_stop = float(event.last_px) - (
                self._trade["direction"] * self._cfg.stop_atr_mult * self._trade["atr_at_signal"])
            ticks = (Decimal(str(raw_stop)) / Decimal("0.25")).to_integral_value(
                rounding=ROUND_HALF_UP)
            stop_px = float(ticks * Decimal("0.25"))
            self._trade["stop_price"] = stop_px
            if self._trade.get("confirmed"):
                self._trade["confirmation_price"] = float(event.last_px)
            if self._cfg.policy not in ("P0", "P2"):
                side = OrderSide.SELL if self._trade["direction"] == 1 else OrderSide.BUY
                stop = self.order_factory.stop_market(
                    instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
                    order_side=side, quantity=Quantity.from_int(self._cfg.position_size),
                    trigger_price=Price(stop_px, 2), time_in_force=TimeInForce.GTC,
                    reduce_only=True,
                )
                self._trade["stop_order_id"] = stop.client_order_id.value
                self.submit_order(stop)
            self._entry_timing_audit.append({
                "trade_id": self._trade["trade_id"],
                "decision_ts": self._trade["decision_ts"],
                "fill_ts": int(event.ts_event), "fill_price": float(event.last_px),
                # At a bar boundary, the next bar's ts_event equals the prior
                # completed bar's ts_init/decision timestamp.
                "filled_at_or_after_decision": int(event.ts_event) >= self._trade["decision_ts"],
                "actual_executable_fill": True,
                "submit_ts": self._trade["entry_submit_ts"],
                "expected_next_open_boundary": int(event.ts_event) == self._trade["decision_ts"],
            })

    def on_order_filled(self, event):
        t = self._trade
        if t is not None and event.client_order_id.value == t.get("stop_order_id"):
            t["exit_order_id"] = t["stop_order_id"]
            t["exit_price"] = float(event.last_px)
            t["exit_ts"] = int(event.ts_event)
            t["stop_trigger_ts"] = int(event.ts_event)
            t["stop_trigger_price"] = t["stop_price"]
            t["exit_reason"] = "stop_after_flip" if t.get("confirmed") else "stop_before_flip"
            self._diag[t["exit_reason"]] += 1
            self._finalize_trade()
            return
        self._handle_regular_fill(event)

    def _submit_exit(self, reason: str):
        t = self._trade
        if t is not None and t.get("stop_order_id"):
            if t.get("stop_cancel_pending"):
                return
            order = self.cache.order(ClientOrderId(t["stop_order_id"]))
            if order is not None and not order.is_closed:
                t["pending_exit_reason"] = reason
                t["stop_cancel_pending"] = True
                self.cancel_order(order)
                return
            t["stop_order_id"] = None
        super()._submit_exit(reason)

    def on_order_canceled(self, event):
        t = self._trade
        if t is None or event.client_order_id.value != t.get("stop_order_id"):
            return
        reason = t.get("pending_exit_reason")
        t["stop_order_id"] = None
        t["stop_cancel_pending"] = False
        t["pending_exit_reason"] = None
        if reason is not None:
            # Submit the replacement only after the stop cancellation is
            # acknowledged. If the stop fills first, on_order_filled finalizes
            # the trade and this callback sees no live trade.
            super()._submit_exit(reason)

    def on_order_cancel_rejected(self, event):
        t = self._trade
        if t is None or event.client_order_id.value != t.get("stop_order_id"):
            return
        t["stop_cancel_pending"] = False
        self._diag["stop_cancel_rejected"] = self._diag.get("stop_cancel_rejected", 0) + 1

    def _update_open_trade(self, bar, decision_ts):
        t = self._trade
        super()._update_open_trade(bar, decision_ts)
        if t is not None and t.get("entry_ts") is not None and not t.get("confirmed"):
            adverse = (t["fill_price"] - float(bar.low) if t["direction"] == 1
                       else float(bar.high) - t["fill_price"])
            t["pre_flip_mae_points"] = max(float(t.get("pre_flip_mae_points", 0)), adverse)

    def _on_regime_flip(self, new_regime, bar_data, decision_ts, bar_ts_event, in_rth):
        self._last_flip_decision_ts = int(decision_ts)
        self._current_regime_id = int(bar_data["ts_init"])
        self._current_regime_direction = int(new_regime)
        self._seen_regimes[self._current_regime_id] = self._current_regime_direction
        t = self._trade
        if t is not None and not t.get("confirmed") and int(new_regime) == int(t["direction"]):
            t["confirmed"] = True
            t["confirmed_regime_id"] = int(bar_data["ts_init"])
            t["confirmation_ts"] = int(decision_ts)
            t["confirmation_price"] = float(bar_data["close"])
            # Explicit reset: no old-regime score/path identifier survives into
            # the new-regime D10 exit association.
            t["old_regime_state_reset"] = True
            return
        if self._cfg.policy in ("P0", "P2") and self._trade is None and self._pending_entry is None:
            if self._cfg.official_start_ns <= decision_ts <= self._cfg.official_end_ns:
                s = self._registry.get("1m")
                atr = float(s.atr) if s is not None and s.atr is not None else float("nan")
                self._schedule_entry(int(new_regime), decision_ts, atr, int(bar_data["ts_init"]))

    def _finalize_trade(self):
        t = self._trade
        if t.get("exit_reason") == "opposite_flip":
            t["exit_reason"] = "opposite_regime_flip_exit"
        if t.get("confirmation_ts") and t.get("confirmation_price") is not None:
            t["pre_flip_pnl"] = ((t["confirmation_price"] - t["fill_price"])
                                 * t["direction"] * self._cfg.multiplier)
            t["post_flip_pnl"] = ((t["exit_price"] - t["confirmation_price"])
                                  * t["direction"] * self._cfg.multiplier)
        else:
            t["pre_flip_pnl"] = ((t["exit_price"] - t["fill_price"])
                                 * t["direction"] * self._cfg.multiplier)
            t["post_flip_pnl"] = 0.0
        t["pre_flip_mae_atr"] = t.get("pre_flip_mae_points", 0.0) / t["atr_at_signal"]
        super()._finalize_trade()

    def on_stop(self):
        if self._trade is not None and self._trade.get("entry_ts") is None:
            self._diag["submitted_unfilled_entry_data_end"] = self._diag.get(
                "submitted_unfilled_entry_data_end", 0) + 1
            self._trade = None
        if self._trade is not None and self._trade.get("entry_ts") is not None:
            t = self._trade
            t.update({"exit_reason": "data_end_censored", "exit_ts": None,
                      "exit_price": None, "gross_pnl": None, "net_pnl": None,
                      "hold_s": None, "session": "RTH" if self._is_rth_minute(t["entry_ts"]) else "ETH"})
            self._trades.append(dict(t))
            self._trade = None
            self._diag["data_end_censored"] += 1
        if self._pending_entry is not None:
            self._diag["pending_entry_data_end_censored"] = self._diag.get(
                "pending_entry_data_end_censored", 0) + 1
            self._pending_entry = None
        super().on_stop()
        if self._cfg.output_dir:
            out = __import__("pathlib").Path(self._cfg.output_dir)
            for name, rows in (("entry_timing_audit.parquet", self._entry_timing_audit),
                               ("score_regime_id_audit.parquet", self._score_regime_audit),
                               ("same_timestamp_exit_audit.parquet", self._same_timestamp_audit)):
                pd.DataFrame(rows).to_parquet(out / name, index=False)

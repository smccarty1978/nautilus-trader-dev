"""Live-style bracket strategy — subclass of CollectorV2.

Inherits the full tested state machine (regime, events, checkpoints,
feature computation) from the v2 collector. At each 30s checkpoint:

  1. Read the 15 top-K feature values from the populated event +
     checkpoint state (no re-computation — just dict lookups)
  2. Score the frozen LightGBM model
  3. If score >= pre-computed top-10% threshold AND no open trade,
     schedule a market-order entry for `decision_time + 30s` (matches
     offline §7.1 fill semantics)

Order lifecycle:
  - Entry fills at the first 1s bar at/after the scheduled fill_time
  - Immediately place PT limit (+1 ATR) and SL stop (−1 ATR) bracket
  - PT/SL fill → close trade, cancel opposing side
  - 1m regime flip against position → cancel bracket + market close

Offline parquet writes are disabled (pure trading, no dataset gen).
The strategy uses the same proven feature pipeline that passed the
WO5 parity harness on all 6 training years.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd

sys.path.insert(0,
                 str(Path(__file__).parent.parent.parent
                     / "1m_regime_collector_v2"))

from collector import CollectorV2, CollectorV2Config  # noqa: E402

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity


class LiveBracketConfig(CollectorV2Config, frozen=True):
    # Additional live-trading fields layered on CollectorV2Config
    model_path: str = ""
    feature_list_path: str = ""
    score_threshold: float = 0.0
    pt_atr_mult: float = 1.0
    sl_atr_mult: float = 1.0
    position_size: int = 1
    # Fill delay (ns) between decision and market-order submission.
    # Matches offline §7.1 convention: fill at decision_time + 30s.
    fill_delay_ns: int = 30_000_000_000
    # Maximum checkpoint age (seconds) at which the model is allowed
    # to score and open new entries. The event lifecycle continues
    # past this for bookkeeping / exits, but no new entries are
    # opened. MUST match the model's training-data scope.
    max_entry_checkpoint_s: int = 600
    # Optional: if set, write a parquet of ALL scored checkpoints
    # (event_id, checkpoint_s, score, decision_ts_ns) for
    # runtime-vs-collector reconciliation. Disabled by default.
    dump_scored_path: str = ""
    # Decision mode for the score:
    #  "select"  : trade when score >= score_threshold  (default; bracket-aligned)
    #  "exclude" : trade when score <  score_threshold  (failure filter — high
    #              score = predicted failure, skip)
    mode: str = "select"


class LiveBracketStrategy(CollectorV2):
    """CollectorV2 subclass that trades at qualifying checkpoints."""

    def __init__(self, config: LiveBracketConfig):
        super().__init__(config)
        self._lcfg = config

        self._model = lgb.Booster(model_file=config.model_path)
        with open(config.feature_list_path) as f:
            self._feat_names: list[str] = json.load(f)["features"]
        self._threshold: float = config.score_threshold

        # Pending entries queued by decision, to submit at fill_time
        # Each item: dict(fill_time_ns, direction, atr_at_signal,
        #                 event_id, checkpoint_s, score, ev_ref)
        self._pending_entries: list[dict] = []

        # Active trades (entry order id → trade state dict)
        self._trades: dict[str, dict] = {}
        # order_id → entry_id (for dispatching bracket fills)
        self._order_to_trade: dict[str, str] = {}
        # event_id → entry_id (for dispatching regime-flip cancels)
        self._event_to_trade: dict[int, str] = {}
        self._open_count: int = 0

        # For reconciliation: log every scored checkpoint
        self._scored_log: list[dict] = []

        self._live_diag = {
            "checkpoints_scored": 0,
            "scores_above_threshold": 0,
            "entries_queued": 0,
            "entries_submitted": 0,
            "entries_filled": 0,
            "brackets_placed": 0,
            "pt_hits": 0,
            "sl_hits": 0,
            "regime_exits": 0,
            "skipped_single_position": 0,
            "missing_features": 0,
        }

    # ----- parquet writes: DISABLED -----
    def _write_outputs(self):
        # Pure trading strategy — no dataset dump
        pass

    # ----- hook: after each checkpoint snap, make trading decision -----
    def _snap_checkpoint(self, ev, T: int, current_ts: int):
        # Parent populates cp.features and cp.alive_at_T
        super()._snap_checkpoint(ev, T, current_ts)
        cp = ev.checkpoints.get(T)
        if cp is None or not cp.alive_at_T:
            return

        # ENTRY-SCOPE GATE: model was trained on T in [0, 600] only.
        # Event lifecycle continues past 600s (bookkeeping + exits)
        # but no new entries are opened beyond the training scope.
        if T > self._lcfg.max_entry_checkpoint_s:
            return

        # Build feature vector from merged root+checkpoint dicts
        merged = {**ev.root_features, **cp.features}
        vec = []
        for name in self._feat_names:
            v = merged.get(name)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                self._live_diag["missing_features"] += 1
                return
            vec.append(float(v))

        self._live_diag["checkpoints_scored"] += 1

        score = float(self._model.predict([vec])[0])

        # Optional reconciliation log: record EVERY scored checkpoint
        if self._lcfg.dump_scored_path:
            self._scored_log.append({
                "event_id": int(ev.event_id),
                "checkpoint_s": int(T),
                "decision_ts_ns": int(current_ts),
                "signal_direction": int(ev.signal_direction),
                "score": score,
                "above_threshold": score >= self._threshold,
                "feature_vec": vec,  # for feature-parity audit
            })

        # Decision rule per config.mode
        if self._lcfg.mode == "select":
            if score < self._threshold:
                return
        elif self._lcfg.mode == "exclude":
            # Failure filter: skip trades with HIGH failure score
            if score >= self._threshold:
                return
        else:
            raise ValueError(f"Unknown mode: {self._lcfg.mode}")

        self._live_diag["scores_above_threshold"] += 1

        # Single-position gate
        if self._open_count > 0:
            self._live_diag["skipped_single_position"] += 1
            return

        # Queue entry at fill_time (= decision + fill_delay)
        fill_time_ns = current_ts + self._lcfg.fill_delay_ns
        self._pending_entries.append({
            "fill_time_ns": fill_time_ns,
            "direction": ev.signal_direction,
            "atr_at_signal": ev.atr_at_signal,
            "event_id": ev.event_id,
            "checkpoint_s": T,
            "decision_ts_ns": current_ts,
            "score": score,
        })
        self._live_diag["entries_queued"] += 1

    # ----- on each 1s bar: check pending entries + collector logic -----
    def _on_1s(self, bar):
        # Let parent do its thing (session, regime, aggregation, etc.)
        super()._on_1s(bar)
        ts = bar.ts_event

        # Fire any pending entries whose fill_time has been reached
        remaining: list[dict] = []
        for pe in self._pending_entries:
            if pe["fill_time_ns"] <= ts:
                self._submit_entry(pe)
            else:
                remaining.append(pe)
        self._pending_entries = remaining

    def _submit_entry(self, pe: dict):
        if self._open_count > 0:
            # Another trade opened between decision and fill — skip
            self._live_diag["skipped_single_position"] += 1
            return
        direction = int(pe["direction"])
        side = OrderSide.BUY if direction == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._lcfg.position_size)

        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._lcfg.instrument_id),
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
        )
        cid = order.client_order_id.value

        trade = {
            "direction": direction,
            "atr_at_signal": float(pe["atr_at_signal"]),
            "event_id": int(pe["event_id"]),
            "checkpoint_s": int(pe["checkpoint_s"]),
            "decision_ts_ns": int(pe["decision_ts_ns"]),
            "score": float(pe["score"]),
            "entry_fill_price": None,
            "pt_id": None,
            "sl_id": None,
            "exit_reason": None,
        }
        self._trades[cid] = trade
        self._order_to_trade[cid] = cid
        self._event_to_trade[trade["event_id"]] = cid
        self.submit_order(order)
        self._live_diag["entries_submitted"] += 1

    # ----- order-fill dispatch -----
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
            self._open_count += 1
            self._live_diag["entries_filled"] += 1
            self._place_bracket(entry_id, trade)
        elif cid == trade["pt_id"]:
            trade["exit_reason"] = "pt"
            self._live_diag["pt_hits"] += 1
            self._open_count = max(0, self._open_count - 1)
            self._on_trade_closed(entry_id)
        elif cid == trade["sl_id"]:
            trade["exit_reason"] = "sl"
            self._live_diag["sl_hits"] += 1
            self._open_count = max(0, self._open_count - 1)
            self._on_trade_closed(entry_id)

    def _place_bracket(self, entry_id: str, trade: dict):
        inst_id = InstrumentId.from_str(self._lcfg.instrument_id)
        inst = self.cache.instrument(inst_id)
        if inst is None:
            self.log.error("Instrument missing at bracket placement")
            return
        d = trade["direction"]
        atr = trade["atr_at_signal"]
        ep = trade["entry_fill_price"]

        pt_raw = ep + d * self._lcfg.pt_atr_mult * atr
        sl_raw = ep - d * self._lcfg.sl_atr_mult * atr
        tick = float(inst.price_increment)
        pt_snap = round(pt_raw / tick) * tick
        sl_snap = round(sl_raw / tick) * tick

        exit_side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._lcfg.position_size)

        pt = self.order_factory.limit(
            instrument_id=inst_id, order_side=exit_side, quantity=qty,
            price=Price(pt_snap, inst.price_precision),
            time_in_force=TimeInForce.GTC, reduce_only=True,
        )
        sl = self.order_factory.stop_market(
            instrument_id=inst_id, order_side=exit_side, quantity=qty,
            trigger_price=Price(sl_snap, inst.price_precision),
            time_in_force=TimeInForce.GTC, reduce_only=True,
        )
        trade["pt_id"] = pt.client_order_id.value
        trade["sl_id"] = sl.client_order_id.value
        self._order_to_trade[trade["pt_id"]] = entry_id
        self._order_to_trade[trade["sl_id"]] = entry_id
        self.submit_order(pt)
        self.submit_order(sl)
        self._live_diag["brackets_placed"] += 1

    def _on_trade_closed(self, entry_id: str):
        # Cancel any leftover bracket side
        self.cancel_all_orders(
            InstrumentId.from_str(self._lcfg.instrument_id))

    # ----- regime-flip cancel: hook into collector's termination -----
    def _terminate_event(self, ev, reason: str, exit_time: int,
                          exit_price: float):
        """Parent terminates event lifecycle. If we have an open trade
        tied to this event AND the exit reason is `regime_flip`, cancel
        the bracket + market close."""
        # Check for live trade tied to this event BEFORE calling parent
        live_cancel = False
        if ev.event_id in self._event_to_trade:
            entry_id = self._event_to_trade[ev.event_id]
            trade = self._trades.get(entry_id)
            if (trade is not None
                    and trade.get("entry_fill_price") is not None
                    and trade.get("exit_reason") is None):
                live_cancel = True

        super()._terminate_event(ev, reason, exit_time, exit_price)

        if live_cancel:
            inst_id = InstrumentId.from_str(self._lcfg.instrument_id)
            self.cancel_all_orders(inst_id)
            self.close_all_positions(inst_id)
            entry_id = self._event_to_trade.pop(ev.event_id, None)
            if entry_id and entry_id in self._trades:
                self._trades[entry_id]["exit_reason"] = "regime_exit"
            self._live_diag["regime_exits"] += 1
            self._open_count = max(0, self._open_count - 1)

    def on_stop(self):
        # Parent terminates active events; we disabled parquet writes
        super().on_stop()
        self.log.info(f"Live diag: {self._live_diag}")

        # Dump scored log if requested (reconciliation)
        if self._lcfg.dump_scored_path and self._scored_log:
            out = pd.DataFrame(self._scored_log)
            # Unpack feature_vec into columns named f_0..f_14
            feat_cols = [f"f_{i}" for i in range(
                len(self._feat_names))]
            feat_df = pd.DataFrame(
                out["feature_vec"].tolist(), columns=feat_cols)
            out = pd.concat([out.drop(columns=["feature_vec"]),
                              feat_df], axis=1)
            Path(self._lcfg.dump_scored_path).parent.mkdir(
                parents=True, exist_ok=True)
            out.to_parquet(self._lcfg.dump_scored_path, index=False)
            self.log.info(
                f"Wrote {len(out)} scored checkpoints to "
                f"{self._lcfg.dump_scored_path}")

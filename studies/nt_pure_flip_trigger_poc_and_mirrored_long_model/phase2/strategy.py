"""NT event-driven simplified fixed-stop/regime-flip strategy for the pure
flip-trigger proof of concept.

Adapted from the already-audited `fable5_nt_short_rth_policy_a/strategy.py`
(schedule-driven entry dispatch, live `RegimeEngine` for flip detection),
with two deliberate simplifications per SPEC.md finding 8:
  - ONE fixed stop at entry_px +/- 1.25*ATR, placed once, never swapped.
  - NO confirmation timeout -- wait indefinitely for the bearish flip.
Exit state logic is delegated to `trade_state.FlipTradeState`
(hand-tested in tests/test_trade_state.py before being wired in here).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine, tick_round  # noqa: E402
from trade_state import (  # noqa: E402
    FlipTradeState, favorable_adverse_points, realized_favorable_atr, unrealized_pnl,
)

NS = 1_000_000_000


class SimpleFlipTriggerConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    variant_label: str = "T1"
    schedule_path: str = ""
    stop_atr_mult: float = 1.25
    multiplier: float = 20.0
    cost_rt: float = 10.0
    rth_start_min: int = 8 * 60 + 30
    rth_end_min: int = 15 * 60


class SimpleFlipTriggerStrategy(Strategy):
    def __init__(self, config: SimpleFlipTriggerConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._engine = RegimeEngine()
        self._regime_dir = 0

        self._sched: list[dict] = []
        self._ptr = 0

        self._trade: Optional[dict] = None
        self._state: Optional[FlipTradeState] = None
        self._entry_order_id: Optional[str] = None
        self._pending_meta: Optional[dict] = None
        self._exit_order_id: Optional[str] = None
        self._exit_reason_pending: Optional[str] = None
        self._exit_retry = False
        self._stop_order_id: Optional[str] = None

        self._last_1s_ts_init = 0
        self._n_trades = 0

        self.trades: list[dict] = []
        self.flips: list[dict] = []
        self.skips: list[dict] = []
        self.raw_paths: list[dict] = []

    # ------------------------------------------------------------- setup
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)
        df = pd.read_parquet(self._cfg.schedule_path).sort_values("signal_decision_ts")
        for r in df.itertuples(index=False):
            self._sched.append({
                "regime_start_ns": int(r.regime_start_ns),
                "signal_decision_ts": int(r.signal_decision_ts),
                "atr": float(r.atr_at_checkpoint),
                "direction": int(r.entry_direction),
                "recon_confirm_flip_ns": int(r.recon_confirm_flip_ns),
            })
        self.log.info(f"[{self._cfg.variant_label}] Loaded {len(self._sched)} entries")

    # ------------------------------------------------------------- bars
    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    def _rth_minute_of_day(self, ts_ns: int) -> int:
        ts = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
        return ts.hour * 60 + ts.minute

    def _in_rth(self, ts_ns: int) -> bool:
        m = self._rth_minute_of_day(ts_ns)
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _on_1s(self, bar: Bar):
        decision_ts = int(bar.ts_init)
        self._last_1s_ts_init = decision_ts

        t, st = self._trade, self._state
        if t is not None and st is not None and not st.closed:
            self._track_excursion(t, st, bar, decision_ts)
            # Stop-touch detection/fill is NOT done here: a real resting
            # `stop_market` order (placed once in `_on_entry_filled`, never
            # swapped) handles it via the engine's own bar-execution model
            # (audit CRITICAL fix -- a prior version manually polled
            # high/low and fired a FOK *market* order on touch, which fills
            # at the bar's CLOSE rather than the stop's trigger price,
            # systematically understating every stop-loss).

        if (self._exit_retry and self._trade is not None and self._exit_order_id is None):
            self._exit_retry = False
            self._submit_exit(self._exit_reason_pending)

        while (self._ptr < len(self._sched)
               and self._sched[self._ptr]["signal_decision_ts"] <= decision_ts):
            entry = self._sched[self._ptr]
            self._ptr += 1
            self._try_enter(entry, decision_ts)

    def _try_enter(self, entry: dict, decision_ts: int):
        if (self._trade is not None or self._entry_order_id is not None
                or self._exit_order_id is not None or self._exit_retry):
            self.skips.append({"signal_decision_ts": entry["signal_decision_ts"],
                               "reason": "position_open_at_entry"})
            return
        if not self._in_rth(decision_ts):
            self.skips.append({"signal_decision_ts": entry["signal_decision_ts"],
                               "reason": "outside_rth_at_dispatch"})
            return
        atr = entry["atr"]
        if atr is None or not np.isfinite(atr) or atr <= 0:
            self.skips.append({"signal_decision_ts": entry["signal_decision_ts"], "reason": "bad_atr"})
            return
        side = OrderSide.SELL if entry["direction"] == -1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
        self._entry_order_id = order.client_order_id.value
        self._pending_meta = {**entry, "submit_ts": decision_ts, "regime_at_entry": self._regime_dir}
        self.submit_order(order)

    # ------------------------------------------------------------- 1m regime
    def _on_1m(self, bar: Bar):
        prev = self._regime_dir
        new = self._engine.update(float(bar.high), float(bar.low), float(bar.close))
        self._regime_dir = new
        flip = prev != 0 and new != 0 and new != prev
        if not flip:
            return
        flip_ts = int(bar.ts_init)
        self.flips.append({"flip_ts": flip_ts, "direction": new})

        t, st = self._trade, self._state
        if t is None or st is None or st.closed:
            return
        result = st.on_regime_update(new, flip_ts)
        if result == "opposing_flip_exit":
            t["bullish_exit_flip_time"] = flip_ts
            if self._exit_order_id is None and not self._exit_retry:
                self._submit_exit("opposing_flip_exit")
        elif st.bearish_flip_confirmed and t.get("bearish_flip_time") is None:
            t["bearish_flip_time"] = flip_ts

    # ------------------------------------------------------------- orders
    def _submit_exit(self, reason: str):
        """Opposing-flip exit ONLY (the fixed stop is a real resting
        stop_market order, handled via on_order_filled routing, not this
        path). Cancels the resting stop first, matching
        fable5_nt_short_rth_policy_a's precedent ordering."""
        t = self._trade
        if t is None or self._exit_order_id is not None:
            return
        self._cancel_stop()
        side = OrderSide.BUY if t["direction"] == -1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK, reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason_pending = reason
        self.submit_order(order)

    def _cancel_stop(self):
        if self._stop_order_id is None:
            return
        o = self.cache.order(ClientOrderId(self._stop_order_id))
        if o is not None and not o.is_closed:
            self.cancel_order(o)
        self._stop_order_id = None

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)
        if cid == self._entry_order_id:
            self._on_entry_filled(px, int(event.ts_event))
        elif cid == self._stop_order_id:
            self._on_stop_filled(px, int(event.ts_event))
        elif cid == self._exit_order_id:
            self._on_exit_filled(px, int(event.ts_event))

    def _on_entry_filled(self, px: float, ts: int):
        meta = self._pending_meta
        self._entry_order_id = None
        self._pending_meta = None
        self._n_trades += 1
        atr = float(meta["atr"])
        direction = int(meta["direction"])
        state = FlipTradeState(entry_direction=direction, entry_px=px, atr=atr,
                               stop_atr_mult=self._cfg.stop_atr_mult)
        t = {
            "variant": self._cfg.variant_label,
            "trade_id": f"{self._cfg.variant_label}_{self._n_trades}",
            "bullish_regime_id_at_entry": int(meta["regime_start_ns"]),
            "entry_trigger_time": int(meta["signal_decision_ts"]),
            "entry_order_time": int(meta["submit_ts"]), "entry_fill_time": int(ts),
            "entry_price": float(px), "atr_entry": atr, "fixed_stop_price": state.stop_px,
            "direction": direction,
            "recon_confirm_flip_ns": int(meta["recon_confirm_flip_ns"]),
            "bearish_flip_time": None, "bullish_exit_flip_time": None,
            "exit_order_time": None, "exit_fill_time": None, "exit_price": None, "exit_reason": None,
            "pre_flip_mfe_pts": 0.0, "pre_flip_mae_pts": 0.0,
            "post_flip_mfe_pts": 0.0, "post_flip_mae_pts": 0.0,
            "whole_trade_mfe_pts": 0.0, "whole_trade_mae_pts": 0.0,
            "max_unrealized_pnl": 0.0, "min_unrealized_pnl": 0.0,
        }
        assert self._trade is None, "entry filled with trade open (desync)"
        self._trade = t
        self._state = state

        # ONE resting stop_market order, placed once, never swapped/moved
        # (SPEC.md finding 8b) -- fills via the engine's own bar-execution
        # model (gap-through fills at trigger price optimistically, matching
        # fable5_nt_short_rth_policy_a's fixture-verified convention), not a
        # manually-polled market order.
        side = OrderSide.BUY if direction == -1 else OrderSide.SELL
        trig = tick_round(state.stop_px)
        so = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), trigger_price=Price(trig, 2),
            time_in_force=TimeInForce.GTC, reduce_only=True)
        self._stop_order_id = so.client_order_id.value
        self.submit_order(so)

    def _on_stop_filled(self, px: float, ts: int):
        self._stop_order_id = None
        st = self._state
        if st is None or st.closed:
            return
        reason = st.on_stop_touch()
        self._close(reason, px, ts)

    def _on_exit_filled(self, px: float, ts: int):
        self._exit_order_id = None
        reason = self._exit_reason_pending
        self._exit_reason_pending = None
        self._close(reason, px, ts)

    def _close(self, reason: str, px: float, ts: int):
        t, st = self._trade, self._state
        t["exit_reason"] = reason
        t["exit_price"] = float(px)
        t["exit_fill_time"] = int(ts)
        t["exit_order_time"] = int(ts)
        gross = (px - t["entry_price"]) * t["direction"] * self._cfg.multiplier
        t["gross_pnl"] = gross
        t["net_pnl"] = gross - self._cfg.cost_rt
        t["hold_seconds"] = (ts - t["entry_fill_time"]) / 1e9
        t["seconds_entry_to_bearish_flip"] = (
            (t["bearish_flip_time"] - t["entry_fill_time"]) / 1e9
            if t["bearish_flip_time"] is not None else None)
        atr = t["atr_entry"]
        t["whole_trade_mfe_atr"] = t["whole_trade_mfe_pts"] / atr
        t["whole_trade_mae_atr"] = t["whole_trade_mae_pts"] / atr
        t["pre_flip_mfe_atr"] = t["pre_flip_mfe_pts"] / atr
        t["pre_flip_mae_atr"] = t["pre_flip_mae_pts"] / atr
        t["post_flip_mfe_atr"] = (t["post_flip_mfe_pts"] / atr
                                  if t["bearish_flip_time"] is not None else np.nan)
        t["post_flip_mae_atr"] = (t["post_flip_mae_pts"] / atr
                                  if t["bearish_flip_time"] is not None else np.nan)
        t["final_giveback_atr"] = t["whole_trade_mfe_atr"] - realized_favorable_atr(
            t["direction"], t["entry_price"], px, atr)
        st.closed = True
        st.exit_reason = reason
        self._cancel_stop()  # idempotent: no-op if already filled/cancelled
        self.trades.append(dict(t))
        self._trade = None
        self._state = None
        self._exit_retry = False

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self._pending_meta = None
            self.skips.append({"reason": "entry_fok_failed"})
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            if self._trade is not None and self._trade.get("exit_reason") is None:
                self._exit_retry = True
        elif cid == self._stop_order_id:
            self._stop_order_id = None
            self.log.error(f"[{self._cfg.variant_label}] stop rejected -- trade unprotected")

    def on_order_denied(self, event):
        self.on_order_rejected(event)

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if cid == self._stop_order_id:
            self._stop_order_id = None

    def on_order_expired(self, event):
        self.on_order_canceled(event)

    # ------------------------------------------------------------- helpers
    def _track_excursion(self, t: dict, st: FlipTradeState, bar: Bar, ts: int):
        ep, d = t["entry_price"], t["direction"]
        h, l = float(bar.high), float(bar.low)
        fav_pts, adv_pts = favorable_adverse_points(d, ep, h, l)
        t["whole_trade_mfe_pts"] = max(t["whole_trade_mfe_pts"], fav_pts)
        t["whole_trade_mae_pts"] = max(t["whole_trade_mae_pts"], adv_pts)
        if not st.bearish_flip_confirmed:
            t["pre_flip_mfe_pts"] = max(t["pre_flip_mfe_pts"], fav_pts)
            t["pre_flip_mae_pts"] = max(t["pre_flip_mae_pts"], adv_pts)
        else:
            t["post_flip_mfe_pts"] = max(t["post_flip_mfe_pts"], fav_pts)
            t["post_flip_mae_pts"] = max(t["post_flip_mae_pts"], adv_pts)
        unrealized = unrealized_pnl(d, ep, float(bar.close), self._cfg.multiplier)
        t["max_unrealized_pnl"] = max(t["max_unrealized_pnl"], unrealized)
        t["min_unrealized_pnl"] = min(t["min_unrealized_pnl"], unrealized)
        self.raw_paths.append({
            "trade_id": t["trade_id"], "ts": ts, "high": h, "low": l, "close": float(bar.close),
            "bearish_flip_confirmed": st.bearish_flip_confirmed,
        })

    def on_stop(self):
        self._cancel_stop()
        t = self._trade
        if t is not None:
            t["exit_reason"] = "end_of_data_exit"
            t["exit_price"] = np.nan
            t["exit_fill_time"] = None
            t["net_pnl"] = np.nan
            t["gross_pnl"] = np.nan
            self.trades.append(dict(t))
        self._trade = None
        self._state = None
        self.log.info(f"[{self._cfg.variant_label}] {len(self.trades)} trades")

"""NT event-driven Policy A management for original-W4 short-RTH fades.

Phase 1 (schedule mode): entries come from the frozen short-RTH W4 entry
schedule; the strategy validates Policy A management + NT fill/event semantics
independent of live signal generation. The live RegimeEngine (exact audited
port) supplies alignment (bearish flip) and opposing-flip (bullish) exits.

Policy A (short fade, direction = -1):
  - entry: FOK market submitted while processing the 1s bar with
    ts_init == target_fill_ts, so it fills at that bar's close stamped at
    target_fill_ts (fixture-verified fill model; ~= offline next-open).
  - pre-alignment stop: resting GTC stop-market at entry + 1.25*ATR (BUY).
  - 300s confirmation clock anchored to the actual entry fill ts.
  - alignment: 1m regime flips bearish (-1) at/if flip_ts <= timeout_ts ->
    cancel the pre stop, place the post stop at entry + 1.50*ATR.
  - timeout: if not aligned and a 1s decision boundary passes the deadline,
    market exit (confirmation_timeout).
  - opposing exit: after alignment, first bullish (+1) flip -> market exit.
  - stops are anchored to entry+ATR, never trailed.

Fill model (fixture-verified, test_fill_fixture in the d10 study): FOK market
fills at the just-completed bar's close at its ts_init boundary; GTC stop fills
at trigger (gap-through optimistically); same-bar stop-vs-exit races resolve to
the stop. No future regime/price state enters any decision.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.strategy import (  # noqa: E402
    RegimeEngine, tick_round,
)

NS = 1_000_000_000


class PolicyAShortRTHConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    year: int = 2025
    schedule_path: str = ""
    preflip_stop_atr: float = 1.25
    postflip_stop_atr: float = 1.50
    timeout_s: int = 300
    multiplier: float = 20.0
    cost_rt: float = 10.0


class PolicyAShortRTHStrategy(Strategy):
    def __init__(self, config: PolicyAShortRTHConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._engine = RegimeEngine()

        self._regime_dir = 0
        self._regime_start: Optional[int] = None

        # schedule: sorted by target_fill_ts, pointer sweep
        self._sched: list[dict] = []
        self._ptr = 0

        self._trade: Optional[dict] = None
        self._entry_order_id: Optional[str] = None
        self._pending_meta: Optional[dict] = None
        self._exit_order_id: Optional[str] = None
        self._exit_reason_pending: Optional[str] = None
        self._exit_retry = False
        self._stop_order_id: Optional[str] = None

        self._last_1s_close: Optional[float] = None
        self._last_1s_ts_init = 0
        self._n_trades = 0

        self.trades: list[dict] = []
        self.flips: list[dict] = []
        self.skips: list[dict] = []
        self.boundary_cases: list[dict] = []
        self.entry_timing: list[dict] = []

    # ------------------------------------------------------------- setup
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)
        df = pd.read_parquet(self._cfg.schedule_path)
        df = df[df["year"] == self._cfg.year].sort_values("target_fill_ts")
        for r in df.itertuples(index=False):
            self._sched.append({
                "regime_start_ns": int(r.regime_start_ns),
                "signal_decision_ts": int(r.signal_decision_ts),
                "target_fill_ts": int(r.target_fill_ts),
                "offline_entry_open": float(r.offline_entry_open),
                "direction": int(r.entry_direction),
                "atr": float(r.atr_at_checkpoint),
                "recon_confirm_flip_ns": int(r.recon_confirm_flip_ns),
                "recon_scheduled_exit_ts": int(r.recon_scheduled_exit_ts),
            })
        self.log.info(f"Loaded {len(self._sched)} short-RTH entries "
                      f"for {self._cfg.year}")

    # ------------------------------------------------------------- bars
    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    def _on_1s(self, bar: Bar):
        decision_ts = int(bar.ts_init)
        self._last_1s_close = float(bar.close)
        self._last_1s_ts_init = decision_ts

        t = self._trade
        if t is not None and t.get("entry_px") is not None:
            self._track_excursion(t, bar)

        # retry a rejected exit FOK on the next bar
        if (self._exit_retry and self._trade is not None
                and self._exit_order_id is None):
            self._exit_retry = False
            self._submit_exit(self._exit_reason_pending)

        # confirmation timeout: not aligned and the deadline has passed
        if (t is not None and t.get("entry_px") is not None
                and not t["aligned"] and self._exit_order_id is None
                and not self._exit_retry
                and decision_ts > t["timeout_ts"]):
            self._submit_exit("confirmation_timeout")

        # entry submission: submit during the bar whose ts_init == target,
        # so the FOK market fills at this bar's close stamped at target ts.
        while (self._ptr < len(self._sched)
               and self._sched[self._ptr]["target_fill_ts"] <= decision_ts):
            entry = self._sched[self._ptr]
            self._ptr += 1
            if entry["target_fill_ts"] != decision_ts:
                # quiet-second: target bar boundary had no 1s bar; submit at
                # the first boundary at/after target (fills at this close).
                self.boundary_cases.append({
                    "case": "entry_target_boundary_absent",
                    "target_fill_ts": entry["target_fill_ts"],
                    "submit_ts": decision_ts})
            self._try_enter(entry, decision_ts)

    def _try_enter(self, entry: dict, decision_ts: int):
        if (self._trade is not None or self._entry_order_id is not None
                or self._exit_order_id is not None or self._exit_retry):
            self.skips.append({"target_fill_ts": entry["target_fill_ts"],
                               "reason": "position_open_at_entry"})
            return
        atr = entry["atr"]
        if atr is None or not np.isfinite(atr) or atr <= 0:
            self.skips.append({"target_fill_ts": entry["target_fill_ts"],
                               "reason": "bad_atr"})
            return
        side = OrderSide.SELL if entry["direction"] == -1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
        self._entry_order_id = order.client_order_id.value
        self._pending_meta = {**entry, "submit_ts": decision_ts,
                              "regime_at_entry": self._regime_dir}
        self.submit_order(order)

    # ------------------------------------------------------------- 1m regime
    def _on_1m(self, bar: Bar):
        prev = self._regime_dir
        new = self._engine.update(float(bar.high), float(bar.low),
                                  float(bar.close))
        self._regime_dir = new
        flip = prev != 0 and new != 0 and new != prev
        if not flip:
            if prev == 0 and new != 0:
                self._regime_start = int(bar.ts_init)
            return
        flip_ts = int(bar.ts_init)   # flip known at 1m close
        self._regime_start = flip_ts
        self.flips.append({"flip_ts": flip_ts, "direction": new,
                           "last_1s_ts_init": self._last_1s_ts_init})

        t = self._trade
        if t is None or t.get("entry_px") is None:
            return
        d = t["direction"]
        if not t["aligned"] and new == d:
            # alignment: bearish flip into the short. Must occur at/before
            # the timeout deadline to count (offline: align_ts <= timeout_ts).
            if flip_ts <= t["timeout_ts"]:
                t["aligned"] = True
                t["align_ts"] = flip_ts
                t["align_lag_from_timeout_s"] = (t["timeout_ts"] - flip_ts) / 1e9
                self._swap_to_post_stop(t)
            else:
                self.boundary_cases.append({
                    "case": "align_after_timeout", "trade_id": t["trade_id"],
                    "flip_ts": flip_ts, "timeout_ts": t["timeout_ts"]})
            if abs(flip_ts - t["timeout_ts"]) <= NS:
                self.boundary_cases.append({
                    "case": "align_within_1s_of_timeout",
                    "trade_id": t["trade_id"], "flip_ts": flip_ts,
                    "timeout_ts": t["timeout_ts"], "aligned": t["aligned"]})
        elif t["aligned"] and new == -d:
            # opposing bullish flip ends the aligned regime -> exit
            if self._exit_order_id is None and not self._exit_retry:
                t["opposing_flip_ts"] = flip_ts
                self._submit_exit("opposite_flip")

    # ------------------------------------------------------------- orders
    def _swap_to_post_stop(self, t: dict):
        # Diagnostic snapshot ONLY (never a decision input): the running max
        # adverse excursion at the instant of alignment, so reconcile.py can
        # measure the pre-stop-breach-then-align tie sub-case (1.25-ATR pre
        # stop touched before the trade aligned instead of stopping out).
        t["mae_atr_at_align"] = float(t["mae_atr"])
        self._cancel_stop()
        trig = tick_round(t["entry_px"] + self._cfg.postflip_stop_atr * t["atr"])
        so = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1), trigger_price=Price(trig, 2),
            time_in_force=TimeInForce.GTC, reduce_only=True)
        self._stop_order_id = so.client_order_id.value
        t["post_stop_px"] = trig
        self.submit_order(so)

    def _submit_exit(self, reason: str):
        t = self._trade
        if t is None or t.get("entry_px") is None:
            return
        if self._exit_order_id is not None:
            return
        # cancel resting stop first: exit decision is causal at the bar
        # boundary and fills at this bar close, ahead of a later intrabar
        # stop trigger (fixture: a same-bar already-triggered stop still wins).
        self._cancel_stop()
        side = OrderSide.BUY if t["direction"] == -1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.FOK, reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason_pending = reason
        t.setdefault("exit_decision_ts", self.clock.timestamp_ns())
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
        atr = meta["atr"]
        t = {
            "trade_id": f"SR_{self._cfg.year}_{self._n_trades}",
            "year": self._cfg.year, "direction": int(meta["direction"]),
            "regime_start_ns": int(meta["regime_start_ns"]),
            "signal_decision_ts": int(meta["signal_decision_ts"]),
            "target_fill_ts": int(meta["target_fill_ts"]),
            "offline_entry_open": float(meta["offline_entry_open"]),
            "regime_at_entry": int(meta["regime_at_entry"]),
            "entry_ts": int(ts), "entry_px": float(px), "atr": float(atr),
            "timeout_ts": int(ts) + self._cfg.timeout_s * NS,
            "aligned": False, "align_ts": None,
            "align_lag_from_timeout_s": None,
            "opposing_flip_ts": None,
            "recon_confirm_flip_ns": int(meta["recon_confirm_flip_ns"]),
            "recon_scheduled_exit_ts": int(meta["recon_scheduled_exit_ts"]),
            "pre_stop_px": None, "post_stop_px": None,
            "mfe_atr": 0.0, "mae_atr": 0.0, "mae_atr_at_align": None,
            "exit_reason": None, "exit_px": None, "exit_ts": None,
        }
        assert self._trade is None, "entry filled with trade open (desync)"
        self._trade = t
        self.entry_timing.append({
            "trade_id": t["trade_id"], "target_fill_ts": t["target_fill_ts"],
            "entry_ts": ts, "entry_px": px,
            "offline_entry_open": t["offline_entry_open"],
            "entry_px_delta": px - t["offline_entry_open"],
            "entry_ts_delta": ts - t["target_fill_ts"]})
        # pre-alignment stop (short: above entry)
        trig = tick_round(px + self._cfg.preflip_stop_atr * atr)
        so = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1), trigger_price=Price(trig, 2),
            time_in_force=TimeInForce.GTC, reduce_only=True)
        self._stop_order_id = so.client_order_id.value
        t["pre_stop_px"] = trig
        self.submit_order(so)

    def _on_stop_filled(self, px: float, ts: int):
        self._stop_order_id = None
        t = self._trade
        if t is None:
            return
        reason = "stop_after_flip" if t["aligned"] else "stop_before_flip"
        self._close(reason, px, ts)

    def _on_exit_filled(self, px: float, ts: int):
        self._exit_order_id = None
        reason = self._exit_reason_pending
        self._exit_reason_pending = None
        if self._trade is None:
            return
        self._close(reason, px, ts)

    def _close(self, reason: str, px: float, ts: int):
        t = self._trade
        t["exit_reason"] = reason
        t["exit_px"] = float(px)
        t["exit_ts"] = int(ts)
        gross = (px - t["entry_px"]) * t["direction"] * self._cfg.multiplier
        t["gross_pnl"] = gross
        t["net_pnl"] = gross - self._cfg.cost_rt
        t["hold_s"] = (ts - t["entry_ts"]) / 1e9
        t["time_to_align_s"] = ((t["align_ts"] - t["entry_ts"]) / 1e9
                                if t["align_ts"] is not None else None)
        self._cancel_stop()
        self.trades.append(dict(t))
        self._trade = None
        self._exit_retry = False
        self._exit_reason_pending = None

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
            else:
                self._exit_reason_pending = None
        elif cid == self._stop_order_id:
            self._stop_order_id = None
            self.log.error("stop rejected — trade unprotected")

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if cid == self._stop_order_id:
            self._stop_order_id = None

    def on_order_expired(self, event):
        self.on_order_canceled(event)

    def on_order_denied(self, event):
        cid = event.client_order_id.value
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self._pending_meta = None
            self.skips.append({"reason": "entry_denied"})
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            if self._trade is not None and self._trade.get("exit_reason") is None:
                self._exit_retry = True

    # ------------------------------------------------------------- helpers
    def _track_excursion(self, t: dict, bar: Bar):
        ep, atr, d = t["entry_px"], t["atr"], t["direction"]
        h, l = float(bar.high), float(bar.low)
        fav = (ep - l) / atr if d == -1 else (h - ep) / atr
        adv = (h - ep) / atr if d == -1 else (ep - l) / atr
        t["mfe_atr"] = max(t["mfe_atr"], fav)
        t["mae_atr"] = max(t["mae_atr"], adv)

    def on_stop(self):
        t = self._trade
        if t is not None and t.get("entry_px") is not None:
            t["exit_reason"] = "data_end_censored"
            t["exit_px"] = np.nan
            t["exit_ts"] = None
            t["net_pnl"] = np.nan
            t["gross_pnl"] = np.nan
            self.trades.append(dict(t))
        self._trade = None
        self.log.info(f"short-RTH {self._cfg.year}: {len(self.trades)} trades")

"""HMM-state-filtered P1 strategy: partial PT at +1 ATR + BE-runner.

Live-style NT validation of the offline P1 finding:
  bar1_confirm entry + hmm_4 state 3 filter
  + 2 contracts; partial 1 ctr at +partial_atr ATR; runner stops at BE,
    else regime-exit
  → offline OOS pooled: +$30/tr per 1-unit notional (≈ +$60/tr per 2-ctr)
     2024 +$52, 2025 +$91, 2026 +$21, 2023 -$31 (per 1-unit)

Filter chain (identical to P4 strategy, only exit mechanics differ):
  1. Detect 1m regime flip at flip-bar close T.
  2. State of FLIP bar (open_ts = T - 60s) == target_state? (causal)
  3. Wait for bar1 (1m bar opening at T, closing at T+60s).
  4. At bar1 close, require shape confirmation:
       long  : bar1.high > flip.high AND bar1.close > bar1.open
       short : bar1.low  < flip.low  AND bar1.close < bar1.open
  5. Submit 2-contract market FOK at next 1s after bar1 close.
  6. On entry fill: submit limit for `partial_size` ctrs at
        entry + dir × partial_atr × atr (partial PT, GTC, reduce_only).
  7. (a) Partial fills → arm BE stop (price = entry_px) on the runner.
        (b) BE level touched intra-bar → exit runner market.
        (c) Regime flip → cancel partial (if still open) + exit remaining market.
  8. Max hold 24h safety.

Position size: configurable. Default 2 ctr entry (1 partial + 1 runner).
PnL: per-trade row includes both legs; aggregator computes
     pnl = partial_qty*(partial_px - entry_px)*dir
         + runner_qty*(runner_exit_px - entry_px)*dir
$5 RT commission applied per ctr-roundtrip post-run.
"""
from __future__ import annotations

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

# Reuse TF1m + constants from P4 strategy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from strategy import TF1m, NS_PER_S, MAX_HOLD_NS


class HMMStateFilteredP1Config(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s:   str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    state_lookup_path: str = "studies/regime_classification/results/states_nq_1m.parquet"
    state_col:     str = "hmm_4"
    target_state:  int = 3
    min_state_dur: int = 0
    entry_size:    int = 2          # total ctrs at entry
    partial_atr:   float = 1.0      # partial PT in ATR units
    partial_size:  int = 1          # ctrs to take off at partial
    be_after_partial: bool = True   # arm BE stop on runner after partial fills
    tick_size:     float = 0.25
    entry_anchor:  str = "bar1_confirm"  # bar1_confirm | bar1 | flip

    # 5m macro HMM
    state_lookup_path_5m: str = ""
    state_col_5m:     str = ""
    target_state_5m:  int = -1
    anchor_5m:        str = "bar1"


class HMMStateFilteredP1Strategy(Strategy):

    def __init__(self, config: HMMStateFilteredP1Config):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._tf1m = TF1m()
        self._state_lookup: dict[int, int] = {}
        self._state_5m_lookup: dict[int, int] = {}

        # Pending bar1 confirmation
        self._pending_flip_ts = None
        self._pending_direction = 0
        self._pending_atr = 0.0
        self._pending_flip_h = 0.0
        self._pending_flip_l = 0.0

        # Active trade state
        self._entry_order_id = None
        self._entry_dir = 0
        self._entry_px = None
        self._entry_atr = None
        self._entry_ts = None

        # P1 legs
        self._partial_order_id = None
        self._partial_filled = False
        self._partial_px = None
        self._partial_ts = None
        self._be_armed = False
        self._runner_qty = 0   # ctrs remaining after partial fill (or full size pre-partial)

        # Exit
        self._exit_order_id = None
        self._exit_reason = None

        self.all_trades: list[dict] = []
        self._diag = {
            "1m_closes": 0,
            "flips_detected": 0,
            "flips_in_target_state": 0,
            "bar1_confirmed": 0,
            "entries_filled": 0,
            "partial_filled": 0,
            "exits_be":      0,
            "exits_regime":  0,
            "exits_maxhold": 0,
        }

    def on_start(self):
        self._bar_type = BarType.from_str(self._cfg.bar_type_1s)
        df = pd.read_parquet(self._cfg.state_lookup_path,
                              columns=[self._cfg.state_col])
        ts_ns = df.index.values.astype("int64")
        states = df[self._cfg.state_col].astype("int64").values
        self._state_lookup = dict(zip(ts_ns, states))
        self.log.info(
            f"P1 state lookup loaded: {len(self._state_lookup):,} entries; "
            f"target {self._cfg.state_col}={self._cfg.target_state}; "
            f"entry_size={self._cfg.entry_size} partial={self._cfg.partial_size}@"
            f"{self._cfg.partial_atr}ATR be={self._cfg.be_after_partial}")
        if self._cfg.state_lookup_path_5m:
            df_5m = pd.read_parquet(self._cfg.state_lookup_path_5m,
                                     columns=[self._cfg.state_col_5m])
            ts_ns_5m = df_5m.index.values.astype("int64")
            states_5m = df_5m[self._cfg.state_col_5m].astype("int64").values
            self._state_5m_lookup = dict(zip(ts_ns_5m, states_5m))
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bar_type:
            return
        ts = bar.ts_init
        o, h, l, c, v = (float(bar.open), float(bar.high),
                         float(bar.low),  float(bar.close), float(bar.volume))

        # ── Max-hold guard ──
        if (self._entry_ts is not None
                and ts - self._entry_ts >= MAX_HOLD_NS
                and not self.portfolio.is_flat(self._inst_id)
                and self._exit_order_id is None):
            self._exit_market("max_hold")
            self._diag["exits_maxhold"] += 1

        # ── BE-stop check (intra 1s; after partial filled) ──
        if (self._be_armed
                and self._entry_ts is not None
                and self._entry_dir != 0
                and not self.portfolio.is_flat(self._inst_id)
                and self._exit_order_id is None):
            be_px = self._entry_px
            if (self._entry_dir == 1 and l <= be_px) or (self._entry_dir == -1 and h >= be_px):
                self._exit_market("be_stop")
                self._diag["exits_be"] += 1

        closed = self._tf1m.update(ts, o, h, l, c, v)
        if closed is None:
            return
        tf = self._tf1m
        self._diag["1m_closes"] += 1
        if not tf.warm:
            return

        bar_close_ts = ts

        # ── 1. Resolve pending bar1 check ──
        if self._pending_flip_ts is not None:
            expected_bar1_close = self._pending_flip_ts + 60 * NS_PER_S
            if bar_close_ts == expected_bar1_close:
                if self._cfg.entry_anchor == "bar1_confirm":
                    if self._pending_direction == 1:
                        confirmed = (closed["high"] > self._pending_flip_h
                                      and closed["close"] > closed["open"])
                    else:
                        confirmed = (closed["low"] < self._pending_flip_l
                                      and closed["close"] < closed["open"])
                else:
                    confirmed = True

                if confirmed and self._cfg.state_lookup_path_5m and self._cfg.anchor_5m == "bar1":
                    t_5m_open = (bar_close_ts // (300 * NS_PER_S)) * (300 * NS_PER_S) - (300 * NS_PER_S)
                    state_5m = self._state_5m_lookup.get(t_5m_open, -1)
                    if state_5m != self._cfg.target_state_5m:
                        confirmed = False

                if (confirmed
                        and self.portfolio.is_flat(self._inst_id)
                        and self._entry_order_id is None):
                    self._diag["bar1_confirmed"] += 1
                    side = (OrderSide.BUY if self._pending_direction == 1
                            else OrderSide.SELL)
                    order = self.order_factory.market(
                        instrument_id=self._inst_id, order_side=side,
                        quantity=Quantity.from_int(self._cfg.entry_size),
                        time_in_force=TimeInForce.FOK)
                    self._entry_order_id = order.client_order_id.value
                    self._entry_dir = self._pending_direction
                    self._entry_atr = self._pending_atr
                    self.submit_order(order)
                self._pending_flip_ts = None
                self._pending_direction = 0
            elif bar_close_ts > expected_bar1_close:
                self._pending_flip_ts = None
                self._pending_direction = 0

        # ── 2. Regime exit (any open position) ──
        if (not self.portfolio.is_flat(self._inst_id)
                and self._entry_dir != 0
                and self._exit_order_id is None
                and tf.regime != self._entry_dir
                and tf.regime != 0):
            self._exit_market("regime_flip")
            self._diag["exits_regime"] += 1

        # ── 3. Detect new flip + state filter ──
        if (tf.regime_flipped and tf.regime != 0
                and self.portfolio.is_flat(self._inst_id)
                and self._entry_order_id is None
                and self._pending_flip_ts is None):
            self._diag["flips_detected"] += 1
            flip_bar_open_ts = bar_close_ts - 60 * NS_PER_S
            state = self._state_lookup.get(flip_bar_open_ts, -1)
            if state == self._cfg.target_state:
                state_dur = 0
                curr_ts = flip_bar_open_ts
                while self._state_lookup.get(curr_ts, -1) == self._cfg.target_state:
                    state_dur += 1
                    curr_ts -= 60 * NS_PER_S
                if state_dur >= self._cfg.min_state_dur:
                    pass_5m = True
                    if self._cfg.state_lookup_path_5m and self._cfg.anchor_5m == "flip":
                        t_5m_open = (bar_close_ts // (300 * NS_PER_S)) * (300 * NS_PER_S) - (300 * NS_PER_S)
                        state_5m = self._state_5m_lookup.get(t_5m_open, -1)
                        if state_5m != self._cfg.target_state_5m:
                            pass_5m = False
                    if pass_5m:
                        self._diag["flips_in_target_state"] += 1
                        if self._cfg.entry_anchor == "flip":
                            if (self.portfolio.is_flat(self._inst_id)
                                    and self._entry_order_id is None):
                                side = (OrderSide.BUY if tf.regime == 1
                                        else OrderSide.SELL)
                                order = self.order_factory.market(
                                    instrument_id=self._inst_id, order_side=side,
                                    quantity=Quantity.from_int(self._cfg.entry_size),
                                    time_in_force=TimeInForce.FOK)
                                self._entry_order_id = order.client_order_id.value
                                self._entry_dir = tf.regime
                                self._entry_atr = tf.atr
                                self.submit_order(order)
                        else:
                            self._pending_flip_ts = bar_close_ts
                            self._pending_direction = tf.regime
                            self._pending_atr = tf.atr
                            self._pending_flip_h = closed["high"]
                            self._pending_flip_l = closed["low"]

    def _cancel_partial(self):
        if self._partial_order_id is not None:
            p = self.cache.order(ClientOrderId(self._partial_order_id))
            if p is not None and not p.is_closed:
                self.cancel_order(p)
            self._partial_order_id = None

    def _submit_partial(self):
        if (self._cfg.partial_atr <= 0 or self._cfg.partial_size <= 0
                or self._entry_atr is None or self._entry_atr <= 0):
            return
        raw = self._entry_px + self._entry_dir * self._cfg.partial_atr * self._entry_atr
        tick = self._cfg.tick_size
        partial_px = round(raw / tick) * tick
        side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        order = self.order_factory.limit(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(self._cfg.partial_size),
            price=Price(partial_px, 2),
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        self._partial_order_id = order.client_order_id.value
        self.submit_order(order)

    def _exit_market(self, reason: str):
        self._cancel_partial()
        net = self.portfolio.net_position(self._inst_id)
        qty = abs(int(net))
        if qty == 0:
            return
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(qty),
            time_in_force=TimeInForce.FOK,
            reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason = reason
        self.submit_order(order)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self._entry_px = px
            self._entry_ts = event.ts_event
            self._runner_qty = self._cfg.entry_size
            self._diag["entries_filled"] += 1
            self._submit_partial()
        elif cid == self._partial_order_id:
            self._partial_order_id = None
            self._partial_filled = True
            self._partial_px = px
            self._partial_ts = event.ts_event
            self._runner_qty = self._cfg.entry_size - self._cfg.partial_size
            self._diag["partial_filled"] += 1
            if self._cfg.be_after_partial:
                self._be_armed = True
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            reason = self._exit_reason or "regime_flip"
            self._exit_reason = None
            self._record_trade(px, event.ts_event, reason)

    def _record_trade(self, runner_exit_px, runner_exit_ts, runner_exit_reason):
        partial_qty = self._cfg.partial_size if self._partial_filled else 0
        runner_qty = self._cfg.entry_size - partial_qty
        self.all_trades.append({
            "entry_ts": self._entry_ts,
            "entry_px": self._entry_px,
            "entry_atr": self._entry_atr,
            "signal_direction": self._entry_dir,
            "entry_qty": self._cfg.entry_size,
            "partial_filled": self._partial_filled,
            "partial_px": self._partial_px,
            "partial_ts": self._partial_ts,
            "partial_qty": partial_qty,
            "runner_exit_px": runner_exit_px,
            "runner_exit_ts": runner_exit_ts,
            "runner_qty": runner_qty,
            "runner_exit_reason": runner_exit_reason,
        })
        # Reset
        self._entry_dir = 0
        self._entry_px = self._entry_atr = self._entry_ts = None
        self._partial_filled = False
        self._partial_px = self._partial_ts = None
        self._be_armed = False
        self._runner_qty = 0

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._entry_order_id:
            self._entry_order_id = None
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            self._exit_reason = None
        elif cid == self._partial_order_id:
            self._partial_order_id = None

    def on_order_canceled(self, event):
        self.on_order_rejected(event)

    def on_order_expired(self, event):
        self.on_order_rejected(event)

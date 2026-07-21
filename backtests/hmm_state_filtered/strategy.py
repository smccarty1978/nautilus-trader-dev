"""HMM-state-filtered, bar1-confirmed, regime-exit NT strategy.

Live-style validation of the offline finding:
  bar1_confirm + bar1-close entry + regime-exit + HMM_4 state 3 filter
  → +$37/trade pooled OOS, 3 of 4 OOS years positive.

Filter chain (all causal):
  1. Detect 1m regime flip at flip-bar close T (sticky EMA3/9 on H/L).
  2. State of FLIP bar (open_ts = T - 60s) == target_state? (causal: state
     computed from features ending at T, observable at T from offline lookup).
  3. If yes, wait for bar1 (the 1m bar opening at T, closing at T+60s).
  4. At bar1 close (= T+60s), check bar1 confirmation:
       long  : bar1.high > flip.high AND bar1.close > bar1.open
       short : bar1.low  < flip.low  AND bar1.close < bar1.open
  5. If confirmed → submit market FOK at next 1s open (≈ bar1 close moment).
  6. Hold until next 1m regime flip OUT of entry direction → exit at market.

Position size: 1 contract.
Max hold (safety): 24 hours; force market exit if regime never flips.
PnL: computed offline from entry_px / exit_px ($5 RT commission applied
post-run; 1-tick slippage on exit market orders post-run).

The state lookup table is loaded from a parquet at on_start. Lookup key
= UTC ns of the 1m bar open. The offline computation in
studies/regime_classification/build_features.py used strictly causal
backward-only windows, so state[T-60s] is observable at time T.
"""
from __future__ import annotations

from datetime import time as dtime, timezone, datetime

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

NS_PER_S    = 1_000_000_000
ATR_PERIOD  = 14
ALPHA_EMA3  = 0.5
ALPHA_EMA9  = 0.2
MAX_HOLD_NS = 24 * 3600 * NS_PER_S


def _ema(prev, x, alpha):
    return x if prev is None else alpha * x + (1.0 - alpha) * prev


class TF1m:
    """Incremental 1-minute aggregator + sticky EMA3/9 regime + Wilder ATR-14."""

    def __init__(self):
        self._period = 60 * NS_PER_S
        self._bin = None
        self._o = self._h = self._l = self._c = None
        self._v = 0.0
        self.ema3_h = self.ema9_h = None
        self.ema3_l = self.ema9_l = None
        self.close = None
        self.atr = None
        self.regime = 0
        self.regime_flipped = False
        self._prev_c = None
        self._tr_seed = []

    def update(self, ts, o, h, l, c, v):
        b = (ts // self._period) * self._period
        closed = None
        if self._bin is None:
            self._bin = b
        elif b != self._bin:
            closed = dict(ts_event=self._bin, open=self._o, high=self._h,
                          low=self._l, close=self._c, volume=self._v,
                          ts_close=self._bin + self._period)
            self._fold(closed)
            self._bin = b
            self._o = self._h = self._l = self._c = None
            self._v = 0.0
        if self._o is None:
            self._o, self._h, self._l, self._c = o, h, l, c
        else:
            self._h = max(self._h, h)
            self._l = min(self._l, l)
            self._c = c
        self._v += v
        return closed

    def _fold(self, bk):
        h, l, c = bk["high"], bk["low"], bk["close"]
        tr = (h - l) if self._prev_c is None else max(
            h - l, abs(h - self._prev_c), abs(l - self._prev_c))
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) == ATR_PERIOD:
                self.atr = sum(self._tr_seed) / ATR_PERIOD
        else:
            self.atr = (self.atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        self._prev_c = c
        self.ema3_h = _ema(self.ema3_h, h, ALPHA_EMA3)
        self.ema9_h = _ema(self.ema9_h, h, ALPHA_EMA9)
        self.ema3_l = _ema(self.ema3_l, l, ALPHA_EMA3)
        self.ema9_l = _ema(self.ema9_l, l, ALPHA_EMA9)
        self.close = c
        prev = self.regime
        if c > self.ema3_h and c > self.ema9_h:
            self.regime = 1
        elif c < self.ema3_l and c < self.ema9_l:
            self.regime = -1
        self.regime_flipped = (self.regime != prev and self.regime != 0)

    @property
    def warm(self): return self.atr is not None and self.atr > 0


class HMMStateFilteredConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s:   str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    state_lookup_path: str = "studies/regime_classification/results/states_nq_1m.parquet"
    state_col:     str = "hmm_4"
    target_state:  int = 3        # -1 = bypass state filter (ablation)
    min_state_dur: int = 0       # 0 = no filter; matches P4 NT-validation cohort
    pt_atr:        float = 2.0   # 0 = no PT (baseline); >0 = limit PT at entry + dir × pt_atr × atr
    sl_atr:        float = 0.0   # 0 = no SL (dynamic regime exit only); >0 = stop-market at entry - dir × sl_atr × atr
    tick_size:     float = 0.25  # for PT price rounding (NQ/ES = 0.25)
    entry_anchor:  str = "bar1_confirm"  # bar1_confirm | bar1 | flip
    be_trig_atr:   float = 0.0   # 0 = disabled; >0 = trigger BE stop once peak MFE reaches this * ATR
    be_level_atr:  float = 0.0   # level to move stop to (e.g. -0.25 ATR or 0.0 ATR)
    min_atr:       float = 0.0   # 0 = disabled; >0 = filter out entry signals if ATR < this value
    max_hold_s:    int = 60      # time-exit duration in seconds
    
    # Strategy F configuration
    vwap_exit_active: bool = False
    qty: int = 1
    pt_runner_atr: float = 2.0
    pt_c1_atr: float = 0.50
    vwap_z_threshold: float = 1.0
    features_lookup_path: str = "studies/regime_classification/results/features_nq_1m.parquet"

    # Post-entry gates configuration (Speed Gate + 60s Causal PnL Gate)
    post_entry_gates_active: bool = False
    speed_gate_threshold_s: float = 30.0
    gate_60s_pnl_atr: float = 0.30
    wide_sl_atr: float = 0.0

    # 5m macro HMM configuration
    state_lookup_path_5m: str = ""  # empty = disabled
    state_col_5m:     str = ""
    target_state_5m:  int = -1
    anchor_5m:        str = "bar1"  # "flip" or "bar1"


class HMMStateFilteredStrategy(Strategy):

    def __init__(self, config: HMMStateFilteredConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._tf1m = TF1m()
        self._state_lookup: dict[int, int] = {}

        # Pending bar1-confirmation state
        self._pending_flip_ts = None  # ts_init of flip-bar close
        self._pending_direction = 0
        self._pending_atr = 0.0
        self._pending_flip_h = 0.0
        self._pending_flip_l = 0.0

        # Active position state
        self._entry_order_id = None
        self._entry_dir = 0
        self._entry_px = None
        self._entry_atr = None
        self._entry_ts = None
        self._exit_order_id = None
        self._exit_reason = None        # 'regime' / 'max_hold' for market exits
        self._pt_order_id = None        # limit PT order (P4)
        self._pt1_order_id = None       # limit PT1 order (Strategy F)
        self._pt2_order_id = None       # limit PT2 order (Strategy F)
        self._vwap_evaluated = False
        self._gate_60s_evaluated = False
        self._current_stop_px = None
        
        self._c1_exit_px = None
        self._c1_exit_ts = None
        self._c1_reason = None
        self._c2_exit_px = None
        self._c2_exit_ts = None
        self._c2_reason = None
        
        # Trailing/BE stop state
        self._peak_mfe = 0.0
        self._be_activated = False

        self.all_trades: list[dict] = []
        self._diag = {
            "1m_closes": 0,
            "flips_detected": 0,
            "flips_in_target_state": 0,
            "bar1_confirmed": 0,
            "entries_filled": 0,
            "exits_filled_pt": 0,
            "exits_filled_regime": 0,
            "exits_filled_maxhold": 0,
        }

    def on_start(self):
        self._bar_type = BarType.from_str(self._cfg.bar_type_1s)
        
        # Load 1m state lookup
        df = pd.read_parquet(self._cfg.state_lookup_path,
                              columns=[self._cfg.state_col])
        ts_ns = df.index.values.astype("int64")
        states = df[self._cfg.state_col].astype("int64").values
        self._state_lookup = dict(zip(ts_ns, states))
        self.log.info(
            f"HMM state lookup loaded: {len(self._state_lookup):,} entries; "
            f"target {self._cfg.state_col}={self._cfg.target_state}")
            
        # Load 5m state lookup if provided
        self._state_5m_lookup = {}
        if self._cfg.state_lookup_path_5m:
            df_5m = pd.read_parquet(self._cfg.state_lookup_path_5m,
                                     columns=[self._cfg.state_col_5m])
            ts_ns_5m = df_5m.index.values.astype("int64")
            states_5m = df_5m[self._cfg.state_col_5m].astype("int64").values
            self._state_5m_lookup = dict(zip(ts_ns_5m, states_5m))
            self.log.info(
                f"HMM 5m macro state lookup loaded: {len(self._state_5m_lookup):,} entries; "
                f"target {self._cfg.state_col_5m}={self._cfg.target_state_5m} ({self._cfg.anchor_5m})")
                
        # Load features to get vwap_z_abs causally if vwap_exit_active is True
        self._vwap_lookup = {}
        if self._cfg.vwap_exit_active:
            feat_df = pd.read_parquet(self._cfg.features_lookup_path, columns=["vwap_z_abs"])
            feat_ts = feat_df.index.values.astype("int64")
            vwap_z_vals = feat_df["vwap_z_abs"].values
            self._vwap_lookup = dict(zip(feat_ts, vwap_z_vals))
            self.log.info(f"Loaded VWAP distance lookup: {len(self._vwap_lookup):,} entries.")
            
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bar_type:
            return
        ts = bar.ts_init
        o, h, l, c, v = (float(bar.open), float(bar.high),
                         float(bar.low),  float(bar.close), float(bar.volume))

        # ── Max-hold guard ──
        if (self._entry_ts is not None
                and ts - self._entry_ts >= self._cfg.max_hold_s * NS_PER_S
                and not self.portfolio.is_flat(self._inst_id)
                and self._exit_order_id is None):
            self._exit_market("max_hold")
            self._diag["exits_filled_maxhold"] += 1

        # ── Stop-loss guard (Breathing Room Trailing Stop) ──
        if (self._entry_ts is not None
                and not self.portfolio.is_flat(self._inst_id)
                and self._entry_dir != 0
                and self._exit_order_id is None):
            
            # Update peak MFE
            if self._entry_dir == 1:
                self._peak_mfe = max(self._peak_mfe, h - self._entry_px)
            else:
                self._peak_mfe = max(self._peak_mfe, self._entry_px - l)
                
            # ── VWAP-conditioned exit evaluation (Strategy F) ──
            if (self._cfg.vwap_exit_active
                    and not self._vwap_evaluated):
                if self._peak_mfe >= self._cfg.pt_c1_atr * self._entry_atr:
                    self._vwap_evaluated = True
                    t_closed_open = (ts // 60_000_000_000) * 60_000_000_000 - 60_000_000_000
                    vwap_z = self._vwap_lookup.get(t_closed_open, 1.0)
                    self.log.info(f"VWAP-Exit Check: Peak MFE={self._peak_mfe:.2f} >= target, VWAP z={vwap_z:.4f}")
                    if vwap_z > self._cfg.vwap_z_threshold:
                        self.log.info(f"VWAP Exhaustion detected (z={vwap_z:.2f} > {self._cfg.vwap_z_threshold}). Exiting entire position immediately!")
                        self._exit_market("VWAP_exhaustion")
                        self._diag["exits_filled_vwap_exhaust"] = self._diag.get("exits_filled_vwap_exhaust", 0) + 1
                
            # Check BE trigger
            if (self._cfg.be_trig_atr > 0 
                    and self._peak_mfe >= self._cfg.be_trig_atr * self._entry_atr 
                    and not self._be_activated):
                self._be_activated = True
                self.log.info(f"BE stop activated at peak MFE {self._peak_mfe:.2f}")
                
            # Determine stop price
            if self._be_activated:
                stop_px = self._entry_px + self._entry_dir * self._cfg.be_level_atr * self._entry_atr
            else:
                stop_px = self._current_stop_px
                
            # Check stop hit
            if stop_px is not None:
                if (self._entry_dir == 1 and l <= stop_px) or (self._entry_dir == -1 and h >= stop_px):
                    reason = "BE_stop" if self._be_activated else "stop_loss"
                    self._exit_market(reason)
                    self._diag[f"exits_filled_{reason}"] = self._diag.get(f"exits_filled_{reason}", 0) + 1

            # ── 60s Causal PnL Gate (Speed Gate Strategy) ──
            if (self._cfg.post_entry_gates_active
                    and self._c2_exit_px is None      # runner is still active (trade is active)
                    and not self._gate_60s_evaluated):
                elapsed_s = (ts - self._entry_ts) / NS_PER_S
                if elapsed_s >= 60.0:
                    self._gate_60s_evaluated = True
                    pnl_60s = (c - self._entry_px) * self._entry_dir
                    if pnl_60s < self._cfg.gate_60s_pnl_atr * self._entry_atr:
                        self.log.info(f"60s Causal Gate triggered: PnL {pnl_60s:.2f} < {self._cfg.gate_60s_pnl_atr:.2f} ATR. Exiting remaining contracts at market.")
                        self._exit_market("Gate_60s_exhaustion")
                        self._diag["exits_filled_gate_60s"] = self._diag.get("exits_filled_gate_60s", 0) + 1
                    else:
                        # Widen stop-loss (Strategy G Adaptive Stop Logic)
                        if self._cfg.wide_sl_atr > 0:
                            self._current_stop_px = self._entry_px - self._entry_dir * self._cfg.wide_sl_atr * self._entry_atr
                            self.log.info(f"60s Causal Gate passed: PnL {pnl_60s:.2f} >= {self._cfg.gate_60s_pnl_atr:.2f} ATR. Widening stop-loss to {self._cfg.wide_sl_atr:.2f} ATR (price: {self._current_stop_px:.2f}).")

        closed = self._tf1m.update(ts, o, h, l, c, v)
        if closed is None:
            return  # Not a 1m boundary

        tf = self._tf1m
        self._diag["1m_closes"] += 1
        if not tf.warm:
            return

        bar_close_ts = ts  # ts_init of the 1s bar that triggered the boundary

        # ── 1. Resolve pending bar1 check ──
        if self._pending_flip_ts is not None:
            expected_bar1_close = self._pending_flip_ts + 60 * NS_PER_S
            if bar_close_ts == expected_bar1_close:
                # This is bar1's close. Check confirmation (if required).
                if self._cfg.entry_anchor == "bar1_confirm":
                    if self._pending_direction == 1:
                        confirmed = (closed["high"] > self._pending_flip_h
                                      and closed["close"] > closed["open"])
                    else:
                        confirmed = (closed["low"] < self._pending_flip_l
                                      and closed["close"] < closed["open"])
                else:  # entry_anchor == "bar1": no shape filter, just enter at bar1 close
                    confirmed = True
                
                # Check 5-minute macro state at bar1 close if anchor_5m == "bar1"
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
                        quantity=Quantity.from_int(self._cfg.qty),
                        time_in_force=TimeInForce.FOK)
                    self._entry_order_id = order.client_order_id.value
                    self._entry_dir = self._pending_direction
                    self._entry_atr = self._pending_atr
                    self.submit_order(order)
                # Clear pending regardless (1-shot)
                self._pending_flip_ts = None
                self._pending_direction = 0
            elif bar_close_ts > expected_bar1_close:
                # Missed bar1 (data gap?). Clear.
                self._pending_flip_ts = None
                self._pending_direction = 0

        # ── 2. Regime exit (if in position) ──
        if (not self.portfolio.is_flat(self._inst_id)
                and self._entry_dir != 0
                and self._exit_order_id is None
                and tf.regime != self._entry_dir
                and tf.regime != 0):
            self._exit_market("regime_flip")
            self._diag["exits_filled_regime"] += 1

        # ── 3. Detect new flip + apply state filter ──
        if (tf.regime_flipped and tf.regime != 0
                and self.portfolio.is_flat(self._inst_id)
                and self._entry_order_id is None
                and self._pending_flip_ts is None):
            # Check minimum ATR filter
            if tf.atr < self._cfg.min_atr:
                return
            self._diag["flips_detected"] += 1
            # State of the flip bar (open_ts = bar_close_ts - 60s)
            flip_bar_open_ts = bar_close_ts - 60 * NS_PER_S
            state = self._state_lookup.get(flip_bar_open_ts, -1)
            if self._cfg.target_state == -1 or state == self._cfg.target_state:
                # Count consecutive target state bars ending at flip_bar
                state_dur = 0
                if self._cfg.target_state != -1:
                    curr_ts = flip_bar_open_ts
                    while self._state_lookup.get(curr_ts, -1) == self._cfg.target_state:
                        state_dur += 1
                        curr_ts -= 60 * NS_PER_S

                if state_dur >= self._cfg.min_state_dur:
                    # Check 5-minute macro state at flip moment if anchor_5m == "flip"
                    pass_5m = True
                    if self._cfg.state_lookup_path_5m and self._cfg.anchor_5m == "flip":
                        t_5m_open = (bar_close_ts // (300 * NS_PER_S)) * (300 * NS_PER_S) - (300 * NS_PER_S)
                        state_5m = self._state_5m_lookup.get(t_5m_open, -1)
                        if state_5m != self._cfg.target_state_5m:
                            pass_5m = False
                            
                    if pass_5m:
                        self._diag["flips_in_target_state"] += 1
                        if self._cfg.entry_anchor == "flip":
                            # Raw-flip entry: submit market FOK immediately at flip-bar close.
                            # Fill at next 1s bar (~T+1s).
                            if (self.portfolio.is_flat(self._inst_id)
                                    and self._entry_order_id is None):
                                side = (OrderSide.BUY if tf.regime == 1
                                        else OrderSide.SELL)
                                order = self.order_factory.market(
                                    instrument_id=self._inst_id, order_side=side,
                                    quantity=Quantity.from_int(self._cfg.qty),
                                    time_in_force=TimeInForce.FOK)
                                self._entry_order_id = order.client_order_id.value
                                self._entry_dir = tf.regime
                                self._entry_atr = tf.atr
                                self.submit_order(order)
                        else:
                            # Save pending bar1 context (bar1_confirm or bar1)
                            self._pending_flip_ts = bar_close_ts
                            self._pending_direction = tf.regime
                            self._pending_atr = tf.atr
                            self._pending_flip_h = closed["high"]
                            self._pending_flip_l = closed["low"]

    def _cancel_pt(self):
        """Cancel any active PT limit order."""
        if self._pt_order_id is not None:
            pt = self.cache.order(ClientOrderId(self._pt_order_id))
            if pt is not None and not pt.is_closed:
                self.cancel_order(pt)
            self._pt_order_id = None
            
        if hasattr(self, "_pt1_order_id") and self._pt1_order_id is not None:
            pt1 = self.cache.order(ClientOrderId(self._pt1_order_id))
            if pt1 is not None and not pt1.is_closed:
                self.cancel_order(pt1)
            self._pt1_order_id = None
            
        if hasattr(self, "_pt2_order_id") and self._pt2_order_id is not None:
            pt2 = self.cache.order(ClientOrderId(self._pt2_order_id))
            if pt2 is not None and not pt2.is_closed:
                self.cancel_order(pt2)
            self._pt2_order_id = None

    def _exit_market(self, reason: str):
        # Cancel PT before market exit so we don't double-close
        self._cancel_pt()
        close_side = (OrderSide.SELL if self._entry_dir == 1
                      else OrderSide.BUY)
        net_pos = self.portfolio.net_position(self._inst_id)
        qty = Quantity.from_int(abs(int(net_pos))) if net_pos != 0 else Quantity.from_int(1)
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason = reason
        self.submit_order(order)

    def _submit_pt(self):
        """Submit limit PT at entry + dir × pt_atr × atr."""
        if self._cfg.pt_atr <= 0 or self._entry_atr is None or self._entry_atr <= 0:
            return
        raw_pt = self._entry_px + self._entry_dir * self._cfg.pt_atr * self._entry_atr
        # Round to tick (away from entry to be conservative — but for PT,
        # rounding TO entry would only make it easier to fill; round to nearest)
        tick = self._cfg.tick_size
        pt_price = round(raw_pt / tick) * tick
        pt_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        order = self.order_factory.limit(
            instrument_id=self._inst_id, order_side=pt_side,
            quantity=Quantity.from_int(1),
            price=Price(pt_price, 2),
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        self._pt_order_id = order.client_order_id.value
        self.submit_order(order)

    def _submit_vwap_pt(self):
        """Submit two separate limit PTs for Strategy F (PT1 = +0.50, PT2 = +2.00)."""
        tick = self._cfg.tick_size
        pt1_raw = self._entry_px + self._entry_dir * self._cfg.pt_c1_atr * self._entry_atr
        pt2_raw = self._entry_px + self._entry_dir * self._cfg.pt_runner_atr * self._entry_atr
        
        pt1_price = round(pt1_raw / tick) * tick
        pt2_price = round(pt2_raw / tick) * tick
        pt_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        
        order1 = self.order_factory.limit(
            instrument_id=self._inst_id, order_side=pt_side,
            quantity=Quantity.from_int(1),
            price=Price(pt1_price, 2),
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        self._pt1_order_id = order1.client_order_id.value
        self.submit_order(order1)
        
        order2 = self.order_factory.limit(
            instrument_id=self._inst_id, order_side=pt_side,
            quantity=Quantity.from_int(1),
            price=Price(pt2_price, 2),
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        self._pt2_order_id = order2.client_order_id.value
        self.submit_order(order2)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self._entry_px = px
            self._entry_ts = event.ts_event
            self._diag["entries_filled"] += 1
            
            # Reset exit states
            self._c1_exit_px = None
            self._c1_exit_ts = None
            self._c1_reason = None
            self._c2_exit_px = None
            self._c2_exit_ts = None
            self._c2_reason = None
            
            # Reset trailing stop state
            self._peak_mfe = 0.0
            self._be_activated = False
            self._vwap_evaluated = False
            self._gate_60s_evaluated = False
            
            if self._cfg.sl_atr > 0:
                self._current_stop_px = px - self._entry_dir * self._cfg.sl_atr * self._entry_atr
            else:
                self._current_stop_px = None
            
            # Submit PT immediately after entry fill
            if self._cfg.vwap_exit_active or self._cfg.post_entry_gates_active:
                self._submit_vwap_pt()
            else:
                self._submit_pt()
        elif cid == self._pt_order_id:
            # PT limit hit → position closed at PT price
            self._pt_order_id = None
            self._diag["exits_filled_pt"] += 1
            self._c1_exit_px = px
            self._c1_exit_ts = event.ts_event
            self._c1_reason = "PT"
            self._c2_exit_px = px
            self._c2_exit_ts = event.ts_event
            self._c2_reason = "PT"
            self._check_and_record_trades()
        elif hasattr(self, "_pt1_order_id") and cid == self._pt1_order_id:
            self._pt1_order_id = None
            self._diag["exits_filled_pt1"] = self._diag.get("exits_filled_pt1", 0) + 1
            self._c1_exit_px = px
            self._c1_exit_ts = event.ts_event
            self._c1_reason = "PT1"
            
            # Speed Gate evaluation
            if self._cfg.post_entry_gates_active:
                elapsed_s = (event.ts_event - self._entry_ts) / NS_PER_S
                if elapsed_s < self._cfg.speed_gate_threshold_s:
                    self.log.info(f"Speed Gate triggered: Target reached in {elapsed_s:.2f}s < {self._cfg.speed_gate_threshold_s:.2f}s. Exiting runner immediately at market.")
                    self._exit_market("SpeedGate_exhaustion")
                    self._diag["exits_filled_speed_gate"] = self._diag.get("exits_filled_speed_gate", 0) + 1
            
            self._check_and_record_trades()
        elif hasattr(self, "_pt2_order_id") and cid == self._pt2_order_id:
            self._pt2_order_id = None
            self._diag["exits_filled_pt2"] = self._diag.get("exits_filled_pt2", 0) + 1
            self._c2_exit_px = px
            self._c2_exit_ts = event.ts_event
            self._c2_reason = "PT2"
            self._check_and_record_trades()
        elif cid == self._exit_order_id:
            # Regime exit or max-hold market fill
            self._exit_order_id = None
            reason = self._exit_reason or "regime"
            self._exit_reason = None
            
            # Market exit closes all remaining size
            if self._c1_exit_px is None:
                self._c1_exit_px = px
                self._c1_exit_ts = event.ts_event
                self._c1_reason = reason
            if self._c2_exit_px is None:
                self._c2_exit_px = px
                self._c2_exit_ts = event.ts_event
                self._c2_reason = reason
                
            self._check_and_record_trades()
 
    def _check_and_record_trades(self):
        if self._c1_exit_px is not None and self._c2_exit_px is not None:
            # Always append the c1 leg.
            self.all_trades.append({
                "entry_ts": self._entry_ts,
                "entry_px": self._entry_px,
                "entry_atr": self._entry_atr,
                "signal_direction": self._entry_dir,
                "exit_ts": self._c1_exit_ts,
                "exit_px": self._c1_exit_px,
                "exit_reason": self._c1_reason,
            })
            # Append the c2 leg ONLY if it represents a genuinely distinct
            # second contract (different fill px/ts/reason). In single-contract
            # mode (qty=1, no PT1/PT2 split) c1 and c2 mirror each other, so
            # appending both produces a 2x duplicate; this guard preserves the
            # 2-contract architecture while eliminating that artifact.
            c2_distinct = (
                self._c1_exit_px != self._c2_exit_px
                or self._c1_exit_ts != self._c2_exit_ts
                or self._c1_reason != self._c2_reason
            )
            if c2_distinct:
                self.all_trades.append({
                    "entry_ts": self._entry_ts,
                    "entry_px": self._entry_px,
                    "entry_atr": self._entry_atr,
                    "signal_direction": self._entry_dir,
                    "exit_ts": self._c2_exit_ts,
                    "exit_px": self._c2_exit_px,
                    "exit_reason": self._c2_reason,
                })
            
            self._entry_dir = 0
            self._entry_px = None
            self._entry_atr = None
            self._entry_ts = None
            self._peak_mfe = 0.0
            self._be_activated = False
            self._vwap_evaluated = False
            self._gate_60s_evaluated = False
            self._current_stop_px = None
            
            self._c1_exit_px = None
            self._c1_exit_ts = None
            self._c1_reason = None
            self._c2_exit_px = None
            self._c2_exit_ts = None
            self._c2_reason = None

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._entry_order_id:
            self._entry_order_id = None
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            self._exit_reason = None
        elif cid == self._pt_order_id:
            self._pt_order_id = None

    def on_order_canceled(self, event):
        self.on_order_rejected(event)

    def on_order_expired(self, event):
        self.on_order_rejected(event)

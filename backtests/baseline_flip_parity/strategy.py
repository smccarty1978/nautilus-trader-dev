"""Baseline flip parity — every 1m regime flip, +1/-1 ATR bracket or Stall-State protection.

Purpose: validate the 61% base win rate from the Python scanner (v2 collector
flips + 1s first-touch unbounded race) against the NT event-driven engine.
Now extended to support the Stall-State Moving Average protection stop logic.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators import AverageTrueRange


NS_PER_S    = 1_000_000_000
NQ_MULT     = 20.0
COMM_RT     = 5.0
ATR_PERIOD  = 14
ALPHA_EMA3  = 0.5
ALPHA_EMA9  = 0.2
MAX_HOLD_NS = 4 * 3600 * NS_PER_S


def _tick_round(val: float) -> float:
    return round(val * 4) / 4.0


# ==================================================================
# Local indicators to match the collector exactly
# ==================================================================

class LocalEMA:
    """Exponential moving average on raw scalar input."""

    __slots__ = ("period", "alpha", "value", "count", "initialized")

    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.count = 0
        self.initialized = False

    def update(self, v: float) -> None:
        self.count += 1
        if self.count == 1:
            self.value = v
        else:
            self.value = self.alpha * v + (1 - self.alpha) * self.value
        if self.count >= self.period:
            self.initialized = True


class RegimeState:
    """EMA3/9 sticky regime on H/L/C.

    Regime is +1 when close > both emaH_3 AND emaH_9.
    Regime is -1 when close < both emaL_3 AND emaL_9.
    Else: sticky (unchanged from prior).
    """

    __slots__ = (
        "emaH_3", "emaH_9", "emaL_3", "emaL_9", "ema3", "ema9",
        "regime", "bars_in_regime", "completed_bars",
    )

    def __init__(self):
        self.emaH_3 = LocalEMA(3)
        self.emaH_9 = LocalEMA(9)
        self.emaL_3 = LocalEMA(3)
        self.emaL_9 = LocalEMA(9)
        self.ema3 = LocalEMA(3)
        self.ema9 = LocalEMA(9)
        self.regime = 0
        self.bars_in_regime = 0
        self.completed_bars = 0

    def update(self, h: float, l: float, c: float) -> int:
        self.emaH_3.update(h)
        self.emaH_9.update(h)
        self.emaL_3.update(l)
        self.emaL_9.update(l)
        self.ema3.update(c)
        self.ema9.update(c)
        self.completed_bars += 1

        if not (self.emaH_3.initialized and self.emaH_9.initialized
                and self.emaL_3.initialized and self.emaL_9.initialized):
            return self.regime

        new_r = self.regime
        if c > self.emaH_3.value and c > self.emaH_9.value:
            new_r = 1
        elif c < self.emaL_3.value and c < self.emaL_9.value:
            new_r = -1

        if new_r != self.regime:
            self.regime = new_r
            self.bars_in_regime = 1
        else:
            self.bars_in_regime += 1
        return self.regime


# ==================================================================
# Strategy Config
# ==================================================================

class BaselineFlipParityConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s:   str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m:   str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    year: int = 2025
    entry_qty: int = 1
    use_stall_protection: bool = False
    gate_atr: float = 0.5
    stall_thresh: int = 3
    ma_period: int = 9
    ma_type: str = "SMA"  # "SMA" or "EMA"
    trade_side: str = "both"  # "both", "long", or "short"
    entry_type: str = "flip"  # "flip" or "random"
    entry_prob: float = 0.040  # probability of random entry when flat
    sl_atr: float = 1.0
    tp_atr: float = 1.0
    use_trailing_stop: bool = False
    trail_distance_atr: float = 0.25
    be_trigger_atr: float = 0.25
    be_level_atr: float = 0.25



class BaselineFlipParityStrategy(Strategy):

    def __init__(self, config: BaselineFlipParityConfig):
        super().__init__(config)
        self._cfg     = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        
        # Core Indicators
        self._regime_state = RegimeState()
        self._atr_14 = AverageTrueRange(14)
        
        # State & Trades
        self._pending_entry = None
        # entry_qty > 1 is submitted as separate 1-lot FOK legs rather than one
        # multi-lot FOK order: NT's bar-execution matching engine synthesizes
        # only a 1-lot top-of-book per tick, so a single FOK order for qty>1
        # gets entirely canceled (not partially filled) whenever the synthetic
        # book can't cover the full size at once — see _pending_entry_ids path.
        self._pending_entry_ids = None
        self._pending_entry_fill_qty = 0
        self._pending_entry_notional = 0.0
        self._entry_side    = None  # OrderSide of entry
        self._entry_dir     = 0     # +1 long, -1 short
        self._entry_px      = None
        self._entry_atr     = None
        self._entry_ts      = None
        self._sl_id  = None
        self._t_id   = None
        self._remaining_qty = 0
        self._exit_order_id = None
        self._exit_reason = None
        # entry_qty > 1 positions can close via more than one fill (either a
        # multi-lot full-exit split into 1-lot legs like entries, or a GTC
        # bracket order that itself partially fills under thin per-tick
        # synthetic liquidity — see _accumulate_exit_leg/_finalize_exit).
        self._exit_order_ids = None
        self._exit_legs: list[tuple[int, float]] = []
        self._partial_exit_order_id = None
        self._partial_exit_reason = None
        self.all_trades: list[dict] = []
        
        # Pending bar1-confirmation state
        self._pending_flip_ts = None
        self._pending_direction = 0
        self._pending_atr = 0.0
        self._pending_flip_h = 0.0
        self._pending_flip_l = 0.0
        self._pending_cat_stop = None
        
        # Bracket order prices (kept for resubmission at reduced qty after a partial exit)
        self._sl_px = None
        self._t_px = None

        # Stall protection state
        self._cat_stop = None
        self._active_stop = None
        self._milestone_reached = False
        self._running_mfe = 0.0
        self._stall_count = 0
        self._closes_1m = deque()
        self._prev_high = None
        self._prev_low = None
        self._ema_close = None
        
        self._1m_count = 0
        self._last_bar1m_high = None
        self._last_bar1m_low = None

        # Seeded random number generator
        import random
        self._rng = random.Random(42 + config.year)
        self._prev_open = None
        self._last_open = None
        
        self._diag = {
            "1m_closes": 0,
            "gate_not_warm": 0,
            "gate_not_flipped": 0,
            "gate_busy": 0,
            "long_signals": 0,
            "short_signals": 0,
        }

    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def _entry_pending(self) -> bool:
        return self._pending_entry is not None or bool(self._pending_entry_ids)

    def _submit_entry_orders(self, order_side: OrderSide):
        """Submit the entry for `self._cfg.entry_qty` contracts.

        For entry_qty == 1, submits a single FOK market order (unchanged legacy
        path, tracked via the `_pending_entry` scalar). For entry_qty > 1,
        submits `entry_qty` separate 1-lot FOK orders instead of one multi-lot
        FOK order: NT's bar-execution matching engine only synthesizes a 1-lot
        top-of-book per tick, so a single FOK order for qty>1 is entirely
        canceled (not partially filled) whenever the synthetic book can't cover
        the full size at once — this was silently discarding ~2/3 of B4 entries.
        Legs are tracked via `_pending_entry_ids` and reconciled in
        `on_order_filled`/`on_order_rejected`/`on_order_canceled`/`on_order_expired`.
        """
        if self._cfg.entry_qty <= 1:
            order = self.order_factory.market(
                instrument_id=self._inst_id,
                order_side=order_side,
                quantity=Quantity.from_int(1),
                time_in_force=TimeInForce.FOK,
            )
            self._pending_entry = order.client_order_id.value
            self.submit_order(order)
        else:
            self._pending_entry_ids = set()
            self._pending_entry_fill_qty = 0
            self._pending_entry_notional = 0.0
            for _ in range(self._cfg.entry_qty):
                leg = self.order_factory.market(
                    instrument_id=self._inst_id,
                    order_side=order_side,
                    quantity=Quantity.from_int(1),
                    time_in_force=TimeInForce.FOK,
                )
                self._pending_entry_ids.add(leg.client_order_id.value)
                self.submit_order(leg)

    def _finalize_entry(self, px_avg: float):
        """Called once all entry legs have resolved with a non-zero fill.

        Arms the SL/target (or stall-protection stop) brackets sized to
        `self._remaining_qty`, which must already be set by the caller.
        """
        self._entry_px = px_avg
        atr = self._entry_atr
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        self._exit_legs = []

        if self._cfg.use_stall_protection:
            self._cat_stop = self._pending_cat_stop
            self._active_stop = self._cat_stop
            self._milestone_reached = True if self._cfg.gate_atr == 0.0 else False
            self._running_mfe = 0.0
            self._stall_count = 0

            # Initialize comparison high/low to Bar1's high/low
            self._prev_high = self._last_bar1m_high
            self._prev_low = self._last_bar1m_low

            # Apply order safety capping to prevent immediate fills
            if self._entry_dir == 1:
                self._active_stop = _tick_round(min(self._active_stop, px_avg - 0.25))
            else:
                self._active_stop = _tick_round(max(self._active_stop, px_avg + 0.25))
            sl_px = self._active_stop
            self._sl_px = sl_px
            self._t_px = None

            sl_ord = self.order_factory.stop_market(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(self._remaining_qty),
                trigger_price=Price(sl_px, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._sl_id = sl_ord.client_order_id.value
            self.submit_order(sl_ord)
        else:
            sl_dist = self._cfg.sl_atr * atr
            tp_dist = self._cfg.tp_atr * atr
            if self._entry_dir == 1:
                t_px  = _tick_round(px_avg + tp_dist)
                sl_px = _tick_round(px_avg - sl_dist)
            else:
                t_px  = _tick_round(px_avg - tp_dist)
                sl_px = _tick_round(px_avg + sl_dist)

            if self._cfg.use_trailing_stop:
                if self._entry_dir == 1:
                    sl_px = _tick_round(min(sl_px, px_avg - 0.25))
                else:
                    sl_px = _tick_round(max(sl_px, px_avg + 0.25))
                self._active_stop = sl_px
                self._running_mfe = 0.0

            self._sl_px = sl_px
            self._t_px = t_px

            sl_ord = self.order_factory.stop_market(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(self._remaining_qty),
                trigger_price=Price(sl_px, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._sl_id = sl_ord.client_order_id.value
            self.submit_order(sl_ord)

            t_ord = self.order_factory.limit(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(self._remaining_qty),
                price=Price(t_px, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._t_id = t_ord.client_order_id.value
            self.submit_order(t_ord)

    def on_bar(self, bar: Bar):
        # 1-second bar handling (for excursion tracking, stops, and hold times)
        if bar.bar_type == self._bt_1s:
            ts = bar.ts_event # Use ts_event to prevent 1s shift skew
            h = float(bar.high)
            l = float(bar.low)

            # Check max hold timer
            if (self._entry_ts is not None
                    and ts - self._entry_ts >= MAX_HOLD_NS
                    and not self.portfolio.is_flat(self._inst_id)):
                self._exit_all_market("max_hold")
                return

            # Track running_mfe if in position and using stall protection or trailing stop
            if self._entry_px is not None:
                if self._cfg.use_stall_protection or self._cfg.use_trailing_stop:
                    if self._entry_dir == 1:
                        mfe_bar = (h - self._entry_px) / self._entry_atr
                    else:
                        mfe_bar = (self._entry_px - l) / self._entry_atr
                    self._running_mfe = max(self._running_mfe, mfe_bar)

                if self._cfg.use_stall_protection and self._running_mfe >= self._cfg.gate_atr:
                    self._milestone_reached = True

                if self._cfg.use_trailing_stop:
                    potential_stop = self._active_stop
                    c = float(bar.close)

                    # 1. Break-even check
                    if self._cfg.be_trigger_atr > 0.0 and self._running_mfe >= self._cfg.be_trigger_atr:
                        be_stop_dist = self._cfg.be_level_atr * self._entry_atr
                        if self._entry_dir == 1:
                            potential_stop = max(potential_stop, self._entry_px + be_stop_dist)
                        else:
                            potential_stop = min(potential_stop, self._entry_px - be_stop_dist)

                    # 2. Trailing stop check
                    if self._cfg.trail_distance_atr > 0.0 and self._running_mfe >= self._cfg.trail_distance_atr:
                        trail_stop_dist = (self._running_mfe - self._cfg.trail_distance_atr) * self._entry_atr
                        if self._entry_dir == 1:
                            potential_stop = max(potential_stop, self._entry_px + trail_stop_dist)
                        else:
                            potential_stop = min(potential_stop, self._entry_px - trail_stop_dist)

                    # Round to ticks
                    new_stop = _tick_round(potential_stop)

                    # Apply stop modification if moved in favor
                    if self._entry_dir == 1:
                        if new_stop > self._active_stop:
                            self._active_stop = new_stop
                            self._update_stop_order(new_stop, c)
                    else:
                        if new_stop < self._active_stop:
                            self._active_stop = new_stop
                            self._update_stop_order(new_stop, c)


        # 1-minute bar handling (for indicators, regime flips, and entry/exit signals)
        elif bar.bar_type == self._bt_1m:
            ts = bar.ts_event # Use ts_event (start of 1m bar)
            o = float(bar.open)
            h = float(bar.high)
            l = float(bar.low)
            c = float(bar.close)

            self._prev_open = self._last_open
            self._last_open = o

            self._1m_count += 1
            self._diag["1m_closes"] += 1
            self._last_bar1m_high = h
            self._last_bar1m_low = l

            # Continuous background updates for stop moving averages
            self._closes_1m.append(c)
            if len(self._closes_1m) > self._cfg.ma_period:
                self._closes_1m.popleft()
                
            if self._ema_close is None:
                self._ema_close = c
            else:
                alpha = 2.0 / (self._cfg.ma_period + 1)
                self._ema_close = alpha * c + (1.0 - alpha) * self._ema_close

            # Update indicators
            self._atr_14.update_raw(h, l, c)
            prev_regime = self._regime_state.regime
            new_regime = self._regime_state.update(h, l, c)
            
            # regime_flipped matches the collector's flip_occurred:
            regime_flipped = (prev_regime != 0 and new_regime != 0 and prev_regime != new_regime)

            # 1. Resolve pending bar1 check (if this bar is Bar1 for a flip)
            if self._pending_flip_ts is not None:
                expected_bar1_start = self._pending_flip_ts + 60 * NS_PER_S
                if ts == expected_bar1_start:
                    if self._pending_direction == 1:
                        confirmed = (h > self._pending_flip_h) # Correct: high break only
                    else:
                        confirmed = (l < self._pending_flip_l) # Correct: low break only
                                      
                    if confirmed and self.portfolio.is_flat(self._inst_id) and not self._entry_pending():
                        self._entry_dir = self._pending_direction
                        self._entry_side = OrderSide.BUY if self._entry_dir == 1 else OrderSide.SELL
                        self._entry_atr = self._pending_atr
                        self._entry_ts = bar.ts_init  # Close of Bar1

                        if self._entry_dir == 1:
                            self._diag["long_signals"] += 1
                        else:
                            self._diag["short_signals"] += 1

                        self._submit_entry_orders(self._entry_side)

                    self._pending_flip_ts = None
                    self._pending_direction = 0
                elif ts > expected_bar1_start:
                    self._pending_flip_ts = None
                    self._pending_direction = 0

            # 2. Check for new entry signal (regime flip or random) if flat
            if (self.portfolio.is_flat(self._inst_id)
                    and not self._entry_pending()):
                
                # Warmup gate (collector uses 150-bar warmup)
                if self._1m_count < 150:
                    self._diag["gate_not_warm"] += 1
                else:
                    # Enforce target year start trading gate and check that ATR is valid (> 0.0)
                    target_start_ns = int(datetime(self._cfg.year, 1, 1, tzinfo=timezone.utc).timestamp() * NS_PER_S)
                    if ts >= target_start_ns and self._atr_14.value > 0.0:
                        if self._cfg.entry_type == "random":
                            if self._rng.random() < self._cfg.entry_prob:
                                if self._cfg.trade_side == "long":
                                    self._entry_dir = 1
                                    self._entry_side = OrderSide.BUY
                                    self._diag["long_signals"] += 1
                                elif self._cfg.trade_side == "short":
                                    self._entry_dir = -1
                                    self._entry_side = OrderSide.SELL
                                    self._diag["short_signals"] += 1
                                else:
                                    # Default to long if both/not specified
                                    self._entry_dir = 1
                                    self._entry_side = OrderSide.BUY
                                    self._diag["long_signals"] += 1
                                
                                self._entry_atr = self._atr_14.value
                                self._entry_ts = bar.ts_init
                                
                                # Set catastrophic stop
                                # For longs: max(prev_open, entry - 1.0 * atr)
                                # For shorts: min(prev_open, entry + 1.0 * atr)
                                if self._entry_dir == 1:
                                    base_stop = self._prev_open if self._prev_open is not None else (c - self._entry_atr)
                                    self._pending_cat_stop = max(base_stop, c - self._entry_atr)
                                else:
                                    base_stop = self._prev_open if self._prev_open is not None else (c + self._entry_atr)
                                    self._pending_cat_stop = min(base_stop, c + self._entry_atr)
                                    
                                self._submit_entry_orders(self._entry_side)
                        else:  # "flip"
                            if self._pending_flip_ts is None:
                                if not regime_flipped:
                                    self._diag["gate_not_flipped"] += 1
                                else:
                                    # Check trade_side filter
                                    if (self._cfg.trade_side == "long" and new_regime != 1) or \
                                       (self._cfg.trade_side == "short" and new_regime != -1):
                                        self._diag["gate_not_flipped"] += 1
                                    else:
                                        # Save pending flip details
                                        self._pending_flip_ts = ts
                                        self._pending_direction = new_regime
                                        self._pending_atr = self._atr_14.value
                                        self._pending_flip_h = h
                                        self._pending_flip_l = l
                                        self._pending_cat_stop = o  # Flip-bar open price

            # 3. Check for exits if in position
            elif not self.portfolio.is_flat(self._inst_id) and self._cfg.use_stall_protection:
                # Opposite regime exit
                if new_regime == -self._entry_dir:
                    self._exit_all_market("regime_exit")
                else:
                    # Stall protection stop ratcheting
                    if self._milestone_reached:
                        if self._prev_high is not None and self._prev_low is not None:
                            if self._entry_dir == 1:
                                if h <= self._prev_high:
                                    self._stall_count += 1
                                else:
                                    self._stall_count = 0
                            else:
                                if l >= self._prev_low:
                                    self._stall_count += 1
                                else:
                                    self._stall_count = 0
                                    
                            if self._stall_count >= self._cfg.stall_thresh:
                                if self._cfg.ma_type == "SMA":
                                    ma_val = sum(self._closes_1m) / len(self._closes_1m)
                                else: # EMA Close
                                    ma_val = self._ema_close
                                    
                                if self._entry_dir == 1:
                                    new_stop = _tick_round(max(self._active_stop, ma_val))
                                else:
                                    new_stop = _tick_round(min(self._active_stop, ma_val))
                                    
                                if new_stop != self._active_stop:
                                    self._active_stop = new_stop
                                    self._update_stop_order(new_stop, c)
                                    
                        self._prev_high = h
                        self._prev_low = l

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px  = float(event.last_px)

        if cid == self._pending_entry:
            self._pending_entry = None
            self._remaining_qty = self._cfg.entry_qty
            self._finalize_entry(px)

        elif self._pending_entry_ids and cid in self._pending_entry_ids:
            fill_qty = int(event.last_qty)
            self._pending_entry_ids.discard(cid)
            self._pending_entry_fill_qty += fill_qty
            self._pending_entry_notional += fill_qty * px
            if not self._pending_entry_ids:
                # All legs resolved. If at least one leg filled, finalize the
                # entry with whatever quantity actually filled (may be less
                # than entry_qty if a leg was itself FOK-killed) — see
                # on_order_rejected/canceled/expired for the zero-fill case.
                if self._pending_entry_fill_qty > 0:
                    avg_px = self._pending_entry_notional / self._pending_entry_fill_qty
                    self._remaining_qty = self._pending_entry_fill_qty
                    self._finalize_entry(avg_px)
                self._pending_entry_fill_qty = 0
                self._pending_entry_notional = 0.0

        elif cid == self._t_id:
            # GTC bracket orders sized >1 lot can partially fill under thin
            # per-tick synthetic liquidity — a fill event here does NOT
            # necessarily mean the whole order (and position) closed.
            self._accumulate_exit_leg(int(event.last_qty), px)
            order = self.cache.order(ClientOrderId(cid))
            if order is None or order.is_closed:
                self._t_id = None
            if self._remaining_qty <= 0:
                self._finalize_exit("T", event.ts_event)
            else:
                self._resize_sibling_bracket()

        elif cid == self._sl_id:
            self._accumulate_exit_leg(int(event.last_qty), px)
            order = self.cache.order(ClientOrderId(cid))
            if order is None or order.is_closed:
                self._sl_id = None
            if self._remaining_qty <= 0:
                self._finalize_exit("SL", event.ts_event)
            else:
                self._resize_sibling_bracket()

        elif cid == self._exit_order_id:
            self._exit_order_id = None
            reason = self._exit_reason
            self._exit_reason = None
            self._accumulate_exit_leg(int(event.last_qty), px)
            if self._remaining_qty <= 0:
                self._finalize_exit(reason, event.ts_event)
            else:
                # FOK never partially fills, so this only happens if _remaining_qty
                # was already >1 when this leg was requested (shouldn't occur via
                # the qty==1 scalar path) — re-arm protection defensively.
                self._resize_sibling_bracket()

        elif self._exit_order_ids and cid in self._exit_order_ids:
            self._exit_order_ids.discard(cid)
            self._accumulate_exit_leg(int(event.last_qty), px)
            if not self._exit_order_ids:
                reason = self._exit_reason
                self._exit_reason = None
                if self._remaining_qty <= 0:
                    self._finalize_exit(reason, event.ts_event)
                else:
                    # Some legs of the multi-lot full-exit attempt were
                    # themselves FOK-killed by thin liquidity; re-arm brackets
                    # for whatever quantity remains rather than leaving it
                    # unprotected.
                    self._resize_sibling_bracket()

        elif cid == self._partial_exit_order_id:
            self._partial_exit_order_id = None
            self._partial_exit_reason = None
            self._accumulate_exit_leg(int(event.last_qty), px)
            if self._remaining_qty <= 0:
                self._finalize_exit("W4_partial_then_flat", event.ts_event)
            else:
                self._resize_sibling_bracket()

    def _update_stop_order(self, new_stop: float, current_close: float):
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        
        # Check if new stop price is already crossed (stopped out) causally
        if (self._entry_dir == 1 and new_stop >= current_close) or \
           (self._entry_dir == -1 and new_stop <= current_close):
            self.log.info(f"Stop level {new_stop:.2f} already crossed by close {current_close:.2f}. Exiting market.")
            self._exit_all_market("SL")
            return

        if self._sl_id:
            sl_order = self.cache.order(ClientOrderId(self._sl_id))
            if sl_order is not None and not sl_order.is_closed:
                self.cancel_order(sl_order)
            self._sl_id = None
            
        sl_ord = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(self._remaining_qty),
            trigger_price=Price(new_stop, 2),
            time_in_force=TimeInForce.GTC, reduce_only=True)
        self._sl_id = sl_ord.client_order_id.value
        self._sl_px = new_stop
        self.submit_order(sl_ord)
        self.log.info(f"Ratcheted stop migrated to {new_stop:.2f}")

    def _resolve_entry_leg_failure(self, cid: str) -> bool:
        """Handle a reject/cancel/expiry of one leg of a multi-leg entry.

        Returns True if `cid` belonged to `_pending_entry_ids`. Once every leg
        has resolved (filled or failed), finalizes the entry with whatever
        quantity actually filled — which may be zero (no position opened at
        all) if every leg failed.
        """
        if not (self._pending_entry_ids and cid in self._pending_entry_ids):
            return False
        self._pending_entry_ids.discard(cid)
        if not self._pending_entry_ids:
            if self._pending_entry_fill_qty > 0:
                avg_px = self._pending_entry_notional / self._pending_entry_fill_qty
                self._remaining_qty = self._pending_entry_fill_qty
                self._finalize_entry(avg_px)
            self._pending_entry_fill_qty = 0
            self._pending_entry_notional = 0.0
        return True

    def _resolve_exit_leg_failure(self, cid: str, ts_event: int) -> bool:
        """Handle a reject/cancel/expiry of one leg of a multi-lot full exit
        (see `_exit_order_ids` in `_exit_all_market`). Returns True if `cid`
        belonged to that set. If some legs failed but others already filled,
        re-arms brackets for whatever quantity remains rather than leaving it
        unprotected.
        """
        if not (self._exit_order_ids and cid in self._exit_order_ids):
            return False
        self._exit_order_ids.discard(cid)
        if not self._exit_order_ids:
            reason = self._exit_reason
            self._exit_reason = None
            if self._remaining_qty <= 0:
                if self._exit_legs:
                    self._finalize_exit(reason, ts_event)
            else:
                self._resize_sibling_bracket()
        return True

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
        elif self._resolve_entry_leg_failure(cid):
            pass
        elif self._resolve_exit_leg_failure(cid, event.ts_event):
            pass
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            self._exit_reason = None
        elif cid == self._partial_exit_order_id:
            self._partial_exit_order_id = None
            self._partial_exit_reason = None

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
        elif self._resolve_entry_leg_failure(cid):
            pass
        elif self._resolve_exit_leg_failure(cid, event.ts_event):
            pass
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            self._exit_reason = None
        elif cid == self._partial_exit_order_id:
            self._partial_exit_order_id = None
            self._partial_exit_reason = None

    def on_order_expired(self, event):
        cid = event.client_order_id.value
        if cid == self._pending_entry:
            self._pending_entry = None
        elif self._resolve_entry_leg_failure(cid):
            pass
        elif self._resolve_exit_leg_failure(cid, event.ts_event):
            pass
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            self._exit_reason = None
        elif cid == self._partial_exit_order_id:
            self._partial_exit_order_id = None
            self._partial_exit_reason = None

    def _accumulate_exit_leg(self, qty: int, px: float):
        self._exit_legs.append((qty, px))
        self._remaining_qty -= qty

    def _resize_sibling_bracket(self):
        """Re-arm whichever of the SL/target brackets are still tracked
        (non-None) at the new, smaller `self._remaining_qty` — called after a
        partial fill on one leg (the other bracket's original quantity is now
        stale) or after a multi-lot exit attempt where only some legs filled.
        Brackets already closed/cleared by the caller are left alone.
        """
        if self._remaining_qty <= 0:
            return
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        if self._sl_id is not None and self._sl_px is not None:
            sl_order = self.cache.order(ClientOrderId(self._sl_id))
            if sl_order is not None and not sl_order.is_closed:
                self.cancel_order(sl_order)
            sl_ord = self.order_factory.stop_market(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(self._remaining_qty),
                trigger_price=Price(self._sl_px, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._sl_id = sl_ord.client_order_id.value
            self.submit_order(sl_ord)
        if self._t_id is not None and self._t_px is not None:
            t_order = self.cache.order(ClientOrderId(self._t_id))
            if t_order is not None and not t_order.is_closed:
                self.cancel_order(t_order)
            t_ord = self.order_factory.limit(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(self._remaining_qty),
                price=Price(self._t_px, 2),
                time_in_force=TimeInForce.GTC, reduce_only=True)
            self._t_id = t_ord.client_order_id.value
            self.submit_order(t_ord)

    def _finalize_exit(self, reason: str, exit_ts: int):
        """Called once `self._remaining_qty` has reached 0 across every
        accumulated exit leg (T/SL/exit_order/partial_exit fills). Cancels
        any still-open bracket/exit orders defensively, then records the
        trade using the blended (volume-weighted) exit price/PnL.
        """
        for oid_attr in ("_sl_id", "_t_id", "_exit_order_id", "_partial_exit_order_id"):
            oid = getattr(self, oid_attr)
            if oid:
                o = self.cache.order(ClientOrderId(oid))
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
                setattr(self, oid_attr, None)
        self._exit_order_ids = None
        self._record_trade(reason, exit_ts)

    def _exit_all_market(self, reason: str):
        # Guard against clobbering an exit already in flight: a second call
        # while one is unresolved would strand the first attempt's tracking.
        if self._exit_order_id is not None or self._exit_order_ids or self._partial_exit_order_id is not None:
            return
        qty = self._remaining_qty
        if qty <= 0:
            return
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        self._exit_reason = reason
        if qty == 1:
            order = self.order_factory.market(
                instrument_id=self._inst_id, order_side=close_side,
                quantity=Quantity.from_int(1),
                time_in_force=TimeInForce.FOK, reduce_only=True)
            self._exit_order_id = order.client_order_id.value
            self.submit_order(order)
        else:
            # Submit as separate 1-lot FOK legs rather than one multi-lot FOK
            # order: NT's bar-execution matching engine only synthesizes a
            # 1-lot top-of-book per tick, so a single FOK order for qty>1 can
            # be entirely canceled instead of partially filled (see
            # _submit_entry_orders for the same fix applied to entries).
            self._exit_order_ids = set()
            for _ in range(qty):
                leg = self.order_factory.market(
                    instrument_id=self._inst_id, order_side=close_side,
                    quantity=Quantity.from_int(1),
                    time_in_force=TimeInForce.FOK, reduce_only=True)
                self._exit_order_ids.add(leg.client_order_id.value)
                self.submit_order(leg)
        for oid_attr in ("_sl_id", "_t_id"):
            oid = getattr(self, oid_attr)
            if oid:
                o = self.cache.order(ClientOrderId(oid))
                if o is not None and not o.is_closed:
                    self.cancel_order(o)
                setattr(self, oid_attr, None)

    def _exit_partial_market(self, qty: int, reason: str):
        """Reduce the open position by `qty` contracts, leaving the remainder open.

        Only valid while 0 < qty < self._remaining_qty. Cancels the existing
        SL/target brackets on fill and resubmits them sized to the remaining
        quantity (see the `_partial_exit_order_id` branch in `on_order_filled`).
        """
        if qty <= 0 or qty >= self._remaining_qty:
            return
        # Guard against clobbering an exit already in flight (see _exit_all_market).
        if self._exit_order_id is not None or self._exit_order_ids or self._partial_exit_order_id is not None:
            return
        close_side = OrderSide.SELL if self._entry_dir == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=close_side,
            quantity=Quantity.from_int(qty),
            time_in_force=TimeInForce.FOK, reduce_only=True)
        self._partial_exit_order_id = order.client_order_id.value
        self._partial_exit_reason = reason
        self.submit_order(order)

    def _record_trade(self, reason: str, exit_ts: int):
        # Blend every accumulated exit leg (T/SL/exit_order/partial_exit fills)
        # into a single volume-weighted exit price/PnL for the trade. For the
        # common 1-lot, single-fill case this is just that one leg.
        total_qty = sum(q for q, _ in self._exit_legs)
        notional = sum(q * p for q, p in self._exit_legs)
        blended_exit_px = notional / total_qty
        pnl_pts = (blended_exit_px - self._entry_px) * self._entry_dir
        pnl_atr = pnl_pts / self._entry_atr

        self.all_trades.append({
            "entry_ts":  self._entry_ts,
            "entry_px":  self._entry_px,
            "entry_atr": self._entry_atr,
            "signal_direction": self._entry_dir,
            "exit_ts":   exit_ts,
            "exit_px":   blended_exit_px,
            "exit_reason": reason,
            "exit_pnl_pts": pnl_pts,
            "exit_pnl_atr": pnl_atr,
        })
        self._entry_px  = None
        self._entry_atr = None
        self._entry_ts  = None
        self._entry_dir = 0
        self._prev_high = None
        self._prev_low = None
        self._milestone_reached = False
        self._running_mfe = 0.0
        self._stall_count = 0
        self._remaining_qty = 0
        self._exit_legs = []
        self._sl_px = None
        self._t_px = None

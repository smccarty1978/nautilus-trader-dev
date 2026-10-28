"""
Production Strategy: Noise Band V2 Strategy
Location: strategies/noise_band_v2_strategy.py

Audited Enhanced V2 Hybrid Intraday Noise Band + Volume Profile Strategy for NautilusTrader.
Based on Zarattini, Aziz & Barbon (2024) Intraday Noise Area Momentum and Prior-Day RTH Volume Profile.

Key Architectural & Microstructure Rules:
1. Frozen Baseline (Zarattini, Aziz & Barbon 2024):
   - 14-day rolling time-of-day volatility cone (sigma_tod) anchored to max/min(RTH_Open, Prev_RTH_Close).
   - band_multiplier: 1.0 (frozen).
2. Prior-Day Volume Profile Room-to-Run Filter (Audited Arm E2):
   - Evaluated strictly on day d-1 RTH bars (09:30:00 to 16:00:00 ET, 2.0 pt bins, 70% Value Area).
   - Long allowed if Close > Prev_VAH or (Close < Prev_VAL and Prev_POC - Close >= 1.5 * ATR_15m).
   - Short allowed if Close < Prev_VAL or (Close > Prev_VAH and Close - Prev_POC >= 1.5 * ATR_15m).
   - Prev_POC profit-taking disabled (take_profit_at_poc = False) to allow runners full trend capture.
3. Microstructure Pre-Sampling Execution Window:
   - Subscribes to 1-SECOND bars.
   - Evaluates signals and executes at t - 1s (:29:59 and :59:59 ET) or pre-sample window
     beating the institutional :00/:30 half-hour queue spike and adverse selection.
4. Midday Entry Blackout Filter:
   - Suppresses opening new positions at 11:59 and 13:59 ET (lunch lull/chop elimination).
   - Trailing stop exits remain active across all checkpoints.
5. Configurable Stop Cadence & Dual-Tier Protection:
   - stop_check_interval_minutes: 30 (default), 15, or 5.
   - hard_stop_atr_mult: 1.0 (continuous 1m catastrophe stop at 1.0 * ATR_15m beyond trailing band).
6. Volatility-Targeted MNQ Sizing (Zarattini Section 3.3):
   - Dynamically scales position size inversely to 10:00 ET expected noise width.
7. Hard EOD Flatten:
   - Closes all positions at 15:59:55 ET.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import time as dt_time
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

TIME_0930 = dt_time(9, 30, 0)
TIME_1600 = dt_time(16, 0, 0)
TIME_0959 = dt_time(9, 59, 0)
TIME_1530 = dt_time(15, 30, 0)
TIME_1559_55 = dt_time(15, 59, 55)


# =============================================================================
# STRATEGY STATE MACHINE
# =============================================================================

class StrategyState(Enum):
    FLAT = auto()
    LONG = auto()
    SHORT = auto()


# =============================================================================
# PRE-COMPUTED DAILY CONTEXT (STRICT ZERO-LOOKAHEAD CONTRACT)
# =============================================================================

@dataclass
class DailyContext:
    """
    Daily context prepared strictly from day d-1 close and past 14 trading days.
    Provides O(1) lookups inside Strategy.on_bar() without runtime aggregations.
    """
    date_str: str
    rth_open: float
    prev_rth_close: float
    prev_poc: float
    prev_vah: float
    prev_val: float
    anchor_high: float
    anchor_low: float
    # minute_of_rth (0..390) -> sigma_tod in points (strictly .shift(1).rolling(14).mean())
    sigma_tod: Dict[int, float] = field(default_factory=dict)
    noise_pts_10am: float = 50.0

    def get_bands(self, minute_idx: int, band_mult: float = 1.0) -> Tuple[float, float]:
        """Returns (UpperBand, LowerBand) for the given minute index in O(1)."""
        sigma = self.sigma_tod.get(minute_idx, self.noise_pts_10am)
        upper = self.anchor_high + band_mult * sigma
        lower = self.anchor_low - band_mult * sigma
        return upper, lower

    def calculate_contracts(
        self,
        risk_budget_usd: float = 400.0,
        point_value: float = 2.0,
        min_contracts: int = 1,
        max_contracts: int = 20,
    ) -> int:
        """Computes volatility-targeted contracts based on 10:00 ET noise."""
        noise = max(10.0, self.noise_pts_10am)
        dollar_noise_unit = noise * point_value
        raw_qty = round(risk_budget_usd / dollar_noise_unit)
        return int(np.clip(raw_qty, min_contracts, max_contracts))


# =============================================================================
# STRATEGY CONFIGURATION
# =============================================================================

class NoiseBandV2Config(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"

    # Core parameters (FROZEN per Zarattini et al. 2024 & Audited V2)
    lookback_days: int = 14
    band_mult: float = 1.0
    vp_bin_size: float = 2.0
    vp_va_threshold: float = 0.70
    vp_atr_clearance: float = 1.5

    # Position sizing
    sizing_mode: str = "volatility_targeted_mnq"  # "volatility_targeted_mnq" or "fixed"
    risk_budget_usd: float = 400.0  # Scalable to 1000.0 for 1-NQ equivalent
    point_value: float = 2.0  # $2.00 for MNQ, $20.00 for NQ
    fixed_qty: int = 1
    min_contracts: int = 1
    max_contracts: int = 20

    # Stop Cadence & Dual-Tier Protection
    stop_check_interval_minutes: int = 30  # 30 (Baseline), 15, or 5
    hard_stop_atr_mult: float = 1.0  # 1.0 = continuous catastrophe hard stop at 1.0 * ATR_15m (0.0 to disable)
    stop_check_second: int = 59  # Exact second to evaluate discrete stops (59 = :59s)

    # Timing & Execution
    lead_time_seconds: int = 1  # 1 to 3 seconds (fires at second 59, 58, or 57)
    checkpoint_lead_seconds: Tuple[int, ...] = (57, 58, 59)
    blackout_entries: Tuple[str, ...] = ("11:59", "13:59")
    checkpoint_stops_only: bool = True  # True = check trailing stop at cadence marks; False = continuous 1m
    take_profit_at_poc: bool = False
    eod_flatten_time_str: str = "15:59:55"


# =============================================================================
# NAUTILUS TRADER STRATEGY CLASS
# =============================================================================

class NoiseBandV2Strategy(Strategy):
    """
    Production-grade NautilusTrader strategy implementing the Audited Enhanced V2
    Hybrid Intraday Noise Band + Volume Profile strategy on 1s/1m futures data.
    """

    def __init__(
        self,
        config: NoiseBandV2Config,
        daily_contexts: Optional[Dict[str, DailyContext]] = None,
    ):
        super().__init__(config)
        self.cfg = config
        self.daily_contexts = daily_contexts or {}

        self.inst_id = InstrumentId.from_str(config.instrument_id)
        self.bt_1s = BarType.from_str(config.bar_type_1s)
        self.bt_1m = BarType.from_str(config.bar_type_1m)

        # State machine
        self.strat_state: StrategyState = StrategyState.FLAT
        self.current_context: Optional[DailyContext] = None
        self.current_date_str: Optional[str] = None
        self.active_contracts: int = 1

        # Intraday VWAP state (resets daily at 09:30 ET, accumulated on 1m completed bars)
        self.cum_vol: float = 0.0
        self.cum_vol_price: float = 0.0
        self.vwap: float = 0.0

        # Rolling 1m bar buffer for ATR_15m estimation
        self.recent_1m_bars: List[Dict[str, float]] = []

        # Position tracking
        self.entry_price: float = 0.0
        self.entry_time: Optional[pd.Timestamp] = None
        self.entry_direction: int = 0
        self.is_case_b: bool = False
        self.prev_poc_target: float = 0.0

        # Checkpoint execution locks
        self.last_fired_checkpoint_minute: Optional[int] = None
        self.trade_log: List[Dict[str, Any]] = []

    def on_start(self):
        super().on_start()
        self.subscribe_bars(self.bt_1s)
        self.subscribe_bars(self.bt_1m)
        self.log.info(f"Subscribed to {self.bt_1s} and {self.bt_1m}")

    def on_bar(self, bar: Bar):
        dt = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC").tz_convert("America/New_York")
        date_str = str(dt.date())

        # Daily context rotation
        if date_str != self.current_date_str:
            self._handle_new_session(date_str)

        # Maintain 1m bar buffer and update canonical 1m VWAP
        if bar.bar_type == self.bt_1m:
            self._process_1m_bar(bar, dt)

        # Process 1-second bar for execution
        elif bar.bar_type == self.bt_1s:
            self._process_1s_bar(bar, dt)

    def _handle_new_session(self, date_str: str):
        """Resets intraday states and loads precomputed daily context."""
        self.current_date_str = date_str
        self.current_context = self.daily_contexts.get(date_str)
        self.cum_vol = 0.0
        self.cum_vol_price = 0.0
        self.vwap = 0.0
        self.recent_1m_bars.clear()
        self.strat_state = StrategyState.FLAT
        self.last_fired_checkpoint_minute = None

        if self.current_context is not None:
            if self.cfg.sizing_mode == "volatility_targeted_mnq":
                self.active_contracts = self.current_context.calculate_contracts(
                    risk_budget_usd=self.cfg.risk_budget_usd,
                    point_value=self.cfg.point_value,
                    min_contracts=self.cfg.min_contracts,
                    max_contracts=self.cfg.max_contracts,
                )
            else:
                self.active_contracts = self.cfg.fixed_qty
            self.log.info(f"Session {date_str} loaded. Active Contracts = {self.active_contracts}")
        else:
            self.active_contracts = self.cfg.fixed_qty
            self.log.warning(f"No DailyContext for {date_str}. Fallback to {self.active_contracts} contracts.")

    def _process_1m_bar(self, bar: Bar, dt: pd.Timestamp):
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)
        self.recent_1m_bars.append({"open": o, "high": h, "low": l, "close": c, "vol": v})
        if len(self.recent_1m_bars) > 60:
            self.recent_1m_bars.pop(0)

        # Canonical 1m VWAP accumulation matching reference dataset
        t_val = dt.time()
        if TIME_0930 <= t_val <= TIME_1600:
            typical_p = (h + l + c) / 3.0
            self.cum_vol += v
            self.cum_vol_price += typical_p * v
            if self.cum_vol > 0:
                self.vwap = self.cum_vol_price / self.cum_vol

    def _calculate_atr_15m(self) -> float:
        """Calculates 15m ATR from rolling 1m bars."""
        if len(self.recent_1m_bars) < 14:
            return 15.0
        trs = []
        for i in range(1, len(self.recent_1m_bars)):
            b = self.recent_1m_bars[i]
            prev_c = self.recent_1m_bars[i - 1]["close"]
            tr = max(b["high"] - b["low"], abs(b["high"] - prev_c), abs(b["low"] - prev_c))
            trs.append(tr)
        atr_1m = float(np.mean(trs[-14:]))
        return max(10.0, atr_1m * math.sqrt(15.0))

    def _process_1s_bar(self, bar: Bar, dt: pd.Timestamp):
        t_val = dt.time()
        close_p = float(bar.close)
        high_p = float(bar.high)
        low_p = float(bar.low)

        # 1. Hard EOD Flatten at 15:59:55 ET
        if dt.hour == 15 and dt.minute == 59 and dt.second >= 55:
            if self.strat_state in (StrategyState.LONG, StrategyState.SHORT):
                self._flatten_position("EOD_Flat", close_p, dt)
            return

        if self.current_context is None:
            return

        minute_idx = min(390, max(0, int((dt.hour * 60 + dt.minute) - (9 * 60 + 30))))
        upper, lower = self.current_context.get_bands(minute_idx, self.cfg.band_mult)
        atr_15m = self._calculate_atr_15m()

        # 2. Dynamic Trailing Stop Exit Evaluation
        if self.strat_state in (StrategyState.LONG, StrategyState.SHORT):
            # 2A. Dual-Tier Continuous Catastrophe Hard Stop Check
            if self.cfg.hard_stop_atr_mult > 0.0:
                if self.strat_state == StrategyState.LONG:
                    hard_stop = max(upper, self.vwap) - self.cfg.hard_stop_atr_mult * atr_15m
                    if close_p < hard_stop:
                        self._flatten_position("CatastropheHardStop", close_p, dt)
                        return
                elif self.strat_state == StrategyState.SHORT:
                    hard_stop = min(lower, self.vwap) + self.cfg.hard_stop_atr_mult * atr_15m
                    if close_p > hard_stop:
                        self._flatten_position("CatastropheHardStop", close_p, dt)
                        return

            # 2B. Configurable Cadence Trailing Stop Check
            interval = self.cfg.stop_check_interval_minutes
            if interval == 30:
                is_stop_minute = dt.minute in (29, 59)
            elif interval == 15:
                is_stop_minute = dt.minute in (14, 29, 44, 59)
            elif interval == 5:
                is_stop_minute = (dt.minute % 5 == 4)
            else:
                is_stop_minute = True

            is_stop_second = (dt.second == self.cfg.stop_check_second)

            should_check_stop = (is_stop_minute and is_stop_second) if self.cfg.checkpoint_stops_only else True
            if should_check_stop:
                if self.strat_state == StrategyState.LONG:
                    stop_lvl = max(upper, self.vwap)
                    if close_p < stop_lvl:
                        self._flatten_position("TrailingStop", close_p, dt)
                        return
                elif self.strat_state == StrategyState.SHORT:
                    stop_lvl = min(lower, self.vwap)
                    if close_p > stop_lvl:
                        self._flatten_position("TrailingStop", close_p, dt)
                        return

        # 3. Checkpoint Entry Evaluation (FLAT state, strictly at half-hour marks)
        is_chk_entry_minute = dt.minute in (29, 59)
        is_chk_entry_second = dt.second in self.cfg.checkpoint_lead_seconds
        in_rth_window = TIME_0959 <= t_val <= TIME_1530

        if self.strat_state == StrategyState.FLAT and is_chk_entry_minute and is_chk_entry_second and in_rth_window:
            chk_key = dt.hour * 60 + dt.minute
            if self.last_fired_checkpoint_minute == chk_key:
                return

            tod_str = dt.strftime("%H:%M")
            if tod_str in self.cfg.blackout_entries:
                return

            prev_poc = self.current_context.prev_poc
            prev_vah = self.current_context.prev_vah
            prev_val = self.current_context.prev_val

            # Long Breakout Check
            if close_p > upper and close_p > self.vwap:
                is_case_a = (close_p > prev_vah)
                is_case_b = (close_p < prev_val and (prev_poc - close_p >= self.cfg.vp_atr_clearance * atr_15m))
                if is_case_a or is_case_b:
                    self.is_case_b = is_case_b
                    self.prev_poc_target = prev_poc
                    self.last_fired_checkpoint_minute = chk_key
                    self._enter_market(OrderSide.BUY, close_p, dt)

            # Short Breakout Check
            elif close_p < lower and close_p < self.vwap:
                is_case_a = (close_p < prev_val)
                is_case_b = (close_p > prev_vah and (close_p - prev_poc >= self.cfg.vp_atr_clearance * atr_15m))
                if is_case_a or is_case_b:
                    self.is_case_b = is_case_b
                    self.prev_poc_target = prev_poc
                    self.last_fired_checkpoint_minute = chk_key
                    self._enter_market(OrderSide.SELL, close_p, dt)

    def _enter_market(self, side: OrderSide, current_price: float, dt: pd.Timestamp):
        qty = Quantity.from_int(self.active_contracts)
        order = self.order_factory.market(
            instrument_id=self.inst_id,
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self.strat_state = StrategyState.LONG if side == OrderSide.BUY else StrategyState.SHORT
        self.entry_price = current_price
        self.entry_time = dt
        self.entry_direction = 1 if side == OrderSide.BUY else -1
        self.log.info(f"Market Entry {side} {qty} @ {current_price:.2f} at {dt}")

    def _flatten_position(self, reason: str, exit_price: float, dt: pd.Timestamp):
        self.cancel_all_orders(self.inst_id)
        self.close_all_positions(self.inst_id)

        gross_pts = (exit_price - self.entry_price) * self.entry_direction
        slip_side = 0.25
        comm_rt = 4.50 / 20.0
        net_pts = gross_pts - (2 * slip_side + comm_rt)

        self.trade_log.append({
            "entry_time": self.entry_time,
            "exit_time": dt,
            "direction": self.entry_direction,
            "contracts": self.active_contracts,
            "entry_price": self.entry_price,
            "exit_price": exit_price,
            "gross_pts": gross_pts,
            "net_pts": net_pts,
            "exit_reason": reason,
            "is_case_b": self.is_case_b,
        })

        self.strat_state = StrategyState.FLAT
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_direction = 0
        self.is_case_b = False
        self.log.info(f"Flattened ({reason}): {exit_price:.2f}, Net: {net_pts:.2f} pt at {dt}")

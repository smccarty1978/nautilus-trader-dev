"""
Unified Production Strategy: Enhanced V2 Trend Following + VP-Rejected Fade Companion
Location: strategies/enhanced_v2_and_vp_fade_strategy.py

Combines:
- Pillar 1: Enhanced V2 30-Minute Checkpoint Trend Following
  (Noise Band breach + VWAP alignment + Volume Profile room-to-run clearance +
   E_0 <= 65pt ceiling + Two-Stage Stop: 40pt initial stop & 30m dynamic BandStop)
- Pillar 2: VP-Rejected Fade Mean-Reversion Companion
  (Continuous 1-minute breaches rejected by Prior-Day Volume Profile clearance,
   faded with a 15-minute time stop, 35pt hard catastrophe stop, and 5pt magnet band re-entry).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy


class EnhancedV2AndVPFadeNQConfig(StrategyConfig, frozen=True):
    symbol: str = "MNQ"
    initial_capital: float = 1000.0
    point_value: float = 2.0
    tick_size: float = 0.25
    round_trip_commission: float = 1.30

    # Position Sizing
    trend_size: int = 1
    fade_size: int = 1

    # Pillar 1 (Trend V2) ATR-Calibrated Parameters
    trend_atr_stop_mult: float = 1.0       # Dynamic 1.0x ATR_15m catastrophe stop on 1m close
    trend_ceiling_pts: float = 65.0        # Anti-chasing boundary for initial extension E_0

    # Pillar 2 (VP Fade) ATR-Calibrated Parameters
    fade_sl_atr_mult: float = 0.50         # 0.5x ATR_15m dynamic stop loss
    fade_tp_atr_mult: float = 0.25         # 0.25x ATR_15m dynamic high-probability take profit target
    fade_time_stop_mins: int = 15          # Maximum 15-bar hold for fade rotation

    # Instrument Mapping
    instrument_id: str = "MNQ.XCME"
    bar_type: str = "MNQ.XCME-1MIN-BAR-LAST"
    stop_eval_on_close: bool = True


class EnhancedV2AndVPFadeConfig(StrategyConfig, frozen=True):
    """Configuration tuned for NQ (E-mini Nasdaq-100) and MNQ futures."""
    instrument_id: str = "NQ.XCME"
    bar_type: str = "NQ.XCME-1MIN-BAR-LAST"
    trend_size: int = 1  # Number of MNQ/NQ contracts for Trend V2
    fade_size: int = 1  # Number of MNQ/NQ contracts for VP Fade Companion
    initial_stop_pts: float = 40.0  # Trend V2 initial hard stop (pts)
    ext_ceiling_pts: float = 65.0  # Trend V2 extension ceiling (pts)
    fade_stop_pts: float = 35.0  # VP Fade hard catastrophe stop (pts)
    fade_time_stop_mins: int = 15  # VP Fade time stop (minutes)
    fade_band_offset_pts: float = 5.0  # VP Fade target offset inside band (pts)
    stop_eval_on_close: bool = True  # True: evaluate 40pt stop on 1m close; False: evaluate intra-bar


class EnhancedV2AndVPFadeESConfig(StrategyConfig, frozen=True):
    """
    Strategy configuration for Enhanced V2 Trend + VP Fade Companion
    tuned specifically for ES (E-mini S&P 500) and MES (Micro E-mini S&P 500) futures.
    """
    instrument_id: str = "ES.CME"  # Or "MES.CME" for Micro E-minis
    bar_type: str = "ES.CME-1MIN-BAR-LAST"

    # Position Sizing
    trend_size: int = 1  # Number of contracts for Pillar 1 (Trend V2)
    fade_size: int = 1  # Number of contracts for Pillar 2 (VP Fade Companion)

    # ES-Scaled Volatility Parameters (approx. 3.25x - 3.5x reduction from NQ)
    initial_stop_pts: float = 12.0      # Two-stage 1-min catastrophe stop on close (ES scaled from 40.0)
    trend_ceiling_pts: float = 20.0     # Anti-chasing extension ceiling E_0 (ES scaled from 65.0)
    fade_stop_pts: float = 10.0         # Hard catastrophe stop for VP-rejected fades (ES scaled from 35.0)
    fade_band_offset_pts: float = 1.5   # Magnet re-entry target offset inside Noise Band (ES scaled from 5.0)
    fade_time_stop_mins: int = 15       # Time stop duration for stalled fade trades
    stop_eval_on_close: bool = True     # True: evaluate stop on 1m close; False: evaluate intra-bar


class EnhancedV2AndVPFadeStrategy(Strategy):
    """
    Unified Trading Strategy combining:
    - Pillar 1: Enhanced V2 30-Minute Checkpoint Trend Following
    - Pillar 2: VP-Rejected Fade Mean-Reversion Companion
    """

    def __init__(
        self,
        config: EnhancedV2AndVPFadeConfig | EnhancedV2AndVPFadeESConfig | EnhancedV2AndVPFadeNQConfig,
    ) -> None:
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(getattr(config, "instrument_id", "MNQ.XCME"))
        self.bar_type = getattr(config, "bar_type", f"{self.instrument_id}-1MIN-BAR-LAST")

        # Sizing & Risk Parameters
        self.trend_size = getattr(config, "trend_size", 1)
        self.fade_size = getattr(config, "fade_size", 1)
        self.trend_atr_stop_mult = getattr(config, "trend_atr_stop_mult", None)
        self.initial_stop_pts = getattr(config, "initial_stop_pts", 40.0)
        self.ext_ceiling_pts = getattr(config, "trend_ceiling_pts", getattr(config, "ext_ceiling_pts", 65.0))
        
        self.fade_sl_atr_mult = getattr(config, "fade_sl_atr_mult", None)
        self.fade_tp_atr_mult = getattr(config, "fade_tp_atr_mult", None)
        self.fade_stop_pts = getattr(config, "fade_stop_pts", 35.0)
        self.fade_time_stop_mins = getattr(config, "fade_time_stop_mins", 15)
        self.fade_band_offset_pts = getattr(config, "fade_band_offset_pts", 5.0)
        self.stop_eval_on_close = getattr(config, "stop_eval_on_close", True)

        # Strategy State Tracking - Pillar 1 (Trend V2)
        self.trend_position_side: PositionSide = PositionSide.FLAT
        self.trend_entry_price: float = 0.0
        self.trend_cur_stop_pts: float = self.initial_stop_pts

        # Strategy State Tracking - Pillar 2 (VP Fade)
        self.fade_position_side: PositionSide = PositionSide.FLAT
        self.fade_entry_price: float = 0.0
        self.fade_cur_sl_pts: float = self.fade_stop_pts
        self.fade_cur_tp_pts: Optional[float] = None
        self.fade_bars_held: int = 0
        self.needs_cone_reset_long: bool = False
        self.needs_cone_reset_short: bool = False

        # Intraday state
        self.current_date = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.instrument_id} not found in cache.")
            self.stop()
            return
        self.subscribe_bars(self.bar_type)
        self.log.info("EnhancedV2AndVPFadeStrategy started successfully.")

    def on_bar(self, bar: Bar) -> None:
        close = float(bar.close)
        high = float(bar.high)
        low = float(bar.low)
        ts = bar.ts_event

        # Extract Custom Attributes (or fallback attributes)
        upper_band = getattr(bar, "upper_band", None)
        lower_band = getattr(bar, "lower_band", None)
        vwap = getattr(bar, "vwap", None)
        atr_15m = getattr(bar, "atr_15m", 15.0)
        prev_poc = getattr(bar, "prev_poc", None)
        prev_vah = getattr(bar, "prev_vah", None)
        prev_val = getattr(bar, "prev_val", None)

        if None in (upper_band, lower_band, vwap, prev_poc, prev_vah, prev_val):
            return  # Missing indicator data

        # Timestamp in ET (New York)
        dt = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/New_York")
        minute = dt.minute
        hour = dt.hour
        time_val = hour * 60 + minute

        # Reset daily state on date change
        current_dt = dt.date()
        if self.current_date != current_dt:
            self.current_date = current_dt
            self.needs_cone_reset_long = False
            self.needs_cone_reset_short = False

        # Update cone reset status for fades if price is inside cone
        if lower_band <= close <= upper_band:
            self.needs_cone_reset_long = False
            self.needs_cone_reset_short = False

        # =====================================================================
        # PILLAR 1: ENHANCED V2 30-MINUTE CHECKPOINT TREND MODEL
        # =====================================================================
        is_30m_checkpoint = minute in (29, 59)

        # 1A. Manage Trend V2 Exits (Two-Stage Stop)
        if self.trend_position_side != PositionSide.FLAT:
            if self.trend_position_side == PositionSide.LONG:
                sl_level = self.trend_entry_price - self.trend_cur_stop_pts
                hit_initial_sl = (close < sl_level) if self.stop_eval_on_close else (low <= sl_level)
                if hit_initial_sl:
                    self._close_trend_position(f"Trend Stop Loss Triggered ({self.trend_cur_stop_pts:.1f}pt)")
                elif is_30m_checkpoint and close < max(upper_band, vwap):
                    self._close_trend_position("Trend Dynamic Band Trail Exit (30m)")

            elif self.trend_position_side == PositionSide.SHORT:
                sl_level = self.trend_entry_price + self.trend_cur_stop_pts
                hit_initial_sl = (close > sl_level) if self.stop_eval_on_close else (high >= sl_level)
                if hit_initial_sl:
                    self._close_trend_position(f"Trend Stop Loss Triggered ({self.trend_cur_stop_pts:.1f}pt)")
                elif is_30m_checkpoint and close > min(lower_band, vwap):
                    self._close_trend_position("Trend Dynamic Band Trail Exit (30m)")

        # 1B. Evaluate Trend V2 Entries (at 30m Checkpoint)
        elif self.trend_position_side == PositionSide.FLAT and is_30m_checkpoint:
            # Skip midday blackout windows (11:59 and 13:59 ET)
            is_blackout = (hour == 11 and minute == 59) or (hour == 13 and minute == 59)
            in_trend_window = (9 * 60 + 59 <= time_val <= 15 * 60 + 29)

            if in_trend_window and not is_blackout:
                is_long_breach = (close > upper_band) and (close > vwap)
                is_short_breach = (close < lower_band) and (close < vwap)

                if is_long_breach or is_short_breach:
                    # Gate 2: Prior-Day VP Clearance
                    pass_vp = False
                    if is_long_breach:
                        pass_vp = (close > prev_vah) or (
                            close < prev_val and (prev_poc - close >= 1.5 * atr_15m)
                        )
                    else:
                        pass_vp = (close < prev_val) or (
                            close > prev_vah and (close - prev_poc >= 1.5 * atr_15m)
                        )

                    if pass_vp:
                        # Gate 3: Extension Ceiling (E_0 <= 65 pts)
                        band_stop_0 = max(upper_band, vwap) if is_long_breach else min(lower_band, vwap)
                        e_0_pts = abs(close - band_stop_0)

                        if e_0_pts <= self.ext_ceiling_pts:
                            side = OrderSide.BUY if is_long_breach else OrderSide.SELL
                            qty = Quantity.from_int(self.trend_size)
                            order = self.order_factory.market(
                                instrument_id=self.instrument_id,
                                order_side=side,
                                quantity=qty,
                            )
                            self.submit_order(order)
                            self.trend_position_side = PositionSide.LONG if is_long_breach else PositionSide.SHORT
                            self.trend_entry_price = close
                            self.trend_cur_stop_pts = (
                                (self.trend_atr_stop_mult * atr_15m)
                                if self.trend_atr_stop_mult is not None
                                else self.initial_stop_pts
                            )
                            self.log.info(
                                f"Trend V2 Entry [{self.trend_position_side}] at {close:.2f}, E0={e_0_pts:.1f}pt, SL={self.trend_cur_stop_pts:.1f}pt"
                            )

        # =====================================================================
        # PILLAR 2: VP-REJECTED FADE MEAN-REVERSION COMPANION
        # =====================================================================
        # 2A. Manage VP Fade Exits
        if self.fade_position_side != PositionSide.FLAT:
            self.fade_bars_held += 1

            if self.fade_position_side == PositionSide.LONG:
                # 1. Stop Loss (ATR dynamic or fixed pts)
                if low <= self.fade_entry_price - self.fade_cur_sl_pts:
                    self._close_fade_position(f"Fade Hard Stop Loss (-{self.fade_cur_sl_pts:.1f}pt)")
                # 2. Take Profit (ATR dynamic target or magnet band)
                elif self.fade_cur_tp_pts is not None and high >= self.fade_entry_price + self.fade_cur_tp_pts:
                    self._close_fade_position(f"Fade Dynamic TP (+{self.fade_cur_tp_pts:.1f}pt)")
                elif self.fade_cur_tp_pts is None and close >= lower_band + self.fade_band_offset_pts:
                    self._close_fade_position("Fade Magnet Band Re-Entry Target")
                # 3. Time Stop (15 minutes exhaustion)
                elif self.fade_bars_held >= self.fade_time_stop_mins:
                    self._close_fade_position("Fade Time Stop (15m Exhaustion)")

            elif self.fade_position_side == PositionSide.SHORT:
                # 1. Stop Loss (ATR dynamic or fixed pts)
                if high >= self.fade_entry_price + self.fade_cur_sl_pts:
                    self._close_fade_position(f"Fade Hard Stop Loss (-{self.fade_cur_sl_pts:.1f}pt)")
                # 2. Take Profit (ATR dynamic target or magnet band)
                elif self.fade_cur_tp_pts is not None and low <= self.fade_entry_price - self.fade_cur_tp_pts:
                    self._close_fade_position(f"Fade Dynamic TP (+{self.fade_cur_tp_pts:.1f}pt)")
                elif self.fade_cur_tp_pts is None and close <= upper_band - self.fade_band_offset_pts:
                    self._close_fade_position("Fade Magnet Band Re-Entry Target")
                # 3. Time Stop (15 minutes exhaustion)
                elif self.fade_bars_held >= self.fade_time_stop_mins:
                    self._close_fade_position("Fade Time Stop (15m Exhaustion)")

        # 2B. Evaluate VP Fade Entries (Continuous 1-minute)
        elif self.fade_position_side == PositionSide.FLAT and (9 * 60 + 31 <= time_val <= 15 * 60 + 29):
            is_upside_breach = (close > upper_band) and (close > vwap)
            is_downside_breach = (close < lower_band) and (close < vwap)

            if is_upside_breach or is_downside_breach:
                # Check cone debounce
                skip_fade = False
                if is_upside_breach and self.needs_cone_reset_long:
                    skip_fade = True
                elif is_downside_breach and self.needs_cone_reset_short:
                    skip_fade = True

                if not skip_fade:
                    # Check Prior-Day VP Clearance
                    pass_vp = False
                    if is_upside_breach:
                        pass_vp = (close > prev_vah) or (
                            close < prev_val and (prev_poc - close >= 1.5 * atr_15m)
                        )
                    else:
                        pass_vp = (close < prev_val) or (
                            close > prev_vah and (close - prev_poc >= 1.5 * atr_15m)
                        )

                    # If REJECTED by VP Clearance -> Trigger Fade Entry
                    if not pass_vp:
                        fade_side = OrderSide.SELL if is_upside_breach else OrderSide.BUY
                        qty = Quantity.from_int(self.fade_size)
                        order = self.order_factory.market(
                            instrument_id=self.instrument_id,
                            order_side=fade_side,
                            quantity=qty,
                        )
                        self.submit_order(order)
                        self.fade_position_side = PositionSide.SHORT if is_upside_breach else PositionSide.LONG
                        self.fade_entry_price = close
                        self.fade_bars_held = 0
                        self.fade_cur_sl_pts = (
                            (self.fade_sl_atr_mult * atr_15m)
                            if self.fade_sl_atr_mult is not None
                            else self.fade_stop_pts
                        )
                        self.fade_cur_tp_pts = (
                            (self.fade_tp_atr_mult * atr_15m)
                            if self.fade_tp_atr_mult is not None
                            else None
                        )
                        target_desc = f"TP={self.fade_cur_tp_pts:.1f}pt" if self.fade_cur_tp_pts is not None else "Target=MagnetBand"
                        self.log.info(
                            f"VP Fade Entry [{self.fade_position_side}] at {close:.2f} (SL={self.fade_cur_sl_pts:.1f}pt, {target_desc})"
                        )

        # =====================================================================
        # END-OF-DAY FLATTEN (15:59 ET)
        # =====================================================================
        if hour == 15 and minute >= 59:
            if self.trend_position_side != PositionSide.FLAT:
                self._close_trend_position("EOD Flatten (15:59)")
            if self.fade_position_side != PositionSide.FLAT:
                self._close_fade_position("EOD Flatten (15:59)")

    def _close_trend_position(self, reason: str) -> None:
        side = OrderSide.SELL if self.trend_position_side == PositionSide.LONG else OrderSide.BUY
        qty = Quantity.from_int(self.trend_size)
        order = self.order_factory.market(
            instrument_id=self.instrument_id, order_side=side, quantity=qty
        )
        self.submit_order(order)
        self.log.info(f"Closing Trend V2 [{self.trend_position_side}] at market. Reason: {reason}")
        self.trend_position_side = PositionSide.FLAT

    def _close_fade_position(self, reason: str) -> None:
        side = OrderSide.BUY if self.fade_position_side == PositionSide.SHORT else OrderSide.SELL
        qty = Quantity.from_int(self.fade_size)
        order = self.order_factory.market(
            instrument_id=self.instrument_id, order_side=side, quantity=qty
        )
        self.submit_order(order)
        self.log.info(f"Closing VP Fade [{self.fade_position_side}] at market. Reason: {reason}")
        if self.fade_position_side == PositionSide.SHORT:
            self.needs_cone_reset_long = True
        elif self.fade_position_side == PositionSide.LONG:
            self.needs_cone_reset_short = True
        self.fade_position_side = PositionSide.FLAT
        self.fade_bars_held = 0

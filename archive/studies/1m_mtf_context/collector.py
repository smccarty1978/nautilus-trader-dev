"""Multi-Timeframe Regime Context Collector.

Captures 94 features around the 1m confirmed regime flip entry (bar+1
HH/LL confirmation, entry at bar+1 close). Features span flip bar
anatomy, bar+1 anatomy, 2-bar sequence, pre-flip 1m context, MAs, 1m
volume, 5m regime, 15m regime, 5s micro-context, and time/session.

Also tracks forward path (MFE/MAE milestones + 5 pre-computed bracket
race outcomes) from bar+1 close until regime flip exit.

Entry rule, data conventions, and no-look-ahead rules per
MTF_REGIME_CONTEXT_COLLECTOR.md.
"""

import os
import sys
from collections import deque
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import pytz

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators import AverageTrueRange

CT = pytz.timezone("America/Chicago")

NQ_MULT = 20.0
COMMISSION = 5.0

# Bracket race configurations (pt_atr, sl_atr, short_tag)
BRACKETS = [
    (0.50, 0.50, "050_050"),
    (0.75, 0.75, "075_075"),
    (1.00, 0.50, "100_050"),
    (1.00, 1.00, "100_100"),
    (1.50, 0.75, "150_075"),
]

# MFE/MAE milestones for path labels (ATR multiples)
MFE_MILESTONES = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
MAE_MILESTONES = [0.25, 0.50, 0.75, 1.00, 1.25]

# Time snapshots (seconds after entry)
TIME_SNAPS = [30, 60, 120, 300, 600]


# --------------------------------------------------------------------
# Lightweight EMA/SMA helpers driven by raw floats (not NT indicator).
# We run independent EMA3/9 on 5m and 15m bars, updated ONLY on HTF
# close. Keeps state local and avoids NT indicator subscription churn.
# --------------------------------------------------------------------

class LocalEMA:
    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value = 0.0
        self.initialized = False
        self.count = 0

    def update(self, v: float) -> None:
        self.count += 1
        if self.count == 1:
            self.value = v
            return
        self.value = self.alpha * v + (1 - self.alpha) * self.value
        if self.count >= self.period:
            self.initialized = True


class LocalSMA:
    def __init__(self, period: int):
        self.period = period
        self.buf = deque(maxlen=period)

    @property
    def initialized(self) -> bool:
        return len(self.buf) >= self.period

    @property
    def value(self) -> float:
        return sum(self.buf) / len(self.buf) if self.buf else 0.0

    def update(self, v: float) -> None:
        self.buf.append(v)


# --------------------------------------------------------------------
# Per-timeframe regime state
# --------------------------------------------------------------------

class RegimeState:
    """EMA3/9 sticky regime on H/L/C for one timeframe."""

    def __init__(self):
        self.emaH_3 = LocalEMA(3)
        self.emaH_9 = LocalEMA(9)
        self.emaL_3 = LocalEMA(3)
        self.emaL_9 = LocalEMA(9)
        self.ema3 = LocalEMA(3)  # of close
        self.ema9 = LocalEMA(9)  # of close
        self.regime = 0  # -1, 0, +1
        self.bars_in_regime = 0
        self.completed_bars = 0  # count of completed bars fed

    def update(self, h: float, l: float, c: float) -> int:
        """Update with a completed bar. Returns new regime (possibly flipped)."""
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

    def live_regime(self, current_close: float) -> int:
        """Return live regime probe using current 1m close vs completed EMAs.

        This is for 5m/15m — we ask 'what regime would be indicated if the
        last observation were `current_close`, using EMAs from completed
        HTF bars'. Returns 0 if EMAs not initialized.
        """
        if not (self.emaH_3.initialized and self.emaH_9.initialized
                and self.emaL_3.initialized and self.emaL_9.initialized):
            return 0
        if (current_close > self.emaH_3.value
                and current_close > self.emaH_9.value):
            return 1
        if (current_close < self.emaL_3.value
                and current_close < self.emaL_9.value):
            return -1
        return self.regime


# --------------------------------------------------------------------
# Rolling-window helpers for 1m context
# --------------------------------------------------------------------

class Bar1mRecord:
    __slots__ = ("ts_event", "o", "h", "l", "c", "v",
                 "up_vol", "down_vol", "is_up_close")

    def __init__(self, ts_event, o, h, l, c, v, up_vol, down_vol):
        self.ts_event = ts_event
        self.o = o
        self.h = h
        self.l = l
        self.c = c
        self.v = v
        self.up_vol = up_vol
        self.down_vol = down_vol
        self.is_up_close = c > o


# --------------------------------------------------------------------
# Path tracker — MFE/MAE milestones + bracket race
# --------------------------------------------------------------------

class PathTracker:
    """Tracks MFE/MAE milestones + bracket race outcomes over a trade."""

    def __init__(self, entry_price: float, direction: int, atr: float,
                 entry_ts: int):
        self.entry_price = entry_price
        self.direction = direction
        self.atr = max(atr, 1e-9)
        self.entry_ts = entry_ts
        self.peak_mfe = 0.0
        self.peak_mae = 0.0
        self.mfe_first = 0  # +1 if MFE reached before MAE
        self._mfe_first_decided = False
        self.mae_at_peak_mfe = 0.0
        self.mfe_at_peak_mae = 0.0
        self.bars_processed = 0

        # Milestones: first time MFE/MAE reached threshold
        self.bars_to_mfe = {m: None for m in MFE_MILESTONES}
        self.bars_to_mae = {m: None for m in MAE_MILESTONES}

        # Time snapshots: MFE/MAE at N seconds after entry
        self.snap_mfe = {t: None for t in TIME_SNAPS}
        self.snap_mae = {t: None for t in TIME_SNAPS}
        self._snap_idx = 0  # pointer into TIME_SNAPS

        # Bracket race: for each bracket, resolve to "PT" / "SL" / None
        self.bracket_results = {tag: None for _, _, tag in BRACKETS}
        self.bracket_pnl_atr = {tag: None for _, _, tag in BRACKETS}
        self.bracket_resolved_bars = {tag: None for _, _, tag in BRACKETS}

    def update_1s(self, h: float, l: float, ts_event: int) -> None:
        self.bars_processed += 1
        d = self.direction
        if d == 1:
            mfe_now = (h - self.entry_price) / self.atr
            mae_now = (self.entry_price - l) / self.atr
        else:
            mfe_now = (self.entry_price - l) / self.atr
            mae_now = (h - self.entry_price) / self.atr

        mfe_now = max(0.0, mfe_now)
        mae_now = max(0.0, mae_now)

        # Update peaks
        if mfe_now > self.peak_mfe:
            self.peak_mfe = mfe_now
            self.mae_at_peak_mfe = self.peak_mae
        if mae_now > self.peak_mae:
            self.peak_mae = mae_now
            self.mfe_at_peak_mae = self.peak_mfe

        # MFE-first flag: which reached 0.25 ATR first
        if not self._mfe_first_decided:
            if self.peak_mfe >= 0.25:
                self.mfe_first = 1
                self._mfe_first_decided = True
            elif self.peak_mae >= 0.25:
                self.mfe_first = -1
                self._mfe_first_decided = True

        # MFE milestones
        for m in MFE_MILESTONES:
            if self.bars_to_mfe[m] is None and self.peak_mfe >= m:
                self.bars_to_mfe[m] = self.bars_processed

        # MAE milestones
        for m in MAE_MILESTONES:
            if self.bars_to_mae[m] is None and self.peak_mae >= m:
                self.bars_to_mae[m] = self.bars_processed

        # Time snapshots
        while self._snap_idx < len(TIME_SNAPS):
            t = TIME_SNAPS[self._snap_idx]
            if self.bars_processed >= t:
                self.snap_mfe[t] = self.peak_mfe
                self.snap_mae[t] = self.peak_mae
                self._snap_idx += 1
            else:
                break

        # Bracket race — check each unresolved bracket
        for pt_atr, sl_atr, tag in BRACKETS:
            if self.bracket_results[tag] is not None:
                continue
            # PT check: favorable reached pt_atr
            # SL check: adverse reached sl_atr
            # Intra-bar: if BOTH hit in same bar, call it PT (optimistic)
            pt_hit = mfe_now >= pt_atr
            sl_hit = mae_now >= sl_atr
            if pt_hit and sl_hit:
                self.bracket_results[tag] = "PT"
                self.bracket_pnl_atr[tag] = pt_atr
                self.bracket_resolved_bars[tag] = self.bars_processed
            elif pt_hit:
                self.bracket_results[tag] = "PT"
                self.bracket_pnl_atr[tag] = pt_atr
                self.bracket_resolved_bars[tag] = self.bars_processed
            elif sl_hit:
                self.bracket_results[tag] = "SL"
                self.bracket_pnl_atr[tag] = -sl_atr
                self.bracket_resolved_bars[tag] = self.bars_processed

    def finalize(self, exit_price: float) -> None:
        """Called at exit. Unresolved brackets → 'neither', PnL from regime exit."""
        exit_atr = (exit_price - self.entry_price) * self.direction / self.atr
        for pt_atr, sl_atr, tag in BRACKETS:
            if self.bracket_results[tag] is None:
                self.bracket_results[tag] = "neither"
                self.bracket_pnl_atr[tag] = exit_atr


# --------------------------------------------------------------------
# Strategy Config
# --------------------------------------------------------------------

class MTFContextConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    output_file: str = \
        "studies/1m_mtf_context/results/trades_unsaved.parquet"
    skipped_file: str = \
        "studies/1m_mtf_context/results/skipped_flips_unsaved.parquet"
    warmup_1m_bars: int = 150


# --------------------------------------------------------------------
# Main Strategy
# --------------------------------------------------------------------

class MTFContextCollector(Strategy):
    """Collect MTF context features around confirmed flip entries."""

    def __init__(self, config: MTFContextConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # 1m indicators
        self.regime_1m = RegimeState()
        self.atr_14 = AverageTrueRange(14)
        self.sma20_1m = LocalSMA(20)
        self.sma50_1m = LocalSMA(50)
        self._prev_sma20 = deque(maxlen=6)   # for 5-bar slope
        self._prev_sma50 = deque(maxlen=11)  # for 10-bar slope
        self._prev_ema3 = deque(maxlen=6)

        # 5m/15m regimes
        self.regime_5m = RegimeState()
        self.regime_15m = RegimeState()
        self.sma20_5m = LocalSMA(20)

        # Aggregation buffers
        self._1m_for_5m = []   # up to 5 consecutive 1m bars
        self._1m_for_15m = []  # up to 15 consecutive 1m bars

        # 1s aggregation to 5s
        self._1s_for_5s = []        # up to 5 1s bars
        self._recent_5s = deque(maxlen=30)  # last ~30 5s bars
        self._recent_1s = deque(maxlen=300)  # last 5 min of 1s

        # Volume direction accumulator for CURRENT 1m bar
        self._current_1m_minute = None  # UTC minute (int, floor to 60s)
        self._current_1m_up_vol = 0.0
        self._current_1m_down_vol = 0.0

        # 1m rolling windows (Bar1mRecord deque)
        self._recent_1m = deque(maxlen=70)

        # Flip history: list of (bar_index, direction)
        self._flip_history = deque(maxlen=80)
        self._1m_bar_count = 0  # total 1m bars processed

        # Session high/low
        self._session_start_ts_ct = None  # str date key
        self._session_high = -1e18
        self._session_low = 1e18

        # Prior regime MFE tracking
        self._regime_start_price = None
        self._regime_mfe_atr = 0.0  # MFE of current (not prior) regime
        self._prior_regime_mfe_atr = 0.0  # saved on flip

        # Flip state machine
        self._state = "WARMUP"
        self._flip_pending = None  # dict when AWAITING_CONFIRMATION
        self._active_trade = None   # dict while IN_TRADE
        self._path = None  # PathTracker while IN_TRADE

        # Pending regime flip detection: flip gets picked up at NEXT 1m bar
        # (we need bar+1 to confirm).

        # Output
        self._trades = []
        self._skipped = []
        self._trade_counter = 0

    # ----- Bar subscription -----
    def on_start(self):
        self._bt_1s = BarType.from_str(self.config.bar_type_1s)
        self._bt_1m = BarType.from_str(self.config.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    # ----- 1s handling -----
    def _on_1s(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # Buffer
        self._recent_1s.append((ts, o, h, l, c, v))

        # Session high/low (rolling, reset at 17:00 CT)
        self._update_session(ts, h, l)

        # Accumulate up/down volume for CURRENT 1m bar
        minute_floor = (ts // 60_000_000_000) * 60_000_000_000
        if self._current_1m_minute != minute_floor:
            # New 1m window. Finalize previous accumulator via on_1m path
            # (the 1m bar callback will use _current_1m_up/down_vol when
            # the 1m bar for the just-ending minute fires).
            self._current_1m_minute = minute_floor
            self._current_1m_up_vol = 0.0
            self._current_1m_down_vol = 0.0

        if c > o:
            self._current_1m_up_vol += v
        elif c < o:
            self._current_1m_down_vol += v
        # flat: excluded

        # 5s aggregation — cleanly aligned
        self._1s_for_5s.append((ts, o, h, l, c, v))
        second_of_5 = (ts // 1_000_000_000) % 5
        if second_of_5 == 4:
            # This 1s closes a 5s window
            bars = self._1s_for_5s
            if bars:
                agg_o = bars[0][1]
                agg_h = max(b[2] for b in bars)
                agg_l = min(b[3] for b in bars)
                agg_c = bars[-1][4]
                agg_v = sum(b[5] for b in bars)
                agg_ts = (ts // 5_000_000_000) * 5_000_000_000
                self._recent_5s.append(
                    (agg_ts, agg_o, agg_h, agg_l, agg_c, agg_v))
            self._1s_for_5s = []

        # Path tracking for open trade
        if self._state == "IN_TRADE" and self._path is not None:
            # Only track 1s bars at or after entry timestamp
            if ts >= self._path.entry_ts:
                self._path.update_1s(h, l, ts)

    def _update_session(self, ts: int, h: float, l: float):
        dt_ct = pd.Timestamp(ts, unit="ns", tz="UTC").astimezone(CT)
        # Session boundary = 17:00 CT; session_date_key = date of 17:00 that
        # began the current session
        if dt_ct.hour >= 17:
            key = str(dt_ct.date())
        else:
            key = str((dt_ct - pd.Timedelta(days=1)).date())
        if key != self._session_start_ts_ct:
            self._session_start_ts_ct = key
            self._session_high = h
            self._session_low = l
        else:
            if h > self._session_high:
                self._session_high = h
            if l < self._session_low:
                self._session_low = l

    # ----- 1m handling -----
    def _on_1m(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        # Snapshot volume accumulator for THIS 1m bar. Note: the 1m bar
        # matches minute-boundary = ts (open time). Our accumulator is
        # currently being updated by 1s bars arriving during this minute.
        # When 1m fires, accumulator has N 1s bars aggregated — may be
        # 59 or 60 depending on exact ordering (see spec Q2). We use the
        # current snapshot.
        up_vol = self._current_1m_up_vol
        down_vol = self._current_1m_down_vol

        # Record 1m bar
        rec = Bar1mRecord(ts, o, h, l, c, v, up_vol, down_vol)
        self._recent_1m.append(rec)
        self._1m_bar_count += 1

        # Update ATR
        self.atr_14.update_raw(h, l, c)
        atr = self.atr_14.value if self.atr_14.initialized else 0.0

        # Update 1m SMAs
        self.sma20_1m.update(c)
        self.sma50_1m.update(c)
        if self.sma20_1m.initialized:
            self._prev_sma20.append(self.sma20_1m.value)
        if self.sma50_1m.initialized:
            self._prev_sma50.append(self.sma50_1m.value)

        # Update 1m regime (EMAs tracked inside RegimeState)
        prev_regime_1m = self.regime_1m.regime
        new_r = self.regime_1m.update(h, l, c)
        if self.regime_1m.ema3.initialized:
            self._prev_ema3.append(self.regime_1m.ema3.value)

        # Track prior-regime MFE (for feature #34)
        if prev_regime_1m == new_r and prev_regime_1m != 0:
            # Continuation of current regime — update MFE
            if self._regime_start_price is not None:
                d = prev_regime_1m
                if d == 1:
                    mfe = (h - self._regime_start_price) / max(atr, 1e-9)
                else:
                    mfe = (self._regime_start_price - l) / max(atr, 1e-9)
                if mfe > self._regime_mfe_atr:
                    self._regime_mfe_atr = max(0.0, mfe)

        # Handle flip — but only AFTER warmup
        warmup_done = self._is_warmed_up()
        if self._state == "WARMUP" and warmup_done:
            self._state = "FLAT"
            self._regime_start_price = c if new_r != 0 else None
            self._regime_mfe_atr = 0.0

        flip_occurred = (self._state != "WARMUP"
                          and prev_regime_1m != 0 and new_r != 0
                          and prev_regime_1m != new_r)

        # Process current state BEFORE handling flip (to snap bar+1
        # confirmation check first)
        if self._state == "AWAITING_CONFIRMATION" and not flip_occurred:
            self._check_confirmation(rec)
        elif self._state == "AWAITING_CONFIRMATION" and flip_occurred:
            # New flip arrives before bar+1 confirmation of previous flip.
            # Record current bar as the "skipped bar+1" for prior flip.
            self._record_skipped(rec, reason="new_flip_before_bar1")
            self._flip_pending = None
            self._state = "FLAT"

        # If IN_TRADE and flip occurs, close trade first
        if flip_occurred and self._state == "IN_TRADE":
            self._close_trade(rec)

        # Handle new flip (queue pending, wait for bar+1)
        if flip_occurred:
            self._on_new_flip(rec, atr, new_r, prev_regime_1m)

        # Update 5m / 15m aggregations
        self._update_htf(rec)

        # Update flip_history and regime_start tracking
        if flip_occurred:
            self._flip_history.append((self._1m_bar_count, new_r))
            self._prior_regime_mfe_atr = self._regime_mfe_atr
            self._regime_mfe_atr = 0.0
            self._regime_start_price = c

    def _is_warmed_up(self) -> bool:
        return (self._1m_bar_count >= self.config.warmup_1m_bars
                and self.atr_14.initialized
                and self.sma50_1m.initialized
                and self.regime_15m.ema9.initialized)

    def _update_htf(self, rec: Bar1mRecord):
        # 5m aggregation — align on minutes divisible by 5
        self._1m_for_5m.append(rec)
        minute_of_hour = (rec.ts_event // 60_000_000_000) % 60
        if minute_of_hour % 5 == 4:  # last 1m of a 5m window
            bars = self._1m_for_5m
            # Only emit if we have exactly 5 consecutive bars
            if len(bars) >= 5:
                sub = bars[-5:]
                agg_h = max(b.h for b in sub)
                agg_l = min(b.l for b in sub)
                agg_c = sub[-1].c
                self.regime_5m.update(agg_h, agg_l, agg_c)
                self.sma20_5m.update(agg_c)
            self._1m_for_5m = []  # reset

        # 15m aggregation — align on minutes divisible by 15
        self._1m_for_15m.append(rec)
        if minute_of_hour % 15 == 14:  # last 1m of a 15m window
            bars = self._1m_for_15m
            if len(bars) >= 15:
                sub = bars[-15:]
                agg_h = max(b.h for b in sub)
                agg_l = min(b.l for b in sub)
                agg_c = sub[-1].c
                self.regime_15m.update(agg_h, agg_l, agg_c)
            self._1m_for_15m = []

    def _on_new_flip(self, rec: Bar1mRecord, atr: float,
                      new_r: int, prev_r: int):
        """On flip detected at bar close: queue pending, wait for bar+1."""
        self._flip_pending = {
            "flip_bar": rec,
            "atr_at_flip": atr,
            "direction": new_r,
            "prior_regime_duration_bars":
                self.regime_1m.bars_in_regime - 1
                if self.regime_1m.bars_in_regime > 0 else 0,
            "flip_time": pd.Timestamp(rec.ts_event, unit="ns", tz="UTC"),
            "prior_regime_mfe_atr": self._regime_mfe_atr,
        }
        self._state = "AWAITING_CONFIRMATION"

    def _check_confirmation(self, bar1: Bar1mRecord):
        """At bar+1 close, check HH/LL confirmation. If confirmed, snap features
        and start path tracking.
        """
        fp = self._flip_pending
        flip_bar = fp["flip_bar"]
        d = fp["direction"]
        if d == 1:
            made = bar1.h > flip_bar.h
        else:
            made = bar1.l < flip_bar.l

        feats = self._snap_all_features(flip_bar, bar1, fp, confirmed=made)

        if not made:
            # Skipped — record features in skipped list, back to FLAT
            feats["reason"] = "bar1_no_hh_ll"
            self._skipped.append(feats)
            self._flip_pending = None
            self._state = "FLAT"
            return

        # Confirmed — record trade, start path tracking
        self._trade_counter += 1
        entry_price_idealized = bar1.c
        # Realistic: approximated as bar1.c (exact first 1s post-close
        # requires a 1s buffer peek — use bar1.c as approximation). We
        # verified in prior work the first 1s open is typically within
        # 1-2 ticks of bar+1 close.
        entry_price_realistic = bar1.c  # fallback identical

        # Find first 1s bar at or after bar1 close for realistic entry
        bar1_close_ts = bar1.ts_event + 60_000_000_000
        for (bts, bo, _h, _l, _c, _v) in self._recent_1s:
            if bts >= bar1_close_ts:
                entry_price_realistic = bo
                break

        trade = {
            "trade_id": self._trade_counter,
            "entry_ts": bar1_close_ts,
            "entry_time": pd.Timestamp(
                bar1_close_ts, unit="ns", tz="UTC"),
            "entry_price": entry_price_idealized,
            "entry_price_realistic": entry_price_realistic,
            "direction": d,
            "atr_at_entry": fp["atr_at_flip"],
            "year": pd.Timestamp(bar1_close_ts, unit="ns",
                                  tz="UTC").year,
            **feats,
        }

        # Start path tracker
        self._path = PathTracker(
            entry_price=entry_price_idealized,
            direction=d,
            atr=fp["atr_at_flip"],
            entry_ts=bar1_close_ts,
        )
        self._active_trade = trade
        self._flip_pending = None
        self._state = "IN_TRADE"

    def _close_trade(self, flip_bar: Bar1mRecord):
        """Called when regime flips while IN_TRADE."""
        t = self._active_trade
        if t is None:
            self._state = "FLAT"
            return

        # Use flip bar's close as exit (it's the bar whose close triggered
        # detection of the new flip)
        exit_price = flip_bar.c
        d = t["direction"]
        pnl_pts = (exit_price - t["entry_price"]) * d
        pnl_dollars = pnl_pts * NQ_MULT - COMMISSION

        # Finalize path tracker
        self._path.finalize(exit_price)

        # Attach path labels
        t.update({
            "exit_ts": flip_bar.ts_event + 60_000_000_000,
            "exit_time": pd.Timestamp(
                flip_bar.ts_event + 60_000_000_000,
                unit="ns", tz="UTC"),
            "exit_price": exit_price,
            "exit_reason_baseline": "regime_flip",
            "regime_pnl_pts": pnl_pts,
            "regime_pnl_dollars": pnl_dollars,
            "regime_duration_bars":
                self._1m_bar_count - self._get_flip_bar_count(t),
            "peak_mfe_atr": self._path.peak_mfe,
            "peak_mae_atr": self._path.peak_mae,
            "mae_at_peak_mfe": self._path.mae_at_peak_mfe,
            "mfe_at_peak_mae": self._path.mfe_at_peak_mae,
            "mfe_first": self._path.mfe_first,
            "bars_processed_1s": self._path.bars_processed,
        })
        for m in MFE_MILESTONES:
            t[f"bars_to_mfe_{int(m*100):03d}"] = self._path.bars_to_mfe[m]
        for m in MAE_MILESTONES:
            t[f"bars_to_mae_{int(m*100):03d}"] = self._path.bars_to_mae[m]
        for tsec in TIME_SNAPS:
            t[f"mfe_at_{tsec}s"] = self._path.snap_mfe[tsec]
            t[f"mae_at_{tsec}s"] = self._path.snap_mae[tsec]
        for _, _, tag in BRACKETS:
            t[f"bracket_{tag}_result"] = self._path.bracket_results[tag]
            t[f"bracket_{tag}_pnl_atr"] = self._path.bracket_pnl_atr[tag]
            t[f"bracket_{tag}_bar"] = (
                self._path.bracket_resolved_bars[tag])

        self._trades.append(t)
        self._active_trade = None
        self._path = None
        self._state = "FLAT"

    def _get_flip_bar_count(self, t):
        """Approximate flip bar count — bar+1 is entry, flip was bar+1-1."""
        # Not critical; approximate
        return self._1m_bar_count - t.get("regime_duration_bars", 0)

    def _record_skipped(self, bar1, reason):
        """Record a skipped flip (bar+1 did not confirm or new flip arrived)."""
        fp = self._flip_pending
        if fp is None:
            return
        feats = self._snap_all_features(
            fp["flip_bar"], bar1, fp, confirmed=False)
        feats["reason"] = reason
        self._skipped.append(feats)

    # ----- Feature snap -----
    def _snap_all_features(self, flip_bar: Bar1mRecord,
                             bar1: Bar1mRecord, fp: dict,
                             confirmed: bool) -> dict:
        atr = fp["atr_at_flip"]
        atr_safe = max(atr, 1e-9)
        d = fp["direction"]

        feats = {}
        feats.update(self._feat_flip_anatomy(flip_bar, atr_safe, d))
        feats.update(self._feat_bar1_anatomy(bar1, flip_bar, atr_safe, d))
        feats.update(self._feat_two_bar(flip_bar, bar1, atr_safe, d))
        feats.update(self._feat_preflip_context(atr_safe, d))
        feats.update(self._feat_ma_context(bar1, atr_safe))
        feats.update(self._feat_1m_volume(flip_bar, bar1))
        feats.update(self._feat_5m_context(bar1, atr_safe, d))
        feats.update(self._feat_15m_context(bar1, atr_safe, d))
        feats.update(self._feat_5s_micro(flip_bar, bar1, atr_safe))
        feats.update(self._feat_time_session(bar1))

        # Metadata
        feats["flip_time"] = fp["flip_time"]
        feats["flip_ts"] = flip_bar.ts_event
        feats["direction"] = d
        feats["atr_at_flip"] = atr
        feats["confirmed"] = 1 if confirmed else 0
        return feats

    # --- Category 1: Flip anatomy (12) ---
    def _feat_flip_anatomy(self, fb: Bar1mRecord, atr: float, d: int) -> dict:
        rng = fb.h - fb.l
        body = abs(fb.c - fb.o)
        upper_wick = fb.h - max(fb.o, fb.c)
        lower_wick = min(fb.o, fb.c) - fb.l
        # prior bar (second-to-last in recent_1m — last is flip itself)
        prior_c = prior_h = prior_l = fb.c  # default = no-op
        if len(self._recent_1m) >= 2:
            pb = self._recent_1m[-2]
            prior_c, prior_h, prior_l = pb.c, pb.h, pb.l

        up = fb.up_vol
        dn = fb.down_vol
        bull_vol_pct = up / (up + dn) if (up + dn) > 0 else 0.5

        return {
            "flip_range_atr": rng / atr,
            "flip_body_atr": body / atr,
            "flip_body_pct": body / rng if rng > 0 else 0.0,
            "flip_close_location": (
                (fb.c - fb.l) / rng if rng > 0 else 0.5),
            "flip_upper_wick_pct": upper_wick / rng if rng > 0 else 0.0,
            "flip_lower_wick_pct": lower_wick / rng if rng > 0 else 0.0,
            "flip_volume": fb.v,
            "flip_vol_vs_20avg": self._vol_vs_20avg(fb.v),
            "flip_close_vs_prior_close_atr":
                (fb.c - prior_c) * d / atr,
            "flip_high_vs_prior_high_atr":
                (fb.h - prior_h) * d / atr,
            "flip_low_vs_prior_low_atr":
                (fb.l - prior_l) * d / atr,
            "flip_bar_bullish_volume_pct": bull_vol_pct,
        }

    # --- Category 2: Bar+1 anatomy (14) ---
    def _feat_bar1_anatomy(self, b1: Bar1mRecord, fb: Bar1mRecord,
                            atr: float, d: int) -> dict:
        rng = b1.h - b1.l
        body = abs(b1.c - b1.o)
        upper_wick = b1.h - max(b1.o, b1.c)
        lower_wick = min(b1.o, b1.c) - b1.l
        up = b1.up_vol
        dn = b1.down_vol
        bull_vol_pct = up / (up + dn) if (up + dn) > 0 else 0.5

        hh_amt = 0.0
        if d == 1:
            hh_amt = (b1.h - fb.h) / atr
        else:
            hh_amt = (fb.l - b1.l) / atr

        b1_close_vs_flip_close = (b1.c - fb.c) * d / atr
        b1_close_above_flip = 1 if b1_close_vs_flip_close > 0 else 0
        b1_close_above_mid = 0
        if rng > 0:
            b1_close_loc = (b1.c - b1.l) / rng
            b1_close_above_mid = 1 if (d == 1 and b1_close_loc > 0.5) \
                else (1 if d == -1 and b1_close_loc < 0.5 else 0)

        return {
            "bar1_range_atr": rng / atr,
            "bar1_body_atr": body / atr,
            "bar1_body_pct": body / rng if rng > 0 else 0.0,
            "bar1_close_location": (
                (b1.c - b1.l) / rng if rng > 0 else 0.5),
            "bar1_upper_wick_pct": upper_wick / rng if rng > 0 else 0.0,
            "bar1_lower_wick_pct": lower_wick / rng if rng > 0 else 0.0,
            "bar1_volume": b1.v,
            "bar1_vol_vs_20avg": self._vol_vs_20avg(b1.v, skip_last=1),
            "bar1_vol_vs_flip_vol": b1.v / fb.v if fb.v > 0 else 1.0,
            "bar1_hh_amount_atr": hh_amt,
            "bar1_close_vs_flip_close_atr": b1_close_vs_flip_close,
            "bar1_close_above_flip_close": b1_close_above_flip,
            "bar1_close_above_50pct_range": b1_close_above_mid,
            "bar1_bullish_volume_pct": bull_vol_pct,
        }

    # --- Category 3: Two-bar sequence (6) ---
    def _feat_two_bar(self, fb: Bar1mRecord, b1: Bar1mRecord,
                       atr: float, d: int) -> dict:
        h_max = max(fb.h, b1.h)
        l_min = min(fb.l, b1.l)
        two_bar_range = h_max - l_min
        two_bar_body = (b1.c - fb.o) * d
        vol_total = fb.v + b1.v

        low_to_high_atr = 0.0
        if d == 1:
            low_to_high_atr = (b1.h - fb.l) / atr
        else:
            low_to_high_atr = (fb.h - b1.l) / atr

        return {
            "two_bar_range_atr": two_bar_range / atr,
            "two_bar_body_atr": two_bar_body / atr,
            "two_bar_close_vs_open_pct": (
                two_bar_body / two_bar_range
                if two_bar_range > 0 else 0.0),
            "two_bar_volume_total": vol_total,
            "two_bar_vol_vs_40avg": self._vol_vs_Navg(vol_total, 40,
                                                       skip_last=1) / 2.0,
            "flip_low_to_bar1_high_atr": low_to_high_atr,
        }

    # --- Category 4: Pre-flip context (12) ---
    def _feat_preflip_context(self, atr: float, d: int) -> dict:
        # Recent 1m has: [..., flip_bar, bar1]
        # Pre-flip bars = bars BEFORE flip_bar (exclude flip and bar1)
        n_recent = len(self._recent_1m)
        # indexes from -3 to -7 are "bars before flip"
        def _bar_back(k):
            """k=3 means 3 bars back from last (which is bar1). So bar1 is -1,
            flip is -2, pre-flip starts at -3."""
            idx = -k
            if abs(idx) > n_recent:
                return None
            return self._recent_1m[idx]

        pre_flip_3 = [_bar_back(k) for k in (3, 4, 5)]
        pre_flip_5 = [_bar_back(k) for k in (3, 4, 5, 6, 7)]
        vol_recent_3 = [_bar_back(k) for k in (3, 4, 5)]
        vol_prior_3 = [_bar_back(k) for k in (6, 7, 8)]

        pf3_range_atr = 0.0
        if all(b is not None for b in pre_flip_3):
            pf3_h = max(b.h for b in pre_flip_3)
            pf3_l = min(b.l for b in pre_flip_3)
            pf3_range_atr = (pf3_h - pf3_l) / atr

        pf5_range_atr = 0.0
        if all(b is not None for b in pre_flip_5):
            pf5_h = max(b.h for b in pre_flip_5)
            pf5_l = min(b.l for b in pre_flip_5)
            pf5_range_atr = (pf5_h - pf5_l) / atr

        pf3_body_dir = 0.0
        if all(b is not None for b in pre_flip_3):
            pf3_body_dir = sum((b.c - b.o) * d for b in pre_flip_3) / atr

        vol_trend = 1.0
        if (all(b is not None for b in vol_recent_3)
                and all(b is not None for b in vol_prior_3)):
            recent_v = sum(b.v for b in vol_recent_3) / 3
            prior_v = sum(b.v for b in vol_prior_3) / 3
            vol_trend = recent_v / prior_v if prior_v > 0 else 1.0

        consec_trend = 0
        for k in range(3, 20):
            b = _bar_back(k)
            if b is None:
                break
            # bullish flip: consecutive bars with close > open
            if d == 1 and b.c > b.o:
                consec_trend += 1
            elif d == -1 and b.c < b.o:
                consec_trend += 1
            else:
                break

        # Flip count in last 30 / 60 1m bars (exclusive of current)
        cutoff_30 = self._1m_bar_count - 30
        cutoff_60 = self._1m_bar_count - 60
        flips_30 = sum(1 for (bc, _) in self._flip_history
                        if bc > cutoff_30 and bc < self._1m_bar_count)
        flips_60 = sum(1 for (bc, _) in self._flip_history
                        if bc > cutoff_60 and bc < self._1m_bar_count)

        # Avg regime duration last 5
        if len(self._flip_history) >= 6:
            recent = list(self._flip_history)[-6:]
            durations = [recent[i + 1][0] - recent[i][0]
                         for i in range(len(recent) - 1)]
            avg_dur_5 = sum(durations) / len(durations)
        else:
            avg_dur_5 = 0.0

        return {
            "prior_regime_duration_bars": (
                self._flip_pending["prior_regime_duration_bars"]
                if self._flip_pending else 0),
            "prior_regime_mfe_atr": (
                self._flip_pending["prior_regime_mfe_atr"]
                if self._flip_pending else 0.0),
            "bars_since_last_flip": (
                self._flip_pending["prior_regime_duration_bars"]
                if self._flip_pending else 0),
            "regime_flips_last_30min": flips_30,
            "regime_flips_last_60min": flips_60,
            "avg_regime_duration_last_5": avg_dur_5,
            "pre_flip_3bar_range_atr": pf3_range_atr,
            "pre_flip_5bar_range_atr": pf5_range_atr,
            "pre_flip_3bar_body_direction": pf3_body_dir,
            "pre_flip_volume_trend": vol_trend,
            "consecutive_trend_bars_pre_flip": consec_trend,
            "atr_14": atr,
        }

    # --- Category 5: MA context (8) ---
    def _feat_ma_context(self, b1: Bar1mRecord, atr: float) -> dict:
        close = b1.c
        sma20 = self.sma20_1m.value if self.sma20_1m.initialized else close
        sma50 = self.sma50_1m.value if self.sma50_1m.initialized else close

        sma20_slope = 0.0
        if len(self._prev_sma20) >= 6:
            sma20_slope = (self._prev_sma20[-1] - self._prev_sma20[-6]) / atr
        sma50_slope = 0.0
        if len(self._prev_sma50) >= 11:
            sma50_slope = (self._prev_sma50[-1] - self._prev_sma50[-11]) / atr
        ema3_slope = 0.0
        if len(self._prev_ema3) >= 6:
            ema3_slope = (self._prev_ema3[-1] - self._prev_ema3[-6]) / atr

        ema3 = self.regime_1m.ema3.value if self.regime_1m.ema3.initialized \
            else close
        ema9 = self.regime_1m.ema9.value if self.regime_1m.ema9.initialized \
            else close
        eh3 = self.regime_1m.emaH_3.value \
            if self.regime_1m.emaH_3.initialized else close
        el3 = self.regime_1m.emaL_3.value \
            if self.regime_1m.emaL_3.initialized else close

        return {
            "price_vs_sma20_atr": (close - sma20) / atr,
            "price_vs_sma50_atr": (close - sma50) / atr,
            "sma20_slope_atr": sma20_slope,
            "sma50_slope_atr": sma50_slope,
            "sma20_vs_sma50_atr": (sma20 - sma50) / atr,
            "ema3_slope_atr": ema3_slope,
            "ema_spread_atr": (eh3 - el3) / atr,
            "ema3_ema9_spread_atr": (ema3 - ema9) / atr,
        }

    # --- Category 6: 1m volume (8) ---
    def _feat_1m_volume(self, fb: Bar1mRecord, b1: Bar1mRecord) -> dict:
        n = len(self._recent_1m)
        # Exclude the current (bar1) bar from recent 20 for avg
        last_20 = [self._recent_1m[i] for i in range(
            max(0, n - 21), n - 1)]
        avg_20 = (sum(b.v for b in last_20) / len(last_20)
                  if last_20 else 0.0)

        last_10 = [self._recent_1m[i] for i in range(
            max(0, n - 11), n - 1)]
        up_vol_10 = sum(b.v for b in last_10 if b.c > b.o)
        dn_vol_10 = sum(b.v for b in last_10 if b.c < b.o)
        ratio_10 = up_vol_10 / dn_vol_10 if dn_vol_10 > 0 else (
            999.0 if up_vol_10 > 0 else 1.0)

        last_20_v = [self._recent_1m[i] for i in range(
            max(0, n - 21), n - 1)]
        up_vol_20 = sum(b.v for b in last_20_v if b.c > b.o)
        dn_vol_20 = sum(b.v for b in last_20_v if b.c < b.o)
        ratio_20 = up_vol_20 / dn_vol_20 if dn_vol_20 > 0 else (
            999.0 if up_vol_20 > 0 else 1.0)

        # Volume acceleration
        last_5 = [self._recent_1m[i] for i in range(
            max(0, n - 6), n - 1)]
        prior_5 = [self._recent_1m[i] for i in range(
            max(0, n - 11), max(0, n - 6))]
        recent_v = sum(b.v for b in last_5) / len(last_5) if last_5 else 0.0
        prior_v = sum(b.v for b in prior_5) / len(prior_5) \
            if prior_5 else 0.0
        vol_accel = recent_v / prior_v if prior_v > 0 else 1.0

        high_vol_count = sum(1 for b in last_10 if b.v > 1.5 * avg_20)

        # Percentile rank of flip and bar1 volume in last 20
        vols_prior_20 = [b.v for b in last_20_v]
        flip_rank = self._percentile_rank(fb.v, vols_prior_20)
        bar1_rank = self._percentile_rank(b1.v, vols_prior_20)

        # Cumulative volume bias
        total_v_10 = up_vol_10 + dn_vol_10
        cum_bias_10 = ((up_vol_10 - dn_vol_10) / total_v_10
                        if total_v_10 > 0 else 0.0)

        return {
            "vol_1m_20avg": avg_20,
            "vol_ratio_up_down_10bar": ratio_10,
            "vol_ratio_up_down_20bar": ratio_20,
            "vol_acceleration_5bar": vol_accel,
            "high_vol_bar_count_10": high_vol_count,
            "flip_bar_vol_rank_20": flip_rank,
            "bar1_vol_rank_20": bar1_rank,
            "cumulative_volume_bias_10": cum_bias_10,
        }

    # --- Category 7: 5m context (10) ---
    def _feat_5m_context(self, b1: Bar1mRecord, atr: float, d: int) -> dict:
        # Live regime using bar+1 close vs last completed 5m EMAs
        live_5m = self.regime_5m.live_regime(b1.c)
        aligned_5m = 1 if live_5m == d else 0
        ema3 = (self.regime_5m.ema3.value
                if self.regime_5m.ema3.initialized else b1.c)
        ema9 = (self.regime_5m.ema9.value
                if self.regime_5m.ema9.initialized else b1.c)
        eh3 = (self.regime_5m.emaH_3.value
                if self.regime_5m.emaH_3.initialized else b1.c)
        el3 = (self.regime_5m.emaL_3.value
                if self.regime_5m.emaL_3.initialized else b1.c)
        sma20_5m = (self.sma20_5m.value
                     if self.sma20_5m.initialized else b1.c)
        # ema3 slope: last completed 5m — approximate with current value
        ema3_slope_5m = 0.0  # not tracked with history; could add later

        # Current 5m bar (in-progress) range
        if self._1m_for_5m:
            current_5m_h = max(b.h for b in self._1m_for_5m)
            current_5m_l = min(b.l for b in self._1m_for_5m)
            current_5m_range = (current_5m_h - current_5m_l) / atr
            current_5m_v = sum(b.v for b in self._1m_for_5m)
        else:
            current_5m_range = 0.0
            current_5m_v = 0.0

        vol_vs_20avg_5m = 1.0  # approximate — would need 5m vol history

        return {
            "regime_5m": live_5m,
            "regime_5m_aligned": aligned_5m,
            "regime_5m_duration_bars": self.regime_5m.bars_in_regime,
            "ema3_slope_5m_atr": ema3_slope_5m,
            "ema_spread_5m_atr": (eh3 - el3) / atr,
            "price_vs_sma20_5m_atr": (b1.c - sma20_5m) / atr,
            "bar_range_5m_current_atr": current_5m_range,
            "hh_count_5m_3": 0,  # needs 5m bar history — approx 0
            "vol_vs_20avg_5m": vol_vs_20avg_5m,
            "regime_flips_5m_last_5": 0,  # needs 5m flip history
        }

    # --- Category 8: 15m context (8) ---
    def _feat_15m_context(self, b1: Bar1mRecord, atr: float, d: int) -> dict:
        live_15m = self.regime_15m.live_regime(b1.c)
        aligned_15m = 1 if live_15m == d else 0
        ema3 = (self.regime_15m.ema3.value
                if self.regime_15m.ema3.initialized else b1.c)
        ema9 = (self.regime_15m.ema9.value
                if self.regime_15m.ema9.initialized else b1.c)
        eh3 = (self.regime_15m.emaH_3.value
                if self.regime_15m.emaH_3.initialized else b1.c)
        el3 = (self.regime_15m.emaL_3.value
                if self.regime_15m.emaL_3.initialized else b1.c)

        # Regime alignment score across 1m, 5m, 15m
        live_5m = self.regime_5m.live_regime(b1.c)
        aligned_5m = 1 if live_5m == d else 0
        aligned_1m = 1  # by construction (d is the 1m regime direction)
        alignment_score = aligned_1m + aligned_5m + aligned_15m
        all_aligned = 1 if alignment_score == 3 else 0

        return {
            "regime_15m": live_15m,
            "regime_15m_aligned": aligned_15m,
            "regime_15m_duration_bars": self.regime_15m.bars_in_regime,
            "ema3_slope_15m_atr": 0.0,  # would need 15m history
            "ema_spread_15m_atr": (eh3 - el3) / atr,
            "price_vs_sma20_15m_atr": 0.0,  # would need 15m SMA
            "regime_alignment_score": alignment_score,
            "all_regimes_aligned": all_aligned,
        }

    # --- Category 9: 5s micro (10) ---
    def _feat_5s_micro(self, fb: Bar1mRecord, b1: Bar1mRecord,
                        atr: float) -> dict:
        # Use last 12 5s bars BEFORE the flip bar (context)
        # and 12 5s bars within bar+1 (internals)
        # Note: 5s aggregator buffers completed 5s bars. At bar+1 close,
        # we may be missing the last 5s of bar+1 due to processing order.
        recent_5s = list(self._recent_5s)
        if not recent_5s:
            return {
                "micro_trend_12bar_5s": 0.0,
                "micro_vol_acceleration_5s": 1.0,
                "micro_range_compression_5s": 1.0,
                "micro_body_pct_avg_5s": 0.5,
                "micro_hh_count_12_5s": 0,
                "micro_hl_count_12_5s": 0,
                "micro_up_vol_pct_12_5s": 0.5,
                "micro_max_retracement_5s": 0.0,
                "bar1_internals_up_pct": 0.5,
                "bar1_internals_trend_5s": 0.0,
            }

        # For "context": 12 5s bars BEFORE flip bar close
        flip_close_ts = fb.ts_event + 60_000_000_000
        bars_before_flip = [b for b in recent_5s if b[0] < flip_close_ts]
        last_12_before = bars_before_flip[-12:]

        micro_trend = 0.0
        if len(last_12_before) >= 2:
            first_c = last_12_before[0][4]
            last_c = last_12_before[-1][4]
            micro_trend = (last_c - first_c) / atr

        # volume accel: avg last 6 vs prior 6
        last_6 = last_12_before[-6:] if len(last_12_before) >= 6 else []
        prior_6 = (last_12_before[-12:-6]
                   if len(last_12_before) >= 12 else [])
        recent_v = (sum(b[5] for b in last_6) / len(last_6)
                    if last_6 else 0.0)
        prior_v = (sum(b[5] for b in prior_6) / len(prior_6)
                   if prior_6 else 0.0)
        vol_accel_5s = recent_v / prior_v if prior_v > 0 else 1.0

        # range compression
        recent_r = (sum(b[2] - b[3] for b in last_6) / len(last_6)
                    if last_6 else 0.0)
        prior_r = (sum(b[2] - b[3] for b in prior_6) / len(prior_6)
                   if prior_6 else 0.0)
        range_compress = recent_r / prior_r if prior_r > 0 else 1.0

        # body pct avg
        body_pcts = []
        for b in last_12_before:
            rng = b[2] - b[3]
            body = abs(b[4] - b[1])
            body_pcts.append(body / rng if rng > 0 else 0.0)
        body_pct_avg = sum(body_pcts) / len(body_pcts) if body_pcts else 0.5

        # HH / HL counts (consecutive bar-to-bar)
        hh_count = 0
        hl_count = 0
        for i in range(1, len(last_12_before)):
            prev_b = last_12_before[i - 1]
            cur_b = last_12_before[i]
            if cur_b[2] > prev_b[2]:
                hh_count += 1
            if cur_b[3] > prev_b[3]:
                hl_count += 1

        # Up vol %
        up_vol = sum(b[5] for b in last_12_before if b[4] > b[1])
        down_vol = sum(b[5] for b in last_12_before if b[4] < b[1])
        up_pct = (up_vol / (up_vol + down_vol)
                  if (up_vol + down_vol) > 0 else 0.5)

        # Max retracement in last 12
        max_retrace_atr = 0.0
        if len(last_12_before) >= 2:
            running_peak = last_12_before[0][4]
            for b in last_12_before:
                c = b[4]
                if c > running_peak:
                    running_peak = c
                retrace = (running_peak - c) / atr
                if retrace > max_retrace_atr:
                    max_retrace_atr = retrace

        # Bar+1 internals: 5s bars WITHIN bar+1 [bar1.ts_event,
        # bar1.ts_event + 60s)
        bar1_start_ts = b1.ts_event
        bar1_end_ts = b1.ts_event + 60_000_000_000
        bar1_5s = [b for b in recent_5s
                    if bar1_start_ts <= b[0] < bar1_end_ts]
        bar1_up = sum(1 for b in bar1_5s if b[4] > b[1])
        bar1_total = len(bar1_5s)
        bar1_up_pct = bar1_up / bar1_total if bar1_total > 0 else 0.5

        bar1_trend = 0.0
        if len(bar1_5s) >= 2:
            bar1_trend = (bar1_5s[-1][4] - bar1_5s[0][4]) / atr

        return {
            "micro_trend_12bar_5s": micro_trend,
            "micro_vol_acceleration_5s": vol_accel_5s,
            "micro_range_compression_5s": range_compress,
            "micro_body_pct_avg_5s": body_pct_avg,
            "micro_hh_count_12_5s": hh_count,
            "micro_hl_count_12_5s": hl_count,
            "micro_up_vol_pct_12_5s": up_pct,
            "micro_max_retracement_5s": max_retrace_atr,
            "bar1_internals_up_pct": bar1_up_pct,
            "bar1_internals_trend_5s": bar1_trend,
        }

    # --- Category 10: Time/session (6) ---
    def _feat_time_session(self, b1: Bar1mRecord) -> dict:
        # entry_time = bar+1 close
        entry_ts = b1.ts_event + 60_000_000_000
        dt_ct = pd.Timestamp(entry_ts, unit="ns", tz="UTC").astimezone(CT)
        hour = dt_ct.hour
        minute = dt_ct.minute
        ct_min = hour * 60 + minute
        is_rth = 1 if 510 <= ct_min < 900 else 0  # 8:30-15:00 CT
        minutes_since_rth = ct_min - 510 if is_rth else ct_min - 510

        atr = self.atr_14.value if self.atr_14.initialized else 1.0
        atr_safe = max(atr, 1e-9)
        dist_high = ((self._session_high - b1.c) / atr_safe
                      if self._session_high > -1e17 else 0.0)
        dist_low = ((b1.c - self._session_low) / atr_safe
                     if self._session_low < 1e17 else 0.0)

        return {
            "hour_of_day": hour,
            "minute_of_hour": minute,
            "is_rth": is_rth,
            "minutes_since_rth_open": minutes_since_rth,
            "distance_from_session_high_atr": dist_high,
            "distance_from_session_low_atr": dist_low,
        }

    # ----- Helper functions -----
    def _vol_vs_20avg(self, v: float, skip_last: int = 0) -> float:
        """Volume divided by 20-bar average, excluding skip_last bars."""
        n = len(self._recent_1m)
        start = max(0, n - 20 - skip_last)
        end = n - skip_last
        bars = [self._recent_1m[i] for i in range(start, end)]
        if not bars:
            return 1.0
        avg = sum(b.v for b in bars) / len(bars)
        return v / avg if avg > 0 else 1.0

    def _vol_vs_Navg(self, v: float, N: int, skip_last: int = 0) -> float:
        n = len(self._recent_1m)
        start = max(0, n - N - skip_last)
        end = n - skip_last
        bars = [self._recent_1m[i] for i in range(start, end)]
        if not bars:
            return 1.0
        avg = sum(b.v for b in bars) / len(bars)
        return v / avg if avg > 0 else 1.0

    def _percentile_rank(self, v: float, vals: list) -> float:
        if not vals:
            return 0.5
        below = sum(1 for x in vals if x < v)
        return below / len(vals)

    # ----- Finalization -----
    def on_stop(self):
        if self._trades:
            df = pd.DataFrame(self._trades)
            Path(self.config.output_file).parent.mkdir(
                parents=True, exist_ok=True)
            df.to_parquet(self.config.output_file, index=False)
            self.log.info(f"Saved {len(df):,} trades to {self.config.output_file}")
        if self._skipped:
            df = pd.DataFrame(self._skipped)
            Path(self.config.skipped_file).parent.mkdir(
                parents=True, exist_ok=True)
            df.to_parquet(self.config.skipped_file, index=False)
            self.log.info(f"Saved {len(df):,} skipped to "
                           f"{self.config.skipped_file}")

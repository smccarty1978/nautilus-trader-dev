"""Delayed Checkpoint Collector v3.

For each 1m EMA3/9 confirmed flip + bar+1 HH/LL confirmation, records
21 checkpoint states at T = {0, 30, 60, ..., 600} seconds after signal.

Per checkpoint:
  - alive_at_T (regime still active strictly after observation_time)
  - fillable_at_T (regime still active at fill_time)
  - state fields (regime context, MA, micro, time/session, ATR)
  - forward path from fill (MFE/MAE peak + snapshots + bracket races)

Spec: 1m_delayed_checkpoint_collector_v2.md + COLLECTOR_V3_REVISIONS_FINAL.md
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
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

CT = pytz.timezone("America/Chicago")
NQ_MULT = 20.0
COMMISSION = 5.0

# Checkpoint times (seconds after signal_time)
CHECKPOINT_TS = list(range(0, 601, 30))  # 0, 30, 60, ..., 600 — 21 points

# Forward snapshot horizons (seconds after fill_time) — drop 240s per Rev 1
FWD_SNAPSHOT_TS = [30, 60, 90, 120, 180, 300]

# Root T0 forward snapshot horizons
ROOT_FWD_SNAPSHOT_TS = [30, 60, 90, 120, 180, 300]

# Bracket race definitions (pt_atr, sl_atr, name)
BRACKETS = [
    (1.00, 1.00, "pt100_before_sl100"),
    (1.50, 1.00, "pt150_before_sl100"),
    (2.00, 1.00, "pt200_before_sl100"),
    (3.00, 1.50, "pt300_before_sl150"),
]


# --------------------------------------------------------------------
# Local indicators (lightweight, raw float input)
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
        else:
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


class RegimeState:
    """EMA3/9 sticky regime on H/L/C for one timeframe."""

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
        # Flip history: list of (bar_index, new_regime)
        self.flip_history = deque(maxlen=20)

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
            self.flip_history.append((self.completed_bars, new_r))
        else:
            self.bars_in_regime += 1
        return self.regime


# --------------------------------------------------------------------
# Bar records
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


class Bar30sRecord:
    __slots__ = ("ts_event", "o", "h", "l", "c", "v")

    def __init__(self, ts_event, o, h, l, c, v):
        self.ts_event = ts_event
        self.o = o
        self.h = h
        self.l = l
        self.c = c
        self.v = v


# --------------------------------------------------------------------
# Forward path tracker — per checkpoint, from fill price
# --------------------------------------------------------------------

class ForwardPathTracker:
    """Tracks forward MFE/MAE + snapshots + bracket races from a fill price."""

    def __init__(self, fill_price: float, direction: int, atr: float,
                 fill_ts: int, snap_ts_offsets):
        self.fill_price = fill_price
        self.direction = direction
        self.atr = max(atr, 1e-9)
        self.fill_ts = fill_ts
        self.peak_mfe = 0.0
        self.peak_mae = 0.0
        self.mfe_at_peak_mae = 0.0
        self.mae_at_peak_mfe = 0.0
        self.mfe_first = 0  # +1 if MFE 0.25 reached before MAE 0.25
        self._mfe_first_decided = False

        # Time snapshots
        self.snap_ts_offsets = snap_ts_offsets
        self.snap_mfe = {t: None for t in snap_ts_offsets}
        self.snap_mae = {t: None for t in snap_ts_offsets}

        # Bracket race outcomes: 1 = PT first, 0 = SL first, None = neither
        self.bracket_outcomes = {tag: None for _, _, tag in BRACKETS}

    def update(self, h: float, l: float, ts_event: int) -> None:
        d = self.direction
        if d == 1:
            mfe_now = max(0.0, (h - self.fill_price) / self.atr)
            mae_now = max(0.0, (self.fill_price - l) / self.atr)
        else:
            mfe_now = max(0.0, (self.fill_price - l) / self.atr)
            mae_now = max(0.0, (h - self.fill_price) / self.atr)

        if mfe_now > self.peak_mfe:
            self.peak_mfe = mfe_now
            self.mae_at_peak_mfe = self.peak_mae
        if mae_now > self.peak_mae:
            self.peak_mae = mae_now
            self.mfe_at_peak_mae = self.peak_mfe

        if not self._mfe_first_decided:
            if self.peak_mfe >= 0.25:
                self.mfe_first = 1
                self._mfe_first_decided = True
            elif self.peak_mae >= 0.25:
                self.mfe_first = 0
                self._mfe_first_decided = True

        # Time snapshots
        elapsed = (ts_event - self.fill_ts) / 1_000_000_000.0
        for t_off in self.snap_ts_offsets:
            if self.snap_mfe[t_off] is None and elapsed >= t_off:
                self.snap_mfe[t_off] = self.peak_mfe
                self.snap_mae[t_off] = self.peak_mae

        # Bracket races
        for pt_atr, sl_atr, tag in BRACKETS:
            if self.bracket_outcomes[tag] is not None:
                continue
            pt_hit = self.peak_mfe >= pt_atr
            sl_hit = self.peak_mae >= sl_atr
            if pt_hit and sl_hit:
                # Use intra-bar order — both hit this bar; check which extreme first
                # Conservative: if both, use SL first (pessimistic)
                # But we can't tell intra-bar order from bar OHLC. Use peak ratio.
                # Prefer the one whose threshold ratio is more decisive.
                # Simplest: PT-first if mfe_now/pt_atr > mae_now/sl_atr.
                if d == 1:
                    cur_mfe = (h - self.fill_price) / self.atr
                    cur_mae = (self.fill_price - l) / self.atr
                else:
                    cur_mfe = (self.fill_price - l) / self.atr
                    cur_mae = (h - self.fill_price) / self.atr
                if cur_mfe / pt_atr > cur_mae / sl_atr:
                    self.bracket_outcomes[tag] = 1
                else:
                    self.bracket_outcomes[tag] = 0
            elif pt_hit:
                self.bracket_outcomes[tag] = 1
            elif sl_hit:
                self.bracket_outcomes[tag] = 0


# --------------------------------------------------------------------
# Strategy Config
# --------------------------------------------------------------------

class DCContextConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    output_file: str = (
        "studies/1m_delayed_checkpoint_context/results/trades_unsaved.parquet"
    )
    warmup_1m_bars: int = 150


# --------------------------------------------------------------------
# Main Collector
# --------------------------------------------------------------------

class DelayedCheckpointCollector(Strategy):
    """v3 collector with 21 checkpoints per confirmed flip."""

    def __init__(self, config: DCContextConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # Indicators on 1m
        self.regime_1m = RegimeState()
        self.atr_14 = AverageTrueRange(14)
        self.sma20_1m = LocalSMA(20)
        self.sma50_1m = LocalSMA(50)
        self._prev_sma20 = deque(maxlen=6)
        self._prev_sma50 = deque(maxlen=11)
        self._prev_ema3 = deque(maxlen=6)

        # 30s aggregation + regime
        self._1s_for_30s = []
        self.regime_30s = RegimeState()
        self.sma20_30s = LocalSMA(20)
        self._recent_30s = deque(maxlen=30)
        # Volume avg over last 20 30s bars (for vol_vs_20avg_30s)

        # 5m aggregation + regime
        self._1m_for_5m = []
        self.regime_5m = RegimeState()
        self.sma20_5m = LocalSMA(20)
        self._recent_5m = deque(maxlen=20)

        # 1s buffer (for micro features at observation times)
        self._recent_1s = deque(maxlen=180)  # 3 min

        # 1m bar buffer (for pre-flip context, MA history)
        self._recent_1m = deque(maxlen=70)
        self._1m_count = 0
        self._warmup = False

        # Volume direction accumulator for current 1m
        self._current_1m_minute = None
        self._current_1m_up_vol = 0.0
        self._current_1m_down_vol = 0.0

        # Session high/low (resets at 17:00 CT)
        self._session_start_key = None
        self._session_high = -1e18
        self._session_low = 1e18

        # 1m flip-pending state for confirmation
        self._flip_pending = None

        # Active trades — list of TradeState
        self._active_trades = []

        # Output records
        self._trades = []
        self._trade_counter = 0

        # Diagnostics
        self._diag = {
            "flips": 0, "confirmed": 0, "skipped_no_hh_ll": 0,
            "regime_exit": 0,
        }

    # --------------------------------------------------------------
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

    # --------------------------------------------------------------
    # 1s bar handling
    # --------------------------------------------------------------
    def _on_1s(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        self._recent_1s.append((ts, o, h, l, c, v))
        self._update_session(ts, h, l)

        # 1m volume direction accumulator (for current 1m bar)
        minute_floor = (ts // 60_000_000_000) * 60_000_000_000
        if self._current_1m_minute != minute_floor:
            self._current_1m_minute = minute_floor
            self._current_1m_up_vol = 0.0
            self._current_1m_down_vol = 0.0
        if c > o:
            self._current_1m_up_vol += v
        elif c < o:
            self._current_1m_down_vol += v

        # 30s aggregation: emit when ts at 30s boundary AFTER buffer
        # Convention: 30s bar covers [A, A+30s). Emit when 1s arrives at A+30s.
        # Buffer 1s bars; when a new 1s arrives whose ts_event is at a 30s
        # boundary, emit the previous 30s bar BEFORE adding current 1s to
        # the new 30s buffer.
        if (ts % 30_000_000_000) == 0 and len(self._1s_for_30s) > 0:
            self._emit_30s_bar(ts)

        self._1s_for_30s.append((ts, o, h, l, c, v))

        # Update active trade forward-path trackers
        for ts_data in self._active_trades:
            for tracker in ts_data.fwd_trackers.values():
                if tracker is not None and ts >= tracker.fill_ts:
                    tracker.update(h, l, ts)
            # Root T0 tracker
            if ts_data.root_tracker is not None \
                    and ts >= ts_data.root_tracker.fill_ts:
                ts_data.root_tracker.update(h, l, ts)

    def _emit_30s_bar(self, current_ts: int):
        """Aggregate buffered 1s bars into a 30s bar that just closed."""
        bars = self._1s_for_30s
        if not bars:
            return
        agg_o = bars[0][1]
        agg_h = max(b[2] for b in bars)
        agg_l = min(b[3] for b in bars)
        agg_c = bars[-1][4]
        agg_v = sum(b[5] for b in bars)
        # 30s bar's "close time" = current_ts (the boundary just hit)
        agg_ts = current_ts - 30_000_000_000  # bar opens 30s ago
        rec = Bar30sRecord(agg_ts, agg_o, agg_h, agg_l, agg_c, agg_v)
        self._recent_30s.append(rec)
        self.regime_30s.update(agg_h, agg_l, agg_c)
        self.sma20_30s.update(agg_c)
        self._1s_for_30s = []

        # Process checkpoints aligned to this 30s close
        # observation_time_T = signal_time + T (must equal current_ts)
        # fill_time_T = obs_time + 30s
        for ts_data in self._active_trades:
            for T in CHECKPOINT_TS:
                obs_time = ts_data.signal_time + T * 1_000_000_000
                fill_time = obs_time + 30_000_000_000
                if obs_time == current_ts and not ts_data.cps[T].observation_done:
                    self._snap_checkpoint(ts_data, T, current_ts)
                if fill_time == current_ts and not ts_data.cps[T].fill_done:
                    self._snap_fill(ts_data, T, current_ts)

    # --------------------------------------------------------------
    # Session high/low
    # --------------------------------------------------------------
    def _update_session(self, ts: int, h: float, l: float):
        dt_ct = pd.Timestamp(ts, unit="ns", tz="UTC").astimezone(CT)
        if dt_ct.hour >= 17:
            key = str(dt_ct.date())
        else:
            key = str((dt_ct - pd.Timedelta(days=1)).date())
        if key != self._session_start_key:
            self._session_start_key = key
            self._session_high = h
            self._session_low = l
        else:
            if h > self._session_high:
                self._session_high = h
            if l < self._session_low:
                self._session_low = l

    # --------------------------------------------------------------
    # 1m bar handling
    # --------------------------------------------------------------
    def _on_1m(self, bar: Bar):
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume) if hasattr(bar, "volume") else 0.0

        rec = Bar1mRecord(ts, o, h, l, c, v,
                           self._current_1m_up_vol,
                           self._current_1m_down_vol)
        self._recent_1m.append(rec)
        self._1m_count += 1

        # Update 1m indicators
        self.atr_14.update_raw(h, l, c)
        self.sma20_1m.update(c)
        self.sma50_1m.update(c)
        if self.sma20_1m.initialized:
            self._prev_sma20.append(self.sma20_1m.value)
        if self.sma50_1m.initialized:
            self._prev_sma50.append(self.sma50_1m.value)

        prev_regime_1m = self.regime_1m.regime
        new_r = self.regime_1m.update(h, l, c)
        if self.regime_1m.ema3.initialized:
            self._prev_ema3.append(self.regime_1m.ema3.value)

        warmup_done = self._is_warmed_up()
        if not self._warmup and warmup_done:
            self._warmup = True

        # Update 5m aggregation
        self._update_5m(rec)

        if not self._warmup:
            return

        # 1m flip detection
        flip_occurred = (prev_regime_1m != 0 and new_r != 0
                          and prev_regime_1m != new_r)
        if flip_occurred:
            self._diag["flips"] += 1
            atr = self.atr_14.value if self.atr_14.initialized else 0.0
            self._flip_pending = {
                "flip_bar": rec,
                "atr_at_flip": atr,
                "direction": new_r,
                "flip_time": ts,
                "prior_regime_duration_bars":
                    self.regime_1m.bars_in_regime - 1,
            }
        elif self._flip_pending is not None:
            # bar+1 — check confirmation
            self._check_confirmation(rec)

        # Active trades: append 1m bars + check for 1m regime exit
        self._update_active_trades_on_1m(rec, prev_regime_1m, new_r,
                                            flip_occurred)

    def _is_warmed_up(self) -> bool:
        return (self._1m_count >= self.config.warmup_1m_bars
                and self.atr_14.initialized
                and self.sma50_1m.initialized
                and self.regime_5m.ema9.initialized)

    def _update_5m(self, rec: Bar1mRecord):
        self._1m_for_5m.append(rec)
        minute_of_hour = (rec.ts_event // 60_000_000_000) % 60
        if minute_of_hour % 5 == 4 and len(self._1m_for_5m) >= 5:
            sub = self._1m_for_5m[-5:]
            agg_h = max(b.h for b in sub)
            agg_l = min(b.l for b in sub)
            agg_c = sub[-1].c
            agg_v = sum(b.v for b in sub)
            self.regime_5m.update(agg_h, agg_l, agg_c)
            self.sma20_5m.update(agg_c)
            # Store record for later context queries
            agg_ts = sub[0].ts_event
            self._recent_5m.append({
                "ts": agg_ts, "h": agg_h, "l": agg_l, "c": agg_c,
                "v": agg_v, "regime": self.regime_5m.regime,
            })
            self._1m_for_5m = []

    def _check_confirmation(self, bar1: Bar1mRecord):
        fp = self._flip_pending
        if fp is None:
            return
        flip_bar = fp["flip_bar"]
        d = fp["direction"]
        if d == 1:
            made = bar1.h > flip_bar.h
        else:
            made = bar1.l < flip_bar.l

        if not made:
            self._diag["skipped_no_hh_ll"] += 1
            self._flip_pending = None
            return

        # CONFIRMED — register trade with 21 checkpoints
        self._diag["confirmed"] += 1
        self._trade_counter += 1
        signal_time = bar1.ts_event + 60_000_000_000  # bar+1 close = ts_event + 60s
        signal_bar_close = signal_time
        atr = fp["atr_at_flip"]

        # T0 fill: use next 30s bar OPEN after signal_time
        # signal_time is at a 1m boundary (= 30s boundary)
        # Per spec convention: fill = next 30s bar open AFTER decision
        # T0 observation = signal_time, T0 fill = signal_time + 30s
        t0_fill_time = signal_time + 30_000_000_000

        # Find current bar+1 close price for T0 candidate fill estimate
        # Realistic t0 fill price will be set when 1s bar at t0_fill_time arrives
        ts_data = TradeState(
            trade_id=self._trade_counter,
            signal_time=signal_time,
            signal_direction=d,
            signal_bar_close=signal_bar_close,
            atr_at_signal=atr,
            t0_fill_time=t0_fill_time,
            flip_bar=flip_bar,
            bar1=bar1,
            collector_root_features=self._snap_root_features(
                flip_bar, bar1, fp, signal_time),
        )
        # Initialize 21 checkpoint slots
        for T in CHECKPOINT_TS:
            ts_data.cps[T] = CheckpointState(T)
        # Initialize 5m flip checkpoint tracking
        ts_data.regime_5m_at_signal = self.regime_5m.regime
        ts_data.regime_5m_aligned_at_signal = (
            1 if ts_data.regime_5m_at_signal == d else 0)
        ts_data.regime_5m_flip_checkpoint = (
            0 if ts_data.regime_5m_aligned_at_signal == 1 else None)

        # Initialize 30s alignment anchor
        ts_data.regime_30s_at_signal = self.regime_30s.regime
        ts_data.regime_30s_aligned_at_signal = (
            1 if ts_data.regime_30s_at_signal == d else 0)

        # T=0 observation will be snapped when 1s bar at signal_time arrives
        # (which triggers _emit_30s_bar with fresh 30s regime state).
        self._active_trades.append(ts_data)
        self._flip_pending = None

    def _update_active_trades_on_1m(self, rec: Bar1mRecord,
                                      prev_regime: int, new_r: int,
                                      flip_occurred: bool):
        """For each active trade: append bar to history, check exit, update
        continuation tracking."""
        opposite_flip = False
        for ts_data in self._active_trades:
            d = ts_data.signal_direction
            # Record 1m bar for continuation analysis
            if rec.ts_event >= ts_data.signal_time:
                ts_data.bars_since_signal_1m.append(rec)
                # Continuation: HH for long, LL for short
                if len(ts_data.bars_since_signal_1m) >= 2:
                    prev_b = ts_data.bars_since_signal_1m[-2]
                    if d == 1:
                        if rec.h > prev_b.h:
                            ts_data.continuation_count += 1
                            ts_data.consec_continuation += 1
                            ts_data.bars_since_continuation = 0
                        else:
                            ts_data.consec_continuation = 0
                            ts_data.bars_since_continuation += 1
                    else:
                        if rec.l < prev_b.l:
                            ts_data.continuation_count += 1
                            ts_data.consec_continuation += 1
                            ts_data.bars_since_continuation = 0
                        else:
                            ts_data.consec_continuation = 0
                            ts_data.bars_since_continuation += 1

            # 1m regime exit check (opposite regime)
            if flip_occurred and new_r == -d:
                ts_data.regime_exit_time = rec.ts_event + 60_000_000_000
                ts_data.regime_exit_price = rec.c

        # Trades that hit regime exit → finalize and remove
        still_active = []
        for ts_data in self._active_trades:
            if ts_data.regime_exit_time is not None:
                self._finalize_trade(ts_data)
                self._diag["regime_exit"] += 1
            elif (rec.ts_event - ts_data.signal_time
                    > 3600 * 1_000_000_000):
                # Safety: force close after 1 hour even if regime didn't flip
                ts_data.regime_exit_time = rec.ts_event + 60_000_000_000
                ts_data.regime_exit_price = rec.c
                self._finalize_trade(ts_data)
            else:
                still_active.append(ts_data)
        self._active_trades = still_active

        # Update 5m flip checkpoint tracking
        # Track whether 5m flipped to align since signal
        for ts_data in self._active_trades:
            if ts_data.regime_5m_flip_checkpoint is not None:
                continue
            cur_5m = self.regime_5m.regime
            d = ts_data.signal_direction
            if cur_5m == d:
                # 5m just flipped to align — find which checkpoint we're at
                elapsed = (rec.ts_event + 60_000_000_000
                           - ts_data.signal_time) / 1_000_000_000
                # Find nearest checkpoint T <= elapsed
                t_match = None
                for T in CHECKPOINT_TS:
                    if T <= elapsed:
                        t_match = T
                if t_match is not None:
                    ts_data.regime_5m_flip_checkpoint = t_match

    # --------------------------------------------------------------
    # Checkpoint snapping
    # --------------------------------------------------------------
    def _snap_checkpoint(self, ts_data, T: int, current_ts: int):
        """Snap state fields at observation time."""
        cp = ts_data.cps[T]
        cp.observation_done = True
        cp.observation_time = current_ts

        d = ts_data.signal_direction
        atr = ts_data.atr_at_signal if ts_data.atr_at_signal > 0 else 1e-9

        # alive_at_T: regime still active strictly after observation_time
        # If regime_exit_time is None, regime is still active.
        # If regime_exit_time > observation_time, alive=1.
        # If regime_exit_time <= observation_time, alive=0.
        if ts_data.regime_exit_time is None or \
                ts_data.regime_exit_time > current_ts:
            cp.alive_at_T = 1
            cp.dead_before_T = 0
        else:
            cp.alive_at_T = 0
            cp.dead_before_T = 1
            return  # Don't snap state if dead

        # Spent move from T0 to checkpoint
        # T0 fill price not yet known if ts_data.t0_fill_price is None
        # at very early checkpoints — but for T=0 observation == signal_time,
        # fill = signal+30s. So at T=0 obs, T0 fill hasn't happened yet.
        # Use signal-bar close as proxy for T0 to allow spent-move computation.
        # Actually spec says "spent move from T0 to checkpoint". If T=0,
        # spent move is 0. For T>0, need t0 fill price.
        if T == 0:
            cp.pnl_from_t0_to_T_atr = 0.0
        elif ts_data.t0_fill_price is not None:
            current_px = self._current_1s_close()
            cp.pnl_from_t0_to_T_atr = (
                (current_px - ts_data.t0_fill_price) * d / atr)
        else:
            cp.pnl_from_t0_to_T_atr = float("nan")

        # Regime context at checkpoint
        cp.regime_1m_T = self.regime_1m.regime
        cp.regime_30s_T = self.regime_30s.regime
        cp.regime_30s_aligned_T = 1 if cp.regime_30s_T == d else 0
        cp.regime_30s_duration_bars_T = self.regime_30s.bars_in_regime
        cp.regime_5m_T = self.regime_5m.regime
        cp.regime_5m_aligned_T = 1 if cp.regime_5m_T == d else 0
        cp.regime_5m_duration_bars_T = self.regime_5m.bars_in_regime

        # 5m flipped to align by T (Section C per-checkpoint version)
        if ts_data.regime_5m_aligned_at_signal == 1:
            cp.regime_5m_flipped_to_align_by_T = 0  # already aligned
        else:
            cp.regime_5m_flipped_to_align_by_T = (
                1 if cp.regime_5m_aligned_T == 1 else 0)
        cp.regime_5m_changed_during_delay_by_T = (
            1 if cp.regime_5m_T != ts_data.regime_5m_at_signal else 0)

        # MA / price context
        atr_safe = atr
        sma20 = self.sma20_30s.value if self.sma20_30s.initialized else \
            self._current_1s_close()
        sma20_5m = self.sma20_5m.value if self.sma20_5m.initialized else \
            self._current_1s_close()
        cur_px = self._current_1s_close()

        cp.ema3_slope_30s_atr_T = 0.0  # not tracking 30s ema slope history
        eh3_30 = (self.regime_30s.emaH_3.value
                   if self.regime_30s.emaH_3.initialized else cur_px)
        el3_30 = (self.regime_30s.emaL_3.value
                   if self.regime_30s.emaL_3.initialized else cur_px)
        cp.ema_spread_30s_atr_T = (eh3_30 - el3_30) / atr_safe
        cp.price_vs_sma20_30s_atr_T = (cur_px - sma20) / atr_safe

        # Current 30s bar in progress
        if self._1s_for_30s:
            cur_30s_h = max(b[2] for b in self._1s_for_30s)
            cur_30s_l = min(b[3] for b in self._1s_for_30s)
            cp.bar_range_30s_current_atr_T = (cur_30s_h - cur_30s_l) / atr_safe
        else:
            cp.bar_range_30s_current_atr_T = 0.0

        cp.ema3_slope_5m_atr_T = 0.0  # not tracking 5m slope history
        eh3_5 = (self.regime_5m.emaH_3.value
                  if self.regime_5m.emaH_3.initialized else cur_px)
        el3_5 = (self.regime_5m.emaL_3.value
                  if self.regime_5m.emaL_3.initialized else cur_px)
        cp.ema_spread_5m_atr_T = (eh3_5 - el3_5) / atr_safe
        cp.price_vs_sma20_5m_atr_T = (cur_px - sma20_5m) / atr_safe

        # Micro context (last 12 1s bars)
        bars12 = list(self._recent_1s)[-12:] if len(self._recent_1s) >= 1 else []
        if len(bars12) >= 2:
            up_count = 0
            down_count = 0
            prev_c = bars12[0][4]
            for b in bars12[1:]:
                if b[4] > prev_c:
                    up_count += 1
                elif b[4] < prev_c:
                    down_count += 1
                prev_c = b[4]
            if d == 1:
                cp.micro_same_dir_count_12s_T = up_count
                cp.micro_opp_dir_count_12s_T = down_count
            else:
                cp.micro_same_dir_count_12s_T = down_count
                cp.micro_opp_dir_count_12s_T = up_count
            total = up_count + down_count
            cp.micro_aligned_T = (
                1 if total > 0 and cp.micro_same_dir_count_12s_T / total >= 0.583
                else 0)
            cp.micro_opposing_T = (
                1 if total > 0 and cp.micro_opp_dir_count_12s_T / total >= 0.583
                else 0)
            # Net return ATR (from first to last close in window)
            cp.micro_net_return_atr_T = (
                (bars12[-1][4] - bars12[0][4]) * d / atr_safe)
            # Range compression (last 6 vs prior 6)
            if len(bars12) >= 12:
                last6 = bars12[-6:]
                prior6 = bars12[-12:-6]
                last6_r = sum(b[2] - b[3] for b in last6) / 6
                prior6_r = sum(b[2] - b[3] for b in prior6) / 6
                cp.micro_range_compression_T = (
                    last6_r / prior6_r if prior6_r > 0 else 1.0)
                # body pct avg
                bodies = []
                for b in bars12:
                    rng = b[2] - b[3]
                    if rng > 0:
                        bodies.append(abs(b[4] - b[1]) / rng)
                cp.micro_body_pct_avg_T = (
                    sum(bodies) / len(bodies) if bodies else 0.5)
            else:
                cp.micro_range_compression_T = 1.0
                cp.micro_body_pct_avg_T = 0.5
        else:
            cp.micro_same_dir_count_12s_T = 0
            cp.micro_opp_dir_count_12s_T = 0
            cp.micro_aligned_T = 0
            cp.micro_opposing_T = 0
            cp.micro_net_return_atr_T = 0.0
            cp.micro_range_compression_T = 1.0
            cp.micro_body_pct_avg_T = 0.5

        # Time/session at checkpoint
        dt_ct = pd.Timestamp(current_ts, unit="ns",
                              tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute
        cp.is_rth_T = 1 if 510 <= ct_min < 900 else 0
        cp.hour_of_day_T = dt_ct.hour
        cp.minute_of_hour_T = dt_ct.minute
        cp.minutes_since_rth_open_T = ct_min - 510
        cp.distance_from_session_high_atr_T = (
            (self._session_high - cur_px) / atr_safe
            if self._session_high > -1e17 else 0.0)
        cp.distance_from_session_low_atr_T = (
            (cur_px - self._session_low) / atr_safe
            if self._session_low < 1e17 else 0.0)

        # ATR at T (use current ATR_14 value)
        cp.atr_14_at_T = self.atr_14.value if self.atr_14.initialized else 0.0

        # Volume features (cheap: ratio over last 12 1s bars)
        cp.vol_total_30s_recent_T = (
            sum(b[5] for b in self._1s_for_30s)
            if self._1s_for_30s else 0.0)
        # vol vs 20-bar avg of 30s bars
        if len(self._recent_30s) >= 20:
            avg_30s_vol = sum(
                b.v for b in list(self._recent_30s)[-20:]) / 20
            cp.vol_vs_20avg_30s_T = (
                cp.vol_total_30s_recent_T / avg_30s_vol
                if avg_30s_vol > 0 else 1.0)
        else:
            cp.vol_vs_20avg_30s_T = 1.0

        # Forward regime remaining (placeholder; finalized later)
        # cp.forward_regime_remaining_s_T set in finalize

        # Momentum continuation
        cp.continuation_count_since_signal_T = ts_data.continuation_count
        cp.consecutive_continuation_bars_T = ts_data.consec_continuation
        cp.bars_since_last_continuation_T = ts_data.bars_since_continuation

    def _snap_fill(self, ts_data, T: int, current_ts: int):
        """Record fill price + start forward path tracker."""
        cp = ts_data.cps[T]
        cp.fill_done = True
        cp.fill_time = current_ts

        # If alive_at_T was 0, NaN out (already done in observation snap)
        if cp.alive_at_T == 0:
            cp.fillable_at_T = 0
            return

        # fillable_at_T: regime still active at fill_time (strictly > or =)
        if ts_data.regime_exit_time is None or \
                ts_data.regime_exit_time > current_ts:
            cp.fillable_at_T = 1
        else:
            cp.fillable_at_T = 0
            return

        # Fill price = open of 1s bar at current_ts (its open)
        # Find the 1s bar whose ts_event = current_ts
        fill_price = None
        for b_ts, b_o, _, _, _, _ in reversed(self._recent_1s):
            if b_ts == current_ts:
                fill_price = b_o
                break
        if fill_price is None:
            cp.fillable_at_T = 0
            return

        cp.fill_price = fill_price

        # Set t0_fill_price if T==0
        if T == 0:
            ts_data.t0_fill_price = fill_price

        # Start forward path tracker
        d = ts_data.signal_direction
        atr = ts_data.atr_at_signal
        ts_data.fwd_trackers[T] = ForwardPathTracker(
            fill_price=fill_price, direction=d, atr=atr,
            fill_ts=current_ts, snap_ts_offsets=FWD_SNAPSHOT_TS)

        # Special case: T=0 also creates the root tracker
        if T == 0:
            ts_data.root_tracker = ForwardPathTracker(
                fill_price=fill_price, direction=d, atr=atr,
                fill_ts=current_ts,
                snap_ts_offsets=ROOT_FWD_SNAPSHOT_TS)

    def _current_1s_close(self) -> float:
        """Most recent 1s close price."""
        if self._recent_1s:
            return self._recent_1s[-1][4]
        return 0.0

    # --------------------------------------------------------------
    # Root features snap (at signal_time)
    # --------------------------------------------------------------
    def _snap_root_features(self, flip_bar, bar1, fp, signal_time) -> dict:
        atr = fp["atr_at_flip"]
        atr_safe = max(atr, 1e-9)
        d = fp["direction"]
        feats = {}

        # Flip bar anatomy
        rng_f = flip_bar.h - flip_bar.l
        body_f = abs(flip_bar.c - flip_bar.o)
        feats.update({
            "flip_range_atr": rng_f / atr_safe,
            "flip_body_atr": body_f / atr_safe,
            "flip_body_pct": body_f / rng_f if rng_f > 0 else 0,
            "flip_close_location":
                (flip_bar.c - flip_bar.l) / rng_f if rng_f > 0 else 0.5,
            "flip_upper_wick_pct":
                (flip_bar.h - max(flip_bar.o, flip_bar.c)) / rng_f
                if rng_f > 0 else 0,
            "flip_lower_wick_pct":
                (min(flip_bar.o, flip_bar.c) - flip_bar.l) / rng_f
                if rng_f > 0 else 0,
            "flip_volume": flip_bar.v,
            "flip_vol_vs_20avg": self._vol_vs_Navg(flip_bar.v, 20, 0),
        })
        # Prior bar reference
        prior_c = prior_h = prior_l = flip_bar.c
        if len(self._recent_1m) >= 2:
            pb = self._recent_1m[-2]
            prior_c, prior_h, prior_l = pb.c, pb.h, pb.l
        feats.update({
            "flip_close_vs_prior_close_atr":
                (flip_bar.c - prior_c) * d / atr_safe,
            "flip_high_vs_prior_high_atr":
                (flip_bar.h - prior_h) * d / atr_safe,
            "flip_low_vs_prior_low_atr":
                (flip_bar.l - prior_l) * d / atr_safe,
        })
        up_v = flip_bar.up_vol
        dn_v = flip_bar.down_vol
        feats["flip_bar_bullish_volume_pct"] = (
            up_v / (up_v + dn_v) if (up_v + dn_v) > 0 else 0.5)

        # Bar+1 anatomy
        rng_b1 = bar1.h - bar1.l
        body_b1 = abs(bar1.c - bar1.o)
        hh_amt = ((bar1.h - flip_bar.h) / atr_safe if d == 1
                   else (flip_bar.l - bar1.l) / atr_safe)
        feats.update({
            "bar1_range_atr": rng_b1 / atr_safe,
            "bar1_body_atr": body_b1 / atr_safe,
            "bar1_body_pct": body_b1 / rng_b1 if rng_b1 > 0 else 0,
            "bar1_close_location":
                (bar1.c - bar1.l) / rng_b1 if rng_b1 > 0 else 0.5,
            "bar1_upper_wick_pct":
                (bar1.h - max(bar1.o, bar1.c)) / rng_b1
                if rng_b1 > 0 else 0,
            "bar1_lower_wick_pct":
                (min(bar1.o, bar1.c) - bar1.l) / rng_b1
                if rng_b1 > 0 else 0,
            "bar1_volume": bar1.v,
            "bar1_vol_vs_flip_vol": bar1.v / flip_bar.v if flip_bar.v > 0 else 1,
            "bar1_hh_amount_atr": hh_amt,
            "bar1_close_vs_flip_close_atr":
                (bar1.c - flip_bar.c) * d / atr_safe,
            "bar1_close_above_flip_close":
                1 if (bar1.c - flip_bar.c) * d > 0 else 0,
        })
        b1_above_mid = 0
        if rng_b1 > 0:
            loc = (bar1.c - bar1.l) / rng_b1
            b1_above_mid = (1 if (d == 1 and loc > 0.5)
                             or (d == -1 and loc < 0.5) else 0)
        feats["bar1_close_above_50pct_range"] = b1_above_mid
        up_v = bar1.up_vol
        dn_v = bar1.down_vol
        feats["bar1_bullish_volume_pct"] = (
            up_v / (up_v + dn_v) if (up_v + dn_v) > 0 else 0.5)

        # Two-bar sequence
        h_max = max(flip_bar.h, bar1.h)
        l_min = min(flip_bar.l, bar1.l)
        two_rng = h_max - l_min
        two_body = (bar1.c - flip_bar.o) * d
        feats.update({
            "two_bar_range_atr": two_rng / atr_safe,
            "two_bar_body_atr": two_body / atr_safe,
            "two_bar_close_vs_open_pct":
                two_body / two_rng if two_rng > 0 else 0,
            "two_bar_volume_total": flip_bar.v + bar1.v,
            "two_bar_vol_vs_40avg":
                self._vol_vs_Navg(flip_bar.v + bar1.v, 40, 1) / 2,
            "flip_low_to_bar1_high_atr":
                (bar1.h - flip_bar.l) / atr_safe if d == 1
                else (flip_bar.h - bar1.l) / atr_safe,
        })

        # Pre-flip 1m context
        n = len(self._recent_1m)
        def bb(k): return self._recent_1m[-k] if k <= n else None
        pre3 = [bb(k) for k in (3, 4, 5)]
        pre5 = [bb(k) for k in (3, 4, 5, 6, 7)]
        pre6 = [bb(k) for k in (6, 7, 8)]
        pf3_rng = (
            (max(b.h for b in pre3) - min(b.l for b in pre3)) / atr_safe
            if all(b is not None for b in pre3) else 0)
        pf5_rng = (
            (max(b.h for b in pre5) - min(b.l for b in pre5)) / atr_safe
            if all(b is not None for b in pre5) else 0)
        pf3_body = (
            sum((b.c - b.o) * d for b in pre3) / atr_safe
            if all(b is not None for b in pre3) else 0)
        vt = 1.0
        if (all(b is not None for b in pre3)
                and all(b is not None for b in pre6)):
            r = sum(b.v for b in pre3) / 3
            p = sum(b.v for b in pre6) / 3
            vt = r / p if p > 0 else 1.0
        consec = 0
        for k in range(3, 20):
            b = bb(k)
            if b is None:
                break
            if d == 1 and b.c > b.o:
                consec += 1
            elif d == -1 and b.c < b.o:
                consec += 1
            else:
                break
        feats.update({
            "prior_regime_duration_bars": fp["prior_regime_duration_bars"],
            "regime_flips_last_30min": sum(
                1 for (bc, _) in self.regime_1m.flip_history
                if bc > self._1m_count - 30),
            "regime_flips_last_60min": sum(
                1 for (bc, _) in self.regime_1m.flip_history
                if bc > self._1m_count - 60),
            "pre_flip_3bar_range_atr": pf3_rng,
            "pre_flip_5bar_range_atr": pf5_rng,
            "pre_flip_3bar_body_direction": pf3_body,
            "pre_flip_volume_trend": vt,
            "consecutive_trend_bars_pre_flip": consec,
            "atr_14": atr,
        })

        # 1m MA context
        sma20 = (self.sma20_1m.value
                  if self.sma20_1m.initialized else flip_bar.c)
        sma50 = (self.sma50_1m.value
                  if self.sma50_1m.initialized else flip_bar.c)
        sma20_slope = ((self._prev_sma20[-1] - self._prev_sma20[-6])
                        / atr_safe if len(self._prev_sma20) >= 6 else 0)
        sma50_slope = ((self._prev_sma50[-1] - self._prev_sma50[-11])
                        / atr_safe if len(self._prev_sma50) >= 11 else 0)
        ema3_slope = ((self._prev_ema3[-1] - self._prev_ema3[-6])
                       / atr_safe if len(self._prev_ema3) >= 6 else 0)
        ema3 = (self.regime_1m.ema3.value
                 if self.regime_1m.ema3.initialized else flip_bar.c)
        ema9 = (self.regime_1m.ema9.value
                 if self.regime_1m.ema9.initialized else flip_bar.c)
        eh3 = (self.regime_1m.emaH_3.value
                if self.regime_1m.emaH_3.initialized else flip_bar.c)
        el3 = (self.regime_1m.emaL_3.value
                if self.regime_1m.emaL_3.initialized else flip_bar.c)
        feats.update({
            "price_vs_sma20_atr": (flip_bar.c - sma20) / atr_safe,
            "price_vs_sma50_atr": (flip_bar.c - sma50) / atr_safe,
            "sma20_slope_atr": sma20_slope,
            "sma50_slope_atr": sma50_slope,
            "sma20_vs_sma50_atr": (sma20 - sma50) / atr_safe,
            "ema3_slope_atr": ema3_slope,
            "ema_spread_atr": (eh3 - el3) / atr_safe,
            "ema3_ema9_spread_atr": (ema3 - ema9) / atr_safe,
        })

        # 1m volume analysis
        last_20 = list(self._recent_1m)[-20:]
        avg20 = sum(b.v for b in last_20) / len(last_20) if last_20 else 0
        last_10 = list(self._recent_1m)[-10:]
        up10 = sum(b.v for b in last_10 if b.c > b.o)
        dn10 = sum(b.v for b in last_10 if b.c < b.o)
        up20 = sum(b.v for b in last_20 if b.c > b.o)
        dn20 = sum(b.v for b in last_20 if b.c < b.o)
        feats.update({
            "vol_1m_20avg": avg20,
            "vol_ratio_up_down_10bar": (
                up10 / dn10 if dn10 > 0 else (999.0 if up10 > 0 else 1.0)),
            "vol_ratio_up_down_20bar": (
                up20 / dn20 if dn20 > 0 else (999.0 if up20 > 0 else 1.0)),
            "vol_acceleration_5bar": vt,  # reuse pre_flip_volume_trend approx
            "high_vol_bar_count_10":
                sum(1 for b in last_10 if b.v > 1.5 * avg20),
            "flip_bar_vol_rank_20": self._pct_rank(flip_bar.v,
                                                     [b.v for b in last_20[:-1]]),
            "bar1_vol_rank_20": self._pct_rank(bar1.v,
                                                 [b.v for b in last_20[:-1]]),
            "cumulative_volume_bias_10": (
                (up10 - dn10) / (up10 + dn10) if (up10 + dn10) > 0 else 0.0),
        })

        # Time/session at signal
        dt_ct = pd.Timestamp(signal_time, unit="ns",
                              tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute
        feats.update({
            "hour_of_day": dt_ct.hour,
            "minute_of_hour": dt_ct.minute,
            "is_rth": 1 if 510 <= ct_min < 900 else 0,
            "minutes_since_rth_open": ct_min - 510,
            "distance_from_session_high_atr":
                (self._session_high - flip_bar.c) / atr_safe
                if self._session_high > -1e17 else 0,
            "distance_from_session_low_atr":
                (flip_bar.c - self._session_low) / atr_safe
                if self._session_low < 1e17 else 0,
            "year": dt_ct.year,
            "date": str(dt_ct.date()),
            "session": "RTH" if 510 <= ct_min < 900 else "ETH",
        })

        return feats

    def _vol_vs_Navg(self, v: float, N: int, skip_last: int = 0) -> float:
        n = len(self._recent_1m)
        start = max(0, n - N - skip_last)
        end = n - skip_last
        bars = [self._recent_1m[i] for i in range(start, end)]
        if not bars:
            return 1.0
        avg = sum(b.v for b in bars) / len(bars)
        return v / avg if avg > 0 else 1.0

    @staticmethod
    def _pct_rank(v: float, vals) -> float:
        if not vals:
            return 0.5
        below = sum(1 for x in vals if x < v)
        return below / len(vals)

    # --------------------------------------------------------------
    # Trade finalization
    # --------------------------------------------------------------
    def _finalize_trade(self, ts_data):
        """Build flat record and append to _trades."""
        # BACKFILL: For checkpoints whose observation never snapped (data gap
        # at exact 30s boundary or trade ended before checkpoint), determine
        # alive/dead state from regime_exit_time vs observation_time.
        for T in CHECKPOINT_TS:
            cp = ts_data.cps[T]
            if not cp.observation_done:
                obs_time = ts_data.signal_time + T * 1_000_000_000
                if (ts_data.regime_exit_time is not None
                        and ts_data.regime_exit_time <= obs_time):
                    # Trade had already exited by this checkpoint
                    cp.alive_at_T = 0
                    cp.dead_before_T = 1
                    cp.fillable_at_T = 0
                # else: trade was alive but data gap prevented snap
                # — leave alive_at_T = None → NaN
        record = {}
        # Root metadata
        record["trade_id"] = ts_data.trade_id
        record["signal_time"] = pd.Timestamp(
            ts_data.signal_time, unit="ns", tz="UTC")
        record["signal_ts"] = ts_data.signal_time
        record["signal_direction"] = ts_data.signal_direction
        record["t0_fill_time"] = pd.Timestamp(
            ts_data.t0_fill_time, unit="ns", tz="UTC")
        record["t0_fill_price"] = ts_data.t0_fill_price
        record["regime_exit_time"] = (
            pd.Timestamp(ts_data.regime_exit_time, unit="ns", tz="UTC")
            if ts_data.regime_exit_time else pd.NaT)
        record["regime_exit_price"] = ts_data.regime_exit_price
        record["atr_at_signal"] = ts_data.atr_at_signal

        # Root anchors (Rev 7) — derive from T=0 cp to ensure consistency
        cp0 = ts_data.cps[0]
        if cp0.alive_at_T == 1:
            record["regime_30s_aligned_t0"] = cp0.regime_30s_aligned_T
            record["regime_5m_aligned_t0"] = cp0.regime_5m_aligned_T
        else:
            # Fallback to early-snap value if T=0 not snapped
            record["regime_30s_aligned_t0"] = (
                ts_data.regime_30s_aligned_at_signal)
            record["regime_5m_aligned_t0"] = (
                ts_data.regime_5m_aligned_at_signal)

        # Rev 5: regime_5m_flip_checkpoint
        record["regime_5m_flip_checkpoint"] = (
            ts_data.regime_5m_flip_checkpoint
            if ts_data.regime_5m_flip_checkpoint is not None
            else float("nan"))

        # Root features
        record.update(ts_data.collector_root_features)

        # Root T0 forward path
        if ts_data.root_tracker is not None:
            rt = ts_data.root_tracker
            record["t0_peak_mfe_atr"] = rt.peak_mfe
            record["t0_peak_mae_atr"] = rt.peak_mae
            record["t0_mfe_first"] = rt.mfe_first
            record["t0_mae_at_peak_mfe"] = rt.mae_at_peak_mfe
            record["t0_mfe_at_peak_mae"] = rt.mfe_at_peak_mae
            for t_off in ROOT_FWD_SNAPSHOT_TS:
                v = rt.snap_mfe[t_off]
                record[f"t0_mfe_at_{t_off}s"] = (
                    v if v is not None else float("nan"))
                v = rt.snap_mae[t_off]
                record[f"t0_mae_at_{t_off}s"] = (
                    v if v is not None else float("nan"))
            # T0 forward regime PnL
            if (ts_data.regime_exit_price is not None
                    and ts_data.t0_fill_price is not None):
                record["t0_forward_regime_pnl_atr"] = (
                    (ts_data.regime_exit_price - ts_data.t0_fill_price)
                    * ts_data.signal_direction / max(ts_data.atr_at_signal,
                                                       1e-9))
                record["t0_forward_regime_pnl_dollars"] = (
                    record["t0_forward_regime_pnl_atr"]
                    * ts_data.atr_at_signal * NQ_MULT - COMMISSION)
            else:
                record["t0_forward_regime_pnl_atr"] = float("nan")
                record["t0_forward_regime_pnl_dollars"] = float("nan")
        else:
            for k in ["t0_peak_mfe_atr", "t0_peak_mae_atr",
                       "t0_mfe_first", "t0_mae_at_peak_mfe",
                       "t0_mfe_at_peak_mae",
                       "t0_forward_regime_pnl_atr",
                       "t0_forward_regime_pnl_dollars"]:
                record[k] = float("nan")
            for t_off in ROOT_FWD_SNAPSHOT_TS:
                record[f"t0_mfe_at_{t_off}s"] = float("nan")
                record[f"t0_mae_at_{t_off}s"] = float("nan")

        # Per-checkpoint fields
        for T in CHECKPOINT_TS:
            cp = ts_data.cps[T]
            tag = f"{T:03d}"

            # Section A: Availability
            record[f"alive_at_T_{tag}"] = (
                cp.alive_at_T if cp.alive_at_T is not None else float("nan"))
            record[f"dead_before_T_{tag}"] = cp.dead_before_T
            record[f"fillable_at_T_{tag}"] = (
                cp.fillable_at_T if cp.fillable_at_T is not None
                else float("nan"))
            record[f"checkpoint_time_T_{tag}"] = (
                pd.Timestamp(cp.observation_time, unit="ns", tz="UTC")
                if cp.observation_time is not None else pd.NaT)
            record[f"checkpoint_elapsed_s_T_{tag}"] = T
            record[f"checkpoint_entry_fill_time_T_{tag}"] = (
                pd.Timestamp(cp.fill_time, unit="ns", tz="UTC")
                if cp.fillable_at_T == 1 and cp.fill_time is not None
                else pd.NaT)
            record[f"checkpoint_entry_fill_price_T_{tag}"] = (
                cp.fill_price if cp.fillable_at_T == 1 else float("nan"))
            record[f"checkpoint_bars_since_signal_1m_T_{tag}"] = (
                len(ts_data.bars_since_signal_1m)
                if cp.alive_at_T == 1 else float("nan"))

            # If dead_before_T = 1, all other fields NaN
            if cp.dead_before_T == 1:
                for sect in ["b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]:
                    self._nan_section(record, tag, sect)
                continue

            # Section B: Spent move
            record[f"pnl_from_t0_to_T_atr_{tag}"] = (
                cp.pnl_from_t0_to_T_atr if cp.pnl_from_t0_to_T_atr is not None
                else float("nan"))
            record[f"pnl_from_t0_to_T_dollars_{tag}"] = (
                cp.pnl_from_t0_to_T_atr * ts_data.atr_at_signal * NQ_MULT
                if cp.pnl_from_t0_to_T_atr is not None
                else float("nan"))
            record[f"mfe_from_t0_to_T_atr_{tag}"] = float("nan")  # placeholder
            record[f"mae_from_t0_to_T_atr_{tag}"] = float("nan")  # placeholder

            # Section C: Regime context
            record[f"regime_1m_T_{tag}"] = cp.regime_1m_T
            record[f"regime_30s_T_{tag}"] = cp.regime_30s_T
            record[f"regime_30s_aligned_T_{tag}"] = cp.regime_30s_aligned_T
            record[f"regime_30s_duration_bars_T_{tag}"] = (
                cp.regime_30s_duration_bars_T)
            record[f"regime_5m_T_{tag}"] = cp.regime_5m_T
            record[f"regime_5m_aligned_T_{tag}"] = cp.regime_5m_aligned_T
            record[f"regime_5m_duration_bars_T_{tag}"] = (
                cp.regime_5m_duration_bars_T)
            record[f"regime_5m_flipped_to_align_by_T_{tag}"] = (
                cp.regime_5m_flipped_to_align_by_T)
            record[f"regime_5m_changed_during_delay_by_T_{tag}"] = (
                cp.regime_5m_changed_during_delay_by_T)

            # Section E: MA / price context
            record[f"ema3_slope_30s_atr_T_{tag}"] = cp.ema3_slope_30s_atr_T
            record[f"ema_spread_30s_atr_T_{tag}"] = cp.ema_spread_30s_atr_T
            record[f"price_vs_sma20_30s_atr_T_{tag}"] = (
                cp.price_vs_sma20_30s_atr_T)
            record[f"bar_range_30s_current_atr_T_{tag}"] = (
                cp.bar_range_30s_current_atr_T)
            record[f"ema3_slope_5m_atr_T_{tag}"] = cp.ema3_slope_5m_atr_T
            record[f"ema_spread_5m_atr_T_{tag}"] = cp.ema_spread_5m_atr_T
            record[f"price_vs_sma20_5m_atr_T_{tag}"] = (
                cp.price_vs_sma20_5m_atr_T)

            # Section F: Price vs key levels
            record[f"distance_from_session_high_atr_T_{tag}"] = (
                cp.distance_from_session_high_atr_T)
            record[f"distance_from_session_low_atr_T_{tag}"] = (
                cp.distance_from_session_low_atr_T)
            record[f"atr_14_at_T_{tag}"] = cp.atr_14_at_T

            # Section G: Momentum continuation
            record[f"continuation_count_since_signal_T_{tag}"] = (
                cp.continuation_count_since_signal_T)
            record[f"consecutive_continuation_bars_T_{tag}"] = (
                cp.consecutive_continuation_bars_T)
            record[f"bars_since_last_continuation_T_{tag}"] = (
                cp.bars_since_last_continuation_T)

            # Section H: Micro context
            record[f"micro_same_dir_count_12s_T_{tag}"] = (
                cp.micro_same_dir_count_12s_T)
            record[f"micro_opp_dir_count_12s_T_{tag}"] = (
                cp.micro_opp_dir_count_12s_T)
            record[f"micro_aligned_T_{tag}"] = cp.micro_aligned_T
            record[f"micro_opposing_T_{tag}"] = cp.micro_opposing_T
            record[f"micro_net_return_atr_T_{tag}"] = cp.micro_net_return_atr_T
            record[f"micro_range_compression_T_{tag}"] = (
                cp.micro_range_compression_T)
            record[f"micro_body_pct_avg_T_{tag}"] = cp.micro_body_pct_avg_T

            # Section I: Volume
            record[f"vol_total_30s_recent_T_{tag}"] = cp.vol_total_30s_recent_T
            record[f"vol_vs_20avg_30s_T_{tag}"] = cp.vol_vs_20avg_30s_T

            # Section J: Time/session  (already has atr_14_at_T above)
            record[f"is_rth_T_{tag}"] = cp.is_rth_T
            record[f"hour_of_day_T_{tag}"] = cp.hour_of_day_T
            record[f"minute_of_hour_T_{tag}"] = cp.minute_of_hour_T
            record[f"minutes_since_rth_open_T_{tag}"] = (
                cp.minutes_since_rth_open_T)

            # Section K: Forward path (only if fillable_at_T = 1)
            tracker = ts_data.fwd_trackers.get(T)
            if cp.fillable_at_T == 1 and tracker is not None:
                record[f"forward_peak_mfe_atr_T_{tag}"] = tracker.peak_mfe
                record[f"forward_peak_mae_atr_T_{tag}"] = tracker.peak_mae
                record[f"forward_mfe_first_T_{tag}"] = tracker.mfe_first
                record[f"forward_mae_at_peak_mfe_T_{tag}"] = (
                    tracker.mae_at_peak_mfe)
                record[f"forward_mfe_at_peak_mae_T_{tag}"] = (
                    tracker.mfe_at_peak_mae)
                for t_off in FWD_SNAPSHOT_TS:
                    v = tracker.snap_mfe[t_off]
                    record[f"forward_mfe_at_{t_off}s_T_{tag}"] = (
                        v if v is not None else float("nan"))
                    v = tracker.snap_mae[t_off]
                    record[f"forward_mae_at_{t_off}s_T_{tag}"] = (
                        v if v is not None else float("nan"))
                # Forward regime PnL
                if (ts_data.regime_exit_price is not None
                        and cp.fill_price is not None):
                    pnl_atr = (
                        (ts_data.regime_exit_price - cp.fill_price)
                        * ts_data.signal_direction
                        / max(ts_data.atr_at_signal, 1e-9))
                    record[f"forward_regime_pnl_atr_T_{tag}"] = pnl_atr
                    record[f"forward_regime_pnl_pts_T_{tag}"] = (
                        (ts_data.regime_exit_price - cp.fill_price)
                        * ts_data.signal_direction)
                    record[f"forward_regime_pnl_dollars_T_{tag}"] = (
                        pnl_atr * ts_data.atr_at_signal * NQ_MULT - COMMISSION)
                    record[f"forward_regime_duration_s_T_{tag}"] = (
                        (ts_data.regime_exit_time - cp.fill_time) / 1e9)
                    record[f"forward_regime_remaining_s_T_{tag}"] = (
                        record[f"forward_regime_duration_s_T_{tag}"])
                else:
                    record[f"forward_regime_pnl_atr_T_{tag}"] = float("nan")
                    record[f"forward_regime_pnl_pts_T_{tag}"] = float("nan")
                    record[f"forward_regime_pnl_dollars_T_{tag}"] = float("nan")
                    record[f"forward_regime_duration_s_T_{tag}"] = float("nan")
                    record[f"forward_regime_remaining_s_T_{tag}"] = float("nan")

                # Section L: Bracket races
                for _, _, b_name in BRACKETS:
                    v = tracker.bracket_outcomes[b_name]
                    record[f"forward_{b_name}_T_{tag}"] = (
                        v if v is not None else float("nan"))
            else:
                # NaN out forward path
                self._nan_section(record, tag, "k")
                self._nan_section(record, tag, "l")

        self._trades.append(record)

    def _nan_section(self, record, tag, section):
        """Set all fields in a section to NaN for a checkpoint."""
        # Helper to set keys based on section
        keys = []
        if section == "b":
            keys = ["pnl_from_t0_to_T_atr", "pnl_from_t0_to_T_dollars",
                    "mfe_from_t0_to_T_atr", "mae_from_t0_to_T_atr"]
        elif section == "c":
            keys = ["regime_1m_T", "regime_30s_T", "regime_30s_aligned_T",
                    "regime_30s_duration_bars_T", "regime_5m_T",
                    "regime_5m_aligned_T", "regime_5m_duration_bars_T",
                    "regime_5m_flipped_to_align_by_T",
                    "regime_5m_changed_during_delay_by_T"]
        elif section == "e":
            keys = ["ema3_slope_30s_atr_T", "ema_spread_30s_atr_T",
                    "price_vs_sma20_30s_atr_T", "bar_range_30s_current_atr_T",
                    "ema3_slope_5m_atr_T", "ema_spread_5m_atr_T",
                    "price_vs_sma20_5m_atr_T"]
        elif section == "f":
            keys = ["distance_from_session_high_atr_T",
                    "distance_from_session_low_atr_T", "atr_14_at_T"]
        elif section == "g":
            keys = ["continuation_count_since_signal_T",
                    "consecutive_continuation_bars_T",
                    "bars_since_last_continuation_T"]
        elif section == "h":
            keys = ["micro_same_dir_count_12s_T", "micro_opp_dir_count_12s_T",
                    "micro_aligned_T", "micro_opposing_T",
                    "micro_net_return_atr_T", "micro_range_compression_T",
                    "micro_body_pct_avg_T"]
        elif section == "i":
            keys = ["vol_total_30s_recent_T", "vol_vs_20avg_30s_T"]
        elif section == "j":
            keys = ["is_rth_T", "hour_of_day_T", "minute_of_hour_T",
                    "minutes_since_rth_open_T"]
        elif section == "k":
            keys = ["forward_peak_mfe_atr_T", "forward_peak_mae_atr_T",
                    "forward_mfe_first_T", "forward_mae_at_peak_mfe_T",
                    "forward_mfe_at_peak_mae_T",
                    "forward_regime_pnl_atr_T", "forward_regime_pnl_pts_T",
                    "forward_regime_pnl_dollars_T",
                    "forward_regime_duration_s_T",
                    "forward_regime_remaining_s_T"]
            for t_off in FWD_SNAPSHOT_TS:
                keys.append(f"forward_mfe_at_{t_off}s_T")
                keys.append(f"forward_mae_at_{t_off}s_T")
        elif section == "l":
            keys = [f"forward_{b_name}_T" for _, _, b_name in BRACKETS]

        for k in keys:
            record[f"{k}_{tag}"] = float("nan")

    # --------------------------------------------------------------
    def on_stop(self):
        # Finalize any remaining active trades
        for ts_data in self._active_trades:
            if ts_data.regime_exit_time is None:
                if self._recent_1m:
                    last = self._recent_1m[-1]
                    ts_data.regime_exit_time = last.ts_event + 60_000_000_000
                    ts_data.regime_exit_price = last.c
            self._finalize_trade(ts_data)
        self._active_trades = []

        if self._trades:
            df = pd.DataFrame(self._trades)
            Path(self.config.output_file).parent.mkdir(
                parents=True, exist_ok=True)
            df.to_parquet(self.config.output_file, index=False)
            self.log.info(
                f"Saved {len(df):,} trades × {len(df.columns)} cols → "
                f"{self.config.output_file}")

        self.log.info(f"Diag: {self._diag}")


# --------------------------------------------------------------------
# Per-trade state container
# --------------------------------------------------------------------

class TradeState:
    """Holds all state for one active trade across its lifetime."""

    __slots__ = (
        "trade_id", "signal_time", "signal_direction",
        "signal_bar_close", "atr_at_signal",
        "t0_fill_time", "t0_fill_price",
        "flip_bar", "bar1",
        "collector_root_features",
        "cps", "fwd_trackers", "root_tracker",
        "regime_exit_time", "regime_exit_price",
        "bars_since_signal_1m",
        "continuation_count", "consec_continuation",
        "bars_since_continuation",
        "regime_5m_at_signal", "regime_5m_aligned_at_signal",
        "regime_5m_flip_checkpoint",
        "regime_30s_at_signal", "regime_30s_aligned_at_signal",
    )

    def __init__(self, trade_id, signal_time, signal_direction,
                 signal_bar_close, atr_at_signal, t0_fill_time,
                 flip_bar, bar1, collector_root_features):
        self.trade_id = trade_id
        self.signal_time = signal_time
        self.signal_direction = signal_direction
        self.signal_bar_close = signal_bar_close
        self.atr_at_signal = atr_at_signal
        self.t0_fill_time = t0_fill_time
        self.t0_fill_price = None
        self.flip_bar = flip_bar
        self.bar1 = bar1
        self.collector_root_features = collector_root_features

        # 21 checkpoints
        self.cps = {}  # T -> CheckpointState
        self.fwd_trackers = {}  # T -> ForwardPathTracker
        self.root_tracker = None

        self.regime_exit_time = None
        self.regime_exit_price = None
        self.bars_since_signal_1m = []
        self.continuation_count = 0
        self.consec_continuation = 0
        self.bars_since_continuation = 0

        self.regime_5m_at_signal = 0
        self.regime_5m_aligned_at_signal = 0
        self.regime_5m_flip_checkpoint = None  # 0 / T / None
        self.regime_30s_at_signal = 0
        self.regime_30s_aligned_at_signal = 0


class CheckpointState:
    """Per-checkpoint state container."""

    __slots__ = (
        "T", "observation_done", "observation_time",
        "fill_done", "fill_time", "fill_price",
        "alive_at_T", "dead_before_T", "fillable_at_T",
        # B
        "pnl_from_t0_to_T_atr",
        # C
        "regime_1m_T", "regime_30s_T", "regime_30s_aligned_T",
        "regime_30s_duration_bars_T", "regime_5m_T", "regime_5m_aligned_T",
        "regime_5m_duration_bars_T", "regime_5m_flipped_to_align_by_T",
        "regime_5m_changed_during_delay_by_T",
        # E
        "ema3_slope_30s_atr_T", "ema_spread_30s_atr_T",
        "price_vs_sma20_30s_atr_T", "bar_range_30s_current_atr_T",
        "ema3_slope_5m_atr_T", "ema_spread_5m_atr_T",
        "price_vs_sma20_5m_atr_T",
        # F + J ATR
        "distance_from_session_high_atr_T",
        "distance_from_session_low_atr_T", "atr_14_at_T",
        # G
        "continuation_count_since_signal_T",
        "consecutive_continuation_bars_T",
        "bars_since_last_continuation_T",
        # H
        "micro_same_dir_count_12s_T", "micro_opp_dir_count_12s_T",
        "micro_aligned_T", "micro_opposing_T",
        "micro_net_return_atr_T", "micro_range_compression_T",
        "micro_body_pct_avg_T",
        # I
        "vol_total_30s_recent_T", "vol_vs_20avg_30s_T",
        # J time/session
        "is_rth_T", "hour_of_day_T", "minute_of_hour_T",
        "minutes_since_rth_open_T",
    )

    def __init__(self, T):
        self.T = T
        self.observation_done = False
        self.observation_time = None
        self.fill_done = False
        self.fill_time = None
        self.fill_price = None
        self.alive_at_T = None
        self.dead_before_T = 0
        self.fillable_at_T = None
        # All other fields default to None and are populated in _snap_checkpoint
        for slot in self.__slots__:
            if not hasattr(self, slot):
                object.__setattr__(self, slot, None)

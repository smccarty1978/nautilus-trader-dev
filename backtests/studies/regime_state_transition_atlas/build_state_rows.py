"""NQ Regime State Transition Atlas - State Rows Collector.

Replays NQ 1s bars (2021-2026), tracks 1m parent regimes, and snapshots causal
state features at each closed 1m bar checkpoint inside the regime.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from collections import deque
from pathlib import Path
import numpy as np
import pandas as pd
import pytz
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from collectors.collector_v2.registry import CompletedBarRegistry, CompletedBarState
from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket
from collectors.collector_v2.regime_engine import RegimeStateEngine

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
OUT = Path("studies/regime_state_transition_atlas/results")
CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000
MULT = 20.0
TFS = ("5m", "1m", "5s")

RTH_START_MIN = 510  # 8:30 AM Central Time
RTH_END_MIN = 900    # 3:00 PM Central Time


class _EMA:
    def __init__(self, period: int):
        self.alpha = 2.0 / (period + 1)
        self.value = None

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class FeatureManager:
    def __init__(self):
        self.closes = {tf: deque(maxlen=512) for tf in TFS}
        self.vols_1m = deque(maxlen=20)
        
        self.emas = {
            "1m": {3: _EMA(3), 9: _EMA(9), 13: _EMA(13), 21: _EMA(21)}
        }
        
        self.ema_hists = {
            "1m": {p: deque(maxlen=6) for p in (3, 9, 13, 21)}
        }
        
        self.ema_slopes_hist = {
            "1m": {p: deque(maxlen=2) for p in (3, 9, 13, 21)}
        }

    def on_bar_closed(self, tf: str, completed: _OpenBucket, atr: float, d: int):
        c = completed.close
        self.closes[tf].append(c)
        
        if tf == "1m":
            for p, ema in self.emas["1m"].items():
                val = ema.update(c)
                self.ema_hists["1m"][p].append(val)
                
                # Calculate causal direction-normalized slope
                slope = self.get_slope_val(p, atr, d)
                if not np.isnan(slope):
                    self.ema_slopes_hist["1m"][p].append(slope)

    def get_slope_val(self, period: int, atr: float, d: int) -> float:
        hist = self.ema_hists["1m"][period]
        if len(hist) < 2 or atr <= 0 or np.isnan(atr):
            return float("nan")
        return (hist[-1] - hist[-2]) * d / atr

    def get_slope(self, period: int) -> float:
        hist = self.ema_slopes_hist["1m"].get(period)
        if not hist or len(hist) < 1:
            return float("nan")
        return hist[-1]

    def get_slope_change(self, period: int) -> float:
        hist = self.ema_slopes_hist["1m"].get(period)
        if not hist or len(hist) < 2:
            return float("nan")
        return hist[-1] - hist[0]

    def get_dist(self, period: int, c: float, d: int, atr: float) -> float:
        v = self.emas["1m"][period].value
        if v is None or atr <= 0 or np.isnan(atr):
            return float("nan")
        return d * (c - v) / atr


class StateRowsReplay:
    def __init__(self, year: int):
        self._year = year
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._engines = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(
            on_bucket_closed=self.on_bucket_closed,
            timeframes=TFS
        )
        self._fm = FeatureManager()
        
        self._prev_regimes = {tf: 0 for tf in TFS}
        
        # 1m parent regime tracking
        self._active_1m_regime = 0
        self._ts_1m_regime_start = 0
        self._px_1m_entry = 0.0
        self._atr_1m_entry_cached = 1.0
        self._1m_regime_id = 0
        self._1m_regime_index = 0
        self._bar_index = 0
        
        self._1m_regime_high = 0.0
        self._1m_regime_low = 0.0
        self._1m_regime_high_prior = 0.0
        self._1m_regime_low_prior = 0.0
        
        # Continuation & pullback tracking
        self._bars_since_last_continuation = 0
        self._consecutive_no_continuation_bars = 0
        self._continuation_count_so_far = 0
        self._max_pullback_depth_so_far_atr = 0.0
        self._prior_bar_made_continuation = 0
        self._prior_bar_failed_continuation = 0
        self._prior_pullback_from_peak_atr = 0.0
        self._prior_close = 0.0
        
        self._aligned_volume_since_regime_start = 0.0
        self._opposed_volume_since_regime_start = 0.0
        self._cum_signed_volume_since_regime_start = 0.0
        
        # Symbols history
        self._regime_bar_symbols = []
        
        # 5s flips tracking
        self._5s_flip_count = 0
        self._5s_opposed_flip_count = 0
        self._ts_5s_aligned_start = None
        self._5s_flip_timestamps = deque()
        
        # Bar 1 confirmed tracking
        self._bar1_confirmed_flag = 0
        self._bar1_made_c = 0
        self._first_two_bars_made_c = 0
        
        self.records = []
        
        self._regime_flipped_flag = False
        self._prev_regime_dir = 0

    def on_bucket_closed(self, tf: str, completed: _OpenBucket):
        self._engines[tf].on_bar_closed(completed)
        
        state = self._reg.get(tf)
        if state is None:
            return
            
        atr = state.atr
        now = state.regime
        prev = self._prev_regimes[tf]
        flipped = (now != prev and now != 0)
        
        # Update FeatureManager
        self._fm.on_bar_closed(tf, completed, atr, self._active_1m_regime if self._active_1m_regime != 0 else 1)
        
        if tf == "1m":
            if flipped:
                self._regime_flipped_flag = True
                self._prev_regime_dir = prev
                
                # Reset new 1m regime
                self._active_1m_regime = now
                self._ts_1m_regime_start = state.close_ts
                self._px_1m_entry = state.close
                self._atr_1m_entry_cached = state.atr if (state.atr > 0 and not np.isnan(state.atr)) else 1.0
                self._1m_regime_index += 1
                self._1m_regime_id = self._year * 100_000 + self._1m_regime_index
                self._bar_index = 0
                
                self._1m_regime_high = state.close
                self._1m_regime_low = state.close
                self._1m_regime_high_prior = state.close
                self._1m_regime_low_prior = state.close
                
                self._bars_since_last_continuation = 0
                self._consecutive_no_continuation_bars = 0
                self._continuation_count_so_far = 0
                self._max_pullback_depth_so_far_atr = 0.0
                self._prior_bar_made_continuation = 0
                self._prior_bar_failed_continuation = 0
                self._prior_pullback_from_peak_atr = 0.0
                self._prior_close = state.close
                
                self._aligned_volume_since_regime_start = 0.0
                self._opposed_volume_since_regime_start = 0.0
                self._cum_signed_volume_since_regime_start = 0.0
                self._regime_bar_symbols = []
                
                self._5s_flip_count = 0
                self._5s_opposed_flip_count = 0
                self._ts_5s_aligned_start = None
                self._5s_flip_timestamps.clear()
                
                self._bar1_confirmed_flag = 0
                self._bar1_made_c = 0
                self._first_two_bars_made_c = 0
            else:
                if self._active_1m_regime != 0:
                    self._bar_index += 1
                    
                    # Snap checkpoint and features before updating state for next bar
                    if self._bar_index <= 30:
                        features = self._snapshot_features(completed, state)
                        self.records.append(features)
                        
                    # Update prior variables for the next bar
                    d = self._active_1m_regime
                    made_continuation = 0
                    if d == 1:
                        if completed.high > self._1m_regime_high_prior:
                            made_continuation = 1
                            self._1m_regime_high_prior = completed.high
                    else:
                        if completed.low < self._1m_regime_low_prior:
                            made_continuation = 1
                            self._1m_regime_low_prior = completed.low
                            
                    if self._bar_index == 1:
                        self._bar1_made_c = made_continuation
                        self._bar1_confirmed_flag = made_continuation
                    elif self._bar_index == 2:
                        self._first_two_bars_made_c = int(self._bar1_made_c & made_continuation)
                        
                    if made_continuation:
                        self._bars_since_last_continuation = 0
                        self._consecutive_no_continuation_bars = 0
                        self._continuation_count_so_far += 1
                    else:
                        self._bars_since_last_continuation += 1
                        self._consecutive_no_continuation_bars += 1
                        
                    self._prior_bar_made_continuation = made_continuation
                    self._prior_bar_failed_continuation = 1 - made_continuation
                    self._prior_close = completed.close
                    
                    current_pnl = (completed.close - self._px_1m_entry) * d / self._atr_1m_entry_cached
                    mfe = (self._1m_regime_high - self._px_1m_entry) * d / self._atr_1m_entry_cached
                    self._prior_pullback_from_peak_atr = max(0.0, mfe - current_pnl)
                    self._max_pullback_depth_so_far_atr = max(self._max_pullback_depth_so_far_atr, self._prior_pullback_from_peak_atr)
                    
                    # Track volume indicators
                    signed_vol = completed.volume * np.sign(completed.close - completed.open) * d
                    self._cum_signed_volume_since_regime_start += signed_vol
                    if (completed.close - completed.open) * d > 0:
                        self._aligned_volume_since_regime_start += completed.volume
                    elif (completed.close - completed.open) * d < 0:
                        self._opposed_volume_since_regime_start += completed.volume
            
            # Append volume to vols_1m AFTER snapshotting/evaluation is done for this bar!
            self._fm.vols_1m.append(completed.volume)
            
        elif tf == "5s":
            if flipped:
                self._5s_flip_timestamps.append(completed.close_ts)
                if self._active_1m_regime != 0:
                    self._5s_flip_count += 1
                    if now == -self._active_1m_regime:
                        self._5s_opposed_flip_count += 1
                    
                    if now == self._active_1m_regime:
                        self._ts_5s_aligned_start = completed.close_ts
                    else:
                        self._ts_5s_aligned_start = None
                        
        self._prev_regimes[tf] = now

    def on_1s(self, o, h, l, c, v, tse, tsi):
        self._regime_flipped_flag = False
        self._prev_regime_dir = 0
        
        self._agg.on_1s_bar(int(tsi), o, h, l, c, v)
        
        if self._active_1m_regime != 0:
            self._1m_regime_high = max(self._1m_regime_high, h)
            self._1m_regime_low = min(self._1m_regime_low, l)
            
        self._prev_regimes["1m"] = self._reg.get("1m").regime if self._reg.get("1m") is not None else 0

    def _snapshot_features(self, completed_1m: _OpenBucket, state_1m: CompletedBarState) -> dict:
        self._reg.audit_provenance(completed_1m.close_ts)
        c = completed_1m.close
        o = completed_1m.open
        h = completed_1m.high
        l = completed_1m.low
        d = state_1m.regime
        atr_ref = self._atr_1m_entry_cached
        
        # 1. Identity
        ct_dt = pd.Timestamp(int(completed_1m.open_ts), tz="UTC").tz_convert(CT)
        date_str = ct_dt.strftime("%Y-%m-%d")
        min_ct = ct_dt.hour * 60 + ct_dt.minute
        is_rth = int(RTH_START_MIN <= min_ct < RTH_END_MIN)
        session = "RTH" if is_rth else "ETH"
        
        # 2. Bar Anatomy
        bar_return_atr = (c - o) * d / atr_ref
        bar_range_atr = (h - l) / atr_ref
        bar_body_atr = abs(c - o) / atr_ref
        bar_body_pct = abs(c - o) / (h - l) if (h - l) > 0 else 0.0
        
        if d == 1:
            bar_close_location = (c - l) / (h - l) if (h - l) > 0 else 0.5
            upper_wick_pct = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0.0
            lower_wick_pct = (min(o, c) - l) / (h - l) if (h - l) > 0 else 0.0
        else:
            bar_close_location = (h - c) / (h - l) if (h - l) > 0 else 0.5
            upper_wick_pct = (min(o, c) - l) / (h - l) if (h - l) > 0 else 0.0
            lower_wick_pct = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0.0
            
        bar_direction_aligned = np.sign(c - o) * d
        
        # 3. Continuation / HH-LL State
        made_continuation = 0
        if d == 1:
            if h > self._1m_regime_high_prior:
                made_continuation = 1
        else:
            if l < self._1m_regime_low_prior:
                made_continuation = 1
                
        # 4. Pullback / Recovery State
        current_pnl = (c - self._px_1m_entry) * d / atr_ref
        mfe_val = (self._1m_regime_high - self._px_1m_entry) * d / atr_ref
        mae_val = (self._px_1m_entry - self._1m_regime_low) * d / atr_ref
        pullback_val = max(0.0, mfe_val - current_pnl)
        
        if d == 1:
            pullback_depth_current_bar = max(0.0, self._1m_regime_high_prior - l) / atr_ref
        else:
            pullback_depth_current_bar = max(0.0, h - self._1m_regime_low_prior) / atr_ref
            
        max_pb_so_far = max(self._max_pullback_depth_so_far_atr, pullback_val)
        
        recovered_prior_peak = 0
        if self._bar_index > 1:
            prior_peak = self._1m_regime_high_prior if d == 1 else self._1m_regime_low_prior
            if self._prior_pullback_from_peak_atr > 0.0:
                if d == 1 and h >= prior_peak:
                    recovered_prior_peak = 1
                elif d == -1 and l <= prior_peak:
                    recovered_prior_peak = 1
                    
        recovered_above_midpoint = 0
        recovered_above_close = 0
        if self._bar_index > 1:
            prior_high = getattr(self, "_prior_bar_high", c)
            prior_low = getattr(self, "_prior_bar_low", c)
            prior_midpoint = (prior_high + prior_low) / 2.0
            
            if d == 1:
                recovered_above_midpoint = int(c > prior_midpoint)
                recovered_above_close = int(c > self._prior_close)
            else:
                recovered_above_midpoint = int(c < prior_midpoint)
                recovered_above_close = int(c < self._prior_close)
                
        self._prior_bar_high = h
        self._prior_bar_low = l
        
        # 5. Symbolic alphabet for pattern mapping
        symbol = "P"
        if made_continuation:
            symbol = "C"
        elif current_pnl < 0:
            symbol = "F"
        elif self._bar_index > 1:
            close_pos_vs_prior = (c - self._prior_close) * d > 0
            if close_pos_vs_prior and self._prior_pullback_from_peak_atr > 0.0:
                symbol = "R"
                
        self._regime_bar_symbols.append(symbol)
        
        last_1_bar_pattern = symbol
        last_2_bar_pattern = "".join(self._regime_bar_symbols[-2:])
        last_3_bar_pattern = "".join(self._regime_bar_symbols[-3:])
        last_4_bar_pattern = "".join(self._regime_bar_symbols[-4:])
        
        # Pullback variables
        if self._bar_index == 1:
            self._bar1_pullback_depth = pullback_val
        bar1_pb_val = getattr(self, "_bar1_pullback_depth", 0.0)
        
        # 6. 5s Context
        s5s = self._reg.get("5s")
        reg_5s = s5s.regime if s5s is not None else 0
        regime_5s_aligned = int(reg_5s == d and reg_5s != 0)
        
        now_ts = completed_1m.close_ts
        flips_last_60s = sum(1 for t in self._5s_flip_timestamps if t >= now_ts - 60 * NS_PER_S)
        flips_last_120s = sum(1 for t in self._5s_flip_timestamps if t >= now_ts - 120 * NS_PER_S)
        
        if self._ts_5s_aligned_start is not None:
            aligned_duration_s = (now_ts - self._ts_5s_aligned_start) / NS_PER_S
        else:
            aligned_duration_s = 0.0
            
        # 7. EMA context
        ema_feats = {}
        for p in (3, 9, 13, 21):
            ema_feats[f"distance_to_ema{p}_atr"] = np.float32(self._fm.get_dist(p, c, d, atr_ref))
            ema_feats[f"ema{p}_slope_atr"] = np.float32(self._fm.get_slope(p))
            ema_feats[f"ema{p}_slope_change"] = np.float32(self._fm.get_slope_change(p))
            
        ema3_val = self._fm.emas["1m"][3].value
        ema9_val = self._fm.emas["1m"][9].value
        ema21_val = self._fm.emas["1m"][21].value
        
        ema3_ema9_spread = (ema3_val - ema9_val) * d / atr_ref if (ema3_val is not None and ema9_val is not None) else float("nan")
        ema9_ema21_spread = (ema9_val - ema21_val) * d / atr_ref if (ema9_val is not None and ema21_val is not None) else float("nan")
        
        # 8. Volume Context
        bar_vol = completed_1m.volume
        vols_list = list(self._fm.vols_1m)
        vol_avg = np.mean(vols_list) if vols_list else 1.0
        bar_volume_vs_20avg = bar_vol / vol_avg
        
        if vols_list:
            rank = sum(v < bar_vol for v in vols_list)
            eq = sum(v == bar_vol for v in vols_list)
            volume_percentile_20 = (rank + 0.5 * eq) / len(vols_list) * 100.0
        else:
            volume_percentile_20 = 50.0
            
        aligned_opposed_volume_ratio = 1.0
        if self._opposed_volume_since_regime_start > 0:
            aligned_opposed_volume_ratio = self._aligned_volume_since_regime_start / self._opposed_volume_since_regime_start
        else:
            aligned_opposed_volume_ratio = float(self._aligned_volume_since_regime_start)
            
        signed_vol = bar_vol * np.sign(c - o) * d
        
        # Efficiency calculations
        denom_eff = mfe_val + mae_val
        progress_efficiency = mfe_val / denom_eff if denom_eff > 1e-9 else 0.0
        mfe_mae_ratio = mfe_val / mae_val if mae_val > 1e-9 else 0.0
        
        f = {
            "regime_id": np.int64(self._1m_regime_id),
            "year": np.int16(self._year),
            "date": date_str,
            "session": session,
            "is_rth": np.int8(is_rth),
            "direction": np.int8(d),
            "regime_start_ts": np.int64(self._ts_1m_regime_start),
            "bar_ts": np.int64(completed_1m.close_ts),
            "bar_index_in_regime": np.int8(self._bar_index),
            "bar1_confirmed_flag": np.int8(self._bar1_confirmed_flag),
            
            # Progress features
            "current_pnl_atr": np.float32(current_pnl),
            "mfe_so_far_atr": np.float32(mfe_val),
            "mae_so_far_atr": np.float32(mae_val),
            "pullback_from_peak_atr": np.float32(pullback_val),
            "max_pullback_depth_so_far_atr": np.float32(max_pb_so_far),
            "progress_efficiency_so_far": np.float32(progress_efficiency),
            "mfe_mae_ratio_so_far": np.float32(mfe_mae_ratio),
            "regime_age_bars": np.int8(self._bar_index),
            
            # Anatomy features
            "bar_return_atr": np.float32(bar_return_atr),
            "bar_range_atr": np.float32(bar_range_atr),
            "bar_body_atr": np.float32(bar_body_atr),
            "bar_body_pct": np.float32(bar_body_pct),
            "bar_close_location": np.float32(bar_close_location),
            "bar_direction_aligned": np.int8(bar_direction_aligned),
            "upper_wick_pct": np.float32(upper_wick_pct),
            "lower_wick_pct": np.float32(lower_wick_pct),
            
            # Continuation features
            "made_continuation_this_bar": np.int8(made_continuation),
            "bars_since_last_continuation": np.int16(self._bars_since_last_continuation),
            "consecutive_no_continuation_bars": np.int16(self._consecutive_no_continuation_bars),
            "continuation_count_so_far": np.int16(self._continuation_count_so_far),
            "prior_bar_made_continuation": np.int8(self._prior_bar_made_continuation),
            "first_bar_made_continuation": np.int8(self._bar1_made_c),
            "first_two_bars_made_continuation": np.int8(self._first_two_bars_made_c),
            
            # Pullback features
            "bar1_pullback_depth_atr": np.float32(bar1_pb_val),
            "current_pullback_depth_atr": np.float32(pullback_val),
            "deep_pullback_gt_0p25": np.int8(int(pullback_val > 0.25)),
            "deep_pullback_gt_0p50": np.int8(int(pullback_val > 0.50)),
            "deep_pullback_gt_0p75": np.int8(int(pullback_val > 0.75)),
            "recovered_prior_peak_this_bar": np.int8(recovered_prior_peak),
            "recovered_above_prior_bar_midpoint": np.int8(recovered_above_midpoint),
            "recovered_above_prior_bar_close": np.int8(recovered_above_close),
            
            # Sequence patterns
            "last_1_bar_pattern": last_1_bar_pattern,
            "last_2_bar_pattern": last_2_bar_pattern,
            "last_3_bar_pattern": last_3_bar_pattern,
            "last_4_bar_pattern": last_4_bar_pattern,
            
            # 5s Context
            "regime_5s_aligned": np.int8(regime_5s_aligned),
            "regime_5s_direction": np.int8(reg_5s),
            "5s_flip_count_since_1m_start": np.int16(self._5s_flip_count),
            "5s_opposed_flip_count_since_1m_start": np.int16(self._5s_opposed_flip_count),
            "5s_current_aligned_duration_s": np.float32(aligned_duration_s),
            "5s_flips_last_60s": np.int16(flips_last_60s),
            "5s_flips_last_120s": np.int16(flips_last_120s),
            
            # EMA spreads
            "ema3_ema9_spread_atr": np.float32(ema3_ema9_spread),
            "ema9_ema21_spread_atr": np.float32(ema9_ema21_spread),
            
            # Volume Context
            "bar_volume": np.float32(bar_vol),
            "bar_volume_vs_20avg": np.float32(bar_volume_vs_20avg),
            "volume_percentile_20": np.float32(volume_percentile_20),
            "signed_volume_proxy": np.float32(signed_vol),
            "cum_signed_volume_since_regime_start": np.float32(self._cum_signed_volume_since_regime_start),
            "aligned_volume_since_regime_start": np.float32(self._aligned_volume_since_regime_start),
            "opposed_volume_since_regime_start": np.float32(self._opposed_volume_since_regime_start),
            "aligned_opposed_volume_ratio": np.float32(aligned_opposed_volume_ratio),
            "checkpoint_px": np.float32(completed_1m.close),
            "atr_1m_entry": np.float32(self._atr_1m_entry_cached)
        }
        f.update(ema_feats)
        return f


def run_year(year, lead_in_days=5, smoke=0):
    t0 = time.time()
    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=lead_in_days)
    load_end = (pd.Timestamp(f"{year}-01-01", tz="UTC") + pd.Timedelta(days=smoke)
                if smoke else pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    
    print(f"Loading data for year {year}...")
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(bar_types=[BAR_TYPE], start=load_start, end=load_end)
    print(f"  loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)")
    if not bars:
        return
        
    t0 = time.time()
    o = np.fromiter((float(b.open) for b in bars), dtype=np.float64, count=len(bars))
    h = np.fromiter((float(b.high) for b in bars), dtype=np.float64, count=len(bars))
    l = np.fromiter((float(b.low) for b in bars), dtype=np.float64, count=len(bars))
    c = np.fromiter((float(b.close) for b in bars), dtype=np.float64, count=len(bars))
    v = np.fromiter((float(b.volume) for b in bars), dtype=np.float64, count=len(bars))
    tse = np.fromiter((int(b.ts_event) for b in bars), dtype=np.int64, count=len(bars))
    tsi = np.fromiter((int(b.ts_init) for b in bars), dtype=np.int64, count=len(bars))
    del bars
    print(f"  extracted arrays ({time.time()-t0:.0f}s)")
    
    rep = StateRowsReplay(year)
    t0 = time.time()
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    print(f"  replay done ({time.time()-t0:.0f}s); checkpoints={len(rep.records):,}")
    
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    
    df_rec = pd.DataFrame(rep.records)
    if df_rec.empty:
        print(f"No checkpoints recorded for {year}")
        return
        
    df_rec = df_rec[(df_rec.bar_ts >= yr0) & (df_rec.bar_ts <= yr1)].copy()
    
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_smoke{smoke}" if smoke else ""
    df_rec.to_parquet(OUT / f"state_rows_{year}{suffix}.parquet", index=False)
    print(f"  saved parquet for {year}. Rows={len(df_rec):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()
    
    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y, smoke=args.smoke)
        
    # Combine parquets
    if not args.smoke:
        list_df = []
        for y in years:
            f = OUT / f"state_rows_{y}.parquet"
            if f.exists():
                list_df.append(pd.read_parquet(f))
        if list_df:
            combined = pd.concat(list_df, ignore_index=True)
            combined.to_parquet(OUT / "state_rows.parquet", index=False)
            print(f"Combined parquets saved to results/state_rows.parquet. Size={len(combined):,}")


if __name__ == "__main__":
    main()

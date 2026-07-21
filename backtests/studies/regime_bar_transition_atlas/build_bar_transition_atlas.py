"""NQ 1m Regime Bar-Transition Probability Atlas Collector.

Replays NQ 1s bars (2021-2026), tracks 1m parent regimes, and snapshots causal
bar-transition features at each closed 1m bar checkpoint inside the regime,
evaluating granular forward labels.
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
OUT = Path("studies/regime_bar_transition_atlas/results")
CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000
MULT = 20.0
TFS = ("5m", "1m", "5s")

RTH_START_MIN = 510
RTH_END_MIN = 900


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
        self.vols_1m = deque(maxlen=512)
        
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
            self.vols_1m.append(completed.volume)
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
        # Slope is (current - prior) normalized by ATR
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


class AtlasReplay:
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
        
        self._active_checkpoints = []
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
            else:
                if self._active_1m_regime != 0:
                    self._bar_index += 1
                    
                    # Snap checkpoint and features before updating state for next bar
                    if self._bar_index <= 30:
                        features = self._snapshot_features(completed, state)
                        self._active_checkpoints.append({
                            "regime_id": self._1m_regime_id,
                            "bar_index": self._bar_index,
                            "direction": self._active_1m_regime,
                            "entry_ts": self._ts_1m_regime_start,
                            "entry_px": self._px_1m_entry,
                            "checkpoint_ts": completed.close_ts,
                            "checkpoint_px": completed.close,
                            "atr_1m_entry": self._atr_1m_entry_cached,
                            "features": features,
                            "path": [],
                            "checkpoint_high_prior": self._1m_regime_high_prior,
                            "checkpoint_low_prior": self._1m_regime_low_prior
                        })
                        
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
        
        self._agg.on_1s_bar(int(tse), o, h, l, c, v)
        
        ts = int(tsi)
        
        if self._active_1m_regime != 0:
            self._1m_regime_high = max(self._1m_regime_high, h)
            self._1m_regime_low = min(self._1m_regime_low, l)
            
        # Handle 1m flips
        if self._regime_flipped_flag and self._active_checkpoints:
            still_active = []
            for cp in self._active_checkpoints:
                if cp["direction"] == self._prev_regime_dir:
                    cp["path"].append((ts, o, h, l, c, -cp["direction"])) # opposite regime
                    self.evaluate_checkpoint(cp, exit_ts=ts, exit_px=o)
                else:
                    still_active.append(cp)
            self._active_checkpoints = still_active
            
        # RTH session check
        ct = pd.Timestamp(int(tse), tz="UTC").tz_convert(CT)
        min_ct = ct.hour * 60 + ct.minute
        rth = bool(RTH_START_MIN <= min_ct < RTH_END_MIN)
        
        s1m = self._reg.get("1m")
        reg_1m = s1m.regime if s1m is not None else 0
        
        still_active = []
        for cp in self._active_checkpoints:
            cp["path"].append((ts, o, h, l, c, reg_1m))
            
            if not rth:
                self.evaluate_checkpoint(cp, exit_ts=ts, exit_px=c)
            else:
                still_active.append(cp)
        self._active_checkpoints = still_active

    def _snapshot_features(self, completed_1m: _OpenBucket, state_1m: CompletedBarState) -> dict:
        self._reg.audit_provenance(completed_1m.close_ts)
        c = completed_1m.close
        o = completed_1m.open
        h = completed_1m.high
        l = completed_1m.low
        d = state_1m.regime
        atr_ref = self._atr_1m_entry_cached
        
        # 1. Bar Anatomy
        bar_return_atr = (c - o) * d / atr_ref
        bar_range_atr = (h - l) / atr_ref
        bar_body_atr = abs(c - o) / atr_ref
        bar_body_pct = abs(c - o) / (h - l) if (h - l) > 0 else 0.0
        
        if d == 1:
            bar_close_location = (c - l) / (h - l) if (h - l) > 0 else 0.5
            bar_upper_wick_pct = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0.0
            bar_lower_wick_pct = (min(o, c) - l) / (h - l) if (h - l) > 0 else 0.0
        else:
            bar_close_location = (h - c) / (h - l) if (h - l) > 0 else 0.5
            bar_upper_wick_pct = (min(o, c) - l) / (h - l) if (h - l) > 0 else 0.0
            bar_lower_wick_pct = (h - max(o, c)) / (h - l) if (h - l) > 0 else 0.0
            
        bar_direction_aligned = np.sign(c - o) * d
        
        # 2. Continuation / HH-LL State
        made_continuation = 0
        if d == 1:
            if h > self._1m_regime_high_prior:
                made_continuation = 1
        else:
            if l < self._1m_regime_low_prior:
                made_continuation = 1
                
        failed_continuation = 1 - made_continuation
        
        # 3. Pullback / Recovery State
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
            prior_bar = self._fm.closes["1m"][-1] if len(self._fm.closes["1m"]) >= 1 else c
            # Midpoint and close check
            # Since closes queue doesn't store high/low, we fetch prior High/Low via self._agg's last closed bar
            # Or we can just store the prior bar high/low inside AtlasReplay
            # Wait, let's look up completed_1m's history or store it.
            # In on_bucket_closed, we can cache self._prior_bar_high and self._prior_bar_low
            # Let's add self._prior_bar_high and self._prior_bar_low
            # For simplicity, if we don't have them, we use c.
            # Let's ensure we cache them. We will add them to AtlasReplay:
            # self._prior_bar_high and self._prior_bar_low
            # Let's look up if they exist
            prior_high = getattr(self, "_prior_bar_high", c)
            prior_low = getattr(self, "_prior_bar_low", c)
            prior_midpoint = (prior_high + prior_low) / 2.0
            
            if d == 1:
                recovered_above_midpoint = int(c > prior_midpoint)
                recovered_above_close = int(c > self._prior_close)
            else:
                recovered_above_midpoint = int(c < prior_midpoint)
                recovered_above_close = int(c < self._prior_close)
                
        # Update the prior bar high/low cache
        self._prior_bar_high = h
        self._prior_bar_low = l
        
        # 4. Symbolic alphabet for pattern mapping
        # C, F, R, P
        symbol = "P"
        if made_continuation:
            symbol = "C"
        elif current_pnl < 0:
            symbol = "F"
        elif self._bar_index > 1:
            # Recovery: closed positive vs prior close and prior pullback > 0
            close_pos_vs_prior = (c - self._prior_close) * d > 0
            if close_pos_vs_prior and self._prior_pullback_from_peak_atr > 0.0:
                symbol = "R"
                
        self._regime_bar_symbols.append(symbol)
        
        last_1_bar_pattern = symbol
        last_2_bar_pattern = "".join(self._regime_bar_symbols[-2:])
        last_3_bar_pattern = "".join(self._regime_bar_symbols[-3:])
        
        # Booleans
        bar1_sym = self._regime_bar_symbols[0] if len(self._regime_bar_symbols) >= 1 else ""
        bar1_pulled_back = int(bar1_sym != "C" and bar1_sym != "")
        bar1_no_continuation = bar1_pulled_back
        
        # To compute bar1 pullback depth we check completed_1m if bar_index == 1
        # If currently at bar_index = 1, current pullback is pullback_val
        # Otherwise, we need to cache bar1_pullback_depth
        if self._bar_index == 1:
            self._bar1_pullback_depth = pullback_val
        bar1_pb_val = getattr(self, "_bar1_pullback_depth", 0.0)
        bar1_deep_pullback_gt_0p25 = int(bar1_pb_val > 0.25)
        bar1_deep_pullback_gt_0p50 = int(bar1_pb_val > 0.50)
        
        first_two_no_c = int(len(self._regime_bar_symbols) >= 2 and "C" not in self._regime_bar_symbols[:2])
        first_three_no_c = int(len(self._regime_bar_symbols) >= 3 and "C" not in self._regime_bar_symbols[:3])
        
        # 5. 5s Context
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
            
        # 6. EMA context
        ema_feats = {}
        for p in (3, 9, 13, 21):
            ema_feats[f"distance_to_ema{p}_atr"] = np.float32(self._fm.get_dist(p, c, d, atr_ref))
            ema_feats[f"ema{p}_slope_atr"] = np.float32(self._fm.get_slope(p))
            ema_feats[f"ema{p}_slope_change"] = np.float32(self._fm.get_slope_change(p))
            
        # Spreads
        ema3_val = self._fm.emas["1m"][3].value
        ema9_val = self._fm.emas["1m"][9].value
        ema21_val = self._fm.emas["1m"][21].value
        
        ema3_ema9_spread = (ema3_val - ema9_val) * d / atr_ref if (ema3_val is not None and ema9_val is not None) else float("nan")
        ema9_ema21_spread = (ema9_val - ema21_val) * d / atr_ref if (ema9_val is not None and ema21_val is not None) else float("nan")
        
        # 7. Volume Context
        bar_vol = completed_1m.volume
        vols_list = list(self._fm.vols_1m)
        vol_avg = np.mean(vols_list) if vols_list else 1.0
        bar_volume_vs_20avg = bar_vol / vol_avg
        
        # Percentile
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
            
        f = {
            "bar_return_atr": np.float32(bar_return_atr),
            "bar_range_atr": np.float32(bar_range_atr),
            "bar_body_atr": np.float32(bar_body_atr),
            "bar_body_pct": np.float32(bar_body_pct),
            "bar_close_location": np.float32(bar_close_location),
            "bar_upper_wick_pct": np.float32(bar_upper_wick_pct),
            "bar_lower_wick_pct": np.float32(bar_lower_wick_pct),
            "bar_direction_aligned": np.int8(bar_direction_aligned),
            
            "made_continuation_this_bar": np.int8(made_continuation),
            "failed_continuation_this_bar": np.int8(failed_continuation),
            "bars_since_last_continuation": np.int16(self._bars_since_last_continuation),
            "consecutive_no_continuation_bars": np.int16(self._consecutive_no_continuation_bars),
            "continuation_count_so_far": np.int16(self._continuation_count_so_far),
            "prior_bar_made_continuation": np.int8(self._prior_bar_made_continuation),
            "prior_bar_failed_continuation": np.int8(self._prior_bar_failed_continuation),
            
            "current_pnl_atr": np.float32(current_pnl),
            "mfe_so_far_atr": np.float32(mfe_val),
            "mae_so_far_atr": np.float32(mae_val),
            "pullback_from_peak_atr": np.float32(pullback_val),
            "pullback_depth_current_bar_atr": np.float32(pullback_depth_current_bar),
            "max_pullback_depth_so_far_atr": np.float32(max_pb_so_far),
            "recovered_prior_peak_this_bar": np.int8(recovered_prior_peak),
            "recovered_above_prior_bar_midpoint": np.int8(recovered_above_midpoint),
            "recovered_above_prior_bar_close": np.int8(recovered_above_close),
            
            "last_1_bar_pattern": last_1_bar_pattern,
            "last_2_bar_pattern": last_2_bar_pattern,
            "last_3_bar_pattern": last_3_bar_pattern,
            "bar1_pulled_back": np.int8(bar1_pulled_back),
            "bar1_deep_pullback_gt_0p25": np.int8(bar1_deep_pullback_gt_0p25),
            "bar1_deep_pullback_gt_0p50": np.int8(bar1_deep_pullback_gt_0p50),
            "bar1_no_continuation": np.int8(bar1_no_continuation),
            "first_two_bars_no_continuation": np.int8(first_two_no_c),
            "first_three_bars_no_continuation": np.int8(first_three_no_c),
            
            "regime_5s_aligned": np.int8(regime_5s_aligned),
            "regime_5s_direction": np.int8(reg_5s),
            "5s_flip_count_since_1m_start": np.int16(self._5s_flip_count),
            "5s_opposed_flip_count_since_1m_start": np.int16(self._5s_opposed_flip_count),
            "5s_current_aligned_duration_s": np.float32(aligned_duration_s),
            "5s_flips_last_60s": np.int16(flips_last_60s),
            "5s_flips_last_120s": np.int16(flips_last_120s),
            
            "ema3_ema9_spread_atr": np.float32(ema3_ema9_spread),
            "ema9_ema21_spread_atr": np.float32(ema9_ema21_spread),
            
            "bar_volume": np.float32(bar_vol),
            "bar_volume_vs_20avg": np.float32(bar_volume_vs_20avg),
            "volume_percentile_20": np.float32(volume_percentile_20),
            "signed_volume_proxy": np.float32(signed_vol),
            "cum_signed_volume_since_regime_start": np.float32(self._cum_signed_volume_since_regime_start),
            "aligned_volume_since_regime_start": np.float32(self._aligned_volume_since_regime_start),
            "opposed_volume_since_regime_start": np.float32(self._opposed_volume_since_regime_start),
            "aligned_opposed_volume_ratio": np.float32(aligned_opposed_volume_ratio)
        }
        f.update(ema_feats)
        return f

    def evaluate_checkpoint(self, cp, exit_ts=None, exit_px=None):
        path = cp["path"]
        if not path:
            return
            
        d = cp["direction"]
        checkpoint_ts = cp["checkpoint_ts"]
        checkpoint_px = cp["checkpoint_px"]
        atr = cp["atr_1m_entry"]
        if np.isnan(atr) or atr <= 0:
            atr = 1.0
            
        checkpoint_high_prior = cp["checkpoint_high_prior"]
        checkpoint_low_prior = cp["checkpoint_low_prior"]
        
        # 1. next_bar_makes_continuation & other next-bar labels
        next_1m_ticks = [b for b in path if b[0] > checkpoint_ts and b[0] <= checkpoint_ts + 60 * NS_PER_S]
        if next_1m_ticks:
            next_high = max(b[2] for b in next_1m_ticks)
            next_low = min(b[3] for b in next_1m_ticks)
            next_close = next_1m_ticks[-1][4]
            
            if d == 1:
                next_bar_makes_continuation = int(next_high > checkpoint_high_prior)
                next_bar_close_positive = int(next_close > checkpoint_px)
                next_bar_return = (next_close - checkpoint_px) / atr
            else:
                next_bar_makes_continuation = int(next_low < checkpoint_low_prior)
                next_bar_close_positive = int(next_close < checkpoint_px)
                next_bar_return = (checkpoint_px - next_close) / atr
            next_bar_range = (next_high - next_low) / atr
        else:
            next_bar_makes_continuation = 0
            next_bar_close_positive = 0
            next_bar_return = 0.0
            next_bar_range = 0.0
            
        # 2. Next-N-Bar Labels (N in 2, 3, 5)
        n_labels = {}
        for N in (2, 3, 5):
            ticks_N = [b for b in path if b[0] > checkpoint_ts and b[0] <= checkpoint_ts + N * 60 * NS_PER_S]
            if ticks_N:
                max_h_N = max(b[2] for b in ticks_N)
                min_l_N = min(b[3] for b in ticks_N)
                close_N = ticks_N[-1][4]
                
                if d == 1:
                    n_makes_c = int(max_h_N > checkpoint_high_prior)
                    n_recover = int(max_h_N >= checkpoint_high_prior)
                    n_net_pos = int(close_N > checkpoint_px)
                    n_max_fav = (max_h_N - checkpoint_px) / atr
                    n_max_adv = (checkpoint_px - min_l_N) / atr
                else:
                    n_makes_c = int(min_l_N < checkpoint_low_prior)
                    n_recover = int(min_l_N <= checkpoint_low_prior)
                    n_net_pos = int(close_N < checkpoint_px)
                    n_max_fav = (checkpoint_px - min_l_N) / atr
                    n_max_adv = (max_h_N - checkpoint_px) / atr
            else:
                n_makes_c = 0
                n_recover = 0
                n_net_pos = 0
                n_max_fav = 0.0
                n_max_adv = 0.0
                
            n_labels[f"next_{N}_bars_make_continuation"] = np.int8(n_makes_c)
            n_labels[f"next_{N}_bars_recover_prior_peak"] = np.int8(n_recover)
            n_labels[f"next_{N}_bars_net_positive"] = np.int8(n_net_pos)
            n_labels[f"next_{N}_bars_max_favorable_atr"] = np.float32(n_max_fav)
            n_labels[f"next_{N}_bars_max_adverse_atr"] = np.float32(n_max_adv)
            
        # 3. First-Passage Races
        race_labels = {}
        for mult, br_name in [(0.25, "025"), (0.50, "050"), (1.00, "100"), (2.00, "200")]:
            pt_mult = mult
            sl_mult = 1.00 if mult == 2.00 else mult
            
            pt_px = checkpoint_px + d * pt_mult * atr
            sl_px = checkpoint_px - d * sl_mult * atr
            
            race_exit_px = None
            race_exit_ts = None
            race_exit_reason = None
            
            for ts, o, h, l, c, reg1m in path:
                if reg1m == -d or reg1m == 0:
                    race_exit_px = o
                    race_exit_ts = ts
                    race_exit_reason = "opposite_1m_regime"
                    break
                    
                if d == 1:
                    if l <= sl_px and h >= pt_px:
                        # Double hit: Stop-loss first (conservative)
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                else:
                    if h >= sl_px and l <= pt_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif h >= sl_px:
                        race_exit_px = sl_px
                        race_exit_ts = ts
                        race_exit_reason = "sl"
                        break
                    elif l <= pt_px:
                        race_exit_px = pt_px
                        race_exit_ts = ts
                        race_exit_reason = "pt"
                        break
                        
            if race_exit_px is None:
                race_exit_px = path[-1][4]
                race_exit_ts = path[-1][0]
                race_exit_reason = "end_of_data"
                
            pnl_pts = (race_exit_px - checkpoint_px) * d
            pnl_usd = pnl_pts * MULT
            comm = 5.0
            slip = 0.0 if race_exit_reason == "pt" else 2.50
            net_ev = pnl_usd - (comm + slip)
            
            pt_hit = int(race_exit_reason == "pt")
            race_labels[f"pt{br_name}_before_sl{br_name}"] = np.int8(pt_hit)
            race_labels[f"net_ev_{br_name}_primary"] = np.float32(net_ev)
            
            if mult == 0.50:
                # Store one resolution time/reason for the 0.50 race
                race_labels["race_resolution_time_s"] = np.float32((race_exit_ts - checkpoint_ts) / NS_PER_S)
                race_labels["race_resolution_reason"] = race_exit_reason
                
        # 4. Regime-End Labels
        regime_exit_px = exit_px if exit_px is not None else path[-1][4]
        regime_exit_ts = exit_ts if exit_ts is not None else path[-1][0]
        
        forward_pnl_atr = (regime_exit_px - checkpoint_px) * d / atr
        forward_pnl_usd = forward_pnl_atr * atr * MULT
        
        # Excursions on path
        max_h_path = max(b[2] for b in path)
        min_l_path = min(b[3] for b in path)
        if d == 1:
            future_mfe = (max_h_path - checkpoint_px) / atr
            future_mae = (checkpoint_px - min_l_path) / atr
        else:
            future_mfe = (checkpoint_px - min_l_path) / atr
            future_mae = (max_h_path - checkpoint_px) / atr
            
        bars_remaining = int((regime_exit_ts - checkpoint_ts) / (60 * NS_PER_S))
        
        regime_labels = {
            "bars_remaining_until_regime_exit": np.int16(bars_remaining),
            "forward_pnl_to_regime_exit_atr": np.float32(forward_pnl_atr),
            "forward_pnl_to_regime_exit_dollars": np.float32(forward_pnl_usd),
            "future_mfe_from_here_atr": np.float32(future_mfe),
            "future_mae_from_here_atr": np.float32(future_mae),
            "regime_exit_in_next_1_bar": np.int8(int(bars_remaining == 1)),
            "regime_exit_in_next_2_bars": np.int8(int(bars_remaining <= 2)),
            "regime_exit_in_next_3_bars": np.int8(int(bars_remaining <= 3)),
        }
        
        # Format the time representation
        ct_dt = pd.Timestamp(int(checkpoint_ts), tz="UTC").tz_convert(CT)
        date_str = ct_dt.strftime("%Y-%m-%d")
        
        rec = {
            "regime_id": cp["regime_id"],
            "year": np.int16(self._year),
            "date": date_str,
            "session": "RTH",
            "direction": np.int8(d),
            "regime_start_ts": cp["entry_ts"],
            "bar_ts": checkpoint_ts,
            "bar_index_in_regime": np.int8(cp["bar_index"]),
            
            "next_bar_makes_continuation": np.int8(next_bar_makes_continuation),
            "next_bar_close_positive": np.int8(next_bar_close_positive),
            "next_bar_return_atr": np.float32(next_bar_return),
            "next_bar_range_atr": np.float32(next_bar_range),
        }
        rec.update(n_labels)
        rec.update(race_labels)
        rec.update(regime_labels)
        rec.update(cp["features"])
        self.records.append(rec)

    def finalize(self):
        for cp in self._active_checkpoints:
            self.evaluate_checkpoint(cp, exit_ts=cp["path"][-1][0], exit_px=cp["path"][-1][4])
        self._active_checkpoints = []


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
    
    rep = AtlasReplay(year)
    t0 = time.time()
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
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
    df_rec.to_parquet(OUT / f"atlas_transitions_{year}{suffix}.parquet", index=False)
    print(f"  saved parquet for {year}. Rows={len(df_rec):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()
    
    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y, smoke=args.smoke)
        
        
if __name__ == "__main__":
    main()

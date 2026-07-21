"""NQ 1m Regime Path Atlas Collector.

Replays NQ 1s bars (2021-2026), tracks 1m regimes, and snapshots causal features
at each 1m bar checkpoint inside the regime, evaluating forward first-passage labels.
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
OUT = Path("studies/regime_path_atlas/results")
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
        self.vols = {tf: deque(maxlen=512) for tf in TFS}
        
        self.emas = {
            "5s": {3: _EMA(3), 9: _EMA(9), 13: _EMA(13), 21: _EMA(21)},
            "1m": {3: _EMA(3), 9: _EMA(9), 13: _EMA(13), 21: _EMA(21)},
            "5m": {3: _EMA(3), 9: _EMA(9), 21: _EMA(21)}
        }
        
        self.ema_hists = {
            "5s": {p: deque(maxlen=6) for p in (3, 9, 13, 21)},
            "1m": {p: deque(maxlen=6) for p in (3, 9, 13, 21)},
            "5m": {p: deque(maxlen=6) for p in (3, 9, 21)}
        }
        
        self.slopes_hist = {
            "5s": {9: deque(maxlen=2)},
            "1m": {9: deque(maxlen=2)}
        }

    def on_bar_closed(self, tf: str, completed: _OpenBucket, atr: float):
        c = completed.close
        v = completed.volume
        
        self.closes[tf].append(c)
        self.vols[tf].append(v)
        
        for p, ema in self.emas[tf].items():
            val = ema.update(c)
            self.ema_hists[tf][p].append(val)
            
        if tf in ("5s", "1m"):
            slope = self.get_slope(tf, 9, atr)
            if not np.isnan(slope):
                self.slopes_hist[tf][9].append(slope)

    def get_slope(self, tf: str, period: int, atr: float) -> float:
        hist = self.ema_hists[tf][period]
        if len(hist) < 6 or atr <= 0 or np.isnan(atr):
            return float("nan")
        slope = (hist[-1] - hist[0]) / 5.0
        return slope / atr

    def get_slope_accel(self, tf: str, period: int) -> float:
        hist = self.slopes_hist[tf].get(period)
        if not hist or len(hist) < 2:
            return float("nan")
        return hist[-1] - hist[0]

    def get_dist(self, tf: str, period: int, c: float, direction: int, atr: float) -> float:
        v = self.emas[tf][period].value
        if v is None or atr <= 0 or np.isnan(atr):
            return float("nan")
        return direction * (c - v) / atr


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
        
        # 1m regime tracking
        self._active_1m_regime = 0
        self._ts_1m_regime_start = 0
        self._px_1m_entry = 0.0
        self._atr_1m_entry_cached = 1.0
        self._1m_regime_id = 0
        self._1m_regime_index = 0
        self._bar_index = 0
        
        # High/Low priors
        self._1m_regime_high = 0.0
        self._1m_regime_low = 0.0
        self._1m_regime_high_prior = 0.0
        self._1m_regime_low_prior = 0.0
        self._bars_since_last_hh_ll = 0
        self._last_bar_hh_ll = 0
        
        # 5s flip tracking
        self._5s_flip_count = 0
        
        # Checkpoints lists
        self._active_checkpoints = []
        self.records = []
        
        # Flags
        self._regime_flipped_flag = False
        self._prev_regime_dir = 0

    def on_bucket_closed(self, tf: str, completed: _OpenBucket):
        self._engines[tf].on_bar_closed(completed)
        
        state = self._reg.get(tf)
        if state is None:
            return
            
        atr = state.atr
        self._fm.on_bar_closed(tf, completed, atr)
        
        prev = self._prev_regimes[tf]
        now = state.regime
        flipped = (now != prev and now != 0)
        
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
                self._bars_since_last_hh_ll = 0
                self._5s_flip_count = 0
                self._last_bar_hh_ll = 1
            else:
                if self._active_1m_regime != 0:
                    self._bar_index += 1
                    
                    # HH/LL check relative to regime's prior high/low
                    if self._active_1m_regime == 1:
                        is_hh = int(completed.high > self._1m_regime_high_prior)
                        self._last_bar_hh_ll = is_hh
                        if is_hh:
                            self._bars_since_last_hh_ll = 0
                            self._1m_regime_high_prior = completed.high
                        else:
                            self._bars_since_last_hh_ll += 1
                    else:
                        is_ll = int(completed.low < self._1m_regime_low_prior)
                        self._last_bar_hh_ll = is_ll
                        if is_ll:
                            self._bars_since_last_hh_ll = 0
                            self._1m_regime_low_prior = completed.low
                        else:
                            self._bars_since_last_hh_ll += 1
                            
                    if self._bar_index <= 30:
                        # Snapshot features causally
                        features = self._snapshot_features(completed, state)
                        
                        # Add a new checkpoint
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
                        
        elif tf == "5s":
            if flipped:
                if self._active_1m_regime != 0:
                    self._5s_flip_count += 1
                    
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
                    self.evaluate_checkpoint(cp, exit_ts=ts, exit_px=o, exit_reason="opposite_1m_regime")
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
                self.evaluate_checkpoint(cp, exit_ts=ts, exit_px=c, exit_reason="end_of_data")
            else:
                still_active.append(cp)
        self._active_checkpoints = still_active

    def _snapshot_features(self, completed_1m: _OpenBucket, state_1m: CompletedBarState) -> dict:
        self._reg.audit_provenance(completed_1m.close_ts)
        c = completed_1m.close
        d = state_1m.regime
        atr_1m = state_1m.atr
        
        state_5s = self._reg.get("5s")
        reg_5s = state_5s.regime if state_5s is not None else 0
        
        state_5m = self._reg.get("5m")
        reg_5m = state_5m.regime if state_5m is not None else 0
        
        mfe_atr = (self._1m_regime_high - self._px_1m_entry) * d / self._atr_1m_entry_cached if self._atr_1m_entry_cached > 0 else 0.0
        mae_atr = (self._px_1m_entry - self._1m_regime_low) * d / self._atr_1m_entry_cached if self._atr_1m_entry_cached > 0 else 0.0
        current_pnl_atr = (c - self._px_1m_entry) * d / self._atr_1m_entry_cached if self._atr_1m_entry_cached > 0 else 0.0
        pullback_atr = mfe_atr - current_pnl_atr
        
        vol_1m = completed_1m.volume
        vols_1m_rolling = list(self._fm.vols["1m"])[-20:]
        vol_1m_avg = np.mean(vols_1m_rolling) if len(vols_1m_rolling) >= 10 else float("nan")
        vol_1m_ratio = vol_1m / vol_1m_avg if vol_1m_avg > 0 else float("nan")
        
        ema9_slope = self._fm.get_slope("1m", 9, self._atr_1m_entry_cached)
        ema9_slope_change = self._fm.get_slope_accel("1m", 9)
        distance_to_ema9 = self._fm.get_dist("1m", 9, c, d, self._atr_1m_entry_cached)
        
        # candle pullback proxy (red candle in uptrend / green candle in downtrend)
        last_bar_pullback = int((completed_1m.close - completed_1m.open) * d < 0)
        
        f = {
            "year": self._year,
            "time_since_flip": (completed_1m.close_ts - self._ts_1m_regime_start) / NS_PER_S,
            "current_pnl_atr": np.float32(current_pnl_atr),
            "mfe_so_far_atr": np.float32(mfe_atr),
            "mae_so_far_atr": np.float32(mae_atr),
            "pullback_from_peak_atr": np.float32(pullback_atr),
            "last_bar_hh_ll": np.int8(self._last_bar_hh_ll),
            "last_bar_pullback": np.int8(last_bar_pullback),
            "bars_since_last_hh_ll": np.int16(self._bars_since_last_hh_ll),
            "5s_flip_count": np.int16(self._5s_flip_count),
            "5s_current_alignment": np.int8(reg_5s * d),
            "ema9_slope": np.float32(ema9_slope),
            "ema9_slope_change": np.float32(ema9_slope_change),
            "distance_to_ema9": np.float32(distance_to_ema9),
            "volume_state": np.float32(vol_1m_ratio),
            "regime_5m": np.int8(reg_5m),
            "aligned_5m_1m": np.int8(int(reg_5m == d and reg_5m != 0))
        }
        return f

    def evaluate_checkpoint(self, cp, exit_ts=None, exit_px=None, exit_reason=None):
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
        
        # 1. next_bar_hh label (next 1m bar HH/LL)
        next_1m_ticks = [b for b in path if b[0] <= checkpoint_ts + 60 * NS_PER_S]
        if next_1m_ticks:
            if d == 1:
                next_high = max(b[2] for b in next_1m_ticks)
                next_bar_hh = int(next_high > checkpoint_high_prior)
            else:
                next_low = min(b[3] for b in next_1m_ticks)
                next_bar_hh = int(next_low < checkpoint_low_prior)
        else:
            next_bar_hh = 0
            
        # 2. Bracket Outcomes
        labels = {}
        for pt_mult, sl_mult, br_name in [(0.5, 0.5, "05"), (1.0, 1.0, "10"), (2.0, 1.0, "20_10")]:
            pt_px = checkpoint_px + d * pt_mult * atr
            sl_px = checkpoint_px - d * sl_mult * atr
            
            bracket_exit_px = None
            bracket_exit_reason = None
            
            for ts, o, h, l, c, reg1m in path:
                if reg1m == -d or reg1m == 0:
                    bracket_exit_px = o
                    bracket_exit_reason = "opposite_1m_regime"
                    break
                    
                if d == 1:
                    if l <= sl_px and h >= pt_px:
                        bracket_exit_px = sl_px
                        bracket_exit_reason = "sl"
                        break
                    elif l <= sl_px:
                        bracket_exit_px = sl_px
                        bracket_exit_reason = "sl"
                        break
                    elif h >= pt_px:
                        bracket_exit_px = pt_px
                        bracket_exit_reason = "pt"
                        break
                else:
                    if h >= sl_px and l <= pt_px:
                        bracket_exit_px = sl_px
                        bracket_exit_reason = "sl"
                        break
                    elif h >= sl_px:
                        bracket_exit_px = sl_px
                        bracket_exit_reason = "sl"
                        break
                    elif l <= pt_px:
                        bracket_exit_px = pt_px
                        bracket_exit_reason = "pt"
                        break
                        
            if bracket_exit_px is None:
                bracket_exit_px = path[-1][4]
                bracket_exit_reason = "end_of_data"
                
            pnl_pts = (bracket_exit_px - checkpoint_px) * d
            pnl_usd = pnl_pts * MULT
            
            comm = 5.0
            slip = 0.0 if bracket_exit_reason == "pt" else 2.50
            net_ev_primary = pnl_usd - (comm + slip)
            
            slip_stress = 0.0 if bracket_exit_reason == "pt" else 5.00
            net_ev_stress = pnl_usd - (comm + slip_stress)
            
            pt_hit = int(bracket_exit_reason == "pt")
            
            labels[f"reach_{br_name}"] = np.int8(pt_hit)
            labels[f"net_ev_{br_name}_primary"] = np.float32(net_ev_primary)
            labels[f"net_ev_{br_name}_stress"] = np.float32(net_ev_stress)
            
        regime_exit_px = exit_px if exit_px is not None else path[-1][4]
        forward_pnl = (regime_exit_px - checkpoint_px) * d / atr
        
        rec = {
            "regime_id": cp["regime_id"],
            "bar_index": np.int8(cp["bar_index"]),
            "direction": np.int8(cp["direction"]),
            "entry_ts": cp["entry_ts"],
            "entry_px": cp["entry_px"],
            "checkpoint_ts": cp["checkpoint_ts"],
            "checkpoint_px": cp["checkpoint_px"],
            "atr_1m": cp["atr_1m_entry"],
            "year": np.int16(cp["features"]["year"]),
            "next_bar_hh": np.int8(next_bar_hh),
            "forward_pnl_to_regime_exit": np.float32(forward_pnl),
        }
        rec.update(labels)
        rec.update(cp["features"])
        self.records.append(rec)

    def finalize(self):
        for cp in self._active_checkpoints:
            self.evaluate_checkpoint(cp, exit_ts=cp["path"][-1][0], exit_px=cp["path"][-1][4], exit_reason="end_of_data")
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
        
    df_rec = df_rec[(df_rec.checkpoint_ts >= yr0) & (df_rec.checkpoint_ts <= yr1)].copy()
    
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_smoke{smoke}" if smoke else ""
    df_rec.to_parquet(OUT / f"atlas_checkpoints_{year}{suffix}.parquet", index=False)
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

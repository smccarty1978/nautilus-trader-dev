"""NQ 5s Regime Scalp Study Replay Runner.

Replays NQ 1s bars (2021-2024), aggregates to 5s, 1m, and 5m, triggers same-direction
5s scalp entries inside active 1m regimes, snapshots extensive causal features,
and evaluates 160 exit configurations on the 1s paths.
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

# Instrument config. PnL is stored in POINTS (instrument-agnostic); the dollar
# multiplier and tick value are applied later in the analyzer. Only the catalog,
# bar type, and output filename prefix change per instrument — the causal replay
# logic (audited) is identical. RTH window (08:30-15:00 CT) is the same CME
# equity-index cash session for both NQ and ES.
INSTRUMENTS = {
    "NQ": dict(catalog="data/catalog/NQ_v0_2020_2026",
               bar_type="NQ.XCME-1-SECOND-LAST-EXTERNAL", prefix=""),
    "ES": dict(catalog="data/catalog/ES_v0_2020_2026",
               bar_type="ES.XCME-1-SECOND-LAST-EXTERNAL", prefix="es_"),
}
CATALOG = INSTRUMENTS["NQ"]["catalog"]      # set by main() from --instrument
BAR_TYPE = INSTRUMENTS["NQ"]["bar_type"]
PREFIX = INSTRUMENTS["NQ"]["prefix"]
OUT = Path("studies/regime_5s_scalps/results")
CT = pytz.timezone("America/Chicago")
NS_PER_S = 1_000_000_000
TICK = 0.25
TFS = ("5m", "1m", "5s")

RTH_START_MIN = 510
RTH_END_MIN = 900

def _tick_round(val: float) -> float:
    return round(val * 4) / 4.0

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

# Brackets configuration
BRACKET_CONFIGS = [
    (0.25, 0.25, "sym025"),
    (0.50, 0.50, "sym050"),
    (0.75, 0.75, "sym075"),
    (1.00, 1.00, "sym100"),
    (0.50, 0.25, "pos050_025"),
    (1.00, 0.50, "pos100_050"),
    (1.50, 0.75, "pos150_075"),
    (2.00, 1.00, "pos200_100"),
    (999.0, 999.0, "nobr")
]


class FeatureManager:
    def __init__(self):
        self.closes = {tf: deque(maxlen=512) for tf in TFS}
        self.vols = {tf: deque(maxlen=512) for tf in TFS}
        
        # EMAs
        self.emas = {
            "5s": {3: _EMA(3), 9: _EMA(9), 13: _EMA(13), 21: _EMA(21)},
            "1m": {3: _EMA(3), 9: _EMA(9), 13: _EMA(13), 21: _EMA(21)},
            "5m": {3: _EMA(3), 9: _EMA(9), 21: _EMA(21)}
        }
        
        # EMA histories for slopes
        self.ema_hists = {
            "5s": {p: deque(maxlen=6) for p in (3, 9, 13, 21)},
            "1m": {p: deque(maxlen=6) for p in (3, 9, 13, 21)},
            "5m": {p: deque(maxlen=6) for p in (3, 9, 21)}
        }
        
        # Slope deques for acceleration
        self.slopes_hist = {
            "5s": {9: deque(maxlen=2)},
            "1m": {9: deque(maxlen=2)}
        }

    def on_bar_closed(self, tf: str, completed: _OpenBucket, atr: float):
        c = completed.close
        v = completed.volume
        
        self.closes[tf].append(c)
        self.vols[tf].append(v)
        
        # Update EMAs
        for p, ema in self.emas[tf].items():
            val = ema.update(c)
            self.ema_hists[tf][p].append(val)
            
        # Update slopes hist for acceleration
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

    def get_spread(self, tf: str, p1: int, p2: int, atr: float) -> float:
        v1 = self.emas[tf][p1].value
        v2 = self.emas[tf][p2].value
        if v1 is None or v2 is None or atr <= 0 or np.isnan(atr):
            return float("nan")
        return (v1 - v2) / atr

    def get_dist(self, tf: str, period: int, c: float, direction: int, atr: float) -> float:
        v = self.emas[tf][period].value
        if v is None or atr <= 0 or np.isnan(atr):
            return float("nan")
        return direction * (c - v) / atr


class ScalpReplay:
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
        self._1m_mfe = 0.0
        self._1m_mae = 0.0
        self._1m_cum_abs_move = 0.0
        self._1m_prev_close = 0.0
        self._1m_ordinal = 0
        
        # 5s flips and chop tracking
        self._5s_flip_count = 0
        self._5s_chop_count = 0
        self._5s_flips_timestamps = deque()
        self._aligned_5s_vol = 0.0
        self._opposing_5s_vol = 0.0
        self._obv_signed_vol = 0.0
        
        # Prior 5s regime details
        self._5s_regime_start_ts = 0
        self._5s_regime_start_px = 0.0
        self._5s_regime_mfe = 0.0
        self._5s_regime_mae = 0.0
        self._prior_5s_stats = {
            "duration": float("nan"),
            "mfe": float("nan"),
            "mae": float("nan"),
            "pnl": float("nan")
        }
        
        # 5m regime tracking for MFE/MAE context
        self._ts_5m_regime_start = 0
        self._px_5m_entry = 0.0
        self._5m_mfe = 0.0
        self._5m_mae = 0.0
        
        # Trade lists
        self._entry_seq = 0
        self._pending_scalps = []
        self._active_scalps = []
        
        self.records_entries = []
        self.records_labels = []

    def on_bucket_closed(self, tf: str, completed: _OpenBucket):
        # Update engine & registry
        self._engines[tf].on_bar_closed(completed)
        
        state = self._reg.get(tf)
        if state is None:
            return
            
        atr = state.atr
        # Update feature manager
        self._fm.on_bar_closed(tf, completed, atr)
        
        prev = self._prev_regimes[tf]
        now = state.regime
        
        # Detect flips
        flipped = (now != prev and now != 0)
        
        if tf == "1m":
            if flipped:
                # 1m Regime flipped!
                self._active_1m_regime = now
                self._ts_1m_regime_start = state.close_ts
                self._px_1m_entry = state.close
                self._1m_mfe = 0.0
                self._1m_mae = 0.0
                self._1m_cum_abs_move = 0.0
                self._1m_prev_close = state.close
                self._1m_ordinal = 0
                self._5s_flip_count = 0
                self._obv_signed_vol = 0.0
                self._aligned_5s_vol = 0.0
                self._opposing_5s_vol = 0.0
                self._5s_chop_count = 0
                
        elif tf == "5m":
            if flipped:
                self._ts_5m_regime_start = state.close_ts
                self._px_5m_entry = state.close
                self._5m_mfe = 0.0
                self._5m_mae = 0.0
                
        elif tf == "5s":
            # Track volume since 1m start
            if self._active_1m_regime != 0:
                if now == self._active_1m_regime:
                    self._aligned_5s_vol += completed.volume
                elif now == -self._active_1m_regime:
                    self._opposing_5s_vol += completed.volume
                    
            if flipped:
                # Prior 5s stats capture
                if prev != 0:
                    dur = (completed.close_ts - self._5s_regime_start_ts) / NS_PER_S
                    prev_atr = self._reg.get("5s").atr # approximate with current 5s ATR
                    mfe_norm = self._5s_regime_mfe / prev_atr if prev_atr > 0 else float("nan")
                    mae_norm = self._5s_regime_mae / prev_atr if prev_atr > 0 else float("nan")
                    pnl_norm = (completed.close - self._5s_regime_start_px) * prev / prev_atr if prev_atr > 0 else float("nan")
                    self._prior_5s_stats = {
                        "duration": dur,
                        "mfe": mfe_norm,
                        "mae": mae_norm,
                        "pnl": pnl_norm
                    }
                
                # Reset 5s tracking. Anchor the NEW regime's start at the flip
                # bar's CLOSE (the prior regime ended at this bar's open); using
                # open_ts would inflate prior_5s_duration by one 5s bucket (N2).
                self._5s_regime_start_ts = completed.close_ts
                self._5s_regime_start_px = completed.close
                self._5s_regime_mfe = 0.0
                self._5s_regime_mae = 0.0
                if self._active_1m_regime != 0:
                    self._5s_chop_count += 1

                # Check for scalp trigger!
                if self._active_1m_regime != 0 and now == self._active_1m_regime:
                    self._1m_ordinal += 1
                    self._5s_flip_count += 1

                    # Snapshot features causally. NOTE: the current flip's
                    # timestamp is appended to _5s_flips_timestamps AFTER this
                    # snapshot (below), so flips_60s/flips_120s count strictly
                    # PRIOR flips, not the triggering flip itself (W3).
                    features = self._snapshot_features(completed, state)

                    # Create pending scalp entry
                    self._pending_scalps.append({
                        "entry_id": self._entry_seq,
                        "year": self._year,
                        "direction": now,
                        "entry_ts": None,
                        "entry_px": None,
                        "atr_5s": state.atr,
                        "atr_1m": self._reg.get("1m").atr if self._reg.get("1m") is not None else float("nan"),
                        "features": features,
                        "path": [],
                        "started": False
                    })
                    self._entry_seq += 1
                # Record THIS flip's timestamp only after the snapshot (W3).
                self._5s_flips_timestamps.append(completed.close_ts / NS_PER_S)
            else:
                # Same regime, update excursions
                pnl = (completed.close - self._5s_regime_start_px) * now
                self._5s_regime_mfe = max(self._5s_regime_mfe, pnl)
                self._5s_regime_mae = max(self._5s_regime_mae, -pnl)
                
        self._prev_regimes[tf] = now

    def on_1s(self, o, h, l, c, v, tse, tsi):
        self._agg.on_1s_bar(int(tse), o, h, l, c, v)

        ts = int(tsi)

        # Accumulate OBV
        if self._active_1m_regime != 0:
            self._obv_signed_vol += v * np.sign(c - o)
            
            # Excursions of 1m regime
            pnl_1m = (c - self._px_1m_entry) * self._active_1m_regime
            self._1m_mfe = max(self._1m_mfe, pnl_1m)
            self._1m_mae = max(self._1m_mae, -pnl_1m)
            self._1m_cum_abs_move += abs(c - self._1m_prev_close)
            self._1m_prev_close = c
            
        # Excursions of 5m regime
        reg_5m = self._reg.get("5m")
        if reg_5m is not None and reg_5m.regime != 0:
            pnl_5m = (c - self._px_5m_entry) * reg_5m.regime
            self._5m_mfe = max(self._5m_mfe, pnl_5m)
            self._5m_mae = max(self._5m_mae, -pnl_5m)

        # Clear old 5s flip timestamps
        ts_s = ts / NS_PER_S
        while self._5s_flips_timestamps and self._5s_flips_timestamps[0] < ts_s - 120.0:
            self._5s_flips_timestamps.popleft()

        # Handle pending entries (executable on next 1s open). RTH-ONLY study
        # (W5): the fill bar's wall-clock (ts_event) in Central Time must fall in
        # the regular session [08:30, 15:00) CT. ETH triggers are dropped — thin
        # overnight liquidity makes the 0.5-tick slippage assumption unrealistic
        # and would pool a structurally different market with the RTH population.
        if self._pending_scalps:
            ct = pd.Timestamp(int(tse), tz="UTC").tz_convert(CT)
            min_ct = ct.hour * 60 + ct.minute
            rth = bool(RTH_START_MIN <= min_ct < RTH_END_MIN)
            if rth:
                for scalp in self._pending_scalps:
                    scalp["entry_ts"] = ts
                    scalp["entry_px"] = o
                    scalp["rth_flag"] = True
                    scalp["started"] = True
                    self._active_scalps.append(scalp)
            self._pending_scalps = []

        # Update active scalps paths
        s5 = self._reg.get("5s")
        s1m = self._reg.get("1m")
        reg5 = s5.regime if s5 is not None else 0
        reg1m = s1m.regime if s1m is not None else 0
        
        still_active = []
        for scalp in self._active_scalps:
            scalp["path"].append((ts, o, h, l, c, reg5, reg1m))
            
            # Stop collecting if:
            # 1. 300s limit reached
            # 2. opposite 1m regime or 1m regime closed (reg1m != scalp["direction"])
            # 3. end of data
            dur = (ts - scalp["entry_ts"]) / NS_PER_S
            parent_flipped = (reg1m != scalp["direction"])
            
            if dur >= 300 or parent_flipped:
                self.evaluate_scalp(scalp)
            else:
                still_active.append(scalp)
        self._active_scalps = still_active

    def evaluate_scalp(self, scalp):
        path = scalp["path"]
        if not path:
            return
            
        d = scalp["direction"]
        entry_px = scalp["entry_px"]
        entry_ts = scalp["entry_ts"]
        
        # Save entry record.
        # NOTE (W2): entry_ts is the fill bar's ts_init (= bar CLOSE time =
        # ts_event + 1s for 1s bars). The fill PRICE is that bar's OPEN, which
        # occurs at ts_event = entry_ts - 1_000_000_000 ns. To recover the
        # wall-clock market time of the entry, subtract 1s from entry_ts.
        rec_ent = {
            "entry_id": scalp["entry_id"],
            "year": scalp["year"],
            "direction": d,
            "entry_ts": entry_ts,
            "entry_px": entry_px,
            "rth_flag": scalp.get("rth_flag", False),
            "atr_5s": scalp["atr_5s"],
            "atr_1m": scalp["atr_1m"]
        }
        rec_ent.update(scalp["features"])
        self.records_entries.append(rec_ent)
        
        # Evaluate configurations (now 180 configs)
        rec_lbl = {"entry_id": scalp["entry_id"]}
        
        for pt_mult, sl_mult, br_name in BRACKET_CONFIGS:
            for atr_type in ("5s", "1m"):
                atr = scalp["atr_5s"] if atr_type == "5s" else scalp["atr_1m"]
                
                # If ATR is missing or invalid, default to 0
                if np.isnan(atr) or atr <= 0:
                    atr = 1.0
                    
                pt_pts = pt_mult * atr
                sl_pts = sl_mult * atr
                
                for exit_flavor in ("bo", "b5f"):
                    for max_hold in (30, 60, 90, 120, 300):
                        # Run path simulation
                        exit_px, exit_reason, exit_dt, mfe_pts, mae_pts = self._simulate_path(
                            path, d, entry_px, pt_pts, sl_pts, exit_flavor, max_hold, entry_ts
                        )
                        
                        pnl_pts = (exit_px - entry_px) * d
                        
                        col_prefix = f"{br_name}_{atr_type}_{exit_flavor}_{max_hold}"
                        rec_lbl[f"pnl_{col_prefix}"] = np.float32(pnl_pts)
                        
                        # Encode exit reason to int8
                        # 1: pt, 2: sl, 3: opposite_regime, 4: opposite_1m_regime, 5: max_hold, 6: end_of_data
                        reason_code = 6
                        if exit_reason == "pt": reason_code = 1
                        elif exit_reason == "sl": reason_code = 2
                        elif exit_reason == "opposite_regime": reason_code = 3
                        elif exit_reason == "opposite_1m_regime": reason_code = 4
                        elif exit_reason == "max_hold": reason_code = 5
                        
                        rec_lbl[f"reason_{col_prefix}"] = np.int8(reason_code)
                        rec_lbl[f"hold_{col_prefix}"] = np.int16(round(exit_dt))
                        rec_lbl[f"mfe_{col_prefix}"] = np.float16(mfe_pts)
                        rec_lbl[f"mae_{col_prefix}"] = np.float16(mae_pts)
                        
        self.records_labels.append(rec_lbl)

    def _simulate_path(self, path, d, entry_px, pt_pts, sl_pts, exit_flavor, max_hold, entry_ts):
        pt_px = entry_px + d * pt_pts
        sl_px = entry_px - d * sl_pts
        
        mfe_pts = 0.0
        mae_pts = 0.0
        
        for idx, (ts, o, h, l, c, reg_5s, reg_1m) in enumerate(path):
            dt = (ts - entry_ts) / NS_PER_S
            
            if dt >= max_hold:
                pnl_o = (o - entry_px) * d
                if pnl_o > 0:
                    mfe_pts = max(mfe_pts, pnl_o)
                else:
                    mae_pts = max(mae_pts, -pnl_o)
                return o, "max_hold", max_hold, mfe_pts, mae_pts
                
            # Regime-flip exits fill at THIS bar's OPEN (W6): the opposing 5s/1m
            # bucket closed on this bar, so the flip is known at the bar's open
            # instant — that is the earliest feasible (causal) exit price, and
            # it precedes this same bar's intrabar PT/SL. We exit AT the open,
            # so the bar's later h/l are not experienced — fold only the open
            # into the MFE/MAE diagnostics (mirrors the max_hold convention).
            if reg_1m == -d or reg_1m == 0:
                pnl_o = (o - entry_px) * d
                if pnl_o > 0:
                    mfe_pts = max(mfe_pts, pnl_o)
                else:
                    mae_pts = max(mae_pts, -pnl_o)
                return o, "opposite_1m_regime", dt, mfe_pts, mae_pts

            if exit_flavor == "b5f" and reg_5s == -d:
                pnl_o = (o - entry_px) * d
                if pnl_o > 0:
                    mfe_pts = max(mfe_pts, pnl_o)
                else:
                    mae_pts = max(mae_pts, -pnl_o)
                return o, "opposite_regime", dt, mfe_pts, mae_pts
                
            # PT / SL hits check
            if d == 1:
                if l <= sl_px and h >= pt_px:
                    mae_pts = max(mae_pts, sl_pts)
                    mfe_pts = max(mfe_pts, h - entry_px)
                    return sl_px, "sl", dt, mfe_pts, mae_pts
                elif l <= sl_px:
                    mae_pts = max(mae_pts, sl_pts)
                    mfe_pts = max(mfe_pts, h - entry_px)
                    return sl_px, "sl", dt, mfe_pts, mae_pts
                elif h >= pt_px:
                    mfe_pts = max(mfe_pts, pt_pts)
                    mae_pts = max(mae_pts, entry_px - l)
                    return pt_px, "pt", dt, mfe_pts, mae_pts
                else:
                    mfe_pts = max(mfe_pts, h - entry_px)
                    mae_pts = max(mae_pts, entry_px - l)
            else:
                if h >= sl_px and l <= pt_px:
                    mae_pts = max(mae_pts, sl_pts)
                    mfe_pts = max(mfe_pts, entry_px - l)
                    return sl_px, "sl", dt, mfe_pts, mae_pts
                elif h >= sl_px:
                    mae_pts = max(mae_pts, sl_pts)
                    mfe_pts = max(mfe_pts, entry_px - l)
                    return sl_px, "sl", dt, mfe_pts, mae_pts
                elif l <= pt_px:
                    mfe_pts = max(mfe_pts, pt_pts)
                    mae_pts = max(mae_pts, h - entry_px)
                    return pt_px, "pt", dt, mfe_pts, mae_pts
                else:
                    mfe_pts = max(mfe_pts, entry_px - l)
                    mae_pts = max(mae_pts, h - entry_px)
                    
        if d == 1:
            mfe_pts = max(mfe_pts, path[-1][2] - entry_px)
            mae_pts = max(mae_pts, entry_px - path[-1][3])
        else:
            mfe_pts = max(mfe_pts, entry_px - path[-1][3])
            mae_pts = max(mae_pts, path[-1][2] - entry_px)
        return path[-1][4], "end_of_data", (path[-1][0] - entry_ts) / NS_PER_S, mfe_pts, mae_pts

    def _snapshot_features(self, completed_5s: _OpenBucket, state_5s: CompletedBarState) -> dict:
        # HARD CAUSALITY GUARD (W1): the decision time is the just-closed 5s
        # bucket's close_ts. Every registry state we read below MUST have
        # close_ts <= decision_ts. This is logically guaranteed by the TF
        # iteration order, but we assert it explicitly so any future refactor
        # that breaks the ordering raises CausalityViolation loudly instead of
        # silently leaking a not-yet-closed bar.
        self._reg.audit_provenance(completed_5s.close_ts)
        c = completed_5s.close
        d = state_5s.regime
        atr_5s = state_5s.atr
        
        state_1m = self._reg.get("1m")
        atr_1m = state_1m.atr if state_1m is not None else float("nan")
        reg_1m = state_1m.regime if state_1m is not None else 0
        
        state_5m = self._reg.get("5m")
        atr_5m = state_5m.atr if state_5m is not None else float("nan")
        reg_5m = state_5m.regime if state_5m is not None else 0
        
        # Flips count in sliding windows
        now_s = completed_5s.close_ts / NS_PER_S
        flips_60 = sum(1 for t in self._5s_flips_timestamps if t >= now_s - 60.0)
        flips_120 = sum(1 for t in self._5s_flips_timestamps if t >= now_s - 120.0)
        
        # Volume features
        vol_5s = completed_5s.volume
        vol_5s_rolling = list(self._fm.vols["5s"])[-20:]
        vol_5s_avg = np.mean(vol_5s_rolling) if len(vol_5s_rolling) >= 10 else float("nan")
        vol_5s_vs_avg = vol_5s / vol_5s_avg if vol_5s_avg > 0 else float("nan")
        
        vol_5s_prev = list(self._fm.vols["5s"])[-6:-1]
        vol_5s_accel = vol_5s - np.mean(vol_5s_prev) if len(vol_5s_prev) >= 5 else float("nan")
        
        # Current-1m participation vs recent average: use the LAST CLOSED 1m
        # bar's volume (causal) vs the rolling mean of recent closed 1m bars.
        # (Do NOT use a global cumulative counter — that grows monotonically
        # across the whole replay and makes the ratio meaningless.)
        vols_1m_rolling = list(self._fm.vols["1m"])[-20:]
        vol_1m_avg = np.mean(vols_1m_rolling) if len(vols_1m_rolling) >= 10 else float("nan")
        vol_1m_last = vols_1m_rolling[-1] if vols_1m_rolling else float("nan")
        vol_1m_ratio = vol_1m_last / vol_1m_avg if vol_1m_avg > 0 else float("nan")
        
        vol_aligned_ratio = self._aligned_5s_vol / self._opposing_5s_vol if self._opposing_5s_vol > 0 else float("nan")
        
        # Vol percentile
        vols_5s_all = list(self._fm.vols["5s"])
        vol_pctile = sum(1 for v in vols_5s_all if v <= vol_5s) / len(vols_5s_all) if vols_5s_all else float("nan")
        
        # Excursion ratios
        mfe_mae_1m_ratio = self._1m_mfe / self._1m_mae if self._1m_mae > 0 else float("nan")
        mfe_mae_5m_ratio = self._5m_mfe / self._5m_mae if self._5m_mae > 0 else float("nan")
        
        # Flip bar details
        rng_5s = completed_5s.high - completed_5s.low
        rng_5s_atr = rng_5s / atr_5s if atr_5s > 0 else float("nan")
        body_5s_pct = abs(completed_5s.close - completed_5s.open) / rng_5s if rng_5s > 0 else 0.0
        
        close_loc_5s = 0.5
        if rng_5s > 0:
            if d == 1:
                close_loc_5s = (completed_5s.close - completed_5s.low) / rng_5s
            else:
                close_loc_5s = (completed_5s.high - completed_5s.close) / rng_5s

        f = {
            # Position
            "time_since_1m": (completed_5s.close_ts - self._ts_1m_regime_start) / NS_PER_S,
            "1m_ordinal": self._1m_ordinal,
            "5s_flip_count": self._5s_flip_count,
            
            # 1m Quality
            "1m_pnl_atr": (c - self._px_1m_entry) * d / atr_1m if atr_1m > 0 else float("nan"),
            "1m_mfe_atr": self._1m_mfe / atr_1m if atr_1m > 0 else float("nan"),
            "1m_mae_atr": self._1m_mae / atr_1m if atr_1m > 0 else float("nan"),
            "1m_mfe_mae_ratio": mfe_mae_1m_ratio,
            "1m_path_efficiency": ((c - self._px_1m_entry) * d) / self._1m_cum_abs_move if self._1m_cum_abs_move > 0 else float("nan"),
            "1m_reached_025": int(self._1m_mfe / atr_1m >= 0.25) if atr_1m > 0 else 0,
            "1m_reached_050": int(self._1m_mfe / atr_1m >= 0.50) if atr_1m > 0 else 0,
            "1m_reached_100": int(self._1m_mfe / atr_1m >= 1.00) if atr_1m > 0 else 0,
            "1m_reached_150": int(self._1m_mfe / atr_1m >= 1.50) if atr_1m > 0 else 0,
            "1m_net_positive": int((c - self._px_1m_entry) * d > 0),
            
            # 5s Structure
            "prior_5s_duration": self._prior_5s_stats["duration"],
            "prior_5s_mfe": self._prior_5s_stats["mfe"],
            "prior_5s_mae": self._prior_5s_stats["mae"],
            "prior_5s_pnl": self._prior_5s_stats["pnl"],
            "flips_60s": flips_60,
            "flips_120s": flips_120,
            "5s_chop_count": self._5s_chop_count,
            "flip_bar_range_atr": rng_5s_atr,
            "flip_bar_body_pct": body_5s_pct,
            "flip_bar_close_loc": close_loc_5s,
            
            # EMA Geometry
            "ema3_1m_dist_atr": self._fm.get_dist("1m", 3, c, d, atr_1m),
            "ema9_1m_dist_atr": self._fm.get_dist("1m", 9, c, d, atr_1m),
            "ema13_1m_dist_atr": self._fm.get_dist("1m", 13, c, d, atr_1m),
            "ema21_1m_dist_atr": self._fm.get_dist("1m", 21, c, d, atr_1m),
            
            "ema3_5s_dist_atr": self._fm.get_dist("5s", 3, c, d, atr_5s),
            "ema9_5s_dist_atr": self._fm.get_dist("5s", 9, c, d, atr_5s),
            "ema13_5s_dist_atr": self._fm.get_dist("5s", 13, c, d, atr_5s),
            "ema21_5s_dist_atr": self._fm.get_dist("5s", 21, c, d, atr_5s),
            
            "ema3_1m_slope": self._fm.get_slope("1m", 3, atr_1m),
            "ema9_1m_slope": self._fm.get_slope("1m", 9, atr_1m),
            "ema13_1m_slope": self._fm.get_slope("1m", 13, atr_1m),
            "ema21_1m_slope": self._fm.get_slope("1m", 21, atr_1m),
            
            "ema3_5s_slope": self._fm.get_slope("5s", 3, atr_5s),
            "ema9_5s_slope": self._fm.get_slope("5s", 9, atr_5s),
            "ema13_5s_slope": self._fm.get_slope("5s", 13, atr_5s),
            "ema21_5s_slope": self._fm.get_slope("5s", 21, atr_5s),
            
            "spread_3_9_1m": self._fm.get_spread("1m", 3, 9, atr_1m),
            "spread_9_21_1m": self._fm.get_spread("1m", 9, 21, atr_1m),
            "spread_3_9_5s": self._fm.get_spread("5s", 3, 9, atr_5s),
            "spread_9_21_5s": self._fm.get_spread("5s", 9, 21, atr_5s),
            
            "ema9_1m_slope_accel": self._fm.get_slope_accel("1m", 9),
            "ema9_5s_slope_accel": self._fm.get_slope_accel("5s", 9),
            
            # 5m Context
            "regime_5m": reg_5m,
            "aligned_5m_1m": int(reg_5m == reg_1m and reg_5m != 0),
            "ema9_5m_slope": self._fm.get_slope("5m", 9, atr_1m),
            "spread_9_21_5m": self._fm.get_spread("5m", 9, 21, atr_1m),
            "ema9_5m_dist_atr": self._fm.get_dist("5m", 9, c, d, atr_1m),
            "ema21_5m_dist_atr": self._fm.get_dist("5m", 21, c, d, atr_1m),
            "age_5m": state_5m.bars_in_regime if state_5m is not None else 0,
            "mfe_5m_atr": self._5m_mfe / atr_1m if atr_1m > 0 else float("nan"),
            "mae_5m_atr": self._5m_mae / atr_1m if atr_1m > 0 else float("nan"),
            
            # Volume
            "vol_5s": vol_5s,
            "vol_5s_vs_avg": vol_5s_vs_avg,
            "vol_5s_accel": vol_5s_accel,
            "vol_1m_ratio": vol_1m_ratio,
            "vol_aligned_5s": self._aligned_5s_vol,
            "vol_opposing_5s": self._opposing_5s_vol,
            "vol_aligned_opposing_ratio": vol_aligned_ratio,
            "obv_signed_vol": self._obv_signed_vol,
            "vol_pctile": vol_pctile
        }
        return f

    def finalize(self):
        # Force exit any remaining active scalps
        s1m = self._reg.get("1m")
        if s1m is not None:
            for scalp in self._active_scalps:
                self.evaluate_scalp(scalp)
        self._active_scalps = []


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
    
    rep = ScalpReplay(year)
    t0 = time.time()
    # Warmup is handled by the lead-in: load_start is `year-01-01` minus
    # lead_in_days, so ATR/EMA/regime warm up on the lead-in bars before any
    # in-year signal can trigger. Entries during the lead-in are discarded by
    # the post-replay year filter (entry_ts >= yr0) below. All bars are streamed
    # identically; there is no special warmup code path.
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
    print(f"  replay done ({time.time()-t0:.0f}s); entries={len(rep.records_entries):,}")
    
    # Filter to in-year rows based on matched timestamps
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    
    df_ent = pd.DataFrame(rep.records_entries)
    if df_ent.empty:
        print(f"No trades triggered for {year}")
        return
        
    df_ent = df_ent[(df_ent.entry_ts >= yr0) & (df_ent.entry_ts <= yr1)].copy()
    valid_eids = set(df_ent["entry_id"])
    
    df_lbl = pd.DataFrame(rep.records_labels)
    if not df_lbl.empty:
        df_lbl = df_lbl[df_lbl["entry_id"].isin(valid_eids)].copy()
        
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_smoke{smoke}" if smoke else ""
    
    df_ent.to_parquet(OUT / f"{PREFIX}5s_scalp_entries_{year}{suffix}.parquet", index=False)
    df_lbl.to_parquet(OUT / f"{PREFIX}5s_scalp_labels_{year}{suffix}.parquet", index=False)
    print(f"  saved parquets for {year}. Entries={len(df_ent):,}, Labels={len(df_lbl):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NQ", choices=sorted(INSTRUMENTS))
    ap.add_argument("--years", default="2021,2022,2023,2024")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()

    global CATALOG, BAR_TYPE, PREFIX
    cfg = INSTRUMENTS[args.instrument]
    CATALOG = cfg["catalog"]; BAR_TYPE = cfg["bar_type"]; PREFIX = cfg["prefix"]
    print(f"Instrument={args.instrument}  catalog={CATALOG}  prefix='{PREFIX}'")

    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y, smoke=args.smoke)
        
if __name__ == "__main__":
    main()

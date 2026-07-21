"""RLFeatureCollector — NT Strategy for RL regime feasibility study.

Subscribes to 1s bars.  Uses TimeframeAggregator for 5s/30s/1m/5m bucketing.

CAUSALITY GUARANTEE
-------------------
on_bar dispatches to the aggregator FIRST (fires bucket callbacks), then
calls _update_rolling().  This means when any bucket-close callback executes,
the rolling trackers (Kalman, close deque, volume) reflect data through the
bar BEFORE the triggering bar.  The triggering bar's data is added to rolling
trackers only after all callbacks return.

Episode lifecycle
-----------------
  Start : first 1m regime flip (0→±1 or +1→-1) with valid ATR.
  End   : opposing 1m flip (finalized inside _on_1m_close),
          30-min timeout (finalized inside _on_5s_close),
          data end (finalized in on_stop).

Each 5s bucket close during an active episode logs one observation row.
When episode ends, all rows in that episode are stamped with
termination_reason and episode_end_time, then appended to obs_log.
"""
from __future__ import annotations

import datetime
import math
import sys
from collections import deque
from pathlib import Path
from typing import Optional

import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket
from collectors.collector_v2.registry import CompletedBarRegistry, CompletedBarState

from studies.rl_regime_feasibility.execution import NS_PER_S, MAX_EPISODE_S
from studies.rl_regime_feasibility.feature_state import (
    RegimeEngine, WilderADX, KalmanPV,
    BollingerKeltner, VolTracker, CloseReturnDeque, TrailingRange,
)

# ── Constants ────────────────────────────────────────────────────────────────

_NS_30MIN    = MAX_EPISODE_S * NS_PER_S
_NS_PER_S    = NS_PER_S
_NS_15S      = 15 * NS_PER_S
_NS_30S      = 30 * NS_PER_S
_NS_60S      = 60 * NS_PER_S

_CT            = pytz.timezone("America/Chicago")
_RTH_OPEN_CT   = datetime.time(8, 30)   # 08:30 CT (DST-aware)
_RTH_CLS_CT    = datetime.time(15, 0)   # 15:00 CT

_FEATURES = [
    "seconds_since_flip", "current_progress_atr", "max_progress_atr",
    "max_adverse_atr", "pullback_from_peak_atr", "seconds_since_peak",
    "progress_efficiency", "aligned_return_5s_atr", "aligned_return_15s_atr",
    "aligned_return_30s_atr", "aligned_return_60s_atr", "realized_vol_60s_atr",
    "range_5s_atr", "volume_5s_zscore", "volume_30s_vs_5m",
    "bollinger_width_percentile_1m", "bollinger_keltner_width_ratio_1m",
    "kalman_velocity_atr_per_s", "kalman_acceleration_atr_per_s2",
    "kalman_innovation_zscore", "ema3_ema9_spread_30s_atr",
    "regime_5s_aligned", "regime_30s_aligned", "regime_5m_aligned",
    "regime_age_1m_bars", "adx14_1m", "position_in_trailing_1m_range",
    "minutes_since_rth_open",
]


# ── Config ────────────────────────────────────────────────────────────────────

class RLCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s:   str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"


# ── Strategy ──────────────────────────────────────────────────────────────────

class RLFeatureCollector(Strategy):

    def __init__(self, config: RLCollectorConfig) -> None:
        super().__init__(config)
        self._cfg = config

        # Aggregator fires 5s/30s/1m/5m callbacks
        self._agg = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=("5s", "30s", "1m", "5m"),
        )

        # Registry for causal provenance audit
        self._reg = CompletedBarRegistry(supported_timeframes=("5s", "30s", "1m", "5m"))

        # Per-timeframe regime engines
        self._1m_eng  = RegimeEngine()
        self._5m_eng  = RegimeEngine()
        self._30s_eng = RegimeEngine()
        self._5s_eng  = RegimeEngine()

        # 1m-specific indicators
        self._adx  = WilderADX()
        self._bk   = BollingerKeltner()
        self._rng  = TrailingRange(n=20)

        # Rolling indicators (updated AFTER aggregator)
        self._kalman = KalmanPV()
        self._vol    = VolTracker()
        self._closes = CloseReturnDeque()

        # Previous 1m regime for flip detection
        self._prev_1m_regime: int = 0

        # Episode state
        self._ep_active:   bool           = False
        self._ep_dir:      int            = 0
        self._ep_flip_ts:  int            = 0
        self._ep_flip_cl:  float          = 0.0
        self._ep_atr:      float          = 0.0
        self._ep_step:     int            = 0
        self._ep_max_prog: float          = 0.0
        self._ep_peak_ts:  int            = 0
        self._ep_max_adv:  float          = 0.0
        self._ep_prev5_cl: float          = 0.0   # previous 5s close in episode
        self._ep_end_rsn:  str            = ""
        self._ep_end_ts:   int            = 0
        self._ep_obs:      list[dict]     = []

        # Output
        self.obs_log: list[dict] = []

    # ── NT lifecycle ──────────────────────────────────────────────────────────

    def on_start(self) -> None:
        bar_type = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        # Step 1: feed aggregator — may fire bucket callbacks
        self._agg.on_1s_bar(
            int(bar.ts_init),
            float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), float(bar.volume),
        )
        # Step 2: update rolling trackers AFTER callbacks
        self._update_rolling(bar)

    def on_stop(self) -> None:
        if self._ep_active:
            self._finalize_episode("data_end", self._ep_flip_ts + _NS_30MIN)

    # ── Aggregator callbacks ──────────────────────────────────────────────────

    def _on_bucket_closed(self, tf: str, bucket: _OpenBucket) -> None:
        if   tf == "1m":  self._on_1m_close(bucket)
        elif tf == "5m":  self._on_5m_close(bucket)
        elif tf == "30s": self._on_30s_close(bucket)
        elif tf == "5s":  self._on_5s_close(bucket)

    def _on_1m_close(self, bucket: _OpenBucket) -> None:
        old_regime = self._1m_eng.regime
        self._1m_eng.update(bucket.high, bucket.low, bucket.close)
        new_regime = self._1m_eng.regime
        atr = self._1m_eng.atr

        # Update 1m-specific indicators
        self._adx.update(bucket.high, bucket.low, bucket.close)
        self._bk.update(bucket.high, bucket.low, bucket.close)
        self._rng.update(bucket.high, bucket.low)

        # Update registry
        if atr is not None:
            self._reg.update("1m", CompletedBarState(
                timeframe="1m",
                open_ts=bucket.open_ts, close_ts=bucket.close_ts,
                open=bucket.open, high=bucket.high, low=bucket.low,
                close=bucket.close, volume=bucket.volume,
                regime=self._1m_eng.regime,
                bars_in_regime=self._1m_eng.bars_in_regime,
                atr=atr,
                ema3_h=self._1m_eng.ema3_h or 0.0,
                ema9_h=self._1m_eng.ema9_h or 0.0,
                ema3_l=self._1m_eng.ema3_l or 0.0,
                ema9_l=self._1m_eng.ema9_l or 0.0,
            ))

        # Flip detection
        if new_regime != 0 and new_regime != old_regime:
            if self._ep_active:
                self._finalize_episode("opposing_flip", bucket.close_ts)
            if atr is not None and atr > 0:
                self._start_episode(new_regime, bucket.close, bucket.close_ts, atr)

    def _on_5m_close(self, bucket: _OpenBucket) -> None:
        self._5m_eng.update(bucket.high, bucket.low, bucket.close)
        atr = self._5m_eng.atr
        self._vol.push_5m(bucket.volume)
        if atr is not None:
            self._reg.update("5m", CompletedBarState(
                timeframe="5m",
                open_ts=bucket.open_ts, close_ts=bucket.close_ts,
                open=bucket.open, high=bucket.high, low=bucket.low,
                close=bucket.close, volume=bucket.volume,
                regime=self._5m_eng.regime,
                bars_in_regime=self._5m_eng.bars_in_regime,
                atr=atr,
                ema3_h=self._5m_eng.ema3_h or 0.0,
                ema9_h=self._5m_eng.ema9_h or 0.0,
                ema3_l=self._5m_eng.ema3_l or 0.0,
                ema9_l=self._5m_eng.ema9_l or 0.0,
            ))

    def _on_30s_close(self, bucket: _OpenBucket) -> None:
        self._30s_eng.update(bucket.high, bucket.low, bucket.close)
        atr = self._30s_eng.atr
        self._vol.push_30s(bucket.volume)
        if atr is not None:
            self._reg.update("30s", CompletedBarState(
                timeframe="30s",
                open_ts=bucket.open_ts, close_ts=bucket.close_ts,
                open=bucket.open, high=bucket.high, low=bucket.low,
                close=bucket.close, volume=bucket.volume,
                regime=self._30s_eng.regime,
                bars_in_regime=self._30s_eng.bars_in_regime,
                atr=atr,
                ema3_h=self._30s_eng.ema3_h or 0.0,
                ema9_h=self._30s_eng.ema9_h or 0.0,
                ema3_l=self._30s_eng.ema3_l or 0.0,
                ema9_l=self._30s_eng.ema9_l or 0.0,
            ))

    def _on_5s_close(self, bucket: _OpenBucket) -> None:
        obs_ts = bucket.close_ts  # decision time

        # Update 5s regime engine
        self._5s_eng.update(bucket.high, bucket.low, bucket.close)
        atr_5s = self._5s_eng.atr
        self._vol.on_5s_close(bucket.volume)

        # Update 5s registry
        if atr_5s is not None:
            self._reg.update("5s", CompletedBarState(
                timeframe="5s",
                open_ts=bucket.open_ts, close_ts=bucket.close_ts,
                open=bucket.open, high=bucket.high, low=bucket.low,
                close=bucket.close, volume=bucket.volume,
                regime=self._5s_eng.regime,
                bars_in_regime=self._5s_eng.bars_in_regime,
                atr=atr_5s,
                ema3_h=self._5s_eng.ema3_h or 0.0,
                ema9_h=self._5s_eng.ema9_h or 0.0,
                ema3_l=self._5s_eng.ema3_l or 0.0,
                ema9_l=self._5s_eng.ema9_l or 0.0,
            ))

        if not self._ep_active:
            return

        # Check 30-minute timeout
        terminated = False
        end_reason = self._ep_end_rsn  # set by _on_1m_close if opposing flip
        end_ts     = self._ep_end_ts

        if obs_ts >= self._ep_flip_ts + _NS_30MIN:
            terminated  = True
            end_reason  = "max_duration"
            end_ts      = self._ep_flip_ts + _NS_30MIN  # cap at exactly 30min

        # Provenance audit
        try:
            self._reg.audit_provenance(obs_ts)
        except Exception as e:
            self.log.error(f"audit_provenance FAILED at {obs_ts}: {e}")
            raise

        # Update path state BEFORE obs so max_progress_atr includes current step
        d_ep  = self._ep_dir
        atr_e = self._ep_atr
        cur_prog = d_ep * (bucket.close - self._ep_flip_cl) / atr_e if atr_e > 0 else 0.0
        if cur_prog > self._ep_max_prog:
            self._ep_max_prog = cur_prog
            self._ep_peak_ts  = obs_ts
        adv = -cur_prog
        if adv > self._ep_max_adv:
            self._ep_max_adv = adv

        # Compute and log this observation
        row = self._compute_obs(bucket, obs_ts)
        row["termination_reason"] = end_reason
        row["episode_end_time"]   = end_ts
        self._ep_obs.append(row)
        self._ep_step += 1
        self._ep_prev5_cl = bucket.close

        if terminated:
            self._finalize_episode(end_reason, end_ts)

    # ── Rolling tracker update (AFTER aggregator) ─────────────────────────────

    def _update_rolling(self, bar: Bar) -> None:
        ts  = int(bar.ts_event)
        c   = float(bar.close)
        v   = float(bar.volume)
        self._kalman.update(c, dt=1.0)
        self._closes.push(ts, c)
        self._vol.push_1s(v)

    # ── Episode management ────────────────────────────────────────────────────

    def _start_episode(self, direction: int, flip_close: float,
                       flip_ts: int, atr: float) -> None:
        self._ep_active   = True
        self._ep_dir      = direction
        self._ep_flip_ts  = flip_ts
        self._ep_flip_cl  = flip_close
        self._ep_atr      = atr
        self._ep_step     = 0
        self._ep_max_prog = 0.0
        self._ep_peak_ts  = flip_ts
        self._ep_max_adv  = 0.0
        self._ep_prev5_cl = flip_close
        self._ep_end_rsn  = ""
        self._ep_end_ts   = 0
        self._ep_obs      = []

    def _finalize_episode(self, reason: str, end_ts: int) -> None:
        for row in self._ep_obs:
            row["termination_reason"] = reason
            row["episode_end_time"]   = end_ts
        self.obs_log.extend(self._ep_obs)
        self._ep_active = False
        self._ep_obs    = []
        self._ep_end_rsn = ""
        self._ep_end_ts  = 0

    # ── Feature computation ───────────────────────────────────────────────────

    def _compute_obs(self, bucket: _OpenBucket, obs_ts: int) -> dict:
        d      = self._ep_dir
        atr    = self._ep_atr
        cl     = bucket.close   # current price (last 1s close in 5s bucket)

        # ── Path state ────────────────────────────────────────────────────────
        prog   = d * (cl - self._ep_flip_cl) / atr if atr > 0 else 0.0
        sec_flip = (obs_ts - self._ep_flip_ts) / _NS_PER_S
        sec_peak = (obs_ts - self._ep_peak_ts) / _NS_PER_S
        pull   = self._ep_max_prog - prog
        eff    = self._ep_max_prog / max(1.0, sec_flip / 60.0)

        # ── Returns (close deque has closes through last _update_rolling bar) ─
        c_5s  = self._ep_prev5_cl
        r5s   = d * (cl - c_5s) / atr if atr > 0 else 0.0

        def _aligned_ret(n_s: int) -> float:
            past = self._closes.get_close_at(obs_ts - n_s * _NS_PER_S)
            if past is None:
                return float("nan")
            return d * (cl - past) / atr if atr > 0 else float("nan")

        r15s  = _aligned_ret(15)
        r30s  = _aligned_ret(30)
        r60s  = _aligned_ret(60)

        # ── Realized vol ──────────────────────────────────────────────────────
        rvol_pts = self._closes.realized_vol(60)
        rvol = rvol_pts / atr if (not math.isnan(rvol_pts) and atr > 0) else float("nan")

        # ── 5s bar stats ──────────────────────────────────────────────────────
        range_5s = (bucket.high - bucket.low) / atr if atr > 0 else 0.0

        # ── Volume ────────────────────────────────────────────────────────────
        vol_zs  = self._vol.volume_5s_zscore
        vol_30_5m = self._vol.volume_30s_vs_5m

        # ── Bollinger/Keltner ─────────────────────────────────────────────────
        bb_pct = self._bk.bb_pctile if not math.isnan(self._bk.bb_pctile) else float("nan")
        bk_rat = self._bk.bk_ratio  if not math.isnan(self._bk.bk_ratio)  else float("nan")

        # ── Kalman ────────────────────────────────────────────────────────────
        kv = self._kalman.velocity   / atr if (self._kalman.is_warm and atr > 0) else float("nan")
        ka = self._kalman.d_velocity / atr if (self._kalman.is_warm and atr > 0) else float("nan")
        ki = self._kalman.innov_zscore if self._kalman.is_warm else float("nan")

        # ── 30s EMA spread ────────────────────────────────────────────────────
        s30 = self._reg.get("30s")
        if s30 and atr > 0:
            if d == 1:
                spread = s30.ema3_h - s30.ema9_h
            else:
                spread = s30.ema9_l - s30.ema3_l
            ema_spread = spread / atr
        else:
            ema_spread = float("nan")

        # ── Multi-TF regime alignment ─────────────────────────────────────────
        def _align(regime: int) -> int:
            if regime == 0:   return 0
            return 1 if regime == d else -1

        r5s_a  = _align(self._5s_eng.regime)
        r30_a  = _align(self._30s_eng.regime)
        r5m_a  = _align(self._5m_eng.regime)

        # ── 1m regime age ─────────────────────────────────────────────────────
        reg_age = self._1m_eng.bars_in_regime

        # ── ADX ───────────────────────────────────────────────────────────────
        adx_val = self._adx.value  # nan until 28 bars

        # ── Position in trailing 1m range ─────────────────────────────────────
        pos_range = self._rng.position(cl)

        # ── Minutes since RTH open ────────────────────────────────────────────
        min_rth = _minutes_since_rth(obs_ts)

        # ── Assemble ──────────────────────────────────────────────────────────
        ep_id = f"{self._ep_flip_ts}_{'+1' if d == 1 else '-1'}"
        return {
            # Episode metadata
            "episode_id":    ep_id,
            "step_index":    self._ep_step,
            "observation_time": obs_ts,
            "flip_time":     self._ep_flip_ts,
            "flip_close":    self._ep_flip_cl,
            "atr_at_flip":   atr,
            "direction":     d,
            # These two are filled in by _finalize_episode or set above:
            "termination_reason": self._ep_end_rsn,
            "episode_end_time":   self._ep_end_ts,
            # ── 28 features ──────────────────────────────────────────────────
            "seconds_since_flip":             sec_flip,
            "current_progress_atr":           prog,
            "max_progress_atr":               self._ep_max_prog,
            "max_adverse_atr":                self._ep_max_adv,
            "pullback_from_peak_atr":         pull,
            "seconds_since_peak":             sec_peak,
            "progress_efficiency":            eff,
            "aligned_return_5s_atr":          r5s,
            "aligned_return_15s_atr":         r15s,
            "aligned_return_30s_atr":         r30s,
            "aligned_return_60s_atr":         r60s,
            "realized_vol_60s_atr":           rvol,
            "range_5s_atr":                   range_5s,
            "volume_5s_zscore":               vol_zs,
            "volume_30s_vs_5m":               vol_30_5m,
            "bollinger_width_percentile_1m":  bb_pct,
            "bollinger_keltner_width_ratio_1m": bk_rat,
            "kalman_velocity_atr_per_s":      kv,
            "kalman_acceleration_atr_per_s2": ka,
            "kalman_innovation_zscore":       ki,
            "ema3_ema9_spread_30s_atr":       ema_spread,
            "regime_5s_aligned":              r5s_a,
            "regime_30s_aligned":             r30_a,
            "regime_5m_aligned":              r5m_a,
            "regime_age_1m_bars":             reg_age,
            "adx14_1m":                       adx_val,
            "position_in_trailing_1m_range":  pos_range,
            "minutes_since_rth_open":         min_rth,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minutes_since_rth(ts_ns: int) -> float:
    """Minutes since 08:30 CT (RTH open). NaN outside 08:30–15:00 CT. DST-aware."""
    utc_dt = datetime.datetime(1970, 1, 1, tzinfo=pytz.utc) + datetime.timedelta(
        seconds=ts_ns / 1e9
    )
    ct_dt   = utc_dt.astimezone(_CT)
    ct_time = ct_dt.time()
    if ct_time < _RTH_OPEN_CT or ct_time >= _RTH_CLS_CT:
        return float("nan")
    open_secs = _RTH_OPEN_CT.hour * 3600 + _RTH_OPEN_CT.minute * 60
    cur_secs  = ct_time.hour * 3600 + ct_time.minute * 60 + ct_time.second
    return (cur_secs - open_secs) / 60.0

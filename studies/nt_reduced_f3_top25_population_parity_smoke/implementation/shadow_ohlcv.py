"""Diagnostic-only shadow re-implementation of `OHLCVDeltaTracker`'s output
features, used ONLY to cross-check the live tracker during the targeted
first-divergence audit (see diagnostics/run_targeted_replay.py). This module
must never be imported by strategy.py, reduced_feature_engine.py, or any
other code path that feeds candidate generation, features, scores, orders,
or trades -- it exists purely to give the audit a second, independently
computed answer to compare the live tracker against.

Design choice (deliberate): ShadowOHLCVCalculator is fed the EXACT SAME call
sequence (update / accumulate_regime_rth / reset_regime / reset_rth /
end_rth) as the live `OHLCVDeltaTracker`, but every output figure is computed
by a FRESH recomputation over retained history at `calculate()` time -- never
via an incrementally-updated running total. This means the shadow cannot
inherit an incremental-accumulation bug the live tracker might have, while
still being sensitive to a call-sequencing/timing bug shared by both (since
both are driven by the identical sequence of calls from the harness). This
directly supports the required 3-way classification:
    shadow == offline, live != shadow  -> live tracker internal state/update defect
    live == shadow, both != offline    -> timestamp/call-sequence/offline-contract mismatch
    all three differ                   -> candidate key / observation timestamp /
                                            source-history mismatch
`calculate()` takes an EXPLICIT `observation_ts` rather than inferring it from
the last-appended bar (unlike the live tracker's `int(ts[-1])`) -- this is
itself a diagnostic: if `observation_ts != self.ts[-1]` at comparison time,
that mismatch is recorded and is significant on its own.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from features.trackers.ohlcv_delta import EPS, NS, WINDOWS_S, bar_estimates

WINDOW_KEYS: Tuple[str, ...] = (
    "vol_sum", "vol_mean_1s", "vol_max_1s", "est_bull_vol_sum",
    "est_bear_vol_sum", "est_delta_sum", "est_abs_delta_sum",
    "est_delta_ratio", "est_delta_pos_sum", "est_delta_neg_sum",
    "upbar_vol_sum", "downbar_vol_sum", "up_down_vol_ratio",
    "price_change_points", "price_change_atr", "range_points",
    "range_atr", "volume_per_point_moved", "volume_per_atr_moved",
    "abs_delta_per_point_moved", "abs_delta_per_atr_moved",
)


class ShadowOHLCVCalculator:
    def __init__(self, maxlen: int = 4000):
        self.maxlen = maxlen
        self.ts: List[int] = []
        self.opens: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.closes: List[float] = []
        self.volumes: List[float] = []
        self.est_deltas: List[float] = []

        # A4: regime-relative log (list of raw bars since last reset_regime,
        # summed FRESH at calculate() time -- see module docstring).
        self._regime_start_ts: Optional[int] = None
        self._regime_anchor_price: Optional[float] = None
        self._regime_log: List[Tuple[int, float, float, float, float]] = []  # ts, high, low, vol, delta

        # A5: RTH-session log.
        self._rth_active = False
        self._rth_start_ts: Optional[int] = None
        self._rth_log: List[Tuple[int, float, float]] = []  # ts, vol, delta

        # Update-integrity bookkeeping.
        self.update_count_by_ts: Dict[int, int] = {}
        self.out_of_order_count = 0
        self.last_update_ts: Optional[int] = None

    # -- update / reset, mirrors OHLCVDeltaTracker's call surface exactly ---

    def update(self, ts_event: int, open_px: float, high: float, low: float,
              close: float, volume: float) -> Dict[str, object]:
        ts_event = int(ts_event)
        self.update_count_by_ts[ts_event] = self.update_count_by_ts.get(ts_event, 0) + 1
        if self.last_update_ts is not None and ts_event <= self.last_update_ts:
            self.out_of_order_count += 1
        self.last_update_ts = ts_event

        b = bar_estimates(open_px, high, low, close, volume)
        self.ts.append(ts_event)
        self.opens.append(float(open_px))
        self.highs.append(float(high))
        self.lows.append(float(low))
        self.closes.append(float(close))
        self.volumes.append(float(volume))
        self.est_deltas.append(b["bar_est_delta"])
        if len(self.ts) > self.maxlen:
            n_drop = len(self.ts) - self.maxlen
            self.ts = self.ts[n_drop:]
            self.opens = self.opens[n_drop:]
            self.highs = self.highs[n_drop:]
            self.lows = self.lows[n_drop:]
            self.closes = self.closes[n_drop:]
            self.volumes = self.volumes[n_drop:]
            self.est_deltas = self.est_deltas[n_drop:]
        return b

    def accumulate_regime_rth(self, ts_event: int, high: float, low: float,
                              volume: float, est_delta: float) -> None:
        ts_event = int(ts_event)
        if self._regime_start_ts is not None:
            self._regime_log.append((ts_event, float(high), float(low), float(volume), float(est_delta)))
        if self._rth_active:
            self._rth_log.append((ts_event, float(volume), float(est_delta)))

    def reset_regime(self, ts_event: int, anchor_price: float) -> None:
        self._regime_start_ts = int(ts_event)
        self._regime_anchor_price = float(anchor_price)
        self._regime_log = []

    def reset_rth(self, ts_event: int) -> None:
        self._rth_active = True
        self._rth_start_ts = int(ts_event)
        self._rth_log = []

    def end_rth(self) -> None:
        self._rth_active = False

    # -- calculate, fresh recompute every call -------------------------------

    def calculate(self, observation_ts: int, atr: float) -> Dict[str, object]:
        observation_ts = int(observation_ts)
        n = len(self.ts)
        out: Dict[str, object] = {
            "shadow_obs_ts_matches_last_bar": bool(n > 0 and observation_ts == self.ts[-1]),
            "shadow_last_bar_ts": self.ts[-1] if n else None,
            "shadow_n_bars_retained": n,
        }
        if n == 0:
            return out
        ts = np.asarray(self.ts, dtype=np.int64)
        opens = np.asarray(self.opens, dtype=float)
        highs = np.asarray(self.highs, dtype=float)
        lows = np.asarray(self.lows, dtype=float)
        closes = np.asarray(self.closes, dtype=float)
        vols = np.asarray(self.volumes, dtype=float)
        deltas = np.asarray(self.est_deltas, dtype=float)

        causal = ts <= observation_ts
        out["shadow_n_bars_future_of_obs_ts_dropped"] = int((~causal).sum())
        ts, opens, highs, lows, closes, vols, deltas = (
            ts[causal], opens[causal], highs[causal], lows[causal], closes[causal],
            vols[causal], deltas[causal])
        if len(ts) == 0:
            return out

        rng = highs - lows
        safe_rng = np.where(rng > 0, rng, 1.0)
        bull_ratio = np.where(rng > 0, np.clip((closes - lows) / safe_rng, 0.0, 1.0), 0.5)
        bull_vol = vols * bull_ratio
        bear_vol = vols - bull_vol

        atr_safe = atr if atr and atr > 0 else None
        window_vals: Dict[int, Dict[str, float]] = {}
        for W in WINDOWS_S:
            cutoff = observation_ts - W * NS
            mask = ts > cutoff
            cnt = int(mask.sum())
            full_available = bool(ts[0] <= cutoff + NS)
            suffix = f"{W}s"
            out[f"shadow_window_oldest_ts_{suffix}"] = int(ts[mask][0]) if cnt else None
            out[f"shadow_window_newest_ts_{suffix}"] = int(ts[mask][-1]) if cnt else None
            out[f"shadow_window_count_{suffix}"] = cnt
            if not full_available or cnt == 0:
                for key in WINDOW_KEYS:
                    out[f"{key}_{suffix}"] = None
                out[f"window_available_{suffix}"] = False
                continue

            wv, wd = vols[mask], deltas[mask]
            wo, wc, wh, wl = opens[mask], closes[mask], highs[mask], lows[mask]
            wbull, wbear = bull_vol[mask], bear_vol[mask]

            vol_sum = float(wv.sum())
            est_delta_sum = float(wd.sum())
            est_abs_delta_sum = float(np.abs(wd).sum())
            price_change_points = float(wc[-1] - wo[0])
            range_points = float(wh.max() - wl.min())
            price_change_atr = (price_change_points / atr_safe) if atr_safe else None
            range_atr = (range_points / atr_safe) if atr_safe else None
            up_mask = wc > wo
            down_mask = wc < wo
            upbar_vol_sum = float(wv[up_mask].sum())
            downbar_vol_sum = float(wv[down_mask].sum())

            vals = {
                "vol_sum": vol_sum,
                "vol_mean_1s": float(wv.mean()),
                "vol_max_1s": float(wv.max()),
                "est_bull_vol_sum": float(wbull.sum()),
                "est_bear_vol_sum": float(wbear.sum()),
                "est_delta_sum": est_delta_sum,
                "est_abs_delta_sum": est_abs_delta_sum,
                "est_delta_ratio": est_delta_sum / max(vol_sum, EPS),
                "est_delta_pos_sum": float(wd[wd > 0].sum()),
                "est_delta_neg_sum": float(wd[wd < 0].sum()),
                "upbar_vol_sum": upbar_vol_sum,
                "downbar_vol_sum": downbar_vol_sum,
                "up_down_vol_ratio": upbar_vol_sum / max(downbar_vol_sum, EPS),
                "price_change_points": price_change_points,
                "price_change_atr": price_change_atr,
                "range_points": range_points,
                "range_atr": range_atr,
                "volume_per_point_moved": vol_sum / max(abs(price_change_points), EPS),
                "volume_per_atr_moved": (vol_sum / max(abs(price_change_atr), EPS)) if atr_safe else None,
                "abs_delta_per_point_moved": est_abs_delta_sum / max(abs(price_change_points), EPS),
                "abs_delta_per_atr_moved": (est_abs_delta_sum / max(abs(price_change_atr), EPS)) if atr_safe else None,
            }
            window_vals[W] = vals
            out[f"window_available_{suffix}"] = True
            for key, val in vals.items():
                out[f"{key}_{suffix}"] = val

        # A4: regime-relative, fresh sum over the retained log (causally bounded).
        if self._regime_start_ts is None:
            out["regime_available"] = False
            out["shadow_regime_log_len"] = 0
        else:
            log = [(t, h, l, v, d) for (t, h, l, v, d) in self._regime_log if t <= observation_ts]
            out["shadow_regime_log_len"] = len(log)
            vol_sum = sum(v for _, _, _, v, _ in log)
            delta_sum = sum(d for _, _, _, _, d in log)
            abs_delta_sum = sum(abs(d) for _, _, _, _, d in log)
            elapsed_s = (observation_ts - self._regime_start_ts) / NS
            out["regime_available"] = True
            out["regime_vol_sum"] = vol_sum
            out["regime_est_delta_sum"] = delta_sum
            out["regime_est_delta_ratio"] = delta_sum / max(vol_sum, EPS)
            out["regime_est_abs_delta_sum"] = abs_delta_sum
            out["regime_elapsed_seconds"] = elapsed_s

        # A5: RTH cumulative, fresh sum over the retained log (causally bounded).
        if not self._rth_active or self._rth_start_ts is None:
            out["rth_available"] = False
            out["shadow_rth_log_len"] = 0
            out["rth_vol_cum"] = None
            out["rth_est_delta_cum"] = None
            out["rth_abs_delta_cum"] = None
        else:
            log = [(t, v, d) for (t, v, d) in self._rth_log if t <= observation_ts]
            out["shadow_rth_log_len"] = len(log)
            rth_vol_cum = sum(v for _, v, _ in log)
            rth_delta_cum = sum(d for _, _, d in log)
            rth_abs_delta_cum = sum(abs(d) for _, _, d in log)
            out["rth_available"] = True
            out["rth_vol_cum"] = rth_vol_cum
            out["rth_est_delta_cum"] = rth_delta_cum
            out["rth_est_delta_ratio_cum"] = rth_delta_cum / max(rth_vol_cum, EPS)
            out["rth_abs_delta_cum"] = rth_abs_delta_cum
            out["rth_elapsed_seconds"] = (observation_ts - self._rth_start_ts) / NS

        return out


# Features flagged as diverging in the live NT run's real output -- the
# audit's primary comparison set (not exhaustive of every tracker output).
FLAGGED_FEATURES: Tuple[str, ...] = (
    "price_change_points_60s",
    "rth_vol_cum",
    "rth_abs_delta_cum",
    "est_delta_sum_1800s",
    "est_bear_vol_sum_300s",
)


def compare(live: Dict[str, object], shadow: Dict[str, object], offline: Optional[Dict[str, object]],
           features=FLAGGED_FEATURES, tol: float = 1e-9) -> Dict[str, dict]:
    """Per-feature 3-way comparison and classification. `offline` may be None
    (no matching offline reference row for this exact checkpoint)."""
    report = {}
    for feat in features:
        lv = live.get(feat)
        sv = shadow.get(feat)
        ov = offline.get(feat) if offline is not None else None

        def _diff(a, b):
            if a is None or b is None:
                return None
            return abs(float(a) - float(b))

        d_live_shadow = _diff(lv, sv)
        d_shadow_offline = _diff(sv, ov) if offline is not None else None
        d_live_offline = _diff(lv, ov) if offline is not None else None

        if offline is None:
            classification = "no_offline_reference"
        elif d_shadow_offline is not None and d_shadow_offline <= tol and d_live_shadow is not None and d_live_shadow > tol:
            classification = "live_tracker_state_update_defect"
        elif (d_live_shadow is not None and d_live_shadow <= tol
              and d_live_offline is not None and d_live_offline > tol):
            classification = "timestamp_or_offline_contract_mismatch"
        elif (d_live_shadow is not None and d_live_shadow <= tol
              and (d_live_offline is None or d_live_offline <= tol)):
            classification = "all_agree"
        else:
            classification = "all_differ_key_or_ts_mismatch"

        report[feat] = {
            "live": lv, "shadow": sv, "offline": ov,
            "diff_live_shadow": d_live_shadow, "diff_shadow_offline": d_shadow_offline,
            "diff_live_offline": d_live_offline, "classification": classification,
        }
    return report

"""Causal OHLCV-estimated volume/delta tracker (1s bars).

Estimates buy/sell pressure from OHLCV alone (no order-flow/order-book data)
by splitting each bar's volume according to where its close falls within its
own high-low range. This is an ESTIMATE, not true order-flow delta -- every
emitted name is prefixed `bar_est_*` / `est_*` to make that explicit.

A1: per-bar estimated delta.
A2: rolling completed-time windows (5s-1800s), completed bars only.
A3: short-vs-long pressure comparison.
A4: regime-relative cumulative volume/delta (reset via reset_regime()).
A5: RTH-session cumulative volume/delta (reset via reset_rth()/end_rth()).

All rolling/cumulative state only ever incorporates bars already passed to
update() -- the caller must call update() only with COMPLETED bars, never a
still-forming bar. A window is marked unavailable (not zero-filled) until
enough completed history exists to cover it fully.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

EPS = 1e-9
NS = 1_000_000_000
WINDOWS_S: Tuple[int, ...] = (5, 15, 30, 60, 120, 300, 900, 1800)


def bar_estimates(open_px: float, high: float, low: float, close: float,
                  volume: float) -> Dict[str, object]:
    """A1: per-bar estimated bull/bear volume split and estimated delta."""
    rng = high - low
    if rng > 0:
        bull_ratio = min(1.0, max(0.0, (close - low) / rng))
        bear_ratio = 1.0 - bull_ratio
        est_delta = volume * (2 * close - high - low) / rng
        est_delta_ratio = est_delta / max(volume, EPS)
        zero_range = False
    else:
        bull_ratio = bear_ratio = 0.5
        est_delta = 0.0
        est_delta_ratio = 0.0
        zero_range = True
    return {
        "bar_volume": float(volume),
        "bar_est_bull_volume": float(volume * bull_ratio),
        "bar_est_bear_volume": float(volume * bear_ratio),
        "bar_est_delta": float(est_delta),
        "bar_est_delta_ratio": float(est_delta_ratio),
        "bar_zero_range": bool(zero_range),
    }


class OHLCVDeltaTracker:
    """Stateful tracker over completed 1s bars. See module docstring."""

    def __init__(self, maxlen: int = 1900):
        self.maxlen = maxlen
        self.ts: deque = deque(maxlen=maxlen)
        self.opens: deque = deque(maxlen=maxlen)
        self.highs: deque = deque(maxlen=maxlen)
        self.lows: deque = deque(maxlen=maxlen)
        self.closes: deque = deque(maxlen=maxlen)
        self.volumes: deque = deque(maxlen=maxlen)
        self.est_deltas: deque = deque(maxlen=maxlen)

        # A4: regime-relative cumulative state
        self._regime_start_ts: Optional[int] = None
        self._regime_anchor_price: Optional[float] = None
        self._regime_vol_sum = 0.0
        self._regime_delta_sum = 0.0
        self._regime_abs_delta_sum = 0.0
        self._regime_high: Optional[float] = None
        self._regime_low: Optional[float] = None
        self._regime_bar_log: List[Tuple[int, float, float]] = []  # (ts, vol, delta)

        # A5: RTH-session cumulative state
        self._rth_active = False
        self._rth_start_ts: Optional[int] = None
        self._rth_vol_cum = 0.0
        self._rth_delta_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    # -- update / reset --------------------------------------------------

    def update(self, ts_event: int, open_px: float, high: float, low: float,
               close: float, volume: float) -> Dict[str, object]:
        """Feed one COMPLETED 1s bar. Never call with a forming bar.

        Only updates the rolling-window deques (A1-A3), which have no
        regime/RTH dependency. Regime-relative (A4) and RTH-cumulative (A5)
        accumulation is intentionally NOT done here -- call
        `accumulate_regime_rth()` separately, after the caller has resolved
        the correct regime/RTH context for this bar. This split exists
        because NT dispatches an entire minute's 1s bars before its parent
        1m bar closes, so a caller driven by 1m-granularity regime/RTH
        detection (e.g. FeatureEngine) cannot know the correct context
        for a bar at the moment `update()` is called -- it must buffer
        this method's returned per-bar estimate and replay it via
        `accumulate_regime_rth()` once the 1m bar confirms the context
        (mirrors the MFE/MAE buffered-retroactive-replay pattern mandated
        by CLAUDE.md invariant 4). A caller that already knows the correct
        context at 1-second granularity (e.g. an offline batch replay
        driven directly by a causal regime timeline) may call
        `accumulate_regime_rth()` immediately after `update()` for the same bar.

        Returns the per-bar `bar_estimates()` dict so callers can reuse
        `bar_est_delta` for `accumulate_regime_rth()` without recomputing it.
        """
        b = bar_estimates(open_px, high, low, close, volume)
        self.ts.append(int(ts_event))
        self.opens.append(float(open_px))
        self.highs.append(float(high))
        self.lows.append(float(low))
        self.closes.append(float(close))
        self.volumes.append(float(volume))
        self.est_deltas.append(b["bar_est_delta"])
        return b

    def accumulate_regime_rth(self, ts_event: int, high: float, low: float,
                              volume: float, est_delta: float) -> None:
        """Attribute one bar's volume/delta to the currently-active regime/RTH
        state. See `update()`'s docstring for why this is a separate call."""
        if self._regime_start_ts is not None:
            self._regime_vol_sum += volume
            self._regime_delta_sum += est_delta
            self._regime_abs_delta_sum += abs(est_delta)
            self._regime_high = high if self._regime_high is None else max(self._regime_high, high)
            self._regime_low = low if self._regime_low is None else min(self._regime_low, low)
            self._regime_bar_log.append((int(ts_event), float(volume), est_delta))

        if self._rth_active:
            self._rth_vol_cum += volume
            self._rth_delta_cum += est_delta
            self._rth_abs_delta_cum += abs(est_delta)

    def reset_regime(self, ts_event: int, anchor_price: float) -> None:
        """Call when the prevailing 1m regime changes (new regime start)."""
        self._regime_start_ts = int(ts_event)
        self._regime_anchor_price = float(anchor_price)
        self._regime_vol_sum = 0.0
        self._regime_delta_sum = 0.0
        self._regime_abs_delta_sum = 0.0
        self._regime_high = None
        self._regime_low = None
        self._regime_bar_log = []

    def reset_rth(self, ts_event: int) -> None:
        """Call at the first bar of a new RTH session."""
        self._rth_active = True
        self._rth_start_ts = int(ts_event)
        self._rth_vol_cum = 0.0
        self._rth_delta_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    def end_rth(self) -> None:
        """Call when RTH ends for the session (post-RTH bars accumulate nothing)."""
        self._rth_active = False

    # -- calculate ---------------------------------------------------------

    def calculate(self, atr: float) -> Dict[str, object]:
        n = len(self.ts)
        if n == 0:
            return {}
        ts = np.asarray(self.ts, dtype=np.int64)
        opens = np.asarray(self.opens, dtype=float)
        highs = np.asarray(self.highs, dtype=float)
        lows = np.asarray(self.lows, dtype=float)
        closes = np.asarray(self.closes, dtype=float)
        vols = np.asarray(self.volumes, dtype=float)
        deltas = np.asarray(self.est_deltas, dtype=float)

        rng = highs - lows
        safe_rng = np.where(rng > 0, rng, 1.0)
        bull_ratio = np.where(rng > 0, np.clip((closes - lows) / safe_rng, 0.0, 1.0), 0.5)
        bull_vol = vols * bull_ratio
        bear_vol = vols - bull_vol

        out: Dict[str, object] = {}
        out.update(bar_estimates(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1]))

        obs_ts = int(ts[-1])
        atr_safe = atr if atr and atr > 0 else None

        window_vals: Dict[int, Dict[str, float]] = {}
        for W in WINDOWS_S:
            cutoff = obs_ts - W * NS
            mask = ts > cutoff
            cnt = int(mask.sum())
            # Each bar's ts is its CLOSE time and covers (ts-1s, ts]; a window
            # of W seconds is fully covered once the oldest buffered bar
            # reaches back to at most cutoff+1s (i.e. W bars at 1s spacing).
            #
            # Deliberately NOT also requiring cnt == W: empirically, this raw
            # feed has routine single-second gaps even during RTH (a second
            # with zero prints), which is normal market quietness, not a data
            # integrity problem -- a volume/delta SUM is legitimately
            # unaffected by a quiet second's correct zero contribution. An
            # exact-count requirement was tried and rejected: it marked
            # ~5% of 5s windows and ~99% of 1800s windows unavailable on a
            # real 5-day sample, which would make these features nearly
            # unusable for a reason that isn't actually a correctness issue
            # (contrast with price_levels.py's rolling 1-minute windows,
            # where a genuine multi-minute gap, e.g. the daily maintenance
            # break, DOES invalidate the intended "last W minutes" semantic
            # and is checked explicitly there).
            full_available = bool(ts[0] <= cutoff + NS)
            suffix = f"{W}s"
            if not full_available or cnt == 0:
                for key in ("vol_sum", "vol_mean_1s", "vol_max_1s", "est_bull_vol_sum",
                            "est_bear_vol_sum", "est_delta_sum", "est_abs_delta_sum",
                            "est_delta_ratio", "est_delta_pos_sum", "est_delta_neg_sum",
                            "upbar_vol_sum", "downbar_vol_sum", "up_down_vol_ratio",
                            "price_change_points", "price_change_atr", "range_points",
                            "range_atr", "volume_per_point_moved", "volume_per_atr_moved",
                            "abs_delta_per_point_moved", "abs_delta_per_atr_moved"):
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

        # A3: short-vs-long pressure comparison
        def _pair(a: int, b: int, key: str, name: str) -> None:
            va, vb = window_vals.get(a), window_vals.get(b)
            if va is None or vb is None:
                out[name] = None
            else:
                out[name] = va[key] - vb[key]

        _pair(15, 60, "est_delta_sum", "est_delta_sum_15s_minus_60s_scaled")
        _pair(30, 120, "est_delta_sum", "est_delta_sum_30s_minus_120s_scaled")
        _pair(60, 300, "est_delta_sum", "est_delta_sum_60s_minus_300s_scaled")
        _pair(15, 60, "est_delta_ratio", "est_delta_ratio_15s_minus_60s")
        _pair(30, 120, "est_delta_ratio", "est_delta_ratio_30s_minus_120s")
        _pair(60, 300, "est_delta_ratio", "est_delta_ratio_60s_minus_300s")

        for a, b, name in ((30, 300, "vol_sum_30s_vs_300s_ratio"),
                          (60, 900, "vol_sum_60s_vs_900s_ratio")):
            va, vb = window_vals.get(a), window_vals.get(b)
            out[name] = (va["vol_sum"] / max(vb["vol_sum"], EPS)) if (va and vb) else None

        # A4: regime-relative volume/delta
        out.update(self._regime_features(obs_ts, closes[-1], atr_safe))

        # A5: RTH cumulative
        out.update(self._rth_features(obs_ts))

        return out

    def _regime_features(self, obs_ts: int, last_close: float,
                         atr_safe: Optional[float]) -> Dict[str, object]:
        keys = ("regime_vol_sum", "regime_est_delta_sum", "regime_est_delta_ratio",
                "regime_est_abs_delta_sum", "regime_elapsed_seconds",
                "regime_volume_per_second", "regime_price_change_atr", "regime_range_atr",
                "regime_volume_per_atr_moved", "regime_abs_delta_per_atr_moved",
                "regime_first_half_est_delta_ratio", "regime_second_half_est_delta_ratio",
                "regime_late_minus_early_delta_ratio", "regime_first_half_vol",
                "regime_second_half_vol", "regime_late_vs_early_vol_ratio",
                "regime_available")
        if self._regime_start_ts is None:
            return {k: (False if k == "regime_available" else None) for k in keys}

        elapsed_s = (obs_ts - self._regime_start_ts) / NS
        vol_sum = self._regime_vol_sum
        delta_sum = self._regime_delta_sum
        out = {
            "regime_available": True,
            "regime_vol_sum": vol_sum,
            "regime_est_delta_sum": delta_sum,
            "regime_est_delta_ratio": delta_sum / max(vol_sum, EPS),
            "regime_est_abs_delta_sum": self._regime_abs_delta_sum,
            "regime_elapsed_seconds": elapsed_s,
            "regime_volume_per_second": vol_sum / max(elapsed_s, EPS),
            "regime_price_change_atr": ((last_close - self._regime_anchor_price) / atr_safe) if atr_safe else None,
        }
        if self._regime_high is not None and atr_safe:
            out["regime_range_atr"] = (self._regime_high - self._regime_low) / atr_safe
        else:
            out["regime_range_atr"] = None
        pca = out["regime_price_change_atr"]
        out["regime_volume_per_atr_moved"] = (vol_sum / max(abs(pca), EPS)) if pca is not None else None
        out["regime_abs_delta_per_atr_moved"] = (
            self._regime_abs_delta_sum / max(abs(pca), EPS)) if pca is not None else None

        log = self._regime_bar_log
        if len(log) < 4 or elapsed_s < 4:
            out.update({
                "regime_first_half_est_delta_ratio": None, "regime_second_half_est_delta_ratio": None,
                "regime_late_minus_early_delta_ratio": None, "regime_first_half_vol": None,
                "regime_second_half_vol": None, "regime_late_vs_early_vol_ratio": None,
            })
        else:
            midpoint = self._regime_start_ts + (obs_ts - self._regime_start_ts) / 2
            first = [(t, v, d) for t, v, d in log if t < midpoint]
            second = [(t, v, d) for t, v, d in log if t >= midpoint]
            if len(first) == 0 or len(second) == 0:
                out.update({
                    "regime_first_half_est_delta_ratio": None, "regime_second_half_est_delta_ratio": None,
                    "regime_late_minus_early_delta_ratio": None, "regime_first_half_vol": None,
                    "regime_second_half_vol": None, "regime_late_vs_early_vol_ratio": None,
                })
            else:
                fv = sum(v for _, v, _ in first)
                fd = sum(d for _, _, d in first)
                sv = sum(v for _, v, _ in second)
                sd = sum(d for _, _, d in second)
                fr = fd / max(fv, EPS)
                sr = sd / max(sv, EPS)
                out.update({
                    "regime_first_half_est_delta_ratio": fr,
                    "regime_second_half_est_delta_ratio": sr,
                    "regime_late_minus_early_delta_ratio": sr - fr,
                    "regime_first_half_vol": fv,
                    "regime_second_half_vol": sv,
                    "regime_late_vs_early_vol_ratio": sv / max(fv, EPS),
                })
        return out

    def _rth_features(self, obs_ts: int) -> Dict[str, object]:
        keys = ("rth_available", "rth_elapsed_seconds", "rth_vol_cum", "rth_est_delta_cum",
                "rth_est_delta_ratio_cum", "rth_abs_delta_cum", "rth_volume_per_second")
        if not self._rth_active or self._rth_start_ts is None:
            return {k: (False if k == "rth_available" else None) for k in keys}
        elapsed_s = (obs_ts - self._rth_start_ts) / NS
        return {
            "rth_available": True,
            "rth_elapsed_seconds": elapsed_s,
            "rth_vol_cum": self._rth_vol_cum,
            "rth_est_delta_cum": self._rth_delta_cum,
            "rth_est_delta_ratio_cum": self._rth_delta_cum / max(self._rth_vol_cum, EPS),
            "rth_abs_delta_cum": self._rth_abs_delta_cum,
            "rth_volume_per_second": self._rth_vol_cum / max(elapsed_s, EPS),
        }

"""Causal price-level context tracker (1-minute bars).

Tracks a bounded, approved set of OHLCV-derived reference levels (prior-day
OHLC, overnight high/low, RTH open, 30-minute opening range, rolling
5/15/30/60-minute OHLC) and computes causal distance/count/nearest/density/
cluster/direction features against them.

Trading-day boundary: this repo has no pre-existing canonical trading-day
utility (see SPEC.md scout item 4). This module defines one: the standard
CME/Globex rollover at 17:00 America/Chicago -- bars at or after 17:00 CT
belong to the NEXT trading day's overnight session. This is the only new
session/timestamp logic in this study; everything else (RTH boundaries,
ATR) is reused from existing sources.

Final overnight/opening-range values become available only once causally
established (session end / 30 minutes elapsed) -- never before. Unavailable
values are always `None` plus an explicit `_available` flag, never zero.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pytz

NS = 1_000_000_000
CT = pytz.timezone("America/Chicago")
TRADING_DAY_ROLL_HOUR_CT = 17  # 5:00 PM CT
OPENING_RANGE_SECONDS = 1800
DENSITY_BANDS_ATR = (0.25, 0.50, 1.00, 2.00)
_DENSITY_SUFFIX = {0.25: "025a", 0.50: "050a", 1.00: "100a", 2.00: "200a"}
ROLLING_WINDOWS_MIN = (5, 15, 30, 60)


def trading_day_key(ts_ns: int) -> str:
    """Trading-day identity for a UTC-nanosecond timestamp. CME/Globex
    convention: the session that opens at 17:00 CT belongs to the NEXT
    calendar trading day."""
    dt_ct = datetime.fromtimestamp(ts_ns / 1e9, tz=pytz.utc).astimezone(CT)
    day = dt_ct.date()
    if dt_ct.hour >= TRADING_DAY_ROLL_HOUR_CT:
        day = day + timedelta(days=1)
    return day.isoformat()


def _position(reference: float, level: float, tolerance: float) -> str:
    if abs(reference - level) <= tolerance:
        return "TOUCH"
    return "ABOVE" if reference > level else "BELOW"


class PriceLevelTracker:
    """Stateful tracker over completed 1-minute bars. See module docstring."""

    def __init__(self, tick_size: float = 0.25, touch_tolerance_ticks: float = 1.0,
                 rolling_windows_min: Optional[Iterable[int]] = None):
        """Create a causal completed-1m level provider.

        The legacy 5/15/30/60-minute catalogue remains the default.  Window
        duration is now a validated provider parameter: it changes the
        completed-bar input interval, never the calculation, availability,
        session reset, or output semantics.
        """
        requested = ROLLING_WINDOWS_MIN if rolling_windows_min is None else tuple(int(value) for value in rolling_windows_min)
        if not requested or any(value <= 0 for value in requested):
            raise ValueError("rolling_windows_min must contain positive completed-minute durations")
        self.tick_size = tick_size
        self.touch_tolerance_ticks = touch_tolerance_ticks
        self.rolling_windows_min = tuple(sorted(set(requested)))
        max_window = max(self.rolling_windows_min)
        self.bars_1m: deque = deque(maxlen=max_window + 5)

        self.current_trading_day: Optional[str] = None
        self.prior_day_ohlc: Optional[Dict[str, float]] = None
        self._today_bars: List[Tuple[int, float, float, float, float]] = []

        self._overnight_high: Optional[float] = None
        self._overnight_low: Optional[float] = None
        self._overnight_final: Optional[Dict[str, float]] = None

        self._rth_open: Optional[float] = None
        self._rth_open_ts: Optional[int] = None

        self._opening_range_high: Optional[float] = None
        self._opening_range_low: Optional[float] = None
        self._opening_range_final: Optional[Dict[str, float]] = None

    # -- update --------------------------------------------------------

    def _on_new_trading_day(self, day_key: str) -> None:
        if self._today_bars:
            o = self._today_bars[0][1]
            h = max(b[2] for b in self._today_bars)
            l = min(b[3] for b in self._today_bars)
            c = self._today_bars[-1][4]
            self.prior_day_ohlc = {"open": o, "high": h, "low": l, "close": c}
        self.current_trading_day = day_key
        self._today_bars = []
        self._overnight_high = None
        self._overnight_low = None
        self._overnight_final = None
        self._rth_open = None
        self._rth_open_ts = None
        self._opening_range_high = None
        self._opening_range_low = None
        self._opening_range_final = None

    def update_1m(self, ts_avail: int, open_px: float, high: float, low: float,
                  close: float, is_rth: bool) -> None:
        """Feed one COMPLETED 1-minute bar, in chronological order.
        `ts_avail` must be the bar's CLOSE timestamp (causally available time)."""
        day_key = trading_day_key(ts_avail)
        if day_key != self.current_trading_day:
            self._on_new_trading_day(day_key)

        self._today_bars.append((ts_avail, open_px, high, low, close))
        self.bars_1m.append((ts_avail, open_px, high, low, close))

        if is_rth:
            if self._rth_open is None:
                self._rth_open = open_px
                self._rth_open_ts = ts_avail
                if self._overnight_high is not None and self._overnight_final is None:
                    self._overnight_final = {"high": self._overnight_high, "low": self._overnight_low}
            elapsed = (ts_avail - self._rth_open_ts) / NS
            if elapsed < OPENING_RANGE_SECONDS:
                self._opening_range_high = high if self._opening_range_high is None else max(self._opening_range_high, high)
                self._opening_range_low = low if self._opening_range_low is None else min(self._opening_range_low, low)
            elif self._opening_range_final is None and self._opening_range_high is not None:
                self._opening_range_final = {"high": self._opening_range_high, "low": self._opening_range_low}
        else:
            if self._rth_open is None:
                self._overnight_high = high if self._overnight_high is None else max(self._overnight_high, high)
                self._overnight_low = low if self._overnight_low is None else min(self._overnight_low, low)

    # -- raw level assembly ----------------------------------------------

    def _raw_levels(self) -> Dict[str, Tuple[Optional[float], str]]:
        """(price_or_None, family) for every approved base level."""
        levels: Dict[str, Tuple[Optional[float], str]] = {}
        pd = self.prior_day_ohlc
        for f in ("open", "high", "low", "close"):
            levels[f"prior_day_{f}"] = (pd[f] if pd else None, "prior_day")

        levels["overnight_high_developing"] = (self._overnight_high, "session")
        levels["overnight_low_developing"] = (self._overnight_low, "session")
        levels["overnight_high_final"] = (
            self._overnight_final["high"] if self._overnight_final else None, "session")
        levels["overnight_low_final"] = (
            self._overnight_final["low"] if self._overnight_final else None, "session")

        levels["rth_open"] = (self._rth_open, "session")

        levels["opening_range_30m_high_developing"] = (self._opening_range_high, "session")
        levels["opening_range_30m_low_developing"] = (self._opening_range_low, "session")
        levels["opening_range_30m_high_final"] = (
            self._opening_range_final["high"] if self._opening_range_final else None, "session")
        levels["opening_range_30m_low_final"] = (
            self._opening_range_final["low"] if self._opening_range_final else None, "session")

        n = len(self.bars_1m)
        for W in self.rolling_windows_min:
            window = list(self.bars_1m)[-W:] if n >= W else []
            # Require the window to actually SPAN W minutes gaplessly (bars
            # are 1-minute apart) -- a real feed gap must not silently mark
            # a truncated/gapped window as available.
            avail = (len(window) == W
                    and window[-1][0] - window[0][0] == (W - 1) * 60 * NS)
            if avail:
                o = window[0][1]
                h = max(b[2] for b in window)
                l = min(b[3] for b in window)
                c = window[-1][4]
            else:
                o = h = l = c = None
            for name, val in (("open", o), ("high", h), ("low", l), ("close", c)):
                levels[f"rolling_{W}m_{name}"] = (val, "rolling")
        return levels

    def opening_range_state(self) -> Dict[str, object]:
        return {
            "opening_range_30m_is_developing": self._opening_range_final is None and self._opening_range_high is not None,
            "opening_range_30m_is_final": self._opening_range_final is not None,
        }

    # -- calculate ---------------------------------------------------------

    def calculate(self, observation_ts: int, reference_price: float, atr: float,
                  direction: int = -1) -> Dict[str, object]:
        levels = self._raw_levels()
        tol = max(self.tick_size, self.touch_tolerance_ticks * self.tick_size)
        atr_safe = atr if atr and atr > 0 else None

        out: Dict[str, object] = {}
        available_prices: Dict[str, float] = {}
        family_of: Dict[str, str] = {}
        for name, (price, family) in levels.items():
            available = price is not None
            out[f"{name}_price"] = price
            out[f"{name}_available"] = available
            if not available:
                out[f"{name}_signed_distance_points"] = None
                out[f"{name}_signed_distance_ticks"] = None
                out[f"{name}_signed_distance_atr"] = None
                out[f"{name}_position"] = "UNAVAILABLE"
                continue
            signed_points = reference_price - price
            out[f"{name}_signed_distance_points"] = signed_points
            out[f"{name}_signed_distance_ticks"] = signed_points / self.tick_size
            out[f"{name}_signed_distance_atr"] = (signed_points / atr_safe) if atr_safe else None
            out[f"{name}_position"] = _position(reference_price, price, tol)
            available_prices[name] = price
            family_of[name] = family

        if self._rth_open_ts is not None:
            out["rth_open_elapsed_seconds"] = (observation_ts - self._rth_open_ts) / NS
        else:
            out["rth_open_elapsed_seconds"] = None
        if self._rth_open_ts is not None:
            elapsed = (observation_ts - self._rth_open_ts) / NS
            out["opening_range_30m_elapsed_seconds"] = min(elapsed, OPENING_RANGE_SECONDS)
        else:
            out["opening_range_30m_elapsed_seconds"] = None
        out.update(self.opening_range_state())

        out.update(self._aggregate_counts(available_prices, family_of, reference_price, tol))
        out.update(self._nearest_geometry(available_prices, reference_price, atr_safe))
        out.update(self._density_envelope(available_prices, reference_price, atr_safe))
        clusters = self._cluster(available_prices, atr_safe)
        out.update(self._cluster_features(clusters, reference_price, atr_safe, tol))
        out.update(self._direction_normalized(available_prices, clusters, reference_price, atr_safe, direction))
        return out

    def _aggregate_counts(self, prices: Dict[str, float], family_of: Dict[str, str],
                          reference_price: float, tol: float) -> Dict[str, object]:
        n = len(prices)
        # A level is BELOW price when reference_price > level_price (+tol);
        # a level is ABOVE price when reference_price < level_price (-tol).
        # Matches the convention already used in _nearest_geometry/
        # _density_envelope/_cluster_features/_direction_normalized.
        n_below = sum(1 for p in prices.values() if reference_price > p + tol)
        n_above = sum(1 for p in prices.values() if reference_price < p - tol)
        touched = n - n_below - n_above
        out = {
            "n_levels_available": n, "n_levels_above": n_above, "n_levels_below": n_below,
            "n_levels_touched": touched,
            "pct_levels_above": (n_above / n) if n else None,
            "pct_levels_below": (n_below / n) if n else None,
            "pct_levels_touched": (touched / n) if n else None,
            "level_balance": ((n_below - n_above) / n) if n else None,
        }
        for fam in ("prior_day", "session", "rolling"):
            fam_prices = [p for name, p in prices.items() if family_of[name] == fam]
            out[f"n_{fam}_levels_above"] = sum(1 for p in fam_prices if reference_price < p - tol)
            out[f"n_{fam}_levels_below"] = sum(1 for p in fam_prices if reference_price > p + tol)
        return out

    def _nearest_geometry(self, prices: Dict[str, float], reference_price: float,
                          atr_safe: Optional[float]) -> Dict[str, object]:
        above = {n: p for n, p in prices.items() if p > reference_price}
        below = {n: p for n, p in prices.items() if p < reference_price}
        out: Dict[str, object] = {}
        if above:
            name = min(above, key=lambda n: above[n])
            price = above[name]
            out["nearest_level_above_name"] = name
            out["nearest_level_above_price"] = price
            out["nearest_level_above_distance_points"] = price - reference_price
            out["nearest_level_above_distance_ticks"] = (price - reference_price) / self.tick_size
            out["nearest_level_above_distance_atr"] = ((price - reference_price) / atr_safe) if atr_safe else None
        else:
            out.update({"nearest_level_above_name": None, "nearest_level_above_price": None,
                       "nearest_level_above_distance_points": None,
                       "nearest_level_above_distance_ticks": None,
                       "nearest_level_above_distance_atr": None})
        if below:
            name = min(below, key=lambda n: reference_price - below[n])
            price = below[name]
            out["nearest_level_below_name"] = name
            out["nearest_level_below_price"] = price
            out["nearest_level_below_distance_points"] = reference_price - price
            out["nearest_level_below_distance_ticks"] = (reference_price - price) / self.tick_size
            out["nearest_level_below_distance_atr"] = ((reference_price - price) / atr_safe) if atr_safe else None
        else:
            out.update({"nearest_level_below_name": None, "nearest_level_below_price": None,
                       "nearest_level_below_distance_points": None,
                       "nearest_level_below_distance_ticks": None,
                       "nearest_level_below_distance_atr": None})

        da = out["nearest_level_above_distance_atr"]
        db = out["nearest_level_below_distance_atr"]
        out["nearest_space_balance_atr"] = (db - da) if (da is not None and db is not None) else None
        out["nearest_space_total_atr"] = (da + db) if (da is not None and db is not None) else None
        out["nearest_upside_downside_ratio"] = (
            da / db if (da is not None and db is not None and db > 0) else None)
        return out

    def _density_envelope(self, prices: Dict[str, float], reference_price: float,
                          atr_safe: Optional[float]) -> Dict[str, object]:
        out: Dict[str, object] = {}
        if not atr_safe or not prices:
            for band in DENSITY_BANDS_ATR:
                s = _DENSITY_SUFFIX[band]
                out[f"level_density_{s}"] = None
                out[f"levels_above_within_{s}"] = None
                out[f"levels_below_within_{s}"] = None
            out["inverse_distance_density"] = None
        else:
            dist_atr = {n: abs(reference_price - p) / atr_safe for n, p in prices.items()}
            for band in DENSITY_BANDS_ATR:
                s = _DENSITY_SUFFIX[band]
                within = [n for n, d in dist_atr.items() if d <= band]
                out[f"level_density_{s}"] = len(within)
                out[f"levels_above_within_{s}"] = sum(1 for n in within if prices[n] > reference_price)
                out[f"levels_below_within_{s}"] = sum(1 for n in within if prices[n] < reference_price)
            out["inverse_distance_density"] = float(sum(1.0 / max(d, 1e-6) for d in dist_atr.values()))

        if prices:
            lo_name = min(prices, key=lambda n: prices[n])
            hi_name = min(prices, key=lambda n: -prices[n])
            lo, hi = prices[lo_name], prices[hi_name]
            width_pts = hi - lo
            out["lowest_available_level"] = lo
            out["highest_available_level"] = hi
            out["full_level_envelope_width_points"] = width_pts
            out["full_level_envelope_width_atr"] = (width_pts / atr_safe) if atr_safe else None
            out["price_position_in_full_envelope"] = (
                (reference_price - lo) / width_pts if width_pts > 0 else None)
            out["distance_above_full_envelope_atr"] = (
                max(0.0, (reference_price - hi) / atr_safe) if atr_safe else None)
            out["distance_below_full_envelope_atr"] = (
                max(0.0, (lo - reference_price) / atr_safe) if atr_safe else None)
        else:
            out.update({"lowest_available_level": None, "highest_available_level": None,
                       "full_level_envelope_width_points": None, "full_level_envelope_width_atr": None,
                       "price_position_in_full_envelope": None,
                       "distance_above_full_envelope_atr": None, "distance_below_full_envelope_atr": None})
        return out

    def _cluster(self, prices: Dict[str, float], atr_safe: Optional[float]) -> List[Dict[str, object]]:
        """Deterministic clustering: sort by price, greedily group members
        within tolerance of the running cluster's median."""
        if not prices:
            return []
        tol = max(2 * self.tick_size, (0.05 * atr_safe) if atr_safe else 2 * self.tick_size)
        items = sorted(prices.items(), key=lambda kv: (kv[1], kv[0]))
        clusters: List[List[Tuple[str, float]]] = []
        for name, price in items:
            if clusters and abs(price - np.median([p for _, p in clusters[-1]])) <= tol:
                clusters[-1].append((name, price))
            else:
                clusters.append([(name, price)])
        return [
            {"price": float(np.median([p for _, p in members])),
             "strength": len(members),
             "members": [n for n, _ in members]}
            for members in clusters
        ]

    def _cluster_features(self, clusters: List[Dict[str, object]], reference_price: float,
                          atr_safe: Optional[float], tol: float) -> Dict[str, object]:
        n = len(clusters)
        above = [c for c in clusters if c["price"] > reference_price + tol]
        below = [c for c in clusters if c["price"] < reference_price - tol]
        touched = n - len(above) - len(below)
        out = {
            "n_level_clusters_available": n, "n_level_clusters_above": len(above),
            "n_level_clusters_below": len(below), "n_level_clusters_touched": touched,
        }
        if above:
            nearest = min(above, key=lambda c: c["price"])
            out["nearest_cluster_above_price"] = nearest["price"]
            out["nearest_cluster_above_distance_atr"] = (
                (nearest["price"] - reference_price) / atr_safe) if atr_safe else None
            out["nearest_cluster_above_strength"] = nearest["strength"]
        else:
            out.update({"nearest_cluster_above_price": None,
                       "nearest_cluster_above_distance_atr": None,
                       "nearest_cluster_above_strength": None})
        if below:
            nearest = min(below, key=lambda c: reference_price - c["price"])
            out["nearest_cluster_below_price"] = nearest["price"]
            out["nearest_cluster_below_distance_atr"] = (
                (reference_price - nearest["price"]) / atr_safe) if atr_safe else None
            out["nearest_cluster_below_strength"] = nearest["strength"]
        else:
            out.update({"nearest_cluster_below_price": None,
                       "nearest_cluster_below_distance_atr": None,
                       "nearest_cluster_below_strength": None})

        out["max_cluster_strength"] = max((c["strength"] for c in clusters), default=None)
        if atr_safe:
            for band, s in (((0.50, "050a")), (1.00, "100a")):
                nearby = [c["strength"] for c in clusters
                         if abs(c["price"] - reference_price) / atr_safe <= band]
                out[f"max_nearby_cluster_strength_{s}"] = max(nearby, default=None)
        else:
            out["max_nearby_cluster_strength_050a"] = None
            out["max_nearby_cluster_strength_100a"] = None
        return out

    def _direction_normalized(self, prices: Dict[str, float], clusters: List[Dict[str, object]],
                              reference_price: float, atr_safe: Optional[float],
                              direction: int) -> Dict[str, object]:
        n = len(prices)
        if direction == -1:
            ahead_prices = [p for p in prices.values() if p < reference_price]
            behind_prices = [p for p in prices.values() if p > reference_price]
        else:
            ahead_prices = [p for p in prices.values() if p > reference_price]
            behind_prices = [p for p in prices.values() if p < reference_price]

        out = {
            "levels_ahead_of_trade": len(ahead_prices), "levels_behind_trade": len(behind_prices),
            "pct_levels_ahead_of_trade": (len(ahead_prices) / n) if n else None,
            "pct_levels_behind_trade": (len(behind_prices) / n) if n else None,
            "nearest_level_ahead_distance_atr": (
                (min(abs(reference_price - p) for p in ahead_prices) / atr_safe)
                if ahead_prices and atr_safe else None),
            "nearest_level_behind_distance_atr": (
                (min(abs(reference_price - p) for p in behind_prices) / atr_safe)
                if behind_prices and atr_safe else None),
        }
        if direction == -1:
            cluster_ahead = [c["price"] for c in clusters if c["price"] < reference_price]
            cluster_behind = [c["price"] for c in clusters if c["price"] > reference_price]
        else:
            cluster_ahead = [c["price"] for c in clusters if c["price"] > reference_price]
            cluster_behind = [c["price"] for c in clusters if c["price"] < reference_price]
        out["nearest_cluster_ahead_distance_atr"] = (
            (min(abs(reference_price - p) for p in cluster_ahead) / atr_safe)
            if cluster_ahead and atr_safe else None)
        out["nearest_cluster_behind_distance_atr"] = (
            (min(abs(reference_price - p) for p in cluster_behind) / atr_safe)
            if cluster_behind and atr_safe else None)
        na, nb = out["nearest_level_ahead_distance_atr"], out["nearest_level_behind_distance_atr"]
        out["directional_space_balance_atr"] = (nb - na) if (na is not None and nb is not None) else None
        return out

"""Streaming, causal-by-construction indicators for the Regime Flip Truth
Collector.

EVERY value in this module is produced by feeding *completed* bars in
chronological order. Nothing here ever looks forward:

  - OneMinuteFeatureEngine.update(bar) is called ONLY when a 1m bucket has
    CLOSED (the collector calls it from the registry-advance path, i.e. at
    decision_ts == bar.ts_init). After update(), every getter returns state
    derived solely from bars whose close_ts <= decision_ts.
  - SessionVWAP.update_1s(...) is fed each CLOSED 1s bar in order; its value
    at time T reflects only 1s bars with ts_init <= T.

There is no array indexing by open-time, no resample, no merge_asof. State is
purely recursive / deque-windowed, so look-ahead is structurally impossible.

All periods (EMA/SMA 9/13/21/50, Bollinger 20/2, Keltner 20/20/1.5) operate on
1-MINUTE CLOSES, per the study spec decision (entry is on 1m flips).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Optional

import pytz

CT = pytz.timezone("America/Chicago")

# Globex session anchor for VWAP: 17:00 CT (open of the trade date's session).
VWAP_ANCHOR_HOUR_CT = 17

MA_PERIODS = (9, 13, 21, 50)
SLOPE_LOOKBACK = 5          # bars used for MA slope (repo convention)
BB_PERIOD = 20
BB_K = 2.0
KELTNER_EMA = 20
KELTNER_ATR = 20
KELTNER_MULT = 1.5


def _nan() -> float:
    return float("nan")


class _EMA:
    """Recursive EMA. Seeded on first value (NT/Keltner convention)."""

    def __init__(self, period: int):
        self.alpha = 2.0 / (period + 1)
        self.value: Optional[float] = None

    def update(self, x: float) -> None:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value


class _SMA:
    """Simple moving average over a fixed window (deque)."""

    def __init__(self, period: int):
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum = 0.0

    def update(self, x: float) -> None:
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]
        self._buf.append(x)
        self._sum += x

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period

    @property
    def value(self) -> Optional[float]:
        if not self.ready:
            return None
        return self._sum / self.period


class _WilderATR:
    """Wilder ATR over `period` completed bars."""

    def __init__(self, period: int):
        self.period = period
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None
        self._warmup: deque[float] = deque(maxlen=period)

    def update(self, high: float, low: float, close: float) -> None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close),
                     abs(low - self._prev_close))
        self._prev_close = close
        if self._atr is None:
            self._warmup.append(tr)
            if len(self._warmup) == self.period:
                self._atr = sum(self._warmup) / self.period
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / self.period

    @property
    def value(self) -> Optional[float]:
        return self._atr


class SessionVWAP:
    """Session-anchored VWAP (+/- sigma bands), fed one CLOSED 1s bar at a
    time. Anchored at 17:00 CT (CME Globex session open). Resets when the
    session date rolls over.

    Causal: value at time T uses only 1s bars with ts_init <= T.
    """

    def __init__(self):
        self._session_key: Optional[int] = None
        self._cum_pv = 0.0       # sum(typical * vol)
        self._cum_v = 0.0        # sum(vol)
        self._cum_p2v = 0.0      # sum(typical^2 * vol) for variance

    @staticmethod
    def _session_date_key(ts_init_ns: int) -> int:
        """Trade-date key: a CT clock-time >= 17:00 belongs to the NEXT
        calendar day's session. Returns an int yyyymmdd-style key."""
        import pandas as pd
        ct = pd.Timestamp(int(ts_init_ns), tz="UTC").tz_convert(CT)
        d = ct.date()
        if ct.hour >= VWAP_ANCHOR_HOUR_CT:
            d = d + pd.Timedelta(days=1)
        return d.year * 10000 + d.month * 100 + d.day

    def update_1s(self, ts_init_ns: int, high: float, low: float,
                  close: float, volume: float) -> None:
        key = self._session_date_key(ts_init_ns)
        if key != self._session_key:
            self._session_key = key
            self._cum_pv = 0.0
            self._cum_v = 0.0
            self._cum_p2v = 0.0
        typical = (high + low + close) / 3.0
        self._cum_pv += typical * volume
        self._cum_v += volume
        self._cum_p2v += typical * typical * volume

    @property
    def value(self) -> Optional[float]:
        if self._cum_v <= 0:
            return None
        return self._cum_pv / self._cum_v

    @property
    def sigma(self) -> Optional[float]:
        if self._cum_v <= 0:
            return None
        mean = self._cum_pv / self._cum_v
        var = self._cum_p2v / self._cum_v - mean * mean
        return sqrt(var) if var > 0 else 0.0


@dataclass
class _Regime:
    """Local mirror of the prior-regime path stats the collector hands back
    so the feature engine can expose them at entry time."""
    prior_regime_duration_bars: float = _nan()
    prior_regime_duration_s: float = _nan()
    prior_regime_mfe_atr: float = _nan()
    prior_regime_mae_atr: float = _nan()


class OneMinuteFeatureEngine:
    """Owns all 1m-close structural indicator state and emits a flat feature
    dict at entry time.

    update(o, h, l, c, v) MUST be called exactly once per completed 1m bar,
    in order. Then snapshot(direction, atr_1m) reads only the state built from
    bars closed at or before the current decision time.
    """

    # how many 1m closes / volumes / atr values to retain for windows + pctile
    HIST = 512

    def __init__(self):
        self._emas = {p: _EMA(p) for p in MA_PERIODS}
        self._smas = {p: _SMA(p) for p in MA_PERIODS}
        # Bollinger basis = SMA(BB_PERIOD); std over same window
        self._bb_buf: deque[float] = deque(maxlen=BB_PERIOD)
        self._keltner_ema = _EMA(KELTNER_EMA)
        self._keltner_atr = _WilderATR(KELTNER_ATR)

        # history deques (closes, volumes, atr, log-returns) for windows
        self._closes: deque[float] = deque(maxlen=self.HIST)
        self._vols: deque[float] = deque(maxlen=self.HIST)
        self._atrs: deque[float] = deque(maxlen=self.HIST)
        self._logret: deque[float] = deque(maxlen=self.HIST)
        # snapshots of each MA SLOPE_LOOKBACK bars ago (for slope)
        self._ema_hist = {p: deque(maxlen=SLOPE_LOOKBACK + 1) for p in MA_PERIODS}
        self._sma_hist = {p: deque(maxlen=SLOPE_LOOKBACK + 1) for p in MA_PERIODS}

        self.n_bars = 0
        self.last_close: Optional[float] = None

    # ------------------------------------------------------------------
    def update(self, o: float, h: float, l: float, c: float, v: float) -> None:
        prev_close = self.last_close
        for p in MA_PERIODS:
            self._emas[p].update(c)
            self._smas[p].update(c)
            self._ema_hist[p].append(self._emas[p].value)
            self._sma_hist[p].append(self._smas[p].value)
        self._bb_buf.append(c)
        self._keltner_ema.update(c)
        self._keltner_atr.update(h, l, c)

        self._closes.append(c)
        self._vols.append(v)
        if prev_close is not None and prev_close > 0 and c > 0:
            from math import log
            self._logret.append(log(c / prev_close))
        self.last_close = c
        self.n_bars += 1

    def push_atr(self, atr: Optional[float]) -> None:
        """Record the registry's 1m ATR(14) for percentile context. Called
        right after update() with the same bar's ATR."""
        if atr is not None and atr == atr:  # not NaN
            self._atrs.append(atr)

    # ------------------------------------------------------------------
    @staticmethod
    def _pctile(window: deque, x: Optional[float]) -> float:
        if x is None or len(window) < 10:
            return _nan()
        n = len(window)
        below = sum(1 for w in window if w <= x)
        return below / n

    @staticmethod
    def _std(vals) -> float:
        vals = list(vals)
        n = len(vals)
        if n < 2:
            return _nan()
        m = sum(vals) / n
        var = sum((x - m) ** 2 for x in vals) / (n - 1)
        return sqrt(var) if var > 0 else 0.0

    def _ret_over(self, n_bars: int) -> float:
        """close[now] - close[now - n_bars] in points."""
        if len(self._closes) <= n_bars:
            return _nan()
        return self._closes[-1] - self._closes[-1 - n_bars]

    def snapshot(self, direction: int, atr_1m: float,
                 prior: _Regime) -> dict:
        """Return a flat feature dict. `direction` (+1/-1) orients
        signed distances so positive = favorable. `atr_1m` is the registry
        ATR(14) used to ATR-normalize distances. Returns NaNs where not yet
        warmed up — the analysis layer filters on warmup.
        """
        c = self.last_close
        out: dict = {}
        a = atr_1m if (atr_1m and atr_1m == atr_1m and atr_1m > 0) else _nan()

        # --- Moving averages: ATR-normalized distance + slope (pts/bar) ---
        for p in MA_PERIODS:
            ema = self._emas[p].value
            sma = self._smas[p].value
            # distance: (close - ma) / atr, signed by direction so +ve = price
            # is on the trade's favorable side of the MA
            out[f"ema{p}_dist_atr"] = (
                direction * (c - ema) / a if (ema is not None and a == a)
                else _nan())
            out[f"sma{p}_dist_atr"] = (
                direction * (c - sma) / a if (sma is not None and a == a)
                else _nan())
            # slope over SLOPE_LOOKBACK bars (pts/bar), signed by direction
            eh = self._ema_hist[p]
            sh = self._sma_hist[p]
            out[f"ema{p}_slope"] = (
                direction * (eh[-1] - eh[0]) / SLOPE_LOOKBACK
                if len(eh) == SLOPE_LOOKBACK + 1 and eh[0] is not None
                else _nan())
            out[f"sma{p}_slope"] = (
                direction * (sh[-1] - sh[0]) / SLOPE_LOOKBACK
                if len(sh) == SLOPE_LOOKBACK + 1 and sh[0] is not None
                else _nan())

        # --- Bollinger(20, 2) on 1m closes ---
        if len(self._bb_buf) == BB_PERIOD:
            basis = sum(self._bb_buf) / BB_PERIOD
            sd = self._std(self._bb_buf)
            upper = basis + BB_K * sd
            lower = basis - BB_K * sd
            width = upper - lower
            out["bb_bandwidth"] = (width / basis) if basis else _nan()
            out["bb_position"] = ((c - lower) / width) if width > 0 else _nan()
            out["bb_dist_upper_atr"] = (upper - c) / a if a == a else _nan()
            out["bb_dist_lower_atr"] = (c - lower) / a if a == a else _nan()
        else:
            out.update(dict.fromkeys(
                ["bb_bandwidth", "bb_position",
                 "bb_dist_upper_atr", "bb_dist_lower_atr"], _nan()))

        # --- Keltner(20, 20, 1.5) on 1m bars ---
        kb = self._keltner_ema.value
        ka = self._keltner_atr.value
        if kb is not None and ka is not None:
            upper = kb + KELTNER_MULT * ka
            lower = kb - KELTNER_MULT * ka
            width = upper - lower
            out["keltner_width_atr"] = (width / a) if a == a else _nan()
            out["keltner_position"] = ((c - lower) / width) if width > 0 else _nan()
            out["keltner_dist_upper_atr"] = (upper - c) / a if a == a else _nan()
            out["keltner_dist_lower_atr"] = (c - lower) / a if a == a else _nan()
        else:
            out.update(dict.fromkeys(
                ["keltner_width_atr", "keltner_position",
                 "keltner_dist_upper_atr", "keltner_dist_lower_atr"], _nan()))

        # --- Volatility ---
        out["atr_1m"] = a
        out["atr_pctile"] = self._pctile(self._atrs, atr_1m)
        # realized vol = stdev of 1m log returns over trailing window
        out["rv_recent_20m"] = self._std(list(self._logret)[-20:])
        out["rv_5m"] = self._std(list(self._logret)[-5:])
        out["rv_30m"] = self._std(list(self._logret)[-30:])

        # --- Volume ---
        vols = list(self._vols)
        vol_1m = vols[-1] if vols else _nan()
        out["vol_1m"] = vol_1m
        out["vol_5m"] = sum(vols[-5:]) if len(vols) >= 5 else _nan()
        out["vol_30m"] = sum(vols[-30:]) if len(vols) >= 30 else _nan()
        out["vol_pctile"] = self._pctile(self._vols, vol_1m)
        if len(vols) >= 6:
            prior5 = sum(vols[-6:-1]) / 5.0
            out["vol_acceleration"] = (vol_1m - prior5)
        else:
            out["vol_acceleration"] = _nan()

        # --- Velocity / momentum (from 1m closes; 30s added by collector) ---
        out["ret_60s_atr"] = (direction * self._ret_over(1) / a) if a == a else _nan()
        out["ret_120s_atr"] = (direction * self._ret_over(2) / a) if a == a else _nan()
        out["ret_300s_atr"] = (direction * self._ret_over(5) / a) if a == a else _nan()
        r1_now = self._ret_over(1)
        r1_prev = (self._closes[-2] - self._closes[-3]
                   if len(self._closes) >= 3 else _nan())
        out["price_velocity"] = direction * r1_now / 60.0 if r1_now == r1_now else _nan()
        out["price_acceleration"] = (
            direction * (r1_now - r1_prev) / 60.0
            if (r1_now == r1_now and r1_prev == r1_prev) else _nan())

        # --- Prior-regime context (handed in by collector) ---
        out["prior_regime_duration_bars"] = prior.prior_regime_duration_bars
        out["prior_regime_duration_s"] = prior.prior_regime_duration_s
        out["prior_regime_mfe_atr"] = prior.prior_regime_mfe_atr
        out["prior_regime_mae_atr"] = prior.prior_regime_mae_atr

        return out

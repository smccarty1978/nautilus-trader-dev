"""Stateful indicator helpers for RL regime feasibility collector.

All classes update in one direction (bar-by-bar, oldest-first) and expose
read-only properties.  No look-ahead: all outputs reflect state through the
last COMPLETED bar whose data was passed to update().

Indicators:
  RegimeEngine      — EMA3/EMA9 HLC regime (reusable across timeframes)
  WilderATR         — standalone 14-period Wilder ATR
  WilderADX         — Wilder ADX(14) on completed 1m bars
  KalmanPV          — 2-state [price, velocity] Kalman filter on 1s closes
  BollingerKeltner  — BB / KC width on last-20 1m bars, with causal percentile
  VolTracker        — volume z-score and 30s-vs-5m rate ratio
  CloseReturnDeque  — rolling 1s close history for multi-horizon returns
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

import bisect

# ── Shared constants ─────────────────────────────────────────────────────────

_ALPHA3 = 2.0 / (3 + 1)   # 0.5
_ALPHA9 = 2.0 / (9 + 1)   # 0.2
_ATR_P  = 14


# ── RegimeEngine ────────────────────────────────────────────────────────────

class RegimeEngine:
    """EMA3/EMA9 regime engine identical in logic to _1mRegimeEngine.

    Works for any timeframe bucket via update(h, l, c).
    Tracks regime, bars_in_regime, Wilder ATR(14), and the four EMAs.
    """

    def __init__(self) -> None:
        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None
        self._prev_c: Optional[float] = None
        self._atr_warmup: list[float] = []
        self._atr: Optional[float]    = None
        self.regime: int              = 0
        self.bars_in_regime: int      = 0

    @property
    def atr(self) -> Optional[float]: return self._atr
    @property
    def ema3_h(self) -> Optional[float]: return self._ema3_h
    @property
    def ema9_h(self) -> Optional[float]: return self._ema9_h
    @property
    def ema3_l(self) -> Optional[float]: return self._ema3_l
    @property
    def ema9_l(self) -> Optional[float]: return self._ema9_l
    @property
    def is_warm(self) -> bool: return self._atr is not None

    def update(self, h: float, l: float, c: float) -> None:
        if self._ema3_h is None:
            self._ema3_h = h; self._ema9_h = h
            self._ema3_l = l; self._ema9_l = l
        else:
            self._ema3_h = _ALPHA3 * h + (1 - _ALPHA3) * self._ema3_h
            self._ema9_h = _ALPHA9 * h + (1 - _ALPHA9) * self._ema9_h
            self._ema3_l = _ALPHA3 * l + (1 - _ALPHA3) * self._ema3_l
            self._ema9_l = _ALPHA9 * l + (1 - _ALPHA9) * self._ema9_l

        tr = (
            (h - l) if self._prev_c is None
            else max(h - l, abs(h - self._prev_c), abs(l - self._prev_c))
        )
        self._prev_c = c
        if self._atr is None:
            self._atr_warmup.append(tr)
            if len(self._atr_warmup) == _ATR_P:
                self._atr = sum(self._atr_warmup) / _ATR_P
                self._atr_warmup = []
        else:
            self._atr = (self._atr * (_ATR_P - 1) + tr) / _ATR_P

        new = self.regime
        if c > self._ema3_h and c > self._ema9_h:  # type: ignore[operator]
            new = 1
        elif c < self._ema3_l and c < self._ema9_l:  # type: ignore[operator]
            new = -1
        if new != 0 and new != self.regime:
            self.bars_in_regime = 1
            self.regime = new
        elif new != 0:
            self.bars_in_regime += 1


# ── WilderATR (standalone) ──────────────────────────────────────────────────

class WilderATR:
    """Standalone Wilder ATR for use where RegimeEngine is not needed."""

    def __init__(self, period: int = 14) -> None:
        self._p       = period
        self._prev_c: Optional[float] = None
        self._warmup: list[float]     = []
        self._atr: Optional[float]    = None

    @property
    def value(self) -> Optional[float]: return self._atr
    @property
    def is_warm(self) -> bool: return self._atr is not None

    def update(self, h: float, l: float, c: float) -> Optional[float]:
        tr = (
            (h - l) if self._prev_c is None
            else max(h - l, abs(h - self._prev_c), abs(l - self._prev_c))
        )
        self._prev_c = c
        if self._atr is None:
            self._warmup.append(tr)
            if len(self._warmup) == self._p:
                self._atr = sum(self._warmup) / self._p
                self._warmup = []
        else:
            self._atr = (self._atr * (self._p - 1) + tr) / self._p
        return self._atr


# ── WilderADX ───────────────────────────────────────────────────────────────

class WilderADX:
    """Wilder's Average Directional Index (ADX) on completed 1m bars.

    Requires 2*period bars before first valid ADX (period for DI smoothing,
    then period more to smooth DX into ADX).  Returns nan until warm.
    """

    PERIOD = 14

    def __init__(self) -> None:
        self._p     = self.PERIOD
        self._bar_n = 0
        self._prev_h: Optional[float] = None
        self._prev_l: Optional[float] = None
        self._prev_c: Optional[float] = None

        # Phase 1 accumulators (bars 1..p)
        self._phase1_trs:  list[float] = []
        self._phase1_dmp:  list[float] = []
        self._phase1_dmn:  list[float] = []

        # Smoothed DI components
        self._tr14:  Optional[float] = None
        self._dmp14: Optional[float] = None
        self._dmn14: Optional[float] = None

        # Phase 2 accumulators for first ADX seed
        self._dx_seed: list[float] = []

        self._adx: Optional[float] = None

    @property
    def value(self) -> float:
        return self._adx if self._adx is not None else float("nan")

    @property
    def is_warm(self) -> bool:
        return self._adx is not None

    def update(self, h: float, l: float, c: float) -> float:
        self._bar_n += 1

        if self._prev_c is None:
            self._prev_h = h
            self._prev_l = l
            self._prev_c = c
            return float("nan")

        ph, pl, pc = self._prev_h, self._prev_l, self._prev_c  # type: ignore[assignment]
        self._prev_h = h
        self._prev_l = l
        self._prev_c = c

        tr  = max(h - l, abs(h - pc), abs(l - pc))
        up  = h - ph
        dn  = pl - l
        dmp = up  if (up > dn  and up  > 0) else 0.0
        dmn = dn  if (dn > up  and dn  > 0) else 0.0

        if self._tr14 is None:
            # Phase 1: accumulate until we have p bars
            self._phase1_trs.append(tr)
            self._phase1_dmp.append(dmp)
            self._phase1_dmn.append(dmn)
            if len(self._phase1_trs) == self._p:
                self._tr14  = sum(self._phase1_trs)
                self._dmp14 = sum(self._phase1_dmp)
                self._dmn14 = sum(self._phase1_dmn)
                self._phase1_trs = []
                self._phase1_dmp = []
                self._phase1_dmn = []
        else:
            self._tr14  = self._tr14  - self._tr14  / self._p + tr
            self._dmp14 = self._dmp14 - self._dmp14 / self._p + dmp
            self._dmn14 = self._dmn14 - self._dmn14 / self._p + dmn

        if self._tr14 is None:
            return float("nan")

        di_p  = 100.0 * self._dmp14 / (self._tr14 + 1e-10)
        di_n  = 100.0 * self._dmn14 / (self._tr14 + 1e-10)
        di_sum = di_p + di_n
        dx    = 100.0 * abs(di_p - di_n) / (di_sum + 1e-10) if di_sum > 0 else 0.0

        if self._adx is None:
            self._dx_seed.append(dx)
            if len(self._dx_seed) == self._p:
                self._adx = sum(self._dx_seed) / self._p
                self._dx_seed = []
        else:
            self._adx = (self._adx * (self._p - 1) + dx) / self._p

        return self.value


# ── KalmanPV ────────────────────────────────────────────────────────────────

class KalmanPV:
    """Two-state Kalman filter: [price, velocity] updated at 1s cadence.

    Adapts observation noise R to the running 60s variance once warm.
    Outputs velocity (pts/s), d_velocity (pts/s²), and innovation z-score.
    """

    _DEFAULT_R = 4.0    # (2 NQ points)^2 — used until variance is stable

    def __init__(self) -> None:
        self._x = [0.0, 0.0]    # [price, velocity]
        self._P = [[1e6, 0.0], [0.0, 1e4]]
        self._R = self._DEFAULT_R
        self._initialised = False

        self._ret_deque: deque[float] = deque(maxlen=60)
        self._innov_std_deque: deque[float] = deque(maxlen=60)

        self._velocity      = float("nan")
        self._d_velocity    = float("nan")
        self._innov_zscore  = float("nan")

    @property
    def velocity(self)     -> float: return self._velocity
    @property
    def d_velocity(self)   -> float: return self._d_velocity
    @property
    def innov_zscore(self) -> float: return self._innov_zscore
    @property
    def is_warm(self)      -> bool:  return self._initialised

    def update(self, price: float, dt: float = 1.0) -> None:
        if not self._initialised:
            self._x = [price, 0.0]
            self._initialised = True
            self._velocity    = 0.0
            self._d_velocity  = 0.0
            self._innov_zscore = 0.0
            return

        # Adapt R from recent variance
        if len(self._ret_deque) >= 10:
            vals = list(self._ret_deque)
            mean = sum(vals) / len(vals)
            var  = sum((v - mean) ** 2 for v in vals) / len(vals)
            self._R = max(var, 0.01)

        # Q scales with R
        qv = self._R * 1e-2
        qa = self._R * 1e-4
        Q  = [[qv, 0.0], [0.0, qa]]

        # Predict
        xp0 = self._x[0] + self._x[1] * dt
        xp1 = self._x[1]
        Pp00 = self._P[0][0] + dt * (self._P[1][0] + self._P[0][1]) + dt * dt * self._P[1][1] + Q[0][0]
        Pp01 = self._P[0][1] + dt * self._P[1][1] + Q[0][1]
        Pp10 = self._P[1][0] + dt * self._P[1][1] + Q[1][0]
        Pp11 = self._P[1][1] + Q[1][1]

        # Innovation: H = [1, 0]
        y = price - xp0
        S = Pp00 + self._R
        if S < 1e-12:
            S = 1e-12

        # Kalman gain
        K0 = Pp00 / S
        K1 = Pp10 / S

        # Update
        prev_vel = self._x[1]
        self._x = [xp0 + K0 * y, xp1 + K1 * y]
        self._P = [
            [Pp00 - K0 * Pp00, Pp01 - K0 * Pp01],
            [Pp10 - K1 * Pp00, Pp11 - K1 * Pp01],
        ]

        # Innovation z-score
        innov_std = math.sqrt(S)
        self._innov_std_deque.append(innov_std)
        med_std = sorted(self._innov_std_deque)[len(self._innov_std_deque) // 2]
        self._innov_zscore = y / (med_std + 1e-8)

        self._velocity   = self._x[1]
        self._d_velocity = self._x[1] - prev_vel

        # Track returns for variance adaptation
        self._ret_deque.append(price - (xp0 - self._x[1] * dt))


# ── BollingerKeltner ────────────────────────────────────────────────────────

class BollingerKeltner:
    """BB and KC widths on last-20 completed 1m bars, with causal percentile.

    BB: SMA20 ± 2*std20 → width = 4*std20
    KC: EMA20 ± 2*ATR20 → width = 4*ATR20
    percentile: rank of current BB width among all prior widths (capped at 1000)
    """

    _N_BARS = 20
    _ALPHA  = 2.0 / (20 + 1)

    def __init__(self) -> None:
        self._bars:     deque[tuple[float, float, float]] = deque(maxlen=self._N_BARS)
        self._ema20:    Optional[float] = None
        self._wilder20: WilderATR      = WilderATR(period=20)

        self._bb_width_history: list[float] = []   # sorted growing list
        self._bb_width:  float = float("nan")
        self._kc_width:  float = float("nan")
        self._bb_pctile: float = float("nan")
        self._bk_ratio:  float = float("nan")

    @property
    def bb_width(self)  -> float: return self._bb_width
    @property
    def kc_width(self)  -> float: return self._kc_width
    @property
    def bb_pctile(self) -> float: return self._bb_pctile
    @property
    def bk_ratio(self)  -> float: return self._bk_ratio

    def update(self, h: float, l: float, c: float) -> None:
        self._bars.append((h, l, c))

        # EMA20 for KC
        if self._ema20 is None:
            self._ema20 = c
        else:
            self._ema20 = self._ALPHA * c + (1 - self._ALPHA) * self._ema20

        # Wilder ATR20 for KC
        atr20 = self._wilder20.update(h, l, c)

        if len(self._bars) < self._N_BARS or not self._wilder20.is_warm:
            return

        closes = [b[2] for b in self._bars]
        mean_c = sum(closes) / self._N_BARS
        var_c  = sum((v - mean_c) ** 2 for v in closes) / self._N_BARS
        std_c  = math.sqrt(var_c)

        self._bb_width = 4.0 * std_c
        self._kc_width = 4.0 * atr20  # type: ignore[arg-type]

        # Causal percentile of bb_width
        bw = self._bb_width
        if len(self._bb_width_history) >= 2:
            rank = bisect.bisect_left(self._bb_width_history, bw)
            self._bb_pctile = rank / len(self._bb_width_history)
        else:
            self._bb_pctile = 0.5

        # Maintain sorted history (cap at 1000 to limit memory)
        bisect.insort(self._bb_width_history, bw)
        if len(self._bb_width_history) > 1000:
            self._bb_width_history.pop(0)

        kc = self._kc_width
        self._bk_ratio = self._bb_width / (kc + 1e-8) if kc > 0 else float("nan")


# ── VolTracker ──────────────────────────────────────────────────────────────

class VolTracker:
    """Tracks volume for z-score and cross-TF ratio.

    Call push_1s(vol) at each 1s bar close (after aggregator).
    Call push_30s(vol) / push_5m(vol) on 30s / 5m bucket close.
    Reads volume_5s_zscore and volume_30s_vs_5m after each 5s close.
    """

    _ZS_MAX_BUCKETS = 60  # 5 minutes of 5s buckets for z-score baseline

    def __init__(self) -> None:
        self._1s_buf:     list[float] = []          # buffer within current 5s
        self._5s_history: deque[float] = deque(maxlen=self._ZS_MAX_BUCKETS)
        self._last_5s_vol:  float = float("nan")
        self._last_30s_vol: float = float("nan")
        self._last_5m_vol:  float = float("nan")

        self.volume_5s_zscore:  float = float("nan")
        self.volume_30s_vs_5m:  float = float("nan")

    def push_1s(self, vol: float) -> None:
        self._1s_buf.append(vol)

    def on_5s_close(self, vol_5s_bucket: float) -> None:
        """Called when 5s bucket closes. vol_5s_bucket = bucket.volume."""
        self._last_5s_vol = vol_5s_bucket
        hist = self._5s_history

        if len(hist) >= 5:
            vals = list(hist)
            mean = sum(vals) / len(vals)
            var  = sum((v - mean) ** 2 for v in vals) / len(vals)
            std  = math.sqrt(var) if var > 0 else 1e-8
            self.volume_5s_zscore = (vol_5s_bucket - mean) / std
        else:
            self.volume_5s_zscore = 0.0

        hist.append(vol_5s_bucket)
        self._1s_buf = []

        # 30s vs 5m ratio
        v30 = self._last_30s_vol
        v5m = self._last_5m_vol
        if not math.isnan(v30) and not math.isnan(v5m) and v5m > 0:
            rate_30s = v30 / 30.0
            rate_5m  = v5m / 300.0
            self.volume_30s_vs_5m = rate_30s / (rate_5m + 1e-10)
        else:
            self.volume_30s_vs_5m = float("nan")

    def push_30s(self, vol: float) -> None:
        self._last_30s_vol = vol

    def push_5m(self, vol: float) -> None:
        self._last_5m_vol = vol


# ── CloseReturnDeque ─────────────────────────────────────────────────────────

class CloseReturnDeque:
    """Rolling deque of (ts_ns: int, close: float) for multi-horizon returns.

    Call push(ts_ns, close) after aggregator (in _update_rolling).
    Call get_close_at(ts_ns) to find the most recent close at-or-before ts_ns.
    """

    _MAXLEN = 120   # 2 minutes of 1s bars

    def __init__(self) -> None:
        self._ts_buf:    list[int]   = []
        self._cl_buf:    list[float] = []

    def push(self, ts_ns: int, close: float) -> None:
        self._ts_buf.append(ts_ns)
        self._cl_buf.append(close)
        if len(self._ts_buf) > self._MAXLEN:
            self._ts_buf.pop(0)
            self._cl_buf.pop(0)

    def get_close_at(self, target_ts_ns: int) -> Optional[float]:
        """Return most recent close where ts_ns <= target_ts_ns, or None."""
        buf = self._ts_buf
        if not buf:
            return None
        idx = bisect.bisect_right(buf, target_ts_ns) - 1
        if idx < 0:
            return None
        return self._cl_buf[idx]

    def latest_close(self) -> Optional[float]:
        if not self._cl_buf:
            return None
        return self._cl_buf[-1]

    def latest_ts(self) -> Optional[int]:
        if not self._ts_buf:
            return None
        return self._ts_buf[-1]

    def realized_vol(self, n_bars: int = 60) -> float:
        """Std dev of last n_bars close-to-close differences (in points)."""
        closes = self._cl_buf[-n_bars - 1:]
        if len(closes) < 4:
            return float("nan")
        diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        mean  = sum(diffs) / len(diffs)
        var   = sum((d - mean) ** 2 for d in diffs) / len(diffs)
        return math.sqrt(var)


# ── Trailing 1m range tracker ────────────────────────────────────────────────

class TrailingRange:
    """Tracks N most recent completed 1m bar highs and lows."""

    def __init__(self, n: int = 20) -> None:
        self._n   = n
        self._hs: deque[float] = deque(maxlen=n)
        self._ls: deque[float] = deque(maxlen=n)

    def update(self, h: float, l: float) -> None:
        self._hs.append(h)
        self._ls.append(l)

    def position(self, price: float) -> float:
        """(price - range_low) / (range_high - range_low), or nan."""
        if len(self._hs) < 2:
            return float("nan")
        hi = max(self._hs)
        lo = min(self._ls)
        rng = hi - lo
        if rng < 1e-8:
            return 0.5
        return (price - lo) / rng

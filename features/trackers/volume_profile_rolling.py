"""tracker.volume_profile.rolling -- rolling volume-at-price profile over completed 1-second bars.

One snapshot per completed OPEN-market minute T of the dataset's Globex ``sessions`` reference table.

Window.  The trailing ``horizon_open_minutes`` open minutes ending at T. Open minutes are
``(open_ns // 60 s + 1 .. close_ns // 60 s) x 60 s`` per session row, so closed time (weekends, holidays,
the daily maintenance break) holds no minutes and consumes no lookback: shortly after the Sunday open
the window reaches back into Friday. An open minute without any 1s bar is a real (empty) minute: it
counts toward the horizon, adds no weight and carries the last close as its price. The window never
crosses a contract roll of the ``rolls`` table (a minute ending after a roll timestamp belongs to the
new contract), nor the first observed minute of the stream (``origin``). ``window_complete`` is true
only when the window holds exactly ``horizon_open_minutes`` minutes; ``roll_truncated`` says a roll is
what shortened it.

Minute membership.  A 1s bar belongs to minute ``ceil(ts_init / 60 s) x 60 s``, i.e. minute T holds the
bars with ts_init in (T - 60 s, T]. Bars whose minute is not an open minute are dropped and counted.

Allocation (``allocation``; one-tick bins; weights in exact int64 fixed point, scale 2**32, so the
rolling add / subtract is order-independent and bit-identical to a scratch rebuild):

==============  =========================================================================================
range_uniform   volume / n on each of the n ticks of [low, high]: volume conserving (canonical R0)
full_per_tick   the full volume on EVERY covered tick: NOT volume conserving. A traversal-weighted
                participation-intensity profile -- never literal executed volume at price
close           the full volume on the close tick: volume conserving
==============  =========================================================================================

Snapshot (null until the window holds >= ``min_window`` minutes AND A is defined):
A = mean 1-minute true range over the minutes with a 1s bar among the trailing ``a_window`` open minutes
(roll-truncated; >= ``a_min_live`` such minutes). Smoothing is along the PRICE axis only: Gaussian,
sigma = ``sigma_a`` x A (scipy ``gaussian_filter1d``, mode constant) over the window's tick range padded by
4 sigma + 2 ticks. POC = argmax of the smoothed profile (first maximum = lowest price). Value area on the
RAW profile from the POC tick: compare the next two ticks above with the next two below, add the larger
pair (tie: both), stop at >= ``va_frac`` of the profile's OWN total weight (for full_per_tick that is
traversal-weighted mass, not contract volume). ``raw_*`` repeats the value area from the raw argmax.
HVN / LVN = the VP V1 node rules on the smoothed profile (prominence >= 0.20 of the POC density,
separation >= 1 A, extent at half prominence clipped at the valley between neighbours).

The parity oracle is the study-local R0 (studies/nq_auction_map_1s/auction_map.py channel ``vr`` +
nq_poc_node_edge_rejection/poc_node.curve + vp_v1.value_area / profile); it is not imported.
"""
from __future__ import annotations

import json
from collections import deque
from fractions import Fraction
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
from numba import njit
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, peak_widths

from features.trackers.base import REQUIRED, BarView, BaseBinding, EmittedEvent, EpochView

NS = 1_000_000_000
MIN_NS = 60 * NS
FP = float(2 ** 32)                 # fixed-point scale of every profile weight
HVN_PROM = 0.20                     # VP V1 node rules (frozen, outcome-blind)
HVN_SEP_A = 1.0
HVN_REL = 0.5
ALLOCATIONS = ("range_uniform", "full_per_tick", "close")


def open_minute_ends(opens_ns: np.ndarray, closes_ns: np.ndarray) -> np.ndarray:
    """Every open-minute end of the session rows, ascending."""
    parts = [np.arange(int(o) // MIN_NS + 1, int(c) // MIN_NS + 1, dtype=np.int64) for o, c in zip(opens_ns, closes_ns)]
    k = np.unique(np.concatenate(parts)) if parts else np.empty(0, np.int64)
    return k * MIN_NS


@lru_cache(maxsize=4)
def load_calendar(dataset: str):
    """(open-minute ends, roll timestamps) from the dataset's hash-verified reference tables."""
    from pathlib import Path

    from research_workflow import dataset_v2
    from research_workflow.roots import resolve_dataset

    repo = Path(__file__).resolve().parents[2]
    resolved = resolve_dataset(dataset, repo)
    t = dataset_v2.load_reference_tables(resolved.catalog_path, ["sessions", "rolls"])
    s = t["sessions"]
    return open_minute_ends(s.open_ns.to_numpy(), s.close_ns.to_numpy()), np.sort(t["rolls"].ts_ns.to_numpy().astype(np.int64))


@njit(cache=True)
def value_area_int(X, C, ip, frac, tot, totc):
    """The same walk on the int64 fixed-point profile with rigorous rounding bounds: C[t] = number of rounded
    bar-tick contributions to tick t (each off by <= 0.5 unit). Returns (lo, hi, acc, ambiguous); ambiguous =
    a pair comparison or the stop test lies inside its error bound -> the caller resolves it exactly."""
    lo = ip
    hi = ip
    acc = X[ip]
    accc = C[ip]
    n = len(X)
    while True:
        m = frac * tot - acc
        if abs(m) <= 0.5 * (accc + frac * totc) + 2.0:
            return lo, hi, acc, True
        if not (m > 0 and (lo > 0 or hi < n - 1)):
            return lo, hi, acc, False
        up, upc, dn, dnc = -1, 0, -1, 0
        if hi < n - 1:
            up = X[hi + 1:min(hi + 3, n)].sum()
            upc = C[hi + 1:min(hi + 3, n)].sum()
        if lo > 0:
            dn = X[max(lo - 2, 0):lo].sum()
            dnc = C[max(lo - 2, 0):lo].sum()
        if up >= 0 and dn >= 0 and upc + dnc > 0 and abs(up - dn) <= 0.5 * (upc + dnc):
            return lo, hi, acc, True
        if up > dn:
            acc += up
            accc += upc
            hi = min(hi + 2, n - 1)
        elif dn > up:
            acc += dn
            accc += dnc
            lo = max(lo - 2, 0)
        else:
            acc += up + dn
            accc += upc + dnc
            hi = min(hi + 2, n - 1)
            lo = max(lo - 2, 0)


def value_area_exact(E, ip, frac):
    """The oracle walk on exact rationals (list of Fraction)."""
    tot, n, lo, hi = sum(E), len(E), ip, ip
    acc, fr = E[ip], Fraction(frac)
    while acc < fr * tot and (lo > 0 or hi < n - 1):
        up = sum(E[hi + 1:min(hi + 3, n)]) if hi < n - 1 else Fraction(-1)
        dn = sum(E[max(lo - 2, 0):lo]) if lo > 0 else Fraction(-1)
        if up > dn:
            acc += up
            hi = min(hi + 2, n - 1)
        elif dn > up:
            acc += dn
            lo = max(lo - 2, 0)
        else:
            acc += up + dn
            hi = min(hi + 2, n - 1)
            lo = max(lo - 2, 0)
    return lo, hi, float(acc / tot) if tot else 0.0


def nodes(S, X, px, ip, val, vah, sig_t, tick):
    """VP V1 HVN / LVN extraction on the smoothed profile (oracle: vp_v1.profile)."""
    tot = X.sum()
    s = S / max(S.max(), 1e-12)
    pk, pr = find_peaks(s, prominence=HVN_PROM, distance=max(1, int(round(HVN_SEP_A * 2 * sig_t))))
    if len(pk) == 0 or s[pk].max() < s[ip]:
        pa, pra = find_peaks(s, prominence=0.0)
        keep = (pra["prominences"] >= HVN_PROM) | (pa == ip)
        pk, pr = pa[keep], {k: v[keep] for k, v in pra.items()}
        if len(pk) == 0 or s[pk].max() < s[ip]:
            pk = np.array([ip]); pr = dict(prominences=np.array([1.0]), left_bases=np.array([0]), right_bases=np.array([len(s) - 1]))
    w = peak_widths(s, pk, rel_height=HVN_REL, prominence_data=(pr["prominences"], pr["left_bases"], pr["right_bases"]))
    lo_i, hi_i = w[2].copy(), w[3].copy()
    valleys = [int(pk[i] + np.argmin(s[pk[i]:pk[i + 1] + 1])) for i in range(len(pk) - 1)]
    for i, v in enumerate(valleys):
        hi_i[i] = min(hi_i[i], v)
        lo_i[i + 1] = max(lo_i[i + 1], v)
    fpx = lambda x: float(px[0] + x * tick)  # noqa: E731
    poc_pk = int(pk[int(np.argmax(s[pk]))])
    poc = float(px[ip])
    hvns = []
    for i, q in enumerate(pk):
        lo_p, hi_p = fpx(lo_i[i]), fpx(hi_i[i])
        m = float(X[int(np.ceil(lo_i[i])):int(np.floor(hi_i[i])) + 1].sum() / max(tot, 1e-12))
        hvns.append(dict(id=i, center=float(px[q]), lo=lo_p, hi=hi_p, peak_rel=float(s[q]), prominence=float(pr["prominences"][i]),
                         width_pts=hi_p - lo_p, dist_poc=float(px[q]) - poc, mass=m, is_poc=bool(q == poc_pk), in_va=bool(val <= px[q] <= vah)))
    lvns = []
    for i, v in enumerate(valleys):
        lo_p, hi_p = hvns[i]["hi"], hvns[i + 1]["lo"]
        lvns.append(dict(id=i, center=float(px[v]), lo=lo_p, hi=hi_p, min_rel=float(s[v]),
                         depth=float(min(s[pk[i]], s[pk[i + 1]]) - s[v]), width_pts=hi_p - lo_p, hvn_below=i, hvn_above=i + 1))
    return hvns, lvns


class _Buf:
    """Growable float64 / bool column indexed by local minute position."""

    def __init__(self, dtype=np.float64, fill=np.nan):
        self.a = np.full(4096, fill, dtype)
        self.fill = fill
        self.n = 0

    def append(self, x):
        if self.n == len(self.a):
            self.a = np.concatenate([self.a, np.full(len(self.a), self.fill, self.a.dtype)])
        self.a[self.n] = x
        self.n += 1


class VolumeProfileKernel:
    """Incremental rolling profile. Feed bars in ts order with ``push``; it returns the open-minute indices
    it closed; ``snapshot()`` describes the latest closed minute (``snapshot(full=True)`` adds the arrays)."""

    def __init__(self, minute_ends: np.ndarray, roll_ts: np.ndarray, horizon_open_minutes: int, allocation: str = "range_uniform",
                 tick: float = 0.25, sigma_a: float = 0.5, a_window: int = 390, a_min_live: int = 30, min_window: int = 30,
                 va_frac: float = 0.70, origin_ns: Optional[int] = None):
        if allocation not in ALLOCATIONS:
            raise ValueError(f"allocation must be one of {ALLOCATIONS}")
        self.om = np.asarray(minute_ends, np.int64)
        self.rolls = np.sort(np.asarray(roll_ts, np.int64))
        self.h_min, self.alloc, self.tick = int(horizon_open_minutes), allocation, float(tick)
        self.sigma_a, self.a_window, self.a_min_live, self.min_window, self.va_frac = float(sigma_a), int(a_window), int(a_min_live), int(min_window), float(va_frac)
        seg = np.searchsorted(self.rolls, self.om, side="left")             # minute ending AT a roll stays with the old contract
        first = np.r_[True, seg[1:] != seg[:-1]]
        self.seg_start = np.maximum.accumulate(np.where(first, np.arange(len(self.om)), 0))
        self.p0: Optional[int] = None if origin_ns is None else int(np.searchsorted(self.om, int(origin_ns), side="right"))
        self.next_p: Optional[int] = self.p0                                 # next open minute to close
        self.pend: List[tuple] = []                                          # bars of minute next_p: (lt, ht, ct, v, h, l, c)
        self.h, self.l, self.c, self.v, self.tr = _Buf(), _Buf(), _Buf(), _Buf(), _Buf()
        self.cs, self.cn = _Buf(), _Buf()
        self.cs.append(0.0); self.cn.append(0.0)
        self.last_close = np.nan
        self.win: deque = deque()                                            # (p, ticks, w_int) of the minutes in the window
        self.base: Optional[int] = None
        self.X = np.zeros(0, np.int64)
        self.vol_in_win = 0.0
        self.last_p: Optional[int] = None
        self.dropped = 0
        self.n_exact = 0                                                     # value-area walks resolved exactly
        self.on_close = None                                                 # optional callback(p), state = right after p closed

    # ----------------------------------------------------------------------------------------- feeding
    def reset_pos(self, p: int) -> int:
        return max(int(self.seg_start[p]), self.p0)

    def push(self, ts: int, high: float, low: float, close: float, volume: float) -> List[int]:
        """Add one 1s bar (ts = ts_init). Returns the open-minute indices closed by this call."""
        mk = -(-int(ts) // MIN_NS) * MIN_NS
        p = int(np.searchsorted(self.om, mk))
        if p >= len(self.om) or self.om[p] != mk:
            self.dropped += 1
            return []
        if self.p0 is None:
            self.p0 = self.next_p = p
        if p < self.next_p:
            raise ValueError("bars must arrive in ts order")
        closed = []
        while self.next_p < p:
            closed.append(self._close())
        t = self.tick
        self.pend.append((int(round(low / t)), int(round(high / t)), int(round(close / t)), float(volume), float(high), float(low), float(close)))
        if mk == int(ts):                                                    # last possible bar of the minute
            closed.append(self._close())
        return closed

    def close_through(self, ts: int) -> List[int]:
        """Close every open minute ending at or before ``ts`` (no bar can join them any more)."""
        closed = []
        while self.next_p is not None and self.next_p < len(self.om) and self.om[self.next_p] <= ts:
            closed.append(self._close())
        return closed

    def _grid(self, lo: int, hi: int):
        if self.base is None:
            self.base = lo - 50_000
            self.X = np.zeros(100_000 + (hi - lo), np.int64)
            self.C = np.zeros_like(self.X)
        if lo < self.base:
            pad = (self.base - lo) + 50_000
            self.X = np.concatenate([np.zeros(pad, np.int64), self.X])
            self.C = np.concatenate([np.zeros(pad, np.int64), self.C])
            self.base -= pad
        if hi - self.base >= len(self.X):
            ext = hi - self.base - len(self.X) + 50_000
            self.X = np.concatenate([self.X, np.zeros(ext, np.int64)])
            self.C = np.concatenate([self.C, np.zeros(ext, np.int64)])

    def _close(self) -> int:
        p = self.next_p
        rp = self.reset_pos(p)
        live = bool(self.pend)
        if live:
            b = np.array([x[:4] for x in self.pend])
            lt, ht, ct, v = b[:, 0].astype(np.int64), b[:, 1].astype(np.int64), b[:, 2].astype(np.int64), b[:, 3]
            h = max(x[4] for x in self.pend); lo_ = min(x[5] for x in self.pend); c = self.pend[-1][6]
            if self.alloc == "close":
                tk, w = ct, np.round(v * FP).astype(np.int64)
            else:
                n = ht - lt + 1
                off = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
                tk = np.repeat(lt, n) + off
                per = v / n if self.alloc == "range_uniform" else v
                w = np.repeat(np.round(per * FP).astype(np.int64), n)
            u, inv = np.unique(tk, return_inverse=True)
            wi = np.zeros(len(u), np.int64)
            np.add.at(wi, inv, w)                                                    # exact int accumulation
            if self.alloc == "range_uniform":                                        # rounding bookkeeping + exact triplets
                ci = np.bincount(inv, minlength=len(u)).astype(np.int64)
                nn = np.repeat(n, n)
                if nn.max() >= 4096:
                    raise ValueError("a 1s bar spans >= 4096 ticks")
                tk_, inv2 = np.unique(tk * 4096 + nn, return_inverse=True)
                tv = np.zeros(len(tk_), np.int64)
                np.add.at(tv, inv2, np.repeat(np.round(v).astype(np.int64), n))
                trip = (tk_, tv)
            else:
                ci, trip = np.zeros(len(u), np.int64), None
            vsum = float(v.sum())
            self.last_close = c
        else:
            u, wi, vsum, ci, trip = np.empty(0, np.int64), np.empty(0, np.int64), 0.0, None, None
            h = lo_ = c = self.last_close
        # minute layer + true range (oracle: auction_map.minute_layer / a_series)
        k = p - self.p0
        pc = self.c.a[k - 1] if k > 0 else np.nan
        if p == rp:
            tr = h - lo_
        else:
            cand = [x for x in (h - lo_, abs(h - pc), abs(lo_ - pc)) if not np.isnan(x)]
            tr = max(cand) if cand else np.nan
        if not live:
            tr = 0.0
        for buf, x in ((self.h, h), (self.l, lo_), (self.c, c), (self.v, vsum), (self.tr, tr)):
            buf.append(x)
        self.cs.append(self.cs.a[self.cs.n - 1] + tr)
        self.cn.append(self.cn.a[self.cn.n - 1] + (1.0 if live else 0.0))
        # rolling window: evict, then add
        start = max(p - self.h_min + 1, rp)
        while self.win and self.win[0][0] < start:
            _, tk_old, w_old, v_old, c_old, _ = self.win.popleft()
            np.subtract.at(self.X, tk_old - self.base, w_old)
            np.subtract.at(self.C, tk_old - self.base, c_old)
            self.vol_in_win -= v_old
        if len(u):
            self._grid(int(u[0]), int(u[-1]))
            np.add.at(self.X, u - self.base, wi)
            np.add.at(self.C, u - self.base, ci)
            self.win.append((p, u, wi, vsum, ci, trip))
            self.vol_in_win += vsum
        self.pend = []
        self.next_p = p + 1
        self.last_p = p
        if self.on_close is not None:
            self.on_close(p)
        return p

    def _exact(self, a: int, b: int) -> list:
        """Exact profile on ticks a..b: contract units for range_uniform (from the window's (tick, n, volume)
        triplets); the exact int64 weights otherwise (comparisons are scale-free)."""
        if self.alloc != "range_uniform":
            return [Fraction(int(x)) for x in self.X[a - self.base:b - self.base + 1]]
        keys = np.concatenate([w[5][0] for w in self.win if w[5] is not None])
        vals = np.concatenate([w[5][1] for w in self.win if w[5] is not None])
        k, inv = np.unique(keys, return_inverse=True)
        tv = np.zeros(len(k), np.int64)
        np.add.at(tv, inv, vals)
        E = [Fraction(0)] * (b - a + 1)
        for key, vol in zip(k.tolist(), tv.tolist()):
            t, n = divmod(key, 4096)
            if a <= t <= b and vol:
                E[t - a] += Fraction(vol, n)
        return E

    # ----------------------------------------------------------------------------------------- snapshot
    def A(self, p: int) -> float:
        k = p - self.p0
        a = max(p - self.a_window + 1, self.reset_pos(p)) - self.p0
        n = self.cn.a[k + 1] - self.cn.a[a]
        return float((self.cs.a[k + 1] - self.cs.a[a]) / n) if n >= self.a_min_live else float("nan")

    def snapshot(self, full: bool = False) -> Optional[Dict[str, Any]]:
        p = self.last_p
        if p is None:
            return None
        rp = self.reset_pos(p)
        start = max(p - self.h_min + 1, rp)
        wm = p - start + 1
        row: Dict[str, Any] = dict(snapshot_ts=int(self.om[p]), minute_idx=p, window_minutes=wm, window_complete=wm == self.h_min,
                                   roll_truncated=bool(int(self.seg_start[p]) > p - self.h_min + 1 and int(self.seg_start[p]) >= self.p0),
                                   dropped_bars=self.dropped)
        A = self.A(p)
        if wm < self.min_window or np.isnan(A) or self.base is None:
            return row | dict(A=None if np.isnan(A) else A, poc=None)
        k0, k1 = start - self.p0, p - self.p0 + 1
        wl, wh = float(np.min(self.l.a[k0:k1])), float(np.max(self.h.a[k0:k1]))
        t = self.tick
        lo_t, hi_t = int(round(wl / t)), int(round(wh / t))
        sig_t = self.sigma_a * A / t
        pad = int(np.ceil(4 * sig_t)) + 2
        a, b = lo_t - pad, hi_t + pad
        self._grid(a, b)
        Xi = self.X[a - self.base:b - self.base + 1]
        X = Xi.astype(np.float64) / FP
        S = np.maximum(gaussian_filter1d(X, sig_t, mode="constant"), 0.0)
        px = np.arange(a, b + 1) * t
        Ci = self.C[a - self.base:b - self.base + 1]
        ip = int(np.argmax(S))
        exact = None
        ir = int(np.argmax(Xi))
        if Ci.any():                                                         # rounding can hide an exact tie for the max
            cand = np.flatnonzero(Xi + 0.5 * Ci >= Xi[ir] - 0.5 * Ci[ir])
            if len(cand) > 1:
                exact = self._exact(a, b)
                vals = [exact[c] for c in cand]
                ir = int(cand[vals.index(max(vals))])
        walks = []
        for i0 in (ip, ir):
            lo_i, hi_i, acc, amb = value_area_int(Xi, Ci, i0, self.va_frac, float(Xi.sum()), float(Ci.sum()))
            if amb:
                exact = exact if exact is not None else self._exact(a, b)
                lo_i, hi_i, fr = value_area_exact(exact, i0, self.va_frac)
                self.n_exact += 1
            else:
                fr = float(acc) / float(Xi.sum())
            walks.append((lo_i, hi_i, fr))
        (l_, h_, frac), (lr, hr, _) = walks
        poc, val, vah = float(px[ip]), float(px[l_]), float(px[h_])
        hv, lv = nodes(S, X, px, ip, val, vah, sig_t, t)
        row.update(A=A, sigma_ticks=sig_t, win_lo=wl, win_hi=wh, profile_width=wh - wl, total_source_volume=self.vol_in_win,
                   total_weight=float(Xi.sum()) / FP, n_occupied_bins=int((Xi > 0).sum()), poc=poc, vah=vah, val=val, va_width=vah - val,
                   va_weight_fraction=float(frac), raw_poc=float(px[ir]), raw_vah=float(px[hr]), raw_val=float(px[lr]),
                   n_hvn=len(hv), n_lvn=len(lv), hvns_json=json.dumps(hv, separators=(",", ":")), lvns_json=json.dumps(lv, separators=(",", ":")))
        if full:
            row.update(px=px, X=X, S=S)
        return row


class VolumeProfileRollingBinding(BaseBinding):
    CAPABILITY = "tracker.volume_profile.rolling"
    PARAMS = {"horizon_open_minutes": REQUIRED, "allocation": "range_uniform", "dataset": REQUIRED, "tick": 0.25, "sigma_a": 0.5,
              "a_window": 390, "a_min_live": 30, "min_window": 30, "va_frac": 0.7}
    INPUTS = {"bars": "stream"}
    FIELDS = ('snapshot_ts', 'window_minutes', 'window_complete', 'roll_truncated', 'A', 'sigma_ticks', 'win_lo', 'win_hi', 'profile_width',
              'total_source_volume', 'total_weight', 'n_occupied_bins', 'poc', 'vah', 'val', 'va_width', 'va_weight_fraction', 'raw_poc',
              'raw_vah', 'raw_val', 'n_hvn', 'n_lvn', 'hvns_json', 'lvns_json', 'dropped_bars')
    EPOCH_FIELDS = ()
    EVENTS = ('minute_closed',)
    SUBSCRIBES = ()
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        pr = self.params
        om, rolls = load_calendar(str(pr["dataset"]))
        self.kernel = VolumeProfileKernel(om, rolls, int(pr["horizon_open_minutes"]), str(pr["allocation"]), float(pr["tick"]),
                                          float(pr["sigma_a"]), int(pr["a_window"]), int(pr["a_min_live"]), int(pr["min_window"]),
                                          float(pr["va_frac"]))
        for f in self.FIELDS:
            setattr(self, f, None)

    def on_bar(self, input_key: str, bar: BarView) -> None:
        closed = self.kernel.push(bar.ts_init, bar.high, bar.low, bar.close, bar.volume)
        self.dropped_bars = self.kernel.dropped
        if not closed:
            return
        snap = self.kernel.snapshot()                       # only the latest closed minute is observable now
        for f in self.FIELDS:
            setattr(self, f, snap.get(f))
        for p in closed:
            self.emit("minute_closed", {"snapshot_ts": int(self.kernel.om[p])})

    def on_event(self, input_key: str, event: EmittedEvent) -> None:
        return None

    def epoch_value(self, name: str, epoch: EpochView) -> Any:
        raise KeyError(name)

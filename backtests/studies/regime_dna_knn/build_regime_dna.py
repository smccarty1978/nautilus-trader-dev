"""Branch 1 — Frozen Regime DNA + tradeable race labels (one causal 1s replay).

At every 1m regime flip we freeze the PRE-FLIP origin story using ONLY bars
strictly before the flip (windows pre_5/15/30), direction-normalized to the NEW
regime direction, with an ATR floor: atr_norm = max(atr, 0.5*rolling_atr_60).
Separately, for every in-regime bar (1..30) we evaluate forward PT-before-SL
races (5 brackets + horizons) on the 1s path, with velocity (bars to PT/SL/flip)
and the next-open regime-exit convention.

Outputs (results/ under this study):
  regime_dna.parquet        one row per regime (frozen DNA + identity)
  dna_race_labels.parquet   one row per in-regime bar (race outcomes + velocity)

    python studies/regime_dna_knn/build_regime_dna.py --years 2021,...,2026
"""
from __future__ import annotations
import argparse, os, sys, time
from collections import deque
from pathlib import Path
import numpy as np
import pandas as pd
import pytz
from nautilus_trader.persistence.catalog import ParquetDataCatalog

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT)); os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from collectors.collector_v2.registry import CompletedBarRegistry  # noqa: E402
from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket  # noqa: E402
from collectors.collector_v2.regime_engine import RegimeStateEngine  # noqa: E402

CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
OUT = Path("studies/regime_dna_knn/results")
CT = pytz.timezone("America/Chicago")
NS = 1_000_000_000
MULT = 20.0
TFS = ("5m", "1m", "5s")
RTH_START_MIN, RTH_END_MIN = 510, 900
WINDOWS = (5, 15, 30)
BRACKETS = [(0.50, 0.25, "pt050_sl025"), (0.75, 0.50, "pt075_sl050"),
            (1.00, 0.50, "pt100_sl050"), (1.50, 0.75, "pt150_sl075"),
            (2.00, 1.00, "pt200_sl100")]
HORIZONS = {"pt050_sl025": (3, 5), "pt100_sl050": (5, 10)}


class _EMA:
    def __init__(self, p):
        self.a = 2.0 / (p + 1); self.v = None; self.prev = None
    def update(self, x):
        self.prev = self.v
        self.v = x if self.v is None else self.a * x + (1 - self.a) * self.v


def _lr_slope(y):
    n = len(y)
    if n < 2:
        return 0.0
    x = np.arange(n); xm = x.mean(); ym = float(np.mean(y))
    den = float(((x - xm) ** 2).sum())
    return float(((x - xm) * (y - ym)).sum() / den) if den > 0 else 0.0


class DNAReplay:
    def __init__(self, year):
        self.year = year
        self._reg = CompletedBarRegistry(supported_timeframes=TFS)
        self._eng = {tf: RegimeStateEngine(tf, self._reg) for tf in TFS}
        self._agg = TimeframeAggregator(on_bucket_closed=self.on_bucket_closed, timeframes=TFS)
        self._prev = {tf: 0 for tf in TFS}
        self._buf = deque(maxlen=70)
        self._atr_hist = deque(maxlen=60)
        self._vol_hist = deque(maxlen=60)
        self._ema9 = _EMA(9); self._ema21 = _EMA(21); self._prev_s9 = None
        # session
        self._vwap_key = None; self._cum_pv = 0.0; self._cum_v = 0.0
        self._sess_hi = -1e18; self._sess_lo = 1e18
        self._on_hi = -1e18; self._on_lo = 1e18; self._prev_is_rth = None
        # regime
        self._dir = 0; self._rid = 0; self._ridx = 0; self._bi = 0
        self._entry_px = 0.0; self._entry_atr = 1.0
        self._rhi_prior = 0.0; self._rlo_prior = 0.0
        self._cps = []; self._pending = []; self._flip = False; self._prevdir = 0
        self._rid_next = 0
        self._cur_minct = 0; self._cur_is_rth = False
        self.dna = []; self.labels = []

    def _update_session(self, tse, h, l, c, v):
        ct = pd.Timestamp(int(tse), tz="UTC").tz_convert(CT)
        minct = ct.hour * 60 + ct.minute
        is_rth = RTH_START_MIN <= minct < RTH_END_MIN
        d = ct.date()
        vkey = (d + pd.Timedelta(days=1)) if ct.hour >= 17 else d
        if vkey != self._vwap_key:
            self._vwap_key = vkey; self._cum_pv = 0.0; self._cum_v = 0.0
        typ = (h + l + c) / 3.0
        self._cum_pv += typ * v; self._cum_v += v
        if is_rth:
            if not self._prev_is_rth:
                self._sess_hi, self._sess_lo = h, l
            else:
                self._sess_hi = max(self._sess_hi, h); self._sess_lo = min(self._sess_lo, l)
        else:
            if self._prev_is_rth:
                self._on_hi, self._on_lo = h, l
            else:
                self._on_hi = max(self._on_hi, h); self._on_lo = min(self._on_lo, l)
        self._prev_is_rth = is_rth
        return minct, is_rth

    def _compute_dna(self, state):
        # Strictly pre-flip: EMAs/session levels are NOT yet advanced through the
        # flip bar (updated AFTER this call), and the reference price is the LAST
        # pre-flip bar close (the flip bar is the resolution, excluded). minct/
        # is_rth are derived from the flip bar close_ts (the flip moment, causal).
        d = state.regime
        ct = pd.Timestamp(int(state.close_ts), tz="UTC").tz_convert(CT)
        minct = ct.hour * 60 + ct.minute
        is_rth = RTH_START_MIN <= minct < RTH_END_MIN
        cur_atr = state.atr if (state.atr == state.atr and state.atr > 0) else 1.0
        roll_atr = float(np.mean(self._atr_hist)) if self._atr_hist else cur_atr
        atrn = max(cur_atr, 0.5 * roll_atr) if roll_atr > 0 else cur_atr
        if atrn <= 0:
            atrn = 1.0
        roll_vol = float(np.mean(self._vol_hist)) if self._vol_hist else 0.0
        roll_vol_std = float(np.std(self._vol_hist)) if len(self._vol_hist) > 1 else 0.0
        buf = list(self._buf)
        rec = {"regime_id": np.int64(self._rid_next), "regime_start_ts": np.int64(state.close_ts),
               "year": np.int16(self.year), "direction": np.int8(d),
               "atr_norm_at_flip": np.float32(atrn),
               "atr_ratio_vs_60": np.float32(cur_atr / roll_atr if roll_atr > 0 else 1.0)}
        for N in WINDOWS:
            pfx = f"pre_{N}"
            if len(buf) >= N:
                w = buf[-N:]
                o = np.array([b[0] for b in w]); h = np.array([b[1] for b in w])
                lo = np.array([b[2] for b in w]); cl = np.array([b[3] for b in w])
                vol = np.array([b[4] for b in w])
                ret = (cl[-1] - cl[0]) * d / atrn
                rng = (h.max() - lo.min()) / atrn
                body = float(np.abs(cl - o).sum()) / atrn
                dif = np.diff(cl)
                rvol = float(np.std(dif)) / atrn if len(dif) else 0.0
                path = float(np.abs(dif).sum())
                eff = abs(cl[-1] - cl[0]) / path if path > 1e-9 else 0.0
                chop = 1.0 - eff
                hh = 0; fbo = 0
                if d == 1:
                    run, runc = -1e18, -1e18
                    for i in range(len(w)):
                        if h[i] > run:
                            hh += 1
                            if run > -1e17 and cl[i] < runc:
                                fbo += 1
                            run = h[i]
                        runc = max(runc, cl[i])
                else:
                    run, runc = 1e18, 1e18
                    for i in range(len(w)):
                        if lo[i] < run:
                            hh += 1
                            if run < 1e17 and cl[i] > runc:
                                fbo += 1
                            run = lo[i]
                        runc = min(runc, cl[i])
                mean_rng = float((h - lo).mean())
                range_ratio = mean_rng / roll_atr if roll_atr > 0 else 1.0
                comp = max(0.0, 1.0 - range_ratio); exp = max(0.0, range_ratio - 1.0)
                lr = _lr_slope(cl) * d / atrn
                vr = (float(vol.mean()) / roll_vol) if roll_vol > 0 else 1.0
                vt = _lr_slope(vol) / roll_vol if roll_vol > 0 else 0.0
                vz = (float(vol.mean()) - roll_vol) / roll_vol_std if roll_vol_std > 0 else 0.0
                sv = float((vol * np.sign(cl - o) * d).sum()) / (float(vol.sum()) + 1e-9)
                vals = dict(return_atr=ret, range_atr=rng, body_sum_atr=body, realized_vol_atr=rvol,
                            efficiency=eff, chop_score=chop, hh_ll_count=hh, failed_breakout_count=fbo,
                            range_ratio_vs_60=range_ratio, compression_score=comp, expansion_score=exp,
                            lr_slope_atr=lr, volume_ratio=vr, volume_trend=vt, volume_zscore=vz,
                            signed_volume_proxy=sv)
            else:
                vals = dict.fromkeys(
                    ["return_atr", "range_atr", "body_sum_atr", "realized_vol_atr", "efficiency",
                     "chop_score", "hh_ll_count", "failed_breakout_count", "range_ratio_vs_60",
                     "compression_score", "expansion_score", "lr_slope_atr", "volume_ratio",
                     "volume_trend", "volume_zscore", "signed_volume_proxy"], np.nan)
            for k, val in vals.items():
                rec[f"{pfx}_{k}"] = np.float32(val)
        e9, e21 = self._ema9.v, self._ema21.v          # pre-flip EMA (not yet advanced through flip bar)
        s9 = ((self._ema9.v - self._ema9.prev) * d / atrn) if self._ema9.prev is not None else np.nan
        s21 = ((self._ema21.v - self._ema21.prev) * d / atrn) if self._ema21.prev is not None else np.nan
        accel = (s9 - self._prev_s9) if (self._prev_s9 is not None and s9 == s9) else np.nan
        if s9 == s9:
            self._prev_s9 = s9
        c = buf[-1][3] if buf else state.close          # last PRE-FLIP close (W2)
        rec["ema9_slope_atr"] = np.float32(s9)
        rec["ema21_slope_atr"] = np.float32(s21)
        rec["slope_acceleration"] = np.float32(accel)
        rec["distance_from_ema9_atr"] = np.float32(d * (c - e9) / atrn if e9 is not None else np.nan)
        rec["distance_from_ema21_atr"] = np.float32(d * (c - e21) / atrn if e21 is not None else np.nan)
        vw = self._cum_pv / self._cum_v if self._cum_v > 0 else None
        rec["time_of_day_bucket"] = np.int8(minct // 30)
        rec["minutes_since_rth_open"] = np.int16(minct - RTH_START_MIN)
        rec["minutes_to_rth_close"] = np.int16(RTH_END_MIN - minct)
        rec["is_rth"] = np.int8(int(is_rth))
        rec["distance_to_vwap_atr"] = np.float32(d * (c - vw) / atrn if vw is not None else np.nan)
        rec["distance_to_session_high_atr"] = np.float32((self._sess_hi - c) / atrn if self._sess_hi > -1e17 else np.nan)
        rec["distance_to_session_low_atr"] = np.float32((c - self._sess_lo) / atrn if self._sess_lo < 1e17 else np.nan)
        rec["distance_to_overnight_high_atr"] = np.float32((self._on_hi - c) / atrn if self._on_hi > -1e17 else np.nan)
        rec["distance_to_overnight_low_atr"] = np.float32((c - self._on_lo) / atrn if self._on_lo < 1e17 else np.nan)
        self.dna.append(rec)

    def on_bucket_closed(self, tf, completed: _OpenBucket):
        self._eng[tf].on_bar_closed(completed)
        st = self._reg.get(tf)
        if st is None:
            return
        now = st.regime; prev = self._prev[tf]
        flipped = (now != prev and now != 0)
        if tf == "1m":
            if flipped:
                self._flip = True; self._prevdir = prev
                self._ridx += 1
                self._rid_next = self.year * 100_000 + self._ridx
                self._compute_dna(st)   # EMAs/buffer NOT yet advanced through the flip bar (W2)
                self._dir = now; self._rid = self._rid_next; self._bi = 0
                self._entry_px = st.close
                cur_atr = st.atr if (st.atr == st.atr and st.atr > 0) else 1.0
                roll_atr = float(np.mean(self._atr_hist)) if self._atr_hist else cur_atr
                self._entry_atr = max(cur_atr, 0.5 * roll_atr) if roll_atr > 0 else cur_atr
                self._rhi_prior = st.close; self._rlo_prior = st.close
            else:
                if self._dir != 0:
                    self._bi += 1
                    if self._bi <= 30:
                        self._cps.append({"regime_id": self._rid, "bar_index": self._bi,
                                          "direction": self._dir, "bar_ts": completed.close_ts,
                                          "checkpoint_px": completed.close, "atr": self._entry_atr,
                                          "path": []})
                    if self._dir == 1 and completed.high > self._rhi_prior:
                        self._rhi_prior = completed.high
                    elif self._dir == -1 and completed.low < self._rlo_prior:
                        self._rlo_prior = completed.low
            # Advance EMA/ATR/vol/buffer state with the flip bar ONLY AFTER the
            # DNA snapshot, so DNA is strictly pre-flip (W2).
            self._ema9.update(completed.close); self._ema21.update(completed.close)
            if st.atr == st.atr and st.atr > 0:
                self._atr_hist.append(st.atr)
            self._vol_hist.append(completed.volume)
            self._buf.append((completed.open, completed.high, completed.low, completed.close,
                              completed.volume, completed.close_ts))
        self._prev[tf] = now

    def on_1s(self, o, h, l, c, v, tse, tsi):
        self._flip = False; self._prevdir = 0
        # Aggregator first: a 1m flip fires _compute_dna while session levels still
        # reflect ONLY bars through the PRIOR 1s bar (W1 — trigger bar excluded).
        self._agg.on_1s_bar(int(tsi), o, h, l, c, v)
        self._update_session(int(tse), h, l, c, v)   # absorb this bar AFTER the snapshot
        ts = int(tsi)
        s1 = self._reg.get("1m"); reg1 = s1.regime if s1 else 0
        if self._pending:
            for cp in self._pending:
                cp["path"].append((ts, o, h, l, c, reg1))
                self._eval(cp, exit_px=o, exit_ts=ts)
            self._pending = []
        if self._flip and self._cps:
            keep = []
            for cp in self._cps:
                if cp["direction"] == self._prevdir:
                    cp["path"].append((ts, o, h, l, c, -cp["direction"]))
                    self._pending.append(cp)
                else:
                    keep.append(cp)
            self._cps = keep
        for cp in self._cps:
            cp["path"].append((ts, o, h, l, c, reg1))

    def _eval(self, cp, exit_px, exit_ts):
        path = cp["path"]
        if not path:
            return
        d = cp["direction"]; cts = cp["bar_ts"]; atr = cp["atr"]
        if atr != atr or atr <= 0:
            atr = 1.0
        cut = cts + NS
        nxt = [b for b in path if cts < b[0] <= cts + 60 * NS]
        base = (nxt[1][1] if len(nxt) > 1 else nxt[0][1]) if nxt else cp["checkpoint_px"]
        flip_ts = None
        for b in path:
            if b[0] > cut and (b[5] == -d or b[5] == 0):
                flip_ts = b[0]; break
        bars_to_flip = int((flip_ts - cts) / (60 * NS)) if flip_ts else int((path[-1][0] - cts) / (60 * NS))
        rec = {"regime_id": np.int64(cp["regime_id"]), "bar_ts": np.int64(cp["bar_ts"]),
               "bar_index_in_regime": np.int8(cp["bar_index"]), "direction": np.int8(d),
               "atr_norm": np.float32(atr), "next_1s_open": np.float32(base),
               "bars_to_regime_flip": np.int16(bars_to_flip)}
        for pt_m, sl_m, name in BRACKETS:
            self._race(rec, path, d, base, atr, cut, cts, pt_m, sl_m, name, None)
            for hb in HORIZONS.get(name, ()):
                self._race(rec, path, d, base, atr, cut, cts, pt_m, sl_m, f"{name}_{hb}b", hb)
        self.labels.append(rec)

    def _race(self, rec, path, d, base, atr, cut, cts, pt_m, sl_m, name, max_bars):
        pt = base + d * pt_m * atr; sl = base - d * sl_m * atr
        cap = (cts + max_bars * 60 * NS) if max_bars else None
        ex_px = ex_ts = reason = None
        for ts, o, h, l, c, r in path:
            if ts <= cut:
                continue
            if cap and ts > cap:
                ex_px, ex_ts, reason = o, ts, "timeout"; break
            if r == -d or r == 0:
                ex_px, ex_ts, reason = o, ts, "regime_flip"; break
            if d == 1:
                if l <= sl:
                    ex_px, ex_ts, reason = sl, ts, "SL"; break
                if h >= pt:
                    ex_px, ex_ts, reason = pt, ts, "PT"; break
            else:
                if h >= sl:
                    ex_px, ex_ts, reason = sl, ts, "SL"; break
                if l <= pt:
                    ex_px, ex_ts, reason = pt, ts, "PT"; break
        if ex_px is None:
            vt = [b for b in path if b[0] > cut]
            ex_px = vt[-1][4] if vt else path[-1][4]; ex_ts = vt[-1][0] if vt else path[-1][0]
            reason = "timeout"
        pnl = (ex_px - base) * d * MULT
        bars = (ex_ts - (cut - NS)) / (60 * NS)
        rec[f"{name}_pt_hit"] = np.int8(int(reason == "PT"))
        rec[f"{name}_reason"] = np.int8({"PT": 1, "SL": 2, "regime_flip": 3, "timeout": 4}[reason])
        rec[f"{name}_gross_pnl"] = np.float32(pnl)
        rec[f"{name}_bars"] = np.float32(bars)

    def finalize(self):
        for cp in self._pending + self._cps:
            if cp["path"]:
                self._eval(cp, cp["path"][-1][4], cp["path"][-1][0])
        self._pending = []; self._cps = []


def run_year(year, lead_in_days=6):
    t0 = time.time()
    ls = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=lead_in_days)
    le = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    print(f"Year {year}: loading")
    cat = ParquetDataCatalog(CATALOG)
    bars = cat.bars(bar_types=[BAR_TYPE], start=ls, end=le)
    print(f"  {len(bars):,} bars ({time.time()-t0:.0f}s)")
    if not bars:
        return
    o = np.fromiter((float(b.open) for b in bars), np.float64, len(bars))
    h = np.fromiter((float(b.high) for b in bars), np.float64, len(bars))
    l = np.fromiter((float(b.low) for b in bars), np.float64, len(bars))
    c = np.fromiter((float(b.close) for b in bars), np.float64, len(bars))
    v = np.fromiter((float(b.volume) for b in bars), np.float64, len(bars))
    tse = np.fromiter((int(b.ts_event) for b in bars), np.int64, len(bars))
    tsi = np.fromiter((int(b.ts_init) for b in bars), np.int64, len(bars))
    del bars
    rep = DNAReplay(year)
    t0 = time.time()
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tse[i], tsi[i])
    rep.finalize()
    print(f"  replay {time.time()-t0:.0f}s; regimes={len(rep.dna):,} label-bars={len(rep.labels):,}")
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    OUT.mkdir(parents=True, exist_ok=True)
    dna = pd.DataFrame(rep.dna)
    dna = dna[(dna.regime_start_ts >= yr0) & (dna.regime_start_ts <= yr1)]
    dna.to_parquet(OUT / f"regime_dna_{year}.parquet", index=False)
    lab = pd.DataFrame(rep.labels)
    lab = lab[(lab.bar_ts >= yr0) & (lab.bar_ts <= yr1)]
    # Drop degenerate races with no post-cut 1s path (exit resolves in 0 elapsed
    # bars at a data-segment boundary). These carry no tradeable information and
    # otherwise trip the strict `bars > 0` data-audit invariant.
    lab = lab[lab["pt100_sl050_bars"] > 0]
    lab.to_parquet(OUT / f"dna_race_labels_{year}.parquet", index=False)
    print(f"  saved dna={len(dna):,} labels={len(lab):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",")]
    for y in years:
        run_year(y)
    for stem in ("regime_dna", "dna_race_labels"):
        parts = [pd.read_parquet(OUT / f"{stem}_{y}.parquet") for y in years
                 if (OUT / f"{stem}_{y}.parquet").exists()]
        if parts:
            pd.concat(parts, ignore_index=True).to_parquet(OUT / f"{stem}.parquet", index=False)
            print(f"Combined {stem}.parquet")


if __name__ == "__main__":
    main()

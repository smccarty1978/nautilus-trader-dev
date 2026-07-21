"""Collect 1s post-flip paths for Bar-3 survivors (OOS 2025-26).

The MFE-conversion test (arm → BE/trail/PT) is a TRIGGER-BASED EXIT study. Per
methodology memory (level_momentum_be_arming_timing_artifact, be_simulation_path_
checkpoint_inflation) 1m-bar arm/trail detection inflates and SIGN-FLIPS the result —
arming on 1m bars implicitly requires a trade to hold +X ATR for ~60s, silently
filtering reversers, while at 1s every intrabar poke arms then BE-stops at zero. So
the conversion grid MUST run on 1s bars. This script persists the 1s post-flip path.

Reuses early_health_filter.CapsuleReplay UNCHANGED for flip detection + regime_id
assignment (year*100000+ridx), so regime_id JOINS 1:1 to early_health_capsule.parquet.
We only ADD a 1s-bar capture in on_1s. Path stored only for n_post>=4 (survivors that
reach a Bar-4 entry); capped at MAXSEC seconds from flip-bar close.

    python studies/regime_dna_knn/build_survivor_1s_paths.py
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
NS = 1_000_000_000
MAXSEC = 1800            # cap 1s path at 30 min from flip close (covers Bar15 + p90 flips)
OOS_YEARS = [2025, 2026]


class PathReplay(E.CapsuleReplay):
    """CapsuleReplay + per-regime 1s post-flip path capture. Flip detection and
    regime_id assignment are inherited UNCHANGED (IDs match the 1m capsule)."""

    def on_1s(self, o, h, l, c, v, tsi):
        # Feed aggregator FIRST (may fire on_bucket_closed → finalize old cap / create
        # new cap). Then attach this 1s bar to whatever capsule is now active. The first
        # 1s after a flip-bar close is bar-1 second 0 of the new regime — correct.
        self._agg.on_1s_bar(int(tsi), o, h, l, c, v)
        cap = self._cap
        if cap is not None:
            buf = cap.get("_p1s")
            if buf is None:
                buf = cap["_p1s"] = []
            if len(buf) < MAXSEC:
                buf.append((int(tsi), float(h), float(l), float(c)))

    def _finalize(self):
        cap = self._cap
        if cap is not None:
            buf = cap.pop("_p1s", [])
            n_post = len(cap["post"])
            if n_post >= 4 and buf:
                t0 = int(cap["regime_start_ts"])
                # store ns offset from flip-bar close, h/l/c; truncation flag
                cap["p1s_t"] = [b[0] - t0 for b in buf]
                cap["p1s_h"] = [b[1] for b in buf]
                cap["p1s_l"] = [b[2] for b in buf]
                cap["p1s_c"] = [b[3] for b in buf]
                cap["p1s_trunc"] = bool(len(buf) >= MAXSEC)
            else:
                cap["p1s_t"] = []
                cap["p1s_h"] = []
                cap["p1s_l"] = []
                cap["p1s_c"] = []
                cap["p1s_trunc"] = False
        super()._finalize()


def run_year(year, lead_in_days=6):
    t0 = time.time()
    ls = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=lead_in_days)
    le = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    cat = ParquetDataCatalog(E.CATALOG)
    bars = cat.bars(bar_types=[E.BAR_TYPE], start=ls, end=le)
    print(f"Year {year}: {len(bars):,} bars ({time.time()-t0:.0f}s)")
    if not bars:
        return
    o = np.fromiter((float(b.open) for b in bars), np.float64, len(bars))
    h = np.fromiter((float(b.high) for b in bars), np.float64, len(bars))
    l = np.fromiter((float(b.low) for b in bars), np.float64, len(bars))
    c = np.fromiter((float(b.close) for b in bars), np.float64, len(bars))
    v = np.fromiter((float(b.volume) for b in bars), np.float64, len(bars))
    tsi = np.fromiter((int(b.ts_init) for b in bars), np.int64, len(bars))
    del bars
    rep = PathReplay(year)
    t0 = time.time()
    for i in range(len(c)):
        rep.on_1s(o[i], h[i], l[i], c[i], v[i], tsi[i])
    rep.finalize()
    df = pd.DataFrame(rep.records)
    yr0 = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    yr1 = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC").value
    df = df[(df.regime_start_ts >= yr0) & (df.regime_start_ts <= yr1)]
    # keep only survivors with a stored path; drop the bulky 1m fields we already have
    df = df[df.n_post >= 4].copy()
    keep = ["regime_id", "regime_start_ts", "year", "direction", "atr_base", "flip_o",
            "n_post", "p1s_t", "p1s_h", "p1s_l", "p1s_c", "p1s_trunc"]
    df = df[keep]
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"survivor_1s_paths_{year}.parquet", index=False)
    npath = (df.p1s_t.str.len() > 0).sum()
    trunc = df.p1s_trunc.sum()
    print(f"  {year}: {len(df):,} survivors, {npath:,} with 1s path, {trunc:,} truncated "
          f"({time.time()-t0:.0f}s replay)")


def main():
    for y in OOS_YEARS:
        run_year(y)
    parts = [pd.read_parquet(OUT / f"survivor_1s_paths_{y}.parquet") for y in OOS_YEARS
             if (OUT / f"survivor_1s_paths_{y}.parquet").exists()]
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(OUT / "survivor_1s_paths.parquet", index=False)
    print(f"Combined: {len(df):,} survivor 1s paths "
          f"({df.p1s_trunc.sum():,} truncated at {MAXSEC}s)")


if __name__ == "__main__":
    main()

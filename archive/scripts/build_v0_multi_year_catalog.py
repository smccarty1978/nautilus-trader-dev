"""Build a multi-year NQ.v.0 catalog covering 2020-2026 YTD.

This catalog REPLACES the legacy NQ_2020_2025 (which was on NQ.c.0,
calendar-continuous) so that all downstream studies use volume-continuous
data — eliminating the contract-mismatch issue around quarterly rolls.

Output: data/catalog/NQ_v0_2020_2026/

Resample uses pandas default `closed='left'` semantics (label='left'
means bin [T, T+rule) labeled at T) — which the catalog audit confirmed
is causal when source index is ts_event (Databento OPEN convention).

Then ts_init_delta shifts to CLOSE time per NT convention.
"""
from __future__ import annotations
import os, sys, time, gc
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.data import BarType

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
RAW_2026 = "data/raw/NQ_v0_1s_2026_ytd.parquet"

OUT_DIR = Path("data/catalog/NQ_v0_2020_2026")


def create_nq_v0():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    # Span the whole range so V_A trades 2020-2026 are within
    # activation/expiration window
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-01-01", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def aggregate_1m(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1s -> 1m using `label='left'` (default closed='left').
    Window [T, T+60s) labeled at T = OPEN time.
    """
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    return df[list(agg)].resample("1min", label="left").agg(agg).dropna()


def main():
    t0 = time.time()
    print("=" * 78)
    print(f"BUILDING MULTI-YEAR NQ.v.0 CATALOG -> {OUT_DIR}")
    print("=" * 78)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(OUT_DIR))
    nq = create_nq_v0()
    catalog.write_data([nq])
    print(f"Instrument: {nq.id}  activation={pd.Timestamp(nq.activation_ns, unit='ns', tz='UTC')}  expiration={pd.Timestamp(nq.expiration_ns, unit='ns', tz='UTC')}")

    # Load 1s data per year and concatenate
    print("\nLoading 1s parquet files...")
    parts = []
    for yr in YEARS:
        p = f"data/raw/NQ_v0_1s_{yr}.parquet"
        df = pd.read_parquet(p, columns=["open","high","low","close","volume"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        print(f"  {yr}: {len(df):,} rows")
        parts.append(df)
    if Path(RAW_2026).exists():
        df = pd.read_parquet(RAW_2026, columns=["open","high","low","close","volume"])
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        print(f"  2026_ytd: {len(df):,} rows")
        parts.append(df)

    df_full = pd.concat(parts).sort_index()
    df_full = df_full[~df_full.index.duplicated(keep="first")]
    print(f"  combined: {len(df_full):,} 1s rows  range "
          f"{df_full.index.min()} -> {df_full.index.max()}")
    del parts; gc.collect()

    # 1s bars
    print("\nWrangling 1s bars...")
    bt_1s = BarType.from_str(f"{nq.id}-1-SECOND-LAST-EXTERNAL")
    w_1s = BarDataWrangler(bar_type=bt_1s, instrument=nq)
    bars_1s = w_1s.process(df_full, ts_init_delta=1_000_000_000)
    print(f"  {len(bars_1s):,} bars")
    catalog.write_data(bars_1s)
    del bars_1s; gc.collect()

    # 1m bars (causal resample)
    print("\nResampling to 1m (label='left' / closed='left')...")
    df_1m = aggregate_1m(df_full)
    print(f"  {len(df_1m):,} 1m bars")
    bt_1m = BarType.from_str(f"{nq.id}-1-MINUTE-LAST-EXTERNAL")
    w_1m = BarDataWrangler(bar_type=bt_1m, instrument=nq)
    bars_1m = w_1m.process(df_1m, ts_init_delta=60_000_000_000)
    print(f"  wrangled to {len(bars_1m):,} 1m bars")
    catalog.write_data(bars_1m)
    del bars_1m, df_1m; gc.collect()

    # 5m bars too (V_A uses 5m for MTF)
    print("\nResampling to 5m...")
    df_5m = df_full[["open","high","low","close","volume"]].resample(
        "5min", label="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    print(f"  {len(df_5m):,} 5m bars")
    bt_5m = BarType.from_str(f"{nq.id}-5-MINUTE-LAST-EXTERNAL")
    w_5m = BarDataWrangler(bar_type=bt_5m, instrument=nq)
    bars_5m = w_5m.process(df_5m, ts_init_delta=300_000_000_000)
    catalog.write_data(bars_5m)
    print(f"  wrote {len(bars_5m):,} 5m bars")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

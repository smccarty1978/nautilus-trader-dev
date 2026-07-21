"""Compare catalog 1s bars vs raw tick file day-by-day for
September 2025 (contains the Sep 18 NQ quarterly roll day).

Goal: figure out exactly what differs between:
  - Catalog: NQ.XCME-1-SECOND-LAST-EXTERNAL (used by strategy)
  - Raw ticks: NQ_trades_20250201_20250930.parquet (used for fills)

Per day, compares:
  1. Catalog bar prices at noon CT
  2. Raw tick prices at noon CT
  3. Difference

Also checks the symbol/contract identifiers in each source.

Output:
  studies/v_a_exit_recon/results/DATA_SOURCE_AUDIT.md
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
OUT = Path("studies/v_a_exit_recon/results")


def main():
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    cat = ParquetDataCatalog("data/catalog/NQ_2020_2025")

    print("=== Tick file metadata ===")
    tick_path = "data/raw/NQ_trades_20250201_20250930.parquet"
    pf = pq.ParquetFile(tick_path)
    schema = pf.schema_arrow
    md = pf.metadata
    print(f"  File: {tick_path}")
    print(f"  Schema cols: {[f.name for f in schema]}")
    print(f"  Total rows: {md.num_rows:,}")
    # Sample symbols
    samp = pq.read_table(
        tick_path, columns=["symbol"],
        filters=[("ts_event", ">=",
                       pd.Timestamp("2025-09-15", tz="UTC")),
                   ("ts_event", "<",
                       pd.Timestamp("2025-09-22", tz="UTC"))]
    ).to_pandas()
    sym_counts = samp["symbol"].value_counts().head(10)
    print(f"  Symbol distribution Sep 15-22 in raw ticks: ")
    for s, c in sym_counts.items():
        print(f"    {s}: {c:,}")
    print()

    print("=== Catalog metadata ===")
    inst = cat.instruments()
    print(f"  Instruments in catalog: "
          f"{[i.id.value for i in inst]}")
    print(f"  (bar_types() method not exposed; using known type "
          "NQ.XCME-1-SECOND-LAST-EXTERNAL)")
    # Read a small slice of the underlying parquet directly
    bar_file = next(
        Path("data/catalog/NQ_2020_2025/data/bar").rglob(
            "*.parquet"))
    print(f"  Sample bar parquet: {bar_file}")
    bar_meta = pq.ParquetFile(bar_file).metadata
    bar_schema = pq.ParquetFile(bar_file).schema_arrow
    print(f"  Bar schema cols: {[f.name for f in bar_schema]}")
    print(f"  Bar rows in this file: {bar_meta.num_rows:,}")
    print()

    print("=== Per-day price comparison: Sep 2025 ===")
    print()
    print(f"{'Date':<12} | {'CT noon catalog OHLC':<32} | "
          f"{'Raw tick price near 12:00 CT':<35} | "
          f"{'Catalog − Tick':>15}")
    print("-" * 100)
    rows = []
    for day in range(1, 26):
        date = pd.Timestamp(f"2025-09-{day:02d}", tz="UTC")
        if date.weekday() >= 5: continue   # weekend
        # 12:00 CT = 17:00 UTC  (CDT) or 18:00 UTC (CST after Nov)
        # Sep is CDT so 12:00 CT = 17:00 UTC
        noon_utc = date + pd.Timedelta(hours=17)
        # Catalog bar at noon
        cat_bars = cat.bars(
            bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
            start=noon_utc,
            end=noon_utc + pd.Timedelta(seconds=2),
        )
        if not cat_bars: continue
        b = cat_bars[0]
        cat_open = float(b.open)
        cat_high = float(b.high)
        cat_low = float(b.low)
        cat_close = float(b.close)
        # Raw ticks in same 1-second window
        tick_tbl = pq.read_table(
            tick_path, columns=["price", "symbol", "action"],
            filters=[
                ("ts_event", ">=", noon_utc),
                ("ts_event", "<=", noon_utc
                    + pd.Timedelta(seconds=2)),
                ("action", "=", "T"),
            ],
        ).to_pandas()
        if not len(tick_tbl):
            tick_str = "(no ticks in 2s window)"
            tick_min = tick_max = None
            sym_str = ""
            diff_str = "—"
        else:
            tick_min = tick_tbl["price"].min()
            tick_max = tick_tbl["price"].max()
            tick_str = f"{tick_min:.2f}-{tick_max:.2f} (n={len(tick_tbl)})"
            sym_set = set(tick_tbl["symbol"].unique())
            sym_str = ",".join(sorted(sym_set))
            diff = cat_open - (tick_min + tick_max) / 2
            diff_str = f"{diff:+8.2f}"
        cat_str = (f"O={cat_open:.2f} H={cat_high:.2f} "
                     f"L={cat_low:.2f} C={cat_close:.2f}")
        print(f"{str(date.date()):<12} | {cat_str:<32} | "
              f"{tick_str + ' [' + sym_str + ']':<35} | "
              f"{diff_str:>15}")
        rows.append({
            "date": str(date.date()),
            "cat_open": cat_open, "cat_high": cat_high,
            "cat_low": cat_low, "cat_close": cat_close,
            "tick_min": tick_min, "tick_max": tick_max,
            "tick_n": len(tick_tbl),
            "tick_symbols": sym_str,
            "diff_cat_minus_tick_mid": (
                cat_open - (tick_min + tick_max) / 2
                if tick_min is not None else None),
        })
    df = pd.DataFrame(rows)
    df.to_parquet(
        OUT / "data_source_audit_sep2025.parquet", index=False)

    # ---- Per-trade comparison ----
    print()
    print("=== Per-trade entry price comparison: Sep 2025 trades ===")
    print()
    # Use the unguarded HH/LL run
    from pathlib import Path as PP
    TICK_NT = PP("collectors/collector_v2/results/tick_nt")
    runs = sorted(TICK_NT.glob("hhll_FebSep_audit*"))
    if not runs:
        print("  No tick-NT run to inspect")
        return
    trades = pd.read_parquet(runs[-1] / "trades.parquet")
    sep_start = pd.Timestamp("2025-09-01", tz="UTC").value
    sep_end = pd.Timestamp("2025-10-01", tz="UTC").value
    sep = trades[(trades["entry_ts"] >= sep_start)
                  & (trades["entry_ts"] < sep_end)
                  & (trades["session"] == "RTH")].copy()
    sep["entry_ct"] = pd.to_datetime(
        sep["entry_ts"], unit="ns",
        utc=True).dt.tz_convert(CT)
    sep["entry_date"] = sep["entry_ct"].dt.date
    print(f"  Sep 2025 RTH trades: {len(sep):,}")

    # For each trade, look up the catalog bar OPEN at entry_ts
    # and compare to fill_price.
    diffs = []
    for _, t in sep.iterrows():
        entry_ts = pd.Timestamp(int(t["entry_ts"]),
                                       tz="UTC")
        bars = cat.bars(
            bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
            start=entry_ts,
            end=entry_ts + pd.Timedelta(seconds=2),
        )
        if not bars: continue
        b = bars[0]
        cat_open = float(b.open)
        fill_px = float(t["fill_price"])
        diffs.append({
            "date": t["entry_date"],
            "fill_price": fill_px,
            "catalog_open": cat_open,
            "diff_cat_minus_fill": cat_open - fill_px,
            "direction": int(t["direction"]),
        })
    diff_df = pd.DataFrame(diffs)
    diff_df.to_parquet(
        OUT / "per_trade_diff_sep2025.parquet", index=False)
    print(f"  Computed for {len(diff_df):,} trades")
    print()
    print(f"{'Date':<12} | n | mean diff | median | min | max | "
          f"sample fill | sample bar |")
    print("-" * 100)
    for date, sub in diff_df.groupby("date"):
        d = sub["diff_cat_minus_fill"]
        print(f"{str(date):<12} | {len(sub):>2} | "
              f"{d.mean():>+9.2f} | {d.median():>+7.2f} | "
              f"{d.min():>+7.2f} | {d.max():>+7.2f} | "
              f"{sub['fill_price'].iloc[0]:>10.2f} | "
              f"{sub['catalog_open'].iloc[0]:>10.2f}")
    print()
    print(f"  Overall mean diff Sep 2025: "
          f"{diff_df['diff_cat_minus_fill'].mean():+.2f}")
    print(f"  Overall median diff: "
          f"{diff_df['diff_cat_minus_fill'].median():+.2f}")

    # ---- Markdown report ----
    lines = []
    lines.append("# Data Source Audit — Catalog Bars vs Raw Tick "
                 "File")
    lines.append("")
    lines.append("Side-by-side comparison of catalog "
                 "`NQ.XCME-1-SECOND-LAST-EXTERNAL` bars vs raw "
                 "`NQ_trades_20250201_20250930.parquet` ticks "
                 "across September 2025 (contains Sep 18 NQ "
                 "quarterly roll day).")
    lines.append("")
    lines.append("## Tick file metadata")
    lines.append("")
    lines.append("- Schema: ts_event, price, size, side, action, "
                  "symbol, sequence, ...")
    lines.append("- Symbol distribution Sep 15-22:")
    for s, c in sym_counts.items():
        lines.append(f"  - `{s}`: {c:,} rows")
    lines.append("")
    lines.append("## Catalog metadata")
    lines.append("")
    lines.append(f"- Instruments: {[i.id.value for i in inst]}")
    lines.append(f"- Bar type: NQ.XCME-1-SECOND-LAST-EXTERNAL")
    lines.append(f"- Sample bar schema cols: "
                  f"{[f.name for f in bar_schema]}")
    lines.append("")
    lines.append("## Daily noon-CT price comparison")
    lines.append("")
    lines.append("| Date | Catalog OHLC | Raw tick range "
                 "(symbol) | Diff (cat − tick mid) |")
    lines.append("|---|---|---|--:|")
    for r in rows:
        cat_str = (f"O={r['cat_open']:.2f} H={r['cat_high']:.2f} "
                     f"L={r['cat_low']:.2f} C={r['cat_close']:.2f}")
        if r["tick_min"] is None:
            tick_str = "(no ticks)"
            diff_str = "—"
        else:
            tick_str = (f"{r['tick_min']:.2f}-{r['tick_max']:.2f} "
                          f"[{r['tick_symbols']}]")
            diff_str = f"{r['diff_cat_minus_tick_mid']:+.2f}"
        lines.append(f"| {r['date']} | {cat_str} | {tick_str} | "
                      f"{diff_str} |")
    lines.append("")

    lines.append("## Per-trade fill_price vs catalog bar OPEN — "
                 "Sep 2025 RTH")
    lines.append("")
    lines.append("| Date | n trades | Mean diff (cat − fill) | "
                 "Median | Min | Max | Sample fill | "
                 "Sample bar OPEN |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for date, sub in diff_df.groupby("date"):
        d = sub["diff_cat_minus_fill"]
        lines.append(
            f"| {date} | {len(sub)} | {d.mean():+.2f} | "
            f"{d.median():+.2f} | {d.min():+.2f} | "
            f"{d.max():+.2f} | "
            f"{sub['fill_price'].iloc[0]:.2f} | "
            f"{sub['catalog_open'].iloc[0]:.2f} |")
    lines.append("")
    lines.append(f"**Overall mean diff**: "
                  f"{diff_df['diff_cat_minus_fill'].mean():+.2f} pts")
    lines.append(f"**Overall median diff**: "
                  f"{diff_df['diff_cat_minus_fill'].median():+.2f} pts")
    lines.append("")

    out_p = OUT / "DATA_SOURCE_AUDIT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()

"""Smoke test: verify the 30s delay removal works.

Run V_A on a single week (Jan 8-15 2024). Inspect entry_ts vs
flip_bar_event timing. Expected:
  - OLD: entry_ts - flip_bar_event ≈ 150s (bar+1 close + 30s)
  - NEW: entry_ts - flip_bar_event ≈ 120s (bar+1 close + 0s, then 1s
         bar latency for fill)

Output: prints first 10 trades with their entry timing offsets.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from collectors.collector_v2.run_smoke import run_one


def main():
    out_dir = Path(
        "collectors/collector_v2/results/smoke_no_30s_delay")
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp("2024-01-05", tz="UTC")
    load_end = pd.Timestamp("2024-01-15 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_v0_2020_2026")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")

    print(f"\nRunning V_A Mode 2 (no 30s delay)...", flush=True)
    t0 = time.time()
    elapsed, diag = run_one("trading", bars_1s, bars_1m, out_dir,
                                require_5m_aligned=False)
    print(f"  Done in {elapsed:.0f}s")
    print(f"  Diag: {diag}")

    trades_p = out_dir / "trades.parquet"
    snaps_p = out_dir / "snapshots.parquet"
    if not trades_p.exists() or not snaps_p.exists():
        print("  No outputs"); return

    trades = pd.read_parquet(trades_p)
    snaps = pd.read_parquet(snaps_p)
    rf = snaps[snaps["kind"] == "regime_flip"][
        ["bar_ts_event", "decision_ts", "direction"]].copy()
    rf["expected_b1_bts"] = rf["bar_ts_event"] + 60_000_000_000
    b1 = snaps[snaps["kind"] == "bar1_check"][
        ["bar_ts_event", "decision_ts", "direction", "confirmed"]].copy()
    b1 = b1.rename(columns={"bar_ts_event": "expected_b1_bts",
                                "decision_ts": "b1_decision_ts"})
    rf_b1 = rf.merge(b1, on=["expected_b1_bts", "direction"],
                          how="inner")
    rf_b1 = rf_b1[rf_b1["confirmed"]].copy()

    print(f"\n  Trades: {len(trades):,}")
    print(f"  Confirmed bar1 checks: {len(rf_b1):,}")

    # Match trades to confirmed bar1_check by direction + bar1_decision_ts
    trades_match = trades.merge(
        rf_b1[["bar_ts_event", "b1_decision_ts", "direction"]],
        left_on=["decision_ts", "direction"],
        right_on=["b1_decision_ts", "direction"],
        how="left")
    trades_match["entry_offset_s"] = (
        (trades_match["entry_ts"] - trades_match["bar_ts_event"]) / 1e9)
    trades_match["bar1_close_offset_s"] = (
        (trades_match["entry_ts"] - trades_match["b1_decision_ts"]) / 1e9)

    print(f"\n  First 10 trades with entry timing:")
    print(f"  {'flip_event':>20}  {'entry_ts':>20}  "
          f"{'offset_from_flip(s)':>20}  {'offset_from_b1_decision(s)':>26}")
    for _, r in trades_match.head(10).iterrows():
        flip_dt = pd.Timestamp(int(r["bar_ts_event"]), unit="ns")
        entry_dt = pd.Timestamp(int(r["entry_ts"]), unit="ns")
        print(f"  {str(flip_dt):>20}  {str(entry_dt):>20}  "
              f"{r['entry_offset_s']:>+18.1f}s  "
              f"{r['bar1_close_offset_s']:>+22.1f}s")

    print(f"\n  STATS:")
    off_flip = trades_match["entry_offset_s"]
    off_b1 = trades_match["bar1_close_offset_s"]
    print(f"  Median entry_ts - flip_bar_event: {off_flip.median():.1f}s "
          f"(was 150s with 30s delay)")
    print(f"  Median entry_ts - b1_decision_ts: {off_b1.median():.1f}s "
          f"(was 30s with 30s delay)")
    print(f"  P25/P75: flip={off_flip.quantile(0.25):.1f}/"
          f"{off_flip.quantile(0.75):.1f}s  "
          f"b1={off_b1.quantile(0.25):.1f}/{off_b1.quantile(0.75):.1f}s")

    if off_flip.median() < 130:
        print(f"\n  ✓ PASS: 30s delay successfully removed "
              f"(median offset < 130s)")
    else:
        print(f"\n  ✗ FAIL: median offset {off_flip.median()}s suggests "
              f"delay still present")

    # PnL summary
    if len(trades):
        wr = (trades["net_pnl"] > 0).mean() * 100
        total = trades["net_pnl"].sum()
        print(f"\n  Smoke PnL: total ${total:+,.0f}, "
              f"WR {wr:.1f}%, n={len(trades):,}")


if __name__ == "__main__":
    main()

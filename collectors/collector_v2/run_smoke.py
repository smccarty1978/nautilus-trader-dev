"""Run Collector V2 smoke parity test — Jan 8-15, 2024.

Runs the same week TWICE through identical strategy code:
  - Mode 1 (research): emits snapshots, no trades
  - Mode 2 (trading):  emits snapshots AT THE SAME MOMENTS,
                        plus actually trades V_A

Then compares row-by-row:
  - bar1_check rows: hhll_ok, momentum_ok, confirmed must match
  - regime_flip rows: regime + close_ts per TF must match
  - All last_<tf>_close_ts <= decision_ts (provenance check, both)

If anything fails, prints diff and exits non-zero.
"""

from __future__ import annotations
import os, sys, time, json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from collectors.collector_v2.strategy import (
    CollectorV2Strategy, CollectorV2Config,
)


def create_nq():
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp(
        "2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp(
        "2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


def run_one(mode: str, bars_1s, bars_1m, out_dir: Path,
              require_5m_aligned: bool = False):
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=f"V2-{mode[:4].upper()}-001",
        logging=LoggingConfig(log_level="WARNING",
                                log_directory=str(out_dir / "logs")),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True)
    engine.add_instrument(create_nq())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)
    cfg = CollectorV2Config(
        instrument_id="NQ.XCME",
        bar_type_1m="NQ.XCME-1-MINUTE-LAST-EXTERNAL",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        mode=mode,
        rth_only=True,
        position_size=1,
        require_5m_aligned=require_5m_aligned,
        output_dir=str(out_dir),
    )
    strat = CollectorV2Strategy(cfg)
    engine.add_strategy(strat)
    t0 = time.time()
    engine.run()
    elapsed = time.time() - t0
    engine.dispose()
    return elapsed, strat._diag


def compare_snapshots(df1: pd.DataFrame, df2: pd.DataFrame) -> dict:
    """Compare two snapshot DataFrames row-by-row.

    Joins on (decision_ts, kind). For each matched pair, compares
    the ALL feature columns and per-TF close_ts. Reports first 10
    mismatches per column.
    """
    if len(df1) == 0 or len(df2) == 0:
        return {"ok": False, "reason": "one side empty",
                "n1": len(df1), "n2": len(df2)}
    # Sort by decision_ts, kind, event_id
    df1 = df1.sort_values(
        ["decision_ts", "kind", "bar_ts_event"]).reset_index(
        drop=True)
    df2 = df2.sort_values(
        ["decision_ts", "kind", "bar_ts_event"]).reset_index(
        drop=True)
    # Join on (decision_ts, kind, bar_ts_event)
    join_cols = ["decision_ts", "kind", "bar_ts_event"]
    merged = df1.merge(df2, on=join_cols, how="outer",
                          indicator=True, suffixes=("_1", "_2"))
    n_both = int((merged["_merge"] == "both").sum())
    n_only_1 = int((merged["_merge"] == "left_only").sum())
    n_only_2 = int((merged["_merge"] == "right_only").sum())
    matched = merged[merged["_merge"] == "both"].copy()

    # Compare columns
    diff_cols = [c for c in df1.columns if c not in join_cols
                  and c != "became_trade"  # mode 2 may set this
                  and c != "event_id"      # event_id is per-run
                  and (c + "_1") in matched.columns]
    mismatches: dict = {}
    for c in diff_cols:
        a = matched[c + "_1"]
        b = matched[c + "_2"]
        if a.dtype == object or b.dtype == object:
            ne = (a != b).sum()
        else:
            # Tolerance for floats
            try:
                ne = int(((a - b).abs() > 1e-9).sum())
            except Exception:
                ne = int((a != b).sum())
        if ne > 0:
            sample = matched[(a != b) | (a.isna() != b.isna())][
                join_cols + [c + "_1", c + "_2"]].head(5)
            mismatches[c] = {
                "n_mismatch": int(ne),
                "sample": sample.to_dict(orient="records"),
            }
    return {
        "ok": (len(mismatches) == 0
                 and n_only_1 == 0 and n_only_2 == 0),
        "n_matched": n_both, "n_only_mode1": n_only_1,
        "n_only_mode2": n_only_2,
        "n_compared_cols": len(diff_cols),
        "mismatches": mismatches,
    }


def provenance_check(df: pd.DataFrame, label: str) -> dict:
    """Verify last_<tf>_close_ts <= decision_ts for every row.

    Returns dict with violation counts per TF. Violations should
    be ZERO.
    """
    out = {"label": label, "n_rows": len(df), "violations": {}}
    if len(df) == 0:
        return out
    for tf in ["30s", "1m", "3m", "5m"]:
        col = f"last_{tf}_close_ts"
        if col not in df.columns:
            continue
        violations = (df[col] > df["decision_ts"]).sum()
        out["violations"][tf] = int(violations)
    return out


def main():
    out_root = Path("collectors/collector_v2/results/smoke_jan2024")
    out_root.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp("2024-01-05", tz="UTC")  # 3-day warmup
    load_end = pd.Timestamp("2024-01-15 23:59:59", tz="UTC")
    print(f"Loading {load_start} -> {load_end}...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    bars_1m = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=load_start, end=load_end)
    print(f"  {len(bars_1s):,} 1s + {len(bars_1m):,} 1m bars "
           f"({time.time()-t0:.0f}s)")

    # Mode 1 — research
    print("\n[Mode 1] Research logging ...", flush=True)
    out_m1 = out_root / "mode1_research"
    elapsed_m1, diag_m1 = run_one("research", bars_1s, bars_1m,
                                       out_m1)
    print(f"  done in {elapsed_m1:.0f}s, diag={diag_m1}")

    # Mode 2 — trading
    print("\n[Mode 2] Trading ...", flush=True)
    out_m2 = out_root / "mode2_trading"
    elapsed_m2, diag_m2 = run_one("trading", bars_1s, bars_1m,
                                       out_m2)
    print(f"  done in {elapsed_m2:.0f}s, diag={diag_m2}")

    # Load outputs
    df_m1_snaps = (pd.read_parquet(out_m1 / "snapshots.parquet")
                       if (out_m1 / "snapshots.parquet").exists()
                       else pd.DataFrame())
    df_m2_snaps = (pd.read_parquet(out_m2 / "snapshots.parquet")
                       if (out_m2 / "snapshots.parquet").exists()
                       else pd.DataFrame())
    df_m2_trades = (pd.read_parquet(out_m2 / "trades.parquet")
                        if (out_m2 / "trades.parquet").exists()
                        else pd.DataFrame())

    print(f"\nMode 1 snapshots: {len(df_m1_snaps):,}")
    print(f"Mode 2 snapshots: {len(df_m2_snaps):,}")
    print(f"Mode 2 trades:    {len(df_m2_trades):,}")

    # Provenance checks
    print("\n=== PROVENANCE CHECK ===")
    pv1 = provenance_check(df_m1_snaps, "Mode 1")
    pv2 = provenance_check(df_m2_snaps, "Mode 2")
    for pv in [pv1, pv2]:
        print(f"  {pv['label']}: n={pv['n_rows']:,}, "
               f"violations={pv['violations']}")
        if any(v > 0 for v in pv["violations"].values()):
            print(f"  *** PROVENANCE VIOLATION in {pv['label']} ***")

    # Snapshot-by-snapshot parity
    print("\n=== SNAPSHOT PARITY (Mode 1 vs Mode 2) ===")
    parity = compare_snapshots(df_m1_snaps, df_m2_snaps)
    print(f"  Matched rows:    {parity.get('n_matched', 0):,}")
    print(f"  Only in Mode 1:  {parity.get('n_only_mode1', 0):,}")
    print(f"  Only in Mode 2:  {parity.get('n_only_mode2', 0):,}")
    print(f"  Cols compared:   "
           f"{parity.get('n_compared_cols', 0):,}")
    n_diff_cols = len(parity.get("mismatches", {}))
    print(f"  Mismatched cols: {n_diff_cols}")
    if n_diff_cols:
        for c, info in parity["mismatches"].items():
            print(f"    {c}: {info['n_mismatch']} mismatches")
            for s in info["sample"][:3]:
                print(f"      {s}")

    # Save report
    report = {
        "mode1_diag": {k: int(v) for k, v in diag_m1.items()},
        "mode2_diag": {k: int(v) for k, v in diag_m2.items()},
        "mode1_runtime_s": elapsed_m1,
        "mode2_runtime_s": elapsed_m2,
        "n_m1_snapshots": len(df_m1_snaps),
        "n_m2_snapshots": len(df_m2_snaps),
        "n_m2_trades": len(df_m2_trades),
        "provenance_mode1": pv1,
        "provenance_mode2": pv2,
        "parity": parity,
    }
    with open(out_root / "smoke_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport: {out_root / 'smoke_report.json'}")

    # Final pass/fail
    passed = (
        parity.get("ok", False)
        and all(v == 0 for v in pv1["violations"].values())
        and all(v == 0 for v in pv2["violations"].values())
    )
    print()
    if passed:
        print("✅ SMOKE PARITY PASSED")
        sys.exit(0)
    else:
        print("❌ SMOKE PARITY FAILED — see report")
        sys.exit(1)


if __name__ == "__main__":
    main()

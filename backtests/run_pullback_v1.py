"""NT BacktestEngine runner — PullbackV1Strategy (5s pullback on qualified 1m regimes).

Runs three depths (0.25 / 0.50 / 0.75 ATR) against OOS 2025 and 2026.
Reports per-year and pooled metrics: trade count, win rate, avg hold time,
avg MAE/MFE, expectancy, profit factor, max drawdown.

Usage:
    python backtests/run_pullback_v1.py

Data:   data/catalog/NQ_v0_2020_2026
hC map: collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from strategies.pullback_5s.strategy import PullbackV1Config, PullbackV1Strategy  # noqa

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
HC_MAP_PATH  = "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
OUT_DIR      = Path("backtests/results/pullback_v1")
DEPTHS       = [0.25, 0.50, 0.75]

# 7-day lead-in for indicator warmup (≥ 6-day capsule builder convention)
LEAD_IN = pd.Timedelta(days=7)
START   = pd.Timestamp("2025-01-01", tz="UTC")
END     = pd.Timestamp("2026-12-31 23:59:59", tz="UTC")


# ── Instrument ─────────────────────────────────────────────────────────────────

def create_nq() -> FuturesContract:
    t = TestInstrumentProvider.future(
        symbol="NQ", underlying="NQ", venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2026-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2020-01-01", tz="UTC").value
    d["multiplier"], d["price_increment"] = "20", "0.25"
    return FuturesContract.from_dict(d)


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {
            "n": 0, "win_rate": float("nan"), "expectancy": float("nan"),
            "profit_factor": float("nan"), "avg_hold_min": float("nan"),
            "avg_mfe_atr": float("nan"), "avg_mae_atr": float("nan"),
            "max_drawdown": float("nan"), "total_pnl": 0.0,
        }
    pnls   = [t["pnl"] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)

    cum = []
    running = 0.0
    for p in pnls:
        running += p
        cum.append(running)

    peak = 0.0
    max_dd = 0.0
    for cp in cum:
        if cp > peak:
            peak = cp
        dd = peak - cp
        if dd > max_dd:
            max_dd = dd

    return {
        "n":            n,
        "win_rate":     len(wins) / n,
        "expectancy":   sum(pnls) / n,
        "profit_factor": (
            sum(wins) / abs(sum(losses)) if losses else float("inf")
        ),
        "avg_hold_min": sum(t["hold_s"] for t in trades) / n / 60,
        "avg_mfe_atr":  sum(t["mfe_atr"] for t in trades) / n,
        "avg_mae_atr":  sum(t["mae_atr"] for t in trades) / n,
        "max_drawdown": max_dd,
        "total_pnl":    sum(pnls),
    }


def split_by_year(trades: list[dict]) -> dict[int, list[dict]]:
    by_year: dict[int, list[dict]] = {}
    for t in trades:
        yr = pd.Timestamp(t["entry_ts"], unit="ns", tz="UTC").year
        by_year.setdefault(yr, []).append(t)
    return by_year


def print_row(label: str, m: dict) -> None:
    if m["n"] == 0:
        print(f"  {label:<12}  n=0  (no trades)")
        return
    print(
        f"  {label:<12}  n={m['n']:>5}  wr={m['win_rate']:.1%}  "
        f"exp={m['expectancy']:>+7.1f}  pf={m['profit_factor']:.2f}  "
        f"hold={m['avg_hold_min']:.0f}m  "
        f"mfe={m['avg_mfe_atr']:.2f}A  mae={m['avg_mae_atr']:.2f}A  "
        f"maxdd=${m['max_drawdown']:.0f}  tot=${m['total_pnl']:.0f}"
    )


# ── Single backtest run ────────────────────────────────────────────────────────

def run_one(depth: float, bars_1s: list, nq: FuturesContract) -> list[dict]:
    """Run backtest for one depth; return trade log."""
    engine_cfg = BacktestEngineConfig(
        trader_id=f"PBV1-{depth:.2f}",
        logging=LoggingConfig(
            log_level="WARNING",
            log_level_file="WARNING",
            log_directory=str(OUT_DIR / "logs"),
        ),
    )
    engine = BacktestEngine(config=engine_cfg)
    engine.add_venue(
        venue=Venue("XCME"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
        bar_execution=True,
    )
    engine.add_instrument(nq)
    engine.add_data(bars_1s)

    cfg = PullbackV1Config(
        instrument_id="NQ.XCME",
        bar_type_1s="NQ.XCME-1-SECOND-LAST-EXTERNAL",
        depth=depth,
        hc_floor=0.50,
        trade_size=1,
        hc_mapping_path=HC_MAP_PATH,
    )
    strat = PullbackV1Strategy(cfg)
    engine.add_strategy(strat)

    engine.run()
    trades = list(strat.trade_log)
    engine.dispose()
    return trades


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading 1s bars from catalog …")
    t0 = time.time()
    cat = ParquetDataCatalog(CATALOG_PATH)
    load_start = START - LEAD_IN
    bars_1s = cat.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=load_start,
        end=END,
    )
    print(f"  {len(bars_1s):,} 1s bars loaded in {time.time()-t0:.0f}s")

    nq = create_nq()

    all_results: dict[float, list[dict]] = {}

    for depth in DEPTHS:
        print(f"\nRunning depth={depth} …", flush=True)
        t0 = time.time()
        trades = run_one(depth, bars_1s, nq)
        elapsed = time.time() - t0
        all_results[depth] = trades
        print(f"  {len(trades)} trades in {elapsed:.0f}s")

    # ── Print results table ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("PullbackV1 Results  (PT @ +0.5A limit | SL close | regime-flip, $20/pt, $4.06 RT)")
    print("=" * 80)
    print(f"{'':14}  {'n':>5}  {'wr':>6}  {'exp':>7}  {'pf':>5}  "
          f"{'hold':>5}  {'mfe':>6}  {'mae':>6}  {'maxdd':>8}  {'tot':>8}")
    print("-" * 80)

    summary_rows: list[tuple] = []

    for depth in DEPTHS:
        trades = all_results[depth]
        by_year = split_by_year(trades)

        print(f"\nDepth {depth:.2f} ATR")
        for yr in [2025, 2026]:
            yr_trades = by_year.get(yr, [])
            m = compute_metrics(yr_trades)
            label = f"  {yr}"
            print_row(label, m)
            summary_rows.append((depth, yr, m))

        m_pool = compute_metrics(trades)
        print_row("  pooled", m_pool)
        summary_rows.append((depth, "pool", m_pool))

    # ── Save trade logs ──────────────────────────────────────────────────────
    for depth in DEPTHS:
        trades = all_results[depth]
        if trades:
            df = pd.DataFrame(trades)
            label = str(depth).replace(".", "p")
            df.to_parquet(OUT_DIR / f"trades_depth{label}.parquet", index=False)

    print(f"\nResults saved to: {OUT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()

"""BacktestEngine runner for the Fable 5 pre-flip D10 study.

Usage:
  python run_nt.py --year 2025 --policy P1 --stop 1.0 [--seed 42]

Feeds catalog 1s+1m bars from Jan 1 of the year (fresh regime engine,
matching the upstream atlas construction); trading window comes from
common.ECON_WINDOWS. Outputs per-run parquets under _work/nt_runs/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
import os  # noqa: E402
os.chdir(PROJECT_ROOT)

import pandas as pd  # noqa: E402

from nautilus_trader.backtest.engine import BacktestEngine  # noqa: E402
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import Venue  # noqa: E402
from nautilus_trader.model.instruments import FuturesContract  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: E402
from nautilus_trader.test_kit.providers import TestInstrumentProvider  # noqa: E402

from studies.fable5_pre_flip_d10_reversal_entry.common import (  # noqa: E402
    CATALOG_PATH, ECON_WINDOWS, WORK, load_frozen_threshold,
)
from studies.fable5_pre_flip_d10_reversal_entry.strategy import (  # noqa: E402
    D10ReversalConfig, D10ReversalStrategy,
)

BAR_1S = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
BAR_1M = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"


def create_instrument() -> FuturesContract:
    t = TestInstrumentProvider.future(symbol="NQ", underlying="NQ",
                                      venue="XCME", exchange="XCME")
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = "20"
    d["price_increment"] = "0.25"
    return FuturesContract.from_dict(d)


def run_one(year: int, policy: str, stop: float, seed: int = 42,
            log_guard=None):
    t0 = time.time()
    thr = load_frozen_threshold()["threshold"]
    econ_s, econ_e = ECON_WINDOWS[year]

    tag = f"{policy}_{year}_s{stop:.2f}".replace(".", "p")
    if policy.startswith("P4"):
        tag += f"_seed{seed}"
    out_dir = WORK / "nt_runs" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    load_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    load_end = pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC")
    catalog = ParquetDataCatalog(str(CATALOG_PATH))
    bars_1s = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bars_1m = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)
    print(f"[{tag}] {len(bars_1s):,} 1s bars, {len(bars_1m):,} 1m bars "
          f"({time.time()-t0:.0f}s)")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="FABLE5-D10",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    if log_guard is None:
        log_guard = engine.get_log_guard()
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=USD,
        starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    engine.add_data(bars_1s)
    engine.add_data(bars_1m)

    cfg = D10ReversalConfig(
        year=year, policy=policy, stop_atr=stop, threshold=thr,
        trade_start_ns=econ_s.value, trade_end_ns=econ_e.value,
        score_path=str(WORK / "causal_scores.parquet"),
        placebo_path=str(WORK / f"placebo_events_seed{seed}.parquet")
        if policy.startswith("P4") else "",
    )
    strat = D10ReversalStrategy(config=cfg)
    engine.add_strategy(strat)
    engine.run(start=load_start)

    for name, rows in [("trades", strat.trades),
                       ("entry_timing", strat.entry_timing_log),
                       ("same_ts", strat.same_ts_log),
                       ("flips", strat.flip_log),
                       ("skips", strat.skip_log)]:
        df = pd.DataFrame(rows)
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
    from studies.fable5_pre_flip_d10_reversal_entry.common import sha256_file
    strategy_src = Path(__file__).resolve().parent / "strategy.py"
    meta = {
        "policy": policy, "year": year, "stop": stop, "seed": seed,
        "threshold": thr, "n_trades": len(strat.trades),
        "strategy_source_sha256": sha256_file(strategy_src),
        "mismatch_count": strat.mismatch_count,
        "lookup_hits": strat.lookup_hits,
        "runtime_s": time.time() - t0,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[{tag}] {len(strat.trades)} trades, "
          f"{strat.mismatch_count} mismatches ({time.time()-t0:.0f}s)")
    engine.dispose()
    return log_guard


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--policy", required=True,
                    choices=["P0", "P1", "P2", "P3", "P4A", "P4B", "ALL"])
    ap.add_argument("--stop", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.policy == "ALL":
        guard = None
        # placebo (P4*) runs last so the placebo build can finish in parallel
        jobs = [("P0", 0.0), ("P2", 0.0)]
        jobs += [("P1", s) for s in (0.50, 1.00, 1.50)]
        jobs += [("P3", s) for s in (0.50, 1.00, 1.50)]
        jobs += [("P4A", s) for s in (0.50, 1.00, 1.50)]
        jobs += [("P4B", s) for s in (0.50, 1.00, 1.50)]
        done = {p.name for p in (WORK / "nt_runs").glob("*") if
                (p / "meta.json").exists()}
        for pol, s in jobs:
            tag = f"{pol}_{args.year}_s{s:.2f}".replace(".", "p")
            if pol.startswith("P4"):
                tag += f"_seed{args.seed}"
            if tag in done:
                print(f"[{tag}] already complete — skipping")
                continue
            guard = run_one(args.year, pol, s, args.seed, guard)
    else:
        run_one(args.year, args.policy, args.stop, args.seed)


if __name__ == "__main__":
    main()

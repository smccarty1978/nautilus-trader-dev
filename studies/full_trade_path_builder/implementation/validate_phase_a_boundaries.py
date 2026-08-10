"""Long-prefix replay validation for monthly Phase A partitions."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument
from studies.full_trade_path_builder.implementation.phase_a_adapter import load_ordered_features
from studies.full_trade_path_builder.implementation.phase_a_core import label_checkpoint, next_flip_after
from studies.full_trade_path_builder.implementation.phase_a_strategy import (
    PhaseABullishCollector, PhaseABullishCollectorConfig,
)
from studies.full_trade_path_builder.implementation.run_phase_a_collect import (
    BAR_1M, BAR_1S, CATALOG,
)


def run_long_prefix(start: datetime, end: datetime, prefix_days: int) -> tuple[list[dict], list[dict]]:
    catalog = ParquetDataCatalog(str(CATALOG))
    load_start, load_end = start - timedelta(days=prefix_days), end + timedelta(seconds=301)
    b1 = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bm = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="PHASE-A-BOUNDARY",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
        base_currency=USD, starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    engine.add_data(b1)
    engine.add_data(bm)
    strategy = PhaseABullishCollector(PhaseABullishCollectorConfig(repo_root=str(ROOT)))
    engine.add_strategy(strategy)
    engine.run(start=load_start, end=load_end)
    lo, hi = int(start.timestamp() * 1e9), int(end.timestamp() * 1e9)
    flips = sorted(strategy.flip_rows, key=lambda x: x["confirm_flip_ns"])
    bearish = [x["confirm_flip_ns"] for x in flips if x["new_direction"] == -1]
    rows = []
    for row in strategy.checkpoint_rows:
        t = row["checkpoint_decision_ns"]
        if lo <= t < hi:
            lab = label_checkpoint(t, next_flip_after(t, bearish), int(strategy.observation_end_ns))
            rows.append({**row, "label_flip_le_300": lab.label_flip_le_300,
                         "label_censored": lab.censored, "confirm_flip_ns": lab.confirm_flip_ns})
    return rows, flips


def compare_boundary(year: int, month: int, data_root: Path, prefix_days: int) -> dict:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=3)
    long_rows, long_flips = run_long_prefix(start, end, prefix_days)
    path = data_root / f"year={year}" / f"month={month:02d}" / "checkpoints.parquet"
    features = load_ordered_features(ROOT)
    cols = [
        "regime_start_ns", "checkpoint_decision_ns", "atr_at_regime_start",
        "atr_at_checkpoint", "label_flip_le_300", "label_censored", "confirm_flip_ns",
    ] + features
    stored = pq.read_table(path, columns=cols).to_pylist()
    hi = int(end.timestamp() * 1e9)
    stored = [r for r in stored if r["checkpoint_decision_ns"] < hi]
    by_key_long = {(r["regime_start_ns"], r["checkpoint_decision_ns"]): r for r in long_rows}
    by_key_stored = {(r["regime_start_ns"], r["checkpoint_decision_ns"]): r for r in stored}
    keys_equal = set(by_key_long) == set(by_key_stored)
    compare_cols = cols[2:]
    mismatches = {}
    if keys_equal:
        for col in compare_cols:
            bad = 0
            for key in by_key_long:
                a, b = by_key_long[key].get(col), by_key_stored[key].get(col)
                if isinstance(a, float) or isinstance(b, float):
                    equal = (a is None and b is None) or (
                        a is not None and b is not None and
                        np.asarray(a, dtype="<f8").tobytes() == np.asarray(b, dtype="<f8").tobytes()
                    )
                else:
                    equal = a == b
                bad += not equal
            mismatches[col] = bad
    payload = {
        "boundary": f"{year}-{month:02d}", "prefix_days": prefix_days,
        "stored_rows": len(stored), "long_prefix_rows": len(long_rows),
        "key_sets_exact": keys_equal, "column_mismatches": mismatches,
        "verdict": "PASS" if keys_equal and not any(mismatches.values()) else "FAIL",
    }
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prefix-days", type=int, default=30)
    args = p.parse_args()
    results = [
        compare_boundary(year, 7, Path(args.data_root), args.prefix_days)
        for year in (2021, 2022, 2023, 2024, 2025)
    ]
    payload = {
        "boundaries": results,
        "verdict": "PASS" if all(x["verdict"] == "PASS" for x in results) else "FAIL",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

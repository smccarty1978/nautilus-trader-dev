"""Engine Builder for NautilusTrader Execution.
==============================================
Constructs BacktestEngine, registers instruments, and loads bars in causal order.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from backtests.nt_runtime.data_plan import DataPlan
from utils.causal_registration import add_bars_causal_order
from utils.runner.data import CausalDataLoader


def create_futures_instrument(data_plan: DataPlan) -> FuturesContract:
    """Creates standard FuturesContract instrument matching catalog metadata."""
    t = TestInstrumentProvider.future(
        symbol=data_plan.symbol,
        underlying=data_plan.symbol,
        venue=data_plan.venue,
        exchange=data_plan.venue,
    )
    d = t.to_dict(t)
    d["activation_ns"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["expiration_ns"] = pd.Timestamp("2027-12-31 23:59:59", tz="UTC").value
    d["ts_event"] = d["ts_init"] = pd.Timestamp("2019-01-01", tz="UTC").value
    d["multiplier"] = str(data_plan.multiplier)
    d["price_increment"] = str(data_plan.price_increment)
    return FuturesContract.from_dict(d)


def build_engine(
    data_plan: DataPlan,
    log_level: str = "ERROR",
    telemetry: Optional[Any] = None,
) -> Tuple[BacktestEngine, FuturesContract]:
    """Constructs BacktestEngine, adds venue/instrument, and loads bars causally."""
    engine_id = f"NT-STUDY-{uuid.uuid4().hex[:8]}"
    engine_config = BacktestEngineConfig(
        trader_id=engine_id,
        logging=LoggingConfig(log_level=log_level),
    )
    engine = BacktestEngine(config=engine_config)

    # 1. Add Venue & Instrument
    venue = Venue(data_plan.venue)
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(1_000_000, USD)],
    )

    instrument = create_futures_instrument(data_plan)
    engine.add_instrument(instrument)

    # 2. Load bars from catalog using CausalDataLoader
    loader = CausalDataLoader(data_plan.catalog_path)
    bars_1s = loader.load_bars(
        bar_type=data_plan.bar_type_1s,
        start=data_plan.warmup_start_dt,
        end=data_plan.end_dt,
    )
    bars_1m = loader.load_bars(
        bar_type=data_plan.bar_type_1m,
        start=data_plan.warmup_start_dt,
        end=data_plan.end_dt,
    )

    if telemetry is not None and hasattr(telemetry, "record_loaded_bars"):
        telemetry.record_loaded_bars("1s", len(bars_1s))
        telemetry.record_loaded_bars("1m", len(bars_1m))

    # 3. Add bars in strict causal multi-timeframe order (1s before coincident 1m)
    add_bars_causal_order(engine, bars_1s, bars_1m)

    return engine, instrument

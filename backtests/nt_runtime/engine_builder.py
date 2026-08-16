"""Engine Builder for NautilusTrader Execution.
==============================================
Constructs BacktestEngine, registers instruments, and loads bars in causal order.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, replace
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


class InvalidExecutionModeError(ValueError):
    """Raised when a declared execution mode is unsupported or internally inconsistent."""


ORDER_HANDLING_VALUES = ("virtual", "simulated_orders")
FILL_MODEL_VALUES = ("bar", "tick")
RUN_WINDOW_MODES = ("bounded", "from_start", "all_loaded")

_OMS_TYPES = {"NETTING": OmsType.NETTING, "HEDGING": OmsType.HEDGING}
_ACCOUNT_TYPES = {"MARGIN": AccountType.MARGIN, "CASH": AccountType.CASH}
_CURRENCIES = {"USD": USD}


@dataclass(frozen=True)
class ExecutionMode:
    """Declared execution semantics for a run.

    A single ``bar_execution`` boolean records a switch position, not a semantic.
    The fill model is a *research-behaviour* parameter (this repository has a
    recorded finding that bar-mode bracket simulation overstates fade strategies),
    so it is declared, validated, and echoed into ``run_manifest.json`` as hashed
    state rather than being left to library defaults.

    ``order_handling`` selects which **output contract** applies:

    * ``virtual``          - strategy keeps internal evaluators and places no NT
      orders; the NT positions report is expected empty and per-evaluator tables
      are the real output.
    * ``simulated_orders`` - strategy submits orders to NT's simulated exchange;
      closed positions plus the strategy's own trade log are the output.

    ``warmup_dispatched`` is an **observation**, never an assumption: it is left
    ``None`` until a run measures whether pre-start bars were actually dispatched.
    """

    order_handling: str = "virtual"
    fill_model: str = "bar"
    bar_execution: bool = True
    bar_adaptive_high_low_ordering: bool = False
    oms_type: str = "NETTING"
    account_type: str = "MARGIN"
    base_currency: str = "USD"
    starting_balance: int = 1_000_000
    commission_model: str = "none"
    slippage_model: str = "none"
    run_window_mode: str = "bounded"
    warmup_days: int = 5
    warmup_dispatched: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.order_handling not in ORDER_HANDLING_VALUES:
            raise InvalidExecutionModeError(
                f"INVALID_ORDER_HANDLING: '{self.order_handling}' is not supported. "
                f"Choose one of {list(ORDER_HANDLING_VALUES)}."
            )
        if self.fill_model not in FILL_MODEL_VALUES:
            raise InvalidExecutionModeError(
                f"INVALID_FILL_MODEL: '{self.fill_model}' is not supported. "
                f"Choose one of {list(FILL_MODEL_VALUES)}."
            )
        if self.run_window_mode not in RUN_WINDOW_MODES:
            raise InvalidExecutionModeError(
                f"INVALID_RUN_WINDOW_MODE: '{self.run_window_mode}' is not supported. "
                f"Choose one of {list(RUN_WINDOW_MODES)}."
            )
        if self.oms_type not in _OMS_TYPES:
            raise InvalidExecutionModeError(
                f"INVALID_OMS_TYPE: '{self.oms_type}'. Supported: {sorted(_OMS_TYPES)}."
            )
        if self.account_type not in _ACCOUNT_TYPES:
            raise InvalidExecutionModeError(
                f"INVALID_ACCOUNT_TYPE: '{self.account_type}'. Supported: {sorted(_ACCOUNT_TYPES)}."
            )
        if self.base_currency not in _CURRENCIES:
            raise InvalidExecutionModeError(
                f"UNSUPPORTED_BASE_CURRENCY: '{self.base_currency}'. Supported: {sorted(_CURRENCIES)}."
            )
        if self.fill_model == "tick":
            raise InvalidExecutionModeError(
                "UNSUPPORTED_FILL_MODEL: tick/MBP-1 replay requires a dedicated catalog loader and "
                "order book venue; only 'bar' is supported (see BACKTEST_HARNESS_B0_BOUNDARY.md §6.3)."
            )

    # -- canonical presets ------------------------------------------------
    @classmethod
    def collector_default(cls) -> "ExecutionMode":
        """Exactly reproduces the venue settings ``build_engine`` used before B1.

        ``bar_execution=True`` and ``bar_adaptive_high_low_ordering=False`` are
        NautilusTrader's own ``add_venue`` defaults, which the pre-B1
        ``build_engine`` inherited by not passing them. Declaring them explicitly
        records the semantic without changing collector behaviour.
        """
        return cls(order_handling="virtual", run_window_mode="all_loaded")

    @classmethod
    def legacy_backtest(cls, order_handling: str, run_window_mode: str = "bounded") -> "ExecutionMode":
        """Matches both legacy runners, which pass ``bar_adaptive_high_low_ordering=True``."""
        return cls(
            order_handling=order_handling,
            bar_execution=True,
            bar_adaptive_high_low_ordering=True,
            run_window_mode=run_window_mode,
        )

    # -- accessors --------------------------------------------------------
    @property
    def nt_oms_type(self) -> OmsType:
        return _OMS_TYPES[self.oms_type]

    @property
    def nt_account_type(self) -> AccountType:
        return _ACCOUNT_TYPES[self.account_type]

    @property
    def nt_base_currency(self) -> Any:
        return _CURRENCIES[self.base_currency]

    def with_observation(self, *, warmup_dispatched: Optional[bool]) -> "ExecutionMode":
        return replace(self, warmup_dispatched=warmup_dispatched)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["run_window"] = {
            "mode": d.pop("run_window_mode"),
            "warmup_days": d.pop("warmup_days"),
            "warmup_dispatched": d.pop("warmup_dispatched"),
        }
        return d


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
    execution_mode: Optional[ExecutionMode] = None,
    trader_id: Optional[str] = None,
    log_directory: Optional[str] = None,
) -> Tuple[BacktestEngine, FuturesContract]:
    """Constructs BacktestEngine, adds venue/instrument, and loads bars causally.

    ``execution_mode`` declares venue/fill semantics. When omitted it defaults to
    :meth:`ExecutionMode.collector_default`, whose venue settings are identical to
    NautilusTrader's ``add_venue`` defaults -- i.e. exactly what this function did
    before the execution-mode contract existed. Collector behaviour is therefore
    unchanged by this parameter's introduction.
    """
    mode = execution_mode or ExecutionMode.collector_default()

    engine_id = trader_id or f"NT-STUDY-{uuid.uuid4().hex[:8]}"
    logging_kwargs: Dict[str, Any] = {"log_level": log_level}
    if log_directory is not None:
        logging_kwargs["log_directory"] = log_directory
    engine_config = BacktestEngineConfig(
        trader_id=engine_id,
        logging=LoggingConfig(**logging_kwargs),
    )
    engine = BacktestEngine(config=engine_config)

    # 1. Add Venue & Instrument
    venue = Venue(data_plan.venue)
    engine.add_venue(
        venue=venue,
        oms_type=mode.nt_oms_type,
        account_type=mode.nt_account_type,
        base_currency=mode.nt_base_currency,
        starting_balances=[Money(mode.starting_balance, mode.nt_base_currency)],
        bar_execution=mode.bar_execution,
        bar_adaptive_high_low_ordering=mode.bar_adaptive_high_low_ordering,
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

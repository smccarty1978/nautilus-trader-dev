"""NautilusTrader Generic Runtime Core.
=====================================
Modular orchestration framework for executing declarative NautilusTrader studies.
"""

from backtests.nt_runtime.compiled_study_loader import (
    load_compiled_study,
    CompiledStudyData,
    StaleCompiledStudyError,
    InvalidCompiledStudyError,
)
from backtests.nt_runtime.data_plan import (
    resolve_data_plan,
    DataPlan,
    UnauthorizedExecutionDomainError,
)
from backtests.nt_runtime.engine_builder import build_engine
from backtests.nt_runtime.strategy_binding import (
    resolve_strategy_binding,
    StrategyBinding,
    UnregisteredStrategyBindingError,
)
from backtests.nt_runtime.run_plan import (
    resolve_run_plan,
    RunPlan,
    RunStage,
)
from backtests.nt_runtime.telemetry import CausalTelemetry
from research_workflow.output_manager import OutputManager

__all__ = [
    "load_compiled_study",
    "CompiledStudyData",
    "StaleCompiledStudyError",
    "InvalidCompiledStudyError",
    "resolve_data_plan",
    "DataPlan",
    "UnauthorizedExecutionDomainError",
    "build_engine",
    "resolve_strategy_binding",
    "StrategyBinding",
    "UnregisteredStrategyBindingError",
    "resolve_run_plan",
    "RunPlan",
    "RunStage",
    "CausalTelemetry",
    "OutputManager",
]

"""Backtest Mode Orchestrator for the NautilusTrader Generic Runtime.
====================================================================

Mirrors ``modes/collect.py`` for standalone (non-collector) backtests.

Two output contracts are supported, selected by ``execution_mode.order_handling``:

``virtual``
    The strategy maintains internal evaluators and submits **no** NT orders
    (e.g. ``ScoreFanningStrategy``). Output is one table per evaluator carrying
    open state and exit reasons. The NT positions report is asserted empty and
    that emptiness is recorded as evidence -- no position artifact is fabricated.

``simulated_orders``
    The strategy submits orders to NT's simulated exchange (e.g.
    ``W4ExitStrategy``). Output is the positions report filtered to closed
    positions, the strategy's own blended-PnL trade log, and an explicit count of
    positions still open at the end of the run.

A single ``trades.parquet`` contract cannot serve both, which is why the contract
is keyed rather than assumed.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from backtests.nt_runtime.data_plan import DataPlan, resolve_catalog_plan, resolve_data_plan
from backtests.nt_runtime.engine_builder import (
    ExecutionMode,
    InvalidExecutionModeError,
    build_engine,
)
from backtests.nt_runtime.strategy_binding import (
    StrategyBinding,
    registered_order_handling,
    resolve_strategy_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

ARTIFACT_SCHEMA_VERSION = "1.0.0"


class BacktestContractError(ValueError):
    """Raised when a run violates the declared backtest contract."""


class SealedStudyOverrideError(BacktestContractError):
    """Raised when a request would run a strategy other than the one a study seals."""


class UnknownParameterError(BacktestContractError):
    """Raised when a --param key is not a declared field of the strategy config."""


class MissingArtifactError(BacktestContractError):
    """Raised when a run finished but did not produce its required artifacts."""


# ---------------------------------------------------------------------------
# Sealed-study protection
# ---------------------------------------------------------------------------


def assert_strategy_matches_sealed_study(study_path: Union[str, Path], requested_strategy: str) -> str:
    """Rejects any attempt to run a strategy other than the one a study declares.

    A sealed study binds an immutable ``strategy_class``; its pre-execution audit
    seal covers *that* code and nothing else. Allowing ``--strategy`` to override it
    would execute unsealed code while seal verification still reported VALID.

    Returns the study's declared ``strategy_class``.
    """
    from backtests.nt_runtime.compiled_study_loader import load_compiled_study

    study_data = load_compiled_study(study_path)
    declared = study_data.spec.execution.strategy_class
    if not requested_strategy:
        return declared

    if requested_strategy == declared:
        return declared

    # Accept a registry key that resolves to the same class as the declared path.
    try:
        req = resolve_strategy_binding(requested_strategy, mode="backtest")
        dec_module, _, dec_class = declared.rpartition(".")
        if req.module_path == dec_module and req.class_name == dec_class:
            return declared
    except Exception:  # noqa: BLE001 - fall through to the hard failure below
        pass

    raise SealedStudyOverrideError(
        f"SEALED_STUDY_STRATEGY_OVERRIDE_BLOCKED: study '{study_data.study_id}' declares "
        f"strategy_class='{declared}', but '{requested_strategy}' was requested. If a study is "
        f"sealed, the strategy it seals is the only strategy permitted to execute under that "
        f"study identity. Run the backtest standalone (without --study) instead."
    )


# ---------------------------------------------------------------------------
# Typed parameter binding
# ---------------------------------------------------------------------------


def _config_fields(config_cls: Any) -> Dict[str, Any]:
    """Returns {field_name: annotation} for an NT StrategyConfig (msgspec Struct)."""
    names = getattr(config_cls, "__struct_fields__", None)
    try:
        hints = typing.get_type_hints(config_cls)
    except Exception:  # noqa: BLE001 - fall back to raw annotations
        hints = dict(getattr(config_cls, "__annotations__", {}))
    if names:
        return {n: hints.get(n, Any) for n in names}
    return hints


def _coerce_scalar(raw: str, annotation: Any, key: str) -> Any:
    origin = typing.get_origin(annotation)
    args = [a for a in typing.get_args(annotation) if a is not type(None)]  # noqa: E721
    if origin is Union and args:
        annotation = args[0]

    if annotation is bool:
        low = raw.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise UnknownParameterError(
            f"INVALID_PARAMETER_VALUE: --param {key}={raw!r} is not a boolean "
            f"(use true/false)."
        )
    if annotation is int:
        try:
            return int(raw)
        except ValueError as err:
            raise UnknownParameterError(
                f"INVALID_PARAMETER_VALUE: --param {key}={raw!r} is not an integer."
            ) from err
    if annotation is float:
        try:
            return float(raw)
        except ValueError as err:
            raise UnknownParameterError(
                f"INVALID_PARAMETER_VALUE: --param {key}={raw!r} is not a number."
            ) from err
    return raw


def coerce_params(config_cls: Any, params: Dict[str, str]) -> Dict[str, Any]:
    """Validates and type-coerces ``--param k=v`` overrides against the config schema.

    Undeclared parameters are rejected: silently accepting one would let a caller
    believe a setting took effect when the strategy never read it.
    """
    fields = _config_fields(config_cls)
    unknown = sorted(k for k in params if k not in fields)
    if unknown:
        raise UnknownParameterError(
            f"UNKNOWN_PARAMETER: {unknown} not declared by {config_cls.__name__}. "
            f"Declared parameters: {sorted(fields)}."
        )
    return {k: _coerce_scalar(v, fields[k], k) if isinstance(v, str) else v for k, v in params.items()}


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------

_VIRTUAL_TRADE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("trade_id", "trade_id"),
    ("entry_time", "entry_time"),
    ("entry_px", "entry_px"),
    ("direction", "direction"),
    ("qty", "qty"),
    ("atr", "atr_at_entry"),
    ("exit_time", "exit_time"),
    ("exit_px", "exit_px"),
    ("exit_reason", "exit_reason"),
    ("pnl", "pnl"),
    ("is_open", "is_open"),
)


def extract_virtual_outputs(strategy: Any) -> Dict[str, pd.DataFrame]:
    """Builds one table per evaluator, matching the legacy runner's column set."""
    evaluators = getattr(strategy, "evaluators", None)
    if not evaluators:
        raise BacktestContractError(
            "VIRTUAL_CONTRACT_UNSATISFIED: order_handling='virtual' requires the strategy to "
            "expose an 'evaluators' collection; none was found. Use "
            "order_handling='simulated_orders' for order-submitting strategies."
        )

    out: Dict[str, pd.DataFrame] = {}
    for evaluator in evaluators:
        trades = list(getattr(evaluator, "trade_history", []) or []) + list(
            getattr(evaluator, "active_trades", []) or []
        )
        rows = [
            {col: getattr(t, attr, None) for col, attr in _VIRTUAL_TRADE_FIELDS} for t in trades
        ]
        out[str(getattr(evaluator, "name", "unnamed"))] = pd.DataFrame(
            rows, columns=[c for c, _ in _VIRTUAL_TRADE_FIELDS]
        )
    return out


def summarize_virtual(tables: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    per_policy: Dict[str, Any] = {}
    for name, df in tables.items():
        closed = df[~df["is_open"].fillna(False)] if not df.empty else df
        pnl = pd.to_numeric(closed.get("pnl"), errors="coerce") if not closed.empty else pd.Series(dtype=float)
        per_policy[name] = {
            "trade_count": int(len(df)),
            "open_count": int(df["is_open"].fillna(False).sum()) if not df.empty else 0,
            "closed_count": int(len(closed)),
            "gross_pnl": float(pnl.sum()) if len(pnl) else 0.0,
            "win_rate": float((pnl > 0).mean()) if len(pnl) else None,
            "exit_reason_distribution": (
                closed["exit_reason"].value_counts(dropna=False).astype(int).to_dict()
                if not closed.empty
                else {}
            ),
        }
    return {"order_handling": "virtual", "per_policy": per_policy}


def extract_simulated_outputs(engine: Any, strategy: Any) -> Dict[str, Any]:
    """Splits the NT positions report into closed/open and captures the strategy log."""
    report = engine.trader.generate_positions_report()
    if len(report) > 0 and "ts_closed" in report.columns:
        closed = report[report["ts_closed"].notna()].copy()
        open_positions = report[report["ts_closed"].isna()].copy()
    else:
        closed = report.copy()
        open_positions = report.iloc[0:0].copy()

    all_trades = getattr(strategy, "all_trades", None)
    strategy_trades = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    return {
        "closed_positions": closed,
        "open_positions": open_positions,
        "strategy_trades": strategy_trades,
        "positions_report_rows": int(len(report)),
    }


def _count_evaluator_trades(strategy: Any) -> int:
    """Counts virtual evaluator trades a strategy is holding, if any.

    Used to detect a virtual strategy running under `simulated_orders` (W1).
    """
    evaluators = getattr(strategy, "evaluators", None)
    if not evaluators:
        return 0
    total = 0
    for evaluator in evaluators:
        total += len(list(getattr(evaluator, "trade_history", []) or []))
        total += len(list(getattr(evaluator, "active_trades", []) or []))
    return total


def summarize_simulated(outputs: Dict[str, Any]) -> Dict[str, Any]:
    closed = outputs["closed_positions"]
    pnl = (
        pd.to_numeric(closed["realized_pnl"].astype(str).str.replace(r"[^0-9eE+\-.]", "", regex=True),
                      errors="coerce")
        if "realized_pnl" in closed.columns and not closed.empty
        else pd.Series(dtype=float)
    )
    wins = pnl[pnl > 0].sum() if len(pnl) else 0.0
    losses = -pnl[pnl < 0].sum() if len(pnl) else 0.0
    equity = pnl.cumsum() if len(pnl) else pd.Series(dtype=float)
    max_dd = float((equity - equity.cummax()).min()) if len(equity) else 0.0

    return {
        "order_handling": "simulated_orders",
        "closed_position_count": int(len(closed)),
        "open_position_count": int(len(outputs["open_positions"])),
        "positions_report_rows": outputs["positions_report_rows"],
        "strategy_trade_count": int(len(outputs["strategy_trades"])),
        "gross_pnl": float(pnl.sum()) if len(pnl) else 0.0,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else None,
        "profit_factor": (float(wins / losses) if losses > 0 else None),
        "max_drawdown": max_dd,
    }


# ---------------------------------------------------------------------------
# Run plan / orchestration
# ---------------------------------------------------------------------------


@dataclass
class BacktestRunPlan:
    strategy: str
    binding: Optional[StrategyBinding]
    symbol: str
    start_date: str
    end_date: str
    warmup_days: int
    execution_mode: ExecutionMode
    params: Dict[str, Any]
    data_plan: DataPlan
    study_path: Optional[str] = None
    run_tag: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "strategy_class": (
                f"{self.binding.module_path}.{self.binding.class_name}" if self.binding else None
            ),
            "config_class": self.binding.config_class_name if self.binding else None,
            "symbol": self.symbol,
            "study_path": self.study_path,
            "run_tag": self.run_tag,
            "dates": {
                "start": self.start_date,
                "end": self.end_date,
                "warmup_days": self.warmup_days,
                "warmup_start": self.data_plan.warmup_start_dt.isoformat(),
                "load_start": self.data_plan.warmup_start_dt.isoformat(),
                "load_end": self.data_plan.end_dt.isoformat(),
            },
            "instrument": {
                "symbol": self.data_plan.symbol,
                "venue": self.data_plan.venue,
                "instrument_id": self.data_plan.instrument_id,
                "multiplier": self.data_plan.multiplier,
                "price_increment": self.data_plan.price_increment,
            },
            "catalog": {
                "path": self.data_plan.catalog_path.as_posix(),
                "bar_type_1s": self.data_plan.bar_type_1s,
                "bar_type_1m": self.data_plan.bar_type_1m,
            },
            "timestamp_contract": {
                "raw_timestamp_semantic": self.data_plan.raw_timestamp_semantic,
                "ts_init_delta_1s_ns": self.data_plan.ts_init_delta_1s_ns,
                "ts_init_delta_1m_ns": self.data_plan.ts_init_delta_1m_ns,
            },
            "execution_mode": self.execution_mode.to_dict(),
            "parameters": self.params,
        }


def resolve_backtest_plan(
    strategy: str,
    symbol: str,
    start_date: str,
    end_date: str,
    warmup_days: int = 5,
    order_handling: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    study_path: Optional[Union[str, Path]] = None,
    execution_mode: Optional[ExecutionMode] = None,
    run_window_mode: Optional[str] = None,
    run_tag: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> BacktestRunPlan:
    """Resolves everything a run needs without touching data or the engine."""
    repo_root = repo_root or REPO_ROOT

    if study_path is not None:
        # A study contract governs identity: it may not be overridden.
        declared = assert_strategy_matches_sealed_study(study_path, strategy)
        strategy = strategy or declared

    binding = resolve_strategy_binding(strategy, mode="backtest")

    handling = order_handling or registered_order_handling(binding.binding_id)
    if handling is None:
        raise InvalidExecutionModeError(
            f"ORDER_HANDLING_UNDECLARED: strategy '{binding.binding_id}' does not declare an "
            f"order_handling and none was supplied. Pass --order-handling "
            f"{{virtual|simulated_orders}} explicitly; the output contract cannot be guessed."
        )

    if execution_mode is None:
        execution_mode = ExecutionMode.legacy_backtest(
            order_handling=handling,
            run_window_mode=run_window_mode or "bounded",
        )
    # Keep the mode consistent with the resolved contract and requested warmup.
    execution_mode = dataclasses.replace(
        execution_mode,
        order_handling=handling,
        warmup_days=warmup_days,
        **({"run_window_mode": run_window_mode} if run_window_mode else {}),
    )

    if study_path is not None:
        from backtests.nt_runtime.compiled_study_loader import load_compiled_study

        data_plan = resolve_data_plan(
            load_compiled_study(study_path), start_date, end_date, warmup_days, repo_root
        )
    else:
        data_plan = resolve_catalog_plan(symbol, start_date, end_date, warmup_days, repo_root)

    typed_params = coerce_params(binding.config_cls, params or {})

    return BacktestRunPlan(
        strategy=binding.binding_id,
        binding=binding,
        symbol=data_plan.symbol,
        start_date=start_date,
        end_date=end_date,
        warmup_days=warmup_days,
        execution_mode=execution_mode,
        params=typed_params,
        data_plan=data_plan,
        study_path=str(study_path) if study_path else None,
        run_tag=run_tag,
    )


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def run_backtest_mode(
    strategy: str,
    symbol: str = "NQ",
    start_date: str = "",
    end_date: str = "",
    warmup_days: int = 5,
    order_handling: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    study_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    run_tag: Optional[str] = None,
    log_level: str = "ERROR",
    run_window_mode: Optional[str] = None,
    dry_run: bool = False,
    trader_id: Optional[str] = None,
    repo_root: Optional[Path] = None,
    execution_mode_override: Optional[ExecutionMode] = None,
) -> Dict[str, Any]:
    """Executes one standalone backtest and writes the standard artifact set."""
    repo_root = repo_root or REPO_ROOT

    plan = resolve_backtest_plan(
        strategy=strategy,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        warmup_days=warmup_days,
        order_handling=order_handling,
        params=params,
        study_path=study_path,
        execution_mode=execution_mode_override,
        run_window_mode=run_window_mode,
        run_tag=run_tag,
        repo_root=repo_root,
    )

    if dry_run:
        return {"mode": "dry_run", "status": "RESOLVED", "plan": plan.to_dict()}

    # --- run directory -------------------------------------------------
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{plan.strategy}_backtest" + (f"_{run_tag}" if run_tag else "")
    base = Path(output_dir).resolve() if output_dir else (repo_root / "runs")
    run_dir = base / run_id
    backtest_dir = run_dir / "backtest"
    logs_dir = run_dir / "logs"
    for d in (run_dir, backtest_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": "backtest",
        "status": "RUNNING",
        "start_time_utc": datetime.now(timezone.utc).isoformat(),
        **plan.to_dict(),
    }
    _write_json(run_dir / "run_manifest.json", manifest)

    # --- strategy config ------------------------------------------------
    cfg_kwargs: Dict[str, Any] = {
        "instrument_id": plan.data_plan.instrument_id,
        "bar_type_1s": plan.data_plan.bar_type_1s,
        "bar_type_1m": plan.data_plan.bar_type_1m,
    }
    declared = _config_fields(plan.binding.config_cls)
    # Route strategy-managed checkpoint state into this run's directory rather
    # than a shared global path (ScoreFanningStrategy writes daily checkpoints
    # unconditionally, so the directory is part of the run, not an optional extra).
    if "checkpoint_dir" in declared and "checkpoint_dir" not in plan.params:
        cfg_kwargs["checkpoint_dir"] = str(backtest_dir / "checkpoints")
        (backtest_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    cfg_kwargs = {k: v for k, v in cfg_kwargs.items() if k in declared}
    cfg_kwargs.update(plan.params)

    strategy_config = plan.binding.config_cls(**cfg_kwargs)
    strategy_obj = plan.binding.strategy_cls(config=strategy_config)

    _write_json(
        run_dir / "resolved_config.json",
        {
            "run_id": run_id,
            "strategy_class": f"{plan.binding.module_path}.{plan.binding.class_name}",
            "config_class": plan.binding.config_class_name,
            "resolved_config": {
                k: getattr(strategy_config, k, None) for k in sorted(declared)
            },
            "explicit_overrides": plan.params,
            "execution_mode": plan.execution_mode.to_dict(),
        },
    )

    # --- engine ----------------------------------------------------------
    started = datetime.now(timezone.utc)
    engine, instrument = build_engine(
        plan.data_plan,
        log_level=log_level,
        execution_mode=plan.execution_mode,
        trader_id=trader_id,
        log_directory=str(logs_dir),
    )
    engine.add_strategy(strategy_obj)

    mode = plan.execution_mode.run_window_mode
    if mode == "bounded":
        engine.run(start=plan.data_plan.start_dt, end=plan.data_plan.end_dt)
    elif mode == "from_start":
        engine.run(start=plan.data_plan.start_dt)
    else:
        engine.run()
    finished = datetime.now(timezone.utc)

    # --- outputs by contract ---------------------------------------------
    artifacts: Dict[str, str] = {}
    if plan.execution_mode.order_handling == "virtual":
        tables = extract_virtual_outputs(strategy_obj)
        for name, df in tables.items():
            if df.empty:
                # An empty evaluator table is a real observation, not an artifact:
                # the legacy runner writes nothing, so neither do we.
                continue
            out = backtest_dir / f"results_{name}.parquet"
            df.to_parquet(out, index=False)
            artifacts[f"results_{name}"] = out.as_posix()

        report = engine.trader.generate_positions_report()
        summary = summarize_virtual(tables)
        summary["nt_positions_report_rows"] = int(len(report))
        summary["nt_positions_report_empty"] = bool(len(report) == 0)
        if len(report) > 0:
            raise BacktestContractError(
                f"VIRTUAL_CONTRACT_VIOLATED: order_handling='virtual' asserts the NT positions "
                f"report is empty, but it contains {len(report)} rows. The strategy submitted "
                f"orders; declare order_handling='simulated_orders' instead."
            )
        summary["evaluator_tables_written"] = sorted(artifacts)
        summary["evaluator_tables_empty"] = sorted(n for n, df in tables.items() if df.empty)
    else:
        outputs = extract_simulated_outputs(engine, strategy_obj)

        # W1: the counterpart to the virtual assertion. A strategy that keeps
        # virtual evaluator trades but places no broker orders is a `virtual`
        # strategy; reporting SUCCESS with an empty trades.parquet silently
        # discards its real output.
        evaluator_trades = _count_evaluator_trades(strategy_obj)
        if evaluator_trades > 0 and outputs["positions_report_rows"] == 0:
            raise BacktestContractError(
                f"SIMULATED_CONTRACT_VIOLATED: strategy produced {evaluator_trades} virtual "
                f"evaluator trades and zero NT positions. Its output is virtual evaluator "
                f"tables, not a broker position stream — declare order_handling='virtual'."
            )

        closed_path = backtest_dir / "trades.parquet"
        outputs["closed_positions"].to_parquet(closed_path, index=False)
        artifacts["trades"] = closed_path.as_posix()

        # W4: strategy_trades is a REQUIRED artifact of this contract, not an
        # optional extra. Writing it only when non-empty let the golden assertion
        # silently pass if the harness stopped producing it.
        st_path = backtest_dir / "strategy_trades.parquet"
        outputs["strategy_trades"].to_parquet(st_path, index=False)
        artifacts["strategy_trades"] = st_path.as_posix()

        if not outputs["open_positions"].empty:
            op_path = backtest_dir / "open_positions.parquet"
            outputs["open_positions"].to_parquet(op_path, index=False)
            artifacts["open_positions"] = op_path.as_posix()

        summary = summarize_simulated(outputs)

    elapsed = (finished - started).total_seconds()
    metrics = {
        "run_id": run_id,
        "wall_time_seconds": round(elapsed, 3),
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "run_window_mode": mode,
        "data_window": {
            "load_start": plan.data_plan.warmup_start_dt.isoformat(),
            "load_end": plan.data_plan.end_dt.isoformat(),
            "run_start": plan.data_plan.start_dt.isoformat(),
            "run_end": plan.data_plan.end_dt.isoformat() if mode == "bounded" else None,
        },
    }
    _write_json(run_dir / "execution_metrics.json", metrics)

    # M3: validate BEFORE any SUCCESS is persisted. The assertion previously ran
    # after the manifest was written, so an incomplete run exited non-zero but left
    # a SUCCESS manifest on disk — the artifact a later reader would trust.
    summary.update({"run_id": run_id, "artifacts": artifacts})
    try:
        _assert_required_artifacts(
            run_dir, plan.execution_mode.order_handling, artifacts,
            require_summary=False,
        )
    except MissingArtifactError as err:
        manifest.update(
            {
                "status": "FAILED_INCOMPLETE_ARTIFACTS",
                "end_time_utc": finished.isoformat(),
                "artifacts": artifacts,
                "execution_metrics": metrics,
                "failure": str(err),
            }
        )
        _write_json(run_dir / "run_manifest.json", manifest)
        summary["status"] = "FAILED_INCOMPLETE_ARTIFACTS"
        summary["failure"] = str(err)
        _write_json(run_dir / "summary.json", summary)
        engine.dispose()
        raise

    summary["status"] = "SUCCESS"
    _write_json(run_dir / "summary.json", summary)

    manifest.update(
        {
            "status": "SUCCESS",
            "end_time_utc": finished.isoformat(),
            "artifacts": artifacts,
            "execution_metrics": metrics,
        }
    )
    _write_json(run_dir / "run_manifest.json", manifest)

    engine.dispose()

    return {
        "run_id": run_id,
        "run_dir": run_dir.as_posix(),
        "status": "SUCCESS",
        "summary": summary,
        "artifacts": artifacts,
        "metrics": metrics,
    }


REQUIRED_ARTIFACT_FILES: Tuple[str, ...] = (
    "run_manifest.json",
    "resolved_config.json",
    "execution_metrics.json",
    "summary.json",
)


def _assert_required_artifacts(
    run_dir: Path,
    order_handling: str,
    artifacts: Dict[str, str],
    *,
    require_summary: bool = True,
) -> None:
    """A run is not SUCCESS unless its declared artifact set actually exists.

    ``require_summary=False`` is used by the in-run check, which deliberately runs
    *before* ``summary.json`` is written so that no SUCCESS is ever persisted ahead
    of validation. Post-hoc callers keep the full set.
    """
    required = REQUIRED_ARTIFACT_FILES
    if not require_summary:
        required = tuple(n for n in required if n != "summary.json")
    missing = [name for name in required if not (run_dir / name).is_file()]
    if not (run_dir / "logs").is_dir():
        missing.append("logs/")
    if order_handling == "simulated_orders" and "trades" not in artifacts:
        missing.append("backtest/trades.parquet")
    if missing:
        raise MissingArtifactError(
            f"REQUIRED_ARTIFACTS_MISSING: run {run_dir.name} cannot be reported SUCCESS without "
            f"{missing}."
        )

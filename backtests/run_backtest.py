#!/usr/bin/env python
"""Standalone NautilusTrader Backtest CLI.
=========================================

The supported entrypoint for **non-collector** backtests. Engine construction,
instrument creation, catalog loading and causal bar registration all come from
``backtests/nt_runtime/``; this file only parses intent.

Usage
-----
    # From an explicit standalone config
    python backtests/run_backtest.py --config backtests/configs/w4_exit_b1_2023.yaml

    # Or fully from flags
    python backtests/run_backtest.py \\
        --strategy w4_exit_strategy --symbol NQ \\
        --start-date 2023-01-01 --end-date 2023-12-31 \\
        --order-handling simulated_orders --run-window from_start \\
        --param year=2023 --param policy=B1 --param theta=0.62 --param N=10

    # Resolve and print the plan without replaying anything
    python backtests/run_backtest.py --config backtests/configs/w4_exit_b1_2023.yaml --dry-run

Notes
-----
* There is no implicit "latest" anything: symbol, dates and strategy must be
  stated explicitly (via flags or a config), and every run writes to its own
  timestamped directory under ``runs/``.
* Non-collector backtests do **not** execute under a collector study directory.
  ``--study`` is accepted only to *bind* a run to a study contract, and it can
  never override that study's sealed ``strategy_class``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtests.nt_runtime.engine_builder import ExecutionMode, InvalidExecutionModeError  # noqa: E402
from backtests.nt_runtime.modes.backtest import (  # noqa: E402
    BacktestContractError,
    run_backtest_mode,
)
from backtests.nt_runtime.strategy_binding import (  # noqa: E402
    STRATEGY_REGISTRY,
    UnregisteredStrategyBindingError,
)


class ConfigError(ValueError):
    """Raised when a standalone backtest config is missing or malformed."""


CONFIG_KEYS = {
    "name", "strategy", "symbol", "start_date", "end_date", "warmup_days",
    "execution_mode", "params", "study", "log_level", "run_tag", "output_dir",
    "trader_id",
}


def load_backtest_config(path: Path) -> Dict[str, Any]:
    """Loads and validates a standalone backtest config."""
    import yaml

    if not path.is_file():
        raise ConfigError(
            f"CONFIG_NOT_FOUND: {path}. Standalone backtest configs live in "
            f"backtests/configs/<name>.yaml."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as err:
        raise ConfigError(f"CONFIG_MALFORMED: {path}: {err}") from err

    if not isinstance(data, dict):
        raise ConfigError(f"CONFIG_MALFORMED: {path} must contain a YAML mapping.")

    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise ConfigError(
            f"CONFIG_UNKNOWN_KEYS: {unknown} in {path}. Supported keys: {sorted(CONFIG_KEYS)}."
        )
    return data


def parse_params(pairs: Optional[List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ConfigError(
                f"INVALID_PARAM: '{item}' must be given as key=value (e.g. --param theta=0.62)."
            )
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise ConfigError(f"INVALID_PARAM: '{item}' has an empty key.")
        out[key] = value
    return out


def build_execution_mode(
    cfg_mode: Optional[Dict[str, Any]],
    order_handling: Optional[str],
    run_window: Optional[str],
    warmup_days: int,
) -> Optional[ExecutionMode]:
    """Builds an ExecutionMode from config + flag overrides, or None to use the default."""
    if not cfg_mode and not order_handling and not run_window:
        return None

    fields: Dict[str, Any] = dict(cfg_mode or {})
    # Config may nest run-window settings the way the manifest renders them.
    run_window_block = fields.pop("run_window", None)
    if isinstance(run_window_block, dict):
        if "mode" in run_window_block:
            fields.setdefault("run_window_mode", run_window_block["mode"])
        if "warmup_days" in run_window_block:
            fields.setdefault("warmup_days", run_window_block["warmup_days"])
    fields.pop("warmup_dispatched", None)  # observed at runtime, never declared

    if order_handling:
        fields["order_handling"] = order_handling
    if run_window:
        fields["run_window_mode"] = run_window
    fields.setdefault("warmup_days", warmup_days)
    fields.setdefault("order_handling", "virtual")
    fields.setdefault("bar_execution", True)
    fields.setdefault("bar_adaptive_high_low_ordering", True)

    valid = set(ExecutionMode.__dataclass_fields__)
    unknown = sorted(set(fields) - valid)
    if unknown:
        raise InvalidExecutionModeError(
            f"INVALID_EXECUTION_MODE_FIELDS: {unknown}. Supported: {sorted(valid)}."
        )
    return ExecutionMode(**fields)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run a standalone (non-collector) NautilusTrader backtest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--config", type=str, help="Path to a standalone backtest config YAML.")
    ap.add_argument("--strategy", type=str, help=f"Registered strategy id: {sorted(STRATEGY_REGISTRY)}")
    ap.add_argument("--symbol", type=str, help="Product symbol (e.g. NQ).")
    ap.add_argument("--start-date", type=str, help="Inclusive run start, YYYY-MM-DD.")
    ap.add_argument("--end-date", type=str, help="Inclusive run end, YYYY-MM-DD.")
    ap.add_argument("--warmup-days", type=int, help="Calendar days of lead-in data (default 5).")
    ap.add_argument("--order-handling", choices=["virtual", "simulated_orders"],
                    help="Output contract. Overrides the strategy's declared default.")
    ap.add_argument("--run-window", choices=["bounded", "from_start", "all_loaded"],
                    help="engine.run(start,end) | engine.run(start) | engine.run().")
    ap.add_argument("--param", action="append", metavar="KEY=VALUE",
                    help="Typed strategy config override (repeatable).")
    ap.add_argument("--study", type=str,
                    help="Optional study contract to bind this run to. Never overrides a sealed "
                         "study's declared strategy_class.")
    ap.add_argument("--run-tag", type=str, help="Short label appended to the run id.")
    ap.add_argument("--output-dir", type=str, help="Base directory for runs (default: runs/).")
    ap.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--trader-id", type=str, help="Explicit NT trader id (default: generated).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve and print the execution plan; replay nothing.")
    ap.add_argument("--resume", action="store_true",
                    help=argparse.SUPPRESS)  # explicitly unsupported; see below
    args = ap.parse_args(argv)

    try:
        cfg: Dict[str, Any] = {}
        if args.config:
            cfg = load_backtest_config(Path(args.config))

        if args.resume:
            raise BacktestContractError(
                "UNSUPPORTED_FEATURE: --resume (DailyStateCheckpointer.verify_manifest + "
                "load_daily_checkpoint) is out of scope for B1 and no captured baseline exercises "
                "it. Run without --resume."
            )

        strategy = args.strategy or cfg.get("strategy")
        symbol = args.symbol or cfg.get("symbol")
        start_date = args.start_date or cfg.get("start_date")
        end_date = args.end_date or cfg.get("end_date")
        warmup_days = args.warmup_days if args.warmup_days is not None else int(cfg.get("warmup_days", 5))
        study = args.study or cfg.get("study")
        log_level = args.log_level or cfg.get("log_level", "ERROR")
        run_tag = args.run_tag or cfg.get("run_tag")
        output_dir = args.output_dir or cfg.get("output_dir")

        missing = [
            n for n, v in (
                ("strategy", strategy), ("symbol", symbol),
                ("start_date", start_date), ("end_date", end_date),
            ) if not v
        ]
        if missing:
            raise ConfigError(
                f"MISSING_REQUIRED_INPUT: {missing}. Supply them via --config or flags; there is "
                f"no implicit default date range, symbol, or strategy."
            )

        params = dict(cfg.get("params") or {})
        params = {k: str(v) for k, v in params.items()}
        params.update(parse_params(args.param))

        execution_mode = build_execution_mode(
            cfg.get("execution_mode"), args.order_handling, args.run_window, warmup_days
        )

        result = run_backtest_mode(
            strategy=strategy,
            symbol=symbol,
            start_date=str(start_date),
            end_date=str(end_date),
            warmup_days=warmup_days,
            order_handling=args.order_handling or (cfg.get("execution_mode") or {}).get("order_handling"),
            params=params,
            study_path=study,
            output_dir=output_dir,
            run_tag=run_tag,
            log_level=log_level,
            run_window_mode=args.run_window,
            dry_run=args.dry_run,
            trader_id=args.trader_id or cfg.get("trader_id"),
            execution_mode_override=execution_mode,
        )

        if args.dry_run:
            print(json.dumps(result, indent=2, default=str))
            return 0

        print(json.dumps(
            {
                "run_id": result["run_id"],
                "run_dir": result["run_dir"],
                "status": result["status"],
                "summary": result["summary"],
            },
            indent=2, default=str,
        ))
        return 0

    except (ConfigError, BacktestContractError, InvalidExecutionModeError,
            UnregisteredStrategyBindingError) as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 2
    except FileNotFoundError as err:
        print(f"[ERROR] MISSING_INPUT: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

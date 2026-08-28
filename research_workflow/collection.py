"""Collection adapters for governed TRAIN/OOS experiments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from research_workflow.experiment import (
    ExperimentAuthorizationError,
    assert_oos_open,
    assert_period_authorized,
    load_authorization,
    runtime_authorization,
)

# Partitioned collection is imported lazily below to keep the public collection
# module lightweight and to avoid initializing NT during planning/tests.


def _year_window(years: tuple[int, ...]) -> tuple[str, str]:
    return f"{years[0]}-01-01", f"{years[-1]}-12-31"


def collect_period(
    study_path: str | Path,
    period: str,
    *,
    run_id: Optional[str] = None,
    output_dir: str | Path | None = None,
    reuse_run: bool = True,
    execute: bool = False,
    log_level: str = "ERROR",
) -> Dict[str, Any]:
    """Resolve or execute one authorized period through the generic NT collector.

    ``execute=False`` is the safe default for orchestration/unit tests.  Execution
    requires the study's explicit date authorization to cover the requested window;
    it never bypasses the runtime chronology gate.
    """
    path = Path(study_path).resolve()
    from research_workflow.experiment import _assert_study_open
    _assert_study_open(path)
    auth = load_authorization(path)
    years = assert_period_authorized(auth, period)
    if period in {"oos", "dev"}:
        assert_oos_open(path)
    if run_id:
        return {
            "status": "REUSED",
            "period": period,
            "run_id": run_id,
            "years": list(years),
            "authorization_sha256": auth.authorization_sha256,
        }
    start, end = _year_window(years)
    if not execute:
        return {
            "status": "PLANNED",
            "period": period,
            "years": list(years),
            "start_date": start,
            "end_date": end,
            "authorization_sha256": auth.authorization_sha256,
        }
    # Keep the import lazy so importing workflow APIs does not initialize NT.
    from backtests.nt_runtime.modes.collect import run_collect_mode

    result = run_collect_mode(
        study_path=path,
        stage="full",
        output_dir=output_dir,
        log_level=log_level,
        experiment_authorization=runtime_authorization(path, period),
    )
    return {
        "status": "COLLECTED",
        "period": period,
        "years": list(years),
        "authorization_sha256": auth.authorization_sha256,
        "run": result,
    }


def build_year_partitions(study_path, period="train", **kwargs):
    from research_workflow.partitioning import build_year_partitions as _build
    return _build(study_path, period, **kwargs)


def collect_partition(study_path, partition, **kwargs):
    from research_workflow.partitioning import collect_partition as _collect
    return _collect(study_path, partition, **kwargs)


def reconcile_partitions(partitions):
    from research_workflow.partitioning import reconcile_partitions as _reconcile
    return _reconcile(partitions)


def merge_partition_outputs(frames, partitions, **kwargs):
    from research_workflow.partitioning import merge_partition_outputs as _merge
    return _merge(frames, partitions, **kwargs)


def collect_period_partitioned(study_path, period="train", *, years=None, execute=False, output_dir=None, **kwargs):
    """Collect an authorized period one bounded year partition at a time."""
    from research_workflow.partitioning import build_year_partitions, collect_partition as _collect
    partitions = build_year_partitions(study_path, period, years=years)
    if not execute:
        results = [_collect(study_path, partition, execute=False, output_dir=output_dir, **kwargs) for partition in partitions]
    else:
        # NautilusTrader's Rust logger is process-global and cannot be initialized
        # twice in one interpreter.  Isolate each year so partitioning is genuinely
        # memory-bounded and a completed engine cannot poison the next partition.
        from concurrent.futures import ProcessPoolExecutor
        jobs = [(str(study_path), partition, output_dir, kwargs) for partition in partitions]
        # NautilusTrader's Rust logger is process-global and cannot be initialized
        # twice in one interpreter.  A single pool with max_workers=1 still reuses
        # that worker across years, so the second partition panics while installing
        # the logger.  Create and tear down one worker process per partition.
        results = []
        for job in jobs:
            with ProcessPoolExecutor(max_workers=1) as pool:
                results.append(pool.submit(_collect_partition_worker, job).result())
    return {"period": period, "partition_count": len(partitions), "partitions": results,
            "status": "COLLECTED" if execute else "PLANNED"}


def _collect_partition_worker(args):
    study_path, partition, output_dir, kwargs = args
    from research_workflow.partitioning import collect_partition as _collect
    return _collect(study_path, partition, execute=True, output_dir=output_dir, **kwargs)

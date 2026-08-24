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

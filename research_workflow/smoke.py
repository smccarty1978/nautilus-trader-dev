"""Structured NT smoke API."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Iterable

def run_smoke(study_path: str | Path, authorized_dates: Iterable[str], **kwargs: Any) -> dict[str, Any]:
    """Execute the bounded generic collector and return structured validation."""
    from backtests.nt_runtime.modes.collect import run_collect_mode
    from scripts.validate_smoke import validate_smoke_run
    study = Path(study_path).resolve()
    date = next(iter(authorized_dates), None)
    if not date:
        raise ValueError("authorized_dates must contain at least one date")
    repo_root = study.parents[1]
    kwargs.setdefault("output_dir", repo_root / "runs")
    run_result = run_collect_mode(study, stage="day", date_override=date, **kwargs)
    run_dir = None
    if isinstance(run_result, dict):
        run_dir = run_result.get("run_dir") or run_result.get("output_dir")
    validation = validate_smoke_run(study, run_dir=Path(run_dir) if run_dir else None,
                                    expected_smoke_date=date, repo_root=repo_root)
    return {"status": "PASS" if validation.get("passed", validation.get("status") == "ACCEPTED") else "FAIL",
            "run": run_result, "validation": validation}

__all__ = ["run_smoke"]

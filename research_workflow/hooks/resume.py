from pathlib import Path
from typing import Any
from research_workflow.workflow_engine import run_workflow
def resume_study(study: str | Path, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("smoke", True)
    kwargs.setdefault("execute_authorized", True)
    return run_workflow(study, **kwargs)
def resume_affected_studies(root: str | Path = "studies", **kwargs: Any) -> list[dict[str, Any]]:
    return [resume_study(p, **kwargs) for p in Path(root).iterdir() if p.is_dir() and (p / "research_decision.yaml").exists()]

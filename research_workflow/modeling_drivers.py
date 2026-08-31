"""Fail-closed detection of undeclared study-local modeling drivers (RT-01).

A study-local ``implementation/*.py`` module that imports a *governed modeling API*
participates in the governed fit / model-selection / TRAIN-freeze path. Its bytes must
therefore be declared in ``ExecutionSpec.modeling_driver_relpaths`` so
``research_workflow.modeling_closure.resolve_modeling_closure`` folds them (and their
transitive import closure) into ``MODELING_EXECUTION_CLOSURE``. An **undeclared**
participant is an under-invalidation hole: a study could edit the code that chooses the
chronology roles, the binary population, the seed, the arm construction or the fit call,
and neither the TRAIN freeze nor the OOS gate would notice.

This module does **not** discover and hash arbitrary implementation files. It statically
scans ``implementation/*.py`` for an import of one of a small fixed set of governed
modeling modules and, if such a file is not in the declared list, raises **before** the
fit. The declaration stays explicit; a driver that reaches a governed API through
``importlib`` or a re-export is outside what a static scan can see and is the study
author's responsibility (the same honest limit the execution-manifest AST closure
carries).

``research.analysis.modeling`` is deliberately **not** a trigger: pure pre-/post-fit
diagnostics (feasibility probes, OOS diagnostics) legitimately call its lower-level
``fit_model`` without touching the governed freeze, and forcing them into the modeling
closure would stale the TRAIN freeze on a diagnostic-only edit -- the opposite of what
RT-01 asks for.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List

# Importing any of these from a study-local module means "this module participates in the
# governed fit / selection / freeze". Keep this list minimal and explicit.
GOVERNED_MODELING_MODULES = (
    "research_workflow.modeling",
    "research_workflow.model_selection",
    "research_workflow.modeling_closure",
    "research_workflow.gates",
)


class UndeclaredModelingDriverError(RuntimeError):
    """A study-local module imports a governed modeling API but is not declared in
    ``execution.modeling_driver_relpaths``."""


def _is_governed(module_name: str) -> bool:
    return any(
        module_name == m or module_name.startswith(m + ".")
        for m in GOVERNED_MODELING_MODULES
    )


def _imports_governed_modeling(py_path: Path) -> bool:
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        # An unparseable implementation file cannot be proven safe -- treat it as a
        # participant so it must be declared (fail closed).
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_governed(alias.name) for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            # `from research_workflow.modeling import ...` (level 0). Relative imports
            # (level > 0) inside a study's implementation/ never reach a governed module.
            if node.level == 0 and _is_governed(node.module or ""):
                return True
    return False


def find_participating_modeling_modules(study_dir: str | Path) -> List[str]:
    """Study-relative posix paths of ``implementation/*.py`` modules that import a
    governed modeling API. ``__init__.py`` is skipped."""
    study_dir = Path(study_dir).resolve()
    impl = study_dir / "implementation"
    if not impl.is_dir():
        return []
    out: List[str] = []
    for py in sorted(impl.rglob("*.py")):
        if py.name == "__init__.py" or "__pycache__" in py.parts:
            continue
        if _imports_governed_modeling(py):
            out.append(py.relative_to(study_dir).as_posix())
    return out


def assert_declared_modeling_drivers(
    study_dir: str | Path, declared_relpaths: Iterable[str] | None
) -> List[str]:
    """Raise :class:`UndeclaredModelingDriverError` if a study-local module participates
    in governed modeling without being declared in ``modeling_driver_relpaths``.

    Returns the list of participating modules on success (may be empty).
    """
    declared = {Path(str(r)).as_posix() for r in (declared_relpaths or [])}
    participating = find_participating_modeling_modules(study_dir)
    undeclared = [rel for rel in participating if rel not in declared]
    if undeclared:
        raise UndeclaredModelingDriverError(
            "MODELING_DRIVER_UNDECLARED: study-local modules import a governed modeling "
            f"API (one of {list(GOVERNED_MODELING_MODULES)}) but are not declared in "
            f"execution.modeling_driver_relpaths: {undeclared}. Declare them in study.yaml "
            "(they then enter MODELING_EXECUTION_CLOSURE and a modeling-only edit stales "
            "the TRAIN freeze) or remove the governed import."
        )
    return participating


__all__ = [
    "GOVERNED_MODELING_MODULES",
    "UndeclaredModelingDriverError",
    "assert_declared_modeling_drivers",
    "find_participating_modeling_modules",
]

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
import re
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


def _study_local_path(study: Path, source: Path, value: str) -> Path | None:
    """Resolve a literal study-local module/script without guessing external imports."""
    raw = Path(value)
    candidates = []
    if raw.suffix in {".py", ".sh"}:
        candidates.extend([study / raw, source.parent / raw])
    else:
        dotted = value.replace(".", "/")
        candidates.extend([study / f"{dotted}.py", study / dotted / "__init__.py"])
        if value.startswith("implementation."):
            candidates.append(study / f"{dotted}.py")
    for candidate in candidates:
        candidate = candidate.resolve()
        try:
            candidate.relative_to(study)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _executed_local_helpers(study: Path, path: Path) -> tuple[set[Path], list[str]]:
    """Declared-driver detector: direct imports, literal dynamic imports and entrypoints.

    This is deliberately a fail-safe detector, not dependency authority.  It recognizes
    only literal local targets. A dynamic/non-literal execution path is itself rejected:
    it cannot be closure-bound honestly.
    """
    if path.suffix == ".sh":
        helpers, errors = set(), []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"(?:python(?:3)?|py)\s+['\"]?([^'\"\s;]+)", line)
            if match:
                target = _study_local_path(study, path, match.group(1))
                if target is None: errors.append(f"MODELING_DRIVER_SHELL_ENTRYPOINT_UNRESOLVED:{path.name}")
                else: helpers.add(target)
        return helpers, errors
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return set(), [f"MODELING_DRIVER_UNPARSEABLE:{path}"]
    helpers, errors = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _study_local_path(study, path, alias.name)
                if target: helpers.add(target)
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            for alias in node.names:
                rel = ("." * node.level) + ((node.module + ".") if node.module else "") + alias.name
                # Relative resolution is delegated to the normal AST closure; also bind
                # the obvious sibling helper for the declaration detector.
                target = _study_local_path(study, path, f"{alias.name}.py")
                if target: helpers.add(target)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                target = _study_local_path(study, path, f"{node.module}.{alias.name}")
                if target: helpers.add(target)
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Attribute): name = node.func.attr
            elif isinstance(node.func, ast.Name): name = node.func.id
            if name in {"import_module", "__import__"}:
                value = _literal(node.args[0]) if node.args else None
                if value is None: errors.append(f"MODELING_DRIVER_DYNAMIC_IMPORT_UNRESOLVED:{path.name}")
                else:
                    target = _study_local_path(study, path, value)
                    if target: helpers.add(target)
            elif name in {"run", "call", "check_call", "check_output", "Popen"}:
                if not node.args: continue
                arg = node.args[0]
                values = [ _literal(x) for x in arg.elts ] if isinstance(arg, (ast.List, ast.Tuple)) else []
                if len(values) < 2 or any(v is None for v in values[1:]):
                    errors.append(f"MODELING_DRIVER_SUBPROCESS_UNRESOLVED:{path.name}")
                    continue
                for value in values[1:]:
                    target = _study_local_path(study, path, value)
                    if target:
                        helpers.add(target)
    return helpers, errors


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
    study = Path(study_dir).resolve()
    declared = {Path(str(r)).as_posix() for r in (declared_relpaths or [])}
    declared_paths = set()
    for rel in declared:
        path = (study / rel).resolve()
        try:
            path.relative_to(study)
        except ValueError as exc:
            raise UndeclaredModelingDriverError(f"MODELING_DRIVER_PATH_ESCAPES_STUDY:{rel}") from exc
        if not path.is_file():
            raise UndeclaredModelingDriverError(f"MODELING_DRIVER_DECLARED_MISSING:{rel}")
        declared_paths.add(path)
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
    pending = list(declared_paths)
    seen: set[Path] = set()
    errors: list[str] = []
    missing_helpers: list[str] = []
    while pending:
        path = pending.pop()
        if path in seen: continue
        seen.add(path)
        helpers, scan_errors = _executed_local_helpers(study, path)
        errors.extend(scan_errors)
        for helper in helpers:
            rel = helper.relative_to(study).as_posix()
            if rel not in declared:
                missing_helpers.append(rel)
            else:
                pending.append(helper)
    if errors or missing_helpers:
        raise UndeclaredModelingDriverError(
            "MODELING_DRIVER_UNDECLARED: declared modeling execution reaches undeclared "
            f"helper(s) {sorted(set(missing_helpers))} or unresolvable dynamic/subprocess "
            f"entrypoint(s) {sorted(set(errors))}"
        )
    return participating


__all__ = [
    "GOVERNED_MODELING_MODULES",
    "UndeclaredModelingDriverError",
    "assert_declared_modeling_drivers",
    "find_participating_modeling_modules",
]

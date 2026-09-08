"""Analysis-operation registration boundary.

This module is the stable resolution API for declarative analysis: the compiler asks it
which extra frames a step must bind, and the ``analyze`` stage asks it to run one.  Both
import *this* module; neither imports an operation's implementation.

It is a **registration boundary** (``docs/RESEARCH_WORKFLOW.md`` §21.14): every operation is
discovered through the declared capability index
(``research_workflow/capabilities_index.d/analysis_ops.yaml``, which ``cap generate --check``
verifies) and its implementation is imported by the dotted path the index carries.  Nothing
here statically imports
``research.analysis.diagnostic_ops`` or any other implementation module, which is what makes
"adding an operation cannot change how an existing one resolves" a fact about the import
graph rather than a claim.

Adding an operation is therefore: one function in an implementation module, one seed entry
declaring its id, ``implementation``, ``inputs`` and ``needs_context``.  No edit here.

The same lazy, resolve-on-access shape as ``features/trackers/host_bindings.py`` (trackers)
and ``features/registry.py`` (feature definitions).
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple

_INDEX_PATH = (Path(__file__).resolve().parents[2] / "research_workflow" / "capabilities_index.d"
               / "analysis_ops.yaml")
_KIND = "analysis_ops"


class AnalysisOpError(RuntimeError):
    pass


def _seed(index_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Declared analysis operations, keyed by capability id, straight from the index."""
    import yaml
    path = Path(index_path) if index_path is not None else _INDEX_PATH
    try:
        seed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AnalysisOpError(f"ANALYSIS_OP_INDEX_UNREADABLE: {path}: {exc}") from exc
    out: Dict[str, Dict[str, Any]] = {}
    for entry in seed.get(_KIND) or []:
        op = str(entry.get("id") or "")
        if op:
            out[op] = entry
    if not out:
        raise AnalysisOpError(f"ANALYSIS_OP_INDEX_EMPTY: {path} declares no {_KIND}")
    return out


def known_ops(index_path: Optional[Path] = None) -> FrozenSet[str]:
    """Every registered operation id."""
    return frozenset(_seed(index_path))


def op_inputs(op: str, index_path: Optional[Path] = None) -> Tuple[str, ...]:
    """The extra frames this operation consumes besides its primary ``rows`` input.

    The compiler reads this to prove a declared step's inputs are bound before the study is
    ever executed.  An unregistered id resolves to no inputs so the compiler reports the
    unknown-capability gap it already reports, not a resolution error on top of it.
    """
    entry = _seed(index_path).get(op)
    return tuple(str(name) for name in (entry.get("inputs") or ())) if entry else ()


def context_ops(index_path: Optional[Path] = None) -> FrozenSet[str]:
    """Operations needing machine-local resolution context.

    Never part of the plan identity: where an operator keeps their files is not a
    scientific fact.
    """
    return frozenset(op for op, entry in _seed(index_path).items() if bool(entry.get("needs_context")))


def op_implementation(op: str, index_path: Optional[Path] = None) -> Callable[..., Dict[str, Any]]:
    """Import and return the callable the index binds this operation id to."""
    entry = _seed(index_path).get(op)
    if entry is None:
        raise AnalysisOpError(f"ANALYSIS_OP_UNKNOWN: {op!r}; known={sorted(_seed(index_path))}")
    dotted = str(entry.get("implementation") or "")
    module, _, attr = dotted.rpartition(".")
    if not module or not attr:
        raise AnalysisOpError(f"ANALYSIS_OP_IMPLEMENTATION_INVALID: {op} declares implementation {dotted!r}")
    try:
        fn = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as exc:
        raise AnalysisOpError(f"ANALYSIS_OP_IMPLEMENTATION_UNRESOLVED: {op} -> {dotted}: {exc}") from exc
    if not callable(fn):
        raise AnalysisOpError(f"ANALYSIS_OP_IMPLEMENTATION_NOT_CALLABLE: {op} -> {dotted}")
    return fn


def implementation_files(ops: Any, index_path: Optional[Path] = None) -> Tuple[str, ...]:
    """Repo-relative files implementing the given operation ids, for the execution closure.

    A dynamically resolved implementation is invisible to the closure's import walk, so the
    compiler seeds it explicitly -- exactly as it seeds the modules a tracker binding names.
    Unknown ids contribute nothing; the compiler gaps them separately.
    """
    seed = _seed(index_path)
    repo_root = Path(__file__).resolve().parents[2]
    out = set()
    for op in ops:
        entry = seed.get(str(op))
        if entry is None:
            continue
        module = str(entry.get("implementation") or "").rpartition(".")[0]
        if not module:
            continue
        candidate = repo_root.joinpath(*module.split("."))
        for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
            if path.is_file():
                out.add(path.resolve().relative_to(repo_root.resolve()).as_posix())
                break
    return tuple(sorted(out))


def run_op(op: str, rows: Any, *, inputs: Mapping[str, Any] | None = None,
           params: Mapping[str, Any] | None = None,
           context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    seed = _seed()
    if op not in seed:
        raise AnalysisOpError(f"ANALYSIS_OP_UNKNOWN: {op!r}; known={sorted(seed)}")
    kwargs = dict(params or {})
    if op in context_ops():
        kwargs["context"] = dict(context or {})
    for name in op_inputs(op):
        if name not in (inputs or {}):
            raise AnalysisOpError(f"ANALYSIS_OP_INPUT_MISSING: {op} needs input {name!r}")
        kwargs[name] = (inputs or {})[name]
    return op_implementation(op)(rows, **kwargs)


__all__ = ["AnalysisOpError", "known_ops", "op_inputs", "context_ops", "op_implementation",
           "implementation_files", "run_op"]

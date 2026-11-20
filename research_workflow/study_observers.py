"""Study-local causal observers: the governed exception to the V2 "zero Python" rule (WORKFLOW.md §Q, P3).

A study may declare ``context.<name>: {tracker: "study_local:<module>", bars: <stream>, ...}``. The compiler then
loads ``studies/<study_id>/observers/<module>.py`` instead of a registered tracker. That observer:

* is a ``features.trackers.base.BaseBinding`` subclass with ``CAPABILITY = "study_local.<module>"``. It runs inside the
  same HostCore event loop as every registered tracker and sees only completed bars in ``ts_init`` order;
* declares ``AVAILABILITY = "bar_close"``: every field is published at the ``ts_init`` of the last ingested bar;
* declares ``MAX_STATE_ITEMS``: an explicit bound on the number of container items it keeps;
* consumes streams only (``INPUTS`` of kind ``stream``), never another tracker, a file or a dataset;
* imports only the allow-list below. No pandas / polars / pyarrow, no file or OS access, no ``importlib`` or ``sys``,
  no ``studies.*`` imports, no relative imports, no ``open`` / ``eval`` / ``exec`` / ``__import__``;
* passes the generated causality harness (:func:`causality_check`) at compile time: determinism, prefix invariance,
  future perturbation at several cuts, scalar fields, and the declared state bound;
* is bound to its own study. The plan's implementation ref names the study id and the path, and the host refuses to
  load it for any other study. Reuse by another study requires promotion through the capability flow (§M.3).

The observer file is hashed into the study's closure like any bound module, so editing it stales the seal.
"""
from __future__ import annotations

import ast
import importlib.util
import math
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

PREFIX = "study_local:"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_IMPORTS = {
    "__future__", "math", "collections", "dataclasses", "typing", "bisect", "heapq", "itertools", "functools",
    "statistics", "enum", "numpy", "features.trackers.base", "research_workflow.host.interfaces",
}
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "input", "breakpoint", "setattr", "delattr"}
FORBIDDEN_ATTRS = {"read_parquet", "read_csv", "shift", "rolling", "iloc", "loc", "path"}
AVAILABILITY_VALUES = ("bar_close",)
NS = 1_000_000_000


class ObserverError(ValueError):
    """A study-local observer is refused. ``code`` is stable; the message says what to fix."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def observer_name(tracker: str) -> Optional[str]:
    return tracker[len(PREFIX):] if str(tracker).startswith(PREFIX) else None


def observer_file(study_dir: Path, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ObserverError("OBSERVER_NAME_INVALID", f"{name!r}: use a lower-case identifier; a study-local observer is named, never a path")
    return Path(study_dir) / "observers" / f"{name}.py"


def static_violations(source: str) -> List[str]:
    """AST check of the isolation rules. It is conservative by construction: anything not on the allow-list is refused."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]
    out: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS and a.name.split(".")[0] not in {"math", "numpy"}:
                    out.append(f"import {a.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                out.append("relative imports are not allowed (an observer may not import other study code)")
            elif node.module not in ALLOWED_IMPORTS:
                out.append(f"from {node.module} import ... is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            out.append(f"call {node.func.id}() is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            out.append(f"attribute .{node.attr} is not allowed (retrospective table access / paths)")
        elif isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            out.append(f"name {node.id} is not allowed")
    return sorted(set(out))


def _module_name(study_id: str, name: str) -> str:
    return f"_nt_study_local.{re.sub(r'[^A-Za-z0-9_]', '_', study_id)}.{name}"


def load_observer(path: Path, study_id: str, name: str) -> type:
    """Static check, import from the file and validate the class declarations. The module name embeds the study id,
    so two studies can never share one module object."""
    from features.trackers.base import BaseBinding

    path = Path(path)
    if not path.is_file():
        raise ObserverError("OBSERVER_NOT_FOUND", f"{path} does not exist (expected studies/<id>/observers/{name}.py)")
    if path.parent.name != "observers" or path.parent.parent.name != study_id or path.stem != name:
        raise ObserverError("OBSERVER_OUTSIDE_STUDY", f"{path} is not studies/{study_id}/observers/{name}.py")
    bad = static_violations(path.read_text(encoding="utf-8"))
    if bad:
        raise ObserverError("OBSERVER_ISOLATION_VIOLATION", "; ".join(bad))
    mod_name = _module_name(study_id, name)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    want = f"study_local.{name}"
    classes = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BaseBinding) and v is not BaseBinding
               and v.__module__ == mod_name]
    matching = [c for c in classes if getattr(c, "CAPABILITY", "") == want]
    if len(matching) != 1:
        raise ObserverError("OBSERVER_CLASS_INVALID", f"{path.name} must define exactly one BaseBinding subclass with CAPABILITY = {want!r}")
    cls = matching[0]
    if getattr(cls, "AVAILABILITY", None) not in AVAILABILITY_VALUES:
        raise ObserverError("OBSERVER_AVAILABILITY_UNDECLARED", f"{cls.__name__}.AVAILABILITY must be one of {AVAILABILITY_VALUES}")
    bound = getattr(cls, "MAX_STATE_ITEMS", None)
    if not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
        raise ObserverError("OBSERVER_STATE_UNBOUNDED", f"{cls.__name__}.MAX_STATE_ITEMS must be a positive int")
    if not cls.FIELDS:
        raise ObserverError("OBSERVER_CLASS_INVALID", f"{cls.__name__} declares no FIELDS")
    non_stream = [k for k, v in cls.INPUTS.items() if v.rstrip("?") != "stream"]
    if non_stream or not cls.INPUTS:
        raise ObserverError("OBSERVER_INPUTS_INVALID", f"{cls.__name__} must consume streams only (got {dict(cls.INPUTS)})")
    if cls.EVENTS or cls.SUBSCRIBES or cls.EPOCH_FIELDS or getattr(cls, "NEEDS_STUDIES_ROOT", False):
        raise ObserverError("OBSERVER_CLASS_INVALID", "an observer publishes FIELDS only (no EVENTS / SUBSCRIBES / EPOCH_FIELDS / studies_root)")
    return cls


def implementation_ref(study_id: str, path: Path, repo_root: Path, cls: type) -> str:
    try:
        rel = Path(path).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        rel = Path(path).resolve().as_posix()
    return f"{PREFIX}{study_id}:{rel}:{cls.__name__}"


def resolve_implementation(ref: str, *, plan_study_id: Optional[str], repo_root: Path) -> type:
    """Host-side load of a ``study_local:<study_id>:<path>:<Class>`` implementation ref. Refused for any other study."""
    body = ref[len(PREFIX):]
    study_id, _, rest = body.partition(":")
    path_s, _, cls_name = rest.rpartition(":")
    if plan_study_id is None or study_id != plan_study_id:
        raise ObserverError("OBSERVER_CROSS_STUDY_IMPORT", f"observer of study {study_id!r} cannot run in study {plan_study_id!r}; promote it (§M.3)")
    p = Path(path_s)
    if not p.is_absolute():
        p = Path(repo_root) / p
    cls = load_observer(p, study_id, p.stem)
    if cls.__name__ != cls_name:
        raise ObserverError("OBSERVER_CLASS_INVALID", f"{p} defines {cls.__name__}, plan names {cls_name}")
    return cls


def bound_observer_files(study_dir: Path, plan: Mapping[str, Any]) -> set:
    """Study-relative paths (``observers/<name>.py``) of the observers the compiled plan binds for THIS study. Used by the
    zero-study-Python check (R10 / ZERO_STUDY_PYTHON); a file is exempt only while the current plan binds it."""
    study_dir = Path(study_dir)
    study_id = (plan.get("study") or {}).get("id")
    out = set()
    for t in plan.get("trackers") or []:
        ref = str(t.get("implementation") or "")
        if not ref.startswith(PREFIX):
            continue
        sid, _, rest = ref[len(PREFIX):].partition(":")
        path_s = rest.rpartition(":")[0]
        name = Path(path_s).stem
        if sid != study_id or sid != study_dir.name or not NAME_RE.match(name) or Path(path_s).parent.name != "observers":
            continue
        if Path(path_s).parent.parent.name == sid:
            out.add(f"observers/{name}.py")
    return out


# --------------------------------------------------------------------------- generated causality harness
def synthetic_tape(n_sessions: int = 3, seconds: int = 1500, seed: int = 20261120, stream: str = "obs") -> list:
    """Deterministic 1 s tape: sessions separated by an overnight gap, irregular intra-session gaps, zero-volume rows,
    trending and reversing price."""
    from research_workflow.host.interfaces import BarView

    rng = random.Random(seed)
    out = []
    t0 = 1_893_456_000 * NS
    for s in range(n_sessions):
        t = t0 + s * 86_400 * NS
        px = 20_000.0
        drift = rng.choice([-0.05, 0.0, 0.05])
        for _ in range(seconds):
            o = px
            px = round(px + drift + rng.choice([-0.5, -0.25, 0.0, 0.25, 0.5]), 2)
            vol = float(rng.choice([0, 0, 1, 2, 5, 13, 40]))
            out.append(BarView(stream, t, t + NS, o, max(o, px) + 0.25, min(o, px) - 0.25, px, vol))
            t += rng.choice([1, 1, 1, 2, 3, 7]) * NS
    return out


def _perturb(bars: list, cut: int, seed: int) -> list:
    from research_workflow.host.interfaces import BarView

    rng = random.Random(seed)
    out = list(bars[:cut + 1])
    for b in bars[cut + 1:]:
        k = rng.uniform(-3.0, 3.0)
        o, c = b.open + k, b.close - k
        out.append(BarView(b.stream, b.ts_event, b.ts_init, o, max(o, c, b.high + abs(k)), min(o, c, b.low - abs(k)), c,
                           float(rng.choice([0, 3, 17, 250]))))
    return out


def _items(obj: Any, depth: int = 0) -> int:
    if depth > 6:
        return 0
    if isinstance(obj, Mapping):
        return len(obj) + sum(_items(v, depth + 1) for v in obj.values())
    if isinstance(obj, (list, tuple, set, frozenset)) or type(obj).__name__ == "deque":
        return len(obj) + sum(_items(v, depth + 1) for v in obj)
    if hasattr(obj, "shape") and hasattr(obj, "size"):
        return int(obj.size)
    return 0


def _norm(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return "NaN"
    return v


def _run(cls: type, params: Mapping[str, Any], bars: list, every: int = 1) -> Tuple[List[tuple], int]:
    inputs = {k: "obs" for k in cls.INPUTS}
    obj = cls(dict(params), inputs)
    key = next(iter(cls.INPUTS))
    snaps, peak = [], 0
    for i, b in enumerate(bars):
        obj.on_bar(key, b)
        snaps.append(tuple(_norm(getattr(obj, f, None)) for f in cls.FIELDS))
        if i % every == 0:
            peak = max(peak, _items({k: v for k, v in vars(obj).items() if k not in ("params", "inputs", "_events")}))
    return snaps, peak


def causality_check(cls: type, params: Mapping[str, Any]) -> Dict[str, Any]:
    """Generated harness every study-local observer must pass at compile time. Returns a compact JSON-able report;
    ``passed`` is False with the first failing check named."""
    tape = synthetic_tape()
    report: Dict[str, Any] = {"bars": len(tape), "checks": {}, "passed": False}
    try:
        full, peak = _run(cls, params, tape, every=25)
        again, _ = _run(cls, params, tape, every=10**9)
    except Exception as exc:  # the observer crashed on ordinary input
        report["failure"] = f"OBSERVER_RUNTIME_ERROR: {type(exc).__name__}: {exc}"
        return report
    report["checks"]["deterministic"] = full == again
    scalar = all(isinstance(v, (int, float, bool, str)) or v is None for row in full for v in row)
    report["checks"]["scalar_fields"] = scalar
    report["checks"]["state_bound"] = {"peak_items": peak, "declared": int(cls.MAX_STATE_ITEMS), "ok": peak <= int(cls.MAX_STATE_ITEMS)}
    prefix_ok, future_ok = True, True
    for j, frac in enumerate((0.2, 0.5, 0.8)):
        cut = int(len(tape) * frac)
        pre, _ = _run(cls, params, tape[:cut + 1], every=10**9)
        prefix_ok &= pre == full[:cut + 1]
        pert, _ = _run(cls, params, _perturb(tape, cut, seed=j + 1), every=10**9)
        future_ok &= pert[:cut + 1] == full[:cut + 1]
    report["checks"]["prefix_invariance"] = prefix_ok
    report["checks"]["future_perturbation"] = future_ok
    varies = len({repr(row) for row in full}) > 1
    report["checks"]["fields_vary"] = varies
    order = ["deterministic", "scalar_fields", "prefix_invariance", "future_perturbation", "fields_vary"]
    for name in order:
        if not report["checks"][name]:
            report["failure"] = f"OBSERVER_{name.upper()}_FAILED"
            return report
    if not report["checks"]["state_bound"]["ok"]:
        report["failure"] = f"OBSERVER_STATE_BOUND_EXCEEDED: peak {peak} > MAX_STATE_ITEMS {cls.MAX_STATE_ITEMS}"
        return report
    report["passed"] = True
    return report


__all__ = ["PREFIX", "ObserverError", "observer_name", "observer_file", "static_violations", "load_observer",
           "implementation_ref", "resolve_implementation", "bound_observer_files", "synthetic_tape", "causality_check"]

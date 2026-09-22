"""``analysis.derive.columns`` -- declared, row-wise, whitelisted column derivation.

The governed replacement for the arithmetic a study-local pandas script used to do between the
collected frame and its tables: signed/absolute distances, direction-dependent level choice,
normalized positions with a null rule, milestone-before-terminal flags, fixed-edge buckets.
Every column is a string in the bounded grammar of ``research.analysis.expressions`` -- parsed,
never ``eval``-ed -- and the step performs no aggregation and never reads another row.

Params::

    columns:  [{name, expr}, {name, expr, each: {var: [values]}}, ...]   # evaluated in order;
              # a later column may read an earlier one; an existing column is never overwritten
    keep:     <boolean expression>   # optional row filter, applied AFTER the columns: rows where it
              # is true are kept, false and NULL rows are dropped and counted
    div_zero: null | error           # a / 0 -> NULL (default) or refuse the step
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd

from research.analysis.expressions import (Evaluator, ExpressionError, definition_sha256, expand_columns,
                                           parse, referenced_columns)
from research.analysis.ops import AnalysisOpError


def derive_columns(rows: pd.DataFrame, *, columns: Sequence[Mapping[str, Any]], keep: Optional[str] = None,
                   div_zero: str = "null") -> Dict[str, Any]:
    if div_zero not in ("null", "error"):
        raise AnalysisOpError(f"ANALYSIS_DERIVE_DIV_ZERO_INVALID: {div_zero!r} (null | error)")
    try:
        pairs = expand_columns(columns)
    except ExpressionError as exc:
        raise AnalysisOpError(f"ANALYSIS_DERIVE_INVALID: {exc}") from exc
    frame = rows.copy()
    definitions = []
    for name, expr in pairs:
        if name in frame.columns:
            raise AnalysisOpError(f"ANALYSIS_DERIVE_COLUMN_EXISTS: {name!r}; a derived column never overwrites one")
        try:
            ast = parse(expr)
            missing = sorted(referenced_columns(ast) - set(frame.columns))
            if missing:
                raise ExpressionError(f"DERIVE_COLUMN_UNKNOWN: {name} references {missing}")
            ev = Evaluator(frame, div_zero=div_zero)
            value = ev.materialize(ev.eval(ast))
        except ExpressionError as exc:
            raise AnalysisOpError(f"ANALYSIS_DERIVE_FAILED: {name}: {exc}") from exc
        frame[name] = value.to_numpy() if value.dtype == object else value
        definitions.append({"name": name, "expr": expr, "definition_sha256": definition_sha256(ast),
                            "n_null": int(pd.isna(frame[name]).sum())})
    n_in = int(len(frame))
    kept_info = None
    if keep is not None:
        try:
            ast = parse(str(keep))
            ev = Evaluator(frame, div_zero=div_zero)
            mask = ev.as_bool(ev.eval(ast))
        except ExpressionError as exc:
            raise AnalysisOpError(f"ANALYSIS_DERIVE_FAILED: keep: {exc}") from exc
        true = mask.fillna(False).to_numpy(dtype=bool)
        kept_info = {"expr": str(keep), "definition_sha256": definition_sha256(ast), "kept": int(true.sum()),
                     "dropped_false": int((mask == False).fillna(False).sum()),  # noqa: E712 (nullable boolean)
                     "dropped_null": int(mask.isna().sum())}
        frame = frame[true].reset_index(drop=True)
    payload = {"schema_version": 1, "n_in": n_in, "n_out": int(len(frame)), "div_zero": div_zero,
               "columns": definitions, "keep": kept_info}
    return {"frame": frame, "payload": payload}


__all__ = ["derive_columns"]

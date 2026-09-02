#!/usr/bin/env python3
"""Frame parity: identical primary keys, identical values within declared tolerance, and the
EARLIEST divergence localized (timestamp, key, column, reference vs runtime).

Used by every parity shape.  Numeric columns compare with an absolute tolerance
(default 1e-9); everything else compares exactly (None == NaN).  Reports never stop at
the first mismatch: counts per column are always complete, the first divergence is
just the pointer for ``find_first_parity_divergence``-style triage.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]


def _is_null(v: Any) -> bool:
    if v is None:
        return True
    try:
        return isinstance(v, float) and math.isnan(v)
    except TypeError:
        return False


def compare_frames(reference: pd.DataFrame, runtime: pd.DataFrame, *, key: Sequence[str] = KEY, tolerance: float = 1e-9,
                   columns: Optional[Sequence[str]] = None, ignore: Sequence[str] = ()) -> Dict[str, Any]:
    ref = reference.copy()
    run = runtime.copy()
    for k in key:
        if k not in ref.columns or k not in run.columns:
            return {"passed": False, "error": f"KEY_COLUMN_MISSING: {k}", "reference_rows": len(ref), "runtime_rows": len(run)}
    ref_keys = set(map(tuple, ref[list(key)].astype("int64").itertuples(index=False, name=None)))
    run_keys = set(map(tuple, run[list(key)].astype("int64").itertuples(index=False, name=None)))
    only_ref = sorted(ref_keys - run_keys)
    only_run = sorted(run_keys - ref_keys)
    dup_ref = int(ref.duplicated(list(key)).sum())
    dup_run = int(run.duplicated(list(key)).sum())
    ref = ref.set_index(list(key)).sort_index()
    run = run.set_index(list(key)).sort_index()
    common = ref.index.intersection(run.index)
    ref_c = ref.loc[common]
    run_c = run.loc[common]
    cols = [c for c in (columns or ref.columns) if c not in ignore]
    missing_cols = [c for c in cols if c not in run_c.columns]
    cols = [c for c in cols if c in run_c.columns]
    per_column: Dict[str, Dict[str, Any]] = {}
    first: Optional[Dict[str, Any]] = None
    mismatch_rows_total = 0
    for c in cols:
        a = ref_c[c].to_numpy()
        b = run_c[c].to_numpy()
        numeric = pd.api.types.is_numeric_dtype(ref_c[c]) and pd.api.types.is_numeric_dtype(run_c[c])
        if numeric:
            af = pd.to_numeric(ref_c[c], errors="coerce").to_numpy(dtype="float64")
            bf = pd.to_numeric(run_c[c], errors="coerce").to_numpy(dtype="float64")
            both_nan = np.isnan(af) & np.isnan(bf)
            diff = np.abs(af - bf)
            bad = ~both_nan & ~(diff <= tolerance)
            max_abs = float(np.nanmax(diff)) if len(diff) and not np.all(np.isnan(diff)) else 0.0
        else:
            an = np.array([None if _is_null(x) else x for x in a], dtype=object)
            bn = np.array([None if _is_null(x) else x for x in b], dtype=object)
            bad = an != bn
            max_abs = None
        n_bad = int(bad.sum())
        per_column[c] = {"mismatches": n_bad, "max_abs_diff": max_abs}
        if n_bad:
            mismatch_rows_total += n_bad
            idx = int(np.argmax(bad))
            k = common[idx]
            cand = {"timestamp": int(k[0]), "key": [int(x) for x in k], "column": c,
                    "reference": None if _is_null(a[idx]) else (a[idx].item() if hasattr(a[idx], "item") else a[idx]),
                    "runtime": None if _is_null(b[idx]) else (b[idx].item() if hasattr(b[idx], "item") else b[idx])}
            if first is None or cand["timestamp"] < first["timestamp"]:
                first = cand
    if only_ref and (first is None or only_ref[0][0] < first["timestamp"]):
        first = {"timestamp": int(only_ref[0][0]), "key": [int(x) for x in only_ref[0]], "column": "<row>", "reference": "present", "runtime": "missing"}
    if only_run and (first is None or only_run[0][0] < first["timestamp"]):
        first = {"timestamp": int(only_run[0][0]), "key": [int(x) for x in only_run[0]], "column": "<row>", "reference": "missing", "runtime": "present"}
    passed = not only_ref and not only_run and not missing_cols and mismatch_rows_total == 0 and dup_ref == 0 and dup_run == 0
    return {"passed": passed, "reference_rows": int(len(reference)), "runtime_rows": int(len(runtime)),
            "common_rows": int(len(common)), "only_in_reference": len(only_ref), "only_in_runtime": len(only_run),
            "duplicate_keys": {"reference": dup_ref, "runtime": dup_run}, "missing_columns": missing_cols,
            "columns_compared": len(cols), "value_mismatches": mismatch_rows_total,
            "per_column": {c: v for c, v in per_column.items() if v["mismatches"]},
            "first_divergence": first, "tolerance": tolerance,
            "only_in_reference_examples": [[int(x) for x in k] for k in only_ref[:5]],
            "only_in_runtime_examples": [[int(x) for x in k] for k in only_run[:5]]}


def summarize(report: Dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in report.items() if k != "per_column"} | {"columns_with_mismatches": sorted(report.get("per_column", {}))}, default=str)


__all__ = ["compare_frames", "summarize", "KEY"]

"""Catalog-Level Bar Timing and Semantic Timestamp Invariant Validator.
=====================================================================

Validates that NautilusTrader catalog bars conform strictly to declared timestamp semantics:
  - Invariant: ts_init >= ts_event (causality)
  - If nt_ts_event_semantic == "OPEN_STAMPED":
      ts_init - ts_event == bar_duration_ns
  - If nt_ts_event_semantic == "CLOSE_STAMPED":
      ts_init == ts_event
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd


class CatalogTimingError(ValueError):
    """Raised when catalog bar timestamps violate the semantic availability contract."""
    pass


def validate_bar_timestamp_semantics(
    ts_event_series: Sequence[int],
    ts_init_series: Sequence[int],
    bar_duration_ns: int,
    ts_event_semantic: str = "OPEN_STAMPED",
) -> Tuple[bool, List[str]]:
    """Validates bar timestamps against semantic contract.

    Parameters
    ----------
    ts_event_series : sequence of int
        Nanosecond timestamps of ts_event.
    ts_init_series : sequence of int
        Nanosecond timestamps of ts_init.
    bar_duration_ns : int
        Bar duration in nanoseconds (e.g. 1_000_000_000 for 1s, 60_000_000_000 for 1m).
    ts_event_semantic : str
        "OPEN_STAMPED" or "CLOSE_STAMPED".

    Returns
    -------
    (bool, list of error messages)
    """
    errors: List[str] = []
    events = np.asarray(ts_event_series, dtype=np.int64)
    inits = np.asarray(ts_init_series, dtype=np.int64)

    if len(events) == 0:
        return True, []

    # 1. Monotonic / Causality check: ts_init >= ts_event
    if np.any(inits < events):
        bad_idx = np.where(inits < events)[0][0]
        errors.append(
            f"Causal violation at index {bad_idx}: ts_init ({inits[bad_idx]}) < ts_event ({events[bad_idx]})"
        )

    # 2. Semantic delta check
    deltas = inits - events
    if ts_event_semantic.upper() == "OPEN_STAMPED":
        mismatches = deltas != bar_duration_ns
        if np.any(mismatches):
            bad_idx = np.where(mismatches)[0][0]
            errors.append(
                f"Semantic delta mismatch for OPEN_STAMPED bars at index {bad_idx}: "
                f"expected delta={bar_duration_ns}ns ({bar_duration_ns/1e9}s), "
                f"got delta={deltas[bad_idx]}ns ({deltas[bad_idx]/1e9}s)"
            )
    elif ts_event_semantic.upper() == "CLOSE_STAMPED":
        mismatches = deltas != 0
        if np.any(mismatches):
            bad_idx = np.where(mismatches)[0][0]
            errors.append(
                f"Semantic delta mismatch for CLOSE_STAMPED bars at index {bad_idx}: "
                f"expected delta=0ns, got delta={deltas[bad_idx]}ns"
            )
    else:
        errors.append(f"Unknown ts_event_semantic: {ts_event_semantic}")

    return (len(errors) == 0), errors

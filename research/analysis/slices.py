"""Recurring analysis slices (A0 §9, roadmap A2).

Only the slices that actually recur are implemented: direction, year/partition,
maturity, decile, regime, session. Each returns a label Series aligned to the
metadata frame, plus a description of how it was derived, so a table can state its
own filters rather than relying on the reader to remember them.

A slice that cannot be derived (missing column, constant value) is reported as
degenerate rather than silently producing one group — Fixture B has only one
`regime_direction`, so a direction slice there is not a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class SliceResult:
    name: str
    labels: Optional[pd.Series]
    derivable: bool
    reason: str = ""
    definition: str = ""
    groups: List[Any] = field(default_factory=list)

    @property
    def degenerate(self) -> bool:
        """A single group is not a comparison."""
        return self.derivable and len(self.groups) < 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slice": self.name,
            "derivable": self.derivable,
            "degenerate": self.degenerate,
            "reason": self.reason,
            "definition": self.definition,
            "groups": [_j(g) for g in self.groups],
            "n_groups": len(self.groups),
        }


def _j(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def _missing(name: str, column: str, definition: str) -> SliceResult:
    return SliceResult(name, None, False,
                       reason=f"required column {column!r} is not present", definition=definition)


def _finish(name: str, labels: pd.Series, definition: str) -> SliceResult:
    groups = sorted(labels.dropna().unique().tolist(), key=lambda x: (str(type(x)), x))
    res = SliceResult(name, labels, True, definition=definition, groups=groups)
    if res.degenerate:
        res.reason = (
            f"only {len(groups)} distinct group ({groups}); this slice is constant on this "
            f"collection and is not a comparison"
        )
    return res


# ---------------------------------------------------------------------------
# Slice implementations
# ---------------------------------------------------------------------------

DIRECTION_DEF = "regime_direction as emitted by the collector: -1 short / +1 long."


def slice_direction(meta: pd.DataFrame) -> SliceResult:
    if "regime_direction" not in meta.columns:
        return _missing("direction", "regime_direction", DIRECTION_DEF)
    labels = meta["regime_direction"].map({-1: "short", 1: "long"}).fillna("unknown")
    return _finish("direction", labels, DIRECTION_DEF)


YEAR_DEF = "Calendar year derived from observation_ts in UTC."


def slice_year(meta: pd.DataFrame) -> SliceResult:
    if "_year" in meta.columns:
        return _finish("year", meta["_year"].astype("Int64"), YEAR_DEF)
    if "observation_ts" not in meta.columns:
        return _missing("year", "observation_ts", YEAR_DEF)
    years = pd.to_datetime(meta["observation_ts"], unit="ns", utc=True).dt.year
    return _finish("year", years.astype("Int64"), YEAR_DEF)


PARTITION_DEF = "TRAIN/DEV/diagnostic partition from the study's declared chronology."


def slice_partition(meta: pd.DataFrame) -> SliceResult:
    if "_partition" not in meta.columns:
        return _missing("partition", "_partition", PARTITION_DEF)
    return _finish("partition", meta["_partition"].astype(str), PARTITION_DEF)


MATURITY_DEF = (
    "regime_age_seconds bucketed at 120s / 300s / 600s boundaries: "
    "young (<120), establishing (120-300), mature (300-600), old (>=600)."
)
MATURITY_EDGES = (0.0, 120.0, 300.0, 600.0, float("inf"))
MATURITY_LABELS = ("young", "establishing", "mature", "old")


def slice_maturity(meta: pd.DataFrame) -> SliceResult:
    if "regime_age_seconds" not in meta.columns:
        return _missing("maturity", "regime_age_seconds", MATURITY_DEF)
    labels = pd.cut(
        meta["regime_age_seconds"].astype("float64"),
        bins=list(MATURITY_EDGES), labels=list(MATURITY_LABELS),
        right=False, include_lowest=True,
    ).astype("object")
    return _finish("maturity", pd.Series(labels, index=meta.index), MATURITY_DEF)


REGIME_DEF = "Prevailing regime state; falls back to direction sign when no regime column exists."


def slice_regime(meta: pd.DataFrame) -> SliceResult:
    for col in ("regime_state", "prevailing_regime", "regime"):
        if col in meta.columns:
            return _finish("regime", meta[col].astype(str), REGIME_DEF)
    if "regime_direction" in meta.columns:
        labels = meta["regime_direction"].map({-1: "bearish", 1: "bullish"}).fillna("unknown")
        return _finish("regime", labels, REGIME_DEF + " (derived from regime_direction)")
    return _missing("regime", "regime_state", REGIME_DEF)


SESSION_DEF = (
    "RTH (13:30-20:00 UTC ~ 08:30-15:00 CT) versus ETH, derived from observation_ts. "
    "Approximate: it does not model DST or holiday sessions."
)


def slice_session(meta: pd.DataFrame) -> SliceResult:
    if "observation_ts" not in meta.columns:
        return _missing("session", "observation_ts", SESSION_DEF)
    ts = pd.to_datetime(meta["observation_ts"], unit="ns", utc=True)
    minutes = ts.dt.hour * 60 + ts.dt.minute
    labels = pd.Series(np.where((minutes >= 13 * 60 + 30) & (minutes < 20 * 60), "RTH", "ETH"),
                       index=meta.index)
    return _finish("session", labels, SESSION_DEF)


TARGET_DISPOSITION_DEF = (
    "Positive (target==1) vs negative (target==0) slice of the declared target column. "
    "Null/unresolved (censored) target values are excluded from BOTH groups -- they are "
    "never folded into 'negative' -- and surface as build_slice_table's separate "
    "'unassigned' row instead."
)


def slice_target_disposition(
    meta: pd.DataFrame, *, target_column: str = "target_flip_within_horizon"
) -> SliceResult:
    if target_column not in meta.columns:
        return _missing("target_disposition", target_column, TARGET_DISPOSITION_DEF)
    t = meta[target_column]
    labels = pd.Series(pd.NA, index=meta.index, dtype="object")
    labels[t == 1] = "positive"
    labels[t == 0] = "negative"
    # Any other value (including NaN/censored) stays <NA> -- neither label is assigned,
    # so it cannot be silently counted as negative.
    return _finish("target_disposition", labels, TARGET_DISPOSITION_DEF)


@dataclass(frozen=True)
class FixedInterval:
    """One explicitly declared, data-independent bucket edge.

    `lower`/`upper` of None mean -inf/+inf. Boundary inclusion is declared per-edge
    (not assumed) so callers can express `[0, 1]` and `(-inf, 0)` as adjacent,
    non-overlapping buckets without relying on `pd.cut`'s single global `right=`.
    """

    label: str
    lower: Optional[float]
    upper: Optional[float]
    lower_closed: bool = True
    upper_closed: bool = False

    def contains(self, x: float) -> bool:
        if x != x:  # NaN
            return False
        if self.lower is not None:
            if self.lower_closed and x < self.lower:
                return False
            if not self.lower_closed and x <= self.lower:
                return False
        if self.upper is not None:
            if self.upper_closed and x > self.upper:
                return False
            if not self.upper_closed and x >= self.upper:
                return False
        return True


def _interval_repr(iv: FixedInterval) -> str:
    lo = "-inf" if iv.lower is None else str(iv.lower)
    hi = "+inf" if iv.upper is None else str(iv.upper)
    l_br = "[" if iv.lower_closed and iv.lower is not None else "("
    r_br = "]" if iv.upper_closed and iv.upper is not None else ")"
    return f"{iv.label}={l_br}{lo}, {hi}{r_br}"


def _fixed_edges_definition(intervals: Sequence[FixedInterval]) -> str:
    return (
        "Declared fixed-edge buckets (edges are caller-supplied, never derived from "
        "observed data): " + "; ".join(_interval_repr(iv) for iv in intervals)
    )


# This study's declared buckets: (-inf, 0) / [0, 1] / (1, +inf). A fixed reference
# constant, not a default inferred from any dataset.
STUDY_FIXED_EDGES: "tuple[FixedInterval, ...]" = (
    FixedInterval("(-inf,0)", None, 0.0, lower_closed=True, upper_closed=False),
    FixedInterval("[0,1]", 0.0, 1.0, lower_closed=True, upper_closed=True),
    FixedInterval("(1,+inf)", 1.0, None, lower_closed=False, upper_closed=True),
)


def slice_fixed_edges(
    values: Sequence, intervals: Sequence[FixedInterval], *, name: str = "fixed_edges"
) -> SliceResult:
    """Generic fixed-edge bucketing: caller declares the intervals; none are fit
    from the data, and this must never be substituted with quantile/decile cuts."""
    s = pd.Series(list(values), dtype="float64")
    definition = _fixed_edges_definition(intervals)
    if s.dropna().empty:
        return SliceResult(name, None, False, reason="no non-null values to bucket", definition=definition)
    labels = pd.Series(pd.NA, index=s.index, dtype="object")
    arr = s.to_numpy()
    valid = ~np.isnan(arr)
    for iv in intervals:
        lower_ok = np.ones(len(arr), dtype=bool) if iv.lower is None else (
            arr >= iv.lower if iv.lower_closed else arr > iv.lower)
        upper_ok = np.ones(len(arr), dtype=bool) if iv.upper is None else (
            arr <= iv.upper if iv.upper_closed else arr < iv.upper)
        mask = lower_ok & upper_ok & valid
        labels[mask] = iv.label
    return _finish(name, labels, definition)


DECILE_DEF = "Decile of the supplied score, computed within the slice; ties share a bucket."


def slice_decile(values: Sequence, n_buckets: int = 10, name: str = "decile") -> SliceResult:
    s = pd.Series(list(values), dtype="float64")
    if s.dropna().empty:
        return SliceResult(name, None, False, reason="no non-null values to rank",
                           definition=DECILE_DEF)
    if s.dropna().nunique() < 2:
        return SliceResult(name, None, True, definition=DECILE_DEF,
                           groups=[0],
                           reason="score is constant; deciles are not separable")
    try:
        labels = pd.qcut(s, q=n_buckets, labels=False, duplicates="drop")
    except ValueError as err:
        return SliceResult(name, None, False, reason=f"qcut failed: {err}", definition=DECILE_DEF)
    return _finish(name, labels.astype("Int64"), DECILE_DEF)


SLICE_REGISTRY: Dict[str, Callable[[pd.DataFrame], SliceResult]] = {
    "direction": slice_direction,
    "year": slice_year,
    "partition": slice_partition,
    "maturity": slice_maturity,
    "regime": slice_regime,
    "session": slice_session,
}


def available_slices() -> List[str]:
    # "target_disposition" requires a specific declared target column that a generic
    # metadata frame need not carry (unlike every SLICE_REGISTRY entry, which must
    # derive on any normal frame); "decile" and "fixed_edges" take a value series, not
    # `meta`. None fit SLICE_REGISTRY's Callable[[pd.DataFrame], SliceResult] shape,
    # but all three are real, callable slices -- listed here so callers can discover them.
    return sorted(SLICE_REGISTRY) + ["decile", "fixed_edges", "target_disposition"]


def build_slices(meta: pd.DataFrame, names: Optional[Sequence[str]] = None) -> Dict[str, SliceResult]:
    """Builds every requested slice, reporting rather than raising on failure."""
    requested = list(names) if names else sorted(SLICE_REGISTRY)
    out: Dict[str, SliceResult] = {}
    for n in requested:
        fn = SLICE_REGISTRY.get(n)
        if fn is None:
            out[n] = SliceResult(n, None, False, reason=f"unknown slice {n!r}; "
                                                        f"available: {available_slices()}")
            continue
        out[n] = fn(meta)
    return out

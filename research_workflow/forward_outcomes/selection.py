"""Frozen-selector construction of immutable proposed-entry sets.

The selector runs first and finishes completely: it produces an entry set, and only
then does the observation layer look at any future bar. That ordering is the whole
lookahead defence, so nothing in this module may consult an outcome.

The second defence is that every selection boundary must already be frozen. A "top
decile" or "P95 crossing" computed from the population being evaluated is a threshold
that saw its own test set; these functions therefore refuse a threshold record that
does not declare a TRAIN derivation, rather than quietly computing a quantile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research_workflow.forward_outcomes.contracts import (
    Direction,
    ForwardOutcomeError,
    ProposedEntry,
    ReferencePrice,
)

# A frozen boundary must say where it came from. Anything else is a threshold that may
# have been fitted on the population it is about to select from.
ALLOWED_DERIVATION_POPULATIONS = frozenset({"train"})


class SelectionError(ForwardOutcomeError):
    """Raised when a selector is asked to derive a boundary it must inherit."""


@dataclass(frozen=True)
class EntryContext:
    """Provenance stamped onto every entry a selector produces."""

    study_id: str
    source_period: str
    authorization_sha256: str
    source_freeze_sha256: str
    reference_price: ReferencePrice = ReferencePrice.DECISION_CLOSE
    model_id: Optional[str] = None
    model_hash: Optional[str] = None


@dataclass(frozen=True)
class EntryColumns:
    """Names of the causal columns a selector reads from the score frame."""

    candidate_key: str
    decision_ts: str
    price: str
    entry_ts: Optional[str] = None          # defaults to decision_ts
    direction: Optional[str] = None         # column name; else direction_value is required
    direction_value: Optional[str] = None
    score: Optional[str] = None
    atr: Optional[str] = None
    regime_id: Optional[str] = None
    maturity_bucket: Optional[str] = None
    maturity_seconds: Optional[str] = None
    session_close_ts: Optional[str] = None

    def required(self) -> list[str]:
        names = [self.candidate_key, self.decision_ts, self.price]
        for optional in (
            self.entry_ts, self.direction, self.score, self.atr, self.regime_id,
            self.maturity_bucket, self.maturity_seconds, self.session_close_ts,
        ):
            if optional:
                names.append(optional)
        return names


def _validate_frame(frame: pd.DataFrame, columns: EntryColumns) -> None:
    missing = [c for c in columns.required() if c not in frame.columns]
    if missing:
        raise SelectionError(f"score frame is missing declared columns: {missing}")
    if columns.direction is None and columns.direction_value is None:
        raise SelectionError("EntryColumns must declare either direction or direction_value")


def validate_frozen_threshold(label: str, record: Mapping[str, Any]) -> float:
    """Accept only a threshold that declares a TRAIN derivation."""
    if "threshold" not in record:
        raise SelectionError(f"threshold record {label!r} has no 'threshold' value")
    population = str(record.get("derivation_population", "")).lower()
    if population not in ALLOWED_DERIVATION_POPULATIONS:
        raise SelectionError(
            f"threshold {label!r} declares derivation_population={population!r}; a "
            f"selection boundary must be frozen on TRAIN, never recomputed on the "
            f"population it selects from"
        )
    return float(record["threshold"])


def _row_entry(
    row: Mapping[str, Any],
    *,
    context: EntryContext,
    columns: EntryColumns,
    selector_id: str,
    threshold_id: Optional[str],
    score_decile: Optional[int] = None,
    extra_metadata: Optional[Mapping[str, Any]] = None,
) -> ProposedEntry:
    direction = (
        str(row[columns.direction]) if columns.direction else str(columns.direction_value)
    )
    entry_ts = int(row[columns.entry_ts]) if columns.entry_ts else int(row[columns.decision_ts])
    return ProposedEntry(
        study_id=context.study_id,
        source_period=context.source_period,
        candidate_key=str(row[columns.candidate_key]),
        decision_ts=int(row[columns.decision_ts]),
        entry_ts=entry_ts,
        direction=Direction(direction),
        entry_price=float(row[columns.price]),
        reference_price=context.reference_price,
        authorization_sha256=context.authorization_sha256,
        source_freeze_sha256=context.source_freeze_sha256,
        regime_id=str(row[columns.regime_id]) if columns.regime_id else None,
        entry_atr=float(row[columns.atr]) if columns.atr else None,
        model_id=context.model_id,
        model_hash=context.model_hash,
        score=float(row[columns.score]) if columns.score else None,
        score_decile=score_decile,
        threshold_id=threshold_id,
        maturity_bucket=str(row[columns.maturity_bucket]) if columns.maturity_bucket else None,
        maturity_seconds=(
            float(row[columns.maturity_seconds]) if columns.maturity_seconds else None
        ),
        session_close_ts=(
            int(row[columns.session_close_ts]) if columns.session_close_ts else None
        ),
        selector_id=selector_id,
        metadata=dict(extra_metadata or {}),
    )


def build_entries(
    frame: pd.DataFrame,
    *,
    context: EntryContext,
    columns: EntryColumns,
    selector_id: str,
    threshold_id: Optional[str] = None,
) -> list[ProposedEntry]:
    """Anchor every row of an already-selected frame. No filtering happens here."""
    _validate_frame(frame, columns)
    ordered = frame.sort_values([columns.decision_ts, columns.candidate_key], kind="mergesort")
    return [
        _row_entry(
            row, context=context, columns=columns,
            selector_id=selector_id, threshold_id=threshold_id,
        )
        for row in ordered.to_dict("records")
    ]


def first_crossing_entries(
    frame: pd.DataFrame,
    *,
    context: EntryContext,
    columns: EntryColumns,
    threshold_records: Mapping[str, Mapping[str, Any]],
    group_column: str,
    score_column: Optional[str] = None,
    selector_id: str = "first_crossing",
) -> list[ProposedEntry]:
    """One entry per group per frozen threshold: the first score crossing.

    "First" is resolved on ``decision_ts`` order within the group, so the anchor is the
    earliest moment the frozen boundary was cleared -- exactly what a live system would
    have acted on. Later crossings in the same group are not entries.
    """
    _validate_frame(frame, columns)
    score = score_column or columns.score
    if not score:
        raise SelectionError("first_crossing_entries requires a score column")
    if group_column not in frame.columns:
        raise SelectionError(f"group column {group_column!r} is not in the score frame")

    work = frame.sort_values([group_column, columns.decision_ts], kind="mergesort")
    entries: list[ProposedEntry] = []
    for label in sorted(threshold_records):
        threshold = validate_frozen_threshold(label, threshold_records[label])
        armed = work[work[score].astype(float) >= threshold]
        if armed.empty:
            continue
        first = armed.groupby(group_column, sort=True, as_index=False).head(1)
        for row in first.to_dict("records"):
            entries.append(_row_entry(
                row, context=context, columns=columns,
                selector_id=selector_id, threshold_id=label,
                extra_metadata={"threshold_value": threshold},
            ))
    entries.sort(key=lambda e: (e.entry_ts, e.entry_id))
    return entries


def threshold_crossing_entries(
    frame: pd.DataFrame,
    *,
    context: EntryContext,
    columns: EntryColumns,
    threshold_records: Mapping[str, Mapping[str, Any]],
    score_column: Optional[str] = None,
    selector_id: str = "threshold_crossing",
) -> list[ProposedEntry]:
    """Every row clearing a frozen threshold (no first-per-group reduction)."""
    _validate_frame(frame, columns)
    score = score_column or columns.score
    if not score:
        raise SelectionError("threshold_crossing_entries requires a score column")
    entries: list[ProposedEntry] = []
    for label in sorted(threshold_records):
        threshold = validate_frozen_threshold(label, threshold_records[label])
        armed = frame[frame[score].astype(float) >= threshold]
        for row in armed.sort_values(columns.decision_ts, kind="mergesort").to_dict("records"):
            entries.append(_row_entry(
                row, context=context, columns=columns,
                selector_id=selector_id, threshold_id=label,
                extra_metadata={"threshold_value": threshold},
            ))
    entries.sort(key=lambda e: (e.entry_ts, e.entry_id))
    return entries


def assign_frozen_deciles(
    scores: pd.Series, decile_edges: Sequence[float], *, n_deciles: int = 10
) -> pd.Series:
    """Map scores onto TRAIN-frozen decile edges.

    ``decile_edges`` are the interior boundaries (``n_deciles - 1`` of them). Using the
    frozen edges rather than re-ranking is what keeps an OOS "top decile" comparable to
    the TRAIN one instead of being redefined by the OOS distribution.
    """
    edges = [float(e) for e in decile_edges]
    if len(edges) != n_deciles - 1:
        raise SelectionError(
            f"expected {n_deciles - 1} interior decile edges, received {len(edges)}"
        )
    if any(b < a for a, b in zip(edges, edges[1:])):
        raise SelectionError("decile edges must be non-decreasing")
    return pd.Series(
        np.searchsorted(np.asarray(edges, dtype=float), scores.astype(float).to_numpy(), side="right") + 1,
        index=scores.index, dtype=int,
    )


def score_decile_entries(
    frame: pd.DataFrame,
    *,
    context: EntryContext,
    columns: EntryColumns,
    decile_record: Mapping[str, Any],
    select_deciles: Iterable[int],
    score_column: Optional[str] = None,
    selector_id: str = "score_decile",
    n_deciles: int = 10,
) -> list[ProposedEntry]:
    """Entries drawn from declared deciles of a TRAIN-frozen score partition."""
    _validate_frame(frame, columns)
    score = score_column or columns.score
    if not score:
        raise SelectionError("score_decile_entries requires a score column")
    population = str(decile_record.get("derivation_population", "")).lower()
    if population not in ALLOWED_DERIVATION_POPULATIONS:
        raise SelectionError(
            f"decile record declares derivation_population={population!r}; decile edges "
            f"must be frozen on TRAIN"
        )
    edges = decile_record.get("edges")
    if not edges:
        raise SelectionError("decile record has no 'edges'")
    wanted = sorted({int(d) for d in select_deciles})
    if any(d < 1 or d > n_deciles for d in wanted):
        raise SelectionError(f"deciles must lie in 1..{n_deciles}")

    work = frame.copy()
    work["_decile"] = assign_frozen_deciles(work[score], edges, n_deciles=n_deciles)
    selected = work[work["_decile"].isin(wanted)].sort_values(
        [columns.decision_ts, columns.candidate_key], kind="mergesort"
    )
    entries = [
        _row_entry(
            row, context=context, columns=columns, selector_id=selector_id,
            threshold_id=f"decile_{int(row['_decile'])}",
            score_decile=int(row["_decile"]),
        )
        for row in selected.to_dict("records")
    ]
    entries.sort(key=lambda e: (e.entry_ts, e.entry_id))
    return entries


def local_score_maximum_entries(
    frame: pd.DataFrame,
    *,
    context: EntryContext,
    columns: EntryColumns,
    window_seconds: int,
    floor_record: Mapping[str, Any],
    group_column: str,
    score_column: Optional[str] = None,
    selector_id: str = "local_score_maximum",
) -> list[ProposedEntry]:
    """Highest score inside each group, gated by a frozen floor.

    A local maximum is a *retrospective* statement about a score series: the group's
    peak is only knowable once the group is over. That is legitimate here only because
    the score series is causal and the anchor is used descriptively -- so the selector
    records ``score_peak_is_retrospective`` in the entry metadata rather than letting a
    later reader mistake these anchors for a live trigger.
    """
    _validate_frame(frame, columns)
    score = score_column or columns.score
    if not score:
        raise SelectionError("local_score_maximum_entries requires a score column")
    if group_column not in frame.columns:
        raise SelectionError(f"group column {group_column!r} is not in the score frame")
    floor = validate_frozen_threshold("floor", floor_record)

    work = frame[frame[score].astype(float) >= floor].sort_values(
        [group_column, columns.decision_ts], kind="mergesort"
    )
    entries: list[ProposedEntry] = []
    for _, group in work.groupby(group_column, sort=True):
        best_idx = group[score].astype(float).idxmax()
        row = group.loc[best_idx].to_dict()
        entries.append(_row_entry(
            row, context=context, columns=columns, selector_id=selector_id,
            threshold_id="local_max",
            extra_metadata={
                "floor_value": floor,
                "window_seconds": int(window_seconds),
                "score_peak_is_retrospective": True,
            },
        ))
    entries.sort(key=lambda e: (e.entry_ts, e.entry_id))
    return entries


def entries_to_frame(entries: Sequence[ProposedEntry]) -> pd.DataFrame:
    """Deterministic ``proposed_entries`` table."""
    if not entries:
        return pd.DataFrame()
    frame = pd.DataFrame([e.to_row() for e in entries])
    if frame["entry_id"].duplicated().any():
        dupes = sorted(frame.loc[frame["entry_id"].duplicated(), "entry_id"].unique())
        raise SelectionError(f"duplicate entry_id in proposed entry set: {dupes[:5]}")
    return frame.sort_values(["entry_ts", "entry_id"], kind="mergesort").reset_index(drop=True)

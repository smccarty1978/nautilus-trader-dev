"""Generic, declarative post-collection analysis operations for Platform V2.

These are the governed alternative to a study-local pandas script. Every operation is
study-agnostic: it reads named columns off a study's own collected frame, takes its
science from declared parameters, and returns a frame plus a JSON-able payload. Nothing
here knows what a "P90 warning" is -- it knows about anchors, horizons, strata and
thresholds.

Six operations, each answering one question the V2 ``analyze`` stage could not previously
express at all (it emitted only row counts, disposition counts and roc_auc/pr_auc/brier):

* ``anchor.first_threshold_crossing`` -- the first row per group whose declared per-arm
  value reaches its declared per-arm threshold, optionally restricted to an eligibility
  subset. One anchor per group, maximum.
* ``incidence.cumulative``            -- right-censoring-aware cumulative AND incremental
  event incidence over declared horizons, with an explicit per-horizon eligible-n.
* ``decomposition.buckets``           -- a mutually exclusive partition of a censored
  duration, reported against two declared denominators.
* ``control.cell_matched``            -- deterministic, predeclared control selection: at
  most one control row per (group x stratum cell), never chosen by looking at outcomes.
* ``path.anchored_offsets``           -- the value path at declared offsets from an anchor,
  with time-to-level, collapse and recross summaries.
* ``classify.precedence``             -- ordered, first-match-wins categorical labelling.

Plus two STOP GATES, which add no column and exist only to REFUSE:

* ``gate.population_parity``          -- the population is identical to a frozen reference.
* ``gate.arm_delta_integrity``        -- every non-baseline arm's added feature block is
  populated and varying on the fitted population, and actually changed the fitted model.

Causality: these run AFTER collection on already-materialized frames. They may read
outcome columns (that is their job) and must never be used to build a feature.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

NS = 1_000_000_000

__all__ = [
    "AnalysisOpError", "OPS", "run_op", "eligibility_mask", "resolve_by", "apply_terminal",
    "anchor_first_threshold_crossing", "cumulative_incidence", "bucket_decomposition",
    "cell_matched_controls", "anchored_path", "precedence_labels", "population_parity_gate",
    "arm_delta_integrity_gate",
]


class AnalysisOpError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
_COMPARISONS = {
    "eq": lambda s, v: s.eq(v), "ne": lambda s, v: s.ne(v), "lt": lambda s, v: s.lt(v),
    "lte": lambda s, v: s.le(v), "gt": lambda s, v: s.gt(v), "gte": lambda s, v: s.ge(v),
    "is_null": lambda s, v: s.isna() if v else s.notna(),
}


def _require(frame: pd.DataFrame, columns: Sequence[str], where: str) -> None:
    missing = [c for c in columns if c and c not in frame.columns]
    if missing:
        raise AnalysisOpError(f"ANALYSIS_COLUMN_MISSING: {where} needs {sorted(set(missing))}")


def _case_key(value: Any) -> str:
    """Normalize a case-selector value so 1, 1.0, '1' and True all key the same case."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return str(int(value)) if float(value).is_integer() else repr(float(value))
    return str(value)


def resolve_by(frame: pd.DataFrame, by: Mapping[str, Any], *, need: Sequence[str] = ("value", "threshold"),
               levels: Sequence[str] = ()) -> pd.DataFrame:
    """Resolve a per-arm ("directional") selector into flat ``_value`` / ``_threshold`` columns.

    ``by`` is ``{column: <selector column>, cases: {<value>: {value: <col>, threshold: <float>,
    levels: {<name>: <float>}}}}``. Every row's selector value must name a declared case --
    an unmatched row is refused rather than silently dropped, because a silently dropped
    arm is exactly how a population loses scope without anyone noticing.
    """
    column = by.get("column")
    cases = by.get("cases") or {}
    if not column or not cases:
        raise AnalysisOpError("ANALYSIS_BY_INVALID: 'by' needs a column and at least one case")
    _require(frame, [column], "by.column")
    keys = frame[column].map(_case_key)
    declared = {_case_key(k): v for k, v in cases.items()}
    unknown = sorted(set(keys.unique()) - set(declared))
    if unknown:
        raise AnalysisOpError(f"ANALYSIS_BY_UNMATCHED_ROWS: {column} values {unknown} match no declared case")
    out = pd.DataFrame(index=frame.index)
    for field in need:
        if field == "value":
            cols = {k: v.get("value") for k, v in declared.items()}
            _require(frame, [c for c in cols.values() if c], "by.cases[].value")
            out["_value"] = [frame.at[i, cols[k]] if cols.get(k) else np.nan for i, k in zip(frame.index, keys)]
        elif field == "threshold":
            thr = {k: v.get("threshold") for k, v in declared.items()}
            if any(t is None for t in thr.values()):
                raise AnalysisOpError("ANALYSIS_BY_INVALID: every case needs a threshold")
            out["_threshold"] = [float(thr[k]) for k in keys]
    for name in levels:
        lv = {k: (v.get("levels") or {}).get(name) for k, v in declared.items()}
        if any(x is None for x in lv.values()):
            raise AnalysisOpError(f"ANALYSIS_BY_INVALID: every case needs levels.{name}")
        out[f"_level_{name}"] = [float(lv[k]) for k in keys]
    out["_case"] = keys.values
    return out


def eligibility_mask(frame: pd.DataFrame, *, column: Optional[str] = None,
                     conditions: Optional[Sequence[Sequence[Any]]] = None, where: str = "eligibility") -> pd.Series:
    """Resolve a declared eligibility subset: a boolean column, a list of ``[column, op, value]``
    conditions (ANDed), or both.

    Eligibility restricts which rows may be SELECTED without removing any row from the frame.
    That is what lets a study carry a strict superset population -- so a value path can continue
    past the point a frozen parent's qualification would have ended -- while still reproducing
    the parent's selection identity exactly, by declaring the parent's qualification here.
    """
    mask = pd.Series(True, index=frame.index)
    if column:
        _require(frame, [column], where)
        mask &= frame[column].fillna(False).astype(bool)
    for cond in (conditions or []):
        if len(cond) != 3:
            raise AnalysisOpError(f"ANALYSIS_ELIGIBILITY_INVALID: {where} condition must be [column, op, value]")
        name, op, value = cond
        if op not in _COMPARISONS:
            raise AnalysisOpError(f"ANALYSIS_ELIGIBILITY_INVALID: {where} unknown op {op!r}; known={sorted(_COMPARISONS)}")
        _require(frame, [name], where)
        series = frame[name]
        if isinstance(value, bool) and series.dtype == object:
            series = series.fillna(False).astype(bool)
        mask &= _COMPARISONS[op](series, value).fillna(False)
    return mask


def apply_terminal(frame: pd.DataFrame, terminal: Optional[Mapping[str, Any]], *, order_by: str,
                   where: str = "terminal") -> pd.DataFrame:
    """Reduce several terminal timestamps to one, and emit ``terminal_ts`` / ``observed_seconds``.

    An anchor and a control must be measured against the SAME observation horizon or their
    incidence rates are not comparable, so the reduction is one shared operation rather than a
    rule each statistic re-derives for itself.
    """
    if terminal is None or not len(frame):
        return frame
    columns = list(terminal.get("columns") or [])
    if not columns:
        raise AnalysisOpError(f"ANALYSIS_TERMINAL_INVALID: {where} needs at least one column")
    _require(frame, columns, f"{where}.columns")
    reduce = str(terminal.get("reduce", "min"))
    if reduce not in ("min", "max"):
        raise AnalysisOpError(f"ANALYSIS_TERMINAL_INVALID: {where}.reduce must be min or max, got {reduce!r}")
    block = frame[columns].apply(pd.to_numeric, errors="coerce")
    out = frame.assign(terminal_ts=(block.min(axis=1) if reduce == "min" else block.max(axis=1)))
    scale = NS if str(terminal.get("unit", "ns")) == "ns" else 1
    out = out.assign(observed_seconds=(out["terminal_ts"] - pd.to_numeric(out[order_by], errors="coerce")) / scale)
    if (out["observed_seconds"] < 0).any():
        raise AnalysisOpError(f"ANALYSIS_TERMINAL_BEFORE_ANCHOR: {where} reduced a terminal that precedes its own row")
    return out


def _seconds(frame: pd.DataFrame, column: str, *, unit: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    return values / NS if unit == "ns" else values


# --------------------------------------------------------------------------- #
# A1 -- anchor selection
# --------------------------------------------------------------------------- #
def anchor_first_threshold_crossing(rows: pd.DataFrame, *, by: Mapping[str, Any], group_by: Sequence[str],
                                    order_by: str, eligible_column: Optional[str] = None,
                                    eligible_when: Optional[Sequence[Sequence[Any]]] = None,
                                    inclusive: bool = True,
                                    terminal: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The FIRST row per group whose per-arm value reaches its per-arm threshold.

    ``eligible_column`` (a boolean column) restricts WHICH rows may become an anchor without
    removing any row from the frame -- so a study can carry a strict superset population and
    still reproduce a frozen parent's anchor identity exactly by declaring the parent's
    eligibility as a column. ``inclusive`` selects ``>=`` (no below->above crossing is
    required: a group whose first eligible row is already at or above threshold anchors there).
    At most one anchor per group.

    ``terminal`` = ``{columns: [...], reduce: min|max, unit: ns|s}`` reduces several terminal
    timestamps (the event time, the session close, a data-gap censor) to the single instant the
    anchor stopped being observable, and emits ``terminal_ts`` and ``observed_seconds``.
    Every downstream operation then takes the SAME observation horizon from the anchor rather
    than re-deriving it, so a censoring rule cannot drift between two statistics in one report.
    """
    group_by = list(group_by)
    _require(rows, group_by + [order_by], "anchor.first_threshold_crossing")
    resolved = resolve_by(rows, by)
    work = rows.copy()
    work["_value"], work["_threshold"], work["_case"] = resolved["_value"], resolved["_threshold"], resolved["_case"]
    eligible = eligibility_mask(work, column=eligible_column, conditions=eligible_when, where="anchor.eligibility")
    restricted = bool(eligible_column) or bool(eligible_when)
    hit = work["_value"].notna() & ((work["_value"] >= work["_threshold"]) if inclusive else (work["_value"] > work["_threshold"]))
    candidates = work[eligible & hit].sort_values(order_by, kind="mergesort")
    anchors = candidates.groupby(group_by, as_index=False, sort=True).first() if len(candidates) else candidates.copy()
    if len(anchors) and anchors.duplicated(group_by).any():
        raise AnalysisOpError("ANALYSIS_ANCHOR_DUPLICATE: more than one anchor per group")
    anchors = apply_terminal(anchors, terminal, order_by=order_by, where="anchor.terminal")
    payload = {
        "schema_version": 1,
        "groups_total": int(work[group_by].drop_duplicates().shape[0]),
        "groups_eligible": int(work[eligible][group_by].drop_duplicates().shape[0]),
        "rows_total": int(len(work)), "rows_eligible": int(eligible.sum()), "eligibility_restricted": restricted,
        "anchors": int(len(anchors)),
        "anchors_by_case": {k: int(v) for k, v in anchors["_case"].value_counts().sort_index().items()} if len(anchors) else {},
        "inclusive": bool(inclusive),
        "eligible_column": eligible_column, "eligible_when": [list(c) for c in (eligible_when or [])],
        "thresholds_by_case": {_case_key(k): (v or {}).get("threshold") for k, v in (by.get("cases") or {}).items()},
        "terminal": dict(terminal) if terminal else None,
        "observed_seconds": ({"min": float(anchors["observed_seconds"].min()), "median": float(anchors["observed_seconds"].median()),
                              "max": float(anchors["observed_seconds"].max())}
                             if terminal is not None and len(anchors) else None),
    }
    return {"frame": anchors.reset_index(drop=True), "payload": payload}


# --------------------------------------------------------------------------- #
# A2 -- cumulative incidence
# --------------------------------------------------------------------------- #
def cumulative_incidence(rows: pd.DataFrame, *, horizons: Sequence[float], resolved_column: str,
                         duration_column: str, observed_seconds_column: str, strata: Sequence[str] = (),
                         duration_unit: str = "s", observed_unit: str = "s") -> Dict[str, Any]:
    """Cumulative and incremental event incidence over declared horizons, censoring-aware.

    The eligible denominator at horizon ``h`` is every unit that either resolved at or before
    ``h`` OR was observed for at least ``h``. Requiring only "observed for at least h" would
    silently drop fast resolvers -- a unit that resolved at 90s stops being observed at 90s and
    would leave the 180s denominator, inflating every longer horizon's rate.
    """
    horizons = [float(h) for h in horizons]
    if sorted(horizons) != horizons or len(set(horizons)) != len(horizons):
        raise AnalysisOpError("ANALYSIS_HORIZONS_INVALID: horizons must be strictly increasing")
    _require(rows, [resolved_column, duration_column, observed_seconds_column, *strata], "incidence.cumulative")
    resolved = rows[resolved_column].fillna(False).astype(bool)
    duration = _seconds(rows, duration_column, unit=duration_unit)
    observed = _seconds(rows, observed_seconds_column, unit=observed_unit)

    def _series(mask: pd.Series) -> List[Dict[str, Any]]:
        r, d, o = resolved[mask], duration[mask], observed[mask]
        out, previous = [], 0
        for h in horizons:
            resolved_by_h = r & d.le(h)
            eligible = resolved_by_h | o.ge(h)
            n = int(eligible.sum())
            count = int((resolved_by_h & eligible).sum())
            increment = count - previous
            out.append({"horizon_seconds": h, "eligible_n": n, "cumulative_count": count,
                        "cumulative_rate": (count / n) if n else None,
                        "increment_count": increment, "increment_rate": (increment / n) if n else None,
                        "not_yet_resolved_n": int((eligible & ~resolved_by_h).sum()),
                        "ineligible_right_censored_n": int((~eligible).sum())})
            previous = count
        out.append({"horizon_seconds": "observed_end", "eligible_n": int(mask.sum()),
                    "cumulative_count": int(r.sum()), "cumulative_rate": (float(r.sum()) / int(mask.sum())) if int(mask.sum()) else None,
                    "increment_count": int(r.sum()) - previous, "increment_rate": None,
                    "not_yet_resolved_n": int((~r).sum()), "ineligible_right_censored_n": 0})
        return out

    populations = {"pooled": _series(pd.Series(True, index=rows.index))}
    for column in strata:
        for value, part in rows.groupby(column, sort=True):
            populations[f"{column}={_case_key(value)}"] = _series(rows.index.isin(part.index))
    return {"frame": rows, "payload": {"schema_version": 1, "horizons_seconds": horizons, "n": int(len(rows)),
                                       "eligibility_rule": "resolved_at_or_before_h OR observed_for_at_least_h",
                                       "strata": list(strata), "populations": populations}}


# --------------------------------------------------------------------------- #
# A3 -- decomposition
# --------------------------------------------------------------------------- #
def bucket_decomposition(rows: pd.DataFrame, *, buckets: Sequence[Mapping[str, Any]], resolved_column: str,
                         duration_column: str, observed_seconds_column: str, negative_after_seconds: float,
                         terminal_column: Optional[str] = None, strata: Sequence[str] = (),
                         duration_unit: str = "s", observed_unit: str = "s") -> Dict[str, Any]:
    """Partition a censored duration into declared, mutually exclusive buckets.

    Each bucket is ``{id, gt, lte}`` over the resolved duration, or ``{id, unresolved: true,
    min_observed_seconds: X}`` / ``{id, terminal: <value>}`` for the unresolved tail. Buckets are
    applied in declaration order, first match wins, so the partition is exclusive by
    construction and every row lands in exactly one bucket (or ``UNCLASSIFIED``, which is
    reported rather than hidden). Two denominators are reported: all rows, and the rows that
    are NEGATIVE at ``negative_after_seconds``.
    """
    _require(rows, [resolved_column, duration_column, observed_seconds_column, *strata], "decomposition.buckets")
    if terminal_column:
        _require(rows, [terminal_column], "decomposition.terminal_column")
    resolved = rows[resolved_column].fillna(False).astype(bool)
    duration = _seconds(rows, duration_column, unit=duration_unit)
    observed = _seconds(rows, observed_seconds_column, unit=observed_unit)
    negative = ~(resolved & duration.le(float(negative_after_seconds)))

    assigned = pd.Series(None, index=rows.index, dtype=object)
    for spec in buckets:
        bid = str(spec["id"])
        if spec.get("unresolved"):
            mask = ~resolved
            if spec.get("min_observed_seconds") is not None:
                mask &= observed.ge(float(spec["min_observed_seconds"]))
            if spec.get("max_observed_seconds") is not None:
                mask &= observed.lt(float(spec["max_observed_seconds"]))
        elif spec.get("terminal") is not None:
            if not terminal_column:
                raise AnalysisOpError("ANALYSIS_BUCKET_INVALID: a terminal bucket needs terminal_column")
            mask = rows[terminal_column].astype(str).eq(str(spec["terminal"]))
        else:
            mask = resolved.copy()
            if spec.get("gt") is not None:
                mask &= duration.gt(float(spec["gt"]))
            if spec.get("lte") is not None:
                mask &= duration.le(float(spec["lte"]))
        assigned = assigned.where(assigned.notna(), other=pd.Series(np.where(mask, bid, None), index=rows.index))
    assigned = assigned.fillna("UNCLASSIFIED")

    def _rows_for(mask: pd.Series) -> List[Dict[str, Any]]:
        total, neg = int(mask.sum()), int((mask & negative).sum())
        out = []
        for bid in [str(b["id"]) for b in buckets] + ["UNCLASSIFIED"]:
            hit = mask & assigned.eq(bid)
            n = int(hit.sum())
            out.append({"bucket": bid, "n": n, "percent_of_all": (n / total) if total else None,
                        "n_within_negative": int((hit & negative).sum()),
                        "percent_of_negative": (int((hit & negative).sum()) / neg) if neg else None})
        return out

    payload = {"schema_version": 1, "n": int(len(rows)), "negative_after_seconds": float(negative_after_seconds),
               "negative_denominator": int(negative.sum()), "mutually_exclusive": True,
               "populations": {"pooled": _rows_for(pd.Series(True, index=rows.index))}}
    for column in strata:
        for value, part in rows.groupby(column, sort=True):
            payload["populations"][f"{column}={_case_key(value)}"] = _rows_for(pd.Series(rows.index.isin(part.index), index=rows.index))
    return {"frame": rows.assign(**{"bucket": assigned.values}), "payload": payload}


# --------------------------------------------------------------------------- #
# A4 -- deterministic control selection
# --------------------------------------------------------------------------- #
def cell_matched_controls(rows: pd.DataFrame, *, anchors: pd.DataFrame, by: Mapping[str, Any],
                          group_by: Sequence[str], strata: Sequence[str], order_by: str,
                          min_n: int = 30, eligible_column: Optional[str] = None,
                          eligible_when: Optional[Sequence[Sequence[Any]]] = None,
                          terminal: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """At most one control row per (group x stratum cell), chosen without looking at outcomes.

    Two selection rules, both deterministic and both predeclared:

    * a group that produced an anchor contributes the LATEST eligible row in the cell that is
      strictly BEFORE its anchor and below threshold;
    * a group that produced no anchor contributes the LATEST eligible row in the cell that is
      below threshold.

    No nearest-neighbour search, no propensity model, no weighting, and nothing that reads a
    label. A cell is reportable only when BOTH its anchor count and its control count reach
    ``min_n``; otherwise it is INSUFFICIENT and says so rather than being pooled away.
    """
    group_by, strata = list(group_by), list(strata)
    _require(rows, group_by + strata + [order_by], "control.cell_matched")
    resolved = resolve_by(rows, by)
    work = rows.copy()
    work["_value"], work["_threshold"], work["_case"] = resolved["_value"], resolved["_threshold"], resolved["_case"]
    eligible = (work["_value"].notna() & work["_value"].lt(work["_threshold"])
                & eligibility_mask(work, column=eligible_column, conditions=eligible_when, where="control.eligibility"))
    work = work[eligible]

    anchor_time = {}
    if len(anchors):
        _require(anchors, group_by + [order_by], "control.anchors")
        for _, a in anchors.iterrows():
            anchor_time[tuple(a[c] for c in group_by)] = a[order_by]
    keep = []
    for key, part in work.groupby(group_by + strata, sort=True):
        gkey = tuple(key[:len(group_by)]) if isinstance(key, tuple) else (key,)
        cutoff = anchor_time.get(gkey)
        usable = part[part[order_by] < cutoff] if cutoff is not None else part
        if len(usable):
            keep.append(usable.sort_values(order_by, kind="mergesort").iloc[-1])
    controls = pd.DataFrame(keep).reset_index(drop=True) if keep else work.iloc[0:0].copy()
    controls = apply_terminal(controls, terminal, order_by=order_by, where="control.terminal")
    controls = controls.assign(control_kind=[("pre_anchor" if tuple(r[c] for c in group_by) in anchor_time else "never_anchored")
                                             for _, r in controls.iterrows()]) if len(controls) else controls.assign(control_kind=[])

    def _cell(frame: pd.DataFrame) -> pd.Series:
        if not len(frame):
            return pd.Series([], dtype=object)
        return frame[strata].astype(str).agg("|".join, axis=1) if strata else pd.Series(["ALL"] * len(frame), index=frame.index)

    anchor_cells, control_cells = _cell(anchors), _cell(controls)
    names = sorted(set(anchor_cells.unique()) | set(control_cells.unique()))
    cells = []
    for name in names:
        an, cn = int((anchor_cells == name).sum()), int((control_cells == name).sum())
        cells.append({"cell": name, "anchor_n": an, "control_n": cn,
                      "status": "OK" if (an >= min_n and cn >= min_n) else "INSUFFICIENT"})
    return {"frame": controls, "payload": {
        "schema_version": 1, "strata": strata, "min_n": int(min_n),
        "selection_rule": "latest eligible row below threshold in the cell; strictly before the anchor for a group that anchored",
        "eligible_column": eligible_column, "eligible_when": [list(c) for c in (eligible_when or [])],
        "controls": int(len(controls)),
        "controls_by_kind": {k: int(v) for k, v in controls["control_kind"].value_counts().sort_index().items()} if len(controls) else {},
        "reportable_cells": sum(1 for c in cells if c["status"] == "OK"), "cells": cells}}


# --------------------------------------------------------------------------- #
# A5 -- anchored path
# --------------------------------------------------------------------------- #
def anchored_path(rows: pd.DataFrame, *, anchors: pd.DataFrame, by: Mapping[str, Any], group_by: Sequence[str],
                  order_by: str, offsets: Sequence[float], max_offset_seconds: float,
                  terminal_column: str, levels: Sequence[str] = (), time_unit: str = "ns") -> Dict[str, Any]:
    """The value path at declared offsets after each anchor, bounded by the anchor's terminal.

    An offset is REQUIRED only when it falls at or before the anchor's terminal; a required
    offset with no observed value censors that anchor's path (``path_censored``) and is never
    imputed. Market-path and value-path observability stay separate: an anchor whose market
    outcome is fully observed keeps it even when its value path is censored.
    """
    group_by, offsets = list(group_by), [float(o) for o in offsets]
    if not len(anchors):
        empty = pd.DataFrame(columns=list(anchors.columns) + ["path_censored", "max_value", "max_delta_from_threshold", "fell_below", "recrossed"])
        return {"frame": empty, "payload": {"schema_version": 1, "anchors": 0, "offsets_seconds": offsets}}
    _require(rows, group_by + [order_by], "path.anchored_offsets")
    _require(anchors, group_by + [order_by, terminal_column], "path.anchors")
    resolved = resolve_by(rows, by, levels=levels)
    work = rows.copy()
    for c in resolved.columns:
        work[c] = resolved[c]
    scale = NS if time_unit == "ns" else 1
    # Always key by a tuple: pandas hands back a scalar for a single grouping column in some
    # versions and a 1-tuple in others, and a silent key mismatch would look exactly like
    # "this anchor has no path" rather than like a bug.
    indexed = {(k if isinstance(k, tuple) else (k,)): g.sort_values(order_by, kind="mergesort")
               for k, g in work.groupby(group_by, sort=False)}

    records, observations = [], []
    for _, a in anchors.iterrows():
        key = tuple(a[c] for c in group_by)
        t0, terminal, threshold = float(a[order_by]), float(a[terminal_column]), float(a["_threshold"])
        limit = min((terminal - t0) / scale, float(max_offset_seconds))
        group = indexed.get(key)
        after = group[(group[order_by] > t0) & (group[order_by] <= t0 + limit * scale)] if group is not None else None
        seen = {}
        if after is not None and len(after):
            offs = ((after[order_by].astype("float64") - t0) / scale).round(6)
            for off, value in zip(offs, after["_value"]):
                if pd.notna(value):
                    seen.setdefault(float(off), float(value))
        required = [o for o in offsets if o <= limit + 1e-9]
        missing = [o for o in required if o not in seen]
        observed = pd.Series(list(seen.values()), dtype="float64")
        below = [o for o, v in sorted(seen.items()) if v < threshold]
        first_below = below[0] if below else None
        # Carry the whole anchor row through, not just its key: a later classification step must
        # be able to read the anchor's market outcome (resolved? how long?) alongside its value
        # path, and re-joining them downstream is exactly where a population silently loses rows.
        record: Dict[str, Any] = {**{c: a[c] for c in anchors.columns if not str(c).startswith("_")},
                                  "anchor_value": float(a["_value"]),
                                  "threshold": threshold, "terminal_offset_seconds": limit,
                                  "required_offsets": required, "missing_offsets": missing,
                                  "path_censored": bool(missing),
                                  "max_value": float(observed.max()) if len(observed) else None,
                                  "max_delta_from_threshold": float(observed.max() - threshold) if len(observed) else None,
                                  "fell_below": bool(below),
                                  "recrossed": bool(first_below is not None and any(v >= threshold for o, v in sorted(seen.items()) if o > first_below)),
                                  "continuously_at_or_above": bool(not below and not missing)}
        for o in offsets:
            record[f"value_at_{int(o)}s"] = seen.get(o)
            record[f"delta_at_{int(o)}s"] = (seen[o] - float(a["_value"])) if o in seen else None
        for name in levels:
            level = float(a.get(f"_level_{name}", np.nan)) if f"_level_{name}" in anchors.columns else float(resolve_by(pd.DataFrame([a]), by, levels=[name])[f"_level_{name}"].iloc[0])
            reach = [o for o, v in sorted(seen.items()) if v >= level]
            record[f"reached_{name}"] = bool(reach) or float(a["_value"]) >= level
            record[f"time_to_{name}_seconds"] = 0.0 if float(a["_value"]) >= level else (reach[0] if reach else None)
        records.append(record)
        observations += [{**{c: a[c] for c in group_by}, "offset_seconds": o, "value": v,
                          "delta_from_anchor": v - float(a["_value"]), "delta_from_threshold": v - threshold}
                         for o, v in sorted(seen.items())]
    frame = pd.DataFrame(records)
    payload = {"schema_version": 1, "anchors": int(len(frame)), "offsets_seconds": offsets,
               "max_offset_seconds": float(max_offset_seconds),
               "path_censored": int(frame["path_censored"].sum()),
               "fell_below": int(frame["fell_below"].sum()), "recrossed": int(frame["recrossed"].sum()),
               "levels": {name: {"reached": int(frame[f"reached_{name}"].sum())} for name in levels}}
    return {"frame": frame, "payload": payload, "observations": pd.DataFrame(observations)}


# --------------------------------------------------------------------------- #
# A6 -- precedence classification
# --------------------------------------------------------------------------- #
def precedence_labels(rows: pd.DataFrame, *, rules: Sequence[Mapping[str, Any]], output_column: str = "label",
                      strata: Sequence[str] = ()) -> Dict[str, Any]:
    """Ordered, first-match-wins labelling. Declaration order IS the precedence.

    Each rule is ``{label, when: [[column, op, value], ...]}`` and its conditions are ANDed; a
    rule with an empty ``when`` is an explicit catch-all. Because the first match wins, a rule
    that dominates (e.g. a censoring rule) is expressed by declaring it first, and a later rule
    can never reclaim a row an earlier one took.
    """
    if not rules:
        raise AnalysisOpError("ANALYSIS_RULES_EMPTY: precedence classification needs at least one rule")
    assigned = pd.Series(None, index=rows.index, dtype=object)
    matched_by_rule = []
    for i, rule in enumerate(rules):
        label = str(rule["label"])
        mask = pd.Series(True, index=rows.index)
        for cond in (rule.get("when") or []):
            if len(cond) != 3:
                raise AnalysisOpError(f"ANALYSIS_RULE_INVALID: rules[{i}] condition must be [column, op, value]")
            column, op, value = cond
            if op not in _COMPARISONS:
                raise AnalysisOpError(f"ANALYSIS_RULE_INVALID: rules[{i}] unknown op {op!r}; known={sorted(_COMPARISONS)}")
            _require(rows, [column], f"classify.precedence rules[{i}]")
            series = rows[column]
            if isinstance(value, bool) and series.dtype == object:
                series = series.fillna(False).astype(bool)
            mask &= _COMPARISONS[op](series, value)
        fresh = mask & assigned.isna()
        matched_by_rule.append({"rule_index": i, "label": label, "matched": int(fresh.sum()),
                                "would_have_matched": int(mask.sum())})
        assigned = assigned.where(~fresh, label)
    unlabelled = int(assigned.isna().sum())
    assigned = assigned.fillna("UNCLASSIFIED")
    payload = {"schema_version": 1, "n": int(len(rows)), "output_column": output_column,
               "precedence": [str(r["label"]) for r in rules], "unclassified": unlabelled,
               "rule_matches": matched_by_rule,
               "counts": {k: int(v) for k, v in assigned.value_counts().sort_index().items()},
               "percent": {k: (int(v) / len(rows) if len(rows) else None) for k, v in assigned.value_counts().sort_index().items()}}
    for column in strata:
        _require(rows, [column], "classify.strata")
        payload.setdefault("by_stratum", {})[column] = {
            _case_key(v): {k: int(n) for k, n in assigned[rows[column] == v].value_counts().sort_index().items()}
            for v in sorted(rows[column].unique())}
    return {"frame": rows.assign(**{output_column: assigned.values}), "payload": payload}


# --------------------------------------------------------------------------- #
# A7 -- population parity STOP GATE
# --------------------------------------------------------------------------- #
def population_parity_gate(rows: pd.DataFrame, *, reference_path: str, reference_sha256: str,
                           key: Sequence[str], reference_key: Sequence[str],
                           expected_total: Optional[int] = None,
                           expected_by: Optional[Mapping[str, Mapping[str, int]]] = None,
                           timestamp_column: Optional[str] = None,
                           reference_timestamp_column: Optional[str] = None,
                           value_map: Optional[Mapping[str, Mapping[str, Any]]] = None,
                           excluded_session_dates: Optional[Sequence[Mapping[str, str]]] = None,
                           exclusion_timezone: str = "UTC",
                           context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """RAISE unless this population is identical to a frozen reference population.

    A parity requirement written only in prose is not a gate: nothing refuses to emit the
    downstream statistics when the population silently drifts. This is the executable form. It
    runs as an ordinary pipeline step, so placing it immediately after the step that builds the
    population means a failure aborts the analyze stage before ANY declared artifact is written.

    Fails closed on: a missing reference; reference bytes that do not match the declared sha256
    (so the frozen comparison cannot itself drift); a total or per-stratum count differing from
    the declared expectation; ANY key present on one side only; and, when a timestamp column is
    declared, any row resolving at a different instant. Missing and extra keys are reported
    explicitly, not just counted -- "how many" never says which.
    """
    import hashlib

    key, reference_key = list(key), list(reference_key)
    if len(key) != len(reference_key):
        raise AnalysisOpError("ANALYSIS_PARITY_KEY_ARITY: key and reference_key must line up")
    root = Path((context or {}).get("studies_root") or ".")
    path = (root / str(reference_path)).resolve()
    if not path.is_file():
        raise AnalysisOpError("ANALYSIS_PARITY_REFERENCE_MISSING: " + str(path))
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != reference_sha256:
        raise AnalysisOpError(
            "ANALYSIS_PARITY_REFERENCE_SHA_MISMATCH: expected %s, got %s" % (reference_sha256, actual_sha))
    reference = pd.read_parquet(path)
    _require(reference, reference_key, "parity.reference_key")
    _require(rows, key, "parity.key")

    # Translate the reference's own vocabulary into this frame's (e.g. LONG/SHORT -> +1/-1).
    ref = reference.copy()
    for column, mapping in (value_map or {}).items():
        _require(ref, [column], "parity.value_map")
        table = {_case_key(k): v for k, v in mapping.items()}
        unknown = sorted(set(ref[column].map(_case_key)) - set(table))
        if unknown:
            raise AnalysisOpError("ANALYSIS_PARITY_VALUE_MAP_UNMATCHED: %s values %s" % (column, unknown))
        ref[column] = [table[_case_key(v)] for v in ref[column]]

    # PREDECLARED exceptions. Each entry is {date, reason} and is applied SYMMETRICALLY to both
    # sides before any comparison, so an exception can never hide a difference on a day that is
    # still being compared. Two properties make this a narrow escape hatch rather than a hole:
    #   * it removes whole session dates from BOTH frames, never individual keys, so it cannot
    #     be tuned to make a specific disagreement disappear;
    #   * an exception that removes nothing from EITHER side is itself a failure -- a stale
    #     declaration is a defect, not a harmless leftover.
    exclusions = [dict(e) for e in (excluded_session_dates or [])]
    removed: List[Dict[str, Any]] = []
    if exclusions:
        if not (timestamp_column and reference_timestamp_column):
            raise AnalysisOpError(
                "ANALYSIS_PARITY_EXCLUSION_NEEDS_TIMESTAMPS: excluded_session_dates requires "
                "timestamp_column and reference_timestamp_column to derive a session date")
        missing_reason = [e for e in exclusions if not e.get("date") or not e.get("reason")]
        if missing_reason:
            raise AnalysisOpError(
                "ANALYSIS_PARITY_EXCLUSION_UNREASONED: every excluded_session_dates entry needs "
                "a date and a reason: %s" % missing_reason)
        _require(rows, [timestamp_column], "parity.timestamp_column")
        _require(ref, [reference_timestamp_column], "parity.reference_timestamp_column")

        def _dates(frame, column):
            return pd.to_datetime(frame[column], unit="ns", utc=True).dt.tz_convert(exclusion_timezone).dt.date

        lhs_dates, rhs_dates = _dates(rows, timestamp_column), _dates(ref, reference_timestamp_column)
        keep_l = pd.Series(True, index=rows.index)
        keep_r = pd.Series(True, index=ref.index)
        for e in exclusions:
            day = pd.Timestamp(str(e["date"])).date()
            dl, dr = int((lhs_dates == day).sum()), int((rhs_dates == day).sum())
            removed.append({"date": str(e["date"]), "reason": str(e["reason"]),
                            "removed_from_population": dl, "removed_from_reference": dr})
            keep_l &= lhs_dates != day
            keep_r &= rhs_dates != day
        dead = [r for r in removed if r["removed_from_population"] == 0 and r["removed_from_reference"] == 0]
        if dead:
            raise AnalysisOpError(
                "ANALYSIS_PARITY_EXCLUSION_DEAD: declared exception(s) removed nothing from "
                "either side, so the declaration is stale: %s" % [d["date"] for d in dead])
        rows, ref = rows[keep_l], ref[keep_r]

    report: Dict[str, Any] = {"schema_version": 1, "reference_path": str(reference_path),
                              "reference_sha256": actual_sha,
                              "reference_rows": int(len(ref)), "population_rows": int(len(rows)),
                              "excluded_session_dates": removed,
                              "compared_after_exclusions": {"population": int(len(rows)), "reference": int(len(ref))}}
    failures: List[str] = []
    if expected_total is not None:
        report["expected_total"] = int(expected_total)
        for label, n in (("reference", len(ref)), ("population", len(rows))):
            if int(n) != int(expected_total):
                failures.append("%s has %d rows, expected %d" % (label, n, expected_total))
    if expected_by:
        report["expected_by"] = {c: dict(m) for c, m in expected_by.items()}
        report["observed_by"] = {}
        for column, expectation in expected_by.items():
            _require(rows, [column], "parity.expected_by")
            counts = {_case_key(k): int(v) for k, v in rows[column].value_counts().items()}
            report["observed_by"][column] = counts
            want = {_case_key(k): int(v) for k, v in expectation.items()}
            if counts != want:
                failures.append("%s counts %s != expected %s" % (column, counts, want))

    left = {tuple(r) for r in rows[key].itertuples(index=False, name=None)}
    right = {tuple(r) for r in ref[reference_key].itertuples(index=False, name=None)}
    missing, extra = sorted(right - left), sorted(left - right)
    report["missing_from_population"] = len(missing)
    report["extra_in_population"] = len(extra)
    report["missing_examples"] = [list(x) for x in missing[:10]]
    report["extra_examples"] = [list(x) for x in extra[:10]]
    if missing or extra:
        failures.append("%d reference key(s) absent, %d unexpected key(s) present" % (len(missing), len(extra)))

    if timestamp_column and reference_timestamp_column:
        _require(rows, [timestamp_column], "parity.timestamp_column")
        _require(ref, [reference_timestamp_column], "parity.reference_timestamp_column")
        lhs = {tuple(r[:-1]): r[-1] for r in rows[key + [timestamp_column]].itertuples(index=False, name=None)}
        rhs = {tuple(r[:-1]): r[-1] for r in ref[reference_key + [reference_timestamp_column]].itertuples(index=False, name=None)}
        drift = [{"key": list(k), "population": int(lhs[k]), "reference": int(rhs[k])}
                 for k in sorted(set(lhs) & set(rhs)) if int(lhs[k]) != int(rhs[k])]
        report["timestamp_mismatches"] = len(drift)
        report["timestamp_mismatch_examples"] = drift[:10]
        if drift:
            failures.append("%d key(s) resolve at a different instant than the reference" % len(drift))

    report["failures"] = failures
    report["status"] = "PASS" if not failures else "FAIL"
    if failures:
        raise AnalysisOpError("ANALYSIS_POPULATION_PARITY_FAILED: " + "; ".join(failures))
    return {"frame": rows, "payload": report}


# --------------------------------------------------------------------------- #
# A8 -- arm-delta integrity STOP GATE
# --------------------------------------------------------------------------- #
def _read_json(path: Path, what: str) -> Dict[str, Any]:
    import json
    if not path.is_file():
        raise AnalysisOpError(f"ANALYSIS_ARM_INTEGRITY_{what}_MISSING: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _fit_identity(manifest: Mapping[str, Any]) -> tuple:
    """The identity of the FIT, resolved from what the store actually recorded.

    Preference order matters: an explicitly recorded ``fit_identity_sha256`` is the fit; the
    canonical artifact's bytes are the next best evidence of it; ``model_id`` is last because it
    is DERIVED from the declaration (lineage, which contains ``ordered_inputs``), so two arms
    with different feature lists differ there by construction. The source is reported so a reader
    can see which of the three actually carried the check.
    """
    lineage = manifest.get("lineage") or {}
    if lineage.get("fit_identity_sha256"):
        return str(lineage["fit_identity_sha256"]), "lineage.fit_identity_sha256"
    canonical = (manifest.get("canonical") or {}).get("byte_sha256")
    if canonical:
        return str(canonical), "canonical.byte_sha256"
    return str(manifest.get("model_id")), "model_id"


def _block_population(rows: pd.DataFrame, column: str, min_non_null_rate: float) -> Dict[str, Any]:
    """Population and variance of ONE added column on the fitted population."""
    series = rows[column]
    n = int(len(series))
    n_non_null = int(series.notna().sum())
    rate = (n_non_null / n) if n else 0.0
    numeric = series if pd.api.types.is_numeric_dtype(series) else pd.to_numeric(series, errors="coerce")
    std = float(numeric.std(ddof=0)) if n_non_null else None
    if std is not None and not np.isfinite(std):
        std = None
    n_unique = int(series.nunique(dropna=True))
    return {"column": column, "n": n, "n_non_null": n_non_null, "non_null_rate": rate,
            "n_unique": n_unique, "std": std,
            "populated": bool(rate >= float(min_non_null_rate)),
            "has_variance": bool(n_unique > 1 and (std is None or std > 0.0))}


def arm_delta_integrity_gate(rows: pd.DataFrame, *, baseline_arm: str, scope: str = "per_cell",
                             min_non_null_rate: float = 0.95, require_positive_variance: bool = True,
                             require_distinct_fit_identity: bool = True, require_distinct_predictions: bool = True,
                             min_prediction_divergence: float = 0.0,
                             models_manifest: Optional[str] = None, study_id: Optional[str] = None,
                             context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """RAISE unless every non-baseline arm's ADDED feature block is alive and actually changed the fit.

    A controlled feature-family study reports the delta between an arm and a baseline arm that
    differ only by an added block of columns. If that block is degenerate on the FITTED
    population -- mostly-null without being all-null, or constant -- a boosted tree never splits
    on it, the arm collapses onto the baseline, and the paired delta is ~0 with balanced fold
    signs. That is indistinguishable from the genuine negative result "this family carries no
    information", which is the result such a study is most likely to report. An all-null column
    check (``check_feature_surface.py``) establishes neither variance nor distinctness.

    Four properties, each independently switchable and each REPORTED whether or not it is
    enforced, per non-baseline arm and per declared cell (LONG and SHORT are fit separately, so a
    block can be dead in one cell only):

    (a) ``min_non_null_rate``             -- the added block is POPULATED on the fitted population;
    (b) ``require_positive_variance``     -- and is not constant;
    (c) ``require_distinct_fit_identity`` -- and produced a model whose fit identity differs from
        the baseline arm's model in the same cell. See ``_fit_identity``: this is a
        DECLARATION-level check. It catches an arm whose feature list resolved to the baseline's
        and a reused stored model; it does NOT catch a model that ignored a block it was given.
    (d) ``require_distinct_predictions``  -- and predictions on the fitted population that are not
        identical to the baseline's. This is the BEHAVIOURAL check -- the one that fails when the
        block was present, varying and still never used. ``min_prediction_divergence`` raises the
        bar above exact identity (default 0.0 = only byte-identical scores fail).

    The gate refuses to vouch for a population it cannot reproduce: it rebuilds each cell's fitted
    population from the frame (binary-label rows, the fit stage's tuning years, the cell's declared
    subset) and RAISES when the count disagrees with the ``final_fit_rows`` the fit stage recorded.
    A check that derives its own scope cannot detect scope loss.

    It runs as an ordinary pipeline step, so a failure aborts the analyze stage before ANY declared
    artifact is written. Fails closed on: a missing models manifest or compiled plan; a missing
    baseline-arm model; an EMPTY added block (an arm whose columns are the baseline's is not an
    arm); an empty fitted population; and any model whose canonical bytes no longer hash to what
    the store recorded (``score`` verifies that before predicting).
    """
    from research_workflow.model_store import read_manifest, score

    ctx = dict(context or {})
    if scope not in ("per_cell", "pooled"):
        raise AnalysisOpError(f"ANALYSIS_ARM_INTEGRITY_SCOPE_UNKNOWN: {scope!r}; known=['per_cell', 'pooled']")
    studies_root = Path(ctx.get("studies_root") or ".")
    # An explicit declaration wins over the execution context: the context is the normal path
    # (the lifecycle knows which study it is analysing), the parameters are the escape hatch.
    if models_manifest:
        manifest_path = Path(str(models_manifest))
        if not manifest_path.is_absolute():
            manifest_path = studies_root / manifest_path
    elif study_id:
        manifest_path = studies_root / str(study_id) / "artifacts" / "experiment_models.json"
    elif ctx.get("study_dir"):
        manifest_path = Path(str(ctx["study_dir"])) / "artifacts" / "experiment_models.json"
    else:
        raise AnalysisOpError(
            "ANALYSIS_ARM_INTEGRITY_STUDY_UNRESOLVED: this gate reads the fitted arms of its own "
            "study; the execution context carries no 'study_dir' and the step declares neither "
            "'models_manifest' nor 'study_id'")
    manifest_path = manifest_path.resolve()
    models_doc = _read_json(manifest_path, "MODELS")
    plan = _read_json(manifest_path.parent.parent / "compiled_plan.json", "PLAN")
    model_root = ctx.get("model_root")
    model_root = Path(str(model_root)) if model_root else None

    trained = [m for m in (models_doc.get("models") or []) if isinstance(m, Mapping)]
    if not trained:
        raise AnalysisOpError(f"ANALYSIS_ARM_INTEGRITY_NO_ARMS: {manifest_path} records no fitted models")
    label = str(models_doc.get("label_column") or (plan.get("outcome") or {}).get("label_column") or "")
    if not label:
        raise AnalysisOpError("ANALYSIS_ARM_INTEGRITY_LABEL_UNKNOWN: neither the models manifest nor the "
                              "compiled plan names a label column")
    tuning_years = [int(y) for y in (models_doc.get("tuning_years") or [])]
    cells = {str(c["id"]): dict(c.get("subset") or {}) for c in ((plan.get("model") or {}).get("cells") or [])}
    if not cells:
        cells = {"all": {}}

    _require(rows, [label], "arm_delta_integrity.label")
    frame = rows
    if "_year" not in frame.columns:
        _require(frame, ["observation_ts"], "arm_delta_integrity.year")
        frame = frame.assign(_year=pd.to_datetime(frame["observation_ts"], unit="ns", utc=True).dt.year)
    # The fit stage's own population rule, mirrored exactly (lifecycle_v2 fit): binary label
    # rows, restricted to the tuning years the manifest recorded, then the cell's subset.
    binary = frame[frame[label].isin([0, 1, 0.0, 1.0])]
    if tuning_years:
        binary = binary[binary["_year"].isin(tuning_years)]

    failures: List[str] = []
    cell_report: List[Dict[str, Any]] = []
    populations: Dict[str, pd.DataFrame] = {}
    for cell_id, subset in cells.items():
        pop = binary
        for column, value in subset.items():
            _require(pop, [column], f"arm_delta_integrity.cell[{cell_id}].subset")
            pop = pop[pop[column] == value]
        populations[cell_id] = pop
        recorded = sorted({int(m["final_fit_rows"]) for m in trained
                           if str(m.get("cell")) == cell_id and m.get("final_fit_rows") is not None})
        cell_report.append({"cell": cell_id, "subset": {k: str(v) for k, v in subset.items()},
                            "rebuilt_fitted_rows": int(len(pop)), "recorded_final_fit_rows": recorded,
                            "population_reconciled": bool(recorded == [int(len(pop))])})
        if not len(pop):
            failures.append(f"cell {cell_id!r} rebuilds an EMPTY fitted population; the gate can establish nothing on it")
        elif recorded and recorded != [int(len(pop))]:
            failures.append(f"cell {cell_id!r} rebuilt {len(pop)} fitted rows but the fit stage recorded {recorded}; "
                            "the gate cannot vouch for a population it cannot reproduce")

    arm_report: List[Dict[str, Any]] = []
    for cell_id in cells:
        in_cell = [m for m in trained if str(m.get("cell")) == cell_id]
        base = [m for m in in_cell if str(m.get("arm")) == str(baseline_arm)]
        if not base:
            failures.append(f"cell {cell_id!r} has no model for the declared baseline arm {baseline_arm!r}")
            continue
        base_rec = base[0]
        base_cols = list(base_rec.get("features") or [])
        base_identity, base_identity_source = _fit_identity(read_manifest(str(base_rec["model_id"]), model_root))
        for rec in in_cell:
            arm = str(rec.get("arm"))
            if arm == str(baseline_arm):
                continue
            arm_cols = list(rec.get("features") or [])
            added = [c for c in arm_cols if c not in base_cols]
            arm_failures: List[str] = []
            report: Dict[str, Any] = {"arm": arm, "cell": cell_id, "model_id": rec.get("model_id"),
                                      "baseline_model_id": base_rec.get("model_id"), "added_block": added,
                                      "removed_from_baseline": [c for c in base_cols if c not in arm_cols],
                                      "columns": [], "failures": arm_failures}
            arm_report.append(report)
            if not added:
                arm_failures.append(f"arm {arm!r} cell {cell_id!r}: the added block is EMPTY -- its columns are the "
                                    "baseline arm's, so there is no delta for this gate to vouch for")
                failures.extend(arm_failures)
                continue
            measured = populations[cell_id] if scope == "per_cell" else binary
            _require(measured, added, f"arm_delta_integrity.added_block[{arm}/{cell_id}]")
            for column in added:
                stat = _block_population(measured, column, min_non_null_rate)
                report["columns"].append(stat)
                if not stat["populated"]:
                    arm_failures.append(f"arm {arm!r} cell {cell_id!r}: added column {column!r} is populated on "
                                        f"{stat['non_null_rate']:.4f} of the fitted population, below {min_non_null_rate}")
                if require_positive_variance and not stat["has_variance"]:
                    arm_failures.append(f"arm {arm!r} cell {cell_id!r}: added column {column!r} is CONSTANT on the "
                                        f"fitted population (n_unique={stat['n_unique']}, std={stat['std']})")
            identity, identity_source = _fit_identity(read_manifest(str(rec["model_id"]), model_root))
            report.update({"fit_identity": identity, "fit_identity_source": identity_source,
                           "baseline_fit_identity": base_identity, "baseline_fit_identity_source": base_identity_source,
                           "fit_identity_distinct": bool(identity != base_identity)})
            if require_distinct_fit_identity and identity == base_identity:
                arm_failures.append(f"arm {arm!r} cell {cell_id!r}: fit identity is IDENTICAL to the baseline arm's "
                                    f"({identity_source}={identity})")
            pop = populations[cell_id]
            if len(pop):
                diff = np.abs(np.asarray(score(str(rec["model_id"]), pop, model_root=model_root), dtype=float)
                              - np.asarray(score(str(base_rec["model_id"]), pop, model_root=model_root), dtype=float))
                identical = int((diff == 0.0).sum())
                prediction = {"n": int(len(pop)), "max_abs_diff": float(diff.max()), "mean_abs_diff": float(diff.mean()),
                              "identical_rows": identical, "identical_fraction": float(identical / len(pop)),
                              "distinct": bool(float(diff.max()) > float(min_prediction_divergence))}
                report["predictions"] = prediction
                if require_distinct_predictions and not prediction["distinct"]:
                    arm_failures.append(f"arm {arm!r} cell {cell_id!r}: predictions on the fitted population do not "
                                        f"diverge from the baseline arm's (max_abs_diff={prediction['max_abs_diff']:.3e} "
                                        f"<= {min_prediction_divergence}); the added block did not change the model")
            failures.extend(arm_failures)

    payload = {"schema_version": 1, "baseline_arm": str(baseline_arm), "scope": scope,
               "thresholds": {"min_non_null_rate": float(min_non_null_rate),
                              "require_positive_variance": bool(require_positive_variance),
                              "require_distinct_fit_identity": bool(require_distinct_fit_identity),
                              "require_distinct_predictions": bool(require_distinct_predictions),
                              "min_prediction_divergence": float(min_prediction_divergence)},
               "models_manifest": str(manifest_path), "label_column": label, "tuning_years": tuning_years,
               "population": {"rows_in": int(len(rows)), "binary_rows_in_tuning_years": int(len(binary))},
               "cells": cell_report, "arms": arm_report, "failures": failures,
               "status": "PASS" if not failures else "FAIL"}
    if failures:
        raise AnalysisOpError("ANALYSIS_ARM_DELTA_INTEGRITY_FAILED: " + "; ".join(failures))
    return {"frame": rows, "payload": payload}



def tail_lift(rows: pd.DataFrame, *, reference: pd.DataFrame, score: str, label: str,
              quantiles: Sequence[float] = (0.90, 0.95, 0.975), group_by: Optional[str] = None,
              interpolation: str = "higher") -> Dict[str, Any]:
    """Label-rate lift inside the score tail, at thresholds FROZEN from a reference frame.

    The threshold for each quantile is the quantile of ``score`` on ``reference`` (per ``group_by`` value
    when given), never on ``rows`` themselves: a tail evaluated at its own in-sample quantile is a
    description, not a test. Declare ``inputs: {reference: <train step>}`` and point ``rows`` at the
    evaluation frame. ``lift = tail label rate / base label rate`` where base is the label rate of every
    evaluated row of the group. Rows with a null score or a non-binary label (censored) are excluded and
    counted in the payload; a group with no reference rows is an error, not a silent skip.

    Named as ANALYSIS_HARNESS_GAP by es_180s_model_c_portability (2026-09-06): frozen TRAIN P90/P95/P97.5
    tail lift applied to OOS was one of three required outputs the platform could not express.
    """
    cols = [score, label] + ([group_by] if group_by else [])
    _require(rows, cols, "tail_lift.rows")
    _require(reference, [score] + ([group_by] if group_by else []), "tail_lift.reference")
    qs = sorted({float(q) for q in quantiles})
    if not qs or any(not (0.0 < q < 1.0) for q in qs):
        raise AnalysisOpError(f"ANALYSIS_TAIL_LIFT_QUANTILES_INVALID: {list(quantiles)!r} (each must satisfy 0 < q < 1)")
    if interpolation not in ("higher", "lower", "nearest", "linear", "midpoint"):
        raise AnalysisOpError(f"ANALYSIS_TAIL_LIFT_INTERPOLATION_INVALID: {interpolation!r}")
    binary = {0, 1, 0.0, 1.0, True, False}
    ev0 = rows[rows[score].notna()]
    ev = ev0[ev0[label].isin(binary)]
    ref = reference[reference[score].notna()]
    excluded = {"rows_null_score": int(len(rows) - len(ev0)), "rows_non_binary_label": int(len(ev0) - len(ev)),
                "reference_null_score": int(len(reference) - len(ref))}
    if group_by is None:
        groups: List[Any] = [None]
    else:
        groups = sorted(ev[group_by].dropna().unique().tolist(), key=lambda v: (str(type(v)), str(v)))
    cells: List[Dict[str, Any]] = []
    for g in groups:
        e = ev if g is None else ev[ev[group_by] == g]
        r = ref if g is None else ref[ref[group_by] == g]
        if len(r) == 0:
            raise AnalysisOpError(f"ANALYSIS_TAIL_LIFT_REFERENCE_EMPTY: group {g!r} has no reference rows with a score")
        if len(e) == 0:
            raise AnalysisOpError(f"ANALYSIS_TAIL_LIFT_ROWS_EMPTY: group {g!r} has no evaluable rows")
        base = float(e[label].astype(float).mean())
        for q in qs:
            thr = float(r[score].astype(float).quantile(q, interpolation=interpolation))
            tail = e[e[score].astype(float) >= thr]
            n_tail = int(len(tail))
            tail_rate = float(tail[label].astype(float).mean()) if n_tail else None
            lift = (tail_rate / base) if (n_tail and base > 0.0) else None
            cells.append({"group": g, "quantile": q, "threshold": thr, "n_reference": int(len(r)), "n_rows": int(len(e)),
                          "n_tail": n_tail, "tail_share": n_tail / len(e), "base_rate": base, "tail_rate": tail_rate, "lift": lift})
    frame = pd.DataFrame(cells, columns=["group", "quantile", "threshold", "n_reference", "n_rows", "n_tail", "tail_share",
                                         "base_rate", "tail_rate", "lift"])
    payload = {"score": score, "label": label, "group_by": group_by, "quantiles": qs, "interpolation": interpolation,
               "excluded": excluded, "cells": cells}
    return {"frame": frame, "payload": payload}


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
OPS = {
    "analysis.anchor.first_threshold_crossing": anchor_first_threshold_crossing,
    "analysis.incidence.cumulative": cumulative_incidence,
    "analysis.decomposition.buckets": bucket_decomposition,
    "analysis.control.cell_matched": cell_matched_controls,
    "analysis.path.anchored_offsets": anchored_path,
    "analysis.classify.precedence": precedence_labels,
    "analysis.gate.population_parity": population_parity_gate,
    "analysis.gate.arm_delta_integrity": arm_delta_integrity_gate,
    "analysis.metric.tail_lift": tail_lift,
}
# Which extra frames each op consumes besides its primary ``rows`` input. The compiler reads
# this to prove a declared step's inputs are bound before the study is ever executed.
OP_INPUTS = {
    "analysis.anchor.first_threshold_crossing": (),
    "analysis.incidence.cumulative": (),
    "analysis.decomposition.buckets": (),
    "analysis.control.cell_matched": ("anchors",),
    "analysis.path.anchored_offsets": ("anchors",),
    "analysis.classify.precedence": (),
    "analysis.gate.population_parity": (),
    "analysis.gate.arm_delta_integrity": (),
    "analysis.metric.tail_lift": ("reference",),
}

# Ops needing machine-local resolution context. Never part of the plan identity: where an
# operator keeps their files is not a scientific fact.
OP_CONTEXT = frozenset({"analysis.gate.population_parity", "analysis.gate.arm_delta_integrity"})


def run_op(op: str, rows: pd.DataFrame, *, inputs: Mapping[str, pd.DataFrame] | None = None,
           params: Mapping[str, Any] | None = None,
           context: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    if op not in OPS:
        raise AnalysisOpError(f"ANALYSIS_OP_UNKNOWN: {op!r}; known={sorted(OPS)}")
    kwargs = dict(params or {})
    if op in OP_CONTEXT:
        kwargs["context"] = dict(context or {})
    for name in OP_INPUTS[op]:
        if name not in (inputs or {}):
            raise AnalysisOpError(f"ANALYSIS_OP_INPUT_MISSING: {op} needs input {name!r}")
        kwargs[name] = (inputs or {})[name]
    return OPS[op](rows, **kwargs)

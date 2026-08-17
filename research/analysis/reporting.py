"""Standard tables and the compact reviewer packet (roadmap A4).

Every table carries its own sample size, filters, data identity, metric definitions
and caveats, so a table can be read on its own without the reader reconstructing
what produced it. `analysis_context.json` is deliberately small: it references
artifacts rather than embedding data, so a reasoning agent can consume it without
loading parquet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from research.analysis.metrics import (
    METRIC_DEFINITIONS, classification_bundle, economic_bundle,
)
from research.analysis.slices import SliceResult, build_slices, slice_decile

REPORTING_VERSION = "1.0.0"


@dataclass
class StandardTable:
    """A table plus everything needed to interpret it without external context."""

    name: str
    rows: List[Dict[str, Any]]
    slice_name: str
    filters: Dict[str, Any] = field(default_factory=dict)
    dataset_identity_sha256: Optional[str] = None
    analysis_spec_sha256: Optional[str] = None
    caveats: List[str] = field(default_factory=list)
    metric_definitions: Dict[str, str] = field(default_factory=dict)
    # Row reconciliation (H4). `n_input_rows` is the population the table was built
    # from; `reconciles_rows` says whether Σ(row n) is supposed to equal it. It is
    # False for the arm table (every arm is scored on ALL rows, so the sum is
    # n_arms × N by design) and for a slice that could not be derived at all.
    n_input_rows: Optional[int] = None
    reconciles_rows: bool = True

    @property
    def total_n(self) -> int:
        return int(sum(r.get("n", 0) for r in self.rows))

    @property
    def unassigned_rows(self) -> Optional[int]:
        if not self.reconciles_rows or self.n_input_rows is None:
            return None
        return int(self.n_input_rows) - self.total_n

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.name,
            "slice": self.slice_name,
            "reporting_version": REPORTING_VERSION,
            "n_rows_in_table": len(self.rows),
            "total_sample_count": self.total_n,
            "n_input_rows": self.n_input_rows,
            "row_reconciliation": (
                "sum(group n) == n_input_rows" if self.reconciles_rows
                else "not applicable to this table"
            ),
            "filters": self.filters,
            "dataset_identity_sha256": self.dataset_identity_sha256,
            "analysis_spec_sha256": self.analysis_spec_sha256,
            "metric_definitions": self.metric_definitions,
            "caveats": self.caveats,
            "rows": self.rows,
        }

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def write(self, out_dir: Path) -> Dict[str, str]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"{self.name}.csv"
        json_path = out_dir / f"{self.name}.json"
        # LF everywhere: a harness artifact whose bytes depend on the host OS cannot
        # be hash-compared across machines (L8).
        self.to_frame().to_csv(csv_path, index=False, lineterminator="\n")
        json_path.write_text(json.dumps(self.to_dict(), indent=2, default=str),
                             encoding="utf-8", newline="\n")
        return {"csv": csv_path.as_posix(), "json": json_path.as_posix()}


REQUIRED_TABLE_KEYS = (
    "table", "slice", "total_sample_count", "n_input_rows", "filters",
    "dataset_identity_sha256", "metric_definitions", "caveats", "rows",
)

UNASSIGNED_GROUP = "unassigned"


def _row_metrics(y: pd.Series, scores: Optional[pd.Series]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {"n": int(len(y))}
    try:
        bundle = classification_bundle(y, scores)
    except (ValueError, TypeError, FloatingPointError) as err:
        # One pathological group must not abort the whole table build (M6). Report
        # the refusal in the row rather than losing every other group with it.
        flat["metrics_status"] = "not_computable"
        flat["metrics_reason"] = f"metric bundle raised {type(err).__name__}: {err}"
        return flat
    for key, res in bundle.items():
        flat[key] = res["value"]
        if res["status"] != "ok":
            flat[f"{key}_status"] = res["status"]
            flat[f"{key}_reason"] = res["reason"]
    return flat


def build_slice_table(
    y: pd.Series,
    sl: SliceResult,
    *,
    scores: Optional[pd.Series] = None,
    name: Optional[str] = None,
    dataset_identity_sha256: Optional[str] = None,
    analysis_spec_sha256: Optional[str] = None,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> StandardTable:
    """One row per group of a slice, with per-group metrics and status."""
    table_name = name or f"by_{sl.name}"
    caveats: List[str] = []
    rows: List[Dict[str, Any]] = []
    n_input = int(len(y))
    derivable = bool(sl.derivable and sl.labels is not None)

    if not derivable:
        caveats.append(f"slice '{sl.name}' is not derivable on this dataset: {sl.reason}")
    else:
        if sl.degenerate:
            caveats.append(
                f"slice '{sl.name}' has {len(sl.groups)} group(s); this is not a comparison "
                f"on this collection ({sl.reason})"
            )
        labels = sl.labels.reset_index(drop=True)
        y_r = y.reset_index(drop=True)
        s_r = scores.reset_index(drop=True) if scores is not None else None
        assigned = np.zeros(n_input, dtype=bool)
        for group in sl.groups:
            mask = (labels == group).fillna(False).to_numpy().astype(bool)
            assigned |= mask
            grp_y = y_r[mask]
            grp_s = s_r[mask] if s_r is not None else None
            row = {"group": _plain(group)}
            row.update(_row_metrics(grp_y, grp_s))
            rows.append(row)

        # H4: a row that belongs to no group is invisible to every per-group check.
        # `pd.cut` yields NaN outside its bins and `qcut` yields NaN for NaN input, so
        # a negative regime_age_seconds, a NaT timestamp or a NaN score silently
        # shrinks total_sample_count while the table still looks internally coherent.
        # Account for every input row explicitly instead.
        unassigned_mask = ~assigned
        n_unassigned = int(unassigned_mask.sum())
        if n_unassigned:
            row = {"group": UNASSIGNED_GROUP}
            row.update(_row_metrics(
                y_r[unassigned_mask],
                s_r[unassigned_mask] if s_r is not None else None,
            ))
            rows.append(row)
            caveats.append(
                f"slice '{sl.name}' left {n_unassigned} of {n_input} rows in no group "
                f"(value outside the slice's declared bins, or null); they are reported as "
                f"'{UNASSIGNED_GROUP}' and are NOT part of any comparison group"
            )

    small = [r["group"] for r in rows if r.get("n", 0) < 30]
    if small:
        caveats.append(
            f"groups with n<30 (metrics are unstable at this size): {small}"
        )

    defs = {k: METRIC_DEFINITIONS[k] for k in ("sample_count", "positive_rate", "roc_auc",
                                               "pr_auc", "brier") if k in METRIC_DEFINITIONS}
    filters = {"slice": sl.name, "slice_definition": sl.definition}
    if extra_filters:
        filters.update(extra_filters)

    return StandardTable(
        name=table_name, rows=rows, slice_name=sl.name, filters=filters,
        dataset_identity_sha256=dataset_identity_sha256,
        analysis_spec_sha256=analysis_spec_sha256,
        caveats=caveats, metric_definitions=defs,
        n_input_rows=n_input, reconciles_rows=derivable,
    )


def _plain(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v) if not isinstance(v, (int, float, bool, str)) else v


def build_arm_table(
    y: pd.Series,
    arm_scores: Dict[str, Sequence[float]],
    *,
    dataset_identity_sha256: Optional[str] = None,
    analysis_spec_sha256: Optional[str] = None,
    arm_provenance: Optional[Dict[str, Dict[str, Any]]] = None,
) -> StandardTable:
    """The declared A/B/C comparison: one row per arm, identical evaluation rows."""
    rows: List[Dict[str, Any]] = []
    for arm, scores in arm_scores.items():
        s = pd.Series(list(scores), dtype="float64")
        row = {"arm": arm}
        row.update(_row_metrics(y.reset_index(drop=True), s))
        if arm_provenance and arm in arm_provenance:
            p = arm_provenance[arm]
            row["n_features"] = p.get("n_features")
            row["seed"] = p.get("seed")
            row["estimator"] = p.get("estimator")
            row["fit_identity_sha256"] = p.get("fit_identity_sha256")
        rows.append(row)

    caveats = [
        "All arms are scored on the identical evaluation rows; differences are attributable "
        "to the feature sets, not to differing samples.",
    ]
    if len(y) < 30:
        caveats.append(f"evaluation set is small (n={len(y)}); arm differences are not meaningful")

    return StandardTable(
        name="by_arm", rows=rows, slice_name="model_arm",
        filters={"comparison": "declared A/B/C feature-set arms"},
        dataset_identity_sha256=dataset_identity_sha256,
        analysis_spec_sha256=analysis_spec_sha256,
        caveats=caveats,
        metric_definitions={k: METRIC_DEFINITIONS[k] for k in
                            ("sample_count", "positive_rate", "roc_auc", "pr_auc", "brier")},
        # Every arm is scored on ALL rows, so Σ(row n) is n_arms × N by construction.
        n_input_rows=int(len(y)), reconciles_rows=False,
    )


def build_decile_table(
    y: pd.Series,
    scores: Sequence[float],
    *,
    n_buckets: int = 10,
    dataset_identity_sha256: Optional[str] = None,
    analysis_spec_sha256: Optional[str] = None,
) -> StandardTable:
    sl = slice_decile(scores, n_buckets=n_buckets)
    return build_slice_table(
        y, sl, scores=pd.Series(list(scores), dtype="float64"), name="by_decile",
        dataset_identity_sha256=dataset_identity_sha256,
        analysis_spec_sha256=analysis_spec_sha256,
        extra_filters={"n_buckets": n_buckets},
    )


def build_standard_tables(
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    scores: Optional[Sequence[float]] = None,
    arm_scores: Optional[Dict[str, Sequence[float]]] = None,
    arm_provenance: Optional[Dict[str, Dict[str, Any]]] = None,
    dataset_identity_sha256: Optional[str] = None,
    analysis_spec_sha256: Optional[str] = None,
    slice_names: Sequence[str] = ("direction", "year", "partition", "maturity", "session", "regime"),
) -> Dict[str, StandardTable]:
    """The standard set: A/B/C, direction, year, maturity, decile (+ partition, session, regime)."""
    s = pd.Series(list(scores), dtype="float64") if scores is not None else None
    tables: Dict[str, StandardTable] = {}

    for name, sl in build_slices(meta, slice_names).items():
        t = build_slice_table(
            y, sl, scores=s,
            dataset_identity_sha256=dataset_identity_sha256,
            analysis_spec_sha256=analysis_spec_sha256,
        )
        tables[t.name] = t

    if scores is not None:
        tables["by_decile"] = build_decile_table(
            y, scores, dataset_identity_sha256=dataset_identity_sha256,
            analysis_spec_sha256=analysis_spec_sha256,
        )
    if arm_scores:
        tables["by_arm"] = build_arm_table(
            y, arm_scores, dataset_identity_sha256=dataset_identity_sha256,
            analysis_spec_sha256=analysis_spec_sha256, arm_provenance=arm_provenance,
        )
    return tables


# ---------------------------------------------------------------------------
# Context packet
# ---------------------------------------------------------------------------


def build_analysis_context(
    *,
    analysis_id: str,
    question: str,
    dataset_identity: Dict[str, Any],
    analysis_spec_sha256: Optional[str],
    validation: Dict[str, Any],
    tables: Dict[str, StandardTable],
    table_paths: Optional[Dict[str, Dict[str, str]]] = None,
    headline_metrics: Optional[Dict[str, Any]] = None,
    caveats: Optional[Sequence[str]] = None,
    allow_unsealed_collection: bool = False,
) -> Dict[str, Any]:
    """Compact packet for a reasoning agent: identity, metrics, paths, caveats.

    References artifacts rather than embedding data — the whole point is that a
    reviewer can answer the research question without opening parquet.
    """
    all_caveats: List[str] = list(caveats or [])
    for t in tables.values():
        all_caveats.extend(f"[{t.name}] {c}" for c in t.caveats)

    identity = dataset_identity.get("identity", {})
    return {
        "schema_version": REPORTING_VERSION,
        "analysis_id": analysis_id,
        "question": question,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "collection_identity_sha256": dataset_identity.get("collection_identity_sha256"),
            "analysis_spec_sha256": analysis_spec_sha256,
            "run_id": identity.get("run_id"),
            "study_id": identity.get("study_id"),
            "sealed": dataset_identity.get("sealed"),
            "allow_unsealed_collection": bool(allow_unsealed_collection),
            "stage": identity.get("stage"),
            "window": [identity.get("start_date"), identity.get("end_date")],
        },
        "validation": {
            "passed": validation.get("passed"),
            "failed_checks": [c["check"] for c in validation.get("checks", []) if not c["passed"]],
            "spec_supplied": validation.get("spec_supplied"),
            "skipped_checks": validation.get("skipped_checks", []),
            "partition_row_counts": validation.get("partition_row_counts", {}),
            "join_key": validation.get("join_key", []),
            "join_key_source": validation.get("join_key_source"),
            "metadata_source": validation.get("metadata_source"),
        },
        "headline_metrics": headline_metrics or {},
        # The per-table summary is what binds the packet to the tables it claims to
        # describe: `check_report_completeness` reconciles every field here against
        # the table objects it is handed (N1). Recording only names and a total would
        # let a different table set pass the same gate.
        "tables": {
            name: {
                "slice": t.slice_name,
                "n_groups": len(t.rows),
                "total_sample_count": t.total_n,
                "n_input_rows": t.n_input_rows,
                "reconciles_rows": t.reconciles_rows,
                "unassigned_rows": t.unassigned_rows,
                "paths": (table_paths or {}).get(name, {}),
            }
            for name, t in tables.items()
        },
        "metric_definitions": METRIC_DEFINITIONS,
        "caveats": all_caveats,
        "data_access_note": (
            "This packet references artifacts; it does not embed row-level data. Open the "
            "referenced tables only if an anomaly needs investigation."
        ),
    }


def write_analysis_context(context: Dict[str, Any], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(context, indent=2, default=str), encoding="utf-8",
                        newline="\n")
    return out_path


def check_report_completeness(context: Dict[str, Any], tables: Dict[str, StandardTable]) -> List[str]:
    """Returns a list of completeness problems; empty means complete.

    This is the only mechanical gate over the reviewer packet, so it must read the
    verdict rather than merely confirm a verdict field exists (M5), reconcile row
    counts rather than trust a table's own total (H4), and check the tables it is
    handed are the ones the packet describes (N1).
    """
    problems: List[str] = []
    identity = context.get("identity", {})
    if not identity.get("collection_identity_sha256"):
        problems.append("context is missing collection_identity_sha256")
    if context.get("analysis_spec_sha256") is None and not identity.get("analysis_spec_sha256"):
        problems.append("context is missing analysis_spec_sha256")

    validation = context.get("validation")
    if validation is None:
        problems.append("context is missing the validation summary")
    else:
        # M5: previously this asserted only that the key existed, so a
        # hash-mismatched, unsealed analysis was reported as "complete".
        if validation.get("passed") is not True:
            problems.append(
                f"validation did not pass (passed={validation.get('passed')!r}; "
                f"failed checks: {validation.get('failed_checks') or 'unreported'})"
            )
        if validation.get("spec_supplied") is False:
            problems.append(
                "validation ran without an analysis spec, so these checks never ran: "
                f"{validation.get('skipped_checks') or 'unrecorded'}"
            )

    if identity.get("sealed") is False and not identity.get("allow_unsealed_collection"):
        problems.append(
            "collection is unsealed and no allow_unsealed_collection authorisation is recorded"
        )

    # N1: the gate must validate THIS packet's table set. Previously it iterated
    # only over whatever `tables` it was handed, so a context built from six tables
    # over 120 rows was reported complete when passed `{}`, or when passed an
    # unrelated set of tables over 30 rows. A completeness check that derives its own
    # scope from its argument cannot detect that the scope is wrong.
    ctx_tables = context.get("tables")
    if not isinstance(ctx_tables, dict):
        problems.append("context is missing the tables summary, so no table set can be verified")
        ctx_tables = {}
    for name in sorted(set(ctx_tables) - set(tables)):
        problems.append(
            f"context declares table {name!r} but it was not supplied for verification"
        )
    for name in sorted(set(tables) - set(ctx_tables)):
        problems.append(
            f"table {name!r} was supplied but the context packet does not declare it"
        )

    for name, t in tables.items():
        # Same name is not the same table: reconcile every summary field the packet
        # recorded against the object handed in, so a replacement table object cannot
        # be silently validated against another table's summary.
        summary = ctx_tables.get(name)
        if isinstance(summary, dict):
            for key, actual in (
                ("slice", t.slice_name),
                ("n_groups", len(t.rows)),
                ("total_sample_count", t.total_n),
                ("n_input_rows", t.n_input_rows),
                ("reconciles_rows", t.reconciles_rows),
                ("unassigned_rows", t.unassigned_rows),
            ):
                if key in summary and summary[key] != actual:
                    problems.append(
                        f"table {name} does not match the context packet: context records "
                        f"{key}={summary[key]!r} but the supplied table has {key}={actual!r}"
                    )

        d = t.to_dict()
        for key in REQUIRED_TABLE_KEYS:
            if key not in d:
                problems.append(f"table {name} is missing required key {key!r}")
        if not d.get("metric_definitions"):
            problems.append(f"table {name} declares no metric definitions")
        if d.get("dataset_identity_sha256") is None:
            problems.append(f"table {name} does not carry a dataset identity")
        unassigned = t.unassigned_rows
        if unassigned:
            problems.append(
                f"table {name} does not account for every input row: "
                f"total_sample_count={t.total_n} vs n_input_rows={t.n_input_rows} "
                f"({unassigned} unreconciled)"
            )
    return problems

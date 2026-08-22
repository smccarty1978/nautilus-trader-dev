#!/usr/bin/env python3
"""Declared feature contract <=> produced feature surface (Finding C1).

The failed ES acceptance test recorded a run as ``COMPLETED`` / ``SUCCESS`` with 1748
candidates in which ``latest_1m_wick_imbalance`` was **100% NULL**. Every control that
looked at features passed, because every one of them asked a question about *column
names*: does the column exist, is the count right, does the ordered list hash match.
None asked whether the feature had a value.

This module asks that question, and asks it against the authoritative registry rather
than a hard-coded rule. The distinction that matters:

``null_policy='disallow'``
    no nulls are permitted at all.
``null_policy='allow'``
    *some* nulls are permitted -- typically warmup, where the feature genuinely does
    not exist yet. It is not a licence for an all-null column. A column that is null in
    every row was never emitted, and "never emitted" is a different fact from
    "sometimes unavailable". That case is refused under **either** policy.

Used by both ``OutputManager.persist_collection`` (so a bad collection cannot be filed
as successful) and ``scripts/validate_smoke.py`` (so acceptance re-derives it
independently). The duplication is deliberate: they are separate gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_NUMERIC_DTYPES = {"float64", "float32", "int64", "int32"}

# Legitimate non-feature columns emitted by the canonical collector: candidate identity,
# timing, causality metadata and running state. Anything outside this set AND outside the
# declared feature list is an undeclared feature column.
DEFAULT_METADATA_COLUMNS = (
    "observation_ts",
    "regime_start_ns",
    "regime_direction",
    "checkpoint_index",
    "regime_age_seconds",
    "close",
    "atr",
    "running_mfe_atr",
    "running_mae_atr",
    "current_pnl_atr",
    "new_progress_windows",
    "retained_mfe_ratio",
    "triggering_1s_ts_init",
)


class FeatureSurfaceError(RuntimeError):
    """Raised when the produced feature surface contradicts the declared contract."""


@dataclass
class SurfaceReport:
    passed: bool
    findings: List[Dict[str, Any]] = field(default_factory=list)
    per_feature: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    declared_features: List[str] = field(default_factory=list)
    emitted_features: List[str] = field(default_factory=list)
    metadata_columns: List[str] = field(default_factory=list)
    collection_universe_columns: List[str] = field(default_factory=list)
    undeclared_columns: List[str] = field(default_factory=list)
    rows: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "rows": self.rows,
            "declared_features": self.declared_features,
            "emitted_features": self.emitted_features,
            "metadata_columns": self.metadata_columns,
            "collection_universe_columns": self.collection_universe_columns,
            "undeclared_columns": self.undeclared_columns,
            "per_feature": self.per_feature,
            "findings": self.findings,
        }


def _dtype_compatible(series, declared: str) -> bool:
    """Is the produced pandas dtype usable as the registry's declared dtype?

    Deliberately tolerant in one direction only: an all-``None`` object column is *not*
    accepted as float64 -- that is precisely the historical failure. A float column
    holding NaNs is accepted, because NaN is how pandas represents a permitted null.
    """
    import pandas as pd  # local: keeps this module importable without pandas loaded

    kind = series.dtype.kind
    if declared in ("float64", "float32"):
        return kind == "f"
    if declared in ("int64", "int32"):
        # A nullable integer feature surfaces as float once any null is present.
        return kind in ("i", "f")
    if declared == "bool":
        return kind == "b"
    return True  # unconstrained declaration


def validate_feature_surface(
    candidates_df,
    declared_features: List[str],
    registry: Optional[Dict[str, Any]] = None,
    *,
    strict_order: bool = True,
    metadata_columns: Optional[List[str]] = None,
    collection_universe: Optional[List[str]] = None,
) -> SurfaceReport:
    """Validates a produced candidate surface against its declared feature contract.

    Both directions are enforced (W2): every declared feature must be present, AND no
    undeclared *feature* column may appear. Checking only the forward direction lets an
    unreviewed feature ride along into the surface -- it satisfies every contract check,
    because no contract check ever looks at it.

    ``metadata_columns`` names the legitimate non-feature columns (identity, timing,
    target, bookkeeping). They are explicitly distinguished rather than guessed, so a
    real metadata column is never rejected as a stowaway feature.

    ``collection_universe`` (Phase 1 Packet D2) names features that ARE features -- not
    metadata -- but are not yet part of the frozen, ordered ``declared_features`` list. A
    study collecting from a registry-defined candidate universe before TRAIN-stage
    selection freezes its Top-N model list legitimately emits any subset of that universe;
    columns in it are excluded from the "undeclared" check the same way metadata is, but
    -- unlike ``declared_features`` -- membership here never participates in the strict
    ordered-identity/hash check below. That check remains exclusively about the later
    frozen model feature list, so a wide collection-time universe can never be mistaken
    for a frozen, ordered model input list.
    """
    if registry is None:
        from features.registry import FEATURE_REGISTRY as registry  # noqa: N806

    declared_features = list(declared_features or [])
    report = SurfaceReport(
        passed=True,
        declared_features=declared_features,
        rows=int(len(candidates_df)),
    )

    def fail(code: str, feature: Optional[str], message: str) -> None:
        report.passed = False
        report.findings.append({"code": code, "feature": feature, "message": message})

    meta = set(metadata_columns if metadata_columns is not None else DEFAULT_METADATA_COLUMNS)
    report.metadata_columns = sorted(meta)

    collection_universe_set = set(collection_universe or ())
    report.collection_universe_columns = sorted(collection_universe_set)

    # W2 (reverse direction): no undeclared feature column may enter the surface.
    # Runs whether or not features are declared -- a study declaring none must emit none,
    # unless collection_universe explicitly widens what's allowed at collection time.
    undeclared = [
        c for c in candidates_df.columns
        if c not in set(declared_features) and c not in meta and c not in collection_universe_set
    ]
    if undeclared:
        report.undeclared_columns = sorted(undeclared)
        fail(
            "UNDECLARED_FEATURE_COLUMN", None,
            f"columns {sorted(undeclared)} are neither declared features nor declared "
            f"metadata. An undeclared feature satisfies every contract check because no "
            f"contract check looks at it.",
        )

    if not declared_features:
        return report  # nothing else to bind

    emitted = [c for c in candidates_df.columns if c in set(declared_features)]
    report.emitted_features = emitted

    # 1. Ordered identity: no substitution, no reordering, no omission.
    if strict_order and emitted != declared_features:
        fail(
            "FEATURE_SURFACE_IDENTITY_MISMATCH", None,
            f"emitted ordered feature columns {emitted} != declared {declared_features}",
        )

    for name in declared_features:
        entry: Dict[str, Any] = {}

        # 2. Registry binding must resolve.
        fdef = registry.get(name)
        if fdef is None:
            fail("FEATURE_NOT_REGISTERED", name,
                 f"'{name}' is declared by the study but absent from the feature registry")
            report.per_feature[name] = {"registered": False}
            continue
        entry["registered"] = True
        entry["status"] = getattr(fdef, "status", None)
        entry["null_policy"] = getattr(fdef, "null_policy", "disallow")
        entry["declared_dtype"] = getattr(fdef, "dtype", "float64")

        # 3. The column has to be there at all.
        if name not in candidates_df.columns:
            fail("FEATURE_COLUMN_MISSING", name,
                 f"declared feature '{name}' has no column in the produced surface")
            report.per_feature[name] = entry
            continue

        series = candidates_df[name]
        n = len(series)
        n_null = int(series.isna().sum())
        entry["rows"] = n
        entry["null_count"] = n_null
        entry["null_fraction"] = round(n_null / n, 6) if n else 0.0
        entry["produced_dtype"] = str(series.dtype)

        if n == 0:
            report.per_feature[name] = entry
            continue

        # 4. An all-null column was never emitted -- refused under EVERY null policy.
        if n_null == n:
            fail(
                "FEATURE_NEVER_EMITTED", name,
                f"'{name}' is null in all {n} rows. null_policy="
                f"{entry['null_policy']!r} permits unavailable values, not a feature that "
                f"was never produced.",
            )
            report.per_feature[name] = entry
            continue

        # 5. Otherwise honour the declared null policy.
        if entry["null_policy"] == "disallow" and n_null > 0:
            fail("FEATURE_NULL_POLICY_VIOLATION", name,
                 f"'{name}' declares null_policy='disallow' but has {n_null}/{n} null rows")

        # 6. Datatype must be usable as declared.
        if not _dtype_compatible(series, entry["declared_dtype"]):
            fail("FEATURE_DTYPE_INCOMPATIBLE", name,
                 f"'{name}' produced dtype {series.dtype} is not compatible with declared "
                 f"{entry['declared_dtype']}")

        # 7. A constant column is not a validity failure, but it is worth recording:
        # it is how a stuck tracker looks once it stops being all-null.
        entry["distinct_non_null"] = int(series.nunique(dropna=True))

        report.per_feature[name] = entry

    return report


def assert_feature_surface(candidates_df, declared_features, registry=None) -> SurfaceReport:
    """Fail-closed wrapper: raises ``FeatureSurfaceError`` when validation does not pass."""
    report = validate_feature_surface(candidates_df, declared_features, registry)
    if not report.passed:
        detail = "; ".join(f"[{f['code']}] {f['message']}" for f in report.findings)
        raise FeatureSurfaceError(f"FEATURE_SURFACE_INVALID: {detail}")
    return report


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description="Validate a produced feature surface against a study contract")
    ap.add_argument("--study", required=True, help="Path to study directory")
    ap.add_argument("--candidates", required=True, help="Path to candidates.parquet")
    ap.add_argument("--json", help="Write the surface report to this path")
    args = ap.parse_args()

    import yaml
    study_dir = Path(args.study).resolve()
    cfg = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    declared = (cfg.get("features") or {}).get("feature_list") or []

    df = pd.read_parquet(args.candidates)
    report = validate_feature_surface(df, declared)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

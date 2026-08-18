"""Reproducible modelling wrappers (A0 §6, roadmap A3).

Thin wrappers around the project's existing libraries (scikit-learn, LightGBM) —
**not** a generic ML platform. The value here is provenance, not modelling: a fit
records ordered features, dataset identity, split policy, seed, library version,
hyperparameters, model checksum, prediction identity, and threshold-freeze identity,
so two results that claim to be comparable can be checked mechanically.

Guardrails carried from the contract:
  * a fit refuses to mix TRAIN and DEV rows in one arm;
  * a fit refuses outcome columns as features;
  * a threshold refuses to mix TRAIN and DEV rows, and MEASURES the population it
    was derived from rather than accepting the caller's word for it, because a
    threshold frozen on one population is not valid on another.

This module trains no real study models. Its tests use synthetic data only.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.analysis.errors import (
    InvalidAnalysisSpec, PartitionMixing, PartitionProvenanceMissing, SchemaMissing,
    SchemaSurplus,
)
from research.analysis.identity import OUTCOME_COLUMNS, canonical_sha256
from research.analysis.spec import AnalysisSpec, ModelArm

MODELING_VERSION = "1.0.0"

SUPPORTED_ESTIMATORS = ("logistic_regression", "gradient_boosting", "lightgbm")


def library_versions() -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {"python": platform.python_version()}
    for mod in ("numpy", "pandas", "sklearn", "lightgbm"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            out[mod] = None
    return out


@dataclass
class SplitPolicy:
    """How rows were assigned to fit vs evaluation. Recorded, never inferred."""

    kind: str  # "single_partition" | "explicit_index" | "none"
    fit_partitions: Tuple[str, ...] = ()
    eval_partitions: Tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "fit_partitions": list(self.fit_partitions),
            "eval_partitions": list(self.eval_partitions),
            "description": self.description,
        }


@dataclass
class FitProvenance:
    """Everything needed to decide whether two fits are the same experiment."""

    arm: str
    estimator: str
    ordered_features: List[str]
    n_features: int
    n_rows: int
    seed: int
    hyperparameters: Dict[str, Any]
    split_policy: Dict[str, Any]
    dataset_identity_sha256: Optional[str]
    analysis_spec_sha256: Optional[str]
    library_versions: Dict[str, Optional[str]]
    model_sha256: str
    # Content hashes of the frame actually fitted. `dataset_identity_sha256` is a
    # caller assertion; these are measured (M2).
    x_content_sha256: Optional[str] = None
    y_content_sha256: Optional[str] = None
    partition_provenance: str = ""
    prediction_sha256: Optional[str] = None
    threshold_freeze: Optional[Dict[str, Any]] = None
    modeling_version: str = MODELING_VERSION
    fitted_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def fit_identity_sha256(self) -> str:
        """Stable across re-runs of the same experiment; changes when anything material does.

        Binds the ACTUAL training data, not only asserted identities. Previously two
        fits on entirely different populations (n=200 vs n=80, different
        distributions) produced the same hash whenever the caller passed the same
        `dataset_identity_sha256` string, and a library upgrade left the identity
        untouched although it was recorded in provenance (M2).
        """
        payload = {
            "arm": self.arm,
            "estimator": self.estimator,
            "ordered_features": self.ordered_features,
            "n_rows": self.n_rows,
            "seed": self.seed,
            "hyperparameters": self.hyperparameters,
            "split_policy": self.split_policy,
            "partition_provenance": self.partition_provenance,
            "dataset_identity_sha256": self.dataset_identity_sha256,
            "analysis_spec_sha256": self.analysis_spec_sha256,
            "x_content_sha256": self.x_content_sha256,
            "y_content_sha256": self.y_content_sha256,
            "library_versions": self.library_versions,
        }
        return canonical_sha256(payload)


@dataclass
class FittedModel:
    estimator: Any
    provenance: FitProvenance

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        cols = self.provenance.ordered_features
        missing = [c for c in cols if c not in X.columns]
        if missing:
            raise SchemaMissing(
                f"prediction frame is missing fitted features: {missing}", missing=missing
            )
        # Reindex to the FITTED order: same members in a different order is a
        # different model input, and silently accepting it is a real defect class.
        Xo = X[cols]
        proba = self.estimator.predict_proba(Xo)
        return np.asarray(proba)[:, 1]


def _model_checksum(estimator: Any) -> str:
    try:
        blob = pickle.dumps(estimator)
    except Exception:  # noqa: BLE001 - not all estimators pickle; fall back to repr
        blob = repr(estimator).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def prediction_identity(scores: Sequence[float]) -> str:
    arr = np.asarray(list(scores), dtype="float64")
    rounded = np.round(arr, 12)
    return hashlib.sha256(rounded.tobytes()).hexdigest()


def frame_content_identity(frame: pd.DataFrame) -> str:
    """Column-ordered content hash of a feature frame.

    Per column rather than whole-frame so the hash is insensitive to dtype backend
    and block layout but sensitive to values, column names and column ORDER.
    """
    per_column = []
    for col in frame.columns:
        series = frame[col]
        try:
            digest = prediction_identity(series.to_numpy(dtype="float64", na_value=np.nan))
        except (TypeError, ValueError):
            # Non-numeric column: hash its string form rather than refuse.
            digest = hashlib.sha256(
                "\x1f".join(map(repr, series.tolist())).encode("utf-8")
            ).hexdigest()
        per_column.append([str(col), digest])
    return canonical_sha256(per_column)


def series_content_identity(series: Sequence[Any]) -> str:
    s = series if isinstance(series, pd.Series) else pd.Series(list(series))
    try:
        return prediction_identity(s.to_numpy(dtype="float64", na_value=np.nan))
    except (TypeError, ValueError):
        return hashlib.sha256("\x1f".join(map(repr, s.tolist())).encode("utf-8")).hexdigest()


def _build_estimator(estimator: str, seed: int, hyperparameters: Dict[str, Any]):
    if estimator not in SUPPORTED_ESTIMATORS:
        raise InvalidAnalysisSpec(
            f"unsupported estimator {estimator!r}; supported: {list(SUPPORTED_ESTIMATORS)}"
        )
    params = dict(hyperparameters or {})
    if estimator == "logistic_regression":
        from sklearn.linear_model import LogisticRegression

        params.setdefault("max_iter", 1000)
        return LogisticRegression(random_state=seed, **params)
    if estimator == "gradient_boosting":
        from sklearn.ensemble import GradientBoostingClassifier

        return GradientBoostingClassifier(random_state=seed, **params)
    from lightgbm import LGBMClassifier  # noqa: WPS433 - optional dependency

    params.setdefault("verbose", -1)
    return LGBMClassifier(random_state=seed, **params)


def fit_model(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    arm: str,
    estimator: str = "logistic_regression",
    seed: int = 0,
    hyperparameters: Optional[Dict[str, Any]] = None,
    split_policy: Optional[SplitPolicy] = None,
    dataset_identity_sha256: Optional[str] = None,
    analysis_spec_sha256: Optional[str] = None,
    meta: Optional[pd.DataFrame] = None,
) -> FittedModel:
    """Fits one arm and records complete provenance.

    `meta` carrying a `_partition` column is REQUIRED unless the caller passes an
    explicit `split_policy` opt-out: absence of partition provenance is not evidence
    of a single partition, and the TRAIN/DEV guard cannot run without it (M3).
    """
    if X.empty:
        raise SchemaMissing("cannot fit on an empty feature frame", arm=arm)
    if len(X) != len(y):
        raise SchemaMissing(f"X has {len(X)} rows but y has {len(y)}", arm=arm)

    leaking = [c for c in X.columns if c in OUTCOME_COLUMNS]
    if leaking:
        raise SchemaSurplus(
            f"outcome columns present in the feature frame: {leaking}", leaking=leaking
        )

    has_partition = meta is not None and "_partition" in getattr(meta, "columns", [])
    if has_partition:
        if len(meta) != len(X):
            raise SchemaMissing(
                f"meta has {len(meta)} rows but X has {len(X)}; the partition column does not "
                f"describe these rows",
                arm=arm,
            )
        present = set(meta["_partition"].dropna().unique().tolist())
        if {"train", "dev"} <= present:
            raise PartitionMixing(
                f"fit spans partitions {sorted(present)}; TRAIN and DEV may not appear in one arm",
                partitions=sorted(present),
            )
        partition_provenance = "meta_partition"
        if split_policy is None:
            split_policy = SplitPolicy(
                kind="single_partition",
                fit_partitions=tuple(sorted(present)),
                description="derived from the metadata partition column",
            )
    else:
        # The old default silently synthesised `split_policy={'kind':'none', …,
        # 'description':'no partition metadata supplied'}`, i.e. the provenance
        # asserted an innocent explanation for its own blind spot. Refuse instead.
        if split_policy is None:
            raise PartitionProvenanceMissing(
                "refusing to fit without partition provenance: pass meta with a '_partition' "
                "column (as returned by get_features_targets_metadata), or pass an explicit "
                "SplitPolicy opt-out that is recorded on the artifact. Without it the "
                "TRAIN/DEV guard cannot run and a contaminated fit is indistinguishable from "
                "a clean one.",
                arm=arm,
            )
        partition_provenance = "explicit_opt_out"

    ordered = list(X.columns)
    est = _build_estimator(estimator, seed, hyperparameters or {})
    est.fit(X[ordered], y)

    prov = FitProvenance(
        arm=arm,
        estimator=estimator,
        ordered_features=ordered,
        n_features=len(ordered),
        n_rows=int(len(X)),
        seed=seed,
        hyperparameters=dict(hyperparameters or {}),
        split_policy=split_policy.to_dict(),
        dataset_identity_sha256=dataset_identity_sha256,
        analysis_spec_sha256=analysis_spec_sha256,
        library_versions=library_versions(),
        model_sha256=_model_checksum(est),
        x_content_sha256=frame_content_identity(X[ordered]),
        y_content_sha256=series_content_identity(y),
        partition_provenance=partition_provenance,
    )
    return FittedModel(estimator=est, provenance=prov)


def score_and_record(model: FittedModel, X: pd.DataFrame) -> Tuple[np.ndarray, str]:
    scores = model.predict_proba(X)
    ident = prediction_identity(scores)
    model.provenance.prediction_sha256 = ident
    return scores, ident


# ---------------------------------------------------------------------------
# Threshold freeze
# ---------------------------------------------------------------------------


def _partition_labels(meta: pd.DataFrame) -> List[str]:
    """The distinct, non-null partition labels carried by these rows."""
    return sorted({str(p) for p in pd.Series(meta["_partition"]).dropna().unique()})


def derive_population_label(meta: pd.DataFrame) -> Optional[str]:
    """The population label implied by the scored rows' own partition column."""
    if meta is None or "_partition" not in getattr(meta, "columns", []):
        return None
    parts = _partition_labels(meta)
    return "+".join(parts) if parts else None


def freeze_threshold(
    scores: Sequence[float],
    y_true: Sequence[float],
    *,
    meta: Optional[pd.DataFrame] = None,
    method: str = "quantile",
    value: float = 0.9,
    population: Optional[str] = None,
    dataset_identity_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Derives a threshold and MEASURES the population it came from.

    A threshold is a fitted parameter, so it follows the same partition discipline
    as a model fit: `meta` carrying a `_partition` column is required, and the
    population is derived from it. `meta` keeps a `None` default only so its absence
    fails with the contract's own code (PARTITION_PROVENANCE_MISSING) instead of a
    bare TypeError — it is not optional.

    Two residual holes are closed here (M4):

    * `freeze_threshold(dev_scores, y, population="train")` with no `meta` used to
      succeed and record `derivation_population_source="caller_declared"`, so DEV
      rows could be labelled TRAIN simply by omitting provenance. There is no
      caller-declared route any more.
    * Mixed rows used to be recorded as `derivation_population="dev+train"`, which
      names the contamination rather than refusing it. Mixing is now PARTITION_MIXING,
      exactly as it is for `fit_model`.

    `population` survives only as an assertion the caller may make; it is
    cross-checked against the derived label and never authoritative. Disagreement is
    a hard error.

    Deriving `"dev"` is mechanically permitted — this function reports what the rows
    are, it does not own OOS/DEV policy. Whether such a freeze is authorised is
    decided by the analysis spec and the seal policy, not here.
    """
    n_scores = len(list(scores))

    if meta is None:
        raise PartitionProvenanceMissing(
            "refusing to freeze a threshold without partition provenance: pass the `meta` frame "
            "from get_features_targets_metadata so the derivation population is measured from "
            "'_partition'. A threshold is a fitted parameter; a caller-declared population is an "
            "assertion, and a DEV-derived threshold labelled 'train' is byte-indistinguishable "
            "from a real TRAIN freeze."
        )
    if "_partition" not in getattr(meta, "columns", []):
        raise PartitionProvenanceMissing(
            "meta carries no '_partition' column, so the derivation population cannot be "
            "measured. Absence of provenance is not evidence of a single clean partition."
        )
    if len(meta) != n_scores:
        raise SchemaMissing(
            f"meta has {len(meta)} rows but {n_scores} scores were supplied; the partition "
            f"column does not describe these rows"
        )

    arr = pd.Series(list(scores), dtype="float64").dropna()
    if arr.empty:
        raise SchemaMissing("cannot freeze a threshold on an empty score set")

    parts = _partition_labels(meta)
    if not parts:
        raise PartitionProvenanceMissing(
            "meta's '_partition' column is entirely null for these rows, so the derivation "
            "population cannot be measured."
        )
    if len(parts) > 1:
        raise PartitionMixing(
            f"threshold would be derived from rows spanning partitions {parts}; a threshold is a "
            f"fitted parameter and may no more pool partitions than a model fit can. Recording "
            f"the population as {'+'.join(parts)!r} names the contamination instead of refusing it.",
            partitions=parts,
        )

    derived = parts[0]
    if population is not None:
        declared = str(population).strip()
        if not declared or declared.casefold() != derived.casefold():
            raise InvalidAnalysisSpec(
                f"declared threshold population {population!r} contradicts the scored rows: "
                f"their _partition is {derived!r}. A threshold frozen on one population is not "
                f"valid on another, and the declaration is a cross-check, never the source.",
                declared=population, derived=derived,
            )
    population = derived
    population_source = "derived_from_meta_partition"

    if method == "quantile":
        thr = float(np.quantile(arr.to_numpy(), value))
    elif method == "fixed":
        thr = float(value)
    else:
        raise InvalidAnalysisSpec(f"unsupported threshold method {method!r}; use quantile|fixed")

    yt = pd.Series(list(y_true), dtype="float64")
    selected = pd.Series(list(scores), dtype="float64") >= thr
    n_sel = int(selected.sum())
    ppv = float(yt[selected.values].mean()) if n_sel and not yt.empty else None

    record = {
        "method": method,
        "parameter": value,
        "threshold": thr,
        "derivation_population": population,
        "derivation_population_source": population_source,
        "derivation_n": int(arr.size),
        "selected_n": n_sel,
        "selected_rate": float(n_sel / arr.size) if arr.size else None,
        "ppv_on_derivation_population": ppv,
        "dataset_identity_sha256": dataset_identity_sha256,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
    }
    record["threshold_freeze_sha256"] = canonical_sha256(
        {k: v for k, v in record.items() if k != "frozen_utc"}
    )
    return record


# ---------------------------------------------------------------------------
# Declared A/B/C comparison
# ---------------------------------------------------------------------------


def resolve_arms(spec: AnalysisSpec, available_features: Sequence[str]) -> List[ModelArm]:
    """Validates declared arms against what the collection actually provides."""
    if not spec.model_arms:
        raise InvalidAnalysisSpec(
            "no model_arms declared; an A/B/C comparison must be predeclared in the analysis spec"
        )
    have = set(available_features)
    for arm in spec.model_arms:
        missing = [f for f in arm.features if f not in have]
        if missing:
            raise SchemaMissing(
                f"arm {arm.name!r} requests features absent from the collection: {missing}",
                arm=arm.name, missing=missing,
            )
    return list(spec.model_arms)


def fit_arms(
    X: pd.DataFrame,
    y: pd.Series,
    spec: AnalysisSpec,
    *,
    estimator: str = "logistic_regression",
    hyperparameters: Optional[Dict[str, Any]] = None,
    dataset_identity_sha256: Optional[str] = None,
    meta: Optional[pd.DataFrame] = None,
) -> Dict[str, FittedModel]:
    """Fits every declared arm on the same rows, with the same seed and split policy."""
    arms = resolve_arms(spec, list(X.columns))
    out: Dict[str, FittedModel] = {}
    for arm in arms:
        out[arm.name] = fit_model(
            X[list(arm.features)], y,
            arm=arm.name,
            estimator=estimator,
            seed=spec.seed,
            hyperparameters=hyperparameters,
            dataset_identity_sha256=dataset_identity_sha256,
            analysis_spec_sha256=spec.analysis_spec_sha256,
            meta=meta,
        )
    return out


def write_model_manifest(models: Dict[str, FittedModel], out_path: Path) -> Dict[str, Any]:
    payload = {
        "modeling_version": MODELING_VERSION,
        "arms": {
            name: {**m.provenance.to_dict(), "fit_identity_sha256": m.provenance.fit_identity_sha256}
            for name, m in models.items()
        },
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8",
                        newline="\n")
    return payload

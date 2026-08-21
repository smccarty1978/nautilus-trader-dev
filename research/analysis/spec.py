"""Analysis specification schema and identity (A0 §6).

A spec is declarative, validated, and hashed. `analysis_spec_sha256` changes whenever
the seed, partitions, feature set, or target change, so two results that claim to be
comparable can be checked mechanically rather than by reading prose.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from research.analysis.errors import InvalidAnalysisSpec
from research.analysis.identity import canonical_sha256

SPEC_SCHEMA_VERSION = 1

VALID_PARTITIONS = ("train", "dev", "diagnostic")
VALID_MISSING_POLICIES = ("report_only",)
VALID_FEATURE_SETS = ("declared",)  # `subset:<name>` handled separately

_TOP_LEVEL_KEYS = {
    "analysis_id", "schema_version", "collection", "target", "partitions",
    "features", "missing_values", "seed", "slices", "model_arms", "notes",
}
_COLLECTION_KEYS = {
    "run_id", "study_id", "collection_identity_sha256", "allow_unsealed_collection",
    "allow_stale_compiled_study", "expected_join_key",
}
_TARGET_KEYS = {"column", "horizon_seconds"}
_FEATURE_KEYS = {"feature_list_sha256", "set", "subset"}


@dataclass(frozen=True)
class ModelArm:
    """One declared arm of an A/B/C feature-set comparison."""

    name: str
    features: List[str]
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "features": list(self.features), "description": self.description}


@dataclass(frozen=True)
class AnalysisSpec:
    analysis_id: str
    run_id: str
    study_id: Optional[str] = None
    collection_identity_sha256: Optional[str] = None
    allow_unsealed_collection: bool = False
    allow_stale_compiled_study: bool = False
    # The join key the analyst asserts this collection has. Optional, and the
    # strongest form of the declaration: pinning it here removes any dependence on
    # what the frames happen to contain.
    expected_join_key: tuple = ()
    target_column: str = "target_flip_within_horizon"
    target_horizon_seconds: Optional[int] = None
    partitions: tuple = ("train",)
    feature_list_sha256: Optional[str] = None
    feature_set: str = "declared"
    feature_subset: tuple = ()
    missing_values: str = "report_only"
    seed: int = 0
    slices: tuple = ()
    model_arms: tuple = ()
    schema_version: int = SPEC_SCHEMA_VERSION
    notes: str = ""

    # -- identity ---------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["partitions"] = list(self.partitions)
        d["expected_join_key"] = list(self.expected_join_key)
        d["feature_subset"] = list(self.feature_subset)
        d["slices"] = list(self.slices)
        d["model_arms"] = [a.to_dict() if isinstance(a, ModelArm) else dict(a) for a in self.model_arms]
        return d

    @property
    def analysis_spec_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def arm(self, name: str) -> ModelArm:
        for a in self.model_arms:
            if a.name == name:
                return a
        raise InvalidAnalysisSpec(f"no declared model arm named {name!r}",
                                  declared=[a.name for a in self.model_arms])


def _require_mapping(value: Any, where: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidAnalysisSpec(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(keys, allowed, where: str) -> None:
    unknown = sorted(set(keys) - set(allowed))
    if unknown:
        raise InvalidAnalysisSpec(
            f"unknown key(s) {unknown} in {where}; allowed: {sorted(allowed)}",
            unknown=unknown, where=where,
        )


def parse_analysis_spec(payload: Dict[str, Any]) -> AnalysisSpec:
    """Validates and normalises a spec mapping. Unknown keys are rejected.

    Rejecting unknown keys matters: a misspelled `partition:` would otherwise
    silently leave the default `["train"]` in place while the author believed they
    had selected something else.
    """
    if not isinstance(payload, dict):
        raise InvalidAnalysisSpec(f"spec must be a mapping, got {type(payload).__name__}")
    _reject_unknown(payload, _TOP_LEVEL_KEYS, "analysis spec")

    analysis_id = payload.get("analysis_id")
    if not analysis_id or not isinstance(analysis_id, str):
        raise InvalidAnalysisSpec("analysis_id is required and must be a non-empty string")

    schema_version = payload.get("schema_version", SPEC_SCHEMA_VERSION)
    if schema_version != SPEC_SCHEMA_VERSION:
        raise InvalidAnalysisSpec(
            f"unsupported schema_version {schema_version!r}; this harness implements "
            f"{SPEC_SCHEMA_VERSION}"
        )

    collection = _require_mapping(payload.get("collection"), "collection")
    _reject_unknown(collection, _COLLECTION_KEYS, "collection")
    run_id = collection.get("run_id")
    if not run_id or not isinstance(run_id, str):
        raise InvalidAnalysisSpec(
            "collection.run_id is required and must name one exact run; there is no 'latest'"
        )
    if run_id.strip().lower() in {"latest", "last", "newest", "*"}:
        raise InvalidAnalysisSpec(
            f"collection.run_id={run_id!r} is not an explicit run identity. An analysis must "
            f"bind to exactly one immutable run."
        )

    expected_join_key = collection.get("expected_join_key") or ()
    if isinstance(expected_join_key, str):
        raise InvalidAnalysisSpec(
            "collection.expected_join_key must be an ordered list of column names"
        )
    if not isinstance(expected_join_key, (list, tuple)):
        raise InvalidAnalysisSpec(
            f"collection.expected_join_key must be a list, got {type(expected_join_key).__name__}"
        )
    expected_join_key = [str(k) for k in expected_join_key]
    if len(set(expected_join_key)) != len(expected_join_key):
        raise InvalidAnalysisSpec(
            "collection.expected_join_key lists a duplicate column",
            expected_join_key=expected_join_key,
        )

    target = _require_mapping(payload.get("target"), "target")
    _reject_unknown(target, _TARGET_KEYS, "target")

    partitions = payload.get("partitions", ["train"])
    if isinstance(partitions, str):
        partitions = [partitions]
    if not isinstance(partitions, (list, tuple)) or not partitions:
        raise InvalidAnalysisSpec("partitions must be a non-empty list")
    bad = sorted(set(partitions) - set(VALID_PARTITIONS))
    if bad:
        raise InvalidAnalysisSpec(
            f"unknown partition(s) {bad}; valid: {list(VALID_PARTITIONS)}", invalid=bad
        )

    features = _require_mapping(payload.get("features"), "features")
    _reject_unknown(features, _FEATURE_KEYS, "features")
    feature_set = features.get("set", "declared")
    subset = tuple(features.get("subset") or ())
    if feature_set != "declared":
        if not feature_set.startswith("subset:"):
            raise InvalidAnalysisSpec(
                f"features.set must be 'declared' or 'subset:<name>', got {feature_set!r}"
            )
        if not subset:
            raise InvalidAnalysisSpec(
                f"features.set={feature_set!r} requires a non-empty features.subset list"
            )

    missing = payload.get("missing_values", "report_only")
    if missing not in VALID_MISSING_POLICIES:
        raise InvalidAnalysisSpec(
            f"missing_values={missing!r} is not supported. The loader never imputes; "
            f"imputation is a modelling decision. Valid: {list(VALID_MISSING_POLICIES)}"
        )

    seed = payload.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise InvalidAnalysisSpec(f"seed must be an int, got {type(seed).__name__}")

    arms: List[ModelArm] = []
    for raw in payload.get("model_arms") or []:
        raw = _require_mapping(raw, "model_arms[]")
        name = raw.get("name")
        feats = raw.get("features")
        if not name or not isinstance(feats, (list, tuple)) or not feats:
            raise InvalidAnalysisSpec(
                "each model arm needs a 'name' and a non-empty ordered 'features' list",
                arm=raw,
            )
        if len(set(feats)) != len(feats):
            raise InvalidAnalysisSpec(f"model arm {name!r} lists a duplicate feature", arm=name)
        arms.append(ModelArm(name=name, features=list(feats), description=raw.get("description", "")))
    if len({a.name for a in arms}) != len(arms):
        raise InvalidAnalysisSpec("model arm names must be unique")

    return AnalysisSpec(
        analysis_id=analysis_id,
        run_id=run_id,
        study_id=collection.get("study_id"),
        collection_identity_sha256=collection.get("collection_identity_sha256"),
        allow_unsealed_collection=bool(collection.get("allow_unsealed_collection", False)),
        allow_stale_compiled_study=bool(collection.get("allow_stale_compiled_study", False)),
        expected_join_key=tuple(expected_join_key),
        target_column=target.get("column", "target_flip_within_horizon"),
        target_horizon_seconds=target.get("horizon_seconds"),
        partitions=tuple(partitions),
        feature_list_sha256=features.get("feature_list_sha256"),
        feature_set=feature_set,
        feature_subset=subset,
        missing_values=missing,
        seed=seed,
        slices=tuple(payload.get("slices") or ()),
        model_arms=tuple(arms),
        schema_version=schema_version,
        notes=payload.get("notes", ""),
    )


def load_analysis_spec(path: Path) -> AnalysisSpec:
    import yaml

    path = Path(path)
    if not path.is_file():
        raise InvalidAnalysisSpec(f"analysis spec not found: {path}", path=str(path))
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise InvalidAnalysisSpec(f"analysis spec {path} is not valid YAML: {err}") from err
    return parse_analysis_spec(payload)

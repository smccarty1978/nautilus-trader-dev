"""Strict Machine-Readable StudySpec Schema.
=========================================
Authoritative schema for study.yaml files in the NautilusTrader framework.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StudyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique study directory and experiment identifier")
    type: Literal["flip_prediction", "bespoke"] = Field(
        ..., description="Supported canonical study type or bespoke escape hatch"
    )
    risk_tier: Literal[1, 2, 3, "Tier 1", "Tier 2", "Tier 3"] = Field(
        2, description="Governance risk tier (1=diagnostic, 2=study, 3=model freeze)"
    )
    description: str = Field(..., description="High-level description of research intent")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("Study ID cannot be empty")
        if any(c in v_clean for c in r'/\:*?"<>| '):
            raise ValueError(f"Invalid study ID '{v_clean}': must not contain spaces or path separators")
        return v_clean


class InstrumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="Underlying symbol, e.g. NQ, ES, YM")
    venue: str = Field("XCME", description="Execution/Exchange venue, e.g. XCME")


class PopulationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field("regime_state", description="Population type, e.g. regime_state, breakout")
    prevailing_regime: Optional[str] = Field(
        None, description="Prevailing regime direction, e.g. bearish, bullish"
    )
    session: str = Field("RTH", description="Session filter, e.g. RTH, ETH, ALL")
    qualification: Optional[Dict[str, Any]] = Field(
        default=None, description="Qualification rules, e.g. age_gate_seconds, established"
    )


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field("flip", description="Target type, e.g. flip, excursion, return")
    event: Optional[str] = Field(None, description="Target event name, e.g. regime_flip")
    direction: Optional[str] = Field(
        None, description="Target direction, e.g. bullish (for bearish prevailing), bearish"
    )
    horizon_seconds: Optional[int] = Field(
        None, description="Prediction horizon in seconds, e.g. 300"
    )
    confirmation: Optional[Dict[str, Any]] = Field(
        default=None, description="Confirmation parameters, e.g. bars_required, ticks_required"
    )


class FeatureSelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["train_only", "pre_frozen", "none"] = Field(
        "train_only", description="Feature selection regime mode"
    )
    source: str = Field(
        "verified_registry_numeric_universe",
        description="Candidate feature pool source (e.g. verified_registry_numeric_universe)",
    )
    years: Optional[List[int]] = Field(
        default=None, description="Authorized selection years (must be subset of train years)"
    )
    feature_count: Optional[int] = Field(
        25, description="Target feature count per directional model"
    )
    direction_specific: bool = Field(
        True, description="Whether selection is performed separately for SHORT and LONG models"
    )
    ranking_method: Optional[str] = Field(
        "frozen_train_only_temporal_rank", description="Ranking methodology"
    )


class FeaturesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_manifest: Optional[str] = Field(
        None, description="Path or identifier of feature manifest"
    )
    source: Optional[str] = Field(
        None, description="Feature source universe, e.g. verified_registry_numeric_universe"
    )
    source_key: Optional[str] = Field(
        None, description="Key identifier for feature set, e.g. F3_top25_gbt_v1"
    )
    selection: Optional[FeatureSelectionSpec] = Field(
        default=None, description="Feature selection specification"
    )
    forbidden_lineage: Optional[List[str]] = Field(
        default=None, description="Forbidden prior feature keys or lineage sources"
    )
    feature_list: Optional[List[str]] = Field(
        default=None, description="Exact ordered feature names"
    )
    feature_list_sha256: Optional[str] = Field(
        None, description="SHA-256 hash of ordered feature list"
    )
    directional_mapping: Optional[str] = Field(
        None, description="Directional polarity mapping policy"
    )
    timing_contract: Optional[str] = Field(
        "verified", description="Feature timing audit status, e.g. verified"
    )
    metadata_columns: Optional[List[str]] = Field(
        default=None, description="Declared non-feature metadata columns for output contract validation"
    )


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Optional[str] = Field("scoring", description="Model mode: scoring, training, evaluation")
    family: Optional[str] = Field(
        None, description="Model family, e.g. HistGradientBoostingClassifier, LogisticRegression"
    )
    arms: Optional[List[str]] = Field(
        default=None, description="Model arms, e.g. [BASELINE_A, STRUCTURAL_B, ROLLING_PRODUCTIVITY_C]"
    )
    artifact_path: Optional[str] = Field(
        None, description="Path to trained model artifact (.joblib, .onnx)"
    )
    artifact_sha256: Optional[str] = Field(
        None, description="Pinned SHA-256 of model artifact"
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None, description="Model hyperparameters"
    )


class WarmupSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_before_partition: int = Field(5, description="Warmup lookback in days prior to partition start")
    allowed: bool = Field(True, description="Whether warmup data loading is authorized")
    candidate_emission: bool = Field(False, description="Whether candidate emission is permitted during warmup")
    target_generation: bool = Field(False, description="Whether target generation is permitted during warmup")
    permitted_partition_relationship: Literal["pre_train_only", "pre_partition", "explicit_whitelist"] = Field(
        "pre_train_only", description="Permitted chronological relationship for warmup"
    )


class ChronologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train: Optional[List[int]] = Field(
        default=None, description="Authorized training years, e.g. [2021, 2022, 2023, 2024]"
    )
    dev: Optional[List[int]] = Field(
        default=None, description="Authorized validation/development years, e.g. [2025]"
    )
    diagnostic: Optional[List[int]] = Field(
        default=None, description="Authorized diagnostic evaluation years"
    )
    prohibited: Optional[List[int]] = Field(
        default=None, description="Prohibited OOS/test years, e.g. [2026]"
    )
    warmup: Optional[WarmupSpec] = Field(
        default=None, description="Explicit warmup authorization specification"
    )

    @model_validator(mode="after")
    def check_chronology_disjoint(self) -> ChronologySpec:
        train_set = set(self.train or [])
        dev_set = set(self.dev or [])
        prohib_set = set(self.prohibited or [])

        overlap_train_dev = train_set & dev_set
        if overlap_train_dev:
            raise ValueError(f"Chronology error: train and dev overlap on years {sorted(overlap_train_dev)}")

        overlap_prohib = (train_set | dev_set) & prohib_set
        if overlap_prohib:
            raise ValueError(
                f"Chronology error: prohibited years {sorted(overlap_prohib)} appear in train/dev partition"
            )
        return self


class StratificationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: Optional[str] = Field(None, description="Stratification feature column")
    buckets: Optional[List[List[Any]]] = Field(
        default=None, description="Bucket intervals [lower, upper]"
    )
    extrapolation_bucket: Optional[str] = Field(
        None, description="Descriptive extrapolation bucket label, e.g. '>=1800s'"
    )


class BaselineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study: Optional[str] = Field(None, description="Reference baseline study name")
    manifest_sha256: Optional[str] = Field(None, description="Pinned SHA256 of baseline manifest")
    results_sha256: Optional[str] = Field(None, description="Pinned SHA256 of baseline results")


class LineageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_study: Optional[str] = Field(None, description="Parent study identifier")
    parent_manifest_sha256: Optional[str] = Field(None, description="Pinned parent manifest SHA256")
    clean_lineage_start: Optional[str] = Field(
        None, description="Timestamp marking the clean lineage reset boundary"
    )
    invalidated_prior_runs: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Record of quarantined historical runs"
    )
    intended_changes: Optional[List[str]] = Field(
        default=None, description="List of dimensions intended to change"
    )
    frozen: Optional[List[str]] = Field(
        default=None, description="List of dimensions strictly frozen against parent"
    )


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime: Literal["nautilustrader"] = Field(
        "nautilustrader",
        description="Execution runtime environment. MUST strictly be 'nautilustrader'",
    )
    strategy_class: Optional[str] = Field(
        None, description="Fully qualified Python class of NautilusTrader strategy"
    )
    data_requirements: Optional[Dict[str, Any]] = Field(
        default=None, description="Data timeframe and catalog requirements"
    )
    checkpoint: Optional[str] = Field(None, description="Checkpoint storage identifier")
    progress_seconds: Optional[int] = Field(60, description="Bounded runner progress interval")
    bounded: Optional[bool] = Field(True, description="Enforce bounded study process control")
    observation_policy: Optional[Dict[str, Any]] = Field(
        default=None, description="Observation timing policy (exact_grid, parent_bar_close, event_driven)"
    )


class AcceptanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: Optional[Dict[str, Any]] = Field(
        default=None, description="Structured quantitative acceptance gates"
    )


class BespokeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(None, description="Justification why canonical study types cannot fit")
    unsupported_contract_element: Optional[str] = Field(
        None, description="Specific element unsupported by canonical types"
    )
    canonical_type_considered: Optional[str] = Field(
        None, description="Canonical type evaluated prior to choosing bespoke"
    )
    reusable_extension_considered: Optional[str] = Field(
        None, description="Assessment of whether a reusable extension was feasible"
    )
    custom_scope: Optional[List[str]] = Field(
        default=None, description="List of bespoke custom implementation files"
    )


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "train_evaluate",
        "artifact_reconstruction",
        "runtime_population_parity",
        "score_parity",
        "execution_economics",
        "bespoke_operation",
    ] = Field("train_evaluate", description="Specific research operation type")
    target_metric: Optional[str] = Field(None, description="Primary quantitative evaluation metric")
    reconciliation_target: Optional[str] = Field(None, description="Target for parity/reconciliation studies")


class StudySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study: StudyMetadata
    operation: OperationSpec = Field(default_factory=OperationSpec)
    instrument: InstrumentSpec
    population: PopulationSpec
    target: TargetSpec
    features: Optional[FeaturesSpec] = Field(default_factory=FeaturesSpec)
    model: Optional[ModelSpec] = Field(default_factory=ModelSpec)
    chronology: Optional[ChronologySpec] = Field(default_factory=ChronologySpec)
    stratification: Optional[StratificationSpec] = Field(default_factory=StratificationSpec)
    baseline: Optional[BaselineSpec] = Field(default_factory=BaselineSpec)
    lineage: Optional[LineageSpec] = Field(default_factory=LineageSpec)
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    acceptance: Optional[AcceptanceSpec] = Field(default_factory=AcceptanceSpec)
    bespoke: Optional[BespokeSpec] = Field(default_factory=BespokeSpec)

    @model_validator(mode="after")
    def validate_study_type_and_bespoke(self) -> StudySpec:
        # Enforce Bespoke justification rules
        if self.study.type == "bespoke":
            if not self.bespoke or not self.bespoke.reason or not self.bespoke.reason.strip():
                raise ValueError(
                    "BESPOKE_JUSTIFICATION_MISSING: study.type='bespoke' requires a non-empty 'bespoke.reason'"
                )
            if not self.bespoke.unsupported_contract_element or not self.bespoke.unsupported_contract_element.strip():
                raise ValueError(
                    "BESPOKE_JUSTIFICATION_INCOMPLETE: 'bespoke.unsupported_contract_element' is required"
                )
        return self

    def compute_sha256(self) -> str:
        """Computes deterministic canonical SHA-256 hash of the StudySpec."""
        data_dict = self.model_dump(exclude_none=False)
        canonical_json = json.dumps(data_dict, sort_keys=True, indent=None)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

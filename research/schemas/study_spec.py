"""Strict Machine-Readable StudySpec Schema.
=========================================
Authoritative schema for study.yaml files in the NautilusTrader framework.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, Any, ClassVar, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Shared causal ordering for the three named decision-path timestamps a study may
# reference (`TargetSpec.decision_reference`, `DerivedCausalInputSpec.availability_reference`).
# Mirrors the ordering already implicit in `research_workflow.forward_outcomes.contracts`
# (`ProposedEntry` requires `entry_ts >= decision_ts`; a `ConfirmationSpec` is documented as
# strictly after entry). Defined here, not imported from `research_workflow`, because
# `research/schemas` is lower in the layering than `research_workflow` -- research_workflow
# imports this module, never the reverse.
TIMESTAMP_CAUSAL_ORDER: Dict[str, int] = {
    "decision_ts": 0,
    "entry_ts": 1,
    "confirmation_ts": 2,
}


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


class EpisodeArmConditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["directional_adverse_excursion"] = "directional_adverse_excursion"
    threshold_atr: float = Field(..., gt=0)
    price_source: Literal["completed_1s_intrabar"]


class EpisodeStateRequirementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["direction_relation"] = "direction_relation"
    source: str
    bar_state: Literal["completed"]
    availability_timestamp: Literal["completed_source_bar_ts_init"]
    relation: Literal["opposite_prevailing", "aligned_prevailing"]
    active_at_arm_counts: bool = True


class EpisodeEmitConditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["direction_transition"] = "direction_transition"
    source: str
    bar_state: Literal["completed"]
    availability_timestamp: Literal["completed_source_bar_ts_init"]
    from_relation: Literal["opposite_prevailing", "aligned_prevailing"]
    to_relation: Literal["opposite_prevailing", "aligned_prevailing"]
    strictly_after_arm: bool = True


class EpisodeLifecycleSpec(BaseModel):
    """Bounded declarative arm/intermediate/emit/reset population protocol."""

    model_config = ConfigDict(extra="forbid")

    arm_condition: EpisodeArmConditionSpec
    required_event: EpisodeStateRequirementSpec
    emit_condition: EpisodeEmitConditionSpec
    rearm_on: List[Literal["new_favorable_extreme"]]
    terminate_on: List[Literal["prevailing_regime_flip"]]
    max_candidates_per_episode: int = Field(1, ge=1)

    @model_validator(mode="after")
    def validate_sources_and_ordering(self) -> EpisodeLifecycleSpec:
        if self.required_event.source != self.emit_condition.source:
            raise ValueError("EPISODE_STATE_SOURCE_MISMATCH")
        if not self.emit_condition.strictly_after_arm:
            raise ValueError("EPISODE_RETROACTIVE_EMISSION_FORBIDDEN")
        return self


class PopulationQualificationSpec(BaseModel):
    """Typed, closed qualification schema for the existing population primitives (RT-06).

    ``qualification`` used to be ``Dict[str, Any]`` -- an unknown authored key compiled,
    sealed, and was silently ignored (``clean_tradable_reversal`` alone carried nine keys,
    only one of which any code reads). Every field a real study authors is now declared
    here, in one of three groups, and ``extra="forbid"`` rejects anything else at compile
    time. Per-field ``exclude_if`` keeps ``model_dump`` byte-identical to the old dict so
    this does not stale an existing study's ``spec_sha256``.

    Group A -- consumed by the ESTABLISHED-FILTER population runtime
      (``research_workflow.generic_collector``: ``_evaluate_checkpoint`` /
      ``build_collector_config_kwargs``). The default population test.
    Group B -- consumed by the IDENTITY-ALLOWLIST population runtime. When
      ``required_checkpoint_identities_path`` is set it is the ONLY test applied and the
      established filter is not evaluated (RESEARCH_WORKFLOW.md §7); the other group-B keys
      are frozen-population provenance.
    Group C -- ANALYSIS-SLICE metadata. Not a runtime gate and never a model input; drives
      maturity-stratified reporting and is traced from ``research_decision.yaml``. Declared
      here so it is a typed, documented field rather than a silently-ignored key.
    """

    model_config = ConfigDict(extra="forbid")

    # -- Group A: established filter ----------------------------------------------
    established: Optional[bool] = Field(None, exclude_if=lambda v: v is None)
    age_gate_seconds: Optional[int] = Field(None, exclude_if=lambda v: v is None)
    cadence_seconds: Optional[int] = Field(None, exclude_if=lambda v: v is None)
    running_mfe_atr_gte: Optional[float] = Field(None, exclude_if=lambda v: v is None)
    new_progress_windows_gte: Optional[int] = Field(None, exclude_if=lambda v: v is None)
    retained_mfe_ratio_gte: Optional[float] = Field(None, exclude_if=lambda v: v is None)

    # -- Group B: identity allowlist + its provenance ---------------------------
    required_checkpoint_identities_path: Optional[str] = Field(None, exclude_if=lambda v: v is None)
    required_checkpoint_identities_sha256: Optional[str] = Field(
        None, pattern=r"^[0-9a-fA-F]{64}$", exclude_if=lambda v: v is None
    )
    population_version: Optional[str] = Field(None, exclude_if=lambda v: v is None)
    selection: Optional[str] = Field(None, exclude_if=lambda v: v is None)
    stage1_score_threshold_source: Optional[str] = Field(None, exclude_if=lambda v: v is None)
    stage1_score_threshold_derivation: Optional[str] = Field(None, exclude_if=lambda v: v is None)

    # -- Group C: analysis-slice metadata (never a runtime gate) ----------------
    primary_maturity_buckets: Optional[List[str]] = Field(None, exclude_if=lambda v: v is None)
    diagnostic_maturity_buckets: Optional[List[str]] = Field(None, exclude_if=lambda v: v is None)
    maturity_role: Optional[str] = Field(None, exclude_if=lambda v: v is None)

    #: Keys the generic collector runtime actually consumes. A machine-readable list so
    #: preflight can re-assert coverage against the *selected* runtime (RT-06).
    ESTABLISHED_FILTER_KEYS: ClassVar[frozenset] = frozenset({
        "established", "age_gate_seconds", "cadence_seconds", "running_mfe_atr_gte",
        "new_progress_windows_gte", "retained_mfe_ratio_gte",
    })
    IDENTITY_ALLOWLIST_KEYS: ClassVar[frozenset] = frozenset({
        "required_checkpoint_identities_path", "required_checkpoint_identities_sha256",
    })
    RUNTIME_CONSUMED_KEYS: ClassVar[frozenset] = ESTABLISHED_FILTER_KEYS | IDENTITY_ALLOWLIST_KEYS

    @model_validator(mode="after")
    def validate_mutually_exclusive_population_tests(self) -> "PopulationQualificationSpec":
        if self.required_checkpoint_identities_path is not None:
            if self.required_checkpoint_identities_sha256 is None:
                raise ValueError("REQUIRED_CHECKPOINT_IDENTITIES_SHA256_REQUIRED")
            established_thresholds = [
                k for k in ("age_gate_seconds", "running_mfe_atr_gte",
                            "new_progress_windows_gte", "retained_mfe_ratio_gte")
                if getattr(self, k) is not None
            ] + (["established"] if self.established else [])
            if established_thresholds:
                raise ValueError(
                    "POPULATION_QUALIFICATION_TESTS_MUTUALLY_EXCLUSIVE: "
                    "required_checkpoint_identities_path (identity allowlist) is the only "
                    "qualification test applied when set; it may not be combined with the "
                    f"established-filter keys {established_thresholds} (RESEARCH_WORKFLOW.md §7)"
                )
        elif self.required_checkpoint_identities_sha256 is not None:
            raise ValueError("REQUIRED_CHECKPOINT_IDENTITIES_PATH_REQUIRED")
        return self


class PopulationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field("regime_state", description="Population type, e.g. regime_state, breakout")
    prevailing_regime: Optional[str] = Field(
        None, description="Prevailing regime direction, e.g. bearish, bullish"
    )
    session: str = Field("RTH", description="Session filter, e.g. RTH, ETH, ALL")
    qualification: Optional[PopulationQualificationSpec] = Field(
        default=None,
        description="Typed, closed qualification rules -- see PopulationQualificationSpec",
    )
    episode_lifecycle: Optional[EpisodeLifecycleSpec] = Field(
        None, exclude_if=lambda value: value is None
    )


class FlipConditionSpec(BaseModel):
    """One condition of a composite target: a regime-flip event."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique condition id within this target")
    kind: Literal["flip"] = "flip"
    event: Optional[str] = Field(None, description="Target event name, e.g. regime_flip")
    direction: Optional[str] = Field(None, description="Target direction, e.g. bullish, bearish")
    horizon_seconds: Optional[int] = Field(None, gt=0, description="Prediction horizon in seconds")
    confirmation: Optional["TargetConfirmationSpec"] = Field(default=None)
    # A composite primitive owns its own censoring semantics.  These defaults are
    # deliberately explicit at compile time; a target-level convenience setting may
    # not reinterpret a child.
    session_end_censoring: Optional[bool] = None
    max_gap_seconds: Optional[int] = Field(None, gt=0)


class TargetConfirmationSpec(BaseModel):
    """The only confirmation semantics implemented by the flip runtime today."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["bar_close", "completed_1m_bar"] = "bar_close"
    confirmation_bars: Literal[1] = 1


class ExcursionConditionSpec(BaseModel):
    """One condition of a composite target: a threshold on a forward-outcome excursion metric.

    ``metric`` is a free string (e.g. ``mfe_atr``, ``mae_atr``) -- it is never enum-locked to a
    specific pair of metrics, so this stays a generic mechanism rather than an
    MFE/MAE special case. The metric is *generated*, not computed here: see
    ``forward_outcome_id`` and ``TargetSpec.required_forward_outcomes``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique condition id within this target")
    kind: Literal["excursion"] = "excursion"
    metric: str = Field(..., description="Forward-outcome metric name, e.g. mfe_atr, mae_atr")
    comparator: Literal[">=", "<=", ">", "<", "=="] = Field(...)
    threshold: float = Field(...)
    forward_outcome_id: str = Field(
        ..., description="id of the TargetSpec.required_forward_outcomes entry that generates this metric"
    )


class ReturnConditionSpec(BaseModel):
    """One condition of a composite target: a threshold on a forward-outcome return metric."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique condition id within this target")
    kind: Literal["return"] = "return"
    comparator: Literal[">=", "<=", ">", "<", "=="] = Field(...)
    threshold: float = Field(...)
    forward_outcome_id: str = Field(
        ..., description="id of the TargetSpec.required_forward_outcomes entry that generates this metric"
    )


class OrderedBarrierConditionSpec(BaseModel):
    """Binary label produced by a declared asymmetric ordered-barrier race."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique condition id within this target")
    kind: Literal["ordered_barrier"] = "ordered_barrier"
    forward_outcome_id: str = Field(...)
    barrier_id: str = Field(...)


TargetConditionSpec = Annotated[
    Union[
        FlipConditionSpec,
        ExcursionConditionSpec,
        ReturnConditionSpec,
        OrderedBarrierConditionSpec,
    ],
    Field(discriminator="kind"),
]
class OrderedBarrierRequirementSpec(BaseModel):
    """Schema-layer declaration compiled to the runtime OrderedBarrierSpec."""

    model_config = ConfigDict(extra="forbid")

    id: str
    favorable_atr: float = Field(..., gt=0)
    adverse_atr: float = Field(..., gt=0)
    horizon_seconds: int = Field(..., gt=0)
    horizon_expiry_policy: Optional[Literal["censor", "negative"]] = Field(
        "censor", description="Disposition when horizon expires without touching either barrier"
    )


class RequiredForwardOutcomeSpec(BaseModel):
    """Declares how a forward-outcome measurement referenced by a composite condition is generated.

    Kept distinct from the conditions themselves (review correction): a threshold condition
    *consumes* a value; this spec declares *how that value is produced* -- entry reference,
    horizon, ATR/units, bar inclusion, censoring. ``target_engine.compile_target_contract``
    constructs a real ``research_workflow.forward_outcomes.contracts.ForwardOutcomeSpec`` from
    this (not an approximation of its shape), so the same causal guard that already protects
    forward-outcome columns applies to composite-target excursion conditions for free.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique id referenced by condition forward_outcome_id values")
    entry_reference: Literal["decision_close", "next_bar_open", "confirmation_close", "explicit"] = "next_bar_open"
    horizon_seconds: int = Field(..., gt=0, description="Measurement horizon in seconds")
    max_tracking_seconds: Optional[int] = Field(
        None, gt=0, description="Tracking budget; defaults to horizon_seconds when unset"
    )
    excursion_units: List[Literal["points", "atr", "ticks"]] = Field(default_factory=lambda: ["atr"])
    bar_inclusion: Literal["fully_forward", "close_after_entry"] = "fully_forward"
    session_end_censoring: bool = False
    horizon_expiry_policy: Optional[Literal["censor", "negative"]] = Field(
        "censor", description="Disposition when horizon expires without touching either barrier"
    )
    max_gap_seconds: Optional[int] = Field(
        None, gt=0, exclude_if=lambda value: value is None
    )
    # Provenance of the numeric ``ProposedEntry.entry_atr`` used by ATR barriers.
    # It is declarative identity, not another calculated ATR stream.
    atr_source: Optional[Literal["latest_causally_completed_1m_wilder_atr_14_available_at_T"]] = Field(None)
    atr_frozen_at: Optional[Literal["decision_ts", "entry_ts", "confirmation_ts"]] = Field(None)
    ordered_barriers: Optional[List[OrderedBarrierRequirementSpec]] = Field(
        None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_ordered_barriers(self) -> RequiredForwardOutcomeSpec:
        barriers = self.ordered_barriers or []
        ids = [b.id for b in barriers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"DUPLICATE_ORDERED_BARRIER_ID: {ids}")
        budget = self.max_tracking_seconds if self.max_tracking_seconds is not None else self.horizon_seconds
        if any(b.horizon_seconds > budget for b in barriers):
            raise ValueError("ORDERED_BARRIER_HORIZON_EXCEEDS_TRACKING_BUDGET")
        if (self.atr_source is None) != (self.atr_frozen_at is None):
            raise ValueError("ATR_PROVENANCE_REQUIRES_SOURCE_AND_FREEZE_REFERENCE")
        if barriers and self.atr_source is None:
            raise ValueError("ORDERED_BARRIER_ATR_SOURCE_REQUIRED")
        if barriers and self.atr_frozen_at is not None and self.atr_frozen_at != "decision_ts":
            raise ValueError("ORDERED_BARRIER_ATR_MUST_FREEZE_AT_DECISION")
        return self


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field("flip", description="Target type, e.g. flip, excursion, return, composite")
    event: Optional[str] = Field(None, description="Target event name, e.g. regime_flip")
    direction: Optional[str] = Field(
        None, description="Target direction, e.g. bullish (for bearish prevailing), bearish"
    )
    horizon_seconds: Optional[int] = Field(None, gt=0, description="Prediction horizon in seconds, e.g. 300")
    confirmation: Optional[TargetConfirmationSpec] = Field(default=None)
    session_end_censoring: Optional[bool] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Whether a candidate whose resolution window extends past its own session "
            "close is CENSORED rather than labeled. Authoritative for a plain flip "
            "target; a composite / ordered-barrier target instead carries this on each "
            "required_forward_outcomes entry (RequiredForwardOutcomeSpec.session_end_"
            "censoring) and target_engine derives the collector-global value from those. "
            "Left unset, a plain flip target keeps the historical default (True). "
            "Additive and hash-neutral (excluded from model_dump when None)."
        ),
    )
    # -- composite target support -------------------------------------------------
    # A study with no `conditions` declared compiles exactly as it always has -- these
    # fields are additive and never required.
    conditions: Optional[List[TargetConditionSpec]] = Field(
        default=None, description="Composite target: typed, discriminated conditions"
    )
    condition_logic: Optional[Literal["AND", "OR"]] = Field(
        default=None, description="Boolean composition of `conditions`; required when len(conditions) > 1"
    )
    required_forward_outcomes: Optional[List[RequiredForwardOutcomeSpec]] = Field(
        default=None, description="Forward-outcome generation specs referenced by excursion/return conditions"
    )
    decision_reference: Literal["decision_ts", "entry_ts", "confirmation_ts"] = Field(
        "decision_ts",
        description="When this study model actually makes its decision, on the shared "
                    "TIMESTAMP_CAUSAL_ORDER scale. Not assumed to always be decision_ts.",
    )

    @model_validator(mode="after")
    def validate_composite_target(self) -> TargetSpec:
        conditions = self.conditions or []
        if self.required_forward_outcomes and self.session_end_censoring is not None:
            raise ValueError("COMPOSITE_SESSION_POLICY_MUST_BE_CHILD_OWNED")
        if len(conditions) > 1 and not self.condition_logic:
            raise ValueError(
                "TARGET_CONDITION_LOGIC_REQUIRED: a composite target with more than one "
                "condition must declare condition_logic (AND/OR)"
            )
        ids = [c.id for c in conditions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"DUPLICATE_TARGET_CONDITION_ID: {ids}")
        declared_fo_ids = {fo.id for fo in (self.required_forward_outcomes or [])}
        declared_fo = {fo.id: fo for fo in (self.required_forward_outcomes or [])}
        for c in conditions:
            if c.kind in ("excursion", "return", "ordered_barrier") and c.forward_outcome_id not in declared_fo_ids:
                raise ValueError(
                    f"TARGET_CONDITION_FORWARD_OUTCOME_UNDECLARED: condition {c.id!r} "
                    f"references undeclared forward_outcome_id {c.forward_outcome_id!r}"
                )
            if c.kind == "ordered_barrier" and c.forward_outcome_id in declared_fo:
                barrier_ids = {
                    b.id for b in (declared_fo[c.forward_outcome_id].ordered_barriers or [])
                }
                if c.barrier_id not in barrier_ids:
                    raise ValueError(
                        f"TARGET_CONDITION_ORDERED_BARRIER_UNDECLARED: condition {c.id!r} "
                        f"references barrier {c.barrier_id!r}"
                    )
        return self


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


class DiagnosticModelReusePolicySpec(BaseModel):
    """Closed, evidence-bound authorization for diagnostic derived-model reuse.

    A registry ``UNASSESSED`` record is not approved merely because its source closure
    assessed it.  Its child declaration must pin that closure's byte and canonical
    identities, the exact assessed model byte, and the expected diagnostic assessment.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["diagnostic_derived_causal_input"] = "diagnostic_derived_causal_input"
    model_id: str
    parent_study_id: str
    parent_closure_path: Literal["artifacts/study_closure.json"]
    parent_closure_sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    parent_closure_identity_sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    expected_assessment: Literal["VALID_DIAGNOSTIC"] = "VALID_DIAGNOSTIC"
    artifact_sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    # Runtime drift is exceptional: when requested it must be tied to a concrete,
    # hash-pinned parent-study evidence artifact rather than a bare boolean.
    allow_runtime_drift: bool = False
    runtime_drift_evidence_path: Optional[str] = None
    runtime_drift_evidence_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def validate_runtime_drift_evidence(self) -> "DiagnosticModelReusePolicySpec":
        evidence = (self.runtime_drift_evidence_path, self.runtime_drift_evidence_sha256)
        if self.allow_runtime_drift and not all(evidence):
            raise ValueError("DIAGNOSTIC_REUSE_RUNTIME_DRIFT_EVIDENCE_REQUIRED")
        if not self.allow_runtime_drift and any(evidence):
            raise ValueError("DIAGNOSTIC_REUSE_RUNTIME_DRIFT_EVIDENCE_UNEXPECTED")
        return self


class DerivedCausalInputSpec(BaseModel):
    """A causal input that is NOT a canonical market FeatureInstance.

    Distinguished by construction from `features.instances`: this is never resolvable
    through `features.registry`, and the compiled feature contract keeps it in a separate
    `derived_causal_inputs` key. Initial supported kind is a frozen external model score --
    the output of another study's TRAIN freeze, consumed as a first-class input with
    provenance, never re-derived or retrained by the child study.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Column name this input is bound to")
    kind: Literal["frozen_external_model_score"] = "frozen_external_model_score"
    model_id: Optional[str] = Field(None, description="Immutable preserved-model registry identity")
    parent_study_id: Optional[str] = Field(None, description="Upstream study directory id")
    parent_train_freeze_artifact: Optional[str] = Field(
        None, description="Relative path within the parent study to its authoritative TRAIN freeze"
    )
    parent_train_freeze_artifact_sha256: Optional[str] = Field(
        None, description="sha256 of the exact file bytes at parent_train_freeze_artifact"
    )
    parent_frozen_execution_composite_sha256: Optional[str] = Field(
        None, description="Parent's audited execution composite, from its audit/status.json"
    )
    model_hashes: Dict[str, str] = Field(default_factory=dict, description="Per-arm fit_identity_sha256 values, must match the parent freeze")
    preprocessing_hash: Optional[str] = Field(None)
    score_artifact_path: Optional[str] = Field(
        None, description="A materialized score table, if consumed instead of the raw model artifact"
    )
    score_artifact_sha256: Optional[str] = Field(None)
    model_artifact_path: Optional[str] = Field(None, exclude_if=lambda value: value is None)
    model_artifact_sha256: Optional[str] = Field(None, exclude_if=lambda value: value is None)
    preprocessing_artifact_path: Optional[str] = Field(None, exclude_if=lambda value: value is None)
    preprocessing_artifact_sha256: Optional[str] = Field(None, exclude_if=lambda value: value is None)
    ordered_feature_surfaces: Optional[Dict[str, List[str]]] = Field(
        None, exclude_if=lambda value: value is None
    )
    direction_arm_mapping: Optional[Dict[Literal["LONG", "SHORT"], str]] = Field(
        None, exclude_if=lambda value: value is None
    )
    score_output: Literal["predict_proba_positive"] = Field(
        "predict_proba_positive",
        exclude_if=lambda value: value == "predict_proba_positive",
    )
    availability_reference: Literal["decision_ts", "entry_ts", "confirmation_ts"] = "decision_ts"
    retrain_prohibited: bool = Field(
        True, description="Must be True for this kind -- the child study may never retrain the upstream model"
    )
    diagnostic_reuse_policy: Optional[DiagnosticModelReusePolicySpec] = Field(
        None, exclude_if=lambda value: value is None,
        description="Closed explicit authorization required only for VALID_DIAGNOSTIC model reuse",
    )

    @field_validator("retrain_prohibited")
    @classmethod
    def validate_retrain_prohibited(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "DERIVED_INPUT_RETRAIN_PROHIBITED_REQUIRED: frozen_external_model_score inputs "
                "may never permit upstream retraining"
            )
        return v

    @model_validator(mode="after")
    def validate_model_binding_xor(self):
        legacy = (self.parent_study_id, self.parent_train_freeze_artifact,
                  self.parent_train_freeze_artifact_sha256,
                  self.parent_frozen_execution_composite_sha256,
                  self.model_hashes, self.preprocessing_hash)
        complete_legacy = all(legacy)
        any_legacy = any(legacy)
        if self.model_id and any_legacy:
            raise ValueError("DERIVED_INPUT_BINDING_XOR: model_id binding may not include legacy binding fields")
        if not self.model_id and not complete_legacy:
            raise ValueError("DERIVED_INPUT_BINDING_XOR: declare model_id or a complete legacy binding")
        return self


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

    # V2 study-local instance declarations.  They are intentionally a list in
    # the StudySpec, not a global instance registry: the canonical definition
    # owns lifecycle while a study supplies only its parameters/output alias.
    instances: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Canonical FeatureInstance declarations: feature, parameters, optional physical_alias",
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
    derived_inputs: Optional[List[DerivedCausalInputSpec]] = Field(
        default=None, description="Non-FeatureInstance causal inputs, e.g. a frozen external model score"
    )


class HyperparameterDomainSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["choice", "int_range", "float_range"]
    values: Optional[List[Any]] = None
    low: Optional[float] = None
    high: Optional[float] = None
    log_scale: bool = False

    @model_validator(mode="after")
    def validate_domain(self) -> HyperparameterDomainSpec:
        if self.kind == "choice" and not self.values:
            raise ValueError("HYPERPARAMETER_CHOICE_REQUIRES_VALUES")
        if self.kind in ("int_range", "float_range"):
            if self.low is None or self.high is None or self.low >= self.high:
                raise ValueError("HYPERPARAMETER_RANGE_REQUIRES_LOW_LT_HIGH")
            if self.log_scale and self.low <= 0:
                raise ValueError("LOG_SCALE_REQUIRES_POSITIVE_LOW")
        return self


class ModelFamilySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    fixed_hyperparameters: Optional[Dict[str, Any]] = None
    tunable_hyperparameters: Optional[List[HyperparameterDomainSpec]] = None


class MetricBoundSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    @model_validator(mode="after")
    def at_least_one_bound(self) -> MetricBoundSpec:
        if self.minimum is None and self.maximum is None:
            raise ValueError("METRIC_BOUND_REQUIRES_MIN_OR_MAX")
        return self


class FinalValidationRequirementsSpec(BaseModel):
    """Typed acceptance bounds for the final TRAIN-side validation period.

    The final-validation period may only ACCEPT or REJECT the winner an inner
    chronological search already selected -- it never triggers another search. See
    `ModelSelectionSpec.final_validation_policy`.
    """

    model_config = ConfigDict(extra="forbid")

    primary_metric_bound: Optional[MetricBoundSpec] = None
    max_degradation_vs_inner_validation: Optional[float] = Field(
        None, description="Direction-aware fraction: how much worse the final metric may be than inner"
    )
    calibration_max_brier: Optional[float] = None
    secondary_metric_bounds: Optional[List[MetricBoundSpec]] = None


class ModelSelectionSpec(BaseModel):
    """Bounded, TRAIN-only hyperparameter search protocol -- never an unbounded AutoML system."""

    model_config = ConfigDict(extra="forbid")

    allowed_families: List[ModelFamilySpec] = Field(default_factory=list)
    search_method: Literal["grid", "random", "none"] = "none"
    max_trials: Optional[int] = None
    random_seed: Optional[int] = None
    tuning_years: Optional[List[int]] = Field(
        default=None, description="Inner-TRAIN chronological search years -- distinct from chronology.dev (OOS)"
    )
    final_train_validation_years: Optional[List[int]] = Field(
        default=None, description="Inner-TRAIN confirmatory years -- accept/reject only, never re-selects"
    )
    primary_selection_metric: Optional[str] = None
    primary_selection_metric_direction: Literal["maximize", "minimize"] = "maximize"
    secondary_metrics: Optional[List[str]] = None
    calibration_required: bool = False
    simpler_model_tie_preference: bool = True
    final_validation_policy: Literal["gated", "report_only"] = "gated"
    final_validation_requirements: Optional[FinalValidationRequirementsSpec] = None

    @model_validator(mode="after")
    def validate_bounded_search(self) -> ModelSelectionSpec:
        if self.search_method != "none":
            if not self.max_trials:
                raise ValueError("MODEL_SELECTION_MAX_TRIALS_REQUIRED")
            if not any(f.tunable_hyperparameters for f in self.allowed_families):
                raise ValueError("MODEL_SELECTION_NO_TUNABLE_DOMAIN")
            if not self.tuning_years or len(self.tuning_years) < 2:
                raise ValueError("INSUFFICIENT_TUNING_YEARS_FOR_INNER_VALIDATION")
            if self.search_method == "grid":
                bad = [
                    h.name for f in self.allowed_families
                    for h in (f.tunable_hyperparameters or [])
                    if h.kind != "choice"
                ]
                if bad:
                    raise ValueError(f"GRID_REQUIRES_CHOICE_DOMAINS: {bad}")
            # Explicit, not implicit: a study that wants no numerical gate must say so.
            if self.final_validation_policy == "gated" and not self.final_validation_requirements:
                raise ValueError("FINAL_VALIDATION_REQUIREMENTS_REQUIRED_FOR_GATED_POLICY")
        return self


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
    selection: Optional[ModelSelectionSpec] = Field(
        default=None, description="Bounded TRAIN-only model-selection / hyperparameter search protocol"
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


class GateScopeField(str, Enum):
    """Typed StudySpec sections the required-gate artifact staleness hash may bind to.

    An Enum rejects an unknown/typo'd scope name at Pydantic validation time -- no custom
    validator needed for that half of the review's requirement.
    """

    POPULATION = "population"
    TARGET = "target"
    CHRONOLOGY = "chronology"
    FEATURES = "features"
    INSTRUMENT = "instrument"


class RequiredGateSpec(BaseModel):
    """A study-declared pre-freeze gate PREPARE/READINESS/PREFLIGHT/SEAL/TRAIN FREEZE must
    fail closed on if the artifact it names is missing, stale, or not PASS. Never an
    arbitrary shell command -- always a structured artifact (see research_workflow.gates).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    stage: Literal["prepare", "readiness", "preflight", "seal", "pre_fit", "train_freeze"]
    artifact_path: str = Field(..., description="Relative path within the study directory")
    artifact_schema_version: int
    scope_fields: List[GateScopeField] = Field(
        default_factory=lambda: [GateScopeField.POPULATION, GateScopeField.CHRONOLOGY, GateScopeField.TARGET]
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
    modeling_driver_relpaths: Optional[List[str]] = Field(
        default=None,
        exclude_if=lambda value: not value,
        description=(
            "Study-relative paths to study-local modeling driver module(s) (e.g. "
            "'implementation/train_merge_fit_freeze.py') that compose governed modeling "
            "APIs (fit / model-selection / freeze / pre-fit gate scope). Declaring a "
            "driver here binds its exact file bytes -- and its transitive import closure "
            "-- into MODELING_EXECUTION_CLOSURE (research_workflow/modeling_closure.py), "
            "so a modeling-only edit to it stales the TRAIN freeze / blocks OOS without "
            "invalidating collection. A study-local implementation module that imports a "
            "governed modeling API but is NOT declared here fails closed before fit "
            "(research_workflow/modeling_drivers.py). Additive and hash-neutral: absent, "
            "null and [] all serialize identically (the exclude_if drops the key), so "
            "adding this field never stales an already-compiled study."
        ),
    )
    # NOTE: authorized modes are deliberately NOT a StudySpec field.
    # `compute_sha256` hashes `model_dump(exclude_none=False)`, so any additional field --
    # even an unset optional one -- changes every study's spec hash and marks every
    # existing compiled_study.json stale (UNLESS, like `modeling_driver_relpaths` above,
    # it carries an `exclude_if` that drops it from `model_dump` when unset). The
    # mode-partitioned deliverables contract therefore derives its modes from
    # `operation.kind` in the compiler instead (research/engines/deliverables_engine.py).
    # Adding a declarative override here needs a deliberate spec-version bump and a
    # recompile of every study.


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
        "diagnostic_followup",
        "bespoke_operation",
    ] = Field("train_evaluate", description="Specific research operation type")
    target_metric: Optional[str] = Field(None, description="Primary quantitative evaluation metric")
    reconciliation_target: Optional[str] = Field(None, description="Target for parity/reconciliation studies")


class StudySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study: StudyMetadata
    operation: OperationSpec = Field(default_factory=OperationSpec)
    # Immutable operational parameters for the one generic diagnostic follow-up
    # runtime.  Kept opaque to the generic StudySpec; its exact validation and
    # execution binding live with the diagnostic runtime/compiler.
    diagnostic_followup: Optional[Dict[str, Any]] = Field(default=None)
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
    required_gates: Optional[List[RequiredGateSpec]] = Field(
        default=None, description="Machine-enforced pre-freeze gates this study declares"
    )

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

    @model_validator(mode="after")
    def validate_derived_input_causal_ordering(self) -> StudySpec:
        """Availability must be provably at-or-before the decision point of the CHILD study --

        not merely membership in the {decision_ts, entry_ts, confirmation_ts} enum. A derived
        input available only at confirmation_ts is illegal for a study whose own model decides
        at decision_ts (confirmation happens strictly after); a later-deciding study may
        legitimately consume it. The comparison is a real ordering check on
        TIMESTAMP_CAUSAL_ORDER, not a decision_ts-only special case.
        """
        decision_idx = TIMESTAMP_CAUSAL_ORDER[self.target.decision_reference]
        for di in ((self.features.derived_inputs if self.features else None) or []):
            avail_idx = TIMESTAMP_CAUSAL_ORDER[di.availability_reference]
            if avail_idx > decision_idx:
                raise ValueError(
                    f"DERIVED_INPUT_NOT_AVAILABLE_AT_DECISION: input {di.name!r} available at "
                    f"{di.availability_reference!r} but this study's decision point is "
                    f"{self.target.decision_reference!r}"
                )
        return self

    @model_validator(mode="after")
    def validate_model_selection_chronology(self) -> StudySpec:
        """chronology.dev already means OOS in this codebase (experiment.py binds it to
        oos_years); tuning_years/final_train_validation_years are a distinct inner-TRAIN
        concept and must never overlap it, chronology.prohibited, or fall outside
        chronology.train. This is the compile-time half of "OOS years can never enter tuning".
        """
        selection = self.model.selection if self.model else None
        if not selection or not (selection.tuning_years or selection.final_train_validation_years):
            return self
        train_years = set(self.chronology.train or []) if self.chronology else set()
        oos_years = set(self.chronology.dev or []) if self.chronology else set()
        prohibited_years = set(self.chronology.prohibited or []) if self.chronology else set()
        tuning = set(selection.tuning_years or [])
        final_val = set(selection.final_train_validation_years or [])
        if not tuning or not final_val:
            raise ValueError(
                "MODEL_SELECTION_YEARS_INCOMPLETE: both tuning_years and "
                "final_train_validation_years are required when either is declared"
            )
        if tuning & final_val:
            raise ValueError(
                f"MODEL_SELECTION_YEARS_OVERLAP: tuning_years and "
                f"final_train_validation_years share {sorted(tuning & final_val)}"
            )
        for label, years in (('tuning_years', tuning), ('final_train_validation_years', final_val)):
            if not years <= train_years:
                raise ValueError(
                    f"MODEL_SELECTION_YEARS_NOT_SUBSET_OF_TRAIN: {label} {sorted(years)} "
                    f"is not a subset of chronology.train {sorted(train_years)}"
                )
            if years & oos_years:
                raise ValueError(
                    f"MODEL_SELECTION_YEARS_INCLUDE_OOS: {label} {sorted(years)} overlaps "
                    f"chronology.dev (OOS) {sorted(oos_years)}"
                )
            if years & prohibited_years:
                raise ValueError(
                    f"MODEL_SELECTION_YEARS_INCLUDE_PROHIBITED: {label} {sorted(years)} "
                    f"overlaps chronology.prohibited {sorted(prohibited_years)}"
                )
        return self

    def compute_sha256(self) -> str:
        """Computes deterministic canonical SHA-256 hash of the StudySpec."""
        data_dict = self.model_dump(exclude_none=False)
        # `model_id` is an additive, opt-in derived-input binding (see
        # DerivedCausalInputSpec.validate_model_binding_xor). Studies compiled before it
        # existed declare a legacy binding and never set it; dropping the null key keeps
        # their canonical spec hash byte-identical so an additive schema field cannot
        # stale an already-compiled (or sealed, or closed) study.
        for _di in ((data_dict.get("features") or {}).get("derived_inputs") or []):
            if isinstance(_di, dict) and _di.get("model_id") is None:
                _di.pop("model_id", None)
        for _cond in ((data_dict.get("target") or {}).get("conditions") or []):
            if isinstance(_cond, dict):
                if _cond.get("session_end_censoring") is None:
                    _cond.pop("session_end_censoring", None)
                if _cond.get("max_gap_seconds") is None:
                    _cond.pop("max_gap_seconds", None)
        canonical_json = json.dumps(data_dict, sort_keys=True, indent=None)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

# tamper_authority_canary

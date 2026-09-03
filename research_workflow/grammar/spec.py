"""StudySpecV2: the composition grammar (schema only; no semantics live here).

Sections (``study``, ``streams``, ``population``, ``outcome``, ``chronology`` required;
``context``, ``triggers``, ``features``, ``model`` optional).  There is no ``study.type``:
a flip study, a checkpoint study and a stateful watch/trigger study are all compositions
of the same six primitive kinds.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DURATION_RE = re.compile(r"^(\d+)(s|m|h)$")
_UNIT = {"s": 1, "m": 60, "h": 3600}


def duration_seconds(value: Union[str, int, float], *, where: str = "duration") -> int:
    """'600s' | '5m' | 300 -> seconds (integer)."""
    if isinstance(value, bool):
        raise ValueError(f"{where}: boolean is not a duration")
    if isinstance(value, (int, float)):
        if value < 0 or int(value) != value:
            raise ValueError(f"{where}: {value!r} is not a non-negative integer number of seconds")
        return int(value)
    m = _DURATION_RE.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"{where}: {value!r} is not a duration like '600s' or '5m'")
    return int(m.group(1)) * _UNIT[m.group(2)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudySection(_Strict):
    id: str
    tier: int = Field(2, ge=1, le=3)
    question: str = Field(..., min_length=1)
    description: Optional[str] = None


class StreamSpec(_Strict):
    dataset: str
    instrument: Optional[str] = None         # defaults to the dataset's instrument symbol
    timeframes: List[str] = Field(..., min_length=1)
    role: Literal["execution", "context"] = "execution"
    same_ts: Literal["unavailable", "available"] = "unavailable"   # context streams only

    @field_validator("timeframes")
    @classmethod
    def _tf(cls, v: List[str]) -> List[str]:
        for tf in v:
            duration_seconds(tf, where="streams.timeframes")
        if len(set(v)) != len(v):
            raise ValueError("streams.timeframes has duplicates")
        return v


class GridCadence(_Strict):
    every: str                                 # '5s'
    anchor: str                                # 'regime_1m.start_ns'  (tracker field)
    max_age: Optional[str] = None              # '1800s'
    index_column: str = "checkpoint_index"


class PopulationSpec(_Strict):
    session: str = "RTH"
    cadence: Union[str, GridCadence] = "completed_1s"   # 'completed_1s' | 'completed_1m' | grid
    qualify: Optional[str] = None                        # predicate text
    direction: Optional[str] = None                      # reference, e.g. 'regime_1m.dir'
    anchor_identity: Optional[str] = None                # reference stamped as regime_start_ns


class ContextTrackerSpec(BaseModel):
    """``name: {tracker: <capability>, <params...>}`` -- params are free-form per tracker."""
    model_config = ConfigDict(extra="allow")
    tracker: str
    instrument: Optional[str] = None


class TriggerStateSpec(_Strict):
    enter_when: str
    expire_when: Optional[str] = None
    from_states: List[str] = Field(default_factory=list, alias="from")
    chain: bool = False                        # may be entered in the same sub-epoch as its predecessor
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EntrySpec(_Strict):
    when: str
    reference: str = "next_bar_open"
    context: List[str] = Field(default_factory=list)
    max_per_watch: Optional[int] = None
    cooldown: Optional[str] = None


class AddSpec(_Strict):
    when: str
    max_adds: int = 1


class TriggerGraphSpec(_Strict):
    cadence: Optional[str] = None                 # 'completed_1s' | 'tracker_events'
    states: Dict[str, TriggerStateSpec] = Field(default_factory=dict)
    entry: Optional[EntrySpec] = None
    add: Optional[AddSpec] = None
    precedence: List[str] = Field(default_factory=list)
    reset_when: Optional[str] = None               # graph-level edge events that clear every state
    max_transitions_per_epoch: int = 1
    sub_epochs: Literal["none", "tracker_events"] = "none"


TriggersSpec = Union[Literal["every_candidate"], TriggerGraphSpec]


class FeatureInstanceSpec(BaseModel):
    """``{feature, parameters?, over?: {param: [values...]}, alias?}`` -- free params allowed."""
    model_config = ConfigDict(extra="allow")
    feature: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    over: Dict[str, List[Any]] = Field(default_factory=dict)
    alias: Optional[str] = None


class DerivedInputSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    kind: str


class FeaturesSpec(_Strict):
    host: Literal["provider_host", "synthetic"] = "provider_host"
    columns: Dict[str, str] = Field(default_factory=dict)         # synthetic host: column -> reference
    instances: List[FeatureInstanceSpec] = Field(default_factory=list)
    metadata: Dict[str, str] = Field(default_factory=dict)      # output column -> 'tracker.field'
    derived_inputs: List[DerivedInputSpec] = Field(default_factory=list)
    bindings: Dict[str, Any] = Field(default_factory=dict)       # feature-host input bindings (see compiler)


class BarrierArmSpec(_Strict):
    id: str
    favorable_atr: float = Field(..., gt=0)
    adverse_atr: float = Field(..., gt=0)
    horizon: Optional[str] = None
    expiry: Literal["censor", "negative"] = "censor"


class OutcomeItemSpec(_Strict):
    id: str
    kind: Literal["barrier", "event", "horizon", "stop_move", "trail"]
    favorable_atr: Optional[float] = None
    adverse_atr: Optional[float] = None
    when: Optional[str] = None
    horizon: Optional[str] = None
    expiry: Literal["censor", "negative"] = "censor"


class FillModelSpec(_Strict):
    order_type: Literal["market", "limit", "stop"] = "market"
    latency_bars: int = 0
    slippage_ticks: float = 0.0
    spread_ticks: float = 0.0


class OutcomeSpec(_Strict):
    kind: Literal["label", "trade"]
    entry_reference: str = "next_bar_open"
    direction: Optional[str] = None                # reference; default population.direction
    relation: Literal["continuation", "fade"] = "continuation"   # barrier/event direction relative to `direction`
    atr: Optional[str] = None                      # reference, e.g. 'regime_1m.atr' (frozen at decision)
    # When is "the ATR available at T" read?  at_decision_delivery = the tracker state when
    # the decision bar is delivered (a same-timestamp coarser bar not yet applied);
    # through_decision_ts = after every bar with ts_init == T has been applied.
    atr_availability: Optional[Literal["at_decision_delivery", "through_decision_ts"]] = None
    horizon: Optional[str] = None                  # default horizon for items without their own
    session_end: Literal["censor", "ignore"] = "censor"
    session: Optional[str] = None                  # censoring session (default: population.session)
    max_gap: Optional[str] = None
    same_bar_rule: Literal["ambiguous_censor", "adverse_first"] = "ambiguous_censor"
    # strict: no bar closing after the horizon end is ever evaluated (a bar closing exactly at the end is).
    # first_bar_at_or_after: the first bar closing at or after the horizon end is still evaluated for a
    # barrier hit before expiry (the sealed regime_transition target authority's realized semantics on
    # sparse seconds; identical to strict on dense tapes). Resolution precedence at every bar (in-horizon
    # or the first post-horizon bar under first_bar_at_or_after) is SESSION_END > GAP > BARRIER_TOUCH >
    # HORIZON_EXPIRY: max_gap is adjudicated before a post-horizon bar's touch is ever accepted, so a
    # sparse tape cannot resolve a candidate from a bar farther than max_gap from the prior accepted bar.
    horizon_end_rule: Literal["strict", "first_bar_at_or_after"] = "strict"
    barrier: Optional[Dict[str, Any]] = None       # {favorable_atr, adverse_atr, horizon?, expiry?, arms?: [...]}
    event: Optional[str] = None                    # predicate over tracker events (e.g. 'regime_1m.flipped')
    items: List[OutcomeItemSpec] = Field(default_factory=list)
    composition: Optional[Literal["AND", "OR"]] = None
    precedence: List[str] = Field(default_factory=list)
    fill_model: Optional[FillModelSpec] = None
    label_column: Optional[str] = None             # name of the primary label column


class WarmupSpec(_Strict):
    days_before_partition: int = 5
    candidate_emission: bool = False
    target_generation: bool = False


class ChronologySpec(_Strict):
    train: List[int] = Field(..., min_length=1)
    dev: List[int] = Field(default_factory=list)
    prohibited: List[int] = Field(default_factory=list)
    diagnostic: List[int] = Field(default_factory=list)
    warmup: WarmupSpec = Field(default_factory=WarmupSpec)
    authorized_dates: List[str] = Field(default_factory=list)


class ValidationSpec(_Strict):
    protocol: str                                  # 'validation.model_selection.random' ...
    tuning_years: List[int] = Field(default_factory=list)
    final_train_validation_years: List[int] = Field(default_factory=list)
    max_trials: Optional[int] = None
    random_seed: Optional[int] = None
    primary_metric: Optional[str] = None


class ScoredModelExpectSpec(_Strict):
    """Optional identity expectations checked against the model-store lineage before scoring."""
    study_id: Optional[str] = None
    target_arm: Optional[str] = None
    direction: Optional[str] = None
    cell_id: Optional[str] = None
    # W-1: binds to the estimator's actual canonical BYTES (manifest["canonical"]
    # ["byte_sha256"]), not a lineage field -- catches a substituted estimator that
    # refreshes its own canonical/golden bytes under the unchanged model_id.
    canonical_sha256: Optional[str] = None


class ScoredModelSpec(_Strict):
    """A frozen model reused from the model store: scored, never refit."""
    id: str                                        # model store id (sha256)
    label: str                                     # label column the model is evaluated against
    subset: Dict[str, Any] = Field(default_factory=dict)   # column == value row filters (explicit, no hidden direction semantics)
    name: Optional[str] = None
    expect: Optional[ScoredModelExpectSpec] = None  # authenticated against model-store lineage before scoring


class ModelSpec(_Strict):
    mode: Literal["train", "score"] = "train"
    family: Optional[str] = None                   # required for mode: train
    params: Dict[str, Any] = Field(default_factory=dict)
    arms: List[str] = Field(default_factory=list)
    validation: Optional[ValidationSpec] = None
    models: List[ScoredModelSpec] = Field(default_factory=list)   # required for mode: score
    # Bounded TRAIN-only hyperparameter search over walk-forward folds of validation.tuning_years.
    # param -> [choices] | {low, high, log?: bool, int?: bool}; sampler = validation.protocol
    # (model_selection.random | model_selection.optuna), trials = validation.max_trials.
    # random_seed governs the SAMPLER (random-search RNG / Optuna TPESampler seed) only; when
    # absent the sampler falls back to model.params.random_state|seed. The estimator fit on
    # each fold always uses model.params.random_state|seed, never random_seed.
    search_space: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _mode(self) -> "ModelSpec":
        if self.mode == "train" and not self.family:
            raise ValueError("model.family is required for mode: train")
        if self.mode == "score" and not self.models:
            raise ValueError("model.models must list at least one frozen model for mode: score")
        return self


class StudySpecV2(_Strict):
    study: StudySection
    streams: List[StreamSpec] = Field(..., min_length=1)
    population: PopulationSpec
    context: Dict[str, ContextTrackerSpec] = Field(default_factory=dict)
    triggers: TriggersSpec = "every_candidate"
    features: FeaturesSpec = Field(default_factory=FeaturesSpec)
    outcome: OutcomeSpec
    chronology: ChronologySpec
    model: Union[Literal["none"], ModelSpec] = "none"

    @model_validator(mode="after")
    def _roles(self) -> "StudySpecV2":
        execution = [s for s in self.streams if s.role == "execution"]
        if len(execution) != 1:
            raise ValueError("exactly one stream must carry role: execution (the first stream by default)")
        return self

    @model_validator(mode="before")
    @classmethod
    def _default_first_execution(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("streams"), list) and data["streams"]:
            first = data["streams"][0]
            if isinstance(first, dict) and "role" not in first:
                first = dict(first); first["role"] = "execution"; data = dict(data); data["streams"] = [first] + list(data["streams"][1:])
            rest = []
            for s in data["streams"][1:]:
                if isinstance(s, dict) and "role" not in s:
                    s = dict(s); s["role"] = "context"
                rest.append(s)
            data["streams"] = [data["streams"][0]] + rest
        return data


__all__ = [
    "StudySpecV2", "StudySection", "StreamSpec", "PopulationSpec", "GridCadence", "ContextTrackerSpec",
    "TriggerGraphSpec", "TriggerStateSpec", "EntrySpec", "AddSpec", "FeaturesSpec", "FeatureInstanceSpec",
    "OutcomeSpec", "OutcomeItemSpec", "BarrierArmSpec", "ChronologySpec", "ModelSpec", "ValidationSpec",
    "duration_seconds",
]

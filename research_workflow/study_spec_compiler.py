"""Deterministic materialization of a StudySpec from an approved intake.

This module intentionally has no natural-language interpretation layer.  An intake must
either carry a machine readable ``study_spec``/``study_yaml`` block, or use the small
documented decision-contract projection below.  Everything else is reported as a field
resolution, never guessed.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class FieldResolution(str, Enum):
    RESOLVED_EXPLICITLY = "RESOLVED_EXPLICITLY"
    RESOLVED_FROM_CANONICAL_AUTHORITY = "RESOLVED_FROM_CANONICAL_AUTHORITY"
    RESOLVED_FROM_FROZEN_LINEAGE = "RESOLVED_FROM_FROZEN_LINEAGE"
    RESOLVED_FROM_ALLOWED_DEFAULT = "RESOLVED_FROM_ALLOWED_DEFAULT"
    SEMANTIC_DECISION_REQUIRED = "SEMANTIC_DECISION_REQUIRED"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    UNSAFE_TO_INFER = "UNSAFE_TO_INFER"


AUTO_RESOLVED = frozenset(FieldResolution.__members__[x] for x in (
    "RESOLVED_EXPLICITLY", "RESOLVED_FROM_CANONICAL_AUTHORITY",
    "RESOLVED_FROM_FROZEN_LINEAGE", "RESOLVED_FROM_ALLOWED_DEFAULT"))


# Scaffolding invariant: a capability authority (feature_candidate.yaml, the active
# feature bundle, promotion facts) may RESOLVE an explicitly-requested FeatureInstance,
# but it is never the study's scientific feature-selection authority. The compiler must
# not infer the motivated feature surface from the set of available/candidate
# capabilities. An intake that names families/concepts but not exact instances is a
# researcher decision -> SEMANTIC_DECISION_REQUIRED, never a guessed list.
class _UnresolvedFeatureSurface(dict):
    """Sentinel: the intake describes a feature surface by concept, not by instance."""


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _load(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("REQUEST_NOT_MAPPING")
    return raw


def _projection(request: dict[str, Any], study_id: str) -> dict[str, Any] | None:
    """Project the intentionally simple, reusable intake shape to StudySpec.

    This is deliberately narrow: callers with a more complex target/population must
    supply ``study_spec`` rather than have an engine invent causal semantics.
    """
    if not all(k in request for k in ("instrument", "chronology", "population", "target")):
        return None
    return {
        "study": request.get("study") or {"id": study_id, "type": request.get("type", "flip_prediction"),
            "description": request.get("description") or request.get("research_question", "Approved research study")},
        "instrument": request["instrument"], "chronology": request["chronology"],
        "population": request["population"], "target": request["target"],
        "features": request.get("features", {"source": "canonical_verified_definition_universe"}),
        "model": request.get("model", {}), "execution": request.get("execution", {"runtime": "nautilustrader"}),
        "operation": request.get("operation", {"kind": "train_evaluate"}),
    }


def _deep_pullback_projection(request: dict[str, Any], study: Path) -> dict[str, Any] | None:
    """Lossless projection of the approved deep-pullback contract format.

    The named fields in this intake predate ``StudySpec`` but are already structured;
    this adapter only selects the corresponding schema representation.
    """
    required = {"candidate_population", "primary_target", "stage1_dependency", "feature_policy", "model", "chronology", "instrument"}
    if not required <= set(request): return None
    if not request["instrument"].get("dataset_id"): return None
    candidate = request["candidate_population"]; target = request["primary_target"]; dep = request["stage1_dependency"]

    # The scientific feature surface must be authored explicitly in the intake as an
    # ordered list of exact FeatureInstances. feature_candidate.yaml is a capability
    # authority, not this surface -- deriving instances from it would guess the study.
    policy = request.get("feature_policy") or {}
    surface = (request.get("feature_surface") or request.get("feature_instances")
               or policy.get("feature_surface") or policy.get("feature_instances"))
    if not isinstance(surface, list) or not surface:
        concept_hints = sorted(set((policy.get("families") or {}).keys()) | set(policy.get("requested_new_concepts") or []))
        return _UnresolvedFeatureSurface(
            reason="FEATURE_SURFACE_NOT_AUTHORED",
            detail=(
                "The approved intake specifies feature families/concepts but no exact ordered "
                "FeatureInstance surface. Author `feature_surface:` (list of {feature, parameters}) "
                "in research_decision.yaml; the compiler will not infer it from capability authorities."
            ),
            target_count_range=[policy.get("target_count_min"), policy.get("target_count_max")],
            unresolved_concepts=concept_hints,
        )
    instances = []
    for item in surface:
        instances.append({"feature": str(item["feature"]), "parameters": dict(item.get("parameters", {}))})
    target_id = target["id"]
    life = {"arm_condition": {"threshold_atr": candidate["pullback_gate_atr"], "price_source": "completed_1s_intrabar"},
            "required_event": {"source": "generic_completed_5s_regime_state", "bar_state": "completed", "availability_timestamp": "completed_source_bar_ts_init", "relation": "opposite_prevailing", "active_at_arm_counts": True},
            "emit_condition": {"source": "generic_completed_5s_regime_state", "bar_state": "completed", "availability_timestamp": "completed_source_bar_ts_init", "from_relation": "opposite_prevailing", "to_relation": "aligned_prevailing", "strictly_after_arm": True},
            "rearm_on": ["new_favorable_extreme"], "terminate_on": ["prevailing_regime_flip"], "max_candidates_per_episode": candidate["candidates_per_episode"]}
    derived = {"name": "frozen_model_c_score", "kind": "frozen_external_model_score", "parent_study_id": dep["parent_study_id"],
        "parent_train_freeze_artifact": dep["parent_train_freeze_artifact"], "parent_train_freeze_artifact_sha256": dep["parent_train_freeze_artifact_sha256"],
        "parent_frozen_execution_composite_sha256": dep["parent_frozen_execution_composite_sha256"], "model_hashes": dep["model_hashes"],
        "preprocessing_hash": dep["preprocessing_sha256"], "ordered_feature_surfaces": {"MODEL_C": dep["ordered_model_c_feature_surface"]},
        "availability_reference": dep["candidate_score"]["availability_reference"], "retrain_prohibited": True}
    proto = request["model"].get("proposed_inner_train_chronology", {})
    return {"study": {"id": study.name, "type": "flip_prediction", "description": request["research_question"]},
        "instrument": {"symbol": request["instrument"]["symbol"], "venue": request["instrument"].get("venue", "XCME")},
        "population": {"type": "regime_state", "session": "RTH", "episode_lifecycle": life},
        "target": {"type": "composite", "decision_reference": "decision_ts", "conditions": [{"id": "ordered_continuation", "kind": "ordered_barrier", "forward_outcome_id": target_id, "barrier_id": target_id}],
                   "required_forward_outcomes": [{"id": target_id, "entry_reference": "next_bar_open", "horizon_seconds": target["horizon_seconds"], "max_tracking_seconds": target["horizon_seconds"], "excursion_units": ["atr"], "bar_inclusion": "fully_forward", "session_end_censoring": True, "max_gap_seconds": 1, "atr_source": request["target_atr"]["source"], "atr_frozen_at": request["target_atr"]["frozen_at"], "ordered_barriers": [{"id": target_id, "favorable_atr": target["favorable_barrier_atr"], "adverse_atr": target["adverse_barrier_atr"], "horizon_seconds": target["horizon_seconds"]}]}]},
        # mode "none" == no selection: the ordered `instances` list IS the final surface,
        # so feature_count is exactly its length (not the schema's 25-feature default).
        # metadata_columns = the candidate key only: this episode-population study persists
        # no extra runtime observables on the candidates frame (episode/barrier bookkeeping
        # lives on the observations frame). Matches clean_tradable_reversal's contract and
        # keeps the collector's emitted set == OutputManager's declared set.
        "features": {"source": "canonical_verified_definition_universe", "instances": instances, "derived_inputs": [derived],
                     "metadata_columns": ["observation_ts", "regime_start_ns", "checkpoint_index"],
                     "selection": {"mode": "none", "source": "canonical_verified_definition_universe",
                                   "feature_count": len(instances), "direction_specific": False}},
        "model": {"family": request["model"]["allowed_family"], "arms": ["BROAD"], "selection": {"search_method": "none", "allowed_families": [{"family": request["model"]["allowed_family"]}], "tuning_years": proto.get("selection_fit_years", []) + proto.get("selection_validation_years", []), "final_train_validation_years": proto.get("final_train_validation_years", [])}},
        "chronology": request["chronology"],
        "execution": {"runtime": "nautilustrader", "strategy_class": "research_workflow.generic_collector.GenericStudyCollector",
                      "data_requirements": {"dataset_id": request["instrument"]["dataset_id"]}},
        "required_gates": [{"id": "population_target_gate", "stage": "pre_fit", "artifact_path": "artifacts/population_target_gate.json", "artifact_schema_version": 1, "scope_fields": ["population", "target", "chronology"]}]}


def compile_approved_request(study: str | Path, *, write: bool = True) -> dict[str, Any]:
    """Compile a complete approved request and return machine-readable resolution data."""
    study = Path(study).resolve()
    request_path = study / "research_decision.yaml"
    if not request_path.exists():
        return {"ok": False, "terminal": "SEMANTIC_DECISION_REQUIRED", "resolutions": {
            "research_decision": FieldResolution.SEMANTIC_DECISION_REQUIRED.value}}
    request = _load(request_path)
    supplied = request.get("study_spec") or request.get("study_yaml")
    spec_data = supplied if isinstance(supplied, dict) else (_projection(request, study.name) or _deep_pullback_projection(request, study))
    if isinstance(spec_data, _UnresolvedFeatureSurface):
        return {"ok": False, "terminal": "SEMANTIC_DECISION_REQUIRED",
                "resolutions": {"features.instances": FieldResolution.SEMANTIC_DECISION_REQUIRED.value},
                "detail": spec_data.get("detail"),
                "unresolved": {k: v for k, v in spec_data.items() if k != "detail"}}
    if spec_data is None:
        return {"ok": False, "terminal": "SEMANTIC_DECISION_REQUIRED", "resolutions": {
            "study_spec": FieldResolution.SEMANTIC_DECISION_REQUIRED.value},
            "detail": "Approved request has no complete machine-readable StudySpec projection."}
    if spec_data.get("study", {}).get("id") not in (None, study.name):
        return {"ok": False, "terminal": "AUTHORITY_CONFLICT", "resolutions": {
            "study.id": FieldResolution.AUTHORITY_CONFLICT.value}}
    spec_data.setdefault("study", {})["id"] = study.name
    try:
        from research.schemas.study_spec import StudySpec
        spec = StudySpec.model_validate(spec_data)
    except Exception as exc:
        return {"ok": False, "terminal": "SEMANTIC_DECISION_REQUIRED", "resolutions": {
            "study_spec": FieldResolution.SEMANTIC_DECISION_REQUIRED.value}, "detail": str(exc)}
    resolutions = {"research_decision": FieldResolution.RESOLVED_EXPLICITLY.value,
                   "study.id": FieldResolution.RESOLVED_EXPLICITLY.value,
                   "execution.runtime": FieldResolution.RESOLVED_FROM_ALLOWED_DEFAULT.value}
    if not supplied and request.get("stage1_dependency"):
        resolutions["candidate_population"] = FieldResolution.RESOLVED_EXPLICITLY.value
        resolutions["primary_target"] = FieldResolution.RESOLVED_EXPLICITLY.value
        # The feature surface is resolved from the intake's explicit `feature_surface`
        # list (per-instance RESOLVED_EXPLICITLY below), never from a capability authority.
        resolutions["model_c_derived_input"] = FieldResolution.RESOLVED_FROM_FROZEN_LINEAGE.value
    for item in (spec.features.instances if spec.features else []) or []:
        item_data = item.model_dump() if hasattr(item, "model_dump") else item
        resolutions[f"feature:{item_data.get('feature', '?')}"] = FieldResolution.RESOLVED_EXPLICITLY.value
    for item in (spec.features.derived_inputs if spec.features else []) or []:
        resolutions[f"derived:{item.name}"] = FieldResolution.RESOLVED_FROM_FROZEN_LINEAGE.value
    if write:
        study.mkdir(parents=True, exist_ok=True)
        from research_workflow.study_factory import materialize_compiled_study
        materialize_compiled_study(spec, study, write_study_yaml=True)
        (study / "artifacts").mkdir(exist_ok=True)
        (study / "artifacts" / "study_spec_compilation.json").write_text(json.dumps({"request_sha256": _sha(request_path), "feature_candidate_semantics_sha256": _sha(study / "feature_candidate.yaml"), "resolutions": resolutions, "spec_sha256": spec.compute_sha256()}, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "spec_sha256": spec.compute_sha256(), "resolutions": resolutions,
            "request_sha256": _sha(request_path), "study_yaml": str(study / "study.yaml")}

"""Feature Binding and Validation Engine.
========================================
Resolves requested features against canonical features.registry,
enforces SHA-256 hash pinning, and compiles the feature contract JSON.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from research.schemas.study_spec import FeaturesSpec


class FeatureBindingError(ValueError):
    """Raised when feature resolution or verification fails."""
    pass


def compute_feature_list_sha256(features: List[str]) -> str:
    """Computes deterministic SHA-256 hash of ordered feature names."""
    content = json.dumps(features, indent=None)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compile_feature_contract(features_spec: Optional[FeaturesSpec]) -> Dict[str, Any]:
    """Resolves and validates features against the central feature registry.

    Returns
    -------
    Dict[str, Any]
        Authoritative feature contract dictionary.
    """
    # Check forbidden lineage
    if features_spec and features_spec.forbidden_lineage:
        forbidden = set(features_spec.forbidden_lineage)
        source_key = features_spec.source_key or ""
        if source_key in forbidden:
            raise FeatureBindingError(
                f"FORBIDDEN_FEATURE_LINEAGE: Study requires fresh feature selection but specifies "
                f"forbidden source_key='{source_key}' (forbidden: {sorted(list(forbidden))})"
            )
        if "F3_selected" in forbidden and "F3" in source_key:
            raise FeatureBindingError(
                f"FORBIDDEN_FEATURE_LINEAGE: Study forbids prior F3 feature inheritance, "
                f"but found source_key='{source_key}'"
            )

    if not features_spec or (not features_spec.feature_list and not features_spec.instances and not features_spec.selection):
        return {
            "source_key": getattr(features_spec, "source_key", None) if features_spec else None,
            "feature_count": 0,
            "feature_list": [],
            "feature_list_sha256": None,
            "bound_trackers": [],
            "timing_contract": "verified",
            "derived_causal_inputs": _compile_derived_causal_inputs(features_spec),
        }

    # Handle unselected candidate universe mode (e.g. verified_registry_numeric_universe)
    if features_spec.selection and features_spec.selection.mode == "train_only" and not features_spec.feature_list and not features_spec.instances:
        try:
            from features.registry import resolve_source_universe
        except ImportError as e:
            raise FeatureBindingError(f"Unable to import features.registry: {e}")

        # One canonical resolver; compiler must not recreate a local status/dtype/
        # implementation predicate that can drift from runtime collection.
        source = features_spec.selection.source
        if source == "verified_registry_numeric_universe":
            raise FeatureBindingError(
                "LEGACY_FEATURE_ALIAS_NOT_ALLOWED: declare canonical_verified_definition_universe "
                "and canonical FeatureInstances for new studies"
            )
        verified_feats = resolve_source_universe(source)
        return {
            "source_universe": source,
            "selection_mode": "train_only",
            "selection_years": features_spec.selection.years or [],
            "feature_count": features_spec.selection.feature_count,
            "direction_specific": features_spec.selection.direction_specific,
            "ranking_method": features_spec.selection.ranking_method,
            "candidate_universe_count": len(verified_feats),
            "candidate_universe_hash": hashlib.sha256(json.dumps(verified_feats).encode("utf-8")).hexdigest(),
            "timing_contract": "verified",
            "derived_causal_inputs": _compile_derived_causal_inputs(features_spec),
        }

    # Resolve every requested output name through the single canonical feature
    # authority.  A physical alias is compatibility/output vocabulary, never a
    # registry identity owned by this compiler.
    try:
        from features.registry import resolve_feature_request
    except ImportError as e:
        raise FeatureBindingError(f"Unable to import features.registry: {e}")

    instance_requests = list(features_spec.instances or [])
    if features_spec.feature_list and instance_requests:
        raise FeatureBindingError("FEATURE_LIST_AND_INSTANCES_CONFLICT: choose aliases or canonical instances")
    try:
        instance_aliases = [resolve_feature_request(
            str(item["feature"]), item.get("parameters", {}),
            physical_alias=item.get("physical_alias"),
        )["physical_alias"] for item in instance_requests]
    except KeyError as exc:
        raise FeatureBindingError(f"INVALID_FEATURE_INSTANCE: missing {exc.args[0]!r}") from exc
    except Exception as exc:
        raise FeatureBindingError(f"INVALID_FEATURE_INSTANCE: {exc}") from exc
    feature_list = list(features_spec.feature_list or instance_aliases)
    computed_hash = compute_feature_list_sha256(feature_list)

    # Hash verification if pinned in spec
    if features_spec.feature_list_sha256:
        if features_spec.feature_list_sha256 != computed_hash:
            raise FeatureBindingError(
                f"FEATURE_LIST_HASH_DRIFT: Spec declared sha256='{features_spec.feature_list_sha256}', "
                f"but computed sha256='{computed_hash}' for {len(feature_list)} features"
            )

    # Validate all features against the selected authority.
    unregistered: List[str] = []
    bound_trackers: set = set()
    families: set = set()
    timeframes: set = set()
    # An explicit feature_list bypasses the verified-universe filter above, so the
    # lifecycle status of each named feature is recorded here. Without it a contract can
    # name a `provisional` feature while the study's `features.source` claims a verified
    # universe, and nothing in the compiled artifacts contradicts the claim.
    feature_statuses: Dict[str, str] = {}
    null_policies: Dict[str, str] = {}

    resolved_instances: List[Dict[str, Any]] = []
    instance_by_alias = {
        resolve_feature_request(str(item["feature"]), item.get("parameters", {}),
                                physical_alias=item.get("physical_alias"))["physical_alias"]: item
        for item in instance_requests
    }
    for name in feature_list:
        try:
            # Preserve an explicitly declared compatibility/output alias only
            # as the instance's physical output name; canonical identity and
            # validation remain parameter-driven.
            item_for_name = instance_by_alias.get(name)
            resolved = resolve_feature_request(
                (item_for_name or {}).get("feature", name),
                (item_for_name or {}).get("parameters", {}) if item_for_name else {},
                physical_alias=(item_for_name or {}).get("physical_alias") if item_for_name else None,
            )
        except Exception:
            unregistered.append(name)
            continue
        if resolved["provider"]:
            bound_trackers.add(resolved["provider"])
        if resolved["family"]:
            families.add(str(resolved["family"]))
        for stream in resolved["input_requirements"].get("required_streams", []):
            timeframes.add(stream)
        feature_statuses[name] = str(resolved["status"])
        # Canonical candidate records preserve the existing allow/null
        # contract through the parity matrix; compiler records the resolved
        # contract without inspecting a legacy registry entry.
        null_policies[name] = "allow"
        resolved_instances.append({
            "requested": name,
            "canonical_name": resolved["canonical_name"],
            "parameters": resolved["parameters"],
            "physical_alias": resolved["physical_alias"],
        })

    if unregistered:
        raise FeatureBindingError(
            f"FEATURE_NOT_REGISTERED: {len(unregistered)} features missing from central registry: "
            f"{unregistered[:5]}{'...' if len(unregistered) > 5 else ''}"
        )

    contract = {
        "source_key": features_spec.source_key,
        "feature_count": len(feature_list),
        "feature_list": feature_list,
        "resolved_feature_instances": resolved_instances,
        "feature_list_sha256": computed_hash,
        "bound_trackers": sorted(list(bound_trackers)),
        "families": sorted(list(families)),
        "source_timeframes": sorted(list(timeframes)),
        "feature_statuses": feature_statuses,
        "feature_null_policies": null_policies,
        "contains_provisional_features": sorted(
            n for n, s in feature_statuses.items() if s != "verified"
        ),
        "directional_mapping": features_spec.directional_mapping or "direction_normalized",
        "timing_contract": features_spec.timing_contract or "verified",
    }
    # Explicit instances are the execution surface, while train-only
    # selection still needs the canonical candidate universe for ranking. Keep
    # both facts in the compiled contract without reverting to alias-driven
    # instance inference.
    if features_spec.selection and features_spec.selection.mode == "train_only":
        from features.registry import resolve_source_universe
        candidate = resolve_source_universe(features_spec.selection.source)
        contract["source_universe"] = features_spec.selection.source
        contract["candidate_universe_count"] = len(candidate)
        contract["candidate_universe_hash"] = hashlib.sha256(
            json.dumps(candidate).encode("utf-8")
        ).hexdigest()
    from features.registry import derive_study_feature_requirements
    contract["runtime_data_requirements"] = derive_study_feature_requirements(features_spec)
    contract["derived_causal_inputs"] = _compile_derived_causal_inputs(features_spec)
    return contract


def _compile_derived_causal_inputs(features_spec: Optional[FeaturesSpec]) -> List[Dict[str, Any]]:
    """Structurally separate from ``resolved_feature_instances``/``feature_list``.

    Never resolvable through ``features.registry`` -- a derived causal input is not a
    canonical market ``FeatureInstance`` and must not be absorbed by the feature
    promotion path. Provenance verification against the declared upstream freeze
    (``research_workflow.derived_inputs.verify_derived_causal_inputs``) happens at
    PREPARE time, not here -- the compiler records the declaration; phase0 authenticates it.
    """
    derived = (features_spec.derived_inputs if features_spec else None) or []
    return [
        {
            "name": d.name,
            "kind": d.kind,
            "parent_study_id": d.parent_study_id,
            "parent_train_freeze_artifact": d.parent_train_freeze_artifact,
            "parent_train_freeze_artifact_sha256": d.parent_train_freeze_artifact_sha256,
            "parent_frozen_execution_composite_sha256": d.parent_frozen_execution_composite_sha256,
            "model_hashes": dict(d.model_hashes),
            "preprocessing_hash": d.preprocessing_hash,
            "score_artifact_path": d.score_artifact_path,
            "score_artifact_sha256": d.score_artifact_sha256,
            "availability_reference": d.availability_reference,
            "retrain_prohibited": d.retrain_prohibited,
        }
        for d in derived
    ]

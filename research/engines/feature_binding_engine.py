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

    if not features_spec or (not features_spec.feature_list and not features_spec.selection):
        return {
            "source_key": getattr(features_spec, "source_key", None) if features_spec else None,
            "feature_count": 0,
            "feature_list": [],
            "feature_list_sha256": None,
            "bound_trackers": [],
            "timing_contract": "verified",
        }

    # Handle unselected candidate universe mode (e.g. verified_registry_numeric_universe)
    if features_spec.selection and features_spec.selection.mode == "train_only" and not features_spec.feature_list:
        try:
            from features.registry import FEATURE_REGISTRY
        except ImportError as e:
            raise FeatureBindingError(f"Unable to import features.registry: {e}")

        # Catalog verified numeric features from registry
        verified_feats = [
            k for k, v in sorted(FEATURE_REGISTRY.items())
            if v.status == "verified" and v.dtype in ("float64", "int64", "float32", "int32")
        ]
        return {
            "source_universe": features_spec.selection.source,
            "selection_mode": "train_only",
            "selection_years": features_spec.selection.years or [],
            "feature_count": features_spec.selection.feature_count,
            "direction_specific": features_spec.selection.direction_specific,
            "ranking_method": features_spec.selection.ranking_method,
            "candidate_universe_count": len(verified_feats),
            "candidate_universe_hash": hashlib.sha256(json.dumps(verified_feats).encode("utf-8")).hexdigest(),
            "timing_contract": "verified",
        }

    # Import central registry
    try:
        from features.registry import FEATURE_REGISTRY
    except ImportError as e:
        raise FeatureBindingError(f"Unable to import features.registry: {e}")

    feature_list = features_spec.feature_list
    computed_hash = compute_feature_list_sha256(feature_list)

    # Hash verification if pinned in spec
    if features_spec.feature_list_sha256:
        if features_spec.feature_list_sha256 != computed_hash:
            raise FeatureBindingError(
                f"FEATURE_LIST_HASH_DRIFT: Spec declared sha256='{features_spec.feature_list_sha256}', "
                f"but computed sha256='{computed_hash}' for {len(feature_list)} features"
            )

    # Validate all features against registry
    unregistered: List[str] = []
    bound_trackers: set = set()
    families: set = set()
    timeframes: set = set()

    for name in feature_list:
        if name not in FEATURE_REGISTRY:
            unregistered.append(name)
        else:
            feat_def = FEATURE_REGISTRY[name]
            if feat_def.implementation:
                bound_trackers.add(feat_def.implementation)
            if feat_def.family:
                families.add(feat_def.family)
            if feat_def.source_timeframe:
                timeframes.add(feat_def.source_timeframe)

    if unregistered:
        raise FeatureBindingError(
            f"FEATURE_NOT_REGISTERED: {len(unregistered)} features missing from central registry: "
            f"{unregistered[:5]}{'...' if len(unregistered) > 5 else ''}"
        )

    contract = {
        "source_key": features_spec.source_key,
        "feature_count": len(feature_list),
        "feature_list": feature_list,
        "feature_list_sha256": computed_hash,
        "bound_trackers": sorted(list(bound_trackers)),
        "families": sorted(list(families)),
        "source_timeframes": sorted(list(timeframes)),
        "directional_mapping": features_spec.directional_mapping or "direction_normalized",
        "timing_contract": features_spec.timing_contract or "verified",
    }
    return contract

"""Legacy physical instance aliases: historical spellings of canonical instances.

Registered through ``research_workflow/capabilities_index.d/feature_definitions.yaml``
and merged by ``features.registry``; nothing imports this module by name.
"""
from typing import Dict

from features.feature_types import FeatureInstance

# The 35 existing physical aliases are deliberately a small compatibility map, not an
# instance registry.  New aliases are generated deterministically below; these preserve
# historical parquet/model contracts whose legacy spelling uses 5m for a 300s window.
LEGACY_FEATURE_INSTANCE_OVERRIDES: Dict[str, FeatureInstance] = {}
for _metric in (
    "duration_min", "range_atr", "net_directional_move_atr", "mfe_atr",
    "range_atr_per_min", "net_move_atr_per_min", "efficiency",
):
    for _tf in ("1m", "5m"):
        _alias = f"prior_{_tf}_regime_{_metric}"
        LEGACY_FEATURE_INSTANCE_OVERRIDES[_alias] = FeatureInstance(
            f"regime_{_metric}", {"timeframe": _tf, "context": "prior", "bar_state": "completed"}, _alias,
        )
LEGACY_FEATURE_INSTANCE_OVERRIDES.update({
    "current_5m_regime_age_min": FeatureInstance("regime_age_min", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_regime_range_atr": FeatureInstance("regime_range_atr", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_regime_mfe_atr": FeatureInstance("regime_mfe_atr", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_directional_displacement_atr": FeatureInstance("regime_directional_displacement_atr", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_regime_range_atr_per_min": FeatureInstance("regime_range_atr_per_min", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "distance_to_completed_5m_high_atr": FeatureInstance("distance_to_completed_range_high_atr", {"reference_timeframe": "5m", "bar_state": "completed"}),
    "distance_to_completed_5m_low_atr": FeatureInstance("distance_to_completed_range_low_atr", {"reference_timeframe": "5m", "bar_state": "completed"}),
    "current_1m_move_outside_completed_5m_range": FeatureInstance("move_outside_completed_range", {"source_timeframe": "1m", "reference_timeframe": "5m", "context": "current", "source_bar_state": "completed", "reference_bar_state": "completed"}),
})
for _name in (
    "structural_max_expansion_atr", "structural_current_expansion_atr",
    "structural_giveback_atr", "structural_retention_ratio",
    "structural_expansion_atr_per_min", "regime_expansion_atr_per_min",
):
    LEGACY_FEATURE_INSTANCE_OVERRIDES[_name] = FeatureInstance(_name, {"context": "current"}, _name)
for _suffix in (
    "max_progress_atr", "current_progress_atr", "giveback_atr", "retention_ratio",
    "max_speed_atr_per_min", "current_speed_atr_per_min", "max_speed_vs_lifetime",
    "current_speed_vs_lifetime",
):
    _alias = f"rolling_5m_{_suffix}"
    LEGACY_FEATURE_INSTANCE_OVERRIDES[_alias] = FeatureInstance(
        f"rolling_{_suffix}", {"window": "300s", "update_every": "1s"}, _alias,
    )

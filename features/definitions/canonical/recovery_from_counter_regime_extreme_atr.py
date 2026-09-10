"""Canonical feature definition record: ``recovery_from_counter_regime_extreme_atr``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

DEFINITION = FeatureDefinition(
    name='recovery_from_counter_regime_extreme_atr',
    status='provisional',
    family='counter_regime_geometry',
    source_timeframe='5s',
    update_anchor='completed_5s_regime_flip',
    null_policy='allow',
    implementation='features.trackers.generic_regime_geometry.GenericCompletedRegimeGeometryProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('timeframe',),
    supported_timeframes=('5s',),
    supported_parameter_values={
        'timeframe': ('5s',),
    },
    required_parameters=('timeframe',),
    coverage_family='counter_regime_geometry',
)

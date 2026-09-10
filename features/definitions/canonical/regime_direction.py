"""Canonical feature definition record: ``regime_direction``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

DEFINITION = FeatureDefinition(
    name='regime_direction',
    status='provisional',
    family='completed_regime_context',
    source_timeframe='5m',
    update_anchor='completed_5m_bar',
    normalizer='none',
    null_policy='allow',
    implementation='features.trackers.generic_regime_geometry.GenericCompletedRegimeGeometryProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('timeframe', 'context', 'bar_state'),
    supported_timeframes=('5m',),
    supported_parameter_values={
        'timeframe': ('5m',),
        'context': ('current',),
        'bar_state': ('completed',),
    },
    required_parameters=('timeframe', 'context', 'bar_state'),
    supported_parameter_combinations=(
        {
            'timeframe': '5m',
            'context': 'current',
            'bar_state': 'completed',
        },
    ),
    coverage_family='completed_regime_context',
)

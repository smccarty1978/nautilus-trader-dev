"""Canonical feature definition record: ``prior_deep_pullback_count``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

DEFINITION = FeatureDefinition(
    name='prior_deep_pullback_count',
    status='provisional',
    family='pullback_sequence_maturity',
    source_timeframe='1s+1m',
    update_anchor='completed_1s_at_candidate',
    null_policy='allow',
    implementation='features.trackers.generic_episode_geometry.GenericEpisodeGeometryProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('timeframe', 'context', 'bar_state', 'threshold_atr'),
    supported_timeframes=('1m',),
    supported_parameter_values={
        'timeframe': ('1m',),
        'context': ('current',),
        'bar_state': ('completed',),
        'threshold_atr': (
            1.0,
        ),
    },
    required_parameters=('timeframe', 'context', 'bar_state', 'threshold_atr'),
    supported_parameter_combinations=(
        {
            'timeframe': '1m',
            'context': 'current',
            'bar_state': 'completed',
            'threshold_atr': 1.0,
        },
    ),
    coverage_family='pullback_sequence_maturity',
)

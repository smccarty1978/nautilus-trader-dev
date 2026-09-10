"""Canonical feature definition record: ``seconds_since_prevailing_directional_extreme``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

DEFINITION = FeatureDefinition(
    name='seconds_since_prevailing_directional_extreme',
    status='provisional',
    family='pullback_sequence_maturity',
    source_timeframe='1s+1m',
    update_anchor='completed_1s_at_candidate',
    null_policy='allow',
    implementation='features.trackers.generic_episode_geometry.GenericEpisodeGeometryProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('timeframe', 'context', 'bar_state'),
    supported_timeframes=('1m',),
    supported_parameter_values={
        'timeframe': ('1m',),
        'context': ('current',),
        'bar_state': ('completed',),
        'threshold_atr': (
            1.0,
        ),
    },
    required_parameters=('timeframe', 'context', 'bar_state'),
    supported_parameter_combinations=(
        {
            'timeframe': '1m',
            'context': 'current',
            'bar_state': 'completed',
        },
    ),
    coverage_family='pullback_sequence_maturity',
)

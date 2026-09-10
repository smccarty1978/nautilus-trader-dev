"""Canonical feature definition record: ``regime_net_move_atr_per_min``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition
from features.definitions.providers import STRUCTURAL_IMPL, STRUCTURAL_TESTS

DEFINITION = FeatureDefinition(
    name='regime_net_move_atr_per_min',
    status='provisional',
    family='structural_regime_geometry',
    source_timeframe='1s+1m+5m',
    update_anchor='completed_1s_completed_5m_then_1m_flip',
    null_policy='allow',
    implementation=STRUCTURAL_IMPL,
    tests=STRUCTURAL_TESTS,
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('timeframe', 'context', 'regime', 'bar_state'),
    supported_timeframes=('1m', '5m', '5s'),
    supported_parameter_values={
        'timeframe': ('1m', '5m', '5s'),
        'bar_state': ('completed',),
        'regime': (),
    },
    required_parameters=('timeframe', 'context'),
    supported_parameter_combinations=(
        {
            'timeframe': '1m',
            'context': 'prior',
            'bar_state': 'completed',
        },
        {
            'timeframe': '5m',
            'context': 'prior',
            'bar_state': 'completed',
        },
        {
            'timeframe': '5s',
            'context': 'prior',
            'bar_state': 'completed',
        },
    ),
    coverage_family='structural_regime_geometry',
)

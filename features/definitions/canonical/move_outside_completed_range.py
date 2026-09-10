"""Canonical feature definition record: ``move_outside_completed_range``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition
from features.definitions.providers import STRUCTURAL_IMPL, STRUCTURAL_TESTS

DEFINITION = FeatureDefinition(
    name='move_outside_completed_range',
    status='provisional',
    family='structural_regime_geometry',
    source_timeframe='1s+1m+5m',
    update_anchor='completed_1s_completed_5m_then_1m_flip',
    null_policy='allow',
    implementation=STRUCTURAL_IMPL,
    tests=STRUCTURAL_TESTS,
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('source_timeframe', 'reference_timeframe', 'context', 'source_bar_state', 'reference_bar_state'),
    supported_timeframes=('1m', '5m', '5s'),
    supported_parameter_values={
        'source_timeframe': ('1m',),
        'reference_timeframe': ('5m',),
        'context': ('current',),
        'source_bar_state': ('completed',),
        'reference_bar_state': ('completed',),
    },
    required_parameters=('source_timeframe', 'reference_timeframe', 'context'),
    supported_parameter_combinations=(
        {
            'source_timeframe': '1m',
            'reference_timeframe': '5m',
            'context': 'current',
            'source_bar_state': 'completed',
            'reference_bar_state': 'completed',
        },
    ),
    coverage_family='structural_regime_geometry',
)

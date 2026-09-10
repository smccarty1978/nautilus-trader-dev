"""Canonical feature definition record: ``structural_expansion_atr_per_min``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition
from features.definitions.providers import STRUCTURAL_IMPL, STRUCTURAL_TESTS

DEFINITION = FeatureDefinition(
    name='structural_expansion_atr_per_min',
    status='provisional',
    family='structural_regime_geometry',
    source_timeframe='1s+1m+5m',
    update_anchor='completed_1s_completed_5m_then_1m_flip',
    null_policy='allow',
    implementation=STRUCTURAL_IMPL,
    tests=STRUCTURAL_TESTS,
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('context',),
    supported_timeframes=('1m', '5m', '5s'),
    supported_parameter_values={
        'context': ('current',),
    },
    required_parameters=('context',),
    supported_parameter_combinations=(
        {
            'context': 'current',
        },
    ),
    coverage_family='structural_regime_geometry',
)

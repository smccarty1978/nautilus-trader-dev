"""Canonical feature definition record: ``rolling_current_speed_atr_per_min``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition
from features.definitions.providers import ROLLING_PRODUCTIVITY_IMPL, ROLLING_PRODUCTIVITY_TESTS

DEFINITION = FeatureDefinition(
    name='rolling_current_speed_atr_per_min',
    status='provisional',
    family='rolling_productivity',
    update_anchor='completed_1s_at_or_before_checkpoint',
    normalizer='current_1m_regime_start_atr',
    null_policy='allow',
    implementation=ROLLING_PRODUCTIVITY_IMPL,
    tests=ROLLING_PRODUCTIVITY_TESTS,
    window_unit='seconds',
    parameter_schema=('window', 'update_every'),
    supported_update_every=('1s',),
    supported_parameter_values={
        'update_every': ('1s',),
    },
    required_parameters=('window', 'update_every'),
    coverage_family='rolling_productivity',
)

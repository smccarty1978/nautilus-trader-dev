"""Canonical feature definition record: ``trend_normalized_est_delta_sum``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

# Window support is a declaration, not an implementation limit: GenericOHLCVDeltaProvider builds whatever
# trailing windows its instances ask for. 30s was once undeclared and a study asking for it got
# INVALID_PARAMETERIZATION for a window the runtime could always produce.
DEFINITION = FeatureDefinition(
    name='trend_normalized_est_delta_sum',
    status='provisional',
    family='direction_normalized_ohlcv_est_delta',
    update_anchor='completed_1s_at_checkpoint',
    null_policy='allow',
    implementation='features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='seconds',
    parameter_schema=('window', 'update_every', 'direction_reference'),
    supported_update_every=('1s',),
    supported_parameter_values={
        'window': ('5s', '30s', '60s', '300s'),
        'numerator_window': ('5s', '30s', '60s'),
        'denominator_window': ('300s',),
        'short_window': ('5s', '30s', '60s'),
        'update_every': ('1s',),
        'direction_reference': ('prevailing_1m',),
    },
    required_parameters=('window', 'update_every', 'direction_reference'),
    coverage_family='direction_normalized_ohlcv_est_delta',
)

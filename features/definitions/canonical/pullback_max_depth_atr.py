"""Canonical feature definition record: ``pullback_max_depth_atr``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.
"""
from features.feature_types import FeatureDefinition

DEFINITION = FeatureDefinition(
    name='pullback_max_depth_atr',
    status='provisional',
    family='pullback_episode_geometry',
    update_anchor='completed_1s_at_candidate',
    null_policy='allow',
    implementation='features.trackers.generic_episode_geometry.GenericEpisodeGeometryProvider',
    tests=('features/tests/test_generic_episode_geometry.py',),
    window_unit='events',
    reset_policy='episode',
    parameter_schema=('scope', 'extreme_source'),
    supported_parameter_values={
        'scope': ('current_deep_pullback_episode',),
        'extreme_source': ('prevailing_directional_extreme',),
    },
    required_parameters=('scope', 'extreme_source'),
    coverage_family='pullback_episode_geometry',
)

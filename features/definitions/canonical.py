"""Canonical feature definitions -- the V2 lifecycle/promotion authority.

Registered through ``research_workflow/capabilities_index.d/feature_definitions.yaml``
and merged by ``features.registry``; nothing imports this module by name.
"""
from typing import Any, Dict, Mapping, Optional, Tuple

from features.feature_types import FeatureDefinition
from features.definitions.providers import (ROLLING_PRODUCTIVITY_IMPL as _ROLLING_PRODUCTIVITY_IMPL,
                                            ROLLING_PRODUCTIVITY_TESTS as _ROLLING_PRODUCTIVITY_TESTS,
                                            STRUCTURAL_IMPL as _STRUCTURAL_IMPL,
                                            STRUCTURAL_TESTS as _STRUCTURAL_TESTS)

def _canonical_definition(
    name: str, *, family: str, implementation: str, tests: Tuple[str, ...],
    parameters: Tuple[str, ...], source_timeframe: str, update_anchor: str,
    normalizer: str, window_unit: Optional[str], reset_policy: str,
    null_policy: str = "allow", supported_timeframes: Tuple[str, ...] = (),
    supported_update_every: Tuple[str, ...] = (),
    supported_parameter_values: Optional[Mapping[str, Tuple[Any, ...]]] = None,
    required_parameters: Tuple[str, ...] = (),
    supported_parameter_combinations: Tuple[Mapping[str, Any], ...] = (),
) -> FeatureDefinition:
    return FeatureDefinition(
        name=name, status="provisional", family=family, implementation=implementation,
        tests=tests, source_timeframe=source_timeframe, update_anchor=update_anchor,
        normalizer=normalizer, window_unit=window_unit, reset_policy=reset_policy,
        null_policy=null_policy, parameter_schema=parameters, coverage_family=family,
        supported_timeframes=supported_timeframes, supported_update_every=supported_update_every,
        supported_parameter_values=dict(supported_parameter_values or {}),
        required_parameters=required_parameters,
        supported_parameter_combinations=tuple(dict(item) for item in supported_parameter_combinations),
    )


CANONICAL_FEATURE_DEFINITIONS: Dict[str, FeatureDefinition] = {}
for _name in (
    "regime_duration_min", "regime_range_atr", "regime_net_directional_move_atr",
    "regime_mfe_atr", "regime_range_atr_per_min", "regime_net_move_atr_per_min",
    "regime_efficiency", "regime_age_min", "regime_directional_displacement_atr",
    "distance_to_completed_range_high_atr", "distance_to_completed_range_low_atr",
    "move_outside_completed_range", "structural_max_expansion_atr",
    "structural_current_expansion_atr", "structural_giveback_atr",
    "structural_retention_ratio", "structural_expansion_atr_per_min",
    "regime_expansion_atr_per_min",
):
    _params = ("timeframe", "context", "regime", "bar_state")
    if _name.startswith("distance_to_completed_range"):
        _params = ("reference_timeframe", "bar_state")
    elif _name == "move_outside_completed_range":
        _params = ("source_timeframe", "reference_timeframe", "context", "source_bar_state", "reference_bar_state")
    elif _name.startswith("structural_") or _name == "regime_expansion_atr_per_min":
        _params = ("context",)
    _value_domain: Mapping[str, Tuple[Any, ...]] = {"bar_state": ("completed",)}
    _required: Tuple[str, ...] = ("timeframe", "context")
    _combinations: Tuple[Mapping[str, Any], ...] = (
        {"timeframe": "1m", "context": "prior", "bar_state": "completed"},
        {"timeframe": "5m", "context": "prior", "bar_state": "completed"},
    )
    if _name.startswith("distance_to_completed_range"):
        _value_domain = {"reference_timeframe": ("5m",), "bar_state": ("completed",)}
        _required = ("reference_timeframe",)
        _combinations = ({"reference_timeframe": "5m", "bar_state": "completed"},)
    elif _name == "move_outside_completed_range":
        _value_domain = {"source_timeframe": ("1m",), "reference_timeframe": ("5m",),
                         "context": ("current",), "source_bar_state": ("completed",),
                         "reference_bar_state": ("completed",)}
        _required = ("source_timeframe", "reference_timeframe", "context")
        _combinations = ({"source_timeframe": "1m", "reference_timeframe": "5m", "context": "current",
                          "source_bar_state": "completed", "reference_bar_state": "completed"},)
    elif _name.startswith("structural_") or _name == "regime_expansion_atr_per_min":
        _value_domain = {"context": ("current",)}
        _required = ("context",)
        _combinations = ({"context": "current"},)
    else:
        # ``regime`` remains in the historical schema for promotion-record
        # compatibility, but no active completed-bar provider consumes it;
        # an empty domain makes every supplied value fail closed.
        _value_domain = {"timeframe": ("1m", "5m", "5s"), "bar_state": ("completed",), "regime": ()}
        _combinations = (*_combinations, {"timeframe": "5s", "context": "prior", "bar_state": "completed"})
        if _name in {"regime_age_min", "regime_range_atr", "regime_directional_displacement_atr", "regime_range_atr_per_min"}:
            _combinations = (*_combinations, {"timeframe": "5m", "context": "current", "bar_state": "completed"})
        if _name == "regime_age_min":
            _combinations = (*_combinations, {"timeframe": "1m", "context": "current", "bar_state": "completed"})
        if _name in {"regime_efficiency", "regime_mfe_atr"}:
            # regime_mfe_atr current-context = maximum favorable excursion SO FAR of the
            # in-progress 5m regime, from completed-5m running extreme up to T. Distinct
            # from the completed-regime (context=prior) statistic; no forming-5m state.
            _combinations = (*_combinations, {"timeframe": "5m", "context": "current", "bar_state": "completed"})
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family="structural_regime_geometry", implementation=_STRUCTURAL_IMPL,
        tests=_STRUCTURAL_TESTS, parameters=_params, source_timeframe="1s+1m+5m",
        update_anchor="completed_1s_completed_5m_then_1m_flip",
        normalizer="study_contract", window_unit="since_regime_flip", reset_policy="event_start",
        supported_timeframes=("1m", "5m", "5s"),
        supported_parameter_values=_value_domain,
        required_parameters=_required, supported_parameter_combinations=_combinations,
    )

# Deep-pullback episode geometry is supplied by the reusable episode tracker.  These
# definitions remain provisional until causal/runtime evidence is promoted through the
# canonical authority workflow; registry presence must never self-grant verification.
_EPISODE_IMPL = 'features.trackers.generic_episode_geometry.GenericEpisodeGeometryProvider'
_EPISODE_TESTS = ('features/tests/test_generic_episode_geometry.py',)
for _name, _params, _required, _values in (
    ('pullback_max_depth_atr', ('scope', 'extreme_source'), ('scope', 'extreme_source'), {'scope': ('current_deep_pullback_episode',), 'extreme_source': ('prevailing_directional_extreme',)}),
    # Remaining adverse depth from the prevailing-1m running favorable extreme at
    # candidate T, normalized by the candidate-time ATR contract. Emitted by the same
    # GenericEpisodeGeometryProvider.candidate_snapshot as pullback_max_depth_atr /
    # pullback_recovery_from_extreme_atr; it is a model feature, not an ATR anchor.
    ('pullback_current_depth_atr', ('scope',), ('scope',), {'scope': ('current_deep_pullback_episode',)}),
    ('pullback_recovery_from_extreme_atr', ('scope',), ('scope',), {'scope': ('current_deep_pullback_episode',)}),
    ('pullback_post_arm_seconds', ('scope',), ('scope',), {'scope': ('current_deep_pullback_episode',)}),
    ('pullback_elapsed_seconds', ('scope',), ('scope',), {'scope': ('current_deep_pullback_episode',)}),
    ('pullback_fraction_of_structural_move', ('scope',), ('scope',), {'scope': ('current_deep_pullback_episode',)}),
):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family='pullback_episode_geometry', implementation=_EPISODE_IMPL,
        tests=_EPISODE_TESTS, parameters=_params, source_timeframe='1s',
        update_anchor='completed_1s_at_candidate', normalizer='study_contract',
        window_unit='events', reset_policy='episode', null_policy='allow',
        required_parameters=_required, supported_parameter_values=_values,
    )

for _name, _params in (
    ('seconds_since_prevailing_directional_extreme', ('timeframe', 'context', 'bar_state')),
    ('prior_deep_pullback_count', ('timeframe', 'context', 'bar_state', 'threshold_atr')),
):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family='pullback_sequence_maturity', implementation=_EPISODE_IMPL,
        tests=_EPISODE_TESTS, parameters=_params, source_timeframe='1s+1m',
        update_anchor='completed_1s_at_candidate', normalizer='study_contract',
        window_unit='since_regime_flip', reset_policy='event_start', null_policy='allow',
        supported_timeframes=('1m',),
        supported_parameter_values={
            'timeframe': ('1m',), 'context': ('current',), 'bar_state': ('completed',),
            'threshold_atr': (1.0,),
        }, required_parameters=_params,
        supported_parameter_combinations=(
            {'timeframe': '1m', 'context': 'current', 'bar_state': 'completed',
             **({'threshold_atr': 1.0} if _name == 'prior_deep_pullback_count' else {})},
        ),
    )

_REGIME_GEOMETRY_IMPL = 'features.trackers.generic_regime_geometry.GenericCompletedRegimeGeometryProvider'
for _name in ('recovery_from_counter_regime_extreme_atr', 'fraction_of_counter_regime_move_recovered'):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family='counter_regime_geometry', implementation=_REGIME_GEOMETRY_IMPL,
        tests=_EPISODE_TESTS, parameters=('timeframe',), source_timeframe='5s',
        update_anchor='completed_5s_regime_flip', normalizer='study_contract',
        window_unit='since_regime_flip', reset_policy='event_start', null_policy='allow',
        supported_timeframes=('5s',), supported_parameter_values={'timeframe': ('5s',)},
        required_parameters=('timeframe',),
    )

_DELTA_IMPL = 'features.trackers.generic_ohlcv_delta.GenericOHLCVDeltaProvider'
# Window support is a declaration, not an implementation limit: GenericOHLCVDeltaProvider
# builds whatever trailing windows its instances ask for, and OHLCVDeltaAdapter derives that
# set from the compiled instances. 30s was simply never declared, so a study asking for it
# got INVALID_PARAMETERIZATION for a window the runtime could always have produced.
#
# `short_window` (acceleration) additionally implies 2*short_window, which the adapter adds
# to the provider's window set; that is why its supported values are a subset of `window`.
_DELTA_PARAM_VALUES = {
    'window': ('5s', '30s', '60s', '300s'),
    'numerator_window': ('5s', '30s', '60s'),
    'denominator_window': ('300s',),
    'short_window': ('5s', '30s', '60s'),
    'update_every': ('1s',),
    'direction_reference': ('prevailing_1m',),
}
for _name, _params, _required in (
    ('trend_normalized_est_delta_sum', ('window', 'update_every', 'direction_reference'),
     ('window', 'update_every', 'direction_reference')),
    ('trend_normalized_est_delta_sum_ratio',
     ('numerator_window', 'denominator_window', 'update_every', 'direction_reference'),
     ('numerator_window', 'denominator_window', 'update_every', 'direction_reference')),
    # Directional pressure over [T-w, T] MINUS directional pressure over [T-2w, T-w]:
    # is pressure along the prevailing regime building or fading versus the immediately
    # preceding equal-length window? Distinct from est_delta_sum_minus_scaled, which is
    # D(a) - D(b) for a fixed unequal (a, b) -- see features/trackers/ohlcv_delta.py.
    ('trend_normalized_est_delta_acceleration',
     ('short_window', 'update_every', 'direction_reference'),
     ('short_window', 'update_every', 'direction_reference')),
):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family='direction_normalized_ohlcv_est_delta', implementation=_DELTA_IMPL,
        tests=_EPISODE_TESTS, parameters=_params, source_timeframe='1s',
        update_anchor='completed_1s_at_checkpoint', normalizer='study_contract',
        window_unit='seconds', reset_policy='none', null_policy='allow',
        supported_update_every=('1s',), supported_parameter_values=dict(_DELTA_PARAM_VALUES),
        required_parameters=_required,
    )

CANONICAL_FEATURE_DEFINITIONS['regime_direction'] = _canonical_definition(
    'regime_direction', family='completed_regime_context', implementation=_REGIME_GEOMETRY_IMPL,
    tests=_EPISODE_TESTS, parameters=('timeframe', 'context', 'bar_state'), source_timeframe='5m',
    update_anchor='completed_5m_bar', normalizer='none', window_unit='since_regime_flip',
    reset_policy='event_start', null_policy='allow', supported_timeframes=('5m',),
    supported_parameter_values={'timeframe': ('5m',), 'context': ('current',), 'bar_state': ('completed',)},
    required_parameters=('timeframe', 'context', 'bar_state'),
    supported_parameter_combinations=({'timeframe': '5m', 'context': 'current', 'bar_state': 'completed'},),
)
CANONICAL_FEATURE_DEFINITIONS['regime_alignment'] = _canonical_definition(
    'regime_alignment', family='completed_regime_context', implementation=_REGIME_GEOMETRY_IMPL,
    tests=_EPISODE_TESTS, parameters=('source_timeframe', 'reference_timeframe', 'context', 'bar_state'),
    source_timeframe='1m+5m', update_anchor='completed_5m_bar', normalizer='none',
    window_unit='since_regime_flip', reset_policy='event_start', null_policy='allow',
    supported_timeframes=('1m', '5m'), supported_parameter_values={
        'source_timeframe': ('1m',), 'reference_timeframe': ('5m',),
        'context': ('current',), 'bar_state': ('completed',),
    }, required_parameters=('source_timeframe', 'reference_timeframe', 'context', 'bar_state'),
    supported_parameter_combinations=({'source_timeframe': '1m', 'reference_timeframe': '5m',
                                       'context': 'current', 'bar_state': 'completed'},),
)

for _name in (
    "rolling_max_progress_atr", "rolling_current_progress_atr", "rolling_giveback_atr",
    "rolling_retention_ratio", "rolling_max_speed_atr_per_min",
    "rolling_current_speed_atr_per_min", "rolling_max_speed_vs_lifetime",
    "rolling_current_speed_vs_lifetime",
):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family="rolling_productivity", implementation=_ROLLING_PRODUCTIVITY_IMPL,
        tests=_ROLLING_PRODUCTIVITY_TESTS, parameters=("window", "update_every"),
        source_timeframe="1s", update_anchor="completed_1s_at_or_before_checkpoint",
        normalizer="current_1m_regime_start_atr", window_unit="seconds", reset_policy="none",
        supported_update_every=("1s",),
        supported_parameter_values={"update_every": ("1s",)},
        required_parameters=("window", "update_every"),
    )

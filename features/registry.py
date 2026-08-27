from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Set
import re
import hashlib
import warnings

@dataclass
class FeatureDefinition:
    """Metadata schema defining a registered canonical or alias feature."""
    name: str
    aliases: Tuple[str, ...] = ()
    version: str = "1.0"
    status: str = "verified"  # verified, provisional, deprecated, archived
    family: str = ""
    stateful: bool = True
    source_timeframe: str = "1s"
    update_anchor: str = "after_1s_close"
    snapshot_anchor: str = "caller_defined"
    warmup: Optional[int] = None
    normalizer: str = "study_contract"
    direction_normalized: bool = True
    dtype: str = "float64"
    null_policy: str = "disallow"
    implementation: str = ""
    tests: Tuple[str, ...] = ()
    parity_tolerance: str = "tight"
    # Added by nt_live_scoring_infra_prereqs Phase 2 -- FEATURE_REGISTRY_CONTRACT.md
    # section 2 already specified `window_unit`/`reset_policy` as required tracker
    # parameterization in prose; these fields encode that as actual registry data
    # instead of leaving it narrative-only. `window` is the paired numeric lookback
    # value (e.g. 30 for a 30-second window); None where a feature has no single
    # scalar window (e.g. stateless/session-boundary features).
    window: Optional[float] = None
    window_unit: Optional[str] = None  # bars|seconds|minutes|events|session|since_signal|since_regime_flip
    reset_policy: str = "none"  # e.g. event_start, session_boundary, none
    # V2 additions.  Legacy physical entries leave these empty; canonical definitions
    # declare their supported instance parameters here.  This deliberately extends the
    # existing registry record rather than creating a parallel metadata authority.
    parameter_schema: Tuple[str, ...] = ()
    supported_bar_states: Tuple[str, ...] = ("completed",)
    supported_timeframes: Tuple[str, ...] = ()
    supported_update_every: Tuple[str, ...] = ()
    supported_parameter_values: Mapping[str, Tuple[Any, ...]] = field(default_factory=dict)
    required_parameters: Tuple[str, ...] = ()
    supported_parameter_combinations: Tuple[Mapping[str, Any], ...] = ()
    temporal_identity_exception: bool = False
    coverage_family: str = ""


class FeatureInstanceError(ValueError):
    """Fail-closed instance/configuration error."""


_DURATION_RE = re.compile(r"^(?P<value>[1-9][0-9]*)(?P<unit>s|m)$")
_TEMPORAL_NAME_RE = re.compile(r"(?:^|_)[0-9]+(?:s|m)(?:_|$)|(?:^|_)rolling_[0-9]+(?:s|m)(?:_|$)")
_INSTANCE_NAME_RE = re.compile(
    r"(?:^|_)(?:ema|sma|wma|rsi|median|atr)_[1-9][0-9]*(?:_|$)|"
    r"(?:^|_)(?:period|window|lookback)_[1-9][0-9]*(?:_|$)|"
    r"(?:^|_)seq_[1-9][0-9]*r(?:_|$)"
)


@dataclass(frozen=True)
class FeatureInstance:
    """A study-local request for one canonical definition.

    Instances are intentionally not a registry and have no lifecycle state.  The
    physical alias is an output-compatibility name, while verification remains on the
    canonical FeatureDefinition.
    """
    canonical_name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    physical_alias: Optional[str] = None


def _duration_seconds(value: str) -> int:
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise FeatureInstanceError(f"INVALID_TEMPORAL_PARAMETER: {value!r}; expected '<positive>s' or '<positive>m'")
    number = int(match.group("value"))
    return number * (60 if match.group("unit") == "m" else 1)

# Centralized canonical registry
FEATURE_REGISTRY: Dict[str, FeatureDefinition] = {
    'arrival_vel_5s': FeatureDefinition(
        name='arrival_vel_5s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker',
        tests=('tests/test_feature_library.py',)
    ),
    'arrival_vel_10s': FeatureDefinition(
        name='arrival_vel_10s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'arrival_vel_20s': FeatureDefinition(
        name='arrival_vel_20s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'arrival_vel_30s': FeatureDefinition(
        name='arrival_vel_30s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'arrival_accel_5s': FeatureDefinition(
        name='arrival_accel_5s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'arrival_accel_10s': FeatureDefinition(
        name='arrival_accel_10s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'arrival_jerk': FeatureDefinition(
        name='arrival_jerk',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'max_vel_30s': FeatureDefinition(
        name='max_vel_30s',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'vel_ratio_5_20': FeatureDefinition(
        name='vel_ratio_5_20',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),
    'is_decelerating': FeatureDefinition(
        name='is_decelerating',
        status='verified',
        family='arrival_velocity',
        implementation='features.trackers.velocity.ArrivalVelocityTracker'
    ),

    'rvol_1s': FeatureDefinition(
        name='rvol_1s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'rvol_5s': FeatureDefinition(
        name='rvol_5s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'rvol_10s': FeatureDefinition(
        name='rvol_10s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'vol_trend_10s': FeatureDefinition(
        name='vol_trend_10s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'vol_spike': FeatureDefinition(
        name='vol_spike',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'vol_climax': FeatureDefinition(
        name='vol_climax',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'vol_accel': FeatureDefinition(
        name='vol_accel',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'up_vol_ratio_10s': FeatureDefinition(
        name='up_vol_ratio_10s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'down_vol_ratio_10s': FeatureDefinition(
        name='down_vol_ratio_10s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),
    'vol_price_corr_10s': FeatureDefinition(
        name='vol_price_corr_10s',
        status='verified',
        family='arrival_volume',
        implementation='features.trackers.volume.ArrivalVolumeTracker'
    ),

    'higher_lows_count_1s': FeatureDefinition(
        name='higher_lows_count_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'lower_highs_count_1s': FeatureDefinition(
        name='lower_highs_count_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'swing_count_1s': FeatureDefinition(
        name='swing_count_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'pullback_linearity_1s': FeatureDefinition(
        name='pullback_linearity_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'consecutive_down_1s': FeatureDefinition(
        name='consecutive_down_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'consecutive_up_1s': FeatureDefinition(
        name='consecutive_up_1s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'range_30s_atr': FeatureDefinition(
        name='range_30s_atr',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'close_vs_range_30s': FeatureDefinition(
        name='close_vs_range_30s',
        status='verified',
        family='pullback_1s',
        implementation='features.trackers.pullback.PullbackTracker'
    ),

    'higher_lows_count_1m': FeatureDefinition(
        name='higher_lows_count_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'lower_highs_count_1m': FeatureDefinition(
        name='lower_highs_count_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'swing_count_1m': FeatureDefinition(
        name='swing_count_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'pullback_depth_atr': FeatureDefinition(
        name='pullback_depth_atr',
        aliases=('pb_depth_atr',),
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'pullback_bars_1m': FeatureDefinition(
        name='pullback_bars_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'pullback_efficiency_1m': FeatureDefinition(
        name='pullback_efficiency_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'retracement_pct': FeatureDefinition(
        name='retracement_pct',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),
    'clean_pullback_score_1m': FeatureDefinition(
        name='clean_pullback_score_1m',
        status='verified',
        family='pullback_1m',
        implementation='features.trackers.pullback.PullbackTracker'
    ),

    'regime_age_bars': FeatureDefinition(
        name='regime_age_bars',
        aliases=('bars_in_regime', 'bars_into_regime'),
        status='verified',
        family='context',
        source_timeframe='1m'
    ),
    'ema_slope_short': FeatureDefinition(name='ema_slope_short', status='verified', family='context', source_timeframe='1m'),
    'ema_slope_long': FeatureDefinition(name='ema_slope_long', status='verified', family='context', source_timeframe='1m'),
    'is_rth': FeatureDefinition(name='is_rth', status='verified', family='context', stateful=False),
    'minutes_since_rth_open': FeatureDefinition(name='minutes_since_rth_open', status='verified', family='context', stateful=False),
    'latest_1m_wick_imbalance': FeatureDefinition(
        name='latest_1m_wick_imbalance',
        # Provisional until the promotion validator's evidence requirements are met.
        # A feature may not self-grant 'verified' in the change that implements it --
        # see scripts/check_feature_promotion.py and FEATURE_REGISTRY_CONTRACT.md s1.
        status='provisional',
        family='wick_imbalance',
        implementation='features.trackers.wick.WickTracker',
        tests=('tests/test_feature_library.py', 'scripts/tests/test_wick_availability.py'),
        source_timeframe='1m',
        update_anchor='completed_1m_bar',
        # 'allow' is load-bearing: the feature is genuinely unavailable (None) until the
        # first completed 1m bar. It is NOT a licence for an all-null column, which the
        # surface validator rejects as never-emitted regardless of null policy.
        null_policy='allow',
        warmup=1,
        window=1,
        window_unit='bars',
        reset_policy='none',
        direction_normalized=False,
    ),
    'latest_1m_close_position_prev5_range': FeatureDefinition(
        name='latest_1m_close_position_prev5_range',
        # Provisional until the promotion validator's evidence requirements are met.
        # A feature may not self-grant 'verified' in the change that implements it --
        # see scripts/check_feature_promotion.py and FEATURE_REGISTRY_CONTRACT.md s1.
        status='provisional',
        family='range_position',
        implementation='features.trackers.range_position.RangePositionTracker',
        tests=('tests/test_feature_library.py', 'scripts/tests/test_range_position_availability.py'),
        source_timeframe='1m',
        update_anchor='completed_1m_bar',
        # 'allow' is load-bearing: unavailable (None) until 5 prior completed 1m bars
        # exist, and also None for a flat prior 5-bar range (prev5_high == prev5_low).
        # Neither is an all-null column -- the surface validator still requires the
        # feature to emit real values once warmup is satisfied on a non-flat range.
        null_policy='allow',
        warmup=6,
        window=5,
        window_unit='bars',
        reset_policy='none',
        direction_normalized=False,
    ),
}

# ---------------------------------------------------------------------------
# OHLCV estimated volume/delta (family 'ohlcv_est_delta') and causal
# price-level context (family 'price_level_context') -- generated
# programmatically because each family follows a strict, systematic naming
# pattern over a fixed set of windows/levels (see
# studies/ohlcv_volume_delta_price_level_features/SPEC.md, Parts A & B).
# Status is 'provisional' until the study's lookahead-auditor pass and
# deterministic/runtime-validation tests all clear -- see that study's
# audit/audit.md before promoting any of these to 'verified'.
#
# Deliberately a NEW family, not an extension of the existing
# 'arrival_volume' family (ArrivalVolumeTracker): that family splits volume
# by candle direction (close>=open) over relative-history ratios;
# 'ohlcv_est_delta' splits volume by close-position-within-range over fixed
# windows. Different calculation basis, different features -- not a
# duplicate (documented exemption per FEATURE_REGISTRY_CONTRACT.md).
# ---------------------------------------------------------------------------

_OHLCV_DELTA_IMPL = 'features.trackers.ohlcv_delta.OHLCVDeltaTracker'
_PRICE_LEVEL_IMPL = 'features.trackers.price_levels.PriceLevelTracker'
_OHLCV_TESTS = ('studies/ohlcv_volume_delta_price_level_features/tests/test_ohlcv_delta.py',)
_PRICE_LEVEL_TESTS = ('studies/ohlcv_volume_delta_price_level_features/tests/test_price_levels.py',)

_WINDOWS_S = (5, 15, 30, 60, 120, 300, 900, 1800)
_ROLLING_WINDOWS_MIN = (5, 15, 30, 60)


# Promoted from 'provisional' after studies/ohlcv_volume_delta_price_level_features/
# cleared its independent audit (0 CRITICAL, 3rd pass) and full 6-year
# production join (row/label preservation verified all years) -- see that
# study's STUDY_REPORT.md.
_VERIFIED_STATUS = 'verified'


def _add(name: str, family: str, subfamily: str, implementation: str,
        tests: Tuple[str, ...], null_policy: str = 'disallow',
        source_timeframe: str = '1s', window: Optional[float] = None,
        window_unit: Optional[str] = None, reset_policy: str = 'none') -> None:
    FEATURE_REGISTRY[name] = FeatureDefinition(
        name=name, status=_VERIFIED_STATUS, family=family,
        source_timeframe=source_timeframe, normalizer='study_contract',
        null_policy=null_policy, implementation=implementation, tests=tests,
        window=window, window_unit=window_unit, reset_policy=reset_policy,
    )


# --- Part A1: per-bar estimated delta ---
for _n in ('bar_volume', 'bar_est_bull_volume', 'bar_est_bear_volume',
          'bar_est_delta', 'bar_est_delta_ratio', 'bar_zero_range'):
    _add(_n, 'ohlcv_est_delta', 'bar_level', _OHLCV_DELTA_IMPL, _OHLCV_TESTS,
        window=1, window_unit='bars', reset_policy='none')

# --- Part A2: rolling completed-time windows ---
_A2_METRICS = (
    'vol_sum', 'vol_mean_1s', 'vol_max_1s', 'est_bull_vol_sum', 'est_bear_vol_sum',
    'est_delta_sum', 'est_abs_delta_sum', 'est_delta_ratio', 'est_delta_pos_sum',
    'est_delta_neg_sum', 'upbar_vol_sum', 'downbar_vol_sum', 'up_down_vol_ratio',
    'price_change_points', 'price_change_atr', 'range_points', 'range_atr',
    'volume_per_point_moved', 'volume_per_atr_moved', 'abs_delta_per_point_moved',
    'abs_delta_per_atr_moved',
)
for _w in _WINDOWS_S:
    _add(f'window_available_{_w}s', 'ohlcv_est_delta', 'rolling_window',
        _OHLCV_DELTA_IMPL, _OHLCV_TESTS, null_policy='disallow',
        window=_w, window_unit='seconds', reset_policy='none')
    for _m in _A2_METRICS:
        _add(f'{_m}_{_w}s', 'ohlcv_est_delta', 'rolling_window',
            _OHLCV_DELTA_IMPL, _OHLCV_TESTS, null_policy='allow',
            window=_w, window_unit='seconds', reset_policy='none')

# --- Part A3: short-vs-long pressure comparison (two windows combined; no
# single scalar window -- window/window_unit left None, both component
# windows are recoverable from the feature name itself) ---
for _n in ('est_delta_sum_15s_minus_60s_scaled', 'est_delta_sum_30s_minus_120s_scaled',
          'est_delta_sum_60s_minus_300s_scaled', 'est_delta_ratio_15s_minus_60s',
          'est_delta_ratio_30s_minus_120s', 'est_delta_ratio_60s_minus_300s',
          'vol_sum_30s_vs_300s_ratio', 'vol_sum_60s_vs_900s_ratio'):
    _add(_n, 'ohlcv_est_delta', 'cross_window', _OHLCV_DELTA_IMPL, _OHLCV_TESTS,
        null_policy='allow', reset_policy='none')

# --- Part A4: regime-relative volume/delta (resets at each new regime start) ---
for _n in ('regime_available', 'regime_vol_sum', 'regime_est_delta_sum',
          'regime_est_delta_ratio', 'regime_est_abs_delta_sum', 'regime_elapsed_seconds',
          'regime_volume_per_second', 'regime_price_change_atr', 'regime_range_atr',
          'regime_volume_per_atr_moved', 'regime_abs_delta_per_atr_moved',
          'regime_first_half_est_delta_ratio', 'regime_second_half_est_delta_ratio',
          'regime_late_minus_early_delta_ratio', 'regime_first_half_vol',
          'regime_second_half_vol', 'regime_late_vs_early_vol_ratio'):
    _add(_n, 'ohlcv_est_delta', 'regime_relative', _OHLCV_DELTA_IMPL, _OHLCV_TESTS,
        null_policy='allow', source_timeframe='1m',
        window_unit='since_regime_flip', reset_policy='event_start')

# --- Part A5: RTH-session cumulative (resets at each RTH session boundary) ---
for _n in ('rth_available', 'rth_elapsed_seconds', 'rth_vol_cum', 'rth_est_delta_cum',
          'rth_est_delta_ratio_cum', 'rth_abs_delta_cum', 'rth_volume_per_second'):
    _add(_n, 'ohlcv_est_delta', 'rth_cumulative', _OHLCV_DELTA_IMPL, _OHLCV_TESTS,
        null_policy='allow', window_unit='session', reset_policy='session_boundary')

# --- Part B1/B2: approved base levels + per-level distance features ---
_BASE_LEVELS = (
    ['prior_day_open', 'prior_day_high', 'prior_day_low', 'prior_day_close',
     'overnight_high_developing', 'overnight_low_developing',
     'overnight_high_final', 'overnight_low_final', 'rth_open',
     'opening_range_30m_high_developing', 'opening_range_30m_low_developing',
     'opening_range_30m_high_final', 'opening_range_30m_low_final']
    + [f'rolling_{w}m_{f}' for w in _ROLLING_WINDOWS_MIN for f in ('open', 'high', 'low', 'close')]
)


def _level_window_meta(lvl: str) -> Tuple[Optional[float], Optional[str], str]:
    """`rolling_{w}m_*` levels have a genuine scalar rolling window (minutes,
    never reset -- continuously rolling); every other base level here is
    anchored to a fixed session boundary (prior day, overnight, RTH open,
    opening range) with no single scalar window, reset at that boundary."""
    if lvl.startswith('rolling_') and lvl.split('_')[1].endswith('m'):
        w = int(lvl.split('_')[1][:-1])
        return w, 'minutes', 'none'
    return None, 'session', 'session_boundary'


for _lvl in _BASE_LEVELS:
    _lvl_window, _lvl_unit, _lvl_reset = _level_window_meta(_lvl)
    for _suffix in ('_price', '_available', '_signed_distance_points',
                    '_signed_distance_ticks', '_signed_distance_atr', '_position'):
        _add(f'{_lvl}{_suffix}', 'price_level_context', 'per_level_distance',
            _PRICE_LEVEL_IMPL, _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m',
            window=_lvl_window, window_unit=_lvl_unit, reset_policy=_lvl_reset)

for _n in ('opening_range_30m_is_developing', 'opening_range_30m_is_final',
          'opening_range_30m_elapsed_seconds', 'rth_open_elapsed_seconds'):
    _add(_n, 'price_level_context', 'session_state', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m',
        window_unit='session', reset_policy='session_boundary')

# --- Part B3: aggregate level-count features (point-in-time snapshot over
# whatever levels are currently available; no single scalar window) ---
for _n in ('n_levels_available', 'n_levels_above', 'n_levels_below', 'n_levels_touched',
          'pct_levels_above', 'pct_levels_below', 'pct_levels_touched', 'level_balance',
          'n_prior_day_levels_above', 'n_prior_day_levels_below',
          'n_session_levels_above', 'n_session_levels_below',
          'n_rolling_levels_above', 'n_rolling_levels_below'):
    _add(_n, 'price_level_context', 'aggregate_counts', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')

# --- Part B4: nearest-level geometry (point-in-time; no single scalar window) ---
for _n in ('nearest_level_above_name', 'nearest_level_above_price',
          'nearest_level_above_distance_points', 'nearest_level_above_distance_ticks',
          'nearest_level_above_distance_atr', 'nearest_level_below_name',
          'nearest_level_below_price', 'nearest_level_below_distance_points',
          'nearest_level_below_distance_ticks', 'nearest_level_below_distance_atr',
          'nearest_space_balance_atr', 'nearest_space_total_atr',
          'nearest_upside_downside_ratio'):
    _add(_n, 'price_level_context', 'nearest_geometry', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')

# --- Part B5: level density and envelope (bands are ATR-distance bands, not
# time windows -- window_unit intentionally None) ---
for _band in ('025a', '050a', '100a', '200a'):
    for _n in (f'level_density_{_band}', f'levels_above_within_{_band}', f'levels_below_within_{_band}'):
        _add(_n, 'price_level_context', 'density_envelope', _PRICE_LEVEL_IMPL,
            _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')
for _n in ('inverse_distance_density', 'lowest_available_level', 'highest_available_level',
          'full_level_envelope_width_points', 'full_level_envelope_width_atr',
          'price_position_in_full_envelope', 'distance_above_full_envelope_atr',
          'distance_below_full_envelope_atr'):
    _add(_n, 'price_level_context', 'density_envelope', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')

# --- Part B6: simple clustered levels (point-in-time; no single scalar window) ---
for _n in ('n_level_clusters_available', 'n_level_clusters_above', 'n_level_clusters_below',
          'n_level_clusters_touched', 'nearest_cluster_above_price',
          'nearest_cluster_above_distance_atr', 'nearest_cluster_above_strength',
          'nearest_cluster_below_price', 'nearest_cluster_below_distance_atr',
          'nearest_cluster_below_strength', 'max_cluster_strength',
          'max_nearby_cluster_strength_050a', 'max_nearby_cluster_strength_100a'):
    _add(_n, 'price_level_context', 'clustering', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')

# --- Part B7: direction-normalized level features (point-in-time; no single
# scalar window -- direction_normalized=True is already the dataclass default) ---
for _n in ('levels_ahead_of_trade', 'levels_behind_trade', 'pct_levels_ahead_of_trade',
          'pct_levels_behind_trade', 'nearest_level_ahead_distance_atr',
          'nearest_level_behind_distance_atr', 'nearest_cluster_ahead_distance_atr',
          'nearest_cluster_behind_distance_atr', 'directional_space_balance_atr'):
    _add(_n, 'price_level_context', 'direction_normalized', _PRICE_LEVEL_IMPL,
        _PRICE_LEVEL_TESTS, null_policy='allow', source_timeframe='1m', reset_policy='none')

del _n, _w, _m, _lvl, _suffix, _band

# --- F0: Regime median centers, activity, and sequence features ---
_F0_IMPL = 'features.trackers.median_center.MedianCenterTracker'
_F0_TESTS = ('tests/test_median_center.py',)

# 1. Aligned price minus centers
for _lvl in ('5m', '15m', '30m'):
    FEATURE_REGISTRY[f'aligned_price_minus_center_{_lvl}'] = FeatureDefinition(
        name=f'aligned_price_minus_center_{_lvl}',
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 2. Slopes aligned atr
for _col in ('slope_5m_1m', 'slope_5m_3m', 'slope_5m_5m',
            'slope_15m_3m', 'slope_15m_5m', 'slope_15m_10m',
            'slope_30m_5m', 'slope_30m_10m', 'slope_30m_15m'):
    FEATURE_REGISTRY[f'{_col}_aligned_atr'] = FeatureDefinition(
        name=f'{_col}_aligned_atr',
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 3. Slope changes and accelerations
for _col in ('center_slope_change_5m', 'center_slope_change_15m', 'center_slope_change_30m',
            'center_slope_acceleration_5m', 'center_slope_acceleration_15m', 'center_slope_acceleration_30m'):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col,
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 4. Spreads and spread changes
for _col in ('center_spread_5m_15m', 'center_spread_15m_30m', 'center_spread_5m_30m',
            'spread_change_5m_15m', 'spread_change_15m_30m', 'spread_change_5m_30m'):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col,
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 5. Ordering state features
for _col in ('ordering_state', 'seconds_in_current_ordering',
            'ordering_changes_15m', 'ordering_changes_30m', 'ordering_changes_60m'):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col,
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 6. Crossing behavior
for _col in ('price_cross_count_5m', 'price_cross_count_15m', 'price_cross_count_30m',
            'crosses_per_minute', 'fraction_of_time_on_favorable_side', 'fraction_of_time_on_adverse_side'):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col,
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 7. Activity features
for _col in ('activity_regime_count_5m', 'activity_regime_count_15m', 'activity_regime_count_30m',
            'activity_regime_count_60m', 'activity_regime_count_120m', 'activity_flip_count_30m',
            'activity_duration_median_5m', 'activity_duration_median_15m', 'activity_duration_median_30m',
            'activity_duration_median_60m', 'activity_duration_median_120m', 'activity_regime_count_std',
            'duration_median_last_3', 'duration_median_last_5',
            'duration_median_last_10', 'duration_ratio_3_vs_10', 'duration_ratio_5_vs_10',
            'cross_family_spread_vs_reg_count', 'cross_family_slope_vs_reg_count'):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col,
        status='provisional',
        family='regime_median_center_slope_alignment',
        implementation=_F0_IMPL,
        tests=_F0_TESTS,
        source_timeframe='1s',
        window_unit='bars',
        reset_policy='none'
    )

# 8. Completed regime sequence stats (seq_Kr_*) for K in (3, 5, 8, 12)
for _K in (3, 5, 8, 12):
    _prefix = f'seq_{_K}r_'
    for _suffix in (
        'alternation_rate', 'perfect_alternation', 'efficiency', 'disp_atr',
        'mean_overlap', 'median_overlap', 'max_overlap', 'overlap_above_50', 'overlap_above_75',
        'mean_retracement', 'mean_retracement_mfe', 'reclaim_rate', 'range_atr', 'position_pct',
        'dist_to_high_atr', 'dist_to_low_atr', 'center_migration_slope_atr', 'center_migration_r2',
        'center_dir_consistency', 'center_reversal_count', 'asym_duration', 'asym_mfe',
        'asym_net_move', 'asym_efficiency', 'asym_volume'
    ):
        _name = f'{_prefix}{_suffix}'
        FEATURE_REGISTRY[_name] = FeatureDefinition(
            name=_name,
            status='provisional',
            family='regime_median_center_slope_alignment',
            implementation=_F0_IMPL,
            tests=_F0_TESTS,
            source_timeframe='1s',
            window_unit='bars',
            reset_policy='none'
        )

# Structural-regime geometry is provisional until the owning study's parity,
# prefix-invariance, and causal audits clear. Its study-specific snapshot binding is
# declared by the collector; the registry records update ownership and formulas.
_STRUCTURAL_IMPL = 'features.trackers.structural_regime_geometry.StructuralRegimeGeometryTracker'
_STRUCTURAL_TESTS = ('studies/Codex_structural_regime_geometry_maturity/tests/test_geometry_tracker.py',)
# Declared here as well as consumed by the legacy physical-alias loop below so V2
# canonical definitions can be constructed before that loop.  They intentionally name
# the existing provider and test surface; no formula is moved or duplicated.
_ROLLING_PRODUCTIVITY_IMPL = 'features.trackers.rolling_5m_productivity.Rolling5mProductivityTracker'
_ROLLING_PRODUCTIVITY_TESTS = ('studies/Codex_clean_maturity_flip_rolling_5m_productivity/tests/test_rolling_5m_productivity.py',)
for _col in (
    'structural_max_expansion_atr', 'structural_current_expansion_atr',
    'structural_giveback_atr', 'structural_retention_ratio',
    'structural_expansion_atr_per_min', 'regime_expansion_atr_per_min',
    'prior_1m_regime_duration_min', 'prior_1m_regime_range_atr',
    'prior_1m_regime_net_directional_move_atr', 'prior_1m_regime_mfe_atr',
    'prior_1m_regime_range_atr_per_min', 'prior_1m_regime_net_move_atr_per_min',
    'prior_1m_regime_efficiency', 'current_5m_regime_age_min',
    'current_5m_regime_range_atr', 'current_5m_directional_displacement_atr',
    'current_5m_regime_range_atr_per_min', 'prior_5m_regime_duration_min',
    'prior_5m_regime_range_atr', 'prior_5m_regime_net_directional_move_atr',
    'prior_5m_regime_mfe_atr', 'prior_5m_regime_range_atr_per_min',
    'prior_5m_regime_net_move_atr_per_min', 'prior_5m_regime_efficiency',
    'distance_to_completed_5m_high_atr', 'distance_to_completed_5m_low_atr',
    'current_1m_move_outside_completed_5m_range',
):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col, status='provisional', family='structural_regime_geometry',
        implementation=_STRUCTURAL_IMPL, tests=_STRUCTURAL_TESTS,
        source_timeframe='1s+1m+5m',
        update_anchor='completed_1s_completed_5m_then_1m_flip',
        normalizer='study_contract', window_unit='since_regime_flip',
        reset_policy='event_start', null_policy='allow',
    )


# ---------------------------------------------------------------------------
# Feature System V2 -- canonical building blocks for the first two migrated
# families.  FEATURE_REGISTRY remains the compatibility registry of physical
# output aliases; these definitions are the one lifecycle/promotion authority.
# ---------------------------------------------------------------------------
_CANONICAL_PROMOTIONS_PATH = __import__("pathlib").Path(__file__).with_name("feature_definition_promotions.json")


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
        if _name == "regime_efficiency":
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
    ('pullback_max_depth_atr', ('scope', 'extreme_source'), ('scope', 'extreme_source'), {}),
    ('pullback_recovery_from_extreme_atr', ('scope',), ('scope',), {}),
    ('pullback_post_arm_seconds', ('scope',), ('scope',), {}),
    ('pullback_elapsed_seconds', ('scope',), ('scope',), {}),
    ('pullback_fraction_of_structural_move', ('scope',), ('scope',), {}),
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
for _name, _params, _required in (
    ('trend_normalized_est_delta_sum', ('window', 'update_every', 'direction_reference'),
     ('window', 'update_every', 'direction_reference')),
    ('trend_normalized_est_delta_sum_ratio',
     ('numerator_window', 'denominator_window', 'update_every', 'direction_reference'),
     ('numerator_window', 'denominator_window', 'update_every', 'direction_reference')),
):
    CANONICAL_FEATURE_DEFINITIONS[_name] = _canonical_definition(
        _name, family='direction_normalized_ohlcv_est_delta', implementation=_DELTA_IMPL,
        tests=_EPISODE_TESTS, parameters=_params, source_timeframe='1s',
        update_anchor='completed_1s_at_checkpoint', normalizer='study_contract',
        window_unit='seconds', reset_policy='none', null_policy='allow',
        supported_update_every=('1s',), supported_parameter_values={
            'update_every': ('1s',), 'direction_reference': ('prevailing_1m',),
        }, required_parameters=_required,
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


# The 35 existing physical aliases are deliberately a small compatibility map, not an
# instance registry.  New aliases are generated deterministically below; these preserve
# historical parquet/model contracts whose legacy spelling uses 5m for a 300s window.
LEGACY_FEATURE_INSTANCE_OVERRIDES: Dict[str, FeatureInstance] = {}
for _metric in (
    "duration_min", "range_atr", "net_directional_move_atr", "mfe_atr",
    "range_atr_per_min", "net_move_atr_per_min", "efficiency",
):
    for _tf in ("1m", "5m"):
        _alias = f"prior_{_tf}_regime_{_metric}"
        LEGACY_FEATURE_INSTANCE_OVERRIDES[_alias] = FeatureInstance(
            f"regime_{_metric}", {"timeframe": _tf, "context": "prior", "bar_state": "completed"}, _alias,
        )
LEGACY_FEATURE_INSTANCE_OVERRIDES.update({
    "current_5m_regime_age_min": FeatureInstance("regime_age_min", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_regime_range_atr": FeatureInstance("regime_range_atr", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_directional_displacement_atr": FeatureInstance("regime_directional_displacement_atr", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "current_5m_regime_range_atr_per_min": FeatureInstance("regime_range_atr_per_min", {"timeframe": "5m", "context": "current", "bar_state": "completed"}),
    "distance_to_completed_5m_high_atr": FeatureInstance("distance_to_completed_range_high_atr", {"reference_timeframe": "5m", "bar_state": "completed"}),
    "distance_to_completed_5m_low_atr": FeatureInstance("distance_to_completed_range_low_atr", {"reference_timeframe": "5m", "bar_state": "completed"}),
    "current_1m_move_outside_completed_5m_range": FeatureInstance("move_outside_completed_range", {"source_timeframe": "1m", "reference_timeframe": "5m", "context": "current", "source_bar_state": "completed", "reference_bar_state": "completed"}),
})
for _name in (
    "structural_max_expansion_atr", "structural_current_expansion_atr",
    "structural_giveback_atr", "structural_retention_ratio",
    "structural_expansion_atr_per_min", "regime_expansion_atr_per_min",
):
    LEGACY_FEATURE_INSTANCE_OVERRIDES[_name] = FeatureInstance(_name, {"context": "current"}, _name)
for _suffix in (
    "max_progress_atr", "current_progress_atr", "giveback_atr", "retention_ratio",
    "max_speed_atr_per_min", "current_speed_atr_per_min", "max_speed_vs_lifetime",
    "current_speed_vs_lifetime",
):
    _alias = f"rolling_5m_{_suffix}"
    LEGACY_FEATURE_INSTANCE_OVERRIDES[_alias] = FeatureInstance(
        f"rolling_{_suffix}", {"window": "300s", "update_every": "1s"}, _alias,
    )


def canonical_definition_status(name: str) -> str:
    """Effective V2 lifecycle status backed by a generated promotion record."""
    definition = CANONICAL_FEATURE_DEFINITIONS[name]
    if definition.status == "verified":
        return "verified"
    try:
        import json
        records = json.loads(_CANONICAL_PROMOTIONS_PATH.read_text(encoding="utf-8")).get("promotions", [])
    except (OSError, ValueError):
        return definition.status
    record = next((item for item in records if isinstance(item, dict) and item.get("feature") == name), None)
    if record is None:
        return definition.status
    module = definition.implementation.rsplit(".", 1)[0]
    implementation_path = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath(*module.split(".")).with_suffix(".py")
    try:
        implementation_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    except OSError:
        return definition.status
    audit_path = __import__("pathlib").Path(__file__).resolve().parents[1] / str(record.get("causal_audit_artifact", ""))
    if (not audit_path.is_file() or not record.get("audited_execution_composite_sha256")
            or not record.get("promoted_by")
            or record.get("reviewed_implementation_sha256") != implementation_hash
            or list(record.get("supported_parameter_schema", ())) != list(definition.parameter_schema)):
        return definition.status
    return "verified"


def validate_feature_instance(instance: FeatureInstance) -> Dict[str, Any]:
    """Validate a canonical instance and return normalized parameters.

    The raw parameter membership check is important: a 1m request updated every second
    without an explicit bar_state is ambiguous, rather than silently becoming a completed
    bar request.
    """
    if instance.canonical_name not in CANONICAL_FEATURE_DEFINITIONS:
        # The active V2 bundle is authoritative after cutover; the historical
        # Python catalog is intentionally only a compatibility surface.  Keep
        # validation fail-closed while accepting bundle definitions without
        # duplicating a second registry in code.
        bundle = _canonical_bundle("active")
        bundle_def = _canonical_definition_by_name(bundle, instance.canonical_name) if bundle else None
        if bundle_def is None:
            raise FeatureInstanceError(f"UNKNOWN_CANONICAL_FEATURE: {instance.canonical_name!r}")
        params = dict(instance.parameters)
        schema = set(bundle_def.get("parameter_schema", ()))
        unknown = sorted(set(params) - schema)
        if unknown:
            raise FeatureInstanceError(f"UNKNOWN_FEATURE_PARAMETER: {instance.canonical_name}: {unknown}")
        for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
            if state_key in schema:
                params.setdefault(state_key, "completed")
        for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
            if params.get(state_key) not in {None, "completed"}:
                raise FeatureInstanceError(
                    f"FORMING_BAR_UNSUPPORTED: {instance.canonical_name} supports completed bar states only"
                )
        return params
    definition = CANONICAL_FEATURE_DEFINITIONS[instance.canonical_name]
    params = dict(instance.parameters)
    if "timeframe" in params and "update_every" in params and "bar_state" not in params:
        raise FeatureInstanceError("AMBIGUOUS_TEMPORAL_SEMANTICS: timeframe plus update_every requires bar_state=forming, or declare a rolling window")
    # Bar-state defaults belong to definitions; a temporal update cadence is
    # separately validated below and cannot silently turn a calendar bar into
    # a forming stream.
    for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
        if state_key in definition.parameter_schema:
            params.setdefault(state_key, "completed")
    for state_key in ("bar_state", "source_bar_state", "reference_bar_state"):
        requested_bar_state = params.get(state_key)
        if requested_bar_state is None:
            continue
        if requested_bar_state not in {"completed", "forming"}:
            raise FeatureInstanceError("INVALID_BAR_STATE: expected 'completed' or 'forming'")
        if requested_bar_state not in definition.supported_bar_states:
            raise FeatureInstanceError(
                f"FORMING_BAR_UNSUPPORTED: {instance.canonical_name} supports "
                f"{list(definition.supported_bar_states)} bar states only"
            )
    # Reject an unimplemented temporal state before reporting incidental
    # parameter membership. This keeps the causal contract diagnostic exact.
    unknown = sorted(set(params) - set(definition.parameter_schema))
    if unknown:
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_PARAMETER: {instance.canonical_name}: {unknown}")
    for key, allowed in definition.supported_parameter_values.items():
        if key in params and params[key] not in allowed:
            if (key in {"timeframe", "source_timeframe", "reference_timeframe"}
                    and params[key] not in definition.supported_timeframes):
                raise FeatureInstanceError(
                    f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                    f"{list(definition.supported_timeframes)}, not {params[key]!r}"
                )
            if key == "update_every":
                raise FeatureInstanceError(
                    f"UNSUPPORTED_UPDATE_CADENCE: {instance.canonical_name} supports "
                    f"{list(allowed)}, not {params[key]!r}"
                )
            raise FeatureInstanceError(
                f"UNSUPPORTED_FEATURE_PARAMETER_VALUE: {instance.canonical_name} "
                f"requires {key} in {list(allowed)}, not {params[key]!r}"
            )
    missing_required = [key for key in definition.required_parameters if key not in params]
    if missing_required:
        raise FeatureInstanceError(f"MISSING_REQUIRED_FEATURE_PARAMETER: {instance.canonical_name}: {missing_required}")
    if "timeframe" in params:
        _duration_seconds(str(params["timeframe"]))
        if definition.supported_timeframes and params["timeframe"] not in definition.supported_timeframes:
            raise FeatureInstanceError(
                f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                f"{list(definition.supported_timeframes)}, not {params['timeframe']!r}"
            )
        params.setdefault("bar_state", "completed")
        if params["bar_state"] == "forming":
            if "update_every" not in params:
                raise FeatureInstanceError("FORMING_BAR_UPDATE_REQUIRED: forming calendar bars require update_every")
            if _duration_seconds(str(params["update_every"])) > _duration_seconds(str(params["timeframe"])):
                raise FeatureInstanceError("FORMING_BAR_UPDATE_INVALID: update_every cannot exceed timeframe")
        elif "update_every" in params:
            raise FeatureInstanceError("COMPLETED_BAR_UPDATE_FREQUENCY_INVALID: completed calendar bars update only on completion")
    if "window" in params:
        if "timeframe" in params:
            raise FeatureInstanceError("AMBIGUOUS_TEMPORAL_SEMANTICS: use either calendar timeframe or rolling window")
        _duration_seconds(str(params["window"]))
        if "update_every" not in params:
            raise FeatureInstanceError("ROLLING_WINDOW_UPDATE_REQUIRED: rolling windows require update_every")
        _duration_seconds(str(params["update_every"]))
        if definition.supported_update_every and params["update_every"] not in definition.supported_update_every:
            raise FeatureInstanceError(
                f"UNSUPPORTED_UPDATE_CADENCE: {instance.canonical_name} supports "
                f"{list(definition.supported_update_every)}, not {params['update_every']!r}"
            )
    for key in ("numerator_window", "denominator_window"):
        if key in params:
            _duration_seconds(str(params[key]))
    for key in ("source_timeframe", "reference_timeframe"):
        if key in params:
            _duration_seconds(str(params[key]))
            if definition.supported_timeframes and params[key] not in definition.supported_timeframes:
                raise FeatureInstanceError(
                    f"UNSUPPORTED_TIMEFRAME_PARAMETER: {instance.canonical_name} supports "
                    f"{list(definition.supported_timeframes)}, not {params[key]!r}"
                )
    if definition.supported_parameter_combinations and not any(
            all(params.get(key) == value for key, value in allowed.items())
            for allowed in definition.supported_parameter_combinations):
        raise FeatureInstanceError(
            f"UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: {instance.canonical_name}: {params}"
        )
    return params


def generate_physical_alias(instance: FeatureInstance) -> str:
    """Deterministically render a V2 instance, retaining explicit legacy aliases."""
    params = validate_feature_instance(instance)
    if instance.physical_alias:
        return instance.physical_alias
    name = instance.canonical_name
    if name.startswith("regime_") and "timeframe" in params:
        prefix = f"{params.get('context', 'current')}_{params['timeframe']}_"
        return f"{prefix}{name}"
    if name.startswith("rolling_") and "window" in params:
        return f"rolling_{params['window']}_{name[len('rolling_'):]}"
    if name == "trend_normalized_est_delta_sum" and "window" in params:
        return f"trend_normalized_est_delta_sum_{params['window']}"
    if name == "trend_normalized_est_delta_sum_ratio" and "numerator_window" in params:
        return (
            f"trend_normalized_est_delta_sum_ratio_{params['numerator_window']}"
            f"_vs_{params['denominator_window']}"
        )
    if name.startswith("distance_to_completed_range_"):
        return f"distance_to_completed_{params['reference_timeframe']}_{name[len('distance_to_completed_range_'):]}"
    if name == "move_outside_completed_range":
        return f"{params.get('context', 'current')}_{params['source_timeframe']}_move_outside_completed_{params['reference_timeframe']}_range"
    return name


def derive_instance_input_requirements(instance: FeatureInstance) -> Dict[str, Any]:
    """Describe the runtime streams/availability contract derived from an instance."""
    params = validate_feature_instance(instance)
    definition = CANONICAL_FEATURE_DEFINITIONS[instance.canonical_name]
    if params.get("bar_state") == "forming":
        return {"provider": definition.implementation, "required_streams": ["completed_1s"],
                "calendar_timeframe": params["timeframe"], "bar_state": "forming",
                "update_every": params["update_every"]}
    rolling_legacy = params.get("context") == "rolling" and "timeframe" in params
    if "window" in params or rolling_legacy:
        window = params.get("window", params.get("timeframe"))
        return {"provider": definition.implementation, "required_streams": ["completed_1s"],
                "window_type": "rolling", "window": window, "update_every": params.get("update_every", "1s")}
    if "source_timeframe" in params or "reference_timeframe" in params:
        streams = []
        for key, state_key in (("source_timeframe", "source_bar_state"), ("reference_timeframe", "reference_bar_state")):
            if key in params:
                state = params.get(state_key, "completed")
                streams.append(f"{state}_{params[key]}")
        return {"provider": definition.implementation, "required_streams": sorted(set(streams)),
                "source_timeframe": params.get("source_timeframe"),
                "reference_timeframe": params.get("reference_timeframe"),
                "source_bar_state": params.get("source_bar_state", "completed"),
                "reference_bar_state": params.get("reference_bar_state", "completed")}
    return {"provider": definition.implementation, "required_streams": [f"completed_{params.get('timeframe', definition.source_timeframe)}"],
            "bar_state": params.get("bar_state", "completed")}


def resolve_feature_instances(source: Optional[str], instances: Optional[Tuple[FeatureInstance, ...]] = None, *, legacy_mode: bool = False) -> List[Dict[str, Any]]:
    """The single collection-time resolver used by compiler, phase0, runtime and output.

    Active resolution returns canonical definitions/instances only.  The historical
    physical universe is available solely through explicit ``legacy_mode``.
    """
    if not source:
        return []
    if source == "canonical_verified_definition_universe":
        bundle = _canonical_bundle("active")
        definitions = (bundle or {}).get("registry", {}).get("definitions", [])
        if instances is not None:
            resolved = []
            for instance in instances:
                params = validate_feature_instance(instance)
                definition = _canonical_definition_by_name(bundle, instance.canonical_name) if bundle else None
                if definition is None or definition.get("status") != "verified":
                    raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {instance.canonical_name}")
                resolved.append({"canonical_name": instance.canonical_name, "parameters": params,
                                 "physical_alias": generate_physical_alias(instance), "provider": definition.get("provider", ""),
                                 "status": "verified", "causal_input_requirements": definition.get("input_availability_contracts", [])})
            return sorted(resolved, key=lambda item: item["physical_alias"])
        return [{"canonical_name": item["canonical_name"], "parameters": {},
                 "physical_alias": item["canonical_name"], "provider": item.get("provider", ""),
                 "status": item.get("status"), "causal_input_requirements": item.get("input_availability_contracts", [])}
                for item in definitions if item.get("status") == "verified"]
    if source != "verified_registry_numeric_universe":
        raise ValueError(f"UNKNOWN_FEATURE_SOURCE: '{source}' is not a recognized features.source value")
    if not legacy_mode:
        raise FeatureInstanceError("LEGACY_FEATURE_ALIAS_NOT_ALLOWED: use canonical FeatureInstances or explicit legacy replay mode")
    resolved: List[Dict[str, Any]] = []
    if instances is not None:
        for instance in instances:
            params = validate_feature_instance(instance)
            definition = CANONICAL_FEATURE_DEFINITIONS[instance.canonical_name]
            if canonical_definition_status(instance.canonical_name) != "verified":
                raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {instance.canonical_name}")
            resolved.append({"canonical_name": instance.canonical_name, "parameters": params,
                             "physical_alias": generate_physical_alias(instance), "provider": definition.implementation,
                             "status": "verified", "causal_input_requirements": definition.update_anchor})
        return sorted(resolved, key=lambda item: item["physical_alias"])
    for name, definition in FEATURE_REGISTRY.items():
        if definition.status == "verified" and definition.dtype in _NUMERIC_DTYPES and definition.implementation.startswith("features."):
            resolved.append({"canonical_name": name, "parameters": {}, "physical_alias": name,
                             "provider": definition.implementation, "status": "verified",
                             "causal_input_requirements": definition.update_anchor})
    for alias, instance in LEGACY_FEATURE_INSTANCE_OVERRIDES.items():
        canonical = instance.canonical_name
        if canonical_definition_status(canonical) == "verified":
            definition = CANONICAL_FEATURE_DEFINITIONS[canonical]
            resolved.append({"canonical_name": canonical, "parameters": validate_feature_instance(instance),
                             "physical_alias": alias, "provider": definition.implementation, "status": "verified",
                             "causal_input_requirements": definition.update_anchor})
    return sorted(resolved, key=lambda item: item["physical_alias"])

# Study-owned rolling productivity.  It is provisional until this study's
# pre-execution and completion audits, deterministic boundary tests, and NT
# collection validation have all cleared.  The tracker has no hidden label or
# outcome input: every value comes from completed 1s bars at the checkpoint.
_ROLLING_PRODUCTIVITY_IMPL = 'features.trackers.rolling_5m_productivity.Rolling5mProductivityTracker'
_ROLLING_PRODUCTIVITY_TESTS = ('studies/Codex_clean_maturity_flip_rolling_5m_productivity/tests/test_rolling_5m_productivity.py',)
for _col in (
    'rolling_5m_max_progress_atr', 'rolling_5m_current_progress_atr',
    'rolling_5m_giveback_atr', 'rolling_5m_retention_ratio',
    'rolling_5m_max_speed_atr_per_min', 'rolling_5m_current_speed_atr_per_min',
    'rolling_5m_max_speed_vs_lifetime',
    'rolling_5m_current_speed_vs_lifetime',
):
    FEATURE_REGISTRY[_col] = FeatureDefinition(
        name=_col, status='provisional', family='rolling_5m_productivity',
        implementation=_ROLLING_PRODUCTIVITY_IMPL, tests=_ROLLING_PRODUCTIVITY_TESTS,
        source_timeframe='1s', update_anchor='completed_1s_at_or_before_checkpoint',
        snapshot_anchor='at_5s_decision_ts', normalizer='current_1m_regime_start_atr',
        window=300, window_unit='seconds', reset_policy='none', null_policy='allow',
    )

# Reverse mapping for alias lookup
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canonical_name, definition in FEATURE_REGISTRY.items():
    for alias in definition.aliases:
        _ALIAS_TO_CANONICAL[alias] = canonical_name

def resolve_feature_name(name: str) -> str:
    """
    Resolves any alias to its canonical target.
    
    If the name is a registered alias, it issues a DeprecationWarning.
    """
    if name in _ALIAS_TO_CANONICAL:
        canonical = _ALIAS_TO_CANONICAL[name]
        warnings.warn(
            f"Feature alias {name!r} is deprecated. Use canonical name {canonical!r} instead.",
            category=DeprecationWarning,
            stacklevel=2
        )
        return canonical
    return name


# ---------------------------------------------------------------------------
# Collection-time source universe resolution (Phase 1 Packet D2)
#
# `StudySpec.features.source` names a collection-time candidate feature universe --
# distinct from the later frozen `features.feature_list` (a small, ordered, hash-pinned
# Top-N selection that exists only after TRAIN-stage feature selection). A study whose
# `source` is set but whose `feature_list` is still null is not missing configuration; it
# is correctly declaring "collect from this universe, freeze the model list later."
#
# "verified_registry_numeric_universe" is the exact filter already used to authenticate
# the collection-time candidate set elsewhere in the repo (see
# studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/phase0.py
# :verified_numeric_candidates and that study's collector.py:BASELINE_CANDIDATES). This
# function gives the output-contract path (OutputManager, check_feature_surface) the same
# resolution without either of those study-local copies importing framework code, or the
# framework importing study-local code.
# ---------------------------------------------------------------------------
_NUMERIC_DTYPES = {"float64", "float32", "int64", "int32"}


def resolve_source_universe(source: Optional[str], *, authority: str = "active", legacy_mode: bool = False) -> List[str]:
    """Resolves a StudySpec `features.source` name to its collection-time candidate list.

    Returns ``[]`` when `source` is unset (``None``/empty) -- a study that has not
    declared a collection-time source is unaffected, not an error. An explicitly set but
    unrecognized `source` string fails closed rather than silently resolving to nothing.
    """
    if not source:
        return []
    # Candidate authority is explicit and inert by default. Once activation has
    # written the sole active pointer, the exact same resolver reads that
    # reviewed bundle; before then, active preserves the existing authority.
    from features.candidate_authority import ACTIVE_POINTER, resolve_candidate_aliases
    if source == "canonical_verified_definition_universe":
        bundle = _canonical_bundle(authority)
        if bundle is None:
            return sorted(CANONICAL_FEATURE_DEFINITIONS)
        return sorted(item["canonical_name"] for item in bundle["registry"].get("definitions", [])
                      if item.get("status") == "verified")
    if source != "verified_registry_numeric_universe":
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_SOURCE: {source!r}")
    if not legacy_mode:
        raise FeatureInstanceError(
            "LEGACY_FEATURE_ALIAS_NOT_ALLOWED: verified_registry_numeric_universe is a legacy alias source; "
            "declare canonical FeatureInstances or use explicit legacy replay mode"
        )
    if authority == "legacy":
        return sorted(LEGACY_FEATURE_INSTANCE_OVERRIDES)
    if authority == "candidate":
        # Explicit candidate selection is never substitutable.  A malformed or
        # incomplete candidate must surface its own fail-closed authority error.
        return resolve_candidate_aliases(source or "", authority="candidate", legacy_mode=True)
    if authority not in {"active", "legacy"}:
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_AUTHORITY: {authority!r}")
    if ACTIVE_POINTER.is_file():
        # Once cut over, active is the reviewed bundle.  Do not resurrect the
        # legacy registry if its pointer/bundle is damaged.
        return resolve_candidate_aliases(source or "", authority="active", legacy_mode=True)
    return [item["physical_alias"] for item in resolve_feature_instances(source)]


# ---------------------------------------------------------------------------
# Active pipeline resolution API
# ---------------------------------------------------------------------------
# FEATURE_REGISTRY above is retained as a compatibility implementation catalog
# until the old source file can be retired.  It is deliberately not exposed to
# pipeline callers as an authority: membership, lifecycle and alias identity
# below come from the activated canonical bundle (or the explicitly requested
# candidate bundle).  Keeping the compatibility lookup here avoids each caller
# reimplementing a partial alias/verified/provider predicate.

def _canonical_bundle(authority: str) -> Optional[Dict[str, Any]]:
    """Return an explicitly selected canonical bundle when one is authoritative.

    Before the one-shot cutover normal ``active`` continues to use the legacy
    authority so existing studies remain runnable. Candidate is always
    explicit and never falls back. After cutover, active reads exactly the
    bundle selected by the active pointer.
    """
    from features.candidate_authority import ACTIVE_POINTER, load_authority
    if authority == "legacy":
        return None
    if authority == "candidate":
        return load_authority("candidate")
    if authority != "active":
        raise FeatureInstanceError(f"UNKNOWN_FEATURE_AUTHORITY: {authority!r}")
    return load_authority("active") if ACTIVE_POINTER.is_file() else None


def _canonical_definition_by_name(bundle: Mapping[str, Any], name: str) -> Optional[Mapping[str, Any]]:
    for definition in bundle["registry"].get("definitions", []):
        if definition.get("canonical_name") == name:
            return definition
    return None


def resolve_feature_request(
    requested: str,
    parameters: Optional[Mapping[str, Any]] = None,
    *,
    authority: str = "active",
    physical_alias: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve a canonical request or compatibility alias through one API.

    The returned ``physical_alias`` is an output name only.  No caller should
    infer lifecycle, provider, timing or parameters from that spelling.
    """
    bundle = _canonical_bundle(authority)
    supplied = dict(parameters or {})
    if bundle is None:
        if authority == "legacy" and requested in LEGACY_FEATURE_INSTANCE_OVERRIDES:
            instance = LEGACY_FEATURE_INSTANCE_OVERRIDES[requested]
            resolved = resolve_feature_request(instance.canonical_name, instance.parameters, authority="active")
            resolved.update({"requested": requested, "physical_alias": requested,
                             "parameters": dict(instance.parameters), "legacy_mode": True})
            return resolved
        # Compatibility path is available only for explicit legacy replay.
        if requested not in FEATURE_REGISTRY:
            raise FeatureInstanceError(f"FEATURE_NOT_REGISTERED: {requested!r}")
        definition = FEATURE_REGISTRY[requested]
        return {
            "requested": requested, "canonical_name": requested,
            "parameters": supplied, "physical_alias": requested,
            "provider": definition.implementation, "family": definition.family,
            "dtype": definition.dtype, "status": definition.status,
            "input_requirements": {"required_streams": [f"completed_{definition.source_timeframe}"]},
        }

    definition = None
    canonical_definition = _canonical_definition_by_name(bundle, requested)
    # Explicit study instances may retain a historical physical output alias.
    # Resolve it only through the active bundle's deterministic compatibility
    # record; this is not a legacy-universe fallback and never consults the
    # archived registry.
    if canonical_definition is None and requested in bundle.get("aliases", {}).get("aliases", {}):
        record = bundle["aliases"]["aliases"][requested]
        canonical_name = str(record["canonical_feature"])
        definition = _canonical_definition_by_name(bundle, canonical_name)
        supplied = dict(record.get("parameters", {})) | supplied
        physical_alias = physical_alias or requested
        resolved_parameters = validate_feature_instance(FeatureInstance(canonical_name, supplied))
    elif canonical_definition is None and (_INSTANCE_NAME_RE.search(requested) or _TEMPORAL_NAME_RE.search(requested)):
        # Active resolution intentionally does not load or consult the legacy
        # alias map.  Migration guidance is provided by feature_ctl; runtime
        # rejects the instance-shaped request fail-closed.
        raise FeatureInstanceError(
            f"LEGACY_FEATURE_ALIAS_NOT_ALLOWED: {requested!r}; declare canonical "
            "FeatureInstances or invoke explicit legacy replay mode"
        )
    elif definition is None:
        canonical_name = requested
        definition = canonical_definition or _canonical_definition_by_name(bundle, canonical_name)
        if definition is None:
            raise FeatureInstanceError(f"UNKNOWN_CANONICAL_FEATURE: {requested!r}")
        # Canonical instances must be validated at the authority boundary.  A
        # bare canonical name is retained only for collection-universe
        # enumeration (where the caller is asking for definitions, not an
        # executable instance); any request carrying parameters is a real
        # FeatureInstance and must fail closed on unsupported temporal/domain
        # combinations.
        if supplied:
            normalized = validate_feature_instance(
                FeatureInstance(canonical_name, supplied)
            )
            resolved_parameters = normalized
        else:
            resolved_parameters = supplied
        # Active canonical requests never resolve through the historical alias
        # map.  A physical alias is only an explicit legacy-replay concern.
        physical_alias = physical_alias or canonical_name
    if definition is None or definition.get("status") != "verified":
        raise FeatureInstanceError(f"UNVERIFIED_CANONICAL_FEATURE: {canonical_name}")
    return {
        "requested": requested, "canonical_name": canonical_name,
        "parameters": resolved_parameters, "physical_alias": physical_alias,
        "provider": definition.get("provider", ""), "family": definition.get("family", ""),
        "dtype": definition.get("dtype", "float64"), "status": definition.get("status"),
        "input_requirements": derive_resolved_input_requirements(
            canonical_name, resolved_parameters, definition),
    }


def derive_resolved_input_requirements(
    canonical_name: str, parameters: Mapping[str, Any], definition: Mapping[str, Any],
) -> Dict[str, Any]:
    """Derive runtime requirements from instance parameters, never alias text."""
    params = dict(parameters)
    streams: Set[str] = set()
    # OHLCV rolling aliases historically encoded the trailing duration in the
    # `timeframe` parameter.  The provider consumes completed 1s bars; expose
    # that true causal requirement without changing the historical alias or
    # values.  New instances should use `window` explicitly.
    rolling_legacy = params.get("context") == "rolling" and "timeframe" in params
    if "window" in params or rolling_legacy:
        window = params.get("window", params.get("timeframe"))
        streams.add("completed_1s")
        temporal = {"window_type": "rolling", "window": window,
                    "update_every": params.get("update_every", "1s")}
    else:
        temporal = {}
        for key, state_key in (("timeframe", "bar_state"), ("source_timeframe", "source_bar_state"),
                               ("reference_timeframe", "reference_bar_state")):
            if key in params:
                streams.add(f"{params.get(state_key, 'completed')}_{params[key]}")
        if not streams:
            for requirement in definition.get("input_availability_contracts", []):
                streams.add(f"completed_{requirement}")
    return {"canonical_name": canonical_name, "provider": definition.get("provider", ""),
            "required_streams": sorted(streams), **temporal}


def resolve_runtime_feature_definition(requested: str, *, authority: str = "active") -> FeatureDefinition:
    """Return canonical-authorized metadata for a pipeline binding.

    This intentionally constructs the narrow legacy-compatible record required
    by older tracker binders while authorization remains canonical.  Direct
    consumers must call this rather than indexing ``FEATURE_REGISTRY``.
    """
    resolved = resolve_feature_request(requested, authority=authority)
    return FeatureDefinition(
        name=resolved["physical_alias"], status=resolved["status"],
        family=resolved["family"], implementation=resolved["provider"],
        dtype=resolved["dtype"], source_timeframe="1s",
        update_anchor="canonical_instance_contract", null_policy="allow",
    )


def resolve_runtime_feature_aliases(
    source: Optional[str] = "canonical_verified_definition_universe", *, authority: str = "active",
) -> List[str]:
    """Return the physical output aliases permitted by the selected authority."""
    return resolve_source_universe(source, authority=authority)


def resolve_runtime_family_aliases(families: Set[str], *, authority: str = "active") -> List[str]:
    """Filter resolved aliases by canonical family without alias-name parsing."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return sorted(name for name, definition in FEATURE_REGISTRY.items() if definition.family in families)
    definitions = {item["canonical_name"]: item for item in bundle["registry"].get("definitions", [])}
    return sorted(name for name, definition in definitions.items()
                  if set(definition.get("family", [])) & set(families)
                  and definition.get("status") == "verified")


def resolve_feature_engine_output_aliases(*, authority: str = "active") -> List[str]:
    """Resolve the physical surface implemented by the shared FeatureEngine.

    The canonical universe has 693 compatible aliases, while this particular
    engine deliberately implements the historical 532-column collector
    surface. Its capability is declared once here from compatibility
    implementation metadata and intersected with canonical authority; callers
    neither parse names nor widen a collector merely because an alias exists.
    """
    bundle = _canonical_bundle(authority)
    if bundle is not None:
        implemented = {item["canonical_name"] for item in bundle["registry"].get("definitions", [])
                       if item.get("status") == "verified"}
    else:
        implemented = {name for name, definition in FEATURE_REGISTRY.items()
                       if definition.status == "verified" and definition.implementation}
    allowed = set(resolve_runtime_feature_aliases(authority=authority))
    return sorted(implemented & allowed)


def provider_compatibility_keys(canonical_name: str, *, authority: str = "active") -> List[str]:
    """Implementation-only adapter for providers retaining historical field labels."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return []
    return sorted(alias for alias, record in bundle.get("aliases", {}).get("aliases", {}).items()
                  if record.get("canonical_feature") == canonical_name)


def canonicalize_provider_columns(columns: Iterable[str], *, authority: str = "active") -> Dict[str, str]:
    """Map provider compatibility labels to canonical output labels at the boundary."""
    bundle = _canonical_bundle(authority)
    if bundle is None:
        return {name: name for name in columns}
    aliases = bundle.get("aliases", {}).get("aliases", {})
    return {name: aliases.get(name, {}).get("canonical_feature", name) for name in columns}


def derive_study_feature_requirements(features_spec: Any, *, authority: str = "active") -> Dict[str, Any]:
    """Derive collector streams/windows exclusively from study-local instances.

    A legacy feature_list is resolved through compatibility mapping.  A source
    universe without explicit instances returns its declared aliases but does
    not guess provider-internal requirements from alias text.
    """
    requests: List[Tuple[str, Mapping[str, Any], Optional[str]]] = []
    for item in (getattr(features_spec, "instances", None) or []):
        requests.append((str(item["feature"]), dict(item.get("parameters", {})), item.get("physical_alias")))
    for alias in (getattr(features_spec, "feature_list", None) or []):
        requests.append((str(alias), {}, None))
    resolved = []
    for name, params, alias in requests:
        item = resolve_feature_request(name, params, authority=authority, physical_alias=alias)
        # Canonical instances receive the deterministic compatibility/output alias
        # generated from their parameters.  A caller-provided physical_alias remains
        # an explicit compatibility override.
        if alias is None and name in CANONICAL_FEATURE_DEFINITIONS:
            item["physical_alias"] = generate_physical_alias(
                FeatureInstance(name, params)
            )
        resolved.append(item)
    streams: Set[str] = set()
    rolling_windows: Set[str] = set()
    for item in resolved:
        requirements = item["input_requirements"]
        streams.update(requirements.get("required_streams", []))
        if requirements.get("window"):
            rolling_windows.add(str(requirements["window"]))
    return {"resolved_instances": resolved, "required_streams": sorted(streams),
            "rolling_windows": sorted(rolling_windows),
            "aliases": [item["physical_alias"] for item in resolved]}


def validate_canonical_feature_name(definition: FeatureDefinition) -> None:
    """Reject temporal instance tokens in new canonical names unless documented.

    Existing physical FEATURE_REGISTRY aliases predate V2 and are intentionally not
    subjected to this rule.  New canonical definitions must keep time/window/context
    in FeatureInstance.parameters, with an explicit exception for a genuinely intrinsic
    temporal formula.
    """
    if (_TEMPORAL_NAME_RE.search(definition.name) or _INSTANCE_NAME_RE.search(definition.name)) and not definition.temporal_identity_exception:
        raise FeatureInstanceError(
            f"FEATURE_NAME_EMBEDS_TEMPORAL_INSTANCE: {definition.name!r}; move timeframe/window to FeatureInstance parameters or document temporal_identity_exception"
        )


# ---------------------------------------------------------------------------
# Snapshot-anchor binding (nt_live_scoring_infra_prereqs Phase 2) -- codifies
# FEATURE_REGISTRY_CONTRACT.md section 6's existing deferral ("Exact snapshot
# timings must remain part of the study-specific contract") as actual data
# instead of leaving it narrative-only. A registry entry's own
# `snapshot_anchor` field stays a shared class-level default
# ('caller_defined' unless set otherwise); a consuming study declares WHEN
# IT snaps a given feature via `bind_snapshot_anchor`, without ever
# mutating the shared `FeatureDefinition` object other studies also read.
# ---------------------------------------------------------------------------
_SNAPSHOT_ANCHOR_BINDINGS: Dict[Tuple[str, str], str] = {}


def bind_snapshot_anchor(feature_name: str, study_name: str, anchor: str) -> None:
    """Declare that `study_name` snaps `feature_name` at `anchor` (e.g.
    'at_signal_decision_ts', 'at_touch_time', 'at_fill_time'). Raises if
    the feature isn't registered -- a study cannot bind a snapshot anchor
    for a feature that doesn't exist."""
    try:
        resolved = resolve_feature_request(feature_name)
    except FeatureInstanceError as exc:
        raise KeyError(f"cannot bind snapshot anchor for unregistered feature {feature_name!r}") from exc
    _SNAPSHOT_ANCHOR_BINDINGS[(resolved["physical_alias"], study_name)] = anchor


def effective_snapshot_anchor(feature_name: str, study_name: str) -> str:
    """The snapshot anchor `study_name` actually uses for `feature_name`:
    its own declared binding if one was made via `bind_snapshot_anchor`,
    else the registry entry's shared class-level default."""
    try:
        resolved = resolve_feature_request(feature_name)
    except FeatureInstanceError as exc:
        raise KeyError(f"unregistered feature {feature_name!r}") from exc
    key = (resolved["physical_alias"], study_name)
    if key in _SNAPSHOT_ANCHOR_BINDINGS:
        return _SNAPSHOT_ANCHOR_BINDINGS[key]
    # Canonical definitions place timing in their instance input contract;
    # legacy pre-cutover records retain their historical default only behind
    # this boundary.
    return "canonical_instance_contract" if _canonical_bundle("active") else FEATURE_REGISTRY[feature_name].snapshot_anchor

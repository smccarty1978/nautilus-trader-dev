# Feature Schema — OHLCV Volume/Delta & Price-Level Context

Generated from `features/registry.py` — 461 new features (214 in `ohlcv_est_delta`, 247 in `price_level_context`). Regenerate with `python generate_schema.py` after any registry change; never hand-edit `feature_schema.csv`.

## `ohlcv_est_delta` (214 features)

### bar_level (6)

Per-bar estimated bull/bear volume split by close position within the bar's own high-low range.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `bar_est_bear_volume` | object | contracts | - | 1s | study_contract |
| `bar_est_bull_volume` | object | contracts | - | 1s | study_contract |
| `bar_est_delta` | object | float | - | 1s | study_contract |
| `bar_est_delta_ratio` | object | ratio | - | 1s | study_contract |
| `bar_volume` | object | contracts | - | 1s | study_contract |
| `bar_zero_range` | object | bool | - | 1s | study_contract |

### cross_window (5)

Short-vs-long window comparison (e.g. 15s minus 60s) capturing pressure divergence.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `est_delta_sum_15s_minus_60s_scaled` | object | float | 15s | 1s | study_contract |
| `est_delta_sum_30s_minus_120s_scaled` | object | float | 30s | 1s | study_contract |
| `est_delta_sum_60s_minus_300s_scaled` | object | float | 60s | 1s | study_contract |
| `vol_sum_30s_vs_300s_ratio` | object | contracts | 30s | 1s | study_contract |
| `vol_sum_60s_vs_900s_ratio` | object | contracts | 60s | 1s | study_contract |

### regime_relative (17)

Cumulative volume/delta since the current prevailing 1m regime began, reset on regime change.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `regime_abs_delta_per_atr_moved` | object | ATR | - | 1m | study_contract |
| `regime_available` | object | bool | - | 1m | study_contract |
| `regime_elapsed_seconds` | object | seconds | - | 1m | study_contract |
| `regime_est_abs_delta_sum` | object | float | - | 1m | study_contract |
| `regime_est_delta_ratio` | object | ratio | - | 1m | study_contract |
| `regime_est_delta_sum` | object | float | - | 1m | study_contract |
| `regime_first_half_est_delta_ratio` | object | ratio | - | 1m | study_contract |
| `regime_first_half_vol` | object | contracts | - | 1m | study_contract |
| `regime_late_minus_early_delta_ratio` | object | ratio | - | 1m | study_contract |
| `regime_late_vs_early_vol_ratio` | object | contracts | - | 1m | study_contract |
| `regime_price_change_atr` | object | ATR | - | 1m | study_contract |
| `regime_range_atr` | object | ATR | - | 1m | study_contract |
| `regime_second_half_est_delta_ratio` | object | ratio | - | 1m | study_contract |
| `regime_second_half_vol` | object | contracts | - | 1m | study_contract |
| `regime_vol_sum` | object | contracts | - | 1m | study_contract |
| `regime_volume_per_atr_moved` | object | ATR | - | 1m | study_contract |
| `regime_volume_per_second` | object | contracts | - | 1m | study_contract |

### rolling_window (179)

Rolling completed-time-window aggregate over 1s bars (5s-1800s).

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `abs_delta_per_atr_moved_120s` | object | ATR | 120s | 1s | study_contract |
| `abs_delta_per_atr_moved_15s` | object | ATR | 15s | 1s | study_contract |
| `abs_delta_per_atr_moved_1800s` | object | ATR | 1800s | 1s | study_contract |
| `abs_delta_per_atr_moved_300s` | object | ATR | 300s | 1s | study_contract |
| `abs_delta_per_atr_moved_30s` | object | ATR | 30s | 1s | study_contract |
| `abs_delta_per_atr_moved_5s` | object | ATR | 5s | 1s | study_contract |
| `abs_delta_per_atr_moved_60s` | object | ATR | 60s | 1s | study_contract |
| `abs_delta_per_atr_moved_900s` | object | ATR | 900s | 1s | study_contract |
| `abs_delta_per_point_moved_120s` | object | float | 120s | 1s | study_contract |
| `abs_delta_per_point_moved_15s` | object | float | 15s | 1s | study_contract |
| `abs_delta_per_point_moved_1800s` | object | float | 1800s | 1s | study_contract |
| `abs_delta_per_point_moved_300s` | object | float | 300s | 1s | study_contract |
| `abs_delta_per_point_moved_30s` | object | float | 30s | 1s | study_contract |
| `abs_delta_per_point_moved_5s` | object | float | 5s | 1s | study_contract |
| `abs_delta_per_point_moved_60s` | object | float | 60s | 1s | study_contract |
| `abs_delta_per_point_moved_900s` | object | float | 900s | 1s | study_contract |
| `downbar_vol_sum_120s` | object | contracts | 120s | 1s | study_contract |
| `downbar_vol_sum_15s` | object | contracts | 15s | 1s | study_contract |
| `downbar_vol_sum_1800s` | object | contracts | 1800s | 1s | study_contract |
| `downbar_vol_sum_300s` | object | contracts | 300s | 1s | study_contract |
| `downbar_vol_sum_30s` | object | contracts | 30s | 1s | study_contract |
| `downbar_vol_sum_5s` | object | contracts | 5s | 1s | study_contract |
| `downbar_vol_sum_60s` | object | contracts | 60s | 1s | study_contract |
| `downbar_vol_sum_900s` | object | contracts | 900s | 1s | study_contract |
| `est_abs_delta_sum_120s` | object | float | 120s | 1s | study_contract |
| `est_abs_delta_sum_15s` | object | float | 15s | 1s | study_contract |
| `est_abs_delta_sum_1800s` | object | float | 1800s | 1s | study_contract |
| `est_abs_delta_sum_300s` | object | float | 300s | 1s | study_contract |
| `est_abs_delta_sum_30s` | object | float | 30s | 1s | study_contract |
| `est_abs_delta_sum_5s` | object | float | 5s | 1s | study_contract |
| `est_abs_delta_sum_60s` | object | float | 60s | 1s | study_contract |
| `est_abs_delta_sum_900s` | object | float | 900s | 1s | study_contract |
| `est_bear_vol_sum_120s` | object | contracts | 120s | 1s | study_contract |
| `est_bear_vol_sum_15s` | object | contracts | 15s | 1s | study_contract |
| `est_bear_vol_sum_1800s` | object | contracts | 1800s | 1s | study_contract |
| `est_bear_vol_sum_300s` | object | contracts | 300s | 1s | study_contract |
| `est_bear_vol_sum_30s` | object | contracts | 30s | 1s | study_contract |
| `est_bear_vol_sum_5s` | object | contracts | 5s | 1s | study_contract |
| `est_bear_vol_sum_60s` | object | contracts | 60s | 1s | study_contract |
| `est_bear_vol_sum_900s` | object | contracts | 900s | 1s | study_contract |
| `est_bull_vol_sum_120s` | object | contracts | 120s | 1s | study_contract |
| `est_bull_vol_sum_15s` | object | contracts | 15s | 1s | study_contract |
| `est_bull_vol_sum_1800s` | object | contracts | 1800s | 1s | study_contract |
| `est_bull_vol_sum_300s` | object | contracts | 300s | 1s | study_contract |
| `est_bull_vol_sum_30s` | object | contracts | 30s | 1s | study_contract |
| `est_bull_vol_sum_5s` | object | contracts | 5s | 1s | study_contract |
| `est_bull_vol_sum_60s` | object | contracts | 60s | 1s | study_contract |
| `est_bull_vol_sum_900s` | object | contracts | 900s | 1s | study_contract |
| `est_delta_neg_sum_120s` | object | float | 120s | 1s | study_contract |
| `est_delta_neg_sum_15s` | object | float | 15s | 1s | study_contract |
| `est_delta_neg_sum_1800s` | object | float | 1800s | 1s | study_contract |
| `est_delta_neg_sum_300s` | object | float | 300s | 1s | study_contract |
| `est_delta_neg_sum_30s` | object | float | 30s | 1s | study_contract |
| `est_delta_neg_sum_5s` | object | float | 5s | 1s | study_contract |
| `est_delta_neg_sum_60s` | object | float | 60s | 1s | study_contract |
| `est_delta_neg_sum_900s` | object | float | 900s | 1s | study_contract |
| `est_delta_pos_sum_120s` | object | float | 120s | 1s | study_contract |
| `est_delta_pos_sum_15s` | object | float | 15s | 1s | study_contract |
| `est_delta_pos_sum_1800s` | object | float | 1800s | 1s | study_contract |
| `est_delta_pos_sum_300s` | object | float | 300s | 1s | study_contract |
| `est_delta_pos_sum_30s` | object | float | 30s | 1s | study_contract |
| `est_delta_pos_sum_5s` | object | float | 5s | 1s | study_contract |
| `est_delta_pos_sum_60s` | object | float | 60s | 1s | study_contract |
| `est_delta_pos_sum_900s` | object | float | 900s | 1s | study_contract |
| `est_delta_ratio_120s` | object | ratio | 120s | 1s | study_contract |
| `est_delta_ratio_15s` | object | ratio | 15s | 1s | study_contract |
| `est_delta_ratio_15s_minus_60s` | object | ratio | 15s | 1s | study_contract |
| `est_delta_ratio_1800s` | object | ratio | 1800s | 1s | study_contract |
| `est_delta_ratio_300s` | object | ratio | 300s | 1s | study_contract |
| `est_delta_ratio_30s` | object | ratio | 30s | 1s | study_contract |
| `est_delta_ratio_30s_minus_120s` | object | ratio | 30s | 1s | study_contract |
| `est_delta_ratio_5s` | object | ratio | 5s | 1s | study_contract |
| `est_delta_ratio_60s` | object | ratio | 60s | 1s | study_contract |
| `est_delta_ratio_60s_minus_300s` | object | ratio | 60s | 1s | study_contract |
| `est_delta_ratio_900s` | object | ratio | 900s | 1s | study_contract |
| `est_delta_sum_120s` | object | float | 120s | 1s | study_contract |
| `est_delta_sum_15s` | object | float | 15s | 1s | study_contract |
| `est_delta_sum_1800s` | object | float | 1800s | 1s | study_contract |
| `est_delta_sum_300s` | object | float | 300s | 1s | study_contract |
| `est_delta_sum_30s` | object | float | 30s | 1s | study_contract |
| `est_delta_sum_5s` | object | float | 5s | 1s | study_contract |
| `est_delta_sum_60s` | object | float | 60s | 1s | study_contract |
| `est_delta_sum_900s` | object | float | 900s | 1s | study_contract |
| `price_change_atr_120s` | object | ATR | 120s | 1s | study_contract |
| `price_change_atr_15s` | object | ATR | 15s | 1s | study_contract |
| `price_change_atr_1800s` | object | ATR | 1800s | 1s | study_contract |
| `price_change_atr_300s` | object | ATR | 300s | 1s | study_contract |
| `price_change_atr_30s` | object | ATR | 30s | 1s | study_contract |
| `price_change_atr_5s` | object | ATR | 5s | 1s | study_contract |
| `price_change_atr_60s` | object | ATR | 60s | 1s | study_contract |
| `price_change_atr_900s` | object | ATR | 900s | 1s | study_contract |
| `price_change_points_120s` | object | points | 120s | 1s | study_contract |
| `price_change_points_15s` | object | points | 15s | 1s | study_contract |
| `price_change_points_1800s` | object | points | 1800s | 1s | study_contract |
| `price_change_points_300s` | object | points | 300s | 1s | study_contract |
| `price_change_points_30s` | object | points | 30s | 1s | study_contract |
| `price_change_points_5s` | object | points | 5s | 1s | study_contract |
| `price_change_points_60s` | object | points | 60s | 1s | study_contract |
| `price_change_points_900s` | object | points | 900s | 1s | study_contract |
| `range_atr_120s` | object | ATR | 120s | 1s | study_contract |
| `range_atr_15s` | object | ATR | 15s | 1s | study_contract |
| `range_atr_1800s` | object | ATR | 1800s | 1s | study_contract |
| `range_atr_300s` | object | ATR | 300s | 1s | study_contract |
| `range_atr_30s` | object | ATR | 30s | 1s | study_contract |
| `range_atr_5s` | object | ATR | 5s | 1s | study_contract |
| `range_atr_60s` | object | ATR | 60s | 1s | study_contract |
| `range_atr_900s` | object | ATR | 900s | 1s | study_contract |
| `range_points_120s` | object | points | 120s | 1s | study_contract |
| `range_points_15s` | object | points | 15s | 1s | study_contract |
| `range_points_1800s` | object | points | 1800s | 1s | study_contract |
| `range_points_300s` | object | points | 300s | 1s | study_contract |
| `range_points_30s` | object | points | 30s | 1s | study_contract |
| `range_points_5s` | object | points | 5s | 1s | study_contract |
| `range_points_60s` | object | points | 60s | 1s | study_contract |
| `range_points_900s` | object | points | 900s | 1s | study_contract |
| `up_down_vol_ratio_120s` | object | contracts | 120s | 1s | study_contract |
| `up_down_vol_ratio_15s` | object | contracts | 15s | 1s | study_contract |
| `up_down_vol_ratio_1800s` | object | contracts | 1800s | 1s | study_contract |
| `up_down_vol_ratio_300s` | object | contracts | 300s | 1s | study_contract |
| `up_down_vol_ratio_30s` | object | contracts | 30s | 1s | study_contract |
| `up_down_vol_ratio_5s` | object | contracts | 5s | 1s | study_contract |
| `up_down_vol_ratio_60s` | object | contracts | 60s | 1s | study_contract |
| `up_down_vol_ratio_900s` | object | contracts | 900s | 1s | study_contract |
| `upbar_vol_sum_120s` | object | contracts | 120s | 1s | study_contract |
| `upbar_vol_sum_15s` | object | contracts | 15s | 1s | study_contract |
| `upbar_vol_sum_1800s` | object | contracts | 1800s | 1s | study_contract |
| `upbar_vol_sum_300s` | object | contracts | 300s | 1s | study_contract |
| `upbar_vol_sum_30s` | object | contracts | 30s | 1s | study_contract |
| `upbar_vol_sum_5s` | object | contracts | 5s | 1s | study_contract |
| `upbar_vol_sum_60s` | object | contracts | 60s | 1s | study_contract |
| `upbar_vol_sum_900s` | object | contracts | 900s | 1s | study_contract |
| `vol_max_1s_120s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_15s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_1800s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_300s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_30s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_5s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_60s` | object | contracts | 1s | 1s | study_contract |
| `vol_max_1s_900s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_120s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_15s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_1800s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_300s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_30s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_5s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_60s` | object | contracts | 1s | 1s | study_contract |
| `vol_mean_1s_900s` | object | contracts | 1s | 1s | study_contract |
| `vol_sum_120s` | object | contracts | 120s | 1s | study_contract |
| `vol_sum_15s` | object | contracts | 15s | 1s | study_contract |
| `vol_sum_1800s` | object | contracts | 1800s | 1s | study_contract |
| `vol_sum_300s` | object | contracts | 300s | 1s | study_contract |
| `vol_sum_30s` | object | contracts | 30s | 1s | study_contract |
| `vol_sum_5s` | object | contracts | 5s | 1s | study_contract |
| `vol_sum_60s` | object | contracts | 60s | 1s | study_contract |
| `vol_sum_900s` | object | contracts | 900s | 1s | study_contract |
| `volume_per_atr_moved_120s` | object | ATR | 120s | 1s | study_contract |
| `volume_per_atr_moved_15s` | object | ATR | 15s | 1s | study_contract |
| `volume_per_atr_moved_1800s` | object | ATR | 1800s | 1s | study_contract |
| `volume_per_atr_moved_300s` | object | ATR | 300s | 1s | study_contract |
| `volume_per_atr_moved_30s` | object | ATR | 30s | 1s | study_contract |
| `volume_per_atr_moved_5s` | object | ATR | 5s | 1s | study_contract |
| `volume_per_atr_moved_60s` | object | ATR | 60s | 1s | study_contract |
| `volume_per_atr_moved_900s` | object | ATR | 900s | 1s | study_contract |
| `volume_per_point_moved_120s` | object | contracts | 120s | 1s | study_contract |
| `volume_per_point_moved_15s` | object | contracts | 15s | 1s | study_contract |
| `volume_per_point_moved_1800s` | object | contracts | 1800s | 1s | study_contract |
| `volume_per_point_moved_300s` | object | contracts | 300s | 1s | study_contract |
| `volume_per_point_moved_30s` | object | contracts | 30s | 1s | study_contract |
| `volume_per_point_moved_5s` | object | contracts | 5s | 1s | study_contract |
| `volume_per_point_moved_60s` | object | contracts | 60s | 1s | study_contract |
| `volume_per_point_moved_900s` | object | contracts | 900s | 1s | study_contract |
| `window_available_120s` | object | bool | 120s | 1s | study_contract |
| `window_available_15s` | object | bool | 15s | 1s | study_contract |
| `window_available_1800s` | object | bool | 1800s | 1s | study_contract |
| `window_available_300s` | object | bool | 300s | 1s | study_contract |
| `window_available_30s` | object | bool | 30s | 1s | study_contract |
| `window_available_5s` | object | bool | 5s | 1s | study_contract |
| `window_available_60s` | object | bool | 60s | 1s | study_contract |
| `window_available_900s` | object | bool | 900s | 1s | study_contract |

### rth_cumulative (7)

Cumulative volume/delta since the current RTH session began, reset each session.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `rth_abs_delta_cum` | object | float | - | 1s | study_contract |
| `rth_available` | object | bool | - | 1s | study_contract |
| `rth_elapsed_seconds` | object | seconds | - | 1s | study_contract |
| `rth_est_delta_cum` | object | float | - | 1s | study_contract |
| `rth_est_delta_ratio_cum` | object | ratio | - | 1s | study_contract |
| `rth_vol_cum` | object | contracts | - | 1s | study_contract |
| `rth_volume_per_second` | object | contracts | - | 1s | study_contract |

## `price_level_context` (247 features)

### aggregate_counts (14)

Count/percent of raw levels above, below, or touched by the reference price, plus level_balance.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `level_balance` | object | float | - | 1m | study_contract |
| `n_levels_above` | object | count | - | 1m | study_contract |
| `n_levels_available` | object | bool | - | 1m | study_contract |
| `n_levels_below` | object | count | - | 1m | study_contract |
| `n_levels_touched` | object | count | - | 1m | study_contract |
| `n_prior_day_levels_above` | object | count | - | 1m | study_contract |
| `n_prior_day_levels_below` | object | count | - | 1m | study_contract |
| `n_rolling_levels_above` | object | count | - | 1m | study_contract |
| `n_rolling_levels_below` | object | count | - | 1m | study_contract |
| `n_session_levels_above` | object | count | - | 1m | study_contract |
| `n_session_levels_below` | object | count | - | 1m | study_contract |
| `pct_levels_above` | object | fraction[0,1] | - | 1m | study_contract |
| `pct_levels_below` | object | fraction[0,1] | - | 1m | study_contract |
| `pct_levels_touched` | object | fraction[0,1] | - | 1m | study_contract |

### clustering (15)

Deterministic median-price clustering of nearby raw levels, and nearest-cluster geometry.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `max_cluster_strength` | object | float | - | 1m | study_contract |
| `max_nearby_cluster_strength_050a` | object | float | - | 1m | study_contract |
| `max_nearby_cluster_strength_100a` | object | float | - | 1m | study_contract |
| `n_level_clusters_above` | object | count | - | 1m | study_contract |
| `n_level_clusters_available` | object | bool | - | 1m | study_contract |
| `n_level_clusters_below` | object | count | - | 1m | study_contract |
| `n_level_clusters_touched` | object | count | - | 1m | study_contract |
| `nearest_cluster_above_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_cluster_above_price` | object | float | - | 1m | study_contract |
| `nearest_cluster_above_strength` | object | float | - | 1m | study_contract |
| `nearest_cluster_ahead_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_cluster_behind_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_cluster_below_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_cluster_below_price` | object | float | - | 1m | study_contract |
| `nearest_cluster_below_strength` | object | float | - | 1m | study_contract |

### density_envelope (20)

Level density within fixed ATR bands, plus the full level envelope (lowest/highest available level).

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `distance_above_full_envelope_atr` | object | ATR | - | 1m | study_contract |
| `distance_below_full_envelope_atr` | object | ATR | - | 1m | study_contract |
| `full_level_envelope_width_atr` | object | ATR | - | 1m | study_contract |
| `full_level_envelope_width_points` | object | points | - | 1m | study_contract |
| `highest_available_level` | object | bool | - | 1m | study_contract |
| `inverse_distance_density` | object | float | - | 1m | study_contract |
| `level_density_025a` | object | float | - | 1m | study_contract |
| `level_density_050a` | object | float | - | 1m | study_contract |
| `level_density_100a` | object | float | - | 1m | study_contract |
| `level_density_200a` | object | float | - | 1m | study_contract |
| `levels_above_within_025a` | object | count | - | 1m | study_contract |
| `levels_above_within_050a` | object | count | - | 1m | study_contract |
| `levels_above_within_100a` | object | count | - | 1m | study_contract |
| `levels_above_within_200a` | object | count | - | 1m | study_contract |
| `levels_below_within_025a` | object | count | - | 1m | study_contract |
| `levels_below_within_050a` | object | count | - | 1m | study_contract |
| `levels_below_within_100a` | object | count | - | 1m | study_contract |
| `levels_below_within_200a` | object | count | - | 1m | study_contract |
| `lowest_available_level` | object | bool | - | 1m | study_contract |
| `price_position_in_full_envelope` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |

### direction_normalized (7)

Ahead/behind reframing of levels relative to a known trade direction (short: ahead=below).

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `directional_space_balance_atr` | object | ATR | - | 1m | study_contract |
| `levels_ahead_of_trade` | object | float | - | 1m | study_contract |
| `levels_behind_trade` | object | float | - | 1m | study_contract |
| `nearest_level_ahead_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_level_behind_distance_atr` | object | ATR | - | 1m | study_contract |
| `pct_levels_ahead_of_trade` | object | fraction[0,1] | - | 1m | study_contract |
| `pct_levels_behind_trade` | object | fraction[0,1] | - | 1m | study_contract |

### nearest_geometry (13)

Nearest raw level above/below the reference price and the resulting space balance.

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `nearest_level_above_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_level_above_distance_points` | object | points | - | 1m | study_contract |
| `nearest_level_above_distance_ticks` | object | ticks | - | 1m | study_contract |
| `nearest_level_above_name` | object | str | - | 1m | study_contract |
| `nearest_level_above_price` | object | float | - | 1m | study_contract |
| `nearest_level_below_distance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_level_below_distance_points` | object | points | - | 1m | study_contract |
| `nearest_level_below_distance_ticks` | object | ticks | - | 1m | study_contract |
| `nearest_level_below_name` | object | str | - | 1m | study_contract |
| `nearest_level_below_price` | object | float | - | 1m | study_contract |
| `nearest_space_balance_atr` | object | ATR | - | 1m | study_contract |
| `nearest_space_total_atr` | object | ATR | - | 1m | study_contract |
| `nearest_upside_downside_ratio` | object | ratio | - | 1m | study_contract |

### per_level_distance (174)

Price/availability/signed-distance/position for one approved base level (prior-day, overnight, RTH open, opening range, or rolling-window OHLC).

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `opening_range_30m_high_developing_available` | object | bool | 30m | 1m | study_contract |
| `opening_range_30m_high_developing_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `opening_range_30m_high_developing_price` | object | float | 30m | 1m | study_contract |
| `opening_range_30m_high_developing_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `opening_range_30m_high_developing_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `opening_range_30m_high_developing_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `opening_range_30m_high_final_available` | object | bool | 30m | 1m | study_contract |
| `opening_range_30m_high_final_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `opening_range_30m_high_final_price` | object | float | 30m | 1m | study_contract |
| `opening_range_30m_high_final_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `opening_range_30m_high_final_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `opening_range_30m_high_final_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_available` | object | bool | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_price` | object | float | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `opening_range_30m_low_developing_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `opening_range_30m_low_final_available` | object | bool | 30m | 1m | study_contract |
| `opening_range_30m_low_final_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `opening_range_30m_low_final_price` | object | float | 30m | 1m | study_contract |
| `opening_range_30m_low_final_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `opening_range_30m_low_final_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `opening_range_30m_low_final_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `overnight_high_developing_available` | object | bool | - | 1m | study_contract |
| `overnight_high_developing_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `overnight_high_developing_price` | object | float | - | 1m | study_contract |
| `overnight_high_developing_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `overnight_high_developing_signed_distance_points` | object | points | - | 1m | study_contract |
| `overnight_high_developing_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `overnight_high_final_available` | object | bool | - | 1m | study_contract |
| `overnight_high_final_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `overnight_high_final_price` | object | float | - | 1m | study_contract |
| `overnight_high_final_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `overnight_high_final_signed_distance_points` | object | points | - | 1m | study_contract |
| `overnight_high_final_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `overnight_low_developing_available` | object | bool | - | 1m | study_contract |
| `overnight_low_developing_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `overnight_low_developing_price` | object | float | - | 1m | study_contract |
| `overnight_low_developing_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `overnight_low_developing_signed_distance_points` | object | points | - | 1m | study_contract |
| `overnight_low_developing_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `overnight_low_final_available` | object | bool | - | 1m | study_contract |
| `overnight_low_final_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `overnight_low_final_price` | object | float | - | 1m | study_contract |
| `overnight_low_final_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `overnight_low_final_signed_distance_points` | object | points | - | 1m | study_contract |
| `overnight_low_final_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `prior_day_close_available` | object | bool | - | 1m | study_contract |
| `prior_day_close_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `prior_day_close_price` | object | float | - | 1m | study_contract |
| `prior_day_close_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `prior_day_close_signed_distance_points` | object | points | - | 1m | study_contract |
| `prior_day_close_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `prior_day_high_available` | object | bool | - | 1m | study_contract |
| `prior_day_high_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `prior_day_high_price` | object | float | - | 1m | study_contract |
| `prior_day_high_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `prior_day_high_signed_distance_points` | object | points | - | 1m | study_contract |
| `prior_day_high_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `prior_day_low_available` | object | bool | - | 1m | study_contract |
| `prior_day_low_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `prior_day_low_price` | object | float | - | 1m | study_contract |
| `prior_day_low_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `prior_day_low_signed_distance_points` | object | points | - | 1m | study_contract |
| `prior_day_low_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `prior_day_open_available` | object | bool | - | 1m | study_contract |
| `prior_day_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `prior_day_open_price` | object | count | - | 1m | study_contract |
| `prior_day_open_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `prior_day_open_signed_distance_points` | object | points | - | 1m | study_contract |
| `prior_day_open_signed_distance_ticks` | object | ticks | - | 1m | study_contract |
| `rolling_15m_close_available` | object | bool | 15m | 1m | study_contract |
| `rolling_15m_close_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 15m | 1m | study_contract |
| `rolling_15m_close_price` | object | float | 15m | 1m | study_contract |
| `rolling_15m_close_signed_distance_atr` | object | ATR | 15m | 1m | study_contract |
| `rolling_15m_close_signed_distance_points` | object | points | 15m | 1m | study_contract |
| `rolling_15m_close_signed_distance_ticks` | object | ticks | 15m | 1m | study_contract |
| `rolling_15m_high_available` | object | bool | 15m | 1m | study_contract |
| `rolling_15m_high_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 15m | 1m | study_contract |
| `rolling_15m_high_price` | object | float | 15m | 1m | study_contract |
| `rolling_15m_high_signed_distance_atr` | object | ATR | 15m | 1m | study_contract |
| `rolling_15m_high_signed_distance_points` | object | points | 15m | 1m | study_contract |
| `rolling_15m_high_signed_distance_ticks` | object | ticks | 15m | 1m | study_contract |
| `rolling_15m_low_available` | object | bool | 15m | 1m | study_contract |
| `rolling_15m_low_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 15m | 1m | study_contract |
| `rolling_15m_low_price` | object | float | 15m | 1m | study_contract |
| `rolling_15m_low_signed_distance_atr` | object | ATR | 15m | 1m | study_contract |
| `rolling_15m_low_signed_distance_points` | object | points | 15m | 1m | study_contract |
| `rolling_15m_low_signed_distance_ticks` | object | ticks | 15m | 1m | study_contract |
| `rolling_15m_open_available` | object | bool | 15m | 1m | study_contract |
| `rolling_15m_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 15m | 1m | study_contract |
| `rolling_15m_open_price` | object | count | 15m | 1m | study_contract |
| `rolling_15m_open_signed_distance_atr` | object | ATR | 15m | 1m | study_contract |
| `rolling_15m_open_signed_distance_points` | object | points | 15m | 1m | study_contract |
| `rolling_15m_open_signed_distance_ticks` | object | ticks | 15m | 1m | study_contract |
| `rolling_30m_close_available` | object | bool | 30m | 1m | study_contract |
| `rolling_30m_close_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `rolling_30m_close_price` | object | float | 30m | 1m | study_contract |
| `rolling_30m_close_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `rolling_30m_close_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `rolling_30m_close_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `rolling_30m_high_available` | object | bool | 30m | 1m | study_contract |
| `rolling_30m_high_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `rolling_30m_high_price` | object | float | 30m | 1m | study_contract |
| `rolling_30m_high_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `rolling_30m_high_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `rolling_30m_high_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `rolling_30m_low_available` | object | bool | 30m | 1m | study_contract |
| `rolling_30m_low_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `rolling_30m_low_price` | object | float | 30m | 1m | study_contract |
| `rolling_30m_low_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `rolling_30m_low_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `rolling_30m_low_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `rolling_30m_open_available` | object | bool | 30m | 1m | study_contract |
| `rolling_30m_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 30m | 1m | study_contract |
| `rolling_30m_open_price` | object | count | 30m | 1m | study_contract |
| `rolling_30m_open_signed_distance_atr` | object | ATR | 30m | 1m | study_contract |
| `rolling_30m_open_signed_distance_points` | object | points | 30m | 1m | study_contract |
| `rolling_30m_open_signed_distance_ticks` | object | ticks | 30m | 1m | study_contract |
| `rolling_5m_close_available` | object | bool | 5m | 1m | study_contract |
| `rolling_5m_close_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 5m | 1m | study_contract |
| `rolling_5m_close_price` | object | float | 5m | 1m | study_contract |
| `rolling_5m_close_signed_distance_atr` | object | ATR | 5m | 1m | study_contract |
| `rolling_5m_close_signed_distance_points` | object | points | 5m | 1m | study_contract |
| `rolling_5m_close_signed_distance_ticks` | object | ticks | 5m | 1m | study_contract |
| `rolling_5m_high_available` | object | bool | 5m | 1m | study_contract |
| `rolling_5m_high_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 5m | 1m | study_contract |
| `rolling_5m_high_price` | object | float | 5m | 1m | study_contract |
| `rolling_5m_high_signed_distance_atr` | object | ATR | 5m | 1m | study_contract |
| `rolling_5m_high_signed_distance_points` | object | points | 5m | 1m | study_contract |
| `rolling_5m_high_signed_distance_ticks` | object | ticks | 5m | 1m | study_contract |
| `rolling_5m_low_available` | object | bool | 5m | 1m | study_contract |
| `rolling_5m_low_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 5m | 1m | study_contract |
| `rolling_5m_low_price` | object | float | 5m | 1m | study_contract |
| `rolling_5m_low_signed_distance_atr` | object | ATR | 5m | 1m | study_contract |
| `rolling_5m_low_signed_distance_points` | object | points | 5m | 1m | study_contract |
| `rolling_5m_low_signed_distance_ticks` | object | ticks | 5m | 1m | study_contract |
| `rolling_5m_open_available` | object | bool | 5m | 1m | study_contract |
| `rolling_5m_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 5m | 1m | study_contract |
| `rolling_5m_open_price` | object | count | 5m | 1m | study_contract |
| `rolling_5m_open_signed_distance_atr` | object | ATR | 5m | 1m | study_contract |
| `rolling_5m_open_signed_distance_points` | object | points | 5m | 1m | study_contract |
| `rolling_5m_open_signed_distance_ticks` | object | ticks | 5m | 1m | study_contract |
| `rolling_60m_close_available` | object | bool | 60m | 1m | study_contract |
| `rolling_60m_close_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 60m | 1m | study_contract |
| `rolling_60m_close_price` | object | float | 60m | 1m | study_contract |
| `rolling_60m_close_signed_distance_atr` | object | ATR | 60m | 1m | study_contract |
| `rolling_60m_close_signed_distance_points` | object | points | 60m | 1m | study_contract |
| `rolling_60m_close_signed_distance_ticks` | object | ticks | 60m | 1m | study_contract |
| `rolling_60m_high_available` | object | bool | 60m | 1m | study_contract |
| `rolling_60m_high_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 60m | 1m | study_contract |
| `rolling_60m_high_price` | object | float | 60m | 1m | study_contract |
| `rolling_60m_high_signed_distance_atr` | object | ATR | 60m | 1m | study_contract |
| `rolling_60m_high_signed_distance_points` | object | points | 60m | 1m | study_contract |
| `rolling_60m_high_signed_distance_ticks` | object | ticks | 60m | 1m | study_contract |
| `rolling_60m_low_available` | object | bool | 60m | 1m | study_contract |
| `rolling_60m_low_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 60m | 1m | study_contract |
| `rolling_60m_low_price` | object | float | 60m | 1m | study_contract |
| `rolling_60m_low_signed_distance_atr` | object | ATR | 60m | 1m | study_contract |
| `rolling_60m_low_signed_distance_points` | object | points | 60m | 1m | study_contract |
| `rolling_60m_low_signed_distance_ticks` | object | ticks | 60m | 1m | study_contract |
| `rolling_60m_open_available` | object | bool | 60m | 1m | study_contract |
| `rolling_60m_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | 60m | 1m | study_contract |
| `rolling_60m_open_price` | object | count | 60m | 1m | study_contract |
| `rolling_60m_open_signed_distance_atr` | object | ATR | 60m | 1m | study_contract |
| `rolling_60m_open_signed_distance_points` | object | points | 60m | 1m | study_contract |
| `rolling_60m_open_signed_distance_ticks` | object | ticks | 60m | 1m | study_contract |
| `rth_open_available` | object | bool | - | 1m | study_contract |
| `rth_open_position` | object | enum(ABOVE|BELOW|TOUCH|UNAVAILABLE) | - | 1m | study_contract |
| `rth_open_price` | object | count | - | 1m | study_contract |
| `rth_open_signed_distance_atr` | object | ATR | - | 1m | study_contract |
| `rth_open_signed_distance_points` | object | points | - | 1m | study_contract |
| `rth_open_signed_distance_ticks` | object | ticks | - | 1m | study_contract |

### session_state (4)

Session/opening-range state flags (developing vs. final, elapsed seconds).

| feature_name | dtype | units | window | source | normalization |
|---|---|---|---|---|---|
| `opening_range_30m_elapsed_seconds` | object | seconds | 30m | 1m | study_contract |
| `opening_range_30m_is_developing` | object | bool | 30m | 1m | study_contract |
| `opening_range_30m_is_final` | object | bool | 30m | 1m | study_contract |
| `rth_open_elapsed_seconds` | object | count | - | 1m | study_contract |

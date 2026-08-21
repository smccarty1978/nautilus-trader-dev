# NautilusTrader Feature Engineering Master Catalog

> **Comprehensive authoritative specification of all 110 registered indicators, stateful trackers, and multi-timeframe feature calculations in the NautilusTrader event-loop ecosystem.**

---

## 1. Feature Registry Overview (110 Total Features)

| Feature Name | Family | Timeframe | Stateful | Warmup | Normalizer | Description / Units |
|---|---|---|---|---|---|---|
| `adx` | `general` | `1s/1m` | Yes | - | `study_contract` | ADX(14) - trend strength |
| `aroon_down` | `general` | `1s/1m` | Yes | - | `study_contract` | Aroon Down(25) |
| `aroon_osc` | `general` | `1s/1m` | Yes | - | `study_contract` | Aroon Oscillator |
| `aroon_up` | `general` | `1s/1m` | Yes | - | `study_contract` | Aroon Up(25) |
| `arrival_accel_10s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_accel_5s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_jerk` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_vel_10s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_vel_20s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_vel_30s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `arrival_vel_5s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `atr_14` | `general` | `1s/1m` | Yes | - | `study_contract` | ATR(14) - standard |
| `atr_200` | `general` | `1s/1m` | Yes | - | `study_contract` | ATR(200) - long |
| `atr_50` | `general` | `1s/1m` | Yes | - | `study_contract` | ATR(50) - medium |
| `atr_ratio_14_200` | `general` | `1s/1m` | Yes | - | `study_contract` | ATR(14)/ATR(200) |
| `atr_ratio_14_50` | `general` | `1s/1m` | Yes | - | `study_contract` | ATR(14)/ATR(50) |
| `bars_since_high` | `general` | `1s/1m` | Yes | - | `study_contract` | Bars since swing high |
| `bars_since_low` | `general` | `1s/1m` | Yes | - | `study_contract` | Bars since swing low |
| `bb_position` | `general` | `1s/1m` | Yes | - | `study_contract` | Position in bands |
| `bb_width_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | BB(20,2) width |
| `cci` | `general` | `1s/1m` | Yes | - | `study_contract` | CCI(20) |
| `clean_pullback_score_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `close_vs_range_30s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `cmo` | `general` | `1s/1m` | Yes | - | `study_contract` | Chande Momentum(14) |
| `consecutive_down_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `consecutive_up_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `day_of_week` | `general` | `1s/1m` | Yes | - | `study_contract` | Day (0=Mon, 4=Fri) |
| `dc_position` | `general` | `1s/1m` | Yes | - | `study_contract` | Position in DC(20) |
| `dc_width_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | DC(20) width |
| `di_diff` | `general` | `1s/1m` | Yes | - | `study_contract` | +DI - (-DI) |
| `di_minus` | `general` | `1s/1m` | Yes | - | `study_contract` | -DI(14) |
| `di_plus` | `general` | `1s/1m` | Yes | - | `study_contract` | +DI(14) |
| `down_vol_ratio_10s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `efficiency_ratio` | `general` | `1s/1m` | Yes | - | `study_contract` | Efficiency Ratio(10) |
| `ema_13_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(13) |
| `ema_13_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(13) over 5 bars |
| `ema_21_50_cross` | `general` | `1s/1m` | Yes | - | `study_contract` | EMA(21) vs EMA(50) |
| `ema_21_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(21) |
| `ema_21_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(21) over 5 bars |
| `ema_3_9_cross` | `general` | `1s/1m` | Yes | - | `study_contract` | EMA(3) vs EMA(9) |
| `ema_3_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(3) |
| `ema_3_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(3) over 5 bars |
| `ema_50_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(50) |
| `ema_50_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(50) over 5 bars |
| `ema_5_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(5) |
| `ema_5_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(5) over 5 bars |
| `ema_9_21_cross` | `general` | `1s/1m` | Yes | - | `study_contract` | EMA(9) vs EMA(21) |
| `ema_9_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from EMA(9) |
| `ema_9_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Slope of EMA(9) over 5 bars |
| `ema_slope_long` | `context` | `1m` | Yes | - | `study_contract` | - |
| `ema_slope_short` | `context` | `1m` | Yes | - | `study_contract` | - |
| `hh_count_10` | `general` | `1s/1m` | Yes | - | `study_contract` | Higher highs in last 10 bars |
| `higher_lows_count_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `higher_lows_count_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `hma_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from Hull MA(20) |
| `hour_ct` | `general` | `1s/1m` | Yes | - | `study_contract` | Hour (Central Time) |
| `is_decelerating` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `is_rth` | `context` | `1s` | No | - | `study_contract` | Is RTH (8:30-15:00 CT) |
| `kc_position` | `general` | `1s/1m` | Yes | - | `study_contract` | Position in channel |
| `kc_width_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | KC(20,2) width |
| `linreg_r2` | `general` | `1s/1m` | Yes | - | `study_contract` | Linear Regression R² |
| `linreg_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | Linear Regression(20) slope |
| `ll_count_10` | `general` | `1s/1m` | Yes | - | `study_contract` | Lower lows in last 10 bars |
| `lower_highs_count_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `lower_highs_count_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `macd` | `general` | `1s/1m` | Yes | - | `study_contract` | MACD(12,26) value |
| `max_vel_30s` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `minutes_since_rth_open` | `context` | `1s` | No | - | `study_contract` | Minutes since 8:30 CT |
| `obv_slope` | `general` | `1s/1m` | Yes | - | `study_contract` | OBV slope (normalized) |
| `pressure` | `general` | `1s/1m` | Yes | - | `study_contract` | Pressure indicator |
| `pressure_cumulative` | `general` | `1s/1m` | Yes | - | `study_contract` | Cumulative pressure |
| `pullback_bars_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `pullback_depth_atr` | `` | `1s` | Yes | - | `study_contract` | - |
| `pullback_efficiency_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `pullback_linearity_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `range_30s_atr` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `range_position_20` | `general` | `1s/1m` | Yes | - | `study_contract` | Position in 20-bar range |
| `regime_age_bars` | `` | `1s` | Yes | - | `study_contract` | - |
| `retracement_pct` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `roc_10` | `general` | `1s/1m` | Yes | - | `study_contract` | ROC(10) |
| `roc_20` | `general` | `1s/1m` | Yes | - | `study_contract` | ROC(20) |
| `roc_5` | `general` | `1s/1m` | Yes | - | `study_contract` | ROC(5) |
| `rsi_14` | `general` | `1s/1m` | Yes | - | `study_contract` | RSI(14) - standard |
| `rsi_14_zone` | `general` | `1s/1m` | Yes | - | `study_contract` | RSI(14) zone |
| `rsi_21` | `general` | `1s/1m` | Yes | - | `study_contract` | RSI(21) - slow |
| `rsi_7` | `general` | `1s/1m` | Yes | - | `study_contract` | RSI(7) - fast |
| `rvol_10s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `rvol_1s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `rvol_5s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `session` | `general` | `1s/1m` | Yes | - | `study_contract` | Session code |
| `sma_10_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from SMA(10) |
| `sma_20_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from SMA(20) |
| `sma_50_dist_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Price distance from SMA(50) |
| `squeeze` | `general` | `1s/1m` | Yes | - | `study_contract` | BB inside KC (volatility squeeze) |
| `stoch_cross` | `general` | `1s/1m` | Yes | - | `study_contract` | %K vs %D position |
| `stoch_d` | `general` | `1s/1m` | Yes | - | `study_contract` | Stochastic %D(3) |
| `stoch_k` | `general` | `1s/1m` | Yes | - | `study_contract` | Stochastic %K(14) |
| `swing_count_1m` | `pullback_1m` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `swing_count_1s` | `pullback_1s` | `1s` | Yes | - | `study_contract` | PullbackTracker |
| `swing_direction` | `general` | `1s/1m` | Yes | - | `study_contract` | Current swing direction |
| `swing_length_atr` | `general` | `1s/1m` | Yes | - | `study_contract` | Current swing size |
| `up_vol_ratio_10s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `vel_ratio_5_20` | `arrival_velocity` | `1s` | Yes | - | `study_contract` | ArrivalVelocityTracker |
| `vol_accel` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `vol_climax` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `vol_price_corr_10s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `vol_ratio` | `general` | `1s/1m` | Yes | - | `study_contract` | Built-in Volatility Ratio |
| `vol_spike` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `vol_trend_10s` | `arrival_volume` | `1s` | Yes | - | `study_contract` | ArrivalVolumeTracker |
| `volume_ratio` | `general` | `1s/1m` | Yes | - | `study_contract` | Current vol / 20-bar avg |

---

## 2. Detailed Mathematical Contracts by Feature Family


### Family: `` (2 Features)

#### Feature: `pullback_depth_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`

#### Feature: `regime_age_bars`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`


### Family: `arrival_velocity` (10 Features)

#### Feature: `arrival_accel_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_accel_5s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_jerk`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_vel_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_vel_20s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_vel_30s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `arrival_vel_5s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `is_decelerating`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `max_vel_30s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`

#### Feature: `vel_ratio_5_20`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.velocity.ArrivalVelocityTracker`


### Family: `arrival_volume` (10 Features)

#### Feature: `down_vol_ratio_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `rvol_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `rvol_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `rvol_5s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `up_vol_ratio_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `vol_accel`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `vol_climax`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `vol_price_corr_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `vol_spike`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`

#### Feature: `vol_trend_10s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.volume.ArrivalVolumeTracker`


### Family: `context` (4 Features)

#### Feature: `ema_slope_long`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`

#### Feature: `ema_slope_short`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`

#### Feature: `is_rth`
- **Status:** `verified` | **Stateful:** `False` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Is RTH (8:30-15:00 CT)
- **Units / Valid Range:** `0 or 1`

#### Feature: `minutes_since_rth_open`
- **Status:** `verified` | **Stateful:** `False` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Minutes since 8:30 CT
- **Units / Valid Range:** `0-390 or -1`


### Family: `general` (69 Features)

#### Feature: `adx`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ADX(14) - trend strength
- **Units / Valid Range:** `0-100`

#### Feature: `aroon_down`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Aroon Down(25)
- **Units / Valid Range:** `0-100`

#### Feature: `aroon_osc`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Aroon Oscillator
- **Units / Valid Range:** `-100 to +100`

#### Feature: `aroon_up`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Aroon Up(25)
- **Units / Valid Range:** `0-100`

#### Feature: `atr_14`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ATR(14) - standard
- **Units / Valid Range:** `Price`

#### Feature: `atr_200`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ATR(200) - long
- **Units / Valid Range:** `Price`

#### Feature: `atr_50`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ATR(50) - medium
- **Units / Valid Range:** `Price`

#### Feature: `atr_ratio_14_200`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ATR(14)/ATR(200)
- **Units / Valid Range:** `>1 = expanding vol`

#### Feature: `atr_ratio_14_50`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ATR(14)/ATR(50)
- **Units / Valid Range:** `>1 = expanding vol`

#### Feature: `bars_since_high`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Bars since swing high
- **Units / Valid Range:** `Bars`

#### Feature: `bars_since_low`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Bars since swing low
- **Units / Valid Range:** `Bars`

#### Feature: `bb_position`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Position in bands
- **Units / Valid Range:** `-1 to +1`

#### Feature: `bb_width_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** BB(20,2) width
- **Units / Valid Range:** `ATR`

#### Feature: `cci`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** CCI(20)
- **Units / Valid Range:** `Unbounded`

#### Feature: `cmo`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Chande Momentum(14)
- **Units / Valid Range:** `-100 to +100`

#### Feature: `day_of_week`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Day (0=Mon, 4=Fri)
- **Units / Valid Range:** `0-4`

#### Feature: `dc_position`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Position in DC(20)
- **Units / Valid Range:** `0 to 1`

#### Feature: `dc_width_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** DC(20) width
- **Units / Valid Range:** `ATR`

#### Feature: `di_diff`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** +DI - (-DI)
- **Units / Valid Range:** `-100 to +100`

#### Feature: `di_minus`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** -DI(14)
- **Units / Valid Range:** `0-100`

#### Feature: `di_plus`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** +DI(14)
- **Units / Valid Range:** `0-100`

#### Feature: `efficiency_ratio`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Efficiency Ratio(10)
- **Units / Valid Range:** `0-1`

#### Feature: `ema_13_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(13)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_13_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(13) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `ema_21_50_cross`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** EMA(21) vs EMA(50)
- **Units / Valid Range:** `+1 (above), -1 (below)`

#### Feature: `ema_21_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(21)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_21_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(21) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `ema_3_9_cross`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** EMA(3) vs EMA(9)
- **Units / Valid Range:** `+1 (above), -1 (below)`

#### Feature: `ema_3_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(3)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_3_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(3) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `ema_50_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(50)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_50_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(50) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `ema_5_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(5)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_5_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(5) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `ema_9_21_cross`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** EMA(9) vs EMA(21)
- **Units / Valid Range:** `+1 (above), -1 (below)`

#### Feature: `ema_9_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from EMA(9)
- **Units / Valid Range:** `ATR`

#### Feature: `ema_9_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Slope of EMA(9) over 5 bars
- **Units / Valid Range:** `ATR/bar`

#### Feature: `hh_count_10`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Higher highs in last 10 bars
- **Units / Valid Range:** `0-9`

#### Feature: `hma_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from Hull MA(20)
- **Units / Valid Range:** `ATR`

#### Feature: `hour_ct`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Hour (Central Time)
- **Units / Valid Range:** `0-23`

#### Feature: `kc_position`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Position in channel
- **Units / Valid Range:** `-1 to +1`

#### Feature: `kc_width_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** KC(20,2) width
- **Units / Valid Range:** `ATR`

#### Feature: `linreg_r2`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Linear Regression R²
- **Units / Valid Range:** `0-1`

#### Feature: `linreg_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Linear Regression(20) slope
- **Units / Valid Range:** `ATR`

#### Feature: `ll_count_10`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Lower lows in last 10 bars
- **Units / Valid Range:** `0-9`

#### Feature: `macd`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** MACD(12,26) value
- **Units / Valid Range:** `ATR`

#### Feature: `obv_slope`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** OBV slope (normalized)
- **Units / Valid Range:** `-1 to +1`

#### Feature: `pressure`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Pressure indicator
- **Units / Valid Range:** `Unbounded`

#### Feature: `pressure_cumulative`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Cumulative pressure
- **Units / Valid Range:** `Unbounded`

#### Feature: `range_position_20`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Position in 20-bar range
- **Units / Valid Range:** `0 to 1`

#### Feature: `roc_10`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ROC(10)
- **Units / Valid Range:** `%`

#### Feature: `roc_20`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ROC(20)
- **Units / Valid Range:** `%`

#### Feature: `roc_5`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** ROC(5)
- **Units / Valid Range:** `%`

#### Feature: `rsi_14`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** RSI(14) - standard
- **Units / Valid Range:** `0-100`

#### Feature: `rsi_14_zone`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** RSI(14) zone
- **Units / Valid Range:** `-1 (OS), 0 (neutral), +1 (OB)`

#### Feature: `rsi_21`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** RSI(21) - slow
- **Units / Valid Range:** `0-100`

#### Feature: `rsi_7`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** RSI(7) - fast
- **Units / Valid Range:** `0-100`

#### Feature: `session`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Session code
- **Units / Valid Range:** `0=overnight, 1=AM, 2=midday, 3=PM`

#### Feature: `sma_10_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from SMA(10)
- **Units / Valid Range:** `ATR`

#### Feature: `sma_20_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from SMA(20)
- **Units / Valid Range:** `ATR`

#### Feature: `sma_50_dist_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Price distance from SMA(50)
- **Units / Valid Range:** `ATR`

#### Feature: `squeeze`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** BB inside KC (volatility squeeze)
- **Units / Valid Range:** `0 or 1`

#### Feature: `stoch_cross`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** %K vs %D position
- **Units / Valid Range:** `+1 (K>D), -1 (K<D)`

#### Feature: `stoch_d`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Stochastic %D(3)
- **Units / Valid Range:** `0-100`

#### Feature: `stoch_k`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Stochastic %K(14)
- **Units / Valid Range:** `0-100`

#### Feature: `swing_direction`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Current swing direction
- **Units / Valid Range:** `-1, 0, +1`

#### Feature: `swing_length_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Current swing size
- **Units / Valid Range:** `ATR`

#### Feature: `vol_ratio`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Built-in Volatility Ratio
- **Units / Valid Range:** `>1 = expanding`

#### Feature: `volume_ratio`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s/1m`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Description:** Current vol / 20-bar avg
- **Units / Valid Range:** `Ratio`


### Family: `pullback_1m` (7 Features)

#### Feature: `clean_pullback_score_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `higher_lows_count_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `lower_highs_count_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `pullback_bars_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `pullback_efficiency_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `retracement_pct`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `swing_count_1m`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`


### Family: `pullback_1s` (8 Features)

#### Feature: `close_vs_range_30s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `consecutive_down_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `consecutive_up_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `higher_lows_count_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `lower_highs_count_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `pullback_linearity_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `range_30s_atr`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

#### Feature: `swing_count_1s`
- **Status:** `verified` | **Stateful:** `True` | **Timeframe:** `1s`
- **Update Anchor:** `after_1s_close` | **Snapshot Anchor:** `caller_defined`
- **Normalization:** `study_contract` | **Dtype:** `float64`
- **Implementation Class:** `features.trackers.pullback.PullbackTracker`

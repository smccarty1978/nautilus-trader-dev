# Good Entry v2 — Phase 2 LightGBM Report

## Setup

- Features used: 177 (role == model_feature, intersected with collector output, numeric-only)
- Train: 724,772 rows from 19,312 events (years 2020-2023)
- Val:   178,661 rows from 18,437 events (year 2024)
- OOS:   181,255 rows from 18,672 events (year 2025)
- Model: LightGBM binary, early-stopped on val AUC
- Best iteration: 40

## OOS metrics (2025)

- N rows: 181,255
- Base rate: 38.4%
- **AUC: 0.5447**
- **PR-AUC: 0.4151** (baseline = 0.3839)
- Brier score: 0.2347

## OOS AUC / PR-AUC by stratum

| Stratum | n | Base rate | AUC | PR-AUC | Brier |
|---|--:|--:|--:|--:|--:|
| All | 181,255 | 38.4% | 0.5447 | 0.4151 | 0.2347 |
| RTH | 80,035 | 38.4% | 0.5318 | 0.4120 | 0.2359 |
| ETH | 101,220 | 38.3% | 0.5537 | 0.4162 | 0.2337 |
| Long | 92,106 | 37.5% | 0.5483 | 0.4098 | 0.2327 |
| Short | 89,149 | 39.3% | 0.5381 | 0.4206 | 0.2367 |
| RTH-Long | 41,120 | 37.2% | 0.5326 | 0.3984 | 0.2330 |
| RTH-Short | 38,915 | 39.7% | 0.5249 | 0.4235 | 0.2390 |
| ETH-Long | 50,986 | 37.8% | 0.5593 | 0.4173 | 0.2325 |
| ETH-Short | 50,234 | 38.9% | 0.5476 | 0.4174 | 0.2349 |

## Calibration (10 score deciles, OOS)

| Decile | n | Mean predicted | Actual rate | Mean PnL $ | PT100 rate (resolved) |
|--:|--:|--:|--:|--:|--:|
| 0 | 18,126 | 0.3024 | 29.0% | $0.54 | 42.1% (n=12,708) |
| 1 | 18,125 | 0.3580 | 35.6% | $0.57 | 45.2% (n=14,099) |
| 2 | 18,126 | 0.3699 | 36.0% | $-2.35 | 45.2% (n=14,690) |
| 3 | 18,125 | 0.3780 | 38.2% | $12.56 | 47.0% (n=15,329) |
| 4 | 18,126 | 0.3847 | 38.8% | $10.63 | 47.7% (n=15,770) |
| 5 | 18,125 | 0.3908 | 39.4% | $1.63 | 47.8% (n=16,126) |
| 6 | 18,125 | 0.3970 | 40.3% | $-0.41 | 48.4% (n=16,491) |
| 7 | 18,126 | 0.4040 | 40.9% | $-8.96 | 48.7% (n=16,893) |
| 8 | 18,125 | 0.4131 | 42.1% | $5.03 | 49.3% (n=17,355) |
| 9 | 18,126 | 0.4314 | 43.5% | $20.27 | 49.7% (n=17,781) |

## OOS economics by top-k score bucket

| Top-k | n | good_entry rate | Mean $ | Median $ | PT100% (resolved) |
|---|--:|--:|--:|--:|--:|
| ALL (baseline) | 181,255 | 38.4% | $3.95 | $-90.00 | 47.1% (n=157,242) |
| top 10% | 18,126 | 43.5% | $20.27 | $-100.00 | 49.7% (n=17,781) |
| top 20% | 36,251 | 42.8% | $12.65 | $-100.00 | 49.5% (n=35,136) |
| top 30% | 54,376 | 42.2% | $5.44 | $-100.00 | 49.2% (n=52,028) |

## OOS top-10% economics by stratum

| Stratum | top-10% n | good_entry rate | Mean $ | ALL Mean $ | Lift $ |
|---|--:|--:|--:|--:|--:|
| All | 18,126 | 43.5% | $20.27 | $3.95 | $16.32 |
| RTH | 8,004 | 43.7% | $82.98 | $23.75 | $59.24 |
| ETH | 10,122 | 43.2% | $-17.97 | $-11.70 | $-6.27 |
| Long | 9,211 | 43.4% | $23.79 | $7.85 | $15.94 |
| Short | 8,915 | 44.2% | $31.11 | $-0.08 | $31.19 |
| RTH-Long | 4,112 | 42.0% | $51.60 | $16.26 | $35.34 |
| RTH-Short | 3,892 | 44.1% | $108.59 | $31.66 | $76.93 |
| ETH-Long | 5,099 | 44.0% | $-0.08 | $1.07 | $-1.15 |
| ETH-Short | 5,023 | 43.2% | $-37.50 | $-24.66 | $-12.83 |

## Top 25 feature importances (gain)

| Rank | Feature | % gain | Splits |
|--:|---|--:|--:|
| 1 | `session_bars_since_open` | 13.0% | 63 |
| 2 | `ema_spread_1m_atr_checkpoint` | 8.0% | 62 |
| 3 | `ema_spread_30s_atr` | 6.2% | 58 |
| 4 | `minute_of_hour_checkpoint` | 2.0% | 37 |
| 5 | `price_vs_ema3_5m_atr` | 1.7% | 25 |
| 6 | `vol_1m_20avg` | 1.5% | 40 |
| 7 | `pre_10_vol_vs_avg` | 1.5% | 36 |
| 8 | `pre_10_volume_total` | 1.4% | 32 |
| 9 | `price_vs_flip_bar_high_atr` | 1.4% | 22 |
| 10 | `minutes_since_rth_open_checkpoint` | 1.3% | 37 |
| 11 | `swing_extension_at_signal_atr` | 1.2% | 42 |
| 12 | `distance_from_session_low_atr` | 1.2% | 40 |
| 13 | `flip_vol_vs_20avg` | 1.2% | 31 |
| 14 | `distance_from_session_high_atr` | 1.1% | 36 |
| 15 | `pre_5_body_efficiency` | 1.1% | 36 |
| 16 | `prior_regime_mfe_atr` | 1.1% | 39 |
| 17 | `pre_signal_vol_compression_3v10` | 1.1% | 36 |
| 18 | `pre_5_range_atr` | 1.1% | 36 |
| 19 | `avg_regime_duration_last_5` | 1.1% | 36 |
| 20 | `price_vs_sma50_atr` | 1.0% | 34 |
| 21 | `minutes_since_rth_open` | 1.0% | 23 |
| 22 | `two_bar_vol_vs_40avg` | 1.0% | 29 |
| 23 | `atr_at_signal` | 1.0% | 31 |
| 24 | `ema_spread_5m_atr` | 0.9% | 33 |
| 25 | `bar1_range_atr` | 0.9% | 32 |

## Phase 2 verdict

- OOS AUC: 0.5447
- PR-AUC vs base: 0.4151 vs 0.3839 (lift +0.0312)
- Top-10% economic lift over ALL: $16.32
- VERDICT: WEAK — features do not predict good_entry_300s well enough to act on. Either the label horizon is wrong or 1m flips are too noisy at the snap-time feature level.
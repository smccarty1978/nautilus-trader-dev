# Good Entry v2 — Phase 3 RTH Regression Report

## Setup

- Population: RTH-only checkpoints (is_rth_checkpoint == 1)
- Target: `regime_exit_pnl_atr` (ATR-normalized hold-to-flip PnL)
- Loss: L2 (MSE)
- Features: 177 model_feature cols (checkpoint_s included for pooling)
- Train: 320,587 rows from 14,303 events (years 2020-2023)
- Val:   77,647 rows from 5,412 events (year 2024)
- OOS:   80,035 rows from 5,677 events (year 2025)
- Best iteration: 4

## OOS rank quality (2025 RTH)

- N: 80,035
- **Spearman ρ: 0.0109** (p ≈ 1.99e-03)
- RMSE (ATR units): 2.5095
- MAE  (ATR units): 1.5916

## Decile-by-decile, OOS RTH

| Decile | n | Pred ATR | Actual ATR mean | Actual ATR med | $ mean | $ median | $ p25 | $ p75 | Trim 5% mean | Win% | Avg win $ | Avg loss $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 | 8,004 | -0.0808 | +0.1810 | -0.6435 | $33.60 | $-120.00 | $-305.00 | $180.00 | $-33.46 | 34.1% | $712.64 | $-319.83 |
| 1 | 8,003 | -0.0427 | +0.1239 | -0.6152 | $30.35 | $-135.00 | $-315.00 | $125.00 | $-42.63 | 31.5% | $808.92 | $-330.03 |
| 2 | 8,004 | -0.0333 | +0.0734 | -0.5550 | $17.35 | $-130.00 | $-320.00 | $125.00 | $-38.97 | 32.3% | $711.72 | $-315.28 |
| 3 | 8,003 | -0.0256 | +0.0272 | -0.6419 | $18.61 | $-145.00 | $-345.00 | $115.00 | $-52.96 | 30.2% | $845.31 | $-340.75 |
| 4 | 8,004 | -0.0187 | -0.0283 | -0.6153 | $11.10 | $-140.00 | $-330.00 | $105.00 | $-69.22 | 31.6% | $758.27 | $-336.90 |
| 5 | 8,003 | -0.0128 | +0.0852 | -0.5276 | $28.19 | $-125.00 | $-325.00 | $220.00 | $-25.41 | 35.3% | $710.82 | $-346.65 |
| 6 | 8,003 | -0.0076 | +0.0282 | -0.5639 | $29.11 | $-140.00 | $-335.00 | $135.00 | $-52.76 | 32.3% | $778.63 | $-330.29 |
| 7 | 8,004 | -0.0017 | +0.2293 | -0.5176 | $47.85 | $-125.00 | $-335.00 | $236.25 | $-24.42 | 35.9% | $781.07 | $-364.82 |
| 8 | 8,003 | +0.0057 | -0.1354 | -0.6154 | $-1.82 | $-150.00 | $-340.00 | $65.00 | $-106.57 | 29.2% | $793.44 | $-331.95 |
| 9 | 8,004 | +0.0972 | +0.0219 | -0.6064 | $23.12 | $-130.00 | $-325.00 | $145.00 | $-43.99 | 33.1% | $741.67 | $-334.18 |

**Reading guide**: a thin-tail mirage shows mean diverging from median + trimmed mean; a real signal shows mean, median, and trimmed-mean all moving together. Win rate trending with the mean is also a good signal.

## OOS top-k economics (full risk profile)

| Bucket | n | Mean $ | Median $ | p25 $ | p75 $ | Trim 5% mean | Win% | Avg win $ | Avg loss $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ALL (baseline) | 80,035 | $23.75 | $-135.00 | $-325.00 | $145.00 | $-49.61 | 32.6% | $762.69 | $-334.89 |
| top 10% | 8,004 | $23.11 | $-130.00 | $-325.00 | $145.00 | $-44.00 | 33.1% | $741.67 | $-334.20 |
| top 20% | 16,007 | $10.81 | $-140.00 | $-335.00 | $105.00 | $-76.72 | 31.2% | $764.98 | $-333.19 |
| top 30% | 24,010 | $23.96 | $-135.00 | $-335.00 | $150.00 | $-59.96 | 32.8% | $773.65 | $-343.33 |

## OOS top-10% economics: Long vs Short (RTH)

| Side | n | Mean $ | Median $ | Trim 5% | Win% | Spearman ρ |
|---|--:|--:|--:|--:|--:|--:|
| RTH-Long top-10% | 4,112 | $14.37 | $-132.50 | $-54.43 | 33.1% | +0.0050 |
| RTH-Long ALL | 41,120 | $16.26 | $-130.00 | $-51.80 | 33.9% | — |
| RTH-Short top-10% | 3,892 | $15.47 | $-125.00 | $-48.12 | 32.2% | +0.0032 |
| RTH-Short ALL | 38,915 | $31.66 | $-140.00 | $-45.25 | 31.1% | — |

## OOS top-10% economics by T bucket (within 600s)

| T bucket | n | top-10% n | top-10% Mean $ | top-10% Median $ | top-10% Trim 5% | top-10% Win% |
|---|--:|--:|--:|--:|--:|--:|
| 0-90s | 15,771 | 1,577 | $30.12 | $-125.00 | $-46.59 | 33.1% |
| 90-180s | 14,130 | 1,413 | $2.58 | $-135.00 | $-60.14 | 33.0% |
| 180-300s | 16,698 | 1,670 | $12.98 | $-135.00 | $-55.20 | 32.8% |
| 300-450s | 17,299 | 1,730 | $16.91 | $-125.00 | $-47.85 | 33.2% |
| 450-600s | 16,137 | 1,614 | $42.52 | $-120.00 | $-18.43 | 33.6% |

## OOS top-10% economics by 2025 quarter (stability check)

| Quarter | n | top-10% n | top-10% Mean $ | top-10% Median $ | top-10% Trim 5% | top-10% Win% | Spearman ρ |
|---|--:|--:|--:|--:|--:|--:|--:|
| 2025-Q1 | 19,217 | 1,922 | $-6.80 | $-130.00 | $-44.96 | 35.4% | +0.0155 |
| 2025-Q2 | 20,776 | 2,078 | $21.06 | $-170.00 | $-46.82 | 31.7% | +0.0003 |
| 2025-Q3 | 19,819 | 1,982 | $-5.77 | $-115.00 | $-56.01 | 30.4% | -0.0018 |
| 2025-Q4 | 20,223 | 2,022 | $78.09 | $-110.00 | $-27.23 | 36.0% | +0.0243 |

## Top 25 feature importances (gain)

| Rank | Feature | % gain | Splits |
|--:|---|--:|--:|
| 1 | `pre_5_net_return_atr` | 3.5% | 7 |
| 2 | `pre_10_range_atr` | 3.4% | 9 |
| 3 | `sma20_vs_sma50_atr` | 3.3% | 8 |
| 4 | `distance_from_session_mid_atr` | 3.1% | 4 |
| 5 | `atr_at_signal` | 2.8% | 4 |
| 6 | `two_bar_body_atr` | 2.8% | 6 |
| 7 | `flip_low_vs_prior_low_atr` | 2.6% | 4 |
| 8 | `vol_acceleration_5bar` | 2.6% | 7 |
| 9 | `pre_10_vol_vs_avg` | 2.6% | 6 |
| 10 | `bar1_body_atr` | 2.5% | 7 |
| 11 | `pre_5_range_atr` | 2.4% | 5 |
| 12 | `vol_ratio_up_down_20bar` | 2.4% | 7 |
| 13 | `pre_3_volume_total` | 2.1% | 6 |
| 14 | `distance_from_session_low_atr` | 2.1% | 5 |
| 15 | `pre_10_mean_body_pct` | 2.0% | 5 |
| 16 | `ema_spread_atr` | 2.0% | 5 |
| 17 | `bar1_close_location` | 1.8% | 4 |
| 18 | `price_vs_sma20_atr` | 1.6% | 4 |
| 19 | `pre_signal_trend_efficiency_5` | 1.5% | 3 |
| 20 | `flip_vol_vs_20avg` | 1.4% | 2 |
| 21 | `minute_of_hour` | 1.3% | 4 |
| 22 | `pre_3_vol_vs_avg` | 1.3% | 4 |
| 23 | `bar1_vol_vs_flip_vol` | 1.3% | 3 |
| 24 | `prior_regime_mfe_atr` | 1.3% | 4 |
| 25 | `two_bar_volume_total` | 1.3% | 2 |

## Phase 3 verdict

- Spearman ρ on OOS: +0.0109
- Top-10% lift: mean $-0.63, median $5.00, trimmed-5% $5.61
- Tail-vs-body read: Lift is small enough that tail vs body is moot.

- VERDICT: WEAK. RTH-only regression doesn't rescue the binary classifier — magnitude ranking is also marginal.
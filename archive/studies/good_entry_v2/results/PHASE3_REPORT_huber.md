# Good Entry v2 — Phase 3 RTH Regression Report

## Setup

- Population: RTH-only checkpoints (is_rth_checkpoint == 1)
- Target: `regime_exit_pnl_atr` (ATR-normalized hold-to-flip PnL)
- Loss: L2 (MSE)
- Features: 177 model_feature cols (checkpoint_s included for pooling)
- Train: 320,587 rows from 14,303 events (years 2020-2023)
- Val:   77,647 rows from 5,412 events (year 2024)
- OOS:   80,035 rows from 5,677 events (year 2025)
- Best iteration: 111

## OOS rank quality (2025 RTH)

- N: 80,035
- **Spearman ρ: 0.0784** (p ≈ 1.93e-109)
- RMSE (ATR units): 2.5767
- MAE  (ATR units): 1.4840

## Decile-by-decile, OOS RTH

| Decile | n | Pred ATR | Actual ATR mean | Actual ATR med | $ mean | $ median | $ p25 | $ p75 | Trim 5% mean | Win% | Avg win $ | Avg loss $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 | 8,004 | -0.8159 | +0.1651 | -0.8828 | $43.10 | $-140.00 | $-335.00 | $165.00 | $-32.97 | 33.3% | $826.74 | $-349.70 |
| 1 | 8,003 | -0.6435 | +0.0914 | -0.7041 | $17.17 | $-125.00 | $-320.00 | $150.00 | $-40.82 | 33.3% | $711.44 | $-330.15 |
| 2 | 8,004 | -0.5818 | +0.0371 | -0.6442 | $10.14 | $-135.00 | $-335.00 | $115.00 | $-59.59 | 31.6% | $745.56 | $-332.79 |
| 3 | 8,003 | -0.5431 | +0.0113 | -0.6259 | $3.79 | $-135.00 | $-330.00 | $135.00 | $-58.82 | 31.8% | $725.59 | $-334.64 |
| 4 | 8,004 | -0.5118 | +0.0105 | -0.6160 | $1.32 | $-140.00 | $-325.00 | $100.00 | $-68.77 | 30.6% | $751.13 | $-330.57 |
| 5 | 8,003 | -0.4820 | +0.0679 | -0.5777 | $17.16 | $-140.00 | $-325.00 | $115.00 | $-59.37 | 31.4% | $772.97 | $-330.84 |
| 6 | 8,003 | -0.4506 | +0.0590 | -0.5211 | $17.30 | $-125.00 | $-315.00 | $125.00 | $-53.87 | 32.4% | $724.76 | $-324.66 |
| 7 | 8,004 | -0.4140 | +0.0683 | -0.5254 | $58.12 | $-135.00 | $-315.00 | $131.25 | $-46.26 | 31.9% | $868.23 | $-322.76 |
| 8 | 8,003 | -0.3642 | +0.0174 | -0.5123 | $33.68 | $-135.00 | $-325.00 | $145.00 | $-47.52 | 33.0% | $775.28 | $-333.91 |
| 9 | 8,004 | -0.2478 | +0.0786 | -0.4693 | $35.68 | $-125.00 | $-345.00 | $260.00 | $-26.00 | 36.3% | $728.92 | $-360.76 |

**Reading guide**: a thin-tail mirage shows mean diverging from median + trimmed mean; a real signal shows mean, median, and trimmed-mean all moving together. Win rate trending with the mean is also a good signal.

## OOS top-k economics (full risk profile)

| Bucket | n | Mean $ | Median $ | p25 $ | p75 $ | Trim 5% mean | Win% | Avg win $ | Avg loss $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ALL (baseline) | 80,035 | $23.75 | $-135.00 | $-325.00 | $145.00 | $-49.61 | 32.6% | $762.69 | $-334.89 |
| top 10% | 8,004 | $35.68 | $-125.00 | $-345.00 | $260.00 | $-26.00 | 36.3% | $728.92 | $-360.76 |
| top 20% | 16,007 | $34.69 | $-130.00 | $-335.00 | $200.00 | $-36.92 | 34.6% | $751.03 | $-347.01 |
| top 30% | 24,010 | $42.46 | $-135.00 | $-330.00 | $180.00 | $-40.10 | 33.7% | $787.93 | $-338.70 |

## OOS top-10% economics: Long vs Short (RTH)

| Side | n | Mean $ | Median $ | Trim 5% | Win% | Spearman ρ |
|---|--:|--:|--:|--:|--:|--:|
| RTH-Long top-10% | 4,112 | $44.76 | $-115.00 | $-18.78 | 37.1% | +0.0390 |
| RTH-Long ALL | 41,120 | $16.26 | $-130.00 | $-51.80 | 33.9% | — |
| RTH-Short top-10% | 3,892 | $120.73 | $-130.00 | $33.20 | 31.9% | +0.1099 |
| RTH-Short ALL | 38,915 | $31.66 | $-140.00 | $-45.25 | 31.1% | — |

## OOS top-10% economics by T bucket (within 600s)

| T bucket | n | top-10% n | top-10% Mean $ | top-10% Median $ | top-10% Trim 5% | top-10% Win% |
|---|--:|--:|--:|--:|--:|--:|
| 0-90s | 15,771 | 1,577 | $45.02 | $-145.00 | $-25.19 | 35.2% |
| 90-180s | 14,130 | 1,413 | $44.59 | $-140.00 | $-21.50 | 35.1% |
| 180-300s | 16,698 | 1,670 | $55.15 | $-115.00 | $-3.82 | 37.9% |
| 300-450s | 17,299 | 1,730 | $35.46 | $-120.00 | $-23.02 | 36.8% |
| 450-600s | 16,137 | 1,614 | $-1.82 | $-120.00 | $-47.41 | 35.5% |

## OOS top-10% economics by 2025 quarter (stability check)

| Quarter | n | top-10% n | top-10% Mean $ | top-10% Median $ | top-10% Trim 5% | top-10% Win% | Spearman ρ |
|---|--:|--:|--:|--:|--:|--:|--:|
| 2025-Q1 | 19,217 | 1,922 | $21.55 | $-130.00 | $-21.31 | 39.1% | +0.0533 |
| 2025-Q2 | 20,776 | 2,078 | $77.74 | $-130.00 | $-6.71 | 35.6% | +0.0730 |
| 2025-Q3 | 19,819 | 1,982 | $-8.67 | $-115.00 | $-33.05 | 36.1% | +0.0942 |
| 2025-Q4 | 20,223 | 2,022 | $60.92 | $-127.50 | $-21.03 | 35.2% | +0.0915 |

## Top 25 feature importances (gain)

| Rank | Feature | % gain | Splits |
|--:|---|--:|--:|
| 1 | `prior_regime_mfe_atr` | 2.3% | 168 |
| 2 | `ema3_slope_atr` | 1.9% | 103 |
| 3 | `vol_ratio_up_down_20bar` | 1.8% | 124 |
| 4 | `minutes_since_rth_open` | 1.7% | 122 |
| 5 | `avg_regime_duration_last_5` | 1.7% | 125 |
| 6 | `distance_from_session_low_atr` | 1.6% | 94 |
| 7 | `pre_5_net_return_atr` | 1.6% | 103 |
| 8 | `bar1_bullish_volume_pct` | 1.5% | 99 |
| 9 | `sma20_vs_sma50_atr` | 1.4% | 101 |
| 10 | `pre_5_body_efficiency` | 1.4% | 99 |
| 11 | `pre_10_mean_body_pct` | 1.4% | 92 |
| 12 | `atr_at_signal` | 1.4% | 94 |
| 13 | `bar1_range_atr` | 1.4% | 99 |
| 14 | `sma50_slope_atr` | 1.3% | 89 |
| 15 | `price_vs_sma50_atr` | 1.3% | 91 |
| 16 | `two_bar_close_vs_open_pct` | 1.3% | 88 |
| 17 | `bar1_body_pct` | 1.3% | 87 |
| 18 | `minute_of_hour` | 1.3% | 89 |
| 19 | `pre_5_vol_vs_avg` | 1.3% | 86 |
| 20 | `flip_body_pct` | 1.2% | 84 |
| 21 | `pre_10_volume_total` | 1.2% | 81 |
| 22 | `distance_from_session_mid_atr` | 1.2% | 73 |
| 23 | `sma20_slope_atr` | 1.2% | 86 |
| 24 | `session_bars_since_open` | 1.2% | 86 |
| 25 | `pre_5_range_atr` | 1.2% | 73 |

## Phase 3 verdict

- Spearman ρ on OOS: +0.0784
- Top-10% lift: mean $11.93, median $10.00, trimmed-5% $23.61
- Tail-vs-body read: Robust — trimmed-mean lift moves with raw mean, suggesting genuine payoff ranking rather than tail-chasing.

- VERDICT: MODERATE. Real but small signal. Consider Huber loss / quantile regression / RTH-Long-only or RTH-Short-only models before committing to backtest.
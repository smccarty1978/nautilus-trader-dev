# NQ V_A Viability Classifier v1

**Population**: NQ RTH only, V_A baseline (1m HH/LL + momentum confirm, hold to opposing 1m flip), all 7 years 2020-2026 = 21,691 trades.

**Per-year baseline**:

| Year | n | WR | Mean $ | Total $ |
|---|--:|--:|--:|--:|
| 2020 | 3,571 | 35.7% | $-9.57 | $-34,170 |
| 2021 | 3,548 | 33.2% | $-22.02 | $-78,130 |
| 2022 | 3,465 | 34.2% | $-15.82 | $-54,805 |
| 2023 | 3,448 | 34.3% | $-13.28 | $-45,780 |
| 2024 | 3,343 | 35.2% | $6.35 | $21,220 |
| 2025 | 3,310 | 34.2% | $18.04 | $59,720 |
| 2026 | 1,006 | 35.1% | $-17.23 | $-17,335 |

## 1. Descriptive — feature differences across cohorts

Cohorts (NQ RTH only):
- **A**: 2024-2025 winners
- **B**: 2024-2025 losers
- **C**: 2020-2023 losers
- **D**: 2026 losers

- A n=2,309, B n=4,344, C n=9,212, D n=653

### A (24-25 winners) vs C (20-23 losers) — what makes the good pocket different from structurally bad years

| Feature | Med A (24-25 W) | Med C (20-23 L) | Cohen's d | Δ |
|---|--:|--:|--:|--:|
| atr_5m | 25.095 | 20.036 | +0.542 | +5.059 |
| atr_3m | 19.917 | 15.690 | +0.535 | +4.227 |
| atr_1m | 11.610 | 9.128 | +0.491 | +2.482 |
| atr_30s | 8.075 | 6.373 | +0.467 | +1.702 |
| direction_trade | 1.000 | -1.000 | +0.076 | +2.000 |
| regime_30s | 1.000 | -1.000 | +0.076 | +2.000 |
| bar1_close_loc | 0.533 | 0.500 | +0.076 | +0.033 |
| atr_1m_pct_year | 0.524 | 0.492 | +0.071 | +0.032 |
| dist_close_to_ema9_l_5m_atr | 0.488 | 0.541 | -0.071 | -0.053 |
| dist_close_to_ema9_h_5m_atr | -0.505 | -0.429 | -0.069 | -0.076 |
| dist_close_to_ema3_h_1m_atr | -0.095 | -0.613 | +0.066 | +0.519 |
| regime_5m | 1.000 | 1.000 | -0.066 | +0.000 |
| bar1_range_atr | 0.973 | 0.995 | -0.060 | -0.023 |
| dist_close_to_ema9_h_1m_atr | 0.129 | -0.873 | +0.060 | +1.002 |
| dist_close_to_ema9_l_1m_atr | 1.088 | 0.048 | +0.058 | +1.040 |

### A (24-25 winners) vs B (24-25 losers) — what distinguishes winners within the good pocket

| Feature | Med A | Med B | Cohen's d | Δ |
|---|--:|--:|--:|--:|
| regime_5m | 1.000 | 1.000 | -0.083 | +0.000 |
| bar1_body_pct | 0.484 | 0.451 | +0.083 | +0.032 |
| atr_1m_pct_year | 0.524 | 0.488 | +0.075 | +0.036 |
| dist_close_to_ema3_h_5m_atr | -0.463 | -0.438 | -0.069 | -0.025 |
| dist_close_to_ema9_h_5m_atr | -0.505 | -0.420 | -0.067 | -0.085 |
| close_through_atr | 0.300 | 0.263 | +0.063 | +0.036 |
| dist_close_to_ema9_l_5m_atr | 0.488 | 0.548 | -0.061 | -0.060 |
| direction_trade | 1.000 | 1.000 | +0.054 | +0.000 |
| regime_30s | 1.000 | 1.000 | +0.053 | +0.000 |
| dist_close_to_ema3_l_1m_atr | 0.792 | 0.657 | +0.052 | +0.135 |
| atr_30s | 8.075 | 7.746 | +0.052 | +0.330 |
| atr_1m | 11.610 | 11.068 | +0.050 | +0.542 |
| dist_close_to_ema3_l_5m_atr | 0.469 | 0.488 | -0.048 | -0.018 |
| dist_close_to_ema9_l_1m_atr | 1.088 | 0.953 | +0.047 | +0.136 |
| atr_1m_slope_30m | -0.063 | -0.064 | +0.044 | +0.001 |

### C (20-23 losers) vs D (2026 losers) — are the bad years all the same?

| Feature | Med C (20-23 L) | Med D (26 L) | Cohen's d | Δ |
|---|--:|--:|--:|--:|
| atr_5m | 20.036 | 36.055 | -1.431 | -16.019 |
| atr_3m | 15.690 | 28.452 | -1.375 | -12.763 |
| atr_1m | 9.128 | 15.824 | -1.165 | -6.696 |
| atr_30s | 6.373 | 10.979 | -1.100 | -4.606 |
| bar1_range_atr | 0.995 | 0.947 | +0.149 | +0.049 |
| hhll_break_atr | 0.586 | 0.556 | +0.106 | +0.030 |
| close_through_atr | 0.290 | 0.250 | +0.102 | +0.040 |
| dist_close_to_ema9_h_5m_atr | -0.429 | -0.385 | -0.088 | -0.044 |
| regime_3m | 1.000 | 1.000 | -0.087 | +0.000 |
| atr_1m_slope_30m | -0.046 | -0.085 | -0.081 | +0.039 |
| bar1_body_pct | 0.474 | 0.448 | +0.074 | +0.025 |
| dist_close_to_ema3_h_5m_atr | -0.446 | -0.423 | -0.070 | -0.023 |
| dist_close_to_ema9_h_3m_atr | -0.477 | -0.424 | -0.063 | -0.052 |
| aligned_5m | 0.000 | 0.000 | +0.056 | +0.000 |
| dist_close_to_ema9_l_5m_atr | 0.541 | 0.513 | -0.053 | +0.028 |

### Year-by-year median for top-discriminating features

Look for features that drift in 2024-2025 vs other years.

#### flip_count_30m

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 3.000 | 3.042 |
| 2021 | 3.000 | 3.091 |
| 2022 | 3.000 | 3.063 |
| 2023 | 3.000 | 3.141 |
| 2024 | 3.000 | 3.002 |
| 2025 | 3.000 | 3.076 |
| 2026 | 3.000 | 3.054 |

#### flip_count_60m

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 5.000 | 5.242 |
| 2021 | 5.000 | 5.324 |
| 2022 | 5.000 | 5.304 |
| 2023 | 5.000 | 5.363 |
| 2024 | 5.000 | 5.152 |
| 2025 | 5.000 | 5.308 |
| 2026 | 5.000 | 5.320 |

#### avg_regime_dur_5_s

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 780.000 | 842.026 |
| 2021 | 768.000 | 797.496 |
| 2022 | 756.000 | 799.571 |
| 2023 | 756.000 | 791.501 |
| 2024 | 792.000 | 835.568 |
| 2025 | 756.000 | 806.428 |
| 2026 | 756.000 | 807.825 |

#### atr_1m

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 8.369 | 9.797 |
| 2021 | 7.710 | 8.870 |
| 2022 | 12.588 | 14.090 |
| 2023 | 8.585 | 9.378 |
| 2024 | 10.038 | 11.362 |
| 2025 | 13.071 | 15.216 |
| 2026 | 15.677 | 17.295 |

#### atr_1m_pct_year

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 0.500 | 0.500 |
| 2021 | 0.500 | 0.500 |
| 2022 | 0.500 | 0.500 |
| 2023 | 0.500 | 0.500 |
| 2024 | 0.500 | 0.500 |
| 2025 | 0.500 | 0.500 |
| 2026 | 0.500 | 0.500 |

#### bar1_body_pct

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 0.486 | 0.481 |
| 2021 | 0.485 | 0.484 |
| 2022 | 0.471 | 0.469 |
| 2023 | 0.476 | 0.473 |
| 2024 | 0.462 | 0.464 |
| 2025 | 0.467 | 0.466 |
| 2026 | 0.462 | 0.460 |

#### all_3_aligned

| Year | Median | Mean |
|---|--:|--:|
| 2020 | 0.000 | 0.331 |
| 2021 | 0.000 | 0.305 |
| 2022 | 0.000 | 0.324 |
| 2023 | 0.000 | 0.314 |
| 2024 | 0.000 | 0.316 |
| 2025 | 0.000 | 0.309 |
| 2026 | 0.000 | 0.306 |

## 2. Simple filter tests

Each filter applied per year. Promising filters improve 2020-2023 + 2026 without destroying 2024-2025.

### Filter performance per year

| Filter | Year | %kept | n | WR | Mean $ | PF | Total $ | Max DD | Δ Mean | Δ Total |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| none | 2020 | 100.0% | 3,571 | 35.7% | $-9.57 | 0.94 | $-34,170 | $-54,310 | $0.00 | $0.00 |
| none | 2021 | 100.0% | 3,548 | 33.2% | $-22.02 | 0.86 | $-78,130 | $-105,865 | $0.00 | $0.00 |
| none | 2022 | 100.0% | 3,465 | 34.2% | $-15.82 | 0.94 | $-54,805 | $-69,695 | $0.00 | $0.00 |
| none | 2023 | 100.0% | 3,448 | 34.3% | $-13.28 | 0.92 | $-45,780 | $-55,830 | $0.00 | $0.00 |
| none | 2024 | 100.0% | 3,343 | 35.2% | $6.35 | 1.03 | $21,220 | $-42,045 | $0.00 | $0.00 |
| none | 2025 | 100.0% | 3,310 | 34.2% | $18.04 | 1.07 | $59,720 | $-46,270 | $0.00 | $0.00 |
| none | 2026 | 100.0% | 1,006 | 35.1% | $-17.23 | 0.94 | $-17,335 | $-28,790 | $0.00 | $0.00 |
| flip_count_60m <= 6 | 2020 | 78.4% | 2,800 | 35.4% | $-12.17 | 0.93 | $-34,085 | $-47,695 | $-2.60 | $85.00 |
| flip_count_60m <= 6 | 2021 | 75.3% | 2,671 | 32.9% | $-20.02 | 0.87 | $-53,480 | $-85,525 | $2.00 | $24,650 |
| flip_count_60m <= 6 | 2022 | 76.1% | 2,636 | 34.3% | $-14.55 | 0.94 | $-38,355 | $-51,440 | $1.27 | $16,450 |
| flip_count_60m <= 6 | 2023 | 74.6% | 2,573 | 34.9% | $-7.96 | 0.95 | $-20,485 | $-30,465 | $5.32 | $25,295 |
| flip_count_60m <= 6 | 2024 | 77.7% | 2,598 | 35.1% | $6.64 | 1.03 | $17,245 | $-35,885 | $0.29 | $-3,975 |
| flip_count_60m <= 6 | 2025 | 74.3% | 2,460 | 34.3% | $13.74 | 1.06 | $33,805 | $-24,005 | $-4.30 | $-25,915 |
| flip_count_60m <= 6 | 2026 | 74.3% | 747 | 34.7% | $-25.37 | 0.91 | $-18,955 | $-25,555 | $-8.14 | $-1,620 |
| flip_count_60m <= 4 | 2020 | 35.2% | 1,257 | 34.9% | $-15.67 | 0.90 | $-19,695 | $-22,590 | $-6.10 | $14,475 |
| flip_count_60m <= 4 | 2021 | 34.2% | 1,213 | 32.4% | $-27.17 | 0.82 | $-32,960 | $-52,615 | $-5.15 | $45,170 |
| flip_count_60m <= 4 | 2022 | 34.3% | 1,188 | 32.2% | $-35.74 | 0.86 | $-42,465 | $-46,945 | $-19.93 | $12,340 |
| flip_count_60m <= 4 | 2023 | 33.7% | 1,162 | 34.6% | $-18.29 | 0.88 | $-21,250 | $-26,080 | $-5.01 | $24,530 |
| flip_count_60m <= 4 | 2024 | 38.1% | 1,274 | 35.4% | $-3.96 | 0.98 | $-5,050 | $-32,515 | $-10.31 | $-26,270 |
| flip_count_60m <= 4 | 2025 | 34.8% | 1,151 | 33.8% | $-21.28 | 0.92 | $-24,490 | $-45,625 | $-39.32 | $-84,210 |
| flip_count_60m <= 4 | 2026 | 35.9% | 361 | 33.5% | $-77.17 | 0.75 | $-27,860 | $-35,005 | $-59.94 | $-10,525 |
| avg_regime_dur_5_s >= 600 | 2020 | 75.0% | 2,679 | 35.1% | $-13.82 | 0.92 | $-37,020 | $-47,305 | $-4.25 | $-2,850 |
| avg_regime_dur_5_s >= 600 | 2021 | 73.1% | 2,594 | 32.9% | $-18.44 | 0.88 | $-47,830 | $-83,685 | $3.58 | $30,300 |
| avg_regime_dur_5_s >= 600 | 2022 | 72.7% | 2,519 | 34.1% | $-12.76 | 0.95 | $-32,135 | $-43,965 | $3.06 | $22,670 |
| avg_regime_dur_5_s >= 600 | 2023 | 71.4% | 2,461 | 34.7% | $-11.59 | 0.93 | $-28,515 | $-35,950 | $1.69 | $17,265 |
| avg_regime_dur_5_s >= 600 | 2024 | 75.4% | 2,521 | 35.3% | $9.88 | 1.05 | $24,895 | $-32,805 | $3.53 | $3,675 |
| avg_regime_dur_5_s >= 600 | 2025 | 72.1% | 2,385 | 34.1% | $15.30 | 1.06 | $36,500 | $-31,205 | $-2.74 | $-23,220 |
| avg_regime_dur_5_s >= 600 | 2026 | 73.2% | 736 | 34.2% | $-28.61 | 0.90 | $-21,055 | $-29,540 | $-11.38 | $-3,720 |
| avg_regime_dur_5_s >= 900 | 2020 | 34.8% | 1,244 | 35.1% | $-23.67 | 0.86 | $-29,450 | $-31,620 | $-14.10 | $4,720 |
| avg_regime_dur_5_s >= 900 | 2021 | 32.9% | 1,166 | 31.4% | $-30.58 | 0.81 | $-35,655 | $-54,920 | $-8.56 | $42,475 |
| avg_regime_dur_5_s >= 900 | 2022 | 33.4% | 1,156 | 30.6% | $-44.46 | 0.82 | $-51,395 | $-53,275 | $-28.64 | $3,410 |
| avg_regime_dur_5_s >= 900 | 2023 | 33.0% | 1,138 | 33.9% | $-25.51 | 0.83 | $-29,025 | $-30,385 | $-12.23 | $16,755 |
| avg_regime_dur_5_s >= 900 | 2024 | 37.1% | 1,239 | 34.7% | $2.41 | 1.01 | $2,985 | $-26,065 | $-3.94 | $-18,235 |
| avg_regime_dur_5_s >= 900 | 2025 | 34.4% | 1,139 | 34.0% | $1.16 | 1.00 | $1,325 | $-33,940 | $-16.88 | $-58,395 |
| avg_regime_dur_5_s >= 900 | 2026 | 35.4% | 356 | 34.3% | $-61.76 | 0.79 | $-21,985 | $-28,540 | $-44.52 | $-4,650 |
| bar1_body_pct >= 0.5 | 2020 | 49.2% | 1,757 | 36.5% | $-9.05 | 0.95 | $-15,895 | $-33,355 | $0.52 | $18,275 |
| bar1_body_pct >= 0.5 | 2021 | 49.2% | 1,745 | 34.2% | $-21.68 | 0.87 | $-37,835 | $-52,260 | $0.34 | $40,295 |
| bar1_body_pct >= 0.5 | 2022 | 47.0% | 1,628 | 35.8% | $-7.56 | 0.97 | $-12,305 | $-42,465 | $8.26 | $42,500 |
| bar1_body_pct >= 0.5 | 2023 | 48.1% | 1,659 | 36.4% | $1.20 | 1.01 | $1,985 | $-18,620 | $14.47 | $47,765 |
| bar1_body_pct >= 0.5 | 2024 | 46.3% | 1,548 | 37.0% | $2.25 | 1.01 | $3,480 | $-31,485 | $-4.10 | $-17,740 |
| bar1_body_pct >= 0.5 | 2025 | 46.5% | 1,540 | 35.6% | $42.13 | 1.16 | $64,885 | $-21,970 | $24.09 | $5,165 |
| bar1_body_pct >= 0.5 | 2026 | 45.5% | 458 | 36.9% | $-19.31 | 0.94 | $-8,845 | $-16,125 | $-2.08 | $8,490 |
| hhll_break_atr >= 0.10 | 2020 | 96.7% | 3,452 | 36.0% | $-7.81 | 0.95 | $-26,945 | $-48,295 | $1.76 | $7,225 |
| hhll_break_atr >= 0.10 | 2021 | 96.7% | 3,431 | 33.2% | $-22.67 | 0.86 | $-77,795 | $-105,520 | $-0.65 | $335.00 |
| hhll_break_atr >= 0.10 | 2022 | 95.8% | 3,321 | 34.3% | $-16.37 | 0.93 | $-54,370 | $-69,680 | $-0.55 | $435.00 |
| hhll_break_atr >= 0.10 | 2023 | 96.4% | 3,325 | 34.3% | $-11.62 | 0.93 | $-38,645 | $-50,340 | $1.65 | $7,135 |
| hhll_break_atr >= 0.10 | 2024 | 96.6% | 3,228 | 35.1% | $6.25 | 1.03 | $20,175 | $-39,300 | $-0.10 | $-1,045 |
| hhll_break_atr >= 0.10 | 2025 | 96.0% | 3,176 | 34.5% | $23.33 | 1.09 | $74,110 | $-42,190 | $5.29 | $14,390 |
| hhll_break_atr >= 0.10 | 2026 | 95.2% | 958 | 34.6% | $-27.78 | 0.91 | $-26,615 | $-36,385 | $-10.55 | $-9,280 |
| close_through_atr >= 0.10 | 2020 | 74.5% | 2,661 | 36.3% | $-4.33 | 0.97 | $-11,520 | $-35,105 | $5.24 | $22,650 |
| close_through_atr >= 0.10 | 2021 | 72.6% | 2,576 | 34.2% | $-18.31 | 0.89 | $-47,155 | $-63,275 | $3.72 | $30,975 |
| close_through_atr >= 0.10 | 2022 | 70.1% | 2,429 | 34.6% | $-14.48 | 0.94 | $-35,180 | $-56,380 | $1.33 | $19,625 |
| close_through_atr >= 0.10 | 2023 | 70.8% | 2,440 | 35.0% | $-8.43 | 0.95 | $-20,575 | $-38,050 | $4.84 | $25,205 |
| close_through_atr >= 0.10 | 2024 | 68.4% | 2,287 | 36.3% | $2.99 | 1.01 | $6,845 | $-47,295 | $-3.35 | $-14,375 |
| close_through_atr >= 0.10 | 2025 | 69.2% | 2,290 | 36.2% | $49.55 | 1.19 | $113,460 | $-26,300 | $31.50 | $53,740 |
| close_through_atr >= 0.10 | 2026 | 68.3% | 687 | 35.8% | $-29.53 | 0.90 | $-20,285 | $-24,710 | $-12.30 | $-2,950 |
| aligned_5m == 1 | 2020 | 42.8% | 1,530 | 37.1% | $4.42 | 1.03 | $6,770 | $-25,145 | $13.99 | $40,940 |
| aligned_5m == 1 | 2021 | 40.9% | 1,450 | 33.4% | $-20.87 | 0.87 | $-30,260 | $-42,120 | $1.15 | $47,870 |
| aligned_5m == 1 | 2022 | 42.5% | 1,473 | 35.5% | $6.12 | 1.02 | $9,010 | $-28,255 | $21.93 | $63,815 |
| aligned_5m == 1 | 2023 | 41.7% | 1,439 | 34.3% | $-9.42 | 0.94 | $-13,550 | $-25,620 | $3.86 | $32,230 |
| aligned_5m == 1 | 2024 | 41.9% | 1,401 | 35.9% | $21.52 | 1.11 | $30,150 | $-16,145 | $15.17 | $8,930 |
| aligned_5m == 1 | 2025 | 41.4% | 1,370 | 33.4% | $-13.36 | 0.95 | $-18,300 | $-43,820 | $-31.40 | $-78,020 |
| aligned_5m == 1 | 2026 | 40.3% | 405 | 37.5% | $6.28 | 1.02 | $2,545 | $-20,300 | $23.52 | $19,880 |
| all_3_aligned == 1 | 2020 | 33.1% | 1,181 | 37.1% | $-3.76 | 0.98 | $-4,440 | $-25,115 | $5.81 | $29,730 |
| all_3_aligned == 1 | 2021 | 30.5% | 1,081 | 33.6% | $-18.19 | 0.89 | $-19,660 | $-30,970 | $3.83 | $58,470 |
| all_3_aligned == 1 | 2022 | 32.4% | 1,121 | 36.4% | $18.24 | 1.07 | $20,450 | $-19,360 | $34.06 | $75,255 |
| all_3_aligned == 1 | 2023 | 31.4% | 1,084 | 34.6% | $-10.49 | 0.93 | $-11,370 | $-23,960 | $2.79 | $34,410 |
| all_3_aligned == 1 | 2024 | 31.6% | 1,057 | 35.2% | $8.74 | 1.04 | $9,240 | $-31,030 | $2.39 | $-11,980 |
| all_3_aligned == 1 | 2025 | 30.9% | 1,022 | 34.0% | $-7.80 | 0.97 | $-7,970 | $-41,300 | $-25.84 | $-67,690 |
| all_3_aligned == 1 | 2026 | 30.6% | 308 | 36.0% | $-3.47 | 0.99 | $-1,070 | $-16,875 | $13.76 | $16,265 |
| morning only (mins_since_open<=60) | 2020 | 16.7% | 598 | 38.1% | $0.26 | 1.00 | $155.00 | $-17,665 | $9.83 | $34,325 |
| morning only (mins_since_open<=60) | 2021 | 16.9% | 600 | 33.2% | $-38.10 | 0.85 | $-22,860 | $-34,160 | $-16.08 | $55,270 |
| morning only (mins_since_open<=60) | 2022 | 17.9% | 619 | 35.1% | $-22.65 | 0.94 | $-14,020 | $-31,945 | $-6.83 | $40,785 |
| morning only (mins_since_open<=60) | 2023 | 16.7% | 577 | 38.1% | $12.23 | 1.06 | $7,055 | $-15,285 | $25.50 | $52,835 |
| morning only (mins_since_open<=60) | 2024 | 17.3% | 577 | 34.3% | $-0.49 | 1.00 | $-285.00 | $-18,125 | $-6.84 | $-21,505 |
| morning only (mins_since_open<=60) | 2025 | 16.3% | 539 | 38.2% | $48.00 | 1.13 | $25,870 | $-16,600 | $29.95 | $-33,850 |
| morning only (mins_since_open<=60) | 2026 | 16.8% | 169 | 38.5% | $26.86 | 1.06 | $4,540 | $-14,085 | $44.10 | $21,875 |
| avoid lunch (mins_since_open<60 OR >180) | 2020 | 70.0% | 2,498 | 35.1% | $-10.53 | 0.94 | $-26,300 | $-38,300 | $-0.96 | $7,870 |
| avoid lunch (mins_since_open<60 OR >180) | 2021 | 69.5% | 2,466 | 32.3% | $-24.65 | 0.85 | $-60,775 | $-77,160 | $-2.62 | $17,355 |
| avoid lunch (mins_since_open<60 OR >180) | 2022 | 68.8% | 2,384 | 33.3% | $-20.48 | 0.92 | $-48,820 | $-66,945 | $-4.66 | $5,985 |
| avoid lunch (mins_since_open<60 OR >180) | 2023 | 68.4% | 2,357 | 34.5% | $-5.90 | 0.96 | $-13,905 | $-26,325 | $7.38 | $31,875 |
| avoid lunch (mins_since_open<60 OR >180) | 2024 | 69.8% | 2,333 | 35.3% | $8.07 | 1.04 | $18,835 | $-41,905 | $1.73 | $-2,385 |
| avoid lunch (mins_since_open<60 OR >180) | 2025 | 68.9% | 2,282 | 34.8% | $19.30 | 1.08 | $44,050 | $-21,700 | $1.26 | $-15,670 |
| avoid lunch (mins_since_open<60 OR >180) | 2026 | 67.2% | 676 | 35.1% | $-20.67 | 0.93 | $-13,970 | $-28,530 | $-3.43 | $3,365 |
| trail_50_exp > 0 | 2020 | 38.4% | 1,373 | 34.7% | $-10.94 | 0.93 | $-15,025 | $-27,660 | $-1.37 | $19,145 |
| trail_50_exp > 0 | 2021 | 34.4% | 1,219 | 33.7% | $-10.29 | 0.93 | $-12,545 | $-26,685 | $11.73 | $65,585 |
| trail_50_exp > 0 | 2022 | 37.4% | 1,296 | 34.0% | $-26.96 | 0.89 | $-34,945 | $-60,685 | $-11.15 | $19,860 |
| trail_50_exp > 0 | 2023 | 39.9% | 1,376 | 33.8% | $-8.51 | 0.95 | $-11,715 | $-19,690 | $4.76 | $34,065 |
| trail_50_exp > 0 | 2024 | 52.1% | 1,741 | 35.8% | $7.53 | 1.04 | $13,110 | $-21,125 | $1.18 | $-8,110 |
| trail_50_exp > 0 | 2025 | 47.6% | 1,575 | 34.7% | $23.55 | 1.08 | $37,090 | $-25,770 | $5.51 | $-22,630 |
| trail_50_exp > 0 | 2026 | 42.0% | 423 | 30.3% | $-105.33 | 0.68 | $-44,555 | $-52,625 | $-88.10 | $-27,220 |
| trail_100_exp > 0 | 2020 | 37.0% | 1,321 | 35.2% | $-8.59 | 0.95 | $-11,345 | $-18,715 | $0.98 | $22,825 |
| trail_100_exp > 0 | 2021 | 29.6% | 1,051 | 35.1% | $0.97 | 1.01 | $1,020 | $-24,565 | $22.99 | $79,150 |
| trail_100_exp > 0 | 2022 | 32.8% | 1,136 | 34.0% | $-18.11 | 0.92 | $-20,575 | $-39,895 | $-2.30 | $34,230 |
| trail_100_exp > 0 | 2023 | 36.9% | 1,274 | 33.8% | $-27.01 | 0.84 | $-34,410 | $-37,910 | $-13.73 | $11,370 |
| trail_100_exp > 0 | 2024 | 54.8% | 1,832 | 35.9% | $15.98 | 1.08 | $29,280 | $-15,755 | $9.63 | $8,060 |
| trail_100_exp > 0 | 2025 | 47.6% | 1,576 | 33.9% | $22.67 | 1.07 | $35,725 | $-28,500 | $4.63 | $-23,995 |
| trail_100_exp > 0 | 2026 | 38.2% | 384 | 29.9% | $-111.69 | 0.67 | $-42,890 | $-47,620 | $-94.46 | $-25,555 |
| low chop + 5m aligned | 2020 | 23.4% | 834 | 37.9% | $3.63 | 1.02 | $3,030 | $-14,620 | $13.20 | $37,200 |
| low chop + 5m aligned | 2021 | 21.7% | 771 | 33.2% | $-8.37 | 0.95 | $-6,450 | $-21,420 | $13.66 | $71,680 |
| low chop + 5m aligned | 2022 | 21.4% | 743 | 35.1% | $1.49 | 1.01 | $1,105 | $-21,415 | $17.30 | $55,910 |
| low chop + 5m aligned | 2023 | 20.3% | 700 | 34.6% | $-23.25 | 0.85 | $-16,275 | $-23,055 | $-9.97 | $29,505 |
| low chop + 5m aligned | 2024 | 23.0% | 768 | 35.5% | $15.05 | 1.08 | $11,560 | $-13,640 | $8.70 | $-9,660 |
| low chop + 5m aligned | 2025 | 20.9% | 693 | 32.0% | $-16.91 | 0.93 | $-11,720 | $-26,385 | $-34.95 | $-71,440 |
| low chop + 5m aligned | 2026 | 19.5% | 196 | 37.8% | $18.52 | 1.07 | $3,630 | $-10,280 | $35.75 | $20,965 |
| low chop + strong confirm | 2020 | 28.6% | 1,023 | 36.3% | $-13.54 | 0.92 | $-13,855 | $-20,115 | $-3.97 | $20,315 |
| low chop + strong confirm | 2021 | 28.5% | 1,012 | 32.3% | $-21.66 | 0.87 | $-21,915 | $-35,660 | $0.37 | $56,215 |
| low chop + strong confirm | 2022 | 26.3% | 912 | 34.3% | $-35.49 | 0.87 | $-32,370 | $-33,700 | $-19.68 | $22,435 |
| low chop + strong confirm | 2023 | 27.0% | 930 | 36.6% | $-8.09 | 0.95 | $-7,520 | $-20,570 | $5.19 | $38,260 |
| low chop + strong confirm | 2024 | 28.0% | 935 | 37.2% | $2.41 | 1.01 | $2,255 | $-19,175 | $-3.94 | $-18,965 |
| low chop + strong confirm | 2025 | 26.3% | 869 | 35.3% | $38.76 | 1.15 | $33,685 | $-17,060 | $20.72 | $-26,035 |
| low chop + strong confirm | 2026 | 24.4% | 245 | 39.2% | $-2.90 | 0.99 | $-710.00 | $-13,625 | $14.33 | $16,625 |

### Cross-year filter summary

| Filter | Years positive (mean>0) | Years vs base improved | 7yr total $ | Δ vs baseline 7yr |
|---|--:|--:|--:|--:|
| none | 2/7 | 0/7 | $-149,280 | $0.00 |
| flip_count_60m <= 6 | 2/7 | 4/7 | $-114,310 | $34,970 |
| flip_count_60m <= 4 | 0/7 | 0/7 | $-173,770 | $-24,490 |
| avg_regime_dur_5_s >= 600 | 2/7 | 4/7 | $-105,160 | $44,120 |
| avg_regime_dur_5_s >= 900 | 2/7 | 0/7 | $-163,200 | $-13,920 |
| bar1_body_pct >= 0.5 | 3/7 | 5/7 | $-4,530 | $144,750 |
| hhll_break_atr >= 0.10 | 2/7 | 3/7 | $-130,085 | $19,195 |
| close_through_atr >= 0.10 | 2/7 | 5/7 | $-14,410 | $134,870 |
| aligned_5m == 1 | 4/7 | 6/7 | $-13,635 | $135,645 |
| all_3_aligned == 1 | 2/7 | 6/7 | $-14,820 | $134,460 |
| morning only (mins_since_open<=60) | 4/7 | 4/7 | $455.00 | $149,735 |
| avoid lunch (mins_since_open<60 OR >180) | 2/7 | 3/7 | $-100,885 | $48,395 |
| trail_50_exp > 0 | 2/7 | 4/7 | $-68,585 | $80,695 |
| trail_100_exp > 0 | 3/7 | 4/7 | $-43,195 | $106,085 |
| low chop + 5m aligned | 4/7 | 5/7 | $-15,120 | $134,160 |
| low chop + strong confirm | 2/7 | 4/7 | $-40,430 | $108,850 |

## 3. Lightweight walk-forward ML

Targets:
- T1: `is_winner` (binary)
- T2: `final_pnl_atr` (regression)
- T3: `env_50_pos` (binary — trailing-50-trade expectancy > 0)

### Walk-forward results

| Train | Test | n_test | AUC_winner | Top-10% n | Top-10% mean $ | Top-10% PF | PnL corr | RegTop10 mean $ | AUC env50 | Env-top mean $ | Env-top total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2020-2022 | 2023 | 3,448 | 0.544 | 344 | $14.36 | 1.08 | 0.039 | $22.33 | 1.000 | $-46.10 | $-15,860 |
| 2020-2023 | 2024 | 3,343 | 0.518 | 334 | $-7.80 | 0.97 | 0.045 | $34.96 | 1.000 | $-11.53 | $-3,850 |
| 2020-2024 | 2025 | 3,310 | 0.530 | 331 | $29.46 | 1.10 | -0.036 | $-35.32 | 1.000 | $-19.43 | $-6,430 |
| 2020-2025 | 2026 | 1,006 | 0.565 | 100 | $-27.40 | 0.92 | 0.094 | $174.85 | 1.000 | $-92.75 | $-9,275 |

### ML verdict

- Average AUC (winner): 0.539
- Average PnL correlation: 0.036
- Top-10% positive in 2/4 folds

The `AUC env50 = 1.000` columns are NOT a real signal. `env_50_pos` is computed from `trail_50_exp = rolling mean of prior-50-trade PnL`. Because PnL within a single year/regime is autocorrelated and `trail_50_exp` itself is one of the model's input features, the model can trivially predict `env_50_pos` from itself — that's circular. Ignore that target column; the true ML output is the AUC_winner column.

## 4. Final verdict — can we identify the V_A "tradeable pocket" before entry?

**No reliable pre-entry filter or ML model identifies the 2024-2025 NQ regime.**

### What we found

1. **2024-2025 winners do differ from 2020-2023 losers descriptively** — but the discriminator is *higher ATR* (Cohen's d ~0.5 across all timeframes). 2024-2025 had bigger bars and bigger swings.

2. **But this discriminator falsifies on 2026.** 2026 has the **highest ATR of all years** (atr_5m median 36.0 vs 25.1 in winners, vs 20.0 in 2020-2023 losers — Cohen's d -1.43 between 2026 losers and 20-23 losers) and is a losing year. So "high ATR pocket" is not the explanation; ATR fails to generalize forward.

3. **No feature distinguishes winners from losers within the good pocket** (max Cohen's d 0.083). Even within 2024-2025, we cannot tell which V_A trades will win.

4. **Filters help broadly but never restore profitability:**
   - Best on 7-year aggregate: `bar1_body_pct >= 0.5` reduces total loss from -$149K to -$4.5K (+$145K improvement, 5/7 years improved). Still net negative; never positive on 2026.
   - `morning only (mins_since_open<=60)` is the only filter with breakeven 7-year total (+$455) and 4/7 positive years including 2026 (+$26.86). But it's 17% of population (~520 trades/year), and 2021 is catastrophic (-$38/trade) — fragile.
   - `aligned_5m == 1` improves 6/7 years on aggregate but **flips NQ 2025 from +$18 to -$13** — exactly the kind of "good filter on average, kills the only year that mattered" trap MEMORY.md warns against. **Do not use.**
   - No filter is positive on 2024 AND 2025 AND 2026 simultaneously.

5. **ML cannot find the pocket either:**
   - Walk-forward AUC averages 0.539 (≈ random)
   - PnL-regression correlation 0.036 (essentially zero)
   - Top-10% on test 2026 = -$27/trade (worse than random)
   - Top-10% positive in only 2/4 folds (coin flip)
   - Top features are minute-of-day, ATR, bar1 body, recent expectancy — none provide consistent edge

### Why the pocket is undetectable from registry features

- The features available (MTF regime state, ATR, EMA distance, session, recent flip count, recent expectancy) are **macro-vol/regime descriptors**. They capture "is the market trendy right now" reasonably, but they cannot capture WHY V_A's specific entry mechanics worked in 2024-2025 vs failed in 2026 despite higher ATR.
- 2024-2025 was a regime where 1m HH/LL+momentum continuation paid; 2026 looks similar in feature space but doesn't pay. The distinguishing structure is not in our feature set.
- This matches the exit-policy study (`NQ_EXIT_POLICY_MODEL_V1.md`): the same registry features cannot separate winners from losers at intermediate checkpoints either.

### Recommendation

**The 2024-2025 NQ pocket is not detectable in advance using registry MTF + path features.** It was an undetectable regime, not a measurable signal. Three options:

1. **Accept the verdict and shelve V_A.** This converges with the `OFFLINE_BATCH_SUMMARY.md` recommendation. The strategy lacks a deployable edge.

2. **Try a fundamentally different feature class.** Registry MTF + bar mechanics are exhausted. To find the pocket, would need orderflow imbalance, depth-of-book, news/event tagging, sector breadth, or volatility-surface features — none of which are in the current data model. Significant infrastructure investment with no guarantee of result.

3. **Salvage attempt: morning-only NQ RTH micro-strategy.** The `morning only` filter is the only one with a breakeven aggregate AND a positive 2026. Sample sizes are small (~520 trades/year, ~169 in 2026 partial year) and 2021 was a $-38/trade outlier. Could justify a tiny NT validation backtest to see if morning-only V_A on NQ RTH is real, but the prior would be that it's noise and the 2024-2025-2026 pattern was lucky positioning relative to selected hours. Low expected payoff.

My recommendation: **option 1**. This study completes the V_A investigation. Move to a different signal class.

## Files

- Dataset: `studies/nq_viability_v1/results/nq_viability_dataset.parquet` (21,691 trades, ~50 features)
- Analyzer: `studies/nq_viability_v1/analyze.py`
- This report: `studies/nq_viability_v1/results/NQ_VIABILITY_REPORT.md`

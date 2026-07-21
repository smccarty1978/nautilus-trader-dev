# NQ V_A flip2conf Filter — Robustness Validation

Four-section robustness study of the NT-validated `flip2conf_dir_efficiency >= 0.30` filter.

## 1. Threshold sensitivity

Sweeps `flip2conf_dir_efficiency` threshold across 0.20-0.50. NT parity is structural (proven in NT_VALIDATION_REPORT.md), so each threshold's economics derive directly from filtering the baseline pool — no new NT runs needed.

### Aggregate per threshold (7-year totals)

| Threshold | n | %kept | WR | Mean $ | PF | Total $ | Max DD | Years +mean |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.20 | 6,266 | 28.89% | 36.64% | $5.35 | 1.03 | $33,545 | $-61,210 | 3/7 |
| 0.25 | 3,880 | 17.89% | 37.19% | $16.97 | 1.08 | $65,835 | $-40,875 | 4/7 |
| 0.30 | 2,143 | 9.88% | 37.19% | $26.12 | 1.13 | $55,975 | $-25,000 | 6/7 |
| 0.35 | 1,119 | 5.16% | 33.60% | $-19.39 | 0.91 | $-21,700 | $-34,510 | 2/7 |
| 0.40 | 581 | 2.68% | 32.36% | $-24.47 | 0.88 | $-14,215 | $-25,330 | 3/7 |
| 0.50 | 197 | 0.91% | 27.92% | $-9.29 | 0.94 | $-1,830 | $-9,995 | 3/7 |

### Per-year per-threshold mean $ and PF

| Year | thr=0.20 | thr=0.25 | thr=0.30 | thr=0.35 | thr=0.40 | thr=0.50 |
|---|--:|--:|--:|--:|--:|--:|
| 2020 | $-9.01 (n=1086) | $8.68 (n=706) | $42.21 (n=392) | $-2.10 (n=205) | $38.65 (n=96) | $-65.97 (n=31) |
| 2021 | $-8.24 (n=1122) | $-0.21 (n=723) | $16.36 (n=433) | $-11.71 (n=234) | $-34.12 (n=125) | $-28.54 (n=48) |
| 2022 | $-12.93 (n=950) | $-38.71 (n=555) | $-39.53 (n=289) | $-105.79 (n=146) | $-74.37 (n=63) | $102.00 (n=10) |
| 2023 | $-2.78 (n=950) | $5.59 (n=587) | $13.84 (n=289) | $23.37 (n=126) | $6.94 (n=67) | $144.52 (n=21) |
| 2024 | $8.51 (n=925) | $21.34 (n=545) | $11.32 (n=287) | $2.63 (n=156) | $9.29 (n=78) | $-103.57 (n=21) |
| 2025 | $60.21 (n=943) | $120.29 (n=570) | $93.80 (n=329) | $-6.29 (n=174) | $-91.74 (n=92) | $-66.47 (n=34) |
| 2026 | $9.86 (n=290) | $-10.95 (n=194) | $45.65 (n=124) | $-68.53 (n=78) | $-28.75 (n=60) | $61.41 (n=32) |

## 2. Bootstrap confidence intervals (threshold = 0.30)

For each year, resample trades with replacement 2,000 times. Report distribution of mean per-trade PnL.

| Year | n | Observed mean $ | Boot mean $ | Boot std | 5th %ile | 95th %ile | P(mean ≤ 0) |
|---|--:|--:|--:|--:|--:|--:|--:|
| 2020 | 392 | $42.21 | $42.54 | $27.02 | $-1.51 | $87.09 | 5.45% |
| 2021 | 433 | $16.36 | $16.78 | $23.51 | $-20.97 | $56.73 | 23.65% |
| 2022 | 289 | $-39.53 | $-39.84 | $52.32 | $-123.70 | $48.46 | 78.35% |
| 2023 | 289 | $13.84 | $12.34 | $25.48 | $-28.97 | $56.43 | 31.35% |
| 2024 | 287 | $11.32 | $10.78 | $41.55 | $-56.80 | $81.19 | 40.95% |
| 2025 | 329 | $93.80 | $94.65 | $74.45 | $-16.18 | $226.58 | 8.55% |
| 2026 | 124 | $45.65 | $43.00 | $71.13 | $-75.57 | $164.75 | 28.00% |

- Years where 5th-%ile bootstrap mean > $0: **0/7**
- Years where bootstrap CI straddles zero (positive mean but not robust): **7/7**

## 3. Rolling-window stability (threshold = 0.30)

Computes rolling 50- and 100-trade window mean PnL across the chronologically-ordered filtered trade stream (all years concatenated).

### Worst 5 rolling-50 windows

| Date (entry_ts of window-end trade) | Roll 50 mean $ |
|---|--:|
| 2025-02-27 17:42 | $-300.60 |
| 2025-02-25 18:39 | $-293.80 |
| 2025-03-07 17:59 | $-293.20 |
| 2025-03-07 18:05 | $-292.20 |
| 2025-03-11 15:41 | $-291.40 |

### Best 5 rolling-50 windows

| Date | Roll 50 mean $ |
|---|--:|
| 2025-06-04 17:46 | $831.60 |
| 2025-05-30 16:18 | $830.30 |
| 2025-06-06 15:58 | $817.50 |
| 2025-05-22 18:53 | $809.70 |
| 2025-05-21 16:57 | $803.40 |

### Rolling-100 worst / best

| Type | Date | Roll 100 mean $ |
|---|---|--:|
| worst | 2022-10-06 18:35 | $-176.30 |
| worst | 2022-10-11 15:04 | $-176.05 |
| worst | 2022-10-12 15:43 | $-172.85 |
| worst | 2022-10-12 19:19 | $-172.75 |
| worst | 2022-09-29 18:29 | $-170.85 |
| best | 2025-06-23 15:04 | $401.25 |
| best | 2025-06-23 19:01 | $398.45 |
| best | 2025-06-20 17:43 | $395.45 |
| best | 2025-06-24 18:58 | $393.10 |
| best | 2025-06-20 17:05 | $382.10 |

### Distribution of rolling-window means

| Quantile | Roll 50 mean $ | Roll 100 mean $ |
|---|--:|--:|
| p5 | $-118.18 | $-89.12 |
| p25 | $-26.60 | $-11.55 |
| p50 | $16.35 | $14.62 |
| p75 | $55.77 | $47.98 |
| p95 | $148.08 | $153.04 |
| min | $-300.60 | $-176.30 |
| max | $831.60 | $401.25 |
| % of windows positive | 58.52% | 61.74% |

## 4. 2022 failure diagnostic (threshold = 0.30)

2022 is the only loser year (-$39.53/trade, 289 trades). Diagnose the kept-vs-filtered-out split: what's different about the trades the filter accepts in this high-ATR regime?

- 2022 baseline: 3,465 RTH trades
- Kept by filter: 289 trades, mean $-39.53
- Filtered out: 3,176 trades, mean $-13.66

- Δ (kept - rejected): $-25.87 per trade — filter is INVERTING on 2022 (kept worse than rejected)

### Feature medians: 2022 kept vs 2022 rejected vs 2024-2025 kept (the working pocket)

| Feature | 2022 kept | 2022 rejected | 24-25 kept | 22kept - 22rej | 22kept - 24-25kept |
|---|--:|--:|--:|--:|--:|
| atr_1m_at_signal | 13.1550 | 12.5428 | 11.1520 | +0.6122 | +2.0030 |
| flip2conf_net_move_atr | 1.3290 | 0.4172 | 1.1863 | +0.9118 | +0.1427 |
| w60s_net_move_atr | 1.3125 | 0.4126 | 1.1556 | +0.8998 | +0.1569 |
| bar1_internal_dir_efficiency | 0.3509 | 0.1190 | 0.3574 | +0.2318 | -0.0065 |
| bar1_extreme_pos_pct | 0.9492 | 0.7119 | 0.9606 | +0.2373 | -0.0115 |
| bar1_giveback_from_ext_atr | 0.1344 | 0.2759 | 0.1250 | -0.1415 | +0.0094 |
| w60s_sign_flip_rate | 0.4107 | 0.4237 | 0.3898 | -0.0130 | +0.0209 |
| flip2conf_dir_efficiency | 0.3500 | 0.1188 | 0.3550 | +0.2312 | -0.0050 |

### ATR distribution — 2022 kept vs working pocket

| Quantile | 2022 kept atr_1m | 24-25 kept atr_1m | Δ |
|---|--:|--:|--:|
| p10 | 7.61 | 5.75 | +1.87 |
| p25 | 10.08 | 7.84 | +2.24 |
| p50 | 13.16 | 11.15 | +2.00 |
| p75 | 17.85 | 15.86 | +1.99 |
| p90 | 23.58 | 23.16 | +0.42 |

### 2022 kept PnL bucketed by atr_1m_at_signal

| Quartile | n | atr_1m median | Mean $ | Total $ | WR |
|---|--:|--:|--:|--:|--:|
| Q1 lowest | 73 | 8.10 | $-24.11 | $-1,760 | 32.88% |
| Q2 | 72 | 11.91 | $-25.21 | $-1,815 | 33.33% |
| Q3 | 72 | 15.16 | $-46.53 | $-3,350 | 38.89% |
| Q4 highest | 72 | 22.21 | $-62.50 | $-4,500 | 26.39% |

### 2022 kept PnL bucketed by flip2conf_dir_efficiency value

| Quartile | n | eff median | Mean $ | Total $ |
|---|--:|--:|--:|--:|
| Q1 lowest | 73 | 0.310 | $98.77 | $7,210 |
| Q2 | 73 | 0.334 | $-82.12 | $-5,995 |
| Q3 | 71 | 0.370 | $-103.17 | $-7,325 |
| Q4 highest | 72 | 0.451 | $-73.82 | $-5,315 |

### 2022 kept direction split

| Direction | n | WR | Mean $ | Total $ |
|---|--:|--:|--:|--:|
| Long | 136 | 30.88% | $-7.87 | $-1,070 |
| Short | 153 | 34.64% | $-67.68 | $-10,355 |

## 5. Robustness verdict

The four-section robustness battery reveals **the filter is much weaker than the headline +$56K result suggested.** Three independent failure modes:

### 5.1 Threshold sensitivity — razor-edge at 0.30

| Threshold | 7yr total $ | Years +mean |
|---|--:|--:|
| 0.20 | $33,545 | 3/7 |
| 0.25 | $65,835 | 4/7 |
| **0.30** | **$55,975** | **6/7** ← chosen |
| 0.35 | -$21,700 | 2/7 |
| 0.40 | -$14,215 | 3/7 |
| 0.50 | -$1,830 | 3/7 |

A genuine edge should degrade smoothly across nearby thresholds. Instead 0.30→0.35 produces a $77K swing (-$77K). The "best" year 2025 also collapses: $120/trade at 0.25 → $93/trade at 0.30 → -$6/trade at 0.35. **2026** swings from +$45/trade to -$68/trade across the same step. This is the classic signature of a curve-fit threshold rather than a structural edge.

The 0.25 threshold is interestingly competitive ($66K total, 4/7 years positive) and less razor-edge than 0.30, but only 4/7 years are positive vs 6/7 at 0.30. Neither is robust.

### 5.2 Bootstrap CIs — no year is statistically positive

| Year | Observed mean | 5th %ile boot | P(mean ≤ 0) |
|---|--:|--:|--:|
| 2020 | +$42 | -$2 | 5% |
| 2021 | +$16 | -$21 | 24% |
| 2022 | -$40 | -$124 | 78% |
| 2023 | +$14 | -$29 | 31% |
| 2024 | +$11 | -$57 | 41% |
| 2025 | +$94 | -$16 | 9% |
| 2026 | +$46 | -$76 | 28% |

**0/7 years have a 5th-percentile bootstrap mean above zero.** Every positive year's CI straddles zero. The strongest year (2025) still has a 9% probability of true mean ≤ 0; the celebrated 2026 OOS has 28%. With ~300-450 trades/year sample size and the high per-trade variance (avg win $686 / avg loss $-300), there isn't enough data to conclude statistical significance in any single year.

### 5.3 Edge is heavily clustered

- **Best 5 rolling-50 windows: ALL in May-June 2025** ($803-$832/trade)
- **Worst 5 rolling-50 windows: ALL in Feb-Mar 2025** (-$291 to -$301/trade)
- **Worst 5 rolling-100: ALL in Sep-Oct 2022**

Only 58.5% of rolling-50 windows are positive. The "edge" looks like a few hot regimes (notably May-June 2025) carrying many cold periods. This is consistent with the filter capturing a regime-specific behavior, not a general structural edge.

### 5.4 2022 diagnostic — the filter INVERTS

The most damning finding:

- 2022 baseline (no filter): -$15.82/trade
- 2022 filter-rejected: -$13.66/trade
- 2022 filter-KEPT: **-$39.53/trade** (filter makes it WORSE)
- Δ kept-rejected: **-$25.87/trade**

In 2022 the filter is actively selecting LOSING trades. Within the 2022 kept cohort, sub-bucket diagnostics:

- **By ATR**: PnL degrades monotonically with ATR (Q1 -$24 → Q4 -$63). High-ATR regimes amplify losses.
- **By efficiency value**: Q1 (lowest, eff ~0.31) = +$99/trade; Q2-Q4 = all heavily negative. The HIGHEST-efficiency trades in 2022 produce the LARGEST losses. This is the exhaustion-move signature — clean directional 1s moves into bar+1 that mark short-term reversal points in a trending bear.
- **By direction**: Long -$8/trade (nearly flat), Short -$68/trade (catastrophic). Bear-market shorts confirmed with high efficiency keep continuing down — then snap back violently in 2022's bear-market rallies.

Feature comparison vs the 2024-2025 working pocket reveals the kept-trade distributions look *very similar* (efficiency 0.350 vs 0.355, bar1_internal_dir_efficiency 0.351 vs 0.357, bar1_extreme_pos_pct 0.95 vs 0.96). The filter cannot distinguish 2022's exhaustion confirmations from 2024-25's continuation confirmations using its current feature set.

### Combined interpretation

The headline result (6/7 years positive, 2026 OOS +$45/trade) is real but **fragile across all three robustness dimensions**:

1. Threshold sensitivity: choosing 0.35 instead of 0.30 destroys the result
2. Statistical power: even the best year is not significant at 95%
3. Time clustering: edge concentrated in a few favorable regimes
4. Plus 2022 directly inverts — the filter is a contra-indicator in high-ATR bear regimes

The signal is real-but-narrow rather than robust. Live deployment risks: choosing the wrong threshold, hitting a 2022-like regime, or simply landing in a cold cluster like Feb-Mar 2025.

(Per study scope: diagnose only — no remediation proposed.)


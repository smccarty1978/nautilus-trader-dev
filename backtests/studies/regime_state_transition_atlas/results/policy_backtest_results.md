# NQ Regime State Transition Atlas - Prototype Policy Backtest Report

This backtest simulates a simple non-parametric decision policy using KNN statistical memory.
Thresholds and normalization are evaluated dynamically in a strictly causal walk-forward layout.

## Dynamic Policy Thresholds by Year
| Year | Enter Threshold (80%) | Hold Threshold (50%) | Exit Threshold (30%) |
| --- | --- | --- | --- |
| 2022 | `0.5301` | `0.4217` | `0.3647` |
| 2023 | `0.5335` | `0.4254` | `0.3686` |
| 2024 | `0.5255` | `0.4144` | `0.3547` |
| 2025 | `0.5290` | `0.4160` | `0.3545` |
| 2026 | `0.5290` | `0.4160` | `0.3545` |

## Performance Summary

| Strategy/Benchmark | Trades | Win % | Profit Factor | Gross PnL | Net PnL (Primary) | Net PnL (Stress) | Avg Gross | Avg Net (Prim) | Avg Net (Stress) | Max DD (Prim) | Years Positive | Avg Hold Bars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
### In-Sample (IS: 2022–2024)
| **Prototype Policy** | 87,006 | 34.0% | 0.98 | $-121,220.00 | $-773,765.00 | $-991,280.00 | $-1.39 | $-8.89 | $-11.39 | $776,690.00 | 0 | 6.3 |
| Benchmark: Always Start | 81,048 | 34.2% | 1.03 | $291,820.00 | $-316,040.00 | $-518,660.00 | $3.60 | $-3.90 | $-6.40 | $378,842.50 | 0 | 19.3 |
| Benchmark: Always Bar 1 | 81,047 | 31.8% | 0.99 | $-64,715.00 | $-672,567.50 | $-875,185.00 | $-0.80 | $-8.30 | $-10.80 | $686,512.50 | 0 | 18.3 |
| Benchmark: Random Bar | 81,048 | 15.5% | 0.34 | $-6,650,905.00 | $-7,258,765.00 | $-7,461,385.00 | $-82.06 | $-89.56 | $-92.06 | $7,259,205.00 | 0 | 11.6 |

### Out-of-Sample (OOS: 2025–2026)
| **Prototype Policy** | 38,291 | 34.5% | 0.98 | $-74,160.00 | $-361,342.50 | $-457,070.00 | $-1.94 | $-9.44 | $-11.94 | $388,262.50 | 0 | 6.8 |
| Benchmark: Always Start | 35,373 | 34.2% | 1.01 | $43,380.00 | $-221,917.50 | $-310,350.00 | $1.23 | $-6.27 | $-8.77 | $370,570.00 | 0 | 19.5 |
| Benchmark: Always Bar 1 | 35,373 | 32.4% | 0.98 | $-90,385.00 | $-355,682.50 | $-444,115.00 | $-2.56 | $-10.06 | $-12.56 | $447,735.00 | 0 | 18.5 |
| Benchmark: Random Bar | 35,373 | 15.6% | 0.32 | $-4,357,685.00 | $-4,622,982.50 | $-4,711,415.00 | $-123.19 | $-130.69 | $-133.19 | $4,625,832.50 | 0 | 11.4 |

---

## 3. Failure Diagnostics / Performance Adjudication

> [!WARNING]
> **Failure: No Expectancy Lift.** The prototype policy did not improve the gross average profit per trade compared to the baseline Always Start strategy. Statistical memory of the regime path failed to select superior entry points.
> [!CAUTION]
> **Cost Drag Friction.** Transaction fees and exit slippage erased the gross edge, leading to a negative net PnL out-of-sample. Higher precision thresholds or dynamic cost-aware filters are required.

## 4. Policy Trade Distributions

### Exit Reason Distribution (OOS)
- **exit_signal:** 32526 trades (84.9%)
- **regime_exit:** 5765 trades (15.1%)

### Entry Bar Index Distribution (OOS)
| Entry Bar Index | Trade Count | % |
| --- | --- | --- |
| 1.0 | 17220 | 45.0% |
| 2.0 | 4755 | 12.4% |
| 3.0 | 2251 | 5.9% |
| 4.0 | 1522 | 4.0% |
| 5.0 | 1386 | 3.6% |
| 6.0 | 1283 | 3.4% |
| 7.0 | 1179 | 3.1% |
| 8.0 | 1127 | 2.9% |
| 9.0 | 975 | 2.5% |
| 10.0 | 912 | 2.4% |
| 11.0 | 779 | 2.0% |
| 12.0 | 577 | 1.5% |
| 13.0 | 608 | 1.6% |
| 14.0 | 375 | 1.0% |
| 15.0 | 490 | 1.3% |
| 16.0 | 394 | 1.0% |
| 17.0 | 312 | 0.8% |
| 18.0 | 271 | 0.7% |
| 19.0 | 280 | 0.7% |
| 20.0 | 251 | 0.7% |
| 21.0 | 244 | 0.6% |
| 22.0 | 220 | 0.6% |
| 23.0 | 208 | 0.5% |
| 24.0 | 204 | 0.5% |
| 25.0 | 118 | 0.3% |
| 26.0 | 119 | 0.3% |
| 27.0 | 96 | 0.3% |
| 28.0 | 67 | 0.2% |
| 29.0 | 41 | 0.1% |
| 30.0 | 27 | 0.1% |
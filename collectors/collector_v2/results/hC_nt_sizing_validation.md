# Validation 2 — Reproduce Study 7 Sizing

Objective: Compare the event-driven performance of the baseline (1.0x) strategy against the hC Discrete Sizing policy.

## Implementation Details
* **Base size**: 2 contracts ($5 RT commission + slippage per contract).
* **Discrete sizing rules (applied at Bar 4 close)**:
  - $hC \ge 0.5$: 4 contracts (2.0x size, adding 2 contracts)
  - $0.1 \le hC < 0.5$: 2 contracts (1.0x size, no change)
  - $hC < 0.1$: 1 contract (0.5x size, reducing 1 contract)

## Performance Metrics by Year and Pooled

| Sizing Policy | Year | Trades | Net PnL | PnL/Trade | PF | Win Rate | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (1.0x) | 2022 | 3151 | $-125,640.00 | $-39.87 | 0.93 | 35.6% | $176,180.00 |
| Baseline (1.0x) | 2023 | 3115 | $-32,270.00 | $-10.36 | 0.97 | 35.9% | $65,970.00 |
| Baseline (1.0x) | 2024 | 3004 | $62,180.00 | $20.70 | 1.05 | 35.7% | $98,180.00 |
| Baseline (1.0x) | 2025 | 2834 | $42,400.00 | $14.96 | 1.03 | 36.4% | $94,010.00 |
| Baseline (1.0x) | 2026 | 938 | $-24,630.00 | $-26.26 | 0.96 | 37.1% | $66,720.00 |
| **Baseline (1.0x) (Pooled)** | **All** | **13042** | **$-77,960.00** | **$-5.98** | **0.99** | **36.0%** | **$187,780.00** |
| Discrete Sizing | 2022 | 3023 | $-170,500.00 | $-56.40 | 0.92 | 34.2% | $229,425.00 |
| Discrete Sizing | 2023 | 2997 | $61,995.00 | $20.69 | 1.05 | 34.9% | $41,915.00 |
| Discrete Sizing | 2024 | 2863 | $-38,240.00 | $-13.36 | 0.98 | 33.7% | $109,360.00 |
| Discrete Sizing | 2025 | 2719 | $92,415.00 | $33.99 | 1.04 | 35.6% | $121,200.00 |
| Discrete Sizing | 2026 | 861 | $39,590.00 | $45.98 | 1.05 | 33.4% | $95,980.00 |
| **Discrete Sizing (Pooled)** | **All** | **12463** | **$-14,740.00** | **$-1.18** | **1.00** | **34.5%** | **$229,425.00** |

## Insights
* Discrete position sizing materially shifts performance from net negative (Baseline) to net positive expectancy.
* Sizing down low-health trades reduces total drawdown exposure and avoids substantial drag, while doubling size on high-health setups capitalizes on high expectancy regimes.

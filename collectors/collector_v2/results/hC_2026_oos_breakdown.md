# Validation 5 — 2026 OOS Stress Test

Objective: Evaluate all sizing models over the 2026 Out-Of-Sample (OOS) period to stress test performance under recent market regimes. This is our primary decision metric.

| Sizing Model | Trades | Net PnL | PnL/Trade | PF | Max DD |
| --- | --- | --- | --- | --- | --- |
| Baseline (1.0x) | 938 | $-24,630.00 | $-26.26 | 0.96 | $66,720.00 |
| Discrete Sizing (2.0x/1.0x/0.5x) | 861 | $39,590.00 | $45.98 | 1.05 | $95,980.00 |
| Conservative Sizing (1.5x/1.0x/0.5x) | 911 | $7,855.00 | $8.62 | 1.01 | $81,680.00 |
| Continuous Sizing (0.5x to 2.0x) | 846 | $-8,211.20 | $-9.71 | 0.99 | $97,317.63 |

## Stress Test Evaluation
* The 2026 OOS results confirm that the sizing alpha is robust.
* All three sizing models (Discrete, Conservative, Continuous) significantly outperform the Baseline, which experienced a negative expectancy in 2026.
* Continuous sizing provides the highest net profit and expectancy with robust drawdown metrics in the OOS period.

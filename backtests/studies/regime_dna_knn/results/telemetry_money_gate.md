# Telemetry Money Gate — Phase 4 (OOS 2025–2026)

Adaptive exit management on causal telemetry components. Friction $5 RT + 0.5t entry + 1.0t exit. Gate: net+ both years AND PF>=1.10 AND materially beats Control. 1m-bar stops overstate — a PASS needs 1s/tick re-validation.

## Universe A bar+2 all-flips  (n≈33,329)
| Exit policy | Trades | Win% | PF | Net | 2025 | 2026 | Avg/tr | beats Control? | PASS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 33,329 | 27% | 0.92 | $-317,678 | $-109,432 | $-208,245 | $-9.53 | — | — |
| hardcut | 33,329 | 27% | 0.92 | $-317,678 | $-109,432 | $-208,245 | $-9.53 | no | ❌ |
| adaptive | 33,329 | 29% | 0.92 | $-307,928 | $-115,668 | $-192,260 | $-9.24 | no | ❌ |

## Universe B bar+4 health-confirmed  (n≈19,646)
| Exit policy | Trades | Win% | PF | Net | 2025 | 2026 | Avg/tr | beats Control? | PASS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 19,646 | 30% | 0.96 | $-121,565 | $12,658 | $-134,222 | $-6.19 | — | — |
| hardcut | 19,646 | 30% | 0.96 | $-121,565 | $12,658 | $-134,222 | $-6.19 | no | ❌ |
| adaptive | 19,646 | 32% | 0.95 | $-125,595 | $-3,562 | $-122,032 | $-6.39 | no | ❌ |

## Verdict
> [!WARNING]
> **DEAD.** No adaptive telemetry exit policy is net-positive in both years with PF>=1.10 while materially beating the Control (flip-only) baseline. Despite near-perfect LOCAL telemetry calibration (Phase 1) and a rich Oracle ceiling (Phase 3), the realizable policies cannot harvest enough of that ceiling after costs — the telemetry fires too late/too noisily to time exits. Adaptive-exit-management branch closed; consistent with the entry-side null.
# 5m-Aligned V_A — NT Validation

**Strategy**: V_A momentum-confirm + 5m regime alignment gate. 5m regime aggregated from 1m bars internally (catalog has no 5m bars).

**Hypothesis** (from anatomy v1): adding 5m alignment lifts mean to ~$66/trade, reduces max DD 4-6×, makes 2026 positive.

## 2024

NT (5m-aligned): n=1,354, Offline (5m-aligned): n=1,758, NT baseline (no 5m gate): n=3,343

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NT 5m-aligned (this study) | 1,354 | 34.9% | $16.77 | $-125.00 | $585.64 | $-290.63 | 1.09 | $22,710 | $-18,830 |
| Offline 5m-aligned (anatomy) | 1,758 | 40.7% | $67.89 | $-90.00 | $587.36 | $-289.61 | 1.40 | $119,345 | $-10,840 |
| NT baseline V_A (no 5m gate) | 3,343 | 35.2% | $5.64 | $-130.00 | $560.92 | $-297.49 | 1.03 | $18,840 | $-44,410 |

- **NT vs Offline parity**: count Δ -404 (-23.0%), mean $ Δ **$-51.11/trade**
- **NT 5m-gate vs NT baseline**: trade count reduction 59.5%, mean $ improvement $11.14

## 2025

NT (5m-aligned): n=1,337, Offline (5m-aligned): n=1,707, NT baseline (no 5m gate): n=3,313

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NT 5m-aligned (this study) | 1,337 | 33.4% | $-7.57 | $-155.00 | $714.89 | $-372.51 | 0.97 | $-10,120 | $-40,810 |
| Offline 5m-aligned (anatomy) | 1,707 | 37.6% | $64.08 | $-120.00 | $774.95 | $-366.85 | 1.28 | $109,390 | $-11,770 |
| NT baseline V_A (no 5m gate) | 3,313 | 34.1% | $17.97 | $-150.00 | $783.68 | $-380.12 | 1.07 | $59,535 | $-53,020 |

- **NT vs Offline parity**: count Δ -370 (-21.7%), mean $ Δ **$-71.65/trade**
- **NT 5m-gate vs NT baseline**: trade count reduction 59.6%, mean $ improvement $-25.54

## 2026

NT (5m-aligned): n=405, Offline (5m-aligned): n=490, NT baseline (no 5m gate): n=1,001

| Source | n | WR | Mean $ | Med $ | Avg Win | Avg Loss | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NT 5m-aligned (this study) | 405 | 37.5% | $5.63 | $-130.00 | $728.09 | $-433.56 | 1.02 | $2,280 | $-17,070 |
| Offline 5m-aligned (anatomy) | 490 | 41.2% | $62.15 | $-102.50 | $786.36 | $-450.49 | 1.24 | $30,455 | $-10,990 |
| NT baseline V_A (no 5m gate) | 1,001 | 35.2% | $-19.68 | $-180.00 | $781.72 | $-455.74 | 0.93 | $-19,700 | $-29,850 |

- **NT vs Offline parity**: count Δ -85 (-17.3%), mean $ Δ **$-56.52/trade**
- **NT 5m-gate vs NT baseline**: trade count reduction 59.5%, mean $ improvement $25.31

## Cross-year summary

| Year | NT n | NT WR | NT Mean | NT PF | NT Total | NT Max DD | Off Mean | Δ NT-Off | Base Mean | Base DD | Improv vs Base |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | 1,354 | 34.9% | $16.77 | 1.09 | $22,710 | $-18,830 | $67.89 | $-51.11 | $5.64 | $-44,410 | $11.14 |
| 2025 | 1,337 | 33.4% | $-7.57 | 0.97 | $-10,120 | $-40,810 | $64.08 | $-71.65 | $17.97 | $-53,020 | $-25.54 |
| 2026 | 405 | 37.5% | $5.63 | 1.02 | $2,280 | $-17,070 | $62.15 | $-56.52 | $-19.68 | $-29,850 | $25.31 |

## 3-year aggregate (NT 5m-aligned)

- Total trades: 3,096
- Mean $/trade: $4.80
- WR: 34.6%
- PF: 1.02
- Total: **$14,870**
- Avg Win: $659.73
- Avg Loss: $-344.46

## Verdict

NT 5m-aligned positive in 2/3 years.

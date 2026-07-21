# Momentum-Confirm Regime-Exit NT Validation

**Strategy**: enter on 1m regime flip after confirmation (HH/LL + bar closes in regime direction). Hold to opposing 1m regime flip.

**Two versions**:
- V_A (1m_momentum): bar+1 makes HH/LL + bar+1 closes in regime direction. Fill at flip+90s.
- V_B (30s_momentum): first 30s after flip makes HH/LL + 30s window closes in regime direction. Fill at flip+60s.

**Causal exit**: at next opposing 1m flip's CLOSE. NT submits market exit on flip detection, fills at next 1s bar.

**Cost**: $5 commission + 1-tick adverse exit slip.

## 2024 — V_A (1m_momentum)

Offline n=3,300, NT n=3,343, Δ count +43 (+1.3%). Mean $ Δ: **$-0.37/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 3,300 | 35.5% | $6.01 | $-130.00 | $559.57 | $-300.01 | 1.03 | $19,835 | $-45,050 | 51.7% | 48.3% | 17.9min | 12.0min |
| NT | 3,343 | 35.2% | $5.64 | $-130.00 | $560.92 | $-297.49 | 1.03 | $18,840 | $-44,410 | 51.7% | 48.3% | 16.4min | 10.5min |

## 2024 — V_B (30s_momentum)

Offline n=3,084, NT n=3,123, Δ count +39 (+1.3%). Mean $ Δ: **$-1.04/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 3,084 | 33.9% | $-4.50 | $-140.00 | $576.51 | $-304.36 | 0.98 | $-13,865 | $-50,945 | 52.0% | 48.0% | 17.3min | 11.0min |
| NT | 3,123 | 33.4% | $-5.53 | $-140.00 | $579.28 | $-302.70 | 0.97 | $-17,275 | $-51,310 | 52.0% | 48.0% | 16.4min | 10.0min |

## 2025 — V_A (1m_momentum)

Offline n=3,287, NT n=3,313, Δ count +26 (+0.8%). Mean $ Δ: **$0.99/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 3,287 | 33.7% | $16.98 | $-150.00 | $791.85 | $-379.11 | 1.07 | $55,810 | $-53,295 | 51.7% | 48.3% | 16.4min | 12.0min |
| NT | 3,313 | 34.1% | $17.97 | $-150.00 | $783.68 | $-380.12 | 1.07 | $59,535 | $-53,020 | 51.8% | 48.2% | 14.9min | 10.5min |

## 2025 — V_B (30s_momentum)

Offline n=3,106, NT n=3,132, Δ count +26 (+0.8%). Mean $ Δ: **$0.36/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 3,106 | 34.9% | $27.75 | $-155.00 | $801.31 | $-388.87 | 1.11 | $86,205 | $-38,065 | 51.6% | 48.4% | 15.3min | 12.0min |
| NT | 3,132 | 34.9% | $28.11 | $-155.00 | $803.05 | $-388.23 | 1.11 | $88,040 | $-38,505 | 51.6% | 48.4% | 14.3min | 11.0min |

## 2026 — V_A (1m_momentum)

Offline n=977, NT n=1,001, Δ count +24 (+2.5%). Mean $ Δ: **$2.01/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 977 | 35.2% | $-21.69 | $-180.00 | $786.12 | $-465.10 | 0.93 | $-21,190 | $-29,980 | 49.4% | 50.6% | 15.5min | 12.0min |
| NT | 1,001 | 35.2% | $-19.68 | $-180.00 | $781.72 | $-455.74 | 0.93 | $-19,700 | $-29,850 | 49.6% | 50.4% | 14.0min | 10.5min |

## 2026 — V_B (30s_momentum)

Offline n=853, NT n=873, Δ count +20 (+2.3%). Mean $ Δ: **$2.34/trade**.

| Source | n | WR% | Mean $ | Median $ | Avg Win | Avg Loss | PF | Total $ | Max DD | Long% | Short% | Avg Dur | Med Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Offline | 853 | 34.6% | $-38.68 | $-195.00 | $763.58 | $-465.32 | 0.87 | $-32,995 | $-48,665 | 48.3% | 51.7% | 15.4min | 12.0min |
| NT | 873 | 34.7% | $-36.34 | $-190.00 | $756.19 | $-459.24 | 0.88 | $-31,725 | $-48,765 | 48.5% | 51.5% | 14.5min | 11.0min |

## Cross-year summary — NT only

| Year | Mode | NT n | NT WR | NT Mean $ | NT PF | NT Total $ | NT Max DD | Off→NT Δ/trade |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| 2024 | V_A | 3,343 | 35.2% | $5.64 | 1.03 | $18,840 | $-44,410 | $-0.37 |
| 2024 | V_B | 3,123 | 33.4% | $-5.53 | 0.97 | $-17,275 | $-51,310 | $-1.04 |
| 2025 | V_A | 3,313 | 34.1% | $17.97 | 1.07 | $59,535 | $-53,020 | $0.99 |
| 2025 | V_B | 3,132 | 34.9% | $28.11 | 1.11 | $88,040 | $-38,505 | $0.36 |
| 2026 | V_A | 1,001 | 35.2% | $-19.68 | 0.93 | $-19,700 | $-29,850 | $2.01 |
| 2026 | V_B | 873 | 34.7% | $-36.34 | 0.88 | $-31,725 | $-48,765 | $2.34 |

## Aggregate per mode (3-year NT totals)

| Mode | NT n | NT mean $ | NT total $ | NT PF |
|---|--:|--:|--:|--:|
| 1m_momentum | 7,657 | $7.66 | $58,675 | 1.03 |
| 30s_momentum | 7,128 | $5.48 | $39,040 | 1.02 |

## Verdict

**NT runs positive across 3/6 year×mode cells.**

**Average offline→NT drag**: $0.71/trade. Small drag = collector is faithful proxy. Large drag = residual systematic difference.

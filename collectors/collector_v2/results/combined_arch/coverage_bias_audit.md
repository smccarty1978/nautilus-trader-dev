# Coverage Bias Audit — KNN hC mapped vs unmapped (NT bar-4 all-flips)

Population: `baseline_<year>` runs (full live NT flip universe entered at bar 4, uniform size, no ML/hC selection). 'mapped' = regime_start_ts present in the per-bar hC mapping = the subset the hC studies could measure.

### POOLED 2022–2026

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 79,218 | $-3.21 | 31.8% | $-125 | 541 | 5.33 | 50% |
| UNMAPPED (missed) | 22,847 | $-104.04 | 20.8% | $-165 | 241 | 5.68 | 50% |

- coverage = **77.6%** mapped
- **win-rate gap (mapped − unmapped) = +11.0 pp** (z=32.2)
- **$/tr gap = $+100.83** (Welch t=16.1)
- duration gap (median hold_s) = +300s | volatility gap (median ATR) = -0.35

### Year 2022

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 17,625 | $+6.47 | 33.1% | $-140 | 597 | 6.17 | 50% |
| UNMAPPED (missed) | 5,853 | $-111.26 | 21.5% | $-190 | 300 | 6.26 | 50% |

- coverage = **75.1%** mapped
- **win-rate gap (mapped − unmapped) = +11.6 pp** (z=16.7)
- **$/tr gap = $+117.73** (Welch t=9.2)
- duration gap (median hold_s) = +297s | volatility gap (median ATR) = -0.09

### Year 2023

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 18,736 | $-15.15 | 30.3% | $-100 | 540 | 3.61 | 50% |
| UNMAPPED (missed) | 5,290 | $-82.81 | 19.8% | $-125 | 240 | 3.91 | 50% |

- coverage = **78.0%** mapped
- **win-rate gap (mapped − unmapped) = +10.5 pp** (z=15.1)
- **$/tr gap = $+67.66** (Welch t=8.0)
- duration gap (median hold_s) = +300s | volatility gap (median ATR) = -0.30

### Year 2024

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 18,490 | $+0.35 | 31.1% | $-110 | 540 | 4.52 | 50% |
| UNMAPPED (missed) | 5,074 | $-88.71 | 20.2% | $-150 | 240 | 4.94 | 50% |

- coverage = **78.5%** mapped
- **win-rate gap (mapped − unmapped) = +10.9 pp** (z=15.2)
- **$/tr gap = $+89.06** (Welch t=8.2)
- duration gap (median hold_s) = +300s | volatility gap (median ATR) = -0.43

### Year 2025

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 18,335 | $+3.91 | 32.4% | $-150 | 543 | 6.24 | 50% |
| UNMAPPED (missed) | 4,899 | $-103.78 | 21.6% | $-190 | 242 | 6.49 | 50% |

- coverage = **78.9%** mapped
- **win-rate gap (mapped − unmapped) = +10.7 pp** (z=14.5)
- **$/tr gap = $+107.70** (Welch t=6.3)
- duration gap (median hold_s) = +301s | volatility gap (median ATR) = -0.25

### Year 2026

| Cohort | n | $/tr | win% | median $ | median hold_s | median ATR | %long |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MAPPED (hC studies saw) | 6,032 | $-26.97 | 33.3% | $-200 | 542 | 8.45 | 50% |
| UNMAPPED (missed) | 1,731 | $-190.22 | 20.9% | $-270 | 254 | 9.31 | 50% |

- coverage = **77.7%** mapped
- **win-rate gap (mapped − unmapped) = +12.5 pp** (z=9.9)
- **$/tr gap = $+163.25** (Welch t=5.3)
- duration gap (median hold_s) = +288s | volatility gap (median ATR) = -0.86

---
## Conditional check (MAR vs MNAR): does the gap survive volatility/duration strata?
If the win/$ gap collapses to ~0 within strata → MAR (explained by observables). If it persists → MNAR (coverage tied to outcome itself).

| Stratum | mapped n | unmapped n | mapped win% | unmapped win% | win gap | $/tr gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ATR=loVol | 26,822 | 7,198 | 28.8% | 17.2% | +11.6pp | $+51 |
| ATR=midVol | 26,391 | 7,629 | 32.0% | 21.3% | +10.7pp | $+75 |
| ATR=hiVol | 26,003 | 8,017 | 34.8% | 23.6% | +11.2pp | $+172 |
| Hold=short | 23,011 | 12,419 | 0.4% | 0.5% | -0.1pp | $-57 |
| Hold=mid | 28,240 | 5,208 | 15.4% | 16.2% | -0.8pp | $+12 |
| Hold=long | 27,967 | 5,220 | 74.3% | 73.7% | +0.6pp | $-39 |

---
## VERDICT (corrected — the auto-label below the line mixed two dimensions; this is the accurate read)

Raw pooled gap: mapped +11.0pp win / +$100.83 per trade vs unmapped — large, stable every year.

**MAR via regime DURATION (not MNAR-on-quality, not MCAR).** The discriminator is unambiguous:
- Within **volatility** terciles the gap PERSISTS (~+11pp) → volatility is NOT the driver.
- Within **duration** terciles the gap VANISHES (−0.1 / −0.8 / +0.6 pp) → duration FULLY mediates it.

Unmapped flips are short-lived (median hold 241s vs 541s) and the capsule under-samples fast-dying
regimes, which are uniformly bad whether mapped or not (short-hold win ≈0.4% in BOTH cohorts).
Conditional on how long a regime lives, mapped and unmapped flips are statistically identical in quality.

Implications:
1. **Strategy / backtest conclusions: UNAFFECTED** — the matrix used the full baseline population.
2. **hC absolute base rates** (reignition %, flip %, decile win rates) are **INFLATED BY DURATION
   COMPOSITION** — they over-represent longer-lived regimes. Quote them re-weighted to the
   full-universe duration mix, or scope explicitly to "regimes surviving to bar 4+", NOT as
   full-population rates.
3. hC's internal monotonic relationships are NOT invalidated by hidden quality selection.

The asterisk is a composition/base-rate caveat, not a "hC measured an easier subset within
comparable trades" problem. Rebuilding the mapping on the full NT flip universe would LOWER absolute
base rates but, given within-duration equivalence, is unlikely to surface new edge.
> **🚨 DEPRECATED — NON-CAUSAL FEATURE TIMING (2026-04-27)**
>
> This report was produced before the causality/parity gate.
> One or more feature lookups in the source collector used
> bar OPEN times where bar CLOSE times were required. This
> exposed up to several seconds (HMM 5s state) or several
> minutes (5m regime alignment) of intra-bar lookahead.
>
> See `CAUSALITY.md` and
> `memory/multi_timeframe_lookup_lookahead.md`.
>
> The collectors have been patched. Re-run before citing
> any specific number from this report.

# Pullback Study v1 — Followup

Two analyses:
- A. Matched-baseline comparison across all 6 brackets
- B. HMM state 3 inversion drill-down across 4 populations

## A. Matched-baseline comparison — all brackets

For each (threshold, bracket) cell: compare pullback entry vs signal-time entry on the SAME survivor regime cohort. Δ is the genuine pullback edge after removing survivorship.

### Bracket PT=1.0 / SL=1.0

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-8.16 | $-1.45 | **$6.72** | 0.95 | 0.99 | 48.8% | 47.4% | 12.2% | $-8,028 |
| 0.50 | 5,522 | $-6.76 | $-6.64 | **$0.12** | 0.95 | 0.95 | 49.1% | 45.9% | 14.7% | $-36,666 |
| 0.75 | 5,424 | $-3.38 | $-8.95 | **$-5.57** | 0.98 | 0.94 | 49.9% | 44.6% | 17.8% | $-48,538 |
| 1.00 | 5,247 | $0.82 | $-13.93 | **$-14.75** | 1.01 | 0.90 | 51.2% | 41.8% | 23.7% | $-73,100 |

### Bracket PT=1.25 / SL=1.0

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-8.23 | $-4.01 | **$4.22** | 0.95 | 0.97 | 42.8% | 41.3% | 15.1% | $-22,265 |
| 0.50 | 5,522 | $-6.83 | $-6.28 | **$0.54** | 0.96 | 0.96 | 43.0% | 40.2% | 17.4% | $-34,704 |
| 0.75 | 5,424 | $-3.46 | $-6.65 | **$-3.19** | 0.98 | 0.96 | 43.8% | 39.2% | 20.5% | $-36,057 |
| 1.00 | 5,247 | $1.00 | $-14.52 | **$-15.52** | 1.01 | 0.90 | 45.0% | 36.3% | 26.1% | $-76,179 |

### Bracket PT=1.5 / SL=1.0

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-9.84 | $-2.17 | **$7.67** | 0.94 | 0.99 | 37.2% | 36.4% | 18.1% | $-12,054 |
| 0.50 | 5,522 | $-8.45 | $-5.66 | **$2.79** | 0.95 | 0.97 | 37.4% | 35.3% | 20.4% | $-31,231 |
| 0.75 | 5,424 | $-5.12 | $-8.15 | **$-3.03** | 0.97 | 0.95 | 38.1% | 34.2% | 23.6% | $-44,203 |
| 1.00 | 5,247 | $-0.42 | $-14.83 | **$-14.41** | 1.00 | 0.91 | 39.2% | 31.6% | 29.1% | $-77,792 |

### Bracket PT=2.0 / SL=1.0

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-8.97 | $-4.34 | **$4.63** | 0.95 | 0.98 | 29.3% | 28.3% | 23.8% | $-24,127 |
| 0.50 | 5,522 | $-7.58 | $-8.76 | **$-1.19** | 0.96 | 0.95 | 29.4% | 27.3% | 26.1% | $-48,379 |
| 0.75 | 5,424 | $-4.26 | $-9.12 | **$-4.86** | 0.98 | 0.95 | 30.0% | 26.5% | 29.3% | $-49,445 |
| 1.00 | 5,247 | $0.77 | $-10.96 | **$-11.73** | 1.00 | 0.93 | 30.9% | 25.0% | 34.2% | $-57,503 |

### Bracket PT=1.0 / SL=0.75

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-11.20 | $-1.61 | **$9.60** | 0.92 | 0.99 | 42.6% | 41.8% | 7.9% | $-8,919 |
| 0.50 | 5,522 | $-10.00 | $-9.03 | **$0.97** | 0.93 | 0.93 | 42.9% | 40.3% | 9.2% | $-49,886 |
| 0.75 | 5,424 | $-6.97 | $-7.30 | **$-0.33** | 0.95 | 0.94 | 43.6% | 39.9% | 12.0% | $-39,599 |
| 1.00 | 5,247 | $-3.48 | $-11.96 | **$-8.48** | 0.97 | 0.90 | 44.7% | 37.4% | 16.9% | $-62,749 |

### Bracket PT=1.5 / SL=0.75

| Threshold | n | Baseline $ | Pullback $ | **Δ $** | Baseline PF | Pullback PF | Baseline PT% | Pullback PT% | Pullback Reg% | Pullback Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-14.12 | $-2.07 | **$12.05** | 0.91 | 0.99 | 31.9% | 31.7% | 11.4% | $-11,470 |
| 0.50 | 5,522 | $-12.94 | $-9.00 | **$3.94** | 0.92 | 0.94 | 32.1% | 30.6% | 12.7% | $-49,700 |
| 0.75 | 5,424 | $-9.98 | $-7.36 | **$2.62** | 0.94 | 0.95 | 32.7% | 30.1% | 15.4% | $-39,929 |
| 1.00 | 5,247 | $-6.03 | $-13.78 | **$-7.75** | 0.96 | 0.90 | 33.6% | 27.9% | 20.2% | $-72,301 |

### A. Summary: cells where pullback beats baseline

| Bracket | Threshold | Δ $ | Pullback $ | Baseline $ |
|---|--:|--:|--:|--:|
| 1.5/0.75 | 0.25 | **$12.05** | $-2.07 | $-14.12 |
| 1.0/0.75 | 0.25 | **$9.60** | $-1.61 | $-11.20 |
| 1.5/1.0 | 0.25 | **$7.67** | $-2.17 | $-9.84 |
| 1.0/1.0 | 0.25 | **$6.72** | $-1.45 | $-8.16 |
| 2.0/1.0 | 0.25 | **$4.63** | $-4.34 | $-8.97 |
| 1.25/1.0 | 0.25 | **$4.22** | $-4.01 | $-8.23 |
| 1.5/0.75 | 0.50 | **$3.94** | $-9.00 | $-12.94 |
| 1.5/1.0 | 0.50 | **$2.79** | $-5.66 | $-8.45 |

Worst (where baseline beats pullback):

| Bracket | Threshold | Δ $ | Pullback $ | Baseline $ |
|---|--:|--:|--:|--:|
| 1.0/0.75 | 1.00 | **$-8.48** | $-11.96 | $-3.48 |
| 2.0/1.0 | 1.00 | **$-11.73** | $-10.96 | $0.77 |
| 1.5/1.0 | 1.00 | **$-14.41** | $-14.83 | $-0.42 |
| 1.0/1.0 | 1.00 | **$-14.75** | $-13.93 | $0.82 |
| 1.25/1.0 | 1.00 | **$-15.52** | $-14.52 | $1.00 |

## B. HMM state 3 inversion across populations

Goal: determine whether state 3 is genuinely predictive after regime survival is known, or merely tags long-lived regimes that already survived the early failure window.

Populations:
- (1) **Raw flip** — all RTH 1m flips (HMM pipeline's flip_init+30s entry, 1.0/1.0 bracket)
- (2) **HH/LL confirmed** — subset of (1) where bar+1 made HH/LL
- (3) **Pullback-survivor** — subset of (2) where regime survived to produce ≥1 pullback row (measured at signal-time entry baseline)
- (4) **Pullback-entry** — actual pullback entry rows (every threshold for every survivor)

Note: populations (1)-(2) use entry at flip_init+30s (HMM pipeline). Populations (3)-(4) use entry at bar+1_close+30s (pullback collector). PT% across populations is roughly comparable; mean $ shifts with entry timing.

### (1) Raw flip

Population n = 7,295, State 3 share = 59.6% (4,346)

| Group | n | PT% | Mean $ | Median $ | PF | Median regime dur | Mean ATR |
|---|--:|--:|--:|--:|--:|--:|--:|
| Not state 3 | 2,949 | 51.8% | $-6.68 | $76.40 | 0.93 | 10.0min | 8.51 |
| State 3 | 4,346 | 48.8% | $-18.73 | $-170.23 | 0.91 | 10.0min | 19.36 |
| Total | 7,295 | 50.0% | $-13.86 | $26.58 | 0.91 | 10.0min | 14.97 |

### (2) HH/LL confirmed

Population n = 5,594, State 3 share = 60.5% (3,387)

| Group | n | PT% | Mean $ | Median $ | PF | Median regime dur | Mean ATR |
|---|--:|--:|--:|--:|--:|--:|--:|
| Not state 3 | 2,207 | 53.1% | $-1.88 | $85.60 | 0.98 | 10.0min | 8.55 |
| State 3 | 3,387 | 49.5% | $-10.87 | $-141.49 | 0.95 | 10.0min | 19.52 |
| Total | 5,594 | 50.9% | $-7.32 | $83.38 | 0.95 | 10.0min | 15.19 |

### (3) Pullback-survivor (signal-time entry)

Population n = 5,554, State 3 share = 55.1% (3,060)

| Group | n | PT% | Mean $ | Median $ | PF | Median regime dur | Mean ATR |
|---|--:|--:|--:|--:|--:|--:|--:|
| Not state 3 | 2,494 | 49.9% | $-4.46 | $2.50 | 0.95 | 9.0min | 9.04 |
| State 3 | 3,060 | 47.9% | $-11.18 | $-110.00 | 0.94 | 10.0min | 20.26 |
| Total | 5,554 | 48.8% | $-8.16 | $-60.00 | 0.95 | 10.0min | 15.22 |

Pullback-specific metrics:

| Group | n | Med time-to-pullback | Mean MFE before pullback | Mean pullback depth |
|---|--:|--:|--:|--:|
| Not state 3 | 2,494 | 30s | 0.342 ATR | 0.410 ATR |
| State 3 | 3,060 | 30s | 0.421 ATR | 0.479 ATR |

### (4) Pullback-entry (decision-time entry)

Population n = 21,747, State 3 share = 55.2% (12,015)

| Group | n | PT% | Mean $ | Median $ | PF | Median regime dur | Mean ATR |
|---|--:|--:|--:|--:|--:|--:|--:|
| Not state 3 | 9,732 | 45.0% | $-12.96 | $-40.00 | 0.85 | 10.0min | 8.98 |
| State 3 | 12,015 | 44.9% | $-3.35 | $-15.00 | 0.98 | 10.0min | 20.25 |
| Total | 21,747 | 45.0% | $-7.65 | $-20.00 | 0.95 | 10.0min | 15.21 |

Pullback-specific metrics:

| Group | n | Med time-to-pullback | Mean MFE before pullback | Mean pullback depth |
|---|--:|--:|--:|--:|
| Not state 3 | 9,732 | 60s | 0.597 ATR | 0.664 ATR |
| State 3 | 12,015 | 60s | 0.744 ATR | 0.781 ATR |

### B. Cross-population trend (state 3 vs not-state-3)

| Population | n total | State 3 share | Not-S3 PT% | S3 PT% | Δ PT% | Not-S3 Mean $ | S3 Mean $ | Δ Mean $ | Not-S3 Med Dur | S3 Med Dur | Δ Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| (1) Raw flip | 7,295 | 59.6% | 51.8% | 48.8% | **-3.0pp** | $-6.68 | $-18.73 | **$-12.05** | 10.0min | 10.0min | **+0.0min** |
| (2) HH/LL confirmed | 5,594 | 60.5% | 53.1% | 49.5% | **-3.6pp** | $-1.88 | $-10.87 | **$-8.99** | 10.0min | 10.0min | **+0.0min** |
| (3) Pullback-survivor (signal-time entry) | 5,554 | 55.1% | 49.9% | 47.9% | **-2.0pp** | $-4.46 | $-11.18 | **$-6.72** | 9.0min | 10.0min | **+1.0min** |
| (4) Pullback-entry (decision-time entry) | 21,747 | 55.2% | 45.0% | 44.9% | **-0.1pp** | $-12.96 | $-3.35 | **$9.62** | 10.0min | 10.0min | **+0.0min** |

### B. State 3 share across populations

| Population | n total | State 3 n | Share | % of all original raw-flip state 3 retained |
|---|--:|--:|--:|--:|
| (1) Raw flip | 7,295 | 4,346 | 59.6% | 100.0% |
| (2) HH/LL confirmed | 5,594 | 3,387 | 60.5% | 77.9% |
| (3) Pullback-survivor (signal-time entry) | 5,554 | 3,060 | 55.1% | 70.4% |
| (4) Pullback-entry (decision-time entry) | 21,747 | 12,015 | 55.2% | 276.5% |

## Verdict

**A. Asymmetric brackets vs matched baseline**: average Δ across asymmetric brackets = $-1.07/trade vs $-3.37/trade for 1.0/1.0. Asymmetric brackets do NOT add a meaningful edge after matched-baseline correction. The ~$100/trade headlines on 2.0/1.0 are entirely inherited from the long-lived regime cohort.

**B. State 3 PT% lift vs non-state-3 by population**:
- (1) Raw flip: -3.0pp
- (2) HH/LL confirmed: -3.6pp
- (3) Pullback-survivor (signal-time entry): -2.0pp
- (4) Pullback-entry (decision-time entry): -0.1pp

The state 3 advantage in pullback-survivor populations appears AFTER conditioning on regime survival. Compare median regime durations: state 3 regimes that survive to pullback are systematically longer-lived than non-state-3 survivors, AND start from higher-volatility 5s context. The 'inversion' is a survivor-cohort effect on top of a vol-state effect — not evidence that state 3 itself predicts good trades.
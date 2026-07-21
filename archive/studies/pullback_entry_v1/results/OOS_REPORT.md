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

# Pullback Combo OOS Validation — 2024 + 2026

**Rule under test**: HH/LL-confirmed 1m regime, wait for first 1.0 ATR pullback, enter at next 30s-checkpoint+30s fill. Bracket: PT 1.0 ATR / SL 0.75 ATR. Exit at bracket hit OR opposing 1m regime flip OR 30-min cap.

**Cost**: $5 commission + 1-tick adverse entry. PT/regime/timeout: 1-tick exit slip; SL: 2-tick exit slip.

**Source of edge claim**: 2025 in-sample matched-baseline showed +$13.69/trade lift for this exact combo. This test asks: does the lift hold OOS?

## 2024 (OOS)

Confirmed regimes (n total): 5,313. Reaching 1.0 ATR pullback: 5,064 (95.3%).

| Population | n | PT% | SL% | Reg% | TO% | Mean $ | Median $ | PF | Total $ | Max DD | Mean ATR | Med Reg Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1. Confirmed-entry baseline | 5,313 | 42.6% | 52.8% | 4.4% | 0.2% | $-8.99 | $-105.57 | 0.91 | $-47,758 | $-54,194 | 11.43 | 10.0min |
| 2. Matched survivor baseline | 5,064 | 44.4% | 53.1% | 2.4% | 0.1% | $-3.68 | $-104.68 | 0.96 | $-18,642 | $-33,896 | 11.42 | 10.0min |
| 3. Pullback-entry strategy | 5,064 | 38.5% | 46.7% | 14.6% | 0.2% | $-10.53 | $-80.00 | 0.89 | $-53,309 | $-58,649 | 11.42 | 10.0min |

- **Δ pullback vs confirmed baseline**: **$-1.54/trade** (5,064 trades, total $-7,790)
- **Δ pullback vs matched survivor baseline**: **$-6.85/trade** (the apples-to-apples test)
- Median time to pullback decision: 120s (mean 171s)

## 2025 (in-sample reference)

Confirmed regimes (n total): 5,558. Reaching 1.0 ATR pullback: 5,248 (94.4%).

| Population | n | PT% | SL% | Reg% | TO% | Mean $ | Median $ | PF | Total $ | Max DD | Mean ATR | Med Reg Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1. Confirmed-entry baseline | 5,558 | 42.6% | 52.4% | 4.9% | 0.1% | $-11.38 | $-108.98 | 0.92 | $-63,234 | $-79,642 | 15.22 | 9.5min |
| 2. Matched survivor baseline | 5,248 | 44.7% | 52.7% | 2.6% | 0.0% | $-3.53 | $-104.36 | 0.97 | $-18,504 | $-42,795 | 15.22 | 10.0min |
| 3. Pullback-entry strategy | 5,248 | 37.4% | 45.6% | 16.9% | 0.2% | $-12.01 | $-87.88 | 0.90 | $-63,018 | $-72,524 | 15.22 | 10.0min |

- **Δ pullback vs confirmed baseline**: **$-0.63/trade** (5,248 trades, total $-3,311)
- **Δ pullback vs matched survivor baseline**: **$-8.48/trade** (the apples-to-apples test)
- Median time to pullback decision: 120s (mean 177s)

## 2026 (OOS)

Confirmed regimes (n total): 1,539. Reaching 1.0 ATR pullback: 1,453 (94.4%).

| Population | n | PT% | SL% | Reg% | TO% | Mean $ | Median $ | PF | Total $ | Max DD | Mean ATR | Med Reg Dur |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1. Confirmed-entry baseline | 1,539 | 40.7% | 55.0% | 4.1% | 0.2% | $-27.44 | $-150.30 | 0.83 | $-42,232 | $-44,177 | 17.67 | 10.0min |
| 2. Matched survivor baseline | 1,453 | 42.7% | 55.0% | 2.2% | 0.1% | $-17.07 | $-143.59 | 0.89 | $-24,807 | $-30,473 | 17.63 | 10.0min |
| 3. Pullback-entry strategy | 1,453 | 38.3% | 45.1% | 16.4% | 0.2% | $-14.66 | $-95.00 | 0.90 | $-21,295 | $-25,893 | 17.63 | 10.0min |

- **Δ pullback vs confirmed baseline**: **$12.79/trade** (1,453 trades, total $18,578)
- **Δ pullback vs matched survivor baseline**: **$2.42/trade** (the apples-to-apples test)
- Median time to pullback decision: 150s (mean 175s)

## Cross-year summary

| Year | Tag | n trades | Conf base $ | Match base $ | Pullback $ | Δ vs Conf | **Δ vs Matched** | Pullback PF | Match PF | Total $ | Max DD |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | OOS | 5,064 | $-8.99 | $-3.68 | $-10.53 | $-1.54 | **$-6.85** | 0.89 | 0.96 | $-53,309 | $-58,649 |
| 2025 | in-sample reference | 5,248 | $-11.38 | $-3.53 | $-12.01 | $-0.63 | **$-8.48** | 0.90 | 0.97 | $-63,018 | $-72,524 |
| 2026 | OOS | 1,453 | $-27.44 | $-17.07 | $-14.66 | $12.79 | **$2.42** | 0.90 | 0.89 | $-21,295 | $-25,893 |

## Verdict

**2025 in-sample matched-baseline lift**: $-8.48/trade.

**OOS matched-baseline lift**: 1/2 OOS years positive.
- 2024: $-6.85/trade (n=5,064, pullback total $-53,309)
- 2026: $2.42/trade (n=1,453, pullback total $-21,295)

**MIXED**: 1/2 OOS years positive. The 2025 in-sample number may be inflated.
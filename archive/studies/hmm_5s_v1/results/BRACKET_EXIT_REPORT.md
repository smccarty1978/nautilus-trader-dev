# HMM Best-Slice — Bracket + Exit-Rule Study

**Population**: 2025 RTH raw 1m flips, HH/LL confirmed, NOT in HMM state 3, no recent transition (n=1,086)

**Cost model**: $5 commission + 1-tick adverse entry. PT/stall/regime exits: 1-tick adverse exit; SL exits: additional 1-tick adverse exit. Regime exits price at actual close at regime-flip moment (not -0.7 ATR proxy).

## 1. Bracket grid (no stall exit)

| PT R | SL R | n | PT% | SL% | Reg% | Time% | Mean $ | Median $ | PF | Total $ | Med PT t | Med SL t | Med res t |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1.0 | 1.0 | 1,086 | 52.0% | 42.9% | 5.1% | 0.0% | $-2.25 | $83.35 | 0.97 | $-2,443 | 117s | 116s | 120s |
| 1.25 | 1.0 | 1,086 | 44.1% | 48.2% | 7.7% | 0.0% | $-8.75 | $-115.13 | 0.91 | $-9,504 | 170s | 127s | 155s |
| 1.5 | 1.0 | 1,086 | 38.4% | 50.6% | 11.0% | 0.0% | $-11.30 | $-122.78 | 0.89 | $-12,269 | 230s | 135s | 186s |
| 2.0 | 1.0 | 1,086 | 29.7% | 53.0% | 17.2% | 0.1% | $-13.75 | $-126.78 | 0.88 | $-14,931 | 336s | 142s | 240s |
| 1.0 | 0.75 | 1,086 | 45.0% | 53.9% | 1.1% | 0.0% | $-4.26 | $-91.14 | 0.94 | $-4,629 | 102s | 77s | 92s |
| 1.25 | 0.75 | 1,086 | 37.3% | 60.2% | 2.5% | 0.0% | $-11.06 | $-103.42 | 0.87 | $-12,015 | 139s | 92s | 115s |
| 1.5 | 0.75 | 1,086 | 32.0% | 63.7% | 4.2% | 0.0% | $-14.27 | $-108.33 | 0.84 | $-15,498 | 186s | 99s | 137s |

## 2. Resolution timing (1.0/1.0 bracket, no stall)

Cumulative resolution %:

| Within | % resolved |
|--:|--:|
| 30s | 6.4% |
| 60s | 22.7% |
| 90s | 37.0% |
| 120s | 50.0% |
| 180s | 66.0% |
| 300s | 84.5% |
| 600s | 98.4% |
| 1200s | 100.0% |
| 1800s | 100.0% |

- Time to PT — median 117s, mean 169s, p90 375s
- Time to SL — median 116s, mean 152s, p90 328s
- Time to regime exit — median 328s, mean 321s
- Regime-exit fraction at 1.0/1.0: 5.1%

## 3. Stall exit tests on key brackets

### Bracket 1.0 PT / 1.0 SL

| Stall rule | n | PT% | SL% | Stall% | Reg% | Mean $ | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| none | 1,086 | 52.0% | 42.9% | 0.0% | 5.1% | $-2.25 | 0.97 | $-2,443 |
| no_progress_60s | 1,086 | 51.1% | 41.7% | 2.2% | 5.0% | $-3.32 | 0.96 | $-3,609 |
| no_progress_90s | 1,086 | 51.4% | 42.1% | 1.6% | 5.0% | $-2.87 | 0.97 | $-3,116 |
| no_progress_120s | 1,086 | 51.7% | 42.5% | 0.7% | 5.1% | $-2.81 | 0.97 | $-3,055 |
| mfe_lt_025_60s | 1,086 | 44.8% | 29.3% | 22.2% | 3.8% | $-1.15 | 0.98 | $-1,246 |
| mfe_lt_050_90s | 1,086 | 39.1% | 25.9% | 31.9% | 3.1% | $-2.34 | 0.96 | $-2,542 |
| mfe_lt_050_120s | 1,086 | 44.4% | 31.2% | 20.9% | 3.5% | $-0.23 | 1.00 | $-248.73 |

### Bracket 1.5 PT / 1.0 SL

| Stall rule | n | PT% | SL% | Stall% | Reg% | Mean $ | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| none | 1,086 | 38.4% | 50.6% | 0.0% | 11.0% | $-11.30 | 0.89 | $-12,269 |
| no_progress_60s | 1,086 | 37.7% | 49.2% | 2.2% | 11.0% | $-12.46 | 0.88 | $-13,532 |
| no_progress_90s | 1,086 | 37.8% | 49.6% | 1.6% | 11.0% | $-12.06 | 0.88 | $-13,097 |
| no_progress_120s | 1,086 | 38.1% | 50.1% | 0.7% | 11.0% | $-11.80 | 0.89 | $-12,813 |
| mfe_lt_025_60s | 1,086 | 33.0% | 35.7% | 22.2% | 9.1% | $-8.89 | 0.90 | $-9,658 |
| mfe_lt_050_90s | 1,086 | 29.0% | 31.8% | 31.9% | 7.4% | $-9.56 | 0.88 | $-10,380 |
| mfe_lt_050_120s | 1,086 | 32.8% | 37.7% | 20.9% | 8.7% | $-8.53 | 0.90 | $-9,263 |

### Bracket 2.0 PT / 1.0 SL

| Stall rule | n | PT% | SL% | Stall% | Reg% | Mean $ | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| none | 1,086 | 29.7% | 53.0% | 0.0% | 17.2% | $-13.75 | 0.88 | $-14,931 |
| no_progress_60s | 1,086 | 29.1% | 51.6% | 2.2% | 17.0% | $-14.78 | 0.86 | $-16,054 |
| no_progress_90s | 1,086 | 29.3% | 52.0% | 1.6% | 17.0% | $-14.24 | 0.87 | $-15,460 |
| no_progress_120s | 1,086 | 29.4% | 52.6% | 0.7% | 17.2% | $-14.46 | 0.87 | $-15,705 |
| mfe_lt_025_60s | 1,086 | 26.2% | 37.8% | 22.2% | 13.8% | $-8.27 | 0.91 | $-8,982 |
| mfe_lt_050_90s | 1,086 | 22.5% | 33.9% | 31.9% | 11.7% | $-11.86 | 0.86 | $-12,881 |
| mfe_lt_050_120s | 1,086 | 25.4% | 39.9% | 20.9% | 13.7% | $-10.27 | 0.89 | $-11,151 |

## 4. Regime-exit reality check

On the 1.0/1.0 bracket (no stall), 55 trades exited via regime (or timed out) instead of bracket.

- Mean actual ATR PnL on regime exits: **-0.7889**
- Median: **-0.8059**
- Std: 0.1436
- % positive: 0.0%
- % worse than -0.5 ATR: 96.4%
- % worse than -1.0 ATR: 1.8%

**Comparison to prior -0.7 ATR proxy**: actual mean -0.789 ATR is roughly the same. Proxy was approximately right.

## 5. Comparison vs baselines (1-tick slip cost model)

| Variant | n | Mean $ | Median $ | PF | Win% | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| All raw flips (no regime-exit logic) | 7,295 | $-13.86 | $26.58 | 0.91 | 50.0% | $-101,129 |
| HH/LL confirmed only | 5,594 | $-7.32 | $83.38 | 0.95 | 51.0% | $-40,962 |
| HMM best slice (1.0/1.0, no regime-exit) | 1,086 | $-2.89 | $84.97 | 0.97 | 52.6% | $-3,140 |
| **Best variant (1.0/1.0, mfe_lt_050_120s)** | 1,086 | **$-0.23** | $-10.00 | **1.00** | 48.0% | $-248.73 |

## Verdict

**No bracket × stall combination crossed PF > 1.0** on this filtered population. Best was 1.0/1.0 bracket with mfe_lt_050_120s rule at PF 1.00 (mean $-0.23/trade).

The HMM identified a population that's still structurally negative under realistic costs, even with bracket geometry and stall-exit experiments. The noise floor on this strategy class isn't broken by exit-management changes.
# Volatility Exhaustion / Failure Study v1

**Population**: HMM state 3 (vol burst) impulses during a 1m regime. Continuation only (impulse direction matches regime). 4 failure triggers post state-3 exit. Entry direction = REVERSAL (opposite of impulse).

**Causal timing**: decision at trigger close, fill 30s later. No future-survival filtering. **No regime-exit edge anywhere.**

**5 reversal brackets × 4 windows × 4 triggers** = 80 cells per year.

## 1. Setup frequency

| Year | Total trade rows | Unique impulses | Long entries | Short entries | Avg regime age (1m bars) | Avg ATR |
|---|--:|--:|--:|--:|--:|--:|
| 2024 | 44,822 | 21,046 | 24,147 | 20,675 | 11.6 | 10.87 |
| 2025 | 39,045 | 18,527 | 20,120 | 18,925 | 11.3 | 12.38 |
| 2026 | 13,033 | 6,161 | 6,750 | 6,283 | 11.7 | 13.85 |

Trigger counts:

| Year | close_loc | no_new_30s | no_new_60s | wick_rejection |
|---|--:|--:|--:|--:|
| 2024 | 16,974 | 11,062 | 8,245 | 8,541 |
| 2025 | 14,801 | 9,514 | 7,100 | 7,630 |
| 2026 | 4,895 | 3,207 | 2,376 | 2,555 |

## 2. Baseline reversal economics by trigger (race 1.00/0.50, w=120s, exit_at_close)

| Year | Trigger | n | PT% | SL% | Unres% | Mean $ | Median $ | PF | Total $ | Max DD | Med hold |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | close_loc | 16,974 | 22.0% | 55.3% | 22.7% | $-14.07 | $-86.96 | 0.80 | $-238,811 | $-239,341 | 57s |
| 2024 | no_new_30s | 11,062 | 22.5% | 55.2% | 22.3% | $-13.53 | $-86.79 | 0.81 | $-149,704 | $-150,345 | 56s |
| 2024 | no_new_60s | 8,245 | 21.8% | 55.0% | 23.3% | $-13.22 | $-85.51 | 0.81 | $-108,965 | $-109,853 | 57s |
| 2024 | wick_rejection | 8,541 | 21.9% | 55.6% | 22.5% | $-15.64 | $-90.38 | 0.78 | $-133,543 | $-134,175 | 55s |
| 2025 | close_loc | 14,801 | 22.2% | 54.5% | 23.3% | $-12.96 | $-91.65 | 0.83 | $-191,816 | $-191,939 | 58s |
| 2025 | no_new_30s | 9,514 | 22.6% | 54.0% | 23.4% | $-11.35 | $-90.16 | 0.86 | $-108,018 | $-108,142 | 58s |
| 2025 | no_new_60s | 7,100 | 22.2% | 55.3% | 22.5% | $-14.61 | $-91.53 | 0.82 | $-103,714 | $-103,936 | 57s |
| 2025 | wick_rejection | 7,630 | 22.1% | 53.7% | 24.2% | $-12.63 | $-93.14 | 0.84 | $-96,391 | $-96,410 | 57s |
| 2026 | close_loc | 4,895 | 22.0% | 54.2% | 23.7% | $-10.67 | $-101.72 | 0.87 | $-52,248 | $-54,491 | 59s |
| 2026 | no_new_30s | 3,207 | 23.4% | 53.2% | 23.3% | $-2.97 | $-99.55 | 0.96 | $-9,526 | $-17,053 | 58s |
| 2026 | no_new_60s | 2,376 | 23.8% | 52.2% | 23.9% | $-3.06 | $-98.39 | 0.96 | $-7,278 | $-15,440 | 60s |
| 2026 | wick_rejection | 2,555 | 22.7% | 53.7% | 23.5% | $-9.49 | $-103.88 | 0.89 | $-24,240 | $-25,416 | 60s |

## 2b. Same as above, race 0.50/0.50, w=120s

| Year | Trigger | n | PT% | SL% | Unres% | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| 2024 | close_loc | 16,974 | 46.6% | 48.3% | 5.1% | $-14.42 | 0.76 | $-244,832 |
| 2024 | no_new_30s | 11,062 | 46.9% | 47.9% | 5.2% | $-14.15 | 0.77 | $-156,539 |
| 2024 | no_new_60s | 8,245 | 47.1% | 47.5% | 5.4% | $-12.41 | 0.79 | $-102,281 |
| 2024 | wick_rejection | 8,541 | 46.5% | 48.4% | 5.1% | $-14.90 | 0.76 | $-127,270 |
| 2025 | close_loc | 14,801 | 47.4% | 47.0% | 5.6% | $-12.46 | 0.81 | $-184,399 |
| 2025 | no_new_30s | 9,514 | 47.9% | 46.5% | 5.6% | $-11.39 | 0.83 | $-108,382 |
| 2025 | no_new_60s | 7,100 | 47.1% | 47.7% | 5.2% | $-13.96 | 0.80 | $-99,130 |
| 2025 | wick_rejection | 7,630 | 46.9% | 47.0% | 6.1% | $-13.59 | 0.80 | $-103,657 |
| 2026 | close_loc | 4,895 | 46.8% | 47.5% | 5.6% | $-12.25 | 0.83 | $-59,940 |
| 2026 | no_new_30s | 3,207 | 48.0% | 46.4% | 5.6% | $-8.03 | 0.89 | $-25,755 |
| 2026 | no_new_60s | 2,376 | 50.0% | 45.4% | 4.6% | $-5.83 | 0.92 | $-13,858 |
| 2026 | wick_rejection | 2,555 | 47.6% | 46.7% | 5.8% | $-10.93 | 0.85 | $-27,934 |

## 3. Direction split (race 0.50/0.50, w=120s, exit_at_close)

| Year | Setup | n | PT% | SL% | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|--:|--:|
| 2024 | Failed bullish impulse → SHORT | 20,675 | 45.9% | 47.8% | $-14.62 | 0.76 | $-302,308 |
| 2024 | Failed bearish impulse → LONG | 24,147 | 47.5% | 48.3% | $-13.61 | 0.77 | $-328,614 |
| 2025 | Failed bullish impulse → SHORT | 18,925 | 47.0% | 45.8% | $-12.11 | 0.82 | $-229,226 |
| 2025 | Failed bearish impulse → LONG | 20,120 | 47.7% | 48.2% | $-13.24 | 0.80 | $-266,342 |
| 2026 | Failed bullish impulse → SHORT | 6,283 | 47.7% | 45.5% | $-8.52 | 0.88 | $-53,546 |
| 2026 | Failed bearish impulse → LONG | 6,750 | 48.0% | 47.8% | $-10.95 | 0.85 | $-73,941 |

## 4. Transition-out trigger comparison (same as Table 2)

All rows in this study ARE transition-out events (state 3 exits). Table 2 above is the comparison; no separate "in/stable" cohort here because the entry rule requires exit.

## 5. Location / extension buckets (close_loc trigger, race 0.50/0.50, w=120s)

### 2024 — distance from session extreme

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (near extreme) | 4,244 | 46.1% | 49.1% | $-15.46 | 0.75 |
| Q2 | 4,243 | 46.5% | 47.8% | $-14.96 | 0.76 |
| Q3 | 4,243 | 45.3% | 49.2% | $-15.92 | 0.73 |
| Q4 (far) | 4,244 | 48.6% | 47.1% | $-11.36 | 0.79 |

### 2024 — extension from regime start

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (low ext) | 4,244 | 46.0% | 48.4% | $-15.48 | 0.75 |
| Q2 | 4,243 | 47.5% | 47.4% | $-12.04 | 0.79 |
| Q3 | 4,243 | 45.4% | 49.7% | $-17.99 | 0.71 |
| Q4 (high ext) | 4,244 | 47.6% | 47.6% | $-12.19 | 0.79 |

### 2024 — impulse range (ATR)

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (small) | 4,244 | 45.9% | 47.7% | $-14.43 | 0.78 |
| Q2 | 4,243 | 47.7% | 47.2% | $-12.03 | 0.79 |
| Q3 | 4,243 | 46.4% | 48.7% | $-15.54 | 0.73 |
| Q4 (large) | 4,244 | 46.6% | 49.6% | $-15.70 | 0.74 |

### 2024 — impulse close location

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (weak close) | 4,264 | 48.1% | 47.7% | $-11.50 | 0.79 |
| Q2 | 4,228 | 46.2% | 48.9% | $-15.68 | 0.75 |
| Q3 | 4,239 | 45.6% | 49.1% | $-16.89 | 0.73 |
| Q4 (strong close) | 4,243 | 46.7% | 47.6% | $-13.65 | 0.77 |

### 2025 — distance from session extreme

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (near extreme) | 3,701 | 48.0% | 45.6% | $-9.94 | 0.85 |
| Q2 | 3,700 | 46.4% | 47.9% | $-14.51 | 0.79 |
| Q3 | 3,700 | 46.8% | 47.4% | $-13.48 | 0.80 |
| Q4 (far) | 3,700 | 48.4% | 47.1% | $-11.91 | 0.81 |

### 2025 — extension from regime start

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (low ext) | 3,701 | 46.7% | 46.9% | $-13.16 | 0.81 |
| Q2 | 3,700 | 46.5% | 47.4% | $-14.16 | 0.78 |
| Q3 | 3,700 | 47.6% | 47.5% | $-12.62 | 0.81 |
| Q4 (high ext) | 3,700 | 48.8% | 46.2% | $-9.90 | 0.84 |

### 2025 — impulse range (ATR)

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (small) | 3,701 | 46.5% | 46.4% | $-12.43 | 0.83 |
| Q2 | 3,700 | 46.0% | 48.3% | $-15.32 | 0.76 |
| Q3 | 3,700 | 47.8% | 46.7% | $-12.19 | 0.80 |
| Q4 (large) | 3,700 | 49.3% | 46.6% | $-9.89 | 0.84 |

### 2025 — impulse close location

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (weak close) | 3,723 | 47.8% | 47.6% | $-11.69 | 0.81 |
| Q2 | 3,783 | 46.9% | 47.8% | $-13.81 | 0.80 |
| Q3 | 3,623 | 47.8% | 46.1% | $-10.90 | 0.84 |
| Q4 (strong close) | 3,672 | 47.1% | 46.4% | $-13.38 | 0.80 |

### 2026 — distance from session extreme

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (near extreme) | 1,224 | 46.8% | 46.7% | $-11.49 | 0.85 |
| Q2 | 1,224 | 45.6% | 47.9% | $-12.62 | 0.83 |
| Q3 | 1,223 | 47.3% | 46.4% | $-10.78 | 0.85 |
| Q4 (far) | 1,224 | 47.7% | 49.2% | $-14.09 | 0.79 |

### 2026 — extension from regime start

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (low ext) | 1,224 | 48.7% | 44.9% | $-5.95 | 0.92 |
| Q2 | 1,224 | 47.2% | 48.2% | $-12.94 | 0.82 |
| Q3 | 1,223 | 46.0% | 47.8% | $-14.34 | 0.80 |
| Q4 (high ext) | 1,224 | 45.5% | 49.2% | $-15.76 | 0.78 |

### 2026 — impulse range (ATR)

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (small) | 1,224 | 45.6% | 47.2% | $-16.49 | 0.79 |
| Q2 | 1,224 | 46.0% | 47.8% | $-12.95 | 0.81 |
| Q3 | 1,223 | 48.8% | 45.1% | $-6.61 | 0.90 |
| Q4 (large) | 1,224 | 47.0% | 50.0% | $-12.92 | 0.83 |

### 2026 — impulse close location

| Bucket | n | PT% | SL% | Mean $ | PF |
|---|--:|--:|--:|--:|--:|
| Q1 (weak close) | 1,247 | 46.0% | 49.7% | $-16.65 | 0.77 |
| Q2 | 1,201 | 46.5% | 48.2% | $-13.92 | 0.82 |
| Q3 | 1,223 | 48.7% | 45.5% | $-5.46 | 0.92 |
| Q4 (strong close) | 1,224 | 46.3% | 46.6% | $-12.90 | 0.82 |

## 6. Cross-year stability (scan all trigger × race × window, threshold PF >= 1.10 + n >= 200)

**No spec passed in >=2 years.**

**No single-year hits either.** Strategy fails the success criteria entirely.

## 7. Unresolved policy stress (race 0.50/0.50, w=120s) — exit_at_close vs exclude

| Year | Trigger | Policy | n | PT% | SL% | Mean $ | PF |
|---|---|---|--:|--:|--:|--:|--:|
| 2024 | close_loc | exit_at_close | 16,974 | 46.6% | 48.3% | $-14.42 | 0.76 |
| 2024 | close_loc | exclude | 16,113 | 46.6% | 48.3% | $-14.57 | 0.76 |
| 2024 | no_new_30s | exit_at_close | 11,062 | 46.9% | 47.9% | $-14.15 | 0.77 |
| 2024 | no_new_30s | exclude | 10,488 | 46.9% | 47.9% | $-14.19 | 0.77 |
| 2024 | no_new_60s | exit_at_close | 8,245 | 47.1% | 47.5% | $-12.41 | 0.79 |
| 2024 | no_new_60s | exclude | 7,800 | 47.1% | 47.5% | $-12.53 | 0.80 |
| 2024 | wick_rejection | exit_at_close | 8,541 | 46.5% | 48.4% | $-14.90 | 0.76 |
| 2024 | wick_rejection | exclude | 8,106 | 46.5% | 48.4% | $-14.83 | 0.77 |
| 2025 | close_loc | exit_at_close | 14,801 | 47.4% | 47.0% | $-12.46 | 0.81 |
| 2025 | close_loc | exclude | 13,971 | 47.4% | 47.0% | $-12.41 | 0.82 |
| 2025 | no_new_30s | exit_at_close | 9,514 | 47.9% | 46.5% | $-11.39 | 0.83 |
| 2025 | no_new_30s | exclude | 8,983 | 47.9% | 46.5% | $-10.95 | 0.84 |
| 2025 | no_new_60s | exit_at_close | 7,100 | 47.1% | 47.7% | $-13.96 | 0.80 |
| 2025 | no_new_60s | exclude | 6,732 | 47.1% | 47.7% | $-14.42 | 0.80 |
| 2025 | wick_rejection | exit_at_close | 7,630 | 46.9% | 47.0% | $-13.59 | 0.80 |
| 2025 | wick_rejection | exclude | 7,164 | 46.9% | 47.0% | $-13.45 | 0.81 |
| 2026 | close_loc | exit_at_close | 4,895 | 46.8% | 47.5% | $-12.25 | 0.83 |
| 2026 | close_loc | exclude | 4,619 | 46.8% | 47.5% | $-12.47 | 0.83 |
| 2026 | no_new_30s | exit_at_close | 3,207 | 48.0% | 46.4% | $-8.03 | 0.89 |
| 2026 | no_new_30s | exclude | 3,028 | 48.0% | 46.4% | $-8.33 | 0.89 |
| 2026 | no_new_60s | exit_at_close | 2,376 | 50.0% | 45.4% | $-5.83 | 0.92 |
| 2026 | no_new_60s | exclude | 2,267 | 50.0% | 45.4% | $-4.96 | 0.93 |
| 2026 | wick_rejection | exit_at_close | 2,555 | 47.6% | 46.7% | $-10.93 | 0.85 |
| 2026 | wick_rejection | exclude | 2,408 | 47.6% | 46.7% | $-11.15 | 0.85 |

## Verdict

**Specs passing success criteria** (PF >= 1.10, n >= 200, positive mean, >=2 years): 0
**Single-year hits**: 0

The 'trade against failed expansion' hypothesis does NOT generate a reversal edge in this event family.

### Why the inversion failed

The lead was: trading WITH regime after "transition OUT of state 3" loses -$15 to -$21/trade (Fast Resolution Study). Hypothesis: invert direction → win.

Counter-result from this study (race 1.00 PT / 0.50 SL within 120s, all triggers):
- 2024: PT% 22%, SL% 55% — same as trading WITH regime
- 2025: PT% 22%, SL% 54% — same
- 2026: PT% 22-24%, SL% 52-54% — same

**The race rate doesn't flip with direction.** A 1.0-ATR favorable / 0.5-ATR adverse race resolves at ~42% favorable regardless of which side you take. This means the post-state-3 price action is genuinely directionless — neither continuation nor reversal beats coin-flip on the bracket geometry.

The Fast Resolution finding ("transition OUT of state 3 = -$15/trade") was NOT a directional signal. It was the **bracket-geometry tax** showing through: any 2:1 reward/risk bracket on a 42% race rate loses money. The same tax applies regardless of which side you take.

Confirming via the symmetric race (0.50/0.50 within 120s, all triggers):
- PT% lands at 46-48% across all triggers, all years, both directions
- True coin flip (effective ~50% race rate after cost)
- Mean $ uniformly negative (-$5 to -$15/trade) — losses dominated by commission + tick slip

### Direction split sanity check

Failed bullish → SHORT vs Failed bearish → LONG: PT% within 1pp of each other in every year. **No directional asymmetry to exploit.**

### Bucket findings

The closest-to-breakeven cell across ALL buckets:
- 2026 / no_new_60s / race 0.50/0.50: PF 0.92, mean -$5.83, n=2,376
- 2026 / extension Q1 (low ext) / close_loc / 0.50/0.50: PF 0.92, mean -$5.95, n=1,224
- 2026 / impulse close-loc Q3 / 0.50/0.50: PF 0.92, mean -$5.46, n=1,223

All are 2026-only and still negative. Not a basis for a strategy.

### Branch decision

**DEAD.** State-3 exit is a vol-state event but has no directional content for short-horizon prediction. The "transition OUT of state 3 = bad" finding from Fast Resolution was a bracket-geometry artifact, not a tradable directional signal.

Trading reversals against failed continuations on this event family does not work. Future work on volatility-exhaustion ideas should investigate:
- Multi-bar confirmation patterns (sustained reversal evidence, not just trigger fires)
- Different timescales (intraday breakout fades over 5-30 min, not 60-300s)
- Different signal sources (orderflow imbalance at extremes, news-driven impulses)
- Volatility-state from a different model (RV/realized variance bursts, not HMM state probability)

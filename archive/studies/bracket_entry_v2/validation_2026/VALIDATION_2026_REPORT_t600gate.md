# 2026 Unseen NT Validation — top_15 Live Strategy

**Test window**: 2026-01-01 through 2026-04-15 (Q1 + 2 weeks of April)

**Model**: top_15 retrained on 2020-2024 / val 2025. Never saw 2026 data.

**Execution**: LiveBracketStrategy (subclass of CollectorV2) — true runtime. Features computed live from the 1s bar stream; model scored at each 30s checkpoint; orders submitted into NT's engine.

## Scenario comparison

| Scenario | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A — Raw ($0 commission, no slippage) | 2,102 | $2.29 | $-50.00 | $2.98 | 46.0% | 1.02 | $4,815 |
| B — +$5 commission + 1-tick slippage | 2,102 | $-10.47 | $-65.00 | $-9.81 | 45.5% | 0.91 | $-22,005 |
| C — +$5 commission + 2-tick slippage | 2,102 | $-18.23 | $-75.00 | $-17.60 | 45.1% | 0.86 | $-38,315 |

## Exit reason mix

| Exit | n | 1-tick Mean $ | 2-tick Mean $ | Total 1-tick $ |
|---|--:|--:|--:|--:|
| pt | 942 | $244.93 | $239.93 | $230,720 |
| regime_exit | 456 | $-141.17 | $-151.17 | $-64,375 |
| sl | 704 | $-267.54 | $-277.54 | $-188,350 |

## Monthly — 1-tick slippage (primary)

| Month | n | Mean $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| 2025-12 | 26 | $-26.73 | $-24.58 | 38.5% | 0.61 | $-695.00 |
| 2026-01 | 553 | $-15.39 | $-14.42 | 45.2% | 0.85 | $-8,510 |
| 2026-02 | 618 | $-19.81 | $-17.37 | 44.2% | 0.84 | $-12,240 |
| 2026-03 | 682 | $11.52 | $12.11 | 48.8% | 1.09 | $7,855 |
| 2026-04 | 223 | $-37.74 | $-37.19 | 40.4% | 0.68 | $-8,415 |

## Direction split — 1-tick slippage

| Side | n | Mean $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| Short | 1,362 | $-4.23 | $-1.51 | 47.1% | 0.96 | $-5,755 |
| Long | 740 | $-21.96 | $-24.89 | 42.4% | 0.83 | $-16,250 |

## Comparison to 2024 and 2025 (top_15, 1-tick slippage, same cost model)

| Year | n | Mean $ | PF | Win% | Total $ | Notes |
|---|--:|--:|--:|--:|--:|---|
| 2024 | 2,719 | $20.79 | 1.21 | 56.5% | +$56,540 | Retrained thru 2022, val 2023 |
| 2025 | 2,697 | $35.50 | 1.26 | 57.1% | +$95,745 | Retrained thru 2023, val 2024 |
| **2026 YTD** | **2,102** | **$-10.47** | **0.91** | **45.5%** | **$-22,005** | Retrained thru 2024, val 2025 |

## Strategy diagnostics (live run)

- Confirmed events: 5,770
- Checkpoints scored (features present): 40,469
- Checkpoints skipped (missing features): 15,952 (28.3%)
- Scores above threshold (0.4719): 4,738 (11.7% of scored)
- Entries queued after single-position gate: 2,655
- Entries filled: 2,102
- PT hits: 942  SL hits: 702  Regime exits: 458

## Verdict

- 1-tick slippage: PF 0.91, total $-22,005
- 2-tick slippage: PF 0.86, total $-38,315
- Verdict: **WEAK — edge collapses on 2026. Model may need retraining or feature stability audit before deployment.**

## Diagnostic observations

- **Score drift**: the threshold pulled 11.7% of 2026 checkpoints over the bar, vs the 10% target by design. The 2026 score distribution has shifted right relative to val 2025 — the fixed threshold is no longer targeting the top decile on the new data. A rolling-percentile threshold (e.g. top 10% of last 20 trading days) would adapt to regime shifts.
- **Missing-feature rate**: 28.3% of checkpoints were skipped due to at least one missing top_15 feature. Investigate which feature is most often NaN on 2026 data.
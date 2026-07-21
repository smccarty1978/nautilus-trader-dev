# 2026 Unseen NT Validation — top_15 Live Strategy

**Test window**: 2026-01-01 through 2026-04-15 (Q1 + 2 weeks of April)

**Model**: top_15 retrained on 2020-2024 / val 2025. Never saw 2026 data.

**Execution**: LiveBracketStrategy (subclass of CollectorV2) — true runtime. Features computed live from the 1s bar stream; model scored at each 30s checkpoint; orders submitted into NT's engine.

## Scenario comparison

| Scenario | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A — Raw ($0 commission, no slippage) | 2,461 | $1.79 | $-45.00 | $1.97 | 46.3% | 1.02 | $4,415 |
| B — +$5 commission + 1-tick slippage | 2,461 | $-10.96 | $-60.00 | $-10.81 | 45.7% | 0.91 | $-26,980 |
| C — +$5 commission + 2-tick slippage | 2,461 | $-18.72 | $-70.00 | $-18.60 | 45.4% | 0.85 | $-46,070 |

## Exit reason mix

| Exit | n | 1-tick Mean $ | 2-tick Mean $ | Total 1-tick $ |
|---|--:|--:|--:|--:|
| pt | 1,104 | $243.50 | $238.50 | $268,825 |
| regime_exit | 540 | $-143.87 | $-153.87 | $-77,690 |
| sl | 817 | $-266.97 | $-276.97 | $-218,115 |

## Monthly — 1-tick slippage (primary)

| Month | n | Mean $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| 2025-12 | 28 | $-17.86 | $-15.19 | 42.9% | 0.72 | $-500.00 |
| 2026-01 | 646 | $-17.72 | $-16.17 | 45.4% | 0.83 | $-11,450 |
| 2026-02 | 737 | $-20.40 | $-19.41 | 44.2% | 0.84 | $-15,035 |
| 2026-03 | 785 | $8.03 | $7.60 | 48.2% | 1.06 | $6,305 |
| 2026-04 | 265 | $-23.77 | $-23.24 | 43.4% | 0.78 | $-6,300 |

## Direction split — 1-tick slippage

| Side | n | Mean $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| Short | 1,613 | $-6.35 | $-5.06 | 47.1% | 0.95 | $-10,245 |
| Long | 848 | $-19.73 | $-21.70 | 43.0% | 0.85 | $-16,735 |

## Comparison to 2024 and 2025 (top_15, 1-tick slippage, same cost model)

| Year | n | Mean $ | PF | Win% | Total $ | Notes |
|---|--:|--:|--:|--:|--:|---|
| 2024 | 2,719 | $20.79 | 1.21 | 56.5% | +$56,540 | Retrained thru 2022, val 2023 |
| 2025 | 2,697 | $35.50 | 1.26 | 57.1% | +$95,745 | Retrained thru 2023, val 2024 |
| **2026 YTD** | **2,461** | **$-10.96** | **0.91** | **45.7%** | **$-26,980** | Retrained thru 2024, val 2025 |

## Strategy diagnostics (live run)

- Confirmed events: 5,770
- Checkpoints scored (features present): 63,061
- Checkpoints skipped (missing features): 24,407 (27.9%)
- Scores above threshold (0.4719): 5,825 (9.2% of scored)
- Entries queued after single-position gate: 3,096
- Entries filled: 2,461
- PT hits: 1,104  SL hits: 815  Regime exits: 542

## Verdict

- 1-tick slippage: PF 0.91, total $-26,980
- 2-tick slippage: PF 0.85, total $-46,070
- Verdict: **WEAK — edge collapses on 2026. Model may need retraining or feature stability audit before deployment.**

## Diagnostic observations

- **Score drift**: the threshold pulled 9.2% of 2026 checkpoints over the bar, vs the 10% target by design. The 2026 score distribution has shifted right relative to val 2025 — the fixed threshold is no longer targeting the top decile on the new data. A rolling-percentile threshold (e.g. top 10% of last 20 trading days) would adapt to regime shifts.
- **Missing-feature rate**: 27.9% of checkpoints were skipped due to at least one missing top_15 feature. Investigate which feature is most often NaN on 2026 data.
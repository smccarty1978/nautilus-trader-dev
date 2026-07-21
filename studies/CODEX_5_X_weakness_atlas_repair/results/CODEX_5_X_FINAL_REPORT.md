# CODEX 5.X Repaired Weakness Atlas and Established-Regime Fade

## Decision

`NO_MONETIZABLE_WEAKNESS_FADE`

The bearish sign defect is repaired, the directional W4 model is causal and
stable out of sample, and long participation is restored. The frozen trading
policy is not robustly profitable: 2025 lost $5.42 net per trade and the
untouched 2026 test made only $6.68 net per trade with a 1.036 profit factor.
Across the two policy periods, gross PnL was +$33,816.78 (+$7.72/trade), but
after the frozen $10 round-trip cost it lost $10,013.22, or $2.28 per completed
trade. This does not advance to NT execution validation.

All policy figures below are **1-second OHLC research simulation** results under
`EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT`; they are not NT-native executable
validation and do not claim exact intrabar sequencing.

## Excursion and ATR contract

- Price reference: the first raw Databento 1-second open at or after the causal
  regime-flip decision (`entry_open`, `entry_ts_event`).
- `current_pnl`, `current_mfe`, and `current_mae` are divided by
  `atr_at_entry`.
- `atr_at_checkpoint` is the ATR on the strictly prior causal feature bar at
  the checkpoint. The legacy `atr` export is an explicit alias of
  `atr_at_checkpoint`.
- `current_mfe == running_mfe` and `current_mae == running_mae`: both are the
  non-negative running extrema observed over `[entry_ts_event,
  observation_time)`. This is intended.
- The policy stop is a separate execution quantity: exactly
  `1.5 * atr_at_checkpoint` from the explicit entry fill open, active on the
  entry bar.

## Repair evidence

The old bearish branch multiplied by direction twice. In 2025, 98.12% of
bearish `current_mfe` rows and 96.43% of bearish `current_mae` rows were
negative. Their medians were -1.5535 and -0.6379 ATR. After repair, the bearish
medians are +1.5634 and +0.6294 ATR, with zero negative rows and zero running
monotonicity violations. Bullish and bearish repaired medians are now comparable.

The final rebuilt atlas contains:

| Year | Checkpoints |
|---:|---:|
| 2021 | 638,930 |
| 2022 | 638,648 |
| 2023 | 638,387 |
| 2024 | 635,277 |
| 2025 | 3,934,266 |
| 2026 through Apr 29 | 1,289,840 |

The full repair gate found zero negative excursions, zero alias violations,
zero ATR-reference violations, and zero within-regime monotonicity violations.
The isolated suite finishes with 43 passing tests.

## Chronological W4

- Train: 2021-2024 only.
- Structure selection: 2025 H1 only.
- Calibration and frozen direction thresholds: 2025 H2 only, with the one
  boundary-spanning regime purged from both halves.
- Final test: 2026 only; no model, threshold, filter, stop, or exit changes.

| 2025 H1 structure | Long AUC | Short AUC | Macro directional AUC | Direction gap |
|---|---:|---:|---:|---:|
| Pooled | 0.773225 | 0.770553 | 0.771889 | 0.002672 |
| Pooled + interactions | 0.772957 | 0.770454 | 0.771706 | 0.002503 |
| Directional pair | 0.772405 | 0.770096 | 0.771250 | 0.002309 |

All candidates were within 0.005 macro AUC, so the predeclared balance rule
selected the directional pair. Frozen thresholds are 0.688350 for prevailing
long regimes and 0.718365 for prevailing short regimes.

| W4 gate | Prevailing long | Prevailing short |
|---|---:|---:|
| 2025 H2 strict-cross regime rate | 87.70% | 84.62% |
| 2026 strict-cross regime rate | 90.57% | 86.45% |
| 2026 ROC-AUC | 0.772371 | 0.768587 |
| 2026 finite score rate | 100% | 100% |

## Frozen monetization policy

The prior symmetric established filter was reused unchanged: age >= 120s,
running MFE >= 1.0 entry ATR, at least two causal progress windows, and retained
MFE ratio >= 0.50. Entry occurs only on the first strict direction-specific W4
threshold crossing while that filter is true. A bullish prevailing regime is
faded short and a bearish prevailing regime is faded long.

Entry is the first available raw 1-second open at or after the decision
boundary. The 1.5 checkpoint-ATR stop is active immediately, including on the
entry bar; gaps through the stop fill at the bar open, otherwise at the stop.
The trade holds through the first aligning flip and exits at the first available
1-second open after the next flip against the trade. Costs are $10 round trip.

| Period | Trades | Longs | Shorts | Mean gross | Total gross | Mean net | Total net | Win rate | Net PF | Stop rate | Median hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 development | 3,246 | 1,390 | 1,856 | +$4.58 | +$14,851.01 | -$5.42 | -$17,608.99 | 30.84% | 0.967 | 42.67% | 491.5s |
| 2026 final through Apr 29 | 1,137 | 481 | 656 | +$16.68 | +$18,965.77 | +$6.68 | +$7,595.77 | 31.57% | 1.036 | 40.99% | 535.0s |

The repaired pipeline no longer produces an effectively short-only study.
Long entries are 42.82% of 2025 trades and 42.30% of 2026 trades.

### Exit reasons

| Period | Opposite flip against trade | Stop before aligned flip | Stop after aligned flip |
|---|---:|---:|---:|
| 2025 development | 1,861 | 1,107 | 278 |
| 2026 final through Apr 29 | 671 | 369 | 97 |

All 4,383 trades have a resolved exit; there are no false or data-end-censored
policy trades in either result set.

### Direction and session sensitivity

| Period / slice | Trades | Mean net/trade | Total net | PF |
|---|---:|---:|---:|---:|
| 2025 short | 1,856 | +$1.82 | +$3,386.28 | 1.012 |
| 2025 long | 1,390 | -$15.10 | -$20,995.27 | 0.916 |
| 2025 ETH | 2,170 | -$9.12 | -$19,785.88 | 0.924 |
| 2025 RTH | 1,076 | +$2.02 | +$2,176.89 | 1.008 |
| 2026 short | 656 | +$23.13 | +$15,171.99 | 1.136 |
| 2026 long | 481 | -$15.75 | -$7,576.23 | 0.923 |
| 2026 ETH | 767 | +$2.69 | +$2,060.17 | 1.018 |
| 2026 RTH | 370 | +$14.96 | +$5,535.59 | 1.057 |

The only persistent directional pattern is that long fades remain negative in
both periods. That is now an economic result rather than a participation/sign
artifact. The modest final-test gain is concentrated in short fades and is too
small to override the negative 2025 validation result.

## Audit chain

- Atlas pre-execution, completion, pre-2026 freeze, and post-2026/pre-policy
  audits: PASS with zero critical findings and zero warnings.
- Policy pre-execution audit: PASS with zero critical findings and zero
  warnings after all identified contract gaps were repaired.
- Exact frozen hashes cover both years' raw data, repaired atlas, score stream,
  manifest, bundle, first-open ledger, runner, policy, and audit authorization.
- Both policy reconciliations have zero closure residual and zero blocking
  errors.

The conclusion is intentionally conservative: repaired W4 is a valid research
signal, but this single frozen fade policy is not monetizable as tested.

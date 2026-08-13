# Full Trade Path Dual-Model Builder — Build Report

## Build status

Phase A through Phase D are complete. Phase E deterministic validation passes.
The canonical artifacts contain 5,836 selected trades and 6,589,582 completed
one-second path rows across the frozen 2021–2025 population.

The threshold reference population overlaps calendar year 2025 of the study
population. Results are descriptive and must not be represented as
threshold-out-of-sample for 2025.

## Frozen models and thresholds

| Entry regime | Model | Frozen Top-2.5% threshold | Cadence | Causal status |
|---|---|---:|---:|---|
| Bullish Fade / short entry | `BULLISH_STRICT_top25_gbt_v2` | 0.5697449423968936 | 5 seconds | corrected, refrozen, parity PASS |
| Bearish Fade / long entry | `LONG_STRICT_top25_gbt_v2` | 0.5641320087327389 | 5 seconds | frozen, parity PASS |

The executed inclusive membership operator is `>=`. Bullish Top-10/Top-5
warning thresholds are 0.43167249785595935 and 0.5067081427626979. Bearish
Top-5 is 0.5084619230529974; Bearish Top-10 is unavailable and remains null
with an explicit reason.

Both independent ordered-vector/null-mask/hash parity checks pass. Both model
probability maximum absolute differences are 0.0 at the canonical cadence.

Exact frozen hashes:

| Artifact | SHA-256 |
|---|---|
| Bullish model | `ac833f5f4c983b791f3632660d762dfd6fd47ecc20e78822797628c11e7817f8` |
| Bullish frozen adapter | `1dc25a262e5fc685a6d2216938838e445b030f526455fb56cb64c7b9bee49e16` |
| Bearish model | `1d696d85f2e31026db8415fb15913267d447bd7fde9be0fcefed490c7bf4af26` |
| Dual runtime adapter | `be45d83723cf5e482cc529e59c6ea944f06246ab6ff67605c182cf461efa2ba3` |

## Score and selection population

- Canonical model-score rows: 5,665,103 in 60 monthly partitions.
- Explicit missing-dispatch grid rows: 2,880,577.
- Accepted confirmed flips: 137,961.
- First in-domain Top-2.5% selections: 5,836.
- Long entries: 2,507; short entries: 3,329.
- Selections by year: 1,147 (2021), 1,206 (2022), 1,187 (2023),
  1,149 (2024), and 1,147 (2025).
- Exact independent first-signal parity: PASS, with no extra trades, missing
  trades, duplicate regimes, or key/score/threshold mismatches.

Score availability and in-domain state remain explicit on every emitted score
row and every path row. Missing dispatches remain in the separate canonical
missing-grid artifact rather than being silently imputed.

All 5,665,103 emitted score rows are RTH rows. Exact monthly rows broken down
by session, bullish/bearish confirmed regime, both-model availability, and
model-specific in-domain status are included in the normative report annex,
`results/build_report_inventory.json`.

| Confirmed regime | Rows | Both models available | Bullish in-domain | Bearish in-domain | Bullish exploratory available | Bearish exploratory available |
|---|---:|---:|---:|---:|---:|---:|
| Bearish (-1) | 2,699,458 | 2,468,814 | 0 | 987,360 | 2,468,814 | 1,571,386 |
| Bullish (+1) | 2,965,645 | 2,721,711 | 1,218,463 | 0 | 1,597,877 | 2,729,882 |

“Exploratory available” means the score is computable but outside that
model’s frozen in-domain regime; it is retained for inspection and never used
as an eligible entry for that direction.

## Full paths and completion

- Completed paths with fallback exit marks: 5,617.
- Right-censored paths at the sealed boundary: 219.
- Maximum simultaneous open paths: 4.
- One-second path rows: 6,589,582.
- Ambiguous same-bar ordering rows: 9,841.
- Canonical population partitions: 120.
- Canonical path partitions: 5,307.
- Compressed canonical path size: approximately 0.380 GiB.
- Compressed canonical population size: approximately 5.861 MiB.

The exact row count, trade count, compressed byte size, and SHA-256 for every
one of the 5,307 canonical path partitions are included in
`results/build_report_inventory.json`. This machine-readable partition table
is the normative per-partition size annex to this report.

## Validation results

- Every-trade summary-versus-path parity: PASS for 5,836/5,836 trades.
- Summary/path mismatches: 0.
- Raw one-second catalog parity: PASS for 360/360 deterministic samples,
  with samples in every monthly partition.
- Raw OHLC mismatches: 0.
- Phase B global population integrity: PASS.
- Phase C exact selection parity: PASS.
- Runtime feature/vector/score parity: PASS for both models.

The deterministic raw-bar sample includes first and last path rows, long and
short trades, confirmation and fallback boundaries, and overlapping paths
where present. Selected trade IDs and timestamps are persisted in
`results/phase_d_validation.json`.

## Baseline completed-path economics

All values below are descriptive fallback-exit marks, not simulated fills or
realized PnL, and exclude the 219 censored paths.

| Metric (ATR) | Mean | p25 | p50 | p75 | Maximum |
|---|---:|---:|---:|---:|---:|
| Fallback-exit return | -0.0668 | -1.2613 | -0.4695 | 0.8859 | 21.6209 |
| Full-path MFE | 2.4793 | 0.8224 | 1.6826 | 3.2046 | 32.6953 |
| Full-path MAE | 1.7122 | 0.6188 | 1.1619 | 2.0356 | 33.8325 |
| Giveback from MFE | 2.5461 | 1.7902 | 2.2007 | 2.8198 | 28.3666 |

The median MFE-capture ratio is -0.2762 among the 5,583 completed paths where
the ratio is defined. Negative ratios are possible because the fallback mark
can be adverse while earlier MFE is positive.

## Opposite-model warning coverage

| Warning level | Trades warned | Completed warning lead-time median | Censored among warned |
|---|---:|---:|---:|
| Top-10 | 2,384 | 330 seconds | 64 (2.68%) |
| Top-5 | 5,560 | 280 seconds | 140 (2.52%) |
| Top-2.5% | 5,304 | 170 seconds | 134 (2.53%) |

Bearish Top-10 is not frozen, so Top-10 remains unavailable for the applicable
opposite-model direction. “Censored among warned” is reported as an observable
warning-without-observed-fallback rate, not as a causal false-positive label.
No threshold optimization was performed.

The frozen operational false-warning definition is: a warning is false when no
accepted fallback flip is observed within 600 seconds after the warning.
Censored observations with less than 600 seconds of follow-up are excluded.

| Warning level | Eligible with 600s outcome | Fallback within 600s | False warnings | False-warning rate |
|---|---:|---:|---:|---:|
| Top-10 | 2,354 | 1,578 | 776 | 32.97% |
| Top-5 | 5,477 | 3,845 | 1,632 | 29.80% |
| Top-2.5% | 5,215 | 3,991 | 1,224 | 23.47% |

This is an operational descriptive label fixed for reporting; it is not a
claim that the warning caused or predicted the accepted flip.

## Artifact locations

- `canonical_trade_population/`
- `canonical_trade_paths/`
- `canonical_phase_d_manifest.json`
- `results/phase_d_validation.json`
- `results/build_report_inventory.json`
- `_work/phase_d_monthly/global_path_manifest.json`
- `audit/phase_d_preexec.md`
- `audit/phase_d_supervisor_preexec.md`

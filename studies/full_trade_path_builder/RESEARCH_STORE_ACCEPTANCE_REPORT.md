# Canonical Research Store Acceptance Report

## Scope

This bounded study validated the three consolidated canonical Parquet
artifacts using the existing lazy loader. It did not modify Parquet files,
schemas, collectors, features, models, thresholds, selection rules, or
NautilusTrader outputs.

## Phase 1 — Analyst-facing load test

Elapsed time includes lazy-plan construction and collection of a pushed-down
row count. Times are local measurements from this acceptance run.

| Operation | Filter | Rows | Elapsed seconds |
|---|---|---:|---:|
| Full observations | none | 5,665,103 | 0.012569 |
| Full trade summaries | none | 5,836 | 0.001531 |
| Full trade paths | none | 6,589,582 | 0.003251 |
| One year | summaries, 2025 | 1,147 | 0.004995 |
| One model | `BULLISH_STRICT_top25_gbt_v2` | 3,329 | 0.002232 |
| One direction | LONG | 2,507 | 0.001855 |
| Bounded date range | summaries, 2025-01-01 through 2025-02-01 | 100 | 0.001804 |

All operations used `scan_canonical_research_population` and returned a Polars
`LazyFrame` before collection.

## Phase 2 — Dataset-level integrity

| Dataset | Rows | Unique semantic observations/trades | Date range, America/Chicago |
|---|---:|---:|---|
| Observations | 5,665,103 | 5,665,103 semantic observation keys | 2021-01-04 08:30:00 to 2025-12-30 14:59:55 |
| Trade summaries | 5,836 | 5,836 trades | 2021-01-04 11:18:45 to 2025-12-30 14:08:35 |
| Trade paths | 6,589,582 | 5,836 trades | 2021-01-04 11:18:46 to 2025-12-30 14:29:00 |

The observation artifact has no `observation_id` column. Its exact immutable
semantic key is `(instrument_id, checkpoint_decision_ns)`.

| Model | Direction | Trades | Complete | Censored |
|---|---|---:|---:|---:|
| `BULLISH_STRICT_top25_gbt_v2` | SHORT | 3,329 | 3,227 | 102 |
| `LONG_STRICT_top25_gbt_v2` | LONG | 2,507 | 2,390 | 117 |

Integrity checks:

- Duplicate semantic observation keys: 0.
- Duplicate trade-summary keys: 0.
- Trades missing a final path row: 0.
- Trades with other than exactly one final path row: 0.
- Complete trades: 5,617.
- Censored trades: 219.

## Phase 3 — Summary-to-path reconciliation

The sample contains 100 completed trades selected deterministically from sorted
trade IDs with seed `20260726`.

Tolerance:

- Absolute: `1e-12`.
- Relative: `1e-12`.

Field mapping:

| Metric | Path reconstruction | Summary field |
|---|---|---|
| Path row count | count rows by `trade_id` | `path_row_count` |
| Trade duration | `(max(timestamp_close_ns) - checkpoint_decision_ns) / 1e9` | `seconds_entry_to_fallback_exit` |
| MFE | `max(running_mfe_atr)` | `full_trade_mfe_atr` |
| MAE | `-min(running_mae_atr)` | positive `full_trade_mae_atr` |
| Final path return | `close_pnl_atr` where `is_final_path_bar` | `fallback_exit_mark_return_atr` |

Path `running_mae_atr` is signed/nonpositive. Summary MAE is its positive
magnitude.

| Metric | Maximum absolute error | Mean absolute error | Failures |
|---|---:|---:|---:|
| Path row count | 0 | 0 | 0 |
| Trade duration, seconds | 4.54747e-13 | 4.23483e-14 | 0 |
| MFE, ATR | 0 | 0 | 0 |
| MAE, ATR | 0 | 0 | 0 |
| Final path return, ATR | 0 | 0 | 0 |

Unexplained failures: 0. There are no failure trade IDs.

## Phase 4 — Observation-to-trade linkage

The exact join key was:

```text
instrument_id
checkpoint_decision_ns
```

No fuzzy timestamp matching was used.

Shared-field mapping:

| Summary field | Observation field |
|---|---|
| `checkpoint_decision_ns` | `checkpoint_decision_ns` |
| `regime_start_ns` | `regime_start_ns` |
| `entry_regime_direction` | `confirmed_regime_direction` |
| SHORT `entry_model_id` | `bullish_model_id` |
| LONG `entry_model_id` | `bearish_model_id` |
| SHORT `entry_raw_score` | `bullish_raw_score` |
| LONG `entry_raw_score` | `bearish_raw_score` |

Results:

- Missing entry observations: 0.
- Checkpoint-key mismatches: 0.
- Regime-start mismatches: 0.
- Regime-direction mismatches: 0.
- Model-ID mismatches: 0.
- Model-score mismatches: 0.

## Phase 5 — Minimal research demonstration

Confirmation MAE, MFE, and return were reconstructed from completed one-second
path rows through the exact `confirm_flip_ns` boundary because these metrics
are not stored directly in the summary artifact.

| Model | Direction | Trades | Complete | Censored | Median regime age, seconds | Confirm ≤300s | Median MAE to confirm, ATR | Median MFE to confirm, ATR | Median return at confirm, ATR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `BULLISH_STRICT_top25_gbt_v2` | SHORT | 3,329 | 3,227 | 102 | 1,445 | 64.94% | 0.56665 | 0.59770 | 0.33668 |
| `LONG_STRICT_top25_gbt_v2` | LONG | 2,507 | 2,390 | 117 | 1,445 | 64.70% | 0.55611 | 0.60377 | 0.36235 |

This table is descriptive only. No hypothesis tests, threshold optimization,
model comparison, or strategy recommendation were performed.

## Final verdict

READY FOR RESEARCH

Limitations:

- No `observation_id` column exists; exact semantic observation keys are used.
- Confirmation MAE, MFE, and return are reconstructed from path rows rather
  than stored directly in trade summaries.

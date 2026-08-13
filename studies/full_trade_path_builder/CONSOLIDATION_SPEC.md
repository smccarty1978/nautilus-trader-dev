# Canonical Research Parquet Consolidation Specification

## Objective

Materialize one analysis-ready Parquet file for each accepted canonical row
grain without changing source values, identifiers, timestamps, model semantics,
or outcomes.

## Accepted source roots

- Checkpoint observations:
  `_work/phase_b_monthly/year=*/month=*/canonical_model_scores.parquet`
- Trade summaries:
  `canonical_trade_population/entry_year=*/entry_month=*/trade_direction=*/part-00000.parquet`
- One-second paths:
  `canonical_trade_paths/entry_year=*/entry_month=*/trade_direction=*/trade_id_prefix=*/part-00000.parquet`

Only complete artifacts whose bytes match their adjacent accepted manifests may
be included. Temporary, smoke, provisional, superseded, or schema-incompatible
files are excluded.

## Outputs

- `consolidated/canonical_observations_all.parquet`
- `consolidated/canonical_trade_summaries_all.parquet`
- `consolidated/canonical_trade_paths_all.parquet`
- `consolidated/RECONCILIATION_REPORT.json`
- `consolidated/SOURCE_INVENTORY.json`

Annual convenience files are not created because they would duplicate the
2.6+ GiB primary artifacts without adding filtering capability.

## Metadata normalization

All outputs add `source_year`, `source_month`, and `source_file`.

Trade summaries retain their accepted `entry_model_id` and explicit
`trade_direction`. The consolidated summary exposes `model_id` as an exact
alias of `entry_model_id`.

Path `model_id` is joined by immutable `trade_id` from the accepted summary
population. Its `trade_direction` must exactly equal the summary mapping.

Checkpoint observations remain one dual-model row per checkpoint. They retain
the explicit `bullish_model_id`, `bearish_model_id`, and
`confirmed_regime_direction`; they are not duplicated into artificial
single-model rows.

## Deterministic ordering

- Observations: `instrument_id`, `checkpoint_decision_ns`
- Summaries: `instrument_id`, `checkpoint_decision_ns`, `model_id`,
  `trade_direction`, `trade_id`
- Paths: `trade_id`, `timestamp_close_ns`

## Acceptance

- All source schemas match exactly within a row grain.
- Every source artifact is manifest/hash verified before and after writing.
- Combined row counts equal accepted source totals globally and by partition.
- No conflicting semantic-key duplicates exist.
- Null counts and selected numeric fingerprints reconcile exactly.
- No source bytes change.
- Loader filters are lazy and operate without month-by-month caller logic.


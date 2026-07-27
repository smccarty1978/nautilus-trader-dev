# Canonical Research Parquet Consolidation Report

## Result

The accepted monthly research outputs were consolidated into three independent,
analysis-ready row grains. No source file was modified, moved, renamed, or
deleted.

| Artifact | Rows | Compressed bytes | SHA-256 |
|---|---:|---:|---|
| Checkpoint observations | 5,665,103 | 1,950,162,290 | `7901507854e5667dd9129a7e6cdb9108dfc11025fbe39050c48f28ecd5c0b251` |
| Trade summaries | 5,836 | 2,016,639 | `45c5d22b6470d1579413dffef471cc1bfedbb37429f46e38aa6df4a61d5f1ef3` |
| One-second trade paths | 6,589,582 | 223,980,477 | `4ee1ba6a6005f31dbac1cde7c4192704a3292519299571c85d94e76533f37f59` |

## Source inventory

- Observation sources: 60 monthly files.
- Trade-summary sources: 120 monthly/direction files.
- Trade-path sources: 5,307 monthly/direction/trade-prefix files.
- Intended study period: January 2021 through December 2025.
- Missing months: none.
- Missing sides/models: none.
- Empty accepted files: none.
- Excluded files: none.

The exact accepted source inventory, grouped by year, month, direction/model,
normalized schema hash, and collector/version hash, is recorded in
`consolidated/SOURCE_INVENTORY.json`.

## Annual reconciliation

### Dual-model checkpoint observations

| Year | Rows |
|---|---:|
| 2021 | 1,118,800 |
| 2022 | 1,157,023 |
| 2023 | 1,140,093 |
| 2024 | 1,135,364 |
| 2025 | 1,113,823 |

### Trade summaries

| Year | Model | Direction | Rows |
|---|---|---|---:|
| 2021 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 674 |
| 2021 | `LONG_STRICT_top25_gbt_v2` | LONG | 473 |
| 2022 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 657 |
| 2022 | `LONG_STRICT_top25_gbt_v2` | LONG | 549 |
| 2023 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 673 |
| 2023 | `LONG_STRICT_top25_gbt_v2` | LONG | 514 |
| 2024 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 661 |
| 2024 | `LONG_STRICT_top25_gbt_v2` | LONG | 488 |
| 2025 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 664 |
| 2025 | `LONG_STRICT_top25_gbt_v2` | LONG | 483 |

### One-second trade paths

| Year | Model | Direction | Rows |
|---|---|---|---:|
| 2021 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 682,605 |
| 2021 | `LONG_STRICT_top25_gbt_v2` | LONG | 506,049 |
| 2022 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 722,376 |
| 2022 | `LONG_STRICT_top25_gbt_v2` | LONG | 639,639 |
| 2023 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 714,264 |
| 2023 | `LONG_STRICT_top25_gbt_v2` | LONG | 600,901 |
| 2024 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 763,643 |
| 2024 | `LONG_STRICT_top25_gbt_v2` | LONG | 587,175 |
| 2025 | `BULLISH_STRICT_top25_gbt_v2` | SHORT | 781,449 |
| 2025 | `LONG_STRICT_top25_gbt_v2` | LONG | 591,481 |

Exact monthly year/month/model/direction counts and timestamp coverage are in
`consolidated/RECONCILIATION_REPORT.json`.

## Validation

- Combined rows equal accepted source rows for all three grains.
- Exact year/month/model/direction reconciliation passes.
- All-column null counts reconcile with no introduced nulls.
- Immutable semantic-key hash sums reconcile.
- Selected numeric min/max and stable aggregate fingerprints reconcile.
- Exact duplicates: 0.
- Conflicting duplicates: 0.
- Source files changed: 0.
- Completed trade summaries: 5,617.
- Right-censored trade summaries: 219.
- Unique path trades: 5,836.
- Trades with a final path row: 5,836.
- Trades missing a final path row: 0.
- Real lazy-loader 2025 filters pass for all three grains.

Physical Arrow `null` fields in all-null partitions were normalized only where
all concrete partitions agreed on one type. Conflicting concrete types,
column order, nullability, or metadata remained fatal.

## Deterministic ordering

- Observations: `instrument_id`, `checkpoint_decision_ns`.
- Summaries: `instrument_id`, `checkpoint_decision_ns`, `model_id`,
  `trade_direction`, `trade_id`.
- Paths: `trade_id`, `timestamp_close_ns`.

## Annual convenience files

Annual duplicate files were not created. The lazy loader applies year/date,
model, and direction filters to the primary artifacts without loading the full
population.


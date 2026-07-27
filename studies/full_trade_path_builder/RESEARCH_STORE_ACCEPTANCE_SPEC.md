# Canonical Research Store Acceptance Specification

## Scope

Validate the three immutable consolidated Parquet artifacts for analyst-facing
loading, dataset integrity, deterministic summary/path reconciliation, exact
observation/trade linkage, and one minimal descriptive grouped table.

No Parquet, collector, feature, model, schema, threshold, selection, or
NautilusTrader change is permitted.

## Inputs

- `consolidated/canonical_observations_all.parquet`
- `consolidated/canonical_trade_summaries_all.parquet`
- `consolidated/canonical_trade_paths_all.parquet`
- `implementation/canonical_research_loader.py`

## Frozen validation contract

- Fixed sample seed: `20260726`.
- Completed-trade sample size: `100`.
- Floating comparison tolerance: absolute `1e-12`, relative `1e-12`.
- Observation semantic key: `instrument_id`, `checkpoint_decision_ns`.
- Summary key: `trade_id`.
- Path key: `trade_id`, `timestamp_close_ns`.
- No fuzzy timestamp matching.
- Path MAE is signed/nonpositive; summary MAE is its positive magnitude.
- Path extrema timestamps use completed one-second bar close timestamps.

## Deliverables

- `analysis/validate_canonical_research_store.py`
- `RESEARCH_STORE_ACCEPTANCE_REPORT.md`
- `results/research_store_acceptance.json`

The final report ends with exactly one verdict: `READY FOR RESEARCH`,
`READY WITH LIMITATIONS`, or `NOT READY`.


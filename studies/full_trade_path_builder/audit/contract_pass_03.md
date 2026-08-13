# Canonical Research Parquet Consolidation — Contract Gate Pass 3

**Date:** 2026-07-26  
**Reviewer:** Main-session contract fallback, explicitly authorized by user  
**Verdict:** **PASS**

## Prior findings

Passes 1 and 2 had no critical or warning findings.

## Amendment reviewed

The first observation artifact write preserved row counts, null counts, keys,
and extrema, but a strict floating-point sum comparison failed after
deterministic sorting changed addition order.

The amendment:

- keeps row count, every-column null count, immutable-key hash sum, numeric
  minimum/maximum, group coverage, and source hashes exact;
- compares only selected floating aggregate sums with documented
  `rel_tol=1e-12` and `abs_tol=1e-9`;
- persists both source and combined fingerprints and the tolerance contract;
- stops and reports field-level differences outside that contract;
- adds a bounded order-stability test.

This does not relax identifier, null, timestamp, schema, coverage, or source
preservation checks.

## Status

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**


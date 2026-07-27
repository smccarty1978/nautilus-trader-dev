# Canonical Research Parquet Consolidation — Contract Gate Pass 2

**Date:** 2026-07-26  
**Reviewer:** Main-session contract fallback, explicitly authorized by user  
**Scope:** C4, D, E, and deliverables after physical-null normalization  
**Verdict:** **PASS**

## Prior findings

Pass 1 had no critical or warning findings.

## Amendment reviewed

The first full-source preflight found four censoring fields physically encoded
as Arrow `null` in an all-null monthly/direction partition while other accepted
partitions encode the same fields as `int64`, `string`, and `double`.

The amendment:

- preserves exact column names and ordering;
- requires identical schema and field metadata;
- requires identical nullability;
- permits physical `null` only when all concrete partitions agree on exactly
  one target type;
- rejects any conflicting concrete types;
- supplies the agreed schema to the lazy scan;
- forbids integer, float, datetime, and categorical casts;
- adds a bounded test proving allowed null-only normalization and rejection of
  concrete `int64`/`string` disagreement.

This is an expected physical representation normalization, not a semantic
union or value coercion. Fingerprint and all-column null-count reconciliation
remain mandatory.

## Status

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**


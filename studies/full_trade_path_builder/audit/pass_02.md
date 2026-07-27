# Causal Audit — Canonical Research Parquet Consolidation

**Date:** 2026-07-26  
**Pass:** 02  
**Auditor:** lookahead-auditor  
**Scope hash:** `e8c06a2c7e802f73359f8099c1a6a403bb6cece8714b9dd0f883f414cad75dc6`

## Scope

- `CONSOLIDATION_SPEC.md`
- `config/consolidation.yaml`
- `implementation/consolidate_research_parquets.py`
- `implementation/canonical_research_loader.py`
- `tests/test_research_parquet_consolidation.py`
- Accepted upstream canonical row semantics

Per `docs/CAUSAL_CHECKLIST.md` SCOPE SPLIT, this pass covers only A, B,
C1–C3, F, G, and H. Deliverables, manifests, seal design, and test quality are
outside this audit.

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**

## Prior-finding adjudication

Pass 01 contained no findings. Its clean causal verdict remains valid.

## Findings

None.

## Amendment review

- Physical Arrow `null` types are normalized only when every concrete source
  type for that column agrees.
- Conflicting concrete types, column order, nullability, field metadata, and
  schema metadata fail closed.
- The normalized schema changes only the physical representation of columns
  whose partition values are entirely null; it cannot introduce a value,
  timestamp, label, or outcome.
- Source scanning uses the frozen normalized schema while forbidding integer,
  float, datetime, categorical, and decimal coercions.
- The only explicit casts are derived partition metadata
  (`source_year`/`source_month`), not canonical market timestamps or outcomes.

## Clean causal checks

- Consolidation remains value-preserving post-NT analysis.
- No signal, feature, label, model, session, or execution decision is computed.
- No temporal shift, rolling operation, fill, as-of join, resampling, or
  normalization statistic exists.
- The immutable `trade_id` join does not use future or outcome-dependent
  matching.
- Loader bounds remain explicit UTC, left-closed, and right-open.
- Missing values remain missing and are not imputed.
- No bracket, stop, target, re-entry, or fill simulation exists.

## Checklist matrix

| Section | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Canonical timestamps preserved; explicit UTC loader bounds |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | N/A | No label construction or data split |
| F1–F4 | PASS/N/A | No session gates; no fixed-offset conversion |
| G1 | N/A | No contract or roll transformation |
| G2 | PASS | Null values preserved without filling |
| G3–G4 | N/A | No resampling or indicator computation |
| H1–H4 | N/A | No bracket or execution simulation |

## Referred to contract-checker

None.

---

*Read-only causal audit complete. The schema-normalization amendment preserves
the clean causal verdict.*

# Causal Audit — Canonical Research Parquet Consolidation

**Date:** 2026-07-26  
**Pass:** 04  
**Auditor:** lookahead-auditor  
**Scope hash:** `7527807ade28a9f3676d51696dd15a379797f7f120fdb89e6e83c24a43e12f48`

## Scope

- `CONSOLIDATION_SPEC.md`
- `config/consolidation.yaml`
- `implementation/consolidate_research_parquets.py`
- `implementation/canonical_research_loader.py`
- `tests/test_research_parquet_consolidation.py`
- Accepted upstream canonical row semantics

Per `docs/CAUSAL_CHECKLIST.md` SCOPE SPLIT, this pass covers only A, B,
C1–C3, F, G, and H.

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**

## Prior-finding adjudication

Passes 01, 02, and 03 contained no findings. Their clean causal verdicts remain
valid.

## Findings

None.

## Amendment review

- Partition metadata extraction now accepts the unprefixed `year=YYYY` and
  `month=MM` segments used by accepted observation paths, in addition to the
  existing `study_` and `entry_` prefixes.
- The correction changes only provenance metadata assignment. It does not
  modify event timestamps, row values, features, labels, trade paths, session
  classification, or execution timing.
- The added regression case verifies that an accepted
  `year=2025/month=07` path yields `source_year=2025` and `source_month=7`.

## Clean causal checks

- Consolidation remains post-NT analysis with no signal, feature, label, model,
  session, or execution decision.
- No rolling, temporal shift, fill, as-of join, resampling, normalization, or
  outcome-dependent matching exists.
- Loader bounds remain explicit UTC, left-closed, and right-open.
- Null values remain unfilled.
- No stop, target, re-entry, bracket, or fill simulation exists.

## Checklist matrix

| Section | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Canonical timestamps preserved; partition metadata correction does not alter timestamps |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | N/A | No label construction or data split |
| F1–F4 | PASS/N/A | No session gate or fixed-offset conversion |
| G1 | N/A | No contract or roll transformation |
| G2 | PASS | Missing values preserved without filling |
| G3–G4 | N/A | No resampling or indicators |
| H1–H4 | N/A | No execution simulation |

## Referred to contract-checker

None.

---

*Read-only causal audit complete. The partition-metadata regex correction
preserves the clean causal verdict.*

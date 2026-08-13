# Causal Audit — Canonical Research Parquet Consolidation

**Date:** 2026-07-26  
**Pass:** 03  
**Auditor:** lookahead-auditor  
**Scope hash:** `6a245ade3441f3a60ccd54b6bd33dfb18d80eec13bcf812439a5b47c18886184`

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

Passes 01 and 02 contained no findings. Both clean causal verdicts remain valid.

## Findings

None.

## Amendment review

- The tolerance applies only to aggregate floating-point `__sum` reconciliation
  after value-preserving consolidation.
- Row counts, all-column null counts, immutable-key hash sums, numeric minima
  and maxima, duplicate keys, coverage, and grouped reconciliation remain exact.
- The comparison does not modify source or output values.
- `rel_tol=1e-12` and `abs_tol=1e-9` accommodate summation-order roundoff only;
  they do not affect timestamps, keys, labels, path values, or selection logic.
- Both source and output fingerprints are retained for inspection.

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
| A1–A5 | PASS/N/A | Canonical timestamps preserved; explicit UTC loader bounds |
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

*Read-only causal audit complete. The fingerprint-comparison amendment preserves
the clean causal verdict.*

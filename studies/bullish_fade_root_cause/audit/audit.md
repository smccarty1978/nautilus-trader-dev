# Pre-Execution Look-Ahead & Causal Audit

**Date:** 2026-07-22  
**Scope:** `studies/bullish_fade_root_cause/{SPEC.md,config.yaml,implementation/run_study.py}` plus direct provenance  
**Verdict:** **BLOCKED — 4 CRITICAL, 3 WARNING**

## Critical findings

1. **Classification support:** classification B was hard-coded without scoring the historical legacy event. Required: compute legacy-event ROC-AUC, AP, Brier, calibration and lift, and make classification conditional.
2. **Population parity:** corrected/legacy inner join could silently discard unmatched keys. Required: exact bidirectional key equality.
3. **Prediction parity:** Bullish frozen-reference inner join could pass on incomplete overlap. Required: exact coverage checks.
4. **Artifact parity:** Bearish comparator lacked frozen prediction reproduction. Required: validate frozen fixture or narrow the claim.

## Warnings

1. Correct the open-labelled one-second endpoint wording and terminal-bar availability semantics.
2. Validate raw one-second timestamps as strictly increasing and unique before binary searches.
3. Enforce `confirm_flip_ns > observation_time` for the Bullish label.

## Clean checks

No 2026 input, legacy-event reconstruction matches the historical implementation, Bullish pure-target arithmetic matches its producer, descriptive path metrics do not simulate fills, and the strict Bearish source enforces causal timestamps.

---

This report is the complete substantive content returned by the repository-provided pre-execution look-ahead auditor. Remediation and re-audit follow below.

## Final pre-execution re-audit

**Verdict: PASS — 0 CRITICAL, 0 WARNING**

The auditor verified: the Classification A published-AUC stop gate; the frozen
and configured Classification C ROC-AUC threshold; sequential A-E precedence;
conditional conclusions and actions; exact Bearish attachment coverage;
legacy-event ROC/PR outputs; exact Bullish population/reference coverage;
bit-exact prediction parity; positive flip horizons; no 2026 access; correct
open-labelled endpoint semantics; strict raw timestamp ordering; descriptive
non-fill economic paths; exact historical legacy-event reconstruction; and
explicit disclosure of the inherited Bullish one-second feature look-ahead.

The study is cleared to execute within its frozen scope.

## Completion audit

The first completion pass was rejected with one CRITICAL population-parity
finding and three WARNING findings: the analysis had not replayed the combined
2024–2025 first-qualifying-per-regime population, prediction confusion matrices
were missing, SHAP distributions were summarized only by means, and feature
saturation used sample extrema. All four findings were remediated and the study
was rerun through the bounded runner.

### Final completion re-audit

**Verdict: ACCEPTED — 0 CRITICAL, 0 WARNING**

The auditor verified the exact combined 2024–2025 percentile/first-signal
replay, Classification B gates, bit-exact model parity, target/event semantics,
prediction confusion matrices, per-row and quantile SHAP distributions,
model-bin saturation, timing/economic semantics, all seven deliverables, and
the successful bounded-run status. At top 2.5%, identical selected signals have
59.87% original-target positives versus 7.01% legacy-event positives (published
7.2%). The inherited Bullish one-second feature look-ahead remains a disclosed
secondary production-validity defect, not the cause of the historical
reliability disconnect.

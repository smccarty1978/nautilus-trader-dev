# Contract Audit — Pass 07

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — FIXED.** All six labels remain reachable through the artifact workflow (`implementation/contracts.py:26-39`; `tests/test_terminal_workflow.py:44-57`).
- **C-02 — FIXED.** Seal payload and artifact bytes are recomputed (`implementation/contracts.py:42-61`); direct inspection verified all 18 hashes and the materialized verifier reports PASS (`results/promotion_gate.json:5-10`).
- **C-03 — FIXED.** Global validation uses every 2021–2024 RTH score key (`implementation/validate.py:73-94`).
- **C-04 — FIXED.** The corrected collection root has all 48 materialized partitions (`results/validation_report.json:3-54`).
- **C-05 — FIXED.** Retained-row readiness remains enforced (`implementation/run_collect.py:45-54,80-90`; `tests/test_warmup_retention.py:8-19`).
- **C-06 — FIXED.** Promotion checks seal, report, validation, phase 0, lint, both audits, and non-abort terminal (`implementation/promote.py:31-59`; `tests/test_promotion.py:14-22`).
- **C-07 — FIXED.** Current summary correctly emits ABORT while the prior contract audit is blocked (`results/summary.json:2-51`).
- **Pass-06 manifest materialization blocker — NOT FIXED.** Phase 0 still omits the frozen strict-age/MFE/progress/retention/ATR-anchor/cadence reconciliation (`results/phase0_contract.json:18-23`).
- **Pass-06 terminal-summary blocker — FIXED.** Summary and report now agree on ABORT (`results/summary.json:2`; `REPORT.md:3-5,91-105`).
- **Pass-06 domain/global-validation blocker — FIXED.** Validation is PASS with 48 partitions and zero missing, duplicate, off-grid, or surplus mappings (`results/validation_report.json:489-496`).
- **Pass-06 C4 materialization blocker — FIXED.** Selection seal and promotion gate exist; all sealed and model-artifact hashes verified (`results/selection_seal.json:3-25`; `results/promotion_gate.json:2-17`).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | Required files and schemas exist, but phase 0 is incomplete (`phase0_contract.json:18-23`) and row metrics contain only 16 directional rows, with no required pooled direction-labelled summary (`oos_row_metrics.csv:1-17`; validator explicitly expects 16 at `validate.py:99-103`). | Supplied suite: 20 passed; no literal phase-0/source or pooled-summary test. | Record every frozen eligibility reconciliation and emit/validate pooled AUC rows for A/B × four buckets. |
| Terminal labels | **PASS** | Real classifier reaches S1–S5/ABORT (`contracts.py:26-39`); current ABORT is consistent with the blocked contract gate (`summary.json:2-51`; `promotion_gate.json:2-17`). | `test_terminal_workflow.py:44-65`. | Re-finalize only after blockers clear. |
| Domain/completeness §7 | **PASS** | UTC 48-month grid, half-open bounds, zero-row rule, hashes, and all-score-key global join are enforced (`validate.py:25-32,73-96,113-115`); materialized counts are clean (`validation_report.json:489-570`). | `test_validate_contract.py:6-18`; supplied suite passed. | None. |
| C4 walk-forward / seal / promotion | **FAIL** | Year split and TRAIN-only thresholds/deciles are explicit (`run_study.py:100-119`), and seal verification passes. However promotion trusts only phase-0's self-declared status (`promote.py:20-21,49-58`), so the wrong frozen source identities below can pass that gate. | Seal tamper and blocker tests pass (`test_contracts.py:16-33`; `test_promotion.py:14-22`), but source identity/content is untested. | Make phase 0 compare exact source names/hashes and eligibility facts before returning PASS; make promotion consume that authenticated result. |
| D1–D4 determinism/hash binding | **PASS / NOT APPLICABLE** | No serve/ONNX path. Fit and inference share ordered feature arrays; seed is fixed (`run_study.py:100-119`). All four declared model hashes match their bytes (`models_manifest.json:49-50,123-124,173-174,247-248`). | Supplied suite passed; no serving contract exists. | Re-audit if serving is introduced. |
| E1–E5 backtest/fill/warmup | **PASS / NOT APPLICABLE** | No executable order path; four-day collector warmup and retained readiness remain enforced (`run_collect.py:27,45-54,67-90`). | `test_warmup_retention.py:8-19`. | None. |

## New blocking findings

- **C-08 — CRITICAL: Baseline A is not the frozen direction-specific Top-25.** SPEC freezes `BULLISH_STRICT_top25_gbt_v2` and `LONG_STRICT_top25_gbt_v2` (`SPEC.md:34-42`), but the run imports one `F3_top25_gbt_v1` list and uses it for both directions (`run_study.py:23,41,68-70,100-119`). Phase 0 falsely names that generic source for both sides (`phase0_contract.json:24-32`). Thus all fitted models, thresholds, scores, and conclusions authenticate the wrong experiment. Smallest remediation: bind each side to its frozen named feature list/hash, fail phase 0 on mismatch, and rerun fitting/evaluation/finalization.
- **C-09 — CRITICAL: Required pooled row-level AUC is absent.** SPEC §5 requires a pooled direction-labelled summary for each A/B model set and bucket, but `oos_row_metrics.csv:1-17` has only 16 direction-specific rows and `validate.py:99-103` treats 16 as complete. Smallest remediation: emit the eight pooled rows from concatenated directional OOS scores and validate the full 24-cell contract.

## Assumptions not structurally enforced

Phase 0 assumes `F3_top25_gbt_v1` is the accepted matching-direction source; neither phase 0 nor promotion verifies the frozen names, hashes, or eligibility facts.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED

Collection/domain validation, hashes, seal verification, terminal reachability, and warmup now pass. Acceptance remains blocked because the materialized models and conclusions use the wrong Baseline-A feature source, phase 0/promotion do not detect that mismatch, required phase-0 eligibility evidence remains incomplete, and the frozen pooled AUC summaries are missing.

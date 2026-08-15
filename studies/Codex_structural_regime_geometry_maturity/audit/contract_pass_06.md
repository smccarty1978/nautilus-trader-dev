# Contract Audit — Pass 06

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — FIXED.** All six labels remain reachable through the real artifact classifier (`implementation/contracts.py:26-39`; `tests/test_terminal_workflow.py:44-57`).
- **C-02 — FIXED.** Seal payload and sealed bytes are recomputed (`implementation/contracts.py:42-61`) and both tamper paths are tested (`tests/test_contracts.py:16-33`).
- **C-03 — FIXED.** Global validation uses all score keys for snapshot matching (`implementation/validate.py:73-94`).
- **C-04 — FIXED.** The corrected collection root remains centralized at `implementation/paths.py:4-8`; 48 partitions are now materialized there.
- **C-05 — FIXED.** Retained-row readiness remains enforced (`implementation/run_collect.py:45-54,80-90`; `tests/test_warmup_retention.py:8-19`).
- **C-06 — FIXED.** Promotion code gates every frozen input (`implementation/promote.py:31-59`; `tests/test_promotion.py:4-22`).
- **C-07 — NOT FIXED.** The implementation aborts on failed validation/audits (`implementation/finalize_artifacts.py:57-62`), but materialized `results/summary.json:1-8` still reports S3/PASS while `results/validation_report.json:1-2` is FAIL.
- **Prior manifest materialization blocker — NOT FIXED.** Tables/models now exist, but required manifest contents and finalized summary/report remain incomplete.
- **Prior terminal-summary blocker — NOT FIXED.** Materialized summary is stale and contradicts the mandatory validation gate.
- **Prior domain/global-validation blocker — NOT FIXED.** The 48-month grid exists, but the required global validation status remains FAIL.
- **Prior C4 materialization blocker — NOT FIXED.** Four model hashes match their artifact bytes, but no materialized selection seal or promotion gate was supplied.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | All listed paths exist, but literal contents fail: `phase0_contract.json:18-23` omits the frozen MFE/progress/retention/ATR-anchor/cadence eligibility facts; `collection_manifest.json:1-7` omits partition coverage, attrition, and source/code hashes; `validation_report.json:1-2` is FAIL; `summary.json:1-8` lacks primary comparisons and attrition; `REPORT.md:3-11,91-102` has no S1–S5 interpretation or limitations section. Model artifact hashes at `models_manifest.json:49-50,123-124,173-174,247-248` match all four files. | Supplied: 20 study tests passed. No literal full-manifest test; direct materialized inspection fails. | Rerun the existing finalizer after correcting validation, expand phase-0 eligibility facts, and regenerate REPORT.
| Terminal labels | **FAIL** | Production reachability is complete (`contracts.py:26-39`), but `summary.json:2-7` emits S3/PASS despite mandatory validation FAIL; the production workflow requires ABORT (`finalize_artifacts.py:57-62`). | Every label and abort input is exercised (`test_terminal_workflow.py:44-65`). | Regenerate summary from current gate inputs; it must emit ABORT until all blockers clear.
| Domain/completeness §7 | **FAIL** | Expected grid/bounds/zero-row/hash checks are implemented (`validate.py:25-32,83-96,113-115`) and the report records 48 partitions with zero missing/duplicate/off-grid score joins (`validation_report.json:489-496`). However status is FAIL because `snapshots_without_canonical_regime=5,218,735`; `validate.py:114` adds a zero-extra-snapshot condition not stated in §7. | Snapshot-key tests cover missing/unavailable and duplicates (`test_validate_contract.py:6-18`), not the materialized extra-snapshot population. | Align the global gate with §7 (or scope snapshots to observed score dispatches), rerun validation, and require PASS.
| C4 walk-forward / seals / promotion | **NOT VERIFIED** | TRAIN/OOS split, TRAIN-only thresholds/deciles, deterministic order and artifact hashes are explicit (`run_study.py:100-121`); promotion gates all frozen checks (`promote.py:31-59`). No `selection_seal.json` or `promotion_gate.json` is materialized, so selected-result authentication/acceptance cannot be verified. This is a C4 finding, not an invented manifest item. | Tamper and per-blocker promotion tests pass (`test_contracts.py:16-33`; `test_promotion.py:14-22`). | After resolving blocking deliverables, materialize and verify the seal and promotion gate.
| D1–D4 train/serve and hash binding | **PASS / NOT APPLICABLE** | No serve/ONNX path exists. Fit and inference use the same ordered arrays and drop-null population (`run_study.py:100-119`); seed is fixed; all four declared model hashes match bytes. | Covered by supplied suite; no serving contract exists. | Re-audit if serving is introduced.
| E1–E4 backtest/fills | **PASS / NOT APPLICABLE** | This study has no executable order path; external LAST bars feed collection only (`implementation/collector.py:16-19,39-40`). | Supplied collector/boundary tests passed. | None.
| E5 warmup | **PASS** | Four-day warmup and first-retained-row readiness are enforced (`implementation/run_collect.py:27,45-54,67-90`). | `test_warmup_retention.py:8-19`. | None.

## New blocking findings

None. All blockers are continuations of Pass 05 findings.

## Assumptions not structurally enforced

The report assumes validation passed (`REPORT.md:11`), but the authoritative materialized validation status says FAIL. No supplied evidence authenticates the current result set with a completed selection seal.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED

The corrected data/model run exists and its model hashes bind correctly, but the frozen deliverables contract is not complete: global validation is FAIL, summary/report contradict that gate and omit required content, phase-0 and collection manifests are incomplete, and C4 seal/promotion acceptance is not materialized. Deployment or study acceptance is not approved.

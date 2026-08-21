# Contract Audit — Pass 05

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — FIXED.** Every frozen label is reached through materialized-style workflow fixtures at `tests/test_terminal_workflow.py:44-57` and the production classifier at `implementation/contracts.py:26-39`.
- **C-02 — FIXED.** Seal payload integrity and artifact bytes are recomputed at `implementation/contracts.py:42-61`; both artifact and seal-payload tampering are tested at `tests/test_contracts.py:16-33`.
- **C-03 — FIXED.** The validator now passes all observed RTH score keys to the composite snapshot check at `implementation/validate.py:75-82,93-94`; accepted eligibility is used only for monthly zero-row adjudication at `:82,88,92`.
- **C-04 — FIXED.** The single corrected root remains frozen at `implementation/paths.py:4-8`, imported by collection consumers, and alternate-root rejection is tested at `tests/test_collection_lineage.py:9-17`.
- **C-05 — FIXED.** First-retained-row readiness is enforced before write at `implementation/run_collect.py:45-54,80-90` and tested at `tests/test_warmup_retention.py:14-19`.
- **C-06 — FIXED.** Promotion gates phase 0, zero-warning lint, both audits, validation, seal verification, report hash, and non-abort terminal state at `implementation/promote.py:20-37,47-59`; blocker tests are at `tests/test_promotion.py:4-22`.
- **C-07 — FIXED.** Terminal abort now consumes phase-0 and lint state at `implementation/finalize_artifacts.py:57-62`; both failure paths are tested at `tests/test_terminal_workflow.py:60-65`.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | The manifest is explicit at `SPEC.md:164-182`. The corrected root at `implementation/paths.py:4-8` has zero partitions. Materialized `results/oos_first_crossings.parquet` has 15 columns and no structural features or Walk-A confirmation/MAE/return/MFE fields; `results/models_manifest.json:1-247` has no model artifact paths/hashes; all four model binaries are absent; `results/validation_report.json:294-307` and `results/summary.json:1-8` are pre-remediation shapes. | Supplied suite: 19 passed; no literal full-manifest/materialized-lineage test. Direct existence/schema inspection fails. | Run the corrected 48-month collection and downstream finalizer, then validate every listed artifact literally. |
| Terminal labels | **FAIL** | Production abort now includes validation, both audits, phase 0, and lint at `finalize_artifacts.py:57-62`, but materialized `results/summary.json:1-8` still declares S3 while contract status is blocked. | All labels and phase-0/lint abort paths are covered at `test_terminal_workflow.py:44-65`. | Regenerate summary after clean completion inputs exist. |
| Domain/completeness §7 | **FAIL** | The 48 UTC intervals, exact boundaries, conditional zero-row rule, and all-score composite join are implemented at `validate.py:25-32,73-94,111-113`. The corrected root is empty, and materialized `validation_report.json:294-307` lacks composite duplicate, zero-row, boundary, denominator, and required-artifact gates. | Supplied 19-test pass; snapshot-unit coverage at `test_validate_contract.py:6-18` does not materialize the 48-month grid. | Materialize the corrected grid and rerun validation globally. |
| C4 walk-forward / seal / promotion | **NOT VERIFIED** | TRAIN/OOS separation, TRAIN-only thresholds/deciles, deterministic models, and model hashes are implemented at `run_study.py:100-121`; seal verification and all frozen promotion inputs are at `contracts.py:42-61` and `promote.py:31-59`. No `results/selection_seal.json`, `results/promotion_gate.json`, or model artifact exists. | Tampering and promotion blocker tests pass at `test_contracts.py:16-33` and `test_promotion.py:4-22`. | Regenerate models, then materialize and verify the seal and promotion gate. |
| D1–D4 train/serve | **PASS / NOT APPLICABLE** | No serving/ONNX path exists. Fit and inference share the same ordered lists, null policy, and model objects at `run_study.py:100-121`; seed is fixed at `:106`. | Included in supplied 19-test suite; no serving contract exists. | Re-audit if serving is introduced. |
| E1–E4 backtest/fills | **PASS / NOT APPLICABLE** | Strategy subscriptions match loaded external LAST 1s/1m bars at `collector.py:16-19,39-40` and `run_collect.py:67-79`; no orders are submitted. | Collector/boundary tests are included in the supplied suite. | None. |
| E5 warmup | **PASS** | Four-day load and pre-write readiness enforcement are at `run_collect.py:27,45-54,67-90`. | `test_warmup_retention.py:8-19`. | None. |

## New blocking findings

None.

## Assumptions not structurally enforced

The materialized results are assumed to represent corrected code, but their declared corrected collection root is empty and their schemas/hashes predate the current workflow. Supplied evidence is therefore insufficient to bind those results to the audited implementation.

## Blocking verdict

BLOCKED

The Pass 04 implementation defects C-03 and C-07 are fixed, but deployment remains blocked: the corrected pipeline has not materialized its required deliverables, global validation, terminal summary, model artifacts, selection seal, or promotion gate. Unit tests establish local behavior but cannot authenticate the stale result set.

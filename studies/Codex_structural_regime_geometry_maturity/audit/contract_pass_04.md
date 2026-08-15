# Contract Audit — Pass 04

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — FIXED.** `tests/test_terminal_workflow.py:42-55` now drives `terminal_summary()` through all S1–S5 and abort using materialized-style fixtures.
- **C-02 — FIXED.** Seal-payload and artifact hashes are recomputed at `implementation/contracts.py:42-61`; tampering coverage remains at `tests/test_contracts.py:16-33`.
- **C-03 — NOT FIXED.** Composite duplicate/missing checks were added at `implementation/validate.py:51-70`, but the function is passed only the accepted subset at `validate.py:78,90` while the collector emits every 5s snapshot at `collector.py:67-75`; unmatched non-accepted snapshots are then counted as failures. SPEC §7 instead requires exact coverage of observed RTH score-row keys and uses accepted eligibility only for zero-row adjudication (`SPEC.md:195-203`).
- **C-04 — FIXED.** The alternate output-root option is removed and producer/consumers import one constant at `run_collection_grid.py:10-13,25-29,36-39`; rejection/default-lineage tests are at `tests/test_collection_lineage.py:9-17`.
- **C-05 — FIXED.** Collection now asserts first-retained structural readiness before writing at `run_collect.py:45-54,80-90`; both pass/fail paths are tested at `tests/test_warmup_retention.py:14-19`.
- **C-06 — FIXED.** Promotion explicitly gates phase 0 and zero-warning lint at `implementation/promote.py:20-37,47-59`, with independent blocker tests at `tests/test_promotion.py:4-22`.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | Manifest is explicit at `SPEC.md:164-182`. Materialized `results/oos_first_crossings.parquet` has only 15 columns and omits every structural feature plus Walk-A confirmation/MAE/return/MFE fields; `results/collection_manifest.json:1-70`, `models_manifest.json:1-247`, `validation_report.json:1-308`, and `summary.json:1-8` are pre-remediation shapes. The corrected root declared at `implementation/paths.py:4-8` has zero partitions. | Direct existence/schema inspection; supplied study suite passed 18 tests but has no literal full-manifest test. | After fixing C-03/C-07, run the corrected 48-month pipeline and finalizer, then validate every manifest artifact literally. |
| Terminal labels | **FAIL** | All labels are reachable through `finalize_artifacts.py:26-50`, but abort depends only on validation and two audits (`:46-49`), omitting failed phase 0 and lint although `SPEC.md:184-193` requires abort for any contract or lint blocker. | `test_terminal_workflow.py:42-55` covers validation abort only. | Pass phase-0 and lint state into `terminal_summary()` and add one failing fixture for each. |
| Domain/completeness §7 | **FAIL** | Forty-eight UTC intervals and boundary/zero-row checks exist at `validate.py:25-32,79-88`; the accepted-surface/all-snapshot mismatch remains at `:43-48,78,89-90`. The materialized validator is also stale: `results/validation_report.json:294-307` lacks the new composite, zero-row, boundary, denominator, and required-artifact gates. | `test_validate_contract.py:6-18` tests only snapshots already present in the accepted subset; no non-accepted snapshot case. | Validate all observed RTH score keys against snapshots; use the direction-eligible surface only for zero-row checks; regenerate the report. |
| C4 walk-forward / selection seal / promotion | **NOT VERIFIED** | Temporal fit/OOS split and TRAIN-only thresholds/deciles are explicit at `run_study.py:100-119`; seal verification and all frozen promotion inputs are implemented at `contracts.py:42-61` and `promote.py:31-59`. No materialized `results/selection_seal.json` or `promotion_gate.json` exists, and current `models_manifest.json:242-246` lacks the artifact hashes now emitted by `run_study.py:108-119`. | Tamper and blocker unit tests pass (`test_contracts.py:16-33`; `test_promotion.py:4-22`). | Regenerate models/manifest, then run promotion to materialize and verify the seal/gate. |
| D1–D4 train/serve | **PASS / NOT APPLICABLE** | No serve/ONNX path exists. Fit and inference use the same ordered feature lists at `run_study.py:100-119`; deterministic seed is fixed at `:106`. | Supplied 18-test pass; no serving contract exists. | Re-audit if serving is introduced. |
| E1–E4 | **PASS / NOT APPLICABLE** | Subscriptions match configured 1s/1m external LAST bars at `collector.py:16-19,39-40`; runner loads those streams at `run_collect.py:67-79`. No executable orders exist. | Collector/boundary tests are included in the supplied 18-test pass. | None. |
| E5 warmup | **PASS** | Four days are loaded and readiness is enforced before retention/write at `run_collect.py:27,45-54,67-90`. | `test_warmup_retention.py:8-19`. | None. |

## New blocking findings

### C-07 — Terminal abort omits frozen phase-0 and lint failures

`terminal_summary()` can emit S1–S5 while phase 0 or lint is failed because neither input participates in `abort` (`finalize_artifacts.py:46-50`). Promotion later blocking that result does not make the declared terminal label correct.

## Assumptions not structurally enforced

The current materialized results are assumed to represent the corrected lineage, but the declared corrected collection root is empty and their JSON schemas/hashes predate the remediation.

## Blocking verdict

BLOCKED

The corrected run must not be accepted or promoted: C-03 remains unresolved, terminal abort is incomplete, the literal manifest is stale/incomplete, and the selection seal/promotion gate have not been materialized. Supplied test evidence is insufficient for those completion requirements.

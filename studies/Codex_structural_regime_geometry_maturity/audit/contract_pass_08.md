# Contract Audit — Pass 08

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability; pre-execution diff

## Prior finding adjudication

- **C-01 — FIXED.** All six labels remain reachable through the artifact workflow (`implementation/contracts.py:26-39`; `tests/test_terminal_workflow.py:44-57`).
- **C-02 — FIXED.** Seal payload and sealed artifact bytes are recomputed (`implementation/contracts.py:42-61`; `tests/test_contracts.py:16-33`).
- **C-03 — FIXED.** Global validation uses every 2021–2024 RTH score key (`implementation/validate.py:73-96`).
- **C-04 — FIXED.** The validator requires the exact 48-month UTC partition set and half-open bounds (`implementation/validate.py:25-32,73-94,114-116`).
- **C-05 — FIXED.** Retained-row readiness remains enforced (`implementation/run_collect.py:45-54,80-90`; `tests/test_warmup_retention.py:8-19`).
- **C-06 — FIXED.** Promotion checks seal, report, validation, phase 0, lint, both audits, and non-abort terminal (`implementation/promote.py:31-60`; `tests/test_promotion.py:14-22`).
- **C-07 — FIXED.** Terminal ABORT consumes failed validation, phase 0, lint, or audit state (`implementation/finalize_artifacts.py:57-62`; `tests/test_terminal_workflow.py:44-65`).
- **C-08 — FIXED (code; rerun pending).** SHORT and LONG now load their frozen named sources independently, preserve direction-specific order, and bind source/list hashes into each model manifest entry (`run_study.py:23-29,74-77,107-127,168-174`). Existing materialized artifacts predate this correction.
- **C-09 — FIXED (code; rerun pending).** The runner emits eight pooled direction-labelled rows in addition to 16 directional rows, and the validator now expects 24 (`run_study.py:188-194`; `implementation/validate.py:99-103`). Existing `results/oos_row_metrics.csv` still has 16 rows because execution is correctly awaiting this gate.
- **Prior phase-0 completeness/authentication blocker — NOT FIXED.** All frozen facts are now written, but none is reconciled against source facts before the function unconditionally returns `status: PASS` (`run_study.py:162-165`); promotion still trusts that field alone (`implementation/promote.py:20-21,49-58`).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **NOT VERIFIED** | All listed paths presently exist, but phase 0 and row metrics are stale pre-remediation materializations (`results/phase0_contract.json:18-32`; `results/oos_row_metrics.csv:1-17`). Corrected generators are at `run_study.py:162-174,188-203`. | Supplied suite: 20 passed; no phase-0 provenance or exact AUC-grid test. | Fix blockers below, pass the gate, rerun, then verify every materialized schema/content literally. |
| Terminal labels | **FAIL** | Pooled AUC rows newly emitted by `run_study.py:188-192` flow unfiltered into comparison/evidence (`implementation/finalize_artifacts.py:39-47`), and `classification_cells >= 2` determines S1 (`implementation/contracts.py:26-34`). | Reachability test uses directional rows only (`tests/test_terminal_workflow.py:15-57`); no pooled-row isolation test. | Exclude `POOLED_DIRECTION_LABELLED` from terminal evidence and test it cannot change a label. |
| Domain/completeness §7 | **FAIL** | Row count and unique-cell count are checked, but exact allowed model/direction/bucket identities are not (`implementation/validate.py:35-40,99-115`). An alien cell replacing a required cell can still yield 24 unique positive cells and PASS. Partition/join enforcement is otherwise direct (`implementation/validate.py:73-96,114-116`). | Join tests cover missing/duplicate snapshots only (`tests/test_validate_contract.py:6-18`). | Compare observed cells to the exact 24-cell set (16 directional + 8 pooled); test substitutions, duplicates, missing cells, and bounds. |
| C4 walk-forward / seal / promotion | **FAIL** | Fit years and TRAIN-only thresholds/deciles are explicit (`run_study.py:107-127`). Phase 0 nevertheless self-certifies without checking source eligibility/provenance (`run_study.py:162-165`), and promotion accepts only its status (`implementation/promote.py:20-21`). | Seal/promotion blocker tests pass, but phase-0 test only supplies `{status: PASS}` (`tests/test_promotion.py:4-11`). | Derive and compare each frozen fact/source identity/hash, return FAIL on mismatch, and test every mismatch through promotion. |
| D1–D4 determinism/hash binding | **PASS / NOT APPLICABLE** | No serve/ONNX path. Directional feature order is shared by fit/inference, seed is fixed, and model entries bind artifact and source/list hashes (`run_study.py:107-127,168-174`). | Supplied suite passed; no serving contract exists. | Re-audit if serving is introduced. |
| E1–E5 backtest/fill/warmup | **PASS / NOT APPLICABLE** | No executable order path; four-day collector warmup and readiness are enforced (`implementation/run_collect.py:27,45-54,67-90`). | `tests/test_warmup_retention.py:8-19`; supplied suite passed. | None. |

## New blocking findings

- **C-10 — CRITICAL: pooled summaries alter terminal selection.** A pooled improvement can supply one of the two `classification_cells`, allowing S1/S2/S3 from evidence not belonging to either frozen direction-specific model. Filter terminal comparisons to SHORT/LONG and add a regression test.
- **C-11 — CRITICAL: the required AUC grid is count-valid, not identity-valid.** Twenty-four distinct positive rows with a missing required cell and an unexpected label pass validation and therefore promotion. Enforce equality with the frozen 24-cell Cartesian set.

## Assumptions not structurally enforced

Phase 0 assumes the source artifacts embody every echoed eligibility fact; exact AUC cell identities are assumed because the current generator emits them.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED

Pre-execution remains blocked: phase 0 still self-certifies rather than authenticating the frozen source and eligibility facts, the validator does not enforce the exact required 24-cell AUC grid, and pooled summary rows can change the terminal decision. Corrected source binding and pooled-row generation are code-fixed but must not be materialized until these contract blockers clear.

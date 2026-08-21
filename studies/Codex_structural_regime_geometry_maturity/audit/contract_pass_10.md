# Contract Audit — Pass 10

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal labels; train-only baseline amendment

## Prior finding adjudication

- **C-01 — FIXED.** All six labels remain reachable (`implementation/contracts.py:12-39`; `tests/test_terminal_workflow.py:44-57`).
- **C-02 — FIXED.** Artifact and seal-payload tampering remain detected (`implementation/contracts.py:42-61`; `tests/test_contracts.py:16-33`).
- **C-03 — FIXED.** Global validation consumes all 2021–2024 RTH score keys (`implementation/validate.py:79-98`).
- **C-04 — FIXED.** Exact 48-month UTC partitions and half-open bounds remain enforced (`implementation/validate.py:29-36,77-98,119-120`).
- **C-05 — FIXED.** Four-day warmup and retained-row readiness remain enforced (`implementation/run_collect.py:35-54,67-90`).
- **C-06 — FIXED.** Promotion still gates seal/report/validation/phase-0/lint/both audits/non-abort terminal (`implementation/promote.py:31-60`).
- **C-07 — FIXED.** Failed validation, phase 0, lint, or audit reaches ABORT (`implementation/finalize_artifacts.py:57-62`; `tests/test_terminal_workflow.py:60-65`).
- **C-08 — FIXED (code; execution pending).** Replacement SHORT/LONG lists load independently and retain direction-specific order (`run_study.py:23-33,78-81,111-131`).
- **C-09 — FIXED (code; execution pending).** The generator emits the frozen 24 directional/pooled AUC cells (`run_study.py:202-208`; `implementation/validate.py:21-22,115-120`).
- **C-10 — FIXED.** Terminal evidence excludes pooled rows (`implementation/finalize_artifacts.py:37-47`).
- **C-11 — FIXED.** Validation requires equality with the exact frozen AUC-cell set (`implementation/validate.py:21-22,115-120`).
- **Pass 09 phase-0 completeness/authentication blocker — NOT FIXED.** The freezer records source hashes and strict facts (`freeze_train_only_baselines.py:58-66`), but `source_contract()` neither recomputes/compares the canonical source hashes nor compares strict age, MFE, progress, retention, and ATR-anchor facts; only cadence is checked (`run_study.py:176-187`). Its ordered-list digest uses default JSON separators at `:182`, unlike the compact serialization frozen at `freeze_train_only_baselines.py:23-24`, so an authentic list cannot verify. Most importantly, `main()` fits at `run_study.py:193-216` before phase 0 is evaluated/written at `:217`; no failed authentication refuses fit.
- **Pass 09 deliverables verdict — NOT VERIFIED.** Current artifacts and seal predate the replacement lineage; replacement freezer artifacts do not yet exist.
- **Pass 09 terminal-label verdict — NOT VERIFIED.** Directional filtering is implemented, but no pooled-row isolation regression exists (`tests/test_terminal_workflow.py:44-65`).
- **Pass 09 domain verdict — NOT VERIFIED.** Exact grid equality is implemented, but the test checks only the expected-set helper, not validator rejection of an alien substitution (`tests/test_validate_contract.py:21-26`).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **NOT VERIFIED** | The manifest is explicit (`SPEC.md:172-190`), but `artifacts/frozen_train_only_baselines/` is absent and current results/selection seal authenticate the superseded lineage. | Supplied lint 0/0 and 21 tests passed; no replacement-lineage materialization test. | Fix pre-fit authentication, rerun the gate, then regenerate and literally validate every listed artifact. |
| Terminal labels | **NOT VERIFIED** | All labels are reachable and pooled AUC is excluded (`finalize_artifacts.py:37-62`). | Reachability passes; no pooled-row isolation regression. | Add the focused regression before completion. |
| Domain/completeness §7 | **NOT VERIFIED** | Exact partitions, joins, zero-row behavior, and 24-cell identity are enforced (`validate.py:29-36,55-74,77-120`). | Helper-grid test only (`test_validate_contract.py:21-26`). | Test an alien-cell substitution through the validation decision. |
| C4 walk-forward / authentication / promotion | **FAIL** | Freezer selection filters scores to 2021–2023 and regime ends before 2024 (`freeze_train_only_baselines.py:32-45`), and fit thresholds remain TRAIN-only (`run_study.py:111-131`). Authentication and pre-fit refusal fail as adjudicated above. | No freezer/source-contract/mismatch/refusal tests exist among the supplied 21 passes. | Use one canonical ordered-list digest; verify pinned manifest bytes, current source hashes, every strict fact, and feature count/order before `load()` or `fit_one()`; refuse on any mismatch and test each failure. |
| D1–D4 determinism/hash binding | **PASS / NOT APPLICABLE** | No serve/ONNX path. Directional feature order is shared by fit/inference and seed is fixed (`run_study.py:111-131`). | Supplied suite passes; no serving interface exists. | Re-audit if serving is introduced. |
| E1–E5 backtest/fill/warmup | **PASS / NOT APPLICABLE** | No executable orders; collection uses explicit 1s/1m bars and four-day warmup (`implementation/run_collect.py:24-28,67-90`). | `tests/test_warmup_retention.py:8-19`. | None. |

## New blocking findings

None. The demonstrated failures are the still-open Pass 09 authentication blocker.

## Assumptions not structurally enforced

The replacement manifests are assumed to describe immutable source bytes and exact strict eligibility, but neither is authenticated before fitting. The `entry_year <= 2023` and regime-end boundary filters implement the 2024+ exclusion; no focused test proves refusal of a future-year row.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED

Pre-execution remains blocked. The amendment creates train-only replacement generators, but their outputs are absent and the fit workflow cannot authenticate them: genuine ordered lists hash differently, source hashes and most strict facts are trusted rather than verified, and phase 0 runs only after model fitting. The 21 passing tests do not exercise this path.

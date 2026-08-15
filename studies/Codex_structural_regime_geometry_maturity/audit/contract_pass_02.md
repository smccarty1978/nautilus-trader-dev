# Contract Audit — Pass 02

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — NOT FIXED.** `implementation/contracts.py:26-39` makes all label strings unit-reachable, but the real workflow at `implementation/finalize_artifacts.py:25-41` considers AUC only: timing improvement can never cause S1/S2/S3, and the test at `tests/test_contracts.py:4-13` bypasses that workflow.
- **C-02 — NOT FIXED.** `implementation/contracts.py:42-58` never recomputes/compares the stored `seal_sha256`, while `implementation/promote.py:14-30` requires audit verdict `PASS`; this checker’s mandated clean verdict is `CLEAR`, so a clean result is forced to BLOCKED/abort.
- **C-03 — NOT FIXED.** `implementation/finalize_artifacts.py:45-56` drops unavailable snapshots from the required checkpoint artifact; `implementation/validate.py:42-68` still joins only `checkpoint_decision_ns`, requires every month nonzero, and omits base-eligible zero-row, composite-key, crossing-uniqueness, positive-label, and full denominator gates.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | `finalize_artifacts.py:45-65`; current `results/oos_first_crossings.parquet` lacks causal features/Walk-A labels and current `results/summary.json:1-8` lacks comparisons/attrition | Schema inspection; no manifest-schema test | Preserve unavailable checkpoint rows/reasons; run the corrected pipeline; validate every listed path and required field. |
| Terminal labels | **FAIL** | `contracts.py:26-39`; `finalize_artifacts.py:25-41` | Helper-only reachability test passes | Drive classification from both frozen discrimination and timing conditions; test `terminal_summary()` scenarios. |
| C4 selection seal / promotion gates | **FAIL** | `contracts.py:42-58`; `promote.py:11-30` | Tamper test passes only artifact mutation | Recompute the seal payload hash during verification; accept the mandated clean audit verdict/schema; test real promotion success and tampering. |
| Domain/completeness §7 | **FAIL** | `validate.py:42-68` | No validator tests | Enforce exact composite keys, conditional zero-row behavior, boundary membership, one arm per regime/model/threshold, positives, and every denominator. |
| D1–D4 train/serve | **NOT APPLICABLE** | No serving/ONNX artifact; ordered features/model hashes at `run_study.py:93-114` | No serve path | Re-audit if serving is introduced. |
| E1–E4 | **PASS / NOT APPLICABLE** | `collector.py:16-50`; `run_collect.py:47-57`; no executable orders | Existing materialized NT collection; boundary tests pass | None. |
| E5 warmup | **NOT VERIFIED** | Four-day load and target-month retention at `run_collect.py:27,45-60` | No warmup/readiness-retention test | Add a test proving retained first-month rows begin only after required state is ready. |

## New blocking findings

### C-04 — Corrected collection is disconnected from all consumers

`implementation/run_collection_grid.py:12,28-47` writes the requested 48 months to `_work/collection`, but `run_study.py:37-49`, `implementation/validate.py:11-14`, and `implementation/finalize_artifacts.py:13-16` hard-code `_work/collection_audit_fix_v2`. A fresh corrected collection can therefore complete while fitting, validation, and finalization silently read the earlier surface. Use one configured collection root, carried into all consumers and sealed in the manifest.

### C-05 — Warmup readiness is unverified

`implementation/run_collect.py:45-60` loads four prior days and clips output, but no test establishes that the 1m/5m state is ready at the first retained checkpoint. Under the audit rule, apparently correct code without a relevant test is `NOT VERIFIED` and cannot be accepted.

## Assumptions not structurally enforced

The observed old output happens to contain 48 nonzero partitions. That does not enforce the SPEC’s conditional zero-row rule, nor prove the newly collected root is the one consumed.

## Blocking verdict

BLOCKED

The corrected 48-month collection must not start: three prior criticals remain, the producer/consumer root mismatch can make the entire rerun stale, and E5 remains unverified. Eight study tests pass, but none exercises the global validator, real terminal summary/promotion path, or warmup readiness.

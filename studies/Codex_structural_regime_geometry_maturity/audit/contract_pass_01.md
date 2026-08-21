# Contract Audit — Pass 01

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **WITHDRAWN — environment-only placeholder:** `audit/contract_status.json` said the checker model was unavailable; this pass completed the mandatory audit, so that condition is no longer applicable.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest (§6) | **FAIL** | `SPEC.md:164-182`; `implementation/finalize_artifacts.py:22-48`; `implementation/report.py:46-72` | Direct schema/content inspection; study tests do not cover artifacts | Materialize every listed path with its required contents; add a manifest-schema/content test. |
| Terminal labels / promotion gate | **FAIL** | `SPEC.md:184-193`; `implementation/finalize_artifacts.py:42-48` | No terminal-label tests | Implement and test a deterministic classifier covering all six labels, including abort. |
| C4 temporal test discipline | **PASS** | `run_study.py:91-107` fixes 2021–2023 TRAIN and 2024 OOS; TRAIN scores alone derive thresholds/deciles | Direct artifact inspection confirms declared train/OOS counts | None. |
| C4 selection-seal integrity / frozen promotion checks | **FAIL** | `implementation/finalize_artifacts.py:33-38`; `results/models_manifest.json:242-246` | No tamper/seal or promotion-gate tests | Seal the selected result and every decision input/output; verify hashes and frozen gates before summary promotion. |
| Domain/completeness (§7) and global validation | **FAIL** | `SPEC.md:195-203`; `implementation/validate.py:22-48` | No zero-row, wrong-grid, missing-dispatch, composite-key, or global-validation tests | Validate the exact 48-month names/bounds, zero-row rule, full decision/regime key cardinality, missing dispatches, boundary membership, and all denominator gates. |
| D1–D4 train/serve | **NOT APPLICABLE** | `SPEC.md:10-12`; no served model/ONNX artifact; ordered feature lists are recorded at `run_study.py:91-107` | No serve-path tests because deployment is outside scope | Re-audit D if a serving artifact is introduced. |
| E1–E2 subscription/data contract | **PASS** | `implementation/collector.py:16-40`; `implementation/run_collect.py:47-56` | `test_completed_5m_boundary.py:4-21` passes | None. |
| E3–E4 executable fill model | **NOT APPLICABLE** | `SPEC.md:133-138` declares analytical diagnostics, not executable fills; collector submits no orders | No fill tests required for this study | None. |
| E5 warmup | **PASS** | `implementation/run_collect.py:27,45-60` loads four days and retains only the target month | Boundary tests pass; no explicit warmup-retention test | Add a retention-boundary test (non-blocking test gap). |

## Blocking findings

### C-01 — Terminal decision labels are unreachable

`finalize_artifacts.py:42-48` computes only a count of AUC deltas, then unconditionally writes `S3_CLASSIFICATION_ONLY`. No code evaluates S1, S2, S4, S5, economic non-worsening, timing, or `ABORT_CONTRACT_OR_CAUSAL_FAILURE`. Consequently five declared terminal outcomes cannot be produced, and even a failed audit leaves `summary.json:2-7` labelled S3. This is the repeat historical terminal-reachability defect.

### C-02 — The selected result does not authenticate itself

`models_manifest.json:242-246` hashes three inputs only. It does not bind fitted model identity, scores, OOS metrics, first crossings/economic labels, validation report, summary, or report. `collection_manifest.json:62-68` binds collection/code but not the selected conclusion. A result file or terminal label can therefore be altered while every stored hash and `validation: PASS` remains unchanged. No promotion gate verifies hashes or all frozen stop conditions before writing the selected result.

### C-03 — Required deliverable contents and global completeness checks are missing

Literal manifest failures: `phase0_contract.json:1-27` does not record the frozen eligibility predicates or separate direction-specific Top-25 sources/reconciliation; `collection_manifest.json:57-61` omits an explicit missing-prior-anchor count; `oos_first_crossings.parquet` has 15 columns but no structural/base features or Walk-A economic labels (those are written to the unlisted `oos_crossing_events.parquet` by `evaluate.py:12-31`); `summary.json:1-7` omits primary comparisons and attrition; `REPORT.md:1-103` omits an S1–S5 interpretation and a limitations section. `validate.py:23-43` checks only partition count (not the exact grid/bounds), joins only `checkpoint_decision_ns`, and does not implement zero-row/base-eligibility, missing-dispatch, boundary-membership, or denominator gates despite Manifest item 11 requiring every deterministic contract and denominator gate.

## Assumptions not structurally enforced

The observed directory happens to contain 48 correctly named nonzero months and the inspected row-metric table has all 16 expected model/direction/bucket cells. The validator does not enforce those exact grids, so this observed compliance is not structural.

## Blocking verdict

BLOCKED

Deployment/acceptance is blocked by three contract failures: terminal labels are not derived or reachable, the selected result lacks a self-authenticating seal/promotion gate, and multiple literal manifest contents plus global completeness checks are absent. Six bounded study tests pass, but none covers these contradictory implementation paths.

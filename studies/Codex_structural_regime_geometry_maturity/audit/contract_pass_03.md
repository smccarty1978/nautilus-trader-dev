# Contract Audit — Pass 03

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability

## Prior finding adjudication

- **C-01 — NOT FIXED.** `implementation/finalize_artifacts.py:26-47` now consumes timing as well as AUC, but `tests/test_contracts.py:4-13` still tests only `classify_terminal()` directly; no test drives `terminal_summary()` through S1–S5 and abort.
- **C-02 — FIXED.** `implementation/contracts.py:52-61` recomputes the seal payload hash, `implementation/promote.py:14-17` accepts `CLEAR`, and tampered artifact/payload tests pass at `tests/test_contracts.py:16-33`.
- **C-03 — NOT FIXED.** `implementation/validate.py:58-60` removes unavailable snapshots before demanding a complete join and joins only `checkpoint_decision_ns`, not the decision/regime composite; `validate.py:52,56` defines zero-row eligibility as every RTH base row rather than the direction-specific accepted surface.
- **C-04 — NOT FIXED.** Defaults share `COLLECTION_ROOT`, but `implementation/run_collection_grid.py:29-34` permits an arbitrary `--output-root` while consumers remain fixed at `paths.py:8`; `tests/test_collection_lineage.py:7-10` proves defaults only.
- **C-05 — NOT FIXED.** `tests/test_warmup_retention.py:6-9` proves interval clipping only; it never proves tracker/1m/5m readiness at the first retained checkpoint.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **FAIL** | Manifest is explicit at `SPEC.md:164-182`; current `results/oos_first_crossings.parquet` lacks the required structural features and Walk-A columns, while `results/collection_manifest.json` and `results/summary.json` are pre-remediation outputs | Direct schema/content inspection; no literal manifest test | Regenerate from the corrected root, then validate every listed artifact and required content. |
| Terminal labels | **NOT VERIFIED** | Real workflow now combines discrimination, timing, and P90 economics at `finalize_artifacts.py:26-47` | 11 tests pass; `test_contracts.py:4-13` bypasses `terminal_summary()` | Add fixture-driven real-workflow scenarios reaching all six labels. |
| C4 selection seal | **PASS** | Model artifacts carry hashes at `run_study.py:101-114`; the decision surface/report are sealed at `promote.py:11,20-29`; payload and artifact hashes are recomputed at `contracts.py:42-61` | Artifact and seal-payload tampering tests pass | None. |
| C4 promotion checks | **FAIL** | `promote.py:27-29` checks validation/audits/terminal, but never requires `phase0_contract.json.status == PASS` or clean `audit/lint.json`, despite frozen abort conditions at `SPEC.md:205-215` | No promotion success/failure test | Explicitly gate phase-0 and lint status; test each frozen blocker independently. |
| Domain/completeness §7 | **FAIL** | Exact 48-month boundaries exist at `validate.py:24-56`, but the filtered/non-composite join and overbroad zero-row denominator are at `validate.py:52,58-60` | No validator tests; lineage test covers paths only | Join all snapshots on the frozen composite key; distinguish unavailable from missing dispatch; compute accepted eligibility per direction. |
| D1–D4 train/serve | **NOT APPLICABLE** | No serving/ONNX path; ordered feature lists and fitted-model hashes are recorded at `run_study.py:100-114` | No serve path | Re-audit if serving is introduced. |
| E1–E4 | **PASS / NOT APPLICABLE** | NT collection has matching 1s/1m data and no executable orders at `implementation/run_collect.py:56-67` | Collector boundary tests pass | None. |
| E5 warmup | **NOT VERIFIED** | Four prior days are loaded at `run_collect.py:55-69` | `test_warmup_retention.py:6-9` tests clipping, not readiness | Assert first retained rows are emitted only after required tracker states are ready. |

## New blocking findings

### C-06 — Promotion omits frozen phase-0 and lint gates

`implementation/promote.py:27-29` can emit `PASS` when the authenticated `phase0_contract.json` itself says `FAIL`, or when `audit/lint.json` is not clean, because neither status is inspected. Authentication proves bytes, not acceptance. Require both frozen status checks and cover their failing cases.

## Assumptions not structurally enforced

Using the default collection root and having four prior calendar days available are true in the intended invocation, but neither guarantees the actual producer root nor indicator readiness.

## Blocking verdict

BLOCKED

Corrected 48-month collection must not start. The validator can reject legitimate unavailable rows while missing composite-key errors, the collection CLI can write a root no consumer reads, the real terminal workflow and warmup readiness remain untested, and promotion can pass failed phase-0 or lint gates.

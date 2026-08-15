# Contract Audit — Pass 09

**Agent:** contract-checker  
**Date:** 2026-08-14  
**Scope:** C4, D, E; SPEC §§6–7; terminal-label reachability; fresh pre-execution source/config

## Prior finding adjudication

- **C-01 — FIXED.** All six declared labels remain reachable through `implementation/contracts.py:12-39` and the artifact workflow test at `tests/test_terminal_workflow.py:44-57`.
- **C-02 — FIXED.** Seal payload and sealed bytes are recomputed at `implementation/contracts.py:42-61`; tamper tests are `tests/test_contracts.py:16-33`.
- **C-03 — FIXED.** Global validation consumes every 2021–2024 RTH score key at `implementation/validate.py:79-98`.
- **C-04 — FIXED.** The exact 48-month UTC grid and half-open boundaries are enforced at `implementation/validate.py:29-36,77-98,119-120`.
- **C-05 — FIXED.** Retained-row readiness remains enforced at `implementation/run_collect.py:35-54,80-90`; tested at `tests/test_warmup_retention.py:8-19`.
- **C-06 — FIXED.** Promotion gates the seal, report, validation, phase 0, lint, both audits, and non-abort terminal at `implementation/promote.py:31-60`; blocker test at `tests/test_promotion.py:14-22`.
- **C-07 — FIXED.** Failed validation, phase 0, lint, or audit reaches ABORT at `implementation/finalize_artifacts.py:57-62`; tested at `tests/test_terminal_workflow.py:44-65`.
- **C-08 — FIXED (code; rerun pending).** SHORT/LONG load named sources independently and bind direction-specific ordered lists and hashes at `run_study.py:23-29,107-127,172-181`. Existing result artifacts predate this code.
- **C-09 — FIXED (code; rerun pending).** The generator emits eight pooled plus sixteen directional AUC rows at `run_study.py:184-201`; stale `results/oos_row_metrics.csv:1-17` awaits authorized execution.
- **C-10 — FIXED.** Terminal AUC evidence is explicitly filtered to SHORT/LONG at `implementation/finalize_artifacts.py:37-47`; timing/crossing inputs are direction-specific score outputs.
- **C-11 — FIXED.** Validation requires equality with the frozen 24-cell set and rejects missing/unexpected substitutions at `implementation/validate.py:21-22,115-120`.
- **Prior phase-0 completeness/authentication blocker — NOT FIXED.** `source_contract` compares only an ordered-list digest/count (`run_study.py:172-181`), while `phase0_contract` tests five observed predicates then echoes the remaining frozen facts (`run_study.py:162-169`). It never authenticates source-manifest/config bytes or compares their model identity, direction, target, session, ATR anchor, cadence, censoring, and eligibility declarations. The SHORT source declares those facts in `studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/config.yaml:3-18,40-68`; the LONG manifest identity/target/direction are at `studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2/manifest.json:2-24`.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables Manifest §6 | **NOT VERIFIED** | Every listed path exists, but phase 0, models manifest, and AUC rows are stale pre-remediation materializations (`results/phase0_contract.json:1-32`; `results/oos_row_metrics.csv:1-17`). | Supplied lint is 0/0 and 21 tests pass; execution is correctly gated. | Fix phase 0, clear both audits, rerun, then literally validate schemas/content. |
| Terminal labels | **NOT VERIFIED** | All labels are reachable and pooled AUC is excluded (`implementation/finalize_artifacts.py:37-62`). | Reachability is tested (`tests/test_terminal_workflow.py:44-57`), but no regression injects pooled rows and proves the label is unchanged. | Add one pooled-row isolation regression. |
| Domain/completeness §7 | **NOT VERIFIED** | Exact partitions, global key join, zero-row rule, no dispatch fill, and exact 24-cell identity are enforced (`implementation/validate.py:29-36,55-74,77-120`). | Grid construction is tested at `tests/test_validate_contract.py:21-25`; no substitution-through-validator test exists. | Test one required cell replaced by an alien cell and require FAIL. |
| C4 walk-forward / seal / promotion | **FAIL** | TRAIN/OOS fitting and TRAIN-only thresholds/deciles are explicit (`run_study.py:107-127`); selection sealing/promotion are direct (`implementation/contracts.py:42-61`; `implementation/promote.py:31-60`). Phase 0 can still PASS without authenticating all frozen source facts (`run_study.py:162-181`). | Seal and promotion tests pass, but no phase-0 source/fact mismatch tests exist. | Load/hash each direction’s frozen manifest/config; compare every frozen fact and ordered feature identity/count; make any mismatch FAIL and test it through promotion. |
| D1–D4 determinism/hash binding | **PASS / NOT APPLICABLE** | No serving/ONNX path. Directional feature order is reused for fit/inference, seed is fixed, and artifacts/source-list hashes are bound (`run_study.py:107-127,172-181`). | Supplied suite passes; no serving interface exists. | Re-audit if serving is introduced. |
| E1–E5 backtest/fill/warmup | **PASS / NOT APPLICABLE** | No executable order path; NT collection uses explicit 1s/1m bars and four-day warmup (`implementation/run_collect.py:24-28,67-90`). | `tests/test_warmup_retention.py:8-19`. | None. |

## New blocking findings

None. The sole blocker is the unremediated Pass 08 phase-0 finding.

## Assumptions not structurally enforced

Phase 0 assumes echoed source identity and eligibility facts match the frozen source artifacts. Pooled-label isolation and alien-cell substitution are implemented but lack direct regression tests.

## Referred to lookahead-auditor

None.

## Blocking verdict

BLOCKED

Pre-execution remains blocked because phase 0 can self-certify without authenticating both frozen direction-specific source contracts and every frozen eligibility fact. The exact 24-cell AUC grid and directional-only terminal evidence are code-fixed; materialized deliverables remain pending the gate and therefore are not yet verified.

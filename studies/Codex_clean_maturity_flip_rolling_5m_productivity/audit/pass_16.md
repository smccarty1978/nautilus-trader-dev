<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "278ae56d33371fbc15f2278834bdd8057d86a9863f3532fa616e123827c13b64"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 16

**Date:** 2026-08-18T00:00:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity/study.yaml` (new `execution.data_requirements.authorized_dates` field only). Read in full to resolve causality: `backtests/nt_runtime/data_plan.py` (`resolve_authorized_dates`, `enforce_authorized_dates`, `resolve_data_plan`), `backtests/nt_runtime/modes/collect.py` (call site), `compiled_study.json` (compiled propagation), `audit/execution_manifest.json`/`preflight.json` (unchanged-file confirmation).
**Scope hash:** `execution_composite_sha256 278ae56d33371fbc15f2278834bdd8057d86a9863f3532fa616e123827c13b64` (preflight run `20260818T150602Z_c76eeeb13596`).
**Lint:** 0 critical / 0 warning (preflight `CAUSAL_LINT` PASSED, `CAUSAL_INVARIANTS` PASSED — `audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 15 Note [B9] | Synthetic test fixture in `test_run_exploratory_runner_integration.py` doesn't exercise the sub-threshold coverage-refusal branch | WITHDRAWN (out of scope this pass) — that test file did not change in this diff (`study:tests/test_run_exploratory_runner_integration.py` hash unchanged per `execution_manifest.json`); the disclosed boundary case remains separately covered by the unchanged `test_structural_coverage_gate.py`. No new evidence to adjudicate; not re-raised. |

## Critical findings
None.

## Warnings
None.

## Notes
- **[F2/G-adjacent, disclosure only]** `study.yaml:73-78` declares exactly 5 consecutive calendar dates (2023-10-02 to 2023-10-06, a Mon-Fri week) with no explicit statement of whether all 5 have complete RTH catalog coverage in `data/catalog/NQ_v0_2020_2026`. This is a data-availability question for the smoke run itself (would surface as a G2/missing-bar condition at execution time, not a causal defect in code), not something `enforce_authorized_dates` is designed to check. Not blocking.

## Verification detail

**1. `enforce_authorized_dates` fails closed (task item 1).**
`backtests/nt_runtime/data_plan.py:56-82`. `resolve_authorized_dates` (`:22-53`) returns the sorted 5-date list from `compiled_data.spec.execution.data_requirements`; `enforce_authorized_dates` builds the full calendar-day range `[start_date, end_date]` (`pd.date_range(..., freq="D")`, `:73-74`) and raises `UnauthorizedExecutionDomainError` (`:76-81`) if **any** requested day is not in the authorized set — a hard exception, not a warning/log/return-code. It is called unconditionally at `resolve_data_plan:274`, which is itself called unconditionally at `backtests/nt_runtime/modes/collect.py:149` (`from backtests.nt_runtime.data_plan import resolve_data_plan` at `:13`) — the only call site in the collect-mode entrypoint, with no bypass flag, env-var override, or conditional skip found in either file. A requested window including e.g. `2023-10-09` (the following Monday, outside the 5 declared dates) would raise before any bar is loaded. Confirmed fail-closed.

**2. Declared dates are genuinely inside TRAIN, clear of DEV/OOS and prohibited years (task item 2).**
`study.yaml:52-55`: `chronology.train: [2021, 2022, 2023]`, `dev: [2024]`, `prohibited: [2025, 2026]`. All 5 authorized dates fall in Oct 2023 → inside `train`. `resolve_data_plan` runs the year-level prohibited check (`:254-260`) and authorized-years check (`:262-270`) *before* the exact-date check (`:272-274`, comment explicitly documents this ordering so a year-level violation reports first) — 2023 passes both, and since `2023 not in dev_years={2024}`, the OOS-unlock-token gate (`:276-293`) is never invoked, correctly, since dates that don't touch DEV shouldn't need an unlock token. Compiled propagation confirmed clean: `compiled_study.json:142-149` carries the identical 5 dates through the compiler with no truncation/reformatting.

**3. No weakening of previously-audited causal contracts (task item 3).**
`enforce_authorized_dates`/`resolve_authorized_dates` only bound the **calendar-day window** passed into `resolve_catalog_plan`/`resolve_data_plan`; they do not touch bar dispatch order, `ts_init` construction, or RTH close-time gating. Confirmed no code changes to the collector or model runner:
- `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/collector.py` hash `fe7f3509fe7f...` and `implementation/phase0.py` hash `28ef17c5c35c...` in `audit/execution_manifest.json` are the files actually bound to this study's runtime/contract closures (`run_exploratory_models.py` is not part of this study's tracked closure at all, consistent with it being a downstream/offline analysis script outside the NT-runtime execution boundary this preflight run covers).
- `utils/causal_registration.py` (1s-before-1m dispatch order, `add_bars_causal_order`) and `utils/session_boundaries.py` (RTH gating) are both listed in `execution_manifest.json`'s `runtime_closure`/`governance_closure` and their hashes are part of the unchanged composite that preflight validated as `CAUSAL_INVARIANTS: PASSED` — no diff surface in those files this pass.
- `resolve_data_plan`'s date-bounding checks run strictly before catalog bar loading in the collect-mode call graph (`modes/collect.py:149` precedes any bar subscription); date-window narrowing cannot introduce look-ahead — it can only ever *reduce* the set of bars presented to the strategy, and the 1s-before-1m ordering and checkpoint cadence (5s, verified in Pass 14/15) are properties of `add_bars_causal_order`/the collector's own event handling, neither of which this diff touches.

## Referred to contract-checker
- None newly referred this pass.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4 unaffected — no execution-affecting collector/model code changed. H1-H4 not applicable (no bracket simulation in this study).
- `enforce_authorized_dates`/`resolve_authorized_dates` (`backtests/nt_runtime/data_plan.py`) verified fail-closed, unconditionally wired into the collect-mode entrypoint, and confirmed to only narrow — never widen or reorder — the execution date/bar surface.

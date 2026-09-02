# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-02 · **Scope** `compiled_plan.json`, `study.yaml`, `research_workflow/host/{mux,strategy,outcomes}.py`,
`research_workflow/host_runner.py`, `backtests/nt_runtime/engine_builder.py`, `utils/causal_registration.py`,
`features/trackers/{generic_structural_geometry,generic_rolling_productivity,host_bindings}.py`
**Scope hash (audited composite)** `b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443`
**Lint** preflight CLEAR (0 critical/warning); readiness overall PASS · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 · Note: 2

## Checks performed
- **Epoch/tracker timing (A, B9).** Grid cadence fires on `nq_1s` (`HostCore._epochs`); `regime_1m`/`regime_bar_5m` update only from `nq_1m` ingests, which are ordered strictly after the coincident `nq_1s` bar at every epoch by construction — traced below, not assumed.
- **Label kernel (C1, C2).** `LabelOutcomeKernel` (flip kernel) resolves only on `on_flip`/subsequent `on_bar` events, i.e. strictly from data at/after `T`; `preflight.json.leaked_outcome_columns=[]` confirms no outcome-shaped name reached `columns.features`/`columns.metadata`. `flip_ts`/`time_to_flip_seconds`/`target_flip_within_horizon`/`disposition`/`censor_reason` are observation-only columns (`compiled_plan.json:393-407`), never candidate features.
- **Population qualify (F/G, C2).** `excursion.frozen_atr/mfe_atr/progress_windows/retained_ratio`, `regime_1m.age_s`, `features.structural_snapshot_ready` are all tracker state evaluated at `T` (`host/strategy.py:270-280`); `excursion`/`regime_1m` are updated from `nq_1s`/`nq_1m` only through in-order `ingest()` calls, so qualify never reads ahead of `T`.
- **Rolling features (B1-B7).** `generic_rolling_productivity.py` → `Rolling5mProductivityTracker` maintains a `deque` bounded by `window_ns` (true rolling window, not lifetime); `rolling_300s_max_progress_atr`/`giveback_atr`/`retention_ratio` are computed only over bars already in the deque at snapshot time — matches the whitelisted "describes the past" pattern, not the "running extremum masquerading as eventual" pattern.
- **Chronology (C3).** `compiled_plan.json.chronology`: train=[2021], dev=[2022] (opened only by OOS stage), prohibited=[2023-2026], authorized smoke date 2021-01-05 — matches the required table exactly.
- **Session (F1-F4).** RTH gate uses `session_table.in_session(T)` with `T = bar.ts_init` (close time), via the canonical `build_session_table` — not a bespoke reimplementation.
- **H (bracket price resolution).** Not applicable: `contract == "label"`, `kernel == "flip"`, `arms == []` — no `TradeExecutionContract`/fill semantics exist in this plan to audit.

## The 1s-before-1m dependency (traced, not assumed)
The compiled plan marks **both** `nq_1s` and `nq_1m` as `"role": "execution"` (`compiled_plan.json:949-973`), so the mux's context-queue protection (`StreamMux._release_context`, strictly-before-T) does **not** apply to `nq_1m`; `assert_epoch_visibility` only forbids `ts_init > T` for execution streams, which permits `nq_1m` at exactly `T`. This matters because the grid anchor is 1m-boundary-aligned (`regime_1m.start_ns`) and steps every 5s, so **1/12 of all epochs land exactly on a completed-1m-bar close** (1/60 for 5m) — not an edge case.
Correctness therefore depends entirely on `nq_1m` being *ingested* strictly after the coincident `nq_1s` bar, which is **not** an NT-native guarantee — `studies/nt_live_scoring_infra_prereqs/tests/test_coincident_bar_ordering.py::test_add_data_call_order_determines_the_tie_break_not_nt_native` proves reversing `add_data()` call order flips the arrival order. Traced the actual path this study uses:
- `run_plan_on_catalog` (real TRAIN/OOS) → `backtests/nt_runtime/engine_builder.py:240` calls `add_bars_causal_order(engine, bars_1s, bars_1m)` — 1s added first, matching the required convention.
- `run_plan_with_engine`/`host_runner.py:89-95` (synthetic/smoke) independently replicates it (`sorted(durations, key=lambda k: durations[k])`, 1s before 1m).
Both paths this study will actually exercise get it right by explicit construction, not by chance.

## Warnings
### [A4/B9] `research_workflow/host/mux.py:159-192`, `compiled_plan.json:949-973` — 1m/5m context has no in-code causal-order safeguard
**Failure path:** `nq_1m` is classified `role="execution"` (default in `research_workflow/grammar/spec.py:48`; no study in this repo declares `role: context`), so `StreamMux` gives it `at_epoch` visibility instead of the `strictly_before` visibility a context stream gets. Correctness at 1/12 of epochs relies entirely on `add_bars_causal_order` continuing to be called correctly in `engine_builder.py`; if a future edit to that file (or a new driver added for platform-v2) ever reorders or omits that call — exactly the regression `test_add_data_call_order_determines_the_tie_break_not_nt_native` exists to catch — `assert_epoch_visibility` would **not** raise (ts_init==T is legal for an execution stream), and `prior_1m_regime_*`, `ema_slope`, and the qualify() gate would silently ingest the bar that just closed at T. `lifecycle_v2.readiness()` (`R1_NQ/R3/R5/R8/R9`, no R4-equivalent) does not independently re-run `verify_callback_causal_order` against a real bounded catalog window for this plan, unlike the legacy `readiness.py` R4 probe.
**Smallest fix:** add a bounded readiness check (or reuse `verify_callback_causal_order`) to `lifecycle_v2.readiness()` that ingests a real 1-hour catalog window through `GovernedHostStrategy` and asserts 1s-before-1m at every coincident timestamp; alternatively, declare `nq_1m` with `role: context` in `StreamSpec` so `StreamMux` enforces `strictly_before` in-code regardless of loader call order.

## Notes
- `StreamSpec.role: Literal["execution","context"]` defaults to `"execution"`; `role: context` is exercised only by `research_workflow/tests/test_host_core.py`'s synthetic fixture — no real study uses it. Framework-wide gap, not unique to this study.
- `SPEC.md` sections (Population/Target/Features/Chronology/Deliverables Manifest) are unpopulated boilerplate for this "zero study Python" plan; `compiled_plan.json`/`study.yaml` are the operative contract. Not re-derived here since it does not affect causal correctness.

## Referred to contract-checker
- `SPEC.md` Deliverables Manifest section is empty — completeness/deliverables scope, not causal.

## Clean checks
A1-A3, A5, B1-B7, B10, C1-C3, F1-F4, G1-G4 clean. H1-H4 not applicable (label-only contract, no arms).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_a_flip_180s", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443", "critical": 0, "warning": 1, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 11

**Date:** 2026-08-16
**Scope:** `backtests/nt_runtime/data_plan.py`, `backtests/nt_runtime/engine_builder.py`, `backtests/nt_runtime/strategy_binding.py` (exactly the 3 files changed since the pass-10 seal), and their effect on the collect-mode call path (`backtests/nt_runtime/modes/collect.py`).
**Scope hash:** not computable in this tool session (no hashing utility available to this agent — Read/Grep/Glob/Write only, no code execution/Bash). Scope is fully enumerated above; `scripts/preexec_audit_seal.py` computes the authoritative AST-closure hash independently and does not depend on this field.
**Lint:** not re-run (deterministic preflight already ran `causal_lint.py`; see preflight note below).
**Verdict:** CLEAR

## Summary

This pass raises no findings at CRITICAL or WARNING severity. Two NOTE-level observations are recorded below (see "Findings by severity"). Authoritative counts are the ones in the AUDIT_SUMMARY_V2 block at the end of this report, not any prose restatement above it.

## Preflight note (not a causal finding, disclosed for transparency)

`audit/preflight.json` currently reports status BLOCKED, failed gate CAUSAL_INVARIANTS, failure id INVARIANT_TEST_FAILURE. The only failing test (`audit/failure_packet.json`) is `test_audit_seal_valid_and_tamper_detection`, which fails because `verify_preexec_audit_seal` correctly detects that the 3 files in this pass's scope no longer match the pass-10 `preexec_audit_seal.json` hashes — i.e. the seal is stale exactly because these 3 files changed, which is the reason this pass exists. All 214 other tests pass, including the two tests directly relevant to this scope (`test_collector_default_execution_mode_matches_nt_add_venue_defaults`, `test_legacy_backtest_mode_enables_adaptive_high_low_ordering`). Seal regeneration/tamper design is `contract-checker` scope (C4/D), not mine; logged once under "Referred to contract-checker" and not itemized further.

## Prior findings adjudicated

Pass 10 verdict was CLEAR with zero findings at any severity. Nothing to adjudicate.

## Findings by severity

No findings meet the CRITICAL or WARNING bar in this pass. Two NOTE-level observations follow.

### NOTE: `ExecutionMode.run_window_mode` / `warmup_days` / `warmup_dispatched` are declared but unconsumed on the collect path
`backtests/nt_runtime/engine_builder.py:72-74` — `ExecutionMode` carries `run_window_mode`, `warmup_days`, and `warmup_dispatched` fields, but `build_engine` never reads them (bars are still loaded `warmup_start_dt -> end_dt` per `DataPlan`, independent of `mode.warmup_days`), and `backtests/nt_runtime/modes/collect.py:198` still calls `engine.run()` with no arguments regardless of `mode.run_window_mode`. This is inert metadata for the collect path today, not a causal defect — collector behaviour is unchanged because nothing new is being read. Flag only so a future wiring of these fields into `collect.py` doesn't silently assume they already gate execution.

### NOTE: no dedicated regression test pins collect-mode dotted-path resolution for the sibling study
`backtests/nt_runtime/strategy_binding.py:100-101` — verified by code-path tracing (not by an existing test) that `studies.Codex_clean_maturity_flip_rolling_5m_productivity.implementation.collector.CleanFlipCollector` (`compiled_study.json:142,214,268`) still resolves under the new `allow_unregistered` gate: `resolve_strategy_binding` is called from `collect.py:153-157` with `mode="collect"` and no explicit `allow_unregistered`, so it defaults to `mode != "backtest"` → `True`, and the dotted-path import branch (`strategy_binding.py:120-140`) is reached exactly as before. No `test_nt_runner_backtest.py` or `strategy_binding` test exercises this specific path. Test-coverage gap is `contract-checker` scope (test quality); referred once below.

## Causal analysis by question

**1. Does the `resolve_catalog_plan` extraction change any value or gate order in `resolve_data_plan`?**
No. `resolve_data_plan` (`data_plan.py:141-243`) calls `resolve_catalog_plan` for the generic half, then re-derives `start_dt`/`end_dt` from the returned `plan` and applies the same four gates in the same order: (1) prohibited-year overlap (`:178-184`), (2) authorized-domain membership (`:186-194`), (3) DEV/OOS unlock via `verify_oos_unlock_token` (`:196-213`), (4) warmup-domain prohibited then warmup-DEV lock (`:215-241`). `warmup_start_dt = start_dt - Timedelta(days=warmup_days)` is computed once, inside `resolve_catalog_plan` (`:120`), and reused unchanged. No value is recomputed with different inputs; no gate was dropped, reordered, or made conditional differently than before.

**2. Does the collect path (`modes/collect.py` -> `build_engine`) change behaviourally? Is the `collector_default()` claim true?**
No behavioural change, and the claim is empirically verified rather than asserted. `collect.py:176` calls `build_engine(data_plan, log_level=log_level, telemetry=telemetry)` with no `execution_mode`, so `build_engine` falls back to `ExecutionMode.collector_default()` (`engine_builder.py:191`), which is `order_handling="virtual", run_window_mode="all_loaded"` with all other fields at dataclass defaults (`bar_execution=True`, `bar_adaptive_high_low_ordering=False`, `oms_type="NETTING"`, `account_type="MARGIN"`, `base_currency="USD"`, `starting_balance=1_000_000`). `scripts/tests/test_nt_runner_backtest.py:119-128` asserts these two fields against `inspect.signature(BacktestEngine.add_venue).parameters[...].default` read live off the installed `nautilus_trader` package — this is a runtime introspection test, not a docstring claim, and it passed in the last full test run (214/215, only the seal-staleness test failed). `engine.add_venue(...)` at `engine_builder.py:205-213` now passes these values explicitly where they were previously passed implicitly (per task description); since the explicit values equal the library defaults, the venue configuration NT actually builds is identical.

**3. Does anything alter bar loading, the `ts_init` contract, or `add_bars_causal_order` ordering?**
No. `build_engine:218-236` is structurally unchanged: `CausalDataLoader(data_plan.catalog_path).load_bars(...)` for `bar_type_1s` then `bar_type_1m`, both windowed `warmup_start_dt -> end_dt`, followed by `add_bars_causal_order(engine, bars_1s, bars_1m)` — the 1s-before-coincident-1m call signature and argument order are untouched. `DataPlan`'s `ts_init_delta_1s_ns`/`ts_init_delta_1m_ns` fields and `PRODUCT_CATALOGS` are unmodified by the extraction.

**4. Does the `allow_unregistered` default change collect-mode strategy resolution for any existing study?**
No. `allow_unregistered` only defaults to `False` when `mode == "backtest"` (`strategy_binding.py:100-101`); `collect.py` always calls with `mode="collect"`, so `allow_unregistered` resolves to `True`, identical to the pre-change behaviour (no gate existed before). Verified concretely for both registered (`strategies.flip_prediction_collector.FlipPredictionCollector`, matches `STRATEGY_REGISTRY["flip_prediction_collector"]` by module+class and resolves via the registry branch) and unregistered (`studies.Codex_clean_maturity_flip_rolling_5m_productivity...CleanFlipCollector`, not in `STRATEGY_REGISTRY`, resolves via the dotted-import branch at `:120-140`) strategy identities used by studies in this repo. The new `w4_exit_strategy` registry entry and `order_handling` field are additive and unread by the collect path.

## Referred to contract-checker
- Preflight CAUSAL_INVARIANTS gate is failing solely due to seal staleness (`test_audit_seal_valid_and_tamper_detection`) pending this pass's seal regeneration — seal/tamper design is C4/D scope.
- No dedicated regression test pins collect-mode resolution of unregistered dotted-path strategy classes under the new `allow_unregistered` branch — test-quality/coverage is contract-checker scope.

## Clean checks
- A (A1-A5): timestamp/`ts_init` contract unchanged by any of the 3 files.
- B, C1-C3: not touched by this diff (no feature/label code in scope).
- F, G, H: not touched by this diff (no session/data-integrity/bracket-sim code in scope).
- Chronology gate order and values in `resolve_data_plan` verified unchanged (Q1).
- `ExecutionMode.collector_default()` venue-default equivalence verified via passing runtime introspection test (Q2).
- Bar loading window and `add_bars_causal_order(engine, bars_1s, bars_1m)` call unchanged (Q3).
- `allow_unregistered` default verified inert for `mode="collect"` on both a registered and an unregistered strategy binding (Q4).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "critical": 0, "warning": 0, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->

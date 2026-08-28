<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "workflow_canary_ordered_barrier_v1", "audited_execution_composite_sha256": "b24fc7a7989a043e843dc41e4c8530935ac56d6ac00678749809885c720e5316"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 02

**Date** 2026-08-28 ·
**Scope** `research_workflow/generic_collector.py` (`_evaluate_checkpoint` `target_atr_t`; 3 checkpoint `cand_record` builders; `_frozen_target_atr_at_T`), `research_workflow/tests/test_ordered_barrier_entry_reference.py::test_5c`. Pass_01 surface (`target_runtime.py`, `target_replay_oracle.py`) unchanged this pass. ·
**Scope hash** frozen composite `b24fc7a7…316` — matches task; cross-checked vs `audit/preflight.json` (CLEAR), `audit/readiness.json` (PASS), `r8_double_identity` (IDENTITY_STABLE, 100% coverage). Freeze is fresh. ·
**Lint** preflight `CAUSAL_LINT` PASSED (0 critical / 0 warning) ·
**Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 2

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [B3/C4] `generic_collector.py:698` — frozen-ATR source differs by population path (checkpoint = regime-start `regime_frozen_atr`; episode = trailing ATR at T) | **FIXED** | `_evaluate_checkpoint:1244` now computes `target_atr_t = float(self.regime_engine.atr or 0.0)` — the latest causally completed 1m Wilder ATR(14) at T — and all three checkpoint `cand_record` builders write it as `target_frozen_atr` (`:1433`, `:1536`, `:1643`). `_frozen_target_atr_at_T:698` prefers `target_frozen_atr` > `atr_t` > `atr`, so both population paths now freeze the ordered-barrier half-width at the **identical** target-time quantity (`self.regime_engine.atr` at T; episode path reads the same at `:1120`). `cand_record["atr"]` (= `regime_frozen_atr`, regime-start) is now feature-normalization only. New read verified causal below. Regression: `test_ordered_barrier_entry_reference.py::test_5c`. |
| 2 | [G2] `target_runtime.py:180` / `generic_collector.py:1020` — `max_gap_seconds = 1` censors on any absent 1s second | **CARRIES (NOTE)** | Unchanged. Detection uses only observed inter-bar spacing and the per-bar flag — fully causal. This is a censoring-rate / study-power property, not look-ahead. No code change; not blocking. |
| 3 | [C1] `target_replay_oracle.py:67` — legacy oracle branch trusts `candidate["entry_price"]` when tape events lack `open` | **CARRIES (NOTE)** | Unchanged. The live collector always emits `open` on every 1s event (`_handle_1s_bar:1023`), so production never reaches the branch; reachable only from direct unit fixtures. Not blocking. |

## Critical findings
None.

## Warnings
None.

## New causal verification — the `target_atr_t` read at T

| Property | Evidence |
|---|---|
| `self.regime_engine.atr` advances only on completed 1m bars | The engine is mutated exclusively by `regime_engine.update(h, l, c)` in `_handle_1m_bar:543`; no 1s path touches it (grep: only reads at `:544`, `:1066`, `:1120`, `:1244`). |
| The read happens at a decision instant that precedes the coincident 1m close | `_evaluate_checkpoint` runs inside `_handle_1s_bar`, and only when `T == ts_avail` of a completed 1s bar (`:1008-1015`). R2 (new composite): 1m `ts_init − ts_event == 60s`; R4 (new composite): 0 causal inversions across 259,559 `(ts_init, timeframe)` callbacks — the 1s bar closing at T is dispatched **before** the 1m bar closing at T. So at checkpoint T, `regime_engine.atr` reflects Wilder ATR(14) through the most recent 1m bar with `ts_init < T`. Strictly ≤ T — **no look-ahead.** |
| Matches the compiled contract | `target_contract.atr_source = latest_causally_completed_1m_wilder_atr_14_available_at_T`, `atr_frozen_at = decision_ts`. `self.regime_engine.atr` at the 1s checkpoint T is exactly that quantity. |
| Frozen once, never recomputed | `_track_pending:651` → `open_pending` captures `atr` once (`target_runtime.py:75`); `ingest_bar`/`terminal` never rewrite it. Later bars cannot alter the barrier half-width (`test_5`, `test_5c`). |
| Fallback chain remains causal | If `regime_engine.atr` were 0/None at T (unreachable once a regime is armed — `:1238` early-returns on non-positive `regime_frozen_atr`, and Wilder ATR stays positive post-warmup), `_frozen_target_atr_at_T` would fall to `atr` = `regime_frozen_atr`, frozen at regime start ≤ T — still ≤ T, still no look-ahead. |

Non-code changes noted (not causally relevant, not in scope): removal of stale `CANARY_BLOCKER.md`; parity driver relocated to `_work/` (out of the execution closure). `r8_double_identity` confirms the closure re-resolves to the declared composite with 100% coverage and no unresolved dependencies.

## Notes

### [G2] `max_gap_seconds = 1` — carried from pass_01
Any single missing RTH second between T and the horizon censors the candidate. Causal; a study-power concern only.

### [C1] Legacy oracle `entry_price` fallback — carried from pass_01
Unreachable from the live collector (always emits `open`); fixture-only.

## Referred to contract-checker
None new. (Pass_01's train/serve referral is resolved by this change — both population paths now freeze the barrier ATR at the same target-time quantity.)

## Clean checks
A1–A5, B1–B7, B9–B10, C1, C2, C3, F1–F4, G1–G4, H1–H4 clean for this change. Pass_01 verified properties 1–8 (entry reference resolution, next-bar-open price, no pre-entry OHLC, ATR frozen at T, `entry_ts = ts − NS`, race-start consistency, oracle independence, session/gap censoring) are unaffected — `target_runtime.py` and `target_replay_oracle.py` are byte-identical to pass_01.

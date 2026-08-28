<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 3, "study": "workflow_canary_ordered_barrier_v1", "audited_execution_composite_sha256": "fd7472b6ee9026840b5a9b2cdb383719b25801b95e6f1b8e7388ca2a3400c6ca"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-08-28 ·
**Scope** `research_workflow/target_runtime.py`, `research_workflow/target_replay_oracle.py`, `research_workflow/generic_collector.py` (ordered-barrier path: `_track_pending`, `_frozen_target_atr_at_T`, `_resolve_ordered_barriers`, `_handle_1s_bar`, `_build_episode_candidate_row`), `research_workflow/tests/test_target_runtime.py`, `research_workflow/tests/test_ordered_barrier_entry_reference.py` ·
**Scope hash** frozen composite `fd7472b6…c6ca` (matches task; cross-checked vs `audit/preflight.json`, `audit/readiness.json`, `audit/frozen_execution_manifest.json` — all three carry the same composite) ·
**Lint** preflight `CAUSAL_LINT` PASSED (0 critical / 0 warning) ·
**Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 3

## Critical findings
None.

## Warnings
None.

## Notes

### [B3/C4] `generic_collector.py:698` — frozen-ATR source differs by population path
`_frozen_target_atr_at_T` resolves `target_frozen_atr` → `atr_t` → `atr`. Checkpoint-grid
candidates supply `atr` = `self.regime_frozen_atr` (frozen at regime start, `_evaluate_checkpoint:1237`);
episode candidates supply `atr_t`/`target_frozen_atr` = `self.regime_engine.atr` (trailing
14-period ATR from the last completed 1m bar at T, `_build_episode_candidate_row:1120`). **Both
are strictly ≤ T, so neither is look-ahead** — the barrier half-width is simply not defined
identically across the two population paths. The canary exercises the checkpoint-grid path
only. Train/serve-consistency of the barrier definition across paths is a contract question.
→ noted for contract-checker.

### [G2] `target_runtime.py:180` / `generic_collector.py:1020` — `max_gap_seconds = 1` censors on any absent 1s second
GAP censor fires whenever `ts - prev_ts > 1s` (a second with no trades) or the resolving bar
carries `gap=True`. Detection uses only observed inter-bar spacing (`self.last_ts_seen`) and
the per-event flag — fully causal — but on this contract a single missing RTH second between
T and horizon censors the candidate. This is a censoring-rate / study-power concern, not a
leak.

### [C1] `target_replay_oracle.py:67` — legacy oracle branch trusts `candidate["entry_price"]`
When tape events lack an `open` key the oracle falls back to a pre-populated `entry_price`
and `entry_ts = T`. The live collector always emits `open` on every 1s event
(`_handle_1s_bar:1023`), so the production path never reaches this branch; it is reachable
only from direct unit fixtures (`test_target_runtime.py`). No production exposure.

## Verified causal properties (this change)

| # | Property | Evidence |
|---|---|---|
| 1 | Entry resolves on the FIRST 1s bar with `ts > observation_ts`; `ts == T` does **not** resolve | `target_runtime.py:122` `if ts <= pending["observation_ts"]: return` (no append, no entry). Integration: at checkpoint T, `_track_pending` appends pending then `_resolve_ordered_barriers` feeds the T-stamped bar → returns unresolved (`_handle_1s_bar:1018-1025`). |
| 2 | `entry_price` = resolving bar's OPEN, never decision close / `price_at_T` / fallback | `target_runtime.py:124` `pending["entry_price"] = float(bar["open"])`. `_build_episode_candidate_row` no longer writes `entry_price` (comment `:1158-1160`); `_track_pending` ordered branch never reads it (`:648-670`); `open_pending` has no `entry_price` input (`:69-112`). |
| 3 | No future OHLC inspected before entry is fixed | Pre-entry bars (`ts ≤ T`) `return` before the `events.append` (`target_runtime.py:121-123`); only the resolving bar onward contributes H/L. `terminal` reads only `pending["events"]`. The resolving bar is the entry bar and is barrier-eligible by design. |
| 4 | Barrier ATR frozen at T, never recomputed post-T/post-entry | `open_pending` captures `atr = float(candidate["atr"])` once (`:75`); `ingest_bar`/`terminal` never rewrite it. Sources (`_frozen_target_atr_at_T`) are all completed-bar ATR ≤ T (see Note 1). `open_pending` rejects non-positive ATR (`TARGET_FROZEN_ATR_NONPOSITIVE`). |
| 5 | `entry_ts = ts − NS` is the correct causal open instant; horizon measured from `entry_ts` | 1s bar is close-stamped (`ts_init = ts_event + 1s`, R2 1s PASS), so `ts − NS = ts_event` = the bar's open. `horizon_end_ts = entry_ts + horizon*NS` matches authoritative `forward_outcomes/tracker.py:77,256` (`entry.entry_ts + horizon_seconds*NS`). For `entry_reference: next_bar_open`, measuring the deadline from the entry instant (not from T) is the tracker convention. |
| 6 | Race start vs the reference bar — internally consistent, matches tracker, **not ambiguous** | Contract sets `bar_inclusion: fully_forward` (`compiled_study.json:62,285`). `tracker._includes` (FULLY_FORWARD) admits a bar with `ts_open ≥ entry_ts`, i.e. the reference bar. `target_runtime.terminal` skips `ts ≤ entry_ts`; the entry bar's close-stamp is `entry_ts + NS > entry_ts`, so it is evaluated. Deadline inclusivity (`ts > horizon_end_ts: break`) matches `tracker._update_ordered_barriers` (`ts_close > deadline: continue`). Consistent. |
| 7 | Oracle independent of runtime pending state | `target_replay_oracle.replay:57-66`: when any event carries `open` (always true for the collector, `_handle_1s_bar:1023`), entry is derived as `next(e for e in evs if ts > T)`, `entry_price = entry_ev["open"]`, `entry_ts = ts − NS` — no read of any `pending`/`entry_resolved`/pre-populated `entry_price` field. Barrier params taken from the contract's `required_forward_outcomes` (`_contract_barrier`). `test_11b` asserts a poisoned `entry_price=999999` does not change the answer. |
| 8 | Session-end and gap censoring remain causal | `session_close_ts = session_close_ns(T, session)` — frozen at T (`_track_pending:663-666`). `terminal` SESSION_END when `horizon_end_ts > close` or an event `ts > close` (`target_runtime.py:158,178`); matches `tracker._horizon_status` / `_includes` truncation. GAP uses only observed spacing (`ts - prev_ts > max_gap_ns`) and the per-bar flag. Unresolved-at-run-end → `DATA_END` censor, never a fabricated outcome (`generic_collector.py:767-778`). |

Additional: direction/`regime_direction` is the prevailing regime direction at T (precedes the
outcome). Timeout → label 0 in both runtime (`target_runtime.py:198`) and oracle
(`:104`). `open_pending` rejects any `entry_reference != "next_bar_open"`
(`TARGET_ENTRY_REFERENCE_UNSUPPORTED`); oracle mirrors (`ORACLE_UNSUPPORTED_ENTRY_REFERENCE`).
Legacy `terminal` branch (`"entry_resolved" not in pending`) is gated on absence of the new
key and only reachable from pre-existing direct unit calls.

## Referred to contract-checker
Frozen-ATR barrier half-width is defined differently across the checkpoint-grid vs episode population paths (both causal); confirm this is acceptable train/serve-wise (Note 1).

## Clean checks
A1–A5, B1–B7, B9–B10, C1, C2, C3, F1–F4, G1–G4, H1–H4 clean for this change.

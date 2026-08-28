<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "workflow_canary_ordered_barrier_v1", "audited_execution_composite_sha256": "f79ecff8a466e6ae3fce130f42d3f9ab355915ea032ec8b1a5adc57eece05408"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 04

**Date** 2026-08-28 ·
**Scope** `research_workflow/generic_collector.py` (`_track_pending` ordered-barrier branch — `horizon_seconds` source, `:668-669`), `research_workflow/tests/test_ordered_barrier_entry_reference.py::test_10c`. `target_runtime.py` / `target_replay_oracle.py` unchanged since pass_03. ·
**Scope hash** frozen composite `f79ecff8…408` — matches task; cross-checked vs `audit/preflight.json` (CLEAR, `execution_composite_sha256`), `audit/readiness.json` (PASS, `prepared_execution_identity`), `audit/frozen_execution_manifest.json` (`frozen_execution_composite_sha256`), `r8_double_identity` (`composite_sha256`). Freeze is fresh. ·
**Lint** preflight `CAUSAL_LINT` PASSED (0 critical / 0 warning) ·
**Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 2

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [B3/C4] frozen-ATR source differs by population path | **FIXED (pass_02)** | Not reopened; that code path unchanged. |
| 2 | [G2] `max_gap_seconds = 1` censors on any absent 1s second | **CARRY (NOTE)** | Unchanged. Gap detection still uses only observed inter-bar spacing + the per-bar flag — causal. Not blocking. (Forward exposure is now smaller — 60s vs 300s window — but the note stands.) |
| 3 | [C1] legacy oracle branch trusts `candidate["entry_price"]` when tape events lack `open` | **CARRY (NOTE)** | Unchanged. Fixture-only; the live collector tape always carries `open`. Not blocking. |

## Critical findings
None.

## Warnings
None.

## Causal verification — barrier horizon now sourced from the compiled contract

| Property | Evidence |
|---|---|
| The horizon used is the compiled contract's | `_track_pending:668` now sets `horizon_seconds = int(self._ordered_barrier.get("horizon_seconds") or self.cfg.horizon_seconds)`. `self._ordered_barrier` is the compiled `target_contract.required_forward_outcomes[].ordered_barriers[]` entry; `compiled_study.json` declares `horizon_seconds: 60` there (and `null` at the top-level target, which is why `cfg.horizon_seconds` had fallen back to the `300` default in `build_collector_config_kwargs`). |
| Now consistent with the oracle and tests | `target_replay_oracle._contract_barrier` reads `barrier["horizon_seconds"]` (60) from the same contract (`target_replay_oracle.py:51-54`); `terminal`/`ingest_bar` math unchanged. Runtime, oracle and `test_10`/`test_10c` now race the same 60s window. |
| The change only *shrinks* the forward observation window | `horizon_seconds` feeds solely `horizon_end_ts = entry_ts + horizon_seconds*NS` (`target_runtime.py:128`); the barrier loop evaluates events with `ts ≤ horizon_end_ts` and `break`s after. 60s < 300s ⇒ strictly fewer forward bars considered. Restricting the label window removes future data from the label — the opposite of look-ahead. No new input is read. |
| Session-end censoring stays causal | `session_close_ts` is still `session_close_ns(T, session)` (frozen at T); `SESSION_END` now triggers on `entry_ts + 60s > close` — a narrower, still-causal condition. |
| Fallback is causal too | `or self.cfg.horizon_seconds` fires only if the compiled barrier dict lacks the key (it does not, per `compiled_study.json`). A fixed integer horizon carries no data either way. |

The pre-change behaviour (racing the barrier over the 300s `cfg` default while the contract/oracle used 60s) was a label-window / contract-fidelity divergence, not look-ahead; it is resolved at this composite. Any residual parity aspect is `contract-checker` scope.

## Notes

### [G2] `max_gap_seconds = 1` — carried (pass_01–03)
Any single missing RTH second between T and the horizon censors the candidate. Causal; study-power concern only.

### [C1] Legacy oracle `entry_price` fallback — carried (pass_01–03)
Reachable only from hand-built fixtures lacking `open`.

## Referred to contract-checker
None new. (The 300s-vs-60s label-window divergence corrected here is contract-fidelity; contract-checker's own pass covers it.)

## Clean checks
A1–A5, B1–B7, B9–B10, C1, C2, C3, F1–F4, G1–G4, H1–H4 clean for this change. All pass_01 verified properties remain intact; `target_runtime.py` / `target_replay_oracle.py` byte-identical to pass_03.

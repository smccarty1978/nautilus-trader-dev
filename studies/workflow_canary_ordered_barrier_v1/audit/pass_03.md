<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "workflow_canary_ordered_barrier_v1", "audited_execution_composite_sha256": "3af4f5e71cd9f8930fafc8b2c83a900fd0dd11ea35f73eb984a6fb3aca286336"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 03

**Date** 2026-08-28 ·
**Scope** `research_workflow/target_runtime.py` (`OrderedBarrierTargetRuntime.ingest_bar` — retention of `open` in appended `pending["events"]` entries), `research_workflow/tests/test_ordered_barrier_entry_reference.py` (`test_3`, `test_11`). `open_pending`, `terminal`, `target_replay_oracle.replay`, `generic_collector.py` unchanged this pass. ·
**Scope hash** frozen composite `3af4f5e7…336` — matches task; cross-checked vs `audit/preflight.json` (CLEAR), `audit/readiness.json` (PASS, `overall_status`), `r8_double_identity` (`composite_sha256` equal, IDENTITY_STABLE). Freeze is fresh. ·
**Lint** preflight `CAUSAL_LINT` PASSED (0 critical / 0 warning) ·
**Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 2

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [B3/C4] frozen-ATR source differs by population path | **FIXED (pass_02)** | Not reopened; `generic_collector.py` byte-identical to pass_02. Both population paths freeze the barrier ATR at `self.regime_engine.atr` at T. |
| 2 | [G2] `max_gap_seconds = 1` censors on any absent 1s second | **CARRY (NOTE)** | Unchanged. Gap detection still uses only observed inter-bar spacing + the per-bar flag — causal. Censoring-rate / study-power property, not look-ahead. Not blocking. |
| 3 | [C1] legacy oracle branch trusts `candidate["entry_price"]` when tape events lack `open` | **CARRY (NOTE), further narrowed** | The branch still exists but is now even less reachable: `ingest_bar` retains `open` on every appended event, so replaying the oracle directly off the collector's own `pending["events"]` tape (as `test_11` now does) always takes the *independent* branch. Legacy branch is fixture-only. Not blocking. |

## Critical findings
None.

## Warnings
None.

## Causal verification — retaining the entry bar's own `open` on the tape

| Property | Evidence |
|---|---|
| `open` is the appended bar's *own* open, not future data | `ingest_bar:135` stores `float(bar["open"])` from the same `bar` whose `ts` (close-stamp) is being appended. The collector builds that dict as `{ts, open, high, low, gap}` from one completed 1s bar (`_handle_1s_bar:1023`); a bar's open is fully known at its own close. |
| Only bars with `ts > T` ever reach the tape | Pre-decision bars still `return` before the append (`ingest_bar:121-123`). Every retained `open` therefore belongs to a bar beginning at or after T (`open` instant `= ts − NS = entry_ts ≥ T` for the entry bar; strictly later otherwise). No pre-T price is recorded. |
| The barrier-race label is unaffected | `terminal` reads only `e["ts"]`, `e.get("gap")`, `e.get("high")`, `e.get("low")` (`target_runtime.py:172-194`) — never `open`. Coordinator confirms barrier math byte-identical; independently verified by reading the function. `open` is inert for label resolution. |
| Oracle re-derivation stays consistent and independent | `replay` independent branch: `entry_ev = next(e for e in evs if ts > T)`, `entry_price = entry_ev["open"]`, `entry_ts = entry_ev["ts"] − NS` (`target_replay_oracle.py:59-66`). Because the retained tape's first entry is the entry bar, this reproduces `ingest_bar`'s `entry_price = bar["open"]` / `entry_ts = ts − NS` exactly. The oracle reads no runtime-internal pending field; `test_11b` (unchanged) still proves a poisoned `entry_price` is ignored. |
| `None`-safety preserved | `ingest_bar:135` guards `bar.get("open") is None`; the live collector always supplies a float open (`_handle_1s_bar:939`). |

## Notes

### [G2] `max_gap_seconds = 1` — carried (pass_01, pass_02)
Any single missing RTH second between T and the horizon censors the candidate. Causal; study-power concern only.

### [C1] Legacy oracle `entry_price` fallback — carried, further narrowed (pass_01, pass_02)
Reachable only from hand-built fixtures lacking `open`; the live collector tape now always carries `open`.

## Referred to contract-checker
None.

## Clean checks
A1–A5, B1–B7, B9–B10, C1, C2, C3, F1–F4, G1–G4, H1–H4 clean for this change. All pass_01 verified properties (entry-reference resolution, next-bar-open price, no pre-entry OHLC inspection, ATR frozen at T, `entry_ts = ts − NS`, race-start consistency vs `forward_outcomes/tracker.py`, oracle independence, session/gap censoring) remain intact; `open_pending`/`terminal`/`replay` barrier logic is byte-identical to pass_02.

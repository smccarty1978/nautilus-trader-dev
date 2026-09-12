# Look-Ahead & Timestamp Audit — Pass 03 (delta)
**Date** 2026-09-12 · **Scope** delta since pass 01: `research_workflow/host/mux.py`, `research_workflow/grammar/compiler.py`, `research_workflow/host/strategy.py` (platform e66c981a), `compiled_plan.json` streams/population/columns/outcome, `study.yaml` metadata rename; re-checked `research_workflow/host/outcomes.py`, `research_workflow/sessions.py`, `features/trackers/ohlcv_delta.py`, `features/trackers/host_bindings.py` · **Scope hash** `plan_sha256 bed51b460286e18d...`, `execution_composite_sha256 041379f7e433a637...` · **Lint** 0 critical / 0 warning (preflight `CLEAR`, all 8 checks PASSED; readiness PASS; tests 150/0 at this composite) · **Verdict** CLEAR

`audit_type: causal`
`study: nq_mtf_regime_atlas_pilot2023`
`audited_execution_composite_sha256: 041379f7e433a637beba1e687fd70124f7d0c79a34e010c6b6de5cc53d13da7c`
`auditor: claude-lookahead-auditor-pass03`

## Summary            Critical: 0 · Warning: 3 · Note: 3

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 01 `[readiness-scope]` R2/R4 absent for this study (WARNING) | **OPEN, carried** | `audit/readiness.json` still lists only R1/R3/R5/R8/R9/R10. The same-instant boundary is now covered by unit fixtures at this composite (`research_workflow/tests/test_host_core.py:79-93`, `test_grammar_v2.py:193-206`), but those are synthetic tapes, not a study-scoped R2/R4 on real bars. |
| 2 | pass 01 `[feature-surface]` uncomposed context features self-disclosed (NOTE) | **Reinstated, unchanged** | 21 instances composed again (`compiled_plan.json` availability rows 93-303); the G3/G6 gaps remain self-disclosed. contract-checker's. |
| 3 | pass 02 `[B9/mux]` CRITICAL — `nq_1m` mis-tagged, `derived_from: nq_1s` naming an absent stream | **RESOLVED** | `compiler.py:242` now scopes `externals` to `set(s.timeframes)`; the plan carries `nq_1s` (`compiled_plan.json` streams, role `execution`, `at_epoch`) so every `derived_from: nq_1s` resolves; `mux.py:144-147` raises `DERIVED_SOURCE_STREAM_ABSENT` otherwise and `compiler.py:821-826` dry-constructs the real `StreamMux` at compile. The `KeyError` path is gone and cannot recur silently. |
| 4 | pass 02 `[B9/mux]` sub-finding — cadence stream declared `strictly_before` | **RESOLVED** | `compiled_plan.json:1996-2002` `nq_1m` `visibility: at_epoch`, `epoch_bearing: true`; `strategy.py:92-95` refuses the composition at construction; `compiler.py:828-831` refuses it at compile. |

## Critical findings
None.

## Warnings

### [B-scope/prose] `research_workflow/grammar/compiler.py:1621` + `research_workflow/audit_packets_v2.py:146` — three declared fields state the opposite of the plan's own enforced `visibility`
**Observation (this is the ALSO-ADJUDICATE item; verdict: (a) stale prose, not correct under any reading):** `availability.same_timestamp_rule` is a hard-coded constant string emitted regardless of the per-stream fields (`compiler.py:1621`), copied into the packet at `audit_packets_v2.py:138`; `invariants[1]` ("context streams visible strictly before T") is likewise hard-coded (`audit_packets_v2.py:146`); and `streams[].same_ts: "unavailable"` on `nq_1m` (`compiled_plan.json` streams) says its same-instant visibility was not opted into. All three are **false for `nq_1m` in this plan**: it is a `role: context` stream with `visibility: at_epoch`, `epoch_bearing: true`, and it is the only stream whose bar is exposed *at* `T`.
**Why not CRITICAL:** no number moves. The mux reads only the per-stream field (`mux.py:134,141,206-211`); `same_ts` is never read by `mux.py` or `strategy.py`. The failure mode is an auditor (or the next re-audit) trusting a packet field that the runtime does not implement.
**Smallest fix:** derive `same_timestamp_rule` and the `invariants` line from the emitted `streams[].visibility` (e.g. name the `at_epoch` context streams), and stop emitting `same_ts: unavailable` on an `epoch_bearing` stream.

### [B9] `studies/.../study.yaml:89,93` + `features/trackers/ohlcv_delta.py:1,73` — `bar_volume` still means "the last 1s bar", but the epoch bar is now the 1m bar
**Failure path:** `{feature: bar_volume, context: bar}` carries no timeframe; it is routed from `completed_1s` (`compiled_plan.json` availability row 274-283; `features.routing.completed_1s.stream: nq_1s`) and `host_bindings.py:543-546` dispatches that 1s bar's `volume` into the tracker documented as a 1s tracker (`ohlcv_delta.py:1`), whose `bar_estimates` returns `bar_volume = float(volume)` of the last bar passed (`ohlcv_delta.py:73`). Under the previous `completed_1s` cadence that bar *was* the epoch bar; under `cadence: completed_1m` it is the final second of the minute. The column is therefore ~1/60 scale and is the tail-second's volume, while `study.yaml:89` describes it as "the flip bar's own volume". Any analysis grouping or thresholding on `bar_volume` reads a different quantity than the contract says.
**Why not CRITICAL:** causally clean (the value is a completed bar with `ts_init == T`); it mis-scales a feature column, not the study's flip-timing headline.
**Smallest fix:** declare the instance with an explicit timeframe (`{feature: bar_volume, context: bar, timeframe: 1m}`) or amend the comment to say "the last completed 1s bar of the epoch minute". `vol_sum_60s_vs_1200s_ratio` and `est_delta_ratio_60s` are unaffected — they are time windows, not per-bar reads.

### [carried] R2/R4 still not proven on real bars for this plan
See adjudication row 1. The epoch semantics changed in exactly the dimension R2/R4 would exercise; the evidence at this composite is fixture-level.

## Notes

### [N1] The relaxation is compiler-scoped, not mux-scoped — and this plan alone cannot prove it
The plan contains exactly one context stream (`nq_1m`), so it carries **no negative control**; scope had to come from code and fixtures. It does: `compiler.py:259` defaults every context stream to `strictly_before`; `_mark_epoch_bearing_stream` (`compiler.py:759-785`) is the only writer of `at_epoch` onto a context stream and is called from exactly one site (`compiler.py:853`) with the population cadence key, flipping one entry; `visibility` is not a `StudySpec` field (no occurrence in `research/schemas/`; `scripts/gen_yaml_reference.py:52` documents only `streams[].same_ts`), so a study author cannot widen it. Contrast fixtures: `test_grammar_v2.py:153-161` — same `shape_b` study *without* `completed_1m` cadence leaves `nq_1m` `("context","strictly_before")`; `test_grammar_v2.py:164-179` — adding the cadence flips that one stream only; `test_host_core.py:89-92` — a `strictly_before` stream still raises `CONTEXT_STREAM_VISIBLE_AT_EPOCH`. **Verdict: SCOPED relaxation.** `mux.py:134` nonetheless trusts whatever the plan declares and does not itself tie `at_epoch` to the cadence stream; a hand-edited plan could mark another context stream `at_epoch`. Even then the exposure is bounded to `ts_init == T` — a completed bar containing no post-`T` data — so it is a governance gap, not look-ahead, and `plan_sha256` binding closes it in practice.

### [N2] `decision_epoch_ts_ns` is now identical to `observation_ts` by construction
`compiled_plan.json:1107-1110` binds it to `epoch.T`; `strategy.py:318` writes `observation_ts = T`. The rename is *correct* (the value is the 1m bar's `ts_init`, `strategy.py:254` `self._epoch(bar, bar.ts_init, None)`), and the old name `triggering_1s_ts_init` would now be a lie. Redundant column, no defect.

### [N3] The epoch fails closed when the same-instant 1s bar is missing
If no 1s bar closes at `T`, the 5m/… bucket containing it is incomplete and is discarded, never published (`mux.py:109-120`), and `nq_1m@T` is released by the next 1s bar. The epoch still fires at `T` with every stream's `visible_through <= T`. If the 1m bar were instead delivered *late* (after 1s bars beyond `T`), `assert_epoch_visibility` raises `EXECUTION_STREAM_AHEAD_OF_EPOCH` (`mux.py:206-209`) rather than emitting a leaked row.

## Referred to contract-checker
- `research_workflow/host/outcomes.py:86-91,277-278` — with `session_end: censor` and `horizon: 24h` (> any Globex trading day), `p.flip_end > p.session_close` holds for every candidate, so every pending row is finished `CENSORED/SESSION_END` with `flip_ts=None` even when the flip occurs inside the session; `study.yaml:181-196` describes `truncate` semantics. Terminal-label (POSITIVE) reachability — contract-checker's `C4`/reachability scope, flagged here once and not re-raised.
- gap_inventory G0/G3/G4/G5/G6/G7 completeness items and `stage: collect` lifecycle state — unchanged from passes 01/02.

## Clean checks
- **Epoch soundness at the 1m close (the central question) — CLEAN.** `mux.ingest` (`mux.py:157-163`) releases queued context bars **before** `_apply` of the execution bar that released them, and `_release_context` (`mux.py:169-178`) admits only `b.ts_init < before_ts`. So at the epoch raised inside `_deliver(nq_1m@T)` (`strategy.py:220-221`, `251-254`, `278-280`): `nq_1s` is visible through `T` (the bar closing *at* `T`, applied earlier), every derived bucket through its last close `<= T` (published inside `_apply` of its source bar, `mux.py:186-197`), and the bar at `T+1s` that triggered the release is **not yet applied**. Nothing visible at `T` carries information from after `T`; the assertion (`mux.py:201-211`) turns any violation into a hard stop, not a silent row. Confirmed end-to-end by the tape in `test_host_core.py:59-86` (`delivered == [a_1s@60, a_1m@60, a_1s@61]`).
- **Callback order at `T` — CLEAN.** `strategy.py:198-227`: deferred opens flush → tracker `on_bar` (regime_1m, excursion_1m, feature host) → `_epochs` → `kernel.on_bar`. Trackers see the completed bar at `T` before the snapshot; the outcome kernel sees it after the candidate is emitted.
- **`atr_availability: through_decision_ts` — CLEAN.** `strategy.py:338-339` defers the kernel open; `_flush_deferred_opens` (`strategy.py:180-192`) resolves `regime_1m.atr` at the first delivery with `ts_init > T` but *before* any tracker consumes that bar (`strategy.py:198-199` precedes `:217`), so the frozen ATR is state as of `<= T`.
- **C1-C3 — CLEAN.** `FORWARD_OUTCOME_GUARD: PASSED`, `leaked_outcome_columns: []`. The flip kernel opens after `T` (`outcomes.py:242-252`), so a flip routed during the bar at `T` (`strategy.py:234-239`) cannot resolve the candidate born at `T`. No forward-outcome column in the 21 aliases; `prior_*`/`current_*` regime and `mfe_atr_1m` reads are running-since-start values.
- **Feature snapshot timing / B1-B7, F — CLEAN.** All 21 instances declare `bar_state: completed` (`study.yaml:69-95`); none declares `forming`. Every availability row is `completed_bar_ts_init`. The 5m family reads `regime_5m`, updated only from complete buckets (`mux.py:91-93`). No 1s-callback read of a forming 1m bar exists — the direction is now the reverse and the 1m bar at the epoch is complete.
- **G/session — CLEAN.** `build_session_table` (`sessions.py:136-154`) yields `SplitSessionTable(gate=AllSessionTable, censor=CalendarSessionTable[TRADING_DAY])`; `in_session(T)` is a pure membership test on the committed table (digest `e577a361…`, R3 PASS) and gates emission only — nothing filters what a provider saw. Censor timestamps (`session_close`, gap ts) are calendar- or observation-derived, never computed from post-boundary data.
- **H (chronology / 2026 non-access) — CLEAN.** `chronology`: train [2023], prohibited [2026], `authorized_dates ["2023-10-02"]`, warmup `candidate_emission:false, target_generation:false`; `CHRONOLOGY_ROLE_TABLE: PASSED` (deterministic gate, not re-derived).
- **A1-A5, B1-B7, B10, C1-C3, F1-F4, G1-G4, H1-H4** otherwise clean at the plan/closure level for this delta.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "041379f7e433a637beba1e687fd70124f7d0c79a34e010c6b6de5cc53d13da7c", "auditor": "claude-lookahead-auditor-pass03", "critical": 0, "note": 3, "study": "nq_mtf_regime_atlas_pilot2023", "verdict": "CLEAR", "warning": 3}
<!-- AUDIT_SUMMARY_V2_END -->

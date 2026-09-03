# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-02 · **Scope** `compiled_plan.json`, `study.yaml`, `research_workflow/host/{mux,strategy,outcomes,triggers}.py`,
`research_workflow/sessions.py`, `research_workflow/external_model_scoring.py`, `features/trackers/host_bindings.py`
(`PullbackEpisodeBinding`, `FrozenExternalScoreBinding`)
**Scope hash (audited composite)** `3f2706959401e687fe2e644399ad8bff9c3502e09522b6a0ac99b9643f17615e`
**Lint** preflight CLEAR (0 critical/warning); readiness overall PASS · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 · Note: 2

## Checks performed
- **Derived 5s/5m bucket ordering (extra Q1).** `StreamMux._apply` (`host/mux.py:165-183`) delivers a bucket completed by the current source bar via a recursive `_apply(out)` call **before** `self._deliver(bar)` runs for the completing source bar itself. Since the epoch fires from `_deliver(bar)` (population `cadence.kind="completed_bar"` on `nq_1s`), `regime_5s`/`regime_5m` and the `regime_5s`-sourced `_turn_events` are updated *before* the epoch/sub-epoch evaluation that reads them — the completing bucket is available at, not after, T. `BucketAggregator._complete()` requires contiguous full membership, so only genuinely complete buckets are ever published; no partial/forming 5s data reaches `regime_5s.turned(...)`.
- **Trigger graph (`triggers.py`)** correctly edge-triggers `reset_when`/`entry.when` via `EdgeMemory`; `ARMED` (chain=true) may enter same sub-epoch as `WATCH`, both level checks on already-current tracker state — no time travel.
- **Pullback tracker metadata (extra Q2).** Traced write sites in `PullbackEpisodeBinding`: `arm_ts` is set synchronously in `on_trigger_transition("WATCH","enter",ts,...)` to `ts=epoch.T` of that transition (never at finalize). `triggering_event_close_ts` returns the firing sub-epoch event's `close_ts` (a just-completed 5s bucket, ≤T) or `epoch.T` itself. `counter_close_ts_at`/`counter_direction_at` read only from a completed `intermediate` (regime_5s) bar or the current event payload — always ≤T. `prior_deep_pullback_count` increments only on an `"entry"` transition, and `_emit_candidate` reads the feature snapshot *before* `on_trigger_transition("ENTRY",...)` increments it — a candidate never counts itself.
- **Model C score (extra Q3).** `FrozenExternalScoreBinding.derive` runs after `row.update(feats)` in `_emit_candidate`, so its 13 inputs are the same already-causal candidate features audited under Shape A (`prior_1m/5m_regime_*`, `rolling_300s_*`, `arrival_*`, `ema_slope`). `FrozenExternalModelScorer.score()` has a real fail-closed check (`EXTERNAL_SCORE_INPUT_NOT_AVAILABLE_AT_CHECKPOINT`) — see Warning below on how it's invoked here.
- **Outcome (C1/C2).** `preflight.json.leaked_outcome_columns=[]`; flip kernel with `role="absolute", target_direction=-1` reproduces the reference collector's asymmetric legacy label (only a flip *to* -1 resolves; a flip to +1 leaves the candidate pending) — disclosed in `study.yaml:118-124`, not a hidden defect.
- **Session split (F1-F4).** `session: ALL / censor_session: RTH` compiles to `SplitSessionTable(gate=AllSessionTable, censor=LegacySessionTable("RTH"))` (`research_workflow/sessions.py:78-98`), a purpose-built primitive for exactly this documented legacy pattern — population gates on ALL, censoring uses RTH close. Matches `R3_session_table` PASS.
- **Chronology (C3).** train=[2021], dev=[2022] (OOS-gated), prohibited=[2023-2026], smoke=2021-01-05 — matches required table.

## Warnings
### [B9] `features/trackers/host_bindings.py:690-691` — Model C's own-availability check is vacuous
**Failure path:** `FrozenExternalScoreBinding.derive` builds `availability_ts={n: ts for n in surf}` — i.e. it stamps **every** input feature's availability as exactly `epoch.T`, then passes that to `FrozenExternalModelScorer.score()`, whose `future = [... if availability_ts[name] > checkpoint_ts]` guard compares `ts > ts`, which is always `False`. The fail-closed check that exists specifically to catch "an input not actually available at the checkpoint" can never fire from this call site, regardless of what the true availability of a given input is. Currently benign only because the 13 consumed features are independently verified causal (audited under Shape A's identical surface); a future addition of a genuinely not-yet-closed input to `ordered_feature_surfaces` would not be caught here.
**Smallest fix:** thread each feature's real availability timestamp (already known to the feature host per its `required_events`/tracker close time) into `availability_ts` instead of a uniform `ts`, so the existing guard does real work.

## Notes
- Asymmetric absolute-direction flip label (`target_direction=-1`) means bearish (`dir=-1`) candidates need a round-trip flip to resolve POSITIVE while bullish candidates need only one transition — an inherited, disclosed parity-reproduction choice (study.yaml comment), not a causal defect.
- `SplitSessionTable` (population ALL / censor RTH) is a shared, previously-tested primitive, not bespoke to this study — flagged only for visibility, not a finding.

## Referred to contract-checker
- None beyond Shape A's SPEC.md-completeness note (same boilerplate pattern here).

## Clean checks
A1-A5, B1-B7, B10, C1-C3, F1-F4, G1-G4 clean. H1-H4 not applicable (label-only contract, no arms).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_b_deep_pullback_5s", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "3f2706959401e687fe2e644399ad8bff9c3502e09522b6a0ac99b9643f17615e", "critical": 0, "warning": 1, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 01
**Date** 2026-09-11 · **Scope** compiled plan / closure files bound to `nq_mtf_regime_atlas_pilot2023` (stage: collect) · **Scope hash** `plan_sha256 67c7b47dca4658...`, `execution_composite_sha256 eceb0985fafc00...` · **Lint** 0 critical / 0 warning (preflight CLEAR) · **Verdict** CLEAR

`audit_type: causal`
`study: nq_mtf_regime_atlas_pilot2023`
`audited_execution_composite_sha256: eceb0985fafc002b67d141fa9fdb728e8a6efe7403dd50a9c686c295d8d50768`
`auditor: lookahead-auditor (claude, pass 01)`

## Summary            Critical: 0 · Warning: 1 · Note: 1

## Prior findings adjudicated
None — this is pass 01, no prior causal report exists for this study.

## Critical findings
None.

## Warnings
### [readiness-scope] `studies/nq_mtf_regime_atlas_pilot2023/audit/readiness.json` — R2/R4 not present for this study
**Observation:** `readiness.json` lists six checks (R1_NQ, R3_session_table, R5_binding_proof, R8_host_boundary_lint, R9_closure_current, R10_zero_study_python), all PASS. There is no R2 (timestamp contracts) or R4 (callback causal order) entry, though the audit brief for this role assumes both are proven "on real bounded samples." `research_workflow/host/mux.py:9` itself documents "there is no proven same-timestamp policy yet, so `same_ts: available` is refused at compile time" — consistent with `same_ts: unavailable` on every stream in the packet, but it means the specific same-instant boundary case this study depends on (a completed 5m/15m/... bucket closing at the same `close_ts` as the 1m anchor bar, e.g. every 5th 1m bar) is covered only by the generic `larger-bucket-first` ordering rule and `test_host_core.py`, not by a study-scoped R2/R4 artifact.
**Why not CRITICAL:** the ordering rule itself is causally conservative (nq_1m is `role: context, visibility: strictly_before`; the derived timeframes are `role: execution, visibility: at_epoch` and are release-queued so a context bar is exposed only once an execution bar with a strictly later `ts_init` has arrived) — I traced this and it resolves correctly; I did not find a failure path. This is "not independently validated for this study" territory, not a demonstrated defect.
**Smallest fix:** none required to proceed; if a future pass wants R2/R4 for this study specifically, request the readiness runner include them for collect-stage studies with derived-timeframe context streams.

## Notes
### [feature-surface] Registered-but-uncomposed context features are self-disclosed, not silent
`research_decision.yaml` gap_inventory (G3/G4/G6) documents that `feature.session_membership`, `feature.relative_volume`, VWAP, ATR-percentile, and the regime family at 30s/3m/15m/30m/1h/4h have no runtime adapter and are therefore NOT composed as features — the study instead carries raw tracker state (`dir_*/age_s_*/bars_*/atr_*`) as metadata for those eight timeframes, exactly as the compiled plan's `metadata` block shows. This is a completeness gap (contract-checker's domain, see below), not a causal defect: nothing here fabricates or backfills a missing feature, and the metadata columns are read from the same live tracker state as the composed features.

## Referred to contract-checker
- gap_inventory G0/G3/G4/G5/G6 (missing multi-timeframe population fan-out, narrow feature-timeframe domain, unregistered VWAP/percentile/session-bucket features, missing grouped-descriptive and cluster-robust analysis ops) — completeness/deliverable-producer gaps, self-disclosed in `research_decision.yaml`; not this role's scope.
- `stage: collect` frame-seal / lifecycle state (no STUDY_CLOSED, contract audit `NOT_REQUIRED`) — lifecycle-state ownership.

## Clean checks
- **A (causality of tracker state at T):** `features/trackers/regime_dual_ema.py:68-109` — `DualEmaRegimeTracker.observe` computes EMA/ATR/regime/`flipped`/`bars_in_regime` entirely from the one completed bar passed to `update`; `flipped` is set within the same call that confirms the new regime, never from a later bar. Applies identically to all nine `regime_<tf>` instances (same tracker class, only `timeframe` varies per `study.yaml`).
- **A (4h and other higher-TF "last completed bucket"):** `research_workflow/host/mux.py:70-108` `BucketAggregator` only emits a derived-timeframe bar via `_complete()` (all expected member bars present, first/last `ts_init` match the bucket bounds); an incomplete bucket is discarded, never partially exposed. 4h/1h/etc. state read by a candidate is therefore always the last fully-completed bucket.
- **A (excursion running fields, not finalize-only):** `features/trackers/host_bindings.py:140-229` `RegimeExcursionBinding` — `mfe_atr/mae_atr/pnl_atr/retained_ratio` are live properties computed from `highest_high/lowest_low/last_close/frozen_atr`, updated on every `on_bar` call for the regime's own bars; not an accumulated field only populated at regime end. Matches the accepted "running, not eventual" pattern (checklist: running extremum requires arming — here the arming IS the regime's own start, and the value is read at the current checkpoint, not claimed as the eventual/terminal MFE).
- **B/F (1s-before-1m / same-timestamp ordering):** `nq_1m` is declared `role: context, visibility: strictly_before`; derived timeframes are `role: execution, visibility: at_epoch`, and `mux.py:4-17` documents the release rule (context bar exposed only once an execution bar with strictly later `ts_init` has arrived; simultaneous-bucket-close publications ordered larger-bucket-first). This means the population's own 1m anchor is release-gated behind the next execution tick, so no context or metadata column can see its own anchor bar before it is confirmed. `R8_host_boundary_lint` (0 findings) and `test_host_core.py` cover this generically.
- **C1-C3 (feature/label separation):** `FORWARD_OUTCOME_GUARD: PASSED`, `leaked_outcome_columns: []`. `outcome.event: regime_1m.flipped` / `kernel: flip` / `entry_reference: decision_close` reference only the anchor's own confirmed state at T; none of the 21 composed feature aliases reads a forward outcome column (`mfe_300s`-style names are absent; the carried `mfe_atr_1m` family are running-since-start values, legitimate per checklist).
- **G/session (TRADING_DAY censoring, no forward leak):** `research_workflow/target_runtime.py:161-179,342-368` — every censoring branch (`SESSION_END`, `GAP`) returns `TargetResult(CENSORED, None, resolved_at_ts, reason)` where `resolved_at_ts` is the session's own `session_close_ts` (calendar-derived, known at candidate build time) or the observed gap timestamp — never a value computed from data beyond that boundary. `session_close_ts` traces to the committed sessions reference table (`R3_session_table` PASS, 1636 sessions, digest `e577a361...`).
- **H (warmup):** `chronology.warmup: {days_before_partition: 5, candidate_emission: false, target_generation: false}` declared identically in `study.yaml` and the compiled packet; enforced by `CHRONOLOGY_ROLE_TABLE: PASSED` (deterministic gate, out of scope to re-derive).
- **Rolling volume/delta features:** `features/trackers/generic_ohlcv_delta.py` — `est_delta_ratio_60s`/`vol_sum_60s_vs_1200s_ratio` are trailing windows ending at T (`[t-w, t]`), never centered or forward; no cross-event elapsed-time defect (checklist item) since both are single-anchor durations, not a gap between two events.
- **A2-A4, B1-B7, C1-C3, F1-F4, G1-G4, H1-H4** otherwise clean at the compiled-plan / closure level; no leaked outcome columns, no unbound primitives (`R5_binding_proof`: 31/31 bound), zero study-local Python (`ZERO_STUDY_PYTHON`, `R10`).

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "eceb0985fafc002b67d141fa9fdb728e8a6efe7403dd50a9c686c295d8d50768", "auditor": "claude-lookahead-auditor-pass01", "critical": 0, "note": 1, "study": "nq_mtf_regime_atlas_pilot2023", "verdict": "CLEAR", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->

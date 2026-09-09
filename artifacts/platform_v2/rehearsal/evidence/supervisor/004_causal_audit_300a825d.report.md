# Look-Ahead & Timestamp Audit — Pass 01 (supervisor bounded mode)

**Date** 2026-09-09 · **Study** `rehearsal_checkpoint_norm` · **Auditor** `lookahead-auditor:004_causal_audit_300a825d`
**Scope** compiled semantic contract `audit_packet_causal.json` (sha256 `168ba1ea9cbb…`, packet_version 2) + 3 source write-sites opened to resolve claims the packet cannot prove
**Audited execution composite** `73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7` (115 closure files, hash v2) · plan `50c8e6667a90` · spec `3af9393f69cc`
**Gate facts cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1_NQ, R2, R3, R4, R5, R8, R9, R10) · tests PASS 137/0 · controller OK @ same composite
**Verdict: CLEAR**

## Summary

Critical: 0 · Warning: 0 · Note: 2

The dominant fact for this audit: **R10_zero_study_python = pass** — the study contributes no Python. The entire executable surface is `main`'s platform, and the brief confirms the study branch changed **no** closure file against `main`. So the causal question reduces to whether the *declared contract* composes the platform's already-audited primitives without creating a leak. It does, and the two highest-risk points are enforced in code rather than merely declared.

## Critical findings

None.

## Warnings

None.

## Notes

### [B9] `features/trackers/structural_regime_geometry.py:89` — prior-5m completion boundary is bucket-granular

`on_5m_bar` completes the outgoing 5m regime with `end_ns = close_ts`, where `close_ts` is the close of the **first bar of the successor** regime. `prior_5m_regime_duration_min` (line 101) and its two `_per_min` derivatives therefore overstate the prior regime's duration by up to one 5m bucket. The 1m path is exact by contrast — `on_1m_flip` completes at the new regime's `start_ns` (line 74), which is contiguous with the prior regime's end.

Not causal: every input is a completed, strictly-past bar, and the flip has already occurred before any checkpoint that can read `_prior_five`. Non-blocking also because **no declared alias depends on it**: `prior_5m_regime_efficiency` is `|net| / range` (line 111), which is duration-free. Raised only so the imprecision is disclosed before a future study declares a `prior_5m_regime_*_per_min` alias.

### [C3] `packet.model.validation` — nominally random selection protocol, degenerate at this composite

`protocol: validation.model_selection.random` is declared alongside `arms: []`, `max_trials: null`, `primary_metric: null`, `random_seed: null`, and one fully specified deterministic parameter set (`random_state: 42`, `deterministic: true`, `n_estimators: 100`, no early stopping). No model selection and therefore no random split is exercised; what actually governs separation is the temporal year-role table. Recorded so that adding arms later triggers a C3 re-audit of the protocol's split semantics rather than inheriting this pass.

## Key clean checks — reasoning where it is not self-evident

**Context visibility at the epoch is enforced, not asserted in prose (A1, A3, A4, B2).** This is the study's sharpest risk: `outcome.flip.inclusive_start = true` opens the label window *at* T on `regime_1m`, a **context** stream. If the 1m bar closing at T were visible at T, a flip carried by that bar would be simultaneously readable by `population.direction`/`qualify` and countable as the label — a direct leak. It is not. `research_workflow/host/mux.py:159` releases queued context bars only on the strict predicate `b.ts_init < before_ts`, and `mux.py:186-192` hard-fails every epoch via `assert_epoch_visibility`: `CONTEXT_STREAM_VISIBLE_AT_EPOCH` when a context stream's `visible_through >= T`, `EXECUTION_STREAM_AHEAD_OF_EPOCH` when an execution stream exceeds T. `same_ts: available` is refused at compile time (`mux.py:9`), and the packet declares `same_ts: unavailable` on both streams. The boundary is consequently exact and gap-free: features see 1m state with `ts_init < T`; the label counts transitions from T forward. No overlap, no blind spot. R4 (callback causal order) proves this on real bounded samples.

**1s-before-1m (A1, §17).** The known hazard — a feature reading "the current 1m bar" from a 1s callback — cannot occur here: nq_1s is `execution`/`at_epoch`, nq_1m is `context`/`strictly_before`, and the mux assertion above separates them. Derived 5m buckets are aggregated from completed 1m bars (`tracker.regime_bar.calendar_bucket`, source `nq_1m`) and re-enter through the same `_apply`/`visible_through` bookkeeping (`mux.py:174-182`), so a derived bucket inherits its source stream's `< T` constraint. No independent 5m stream is loaded — §17 satisfied, and A2/B10 with it.

**Forming-5m state fails closed, twice (B2, feature-instance semantics).** The packet's `routing.completed_5m.ready_gate: false` initially reads as an ungated 5m event, but the gate exists inside the tracker: `structural_regime_geometry.py:127-128` returns `FORMING_OR_MISSING_5M_STATE` whenever `five_provenance_close_ts` is `None` or `> checkpoint_ns`, and lines 123-126 refuse without a completed prior 1m *and* prior 5m regime. The same predicate is re-implemented in `can_snapshot` (lines 170-182), which backs the `features.structural_snapshot_ready` term in `population.qualify` — so under-resolved checkpoints are excluded from the population rather than emitted with invented values. `on_5m_gap` (lines 93-97) invalidates 5m state after an incomplete bucket instead of bridging it, matching the mux's "incomplete bucket is discarded when its successor opens".

**Running vs. eventual extremum is armed (B2, B4).** `structural_max_expansion_atr` (line 139) is `direction * (extreme − origin_price) / atr_start`, where `extreme` is the current 1m regime's running high/low updated **only** from completed 1s bars (`on_1s`, lines 59-69) and `origin_price` is frozen from the *prior* completed regime at flip time (line 78). Arming condition = the 1m flip; anchor = a past extremum. It is a running extremum over `[regime_start, T]`, never an eventual one. Likewise `excursion.mfe_atr` in `qualify` is running MFE since regime start — the legitimate class per the outcome guard, not the `mfe_300s`/`max_mfe_atr` post-event class. `leaked_outcome_columns=[]` at preflight concurs.

**Rolling 300s window refuses rather than substitutes (B1, B4, B5, B6, F2, G2, G3).** `rolling_5m_productivity.py:76-90` requires the completed 1s bar at exactly `checkpoint_ns`, the exact anchor at `T−300s`, and all 301 seconds at exact 1s spacing — otherwise `MISSING_COMPLETED_CHECKPOINT_1S` / `MISSING_EXACT_300S_BOUNDARY` / `INCOMPLETE_1S_WINDOW`. Consequences: no `center=True`, no negative lag, no ffill/bfill, no neighbour substitution (docstring lines 3-6), and **a window spanning a session boundary or data gap is dropped, not silently computed across it** — F2 is handled by refusal. Missing bars are neither forward-filled nor silently dropped (G2). This also settles A4: checkpoints coincide with completed 1s bar closes, so the 5s grid is bar-driven, not timer-driven.

**Normalization is strictly past (B7).** Denominators are `current_regime_start_atr` / `atr_start` (ATR frozen at the regime's start, a past event) and `checkpoint_atr` from `regime_1m.atr` — period-14 on completed 1m bars, visible only `< T`, `atr_availability: at_decision_delivery`. `excursion.frozen_atr` is likewise frozen at the flip. No full-dataset statistic enters any feature.

**Temporal separation holds at the boundary (C1, C2, C3).** Year roles are single-use — 2023 tuning only, 2024 dev_oos only, `final_train_validation_years: []`, 2020-2022/2025-2026 prohibited — so the 2023 double-use failure mode this repository has hit before does not occur. Splits are by year, never random. Look-ahead is confined to `target_flip_within_horizon`; features at row *i* are ≤ T and the label is what the model is asked to predict from them. The 300s horizon cannot spill across the 2023→2024 boundary because `SESSION_END` is the top resolution precedence with `session_end_censoring: true`. `partition_reuse.mode: off`. Warmup emits neither candidates nor targets (`candidate_emission: false`, `target_generation: false`), so the 5 priming days cannot enter the population.

**Sessions and data (F1, F3, F4, G1, G4).** Session classification is table-driven from the `NQ_1S_V2_GLOBEX` calendar (digest `e577a361…`, tables: sessions, holidays, gaps, maintenance, rolls, out_of_calendar) — the CME Globex product schedule, not a floor calendar, and not a fixed UTC offset, so DST is handled by named-zone tables. All availability is `completed_bar_ts_init`, i.e. close time, so the RTH gate cannot repeat the `ts_event`-in-an-RTH-gate defect. Roll handling and `.v.0` provenance are R1_NQ's proof; I did not re-derive them. Thin/zero-volume seconds cannot corrupt the rolling window (refused as incomplete); ATR derives from 1m bars.

**H1-H4 — Not applicable.** The outcome kernel is `flip` with `contract: label` and the invariant "label contract has no fill semantics". There is no bracket, no SL/PT, no offline fill simulation; `entry_reference: next_bar_open` is a reference price, not a simulated fill. The repeated `exit_pnl = (sl_px − entry_px) * direction * MULT` defect has no site here.

## Referred to contract-checker

- `chronology.authorized_dates` is one day (2023-03-01) while chronology declares train 2023 / dev 2024 — authorization scope vs. declared partition breadth.
- `random_seed: null` under a `…model_selection.random` protocol — reproducibility / model-integrity declaration.
- Repeated checkpoints per regime (5s grid, `max_age_ns` 30 min) yield overlapping 300s label windows — effective-sample-size and inference matter, not a leak.

## Clean checks

A1-A5, B1-B7, B9, B10, C1-C3, F1-F4, G1-G4 clean. H1-H4 not applicable (label-only flip kernel, no fill semantics). B9 additionally carries Note 1; C3 additionally carries Note 2. Neither blocks.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "rehearsal_checkpoint_norm", "auditor": "lookahead-auditor:004_causal_audit_300a825d", "audited_execution_composite_sha256": "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7", "critical": 0, "warning": 0, "note": 2}
<!-- AUDIT_SUMMARY_V2_END -->

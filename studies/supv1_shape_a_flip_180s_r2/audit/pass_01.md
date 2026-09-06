# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-06 · **Study** `supv1_shape_a_flip_180s_r2` · **Auditor** `lookahead-auditor:002_causal_audit_c3be3994`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (sha256 `5934d282…`, packet_version 2) + the 90-file execution closure it names
**Scope hash** execution composite `ee051527aa24c26591c0ef9f22316e4d2015ce6d752cdd8d8b66ea3356997984` · plan `19a4543583eb` · spec `6afe992b2bcf`
**Gates cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1_NQ, R3_session_table, R5, R8, R9, R10) · tests PASS 110/0 — all at the same composite
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 3

Closure files changed by the study branch against `main`: **none** — the executable surface is `main`'s platform at the audited composite. Source was opened only for four claims the packet cannot prove: flip-kernel window semantics, oracle/runtime agreement on that window, the regime state machine's direction domain, and the sessions-table authority behind `session.dataset`.

## Critical findings

None.

## Warnings

None.

## Notes

### [C2] `research_workflow/host/outcomes.py:266` — `inclusive_start: true` admits zero-lead positives

`started = p.T <= flip_ts` (`outcome.flip.inclusive_start = true`). A `regime_1m` transition stamped exactly at the decision epoch `T` therefore counts as a positive, while the same transition is invisible to the feature snapshot, because `nq_1m` is a context stream with `visibility: strictly_before` and `same_timestamp_rule: "context streams expose events with ts_init < T only"`. The asymmetry runs the safe way — the label may contain an event the features could not see, never the reverse — so this is disclosure, not leakage: a small share of positives is unpredictable by construction and dilutes the positive class. The convention is deliberate and tested (`research_workflow/tests/test_session_end_truncate.py:79`, "a flip AT T is 0s"), and the replay oracle was aligned to it (`research_workflow/target_replay_oracle.py:341-350` documents the prior `T < ts` divergence and now reads the declared value). No train/serve or runtime/oracle divergence remains.

### [F1/F4] `research/datasets/NQ_1S_V2.yaml:4-10` — legacy sessions table predates the Globex calendar authority (adjudicated)

`session.dataset = NQ_1S_V2`, `session.reference_digest = 0db1f14b…`, which is the pre-fix reference build (`schema_version: 2`, no `rules.session_calendar` block). The corrected rebuild exists over **identical tape bytes** — `NQ_1S_V2_GLOBEX` carries the same `logical_digest 9e7aecb7…` but `reference_digest e577a361…`, `schema_version: 3`, and declares the CME Globex equity-index authority plus an override table (`NQ_1S_V2_GLOBEX.yaml:40-44`). The platform now refuses the floor calendar at build time (`FLOOR_CALENDAR_NOT_AUTHORITATIVE_FOR_GLOBEX_FUTURES`) and pins holiday-eve closes at 12:15 CT, not the floor 12:00 CT (`research_workflow/tests/test_globex_calendar_authority.py:47-70`).

Exposure under this contract: `session_end_censoring: true` with `horizon_end_rule: strict` censors any candidate whose 180s horizon crosses `session_close(T)` (`outcomes.py:246, 277-278`). A close stamped 12:00 instead of 12:15 CT would both censor candidates in the last minutes before 12:00 and suppress emission over the real 12:00–12:15 CT tape, on the holiday-eve class of day only (e.g. 2021-11-26 in TRAIN, 2022-11-25 in dev_oos) — a handful of days per partition year, conservative in direction, immaterial to the headline.

**Explicitly adjudicated, so non-blocking:** `research_decision.yaml:5` pins `dataset_id: NQ_1S_V2` and `SPEC.md:8` requires copying the reference study `v2_shape_a_flip_180s` unchanged, because the terminal decision is reconciliation *against that reference*; `research_decision.yaml:15` sets `calendar_reference_parity: common_interval_exact` — exact on the common calendar interval, Globex-only rows enumerated descriptively. The reference ran on the same table, so parity is the point. The currently authorized date `2021-01-05` is a regular full session and is unaffected.

### [F2/G2] `audit_packet_causal.json:466-478` — `GAP` is in the resolution precedence but inert

`max_gap_ns: null`, so no gap rule can fire; `resolution_precedence` still lists `GAP` ahead of `BARRIER_TOUCH`/`HORIZON_EXPIRY`. Consistent with the platform rule that `max_gap` is barrier-only and inert on flip labels, and largely moot here because `SESSION_END` outranks it and RTH-close censoring already bounds every horizon. Residual: an intra-RTH halt inside a 180s horizon resolves on post-halt regime state without a gap censor. The `gaps`/`maintenance` reference tables are declared but not bound to a label rule. Hygiene only.

## Referred to contract-checker

- `model.validation` declares `validation.model_selection.random` with a single `tuning_years: [2021]` (walk-forward folds are empty at `research_workflow/model_selection.py:244-246`), `max_trials: null`, `primary_metric: null` and `arms: []` — binding/completeness of the selection protocol is C4/D, not causal.

## Clean checks

**A1, A2, A5** — every tracker and feature declares `availability: completed_bar_ts_init`; the dataset declares `source_timestamp_semantics: interval_open`, `availability_rule: interval_end`, `ts_init_delta_ns` 1e9 (1s) / 6e10 (1m) (`NQ_1S_V2.yaml:45-58`); 1m is a build-time aggregation with `closed=left,label=left,minute_exists_iff_native_second` (:58) and 5m is `runtime_complete_calendar_bucket` derived from completed 1m (:60-64), never an independent stream — the `catalog_1m_resample_bug` shape cannot occur. **A3, A4** — not applicable: zero study Python (R10), no strategy or timer callbacks; the grid cadence (`every_ns: 5e9` on `nq_1s`) is bar-driven, not a `TimeEvent`.

**B1-B7** — incremental per-completed-bar trackers, no pandas rolling/`center`, no negative lag, no `bfill` (`rules.forward_fill: false`, `native_rows_only: true`); the regime update consumes only the closed bar's c/h/l and its own prior state (`features/trackers/regime_dual_ema.py:80-109`); no `merge_asof`; the only normalizers are the recursive Wilder ATR (:84-92) and `excursion.frozen_atr`, both past-only. **B9** — periods, timeframe, bucket, `progress_gap: 120s` and warmup are all declared; `nq_1m` warmup 14 bars = `atr_period` = `max_warmup_seconds 840`, and warmup emits nothing (`candidate_emission: false`, `target_generation: false`). **B10** — 1m/5m regime geometry is one capability parameterized by bucket; `prior_5m_*` are output aliases, not a second provider.

**C1** — the only forward-looking column is `target_flip_within_horizon`; `rolling_300s_*` and `prior_*_mfe_atr` are past-describing by write site; preflight proved `leaked_outcome_columns=[]`. **C3** — the year-role table is strictly temporal (2021 tuning/TRAIN, 2022 dev_oos, 2023-2026 prohibited); folds are walk-forward by year (`model_selection.py:244-246`) and "random" names the hyperparameter sampler (`model_selection.py:203-241`, `tuning.py:6`), not a row split.

**F1, F3** — session membership and `session_close(T)` come from the per-date sessions table via `close_ns`, not from an open-time gate; timestamps are int64 ns UTC, CT only through the calendar. **F2** — `max_age_ns` 1800s bounds episode age and the close censors rather than spans. **F4** — per-date `close_ns` rows, no fixed UTC offset. **G1** — provenance `databento *.v.0 raw yearly parquet`, `rolls` table present, R1_NQ pass. **G2, G3, G4** — native rows only: a missing second yields no bar rather than a stale one, a minute exists iff a native second exists, so no zero-volume synthetic bar reaches an indicator.

**H1-H4 — not applicable.** The kernel is `flip`: `outcome.arms: []`, `atr: null`, contract `label` with no fill semantics (declared invariant). There is no bracket simulation, no SL/PT price resolution and no `exit_pnl` computation; `entry_reference: next_bar_open` is a label-side reference only.

Verified: the regime domain question behind the flip guard at `outcomes.py:255` — `regime_dual_ema.py:94-107` is sticky (`new_regime = previous` by default, never returns to 0 once set), so `prev_direction not in (-1, 1)` only guards the pre-first-regime state, which cannot produce a candidate (`qualify` needs `age_s >= 120s` and `frozen_atr > 0`). No missed positive is reachable through a neutral hop.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "supv1_shape_a_flip_180s_r2", "auditor": "lookahead-auditor:002_causal_audit_c3be3994", "audited_execution_composite_sha256": "ee051527aa24c26591c0ef9f22316e4d2015ce6d752cdd8d8b66ea3356997984", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->

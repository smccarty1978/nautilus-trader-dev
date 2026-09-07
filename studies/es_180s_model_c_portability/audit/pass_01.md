# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-06 · **Study** `es_180s_model_c_portability` · **Auditor** `lookahead-auditor:002_causal_audit_857890b1`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (sha256 `43852b71…`, packet_version 2) + 90 closure files @ composite `da3d3ab4ee9b`; branch `study/es_180s_model_c_portability` @ `45c6e1e0`
**Gate facts cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1_ES, R3_session_table, R5, R8, R9, R10) · tests PASS 116/0 @ `da3d3ab4ee9b` · controller OK / NEEDS_CAUSAL_AUDIT
**Changed executable surface** none — the study branch changes no closure file against `main`; pass 01 audits the full declared closure.
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 5

## Critical findings

None.

## Warnings

None.

## Notes

### [B9] `features/trackers/host_bindings.py:154,219-239` — excursion extremes miss the regime-start minute
`regime_1m` sets `start_price = bar.open` of the 1m bar whose **close** established the regime
(`:154`), but `RegimeExcursionBinding` resets `highest_high/lowest_low` to `start_price` only when the
`changed` event arrives (`:219-223`) and thereafter updates from 1s bars only (`:230-233`). Because 1s
bars for that minute were already dispatched (§17, 1s-before-1m), extremes inside the regime-start
minute never enter `mfe_atr` / `retained_ratio` / `progress_windows`. This **omits** past information —
it cannot leak future information — so the qualify gate (`mfe_atr >= 1.0`, `retained_ratio >= 0.5`) is
conservative, not optimistic. Disclosure only; it is `main`'s platform behaviour and identical in the
origin study, which is what a portability comparison requires.

### [G2] `features/trackers/host_bindings.py:275-317` — 5m calendar buckets require no completeness
`CalendarRegimeBarBinding` publishes only when a source 1m `ts_init` is an exact multiple of the bucket
(`:306`) and its docstring states "no completeness is required". If the boundary minute does not print,
no 5m bar is emitted and the accumulator carries into the next bucket, producing one wide bar. Past-only
distortion, documented convention, no future information. The dependent features (`prior_5m_*`) are
additionally gated by `can_snapshot`, so an unavailable bucket suppresses the row rather than
substituting a stale one.

### [F2] `research_workflow/host/…` rolling providers — no session-boundary reset on `rolling_300s_*`
The four `rolling_300s_*` aliases are trailing 300s windows over the 1s stream with no declared session
reset (`chronology.windows: []`). Candidates within 300s of the RTH open therefore aggregate whatever 1s
bars precede them. All such bars are strictly past, so this is not look-ahead; per the ETH/RTH rule a
filter on *emission* (`session: RTH`, `censor_session: RTH`) is legitimate while the provider may see
pre-open state. **Not verified:** whether the data plan streams pre-open 1s bars to the providers at all
— the packet does not carry that, and the answer does not change causality either way.

### [G4] `features/trackers/host_bindings.py:591` — 1m dispatch hardcodes `volume: 0.0`
The `completed_1m` dispatch to the feature host sets `"volume": 0.0` unconditionally. Inert for this
study: none of the 13 declared aliases is volume-derived and no `ohlcv_delta` tracker is instantiated. It
would silently zero any future volume feature bound to `completed_1m`.

### [A1] `features/trackers/structural_regime_geometry.py:176` — `can_snapshot` admits `close_ts == T`
The structural readiness gate rejects only `five_provenance_close_ts > checkpoint_ns`, so a 5m bucket
closing exactly at T would pass. The strictly-before invariant for the `es_1m` context stream is enforced
upstream in the mux (proven by `research_workflow/tests/test_host_core.py:36`,
`test_mux_context_stream_visible_strictly_before_epoch`, green in the 116-test run at this composite), so
the equality case is unreachable in this configuration. Defence-in-depth observation, no failure path.

## Verified positives (the checks that mattered here)

- **Label window inclusive at T is safe.** `flip.inclusive_start=true` makes the kernel resolve on
  `p.T <= flip_ts` (`research_workflow/host/outcomes.py:266`; oracle agrees at
  `target_replay_oracle.py:345-350`). A `regime_1m` flip stamped exactly at T is a **1m context event**
  with `visibility: strictly_before` / `same_ts: unavailable`, so it is not delivered before epoch T and
  is genuinely unobservable there. Independently, `regime_1m.age_s >= 120s` in `population.qualify`
  forbids a candidate at a flip instant (age 0). Look-ahead is confined to the label (C1); the label at
  row *i* is exactly what features at row *i* are asked to predict (C2).
- **Running, not eventual, extremum.** `mfe_atr` (`host_bindings.py:242-247`) is a running maximum over
  bars up to T, armed by the 120s age requirement — not the regime's eventual MFE.
- **Derived 5m is aggregated from completed 1m**, never loaded as an independent stream
  (`trackers.regime_bar_5m.inputs.bars.stream = es_1m`), matching §17. `ready_gate: false` skips only a
  *validity* filter on direction/ATR (`host_bindings.py:601-603`); it does not admit a forming bucket —
  completeness is enforced by `can_snapshot` (`structural_regime_geometry.py:170-182`) via the
  `features.structural_snapshot_ready` term in `qualify`.
- **No pandas look-ahead idioms in the closure.** A repo-wide grep for `center=True`, `.shift(-N)`,
  `bfill`, `merge_asof`, `rolling`, `ewm` returns hits only in legacy `backtests/studies/*` and
  `utils/visualizer*.py` — zero inside the 90 closure files (B1, B4, B5, B6).
- **Temporal split.** train 2020-2023 / dev 2024 / prohibited 2025-2026, warmup 5 days before partition
  with `candidate_emission=false` and `target_generation=false`. With `session_end_censoring=true` and
  `SESSION_END` first in `resolution_precedence`, no 180s label window crosses a session — hence never a
  partition or year boundary (C3, F2).
- **Sessions.** `research_workflow/sessions.py:145,168,186-187` builds RTH 08:30–15:15 from the named
  zone `America/Chicago` per calendar day (F3, F4); windows are indexed on `ts_init` close stamps
  throughout the bindings (F1). `session.reference_digest e98b75e5…` equals the recorded
  `ES_1S_V2_GLOBEX` reference digest, and reference-table loading is fail-closed on digest mismatch
  (`sessions.py:228-236`) — the Globex product calendar, not the floor calendar (G1).
- **No bracket simulation exists.** `outcome.contract: "label"`, `kernel: flip`, `atr: null`.
  `entry_reference: next_bar_open` is defined as "OPEN of the first execution bar **strictly after** the
  decision timestamp T" (`research_workflow/entry_references.py:29-31`), and a label contract carries no
  fill semantics (declared invariant; `resolve_entry_reference:57-58` refuses `decision_close` for a
  label). No `exit_pnl = (trigger_px - entry_px)` construction is reachable (H4).

## Referred to contract-checker

- `chronology.authorized_dates` is a single day (2021-01-05) against a 2020-2023 TRAIN declaration, and
  `model.arms` / `model.validation` are empty — deliverable completeness and lifecycle authorization.

## Clean checks

A1–A5 clean (A3, A4 not applicable: host-driven collector, no strategy price lookup and no timer/alert
callbacks). B1–B7 clean (B7 not applicable: LightGBM, no declared scaler or normalization statistic).
B9, B10 clean (`prior_1m_*` / `prior_5m_*` share the timeframe-parameterized
`generic_regime_geometry` tracker — one verified implementation, no per-timeframe duplicate).
C1–C3 clean. F1–F4 clean. G1, G3 clean; G2, G4 clean with the notes above. H1–H3 not applicable (no
offline bracket simulation); H4 clean.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "es_180s_model_c_portability", "auditor": "lookahead-auditor:002_causal_audit_857890b1", "audited_execution_composite_sha256": "da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540", "critical": 0, "warning": 0, "note": 5}
<!-- AUDIT_SUMMARY_V2_END -->

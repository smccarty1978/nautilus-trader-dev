# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-05 · **Study** `supv1_shape_a_flip_180s` (Supervisor V1 validation rerun of the closed
reference `v2_shape_a_flip_180s`)
**Scope** `_work/controller/audit_packet_causal.json` (primary surface); resolved from it:
`research_workflow/host/{mux,strategy,outcomes}.py`, `research_workflow/grammar/compiler.py` (stream roles,
warmup, flip item), `features/trackers/host_bindings.py` (dual-EMA / excursion / calendar-bucket / feature-host
bindings), `features/trackers/{regime_dual_ema,rolling_5m_productivity,generic_arrival,generic_rolling_productivity,
generic_structural_geometry}.py`, `research_workflow/closure_hash.py`, plus `study.yaml`, `compiled_plan.json`,
`audit/{preflight,readiness,frozen_execution_manifest}.json`, `PLATFORM_STATE.json`, and the reference study's
`audit/pass_01.md` / `pass_02.md`.
**Scope hash (audited composite)** `a563bbf1bf954c6836e6af03b60afbfbebc1d150d84cab051930fe6ea747387a`
(matches `audit/frozen_execution_manifest.json` and `readiness.R9_closure_current`)
**Lint** preflight `CLEAR` (8/8 checks, `leaked_outcome_columns=[]`); readiness `PASS`; tests 110 passed / 0 failed
· **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 3

## Checks performed

- **Epoch / stream visibility (A1, A4, B9).** `nq_1s` is `execution`/`at_epoch`, `nq_1m` is
  `context`/`strictly_before` (packet `streams`; assigned at `research_workflow/grammar/compiler.py:215`).
  `StreamMux.ingest` queues every context bar and releases it only before an execution bar with a *strictly*
  later `ts_init` (`mux.py:142-163`), and `assert_epoch_visibility` raises `CONTEXT_STREAM_VISIBLE_AT_EPOCH`
  for `ts >= T` (`mux.py:186-192`), called at every epoch (`strategy.py:272`). The 1m bar closing **at** T is
  therefore invisible to features, qualify and metadata regardless of loader `add_data()` order. The reference
  study's pass_01 warning (1m classified `execution`, correctness dependent on `add_bars_causal_order`) does not
  apply at this composite: it was remediated platform-side (reference recompiled at `c18fe0de`, adjudicated
  FIXED in its pass_02) and I re-verified the mechanism in code rather than inheriting the adjudication.
- **Tracker → epoch ordering (A3, B2).** `HostCore._deliver` updates trackers and routes their events, then
  evaluates epochs, then sweeps the outcome kernel (`strategy.py:209-219`). At epoch T the `excursion` tracker
  has consumed the 1s bar closing at T (legitimate: closed bar, `at_epoch`), while `regime_1m`/`regime_bar_5m`
  hold state through the last 1m bar with `ts_init < T`.
- **Flip timestamps (A1, C2).** `DualEmaRegimeBinding.on_bar` sets `start_ns = bar.ts_init` — bar **close**,
  not `ts_event` — and emits `changed`/`flipped` with that same `start_ns` (`host_bindings.py:140-164`). So the
  label event, the population anchor (`regime_1m.start_ns`) and `age_s = (T - start_ns)/1e9`
  (`host_bindings.py:168-171`) are all close-stamped and consistent. The dual-EMA math itself
  (`regime_dual_ema.py:90-109`) reads only completed-bar high/low/close.
- **Horizon boundary ordering (C1/C2, the non-obvious case).** A flip whose `flip_ts` equals a candidate's
  `flip_end` must resolve POSITIVE, not be swept to NEGATIVE first. Traced: context release happens inside
  `mux.ingest` *before* the execution bar is applied, so `on_flip` (`outcomes.py:254-285`) always runs ahead of
  `_sweep_flip` for the same instant; and `_sweep_flip` only retires on `end < now_ts` (`outcomes.py:466`).
  Boundary is correct in both directions.
- **Censoring is outcome-independent (censored-population trap).** With `session_end_rule=censor`, a candidate
  is CENSORED/`SESSION_END` iff `flip_end > session_close` (`outcomes.py:277-278`, `477-478`, `492-493`) — a
  predicate over T and the session close only, both known at T. No censoring decision reads the realised
  outcome, so the surviving population is not selected on the label.
- **Population qualify (C2, F).** `excursion.frozen_atr/mfe_atr/progress_windows/retained_ratio`,
  `regime_1m.age_s`, `features.structural_snapshot_ready` are all evaluated at T against tracker state built
  from bars at/before T (`strategy.py:270-280`). `excursion` MFE is a **running** extremum measured from the
  regime start price with the ATR frozen at the regime start (`host_bindings.py:208-229`) — past-only, and it is
  used as an *arming gate at T*, not as a proxy for an eventual extremum.
- **Rolling 300s family (B1-B7).** `Rolling5mProductivityTracker` keeps a deque trimmed to `close_ts -
  window_ns`, rejects non-monotonic bars, and refuses to snapshot unless the exact 301-bar `[T-300s, T]` window
  is present and contiguous (`rolling_5m_productivity.py:43-99`). `giveback`/`max_progress`/`retention` describe
  the past only; no `center=True`, no negative shift, no bfill anywhere in the feature path.
- **Arrival / slope (B2, B3).** `GenericArrivalVelocityProvider.velocity` is `(prices[-1] -
  prices[-(lookback+1)]) / (lookback*atr)` over completed 1s closes (`generic_arrival.py:27-33`); ATR comes from
  `regime_1m.atr`, i.e. the last 1m bar strictly before T.
- **Forming vs completed 5m (feature-instance semantics).** `structural_snapshot_ready` refuses a checkpoint
  with no completed prior 1m/5m regime or forming 5m state (`host_bindings.py:616-622`), and the 5m regime bar
  is emitted only at a bucket boundary (`ts_init % bucket == 0`, `host_bindings.py:300-317`) carrying the
  direction *before* that bar was applied. `ready_gate: false` on `completed_5m` only relaxes a
  direction/ATR-validity filter, not a temporal one.
- **Chronology (C3).** train `[2021]`, dev `[2022]`, prohibited `[2023-2026]`, authorized smoke `2021-01-05`;
  `year_role_table` maps 2021→tuning, 2022→dev_oos, rest prohibited — no year serves two roles, tuning is
  TRAIN-internal, warmup emits neither candidates nor targets (`chronology.warmup`).
- **Warmup (E5-adjacent, B9).** `max_warmup_seconds=840` derives from `per_stream_bars` (14×1m ATR period)
  only; `nq_1s` declares 0. The 300s rolling window and 20-bar arrival lookback are not represented there, but
  they cannot silently degrade: the rolling snapshot fails closed on an incomplete window and
  `structural_snapshot_ready` gates emission, and collection runs with `warmup_days=5` ahead of the partition.
- **Session (F1-F4).** Gate is `session_table.in_session(T)` with T close-stamped (`strategy.py:274`), from the
  canonical `build_session_table` — no bespoke time-of-day arithmetic, no fixed UTC offsets. See Note 2 on
  *which* calendar.
- **H.** Not applicable: `contract=label`, `kernel=flip`, `arms=[]` — no fill or bracket-price semantics exist
  in this plan.

## Notes

- **N1 — `inclusive_start: true` admits zero-lead positives.** `outcomes.py:266` resolves POSITIVE when
  `p.T <= flip_ts`, and the compiler hardcodes `inclusive_start: True` (`compiler.py:845-846`). A flip detected
  on the 1m bar closing exactly at T is inside every candidate's window at `time_to_flip = 0s`. This is *not*
  look-ahead — that bar is invisible to the feature surface (`strictly_before`) — but the label mixes
  "predict the flip being revealed right now" with genuine 180s-ahead forecasting. Any lead-time or economic
  reading of the results should report the `time_to_flip_seconds == 0` share separately. Same semantics as the
  reference study.
- **N2 — session table is the superseded floor-calendar build.** `session.reference_digest`
  `0db1f14bfe0f…` (1632 windows, 16 holidays) belongs to the legacy `NQ_1S_V2` id; `PLATFORM_STATE.json` marks
  that id `SUPERSEDED` and records the Globex authority digest `e577a361…` (1636 sessions) as current. No
  leakage follows, but the RTH gate and the `session_close` used for censoring come from the floor calendar,
  whose known divergence is the early-close time (12:00 vs 12:15 CT; 58 early-close sessions dataset-wide). For
  2021–2022 the recorded holiday overrides (2024-03-29, 2025-01-09, 2025-04-18) are out of range, so the
  divergence here is confined to early-close days. Deliberate for this rerun (the reference binds `NQ_1S_V2`);
  it would need re-examination before any *new* research conclusion.
- **N3 — the flip kernel has no gap protection.** `max_gap_ns` is null, and the flip path never consults it in
  any case (`on_flip`/`_sweep_flip` use only session close and horizon). If 1m bars are missing inside RTH, the
  regime tracker cannot update, the flip is detected only at the first bar after the gap, and a candidate whose
  180s window ends inside that gap is stamped NEGATIVE from absence of observation rather than CENSORED — the
  same failure the barrier path explicitly guards against (`outcomes.py:352-357`). Inherited platform behaviour,
  not introduced here. Concrete but unquantified at this stage: if the TRAIN collection shows intra-RTH 1m gaps,
  count NEGATIVE labels whose horizon overlaps one; a non-trivial count makes this a WARNING at the next pass.

## Referred to contract-checker

- Frozen closure (45 files) records binding modules but not the implementation modules they import
  (`features/trackers/regime_dual_ema.py`, `rolling_5m_productivity.py`, `structural_regime_geometry.py`);
  manifest coverage, not causality — I read those three directly, so this verdict does not rest on the freeze.
- A new study binds the `SUPERSEDED` dataset id `NQ_1S_V2`, which `PLATFORM_STATE.json` reserves for sealed
  historical authority — authorization/provenance scope (packet-instructed, see N2).
- `SPEC.md` is unpopulated scaffold boilerplate; `compiled_plan.json`/`study.yaml` are the operative contract.

## Clean checks

A1-A5, B1-B7, B9, B10, C1-C3, F1-F4, G1, G3, G4 clean (G1 not re-derived: dataset build authority, bytes and
digest verified by `readiness.R1_NQ`). G2 — see Note 3. H1-H4 not applicable (label-only contract, no arms).
C4, D, E deliverable/lifecycle scope not examined (contract-checker).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "supv1_shape_a_flip_180s", "auditor": "lookahead-auditor:002_causal_audit_6b6cdc45", "audited_execution_composite_sha256": "a563bbf1bf954c6836e6af03b60afbfbebc1d150d84cab051930fe6ea747387a", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->

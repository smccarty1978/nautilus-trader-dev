# Look-Ahead & Timestamp Audit — Pass 02

**Date** 2026-09-05 · **Study** `supv1_shape_a_flip_180s` (Supervisor V1 validation rerun; `research_decision.yaml`
mandates a verbatim copy of the closed reference `v2_shape_a_flip_180s`, so no feature/tracker/chronology field may
be re-parameterized here)
**Scope** `_work/controller/audit_packet_causal.json` (primary surface, `packet_sha256 9ebe50e8…`); resolved from it:
`research_workflow/host/{mux,strategy,outcomes}.py`, `research_workflow/provider_host.py`,
`features/trackers/{host_bindings,structural_regime_geometry,rolling_5m_productivity,generic_context,
generic_arrival,generic_rolling_productivity,generic_structural_geometry}.py`,
`research_workflow/grammar/compiler.py` (closure walk), plus `study.yaml`, `research_decision.yaml`,
`compiled_plan.json`, `audit/{preflight,readiness}.json`, `PLATFORM_STATE.json`, `_work/controller/status.json`
and the pass-01 report.
**Scope hash (audited composite)** `34a0dab471d851d916b1d973dd986b48cd462c472709017a9ef110717cd58ac5`
— matches `readiness.R9_closure_current` (`current=34a0dab471d8 frozen=34a0dab471d8`), `preflight`,
`status.fingerprints.plan_closure_composite` and the packet. Not stale.
**Lint** preflight `CLEAR` (8/8, `leaked_outcome_columns=[]`) · readiness `PASS` (R1, R3, R5, R8, R9, R10) ·
tests 110 passed / 0 failed · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 4

## Delta since pass 01 (bounded re-audit)

Pass 01 audited composite `a563bbf1…`; this pass audits `34a0dab4…`. `git diff c49d8140..1b411b6f` over
`research_workflow/ features/ backtests/ utils/ research/` touches exactly one execution-closure file:
`research_workflow/grammar/compiler.py`. The change is closure **membership** only — a static, side-effect-free
AST import walk (`transitive_closure_files`, `_static_imports`, `compiler.py:1236-1319`) seeding the collection
stage set. No runtime, tracker, outcome-kernel, mux or session semantics changed, so pass-01's causal traces
remain valid; I re-verified the four load-bearing ones below rather than inheriting them.

The closure grew 45 → **90 files** and now carries the modules that define the label event and every declared
feature (`features/trackers/regime_dual_ema.py`, `rolling_5m_productivity.py`, `structural_regime_geometry.py`) —
the coverage gap pass 01 referred to contract-checker is closed at this composite. I re-checked the runtime's
dynamic loader path (`host/strategy.py:27-29 _load`) against every `"implementation"`/`"provider"` string in
`compiled_plan.json`: all resolve into `features/trackers/{host_bindings,generic_structural_geometry,
generic_rolling_productivity,generic_arrival,generic_context}.py`, each a closure member, and each of their
repo-local imports is a closure member too.

## Prior findings adjudicated

| # | Finding (pass 01) | Status | Evidence |
|---|---|---|---|
| N1 | `inclusive_start: true` admits zero-lead positives | NOT FIXED (carried, still a note) | `outcomes.py:266,279-280` unchanged; context release is strictly-before (`mux.py:154-163`), so a 1m bar closing at T reaches `on_flip` only after the epoch at T, resolving POSITIVE at `time_to_flip = 0` |
| N2 | Session table is the superseded floor-calendar build | NOT FIXED (carried, still a note) | packet `session.reference_digest 0db1f14b…`; `PLATFORM_STATE.json:45-53` still marks `NQ_1S_V2` SUPERSEDED, gap `W-1` status `open` |
| N3 | Flip kernel has no gap protection | NOT FIXED (carried, still a note) | `outcomes.py:444-448,476-480` unchanged: `_sweep_flip` stamps NEGATIVE on `end < now_ts`; `max_gap_ns` is null and never consulted on the flip path |
| Referral | Frozen closure omitted the implementation modules its bindings import | FIXED | 90-file closure at `34a0dab4…` lists `regime_dual_ema.py:222`, `rolling_5m_productivity.py:220`, `structural_regime_geometry.py:221` of the packet's collection stage |

## Critical findings

None.

## Warnings

None.

## Notes

- NOTE: **[B9] `research_workflow/provider_host.py:279-289` — the declared `ema_slope` lookback is inert.**
  `study.yaml:38` declares `{feature: ema_slope, ema_role: short, lookback: 20}` and `compiled_plan.json:895-902`
  records `parameters.lookback = 20` with `status: "verified"`. `ContextAdapter.snapshot` does not consume it: it
  calls the canonical provider with `FROZEN_FAMILY_A_EMA_SLOPE_STEPS = 5` (`provider_host.py:250,288`), so the
  executed value is a **5-step** slope of the midpoint of an α=0.5 EMA pair over completed 1m highs/lows, divided
  by `5 × family_a_atr`, returning `0.0` (not null) below 6 midpoints (`generic_context.py:24-27`). This is
  deliberate frozen-Model-C parity, documented at `provider_host.py:226-244` and pinned by
  `research_workflow/tests/test_provider_host_audit.py:52-70`, and `research_decision.yaml:3` forbids this study
  from re-parameterizing it — hence a disclosure/inherited-limitation note, not a defect. It is causally clean
  (past-only, no negative lag). Consequence to state in any report: `ema_slope` is a 5-bar EMA-midpoint slope, not
  a 20-bar slope. Category sweep done: `ArrivalAdapter` honours the declared `lookback`/`short_lookback`
  (`provider_host.py:206-208`) and `RollingProductivityAdapter` honours the declared `window`
  (`provider_host.py:423,430`); the `family_a_atr` denominator used by all three (`:201,280,449`) *is* declared,
  at `study.yaml:50` / packet `features.snapshot.family_a_atr`. `ema_slope` is the only inert parameter.
- NOTE: **Zero-lead positives (carried N1).** The label mixes "the flip is being revealed at T" with genuine
  180s-ahead forecasting. Not look-ahead — that 1m bar is invisible to the feature surface — but any lead-time or
  economic reading must report the `time_to_flip_seconds == 0` share separately.
- NOTE: **Floor-calendar session table (carried N2).** The RTH gate and the `session_close` that drives censoring
  come from the legacy floor calendar (1632 windows, 16 holidays) rather than the current Globex authority
  (`e577a361…`, 1636 sessions, 58 early closes). Bars are byte-identical; only the reference table differs, and the
  floor calendar's earlier close censors *more*, so no leakage follows. Deliberate for this rerun.
- NOTE: **Flip kernel gap handling (carried N3).** If 1m bars are missing inside RTH, the regime tracker cannot
  update, a flip inside the window is observed only after it, and the candidate is stamped NEGATIVE from absence of
  observation rather than CENSORED — the guard the barrier path has (`outcomes.py:352-357`) and the flip path does
  not. Inherited platform behaviour. Concrete follow-up unchanged from pass 01: once TRAIN collection exists, count
  NEGATIVE labels whose 180s window overlaps an intra-RTH 1m gap; a non-trivial count makes this a warning.

## Checks re-verified this pass (not inherited)

- **Epoch visibility (A1, A4).** `nq_1m` is `role: context` / `strictly_before` and `nq_1s` is
  `execution` / `at_epoch` (packet `streams`). `StreamMux.ingest` releases queued context bars only for
  `b.ts_init < execution_bar.ts_init` (`mux.py:142-163`) and `assert_epoch_visibility` raises
  `CONTEXT_STREAM_VISIBLE_AT_EPOCH` on `ts >= T` (`mux.py:186-192`), called at every epoch
  (`strategy.py:272`) before qualify, features and metadata. The 1m/5m bar closing **at** T is invisible at T
  regardless of loader `add_data()` order — the pass-01 warning carried by the reference study is structurally
  remediated here, not merely conventionally.
- **Epoch ordering (A3, B2).** Trackers ingest the bar, their events route, then epochs evaluate, then the
  outcome kernel sweeps (`strategy.py:196-219`). Grid epochs fire only when `T == bar.ts_init`
  (`strategy.py:258-268`), so a missing 1s bar skips that checkpoint instead of evaluating it against stale state.
- **Label/censoring independence (C1, C2).** Censoring is `flip_end > session_close` — a predicate over T, the
  180s horizon and the session close, all known at T (`outcomes.py:277-278,442-443,477-478`). No censoring branch
  reads the realised outcome, so the surviving population is not selected on the label.
- **Rolling 300s family (B1-B7).** `Rolling5mProductivityTracker` requires the exact contiguous 301-bar
  `[T-300s, T]` window, rejects non-monotonic bars and fails closed with an explicit reason otherwise
  (`rolling_5m_productivity.py:43-99`). `giveback`/`max_progress`/`retention` are past-only; no `center=True`,
  negative shift, `bfill` or full-sample normalization anywhere in the feature path.
- **Prior 1m/5m regime features (B9, forming-vs-completed).** The six `prior_*` aliases come from
  `_completed(...)` over regimes frozen at their completion (`structural_regime_geometry.py:99-111,147,166`), and
  `snapshot` refuses when the 5m provenance close is `> checkpoint_ns` (`:127-128`) or when either prior regime is
  absent (`:123-126`); `on_5m_gap` invalidates rather than bridges (`:93-97`). No forming-5m information reaches a
  declared feature.
- **Chronology (C3), call-by-call.** Only two roles are reachable in phase B: `train/tuning = 2021`
  (`model.validation.tuning_years = [2021]`, `final_train_validation_years = []`) and `dev_oos = 2022`;
  2023-2026 prohibited; smoke authority is the single date 2021-01-05; warmup emits neither candidates nor targets
  (`chronology.warmup`). No year carries two roles.
- **Session/time (F1-F4).** Gate is `session_table.in_session(T)` with T close-stamped (`strategy.py:274`) from
  the canonical table — no bespoke time-of-day arithmetic, no fixed UTC offsets.
- **H1-H4** not applicable: `contract=label`, `kernel=flip`, `arms=[]` — no fill or bracket-price semantics exist.

## Referred to contract-checker

- Lifecycle/outcome/oos/audit stage sets are static lists and are **not** import-walked (only `collection` is,
  `compiler.py:1319-1322`); `governed_controller.py:18,69` imports `research_workflow/workflow_engine.py` and
  `study_spec_compiler.py`, neither of which is in the 90-file manifest — residual manifest coverage of the same
  DEV-03 class, governance scope not causality.
- `compiled_plan.json:895-902` marks the `ema_slope` instance `status: "verified"` while its declared `lookback`
  is not consumed by the bound adapter (see the note above) — verification-claim scope.
- Study binds the SUPERSEDED dataset id `NQ_1S_V2` (`PLATFORM_STATE.json` gap `W-1`, open); packet-instructed and
  deliberate per `research_decision.yaml:5`, authorization/provenance scope.
- `SPEC.md` is unpopulated scaffold boilerplate; `research_decision.yaml`/`study.yaml`/`compiled_plan.json` are the
  operative contract.

## Clean checks

A1-A5, B1-B7, B10, C1-C3, F1-F4, G1, G3, G4 clean (G1 not re-derived: dataset bytes/digest proven by
`readiness.R1_NQ`). B9 — see the `ema_slope` note. G2 — see the carried gap note. H1-H4 not applicable.
C4, D, E not examined (contract-checker scope).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "supv1_shape_a_flip_180s", "auditor": "lookahead-auditor:005_causal_audit_d9c46349", "audited_execution_composite_sha256": "34a0dab471d851d916b1d973dd986b48cd462c472709017a9ef110717cd58ac5", "critical": 0, "warning": 0, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->

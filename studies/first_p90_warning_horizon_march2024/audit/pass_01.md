# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-04 · **Scope** `research_workflow/{grammar/compiler.py, lifecycle_v2.py, host/outcomes.py,
target_replay_oracle.py, external_model_scoring.py}`, `features/trackers/host_bindings.py`,
`research_workflow/provider_host.py`, `research/analysis/diagnostic_ops.py` (existence/DAG only),
`studies/first_p90_warning_horizon_march2024/{study.yaml,research_decision.yaml,compiled_plan.json}`
· **Scope hash (audited composite)** `6e438b9c47c72e2fe0d24c213e5ecfadac4eda76b8e0c8b212c24df707569bc1`
· **Lint** 0 critical / 0 warning (preflight CLEAR, all 8 required checks PASSED, `FORWARD_OUTCOME_GUARD`
PASSED, `leaked_outcome_columns: []`) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 · Note: 2

## Prior findings adjudicated
N/A — pass 1.

## Critical findings
None.

## Warnings

### [derived-input availability] `features/trackers/host_bindings.py:698-705` — the fail-closed
availability refusal in `FrozenExternalModelScorer.score()` is structurally inert for this binding.

`external_model_scoring.py:178-197` computes `available_at_ns = max(latest_input_availability_ts,
evaluation_ts)` and refuses (`EXTERNAL_SCORE_INPUT_NOT_AVAILABLE_AT_CHECKPOINT`) when that exceeds
`checkpoint_ts` — this is the mechanism §20.2 and the packet's `derived.parent_long_score` /
`derived.parent_short_score` availability rule (`"max(inputs) ∪ evaluation"`) point to as the causal
guarantee for the two derived scores. But `FrozenExternalScoreBinding.derive()` calls it with
`availability_ts={n: ts for n in surf}` and `score_evaluation_ts=ts` — i.e. every input's declared
availability *and* the evaluation timestamp are both hard-set to the checkpoint's own `ts`. That
makes `available_at_ns == checkpoint_ts` by construction on every call; the `>` refusal can never
fire, for any input, ever. The comment at line 694-697 argues this is safe because "the row is
already causally gated upstream by Feature System V2 visibility rules" (true today — verified:
`ProviderHost.snapshot()` raises `SnapshotBeforeLatestRuntimeEvent` if `decision_ts` precedes any
already-dispatched event, and every adapter feeding the parent's 13-column ordered surface — arrival,
context/ema, structural geometry, rolling productivity — is driven only through `dispatch()` on
completed bars). That upstream guarantee is real, but it is a *different* mechanism than the one
`external_model_scoring.py`'s docstring (RT-B2) claims is protecting the score ("a score whose
availability lands after checkpoint_ts is refused, not exposed re-stamped as if current") — for this
binding that specific sentence is false; the refusal is a tautology.

**Failure path:** if a future `ordered_feature_surfaces` entry is bound to an adapter that does not
route exclusively through `ProviderHost.dispatch()`/`snapshot()` (e.g. an asynchronous or
multi-stream provider added later, which the module's own docstring anticipates — "a future
asynchronous/multi-stream scorer passes the real, possibly later, timestamp"), a genuinely late
input would silently score as current with no refusal, because this binding never passes the real
per-input availability — it always overwrites it with `ts`. Today, for the two frozen arms actually
bound (`ccd587df…` / `209da0ff…`, all 13 inputs resolved by `ProviderHost`), the upstream guarantee
holds and no wrong number results.

**Smallest fix:** have `FeatureHostBinding` (or the row assembly in `host/strategy.py:317-324`)
surface the per-column availability timestamps it already effectively guarantees (e.g. `T` for every
`ProviderHost`-backed alias, explicitly, not as a documented-but-unenforced assumption) and pass
those real values into `FrozenExternalScoreBinding.derive()` instead of the blanket `{n: ts ...}`,
so a future non-`ProviderHost` input trips the existing refusal instead of relying on a comment.

## Notes

- **Flip kernel has no `max_gap_ns` censoring path.** `LabelOutcomeKernel.on_flip` /
  `_sweep_flip` (`research_workflow/host/outcomes.py:254-282,453-481`) never consult
  `contract.max_gap_ns` — only the barrier-arm path (`on_bar:319-419`) does. This study's outcome
  compiles `max_gap_ns: null` (packet `outcome.max_gap_ns`), so a silent multi-bar data gap inside
  the 28800s flip horizon would resolve NEGATIVE/CENSORED-SESSION_END exactly as if the tape had
  been continuous, with no `GAP` disposition raised. No evidence of an actual gap in March 2024
  NQ RTH data was found or is claimed here; this is disclosure, not a demonstrated defect.
- **`triggering_1s_ts_init: epoch.T`** and **`regime_age_seconds: regime_1m.age_s`** are trivially
  causal (identity / backward elapsed-time), not cross-event elapsed time — checked against the
  "cross-event elapsed time is look-ahead at the earlier event" pattern specifically; both pass
  because they measure time *since* an already-observed event, never *to* a future one.

## Referred to contract-checker
- Population is a declared strict superset of the frozen parent's training population (no
  1800s age cap, no maturity gates in `population.qualify`); `parent_long_score`/`parent_short_score`
  will be evaluated on checkpoints outside the domain the frozen estimators were fit on
  (age > 1800s, or before `running_mfe_atr/new_progress_windows/retained_mfe_ratio` gates are met).
  This is causally sound (verified below) but is a train/serve distribution question (D2) for the
  contract review, not a look-ahead question.

## Clean checks

**Truncate session-end (new capability).** `LabelOutcomeContract.session_end_rule="truncate"`
(`host/outcomes.py:88-91,267-282,453-481,490-495`) correctly bounds the *observation window* rather
than voiding it: a flip at or before `session_close` resolves POSITIVE at its own timestamp; a
candidate reaching the close without one is CENSORED at the close, independent of whether a later
(possibly next-session) flip event eventually arrives via `on_flip`. Confirmed algebraically
consistent with `_sweep_flip`'s bar-driven retirement (same result either path fires first) and with
the independent `target_replay_oracle._replay_flip_condition` (`target_replay_oracle.py:305-381`,
truncates `end` to `session_close_ts` identically). Because `horizon_ns=28800s` exceeds any RTH
session, truncation is always the binding terminal, matching the study's own design note.
`chronology.windows` (new capability): `_window_bounds` (`lifecycle_v2.py:578-592`) is a hard data
boundary with **no** forward lookahead tail (unlike whole-year `_partition_bounds`) and `run_partition`
*refuses* (`WINDOW_OUTCOME_UNRESOLVED`) rather than silently censoring any candidate still pending at
the window edge — correct, since a silent censor at an arbitrary window edge would be indistinguishable
from a real SESSION_END censor. `reconcile` independently checks rows fall inside declared windows
(not just the calendar year), which a whole-year check would miss.

Derived-score causal ordering (aside from the Warning above): `host/strategy.py:317-326` computes
`feats` via `feature_host.snapshot()` and writes them into `row` *before* `derived_bindings.derive(row,…)`
runs, so both derived scores read only the same-epoch causal feature row, never a later one; this
matches the packet's `availability_table` (`visibility: at_epoch`) for both `derived.parent_long_score`
and `derived.parent_short_score`. `TIMESTAMP_CAUSAL_ORDER` (`availability_reference: decision_ts`)
compile-time check already PASSED under `CAUSAL_INVARIANTS` — not re-derived.

Running-extremum metadata: `RegimeExcursionBinding.mfe_atr`/`retained_ratio`/`progress_windows`
(`features/trackers/host_bindings.py:225-266`) are genuinely running quantities updated only on
completed bars via `on_bar()` — `highest_high`/`lowest_low` accumulate monotonically from bars seen
so far, never from a future extreme. Used only as metadata + analysis eligibility filters, never fed
back into `population.qualify` or a feature the frozen models consume — so the population-superset
design cannot leak into what either frozen scorer or `qualify` sees at T.

Declarative `analysis:` (new capability): `_resolve_analysis` (`grammar/compiler.py:1090-1150`)
proves at compile time that every step's `rows`/`inputs` resolve only to `"frame"` or an *earlier*
declared step — a DAG in declaration order that cannot read its own output and, more importantly,
cannot feed forward into collection (analysis runs strictly after collection in the lifecycle; no
code path routes an analysis artifact back into `features`/`population`/`triggers`). All nine
declared steps (`first_p90` … `warning_subtypes`) read only already-collected/already-resolved
columns (`target_flip_within_horizon`, `time_to_flip_seconds`, `observed_seconds`, the metadata
columns, `parent_long_score`/`parent_short_score`) — legitimate post-collection descriptive use of
forward information, not a feature-path leak.

**A1–A5, B1–B10, C1–C3, F1–F4 clean.** G1 (dataset `NQ_1S_V2_GLOBEX`, `*.v.0` convention per R1
readiness check) clean; G3/G4 not applicable (native 1s/1m streams, no resample in the audited path).
H1–H4 not applicable — this is a `kind: label` / flip-only outcome contract with zero barrier arms;
no bracket/fill price resolution exists in this study.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-claude", "critical": 0, "warning": 1, "note": 2, "study": "first_p90_warning_horizon_march2024", "audited_execution_composite_sha256": "6e438b9c47c72e2fe0d24c213e5ecfadac4eda76b8e0c8b212c24df707569bc1"}
<!-- AUDIT_SUMMARY_V2_END -->

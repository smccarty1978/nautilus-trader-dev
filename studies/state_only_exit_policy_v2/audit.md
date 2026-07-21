# Look-Ahead & Timestamp Audit

**Date:** 2026-07-07
**Scope:** COMPLETION-GATE audit of `studies/state_only_exit_policy_v2/` (full pipeline, post-execution).
Files inspected: `base.py`, `audit_prior_results.py`, `reconcile_baselines.py`, `build_state_events.py`,
`build_deterministic_policies.py`, `simulate_state_stops.py`, `run_matched_controls.py`, `exact_replay.py`,
`run_study.py`. Results spot-checked: `final_report.md`, `control_results.parquet`,
`state_stop_metrics.parquet`, `matched_stop_placebo_summary.parquet`, `policy_metrics.parquet`,
`policy_exit_state_attribution.parquet`, `policy_activation_audit.parquet`, `segment_results.parquet`,
`state_at_decision_results.parquet`, `execution_audit.parquet`. Cross-checked against the live test data
via direct Python re-execution of key code paths (not just static reading) where a static read left
ambiguity.

**Auditor:** lookahead-auditor v1

**Prior audit:** `studies/state_only_exit_policy_v2/audit.md` (pre-execution, 2026-07-06) found 2 CRITICAL +
3 WARNING + 4 NOTE. Both CRITICAL findings and the WARNING/NOTE items reported as fixed are verified below.
Full text of the pre-execution report is preserved at the bottom of this file for the record.

## Summary (this completion pass)

- Critical: **0**
- Warning: 5 (2 new, 1 carried-over/still-open, 1 fragile-but-currently-benign, 1 cosmetic)
- Note: 2

**Bottom line: zero CRITICAL findings remain. This study is decision-grade for the STOP verdict as
reported.** The WARNINGs below affect interpretability of secondary breakdowns (segment deltas, one
regression-guard assertion), not the primary paired-delta number or the overall STOP call.

---

## Fix verification (from pre-execution CRITICALs)

### CRITICAL #1 (wrong-path `load_pb_history`) — CONFIRMED FIXED

`base.py:48` now defines `V2_CONTEXT_CACHE = V2 / "cache" / "full_context_features.parquet"` where
`V2 = REPO / "studies/rl_regime_feasibility/contextual_runner_exit_v2"`. `simulate_state_stops.py:65`
(`load_pb_history`) reads `C.V2_CONTEXT_CACHE`. Verified the file exists on disk at that exact path.
`run_matched_controls.py:312` (`train_pb = SS.load_pb_history(train)`) uses the same fixed function.

### CRITICAL #2 (S4 episode-set-membership ordering bug) — CONFIRMED FIXED

`simulate_state_stops.py:204-231` (`s1s4_pnl`, arch=="S4" branch) now compares actual
`observation_time` values (`w_ts` vs `t_ts`, per episode, via `w_first = w_ts.reindex(all_eps).fillna(inf)
<= t_ts.reindex(all_eps).fillna(inf)`) to determine which event genuinely fires first, and routes each
episode to exactly one branch (`ev_w_wins` -> stop simulation, `ev_t_wins` -> market exit via
`C.policy_pnl`) accordingly. Tie-break (`<=`) favors WEAKENING on an exact timestamp tie, which cannot
occur here in practice (a WEAKENING confirmation and a TERMINAL confirmation are structurally distinct
checkpoint events) and is inconsequential either way. Verified the `all_eps`/`reindex`/`fillna(np.inf)`
construction correctly handles episodes appearing in only one of the two event sets (episode-only-in-W:
`t_ts` reindexed to NaN -> inf, so `w_first` is `True`, W wins, correct; episode-only-in-T: symmetric,
correct).

Downstream note: the frozen architecture actually selected on validation is **S3** (`architecture: S3`
in `frozen_stop_config.json`), not S4 — so this fix, while structurally necessary and correctly applied,
was exercised only during the S1-S4 validation grid-search comparison (where it correctly prevents S4
from being artificially favored) and does not directly gate any number in the final report. This is
expected and not a concern; noted only for completeness.

### Previously-reported WARNING fixes — CONFIRMED

- `exact_match_one_seed` (`simulate_state_stops.py:261-312`) now maintains a single `used_donor_episodes`
  set across the ENTIRE seed (not scoped per-bucket), correctly enforcing episode-level (not just
  row-level) donor exclusivity within a seed, with a skip/restore mechanism that only excludes a donor
  episode from being drawn by OTHER real events, never removes it from future eligibility if only
  skipped for being the same episode as the current target. Verified correct by code reading; the
  skip-restore logic is a legitimate greedy-matching pattern (not globally optimal, but not buggy).
- `run_matched_controls.py`: `test_pb` (dead variable) has been removed. `train_pb` remains (used at
  line 322 for `SS.freeze_bucket_edges(train_pb)`) — see NOTE below; this is harmless, not a live bug.

---

## New findings from this completion pass

### WARNING 1 — [Regression-guard integrity] `exact_replay.py:165-183` — the Phase-10 "required
assertion" never actually executes a real cross-check in this run, and is unsound as designed

```python
p1_states = attrib_df[attrib_df.policy == "P1_immediate_terminal"].set_index("episode_id")[...]
p7_states = attrib_df[attrib_df.policy == "P7_session_specific"].set_index("episode_id")[...]
common_eps = p1_states.index.intersection(p7_states.index)
if len(common_eps) > 0:
    ...
    assert bad.sum() == 0, ...
```

`P7_session_specific` fires on **zero** test episodes (`policy_activation_audit.parquet`:
`episodes_signaled=0` for P7; confirmed independently — validation legitimately selected "disabled" for
both RTH and ETH under P7). `attrib_df` therefore has no `P7_session_specific` rows at all (confirmed:
`attrib_df["policy"].value_counts()` does not list P7). `common_eps` is empty, so the entire `if` block —
including the assertion this study's docstring calls "the repair for the bug this study's own
`audit_prior_results.py` confirmed" — is **silently skipped**. No error, no confirmation message, no
signal that the check never ran. `final_report.md`'s `POLICY-SPECIFIC STATE ATTRIBUTION: PASS` header
line is a **hardcoded string literal** in `run_study.py`'s f-string template (not computed from any
check), so the report asserts a verification that did not, in fact, execute in this run.

Separately, the assertion's own logic is unsound and would produce **false-positive failures** if it
were exercised on almost any real pair of policies, because it conflates "attribution correctly
recomputed per policy" with "state must differ whenever decision_ts differs" — the latter is false
whenever a state genuinely persists across two different decision timestamps (e.g. a delayed policy
fires later in the *same* WEAKENING/TERMINAL dwell as an immediate policy). I confirmed this empirically
by substituting a pair that DOES both fire (P2_immediate_weakening vs P4_weak_delay_term_immediate,
4,369 common episodes): for the 4,333 episodes with differing decision_ts, states were **identical in
85.1%** of them (WEAKENING persisting through P4's 45s wait) — i.e. the exact pattern the assertion
treats as `bad` occurs at massive scale for a legitimate, correctly-computed pair. Had P7 fired on any
nontrivial population, this assertion would very likely have raised a spurious `AssertionError` on this
run even though the Phase-10 mechanism is working correctly.

**Independent verification performed in place of the broken check:** I re-derived the Phase-10 merge
logic by hand (positional vs. label-based indexing, dtype of the merge keys) and empirically cross-
checked P2 vs P4 attribution: 100% state agreement when `decision_ts` is identical (36/36), and a
sensible ~15% state-divergence rate when `decision_ts` differs (consistent with genuine state
transitions, not a copy-paste/reuse bug). **The underlying Phase-10 attribution table itself is correct**
— this finding is about the study's own safety net silently not testing what it claims to test, not
about the attribution numbers being wrong.

**Recommended fix (do not apply):** replace the P1-vs-P7 pair with a pair guaranteed to both fire with a
non-trivial overlap (e.g. P2 vs P4, or P1 vs P9), and change the assertion's logic from "state must
differ whenever ts differs" to a genuine existence/correctness check, e.g. directly re-deriving each
attributed row's `smoothed_state_at_decision` from `checkpoint_lookup` by an independent (e.g.
`.apply`/row-wise) lookup for a sample of rows and asserting equality with the merge-produced value —
this tests "the merge grabbed the right checkpoint," which is the actual property that matters, without
being sensitive to legitimate state persistence. Also have `run_study.py` read the actual pass/fail state
from a file written by `exact_replay.py` (e.g. append a line to `provenance_audit.json`) rather than
hardcoding `PASS` in the report template.

### WARNING 2 — [Construct validity / validation-vs-replay inconsistency] Session gating in
`p9_signal`/`session_gated_signal`/`p6_signal` is per-checkpoint (`df["is_rth"]`), not episode-entry-fixed
as the code's own docstring claims

`build_deterministic_policies.py:8-10` states: *"Session/direction attribution is fixed at episode entry
(first checkpoint's is_rth / direction) -- an exact partition, no outcome leakage, matching the
convention already used (and audited clean) in contextual_runner_exit_v3."* This is true for
**direction** (`ep_meta["direction"]` is genuinely computed once via `.groupby("episode_id").first()`),
but **not** true for **session**: `p9_signal` (line 85), `session_gated_signal` (line 69), and the local
`p6_signal`/`p5_signal` helpers inside `main()` all gate on `df["is_rth"] == 1`, which is the
**checkpoint's own, real-time** RTH/ETH flag — not a value fixed at the episode's entry checkpoint. An
episode that enters during one session and is still open when the session boundary is crossed will,
for its later checkpoints, be evaluated under the **other** session's frozen config.

Confirmed empirically: 89 of 5,642 test episodes (1.6%) have more than one distinct `is_rth` value across
their own checkpoints (session-crossing episodes). For P9 specifically, I isolated the "RTH_short"
segment (`ep_rth.first()==1 & direction==-1`, P9's frozen config for this segment is fully disabled:
`{"weak": null, "term": null}`) and found 13 of 793 episodes in this segment have a
`P9_session_x_direction` PnL that differs from E0 (deltas from -$1,005 to +$515) despite the segment's
OWN config being a no-op. Traced one example (`episode_id=1741722660000000000_-1`): enters at
`is_rth=1`, holds ~1,075s, crosses into `is_rth=0` (ETH) before reaching TERMINAL — and while `is_rth=0`,
the *ETH_short* config (`{"weak": 30, "term": null}`, an active intervention) fires, even though this
episode is classified "RTH_short" everywhere in reporting (`segment_results.parquet`,
`state_at_decision_results.parquet`) based on its entry session.

This also creates an internal inconsistency between how P7/P8/P9's parameters are **selected** versus how
the frozen policy is **replayed**: `select_session_grid`/`select_dir_grid` (used on validation) restrict
each candidate signal to an `idx_mask` built from the ENTRY-session episode set (correctly
entry-fixed, matching the docstring), but `p9_signal`/`session_gated_signal` — the functions actually
used to REPLAY the frozen policy in `exact_replay.py`, `simulate_state_stops.py`, and
`run_matched_controls.py` — do not enforce that same restriction. The mechanism used to choose the
frozen parameters is not exactly the mechanism used to apply them.

This is **not** a look-ahead/causality bug (`is_rth` at a given checkpoint is a real-time, causal value —
no future information is used), and it is applied identically on validation and test (so it is not a
train/serve skew in the model sense), and it does not change the primary paired-delta headline (computed
over the whole test population regardless of session) or the overall STOP verdict. But it does mean the
session-segment breakdowns quoted in the final report (`RTH delta: $-0.41`, `RTH E0 RETENTION: USEFUL`,
`ETH delta: $+3.30`) are not a clean measurement of "the frozen RTH-segment config vs the frozen
ETH-segment config" — a small, non-zero fraction of nominally-RTH episodes are partly governed by the
ETH config and vice versa.

**Recommended fix (do not apply):** either (a) compute an episode-level `entry_is_rth` map (analogous to
`ep_meta["direction"]`) and use `df["episode_id"].map(entry_is_rth)` in place of `df["is_rth"]` inside
`p9_signal`, `session_gated_signal`, and the local `p5_signal`/`p6_signal` helpers, so the replay
mechanism matches both the docstring and the validation-selection mechanism, or (b) if per-checkpoint
session gating is actually the intended behavior, correct the docstring and add an explicit caveat to the
segment-reporting sections of `final_report.md` noting that session-crossing episodes are partially
attributed to the "wrong" segment.

### WARNING 3 (carried over from pre-execution audit, still open) — C1/C2 "spell" scope still spans
the whole episode, not a single contiguous state dwell

Re-verified in the rewritten `c2_matched_cross_episode_timing` (`run_matched_controls.py:140`):
`spell_mask = (ep_obs >= spell_start) & (ep_state == state)` has no upper bound at the point the state
first *leaves* `state` — since TERMINAL/WEAKENING are confirmed non-absorbing (see prior audit's
transition-matrix evidence, unchanged this pass), this can still admit a later, unrelated re-entry into
the same state label rather than only the original contiguous spell. `c1_random_in_spell` has the
identical scope (whole-episode `while i < n` loop keyed only on episode boundaries). This is the same
WARNING from the pre-execution audit (not fixed, not worsened by the C2 vectorization — I confirmed the
vectorized rewrite is a faithful, bit-exact reproduction of this same scope, see Verification note
below). It does not affect the reported verdict (C1/C2 are explicitly NOT the comparator used in the
STOP decision; C5 is — see `final_report.md` section 15's own caveat), but remains an open question for
anyone who later wants to cite C1/C2 numbers as strictly same-spell controls.

**Verification note (rewrite correctness, requested explicitly):** I cross-checked the vectorized C2
against an unambiguous brute-force per-event pandas-filter reimplementation (seed 0, first 30 fired
events): all 30 picks matched exactly, including all 8 "no eligible spell candidate -> None" cases. I
also traced the positional-vs-label-based indexing explicitly: `ep_row_pos` (from
`.groupby(...).indices`) and `obs_arr`/`state_arr` form one self-consistent **positional** system (indices
0..len(df)-1 into the sorted `df`); `pool_groups` (from `.groupby(...).groups` on `bkt`, whose index
equals `df`'s index/labels) and all `.loc[...]` accesses form a separate, self-consistent **label-based**
system. The two systems are never cross-indexed against each other (positions are only ever used with
`obs_arr`/`state_arr`/`df.index[...]`; labels are only ever used with `.loc`), so there is no
off-by-one or positional/label mixup in the rewrite.

### WARNING 4 (low-priority, currently benign) — `exact_replay.py:151-152` merges a float64 decision-ts
column against an int64 nanosecond-epoch column

`fired["policy_decision_ts"]` originates from `base.py::policy_exit_info`'s `decision_ts` Series, which
is initialized via `np.full(n, np.nan)` (float64) and later populated with nanosecond-epoch integers —
so the column is float64 even though its values are exact integers. `checkpoint_lookup["observation_time"]`
remains int64. Nanosecond epoch values for this data (~1.7e18) exceed float64's exact-integer range
(2^53 ≈ 9.0e15), so this merge key comparison depends on pandas casting the int64 side to float64 using
the identical rounding as was already applied when `decision_ts` was first populated FROM that same
`observation_time` column. This holds today (checkpoint spacing is 5s = 5e9 ns, vastly larger than the
~256ns rounding granularity at this magnitude, so no false-match risk; and it's literally the same
underlying integer value cast the same way on both sides, so no false-miss risk either — confirmed
`duplicate_checkpoint_rows: 0` and the P2/P4 cross-check above lines up exactly with expectation). Not a
live bug, but fragile: recommend casting both merge keys to `int64` explicitly before merging, so a
future change to checkpoint granularity or to how `decision_ts` is computed cannot silently introduce a
merge-key precision issue.

### WARNING 5 (cosmetic, does not affect the verdict) — `final_report.md` header shows a contradictory-
looking pair of PASS/FAIL lines for the structural stop

`STATE-TRIGGERED STRUCTURAL STOP: PASS` immediately precedes `STOP TIMING VS MATCHED PLACEBO: FAIL`.
These are not actually contradictory — `stop_pass` (line ~238 in `run_study.py`) is a naive check
(`delta_vs_e0 > 0 and delta_vs_immediate_exit > 0`, both true for the frozen S3/rule-B stop) while
`stop_vs_placebo` is the far more decisive matched-placebo test (S3 loses to its own matched placebo in
100% of 50 seeds) — and the overall verdict logic correctly uses `stop_vs_placebo` (not `stop_pass`) in
`hard_fail`, so the STOP verdict is not corrupted by this. But a reader skimming only the header block
could reasonably come away thinking the structural stop "passed," when the more rigorous, decisive test
two lines later says it did not. Recommend removing the naive `STATE-TRIGGERED STRUCTURAL STOP` line
from the header, or relabeling it e.g. `STRUCTURAL STOP (NAIVE, PRE-PLACEBO): PASS` to make clear it is
superseded.

---

## Notes

### [Dead weight, harmless] `run_matched_controls.py:312,322` — `train_pb` computed but its added column
is never read

`train_pb = SS.load_pb_history(train)` merges `pb_max_depth` onto `train`, then only
`SS.freeze_bucket_edges(train_pb)` is called on it — and `freeze_bucket_edges` (`simulate_state_stops.py:
250-258`) does not reference `pb_max_depth` in any of its bucket-edge computations (`age`, `regime_age`,
`mfe`, `giveback`, `atr`). Harmless (plain `train` would work identically), but the merge and its
`assert len(merged) == len(period_df)` cost are unnecessary here. Low priority.

### [Consistent with prior audit's residual note] Row-order invariant in `base.py::load_base()` remains
unguarded

Same as previously noted: no explicit sort/assert on `(episode_id, observation_time)` monotonicity in
`load_base()`. Re-spot-checked this pass (via the P2/P4 empirical cross-check, which depends on this
invariant holding) — confirmed currently holding. Still an unguarded dependency for a future upstream
cache rebuild; recommendation unchanged from the pre-execution audit.

---

## Clean checks (this pass, in addition to those already listed in the pre-execution audit)

- `base.py::V2_CONTEXT_CACHE` resolves to an existing file; `load_pb_history` calls in both
  `simulate_state_stops.py` and `run_matched_controls.py` succeed (pipeline ran to completion,
  confirming this at runtime, not just via static path inspection).
- `simulate_state_stops.py` S4 fix: verified the `w_first`/`reindex`/`fillna(np.inf)` construction
  handles episode-only-in-one-event-set cases correctly; frozen architecture is S3, so this fix (while
  correctly applied) only actually influenced the S1-S4 validation comparison in this run, not any final
  reported number.
- `exact_replay.py` Phase-10 vectorized merge: independently reverse-derived and confirmed correct via
  (a) explicit positional-vs-label-based indexing trace, and (b) empirical P2-vs-P4 attribution
  cross-check (100% agreement at identical decision_ts, ~15% legitimate divergence at differing
  decision_ts).
- `run_matched_controls.py` C2 vectorized rewrite: confirmed bit-exact against a brute-force per-event
  pandas-filter reimplementation for the first 30 fired events at seed 0 (all picks, including "no
  candidate" cases, matched).
- `execution_audit.parquet`: all 11 checks pass, including `duplicate_checkpoint_rows: 0` (a
  precondition the Phase-10 merge's correctness argument above depends on) and
  `post_exit_positioned_rows: 0`.
- `final_report.md` numeric claims cross-checked directly against `policy_metrics.parquet`,
  `segment_results.parquet`, `state_at_decision_results.parquet`, `matched_stop_placebo_summary.parquet`,
  and `control_results.parquet` — all consistent (P9 paired delta $+2.24 CI (-5.11,9.78), top-decile
  delta $-245.0/retention 0.830, tail `drop_top5` $-1.40, C5 beats real policy in 88% of seeds, S3 stop
  loses to matched placebo in 100% of 50 seeds). The STOP verdict's `hard_fail` logic was traced
  line-by-line and is correctly triggered by at least three independent predeclared criteria
  (`top_decile_damage_fails_hard`, `state_timing_pass=="FAIL"`, `stop_vs_placebo=="FAIL"`,
  `tail_dependent`), so it is robust to any single one of these being disputed.
- `audit_prior_results.py` / `reconcile_baselines.py`: both are read-only diagnostic/reconciliation
  scripts against `contextual_runner_exit_v3`'s artifacts; reasoning and reconstructions checked for
  self-consistency, no causality concerns found (both explicitly reconstruct OLD/broken logic in
  clearly-labeled local functions for comparison only, never feeding into any live policy).
- `build_state_events.py`: Phase 1/2 diagnostic-only outputs (stability metrics, transition atlas);
  confirmed causal throughout (`build_event_atlas`'s retrospective fields are explicitly documented and
  segregated from the causal fields; `pnl_exit_Ns` correctly falls back to E0 when the offset target
  would fall past the episode's true terminal).

---

## Overall verdict on decision-grade status

**Zero CRITICAL findings remain.** Both previously-found CRITICALs are confirmed fixed and were verified
via direct code re-execution against live data, not just static reading. The two rewritten functions
(`c2_matched_cross_episode_timing`, Phase-10 attribution merge) were independently verified correct via
brute-force cross-checks against the actual test data, not just code review. The 5 WARNINGs above affect
interpretability of secondary breakdowns (session-segment deltas, one regression-guard assertion, one
merge-key dtype, one cosmetic header ordering) but do not change, and are not implicated in, the primary
paired-delta number, the CI, the top-decile damage, the tail-dependence check, or the C5/matched-placebo
comparisons that jointly drive the reported **STOP** verdict. The STOP verdict is decision-grade as
reported.

Recommend (not blocking): fix WARNING 1's assertion (replace the vacuous P1-vs-P7 pair and its unsound
logic) and WARNING 2 (entry-fix session gating or correct the docstring) before this pipeline is reused
as a template for a future study, since both are latent correctness/interpretability traps that happened
not to bite this run's headline numbers but could bite a future one with a different frozen config.

---

*Audit complete. Findings reflect a combination of static analysis and targeted dynamic re-execution
against the actual frozen test data (Python re-runs of `p9_signal`, `policy_exit_info`, the C2 matching
logic, and the Phase-10 merge, cross-checked against brute-force reimplementations and against the
persisted parquet/json results). Scope hash: sha over the 9 in-scope .py files + 11 spot-checked results
files as of 2026-07-07 00:19 (final_report.md mtime).*

---
---

# APPENDIX: Pre-execution audit (2026-07-06, preserved verbatim for the record)

# Look-Ahead & Timestamp Audit

**Date:** 2026-07-06
**Scope:** Pre-execution audit of `studies/state_only_exit_policy_v2/`:
  - `base.py` (shared infra, read-only reuse of `contextual_runner_exit_v3` artifacts)
  - `build_deterministic_policies.py` (Phase 3/4, already run once)
  - `simulate_state_stops.py` (Phase 5/6 -- MAIN FOCUS, not yet run)
  - `run_matched_controls.py` (Phase 7, not yet run)

Cross-referenced against: `contextual_runner_exit_v3/base.py`, `.../simulate_structural_stops.py`,
`contextual_runner_exit_v2/build_full_mtf_context.py`, `exit_optimal_stopping/repair/sim_v2.py`,
and the already-produced `studies/state_only_exit_policy_v2/results/state_transition_matrix.parquet`
(used to empirically verify a state-machine assumption below).

**Auditor:** lookahead-auditor v1

## Summary

- Critical: 2
- Warning: 3
- Note: 4

## Critical findings

### [G/pathing, blocking] `simulate_state_stops.py:61-68` -- `load_pb_history` points at a file that does not exist

STATUS: FIXED (verified above). See original description in git history / prior version of this file.

### [Causality, S4 architecture] `simulate_state_stops.py:204-224` -- "already resolved by WEAKENING" check uses episode-set membership, not chronological order

STATUS: FIXED (verified above).

## Warnings

### [Statistical independence] `simulate_state_stops.py:254-293` -- `exact_match_one_seed` de-duplicates donors at the row level, not the episode level

STATUS: FIXED (verified above).

### [Construct validity] `run_matched_controls.py` C1 (`c1_random_in_spell`) and C2
(`c2_matched_cross_episode_timing`) do not bound selection to a single continuous state dwell ("spell")

STATUS: STILL OPEN (see WARNING 3 in the completion-gate section above).

## Notes

### [Defensive coding] Unasserted row-order invariant in `base.py::load_base()`

STATUS: STILL OPEN, low priority (see Notes in the completion-gate section above).

### [Dead code] `run_matched_controls.py:287-288` -- `train_pb`/`test_pb` computed but never used

STATUS: PARTIALLY FIXED (`test_pb` removed; `train_pb` remains, harmlessly — see Notes above).

### [Methodology] Staged (not joint) grid search for stop geometry + architecture in
`simulate_state_stops.py::main()`

STATUS: unchanged, informational only, not a bug.

### [Surfaced by grep sweep, confirmed clean] `build_state_events.py:74` -- `.shift(-1)` on
`transition_confirmed`

STATUS: unchanged, confirmed still clean/unused by any in-scope signal path.

*(Full "Clean checks" list from the pre-execution pass is superseded by, and consistent with, the
completion-gate "Clean checks" section above; not repeated here to avoid duplication.)*

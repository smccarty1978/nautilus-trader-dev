# Look-Ahead & Timestamp Audit — RE-AUDIT

**Date:** 2026-07-06
**Scope:** studies/rl_regime_feasibility/contextual_runner_exit_v3/{base.py, smooth_regime_states.py,
build_policy_candidates.py, simulate_structural_stops.py, run_controls.py, exact_replay.py,
reproduce_baselines.py, run_study.py} plus studies/rl_regime_feasibility/exit_optimal_stopping/repair/sim_v2.py.
**Prior report:** `audit.md` (2026-07-06, pre-fix) — 4 CRITICAL, 3 WARNING, 2 NOTE.
**Auditor:** lookahead-auditor v1
**Scope hash (sha256[:16] of concatenated scope files):** `935e53aa65cc6685`

## Summary

- Critical: **1** (newly found this pass — see below; this is a *different* bug than any of the
  original 4, found while verifying the fix to the WARNING item "C7 sampling still keyed on
  truncated-episode row count")
- Warning: 2 (1 new, 1 carried over unaddressed by design)
- Note: 3 (1 new, 2 carried over)

**Verdict: NOT YET decision-grade.** All 4 originally-reported CRITICAL findings are correctly
resolved (verified below). However, this re-audit found a **new CRITICAL** issue in the very control
(`C7_random_intervention`) whose corrected number is now load-bearing for the report's central,
most-quoted finding (`final_report.md` §13: "an unconditional random trigger does about as well as
the carefully-tuned policy"). That finding cannot yet be trusted.

---

## Part A — Verification of the 4 original CRITICAL fixes

### [RESOLVED] Fix #1 — `sim_v2.py` `detect_stop_hit` phantom fill

`exit_optimal_stopping/repair/sim_v2.py:189-213`. Confirmed: the non-gapped branch now calls
`next_1s_open(bars_arr, stop_bar_ts)` and uses that bar's open as the fill price; the gapped branch
still correctly fills at `bar_open` (worse than trigger, correct direction of bias). This is exactly
the recommended fix from the prior report. No new issue introduced — `next_1s_open` uses
`side="right"` so the fill is strictly after `stop_bar_ts`. **Clean.**

### [RESOLVED] Fix #2 — `simulate_structural_stops.py` matched-placebo geometry mismatch

`simulate_structural_stops.py:250-269` (`matched_placebo`). Confirmed: the donor loop now computes
`prior_pb_px` from `pb_ref = getattr(r, "pb_max_depth", np.nan)` and the donor's own `entry`/`atr`/`d`
— line-for-line the same formula as `build_events` line 90 — instead of hard-coding
`struct_lvl` (Stop A's formula) into `prior_pb_low`/`prior_pb_high`. The assert at line 246-247
(`"pb_max_depth" in donor_full.columns`) guards the precondition. Both legs of the real-vs-placebo
comparison now run the identical Stop-B geometry, differing only in which episode/checkpoint arms it.
**Clean.**

### [RESOLVED, with a caveat — new WARNING] Fix #3 — C1/C5 final-episode-duration matching key

`run_controls.py:57-75` (`build_episode_match_table`, `entry_delay_bucket`). Confirmed: the outcome-
correlated `episode_length_bucket` (final survival duration) has been fully removed from the matching
key. The match table now buckets only on `session` (fixed at entry), `direction` (fixed at entry), and
`delay_bucket` (from `entry_delay_bucket`, nominally "seconds from flip to first checkpoint" —
knowable immediately). This eliminates the specific outcome-leak mechanism described in the original
finding. **However**, verified empirically that `entry_delay_bucket`'s input, `df.groupby("episode_id")
["seconds_since_entry"].transform("min")`, is **0 for all 5,642 test-period episodes** (every episode's
first recorded checkpoint is its own entry, i.e. `seconds_since_entry == 0` for 100% of episodes — see
Part B, W1). This means `delay_bucket` is a constant and the "3-key" match described in the docstring
and in the fix changelog is, in practice, only a 2-key match (`session, direction`). This does **not**
reintroduce look-ahead (session/direction are still both causal, fixed-at-entry quantities — no leak),
but it is materially coarser matching than intended, and the resulting C1/C5 numbers (C1 = +$4.45,
C5 = -$1.76, both reported in §13) should be understood as session×direction-matched, not the
richer match the code comments claim. **See WARNING W1 below.**

### [RESOLVED] Fix #4 — C2 run-length leak across mask boundary

`run_controls.py:144-172` (`c2_masked_circular_shift`). Confirmed: `out_score_masked = np.where
(mask_wrapped, thr + 1, out_score)` is computed and passed into `build_p3_signal` **before** `weak`/
`run` are derived — the wrapped (future-derived, via `np.roll`) rows are neutralized to "never weak"
prior to the consecutive-run calculation, exactly as recommended. This mirrors the `fallback_thr`
technique already used correctly in `c1_matched_score_shuffle`. Verified the shift/wrap semantics are
correct: `np.roll(vals, shift)` at position `i < shift` pulls from `vals[n-shift+i]` (a genuinely later
row in the same episode — correctly flagged as `wrap_mask`), and positions `i >= shift` pull from
`vals[i-shift]` (a genuinely earlier, causal value — correctly left unmasked). **Clean.**

---

## Part B — New findings this pass

### CRITICAL: `run_controls.py:244-267` (`c7_random_intervention`) — the per-episode checkpoint draw is still non-causal, and this control is now central to the report's headline interpretation

The WARNING in the prior report ("C7 sampling still keyed on truncated-episode row count") was fixed
at the **episode-selection** level: `intervene_mask = rng.random(len(ep_ids)) < 0.05` now draws one
independent Bernoulli(0.05) per episode, so every episode has an equal chance of being chosen for
intervention regardless of its own survival length. That part is correctly fixed.

But the **within-episode row-selection** step was not fixed, and reproduces the *exact* causality
violation the repo's own `audit_v2_policies.py` diagnosed for v2's superseded C10 placebo:

```python
chosen_rows = (elig_df[elig_df["episode_id"].isin(intervene_eps)]
               .groupby("episode_id", sort=False)
               .apply(lambda g: g.sample(1, random_state=seed).index[0], include_groups=False))
```

`g.sample(1, ...)` draws uniformly from `g` — **the full, already-truncated, retrospective set of every
eligible checkpoint this episode will ever have**. To draw uniformly over that set, you must already
know its size, i.e. how long the episode ultimately survives. This is line-for-line the same critique
`audit_v2_policies.py:127-136` makes about v2's `C10_stop_placebo`: *"requires the complete in-episode
checkpoint set... to exist before the draw... which can only ever see the checkpoints that have
occurred SO FAR."* A genuinely causal random-intervention control must decide fire/no-fire at each
checkpoint **as it streams**, using only information available up to that checkpoint — it cannot
reach into an episode's future to pick "checkpoint 37 of the 40 this episode will eventually have."

There is a second, compounding bug in the same line: `random_state=seed` is the **same literal
constant** passed to `.sample()` on every group. Since pandas' `.sample(n, random_state=seed)`
constructs a fresh `RandomState(seed)` per call, and the drawn index for `n=1` is a deterministic
function of `(seed, len(g))`, this makes the **relative position chosen within an episode a
deterministic function of that episode's own eligible-row count** — not an independent draw at all.
Two episodes with the same eligible-checkpoint count get the identical relative-position draw, every
time. Verified empirically against the actual test-period data (`seed=21`, the default):

```
n intervened episodes: 268
corr(eligible_row_count, chosen_relative_position) = 0.187
episodes sharing an exact-duplicate eligible-row-count with another intervened episode: 59 / 268 (22%)
```

Both defects point the same direction: the checkpoint chosen for the "random" intervention is
correlated with — and in the duplicate cases, literally *fixed by* — the episode's own eventual
survival length, the exact family of leak this repo has repeatedly flagged as CRITICAL elsewhere
(MEMORY.md: `hc_peak_decay_survivor_dead.md`, `schedule_driven_eval_survivor_bias.md`, and this same
study's own now-fixed C1/C5 finding).

**Why this is CRITICAL and not a WARNING here:** the prior report treated C7's oversampling defect as
a WARNING because its observed value (-$4.72/trade) did not show the "control beats every real policy"
inflation signature. That is no longer true. After the user's fix, C7 = **+$6.76/trade**, and it is now
the single number `final_report.md` §13 leans on hardest: *"a fully unconditional random intervention
on 5% of episodes... does about as well as the carefully-tuned P7 policy... this is the important
caution."* If the row-selection mechanism inside C7 is itself biased by (a function of) episode
survival length, this "cautionary" conclusion cannot be distinguished from an artifact of the same
kind the CRITICAL fixes elsewhere in this pass were specifically designed to eliminate. Given how much
interpretive weight §13 places on this exact number, it must be re-verified with a truly causal
mechanism before the report's "state gate does the work, timing doesn't" conclusion is treated as
established.

**Recommended fix (do not apply):** replace the retrospective `groupby().sample(1)` draw with a
streaming, single-pass mechanism that decides fire/no-fire independently at each eligible checkpoint
in chronological order (e.g., a per-checkpoint Bernoulli probability calibrated so the *cumulative*
probability of intervening by any given checkpoint age matches a target rate, with an early-stop
rule once fired) — i.e., mechanically the same style of real-time trigger `simulate_policy_ev` already
uses for every other policy in this codebase, just with a random rather than score-based trigger.
Separately (and regardless of which mechanism is chosen), never reuse one literal `random_state=seed`
across multiple `.sample()`/`.apply()` calls over different groups — derive an independent seed per
group (e.g. `seed_offset + hash(episode_id) % 2**31`) so draws are not aliased to group size. Re-run
C7 and re-check whether the "+$6.76 ~ P3" result persists under a genuinely causal implementation.

### WARNING (new): `run_controls.py:51-54` (`entry_delay_bucket`) — the matching key is degenerate, silently reducing C1/C5's intended 3-key match to a 2-key match

```python
def entry_delay_bucket(df):
    first_age = df.groupby("episode_id")["seconds_since_entry"].transform("min")
    return pd.cut(first_age, [-1, 30, 60, 120, 1e9], labels=False)
```

Verified: `seconds_since_entry.min()` is exactly `0.0` for all 5,642 test-period episodes (every
episode's checkpoint stream starts at its own entry). `entry_delay_bucket` therefore always returns
bucket `0` — it carries no information and does not discriminate donors at all. This is not a
causality problem (unlike the leak it replaced), but it means the C1/C5 fix's intended match key
(`session, direction, delay_bucket`) is, as implemented, just (`session, direction`) — a materially
coarser match pool than the code comments and docstring describe. This should be corrected or the
docstring/report language adjusted to avoid overstating match granularity, since a coarser match pool
increases the chance that C1/C5's donor swap doesn't fully neutralize other (non-duration, non-score)
confounds between episodes.

**Recommended fix (do not apply):** either compute a genuinely discriminating causal proxy (e.g.
elapsed time from the regime-flip event to first *eligible* checkpoint — `MIN_ELIG_S` seconds after
entry — combined with something that actually varies pre-entry, such as time-of-day or minutes since
session open, if a delay-style key is wanted), or drop the `delay_bucket` key entirely and describe
the match as session×direction only.

### WARNING (carried over, unaddressed by design — not requested): `build_policy_candidates.py` multiple-comparisons / validation over-selection

Unchanged from the original report. The frozen policy config still selects roughly nine free choices
sequentially against the same ~2-month validation period before the single frozen combination is
replayed once on test. `P7_state_gated_dir_session`'s test paired delta is now **+$2.73/trade** (final
report §6), still inside the "conditional pass, CI straddles zero" band the prior report flagged as
fragile relative to the number of validation-set choices behind it. No code change requested; carried
forward as context for interpreting §15's verdict.

---

## Part C — Verification of item (c): `_episode_groups` vectorized donor-lookup helper

`run_controls.py:97-108`. Compared against the semantics implied by the surrounding callers
(`c1_matched_score_shuffle`, `c5_state_shuffle`):

- `_episode_groups` sorts each episode's rows by `seconds_since_entry` once, up front, and returns
  `(sorted_ages, aligned_values)` per episode — this guarantees the array passed to `np.searchsorted`
  as the "haystack" is genuinely sorted, which is the only correctness requirement `searchsorted`
  needs (the "needle" array, `tgt_ages`, does not need to be sorted).
- The target-side lookup (`tgt_groups_pos`, built from `df.groupby("episode_id").indices`) preserves
  each episode's original row order in `df`. Verified `test` (as returned by `base.prepare_base()`) is
  already fully sorted by `[episode_id, seconds_since_entry]` end-to-end (checked directly against the
  cached `prepared_full.parquet` — monotonic for all 619,546 rows), so `tgt_ages` extracted via
  positional indexing is itself already age-ordered, though the lookup does not actually depend on that
  (searchsorted only needs the donor side sorted).
- Donor selection per target row (`pos = np.searchsorted(d_ages, tgt_ages, side="left"); pos =
  np.clip(pos, 0, len(d_ages)-1)`) reproduces "nearest donor checkpoint at or after the target's own
  age, clipped to the donor's last available age" — the same nearest-available-age alignment described
  in the (already-verified-clean) prior audit's donor-matching finding, just computed via one grouped
  pass instead of a per-episode DataFrame filter.
- No future information crosses episodes in either direction: each donor's own `(age, value)` pairs are
  entirely its own, causally-observed history: nothing about the *target* episode's future informs
  which donor row is picked (the donor is chosen by `matched_donor_map`, a fixed pre-registered mapping
  keyed only on session/direction/delay-bucket, independent of any outcome).

**Conclusion: `_episode_groups` is a faithful, non-lookahead-introducing vectorization of the original
per-episode lookup.** The one caveat is the degenerate `delay_bucket` noted above, which affects the
*match key*, not this lookup mechanism.

---

## Notes

### [new] `run_controls.py`'s `c2_masked_circular_shift` relies on an unasserted sort-order invariant for `S_flag` alignment

`c2_masked_circular_shift` does `df = test.copy(); df = df.sort_values(["episode_id",
"seconds_since_entry"])` and then calls `build_p3_signal(df, ..., S_flag)`, where `S_flag` was computed
once in `main()` against the *original* `test` ordering and is aligned by raw `.values`, not by index,
inside `state_gated_signal`. This is currently safe only because `test` (as returned by
`prepare_base()`) is already fully sorted by `[episode_id, seconds_since_entry]`, so the internal
re-sort in `c2_masked_circular_shift` is a no-op and row order is preserved — verified directly. If a
future change to `prepare_base()` or its upstream sort chain ever changed that invariant, `S_flag`
would silently misalign to `df`'s rows with no error raised. Recommend an explicit assertion (e.g.
`assert (df.index == test.index).all()` after the sort, or better, pass `S_flag` reindexed to `df` at
the point of use) rather than relying on an implicit, unstated ordering guarantee shared across two
files.

### [carried over] merge-assert asymmetry — `simulate_structural_stops.py` vs `exact_replay.py`

Unchanged from the original report; still just a defensive-coverage inconsistency, not a causality
issue.

### [carried over] coarse `len_bucket` also used for report-only fallback — `build_policy_candidates.py:274-277`

Unchanged from the original report.

---

## Clean checks (reconfirmed this pass, plus new)

- **Fix #1-#4** — all four originally-reported CRITICAL findings are correctly resolved as described
  by the user, verified by direct code reading (see Part A). No new causality issue was introduced by
  any of the four specific edits themselves.
- **`sim_v2.next_1s_open` / `regime_exit_fill`** — unchanged, still `side="right"`, still strictly
  post-decision fills.
- **`matched_placebo` (`simulate_structural_stops.py`)** — donor `structural_low_high` and
  `prior_pb_px` both now use only the donor's own, causally-observed-at-that-checkpoint inputs; no
  cross-contamination between the real event's geometry and the donor's.
- **`build_episode_match_table` / `matched_donor_map`** — session and direction keys are both fixed
  at episode entry (causal); `matched_donor_map`'s `rng` is a single evolving generator across groups
  (not reseeded per group), so no aliasing artifact there (contrast with the C7 bug above, which is
  specific to `c7_random_intervention`'s literal seed reuse).
- **`_episode_groups`** — verified a faithful, causal-semantics-preserving vectorization (Part C).
- **`smooth_regime_states.py`, `build_policy_candidates.py`, `exact_replay.py`,
  `reproduce_baselines.py`, `base.py`** — re-read in full this pass; no new look-ahead, timestamp
  misuse, or train/serve-skew issues found beyond what's listed above. `build_policy_candidates.py`'s
  dead test-period computations (prior WARNING) are confirmed removed, replaced with an explicit
  comment recording why (`build_policy_candidates.py:131-136`).
- **Ghost-row / truncation / post-terminal invariants** (`base.py:283-288`, `exact_replay.py:204-215`)
  — still asserted zero, still hold after the pipeline rebuild.
- **Final report's section 13 narrative honesty** — confirmed the report text itself accurately
  reflects the control_results.parquet numbers (C1=+4.45, C2=+9.09, C3 family, C4 oracle-quarantined,
  C5=-1.76, C6=-1.09, C7=+6.76, REFERENCE_P3=+0.30) and does not overstate or cherry-pick — the
  reporting layer is faithful to the (currently still-suspect, per the new CRITICAL above) underlying
  C7 number.

---

*Audit complete. This re-audit confirms all 4 originally-reported CRITICAL findings are correctly
fixed. However, it identifies ONE NEW CRITICAL finding in `c7_random_intervention`'s within-episode
row-selection mechanism, which is now load-bearing for the final report's central §13 conclusion, plus
one new WARNING (degenerate `delay_bucket` matching key). Per CLAUDE.md's audit gate: this study is
**NOT YET decision-grade**. The new CRITICAL must be addressed (or explicitly waived by the user) and
this scope re-audited before `final_report.md` §13's "random intervention performs about as well as the
tuned policy" conclusion — and any verdict derived from it — is treated as trustworthy.*

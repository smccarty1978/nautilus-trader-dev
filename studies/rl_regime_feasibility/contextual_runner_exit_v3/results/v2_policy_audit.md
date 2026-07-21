# V2 Policy-Activation Audit

## 1. P2 / P4 / P7 bit-identical -- CONFIRMED, root cause found

- P2 == P4 bit-identical: **True** (changed episodes vs parent: 0)
- P2 == P7 bit-identical: **True** (changed episodes vs parent: 0)
- Rows with local_weak=True AND state in {PROLIFIC_EXPANDING, HEALTHY_ESTABLISHED}: **0** (test period)

### state x local_weak crosstab (test period)
| state | local_weak=False | local_weak=True |
|---|---|---|
| PROLIFIC_EXPANDING | 32304 | 0 |
| HEALTHY_ESTABLISHED | 32440 | 0 |
| ORDINARY | 142285 | 112673 |
| WEAKENING | 0 | 195456 |
| TERMINAL | 0 | 104388 |

**Root cause:** build_regime_state_machine.assign_states() requires ~local_weak for BOTH prolific and healthy states, while P2's weakness trigger IS local_weak. So lockout_test = ~state.isin([PROLIFIC,HEALTHY]) is TRUE at every row where the P2 signal can fire -- P4 = P2 & lockout == P2 identically, and P7's stop-branch (armed only when first weakness occurs during PROLIFIC/HEALTHY) can never activate for the same reason, so P7's immediate-exit branch == P2 identically too. This is a logical tautology, not a coincidence -- co-occurrence is exactly zero across every period.

**v3 fix:** Phase 1 smoothing decouples state-at-decision from the instantaneous local_weak flag: the SMOOTHED state persists through raw weakening blips until a transition is confirmed over N consecutive checkpoints (with dwell + asymmetric hysteresis), so a checkpoint can have local_weak=True while the smoothed state is still PROLIFIC_EXPANDING or HEALTHY_ESTABLISHED (the raw transition simply hasn't been confirmed yet). This is what makes P3/P7 state-gating non-vacuous.

## 2. Sequence-shuffle control (C5) was invalid

- v2 reported EV: 38.07  (vs P1_fittedq test EV: 5.19)
- v2's sequence shuffle used `np.lexsort((RNG.random(len(test)), codes))`, an UNRESTRICTED within-episode permutation with no temporal ordering constraint -- any checkpoint's full feature row (including MTF context computed at a later observation_time) can be relocated to an earlier decision slot in the same episode. The resulting EV (+38.07, far above every real policy) is the signature of a permutation control that leaked future information rather than destroying temporal structure. v3's C1/C5 controls (run_controls.py) use only causal, cross-episode matched shuffles or circular shifts with wrapped-observation masking.
- Verdict: INVALID -- superseded by v3 C1 (matched-episode shuffle) and C2 (masked circular shift)

## 3. Random-checkpoint stop placebo (C10) was inflated

- v2 reported Δ vs E0: 35.54
- corr(episode length, n eligible checkpoints) = 0.9844
- v2's placebo drew a uniform random ELIGIBLE checkpoint from the full, already-truncated episode via pandas groupby.sample(), which requires the complete in-episode checkpoint set (i.e. the episode's eventual survival length) to exist before the draw. Episode length and eligible-checkpoint count are perfectly correlated by construction (corr computed above), so the draw implicitly overweights longer-lived (more often favorable / still-alive) episodes relative to a real-time trigger, which can only ever see the checkpoints that have occurred SO FAR. This explains the suspiciously strong +$35.54/trade result. v3's matched placebo (simulate_structural_stops.py) selects a stop-arm checkpoint from a DIFFERENT episode using only causally-available, bucket-matched state (session/direction/age-bucket/regime-age-bucket/MFE-bucket/giveback-bucket/smoothed-state/vol-bucket), never using final episode duration or future stop/recovery outcomes.
- Verdict: INVALID -- superseded by v3 matched_stop_placebo.parquet

## 4. Regime state flicker

- Median transitions/episode: 13.0
- Mean transitions/episode: 19.11378943637008
- Fraction of state spells lasting <=10s: 57.3%
- Fraction of state spells lasting <=30s: 77.3%
- Raw one-checkpoint (5s) state transitions flicker heavily: median 13 transitions/episode, 57.3% of state spells last <=10s. Using this raw sequence directly as a policy trigger (as v2 did for state-gating) is unstable and, combined with the local_weak tautology above, structurally prevents any weakness-triggered policy from ever firing while the raw state reads PROLIFIC/HEALTHY. v3 Phase 1 (smooth_regime_states.py) adds dwell + confirmation hysteresis.

## Summary of required v3 repairs

1. Smooth the raw state sequence with dwell + confirmation hysteresis (Phase 1) so
   state-at-decision is decoupled from the instantaneous local_weak flag used to
   trigger exits -- this is the ONLY way P3/P7-style state gating can be non-vacuous.
2. Replace the unrestricted within-episode sequence shuffle with matched-episode /
   masked-circular-shift controls (Phase 6, C1/C2).
3. Replace the random-checkpoint stop placebo with a causally matched, cross-episode
   placebo that never uses final episode duration or future outcomes (Phase 5).
4. Add `changed_episode_count_vs_parent > 0` assertions for every derived policy
   (Phase 7) so a silently-inactive policy fails loudly instead of reporting.

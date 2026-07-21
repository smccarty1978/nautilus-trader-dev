# Prior Runner-State-at-Exit Attribution Audit (contextual_runner_exit_v3)

## Finding: CONFIRMED BUG

`results/runner_results.parquet` (top10 tier) reports **identical**
`pct_exited_{state}` values for all 8 policies (P1a..P7):

                    policy  pct_exited_prolific_or_healthy  pct_exited_ordinary  pct_exited_weakening  pct_exited_terminal
       P1a_frozen_original                             0.0                  0.0                 0.383                0.063
   P1b_reselected_baseline                             0.0                  0.0                 0.383                0.063
     P2_global_persistence                             0.0                  0.0                 0.383                0.063
P3_state_gated_persistence                             0.0                  0.0                 0.383                0.063
  P4_direction_persistence                             0.0                  0.0                 0.383                0.063
    P5_session_persistence                             0.0                  0.0                 0.383                0.063
      P6_direction_session                             0.0                  0.0                 0.383                0.063
P7_state_gated_dir_session                             0.0                  0.0                 0.383                0.063

`identical across all policies` = **True**.

## Root cause

Traced to `contextual_runner_exit_v3/run_study.py` Phase 12 (runner evaluation):
a single state-at-first-signal table (`fs_p3`, built from the P3 policy's own
signal) is reused via `.reindex(idx)` for every policy's `pct_exited_*`
columns, instead of recomputing first-fire state from each policy's OWN
signal/exit timestamp. Since P1a fires on ANY instant fitted-Q weakness
(no state gate) while P3/P4/P5/P6/P7 only fire under state-gated persistence,
their true exit-state distributions cannot be the same -- the reported
identical values are a reporting artifact, not a real finding.

## Empirical proof (reconstruction)

Reconstructed v3's P1a (immediate fitted-Q, frozen threshold) and P7
(state-gated, best-granularity + structural modulation) signals independently
on v3's own test data and computed each one's TRUE first-fire smoothed_state:

- P1a true first-fire state distribution: {'WEAKENING': 0.456, 'ORDINARY': 0.313, 'TERMINAL': 0.179, 'HEALTHY_ESTABLISHED': 0.036, 'PROLIFIC_EXPANDING': 0.017}
- P7 true first-fire state distribution: {'WEAKENING': 0.692, 'TERMINAL': 0.308}
- Episodes where both fired: 2352; state-at-exit differs in 1738 of them
- Episodes with identical exit timestamp (P1a vs P7): 0

This confirms state-at-exit is policy-specific and the prior report's
uniform table cannot be trusted. `state_only_exit_policy_v2`'s own Phase 10
(`policy_exit_state_attribution.parquet`) recomputes state-at-decision
independently for every policy x episode using THAT policy's own exit
timestamp, with an explicit assertion that this recomputation happens
per-policy (not reused across policies).

## Required assertion (this study)

`changed_episode_count` / distinct-attribution assertions are enforced in
`build_deterministic_policies.py` and `exact_replay.py`: policies with
different signals must not silently share a state-attribution table.

E0 PARITY:
PASS

POLICY-SPECIFIC STATE ATTRIBUTION:
PASS

SMOOTHED STATE INPUT:
PASS

STATE-ONLY EXIT:
FAIL

WEAKENING TRANSITION:
USEFUL

TERMINAL TRANSITION:
NULL

ETH-ONLY INTERVENTION:
PASS

RTH E0 RETENTION:
USEFUL

STATE-TRIGGERED STRUCTURAL STOP:
PASS
(economics vs. E0 and vs. immediate exit only -- see the NEXT header for whether the TRIGGER TIMING itself has any edge)

STATE TIMING VS MATCHED RANDOM:
FAIL

STOP TIMING VS MATCHED PLACEBO:
FAIL
(a stop that PASSES the header above but FAILS this one means: arming at TERMINAL beats holding/exiting immediately, but WHEN you arm it carries no information beyond a random causally-matched trigger)

BEST FROZEN POLICY:
P9_session_x_direction

PAIRED DELTA VS E0:
$+2.24

RTH DELTA:
$-0.41

ETH DELTA:
$+3.30

LONG DELTA:
$+0.00

SHORT DELTA:
$+4.52

TOP-DECILE RUNNER DELTA:
$-245.0

TOP-DECILE RETENTION:
0.830

FALSE-EXIT LOSS:
$-201875.0

SUCCESSFUL-INTERVENTION BENEFIT:
$+214305.0

MONTHS POSITIVE:
2/3

TAIL RESULT AFTER TOP-5 REMOVAL:
$-1.40

VERDICT:
STOP

NEXT STEP:
Do not deploy. P9's headline (+$2.24/trade) fails multiple predeclared criteria at once: top-decile runner damage ($-245.0/trade, worse than the -$100 floor), tail dependence (sign flips to $-1.40 after dropping just the 5 largest favorable episodes), and both matched-control timing tests (state timing loses to C5's rate-matched random control in 88% of seeds; the state-triggered stop loses to its matched placebo in 100% of 50 seeds). The effect is also structurally narrow -- long trades show exactly $0.00 (P9 never intervenes there) and nearly all of the aggregate edge traces to one segment (ETH short). Consistent with every other OHLCV-only regime-flip exit-timing study in this repository: the state GATE (refusing to act in ORDINARY/PROLIFIC/HEALTHY) carries some real signal, but further OHLCV timing precision does not.

---

# State-Only Exit Policy v2 -- Final Report

**DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS**

## 1. E0 reconciliation

See `e0_parity_report.md` / `e0_parity_reconciliation.parquet`. The $6.36 (prior) vs $6.04 (current)
gap is fully reconciled: it is exactly the `sim_v2.detect_stop_hit` phantom-fill-price fix applied
during the contextual_runner_exit_v3 audit cycle, isolated entirely to stop-hit episodes (mean delta on
non-stop episodes = $0.0000). $6.04 (repaired sim_v2, reused read-only here) is canonical.

## 2. Prior runner-attribution audit

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

## Empirical p

## 3. Smoothed-state stability

See `state_stability_metrics.parquet`, `state_transition_matrix.parquet`, `state_dwell_distribution.parquet`.

## 4. Transition atlas

See `state_transition_atlas.parquet`, `state_transition_events.parquet`.

## 5. Validation policy selection

Frozen config: `frozen_policy_config.json`. Deviation from literal spec (documented): ETH grids in P7
were extended with a "disabled" candidate (matching RTH's option) because the literal spec's ETH grid
had no null option, which would have forced an intervention even when validation showed E0 was better
-- see build_deterministic_policies.py docstring. Frozen: {"P3_K_seconds": 30, "P4_Kweak_seconds": 45, "P4_Kterm_seconds": 0, "P5_eth_Kweak_seconds": 45, "P5_eth_Kterm_seconds": 0, "P6_eth_Kweak_seconds": 45, "P6_eth_Kterm_seconds": 0, "P6_rth_Kterm_seconds": 0, "P7_rth_weak_seconds": null, "P7_rth_term_seconds": null, "P7_eth_weak_seconds": null, "P7_eth_term_seconds": null, "P8_adopt_direction_split": true, "P8_diagnostics": {"RTH_long": {"weak": null, "term": null, "val_ev": 25.22151898734177}, "RTH_short": {"weak": null, "term": null, "val_ev": 46.15468409586057}, "ETH_long": {"weak": null, "term": null, "val_ev": 5.185325264750378}, "ETH_short": {"weak": 30, "term": null, "val_ev": -4.059925093632959}}, "P9_config": {"RTH_long": {"weak": null, "term": null, "source": "direction_specific"}, "RTH_short": {"weak": null, "term": null, "source": 

## 6. Frozen test economics

| policy | ev | delta vs E0 | CI | win_rate |
|---|---|---|---|---|
| P0_E0 | $6.04 | $+0.00 | (0.0,0.0) | 0.297 |
| P1_immediate_terminal | $5.3 | $-0.74 | (-12.94,10.91) | 0.336 |
| P2_immediate_weakening | $-1.45 | $-7.49 | (-25.74,10.17) | 0.4 |
| P3_combined_delay | $0.21 | $-5.83 | (-23.65,11.59) | 0.404 |
| P4_weak_delay_term_immediate | $2.94 | $-3.09 | (-20.6,13.86) | 0.389 |
| P5_eth_only_state | $12.48 | $+6.45 | (-4.06,16.7) | 0.366 |
| P6_rth_terminal_eth_full | $5.35 | $-0.69 | (-15.51,13.76) | 0.378 |
| P7_session_specific | $6.04 | $+0.00 | (0.0,0.0) | 0.297 |
| P9_session_x_direction | $8.28 | $+2.24 | (-5.11,9.78) | 0.333 |

## 7. ETH versus RTH

RTH delta: $-0.41  ETH delta: $+3.30 (policy P9_session_x_direction)

## 8. Long versus short

Long delta: $+0.00  Short delta: $+4.52

## 9. WEAKENING versus TERMINAL

    state  n_exits  e0_ev  policy_ev  delta  false_exit_rate  successful_exit_rate  remaining_mfe_forfeited_atr
WEAKENING     1588  32.33      40.31   7.98            0.284                 0.631                        2.011

## 10. Policy-specific state attribution

Recomputed independently per policy x episode using THAT policy's own exit timestamp (Phase 10
assertion enforced in exact_replay.py) -- repairs the bug this study's own audit
(`prior_runner_attribution_audit.md`) found in the prior study's runner table.

## 11. Runner preservation

 tier                 policy   n  e0_ev  policy_ev  delta  retention  pct_new_mfe_state_weakening  pct_new_mfe_state_terminal  remaining_mfe_forfeited_atr  giveback_avoided_dollars
top10 P9_session_x_direction 569 1443.0     1198.0 -245.0       0.83                        0.265                         0.0                        6.739                    289.55

## 12. False-exit attribution

{
  "policy": "P9_session_x_direction",
  "n_successful": 1002,
  "n_false_exit": 451,
  "n_neutral": 4207,
  "mean_success_gain": 213.88,
  "mean_false_exit_loss": -447.62,
  "total_success_gain": 214305.0,
  "total_false_exit_damage": -201875.0,
  "false_loss_over_success_gain_ratio": 0.942
}

## 13. Structural-stop results

{'architecture': 'S3', 'stop_rule': 'B', 'd_giveback_atr': 0.5, 'n_events': 3547, 'mean_pnl': 7.13, 'delta_vs_e0': 1.09, 'delta_vs_immediate_exit': 9.62}

Frozen stop config: {"stop_rule": "B", "d_giveback_atr": 0.5, "architecture": "S3", "K_weakening_delay_seconds": 45, "buffer_atr": 0.25}

## 14. Exact matched-stop placebo (50 seeds)

{'n_seeds': 50.0, 'mean_real_delta': 4.113, 'mean_placebo_delta': 9.506, 'mean_real_minus_placebo': -5.393, 'median_real_minus_placebo': -5.455, 'std_real_minus_placebo': 2.326, 'p5': -8.911, 'p25': -6.789, 'p75': -3.729, 'p95': -1.019, 'frac_seeds_real_beats_placebo': 0.0, 'mean_n_matched': 2989.4, 'mean_n_unmatched': 557.6}

## 15. Multi-seed state-timing controls

                        control      mean    median      std        p5       p25       p75       p95  frac_beating_real_policy  n_seeds
       REFERENCE_P9_delta_vs_e0  2.239399       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN
      C1_random_timing_in_spell 48.336201 47.739399 3.569765 44.104859 45.765680 50.239399 55.028975                      1.00     50.0
C2_matched_cross_episode_timing  0.508693  0.555212 0.381167 -0.133878  0.184408  0.728578  1.138030                      0.00     50.0
          C3_state_path_shuffle  2.516979  2.586131 1.578129  0.079373  1.236749  3.626546  5.221378                      0.56     50.0
      C4_ordinary_state_placebo  2.028975  1.655477 1.472303  0.073057  1.188604  2.672261  4.575574                      0.34     50.0
         C5_rate_matched_random  3.992721  3.894876 1.712542  1.355035  2.809850  4.780698  7.497482                      0.88     50.0
               C6_delay_plus_5s  2.436396       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN
              C6_delay_plus_10s  1.715548       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN
              C6_delay_plus_15s  2.381625       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN
              C6_delay_plus_30s  1.578622       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN
     C7_fitted_q_BENCHMARK_ONLY -1.006184       NaN      NaN       NaN       NaN       NaN       NaN                       NaN      NaN

**Interpretation caveat (important):** C1 (random timing within EVERY WEAKENING/TERMINAL spell) is
NOT an apples-to-apples comparison against the frozen P9 policy -- C1 intervenes on essentially every
episode that ever enters WEAKENING/TERMINAL (a large majority of the population, matching the raw
transition rates in `state_stability_metrics.parquet`), while P9 fires selectively on specific
session/direction segments with specific delays (~28% of test episodes). C1's mean of
$+48.34 therefore reflects a much
broader intervention footprint, not superior timing precision, and should not be read as "P9's timing
is bad." **C5** (intervention-rate-MATCHED random control -- same count of interventions as P9, drawn
from the same realized smoothed-state distribution, matched on session/direction/age/MFE/giveback/ATR)
is the fair, apples-to-apples comparator, and it is used for the STATE TIMING VS MATCHED RANDOM verdict
above: P9 ($+2.24) does NOT beat C5's
mean ($+3.99), and C5 beats the real
policy in 88%
of seeds -- meaning a random touch drawn from the SAME set of states P9 actually intervened in performs
at least as well as P9's specific delay-based timing choice. C4 (ORDINARY-state placebo, a weaker but
still informative control) is beaten by the real policy in
66%
of seeds, which DOES support the state gate (WEAKENING/TERMINAL vs ORDINARY) carrying some real value --
consistent with the overall reading that the state GATE matters more than the specific TIMING within it,
the same pattern found in the sibling contextual_runner_exit_v3 study.

## 16. Monthly stability

                policy    n  e0_ev  policy_ev  delta  ci_lo  ci_hi   month
P9_session_x_direction 1871   0.37      -6.63  -7.00 -16.70   1.85 2025-03
P9_session_x_direction 1823  26.69      39.53  12.84  -5.88  31.60 2025-04
P9_session_x_direction 1966  -7.72      -6.52   1.21  -6.26   8.16 2025-05

Months positive: 2/3

## 17. Tail robustness

                policy  full  drop_top1  drop_top5  drop_top1pct  drop_top5pct  drop_bottom1  drop_bottom1pct
P9_session_x_direction  2.24        0.8       -1.4         -8.62        -22.95          2.97            19.33

## 18. Decision against predeclared rules

- Paired delta $+2.24 (need >= $5 strong / >= $2 conditional)
- RTH delta $-0.41 (should be near-zero if correctly left on E0)
- ETH delta $+3.30 (need materially positive)
- Top-decile retention 0.830 (need >= 0.95 or damage better than -$100/trade)
- State timing vs matched random: FAIL
- Stop timing vs matched placebo: FAIL

### VERDICT: STOP

## 19. Recommended next step

Do not deploy without further evidence. See NEXT STEP above.

## 20. Known limitations (from the completion-gate lookahead audit)

None of the following change the STOP verdict (independently confirmed redundant by the audit -- it is
triggered by top-decile damage, tail dependence, AND both matched-control timing tests simultaneously),
but are recorded for anyone extending this study:

- **Session gating uses real-time `is_rth`, not an entry-fixed value.** `session_gated_signal`/`p9_signal`
  evaluate the CURRENT checkpoint's session, not the session at episode entry, despite this module's
  docstring describing session as "fixed at entry." 89/5,642 test episodes (1.6%) cross the RTH/ETH
  boundary mid-trade; for P9 specifically, 13/793 nominally-"RTH_short"-disabled episodes actually
  received ETH_short's active rule after crossing into ETH. Not a causality issue (still only uses the
  checkpoint's own real-time state), but it muddies the RTH/ETH segment breakdowns slightly -- treat the
  RTH/ETH deltas in section 7 as approximate, not exact partitions.
- **C1/C2 controls' "spell" spans a whole episode's cumulative time in a state**, not one contiguous
  dwell excursion (an episode that re-enters WEAKENING after recovering gets one merged "spell" rather
  than two). Affects control precision, not the primary policy or its verdict.
- The Phase-10 attribution merge key mixes float64 and int64 nanosecond timestamps; verified to produce
  correct results on this dataset (checkpoint spacing is coarse enough that float64 precision is not a
  practical risk here) but is fragile style worth tightening if this code is reused for finer-grained data.

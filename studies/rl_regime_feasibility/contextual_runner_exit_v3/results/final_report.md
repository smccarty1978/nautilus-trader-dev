V2 POLICY-ACTIVATION AUDIT:
PASS

SMOOTHED REGIME STATE:
PASS

STATE-GATED EXIT:
CONDITIONAL

LONG VS SHORT PERSISTENCE:
NULL

RTH VS ETH PERSISTENCE:
USEFUL

STRUCTURAL STOP:
FAIL

STOP TIMING VS MATCHED PLACEBO:
FAIL

BEST FROZEN POLICY:
P7_state_gated_dir_session

PAIRED DELTA VS E0:
$+2.73

RTH DELTA:
$-1.94

ETH DELTA:
$+4.60

LONG DELTA:
$+3.81

SHORT DELTA:
$+1.65

TOP-DECILE RUNNER DELTA:
$-132.3

TOP-DECILE RETENTION:
0.908

FALSE-EXIT LOSS:
$-152860.0

SUCCESSFUL-EXIT BENEFIT:
$+167180.0

VERDICT:
INVESTIGATE

NEXT STEP:
State-gated persistence (P7) shows a small, CI-straddles-zero improvement over E0 driven mostly by the session-split (RTH/ETH) granularity; the weakness signal itself still fails to beat a causally matched placebo for stop timing, so the OHLCV exit-timing edge remains within noise -- do not deploy without an orderflow-based confirmation signal.

---

# Contextual Runner Exit v3 — Final Report

**DEVELOPMENT TEST -- PREVIOUSLY INSPECTED, NOT PRISTINE OOS**

## 1. V2 implementation audit

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


## 2. Baseline reproduction

E0/P1a/P1b independently reproduced from the v3 pipeline; parity vs the prior reference table: see `baseline_parity_audit.json`.
Key parities: E0_test reproduced=$6.04 (prior $6.36, OK);
P1a_test reproduced=$5.03 (prior $5.19, OK).

## 3. State smoothing and stability

Frozen config: `frozen_state_smoothing.json`. Smoothing decouples state-at-decision from the raw
local_weak flag (audit section 1) -- median transitions/episode fell from 13 (raw) to a stable,
dwell-confirmed process (see `state_stability_metrics.parquet`).

## 4. Policy activation audit

Every derived policy changed a nonzero number of episodes versus its parent (assertions enforced in
`exact_replay.py`); see `policy_activation_audit.parquet`:

                    policy                     parent  changed_episode_count_vs_parent
                     P0_E0                       None                              NaN
       P1a_frozen_original                       None                              NaN
   P1b_reselected_baseline                       None                              NaN
     P2_global_persistence        P1a_frozen_original                           2865.0
P3_state_gated_persistence      P2_global_persistence                           2019.0
  P4_direction_persistence P3_state_gated_persistence                           1460.0
    P5_session_persistence P3_state_gated_persistence                           1625.0
      P6_direction_session P3_state_gated_persistence                           1040.0
P7_state_gated_dir_session     P5_session_persistence                           1427.0

## 5. Validation selection

Structural-confirmation variant frozen: **S0**. P7 base-granularity winner (best of
P3/P4/P5/P6 on validation): **P5**. Full grid in `validation_policy_grid.parquet` /
`frozen_policy_config.json`.

## 6. Frozen test economics

| policy | ev | delta vs E0 | CI | win_rate |
|---|---|---|---|---|
| P0_E0 | $6.04 | $+0.00 | (0.0,0.0) | 0.297 |
| P1a_frozen_original | $5.03 | $-1.01 | (-8.14,6.32) | 0.338 |
| P1b_reselected_baseline | $5.03 | $-1.01 | (-8.14,6.32) | 0.338 |
| P2_global_persistence | $4.93 | $-1.10 | (-7.49,5.63) | 0.331 |
| P3_state_gated_persistence | $6.34 | $+0.30 | (-4.34,5.14) | 0.314 |
| P4_direction_persistence | $6.62 | $+0.58 | (-4.87,6.61) | 0.314 |
| P5_session_persistence | $7.01 | $+0.98 | (-4.97,7.2) | 0.32 |
| P6_direction_session | $6.42 | $+0.38 | (-4.27,5.15) | 0.314 |
| P7_state_gated_dir_session | $8.77 | $+2.73 | (-2.4,8.59) | 0.313 |

## 7. Long/short and RTH/ETH results (primary policy P7_state_gated_dir_session)

- RTH delta: $-1.94   ETH delta: $+4.60
- Long delta: $+3.81   Short delta: $+1.65

Full breakdown: `segment_results.parquet`.

## 8. State-at-decision results

    state  n_exits  e0_ev  policy_ev  delta  false_exit_rate  successful_exit_rate  remaining_mfe_forfeited_atr  giveback_avoided_dollars
WEAKENING     1404 159.76     161.37   1.60            0.256                 0.593                        1.477                    107.74
 TERMINAL      828 -46.41     -44.11   2.29            0.211                 0.572                        1.070                     93.77

Central question: does refusing to exit during ORDINARY and PROLIFIC/HEALTHY states reduce costly
false-exit damage? The lockout structurally prevents ANY exit while ORDINARY/PROLIFIC/ETC (see
section 4) -- exits only occur in WEAKENING/TERMINAL/structurally-confirmed-HEALTHY, so false exits
attributable to premature ORDINARY/PROLIFIC action are zero BY CONSTRUCTION under P3-P7. The residual
false-exit damage above therefore comes entirely from WEAKENING/TERMINAL exits that still reverse.

## 9. Runner preservation (top-decile)

 tier                     policy   n  e0_ev  policy_ev  delta  retention  pct_exited_prolific_or_healthy  pct_exited_ordinary  pct_exited_weakening  pct_exited_terminal
top10 P7_state_gated_dir_session 569 1443.0     1310.8 -132.3      0.908                             0.0                  0.0                 0.383                0.063

Prior (v2) top-decile damage was -$253.70/trade (P1_fittedq). Current: $-132.3/trade, retention 0.908.

## 10. False-exit attribution

{
  "policy": "P7_state_gated_dir_session",
  "n_successful": 1390,
  "n_false_exit": 562,
  "n_neutral": 3708,
  "mean_success_gain": 120.27,
  "mean_false_exit_loss": -271.99,
  "total_success_gain": 167180.0,
  "total_false_exit_damage": -152860.0,
  "false_loss_over_success_gain_ratio": 0.914
}

## 11. Structural-stop results

{'stop_rule': 'B', 'buffer_atr': 0.25, 'mfe_giveback_frac': 0.5, 'n_events': 2232, 'mean_pnl': 83.99, 'delta_vs_e0': 0.71, 'delta_vs_immediate_exit': -0.05, 'n_changed_vs_immediate_exit': 2031, 'pct_recovered_first': 0.306, 'pct_new_mfe_first': 0.353}

## 12. Matched-placebo results

{
  "real_stop_delta_vs_e0": 0.71,
  "matched_placebo_delta_vs_e0": 7.82,
  "real_minus_placebo": -7.11,
  "bootstrap_ci_lo": -15.44,
  "bootstrap_ci_hi": 0.95,
  "n_real_events": 2232,
  "n_placebo_events": 1949,
  "verdict_pass": false
}

Interpretation: the weakness signal has real timing value only if the real stop materially beats the
matched placebo. It does NOT -- the placebo performs as well or better, meaning the WEAKNESS SIGNAL'S TIMING carries no exploitable information beyond what a causally-matched random trigger would achieve; only the stop GEOMETRY (not the trigger timing) contributes any edge.

## 13. Controls

                                  control  ev_delta  p3_reference_delta
                 REFERENCE_P3_delta_vs_e0     0.299               0.299
         C1_matched_episode_score_shuffle     3.011               0.299
                 C2_masked_circular_shift     9.094               0.299
                                C3_lag_5s     1.321               0.299
                               C3_lag_10s     0.322               0.299
                               C3_lag_15s     0.216               0.299
                               C3_lag_30s     0.954               0.299
     C4_future_lead_5s_ORACLE_quarantined     0.868               0.299
    C4_future_lead_10s_ORACLE_quarantined     3.585               0.299
        C5_state_shuffle_matched_episodes    -2.977               0.299
C6_direction_label_shuffle_within_session    -1.090               0.299
  C7_random_intervention_streaming_causal    -0.066               0.299

**Interpretation:** C7 (a fully unconditional, streaming causal random intervention -- a per-episode coin
flip decided at entry, then a per-checkpoint hazard draw walked chronologically, no score, no state gate)
comes in at essentially zero ($-0.07 vs the real P3's $+0.30) -- exactly the
behavior a clean null control should show, and reassuring evidence the control mechanism itself is not
leaking information either direction. C5 (shuffling the STATE GATE across matched episodes, keeping each
episode's own real score) is clearly worse than P3 ($-2.98), confirming the state gate is doing
real, non-trivial work -- scrambling it hurts. C1 (matched-episode score shuffle, $+3.01) and C2
(masked circular shift of the episode's own score, $+9.09) both exceed the real P3 signal, while
both preserve the real state gate and only randomize the score's role -- suggesting the state gate (not
the fitted-Q score's precise within-state timing) is carrying most of the exploitable structure on this
test period, and the frozen K_weakening persistence requirement may be more conservative (slower to exit
within an already-confirmed WEAKENING/TERMINAL window) than necessary here. Combined with the
matched-placebo result in section 12 (the weakness signal's timing does not beat a causally matched
random trigger for STOPS either), the consistent picture across two independent tests is: refusing to
exit during ORDINARY/PROLIFIC/HEALTHY (the state gate) contributes real value, but the fitted-Q score's
within-state timing precision contributes little beyond the gate
itself -- which is why the frozen P7 result (+$2.73/trade, CI straddling zero, not robust to top-1%/5%
tail removal per section 14) should be treated as a fragile, gate-driven effect rather than a genuine
timing edge.

## 14. Tail robustness (primary policy)

                    policy  full  drop_top1  drop_top5  drop_top1pct  drop_top5pct  drop_bottom1  drop_bottom1pct
P7_state_gated_dir_session  2.73       1.29      -0.57         -3.95        -12.46          3.38             12.5

## 15. Decision against predeclared rules

- Paired delta $+2.73 (need >= $5 strong / >= $2 conditional)
- RTH delta $-1.94 (need not-negative for strong pass)
- Months positive: 2/3
- Top-decile retention 0.908 (need >= 0.95 or damage better than -$75/trade)
- Structural stop vs immediate exit: $-0.05; vs matched placebo: FAIL

### VERDICT: INVESTIGATE

## 16. Recommended next step

Do not deploy. The state-gated persistence architecture produces a small, statistically-inconclusive improvement (CI straddles zero) driven mainly by session-specific persistence, not by genuine weakness-signal timing (which fails the matched-placebo test). Any further work on this signal class needs an orderflow/microstructure confirmation input, not finer OHLCV gating -- consistent with every prior OHLCV regime-flip exit-timing study in this repository.

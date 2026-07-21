ALL-FLIPS W4 AUC:
NOT BUILT (W0 only, per user-confirmed scope decision 2026-07-11 -- see Scope Note below). W0 AUC (reserved_eval): 0.7926

F2-CONFIRMED W4 AUC:
NOT BUILT (W0 only, same scope decision). W0 AUC (reserved_eval): 0.7933

BEST ALL-FLIPS POLICY:
NONE (zero of 9 tested policies clear EV lift > 0 in both periods)

BEST F2 POLICY:
NONE (zero of 9 tested policies clear EV lift > 0 in both periods)

ALL-FLIPS 2025 EV LIFT:
$0.00 (no policy improves on E0's -$11.92/tr in dev_test_2025; every policy is WORSE, range -$1.41 to -$19.38/tr)

ALL-FLIPS 2026 EV LIFT:
best observed: S7_checkpoint +$40.78/tr vs E0's -$51.98/tr in reserved_eval_2026 -- but this same policy LOSES -$1.41/tr vs E0 in dev_test_2025, failing the both-periods requirement

F2 2025 EV LIFT:
$0.00 (no policy improves on E0's +$13.73/tr in dev_test_2025; every policy is WORSE, range -$8.73 to -$36.87/tr -- note E0 itself is the best result of this whole grid in this period)

F2 2026 EV LIFT:
best observed: S7_checkpoint +$25.00/tr vs E0's -$34.05/tr in reserved_eval_2026 -- but this same policy LOSES -$34.45/tr vs E0 in dev_test_2025, failing the both-periods requirement

ALL-FLIPS RUNNER RETENTION:
best top-decile retention observed 62.4% (S4_mfe/S6_mfe, reserved_eval) -- below the 95% bar required to advance regardless of EV lift

F2 RUNNER RETENTION:
best top-decile retention observed 64.1% (E1, reserved_eval) -- below the 95% bar required to advance regardless of EV lift

BAR1 CONFIRMATION VERDICT:
MIXED -- bar1 confirmation clearly HELPS entry quality (F2's E0 baseline is genuinely profitable in dev_test_2025, +$13.73/tr / +35.1% win rate, vs ALL_FLIPS's E0 baseline which is negative in BOTH periods), but this entry-quality advantage is ORTHOGONAL to the stop-management question: bar1 confirmation does NOT help the stop-management overlay succeed -- both populations show the identical failure pattern (every policy worse in dev_test_2025, better in reserved_eval_2026, none passing both).

WEAKNESS-EXIT BRANCH VERDICT:
CLOSE (under the tested scope: W0 feature family, 9 of 15 policies -- E1, S1, S4, S6, S7 x 2 anchors, S2/S3/S5 deferred for time). See Scope Note and Recommendation below before treating this as a permanent verdict.

---

# Exit Management Population Comparison -- Final Report

Built: 2026-07-13

## Scope Note (read before treating verdicts as final)

Two scope reductions were made during this study, both by explicit user
decision, both driven by wall-clock/compute constraints, not by any
finding that would justify skipping them on their own merits:

1. **W0-only, W1-W4 deferred.** The weakness model uses ONLY the
   "local progress/giveback" feature family (current_pnl_atr,
   mfe_atr, mae_atr, giveback_atr, distance_from_mfe_atr, age_seconds).
   W1 (median-center context), W2 (regime-sequence context), W3, W4
   were never built -- they require ~180 additional features computed
   causally at this study's own checkpoint grid (see
   audit/train_serve_skew_report.md for why the old atlas's
   precomputed features could not be reused). It is possible a richer
   feature set would produce a materially different, more
   discriminating weakness score that could change the stop-management
   results -- this was NOT tested.
2. **9 of 15 policies tested.** S2, S3, S5 (and their MFE/checkpoint
   anchor variants) were deferred; only E1, S1, S4, S6, S7 (each
   x {checkpoint, mfe}) were run, due to a background-process runtime
   limit that made the full grid impractical in this session (see
   studies/all_flips_exit_management/_work/one_chunk_loop.log for the
   chunked-execution workaround this required). S2/S3's persistence
   requirements and tighter arm/tighten thresholds were never evaluated.

Given this, "WEAKNESS-EXIT BRANCH VERDICT: CLOSE" above should be read
as "CLOSE under W0 + the 9 tested policies" -- not as an exhaustive
refutation of every possible variant in the original spec's full grid.

## Which population has stronger corrected W4 discrimination?

Not answerable -- W4 was not built for either population (see Scope
Note). Both populations' W0 models show near-identical, strong
discrimination: ALL_FLIPS reserved_eval AUC 0.7926 (well-calibrated,
slope 1.03, intercept 0.08) vs F2_CONFIRMED reserved_eval AUC 0.7933
(same AUC, but needs recalibration for absolute probabilities -- slope
1.49, intercept 0.28; rank-ordering, which is all Phase 4/5/6 actually
use, is equally strong for both).

## Which population has better stop-policy economics?

Neither. Both show the IDENTICAL qualitative failure: every one of
the 9 tested policies is worse than E0 in dev_test_2025 and better
than E0 in reserved_eval_2026 -- a perfectly consistent sign flip
across periods for every single policy, in both populations. This is
not "F2 is better than ALL_FLIPS at stop management" or vice versa --
it's the same underlying dynamic (the stop overlay reduces variance in
a way that happens to hurt during 2025's trending-favorable conditions
and help during 2026's conditions) showing up identically regardless
of entry population.

## Does bar1 confirmation help or hurt once stop management exists?

Neither, in the sense that matters for stop-management effectiveness
-- see BAR1 CONFIRMATION VERDICT above. It helps the underlying entry
(F2's E0 is profitable in one period, ALL_FLIPS's E0 never is), but a
better baseline does not translate into stop management working better
on top of it -- F2's stop policies still uniformly fail the
both-periods bar exactly like ALL_FLIPS's do.

## Is every-flip trade management viable?

No, under the tested scope. E0 itself loses money in both periods
(-$11.92/tr dev_test, -$51.98/tr reserved_eval), and no stop-management
policy fixes this in both periods simultaneously.

## Is F2-confirmed trade management viable?

Partially, but not because of the stop-management framework tested
here. F2's OWN entry (E0, hold-to-opposite-flip) is profitable in
dev_test_2025 (+$13.73/tr, 35.1% win rate) -- consistent with this
project's prior finding that bar+1 confirmation carries real edge (see
memory: bar1 confirmation filters generally show modest, real signal).
But F2's baseline reverses to a loss in reserved_eval_2026
(-$34.05/tr), and every tested stop-management overlay makes the
profitable period WORSE without reliably fixing the losing period.
Whether F2's baseline alone (E0, no stop overlay) is a viable
standalone strategy is a SEPARATE question this study's Phase 5-8
scope was not designed to answer (it was designed to test whether
weakness-based stop management improves on that baseline, not to
re-litigate the baseline's own standing, which is already covered by
this project's flip2conf_efficiency_filter_candidate and related
memory entries).

## Should weakness exits continue or close?

CLOSE, under W0 + the tested 9-policy grid, for both populations. Two
independent gates both fail cleanly and simultaneously for every
candidate:
- **EV lift > 0 in both periods**: 0 of 18 (9 policies x 2
  populations) pass. Every single one shows the identical
  worse-then-better sign flip across periods.
- **Top-decile runner retention >= 95%**: 0 of 18 pass. Best observed
  is 64.1% (F2, E1, reserved_eval) -- nowhere close to the bar.

Because BOTH gates fail independently and unanimously (not a marginal
miss on one axis), Phase 8's matched placebo controls were not run:
the study's own decision criteria require passing the EV-lift gate as
a prerequisite before placebo significance is even the deciding
factor, and nothing reached that gate to test.

## Recommendation for any future revisit

If this branch is ever revisited, the highest-leverage next step is
NOT re-running the deferred S2/S3/S5 policies (the failure mode looks
structural -- a giveback/stop mechanism fighting favorable-trend
variance -- not a threshold-tuning problem), but building the deferred
W1-W4 feature families to test whether a richer weakness signal
produces a fundamentally different (not just differently-tuned) stop
policy. Absent evidence that richer features would change the
qualitative sign-flip-across-periods pattern, this branch should stay
closed.

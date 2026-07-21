# ALL_FLIPS Exit Management -- Final Report

Built: 2026-07-13

## Scope actually delivered (vs original spec)

- Phases 0-4 (population definition, corrected atlas, train/serve
  skew audit, W0 model, conditional recovery-MAE tables): delivered in
  full per the original spec.
- Phase 3: **W0 only.** W1 (median-center), W2 (regime-sequence), W3,
  W4 deferred by explicit user decision (2026-07-11) given the
  ~180-feature causal engineering effort required -- see
  audit/population_definition.md and the shared skew-audit report for
  why the old atlas's precomputed features could not be reused.
- Phase 5: full 9-policy grid design (E1 + S1-S7 x {checkpoint, mfe}),
  fully audited (4 rounds; see studies/_shared_exit_mgmt/
  audit_phase5_stop_policy.md) -- 3 CRITICAL and 3 WARNING findings
  fixed or explicitly resolved by direct user decision before first
  execution.
- Phase 6: **9 of 15 policies executed** (E1, S1, S4, S6, S7 x 2
  anchors; S2/S3/S5 deferred, user-confirmed 2026-07-12) over both
  2025 dev_test and 2026 reserved_eval, via a chunked NT BacktestEngine
  executor built specifically to work around a background-process
  runtime limit discovered mid-phase (see
  studies/_shared_exit_mgmt/nt_runner.py's run_period_chunked and
  _work/one_chunk_loop.log).
- Phase 7: delivered in full for the 9 tested policies + E0.
- Phase 8: **not run** -- see Decision below.

## Population definition (recap)

Every completed 1m regime flip on NQ, RTH only, one contract, no
confirmation filter. Entry: flip bar closes -> signal known
immediately -> entry scheduled with entry_delay_ns=0 -> filled at next
executable 1s-open. See audit/population_definition.md for the full
causal-chain audit.

## Key findings

1. **E0 baseline is unprofitable in both tested periods**: -$11.92/tr
   (dev_test_2025, 6,193 trades), -$51.98/tr (reserved_eval_2026,
   2,394 trades) -- consistent with this project's established finding
   that every-flip entry (no confirmation) is a structurally weak
   population (see memory: v_a_1m_flip_signal_class_dead.md).

2. **The W0 weakness model is real and well-calibrated**: ROC AUC
   0.790 (dev_test) / 0.793 (reserved_eval), calibration slope
   0.95-1.03, intercept near 0 across all four chronological splits.
   Decile gradient is clean and monotonic (Phase 4: D5 ~67% eventual
   recovery -> D10 ~23%).

3. **No stop-management policy improves EV over E0 in both periods
   simultaneously.** All 9 policies are WORSE than E0 in dev_test_2025
   (range -$1.41 to -$19.38/tr) and BETTER than E0 in
   reserved_eval_2026 (range -$0.13 to +$40.78/tr) -- a perfectly
   consistent sign flip across every single policy. This is not noise
   in one or two policies; it is the uniform pattern.

4. **S6 == S4 exactly**, in every metric, both periods -- confirms the
   Phase 5 audit's prediction that ratchet-only (S6) is mechanically
   redundant once the user-confirmed "never loosen" rule already
   applies to S1-S5 (see stop_policy.py's module docstring).

5. **Top-decile runner retention never exceeds 62.4%** (best: S4_mfe/
   S6_mfe, reserved_eval) -- well below the 95% bar the spec requires
   for a policy to advance regardless of its EV performance.

## Decision

Per the study's own criteria (EV lift > 0 in both periods, top-decile
runner retention >= 95%, both required simultaneously): **no policy
advances.** Both gates fail independently and unanimously across all 9
tested policies -- not a marginal or close call. Phase 8's matched
placebo controls were not run because the spec's decision framework
requires clearing the EV-lift gate as a prerequisite, and nothing
reached it.

**WEAKNESS-EXIT VERDICT FOR ALL_FLIPS: CLOSE** (under W0 + the 9 tested
policies; see the comparison study's Scope Note for what remains
untested and why a future revisit would need richer features, not more
threshold tuning, to plausibly change this).

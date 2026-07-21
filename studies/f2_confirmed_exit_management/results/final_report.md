# F2_CONFIRMED Exit Management -- Final Report

Built: 2026-07-13

## Scope actually delivered (vs original spec)

- Phases 0-4: delivered in full per the original spec, including the
  Phase 2 finding that F2's flip-close-anchored entry proxy (used by
  every prior study referencing this population) understates the real
  entry cost by a median 0.44 ATR/trade -- see
  audit/train_serve_skew_report.md.
- Phase 3: **W0 only**, same scope decision and rationale as
  ALL_FLIPS -- see that study's final_report.md.
- Phase 5: same shared, fully-audited 9-policy grid as ALL_FLIPS (this
  study reuses the population-agnostic stop-policy mechanism, not a
  separate implementation).
- Phase 6: **9 of 15 policies executed**, same reduced scope and same
  chunked-execution infrastructure as ALL_FLIPS (F2's smaller
  checkpoint volume meant this study's Phase 6 runs completed
  substantially faster and with fewer interruptions than ALL_FLIPS's).
- Phase 7: delivered in full for the 9 tested policies + E0.
- Phase 8: **not run** -- see Decision below.

## Population definition (recap)

Bar+1 HH/LL + momentum confirmed 1m regime-flip entries, RTH only, one
contract, **no 30-second delay** (the delayed-activation convention
used by rank_filter_oos_validation/f5_flip_filter_repair was confirmed
by codebase survey to be a deprecated artifact bolted on downstream of
an already-computed no-delay F2 atlas, never part of the confirmation
logic itself). RTH gated only at the flip bar (user-confirmed
2026-07-11), not re-checked at bar+1 confirmation. See
audit/population_definition.md for the full causal-chain audit.

## Key findings

1. **E0 baseline is genuinely profitable in dev_test_2025**: +$13.73/tr
   (2,774 trades, 35.1% win rate) -- real, causal-chain-audited evidence
   that bar1 confirmation carries edge, consistent with this project's
   prior finding for confirmation-filtered entries. But the SAME
   baseline reverses to -$34.05/tr in reserved_eval_2026 (1,114
   trades) -- a real cross-year fragility, not a bug (both periods use
   identical, audited mechanics).

2. **The W0 weakness model is real but needs recalibration for
   absolute probabilities**: ROC AUC 0.785 (dev_test) / 0.793
   (reserved_eval) -- statistically indistinguishable from ALL_FLIPS's
   discrimination -- but calibration slope is 1.4-1.5 (vs ALL_FLIPS's
   ~1.0), meaning F2's raw predicted probabilities understate how
   sharply outcomes actually vary with the score. Rank-ordering
   (deciles), which is all this study's stop-policy logic uses, is
   unaffected by this.

3. **Every stop-management policy makes the ONE profitable period
   worse.** In dev_test_2025 (where E0 = +$13.73/tr), every policy is
   worse: S1_checkpoint +$5.01/tr (best, still a $8.73/tr reduction),
   down to S7_checkpoint at -$20.72/tr (a $34.45/tr reduction). The
   stop overlay cuts winners short faster than it protects against
   losers, specifically in the period where the underlying edge was
   real.

4. **Same worse-then-better sign flip as ALL_FLIPS across periods**
   for every single policy -- this is not an F2-specific failure mode,
   it is the identical qualitative pattern regardless of entry
   population, suggesting the mechanism (not the population) is the
   root cause.

5. **S6 == S4 exactly** (same confirmed mechanical redundancy as
   ALL_FLIPS).

6. **Top-decile runner retention never exceeds 64.1%** (best: E1,
   reserved_eval) -- below the 95% bar.

## Decision

Same criteria, same simultaneous-failure result as ALL_FLIPS: **no
policy advances.** Phase 8 not run for the same reason (no candidate
cleared the EV-lift prerequisite).

**WEAKNESS-EXIT VERDICT FOR F2_CONFIRMED: CLOSE** (under W0 + the 9
tested policies). Note this verdict is specifically about the
stop-management overlay, NOT about F2's own baseline entry quality,
which shows real (if not cross-year-robust) edge independent of any
exit-management question this study was scoped to test.

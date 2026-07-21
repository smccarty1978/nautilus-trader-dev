# CODEX 5.X W4 Multi-Candidate Re-entry Study

## Objective

Test whether fixed non-adverse price-response gates become useful when a
rejected first W4 crossing can be replaced by a later causal strict crossing
within the same established-regime opportunity.

## Frozen scope

- Repaired frozen W4 score streams and direction thresholds.
- Established filter: age >= 120 seconds, running MFE >= 1 ATR, at least two
  progress windows, and retained-MFE ratio >= 0.50.
- Maximum modeled regime age: 1,800 seconds.
- Policies: R0, R10, R30 only.
- Virtual directional PnL threshold: exactly zero.
- 2025 development precedes sealed 2026 final evaluation.

## Opportunity and candidate contract

An opportunity is one prevailing regime that produces the same first eligible
strict W4 crossing as the frozen established-fade candidate collector. The
opportunity begins at that first eligible crossing. This choice is deliberate:
candidate sequence 1 must reconcile one-to-one to the frozen candidate set.

After candidate 1, the collector remains in the same causal established-filter
window. It emits a later candidate only when:

1. the W4 score went below the direction threshold after a prior crossing;
2. a later causal five-second observation crosses from below to at/above;
3. the established filter remains true at that observation; and
4. the prevailing regime and 1,800-second score horizon remain active.

The opportunity ends at the first later checkpoint where the established
filter is false, the prevailing regime ends, or the score horizon ends. It is
not reopened if eligibility later recovers. This is the prompt's single
eligible-window interpretation and prevents retrospective window selection.

Every emitted row has a stable opportunity ID, candidate sequence, observation
time, would-be fill time/open, score/threshold/margin, direction, session,
year, checkpoint ATR, regime end, and opportunity end.

## Gate sequencing

- R0 evaluates candidate 1 only and fills at the first raw one-second open at
  or after its causal observation, matching the upstream contract.
- R10/R30 start their clock at the candidate's would-be immediate fill.
- The price mark is the latest one-second close whose full interval completed
  by the gate decision.
- Approval requires virtual directional PnL from the candidate would-be fill
  to be >= 0.
- Approved delayed entry uses the first available one-second open strictly
  after the gate decision.
- A crossing during an active confirmation wait is not queued. After an
  adverse rejection, scanning resumes with the first strict crossing after the
  completed gate decision.
- Regime end, opportunity end, unavailable score horizon, or aligning flip
  before delayed fill rejects the candidate causally. A ended opportunity is
  not revived.
- Candidate acceptance consumes the opportunity even if the global
  one-position overlap rule later prevents execution. R0 uses the exact frozen
  4,383-opportunity execution population because current Policy A was an
  independent management replay over those entries; it does not recompute
  overlap after management changes. R10/R30 apply one-position overlap to
  their new accepted-entry timelines. The regenerated skip-forever diagnostic
  isolates the common 4,383-entry comparison.

## Management

From an actual accepted fill:

- 1.25 checkpoint-ATR pre-alignment stop, fill anchored and active on the
  entry bar;
- five-minute confirmation timeout restarted at actual entry;
- aligning flip at the timeout counts as confirmed;
- 1.50 checkpoint-ATR post-alignment stop;
- opposing-flip next-open exit;
- adverse-first stop semantics within one-second OHLC bars;
- $10 round-trip cost and $20/point multiplier.

## Baselines and diagnostics

1. Exact frozen current Policy A result.
2. Regenerated candidate-1/R0 reconciliation to frozen candidates, entries,
   fills, exits, and PnL.
3. A diagnostic first-candidate-only PR10/PR30 replay over the frozen 4,383
   Policy A trades, which must reproduce the prior audited skip-forever study.

## Interpretation

All results are one-second OHLC research simulation, not NT-native executable
validation or tick-level path reconstruction. Candidate diagnostics are
separate from executable policy outcomes. No direction/session subgroup can
be promoted to a policy from this study.

# CODEX 5.X W4 Streaming Lifecycle Study

## Purpose

Test the frozen repaired W4 established-regime fade as one chronological,
one-net-position lifecycle rather than as isolated opportunity trades.

## Frozen inputs

- Audited 2025/2026 multi-candidate streams from
  `codex_5_w4_multi_candidate_reentry`.
- Raw 1-second OHLC bars and repaired W4 inputs already sealed by that study.
- Frozen direction-specific W4 thresholds and established-regime filter.
- Current Policy A/R0 opportunity and trade results as the baseline.

No W4 model, score, threshold, feature, filter, or 2026-selected parameter is
changed.

## Research contract

This is the previously authorized Contract-2 explicit 1-second OHLC research
simulation, not NT-native executable validation. Entries and signal exits fill
at the first available 1-second open after the causal decision. Stops are active
on the entry bar. A touched stop fills at its trigger, except a bar opening
beyond the trigger fills at that adverse open. This is an OHLC research label,
not a claim about NT stop-market sequencing or a next-NT-fill execution. OHLC
bars cannot establish exact intrabar touch ordering.

## Policies

- `BASELINE`: frozen audited Policy A/R0.
- `S1`: immediate strict-cross entry; re-enter after pre-alignment stop or
  timeout; one position maximum; original post-alignment exit.
- `S2`: S1 plus exit-only on the first opposite W4 candidate after alignment.
- `S3`: S1 plus same-fill exit and reversal on that opposite W4 candidate.
- `S4`: S1 lifecycle with the frozen +10-second non-adverse response gate.

R30 is excluded.

## Streaming state and ordering

1. A candidate is consumed once in global chronological order.
2. While flat, the next eligible candidate may be evaluated.
3. While a pre-alignment position is open, all new candidates are ignored and
   no position is queued.
4. A pre-alignment stop or timeout returns the portfolio to flat. Scanning
   resumes only with a strict crossing whose decision is strictly later than
   the exit timestamp and while its original opportunity is valid.
5. Alignment transitions the position to aligned hold.
6. S2/S3 monitor only emitted, established-filter-valid opposite W4 candidates
   belonging to the newly prevailing regime. Their exit/reversal executes at
   the candidate's already-audited next-open fill.
7. Open-timestamp lifecycle exits and scheduled regime exits are evaluated
   before that bar's OHLC stop range. Stops use the conservative audited gap
   fill rule.
8. S2 consumes the W4 signal as an exit and may scan only later crossings. S3
   uses the same fill to close and reverse, then manages the new trade normally.
9. There is never more than one open position.
10. A sequence-1 crossing emitted exactly at the inclusive 1,800-second horizon
    remains valid for immediate entry, matching the frozen collector. Delayed
    confirmation must still complete before the opportunity-ending boundary.

## Management

- 1.25 ATR pre-alignment stop from actual fill.
- Five-minute confirmation timeout from actual fill; exit at the next available
  1-second open if alignment has not occurred.
- 1.50 ATR post-alignment stop from actual fill.
- Original opposing-regime-flip fallback exit.
- $20/point and $10 round-trip cost per executed trade.

## Opportunity and split semantics

The denominator is the frozen 4,767 eligible opportunities. Multiple attempts
are assigned to the opportunity that emitted their entry candidate. Direction
and session splits use the opportunity's frozen first-candidate direction and
session, preserving comparability with the prior study. Actual entry session is
also exported per trade.

## Development isolation

2025 must complete and seal before 2026 can run. The fixed policy set is audited
before either year executes. Combined results are descriptive only.

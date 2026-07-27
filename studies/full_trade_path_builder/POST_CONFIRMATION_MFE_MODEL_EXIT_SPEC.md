# Broad Post-Confirmation MFE and Opposing-Model Exit Study

Status: FROZEN

## Population and inputs

The population is the 5,836 canonical selected first Top-2.5% signals, one per
qualifying regime. It is not the 69,432-observation all-entry population.

Only the consolidated observations, summaries, paths, the canonical lazy
loader, and the accepted 0.75/1.00/1.25 ATR baseline result artifacts may be
read. Canonical artifacts are immutable and NautilusTrader is not rerun.

## Feasibility checkpoint and blocker resolutions

The pre-freeze inspection established:

1. Both model probabilities and domain flags are present on every path row.
2. Scores are newly computed at causal five-second checkpoints (median and p90
   source gap 5 seconds) and carried forward over intervening one-second rows.
   Persistence counts unique `*_score_source_ns` observations, never carried
   seconds.
3. All 831,952 distinct opposing score-source timestamps join exactly to
   `observations.checkpoint_decision_ns`; probability and domain comparisons
   have zero mismatches for both models. No fuzzy join is allowed.
4. Opposing scores exist for all 5,836 trades after confirmation, but the
   opposing model becomes in-domain on only 2,331 trades (39.94%): 1,311/3,329
   shorts and 1,020/2,507 longs. Model policies therefore have limited,
   explicitly reported coverage.
5. Percentile/rank columns are null. Frozen probability thresholds are:
   bullish Top-10 0.43167249785595935, Top-5 0.5067081427626979, Top-2.5
   0.5697449423968936; bearish Top-5 0.5084619230529974 and Top-2.5
   0.5641320087327389. Bearish Top-10 is absent and is unsupported rather than
   estimated. Consequently Top-10 model policies apply only to LONG trades.
6. Scores are causal checkpoint recomputations audited in the accepted builder;
   path values are exact carried copies, not interpolations.
7. Some score-source gaps span market closures. Consecutive means consecutive
   available source observations, and elapsed time is retained; no assumed
   one-second or five-second spacing is imposed.
8. Only 5,708 paths carry an explicit confirmation-boundary flag, but all 5,836
   contain an exact row at `confirm_flip_ns`. Confirmation is keyed by the
   frozen summary timestamp, not by the optional flag.

These constraints do not block Branch A. Unsupported bearish Top-10 rows are
emitted as `UNSUPPORTED_MODEL_POLICY` and excluded from policy-performance
metrics. Model coverage limitations cannot be generalized to the full
population.

## Baselines

Accepted 0.75, 1.00, and 1.25 ATR baseline artifacts must reconcile exactly to
the frozen counts in the user contract. Any mismatch fails the study.

Stop touch uses completed one-second adverse high/low. Stop exits fill at the
next path-bar open price and open timestamp. The original stop is active for
the entire trade. Flat tolerance is 0.125 NQ points.

## Price policies

The frozen families are exactly:

- fixed floor: activation 0.75/1.00/1.50/2.00 ATR × floor 0/0.25/0.50 ATR
- peak giveback: activation 0.75/1.00/1.50/2.00 × giveback 0.50/0.75/1.00 ATR
- fractional retention: activation 1.00/1.50/2.00 × retention 0.25/0.50/0.75

A management floor can execute only after confirmation. The floor applicable
to a bar is calculated from MFE known at the prior completed bar. Thus a newly
achieved activation or peak cannot cause a same-bar assumed exit. A floor
already armed before confirmation that is violated on the confirmation bar is
ambiguous. Touch fills at the next path-bar open. Candidate touch coincident
with an initial stop or regime boundary is ambiguous.

## Model policies

The opposing model is bearish for SHORT trades and bullish for LONG trades.
Primary warnings require a below-to-at/above crossing after confirmation, while
in-domain, with persistence of 1, 2, or 3 consecutive unique eligible score
observations. Already active at confirmation is diagnostic and is not a new
crossing. Domain exit resets persistence.

Immediate warning exits fill at the next path-bar open. A warning coincident
with another terminal signal is ambiguous.

## Combined policies

Representative price rules are:

- P1: activation 1.00, fixed floor +0.25
- P2: activation 1.50, fixed floor +0.50
- P3: activation 1.50, peak giveback 0.75

For every supported threshold:

- first-event-wins compares the price exit, persistence-1 model warning,
  initial stop, and opposing flip;
- model-triggered tightening activates the representative price rule only
  after both its price activation and persistence-1 warning are known. Its
  floor first applies on the next one-second bar.

## Output and validation

Every supported trade-policy pair has one exclusive result. Unsupported
direction-threshold pairs remain explicit. No future scores, fuzzy joins, or
final-MFE decisions are permitted.

Validation requires exact baselines, unique trade-policy keys, monotonic paths,
counts reconciliation, and an independent fixed-seed replay of 100 trades per
initial stop (300 trade-stop cases) with zero unexplained mismatches.

The output artifacts and report names are those in the user contract. The final
verdict is exactly one of its four allowed values.

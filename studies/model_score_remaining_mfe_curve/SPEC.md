# Model Score Level vs Remaining MFE and Confirmation Probability

**Status:** FROZEN 2021–2025 DESCRIPTIVE CONTRACT

This study maps the relation between the two frozen strict model probabilities,
confirmation survival, and remaining opportunity. It does not retrain either
model, create an optimized rule, derive percentile thresholds, or access 2026.

## Population and models

Use only RTH, true scored in-domain checkpoints in the accepted
`data/canonical/regime_complete_v1` score/path store, in 2021–2025, with
`seconds_from_regime_start > 600`. Bullish Fade is a short; Bearish Fade is a
long. No selection may read a future score, path, confirmation, or regime
duration.

## Fixed probability levels

Each model uses its frozen Top-10 and Top-5 probability as endpoints, plus
linear 25%, 50%, and 75% *probability-distance* interpolations. They are named
`FIXED_INTERPOLATED_PROBABILITY_LEVEL`, never percentiles. Frozen Top-2.5 is a
later reference. Top-1 is included only because it exists in the accepted
canonical threshold contract.

| Direction | Top-10 | Top-5 | Top-2.5 | Top-1 |
|---|---:|---:|---:|---:|
| bullish / short | 0.43167249785595935 | 0.5067081427626979 | 0.5697449423968936 | 0.6412279079940403 |
| bearish / long | 0.44559149246408103 | 0.5084619230529974 | 0.5641320087327389 | 0.6306416772425602 |

## Entry views

1. **Independent:** first true in-domain score at or above each fixed level per
   regime after age >600s.
2. **Top-10 armed:** first later true score at or above each level after the
   first Top-10 score at age >600s.

The views are reported separately.

## Measurements

The entry mark is the checkpoint reference price; ATR is frozen at that same
checkpoint. A 1-ATR touch uses 1s high/low and fills next 1s open. The session
is clamped to its own RTH day and forces flat at 15:00 America/Chicago.
Confirmation is the next causally confirmed regime transition into the trade
direction. Remaining MFE is an **unconstrained** max favorable 1s excursion
through the earlier of next opposing confirmed flip or session close; it is not
censored by the hypothetical stop.

## Outputs

`results/score_level_curve.parquet`, `results/score_level_curve.json`,
`results/year_direction_breakdown.parquet`, `results/validation_report.json`,
and `REPORT.md`. Completion requires causal lint and a clean causal audit.

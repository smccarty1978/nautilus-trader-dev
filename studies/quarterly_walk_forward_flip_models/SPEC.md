# Quarterly Walk-Forward Retrain of Strict Flip Models

**Status:** FROZEN PRE-2026 CONTRACT  
**Study:** `quarterly_walk_forward_flip_models`  
**Purpose:** Test whether causal quarterly expanding-window retraining improves
the strict 25-feature flip models, without feature, target, or hyperparameter
search. It does not authorize replacement of either frozen artifact.

## Frozen models

| Model | Regime / target | Trade | Reference status |
|---|---|---|---|
| `BULLISH_STRICT_top25_gbt_v2` | bullish -> confirmed bearish flip in `(T,T+300s]` | short | causal runtime parity passed; final-artifact audit is a required pre-2026 gate |
| `LONG_STRICT_top25_gbt_v2` | bearish -> confirmed bullish flip in `(T,T+300s]` | long | frozen challenger |

The provisional legacy bullish Top-25 artifact is forbidden.  Each model uses
its own exact ordered 25-feature vector, source adapter, population gate, and
`HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
random_state=42)`. Probabilities are `predict_proba(...)[..., 1]`.

## Population and temporal contract

- Source features are previously collected by NautilusTrader and are read-only.
  This study performs no offline signal or feature reconstruction.
- Eligible checkpoints are RTH in-domain, feature-complete rows only. Labels are
  the frozen confirmed-flip target above. Rows whose label window is unresolved
  are excluded.
- Evaluation is by calendar quarter. A model scoring quarter `Q` trains only on
  rows whose label is fully observable before `Q` starts. Thus the final 300s
  immediately preceding the boundary is excluded from training.
- The primary window is expanding. The first eligible quarter is selected only
  after both directions have non-degenerate historical classes.
- Thresholds for each retrained model are 90th, 95th, 97.5th, and 99th
  quantiles of that persisted model's scores on its eligible historical training
  population, with NumPy `method="linear"` and membership `>=`. They are causal
  *in-sample training-distribution* thresholds, disclosed as such.
- Frozen-model threshold views retain only actually artifact-frozen levels;
  unavailable levels are `N/A`. Canonical research thresholds, if displayed,
  are separately labelled and never called artifact-frozen.

## Common entry-path lifecycle

The diagnostic uses the accepted `model_driven_entry_exit_discovery` lifecycle:
RTH entries; first qualifying crossing after regime age >600s; one 1-ATR stop
tested on 1s high/low and filled at the next 1s open; 2-tick round-turn cost;
forced flat at 15:00 America/Chicago; confirmation and final opposing-flip
milestones derived from the canonical regime sequence. Entry references are
marks, not executable fills.

## Sealed 2026 gate

No path, feature, score, label, summary, or model-training row from 2026 may be
opened before all pre-2026 outputs, audits, and `pre_2026_freeze_manifest.json`
exist. A direction may enter 2026 only if every gate below passes independently:

1. median quarterly AUC delta >= +0.005;
2. worst-quarter AUC delta >= -0.02;
3. median confirmation-survival delta is >= +1 percentage point at both Top-5
   and Top-2.5;
4. at least 60% of evaluation quarters have non-negative Top-2.5 survival
   delta;
5. median return-at-confirmation delta >= -0.05 ATR;
6. no single calendar year supplies more than 50% of total positive measured
   improvement;
7. threshold-monotonicity violations occur in <=10% of quarters;
8. common-baseline net-expectancy delta >= -0.03 ATR per completed trade; and
9. causal lint, look-ahead audit, contract audit, and the Bullish strict final
   artifact audit all have zero blockers.

If one direction fails, it never reads 2026. For a passing direction, train one
final model using only observations with resolved labels through 2025-12-31 and
score all 2026 unchanged. No 2026 data enters training.

## Deliverables

`README.md`, `REPORT.md`, configs, model/threshold manifests, the machine
readable files named in the user request, `validation_report.json`, audit
reports/statuses, and an OOS result only for directions that pass the seal.

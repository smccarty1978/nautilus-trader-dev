# Canonical Pre-Flip Reliability — Corrected Pure Events

## Objective

Establish the canonical **event-corrected artifact** reliability characteristics of the frozen
Bullish Fade Top25 GBT V1 and Bearish Fade Top25 GBT V2 under one identical pure
confirmed-flip event contract. This supersedes the Bullish half of
`pre_flip_signal_reliability`; it is forecasting analysis, not execution or
production-model comparison.

The mandated Bullish artifact carries a disclosed inherited one-second feature
look-ahead and is provisional; the Bearish artifact is strict-causal. Therefore
this study is canonical for the corrected event definition and named artifact
pair, but it is not a causally symmetric model comparison and cannot establish
structural market asymmetry. Bullish discrimination may be mildly optimistic.

## Frozen models and populations

- Bullish Fade: `BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1`, legacy artifact
  `short_bearish_flip_top25_current_reference`; corrected bullish-regime
  checkpoint files from `short_rth_pure_flip_prediction_enriched`.
- Bearish Fade: `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2`, legacy artifact
  `LONG_STRICT_top25_gbt_v2`; strict bearish-regime monthly checkpoints from
  `long_rth_strict_symmetric_retrain` joined one-to-one to the strict attached
  surface for `confirm_flip_ns`, checkpoint price, ATR, and direction.
- Research partition: 2024–2025, RTH 08:30 through before 15:15 Chicago.
  Thresholds use the combined partition for continuity with the superseded
  reliability study. 2024 is in-sample and 2025 is development; every core
  model metric is also reported by year. 2026 is sealed and forbidden.

## Mandatory event contract

For both directions, join only on `(regime_start_ns, observation_time)` and set:

```text
seconds_to_flip = (confirm_flip_ns - observation_time) / 1e9
flip_le_300 = 0 < seconds_to_flip <= 300
flip_le_600 = 0 < seconds_to_flip <= 600
```

No policy, trade-survival, stop, target, or simulated-exit field may define or
modify either event. The runner scans its own event-expression source and
active event-column contract before scoring and terminates on violation.

## Population and signal contract

- Bullish rows must have prevailing direction `+1`; Bearish rows `-1`.
- Checkpoint keys must be non-null and unique within direction/year.
- Artifact predictions must pass frozen-reference/fixture parity.
- Persist deterministic arithmetic traces of 50 positives and 50 negatives per
  direction from the pure 300-second event.
- At each combined-population score percentile (top 1, 2.5, 5, 10, 25%), a
  signal is the chronologically first qualifying checkpoint per regime.

## Outputs and statistics

Report signals/day, pure flip rates, timing quantiles, decile and percentile
reliability, ROC/AP/Brier, calibration, PR/ROC/lift, timing histogram/CDF/
survival/discrete hazard, descriptive path economics, and direction-stratified
comparisons. Statistical asymmetry uses two-proportion z tests for event rates,
Mann–Whitney tests for timing/path distributions, and fixed-seed bootstrap
confidence intervals for median differences. Directions are never pooled into
a model score or event rate.

Economic marks use observed raw open-labelled one-second trade bars. A bar
stamped `t` covers `[t,t+1s)` and completes at `t+1s`; paths use observed bars
opening strictly after a checkpoint and strictly before the confirmed flip.
The raw feed is not gap-filled. Boundary lags and interior gaps are persisted;
an empty interval terminates rather than silently dropping a signal. These are
descriptive marks, never executable fills.

## Required deliverables

`canonical_reliability_report.md`, `threshold_summary.csv`,
`timing_distribution.csv`, `reliability_curves.csv`, `economic_summary.csv`,
`bullish_vs_bearish_top25.csv`, `manual_trace_bullish.csv`,
`manual_trace_bearish.csv`, and `audit/audit.md`.

## Stop conditions

- Any 2026 access, duplicate/null key, direction mismatch, non-positive flip
  horizon, incomplete attachment, artifact parity mismatch, policy-conditioned
  event reference, or missing required output terminates the study.
- Any completion-audit CRITICAL blocks acceptance; WARNING must be remediated or
  explicitly adjudicated by the user.

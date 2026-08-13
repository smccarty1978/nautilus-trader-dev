# Bullish Fade Root Cause Investigation

## Decision

Identify exactly one primary cause of the disconnect between the frozen
Bullish Fade model's original checkpoint-level discrimination and the later
pre-flip reliability results. Model improvement and retraining are out of
scope.

## Frozen scope

- Bullish Fade: `short_bearish_flip_top25_current_reference` / canonical
  `BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1`.
- Bearish Fade comparator:
  `BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2`.
- Development/evaluation year: 2025. 2026 remains sealed and is not opened.
- The original Bullish population is the corrected pure-flip checkpoint file
  `short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet`.
- The historical reliability population is the file actually opened by that
  implementation:
  `short_rth_enriched_volume_level_retrain/_work/prepared_2025.parquet`.
- The Bearish comparator population is the strict-causal 2025 monthly surface
  frozen by `long_rth_strict_symmetric_retrain`.

## Contracts tested

1. Reloaded artifacts must reproduce frozen reference predictions exactly.
2. The Bullish training label is exactly
   `(confirm_flip_ns - observation_time) / 1e9 <= 300`, on bullish,
   established-RTH, five-second checkpoints.
3. The historical reliability implementation's effective event is reconstructed
   exactly as its source code does: `confirm_flip_ns = exit_ts` only when
   `hit_opposing_flip`, and flip-within-300 is then measured from checkpoint to
   that exit timestamp. This is a policy-conditioned, horizon-limited event,
   not presumed equal to the pure market-state target.
4. A deterministic key-level sample of 50 positives and 50 negatives is
   manually-arithmetic-traced and persisted.
5. Economic quantities are descriptive marks, not executable fills. `exit_pnl`
   is checkpoint-to-last-close-before-confirmed-flip PnL in the fade direction.
6. A raw open-labelled bar stamped `t` covers `[t,t+1s)` and its completed OHLC
   is available at `t+1s`. Paths exclude the bar opening at the checkpoint and
   include the final bar whose close becomes available at the confirmed-flip
   timestamp.

## Metrics

ROC-AUC, average precision, Brier score, ten-bin calibration, confusion
matrices at 0.5 and prevalence-matched thresholds, lift at top 1/2.5/5/10%,
precision-recall and ROC curves. Event disagreement, timing quantiles,
descriptive economic path metrics, feature importance, SHAP distributions,
and feature saturation are computed separately by model.

## Classification rule

Select exactly one of A-E from the user brief in this order:

1. **A** if artifact/reference prediction parity or published-AUC reproduction
   fails (the study stops before downstream classification, per the user brief).
2. **B** if Bullish AUC reproduces within `1e-5`, target/event disagreement is at
   least 5%, the legacy event captures under 50% of original-target positives,
   and an exact historical 2024–2025 replay (combined-population percentile,
   then first qualifying checkpoint per regime) gives top-2.5% positive rate at
   least 40% on the original target but no more than 15% on the legacy event.
3. **C** if the model remains predictive of the original target (ROC-AUC at
   least 0.60), B fails, and median fade-direction checkpoint-to-flip mark PnL
   is no more than 0 ATR.
4. **D** if B and C fail, target/event disagreement is below 5%, and Bearish
   comparator AUC exceeds Bullish AUC by at least 0.05.
5. **E** otherwise.

Thresholds are duplicated in `config.yaml`; the implementation reads them from
there. If more than one defect exists, the earliest passing rule is primary and
other defects are documented as secondary.

## Required outputs

The seven user-requested deliverables are written at study root. Supporting
CSV/JSON/PNG artifacts live under `results/`; the causal audit is persisted at
`audit/audit.md`.

## Stop conditions

- Prediction parity mismatch: stop before downstream analysis.
- Missing or duplicate checkpoint keys: stop.
- Training-label arithmetic mismatch: stop.
- Any access to 2026 inputs: contract violation and stop.
- Any CRITICAL completion-audit finding: remediate and rerun before reporting.

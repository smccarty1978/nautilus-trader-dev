# BULLISH_STRICT_top25_gbt_v2

## Status

Canonical causal Bullish Fade candidate artifact, pending final completion-audit
signature. It replaces the provisional one-second-look-ahead Bullish artifact.

## Semantics

In an established bullish RTH regime, predict a confirmed bearish regime flip
within `(T,T+300s]`. A positive score describes a candidate short fade. This
artifact does not define an executable fill, stop, target, or PnL policy.

## Training and development

- Training: 2021–2024, 712,166 observable-label rows.
- Development and threshold reference: 2025, 171,334 feature-complete rows.
- Sealed 2026 data was not used.
- Estimator: `HistGradientBoostingClassifier`, depth 3, learning rate 0.05,
  200 iterations, seed 42.
- Development ROC AUC: 0.6665955254.
- Development average precision: 0.3990209961.

## Runtime contract

- Five-second checkpoint cadence.
- Approved domain: established bullish regime, RTH `[08:30,15:00)` CT.
- Direction mapping: `-1`.
- One-second sources require `ts_event<T`, `ts_init<=T`.
- Minute sources require `ts_init<T`.
- Checkpoint ATR normalizes model features; regime-start ATR is used only for
  established-regime geometry.
- Any null or non-finite feature suppresses scoring.
- Probability is uncalibrated `predict_proba(...)[positive_class=1]`.

## Thresholds

- Top 10%: 0.43167249785595935
- Top 5%: 0.5067081427626979
- Top 2.5%: 0.5697449423968936
- Membership operator: `>=`.

## Validation

- 60 monthly partitions, 968,341 checkpoints.
- Five representative 30-day-prefix boundary replays passed exact key, ATR,
  label, censor, and bitwise 25-feature parity.
- Independent March NT runtime replay passed 15,552/15,552 exact keys with
  zero vector, null-mask, suppression, or probability mismatches.

See `parity_binding.json` for immutable evidence bindings.

# Frozen Pre-Flip Model Direction-Semantics Audit

## Verdict

All seven exposed frozen artifacts have internally consistent candidate filters, binary targets, class ordering, and score polarity under the new regime-centered names. No polarity or direction mismatch was found. The legacy names were ambiguous because they used the eventual trade direction as model identity.

The Bullish Fade V1 lineage is **not production-valid**: its frozen manifests disclose an inherited open-labelled one-second look-ahead, and the pre-flip reliability run showed abnormal flip timing. This is a validity defect, not a naming-polarity inversion. Bearish Fade Top103 GBT V2 remains the sole production-valid artifact.

## Evidence trail

- Bullish Fade population/target: `runtime_constrained_f3_feature_reduction/SPEC.md` freezes `bearish_regime_flip_within_300s`, classes `[0,1]`, and `predict_proba[:,1]`; frozen manifests record `current_regime_direction: 1`, predicted flip `bearish`, and short-entry interpretation.
- Bearish Fade V1 population/target: frozen manifests record `current_regime_direction: -1`, target `bullish_regime_flip_within_300s`, positive-class index `1`, and long-entry interpretation. The long forensic audit independently traces those candidates to prevailing bearish regimes.
- Bearish Fade V2 population/target: `long_rth_strict_symmetric_retrain/SPEC.md` freezes prevailing direction `-1`, bullish-flip target/trade direction `+1`, confirmed 300-second horizon, and `predict_proba[:,1]`.
- Training/validation periods and feature counts come from each frozen manifest. Artifact hashes come from the two frozen registries/catalogs and are rechecked by the reproduction script.

## Artifact matrix

| Existing artifact | Saved model name | New canonical name | Prevailing regime | Candidate filter | Positive class / forecast flip | Trade | Horizon | Confirmation | Class / score | Features | Type | Train | Validation | Status |
|---|---|---|---|---|---|---|---:|---|---|---:|---|---|---|---|
| `short_bearish_flip_top25_current_reference` | `F3_top25_gbt_v1` | `BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1` | bullish | direction `+1` | confirmed bearish flip | short | 300s | confirmed | index 1 / `predict_proba[:,1]` | 25 | GBT | 2021–2024 | 2025 | REAUDIT REQUIRED |
| `short_bearish_flip_top100_ref` | `F3_top100_gbt_v1` | `BULLISH_FADE_TO_BEARISH_FLIP_TOP100_GBT_V1` | bullish | direction `+1` | confirmed bearish flip | short | 300s | confirmed | index 1 / `predict_proba[:,1]` | 100 raw / 103 columns | GBT | 2021–2024 | 2025 | UNVALIDATED |
| `long_bullish_flip_top25` | same | `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_LOGREG_V1` | bearish | direction `-1` | confirmed bullish flip | long | 300s | confirmed | index 1 / `predict_proba[:,1]` | 25 | LogReg pipeline | 2021–2024 | 2025 | FROZEN REFERENCE |
| `long_bullish_flip_top50` | same | `BEARISH_FADE_TO_BULLISH_FLIP_TOP50_LOGREG_V1` | bearish | direction `-1` | confirmed bullish flip | long | 300s | confirmed | index 1 / `predict_proba[:,1]` | 50 | LogReg pipeline | 2021–2024 | 2025 | ARCHIVAL |
| `long_bullish_flip_top100` | same | `BEARISH_FADE_TO_BULLISH_FLIP_TOP100_GBT_V1` | bearish | direction `-1` | confirmed bullish flip | long | 300s | confirmed | index 1 / `predict_proba[:,1]` | 100 | GBT | 2021–2024 | 2025 | ARCHIVAL |
| `LONG_STRICT_top25_gbt_v2` | same | `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2` | bearish | population direction `-1` | confirmed bullish flip | long | 300s | confirmed | index 1 / `predict_proba[:,1]` | 25 | GBT | 2021–2024 | 2025 | FROZEN CHALLENGER |
| `LONG_STRICT_top103_gbt_v2` | same | `BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2` | bearish | population direction `-1` | confirmed bullish flip | long | 300s | confirmed | index 1 / `predict_proba[:,1]` | 103 | GBT | 2021–2024 | 2025 | PRODUCTION |

## Required answers

1. Bullish Fade is the legacy `short_bearish_flip_*` / `F3_top*_gbt_v1` lineage.
2. Bearish Fade is the legacy `long_bullish_flip_*` and `LONG_STRICT_*` lineage.
3. Every frozen target matches its new semantic name.
4. No class-polarity, candidate-direction, forecast-direction, or trade-direction mismatch was found.
5. `BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2` is production-valid.
6. The Bullish Fade lineage remains unvalidated for production.
7. Prediction parity is reported independently in `prediction_reproduction_report.json`; completion requires every maximum absolute difference to equal zero.


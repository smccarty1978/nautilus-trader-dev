# Strict Symmetric Long Flip Model Retrain

## Frozen objective and chronology

Predict `bullish_regime_flip_within_300s` at 5-second checkpoints in established
bearish RTH regimes. Prevailing direction is `-1`; predicted flip and trade
direction are `+1`. Train on 2021–2024 and select on 2025 only. 2026 is excluded
from this pipeline and, if explicitly run after freeze, must be labeled
`PREVIOUSLY_EXPOSED_RUNTIME_OOS_DIAGNOSTIC`. This is transition timing, not PnL.

## Authoritative population and timing sources

Population construction is `long_rth_mirrored_surface_top100_training/implementation/build_surface_long.py:build_surface_long`:
it consumes completed-regime 5-second atlas checkpoints, applies the established
filter, RTH/fill, warmup and censoring rules, retains only direction `-1`, and
sets entry direction `+1`. Label construction is
`long_rth_mirrored_surface_top100_training/implementation/assemble_and_label.py:run_year`.

Feature attachment is
`long_rth_mirrored_surface_top100_training/implementation/attach_features_long.py:run_year`.
The legacy condition was `searchsorted(ts, observation_time, side="right") - 1`,
which includes an open-labelled 1-second bar beginning at the observation. The
strict frozen condition is `side="left" - 1`: the latest source bar must satisfy
`ts_event < observation_time`. This applies at both 1-second and 1-minute
boundaries. Equal timestamps are prohibited, including coincident event ordering.
At an observation exactly on a minute boundary the source bar at that instant is
excluded, so the minute ending at that instant has not yet been finalized by the
attachment loop; it becomes available only after the first causally permitted
bar of the new minute is processed. This conservative ordering is frozen and
exercised by `attachment_timing_trace` in the targeted tests.

## Frozen features and mappings

Lists are loaded only from
`runtime_constrained_f3_feature_reduction/results/candidate_feature_sets.json`:
`F3_top25_gbt_v1` (25) and `F3_top100_gbt_v1` (actual 103). Mappings are frozen
in `config/long_feature_mapping.json`; any `UNRESOLVED` entry blocks construction.
Absolute OHLCV/delta and market-level facts remain identical. Signed distances
are not negated. Complete one-hot groups and source order are preserved.
`pct_levels_behind_trade` alone is direction-normalized using trade direction `+1`.

## Model and bounded workflow

Both candidates use only `HistGradientBoostingClassifier(max_depth=3,
learning_rate=0.05,max_iter=200,random_state=42)` and positive-class score
`predict_proba(X)[:,1]`. Build outputs are monthly/resumable and include hashes,
counts and prevalence. No NT execution, PnL, feature search, alternative model,
or 2026 scoring is permitted. Gate order is fixture/tests, representative-month
benchmark, full build, immediate persistence, 2025 evaluation, reproduction,
then final causal audit.

The required artifact status is `CANDIDATE`. Existing v1 long artifacts are
read-only and outside this study.

# TRAIN/OOS Artifact Invalidation

Status: INVALIDATED — feature emission defect

The prior TRAIN and 2024 OOS artifacts were produced while the declared baseline
and rolling feature columns were all-null. They are not valid research inputs or
results and must not be reused.

Invalidated artifacts:

- `train_candidates_merged.parquet`
- `train_observations_merged.parquet`
- `train_partition_merge.json`
- `train_fitted_models.joblib`
- `models_long.json`
- `models_short.json`
- `train_models_manifest.json`
- `train_experiment_freeze.json`
- `oos_unlock.json`
- `oos_2024_analysis.json`

Reason: compact canonical emission did not bind canonical arrival/EMA keys and
did not translate the rolling provider's internal `rolling_5m_*` keys to the
declared `rolling_300s_*` keys. The resulting baseline and rolling matrices were
100% null; Model A was constant and Model C collapsed exactly to Model B.

The stale merged parquet and prior OOS analysis remain on disk for forensic
reference only. Model/freeze filenames now contain the repaired TRAIN-only
replacements and are bound to the repaired merge. No stale version is authorized
for modeling, scoring, or promotion.

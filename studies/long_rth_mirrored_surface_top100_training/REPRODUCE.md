# Reproduce — long_rth_mirrored_surface_top100_training

All commands run from the repo root. Python 3.13, the repo's existing
environment (numpy/pandas/pyarrow/scikit-learn). No NautilusTrader, no MBP-1.

## Inputs (read-only)

- Frozen top-100 list: `studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv`
  (`sha256 6c6ceba7…`).
- 5s atlas (both directions):
  - 2021–2024 `studies/short_rth_entry_surface_backfill/_work/atlas_5s_backfill_{y}.parquet`
  - 2025/2026 `studies/CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years/CODEX_5_X_weakness_atlas_repaired_{y}.parquet`
- Raw 1s bars `CODEX_5_X_common.RAW_1S[y]` (all 6 years present).
- Established filter `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_established_fade_policy.json`.

## Pipeline

```bash
cd studies/long_rth_mirrored_surface_top100_training

# Phase 0 — freeze + verify top-100 (SHA must match prior study)
#   (produced results/top100_feature_list.csv, top100_feature_manifest.json,
#    directionality_audit.csv)

# Phase 1 — mirrored long surface, direction==-1, self-validating (~4 min/yr)
python implementation/build_surface_long.py --years 2021 2022 2023 2024 2025 2026

# Phase 3a — attach 56 ohlcv+price features (PriceLevelTracker direction=+1) (~4 min/yr)
python implementation/attach_features_long.py --years 2021 2022 2023 2024 2025 2026

# Phase 2 + 3b — join 44 atlas center feats + build label + select top-100
python implementation/assemble_and_label.py --years 2021 2022 2023 2024 2025 2026

# Phase 4 — data-readiness + directionality gate (raises SystemExit on FAIL)
python implementation/data_readiness_gate.py

# Phase 5–8 — train logreg + GBT, evaluate, diagnostics, importance
python implementation/train_and_evaluate_long.py

# Tests (small synthetic fixtures only)
python -m pytest tests/test_mirror_logic.py -q
```

## Split discipline (enforced in code)

- Train 2021–2024, dev/select 2025, sealed test 2026.
- `train_and_evaluate_long.py` fits only on train, selects the model by 2025 AUC,
  calibrates only on 2025, and never fits/selects/calibrates on 2026.

## Key determinism facts

- `fit_gbt` / `fit_logistic` imported verbatim from
  `short_rth_enriched_volume_level_retrain/train_and_evaluate.py`; `RANDOM_STATE==42`
  asserted before any fit.
- Every stage records generator SHA-256 + input SHA-256 in its
  `results/phase*_manifest.json`.
- The mirror's directionality is self-proving: `build_surface_long` raises
  `LONG_SURFACE_DIRECTIONALITY_FAILED` unless the re-derived bearish-favorable
  running MFE equals the atlas `current_mfe` to 1e-9 at every checkpoint
  (10,253,579 checks passed across the 6 years).

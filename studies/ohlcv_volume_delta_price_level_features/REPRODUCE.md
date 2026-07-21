# Reproduce — OHLCV Volume/Delta & Price-Level Feature Foundation

Feature construction only — no model training, no entries/exits, no
economic conclusions. All commands assume repo root as working directory.

## 1. Production feature code (already in place, no build step)

- `features/trackers/ohlcv_delta.py` — `OHLCVDeltaTracker` (Part A).
- `features/trackers/price_levels.py` — `PriceLevelTracker` + `trading_day_key()` (Part B).
- `features/registry.py` — 461 new `FeatureDefinition` entries (`ohlcv_est_delta`: 214, `price_level_context`: 247), generated programmatically at the bottom of the file.
- `features/engine.py` — `FeatureEngine` wired to both new trackers (`update_1s`/`update_1m`/`snapshot`), with a 1s-bar buffer for regime/RTH-correct retroactive attribution (see CRIT-2 in `audit/audit.md`).

## 2. Tests

```bash
python -m pytest tests/test_feature_library.py studies/ohlcv_volume_delta_price_level_features/tests/ -q
```

Expected: 40 passed (9 pre-existing + 31 new: 12 in `test_ohlcv_delta.py`,
17 in `test_price_levels.py`, 2 in `test_attach_features.py`, plus 1
FeatureEngine-level regression test appended to `tests/test_feature_library.py`).

## 3. Feature schema

```bash
python studies/ohlcv_volume_delta_price_level_features/generate_schema.py
```

Regenerates `feature_schema.csv`/`.md` directly from `features/registry.py`
— never hand-edit these files. Expected: 461 rows.

## 4. Runtime validation (5-day smoke)

```bash
python studies/ohlcv_volume_delta_price_level_features/attach_features.py \
    --years 2025 --start 2025-01-06 --end 2025-01-11 --out-prefix smoke5day
```

Replays raw 1s/1m bars (with 5-day warmup padding, extended further back if
the regime active at `--start` began earlier) through both trackers,
snapshotting at each existing surface checkpoint's `observation_time`.
Copy `_work/smoke5day_2025.parquet` to `validation/sample_features.parquet`
to refresh the validation artifact. Expected:
`row_count_unchanged=True, labels_unchanged=True, provenance_violations=0`,
2,248 rows for this exact window. See `validation/feature_validation.md`
for the 9 required worked examples plus the post-audit fix log.

## 5. Full 6-year attachment (Part D)

```bash
python studies/ohlcv_volume_delta_price_level_features/attach_features.py \
    --years 2021 2022 2023 2024 2025 2026 --out-prefix full
```

Attaches Part A/B features onto the existing
`short_rth_w4_retrain_entry_strength/_work/labeled_featured_{year}.parquet`
rows (join key: `regime_start_ns`/`observation_time`) — adds columns only,
never changes rows/labels/eligibility. Runtime ~25-30 minutes for all 6
years (benchmarked ~270s/year via live tracker replay, comparable to this
repo's existing atlas-build cost — see SPEC.md scout item 5).

Writes: `_work/full_{year}.parquet` (one per year), `results/full_manifest.json`.

## 6. Post-attachment checks

```bash
python studies/ohlcv_volume_delta_price_level_features/build_join_reports.py
```

Produces `results/feature_join_summary.csv`, `results/feature_availability_by_year.csv`,
`results/feature_nan_rates.csv`, `results/manifest.json` from the `full_{year}.parquet`
outputs and `results/full_manifest.json`.

## Lookahead audit

`audit/audit.md` — two passes. First pass: **FAIL, 4 CRITICAL / 3 WARNING / 3 NOTE**
against the pre-fix code. All 4 CRITICAL and all 3 WARNING findings were
fixed (one, WARN-1, was fixed then partially and deliberately reverted for
`ohlcv_delta.py` after empirical investigation showed the auditor's literal
suggested fix was too strict for this domain — see
`validation/feature_validation.md` for the full reasoning; `price_levels.py`
kept the stricter version). Second pass re-verifies every fix independently.
Acceptance requires 0 CRITICAL on the second pass.

## Order dependency

Steps 2-3 have no dependency on 4-6. Step 5 does not require step 4 to have
run first (they use the same code, independently). Step 6 requires step 5's
`_work/full_{year}.parquet` outputs to exist for all 6 years.

## Not done

Model training. Feature selection. Threshold optimization. Entry/exit
changes. Economic conclusions. Delta-near-level, failed-high, or
level-rejection interaction features (explicitly deferred to a later
phase per SPEC.md). Promotion of any feature from `status='provisional'`
to `'verified'` in the registry (requires the second audit pass to clear
0 CRITICAL first, per `FEATURE_REGISTRY_CONTRACT.md`'s lifecycle rule).

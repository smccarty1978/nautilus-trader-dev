# Runtime-Constrained F3 Feature Reduction and Model Persistence

## Status

**SPEC frozen, pre-execution audit pending.** Do not begin Phase 3+ (importance
calculation, candidate training) until the pre-execution `lookahead-auditor`
pass clears with 0 CRITICAL findings.

## Primary objective

Determine the smallest causally defensible, live-implementable feature set
that preserves the useful high-score candidate population of the existing
695-feature bearish-flip F3 model
(`F3_volume_delta_plus_price_levels` + `HistGradientBoostingClassifier`).

## User decision to inform

Proceed with ~40-100 live-ready features, a larger live-ready subset, or
separately port F0's 149 features because they contain indispensable
predictive information.

## Verified facts (checked directly against current repo state, not assumed)

- Baseline model artifact: `studies/nt_live_scoring_infra_prereqs/_work/F3_volume_delta_plus_price_levels__gbt_reconstructed.joblib`.
  Re-hashed directly this session: `dd16ab38518cc00377058a0ff4068b59477eb1261fc541f25976767a08da670b`
  — **matches** the frozen `phase0_manifest.json` value. `model.classes_ == [0, 1]`.
- `HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)`,
  `fit_gbt` imported verbatim from `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77`.
  Target `bearish_regime_flip_within_300s` (binary), score = `predict_proba(X)[:, 1]`, positive class index 1.
- Ordered 695-feature list: `studies/short_rth_pure_flip_prediction_enriched/_work/feature_sets.json["F3_volume_delta_plus_price_levels"]`
  (flat ordered list, confirmed len==695). Sibling keys in the same file: `F0_existing_only` (149),
  `F1_volume_delta_only` (363), `F2_price_levels_only` (481) — all ordered subsets/supersets of F3, confirmed by direct load.
- Train/dev data: `studies/short_rth_pure_flip_prediction_enriched/_work/train_2021_2024_prepared.parquet` (2021-2024),
  `.../prepared_2025.parquet` (198,255 rows, 786 columns, confirmed by direct load). 2026 file
  (`prepared_2026.parquet`) exists in the same directory — **out of bounds for this entire study**, see
  Guardrails.
- Event/regime grouping key confirmed present in `prepared_2025.parquet`: `regime_start_ns`
  (int64). 198,255 rows / 1,678 unique `regime_start_ns` values in 2025 — confirms the brief's
  concern that naive row-level stability metrics would be dominated by long regimes with many
  checkpoints. All regime-level overlap/stability metrics in this study group by `regime_start_ns`.
- `studies/short_rth_pure_flip_prediction_enriched/results/feature_importance.csv` (3,376 rows) already
  contains permutation importance for all 4 feature-set x {logreg, gbt} combos on the correct binary
  target, scoring="roc_auc", 20,000-row **uniform-random** dev sample, `n_repeats=3`, `random_state=42`,
  `n_jobs=1`. Correct target, correct model family, correct split (2025 dev, no 2026). **Not sufficient
  on its own** for this study's Phase 3 requirements: sampling is uniform-random (not regime-aware /
  monthly-stratified), only 3 repeats, no monthly stability, no grouped/family importance, no
  threshold-side importance, no full-population validation. Treated as a cross-check reference, not
  reused as the final ranking.
- `studies/short_rth_enriched_volume_level_retrain/results/feature_importance.csv` is for a **different**
  5-class `outcome_class` target (`entry_quality_score` study) — **not valid evidence for this study**,
  excluded from Phase 1 inventory reuse.
- `features/registry.py`: 646 lines (was reported as 502 entries as of the frozen prereqs study;
  re-checked directly this session). **New since that study froze**: `features/trackers/median_center.py`
  (`MedianCenterTracker`) now exists and all 149 F0 feature names are registered under family
  `regime_median_center_slope_alignment`, `status="provisional"` (not `"verified"`). Audit-clean per
  `features/audit_median_center.md` (0 CRITICAL/WARNING/NOTE). No parity test exists yet between
  tracker output and the historical `build_median_centers_df` pandas values used to train the frozen
  baseline model — only small synthetic unit tests (`tests/test_median_center.py`).
  **Per explicit user decision this session**: this study adds one bounded Phase 1 parity side-check
  (below) to report whether F0 is now portable in principle. It does **not** change Phase 4-8
  mechanics — primary candidates remain restricted to the pre-existing 546 live-ready features, and F0
  stays out of the forbidden-scope boundary (no retraining on tracker-sourced F0 values in this study).
- No existing repo-wide convention for a per-model `{model.joblib, feature_list.json, manifest.json}`
  artifact directory (`grep joblib.dump` across `studies/**` found only the prereqs study's Phase 0
  script and 3 unrelated RL-feasibility scripts). `CODEX_5_X_frozen_model_manifest.json` is the closest
  style precedent (flat JSON, `dependency_sha256` dict, `status` field) but not a directory convention.
  This study creates the directory convention specified in the brief; no existing convention is
  overridden.
- T1/T2/T3 named trigger stages (as literal names) were **not found** in
  `studies/short_rth_pure_flip_score_entry_policy/` — that study's actual trigger stages are named
  `trig_A`, `trig_B`, `trig_C30`, `trig_C60`, `trig_D15s`, `trig_D30s`, `trig_D60s` (confirmed via
  `_work/schedule_trig_*` artifact filenames). Phase 6's T1/T2/T3 population-overlap requirement is
  explicitly qualified in the brief as "where supported by the frozen trigger policy" — treated as
  best-effort: this study reports population overlap using the `trig_A`-equivalent top-N% score cutoff
  definitions actually found in `studies/short_rth_pure_flip_score_entry_policy/trigger_logic.py`, and
  explicitly notes if a named stage cannot be located rather than fabricating a T1/T2/T3 mapping.

## Reused facts from `nt_live_scoring_infra_prereqs` (re-verified where practical, not re-run wholesale)

- 546/695 F3 features (78.6%) trace to registered `status="verified"` implementations with live
  NT-callback trackers (`OHLCVDeltaTracker`, `PriceLevelTracker`).
- 17 features flagged `TIMING_UNVERIFIED` (regime-relative A4 family) — carried forward as a disclosed
  residual risk, not re-audited in this study.
- `add_bars_causal_order()` helper exists for any future NT run needing coincident 1s/1m ordering — not
  used in this study (no NT `Strategy` or backtest execution here, pure offline model comparison).
- Registry schema already has `window`, `window_unit`, `reset_policy`, `snapshot_anchor` binding fields.

## Study periods and split discipline

```
Training:                    2021-2024  (train_2021_2024_prepared.parquet)
Feature ranking + selection: 2025       (prepared_2025.parquet, 198,255 rows)
2026:                        UNTOUCHED  (prepared_2026.parquet is never opened by any script in this study)
```

## Scope boundaries (see brief for full list — reproduced, not weakened)

Allowed: load frozen prepared datasets, inspect existing artifacts, compute feature importance,
retrain candidate GBT models, compare score/population behavior on 2025, persist models+manifests,
descriptive metrics.

Forbidden: pandas/vectorized economic backtests; changing entry/exit/stop/execution/labels/checkpoint
construction; using 2026 for selection; porting F0 to NT or retraining on tracker-sourced F0 values;
implementing the live-scoring NT strategy; claiming production parity; selecting on economic PnL;
silently changing hyperparameters between feature-set comparisons; any fitted model existing only under
`_work/`.

## Files this study may create or modify

Create only, under `studies/runtime_constrained_f3_feature_reduction/`:
`SPEC.md` (this file), `REPRODUCE.md`, `STUDY_REPORT.md`, `config/*.json`, `implementation/*.py`,
`tests/*.py`, `audit/audit.md`, `artifacts/models/**`, `results/*.{csv,json,md}`, `_work/**`.

No file outside this directory is modified. `features/registry.py`, `features/trackers/**`, and every
prior study's files (`nt_live_scoring_infra_prereqs/**`, `short_rth_*/**`) are read-only inputs.

## Pre-execution audit resolutions (0 CRITICAL, 5 WARNING, 2 NOTE — see `audit/audit.md`)

1. **Selection-on-dev double-dipping (Warning)**: Phase 3 ranking, Phase 4 candidate sizing, and
   Phase 7 gates all run on 2025 only. This is intentional per the brief (2026 stays untouched)
   but means nothing in this study's own scope proves the selected model *generalizes* — only
   that it reproduces baseline behavior on the set used to pick it. `STUDY_REPORT.md` and every
   use of the final decision vocabulary must state this explicitly: selection is validated
   against the 2025 ranking/selection population, not shown to generalize to an unseen year. A
   future, separate study is expected to re-check the frozen selection against 2026 before any
   live-deployment claim — this study does not and must not imply that check happened.
2. **F0 parity harness causal lead-in (Warning)**: Phase 1's tracker replay feeds each sampled
   checkpoint at least 1800s of continuous, causally-ordered 1s history immediately before it
   (matching `MedianCenterTracker`'s longest window), plus that regime's full history back to
   session start for `seq_Kr_*` (up to `seq_12r_*`, 12 completed regimes) where available. Rows
   still inside any individual feature's own warmup window are flagged `INCONCLUSIVE` for that
   feature and excluded from `MATCHES`/`DIVERGES` counts — never silently compared.
3. **Slope null-convention mismatch (Warning)**: `MedianCenterTracker._calculate_slope` returns
   `0.0` under insufficient window; `build_median_centers.py`'s offline reference returns `NaN`
   for the same condition. The parity check independently determines warmup-eligibility (window
   length) per slope/spread/ordering feature before comparing, and buckets warmup-affected rows
   separately rather than diffing `0.0` against `NaN` as if it were a real divergence.
4. **F0 registry `warmup`/`null_policy` left at defaults (Warning)**: out of scope to fix in
   `features/registry.py` here (F0 stays `provisional`, non-retrainable in this study per the
   Guardrails) — noted in `results/f0_tracker_parity_check.json` so a future study doesn't
   mistake the default for "no warmup exists."
5. **`regime_start_ns` causal construction not independently re-verified (Warning, inherited)**:
   carried forward as a disclosed residual risk per `feature_timing_causal_spec.md` — not
   re-audited here since it is the literal grouping key for every regime-overlap metric in
   Phase 6/7. If this ever proves non-causal, every regime-level metric in this study inherits
   the error; flagged in `STUDY_REPORT.md` rather than silently assumed.
6. **`fit_gbt` module-global `RANDOM_STATE` (Note)**: every script in this study that dynamically
   imports `fit_gbt` asserts `_enriched_retrain_train_eval.RANDOM_STATE == 42` immediately after
   import, before any fit call, and records the asserted value in its own manifest.

## Phase 0 — baseline freeze and promotion

1. Verify (done, see Verified facts above): artifact hash, feature order (695, exact list),
   feature-list hash, training/dev data hashes, sklearn/numpy versions, hyperparameters, class
   ordering, score method, exact reproduction (`max_abs_diff=0.0`, 198,255 rows) — all match the frozen
   `phase0_manifest.json`. Recorded verbatim into `results/baseline_manifest_verified.json`.
2. Promote (copy, do not move) the verified `.joblib` into
   `artifacts/models/F3_695_baseline/{model.joblib, feature_list.json, manifest.json, README.md}`.
   Original artifact under `nt_live_scoring_infra_prereqs/_work/` is left untouched.

## Phase 1 — existing importance inventory + F0 parity side-check

1. Write `results/existing_importance_inventory.json` documenting the validity assessment of
   `short_rth_pure_flip_prediction_enriched/results/feature_importance.csv` (valid target/model/split,
   invalid as final ranking per sampling/repeat-count gaps above) and excluding
   `short_rth_enriched_volume_level_retrain/results/feature_importance.csv` (wrong target).
2. **F0 parity side-check** (bounded, per user decision): replay a sample of historical 1s bars for a
   handful of regimes through `MedianCenterTracker`, compare `calculate()` output against the actual
   F0 columns already present in `prepared_2025.parquet` for the corresponding checkpoints, at the
   existing tolerance conventions used elsewhere in this repo. Report `results/f0_tracker_parity_check.json`:
   pass/fail per feature, max/mean abs diff, sample size and construction, and an explicit
   `parity_verdict` (`MATCHES`, `DIVERGES`, `INCONCLUSIVE`). This result feeds only the final report's
   answer to "is F0 portable now" — it does not unlock any F0-based candidate in Phase 4-8 regardless
   of outcome.

## Phase 2 — family ablations (A-G, frozen hyperparameters, GBT only)

Candidates A (695), B (546 live-ready), C (F0-149, from existing pandas columns — NOT tracker output),
D (`ohlcv_est_delta`, 214), E (`price_level_context`, 332 after one-hot grouping / 481 raw per
`F2_price_levels_only`), F (F0+D), G (F0+E). Feature-set columns for D/E derived by filtering the F3
list against `f3_feature_inventory.csv`'s `family` column (regenerated in this study, see Phase 3 note
below). Metrics only — ROC-AUC, average precision, log loss, Brier, monthly stability, score
distribution, high-score population — no economic backtest.

## Phase 3 — feature importance

1. Regenerate this study's own `results/f3_feature_inventory_v2.csv` (does not overwrite the frozen
   prereqs study's `f3_feature_inventory.csv`) by re-running the same classification logic against the
   *current* `features/registry.py`, so canonical family membership, `in_registry`, `registry_match_kind`
   reflect the new `MedianCenterTracker` registration. Confirms whether the "546 live-tracker" count is
   still accurate or whether it should now read differently.
2. Repeated permutation importance (`scoring="roc_auc"`, GBT, F3-695 baseline) on 2025. Given
   198,255 rows x 695 columns is expensive at high repeat counts (existing evidence: ~20k-row sample
   took non-trivial time at `n_repeats=3`), freeze a **regime-stratified** sample: for each calendar
   month, sample checkpoints proportionally across the month's unique `regime_start_ns` values (cap
   per-regime contribution) rather than uniform-random rows, target ~30,000 rows, `n_repeats=5`,
   `random_state=42`. Document and hash the exact sample construction in `config/importance_sample.json`.
   All **selected** candidate models (Phase 5+) are still validated on the **complete** 2025 population
   in Phase 6 — the sample is for ranking only.
3. Monthly importance stability: repeat on each calendar month's own regime-stratified sub-sample,
   report rank correlation across months.
4. Grouped importance by feature family (`ohlcv_est_delta`, `price_level_context`, one-hot-collapsed).
5. Grouped importance by canonical runtime source (collapse `__ABOVE/__BELOW/__TOUCH/__UNAVAILABLE`
   dummies to their categorical base — reuse the existing `DUMMY_SUFFIX_RE` pattern from
   `nt_live_scoring_infra_prereqs/phase1_feature_inventory.py:34`, since it's already audited logic).
6. Threshold-side importance: recompute permutation importance restricted to rows in the top-5% and
   top-2.5% score bands of the baseline model.
7. Correlation/substitutability clusters: pairwise Spearman correlation on the same regime-stratified
   sample, hierarchical clustering at a fixed distance threshold, documented in
   `results/feature_correlation_groups.json`.

## Raw vs. canonical rankings

`results/top_100_raw_feature_columns.csv` and `results/top_canonical_runtime_sources.csv` per the
brief's exact required columns/semantics. Report both model-column count and unique-runtime-calculation
count explicitly in `STUDY_REPORT.md`.

## Phase 4 — candidate construction (546-only, one frozen one-hot policy)

Raw-column targets: 25, 40, 60, 80, 100, 150, 250, 546 — selected from the Phase 3 ranking, restricted
to the 546 live-ready set. **Frozen one-hot policy**: retain complete categorical dummy groups only
(if any member of a one-hot group is selected, all its siblings are included) — chosen over partial
retention because `PriceLevelTracker.calculate()` emits all four position dummies
(`__ABOVE/__BELOW/__TOUCH/__UNAVAILABLE`) atomically per level in one call; there is no live mechanism
to emit a subset, so partial retention would not correspond to any real runtime behavior. Each list
saved to `results/candidate_feature_sets.json` and `config/` with a stable SHA-256 before any training.

## Phase 5 — retrain all candidates

Identical target/population/row-order/hyperparameters/seed/score-method. Deterministic model IDs per
the brief (`F3_live546_gbt_v1`, `F3_top250_gbt_v1`, ... `F3_top25_gbt_v1`), plus the 7 ablation models
from Phase 2 using the same persistence contract. Atomic write -> reload+verify -> hash -> promote.
Never overwrite an existing hash-mismatched artifact — bump `_v2` instead.

## Phase 6 — full 2025 population evaluation

Predictive + population metrics exactly as specified in the brief, grouped by `regime_start_ns` for all
"regime overlap" metrics. Both quantile-matched and count-matched (operating-point) threshold
comparisons — no blind reuse of the baseline's raw numeric cutoff.

## Phase 7 — selection gate

Predeclared gates exactly as specified in the brief (ROC-AUC delta >= -0.005, AP delta >= -0.010, top-5%
and top-2.5% regime overlap >= 95%, no monthly collapse, all features live-tracker + registry-bound, 0
CRITICAL audit). Prefer <=100 raw columns only if passing; never force it.

## Phase 8 — freeze selected model + catalog

`artifacts/models/FROZEN_RUNTIME_MODEL/` with all 7 required files. `results/model_catalog.json` lists
every fitted model (baseline + 7 ablations + 8 raw-count candidates = 16 total) with hash, feature
count, status, path, verdict.

## Required pytest coverage

Exactly the 17 items listed in the brief, under `studies/runtime_constrained_f3_feature_reduction/tests/`.
Full training sweep never runs inside pytest — tests use small synthetic fixtures only.

## Audits

Pre-execution `lookahead-auditor` pass after this SPEC freeze, before Phase 3+. Completion-gate pass
after Phase 8. Both written to `audit/audit.md` (appended, not overwritten).

## Stop conditions

- Phase 0 hash/reproduction mismatch -> `MODEL_ARTIFACT_VALIDATION_FAILED`, halt immediately.
- Pre-execution audit CRITICAL finding -> halt, remediate, re-audit before Phase 3.
- Any script opens `prepared_2026.parquet` -> halt, treat as a contract violation, not a warning.
- Feature-list hash mismatch between construction and training time for any candidate -> halt that
  candidate, do not silently retrain with a different list.
- If no candidate <=546 features passes all Phase 7 gates -> `NO_REDUCED_MODEL_PRESERVES_POPULATION`,
  do not force a selection.

## Final decision vocabulary

`REDUCED_RUNTIME_MODEL_SELECTED` | `LIVE_READY_546_MODEL_SELECTED` | `F0_LIVE_PORT_REQUIRED` |
`NO_REDUCED_MODEL_PRESERVES_POPULATION` | `FEATURE_RANKING_UNSTABLE` |
`MODEL_ARTIFACT_VALIDATION_FAILED` | `STUDY_BLOCKED`

# Artifact / Reproducibility Audit — `freeze_reduced_flip_model_artifacts`

**Date:** 2026-07-21T00:00:00Z (audit run)
**Scope:** `studies/freeze_reduced_flip_model_artifacts/{SPEC.md, REPRODUCE.md, MODEL_REGISTRY.md,
implementation/{freeze_models.py, run_freeze.py, build_registry.py, write_model_cards.py},
results/*, artifacts/*/}` plus direct read-only inputs: `studies/runtime_constrained_f3_feature_reduction/artifacts/models/{F3_top25_gbt_v1,F3_top100_gbt_v1}`,
`studies/nt_reduced_f3_top25_population_parity_smoke/config/*`,
`studies/short_rth_pure_flip_prediction_enriched/_work/*`,
`studies/long_rth_mirrored_surface_top100_training/_work/*` + `results/*`,
`studies/long_rth_pure_flip_top50_top25_training/_work/*` + `results/*`,
`studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py`,
`studies/ohlcv_volume_delta_price_level_features/attach_features.py`,
`studies/long_rth_mirrored_surface_top100_training/audit/audit.md`,
`studies/nt_live_scoring_infra_prereqs/phase0_reconstruct_model.py`.
**Method:** Independent re-execution (not trust of the study's own logs/manifests). All numbers
below were produced by standalone scripts that reload artifacts from disk, reload source parquet/
json files directly, and recompute — none of the study's own `parity_checks.csv` /
`freeze_manifest.json` values were taken on faith. Environment matched exactly what the study
recorded (`python 3.13.7`, `sklearn 1.7.2`, `numpy 2.3.3`, `pandas 2.3.3`, `joblib 1.5.2`).
**Auditor:** lookahead-auditor v1 (artifact/reproducibility mode)

## Summary

- Critical: 0
- Warning: 0
- Note: 3

**This is an artifact-freezing study with no NT, no MBP-1, no bracket simulation, no feature/
target changes.** Sections A/E/F/G/H of the standard checklist are N/A by design (confirmed —
no `nautilus_trader` imports, no network calls, no bar/timestamp construction in any of the four
implementation scripts). The audit below is scoped to the 10 items requested plus the standard
PROVISIONAL-designation check.

## Item-by-item findings

### 1. Nothing outside the freeze study was modified — PASS

- `git status --porcelain=v1 -uall` restricted to paths outside
  `studies/freeze_reduced_flip_model_artifacts/` returns **0 lines**. Everything touched is
  under the study directory (all currently untracked because the repo has a single "Initial
  commit" and this whole study is new work).
- Independently recomputed sha256 of
  `studies/runtime_constrained_f3_feature_reduction/artifacts/models/F3_top25_gbt_v1/model.joblib`
  = `24bf6bece8319cb9…` — matches that model's **own** `manifest.json["model_sha256"]` exactly,
  and matches `nt_reduced_f3_top25_population_parity_smoke/config/model_binding.json["model_sha256"]`.
- Same check for `F3_top100_gbt_v1/model.joblib` sha256 `84af60387cb8dc28…` — matches its own
  manifest exactly.
- Source models are provably byte-identical to what their owning studies recorded before this
  study touched anything.

### 2. Feature order is exactly frozen — PASS

Independently loaded each `artifacts/<mid>/feature_order.csv` and diffed it element-for-element
against the source list, and independently recomputed `feature_order_sha256` with the newline-
join convention used in `freeze_models.py:61-62` (`sha256_list`):

| model_id | source feature list | n | list match | sha256 recomputes |
|---|---|---|---|---|
| `short_bearish_flip_top25_current_reference` | `F3_top25_gbt_v1/feature_list.json["ordered_features"]` | 25 | True | True |
| `short_bearish_flip_top100_ref` | `F3_top100_gbt_v1/feature_list.json["ordered_features"]` | 103 | True | True |
| `long_bullish_flip_top25` | `feature_sets_manifest.json["feature_sets"]["TOP25"]` | 25 | True | True |
| `long_bullish_flip_top50` | `feature_sets_manifest.json["feature_sets"]["TOP50"]` | 50 | True | True |
| `long_bullish_flip_top100` | `top100_feature_manifest.json["feature_names_in_order"]` | 100 | True | True |

(`short_bearish_flip_top100_ref` legitimately has 103 model columns for 100 raw features — the
source manifest itself records `n_raw_features: 100` vs `n_model_columns: 103`; the extra 3
columns are one-hot expansions of categorical `*_position` features. Disclosed accurately in
`manifest.json:9-10`, not a discrepancy.)

### 3. Reloaded joblib scores reproduce stored references — PASS, claim of `max_abs_diff = 0.0` CONFIRMED

Independently (fresh Python process, no imports from the study's `implementation/`):

- Reloaded all 5 `model.joblib` files, scored `prepared_{2025,2026}.parquet` for the
  corresponding side, and diffed against `artifacts/<mid>/score_reference_{2025,2026}.parquet`:
  **max_abs_diff = 0.0 for all 5 models, both splits.**
- For the 3 reconstructed long models, additionally diffed the independently-reloaded scores
  against the **source study's own** stored predictions
  (`studies/long_rth_pure_flip_top50_top25_training/_work/pred_{TOP25,TOP50,TOP100}_{logreg,gbt}_{2025,2026}.parquet`),
  after independently verifying row order via `observation_time` equality:

  | model_id | split | row order match | max_abs_diff vs source pred parquet |
  |---|---|---|---|
  | `long_bullish_flip_top25` | 2025 | True | **0.0** |
  | `long_bullish_flip_top25` | 2026 | True | **0.0** |
  | `long_bullish_flip_top50` | 2025 | True | **0.0** |
  | `long_bullish_flip_top50` | 2026 | True | **0.0** |
  | `long_bullish_flip_top100` | 2025 | True | **0.0** |
  | `long_bullish_flip_top100` | 2026 | True | **0.0** |

  The study's claim of exact bit-identical reconstruction for all three long models is **verified,
  not merely asserted** — confirmed independently against the upstream study's own artifacts.
- Also independently reproduced the `auc_vs_published` cross-check: reloaded
  `short_bearish_flip_top25_current_reference/model.joblib`, scored the 2021-2024 concatenated
  training frame, and got `roc_auc_score = 0.7104411670580576`, exactly equal to
  `F3_top25_gbt_v1/metrics_2025.json["train"]["auc"]`.
- Also independently recomputed `MODEL_REGISTRY.md`'s headline `long_bullish_flip_top25` 2026 AUC
  (0.64619) directly from `score_reference_2026.parquet` — matched.

### 4. The reconstruction is legitimate — PASS

- Searched the entire `studies/` tree for `*.joblib` / `*.pkl` / `*.onnx` files predating this
  study. The only fitted long-side artifact anywhere is the one this study just created under
  `freeze_reduced_flip_model_artifacts/artifacts/long_bullish_flip_*`. No fitted long-side model
  object existed on disk before this study — reconstruction was genuinely required, not a
  convenience.
- The cited precedent, `studies/nt_live_scoring_infra_prereqs/phase0_reconstruct_model.py`, is
  confirmed to target `TARGET = "bearish_regime_flip_within_300s"` (short/bearish side) — it is
  precedent for the *method*, not a pre-existing long-side artifact.
- `freeze_models.py:93-94` loads `short_rth_enriched_volume_level_retrain/train_and_evaluate.py`
  as a module and asserts `RANDOM_STATE == 42` before use. Independently confirmed
  `train_and_evaluate.py:36` sets `RANDOM_STATE = 42`, `fit_logistic` (`:56-64`) uses
  `SimpleImputer(strategy="median")` → `StandardScaler` → `LogisticRegression(penalty="l2", C=1.0,
  max_iter=1000, solver="lbfgs", random_state=42)`, and `fit_gbt` (`:73-77`) uses
  `HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)`
  — exactly the hyperparameters recorded in each frozen `manifest.json["hyperparameters"]`.

### 5. ONNX is secondary and never source of truth — PASS

Independently cross-checked `onnx_status` in each `onnx_parity_report.json` against on-disk
presence of `model.onnx`:

| model_id | onnx_status | `model.onnx` present |
|---|---|---|
| `short_bearish_flip_top25_current_reference` | PASS | YES |
| `short_bearish_flip_top100_ref` | **FAIL** | **NO** |
| `long_bullish_flip_top25` | PASS | YES |
| `long_bullish_flip_top50` | PASS | YES |
| `long_bullish_flip_top100` | **FAIL** | **NO** |

Both FAIL cases have no shipped `.onnx` file — exactly the "delete rather than ship" policy in
`freeze_models.py:233-235`. Grepped every `model_card.md` and `MODEL_REGISTRY.md` for `onnx`/`ONNX`
— every mention frames it as secondary ("Do not use ONNX output as the source of truth — joblib is
authoritative", model cards line ~115; "source of truth: joblib" in every card header and in
`MODEL_REGISTRY.md:3`). Nowhere is ONNX presented as authoritative.

### 6. No 2026 selection — PASS

Grepped all four implementation scripts for every `2026` occurrence (23 hits). Every one of them
is either (a) scoring/reporting (`score_frames["2026"]`, `2026_auc` display column,
`test_rows`/`test_year`) or (b) an explicit disclaimer ("2026 never used for selection",
"never 2026" for future threshold work). No occurrence feeds `2026` into any `fit(...)`,
threshold `np.quantile(...)`, or model-choice branch. `selected_on: 2025` is hard-coded for every
model in `run_freeze.py`.

### 7. Thresholds are copied, not recomputed from 2026 — PASS

Independently diffed `artifacts/short_bearish_flip_top25_current_reference/threshold_manifest.json`
against `studies/nt_reduced_f3_top25_population_parity_smoke/config/frozen_thresholds.json`:

- `top5_cutoff` = `0.4962425079016764` == `top_5pct_threshold` — exact.
- `top2p5_cutoff` = `0.5606134281146` == `top_2_5pct_threshold` — exact.
- `threshold_selection_year: 2025`, derivation method text copied verbatim and matches.
- Independently reloaded the model, rescored `prepared_2025.parquet`, and recomputed
  `sha256(scores.tobytes())` myself (not via the study's pipeline): **matches**
  `frozen_thresholds.json["source_score_column_sha256"]` exactly, and independently recomputed
  `np.quantile(scores, 0.95)` / `np.quantile(scores, 0.975)` — both equal the frozen cutoffs
  bit-exactly.
- `top20_cutoff`/`top15_cutoff`/`top10_cutoff` are `null` in the frozen artifact, matching that
  the upstream smoke study never selected those rungs — not invented.
- Confirmed the other four models (`short_bearish_flip_top100_ref`, `long_bullish_flip_top25`,
  `long_bullish_flip_top50`, `long_bullish_flip_top100`) all carry
  `threshold_status: "NOT_SELECTED"`.

### 8. The logreg coefficient package is correct — PASS

Independently recomputed probabilities for `long_bullish_flip_top25` from
`coefficients.csv` + `intercept.json` **alone** (median-impute → standardize → linear → sigmoid),
written from scratch, no reference to `freeze_models.py`'s `manual_formula_check`:

- 2025: 819 missing values imputed; `max_abs_diff` vs `score_reference_2025.parquet` =
  **2.09e-13** (well inside the stated `1e-9` tolerance).
- 2026: `max_abs_diff` = **2.09e-13**.
- Repeated for `long_bullish_flip_top50` as a second independent check: 2025 `max_abs_diff` =
  **3.99e-12**, 2026 = **4.01e-12** — also well inside tolerance.

This is the package intended for direct NT audit without unpickling, and it is correct.

### 9. Model cards accurately describe target and limitations — PASS

- Every model card's header states "**Status:** …" and every card's final line states
  **"This model predicts regime flip probability, not trade PnL"** verbatim, with a "What not to
  use it for" section reiterating it. Consistent across all 5 cards.
- Short card (`short_bearish_flip_top25_current_reference/model_card.md`) explicitly discloses
  **"Carries a known 1-second look-ahead… NOT fixed upstream; the long-side models were."**
  Independently verified this is real, not a boilerplate disclaimer: grepped
  `studies/ohlcv_volume_delta_price_level_features/attach_features.py:149` and confirmed it still
  uses `np.searchsorted(ts, obs_times, side="right") - 1` (includes a still-forming, open-labelled
  bar at `ts_event == observation_time`) — this is the exact upstream feature-attach path that
  feeds `short_rth_pure_flip_prediction_enriched`, confirmed by grep for
  `ohlcv_volume_delta_price_level_features` references in that study's `SPEC.md`/`phase0_prepare_data.py`.
- Long card (`long_bullish_flip_top25/model_card.md`) states the corrected strict causal
  convention ("Corrected in `long_rth_mirrored_surface_top100_training` after a CRITICAL audit
  finding"). Independently confirmed against
  `studies/long_rth_mirrored_surface_top100_training/audit/audit.md`: the first audit pass records
  **"Blocking verdict: DOES NOT PASS (1 CRITICAL outstanding)"** with the exact same
  `side="right"-1` bug at that study's `attach_features_long.py:83`; the confirmatory pass records
  fix to `side="left"-1` (`:97`) and **"PASSES at 0 CRITICAL / 0 WARNING outstanding"**. The model
  card's claim is a faithful summary of a real, resolved audit finding — not overstated.
- No card overstates validation: every card explicitly states regime-level AUC ≈ 0.50 (chance),
  no economics/stop/fill model has ever validated any of them, and the PROVISIONAL card
  additionally states "Do not treat its numbers as final."

### 10. Pickle/joblib loading is trusted-local-only — PASS

`"loading_trust_model": "TRUSTED_LOCAL_ONLY..."` is written into every `manifest.json`
(`freeze_models.py:349-351`), every `model_card.md` carries the same warning verbatim under "How
to load", and `MODEL_REGISTRY.md:5` carries it at registry level. Consistent three-way coverage.

### PROVISIONAL designation — JUSTIFIED

- Independently confirmed `F3_top25_gbt_v1/manifest.json["status"] == "candidate"` (verbatim,
  read directly).
- Independently confirmed `studies/nt_reduced_f3_top25_population_parity_smoke/` contains **no**
  `STUDY_REPORT.md` anywhere in the tree (only `SPEC.md` and `config/`). The PROVISIONAL label on
  `short_bearish_flip_top25_current_reference` is justified by both stop-condition criteria the
  study cites.

## Notes (non-blocking)

### [N1] `freeze_models.py:322-323` vs `run_freeze.py:114,217-219` — two incompatible hash conventions share the "feature list sha256" naming pattern

`feature_order_sha256` (written by the freeze study itself, `sha256_list()` — newline-joined
strings) and `raw_feature_list_sha256` (copied verbatim from upstream manifests, which hash via
`hashlib.sha256(json.dumps(ordered_features).encode())` — see
`runtime_constrained_f3_feature_reduction/implementation/common.py:152`) are **both independently
correct under their own convention** (verified: both recompute exactly), but a future reader who
tries to "verify" `raw_feature_list_sha256` using the freeze study's own `sha256_list()` helper
will get a false mismatch and may wrongly conclude tampering. Worth a one-line comment in
`manifest.json`'s schema or `SPEC.md` clarifying that `raw_feature_list_sha256` uses the
**upstream** study's hash convention (`json.dumps`), not the freeze study's own.

### [N2] `build_registry.py:82,110` — `n_provisional` computed as `int(bool)`, not a count

```python
provisional = (reg["status"] == "PROVISIONAL").any()   # line 82, a bool
...
"n_provisional": int(provisional),                      # line 110
```
This currently reports `1`, which happens to be correct because exactly one model is
PROVISIONAL. If a future run ever freezes two or more PROVISIONAL models, this field would still
report `1` instead of the true count (should be `int((reg["status"] == "PROVISIONAL").sum())`).
Does not affect any finding in this audit — flagged for future-proofing only.

### [N3] `freeze_models.py:40,371` — unused `WORK` path

`WORK = STUDY / "_work"` is defined and re-exported in `__all__` but is never written to or read
from anywhere in `run_freeze.py`, `build_registry.py`, or `write_model_cards.py`. No `_work/`
directory exists under the study. Harmless dead reference; consider removing for clarity.

## Clean checks (standard checklist, N/A items confirmed by inspection)

- No `nautilus_trader` import, no `BacktestEngine`, no network/`requests`/`urllib`/`socket` calls
  in any of the four implementation scripts — confirmed by grep. Sections A, E, F, G, H of the
  standard look-ahead checklist are correctly N/A for an artifact-freeze study with no NT and no
  bracket simulation, per `SPEC.md`'s own scope declaration.
- B/C (feature/label look-ahead) are inherited-and-disclosed, not re-introduced: the freeze study
  performs no feature engineering of its own; it consumes already-prepared parquet files and
  discloses (rather than silently propagates) the one known upstream defect (short-side 1s
  look-ahead, item 9 above).
- D (train/serve skew): N/A — no live strategy exists yet in this study; the coefficient package
  (item 8) is explicitly built to make a future NT reimplementation checkable against
  `score_reference_2025.parquet` before trusting a new integration (`model_card.md`, "How to
  score").

---

*Audit complete. All quantitative claims in this report were reproduced independently from source
artifacts in a fresh Python process; none were taken from the study's own `parity_checks.csv`,
`freeze_manifest.json`, or `MODEL_REGISTRY.md` without independent recomputation. 0 CRITICAL — the
study clears the mandatory audit gate.*

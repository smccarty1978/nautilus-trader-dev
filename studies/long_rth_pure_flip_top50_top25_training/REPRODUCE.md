# Reproduce — Long-Side Top-50 / Top-25 Reduced-Feature Training

All commands run from the repository root. Total runtime ≈ 10–15 min on one core;
no GPU, no NautilusTrader, no MBP-1, no data download.

## 0. Prerequisites

This study **consumes** the strict-causal prepared data built by
`studies/long_rth_mirrored_surface_top100_training/`. Those six parquet files
must exist:

```
studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_{2021..2026}.parquet
studies/long_rth_mirrored_surface_top100_training/_work/attached_long_{2021..2026}.parquet
```

If they are absent, **do not improvise** — rebuild them with that study's
`REPRODUCE.md` (its corrected strict-causal pipeline) first. This study
deliberately does not rebuild the surface.

## 1. Phase 0 — freeze feature sets + verify data readiness (hard gate)

```bash
python studies/long_rth_pure_flip_top50_top25_training/implementation/build_feature_sets.py
```

Verifies, and exits non-zero on any failure:

- top-100 source `sha256 == 6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619`
- ordered top-100 list `sha256 == f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992`
  (recipe: `sha256("\n".join(names) + "\n")`, proved by reproducing the frozen
  hash before any reduced list is hashed)
- source CSV is in ascending `rank` order; prior study's frozen order matches
- TOP50 / TOP25 are **exact prefixes** of the top-100 (and TOP25 of TOP50)
- per-year row counts equal 164940 / 189071 / 167721 / 161220 / 163397 / 52488
- split rows equal train 682,952 · dev 163,397 · test 52,488
- target present, all 100 features present, 0 object-dtype
- `prevailing_direction == -1` and `entry_direction == +1` everywhere
- **strict causality**: `min(observation_time − latest_source_ts_used) > 0`

Expected tail:

```
TOP50 sha256 5a2b1a70ebaff75ef70cccfd5337059b840b882eb6bb996635d9d5c1b4ac9978
TOP25 sha256 d601abe692c78c0471088b41cae1fe80bbb918bbe7e7af067ddb45e7b0ce45bf
split_rows {'train_2021_2024': 682952, 'dev_2025': 163397, 'test_2026': 52488}
PHASE 0 GATE: PASS
```

Writes `results/feature_sets_manifest.json`, `results/top50_feature_list.csv`,
`results/top25_feature_list.csv`, `results/data_readiness.csv`.

## 2. Phases 1–4 — train and evaluate

```bash
python studies/long_rth_pure_flip_top50_top25_training/implementation/train_reduced.py
```

Fits six models — {TOP100, TOP50, TOP25} × {logreg, gbt} — reusing `fit_logistic`
/ `fit_gbt` **verbatim** from
`studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py` with
`assert RANDOM_STATE == 42`. Re-asserts the prefix property at fit time and
rejects any outcome/key column entering a feature matrix.

TOP100 is re-fit here (not transcribed) so all comparisons are like-for-like; it
reproduces the prior study's 0.6682 / 0.6512.

Writes `results/model_metrics.csv`, `calibration_deciles.csv`,
`feature_importance.csv`, `feature_family_contribution.csv`,
`regime_level_diagnostics.csv`, `monthly_auc_2026.json`, `model_manifest.json`,
and per-candidate scores to `_work/pred_{set}_{model}_{split}.parquet`.

## 3. Phase 5 — gates and decision

```bash
python studies/long_rth_pure_flip_top50_top25_training/implementation/decide.py
```

Applies the minimum-viable and strong-preservation gates and the briefed
preference order, then writes `results/viability_gates.json`,
`results/final_decision.json`, and copies the chosen model's scores to
`results/selected_model_predictions_{2025,2026}.parquet`.

## 4. Audit

```
Agent: lookahead-auditor  ->  studies/long_rth_pure_flip_top50_top25_training/audit/audit.md
```

Run independently of implementation. Acceptance requires **0 CRITICAL**.

## Determinism

`random_state=42` throughout (logreg, GBT, permutation-importance subsample RNG).
Reruns are bit-identical given identical prepared inputs; the per-year prepared
SHA-256 values in `results/data_readiness.csv` pin those inputs.

## What this does NOT do

No surface rebuild · no NautilusTrader · no MBP-1 · no trade economics · no
entry/stop/exit/threshold optimization · no re-ranking of features · no use of
2026 in any fitting, selection, or calibration decision.

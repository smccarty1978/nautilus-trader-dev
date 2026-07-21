# Freeze Reduced Flip Models as Reproducible Artifacts

## Primary decision

Freeze every currently relevant reduced pure-flip model into reproducible,
loadable artifacts so they can be returned to later without retraining,
ambiguity, or feature-order drift.

This is an **artifact-freezing and reproducibility study, not a modeling study**.
No feature, threshold, or target is changed. No NautilusTrader, no trade
economics. 2026 is scored for reference only and never used to select or alter
any model.

## Discovery outcome — two provenance classes

A scan of the six listed studies found that the required models split cleanly:

| Side | Fitted artifact on disk? | Consequence |
|---|---|---|
| Short (`runtime_constrained_f3_feature_reduction/artifacts/models/`) | **Yes** — `F3_top25_gbt_v1`, `F3_top100_gbt_v1`, + 13 others | **COPY** and verify |
| Long (`long_rth_*`) | **No** — only stored per-row predictions | **RECONSTRUCT**, parity-proven |

Accordingly every frozen package is labelled with one of:

- `COPIED_EXISTING_FITTED_ARTIFACT` — byte-copied; the source `model_sha256` is
  re-verified, the artifact is reloaded **from disk**, and it must reproduce the
  source study's own published metrics.
- `RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED` — no fitted object was ever
  persisted, so the exact original fit call path is re-run. Accepted **only** on
  proven parity against the source study's stored per-row predictions. This
  follows the precedent set by
  `nt_live_scoring_infra_prereqs/phase0_reconstruct_model.py`.

Reconstruction happens strictly because the artifact is missing — which the brief
permits — never as a convenience.

## Models frozen

| model_id | side | set | type | provenance | status |
|---|---|---|---|---|---|
| `short_bearish_flip_top25_current_reference` | short | TOP25 | GBT | COPIED | **PROVISIONAL** |
| `short_bearish_flip_top100_ref` | short | TOP100 | GBT | COPIED | FINAL |
| `long_bullish_flip_top25` | long | TOP25 | logreg | RECONSTRUCTED | FINAL |
| `long_bullish_flip_top50` | long | TOP50 | logreg | RECONSTRUCTED | FINAL |
| `long_bullish_flip_top100` | long | TOP100 | GBT | RECONSTRUCTED | FINAL |

### Why the short model is PROVISIONAL

Its own source manifest records `"status": "candidate"`, and
`nt_reduced_f3_top25_population_parity_smoke` — the study that consumes it — has
published no `STUDY_REPORT.md`. Per the brief's stop condition it is frozen as
the *current reference* and explicitly not marked final.

### Short-side TOP50 does not exist

The short reduction ladder is **25/40/60/80/100/150/250** — there is no 50 rung.
This is recorded, not silently skipped; the brief's "TOP50/TOP100 references"
requirement is satisfied by TOP100.

## Artifact policy

**Source of truth: `joblib`** (the sklearn estimator/Pipeline), because the
project must reload the exact estimator and reproduce historical scores.

**ONNX is secondary only.** It is attempted only after joblib parity passes, and
a failing export is deleted rather than shipped so it can never be mistaken for
the source of truth. ONNX failure does not block the study.

For logistic regression a **transparent coefficient package** is also written
(`coefficients.csv`, `intercept.json`, `feature_order.csv`, `score_formula.md`),
so the model can be reimplemented and audited inside NT **without unpickling
anything**. Its correctness is machine-checked: `parity_checks.csv` recomputes
every 2025 row from the CSV + JSON alone and compares to the model's own output.

## Parity requirements

| Check | Applies to | Tolerance |
|---|---|---|
| `joblib_reload_vs_source` | reconstructed | 1e-12 logreg / 1e-9 GBT |
| `auc_vs_published` | all | 1e-9 |
| `score_column_sha256_vs_frozen_thresholds` | short TOP25 | bit-exact |
| `threshold_recompute_q0.95 / q0.975` | short TOP25 | 1e-15 |
| `manual_formula` | logreg | 1e-9 |
| ONNX | secondary | 1e-6 preferred, 1e-5 documented |

**If joblib parity fails, the model is not frozen** (`SystemExit` with
`MODEL_FREEZE_BLOCKED_PARITY_FAILED`).

## Thresholds

Frozen **separately** from models, and **copied**, never recomputed. Where the
upstream source selected only some cutoffs, the rest stay `null` with
`threshold_status = PARTIAL_FROM_SOURCE` — cutoffs are never invented. Models
with no selected thresholds get `NOT_SELECTED`.

## Security posture

`joblib`/`pickle` executes arbitrary code on load. Every manifest, model card,
and the registry carry an explicit **TRUSTED_LOCAL_ONLY** warning.

## Files this study may create

Only under `studies/freeze_reduced_flip_model_artifacts/`. All source studies are
**read-only inputs**; no source model is modified, moved, or overwritten.

## Decision vocabulary

`MODEL_FREEZE_COMPLETE` | `MODEL_FREEZE_COMPLETE_WITH_PROVISIONAL_SHORT` |
`MODEL_FREEZE_PARTIAL_ONNX_FAILED` | `MODEL_FREEZE_BLOCKED_MISSING_ARTIFACTS` |
`MODEL_FREEZE_BLOCKED_PARITY_FAILED` | `MODEL_FREEZE_REMEDIATION_REQUIRED`

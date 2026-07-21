# Model Registry — Reduced Pure-Flip Models

**Decision: `MODEL_FREEZE_COMPLETE_WITH_PROVISIONAL_SHORT`** · source of truth: **joblib** · 5 models · 21/21 parity checks PASS

> **Loading is TRUSTED-LOCAL-ONLY.** `joblib`/`pickle` executes arbitrary code on load. Load these files only from this repository. Never load a model artifact received from an untrusted source.

| model_id | status | dir | n_feat | type | 2025 AUC | 2026 AUC | 2025 top-dec | 2026 top-dec | joblib | ONNX | thresholds | next use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `short_bearish_flip_top25_current_reference` | **PROVISIONAL** | short | 25 | gbt | 0.67099 | 0.67247 | 0.5059 | 0.50095 | PASS | PASS | PARTIAL_FROM_SOURCE | NT live-scoring parity (short) - already bound by nt_reduced_f3_top25_population_parity_smoke; PROVISIONAL until that smoke reports |
| `short_bearish_flip_top100_ref` | **FINAL** | short | 100 | gbt | 0.66411 | 0.66879 | 0.49793 | 0.49032 | PASS | FAIL | NOT_SELECTED | archival only (short reduction lineage reference) |
| `long_bullish_flip_top25` | **FINAL** | long | 25 | logreg | 0.6729 | 0.64619 | 0.50887 | 0.54506 | PASS | PASS | NOT_SELECTED | NT live-scoring parity (long) + entry-trigger study + exit-warning study |
| `long_bullish_flip_top50` | **FINAL** | long | 50 | logreg | 0.67062 | 0.6396 | 0.50294 | 0.53382 | PASS | PASS | NOT_SELECTED | archival only (long reduction lineage comparison) |
| `long_bullish_flip_top100` | **FINAL** | long | 100 | gbt | 0.66816 | 0.6512 | 0.51138 | 0.53648 | PASS | FAIL | NOT_SELECTED | archival only (long reduction reference) |

## Recommended next use — by task

| Task | Model |
|---|---|
| Short NT live-scoring parity | `short_bearish_flip_top25_current_reference` (**PROVISIONAL** — already bound by the NT smoke) |
| Long NT live-scoring parity | `long_bullish_flip_top25` |
| Entry-trigger study | `long_bullish_flip_top25` (long counter-regime entry timing) |
| Exit-warning study | `long_bullish_flip_top25` (short exit warning) |
| Archival / lineage only | `long_bullish_flip_top50`, `long_bullish_flip_top100`, `short_bearish_flip_top100_ref` |

## Provenance classes

- **COPIED_EXISTING_FITTED_ARTIFACT** — a fitted model already existed; byte-copied, recorded sha256 re-verified, reloaded from disk and proven to reproduce the source study's own published metrics.
- **RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED** — no fitted object was ever persisted. The exact original fit path was re-run and the refit reproduces the source study's stored per-row predictions **bit-identically (max_abs_diff = 0.0)**.

## What these models are not

Every model here predicts **regime-flip probability, not trade PnL**. Regime-level AUC is ~0.50 (chance) for the long family — the signal is *within-regime timing*, not regime selection. No economics, stops, or NT execution have validated any of them.

## Missing by design

- **Short-side TOP50 does not exist.** The short reduction ladder is 25/40/60/80/100/150/250; there is no 50 rung. TOP100 serves as the short lineage reference. Recorded, not silently skipped.

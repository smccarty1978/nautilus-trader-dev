# Study Report — Freeze Reduced Flip Models as Reproducible Artifacts

## Decision

**`MODEL_FREEZE_COMPLETE_WITH_PROVISIONAL_SHORT`**

Five models are frozen as loadable joblib artifacts with **21/21 parity checks
PASS**. The label reflects the one materially limiting caveat: the short-side
model remains **PROVISIONAL** pending its NT parity smoke.

`MODEL_FREEZE_PARTIAL_ONNX_FAILED` also technically applies (2 of 5 ONNX exports
failed) but is recorded as a **secondary qualifier**, not the decision — the brief
defines ONNX as a secondary artifact that must not block, and joblib remains the
source of truth in every case.

## The registry

| model_id | status | dir | n_feat | type | 2025 AUC | 2026 AUC | 2025 top-dec | 2026 top-dec | joblib | ONNX | thresholds |
|---|---|---|---:|---|---:|---:|---:|---:|---|---|---|
| `short_bearish_flip_top25_current_reference` | **PROVISIONAL** | short | 25 | GBT | 0.67099 | 0.67247 | 50.6% | 50.1% | PASS | PASS | PARTIAL_FROM_SOURCE |
| `short_bearish_flip_top100_ref` | FINAL | short | 100 | GBT | 0.66411 | 0.66879 | 49.8% | 49.0% | PASS | FAIL | NOT_SELECTED |
| `long_bullish_flip_top25` | FINAL | long | 25 | logreg | 0.67290 | 0.64619 | 50.9% | 54.5% | PASS | PASS | NOT_SELECTED |
| `long_bullish_flip_top50` | FINAL | long | 50 | logreg | 0.67062 | 0.63960 | 50.3% | 53.4% | PASS | PASS | NOT_SELECTED |
| `long_bullish_flip_top100` | FINAL | long | 100 | GBT | 0.66816 | 0.65120 | 51.1% | 53.6% | PASS | FAIL | NOT_SELECTED |

Every metric above was **recomputed from the frozen artifacts' own
`score_reference_*.parquet`**, not copied from the source studies — so the
registry describes what the frozen files actually do.

## The central discovery: two provenance classes

The six listed studies split cleanly, and this drove the whole design:

- **Short side — fitted artifacts already existed.** `F3_top25_gbt_v1` and
  `F3_top100_gbt_v1` were on disk. These were **byte-copied**, their recorded
  `model_sha256` re-verified, then reloaded *from the frozen copy* and required
  to reproduce their source study's own published metrics.
- **Long side — no fitted object had ever been persisted.** Only per-row
  predictions existed. Reconstruction was therefore genuinely *required*, not a
  convenience (the auditor independently swept the whole `studies/` tree and
  confirmed no long-side fitted model existed anywhere).

Every package is labelled `COPIED_EXISTING_FITTED_ARTIFACT` or
`RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED` so this distinction can never be lost.

## Parity — the strongest result here

**All three reconstructed long models reproduce the source studies' stored
per-row predictions with `max_abs_diff = 0.0` — bit-identical, on both 2025 and
2026.** Not "within tolerance": exactly equal. The auditor verified this
independently against the *source study's* `pred_*.parquet` files rather than
this study's copies.

The short side got a different but equally strong proof. Reloading the frozen
`F3_top25_gbt_v1` copy and rescoring 2025 reproduced:

- the published AUC `0.6709948868573161` to all 16 digits,
- the score column's **SHA-256 exactly** (`1e7daf60…`) — bit-identical per row,
- **both frozen thresholds exactly** (`q95 = 0.4962425079016764`,
  `q97.5 = 0.5606134281146`), confirming the NT smoke's thresholds still belong
  to this model.

| Check | Models | Result |
|---|---|---|
| `joblib_reload_vs_source` | 3 long | 6/6 PASS, all `max_abs_diff = 0.0` |
| `auc_vs_published` | all 5 | 9/9 PASS, all `diff = 0.0` |
| `score_column_sha256` | short TOP25 | PASS (bit-exact) |
| `threshold_recompute` | short TOP25 | 2/2 PASS |
| `manual_formula` | 2 logreg | 2/2 PASS (2.1e-13, 4.0e-12) |

## ONNX: attempted, honest about what failed

| Model | Type | Status | max_abs_diff | rows over tol |
|---|---|---|---:|---:|
| short TOP25 | GBT | PASS | 2.78e-07 | 0 / 198,255 |
| long TOP25 | logreg | PASS | 1.73e-07 | 0 / 163,397 |
| long TOP50 | logreg | PASS | 2.16e-07 | 0 / 163,397 |
| short TOP100 | GBT | **FAIL** | 1.05e-03 | **1** / 198,255 |
| long TOP100 | GBT | **FAIL** | 2.06e-01 | **55,048** / 163,397 |

Both failures are GBT; **every logistic regression converted cleanly**. Where
parity failed the `model.onnx` file was **deleted rather than shipped**, so a
broken export can never be mistaken for the source of truth (only the
`onnx_parity_report.json` remains, recording the failure).

**Root cause, investigated rather than assumed.** I first tested the obvious NaN
hypothesis and *refuted* it — the short TOP25 model has 18,272 NaN cells and
passed, and of the long TOP100 model's 55,048 bad rows, 51,125 contain **no
NaN at all**. The actual mechanism is precision: ONNX's `TreeEnsembleClassifier`
is **float32-only** (a float64 export fails to even load), while several features
carry magnitudes up to ~7.7e13 — `volume_per_point_moved_1800s` peaks at
7.69e13, where the float32 ULP is **8.4e6**. Tree split comparisons near such
thresholds flip. Logistic regression is immune because a linear model has no
discrete decision boundaries. Severity depends on which splits the tree actually
uses, which is why one GBT lost a single row and another lost a third of them.

**Practical consequence:** for GBT models, joblib is not merely preferred, it is
the only trustworthy artifact. For the long TOP25 logreg the ONNX export is
sound — but the coefficient package below is better still.

## Answers to the 10 required questions

1. **Which models were frozen?** The five in the registry table above.
2. **Final vs provisional?** Four **FINAL**; `short_bearish_flip_top25_current_reference`
   is **PROVISIONAL** — its own source manifest records `"status": "candidate"`
   and `nt_reduced_f3_top25_population_parity_smoke` has published no
   `STUDY_REPORT.md`. Both facts were independently confirmed by the auditor.
   A third, unplanned confirmation arrived mid-study: `git status` shows that
   study's `implementation/strategy.py` and `tests/test_parity_logger_and_guardrails.py`
   were modified *after* this freeze ran (07:10 vs 07:03) by the concurrent NT
   parity work. That study is still in flight, which is exactly the condition the
   brief's stop condition anticipated. **The freeze is unaffected**: its
   `config/` is clean and the threshold source file's SHA-256
   (`f5a4a62d…`) still matches what was recorded, so the copied cutoffs remain
   valid for the bound model.
3. **Source-of-truth format?** **joblib** (sklearn estimator / Pipeline), in every case.
4. **ONNX attempted?** Yes, for all five — the full toolchain was present
   (skl2onnx 1.19.1, onnx 1.20.0, onnxruntime 1.23.2, opset 17), so no
   `ONNX_NOT_ATTEMPTED_DEPENDENCY_MISSING`.
5. **Which ONNX passed?** short TOP25, long TOP25, long TOP50 (all ≤ 2.8e-07).
   short TOP100 and long TOP100 failed.
6. **Did every joblib artifact reproduce stored scores?** **Yes — 21/21 checks,
   with the long reconstructions bit-identical (0.0).**
7. **Thresholds frozen separately?** Yes, in `threshold_manifest.json`, **copied
   never recomputed**. Only the short TOP25 has any: top-5% and top-2.5%, sourced
   from 2025. `top20/top15/top10` were never selected upstream and are left
   `null` — **not invented**, flagged `PARTIAL_FROM_SOURCE`. All four other models
   are `NOT_SELECTED`.
8. **Feature orders and preprocessing frozen?** Yes. `feature_order.csv` plus a
   `feature_order_sha256` in every manifest. Preprocessing is not a separate file
   — the imputer and scaler are steps *inside* the saved `Pipeline`, which is
   stated explicitly in each `score_formula.md` so nobody hunts for a missing
   `preprocessing.joblib`.
9. **TOP25 logreg coefficients exported?** Yes — `coefficients.csv` (coefficient,
   `mean_train`, `std_train`, median-impute fill, family, timing status),
   `intercept.json`, `score_formula.md`. **And it is machine-verified**: a check
   recomputes all 163,397 2025 rows from the CSV + JSON alone and matches the
   model to 2.1e-13. The model can be reimplemented in NT **without unpickling
   anything.**
10. **What to use next?**

| Task | Model |
|---|---|
| Short NT parity | `short_bearish_flip_top25_current_reference` (already bound; **PROVISIONAL**) |
| Long NT parity | `long_bullish_flip_top25` |
| Entry-trigger study | `long_bullish_flip_top25` (long counter-regime entry timing) |
| Exit-warning study | `long_bullish_flip_top25` (short exit warning) |
| Archival / lineage | `long_bullish_flip_top50`, `long_bullish_flip_top100`, `short_bearish_flip_top100_ref` |

## Two things recorded rather than skipped

**Short-side TOP50 does not exist.** The short reduction ladder is
25/40/60/80/100/150/250 — there is no 50 rung. TOP100 serves as the short lineage
reference. Recorded in `freeze_manifest.json` and `MODEL_REGISTRY.md`.

**The short-side models carry a known 1-second look-ahead.** The upstream
`ohlcv_volume_delta_price_level_features/attach_features.py:149` still uses
`searchsorted(..., side="right")-1`, which includes the still-forming
open-labelled bar at `ts_event == observation_time`. The long side fixed this;
the short side did not. Their metrics are therefore mildly optimistic, and this
is stated in the short model cards' **Causal convention** section rather than
quietly inherited. The auditor independently confirmed the defect is still
present upstream.

## Audit

An independent `lookahead-auditor` pass returned **0 CRITICAL / 0 WARNING /
3 NOTE**. It did not rely on this study's logs: it reloaded every `model.joblib`
in a fresh process, rescored the prepared parquets, recomputed sha256/quantile/
AUC/coefficient-formula values from scratch, verified via `git status` that
nothing outside this study was modified and that both source models' hashes still
match their own manifests and the NT smoke's binding, and swept `studies/` to
confirm no long-side fitted model had ever existed. The three NOTEs were
cosmetic; the one with any substance — a dormant `int(bool)` vs `.sum()`
miscount in `build_registry.py` that was coincidentally correct today — has been
fixed and the registry regenerated.

## Scope honesty

No NautilusTrader, no MBP-1, no trade economics, no threshold/entry/exit tuning,
no feature or target changes. The only fitting performed was the parity-proven
reconstruction of long-side models that had never been persisted — which the
brief explicitly permits, and which is proven equivalent to bit-identity. 2026
was scored for reference only and never used to select or alter any model or
threshold.

**Every model here predicts regime-flip probability, not trade PnL.** Regime-level
AUC is ~0.50 for the long family — this is a within-regime *timing* signal, not
regime selection, and no economics have validated any of it.

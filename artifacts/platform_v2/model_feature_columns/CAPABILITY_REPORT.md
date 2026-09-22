# Capability report — `model_feature_columns`

Chore branch `chore/model_feature_columns` from main `137a7e91`. Requested by
`studies/nq_mtf_structural_predictive_ranking/CAPABILITY_REQUEST_model_surface_metadata_columns.md`.
Nothing was collected, no model was trained, no study was changed, and 2025/2026 were never touched.

## What changed

**`model.feature_columns: [<column>, ...]`** — the explicit model input surface, over columns the study already emits.

| file | change |
|---|---|
| `research_workflow/grammar/spec.py` | `ModelSpec.feature_columns`; refused in `mode: score`; duplicates refused in the validator |
| `research_workflow/grammar/compiler.py` | `_resolve_model_feature_columns` validates per column and records the resolved surface in `plan.model.feature_columns`; arms may subset it |
| `research_workflow/lifecycle_v2.py` | `fit` uses the resolved surface when declared, else the old surface; `MODEL_FEATURE_COLUMNS_UNBOUND` when a declared column is absent from the collected frame |

**Eligibility is per column and fail-closed.** A column is eligible only if it is a declared feature alias, a
derived input, or a declared `features.metadata` column. It is refused if it is:

- an identity/provenance column (`observation_ts`, `regime_start_ns`, `checkpoint_index`);
- any column of the study's own outcome contract — `outcome.observation_columns`, the label column, the per-arm
  `<prefix>_label` columns (so `terminal_*`, `fp_*`, `executable_entry_*`, `disposition`, `censor_reason`,
  `observed_seconds`, `horizon_end_ts` … are all refused);
- refused by the forward-outcome guard's naming grammar (`max_mfe_atr`, `final_return`, `time_to_max_mfe`, …);
- not emitted by the study at all.

There is **no blanket "metadata is safe" rule**: every column is named explicitly and checked individually. The
runtime guard (`assert_causal_feature_surface`) still runs over the resolved surface at fit, so the compiler and
the fit stage both refuse a leak.

Declaration order is the feature order, and it is what the fitted record's ordered inputs carry.

## The reuse invariant (the acceptance test)

`artifacts/platform_v2/model_feature_columns/acceptance_proof.json`, produced by
`prove_model_feature_columns.py` against the **requesting study's real collection contract** (the closed atlas's
`study.yaml`), declaring 75 audited metadata columns as model inputs: 3 MTF/trade fields, current 5m/15m/1h
geometry (direction, age, bars, start price, ATR, frozen ATR, MFE/MAE ATR, displacement, retained, extremes) and
prior 5m/15m/1h geometry (direction, start/end price, frozen ATR, duration, bars, MFE/MAE price and ATR, terminal
displacement, rotation seq).

| property | result |
|---|---|
| `replay_plan_sha256` with `model.feature_columns` | **`d917443a…`** — the value the requesting study recorded |
| same, without any model block | `d917443a…` (identical) |
| replay-stage closure composite | identical (140 files) |
| `streams`, `trackers`, `population`, `triggers`, `outcome`, `columns`, `warmup`, `availability` | identical |
| `plan_sha256` | **differs** (the model contract must reflect the surface) |
| `closure.stages.modeling` | differs (not part of the reuse key) |
| an outcome column in the list (`terminal_gross_pnl_atr`) | refused at compile |

So an already-collected partition stays valid: **adding or removing `model.feature_columns` cannot force a
re-collection.** Regression tests pin both halves (`test_declaring_feature_columns_does_not_change_the_partition_reuse_key`,
`test_reuse_key_is_insensitive_to_the_selected_surface`).

## Chronology (2023 fit / 2024 scored once)

`test_2023_fit_2024_score_chronology` drives the real fit stage over a fabricated two-year merged frame with
`validation.tuning_years: [2023]`, `final_train_validation_years: [2024]`:

- `final_fit_rows == 900` — the final estimator sees the 2023 rows only;
- `final_validation.n == 900` — 2024 is evaluated once, as a whole;
- `metrics.tuning is None` and `folds == []` — no search, no fold selection, so 2024 cannot enter any training
  decision (feature selection, thresholds, hyperparameters).

The compiler already refuses a year used for both tuning and final validation, and refuses dev/OOS years
TRAIN-side (`test_compiler_refuses_2024_in_both_roles`).

## Tests

`research_workflow/tests/test_model_feature_columns.py` — 27 tests, all passing, covering each required case:
metadata column eligible; unknown refused; outcome/label refused; `terminal_*` refused; guard-refused names;
identity refused; duplicates refused; declaration order; arms subsetting; ordinary feature columns unchanged;
legacy plan byte-identical; reuse identity unchanged; model contract changes; 2023/2024 chronology; the
requesting study's surface shape.

Targeted suites for the changed files: `test_multi_arm_modeling.py`, `test_grammar_v2.py`,
`test_declarative_analysis.py` — 69 passed. Pre-merge `test_delta` is reported in the merge commit.

## Finding recorded, deliberately NOT fixed

**The partition-reuse key binds test-file attribution.** `plan.registry_sha256` is the capability registry's
`content_sha256`, which includes each capability's `required_tests` — and that list is discovered by matching
test-file *content*. Adding any test file that happens to mention a capability's name changes the registry hash,
which changes `replay_plan_sha256`, which invalidates every previously collected partition.

This chore hit it directly: the first version of the test file fabricated a column literally named
`regime_direction`, which attached the file to `feature.regime_direction` and moved the registry hash from
`88bebf75…` to `2f6de9c8…` — which would have forced the requesting study to re-collect both years, defeating the
capability. The column was renamed (a false attribution: the test does not exercise that feature), and the
registry hash is byte-identical to main's again, verified.

The underlying fragility is real and is **not** fixed here: a test file's name has nothing to do with what a
replay emits. A follow-up chore should bind a replay-relevant registry identity (for example `inputs_sha256`, or
a subset excluding `required_tests`) rather than `content_sha256`. Until then, **any chore that adds or renames a
test file can silently invalidate collected partitions**, and should check
`research cap generate` output against main before merging.

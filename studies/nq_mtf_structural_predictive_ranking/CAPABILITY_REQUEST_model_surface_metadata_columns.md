# Capability request: let a model fit on declared metadata columns (MODEL_SURFACE_EXCLUDES_AUDITED_METADATA_COLUMNS)

Requesting study: `nq_mtf_structural_predictive_ranking` (lean modeling follow-up to the closed atlas
`nq_mtf_regime_structural_geometry_atlas`, verdict `D_NOT_FOUND`). Found 2026-09-22, session `a2b50fd4`, **before any
collection, fit or scoring**. Evidence: `artifacts/capability_probe_model_surface.json` (three production compiles).

## The defect

The V2 modeling layer can only consume **registered feature-definition instances**:

- `research_workflow/lifecycle_v2.py:1154` — `features = list(plan["columns"]["features"]) + list(plan["columns"].get("derived") or [])`
- `research_workflow/lifecycle_v2.py:1126` — `arm_cols = arm["features"] or features`
- `research_workflow/grammar/compiler.py:1288-1303` — `declared_columns = set(cols["features"]) | set(cols["derived"])`, and an arm naming anything else is `INVALID_PARAMETERIZATION`.

Tracker **metadata** columns are not model-eligible, even though they are in the collected frame, are causally
audited, are already covered by `forward_outcomes/guard.assert_causal_feature_surface`, and are the exact surface
the atlas spent two years auditing.

For this study that is the entire feature surface: 112 metadata columns — `dir_{1m,5m,15m,1h}`, `age_s_*`,
`bars_*`, `start_price_*`, `atr_*`, `frozen_atr_*`, `mfe_atr_*`, `mae_atr_*`, `pnl_atr_*`, `retained_*`,
`highest_high_*`, `lowest_low_*`, and the 39 `prior_*` snapshot fields from `tracker.regime.prior_level_snapshot`.

## Why there is no study-local workaround

| candidate | why it fails |
|---|---|
| declare the same refs under `features.columns` | changes the compiled plan outside `REPLAY_PLAN_EXCLUDED_KEYS`, so the partition-reuse key changes (`d917443a…` → `b0b3c160…`) and **both years are re-replayed (~2 h of identical bars)**. Under `host: provider_host` it does not even reach `columns.features` (still the 2 instances), so the model surface is unchanged. |
| declare new feature-definition instances for the same tracker state | feature development (WORKFLOW §E) **plus** a full recollection; it would also re-derive, under a new name, values the atlas already audited. |
| EXPLORE over a registered frame | runs registered analysis ops only; it trains no model. |
| `research frame register` | refuses a research study (`FRAME_STUDY_NOT_COLLECT`); the atlas is `stage: research`. |
| collect again | exactly what the owner instruction forbids: "STOP and resolve reuse rather than spending another 1-2 hours replaying identical bars". |

**Proved compatible:** a model-only plan change (adding `model:` with `validation.tuning_years: [2023]`,
`final_train_validation_years: [2024]`) compiles and leaves the partition-reuse key **unchanged**
(`replay_plan_sha256 d917443a…` in both), so both audited partitions are servable with no recollection. Only the
feature-surface restriction blocks the study.

## Smallest fix (the chore decides the shape)

Let a study declare model inputs that are already columns of its own collected frame:

1. A declaration such as `model.feature_columns: [...]` (or allowing `model.arms[].features` to name any declared
   column: `columns.features ∪ columns.derived ∪ columns.metadata`).
2. The compiler validates every named column against the plan's declared columns and records the resolved model
   surface in the plan, so the fitted model's `ordered_inputs` stay plan-bound and auditable.
3. `lifecycle_v2.fit` uses that resolved surface instead of `columns.features + derived`. The existing
   `assert_causal_feature_surface` guard continues to run over it unchanged (it is what keeps outcome-derived
   columns out).
4. Identity columns (`observation_ts`, `regime_start_ns`, `checkpoint_index`) and any outcome/observation column
   must stay refused.

Whether the model surface belongs in `REPLAY_PLAN_EXCLUDED_KEYS` is a separate question the chore should answer
deliberately: a model-surface declaration does not change what a replay emits, so excluding it would keep
partitions reusable across modeling variants. Today `model` is already excluded, so a `model.feature_columns`
declaration inherits that property for free.

**Required tests.** An arm/model naming metadata columns compiles and fits; the fitted record's `ordered_inputs`
equal the declared order; an outcome column (e.g. `terminal_gross_pnl_atr`, `fp_fav_2p00_label`) is still
refused by the guard; an identity column is refused; a plan that does not use the new declaration compiles
byte-identically (sealed plans replay unchanged); the partition-reuse key is unchanged by adding the declaration.

## Not requested

- No change to what collection emits, to the outcome kernel, or to any audited semantic.
- No new feature definitions, no re-collection, no change to the closed atlas.

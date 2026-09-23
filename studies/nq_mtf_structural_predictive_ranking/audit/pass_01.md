# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-23 · **Scope** study.yaml, compiled_plan.json (plan `69fd6401`), research_decision.yaml, `research_workflow/lifecycle_v2.py` (fit path), `research_workflow/forward_outcomes/guard.py`, `features/trackers/host_bindings.py` (`RegimeExcursionBinding`) · **Scope hash** `execution_composite_sha256=6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a` (packet `identity.execution_composite_sha256`, matches preflight/readiness) · **Lint** preflight CLEAR (0 critical/warning; `FORWARD_OUTCOME_GUARD`, `CAUSAL_INVARIANTS`, `CHRONOLOGY_ROLE_TABLE` all PASSED) · **Verdict** CLEAR

## Summary            Critical: 0 · Warning: 0 · Note: 1

This is Pass 01 for this study — no prior findings to adjudicate.

## What is new vs. the already-CLEAR atlas audit

The observation surface (streams, trackers, population, outcome kernel) is copied verbatim
from `nq_mtf_regime_structural_geometry_atlas` (causal pass_01 CLEAR) and is unchanged here —
not re-derived. Audited fresh: `model.feature_columns` (78 cols), `model.target`, and
chronology enforcement at the modeling layer.

### 1. `model.feature_columns` (78 columns) — causal availability at T0

Every entry resolves to a tracker snapshot field (`study.yaml:125-231`), all `strictly_before`
or `at_epoch` per the packet's `availability_table`, none from the `outcome`/label surface:

- `dir_1m/5m/15m/1h`, `atr_*`, `bars_*`, `age_s_*`, `start_price_*` — current-regime state,
  causal (regime trackers update only on completed bars).
- `mfe_atr_*`, `mae_atr_*`, `pnl_atr_*`, `retained_*`, `highest_high_*`, `lowest_low_*` —
  **running** excursion-since-regime-start values. Verified the write site
  (`features/trackers/host_bindings.py:202-243`, `RegimeExcursionBinding.on_bar`):
  `highest_high`/`lowest_low` update incrementally per completed bar and `mfe_atr`/`mae_atr`/
  `pnl_atr`/`retained_ratio` are properties computed from that running state — never from the
  regime's eventual/terminal extremum. This is the legitimate "running extremum" case, not the
  "running extremum mechanically contains eventual extremum" trap, because the regime is still
  open at T0.
- `prior_*` (39 fields) — snapshot of the immediately-prior, already-terminated regime
  (`tracker.regime.prior_level_snapshot`), fully resolved before the current regime starts;
  `strictly_before` visibility confirmed in the packet's `availability_table`.
- `checkpoint_seconds_since_flip` = `regime_1m.age_s` — elapsed time from a **past** event
  (flip) to T, computed at T; not the "cross-event elapsed time" trap (which requires the
  *later* event's timestamp to be known at the *earlier* one — not the case here).

None of the 78 names collide with `target.columns` (`terminal_gross_pnl_atr`) or with any
forward-outcome naming (`mfe_300s`, `time_to_*`, `post_confirmation_*`, `reach_*`). Preflight's
`leaked_outcome_columns: []` and `FORWARD_OUTCOME_GUARD: PASSED` confirm this deterministically
(compiled_plan.json:1628-1707).

### 2. `model.target` = `terminal_gross_pnl_atr > 0`

`terminal_gross_pnl_atr` is a genuine C1-terminal outcome column
(`research_workflow/host/outcomes.py:711-718`): `gross_pts = p.direction * (p.exit_price -
p.entry_price)` using executable next-bar-open entry/exit fills, `/ p.atr`. Confirmed this is
derived **after** collection, from an already-collected column, never re-touching the
persisted partition (`research_workflow/lifecycle_v2.py:1058-1093`).

Two independent guards prevent it from also being a feature:
- Compile-time: `assert_causal_feature_surface` (`research_workflow/forward_outcomes/guard.py:97-111`).
- Fit-time hard check: `if model.get("target") and label in features: raise
  MODEL_TARGET_IN_FEATURE_SURFACE` (`lifecycle_v2.py:1100-1101`).

`compiled_plan.json:1722-1729` confirms `target.columns == ["terminal_gross_pnl_atr"]`, which
does not appear in `feature_columns`. C1/C2 clean.

### 3. Chronology — 2024/2025/2026 cannot enter fitting or selection

- Data layer: `merge()` restricts the merged frame to `chronology.train` authorized years
  (`_authorized_years(plan, "train", ...)` → `[2023, 2024]` only); 2025/2026 are never read
  from disk at any stage in this plan (`lifecycle_v2.py:1004-1008`, `1585-1588`). The
  `analyze`/OOS path's authority is `plan.chronology.dev`, which is `[]` here, so nothing opens
  2025/2026 (consistent with the stop condition — the frozen 2024 evaluation has not run yet).
- Fit layer: `final_rows = cell_rows[cell_rows["_year"].isin(tuning)]` with `tuning =
  [2023]` (`lifecycle_v2.py:1110, 1226`) — the stored model is fit **only** on 2023 rows.
  `final_years = validation.get("final_train_validation_years") or []` is empty in the current
  compiled plan, so `final_val = ... if final_years else None` (`lifecycle_v2.py:1230`) means
  2024 rows are merged into memory but never scored or selected against in this run — inert,
  not a leak. C3 clean (no random cross-year split; `validation.model_selection.random` is
  declared but unused because `search_space` is empty for every arm, matching the "no sweeps"
  design).

### 4. Cell `t0` (`subset: {checkpoint_index: 0}`)

`population.cadence.anchor = regime_1m.start_ns`, so `checkpoint_index=0` is the first 15s-grid
tick coincident with the 1m flip — the decision epoch T0, not a mid-regime point already
carrying accrued excursion. `_rows_for(cell)` (`lifecycle_v2.py:1149-1155`) filters the row
population before scoring/fitting on this subset; consistent with a T0 entry-time surface.

## Critical findings
None.

## Warnings
None.

## Notes

### [note-1] `audit/readiness.json` carries no R2/R4 rows for this study
Only R1/R3/R5/R8/R9/R10 are present. Expected: this study performs no new NT collection
(`chronology.partition_reuse: replay_closure`); R2 (timestamp contracts) and R4 (callback
causal order) were proven when the identical bars were originally collected under
`nq_mtf_regime_structural_geometry_atlas` (causal pass_01 CLEAR). Disclosure only, no action.

## Referred to contract-checker
- `research_decision.yaml` documents `final_train_validation_years: [2024]` as the intended
  frozen-2024 evaluation mechanism, but the current compiled plan carries `[]`
  (`compiled_plan.json:1731`, `study.yaml:474`) — no frozen 2024 score will be produced by a
  `fit` run against this exact plan; deliverable/lifecycle-readiness question, not causal.

## Clean checks
C1, C2, C3 clean (verified fresh, this pass). A1-A5, B1-B10, F1-F4, G1-G4, H1-H4 inherited
CLEAR from the verbatim-copied, previously-audited atlas collection contract — not re-derived
per scope (`docs/CAUSAL_CHECKLIST.md` split; observation surface unchanged, preflight/readiness
both CLEAR on the current closure `6ced7ced583a`).

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a", "auditor": "lookahead-auditor", "critical": 0, "note": 1, "study": "nq_mtf_structural_predictive_ranking", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

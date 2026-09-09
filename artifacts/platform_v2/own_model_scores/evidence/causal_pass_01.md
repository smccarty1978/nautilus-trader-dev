---
audit_type: "causal"
study: "s12_own_scores_gate"
pass: 1
auditor: "lookahead-auditor:s12_own_scores_gate_causal_pass01"
audited_execution_composite_sha256: "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7"
---

# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-09 · **Study** `s12_own_scores_gate` (platform gate, disposable, tier 2, zero study
Python) · **Scope** `studies/s12_own_scores_gate/study.yaml`, `compiled_plan.json`,
`audit_packet_causal.json`, `research_workflow/lifecycle_v2.py` (`_declared_analysis`,
`_join_own_model_scores`, `_freeze_bound_fitted_models`, `_train_frame_all_labels`, `analyze`),
`research_workflow/grammar/compiler.py` (`_resolve_analysis`), `research/analysis/diagnostic_ops.py`
(`tail_lift`) · **Scope hash (packet identity)** `execution_composite_sha256=73db2ed0f2131…` /
`plan_sha256=81216d4cd851…` (packet vs. `compiled_plan.json` vs. `audit/frozen_execution_manifest.json`
all identical) · **Lint** preflight `audit/preflight.json` = `CLEAR`, 0 critical / 0 warning
(`FORWARD_OUTCOME_GUARD`, `CAUSAL_INVARIANTS`, `ENTRY_REFERENCE_EXECUTABLE`,
`CHRONOLOGY_ROLE_TABLE` all `PASSED`); readiness `audit/readiness.json` = `PASS`, R1/R3/R5/R8/R9/R10
all `passed: true`; tests 137/137 pass at this composite · **Verdict** **CLEAR**

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
N/A — pass 1, no prior report exists under `studies/s12_own_scores_gate/audit/`.

## Scope-specific verification (own-model score join, this study's reason for existing)

| Question | Evidence | Result |
|---|---|---|
| Is `score__primary` computed AFTER fit/freeze, never during collection/fit? | `_declared_analysis` (lifecycle_v2.py:1482-1563) runs at the `analyze` stage only, calling `_join_own_model_scores` (1345) after `_freeze_bound_fitted_models` (1310) reads `artifacts/train_experiment_freeze.json`. Nothing in `fit()`/`freeze()` (1014-1460) reads or writes a `score__*` column. | Clean |
| Is the scoring model bound to the exact TRAIN-frozen bytes (no post-freeze substitution)? | `_freeze_bound_fitted_models` passes `expect.canonical_sha256 = freeze_canonical["primary"]`; `_join_own_model_scores` calls `authenticate_model(..., expect=m["expect"])` before scoring (1361). | Clean (train/serve-skew adjacent, referred to contract-checker for its own C4/D verification) |
| Is `train_frame` admitted only under `analysis.source: oos`? | Compiler: `builtin = {"frame"} \| ({"train_frame"} if spec.source == "oos" else set())` (compiler.py:1243); any other ref is rejected at `_unbound()` (1250-1253) with an explicit message. This study's compiled `analysis.source == "oos"` (compiled_plan.json:19) and `chronology.dev == [2024]` is non-empty, so the admission condition is genuinely satisfied, not vacuously true. | Clean |
| Does `train_frame` actually read TRAIN-only rows, never OOS? | `_declared_analysis` builds `frames["train_frame"] = self._train_frame_all_labels(plan)` with `base=None` → reads `self.work/"merged"/{candidates,observations}.parquet`, i.e., the TRAIN merge produced by stage 11 (MERGE), populated before OOS ever opens. `frames["frame"]` (OOS) is built separately from `self.work/"partitions"/"oos"/<year>` for `_authorized_years(plan, "oos", ...)`. The two frames never share a code path or a merge step. | Clean |
| Is OOS access gated before either frame is read? | `if spec["source"] == "oos": assert_oos_open(self.study)` (1495) runs before `frame` (OOS) *and* before `train_frame` is built, and before `_join_own_model_scores` touches either. | Clean |
| Does `tail_lift` freeze thresholds on the reference frame only, never on the evaluated rows' own distribution? | `diagnostic_ops.py:974`: `thr = float(r[score].quantile(q, ...))` where `r` is sliced from `reference` (== `train_frame`); `tail = e[e[score] >= thr]` where `e` is sliced from `rows` (== OOS `frame`). No path computes `thr` from `e`. | Clean |
| Is `score__primary` scored independently per frame (no TRAIN score leaking into the OOS column or vice versa)? | `for name in list(frames): frames[name], own_scores[name] = self._join_own_model_scores(frames[name], bound)` (1517-1518) — each call operates on one frame in place, writing `score__primary` into that frame only. | Clean |
| Do the joined feature inputs to the model match the causally-verified feature surface (no outcome column as a model input)? | `_join_own_model_scores` reads `inputs = read_manifest(...)["lineage"]["ordered_inputs"]`, which is the feature set `assert_causal_feature_surface(features, ...)` already validated at `fit()` (line 1032) for this same TRAIN composite — no separate/uncontrolled input list is introduced at analyze time. | Clean |
| `model_scores` only permitted for a study that actually fits its own model (not `mode: score`)? | Compiler gap: `if spec.model_scores and (model == "none" or model.mode != "train"): ctx.gap(...)` (compiler.py:1245-1248). Compiled `model.mode == "train"` (compiled_plan.json:743) — no gap raised, correctly. | Clean |

## Availability table / feature-surface verification

- All three declared feature instances (`prior_1m_regime_efficiency`, `prior_5m_regime_efficiency`,
  `rolling_300s_giveback_atr`) declare `availability: completed_bar_ts_init`, `visibility: at_epoch`,
  `bar_state: completed`, `context: prior` — completed-bar-only, strictly-causal semantics per Feature
  System V2 (RESEARCH_WORKFLOW.md §2). None is a forward-outcome-shaped name (`mfe_300s`,
  `time_to_max_mfe`, `post_confirmation_*`); `rolling_300s_giveback_atr` is the checklist's own example
  of a legitimate past-describing rolling feature.
- Context streams (`regime_1m`, `regime_bar_5m`) both declare `visibility: strictly_before`; the
  execution stream (`nq_1s`) is `at_epoch`. `same_timestamp_rule: "context streams expose events with
  ts_init < T only"` matches RESEARCH_WORKFLOW.md §17's completed-bar/`ts_init` convention; `nq_1m`
  carries `ts_init_delta_ns: 60000000000` and `nq_1s` carries `1000000000` (A2, clean).
- `columns.features` (`prior_1m_regime_efficiency`, `prior_5m_regime_efficiency`,
  `rolling_300s_giveback_atr`) is disjoint from `columns.observation` (`target_flip_within_horizon`,
  `disposition`, `censored`, `flip_ts`, `time_to_flip_seconds`, `horizon_end_ts`, `session_close_ts`,
  `resolved_at_ts`) — no outcome column is present in the feature surface at the schema level (C1
  clean); `FORWARD_OUTCOME_GUARD: PASSED` and `leaked_outcome_columns: []` in preflight corroborate this
  on the real bounded sample.
- Population qualifier (`excursion.frozen_atr > 0 and regime_1m.age_s >= 120s and excursion.mfe_atr >=
  1.0 and features.structural_snapshot_ready`) reads only `at_epoch`/`strictly_before` state; `mfe_atr`
  is the excursion tracker's *running* MFE evaluated at the current epoch (an armed, in-progress
  quantity gating candidate emission), not the trade's eventual/terminal MFE — no running-extremum
  substitution for an eventual one (checklist's "running vs. eventual extremum" pattern).
- Chronology is a temporal split by construction (`train: [2023]`, `dev(oos): [2024]`, disjoint
  narrowed windows `2023-03-01..03` / `2024-03-04..06`, `prohibited: [2021,2022,2025,2026]`) — C3
  clean.

## Critical findings
None.

## Warnings
None.

## Notes

### [N1] In-sample TRAIN scoring of `score__primary` on `train_frame` is scoring the model on rows it was fit on
`_join_own_model_scores` scores the frozen model on `train_frame` (TRAIN rows) to derive `tail_lift`'s
threshold, and the same model was fit on those TRAIN rows. This is in-sample scoring by design — it is
the intended mechanism for "freeze a threshold on TRAIN, evaluate lift on OOS," matching the checklist's
`prior_1m_regime_efficiency`-style legitimate-by-write-site pattern, not a leak: the *evaluation*
(`tail_rate`/`lift`) is always computed on the disjoint OOS `frame`, never on `train_frame`. Documented
here because a superficial "score computed on rows the model was trained on" reading looks alarming
without the call-by-call trace above. No fix needed.

## Referred to contract-checker
- `audit/readiness.json` carries only 6 checks (`R1_NQ`, `R3_session_table`, `R5_binding_proof`,
  `R8_host_boundary_lint`, `R9_closure_current`, `R10_zero_study_python`); it does not list separate
  `R2`/`R4` entries by id. Whether this V2 readiness harness folds R2 (timestamp contracts) / R4
  (callback causal order) into `CAUSAL_INVARIANTS`/`ENTRY_REFERENCE_EXECUTABLE` in preflight, or the
  readiness deliverable set for this study kind is intentionally smaller, is a deliverable-completeness
  question, not a causal one — not re-derived here per role instructions not to re-derive R2/R4.
- Model-bytes authentication (`expect.canonical_sha256` binding at score time) is a train/serve-skew /
  model-integrity control (checklist D3/C4 territory); verified above only as evidence for the causal
  question (post-freeze scores, not mid-fit), not audited for its own completeness.

## Clean checks
A1, A2 · B2, B3, B9 (feature semantics; no B1/B4-B7/B10 code paths in this study — zero study Python) ·
C1, C2, C3 · F1 (session/RTH via calendar reference table, R3 verified) · G1 (`NQ_1S_V2_GLOBEX`
dataset, digest-verified at R1) · H not applicable (no bracket/backtest simulation in this study —
label/analysis gate only, no strategy execution).

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7", "auditor": "lookahead-auditor:s12_own_scores_gate_causal_pass01", "critical": 0, "note": 1, "study": "s12_own_scores_gate", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

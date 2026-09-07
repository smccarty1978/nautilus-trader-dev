# Look-Ahead & Timestamp Audit — Pass 02

**Date** 2026-09-06 · **Study** `es_180s_model_c_portability` · **Auditor** `lookahead-auditor:005_causal_audit_ea737155`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (sha256 `b0a9f7c2…`, packet_version 2) + the 2-file closure delta since the prior audited composite; branch `study/es_180s_model_c_portability` @ `fd943207`
**Audited execution composite** `4f766f57344718f1416cc8f827f67bac8ed4f560b4b86f2fc921e1a7742797a1` (90 files, hash v2) · prior audited `da3d3ab4ee9b` @ `45c6e1e0`
**Gate facts cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1_ES, R3, R5, R8, R9, R10) · tests PASS 132/0 @ `4f766f573447` · controller OK / NEEDS_CAUSAL_AUDIT
**Changed executable surface** 2 changed, 0 added, 0 removed: `research/analysis/diagnostic_ops.py` (`3567f19f2bd5`→`87a13de52bbd`), `research_workflow/lifecycle_v2.py` (`e1fc67f65b20`→`d107c8aed9cd`). Source delta reviewed via `git diff 45c6e1e061ec..HEAD -- <those two files>` (315 insertions / 4 deletions). Both are post-collection stages — neither touches the collection-time feature or label path.
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 6 (5 carried from pass 01, 1 new)

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| B9 | `host_bindings.py:154,219-239` excursion extremes miss the regime-start minute | STANDING (note) | `features/trackers/host_bindings.py` is not in the 2-file delta (brief §3); unchanged since `da3d3ab4ee9b`. Past-information omission, conservative on the qualify gate — non-blocking, and identical in the origin study, which is what a portability comparison requires. |
| G2 | `host_bindings.py:275-317` 5m calendar buckets require no completeness | STANDING (note) | Same file, unchanged in the delta; dependent `prior_5m_*` still gated by `features.structural_snapshot_ready` (`population.qualify`, packet). |
| F2 | `research_workflow/host/…` rolling providers — no session reset on `rolling_300s_*` | STANDING (note) | No `research_workflow/host/*` file is in the delta; `chronology.windows` is still `[]` (packet). All aggregated bars remain strictly past. |
| G4 | `host_bindings.py:591` 1m dispatch hardcodes `volume: 0.0` | STANDING (note) | Same file, unchanged; the 13 declared aliases (packet `features.aliases`) are still volume-free and no `ohlcv_delta` tracker is instantiated (packet `trackers`). |
| A1 | `structural_regime_geometry.py:176` `can_snapshot` admits `close_ts == T` | STANDING (note) | Same file, unchanged; equality case still unreachable — `streams[es_1m].visibility = strictly_before`, `same_ts = unavailable`, and `same_timestamp_rule` in the packet is unchanged; the mux test remains green in the 132-test run at this composite. |

No prior finding is re-raised under new framing; none was CRITICAL or WARNING, so none blocked.

## Critical findings

None.

## Warnings

None.

## Notes

### [C1/C3] `research_workflow/lifecycle_v2.py:1199-1206` — `analyze` now hands ops a path to the study directory
The declared-analysis step context gained `study_dir`, `artifacts_dir` and `model_root`; that branch (`:1246-1252`) deliberately skips `assert_oos_open`, because a train-source diagnostic opens no dev year. The declared invariant "assert_oos_open is the only OOS door" therefore now rests on op-registry discipline rather than on ops having no path to `_work/partitions/oos`. No failure path today: `OPS` is a closed registry inside the audited closure (`diagnostic_ops.py:707-717`), `OP_CONTEXT` is the two gates only, and both read exactly `artifacts/experiment_models.json`, `compiled_plan.json` and the model store — never a partition directory. Disclosure, not a defect. **Inert for this study:** `plan.analysis` is `null` (`studies/es_180s_model_c_portability/compiled_plan.json:2`), so no declared-analysis step executes here.

## Verified positives (the delta-specific checks that mattered)

- **The new multi-cell OOS branch scores, never fits, and only behind the OOS door.** `lifecycle_v2.py:1296-1311` runs after `assert_oos_open` (`:1254`) and builds its frame from `self.work/"partitions"/"oos"` restricted to `self._authorized_years(plan, "oos", …)` (`:1256-1257`, `:1307`). `_score_models` (`:1049-1084`) calls `score()` on stored canonical bytes — no `fit` call is reachable in it (C3 clean).
- **Feature/label separation holds in the new branch.** Each model's inputs are the store's `lineage.ordered_inputs` (`:1061`), a subset of the plan surface already passed through `assert_causal_feature_surface` at fit (`:808`); `_Scorer.scores` selects `frame[self.inputs]` (`model_store.py:144`), so passing a wider frame cannot admit the label column or reorder inputs (C1, C2 clean).
- **The cell's population filter now travels with the frozen record** (`:952`, `"subset": dict(cell.get("subset") or {})`) and is applied at OOS from the record (`:1069`), not re-derived from a possibly recompiled plan — this closes a silent-re-slice path rather than opening one.
- **The new arm-delta gate reconciles against the fit's actual population.** `diagnostic_ops.arm_delta_integrity_gate` rebuilds each cell as binary-label rows ∩ `tuning_years` ∩ cell subset and RAISES on a count mismatch with the recorded `final_fit_rows`. That mirrors the fit exactly: `final_rows = cell_rows[cell_rows["_year"].isin(tuning)]` (`lifecycle_v2.py:930`), `final_fit_rows = len(final_rows)` (`:958`), and `tuning_years` is always written by that same fit (`:969`) — so the gate's "no tuning years" fallback is unreachable for the shape it audits. A check deriving its own scope could not have detected scope loss; this one does not derive it.
- **The gate adds no column and cannot reach a feature.** It returns `{"frame": rows}` unchanged and is registered as an analysis op that runs after collection on materialized frames (`diagnostic_ops.py:24-31`, module docstring). Reading outcome columns is its purpose and is confined to the analysis stage (B4, C1 clean).
- **UTC year assignment is safe here.** Both the fit (`:1046`) and the new gate derive `_year` from `observation_ts` in UTC. Emission is RTH 08:30–15:15 CT = 14:30–21:15 UTC, so the UTC calendar date always equals the CT date for an emitted candidate; no candidate can migrate across a year/partition boundary (F3, F4 clean).
- **The freeze/OOS naming change is symmetric.** `_model_record_name` / `_model_record_id` (`:104-125`) are used by both `freeze` (`:1144-1149`) and `oos` (`:1298-1301`), so a freeze's canonical sha stays findable at OOS; the previously silent fall-through now raises `OOS_MODEL_RECORDS_UNRECOGNISED` (`:1313-1316`) instead of writing an analysis with no OOS metric — a gate that used to read PASS while vouching for nothing.
- **Blast radius for this study.** `model.arms` is `[]` and no `cells` are declared (packet `model`), so fit produces one record and writes `model_id` (`:966`, `:974-978`); freeze and `analyze` both take the pre-existing single-model branches (`:1126`, `:1283`). Every new branch and the new op are closure-membership changes only on this study's executed path — which is exactly what a portability comparison needs.

## Referred to contract-checker

- Freeze/OOS model-integrity binding (`model_canonical_sha256` keying, `authenticate_model` expectations) and the empty `model.arms` / `model.validation` against a 2020-2023 TRAIN declaration with a single `authorized_dates` day — deliverable completeness and model-integrity declarations, not causality.

## Clean checks

A1–A5 clean (A3, A4 not applicable: host-driven collector, no strategy price lookup, no timer/alert callbacks); carried from pass 01 for the unchanged collection surface, plus A1/A5 re-verified on the delta (no new timestamp construction or resampling introduced). B1–B7, B9, B10 clean — the delta introduces no `center=True`, `.shift(-N)`, `bfill` or `merge_asof`, and no feature-path code at all. C1–C3 clean. F1–F4 clean. G1–G4 clean (G2, G4 with the carried notes). H1–H4 not applicable / clean: `outcome.contract` is `label`, `kernel: flip`, `atr: null`; no bracket simulation exists and the delta adds none.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "es_180s_model_c_portability", "auditor": "lookahead-auditor:005_causal_audit_ea737155", "audited_execution_composite_sha256": "4f766f57344718f1416cc8f827f67bac8ed4f560b4b86f2fc921e1a7742797a1", "critical": 0, "warning": 0, "note": 6}
<!-- AUDIT_SUMMARY_V2_END -->

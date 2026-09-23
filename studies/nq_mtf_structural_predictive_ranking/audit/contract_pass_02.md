audit_type: contract
study: nq_mtf_structural_predictive_ranking
auditor: contract-checker (pass 02)
audited_execution_composite_sha256: 6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a

Re-audit of the three findings from `audit/contract_pass_01.md` against the recompiled plan
(`plan_sha256: c5737cb1d2cca831430a349ddcf631f150928a6956cc65ca869058ba56fac4f0`), plus a
re-check of every item passed in pass 01 to confirm the recompile did not disturb them.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Arm defect fixed: four arms now distinct, match `research_decision.yaml session_decisions.controls` | PASS | `study.yaml:483-491` `direction_only: [dir_1m]`, `mtf_state_only: [dir_1m, dir_5m, dir_15m, dir_1h]`; identical in `compiled_plan.json:1517-1535`. `research_decision.yaml:133-137` `session_decisions.controls` describes exactly this split and records the correction was made "after contract pass 01 found direction_only and mtf_state_only declared the identical 4-column list" | none (not yet fit) — LightGBM given 4 raw direction columns can split on any subset/combination, so `mtf_state_only` now carries genuinely more information than `direction_only`'s single column; the two arms will no longer be forced to identical fits | none |
| `full` / `geometry_no_direction` arms unaffected by the fix | PASS | `compiled_plan.json:1431-1513` (`full`, 78 cols, unchanged from pass 01) and `:1536-1614` (`geometry_no_direction`, 71 non-direction cols, unchanged) | n/a | none |
| Stale authority fixed: `research_decision.yaml` status current | PASS | `research_decision.yaml:4` now `status: EXECUTING_TARGET_A`; new `blockers_resolved` block (lines 119-129) records B1 (partition re-attestation, main `bbfeb550`) and B2 (`model.target`, main `bbfeb550`) as resolved with the mechanism cited; new `session_decisions` block (lines 130-137) records `final_train_validation_years: []`, `targets_this_session: [A_win]`, and the corrected `controls` text (including explicit acknowledgment of the pass-01 finding) | none needed (documentation) | none |
| Stale handoff fixed: `CAPABILITY_GAP_HANDOFF.json` current | PASS | `state: "RESOLVED_EXECUTING"` (line 5), `capability_gap.blocking: false` (line 8), new `resolved_by: {model_feature_columns: ff47868d, model_target_and_reuse: bbfeb550}` (lines 37-40), `note: "both capability gaps closed; the study is executing Target A..."` (line 42) | none needed | Minor: `no_work_performed` (lines 25-31) and `next_session`/`ready_when_capability_lands` (lines 32-36) are leftover Phase-A text now contradicted by `resolved_by`/`note` below them — harmless (superseded in-place) but could be trimmed for clarity; not a governance defect |
| Recompile preserved: 78-column feature surface + order | PASS | `compiled_plan.json:1625-1704` byte-identical sequence to pass 01's `1628-1707` (same 78 entries, same order); `study.yaml:391-469 (&id001)` unchanged | n/a | none |
| Recompile preserved: cell `t0` | PASS | `compiled_plan.json:1618-1622` unchanged (`checkpoint_index: 0`) | n/a | none |
| Recompile preserved: fixed hyperparameters, `search_space: none` | PASS | `compiled_plan.json:1707-1716` params block byte-identical to pass 01; `search_space: {}` (line 1718) | n/a | none |
| Recompile preserved: Target A alone | PASS | `compiled_plan.json:1719-1726` `A_win: terminal_gross_pnl_atr > 0`, `expression_sha256` unchanged from pass 01; no B/C/D/E target declared anywhere in `study.yaml` or `compiled_plan.json` | n/a | none |
| Recompile preserved: `final_train_validation_years: []` | PASS | `compiled_plan.json:1727-1728`; `study.yaml:474` unchanged | n/a | none |
| Partition provenance unchanged by the arm-only recompile | PASS | `artifacts/partition_reattestation.json` and `artifacts/experiment_authorization.json` are byte-identical to the versions reviewed in pass 01 (same `current_replay_closure_composite_sha256`, same `authorization_sha256: 30b351e7…`, same `generated_at_utc` timestamps) — confirms the arm/target edit stayed inside the model-only, replay-key-neutral surface and did not force a re-attestation or re-collection | n/a | none |

## Referred to lookahead-auditor
None — no new causal claim introduced by this change; the arm correction is a modeling-surface fix, not a causality change.

## Blocking verdict

**CLEAR.**

All three findings from pass 01 are verified fixed on disk: `direction_only` and
`mtf_state_only` are now distinct arms matching `research_decision.yaml`'s
`session_decisions.controls`; `research_decision.yaml` carries a current `status`,
`blockers_resolved`, and `session_decisions` block; and `CAPABILITY_GAP_HANDOFF.json` reflects
`RESOLVED_EXECUTING` with both resolving commits named. Re-checking every item passed in pass
01 against the recompiled plan (`c5737cb1d2cc…`) shows the feature surface and its order, cell
`t0`, fixed hyperparameters with no search space, Target A alone, and
`final_train_validation_years: []` are all unchanged, and partition provenance
(`artifacts/partition_reattestation.json`, `artifacts/experiment_authorization.json`) is
byte-identical to pass 01 — confirming the arm/target correction stayed inside the model-only,
replay-key-neutral surface with no re-collection triggered. No causal, governance, or
provenance defect remains open for this pass.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "6ced7ced583a3a877a451a373b2350edc7807db3471005b74c7e1cdb1c9a924a", "auditor": "contract-checker-pass02", "critical": 0, "note": 1, "study": "nq_mtf_structural_predictive_ranking", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

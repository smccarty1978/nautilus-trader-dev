---
audit_type: "contract"
study: "s12_own_scores_gate"
pass: 1
auditor: "contract-checker"
audited_execution_composite_sha256: "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7"
---

# Contract & Governance Audit — Pass 01

**Study** `s12_own_scores_gate` (disposable platform gate, tier 2, branched from `chore/analysis-own-model-scores`
@ `c545e596`, disclosed in `research_decision.yaml:4`) · **State** pre-execution: `progress.json`
`last_successful_stage: causal_audit`, `stage: contract_audit`. Only `prepare`, `readiness`, `preflight`,
`tests`, `causal_audit` have run — `collection`/`merge`/`fit`/`freeze`/`oos`/`seal`/`analyze`/`smoke`/`close`
have not. Findings below are scoped accordingly: existence is checked where a stage has run; downstream
declarations are checked for internal consistency, not materialized-artifact existence.

## Referred items from causal audit (pass_01.md)

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Item 2 — score-time model-bytes authentication bound the same way as the OOS metrics path | PASS | `research_workflow/lifecycle_v2.py:1310-1343` `_freeze_bound_fitted_models` is the single producer of `expect.canonical_sha256` (read from `train_experiment_freeze.json:model_canonical_sha256`) for both consumers: the OOS-metrics path in `analyze()` (`lifecycle_v2.py:1598-1622`, `authenticate_model(..., expect={..., "canonical_sha256": csha})`) and the declared-analysis path `_declared_analysis` → `_join_own_model_scores` (`lifecycle_v2.py:1515-1518` → `1345-1384`, `authenticate_model(m["id"], expect=m["expect"], ...)` at line 1361). No second/independent binding path exists. | N/A — code reading only; freeze/fit have not run yet at this composite, so no live authentication call has executed | None — binding is symmetric by construction |
| Item 1 — readiness check-id set (`audit/readiness.json` has only R1/R3/R5/R8/R9/R10) | PASS (not incomplete) | `readiness()` in `lifecycle_v2.py:411-456` is the sole producer of `audit/readiness.json`; it computes exactly six check ids (`R1_<sym>` at 415-427, `R8_host_boundary_lint` at 428-430, `R5_binding_proof` at 431-432, `R3_session_table` at 433-444, `R9_closure_current` at 445-447, `R10_zero_study_python` at 448-450) and no others. A repo-wide search of `research_workflow/` finds no `R2_`/`R4_`/`R6_`/`R7_` id anywhere — they are not skipped for this study, they are not implemented by the platform at all. | `audit/readiness.json`: `overall_status: PASS`, all 6 present and `passed: true` | None for this study. Platform-level: if R2/R4/R6/R7 are intended checks, their absence is a gap in `lifecycle_v2.readiness()` itself, not a per-study contract violation — out of this study's remediation scope |

## Deliverables (`packet.deliverables_by_stage`)

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Stages that have run produced their declared file | PASS | `prepare` → `audit/frozen_execution_manifest.json` (exists, composite `73db2ed0f213…` matches packet identity) + `artifacts/experiment_authorization.json` (exists, `train_years:[2023]`, `oos_years:[2024]`, `prohibited_years:[2021,2022,2025,2026]`, `partition_windows` = the two narrowed 3-day windows) · `readiness` → `audit/readiness.json` (exists, PASS) · `preflight` → `audit/preflight.json` (exists, `status: CLEAR`) · `tests` → `_work/controller/test_summary.json` (exists) · `causal_audit` → `audit/status.json` (exists, CLEAR) | Direct file reads, all present at declared paths | None |
| `analyze` deliverable: packet declares one wrapper file (`artifacts/experiment_analysis_v2.json`); `compiled_plan.json:2-38` additionally declares two named analysis artifacts (`tail_lift.json` kind `json`, `tail_lift.parquet` kind `frame`, both `source: "tail"`, the id of the single `analysis.metric.tail_lift` step) | NOT VERIFIED | `analyze` has not run — `artifacts/` contains only `experiment_authorization.json`. The one-file-per-stage packet list and the two named sub-artifacts inside `compiled_plan.json`'s `analysis.artifacts` are not contradictory on their face (the wrapper is plausibly the container the named artifacts are written into/alongside), but nothing in the currently-executed state proves it | None yet reachable — this is a re-audit item: when `analyze` runs, confirm `tail_lift.json` and `tail_lift.parquet` both materialize (wherever the analysis writer places them) in addition to `experiment_analysis_v2.json`, and that `tail_lift.json`'s reference population is `train_frame` per `compiled_plan.json:24` |
| Stages not yet run (`collection`…`close`) | NOT APPLICABLE (pre-execution) | N/A | N/A | Re-audit at those stages' completion |

## TRAIN/OOS separation and authorization

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| TRAIN/OOS/prohibited years disjoint; authorization not stale | PASS | `artifacts/experiment_authorization.json`: `train_years:[2023]`, `oos_years:[2024]`, `prohibited_years:[2021,2022,2025,2026]` — disjoint. `generated_at_utc: 2026-09-09T05:48:30` is the same session as `frozen_execution_manifest.json` (`05:48:30`) and `readiness.json` (`05:48:36`) — not stale | Direct file read | None |
| `source: oos` analysis is gated by protected-period authorization | PASS (by code, not yet exercised) | `compiled_plan.json:19` `analysis.source == "oos"`; causal pass_01 already traced `assert_oos_open(self.study)` running before either `frame` or `train_frame` is built (`lifecycle_v2.py:1495`, cited in `audit/pass_01.md` line 37) | Not yet exercised at runtime (analyze hasn't run) | None |

## Terminal-decision reachability

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| `terminal_decisions: {}` in `research_decision.yaml:8` — is an empty contract acceptable for this gate? | PASS / NOT APPLICABLE | `research_workflow/study_closure.py:46-68`: the reachability check is conditioned on `declared = ... .get("terminal_decisions") or {}`; when empty, no declared label set exists to validate a closure decision against, so `close()` does not constrain `--closure-decision` to a fixed vocabulary. This study is `disposable: true` (`research_decision.yaml:5`) and its `research_question` is a platform plumbing check, not a PROMOTE/REJECT research verdict — there is no terminal label being declared and left unreachable, which is the shape of the historical CRITICAL (a label declared but not wired to any code path). Here nothing is declared, so nothing can be unreachable | `study_closure.py:46-68` read directly | None. If a future non-disposable study reuses this pattern, `terminal_decisions: {}` should still be flagged then — it is acceptable here specifically because the study is disposable and produces no decision |

## Provenance / lifecycle freshness

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Platform-branch disclosure present | PASS | `research_decision.yaml:4-5`: `platform_branch: "chore/analysis-own-model-scores"`, base commit `c545e596`, `disposable: true` | Direct file read | None |
| Audited execution composite is current | PASS | `audit/frozen_execution_manifest.json: frozen_execution_composite_sha256 = 73db2ed0f213…` == packet `identity.execution_composite_sha256` == `audit/readiness.json` `execution_composite_sha256` == `audit/preflight.json` `execution_composite_sha256` == `tests.execution_composite_sha256` in the packet | Direct file reads, all identical | None |
| Causal and contract reviews have distinct declared identities | PASS | `audit/status.json`: `auditor: "lookahead-auditor:s12_own_scores_gate_causal_pass01"`; this report: `auditor: "contract-checker"` | Direct file read | None |
| Seal binds report bytes to composite | NOT APPLICABLE | `seal` stage has not run — `artifacts/preexec_audit_seal.json` does not exist yet | N/A | Re-audit once `seal` runs |
| TRAIN artifacts frozen before any OOS artifact produced | NOT APPLICABLE | `freeze`/`oos` stages have not run — no `train_experiment_freeze.json`, no OOS partition outputs exist yet | N/A | Re-audit once those stages run |

## Model-integrity declarations

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| `model_scores: true` gated to `mode: train` studies only (not `mode: score`) | PASS | `compiler.py` gap rule cited in `audit/pass_01.md:41`: `if spec.model_scores and (model == "none" or model.mode != "train"): ctx.gap(...)`. `compiled_plan.json` model mode is `train`, packet `model.mode: "train"` | Compiler-level static check; no runtime evidence yet needed | None |
| Freeze-bound authentication (`expect.canonical_sha256`) applied uniformly at score time | PASS | See "Referred items" table item 2 above | Not yet exercised at runtime | None |

## Blocking verdict

**CLEAR.** All checks reachable at this pre-execution composite pass; both items referred by the causal
auditor resolve cleanly (symmetric freeze-binding producer; the six-check readiness set is the platform's
complete implementation, not a per-study omission). The `analyze`-stage two-artifact declaration
(`tail_lift.json`/`tail_lift.parquet`) is `NOT VERIFIED` only because `analyze` has not executed yet — it
is not a blocking defect at this composite, but must be re-checked once `analyze` runs and produces those
artifacts (or fails to). `terminal_decisions: {}` is acceptable given `disposable: true` and no declared
decision vocabulary. No CRITICAL or WARNING findings.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "73db2ed0f21316e4c0a5b04790a37910824f37dc67d964a30d020c39dc6b75f7", "auditor": "contract-checker", "critical": 0, "note": 1, "study": "s12_own_scores_gate", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

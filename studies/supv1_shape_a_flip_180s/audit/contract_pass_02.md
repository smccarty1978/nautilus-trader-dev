# Contract & Governance Audit — Pass 02

**Date** 2026-09-05 · **Study** `supv1_shape_a_flip_180s` (Supervisor V1 validation rerun of the closed
reference `v2_shape_a_flip_180s`) · **Auditor** `contract-checker:006_contract_audit_1bd4f68c`
**Primary surface** `_work/controller/audit_packet_contract.json`. Resolved from it: `study.yaml`,
`research_decision.yaml`, `SPEC.md`, `audit/{frozen_execution_manifest,readiness,preflight,status,contract_pass_01}.{json,md}`,
`artifacts/{experiment_authorization,compile_card,SUPERVISOR_V1_VALIDATION_CARD}.json`,
`_work/controller/{status,test_summary,failure_packet}.json`, `research_workflow/grammar/compiler.py`,
`research_workflow/{governed_controller,governed_controller_v2,workflow_engine,workspace,audit_packets_v2,controller_contracts}.py`,
`PLATFORM_STATE.json`, and causal pass 02 (`lookahead-auditor:005_causal_audit_d9c46349`).
**Audited composite** `34a0dab471d851d916b1d973dd986b48cd462c472709017a9ef110717cd58ac5`
**Verdict** CLEAR — Critical 0 · Warning 4 · Note 4

**Bounded re-audit.** Pass 01 blocked at `a563bbf1…` on C-1. Since then only the closure changed:
`git diff` of `compiled_plan.json` is 110 added / 5 removed lines, all of them closure membership,
`file_count` 45→90, the three stage/plan composites and the `compiler.py` hash. **No line of the
population, features, chronology, model, outcome or columns surface moved.** I re-verified every
requirement at the new composite and re-tested pass-01's carried findings.

**Deliverable authority.** `packet.deliverables_by_stage` (the `lifecycle_v2.DELIVERABLES` constant,
`audit_packets_v2.py:32`). No `config/deliverables_contract.json` exists and none is expected for a V2
study. I consumed the packet's set; I did not reconstruct one.

## Requirements

| Requirement | Verdict | Evidence | Smallest remediation |
|---|---|---|---|
| `study.yaml` is the reference verbatim, `id:` only | PASS | `git diff --no-index studies/v2_shape_a_flip_180s/study.yaml …/supv1_…/study.yaml` → one hunk, line 5 | — |
| `research_decision.yaml` as instructed (DRAFT, `NQ_1S_V2`, `terminal_decisions`, default `autonomy_decisions`, no merge keys) | PASS | `research_decision.yaml:4-17`, unchanged since `c49d8140` | — |
| **C-1 (pass 01) — closure covers the executable scientific surface** | **FIXED** | manifest now lists `features/trackers/{regime_dual_ema,rolling_5m_productivity,structural_regime_geometry}.py` (lines 23-25); `compiler.py:1318` `transitive_closure_files(ctx.closure_files)`; regression test named in `PLATFORM_STATE.closure_resolution` | — |
| Audited composite is current | PASS | `readiness.R9` `current=34a0dab471d8 frozen=34a0dab471d8`; `preflight.EXECUTION_MANIFEST=PASSED`; `status.json.fingerprints` `current_execution_composite == execution_composite == plan_closure_composite` | — |
| Closure covers the executable **control** surface | WARNING | W-4 | walk stage sets, not just `collection` |
| Preflight ran every required check and passed | PASS | 8/8 required `PASSED`, `status: CLEAR`, `leaked_outcome_columns: []` | — |
| Readiness passed | PASS | `overall_status: PASS`; R1/R3/R5/R8/R9/R10 all pass (V2 emits these six only) | — |
| Causal and contract reviews have distinct identities | PASS | `audit/status.json` `lookahead-auditor:005_causal_audit_d9c46349` (CLEAR, 0/0/4) vs. this pass | — |
| Seal binds report bytes to the audited composite | NOT APPLICABLE | pre-seal; this report is an input to it | — |
| TRAIN/dev/prohibited disjoint; authorization fresh | PASS | `experiment_authorization.json` train `[2021]` / oos `[2022]` / prohibited `[2023-2026]`, regenerated 17:56:06 at this composite; `year_role_table` gives each year exactly one role | — |
| Authorized smoke date inside TRAIN | PASS | `2021-01-05` ∈ train `[2021]` | — |
| Frozen feature set free of forward-outcome columns | PASS | `FORWARD_OUTCOME_GUARD=PASSED`; `target_flip_within_horizon` appears only in `columns.observation` | — |
| Every primitive maps to one runtime implementation | PASS | `R5_binding_proof` 16 bound, `unbound=[]`; `binding_proof` 3 trackers + 13 feature columns; `compile_card.features: 13` | — |
| Identity columns on every row | PASS | `columns.identity` = `observation_ts/regime_start_ns/checkpoint_index` | — |
| TRAIN freeze precedes OOS · `derivation_population` · partition reconciliation · `forward_outcome_manifest` | NOT APPLICABLE | no execution artifacts exist; state `NEEDS_CONTRACT_AUDIT` | — |
| Model-arm delta integrity | NOT APPLICABLE | `model.arms: []`, `outcome.arms: []` — no delta claimed | — |
| Model determinism declared | PASS | `deterministic: true`, `n_jobs: 1`, `random_state: 42`; see N-1 | — |
| Zero study Python (tier 2) | PASS | `ZERO_STUDY_PYTHON`, `R10`, `study_python.python_files: []` | — |
| Deliverables exist for every stage run | PASS | compile→`compiled_plan.json`; prepare→`frozen_execution_manifest.json`+`experiment_authorization.json`; readiness/preflight→`audit/*.json`; tests→`test_summary.json`; causal_audit→`audit/status.json` | — |
| Tests green at the audited composite | PASS | `test_summary.json` 110 passed / 0 failed, `execution_composite_sha256 = 34a0dab4…`, run from the study worktree | — |
| SPEC bound and non-vacuous | WARNING | W-2 (carried, unchanged) | — |
| Dataset authorization / provenance | WARNING | W-1 (carried) | — |
| Execution provenance of the freeze | WARNING | W-3 (divergence gone in fact, gate still absent) | — |

## W-4 — the transitive walk covers `collection` only; `workflow_engine.py` executes outside the freeze

`compiler.py:1318` walks imports for the **collection** stage set; `:1320-1325` take `lifecycle`,
`modeling`, `oos`, `outcome`, `audit` from `STAGE_CLOSURE_MODULES` literally. Sweeping that residue:
every repo-local import of the stage-only members (`governed_controller_v2`, `controller_contracts`,
`workspace`, `audit_packets_v2`) resolves inside the 90-file manifest **except**
`research_workflow/workflow_engine.py` (323 lines, `governed_controller.py:18`, a module-import-time
dependency of the V2 controller) and its own lazy `study_spec_compiler.py` (V1-only path). `workflow_engine`
supplies `_read`/`_sha`/`_clear`, used in `governed_controller.py:155-156` — the check that decides whether
an audit is *current against the frozen composite* — and in stage-receipt verification (`:303-324`). So the
freeze does not cover part of the code that evaluates the freeze. This is the same defect class as C-1 on
the control plane; unlike C-1 it touches no label, feature, population or metric, so it cannot change any
number this study produces. **Remediation:** apply `transitive_closure_files` to every stage set, not just
`collection` — a second `chore/` branch (§N.1), not study-side work. Also referred by causal pass 02.

## W-1 — a new study binds the SUPERSEDED `NQ_1S_V2`, still with no gate (carried, partially disclosed)

Unchanged in substance: `study.yaml:9` binds `NQ_1S_V2`, marked `SUPERSEDED` in `PLATFORM_STATE.json:45-53`;
`readiness.R1_NQ` verifies bytes against the digest and nothing checks id status. The binding is instructed
(the reference YAML verbatim). Newly disclosed platform-side as open warning `W-1-superseded-dataset-id`; no
**study** artifact records it yet, and `R3_session_table` confirms the divergent floor-calendar reference
(`0db1f14b…`, 1632 windows vs. the current Globex `e577a361…`, 1636 sessions). **Remediation:** record the
deliberate legacy binding in the study closure so no result is compared against a Globex-calendar study.

## W-2 — `SPEC.md` is unpopulated scaffold (carried, unchanged)

`## Population`, `## Target`, `## Features`, `## Chronology`, `## Deliverables Manifest` are all empty;
only the question renders. `PLAN_BOUND_TO_SPEC` is hash equality, so it passes identically either way. The
second-ranked authority in the declared precedence is vacuous; I verified the domain contract against
`study.yaml`/`compiled_plan.json` instead. **Remediation:** render SPEC sections at compile time.

## W-3 — the freeze still records no resolving checkout (carried; this run's divergence is closed)

`_work/controller/status.json.worktree` now reads `branch: study/supv1_shape_a_flip_180s`,
`head: 1b411b6f`, `path: …-supv1_shape_a_flip_180s`, and `test_summary.json.files` are all inside that
worktree — so the pass-01 main-vs-study split (also DEV-05) does not apply to `34a0dab4…`. But
`frozen_execution_manifest.json` still carries no `resolving_head`/`branch` key, so nothing *enforces* it.
**Remediation:** record the resolving checkout's head in the manifest; fail readiness on mismatch.

## Notes

- **N-1** (carried) the declared `validation.model_selection.random` is inert — no `model.search_space`, so
  `lifecycle_v2` never calls `tune`; `max_trials`/`primary_metric`/`random_seed` are null and unreached. The
  deliverable set correctly omits `artifacts/tuning_trials.json`. Decorative, not a defect.
- **N-2** (carried) terminal-label reachability is vacuous: `terminal_decisions` holds
  `{reference_study, purpose}`, i.e. provenance, not labels. A Supervisor V1 validation drawn from this
  study cannot claim the terminal-label path was tested.
- **N-3** (carried) `deliverables_by_stage` is platform-level and identical for every V2 study; it cannot
  express or detect study-specific scope loss. Adequate here — this study declares none.
- **N-4** all eight audited artifacts are **uncommitted** (`status.json.worktree.dirty_paths`), and two
  stale files from the pass-01 composite remain on disk: `audit/contract_status.json` (BLOCKED @`a563bbf1`,
  overwritten by ingest) and `_work/controller/failure_packet.json` (`CONTRACT_BLOCKER` @`a563bbf1`, while
  `status.json.failure_packet` is `null`). `PLATFORM_STATE.remaining_warning` puts the trust boundary at
  bytes committed at HEAD. **Remediation:** commit the regenerated prepare/readiness/preflight/audit
  artifacts and clear the stale failure packet before the seal.

## Referred to lookahead-auditor

Nothing new. Causal pass 02 is CLEAR at this composite; its four notes (zero-lead positives, floor-calendar
session table — see W-1, no gap protection on the flip kernel, inert `ema_slope` lookback) are causal-scope.

## Blocking verdict

**CLEAR.** C-1 is fixed at the root: the collection closure is now resolved by a transitive first-party
import walk, the manifest grew 45→90 files, and the three modules that define this study's label event and
all thirteen features — `regime_dual_ema.py`, `rolling_5m_productivity.py`, `structural_regime_geometry.py`
— are inside the freeze, with R9, `EXECUTION_MANIFEST` and the plan closure all agreeing on
`34a0dab471d8`. Nothing else moved: the study contract is still the reference verbatim, chronology roles
are disjoint and match the authorization artifact regenerated at this composite, the feature surface carries
no outcome column, there is no study Python, 110/110 selected tests pass at the audited composite, and every
deliverable for every stage actually run exists. The four warnings are each a declared rule with no
executable gate behind it (W-1, W-3), a vacuous second authority (W-2), or a residual control-plane hole in
the same closure defect class (W-4); none of them changes a number this study will produce, and all four are
platform work for a `chore/` branch, not study-side repair. I did **not** verify anything downstream of the
seal — no collection, fit, freeze, OOS or analysis artifact exists yet, so those requirements are NOT
APPLICABLE rather than passed.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "supv1_shape_a_flip_180s", "auditor": "contract-checker:006_contract_audit_1bd4f68c", "audited_execution_composite_sha256": "34a0dab471d851d916b1d973dd986b48cd462c472709017a9ef110717cd58ac5", "critical": 0, "warning": 4, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->

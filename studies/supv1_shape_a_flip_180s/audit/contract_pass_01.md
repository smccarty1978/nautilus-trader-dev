# Contract & Governance Audit — Pass 01

**Date** 2026-09-05 · **Study** `supv1_shape_a_flip_180s` (Supervisor V1 validation rerun of the closed
reference `v2_shape_a_flip_180s`) · **Auditor** `contract-checker:003_contract_audit_182864f7`
**Primary surface** `_work/controller/audit_packet_contract.json`. Resolved from it:
`study.yaml`, `research_decision.yaml`, `SPEC.md`, `audit/{frozen_execution_manifest,readiness,preflight,status}.json`,
`artifacts/experiment_authorization.json`, `_work/controller/{status,test_summary}.json`,
`research_workflow/{lifecycle_v2,closure_hash,audit_packets_v2}.py`, `research_workflow/grammar/compiler.py`,
`features/trackers/{host_bindings,generic_rolling_productivity,generic_structural_geometry}.py`,
`PLATFORM_STATE.json`, `WORKFLOW.md` §N/§O, and the causal pass `002_causal_audit_6b6cdc45`.
**Audited composite** `a563bbf1bf954c6836e6af03b60afbfbebc1d150d84cab051930fe6ea747387a`
**Verdict** BLOCKED — Critical 1 · Warning 3 · Note 3

**Deliverable authority.** This is a Platform-V2 study: the declared set is
`packet.deliverables_by_stage`, built from the `research_workflow.lifecycle_v2.DELIVERABLES` constant
(`audit_packets_v2.py:37-44`). There is no `studies/<id>/config/deliverables_contract.json` and none is
expected — that file is the legacy V1 study-factory artifact. I consumed the packet's set; I did not
reconstruct one.

## Requirements

| Requirement | Verdict | Evidence | Smallest remediation |
|---|---|---|---|
| `study.yaml` is the reference study verbatim, `id:` only | PASS | `diff studies/v2_shape_a_flip_180s/study.yaml studies/supv1_shape_a_flip_180s/study.yaml` → one hunk, line 5, `id:` | — |
| `research_decision.yaml` fields as instructed (DRAFT, `NQ_1S_V2`, `terminal_decisions`, default `autonomy_decisions`, no `platform_merge`/`closed_study_merge`) | PASS | `research_decision.yaml:4-17` | — |
| Deliverables exist for every stage actually run | PASS | compile→`compiled_plan.json`; prepare→`audit/frozen_execution_manifest.json` + `artifacts/experiment_authorization.json`; readiness/preflight→`audit/{readiness,preflight}.json`; tests→`_work/controller/test_summary.json`; causal_audit→`audit/status.json` | — |
| Deliverables for stages not yet run (merge, fit, freeze, oos, analyze, seal, close, smoke, reconcile, collection) | NOT APPLICABLE | state `NEEDS_CONTRACT_AUDIT`; those stages have not executed | — |
| Audited composite is current | PASS | `readiness.R9_closure_current` `current=a563bbf1bf95 frozen=a563bbf1bf95`; `preflight.EXECUTION_MANIFEST=PASSED`; `status.json.fingerprints.current_execution_composite == execution_composite` | — |
| **Closure covers the executable scientific surface** | **FAIL** | C-1 below | add the imported implementation modules to `ctx.closure_files` |
| Preflight ran every required check and passed | PASS | `preflight.json` 8/8 required checks `PASSED`, `status: CLEAR`, `leaked_outcome_columns: []` | — |
| Readiness passed | PASS | `readiness.json` `overall_status: PASS`, all 6 emitted checks pass. V2 emits R1/R3/R5/R8/R9/R10 only (`lifecycle_v2.py:390-435`); R2/R4/R6/R7 are V1 ids with no V2 counterpart | — |
| Causal and contract reviews have distinct identities | PASS | `audit/status.json` `lookahead-auditor:002_causal_audit_6b6cdc45` vs. this pass | — |
| Seal binds report bytes to the audited composite | NOT APPLICABLE | pre-seal; this report is an input to the seal | — |
| TRAIN/dev/prohibited disjoint; authorization fresh | PASS | `experiment_authorization.json` train `[2021]` / oos `[2022]` / prohibited `[2023-2026]`, generated 15:09:02 from the same plan; `year_role_table` gives each year exactly one role | — |
| Authorized smoke date inside TRAIN | PASS | `2021-01-05` ∈ train `[2021]` | — |
| Frozen feature set free of forward-outcome columns | PASS | `preflight.FORWARD_OUTCOME_GUARD=PASSED` over `columns.features` + `columns.metadata`; label `target_flip_within_horizon` lives only in `columns.observation` | — |
| TRAIN freeze precedes OOS · `derivation_population` · partition reconciliation · `forward_outcome_manifest` | NOT APPLICABLE | no execution artifacts exist yet | — |
| Model-arm delta integrity | NOT APPLICABLE | `model.arms: []`, `outcome.arms: []` — no delta is claimed | — |
| Model determinism declared | PASS | `deterministic: true`, `n_jobs: 1`, `random_state: 42`; see N-1 | — |
| Zero study Python (tier 2) | PASS | `preflight.ZERO_STUDY_PYTHON`, `readiness.R10`, `study_python.python_files: []` | — |
| SPEC is bound and non-vacuous | WARNING | W-2 | — |
| Dataset authorization / provenance | WARNING | W-1 | — |
| Execution provenance (which checkout produced the freeze) | WARNING | W-3 | — |
| Tests green at the audited composite | PASS | `test_summary.json` 110 passed / 0 failed at `a563bbf1…` | — |

## C-1 (CRITICAL) — the frozen closure omits the modules that compute the labels and the features

`audit/frozen_execution_manifest.json` freezes 45 files. Three modules that execute on every checkpoint are
not among them:

- `features/trackers/regime_dual_ema.py` — `DualEmaRegimeTracker`, imported at `host_bindings.py:104`. It
  defines the 1m regime, therefore the population anchor, `regime_age_seconds`, the direction **and the
  label event** `regime_1m.flipped`.
- `features/trackers/rolling_5m_productivity.py` — imported at `generic_rolling_productivity.py:9`; computes
  all four `rolling_300s_*` features.
- `features/trackers/structural_regime_geometry.py` — imported at `generic_structural_geometry.py:12`;
  computes all six `prior_{1m,5m}_regime_*` features.

The closure is a flat, explicitly accumulated set with no transitive import walk: `compiler.py:386` and
`:494` add only the bound class's own module (`cls.__module__`, `canonical_provider`'s module), and
`compiler.py:1236-1266` hashes exactly `stage_sets` with no expansion. So the binding shims are frozen and
the implementations they delegate to are not. Editing `regime_dual_ema.py` — a different EMA period, a
different ATR rule — changes every label and every feature in this study while `current_composite()`
(`lifecycle_v2.py:302-307`) is unchanged, so `R9_closure_current`, `preflight.EXECUTION_MANIFEST`, the
freeze and any seal written against it all still pass. This defeats the requirement the freeze exists to
serve, and it contradicts the compiler's own stated design (`compiler.py:46-48`: the collection closure is
"host modules + bound provider/tracker/feature modules"). This is inherited platform behaviour, not
introduced by this study; it is the same defect the causal auditor referred to me, verified independently
here. **Smallest remediation:** in `_closure` / the tracker- and feature-binding paths, walk first-party
imports of each closure member transitively (the machinery already exists —
`closure_hash.wildcard_import_targets` uses `resolve_module_to_path` for exactly this shape), then
re-run PREPARE and readiness. Platform work: a `chore/` branch and a fresh session (§N.1), not a study-side
repair.

## W-1 — a new study binds a SUPERSEDED dataset id, and no gate refuses it

`PLATFORM_STATE.json:45-53` marks `NQ_1S_V2` `SUPERSEDED`, retained "for sealed historical authority only …
never rebuilt, never bound by new studies". This is a new study and it binds `NQ_1S_V2`
(`study.yaml:9`, `packet.instruments.NQ`). Nothing refuses it: `readiness.R1_NQ` only resolves the id and
verifies bytes against the digest, and there is no id-status check anywhere in readiness or preflight — a
declared platform rule wired to no gate. The binding is deliberate and instructed
(`research_decision.yaml:3` requires the reference study's YAML verbatim, `dataset_id: NQ_1S_V2`), and
`bars_identical_to_current: true`, so only the session/calendar reference differs (floor-calendar digest
`0db1f14b…`, 1632 windows, vs. the current Globex authority `e577a361…`, 1636 sessions). No study artifact
discloses that choice. **Remediation:** (a) record the deliberate legacy binding and its early-close
divergence in the study's closure/report so no result from it is compared against a Globex-calendar study;
(b) platform-side, have readiness fail a `SUPERSEDED` dataset id unless the plan declares an explicit
exception.

## W-2 — `SPEC.md` is unpopulated scaffold, and `PLAN_BOUND_TO_SPEC` cannot detect that

`studies/supv1_shape_a_flip_180s/SPEC.md` has empty `## Population`, `## Target`, `## Features`,
`## Chronology` and `## Deliverables Manifest` sections; only the research question is rendered.
`research_decision.yaml:1` declares the precedence `research_decision.yaml > SPEC.md > study.yaml >
compiled_plan.json`, so the second-ranked authority is vacuous. `preflight.PLAN_BOUND_TO_SPEC` compares
`plan.spec_sha256` to `spec_sha256(study)` (`lifecycle_v2.py:440`) — real tamper-binding, but hash equality
only; it passes identically whether the SPEC declares the domain contract or nothing at all. No independent
declaration exists against which the compiled plan's partition grid, boundary convention or completeness
behaviour could be checked; I verified those against `study.yaml`/`compiled_plan.json` instead.
**Remediation:** render the SPEC sections from the compiled plan at compile time (platform-side).

## W-3 — the freeze was resolved in a different checkout from the one that holds the contract

`_work/controller/status.json.worktree` records `branch: main`, `head: a33b1460`,
`path: …\Projects\Nautilus Trader`, and `test_summary.json.files` are all under that same main checkout —
while the study contract lives on `study/supv1_shape_a_flip_180s` @ `c49d8140` in the study worktree that
the packet names as `expected_worktree`. I reconciled it: `git diff --stat a33b1460 c49d8140` touches only
`studies/supv1_shape_a_flip_180s/{SPEC.md,study.yaml,research_decision.yaml,compiled_plan.json}`, so every
closure file is byte-identical in both checkouts and `a563bbf1…` is valid for this study **at this commit**.
Nothing enforces that. If the study worktree ever carried merged platform work that `main` lacked, the
controller would resolve `current_composite()` from `main`'s bytes and compare it to a freeze also written
from `main`'s bytes — R9 and `EXECUTION_MANIFEST` would agree with each other and both would be wrong for
the study. **Remediation:** record the resolving checkout's head in `frozen_execution_manifest.json` and
fail readiness when it differs from the study worktree's head.

## Notes

- **N-1 — the declared validation protocol is inert.** `validation.protocol:
  validation.model_selection.random` with `tuning_years: [2021]`, but the plan declares no
  `model.search_space`, and `lifecycle_v2.py:809` runs `tune(...)` only when one exists. No tuning happens;
  the declared params are fitted directly. `max_trials`, `primary_metric` and `random_seed` are all null and
  their defaults (`tuning.py:155-174`) are never reached. Contract and implementation agree — the packet's
  deliverable set correctly omits `artifacts/tuning_trials.json` — so this is a decorative declaration
  carried verbatim from the reference study, not a defect.
- **N-2 — terminal-label reachability is vacuous here.** `terminal_decisions` carries
  `{reference_study, purpose}`, i.e. provenance metadata, not decision labels. There is nothing to prove
  reachable. Correct for an infrastructure-validation rerun, but it means this study exercises none of the
  terminal-label machinery: a Supervisor V1 validation drawn from it cannot claim that path was tested.
- **N-3 — the V2 deliverable contract is platform-level, not study-level.** `deliverables_by_stage` is the
  `lifecycle_v2.DELIVERABLES` constant plus one plan-conditional entry (`audit_packets_v2.py:37-44`), so it
  is identical for every V2 study. It cannot express a study-specific deliverable, and therefore cannot
  detect study-specific scope loss. Adequate for this study, which declares none.

## Referred to lookahead-auditor

Nothing. The causal pass at this composite is CLEAR; its notes N1 (`inclusive_start` zero-lead positives),
N2 (floor-calendar session table — see W-1) and N3 (no gap protection on the flip kernel) stand as written
and are causal-scope, not contract-scope.

## Blocking verdict

**BLOCKED.** Everything the study itself declares is honoured: `study.yaml` is the reference verbatim, the
chronology roles are disjoint and match the authorization artifact, preflight and readiness are complete and
green, the feature surface carries no outcome column, there is no study Python, and every deliverable for
every stage that has actually run exists. The block is C-1 and it is not a study defect: the platform's
frozen execution closure does not cover `regime_dual_ema.py`, `rolling_5m_productivity.py` or
`structural_regime_geometry.py`, so sealing this study would bind an audit report to a composite that omits
the code defining its labels and its thirteen features — a freeze that cannot vouch for the deliverable it
is vouching for. Because the fix is shared platform code (`research_workflow/grammar/compiler.py`), it
belongs in a `chore/` capability session under §N.1, not in a study-side deterministic repair; after the
merge, PREPARE, readiness, preflight and both audits must be re-run at the new composite. W-1 and W-3 are
each a declared rule with no executable gate behind it and should be fixed in the same sweep. No causal
finding contributed to this verdict.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "study": "supv1_shape_a_flip_180s", "auditor": "contract-checker:003_contract_audit_182864f7", "audited_execution_composite_sha256": "a563bbf1bf954c6836e6af03b60afbfbebc1d150d84cab051930fe6ea747387a", "critical": 1, "warning": 3, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->

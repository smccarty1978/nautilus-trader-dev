# Cleanup, closure, and model status -- report

Branch `chore/cleanup_and_closure` off `main` `9be6eba2`. Seven commits, one per packet item
(C1-C3 share one commit because they are one function's semantics; C4 is its own). Human-attended
session; `study result --packet` was not used (PACKET_BODY_MISSING by design). This report is the
deliverable.

| # | commit | item |
|---|---|---|
| 1 | `ee9f9ec6` | A1 materializer + activation ceremony removed; `verified` has one writer |
| 2 | `f6f1dd8e` | A2 six one-time migration scripts removed |
| 3 | `b4cef72e` | A3 two LEGACY agents removed everywhere; `sync_agents --check` OK |
| 4 | `6a88110d` | B1 grandfather record, B2 site-9 tightening, B3 final-evidence freshness |
| 5 | `8e928388` | C1-C3 closure is the gate; `reuse_status` is the hard block; `assign_scientific_status` retired |
| 6 | `1b990d36` | C4 `WORKFLOW.md` line 336 corrected |
| 7 | (this commit) | report, evidence, `WORKFLOW_REFERENCE_FACTS.md` gate entry |

---

## Part A -- migration removals

### A1 -- materializer and activation ceremony (one door, removed together)

What the door was. `scripts/_legacy_reconcile_study_capabilities.py::reconcile` -- still bound by the
workflow engine as its capability leaf via the deprecated shim -- re-ran
`materialize_feature_candidate.py`, wrote `status: "verified"` / `lifecycle_status: "verified"`
straight into `features/authority/candidate/*.json` for the study's requested scopes, authorized
itself from the study's own audit files and called `activate_pipeline_candidate`, which re-pointed
`features/authority/active.json`. That is the second door to `verified`, and it needed a sealed
authorizing study -- the loop THE REHEARSAL hit.

Removed: `scripts/materialize_feature_candidate.py`, `prepare_feature_candidate.py`,
`authorize_feature_candidate_activation.py`, `activate_feature_pipeline_v2.py`,
`materialize_scoped_promotions.py` (writer of `feature_scoped_promotions.json`),
`_legacy_reconcile_study_capabilities.py`; `freeze_candidate`, `activate_frozen_candidate`,
`activate_pipeline_candidate` in `features/candidate_authority.py`; the six tracked
`scratch/feature_system_v2_*` / `generate_feature_system_v2_mapping.py` materializer inputs
(the other ~288 tracked `scratch/` files are unrelated debug scripts and were not touched).

Preserved as data: `features/authority/candidate/` (bundle, untouched bytes), `load_authority`
(the reader), `resolve_candidate_aliases`, the 36 legacy aliases (`features/definitions/legacy_instances.py`),
`features/feature_scoped_promotions.json` / `feature_definition_promotions.json` (closure data for
sealed studies; still read by `check_feature_promotion.check_scoped_promotions`).

Left in place, with reasons (not removed, not refactored):
- `research_workflow/feature_candidate_authority.py` and `scripts/check_candidate_promotion.py`: readers
  on the candidate-mode branches of `preflight.py`, `seal.py`, `causal_audit.py`, `contract_audit.py`,
  `resolve_execution_manifest.py`. `deep_pullback_5s_reacceleration_model` (sealed, closed) still has a
  `feature_candidate.yaml`, so `resolve_execution_manifest` calls `validate()` on every re-resolution
  of that study; five sealed frozen manifests pin `feature_candidate_authority.py` and one pins
  `check_candidate_promotion.py`. Removing them is a refactor of five core modules with a sealed
  consumer -- out of this packet's "removals only" scope. They cannot set `verified`.
- `scripts/reconcile_study_capabilities.py` keeps its DEPRECATED card (exit 2; `test_duplicate_orchestrators_are_deprecated_shims`)
  and its `reconcile` symbol, which `workflow_engine.py:41` still imports. The leaf now returns
  `{"state": "TRUE_CAPABILITY_GAP", "error": "CAPABILITY_RECONCILIATION_RETIRED", ...}` and performs no I/O;
  the engine surfaces that state as terminal-blocked without writing `capability_reconciliation.json`.

Gates:
- `research feature verify structural_max_expansion_checkpoint_atr` OK; `promote` -> PROMOTED
  (rewrites only `promoted_at_utc`; restored before commit). Compiles: `test_the_rehearsal_feature_resolves_verified_and_compiles`
  in `features/tests/test_feature_promotion_path.py` (33 promotion tests pass).
- 16 tracked `compiled_study.json` plans, 731 instances, re-resolved through `resolve_feature_request`:
  digest `92325805de…` before A1 and after A1 (`evidence/p6_before.json`, `evidence/p6_after_a1.json`;
  the digest formula is this session's, not the previous chore's `4ee011f5…`).
- No remaining path can set `verified` except `features/promotion.py`: `git grep` over tracked
  non-test modules finds no `lifecycle_status … "verified"` assignment and no writer of `ACTIVE_POINTER`;
  asserted by `features/tests/test_verified_single_writer.py` (5 tests: writers absent, entry points
  absent, tracked-module scan, promotion-record writer unique, engine leaf mutates nothing).
- `cap generate --check` OK (`8cd68dde…`).

### A2 -- one-time parity and archival scripts

Removed `run_full_legacy_feature_parity.py`, `audit_full_feature_system_v2_inventory.py`,
`migrate_cleanflip_feature_instances.py`, `archive_legacy_feature_registry.py`,
`restore_legacy_feature_file.py`, `build_canonical_promotion_inventory.py`. Each was named only by
the historical table in `docs/RESEARCH_WORKFLOW.md` (and one archive forensics snapshot); no test,
config allowlist, CLI path or frozen manifest names them. `restore_legacy_feature_file.py` was a
rollback tool for a cutover that is sealed into every study since; the archive it read
(`features/archive/legacy_registry_2026_08_22/`, with README) is kept. Parity tooling that still
earns its place (`scripts/parity/*`, `find_first_parity_divergence.py`, `verify_collector_parity.py`)
is untouched. Nothing ambiguous was found.

### A3 -- the two LEGACY agents

Removed `.claude/agents/{research-executor,capability-router}.md`, their generated
`.codex/agents/*.toml` and `.agents/agents_staging/*.md`, their `CODEX_META` entries, rows in
`AGENTS.md` §11, `docs/AI_AGENTS.md`, `docs/SUBAGENT_ROSTER.md` (now "five roles"; the redesign
history table records the removal), `docs/RESEARCH_STUDY_BLUEPRINT.md`, `CODEX.md` and both
`AGENT_WORKFLOW.md` tables, and the tuples in `test_concurrent_research_docs.py`.
`scripts/route_study_capabilities.py` (the router's only tool, referenced by nothing else) went with
it. `python scripts/sync_agents.py` re-run; `--check`: `AGENT PARITY: OK (12 generated files)`.

---

## Part B -- closure fixes

### B1 -- grandfather, do not re-close

Facts (from the committed closures): all five have `bound_evidence` = seal + TRAIN freeze only and
`experiment_analysis_v2.json` on disk (ES also `analysis_decision.json`); all `closed_at_utc` precede
the rule commit `5d3aad6a` (2026-09-07T12:45:25Z): 09-02 20:14Z, 09-02 20:43Z, 09-03 00:06Z,
09-04 18:31Z, 09-07 02:50Z. Closure `plan_sha256` == `compiled_plan.json` == analysis `plan_sha256`
for all five.

Implementation: `research_workflow/study_closure_grandfather.json` (rule, rule commit, cutoff, and per
study `closed_at_utc`, closure commit, canonical closure hash, canonical hashes of the final-evidence
files). `study_closure._require_mandatory_bound_evidence` consults it only when V2 final evidence is
present but unbound; the entry applies only if the study is listed, `closed_at_utc` equals the recorded
value and precedes the cutoff, the closure file hashes to the record, and every final-evidence file
on disk hashes to the record (otherwise `STUDY_CLOSURE_EVIDENCE_MISMATCH`). `load_grandfather_record`
refuses any entry at or after the cutoff, so the record cannot be widened past the rule. Hashes are
CRLF-normalised (seal-system rule) so a fresh checkout under `core.autocrlf` re-derives them.

Gates: all five validate (`test_grandfathered_closure_validates_without_reclosing`, no `v2_analysis`
key -- not re-closed). Adversarial: a study closed after the rule with unbound final evidence fails
`STUDY_CLOSURE_EVIDENCE_MISSING`; a forged record entry for it is refused `GRANDFATHER_OUT_OF_BOUNDS`;
back-dating the closure changes its bytes and is refused `GRANDFATHER_MISMATCH`; a scratch copy of
each of the five with one byte appended to the analysis is refused `EVIDENCE_MISMATCH (grandfathered)`.

### B2 -- site 9

`study_closure.py` stage-17 branch: `verdict is not None and …` -> `verdict is None or …`, matching
the stage-16 branch. A bound decision whose canonical artifact cannot be classified is now
`STUDY_CLOSURE_EVIDENCE_STALE` (test `test_stage17_binding_whose_canonical_artifact_is_absent_is_refused`).
The one V1 closure that binds stage 17 (`clean_maturity_flip_model_180s_horizon`) still validates.

### B3 -- final-evidence freshness

`_assert_v2_final_evidence_fresh` runs after the byte check for every bound V2 final-evidence key:
- `experiment_analysis_v2.json` must carry the `plan_sha256` that the closure, `compiled_plan.json`
  and the binding carry (one value); the bound TRAIN freeze must be of that plan; every model id the
  analysis scores (`frozen_models_oos`, `train_metrics`) must be one the freeze binds
  (`model_hashes` / `model_canonical_sha256`).
- `analysis_decision.json` must cite `artifacts/experiment_analysis_v2.json` in `evidence` (string or
  `{path, sha256}`); every cited artifact with a hash must still hash the same; `study_id`, if present,
  must match.
- The V2 close writer (`lifecycle_v2.close`) records `plan_sha256` and `train_freeze_sha256` in the
  `v2_analysis` binding and refuses (closure unlinked) an analysis that does not carry its plan.

Gates (`research_workflow/tests/test_closure_final_evidence_freshness.py`, 21 tests): current plan +
freeze passes; same bytes with `compiled_plan.json` changed underneath refused; analysis from an
earlier plan refused even when the closure re-authenticates its bytes; analysis scoring a model the
freeze does not bind refused; freeze of a different plan refused; decision that does not cite the
analysis / was decided on different analysis bytes refused; path-only citation (the supervisor's
scripted decisions) accepted. The five grandfathered closures are unaffected by construction (no
`v2_*` binding to check) and re-validated. The Wave 1 fixture (`test_end_cycle_wave1.closed_fixture`)
now carries `plan_sha256` and cites the analysis; its 12 closure tests pass.

What B3 does not do: no producer changed. It binds through fields the producers already write
(`plan_sha256` in the analysis and the freeze, model ids in both, the decision's `evidence`). An
analysis with no model ids is bound to the freeze through the plan only -- stated, not patched.

---

## Part C -- demote the field, promote the closure

Registry at branch start: 475 records; `scientific_status` 472 UNASSESSED, 2 VALID_DIAGNOSTIC (the
hand-edited `workflow_canary_ordered_barrier_v1` canaries), 1 INVALID_TARGET (historical registration
of `deep_pullback_5s_reacceleration_model`, already `reuse_status: PROHIBITED`); `reuse_status` 474
PERMITTED / 1 PROHIBITED.

C1. `assert_scientific_status_reusable`: the VALID_PRIMARY and VALID_DIAGNOSTIC branches are gone;
the closure-authority function (`_assert_closure_authorized_reuse`, formerly the UNASSESSED-only
exception) is the gate for every record. A record with no pinned parent closure is
`PRESERVED_MODEL_SCIENTIFICALLY_INVALID … CLOSURE_REUSE_EVIDENCE_REQUIRED`.
C2. `reuse_status == PROHIBITED` hard-blocks first in `resolve_model` (unchanged) and now also inside
the gate; `register_historical_model` writes `reuse_prohibited_reason` beside it. The single
INVALID_TARGET record is already PROHIBITED; it was not hand-edited (the governed writer would
rewrite its `artifact_path` as absolute). Explicitly-invalid `scientific_status` values are still
refused (defence in depth); no positive value branches.
C3. `assign_scientific_status` (the last `research_decision_stage17.json` reader in the enumeration),
its three tests and the stage-17 binding are removed. The field remains an informational column.
C4. `WORKFLOW.md` §G: the closure carries the assessment.

Tests migrated to the closure authority (`research_workflow/tests/closure_reuse_support.py`):
`test_model_reuse_scientific_status.py`, `test_derived_input_model_id_prepare.py`,
`test_multiple_derived_inputs.py`, `test_redteam_pass2_acceptance.py` (rt2_14, rt2_15),
`test_synthetic_model_reuse_e2e.py`. Adversarial additions: PROHIBITED record with authenticated
closure evidence -> `REUSE_PROHIBITED`; historical INVALID_TARGET registration with closure evidence
-> `REUSE_PROHIBITED`; VALID_PRIMARY in the registry without the closure -> refused, with it -> resolves.

Gate -- the four frozen-model consumers resolve identically (`evidence/c_gate_before.json`,
`evidence/c_gate_after.json`, produced by resolving each `model_id` derived input exactly as PREPARE does):

| study : input | before | after |
|---|---|---|
| `first_p90_warning_horizon_2024` : parent_long_score / parent_short_score | REFUSED `PRESERVED_MODEL_NATIVE_BOOSTER_CORRUPT` | same (closure policy honoured; still refused downstream at the known byte mismatch) |
| `workflow_canary_model_reuse_v1` : canary_parent_score | REFUSED `PRESERVED_MODEL_SCIENTIFIC_STATUS_REQUIRES_POLICY` | REFUSED `PRESERVED_MODEL_SCIENTIFICALLY_INVALID` (no closure pinned) |
| `first_p90_warning_horizon_march2024` : both inputs | legacy parent-freeze binding, not a registry resolution | same |
| `v2_shape_b_deep_pullback_5s` : model_c_score_at_candidate | legacy parent-freeze binding | same |

---

## The gate

`python scripts/test_delta.py research_workflow/tests scripts/tests features/tests --baseline-reference ee16002e --json`
on `1b990d36` (six commits on `main` `9be6eba2`), Python 3.13.7, Windows, alone on the host. Three attempts,
recorded in `evidence/broad_gate_start.txt`:

| attempt | start (UTC) | result |
|---|---|---|
| 1 | 13:54 | killed by the host after ~40 min ("system running low on memory"); no card |
| 2 | 14:35 | 88m02s (5,281.8 s); 2,310 ran / 2,241 passed / 62 failed: 56 known, **6 NEW** (`evidence/broad_gate_attempt2.json`) |
| 3 | 16:20 | **81m59s (4,918.8 s); 2,310 ran / 2,242 passed / 61 failed: 56 known, 5 NEW, 0 outside scope, 0 now-fixed** (`evidence/broad_gate.json`) |

The five NEW on attempt 3 are exactly the five the packet expects, all pre-existing: `test_acc12_canaries_green`,
`test_no_hardcoded_feature_count_in_generic_workflow`, the two `test_rt2b2_editing_a_governance_authority_moves_the_composite`
cases, and the stale universe count of 129 in `test_candidate_authority`. Nothing in the suites this packet
changed (promotion, candidate authority, closure, model artifacts) is NEW.

The sixth on attempt 2 -- `scripts/tests/test_supervisor_blackbox.py::test_stale_controller_card_forces_reseal_never_an_audit[spec]`
-- was traced, not baselined: its supervisor sandbox shows the controller's `tests` stage failing at
15:59:07Z with `PLATFORM_TESTS_FAILED: {'passed': 0, 'failed': 0}`; `_work/controller/test_summary.json`
holds an **empty** captured tail, i.e. the `pytest` subprocess over the six unchanged PLATFORM_TESTS files
returned nonzero without printing anything -- a process killed under host load, in the same session in
which the OS killed attempt 1. The `[platform]` twin passed in the same run; both params pass alone
(271.9 s). It is not attributable to this packet's changes and did not recur on attempt 3.

`cap generate --check`: OK (`8cd68dde…`). `lint_host`: CLEAR (8 files, 0 findings). Test runs regenerate
`studies/es_wick_imbalance_acceptance_v2/audit/*.json`; restored with `git checkout`, never committed.

---

## Sealed-manifest pins moved by this branch

Measured with the manifests' own `hash_file_v2` (`evidence/manifest_drift.py`): of the five V2 sealed
manifests, `es_180s_model_c_portability` (90 pins: 73 match the tree, 14 already drifted on `main`,
**3 moved by this branch**: `features/candidate_authority.py`, `research/schemas/study_spec.py`,
`research_workflow/model_artifacts.py`), `first_p90_warning_horizon_march2024` (43: 29 / 13 / **1**,
`study_spec.py`); the three shape studies: 0 moved. `study_spec.py` moved because two description
strings were corrected (they are code literals under the semantic hash). No sealed study is in flight;
compiled plans re-resolve to the identical digest (A1 gate).

---

## New findings (not fixed)

1. `workflow_canary_ordered_barrier_v1/artifacts/study_closure.json` fails validation on `main` and
   here: `STUDY_CLOSURE_EVIDENCE_MISSING` -- the study reached TRAIN (freeze present) but its closure
   binds no mandatory terminal evidence. Pre-existing; not one of the five; the canary's own script
   writes that closure.
2. The ordered-barrier canary script (`studies/workflow_canary_ordered_barrier_v1/_work/canary_closure_and_reuse.py:75-78`)
   edits the registry JSON directly to `VALID_DIAGNOSTIC`, bypassing the governed writer. **Nothing
   prevents a non-canary script doing the same**: `studies/model_registry/*.json` are plain files with
   no signature; `persist_models` refuses to overwrite a *differing* existing record
   (`IMMUTABLE_MODEL_REGISTRY_CONFLICT`) but a direct `write_text` is not routed through it. After Part C
   a direct edit of `scientific_status` grants nothing; a direct edit of `reuse_status` from PROHIBITED
   to PERMITTED would lift the hard block -- that is the remaining exposure.
3. `features/tests/test_candidate_authority.py::test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it`
   pins the active universe at 129 (145 now). Expected NEW per the packet; left as found although the
   file was edited (only the activation tests were removed from it).
4. `docs/WORKFLOW_REFERENCE_FACTS.md` "Feature System V2 authority" table still says 129 canonical
   definitions as of 2026-08-25; the paragraph below it now says the bundle grew and the active universe
   is larger. Re-derive before quoting.
5. Sealed V2 frozen manifests already drift from `main` by 9-14 pins each (every platform commit moves
   closure files); the frozen manifest is a record of what ran, not a live gate. The A1 P6 plan digest
   is the check that means something for sealed plans.
6. `research_workflow/feature_candidate_authority.py` + `scripts/check_candidate_promotion.py` and the
   `feature_candidate.yaml` branches in five core modules remain: a closure-aware refactor for a later
   packet (see A1 "left in place").
7. `test_lifecycle_v2.py::test_controller_runs_a_fresh_v2_study_end_to_end` failed once during the
   Part B targeted run with `READY_TO_FREEZE != READY_TO_OOS`: the Part C patch was applied to
   `model_artifacts.py`/`study_spec.py` while that test was mid-run, which moved the execution
   composite between the freeze receipt and the post-check. Alone it passed (263.5 s) and it passed
   on both broad attempts. Lesson recorded: never edit closure files while a controller test runs.
8. The broad gate is memory-bound on this host: the OS killed attempt 1 outright and attempt 2 lost one
   sandboxed `pytest` subprocess to the same pressure (empty output, nonzero exit). A `tests` stage that
   reports `{'passed': 0, 'failed': 0}` with an empty tail is a killed process, not a test failure.

## Out of scope, left as found

Supervisor re-audit route; audit-trail persistence gaps; baseline re-record; the 59-minute tier;
W2.2b/W2.3/W2.4; S2 concurrency; sub-year sharding; frame reuse; warmup convergence; C6.
`collection_latency` worktree untouched.

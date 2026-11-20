# Research lanes — implementation report (P3 / P4 / P5 / P6 approved 2026-11-20)

Branch `chore/research_lanes` from main `dcafca80`. The design is `DESIGN.md` (`b2e4c5ab`).

## Change set

| File | Change |
|---|---|
| `research_workflow/study_observers.py` (new) | Study-local causal observers: static isolation check (import allow-list; no pandas, OS, `sys` or `importlib`, no relative or `studies.*` imports, no `open`/`eval`/`exec`, no `.shift`/`.iloc`/`.loc`/`.rolling`), class contract (`CAPABILITY = study_local.<name>`, `AVAILABILITY = "bar_close"`, `MAX_STATE_ITEMS`, stream inputs only, FIELDS only), a study-bound implementation ref, a generated causality harness (determinism, prefix invariance, future perturbation at three cuts, scalar fields, state bound), and `bound_observer_files` for R10 |
| `research_workflow/grammar/compiler.py` | `tracker: study_local:<name>` resolves `studies/<id>/observers/<name>.py`. The harness runs at compile time; a failure is a study-side `INVALID_PARAMETERIZATION` gap, never `MISSING_CAPABILITY`. The observer file enters the closure. Optional `study_dir` argument |
| `research_workflow/host/strategy.py` | `_load` resolves `study_local:` refs and refuses them for any other study (`OBSERVER_CROSS_STUDY_IMPORT`) |
| `research_workflow/lifecycle_v2.py` | R10 / ZERO_STUDY_PYTHON exempts only the `observers/<name>.py` files the current plan binds for this study. Every other study `.py` still fails |
| `research_workflow/research_lanes.py` (new) | `route`, `required_gates`, `validate_execution_claim` (refuses precomputed schedules), `facts_from_study`, `lane_manifest` / `write_lane_manifest` |
| `research_workflow/merge_tier.py` (new) | Port of the `chore/tiered_gates` classifier and derived surface (`000cbfc3`) with three changes: (1) a modified `conftest.py` / pytest config is CORE (the design proof classified it as TESTS); (2) an added `scripts/parity/*.py` harness is ADDITIVE; (3) `.md` and `artifacts/**` couple only to the tests that name them, not to every module whose text mentions the basename. Without (3), README.md / WORKFLOW.md pulled 143 / 163 test files into the volume-clock surface |
| `scripts/test_delta.py` | `--tier-base <ref>`: ADDITIVE / INERT diffs run the derived surface; CORE / MODIFIED run the given broad scopes unchanged. The card reports `merge_tier` |
| `WORKFLOW.md` | §A, golden rules 7 and 9, §N.1 (routing test before a gap), §E step 4 (parity bar), §N.3 (tiered gate), new §Q (lanes, routing test, observers, budget, manifest, parity bar, retired `research/*` route) |
| `CLAUDE.md` §5 | One line: the observer is the sanctioned exception |
| `research_workflow/tests/test_research_lanes.py` (new) | 34 tests |

## Primary success test

`test_primary_new_exploratory_study_with_a_novel_local_feature_runs_fast_and_causally` builds a throw-away study under
`studies/`. Its novel feature, `signed_volume_streak`, is a same-direction close streak plus 30 s signed volume, and
exists nowhere in the platform.

- **Compile:** `compile_study` binds it with no gap. The observer file is in `plan.closure.files`, and the
  implementation ref names the study.
- **NT host run:** the plan runs through `HostCore` (the NT observation host) on a synthetic 1 s tape. That gives
  more than 1,000 epoch rows.
- **Reference check:** every row equals a brute-force independent reference of the state after the source row
  closing at or before the epoch.
- **Availability:** `seen <= observation_ts`, and every row maps to a source close.
- **Lane:** routes to FAST_OBSERVATION. The gates include the observer harness and exclude `broad_test_delta`,
  `capability_promotion`, `contract_audit` and `full_history_parity`.
- **Result:** writes one `lane_manifest.json` with the verdict.

Converse cases:
- A shared-code change routes to PLATFORM_CHANGE, and the CORE tier runs the broad scopes.
- A trading backtest routes to EXECUTION_VALIDATION (a declared FAST lane is ignored).
- A precomputed schedule is refused as execution evidence.
- A leaky (class-level memory), unbounded or non-scalar observer fails the harness.
- An observer is refused when it imports pandas, another study, `sys` or `importlib`, or uses `open` or `.shift`.
- One study's observer cannot run in another study, or be sanctioned by another study's plan.

Merge-tier classification is tested on a throw-away git repo:
- **ADDITIVE:** new tracker + test + index entry; insertion-only registration.
- **CORE:** compiler edit; edited registration entry; conftest; `studies/**`; unmapped path; deletion.
- **MODIFIED:** capability module edit; changed index entry.

## Test results

| Run | Result |
|---|---|
| `test_research_lanes.py` | 34 passed |
| Targeted `test_delta`: research lanes, grammar, golden fixture, runtime bindings, host core, zero-Python red team, three closure suites, execution closure, capabilities, docs, concurrent-research docs, capability modularity, `test_delta` self-tests, volume-clock tracker, lifecycle_v2 | 250 ran, 248 passed, 2 failed, 2,876 s |
| Classification of the 2 failures | `test_runtime_bindings.py::test_episode_study_is_provider_host_mode_and_all_features_bind` and `::test_existing_non_episode_studies_are_not_regressed`. Both are among main's 63 known failures (exact node ids, `volume_clock_tracker/test_delta_broad.json`): missing V1 study artifacts / collector dispatch. 0 attributable |
| `scripts/lint_host.py` | CLEAR |
| Volume-clock diff (`e3db799d..df84868c`) under the tiered gate | ADDITIVE_CAPABILITY, derived surface 76 test files (broad: about 180). Building the coverage map takes about 325 s |

## Limitations

1. **This chore is itself CORE_SURFACE** (it edits `research_workflow/**`). Under its own §N.3 rule it needs ONE broad
   `test_delta` before merge. That run has not been done.
2. **Closure impact:** `compiler.py`, `host/strategy.py` and `lifecycle_v2.py` are in every V2 study's execution
   closure. After the merge, an in-flight sealed study that merges main sees a stale closure, as with any compiler
   change. Sealed / closed studies keep their authority at their own commit.
3. **Observers are pure bar-stream bindings.** They have no calendar or dataset access and no tracker inputs. An
   observer that needs session calendars or another tracker's state is still a PLATFORM_CHANGE until a governed
   input is added.
4. **The harness is generic.** The synthetic tape exercises gaps, zero volume, session breaks and reversals, but not
   study-specific edge classes. A FAST study still needs its own targeted test and the bounded real-data smoke
   (§Q.3). An observer whose fields never vary on the tape is refused (`fields_vary`).
5. **The static check is an allow-list, not a sandbox.** A determined author can still write bad causal logic inside
   the allowed surface. The perturbation harness and the causal audit are the backstop.
6. **The lane router is advisory.** It selects and reports gates; the controller's own stage gates are unchanged.
   Wiring `required_gates` into the controller (for example, skipping the contract audit in FAST) is not done; the
   FAST path today is the existing `stage: collect` -> frame -> explore flow, which already omits the contract audit.
7. **The ADDITIVE surface is still sizeable** (76 files for a tracker), because the capability index is read by the
   registry, compiler and host. The time saving is unmeasured until the first real additive merge. The design
   recommended shadow-running the broad tier for the first few additive merges.
8. **The baseline is stale** (BASELINE_COMMIT_MISMATCH / BASELINE_ENVIRONMENT_MISMATCH), so every card says
   `NEW_FAILURES` until `--update-baseline` is run deliberately on main. Known failures are classified by node id
   against the last broad gate.

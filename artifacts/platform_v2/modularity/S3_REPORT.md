# Session 3 — prove it with a real addition (chore/analysis-tail-lift)

    packet:   RESTORE THE GATE, THEN UNBLOCK MODULARITY — Session 3
    branch:   chore/analysis-tail-lift, stacked on chore/capability-modularity 3adcb9b0 (B1+B2+B3)
    commit:   017eac8f  feat(analysis): analysis.metric.tail_lift
    capability: `analysis.metric.tail_lift` — label-rate lift inside the score tail at P90/P95/P97.5
              thresholds frozen from a declared reference frame and applied to the evaluation rows.
              Not a fixture: it is the `ANALYSIS_HARNESS_GAP` that `es_180s_model_c_portability` closed
              with on 2026-09-06 ("frozen TRAIN P90/P95/P97.5 tail lift ... NEVER PRODUCED").

## Files touched, split

| bucket | files |
|---|---|
| capability's own | `research/analysis/diagnostic_ops.py` (+1 function, +1 entry in `OPS`, +1 entry in `OP_INPUTS`), `research/analysis/tests/test_diagnostic_ops.py` (+5 tests), `research_workflow/capabilities_index.yaml` (+1 seed entry, appended) |
| generated registry | **none** — `registry.json` is an untracked on-demand cache since B3; `cap generate --check` rebuilt it (analysis_ops 9, status `verified`, no missing tests) |
| host or lifecycle | **none** |

## Mechanical classification

`tier_replay.py classify chore/capability-modularity 017eac8f` on the Session 2 tree:

| path | status | vote | reason |
|---|---|---|---|
| `research/analysis/diagnostic_ops.py` | M | ADDITIVE_CAPABILITY | registration file: insertion-only (every pre-existing top-level statement AST-identical; additions are one new `def` and one new entry in each of the declared literals `OPS`, `OP_INPUTS`) |
| `research/analysis/tests/test_diagnostic_ops.py` | M | TESTS | test file |
| `research_workflow/capabilities_index.yaml` | M | ADDITIVE_CAPABILITY | seed yaml insertion-only (semantic: every old id present and unchanged, one id added) |

**Class: ADDITIVE_CAPABILITY.** The first non-synthetic additive classification in the repository's history
(0 of 30 platform merges before it).

## Derived test surface and duration

Surface (reverse import-coverage map built on this tree, 181 test files): **36 files / 415 tests** =
the op's own test module, `reverse[diagnostic_ops.py]` (32 files: everything that imports the analysis ops
through `lifecycle_v2` → compiler, i.e. the lifecycle, supervisor and closure tests), the readers of the seed
index, and the governance floor.

**Measured** (`evidence: surfaceS3_timing.jsonl`, one detached run of exactly those 36 files, per-test timing
plugin, **contended** by the concurrent Session 1 broad re-record on the same host):

| | value |
|---|---:|
| wall | **58m 50s** (3,531 s) |
| tests run | 428 (421 passed, 7 failed — see below) |
| `scripts/tests/test_supervisor_blackbox.py` | 1,798 s = **51 %** |
| `research_workflow/tests/test_redteam_packet_f.py` | 597 s = 17 % |
| `research_workflow/tests/test_lifecycle_v2.py` | 313 s = 9 % |
| `research_workflow/tests/test_redteam_v2_model_authority.py` | 233 s = 7 % |
| everything else (32 files) | 590 s = 17 % |

So "minutes" does **not** hold for this surface as derived: the analysis-op registry is imported by
`lifecycle_v2` → the whole supervisor / black-box family sits inside `reverse[diagnostic_ops.py]`, and
those four end-to-end files are 83 % of the time. By count the surface is 17 % of the suite; by time,
against the recorded 74m41s broad baseline (uncontended, two scopes), it is roughly 80 %. The saving is
real but small until either (a) the black-box supervisor proof is excluded from the additive tier by a
rule other than reachability (it exercises the supervisor, not the op), or (b) `lifecycle_v2` stops
importing the analysis-op module at module level (it is reached through `research/analysis/diagnostic_ops`
← `lifecycle_v2.analyze`). Reported, not decided here.

Failures in the run: `test_runtime_bindings::test_existing_non_episode_studies_are_not_regressed`
(baseline entry) and `::test_episode_study_is_provider_host_mode_and_all_features_bind` (fresh-worktree
missing model artifact); `scripts/tests/test_session_efficiency.py::test_test_delta_classifies_against_committed_baseline`
(fails identically on clean main 68e0722a — Wave 2 removed the auto-environmental class the test expects;
pre-existing); and four `scripts/tests/test_execution_closure.py` tests that are a **B2 finding**, fixed on
the Session 2 branch (see Session 2 report, B2 follow-up). None is caused by the op.

## Hand edits

Two, both inside the one registration file and both pure insertions: the `OPS` and `OP_INPUTS` dict
entries in `diagnostic_ops.py`. The seed entry in `capabilities_index.yaml` is the declaration itself,
not a wiring edit. B1 made trackers, feature hosts and derived inputs resolve from the seed with no
table edit at all; analysis ops (and provider adapters, `ADAPTER_REGISTRY`) still carry a
hand-maintained dict. Applying the B1 pattern to `OPS` (`run_op` resolving `implementation` from the
seed) removes the last hand edit for this kind; small, not done here, listed.

## Structural residue for this concrete case

The op consumes a score column and a label column of the declarative analysis frame. The frame the
`analyze` stage hands to a declared pipeline is `candidates ⋈ observations` (label, disposition): it
carries frozen **external** scores when a study declares one as a derived input
(`model_c_score_at_candidate`), but **not the scores of the study's own fitted model** — those are
computed in memory in the non-declarative branch of `analyze` and never joined. So the exact ES case
(tail lift of the natively trained ES model on 2024) needs one more thing the op cannot supply: the
analyze stage joining its fitted arms' scores into the declarative frame (per arm / cell, TRAIN scores for
the reference step and OOS scores for the evaluation step). That is a `lifecycle_v2.py` change —
CORE_SURFACE — and it is the residue: **the capability is additive; making a fitted model's own scores
visible to declared analysis is not.** One concrete case, as the packet asked.

## Verdict

Classifies additive under the mechanical rule, derives to 36 files, no host or lifecycle edit, two
insertion-only hand edits in the op registry. Whether "minutes" holds is the measured line above.

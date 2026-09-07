# R2 — Reuse key, Reading 2: the replay closure stops before the compiler

    task_id:      collection_latency_r2
    branch:       chore/collection_latency (S1 at 30cc28c6)
    scope:        derivation of the partition-reuse key only; seal and frozen manifest semantics unchanged
    evidence:     artifacts/platform_v2/collection_latency/evidence/r2_realdata.json, targeted_test_delta4.json

## P1–P3 — prerequisites (verified, not assumed)

**P1 — the plan is in the key: YES, as `replay_plan_sha256`, and `plan_sha256` itself must NOT be.**
The key already bound the plan's replay-affecting content: every top-level plan key except `analysis`,
`model`, `study`, `notes`, the identity fields (`plan_sha256`, `spec_sha256`, `closure`) and
`chronology.partition_reuse`. That subset is the load-bearing substitute for the compiler: a compiler change
that alters what the plan says about replay (streams, trackers, features, population, triggers, outcome,
columns, warmup, availability, binding proof, session, instruments, registry) changes it. `plan_sha256`
itself covers `closure.composite_sha256` (all 115 manifest files, compiler included) and the analysis/model
blocks, so putting it in the key would refuse reuse on every compiler, controller or analysis change — the
exact outcome Reading 2 exists to avoid — and would make V2-r and V3 unreachable by construction. Read
literally, P1 fails; read as "the plan's replay content is hashed", it passes. Implemented under the
second reading and stated here so it can be overruled. Test: `test_key_ignores_post_collection_declarations_and_binds_replay_ones`
and V7(b) below (a compiler change that alters the warmup fact is refused through this hash).

**P2 — zero compiler modules execute during replay: YES, by trace, after two layering fixes.**
Before this session the answer was NO for a reason unrelated to replay semantics:
`research_workflow/grammar/__init__.py` eagerly re-exported `compile_study`, so the host's run-time imports
of `grammar.predicates` / `grammar.spec` executed `compiler.py`'s module body as a package side effect.
Fixed: the package no longer re-exports the compiler (14 callers now import
`research_workflow.grammar.compiler` directly). Second inversion: `policy.assert_old_runtime_allowed`
imported `is_v2_study` from the controller; the frozen-model scoring path (`external_model_scoring →
model_artifacts → model_store → policy`) therefore reached `lifecycle_v2` → `compiler` → analysis modules.
Fixed: `is_v2_study` lives in the leaf module `research_workflow/study_kind.py`. Trace evidence: the cff
partition child (bare interpreter, complete trace) imported 52 repository files during replay, none under
`research_workflow/grammar/` except `grammar/spec.py` (the schema the host reads, correctly in the replay
stage), no `lifecycle_v2.py`, no `research/analysis/*`; verdict `WITHIN_CLOSURE`. ES child traces:
ES 2020 and 2021 partition children each traced 51 repository files, `WITHIN_CLOSURE`, zero compiler / controller / analysis modules (`evidence/r2_realdata.json`, phase `es_V4r_P2`).

**P3 — the compiler writes nothing else consumed at replay: YES, with one replay input found and bound.**
`compiler.py` writes no files; `compiled_plan.json` and `compile_card.json` are written by the lifecycle.
Replay-time reads outside Python modules: the dataset yaml and catalog bytes (verified at launch against
the plan's dataset digest), the session reference tables (digest in the plan), model-store artifacts
(authenticated by id/hash in the plan), and **`features/feature_definition_promotions.json`**, read by
`features/registry.py::canonical_definition_status` when `provider_host.py:981` resolves the feature
instances at replay — in neither the manifest (Python files only) nor, until now, the key. Bound
explicitly: `replay_closure.REPLAY_DATA_FILES`, hashed into the key
(`test_key_binds_replay_time_data_files`).

## 3.1 Derivation

`closure.stages.replay` = transitive repo-import closure seeded at `ctx.closure_files` minus the six
grammar seeds minus files added for a non-replay reason (`research/analysis/diagnostic_ops.py`, added for
the `analysis:` declaration; `ctx.replay_excluded`). `grammar/spec.py`, `grammar/predicates.py`,
`grammar/gaps.py`, `grammar/plan.py` re-enter through the host's own imports; `compiler.py` and
`expansion.py` do not. The key binds the replay stage composite; the frozen manifest is the union of all
stage sets and only grew. The governance stage sets stay declared lists (the red-team invariant
"a perturbation moves its stage and the composite, never an unrelated stage" is a test and still passes);
five modules that the collection walk used to reach only through the removed `policy → lifecycle_v2`
edge (`partitioning.py`, `collection.py`, `first_p90_gate.py`, `first_p90_warning.py`,
`backtests/nt_runtime/modes/collect.py`) are declared on the `oos` list, which is where
`experiment.py` lazily imports them, so no file left the manifest.

## 3.2 Cumulative trace

Every partition run (child process) traces the repository modules first imported inside
`_run_window`, writes `replay_trace.json` next to its manifest, and **halts before persisting** on any
module outside the replay stage (`REPLAY_CLOSURE_ESCAPE`). The parent merges every partition and smoke
trace into `artifacts/replay_closure_trace.json` (`runs`, cumulative `union`). Reuse additionally requires
a clean smoke trace for the current plan (`NO_CLEAN_SMOKE_TRACE_FOR_PLAN`). The key is never widened by a
trace. Tests: `test_partition_run_halts_on_a_replay_module_outside_the_key`,
`test_smoke_proves_replay_imports_inside_the_collection_closure`,
`test_reuse_requires_a_clean_smoke_trace_for_the_current_plan`.

## 3.3 Closure size

| stage | files (13-instance ES plan) |
|---|---:|
| frozen manifest (union) — `main` | 90 |
| frozen manifest — after the `__init__` hole fix (S1) | 116 |
| frozen manifest — now | 115 (superset of `main`'s 90; −1 because `policy` no longer reaches `replay_closure.py`, +`study_kind.py`) |
| collection stage | 101 |
| **replay stage (the reuse key)** | **95** |

The 20 collection-only files: the compiler and its expansion module, the analysis ops module, and modules
reached only through them. Recorded in `docs/WORKFLOW_REFERENCE_FACTS.md`.

## 4 Gates

| # | gate | result |
|---|---|---|
| P1–P3 | prerequisites | P1 passes under the stated reading (see above); P2 passes by trace after the two layering fixes; P3 passes with the promotions JSON bound. |
| V1-r | real replay module → REFUSED | PASS. Real data: a statement appended to `features/trackers/generic_arrival.py` (bound provider) → replay stage composite changed → `train-2024` REFUSED (`REPLAY_CLOSURE_CHANGED:replay_closure_composite_sha256`); file restored. Test: `host/strategy.py` hash perturbed → refused, all recomputed. |
| **V3** | `controlled_feature_family_180s` iteration-2 shape reuses; bytes = forced recompute | **PASS**. Real data (cff plan windowed to 2024-03-01..03-31, 35 instances): baseline 368.6 s, 35,872 candidates. Then a statement appended to **both** `research/analysis/diagnostic_ops.py` and `research_workflow/lifecycle_v2.py` plus a study-text edit: plan changed, manifest changed, replay stage unchanged → `train-2024` REUSED, served bytes identical to the baseline (`43dd411a…` / `61064315…`); shadow = forced full recompute of the same partition, 306.8 s, IDENTICAL; reconcile PASS. |
| V2-r | study-text change reuses, bytes identical | PASS (test; and V3 above includes a study-text edit). |
| V4-r | live sealed ES partitions reproduce byte-for-byte | PASS. ES TRAIN 2020+2021 recomputed under this branch (replay stage 95 files, manifest 115): 2020 candidates/observations byte-identical to the live sealed partition (494,455 rows, 1,199 s), 2021 likewise (478,407 rows, 1,142 s); 2,371 s total, uncontended. |
| V7 | compiler-only change permits reuse; plan-altering compiler change refuses | (a) PASS. Real data: a statement appended to `research_workflow/grammar/compiler.py` → manifest composite changed, replay stage unchanged → `train-2024` REUSABLE (preview); test: same, reused with identical bytes; (b) test `test_compiler_change_reuses_unless_it_alters_the_plan`: warmup fact altered by the compiler → refused via `replay_plan_sha256`. |
| V8 | trace halt | Test: partition importing an out-of-key module halts, is not persisted, receipt records the escape. Real data, two forms: (1) a **static** `import research_workflow.audit_packets_v2` appended to `host_runner.py` did NOT halt — correctly: the compiler's walk derived the new import into the replay stage (113 files), the key changed and reuse was refused through the composite; the halt exists for what static analysis cannot see. (2) A **dynamic** `importlib.import_module` of the same module inside `run_plan_on_catalog`: not derivable, so it stayed outside the key → smoke `REJECTED: replay_imports_within_collection_closure`, trace verdict `REPLAY_CLOSURE_ESCAPE`, escape `research_workflow/audit_packets_v2.py` (`evidence/r2_g2.json`). Both perturbations restored. |

Tests: `research_workflow/tests/test_replay_closure.py` 15/15. Targeted `test_delta` over every touched
suite (21 files incl. red-team closure, lifecycle, controller stages, grammar, docs, supervisor): 193 ran,
193 passed, 0 `NEW_FAILURE` (`evidence/targeted_test_delta4.json`). `lint_host` CLEAR, `cap generate
--check` OK, `gen_yaml_reference --check` current.

## 5 Sequencing (unchanged from the packet)

V6 is **not** re-baselined here. Next: the `_midpoints` decay fix (own packet, bound provider module,
stales everything), then re-baseline V6, then decide whether S2 is still needed.

## 6 Closure hole — governance finding

Recorded in `docs/WORKFLOW_REFERENCE_FACTS.md` → "Known defects", with the retrospective: every **closed**
V2 study is retrospectively sound (zero commits to the nine uncovered package inits inside their seal
windows); **ten still-open sealed studies** (`Codex_…`, `Gemini_…`, `clean_maturity_flip_model_rolling_productivity`,
`clean_tradable_reversal`, `es_wick_imbalance_acceptance_v2`, `es_wick_imbalance_exploratory`,
`regime_transition_target_before_stop_v1`, `test_level_break_collector`, `test_minimal_checkpoint_collector`,
`ym_prev5_range_position`) have such commits inside their open-ended windows and are named, not resealed.
Also recorded: NT pin 1.230.0 and why #3889 does not apply.

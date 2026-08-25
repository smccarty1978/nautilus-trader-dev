# Research Study Blueprint — Implementation Map & Novelty Routing

**This document explains how `docs/RESEARCH_WORKFLOW.md` is instantiated in the current
codebase, today.** `RESEARCH_WORKFLOW.md` remains authoritative for workflow *policy* — the
lifecycle, the gates, the invariants. This document exists one layer down: exact paths, exact
functions, exact CLI syntax, and — its main job — a formal answer to *"a researcher asked for
something not seen before; what happens next?"*

If this document and `RESEARCH_WORKFLOW.md` conflict, `RESEARCH_WORKFLOW.md` wins; treat the
conflict as a bug in this file and fix this file.

Companion document: `docs/templates/RESEARCH_STUDY_REQUEST_TEMPLATE.md` — the researcher-facing
intake form referenced throughout §6–§9.

---

## 0. How to read this document

| You are... | Go to |
|---|---|
| Starting a brand-new study | §6 (blueprint), then fill out the request template |
| Not sure if what you're asking for already exists | §7–§8 (novelty routing) |
| Wondering whether the agent should ask you something | §9 |
| Trying to understand what a real sealed study's directory looks like | §2 |
| Trying to find the actual function that does X | §1 or §4 |
| Wondering whether `study.yaml` can express your target/input/gate | §5 |

---

## 1. Implementation inventory

Not every file — the execution-closure and decision-critical modules. "Stage" refers to the
17-stage table in `docs/RESEARCH_WORKFLOW.md` §3.

### 1.1 `research_workflow/` — the reusable governed lifecycle

| Module | Purpose | Key entry points | Reads | Writes | Stage | Status |
|---|---|---|---|---|---|---|
| `study_factory.py` | Scaffold a study tree from `study.yaml` | `parse_study_spec_from_yaml()` (:28), `get_compiler_for_spec()` (routes to `FlipPredictionCompiler` / `BespokeStudyCompiler`) | `study.yaml` | `studies/<id>/` tree | 0b | Authoritative |
| `compiler.py` | Compile a scaffolded study | `compile_study(study_path) -> int` (:25) | `study.yaml` | `compiled_study.json`, `config/deliverables_contract.json` | 1 | Authoritative |
| `phase0.py` | Build the phase-zero authorization manifest — the authoritative feature-instance universe, independent of any study module import | `build_phase0_manifest(study_dir)` (:223), `build_source_state_binding()` (:93) | `study.yaml`, feature registry | `artifacts/phase0_source_manifest.json` | 1 | Authoritative |
| `prepare.py` | Unifies PREPARE (compile + phase0) and FREEZE (execution-closure resolution) | `run_prepare_and_freeze(study_dir)` (:26) | study tree, `scripts/resolve_execution_manifest.py` | `audit/frozen_execution_manifest.json` | 1 | Authoritative |
| `readiness.py` | R1–R10 (see §1.2) | `run_readiness(study_path, **kwargs)` (:693), `verify_instrument_precision()` (:285, R3) | frozen manifest, real catalog samples | `audit/readiness.json` | 2 | Authoritative |
| `preflight.py` | Six required deterministic checks (§1.3) | `run_preflight(study_dir, ...)` (:334); `REQUIRED_STUDY_CHECKS` (:48); evidence schema v2 (:98) | frozen manifest, study tree | `audit/preflight.json`, `audit/failure_packet.json` | 3 | Authoritative |
| `causal_audit.py` | Executable causal review harness | `run_causal_review(study_path)` (:66) — verifies frozen manifest, runs 5 sub-checks, scans `causal_lint.py` CRITICALs | frozen manifest | `audit/pass_NN.md`, `audit/status.json` | 4 | Authoritative |
| `contract_audit.py` | Executable contract review harness | `run_contract_review(study_path)` (:67) — checks instances vs. phase0 manifest vs. authorized universe | frozen manifest | `audit/contract_pass_NN.md`, `audit/contract_status.json` | 5 | Authoritative |
| `seal.py` | Pre-execution seal | `generate_preexec_audit_seal(study_dir)` (:66), `verify_frozen_execution_identity()`, `assert_preflight_audit_ready()` | frozen manifest, both audit statuses | `artifacts/preexec_audit_seal.json` | 6 | Authoritative |
| `generic_collector.py` | **The** collector strategy — the only NT event-loop path | `FastOHLCVRingBuffer` (:103–149), `on_1s()` callback | compiled instances, bars from NT engine | `candidates_df`, `observations_df` (strategy attrs) | 7–10 | Authoritative — never copy/subclass |
| `execution_plan.py` | Immutable compiled callback groups, bound once at strategy construction | `CompiledExecutionPlan` (:15–59), `.for_collector(collector, aliases)` | compiled instances | callback bindings (in-memory) | 7 | Authoritative |
| `output_manager.py` | Persistence, schema + surface enforcement | `resolve_collection_allowed_feature_aliases()` (:37), `verify_strategy_output_interface()` (:76 — raises `STRATEGY_OUTPUT_INTERFACE_MISSING`) | strategy output attrs | run-dir parquet + manifest | 7, R7 | Authoritative |
| `experiment.py` | The whole TRAIN/OOS authority | `authorize_experiment()` (:69), `load_authorization()` (:108), `write_train_freeze()` (:183), `assert_oos_open()` (:206) | `study.yaml` chronology | `artifacts/experiment_authorization.json`, `artifacts/train_experiment_freeze.json` | 9, 13, 14 | Authoritative |
| `collection.py` | Drives one authorized TRAIN/OOS period through the collector | `collect_period(study_path, period, run_id, execute)` (:24) | experiment authorization | run directory | 10, 15 | Authoritative |
| `partitioning.py` | Year-partitioned TRAIN collection, merge, parity | `PartitionSpec` (:27), `build_year_partitions()` (:58), `reconcile_partitions()`, `merge_partition_outputs()` | study chronology | merged frame | 10–11 | Authoritative |
| `modeling.py` | Governed fit + TRAIN freeze | `fit_models(study_path, X, y, meta, spec, ...)` (:17 — calls `guard_training_frame()`), `freeze_train_artifacts()` (:46 — calls `assert_causal_feature_surface()`) | TRAIN frame | `artifacts/experiment_models.json`, `artifacts/train_experiment_freeze.json` | 12, 13 | Authoritative |
| `analysis.py` | Structured, provenance-bound result computation (thin wrapper over `research/analysis/`) | `classification_results()` (:20), `score_deciles()` (:67), `first_crossings()` (:79) | merged/OOS frame | `artifacts/experiment_analysis.json` | 16 | Authoritative |
| `forward_outcomes/` | Proposed-entry → future-path observation (see §1.4) | see §1.4 | frozen scores/thresholds | `proposed_entries.parquet`, `forward_outcomes.parquet` | any (post-hoc, study-agnostic) | Authoritative |
| `hooks/` | Tiny declarative Protocols a study may implement | `checkpoint.py`, `population.py`, `state.py`, `target.py` | — | — | 7 | Authoritative extension point |
| `lifecycle.py` | Thin facade — `prepare()`, `readiness()`, `bounded_preflight()`, `seal()`, `authorize_experiment_stage()`, `collect_experiment_period()`, `open_oos()` | wraps the above | — | — | all | Authoritative |
| `test_selection.py` | Picks the tests a change actually requires | `get_git_changed_files()`, `discover_all_framework_tests()`, `discover_study_tests()`; `STUDY_CORE_TESTS` (8 mandatory), `STUDY_PROVIDER_TESTS` (2) | git diff | — | 3 (preflight) | Authoritative |
| `__init__.py` | Public export surface | `__all__` (13 modules) | — | — | — | **Inside the execution closure** — a cosmetic edit stales a sealed study's freeze |

### 1.2 READINESS R1–R10 (`readiness.py`)

| Check | Proves |
|---|---|
| R1 | exact physical dataset identity: declared == `DatasetSpec` == resolved == opened, warmup-through-run coverage |
| R2 | 1s/1m `ts_init - ts_event` contracts on real bounded samples; derived 5m via `CompletedMinuteFiveMinuteAggregator` |
| R3 | `verify_instrument_precision()` — `instrument.id` matches `data_plan.instrument_id`, `price_increment` matches, sample bar close precision matches `instrument.price_precision` |
| R4 | callback causal order via probe strategy |
| R5 | real collector constructs under real phase0 authorization (construction only) |
| R6 | `STRATEGY_OUTPUT_INTERFACE_MISSING` contract |
| R7 | synthetic fixture validates through real `OutputManager` |
| R8 | execution identity resolves twice with exact equality, no mutation |
| R9 | zero alternate (ungoverned) catalog openers under `studies/<id>/**/*.py` |
| R10 | bounded real first-nonempty collector output parity vs. collection-time feature contract |

### 1.3 PREFLIGHT required checks (`preflight.py`)

`EXECUTION_MANIFEST` (resolved vs. frozen) · `CAUSAL_LINT` (`scripts/causal_lint.py`) ·
`ARTIFACT_SCHEMA` (`scripts/check_artifact_schema.py`) · `FEATURE_PROMOTION`
(`scripts/check_feature_promotion.py`) · `RESEARCH_DECISION_FIDELITY`
(`scripts/check_research_decision_fidelity.py`) · `CAUSAL_INVARIANTS`
(`research_workflow.test_selection`). All six must *run*, not just pass — `--skip-tests` cannot
report `READY_FOR_AUDIT`.

### 1.4 `research_workflow/forward_outcomes/`

| Module | Role |
|---|---|
| `contracts.py` | `ProposedEntry`, `ForwardOutcomeSpec` (frozen, `spec_sha256`), `Direction`, `OutcomeStatus` (RESOLVED / CENSORED_SESSION / CENSORED_HORIZON / CENSORED_DATA_END / MISSING_DATA), `ReferencePrice`, `BarInclusion`; `build_outcome_columns(spec)` — schema generator |
| `tracker.py` | `ForwardObservation` — mutable per-entry future-path state; `on_bar()`, `finalize()` |
| `selection.py` | build entries from frozen scores — threshold crossings, deciles, local maxima |
| `partition.py` | `required_lookahead_seconds(spec)`, `build_outcome_partitions()`, `assert_partition_parity` |
| `guard.py` | `OUTCOME_COLUMN_PATTERNS` (21 anchored regexes), `CAUSAL_IDENTITY_COLUMNS`, `outcome_column_namespace(spec)`, `assert_causal_feature_surface()` — fail-closed, `OutcomeLeakError`, no warning mode |
| `governance.py` | artifact writing, reconciliation, provenance — **library only, no CLI** |
| `analysis.py` | descriptive summaries only |
| `smoke.py` | streaming-vs-bruteforce infrastructure smoke |

No CLI entry point exists for this package; it is invoked from `research_workflow.lifecycle` or
directly by a study's analysis step.

### 1.5 `research/` — schema and analysis layer consumed by `research_workflow/`

| Area | Path | Purpose |
|---|---|---|
| `StudySpec` | `research/schemas/study_spec.py` | The machine contract schema — see §5.1 for exact field inventory and gaps |
| `DatasetSpec` | `research/schemas/` | Physical dataset identity contract, cross-checked at R1 |
| Engines | `research/engines/{population,target,feature_binding,timestamp,lineage,baseline,deliverables}_engine.py` | Each compiles one contract segment; `deliverables_engine.py` refuses unreachable artifacts at compile time |
| Study types | `research/study_types/{flip_prediction,bespoke,base}.py` | `flip_prediction` = canonical regime-flip type, no custom code; `bespoke` = escape hatch requiring `bespoke.reason` + `bespoke.unsupported_contract_element`, `custom_code_allowed: True`; `base` = abstract `evaluate_fit()` / `compile()` interface |
| Analysis harness | `research/analysis/{loader,spec,slices,metrics,modeling,reporting,identity}.py` | A0-contracted (`ANALYSIS_HARNESS_A0_CONTRACT.md`); imports neither backtest runtime nor collector to avoid perturbing the sealed execution closure |

### 1.6 `features/` — canonical identity

| Path | Purpose |
|---|---|
| `features/registry.py` | `FeatureInstance`, `validate_feature_instance()` (:888–1005) — see §7 for full error-code table |
| `features/candidate_authority.py` | `load_authority()`, `freeze_candidate()`, `activate_frozen_candidate()`, `activate_pipeline_candidate()` |
| `features/authority/active.json` | atomic pointer — `{"activation_kind", "bundle", "bundle_composite_sha256", "schema_version"}` |
| `features/trackers/generic_*.py` | 10 parameterized providers: arrival, bar_geometry, context, median_center, ohlcv_delta, price_levels, pullback, regime_geometry, rolling_productivity, structural_geometry |
| `features/FEATURE_REGISTRY_CONTRACT.md` | DESIGN CONTRACT — promotion lifecycle (§7) |
| `scripts/feature_ctl.py` | `check` / `promote` CLI |

### 1.7 `backtests/nt_runtime/`

| Path | Purpose |
|---|---|
| `data_plan.py` | `resolve_catalog_plan(symbol, ...)` (:215) — generic, no governance; `resolve_data_plan(compiled_data, ...)` (:294) — full study governance: chronology, prohibited years, `verify_catalog_coverage()`, DatasetSpec binding; `PRODUCT_CATALOGS` dict (:121–161) |
| `engine_builder.py` | NT `BacktestEngine` construction — B0-contracted |
| `strategy_binding.py` | `STRATEGY_REGISTRY` — the only place a strategy id is registered |
| `compiled_study_loader.py` | loads `compiled_study.json` into runtime objects |
| `telemetry.py` | opt-in `tracemalloc`, always-on RSS |
| `run_nt_study.py` | collect entrypoint (`--mode collect\|parity\|backtest`, `--stage fixture\|day\|week\|month\|full`) |
| `run_backtest.py` | standalone backtest entrypoint, non-study |

### 1.8 Utility loaders

| Path | Purpose |
|---|---|
| `utils/runner/data.py` | `CausalDataLoader.load_bars(bar_type, start, end)` — the only sanctioned catalog reader; `bar_type` string encodes instrument, no separate symbol param |

---

## 2. How a study exists in the repo — worked example

Two studies together show the full arc: `clean_maturity_flip_model_rolling_productivity`
(fully sealed, TRAIN+OOS complete — 16 causal/contract audit passes) is the **frozen Stage-1
parent**, and `clean_tradable_reversal` (design-checkpoint only, one file) is the **in-flight
Stage-2 child** consuming its frozen score. The link is verifiable: the parent's
`audit/status.json` records `audited_execution_composite_sha256:
7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8`; the child's
`research_decision.yaml` binds to exactly that hash under `stage1_dependency`.

### 2.1 The fully executed reference — `clean_maturity_flip_model_rolling_productivity/`

```
research idea
  -> research_decision.yaml     [git]   the hypothesis, baseline, model arms, prohibited/allowed changes
  -> SPEC.md                    [git]   derived narrative spec
  -> study.yaml                 [git]   machine contract: study/operation/instrument/population/
                                         target/features/model/chronology/stratification/baseline/
                                         lineage/execution/acceptance/bespoke
  -> compiled_study.json        [git]   {study_id, study_type, spec_sha256, spec, contracts, strategy_class}
  -> config/*.json              [git]   one file per compiled contract segment:
                                         population_contract, target_contract, feature_contract,
                                         timestamp_contract, execution_contract, lineage,
                                         deliverables_contract, baseline
  -> feature resolution         --      FeatureInstances resolved against features/authority/active.json
  -> readiness                  [git]   audit/readiness.json (R1-R10)
  -> preflight                  [git]   audit/preflight.json, audit/failure_packet.json (if any)
  -> causal audit                [git]   audit/pass_01.md .. pass_16.md, audit/status.json
                                         (16 passes to CLEAR — this study's real history)
  -> contract audit              [git]   audit/contract_pass_01.md .. contract_pass_16.md,
                                         audit/contract_status.json
  -> seal                        [git]   artifacts/preexec_audit_seal.json
  -> collector execution          --     runs/ (not committed)
  -> TRAIN artifacts             [git]   artifacts/train_collection_manifest.json,
                                         artifacts/train_candidates_merged.parquet (not committed —
                                         parquet is generated data; manifest is)
  -> model fitting                [git]   artifacts/model_manifest.json, models_long.json, models_short.json
  -> TRAIN freeze                 [git]   artifacts/train_experiment_freeze.json
                                         (+ a later train_experiment_freeze_repaired.json — see below)
  -> OOS authorization             [git]   artifacts/oos_unlock.json, experiment_authorization.json
  -> OOS scoring                   [git]   artifacts/oos_2024_analysis.json (+ repaired variant)
  -> analysis / decision            [git]   artifacts/final_research_decision.md/.json
```

Two things this real study's audit trail teaches that a clean linear diagram would hide:

1. **16 causal-audit passes were required**, not 1. `AGENTS.md` §3's "at most 3 new CRITICALs
   per pass, bounded re-audit" is not a hypothetical — this is what it looks like in practice
   over a real study.
2. **A repair cycle happened after freeze.** `train_experiment_freeze_repaired.json`,
   `repaired_oos_summary.json`, `SMOKE_ACCEPTANCE_INVALIDATION.md`, and
   `TRAIN_OOS_ARTIFACT_INVALIDATION.md` exist alongside the originals. A defect found after
   freeze does not get silently patched in place — the original artifact stays, a new
   `*_repaired.json` / `*_INVALIDATION.md` is added, and both are visible in the tree. This is
   the concrete shape of "re-run stage 1, then redo 3–6" (`RESEARCH_WORKFLOW.md` §3.2) when it
   actually fires.

`compiled_study.json` for this study has exactly five top-level keys:
`study_id, study_type, spec_sha256, spec, contracts, strategy_class` — everything else is
inside `spec` (the full `StudySpec`) or `contracts` (the compiled per-segment JSON also mirrored
into `config/*.json`).

### 2.2 The in-flight example — `clean_tradable_reversal/`

As of this writing, the directory contains exactly one file:
`studies/clean_tradable_reversal/research_decision.yaml`, status
`FORMALIZED_NOT_SCAFFOLDED`. Nothing downstream (`SPEC.md`, `study.yaml`,
`compiled_study.json`, `config/`, `audit/`, `artifacts/`) exists yet, **on purpose** — see §5.3
and §10 for why authoring stopped here rather than working around three schema gaps.

This is the correct state for a study at STEP 3 of §6 (RESEARCH DECISION) that has discovered
its target cannot yet be expressed in `study.yaml`. It is not a stalled or broken study; the
decision document is explicit that `study.yaml` authoring is deliberately blocked pending either
a schema extension or an explicit researcher-approved workaround.

---

## 3. Agent roles mapped to the workflow

Full roster and rationale: `AGENTS.md` §11, `docs/SUBAGENT_ROSTER.md`. Mapped onto lifecycle
stages:

| Agent | Invoked at | Owns | May modify | May not decide | Escalates when |
|---|---|---|---|---|---|
| `repo-scout` | Before any plan; STEP 1–2 of §6 | Locating the authoritative implementation, execution-closure tracing, stale/duplicate-path detection | Nothing (read-only: Read/Grep/Glob) | Whether something is a defect vs. a design choice | Ambiguous ownership of a path |
| `lookahead-auditor` | Stage 4 (CAUSAL REVIEW) | Checklist A, B, C1–C3, F, G, H — "could this be known at T?" | Its own `audit/pass_NN.md` | Governance/completeness (C4, D, E) | Finds a completeness gap — refers to `contract-checker` in one line |
| `contract-checker` | Stage 5 (CONTRACT REVIEW) | Checklist C4, D, E — TRAIN/OOS separation, authorization, freeze/seal freshness, provenance, deliverables, model-integrity declarations | Its own `audit/contract_pass_NN.md` | Causality/look-ahead | Finds a causal issue — refers to `lookahead-auditor` |
| `implementer` | Any deterministic-defect repair, STEP 4–6 of §6 | Wiring, fixes, targeted tests, bounded fixtures, first-broken-stage tracing | Code, tests, config | Research semantics (target/population/chronology meaning) | Genuine semantic ambiguity |
| `research-executor` | Stage 7–15 (collection through OOS scoring) | Driving a sealed study through the lifecycle in order, producing declared artifacts | Run directories, artifacts | Whether a result is good — that's `analysis-decider`'s job | Authorization mismatch, stale freeze, prohibited year |
| `analysis-decider` | Stage 16–17 (ANALYSIS/DECISION) | Reading generated artifacts, model comparison, direction/maturity slicing, forward-outcome interpretation, the conclusion | Its own analysis write-ups | Fitting, tuning, re-running anything | Missing or inconsistent artifacts |
| `Explore` | Ad hoc, Claude-only | Not a role — a **model pin** to Haiku for the built-in fan-out search agent, so a routine "where is X" sweep doesn't run at orchestrator cost | — | — | — (use `repo-scout` for anything that feeds a plan or audit) |

**Ownership is exclusive.** An agent finding work outside its column refers it in one line and
moves on — it does not fix it itself. Worker/coding agents cannot spawn subagents; only the main
orchestrator invokes named gates. The causal and contract reviewers must be **distinct declared
identities** — `scripts/run_preexec_audits.py` enforces `AUDITOR_ROLE_REUSE`.

---

## 4. CLI / entry-point lifecycle map

`✓ = deterministic-auto-fix` (implementer fixes and re-runs the bounded check without asking) ·
`? = researcher-clarification` (genuine semantic ambiguity) ·
`⛔ = safety/authorization stop` (one of the six terminal conditions, `AGENTS.md` §6).

### 4.1 Lifecycle core

| Command | Stage | Prerequisites | Output | Common failure | Failure class |
|---|---|---|---|---|---|
| `python -m research_workflow.study_factory --config study.yaml [--out-dir studies]` | 0b | `research_decision.yaml`, `SPEC.md`, `study.yaml` authored | `studies/<id>/` tree | schema validation error | ✓ |
| `python -m research_workflow.prepare --study studies/<id>` | 1 | scaffolded tree | `compiled_study.json`, `audit/frozen_execution_manifest.json` | compile / phase0 regeneration error | ✓ |
| `python -m research_workflow.readiness --study studies/<id> [--reference-date ...] [--json] [--feature-authority active\|candidate]` | 2 | frozen manifest | `audit/readiness.json` | any R1–R10 fails | ✓ (fix at owning layer; §12 of `RESEARCH_WORKFLOW.md`) |
| `python -m research_workflow.preflight --study studies/<id> [--json] [--skip-tests]` | 3 | readiness CLEAR | `audit/preflight.json`, `audit/failure_packet.json` | any of 6 required checks fails or didn't run | ✓ |
| `lookahead-auditor` agent, or `research_workflow.causal_audit.run_causal_review` | 4 | preflight CLEAR | `audit/pass_NN.md` + `audit/status.json` | CRITICAL > 0, stale freeze | ? if genuine ambiguity, else ✓ |
| `contract-checker` agent, or `research_workflow.contract_audit.run_contract_review` | 5 | causal review issued | `audit/contract_pass_NN.md` + `audit/contract_status.json` | missing deliverable, unreachable terminal label | ✓ |
| `research_workflow.seal.generate_preexec_audit_seal` | 6 | both reviews CLEAR and fresh | `artifacts/preexec_audit_seal.json` | `PREEXEC_AUDIT_STALE` | ✓ (re-run stage 1, then 3–6) |
| `python backtests/run_nt_study.py --study studies/<id> --mode collect --stage day` | 7 | seal exists | `runs/<ts>_collect_day/` | runtime error, zero events, schema/surface violation | ✓ or ⛔ if data-safety |
| `python scripts/reconcile_runs.py [--runs-dir] [--study] [--dry-run] [--json]` | 8 | a run exists | `lifecycle.json` sidecar | — (classification only) | — |
| `research_workflow.experiment.authorize_experiment` | 9 | seal + reconciled run | `artifacts/experiment_authorization.json` | chronology missing/overlapping | ⛔ if ambiguous authorization |
| `--mode collect --stage full` (partitioned) via `collection.collect_period_partitioned` | 10 | authorization | one run dir per TRAIN year | authorization mismatch, prohibited year | ⛔ if prohibited year |
| `partitioning.reconcile_partitions` → `merge_partition_outputs` (**library-only, no CLI**) | 11 | all TRAIN years collected | merged frame | overlap, schema/dtype drift | ✓ |
| `modeling.fit_models` (**library-only**) | 12 | merged TRAIN frame | `artifacts/experiment_models.json` | non-TRAIN partition, outcome column in X | ⛔ if outcome leak (never loosen the guard) |
| `modeling.freeze_train_artifacts` (**library-only**) | 13 | fit complete | `artifacts/train_experiment_freeze.json` | non-TRAIN meta, outcome column in a frozen set | ⛔ |
| `experiment.assert_oos_open` (**library-only**) | 14 | TRAIN freeze exists | returns the freeze | `TrainFreezeRequired` | ✓ (freeze first) |
| `collection.collect_period(..., "oos")` (**library-only**) | 15 | OOS open | run dirs | freeze absent/stale | ⛔ |
| `analysis.analyze_results` / `research_workflow.analysis.classification_results` | 16 | OOS scored | `artifacts/experiment_analysis.json` | missing columns, OOS not open | ✓ |
| `analysis-decider` agent | 17 | analysis artifact | `results/STUDY_REPORT.md`, next `research_decision.yaml` | — | — |

**Historical, not the active OOS path:** `python scripts/generate_oos_unlock.py --study PATH
--year YEAR` — superseded by `experiment.assert_oos_open` + the TRAIN freeze; kept only for
studies built against it before the freeze mechanism existed.

### 4.2 Supporting / diagnostic

| Command | Purpose | Sealed-safe |
|---|---|---|
| `python scripts/resolve_execution_manifest.py --study PATH [--json]` | resolve the execution closure + composite | yes |
| `python scripts/run_preexec_audits.py --study PATH --pass-num N --type causal\|contract --ingest report.md --author "<who>"` | ingest an audit report, verify provenance, issue status | yes |
| `python scripts/run_bounded_study.py` | run a stage under time/memory/stale-progress limits, JSON status card | yes |
| `python scripts/validate_smoke.py --study PATH [--run-dir] [--date] [--json]` | canonical smoke acceptance, re-derives feature surface | yes |
| `python scripts/causal_lint.py` | AST lint for recurring causal defects (inside preflight) | yes |
| `python scripts/check_artifact_schema.py` | artifact + seal manifest schema/DAG validation | yes |
| `python scripts/check_model_binding.py` | model sha, feature count/order, binary classes, `predict_proba` | yes |
| `python scripts/check_feature_surface.py` | declared contract == produced surface, all-null refusal | yes |
| `python scripts/check_feature_promotion.py` | feature promotion evidence (§7) | yes |
| `python scripts/check_research_decision_fidelity.py --study PATH` | decision contract → SPEC/study fidelity — **mandatory before compile passes preflight** | yes |
| `python scripts/check_spec_fidelity.py` | SPEC → StudySpec fidelity | yes |
| `python scripts/find_first_parity_divergence.py` | **mandatory first step** for any parity failure | yes (diagnostic, never a gate) |
| `python scripts/safe_cleanup.py --target PATH --disposable-root PATH` | fail-closed recursive-deletion guard | — |
| `python scripts/sync_agents.py [--check]` | regenerate Codex/Antigravity agent defs from `.claude/agents/*.md` | yes |
| `python scripts/feature_ctl.py check\|promote [--feature] [--family] [--request NAME] [--legacy-study]` | V2 feature governance CLI | yes (check) |

---

## 5. The YAML / contract layer

### 5.1 What `StudySpec` can and cannot represent

`research/schemas/study_spec.py`. Top-level sections: `study, operation, instrument,
population, target, features, model, chronology, stratification, baseline, lineage, execution,
acceptance, bespoke`.

| Section | Belongs there |
|---|---|
| `study` | id, type (`flip_prediction` \| `bespoke`), metadata |
| `operation` | operation kind (`train_evaluate`, `artifact_reconstruction`, ...) — drives `deliverables_engine.py` |
| `instrument` | `symbol`, `venue` — the **governed instrument**, validated against loaded bars at R3 |
| `population` | candidate/observation definition — compiled by `population_engine.py` |
| `target` | `TargetSpec`: `type` (`flip`\|`excursion`\|`return`\|`composite`), `event`, `direction`, `horizon_seconds`, `confirmation` dict, `decision_reference`, `conditions`/`condition_logic`/`required_forward_outcomes` (composite targets, §CLOSED-1 below) |
| `features` | `feature_list` (ordered names) or `instances` (canonical `FeatureInstance` + parameters), `source_manifest`/`source_key`, `selection` rules, `derived_inputs` (non-`FeatureInstance` causal inputs, §CLOSED-2 below) |
| `model` | model family, hyperparameter declarations; `selection` — bounded, executable TRAIN-only search protocol (§CLOSED-4 below; formalized, not merely declared) |
| `chronology` | `train` / `dev` / `oos` / `prohibited` — must be non-empty and pairwise disjoint |
| `stratification`, `baseline`, `lineage` | slice/comparison/parent-study bindings |
| `execution` | data requirements, `dataset_id` binding (R1/DatasetSpec) |
| `acceptance` | `criteria: Dict[str, Any]` — **optional, unstructured** |
| `bespoke` | `reason`, `unsupported_contract_element` — required non-empty when `study.type: bespoke` |
| *(top-level)* | `required_gates` — machine-enforced pre-freeze gates (§CLOSED-3 below) |

**CLOSED — the three gaps below, first documented here, are now expressible.** Verified
against `study_spec.py` directly, plus end-to-end smoke tests exercising each mechanism
against real repo artifacts (`scripts/tests/test_study_spec_extensions.py`).

1. **Composite targets.** `TargetSpec.conditions` is a Pydantic discriminated union
   (`FlipConditionSpec` \| `ExcursionConditionSpec` \| `ReturnConditionSpec`, keyed on `kind`)
   composed by `condition_logic` (`AND`/`OR`). An excursion/return condition references a
   `TargetSpec.required_forward_outcomes` entry by id rather than embedding its own generation
   parameters; `target_engine.compile_target_contract` constructs a **real**
   `forward_outcomes.contracts.ForwardOutcomeSpec` from that entry (not an approximation), so
   the composite target's excursion measurements are causally label-only by construction — the
   same `OUTCOME_COLUMN_PATTERNS` guard that already protects forward-outcome tables applies
   here for free. A target with no `conditions` compiles exactly as it always has.
2. **Derived causal inputs.** `FeaturesSpec.derived_inputs`
   (`DerivedCausalInputSpec`, `kind: frozen_external_model_score`) binds `parent_study_id`,
   `parent_train_freeze_artifact` + its exact file-content sha256, per-arm `model_hashes`,
   `preprocessing_hash`, and the parent's `audit/status.json.audited_execution_composite_sha256`.
   `research_workflow/derived_inputs.py::verify_derived_causal_inputs` re-derives all of this
   against on-disk state at PREPARE time and fails closed on drift, invalidation (detected via
   the parent study's existing `*_INVALIDATION.md` convention), or a mismatch — never a warning.
   Availability is checked for causal ordering against the *child's own* declared
   `target.decision_reference` (`TIMESTAMP_CAUSAL_ORDER`), not merely enum membership.
3. **Machine-enforced pre-freeze gates.** `StudySpec.required_gates`
   (`RequiredGateSpec`) binds a gate id to a stage (`prepare`\|`readiness`\|`preflight`\|`seal`\|
   `train_freeze`), a schema-versioned artifact path, and a typed `scope_fields` list
   (`GateScopeField` enum — a typo fails Pydantic validation, not silently). `research_workflow/
   gates.py::assert_gates_satisfied` fails closed if the artifact is missing
   (`RequiredGateNotSatisfied`), stale relative to the study's current declared scope
   (`RequiredGateStale`, detected by recomputing the scope hash), or malformed
   (`RequiredGateArtifactMalformed`). Wired into every stage that can declare one.
4. **Model selection.** `ModelSpec.selection` (`ModelSelectionSpec`) plus
   `research_workflow/model_selection.py` — a real, bounded, executable TRAIN-only search
   (never unbounded AutoML): grid over `choice` domains only (refuses rather than truncates a
   grid exceeding `max_trials`), or random search where `max_trials` counts **unique**
   configurations (deterministic dedup from `random_seed`). `tuning_years`/
   `final_train_validation_years` are a distinct inner-TRAIN concept from `chronology.dev`
   (which already means OOS here) — a `StudySpec` validator rejects any overlap, and the runner
   independently re-checks every row. Final TRAIN validation may only accept/reject the
   already-selected winner — never re-select — and `modeling.freeze_train_artifacts` refuses
   outright on a gated `FAIL` (`ModelSelectionFinalValidationFailed`) or a hyperparameter/seed
   mismatch against the selection manifest (`ModelSelectionBindingMismatch`).

Full design rationale and the two-pass review that shaped these four mechanisms:
`docs/RESEARCH_WORKFLOW.md` §20. §10 below shows the original three gaps as they actually
appeared in a real research decision document before closure, kept for record.

### 5.2 Artifact layer

| Artifact | Written by | Frozen? | Role |
|---|---|---|---|
| `compiled_study.json` | `compiler.py` | no (regenerates on recompile) | `{study_id, study_type, spec_sha256, spec, contracts, strategy_class}` |
| `config/*.json` (population/target/feature/timestamp/execution/lineage/deliverables/baseline `_contract.json`) | `compiler.py` via engines | no | one file per compiled contract segment, machine-readable |
| `audit/frozen_execution_manifest.json` | `prepare.py` | **yes — the freeze** | binds the study's whole execution closure; any execution-affecting edit stales it |
| `audit/readiness.json`, `audit/preflight.json` | stages 2–3 | additive evidence | never rewrites the frozen manifest or status.json |
| `audit/pass_NN.md` + `audit/status.json` | causal reviewer | yes, per pass | machine-parsed `AUDIT_SUMMARY_V2` block is the only thing gates read |
| `audit/contract_pass_NN.md` + `audit/contract_status.json` | contract reviewer | yes, per pass | same protocol, disjoint scope |
| `artifacts/preexec_audit_seal.json` | `seal.py` | yes | proves both audits CLEAR and fresh against the frozen composite |
| `artifacts/experiment_authorization.json` | `experiment.py` | yes | content-hashed chronology binding |
| `artifacts/train_experiment_freeze.json` | `modeling.freeze_train_artifacts` | **yes — the TRAIN freeze** | feature sets, models, preprocessing, thresholds, deciles, `derivation_population: "train"`; OOS cannot open without it |
| `artifacts/experiment_models.json` | `modeling.fit_models` | no | model manifest |
| `artifacts/experiment_analysis.json` | stage 16 | no | analysis outputs |

### 5.3 Schema gaps as declared by a real researcher — `clean_tradable_reversal` (CLOSED)

**Status: closed.** All three gaps below are now expressible per §5.1's CLOSED items 1–3.
Quoted verbatim from `studies/clean_tradable_reversal/research_decision.yaml:198–225`
(`schema_constraints_found`) — kept as the historical record of what prompted the closure,
not as a current limitation:

> 1. TargetSpec (type/event/direction/horizon_seconds/confirmation) has no field for a
>    composite flip+MFE+MAE excursion-conditioned target; T1 cannot be expressed without
>    misusing `confirmation` ... or silently dropping the excursion conditions.
> 2. ModelSpec/FeaturesSpec has no field for a frozen EXTERNAL model's score as a derived
>    causal input bound to another study's model hash — only this study's own
>    `artifact_path`/`artifact_sha256` is representable.
> 3. No StudySpec field anywhere (StudyMetadata, TargetSpec, AcceptanceSpec, ExecutionSpec) can
>    declare a required pre-freeze pipeline gate (`TRAIN_TARGET_BALANCE_PASS`) that
>    PREPARE/READINESS/PREFLIGHT would actually enforce.

The researcher's own conclusion: *"both are misleading contracts, so authoring stopped here per
instruction rather than inventing a workaround."* This is the correct behavior under
`RESEARCH_WORKFLOW.md` §15 (`ANALYSIS_HARNESS_GAP`) and `AGENTS.md` §6 (capability-gap terminal
stop) applied to the *schema* layer rather than the analysis layer — the same principle, one
layer up.

---

## 6. New-study blueprint

| Step | Researcher input | Agent action | Artifact | Gate | Escalation |
|---|---|---|---|---|---|
| **0 — Research request** | question, population, target, inputs, chronology, instrument, timeframe, evaluation goal | none yet — fill `docs/templates/RESEARCH_STUDY_REQUEST_TEMPLATE.md` | filled template | — | — |
| **1 — Repo/capability discovery** | none | `repo-scout` checks existing canonical features (`feature_ctl.py check --request`), providers, data plans, target schemas, collectors, study types | `AGENT INTAKE RESULT` block in the template | — | — |
| **2 — Novelty classification** | none | classify every requirement against §7/§8 (already supported / parameter variation / needs verification / needs promotion / needs new implementation / requires researcher decision) | `NOVELTY_LEVELS` in the template | — | Level 4/5 items always escalate |
| **3 — Research decision** | approves/resolves ambiguities surfaced in step 2 | author `research_decision.yaml` — hypothesis, baseline, target semantics, prohibited/allowed changes, chronology | `research_decision.yaml` | `check_research_decision_fidelity.py` (later) | any Level 4/5 item unresolved |
| **4 — Study contract** | — | `study_factory` scaffold → `compiler.py` compile; if a schema gap exists (§5.1), stop here and report it rather than working around it | `SPEC.md`, `study.yaml`, `compiled_study.json`, `config/*.json` | schema validation | schema cannot represent the design (§5.3 pattern) |
| **5 — Readiness / pre-freeze validation** | — | `prepare` → `readiness` → `preflight` → `causal_audit` → `contract_audit`, autonomously fixing deterministic defects | `audit/*` | R1–R10, 6 preflight checks, both CLEAR | genuine semantic ambiguity found mid-audit |
| **6 — Seal** | — | `seal.generate_preexec_audit_seal` | `artifacts/preexec_audit_seal.json` | `PREEXEC_AUDIT_STALE` | — |
| **7 — TRAIN collection** | authorizes the run (nothing executes before the seal) | `research-executor`: smoke → reconcile → authorize → partitioned collect → merge | run dirs, `artifacts/train_collection_manifest.json` | authorization/prohibited-year check | prohibited year (⛔) |
| **8 — TRAIN model development** | model family / hyperparameter choices (per study type constraints) | `fit_models`, iterate on TRAIN only | `artifacts/experiment_models.json` | `PartitionMixing`/`SchemaSurplus` guards | outcome leak (never loosen the guard) |
| **9 — TRAIN freeze** | confirms readiness to lock | `freeze_train_artifacts` | `artifacts/train_experiment_freeze.json` | `assert_causal_feature_surface` | — |
| **10 — OOS** | explicit go-ahead to open OOS | `assert_oos_open` → `collect_period(..., "oos")` | run dirs | freeze must exist and bind | — |
| **11 — Analysis / decision** | reviews the conclusion | `analysis-decider`: `analyze_results`, integrity-check disclosure | `results/STUDY_REPORT.md`, next `research_decision.yaml` | — | — |

---

## 7. Novelty routing matrix

### A. Existing canonical feature, new parameter instance

Examples: same feature at a different timeframe/window/lookback; completed vs. forming bar
state.

`validate_feature_instance()` (`features/registry.py:888–1005`) is the actual arbiter, in this
order: canonical name exists → all parameters in `parameter_schema` → bar state in
`supported_bar_states` → temporal semantics unambiguous (`AMBIGUOUS_TEMPORAL_SEMANTICS` if
`timeframe`+`update_every` without `bar_state`, or `timeframe`+`window` together) → duration
strings well-formed → parameter values in `supported_parameter_values` domain → required
parameters present → parameter combination in `supported_parameter_combinations`.

| Condition | Routing |
|---|---|
| Parameter value is **already inside** `supported_timeframes` / `supported_bar_states` / `supported_parameter_values` of a `verified` definition | **Automatic (Level 1)** — declare the instance, `validate_feature_instance()` accepts it. This is the only case Level 1 covers. |
| Parameter value is **not yet** inside a `verified` definition's declared support set — even with the formula provably unchanged | **Level 2, corrected** — see below. Not automatic. |
| `timeframe`+`update_every` without `bar_state`, or `timeframe`+`window` together | **Fail closed** — `AMBIGUOUS_TEMPORAL_SEMANTICS`. Never resolved by adding a default; researcher clarification required |
| Formula or reset semantics genuinely differ at the new value | **Level 3** — new provider work, full promotion path (§B) |

**Corrected rule (was too permissive — see below): adding a new value to a verified
definition's declared support set is Level 2, never Level 1, even when the formula is
unchanged.** `validate_feature_instance()` only proves a requested value is *already inside*
`supported_timeframes`/`supported_parameter_values` — it proves nothing about a value being
*added* to that set. Before this closure, `scripts/check_feature_promotion.py` only re-checked
that a promotion record's `supported_parameter_schema` (the parameter *names*) matched the
definition — it did not independently verify that a newly-added parameter *value* carried its
own causal/parity evidence, so a definition's `supported_timeframes` list could in principle be
hand-extended without new audit evidence. **This is now closed, not just documented:**
promotion records may declare `verified_parameter_values: Dict[str, List[Any]]` — the parameter
values that actually carry independent evidence, as opposed to `supported_*`, which is merely
what's currently declared syntactically valid. `check_feature_promotion.py`'s canonical check
now raises `UNVERIFIED_PARAMETER_VALUE` (naming the definition, parameter, and value) whenever
a `supported_*` value has no counterpart in a declared `verified_parameter_values` block.
Backward compatible by construction — a definition that never opts into
`verified_parameter_values` is unaffected, mirroring the existing
`feature_lifecycle_baseline.json` grandfather pattern ("baseline cannot grow, only shrink"),
applied going forward rather than retroactively. Regression test: `scripts/tests/
test_study_spec_extensions.py::test_l_unverified_parameter_value_detected_when_declared`.

Adding `15m` to `regime_efficiency`'s `supported_timeframes`, concretely: confirming the
parameterized provider in `features/trackers/generic_*.py` actually routes/aggregates that
cadence, a test that names the feature at that value, and an explicit promotion-record update
citing causal/parity evidence for `15m` specifically — before `FEATURE_PROMOTION` preflight can
accept it on a definition that has opted into value-specific evidence.

### B. New / unregistered feature

Required path, each stage catches silent inline features:

1. Researcher defines semantic intent — formula, provider, causal/reset/null semantics.
2. Canonical identity declared (`parameter_schema`, `supported_bar_states`,
   `supported_timeframes`).
3. Implementation: a new/extended provider in `features/trackers/generic_*.py` only if the
   formula or state-transition semantics genuinely differ — never "to support a timeframe."
4. Test added under `features/tests/` that **names the feature**.
5. Promotion: `scripts/check_feature_promotion.py` requires (a) implementation resolves, (b) a
   test names the feature or carries `@covers_feature`, (c) an explicit promotion record with
   `causal_audit_artifact`, `audited_execution_composite_sha256`, `promoted_by`,
   `reviewed_implementation_sha256` matching current.
6. `features/authority/active.json` atomically re-pointed via `activate_frozen_candidate()`.

**It cannot silently become an inline feature** — `check_feature_promotion.py` is one of
PREFLIGHT's six required checks (§1.3, §4.1); an unresolved or unpromoted feature fails preflight
before any collection runs. **Level 3.**

### C. Different timeframe

| Case | Routing |
|---|---|
| Existing feature, timeframe already within declared `supported_timeframes` | Level 0/1 — automatic |
| Existing feature, timeframe not yet declared, formula unchanged | **Level 2** (corrected, §A) — requires routing/aggregation confirmation, a value-naming test, and a promotion-record update citing value-specific evidence; `UNVERIFIED_PARAMETER_VALUE` machine-enforced when the definition opts into `verified_parameter_values` |
| "Rolling 300s" vs. "completed 5m calendar bar" | These are **different `FeatureInstance` parameter shapes**, not a timeframe choice — `window: 300s, update_every: 1s` vs. `timeframe: 5m, bar_state: completed`. Conflating them is `AMBIGUOUS_TEMPORAL_SEMANTICS` or a silent semantic error; **always requires the researcher to state which one explicitly (Level 2 minimum)** |
| Formula/reset semantics differ at the new timeframe | Level 3 — new provider work, promotion path (§B) |

### D. Different futures contract / instrument

`instrument.symbol`/`venue` in `study.yaml` is validated at R3 (`verify_instrument_precision`)
against the loaded bars' `instrument.id`, `price_increment`, and `close.precision`. Catalogs are
registered in `PRODUCT_CATALOGS` (`backtests/nt_runtime/data_plan.py:121–161`); confirmed on
disk today: `data/catalog/NQ_v0_2020_2026/`, `data/catalog/ES_v0_2020_2026/`,
`data/catalog/YM_v0_2024/`.

| Case | Routing |
|---|---|
| NQ → ES/YM, catalog already registered and on disk | **Level 1** — change `instrument.symbol`, R3 validates automatically; but **feature and target compatibility is not automatically re-verified** — a feature tuned/verified against NQ's tick/price regime is not thereby verified for ES. Researcher must confirm intent |
| NQ → MNQ, or any symbol not in `PRODUCT_CATALOGS` / no catalog on disk | **Level 3** — register in `PRODUCT_CATALOGS`, build via `scripts/build_v0_catalog.py --product <SYM> --years <Y> --streams 1s,1m`, R1 dataset-identity check must then pass |
| Continuous vs. specific-expiry contract, or roll-handling change | **Level 4** — roll logic is baked into the `.v.0` catalog at build time ("process once, use forever" per `docs/DATA_CATALOG.md`); this is a data-identity change, not a study parameter, and always needs explicit approval + a fresh R1/R2 pass |

**A contract symbol change must never silently imply identical semantics** — R3 will catch a
*precision* mismatch mechanically, but session assumptions, ATR scale, and feature verification
status do not carry over and are not machine-checked. Flag as a caveat and require confirmation
even when R3 passes cleanly.

### E. New data source / catalog

Catalogs are built only via `scripts/build_v0_catalog.py` (or the ES-specific builder), keyed
into `PRODUCT_CATALOGS`, and opened only through `resolve_catalog_plan`/`resolve_data_plan` —
`GovernedCatalogNotFoundError` fails closed rather than falling back to a CWD-relative path
(`data_plan.py:254–266`). The `.v.0` volume-continuous rule (project HARD RULE) is enforced
**structurally**, not by a runtime substring check: only the registered builder scripts produce
catalogs, and only registered `PRODUCT_CATALOGS` entries are opened. There is no code path today
that opens an arbitrary unregistered catalog without editing `data_plan.py` — which is itself a
reviewed code change.

**Always Level 5 (safety/authorization boundary):** a genuinely new data source (new vendor, new
raw file family, non-`.v.0` data) has no automatic path at all and must not be silently
substituted (`RESEARCH_WORKFLOW.md` §13). Explicit researcher authorization is required before
any code is written to ingest it.

### F. New target

| Case | Routing |
|---|---|
| `type: flip \| excursion \| return`, single condition, standard horizon/confirmation | **Level 1** — expressible today via `TargetSpec` |
| Multi-horizon target using existing `type`s independently, compared post-hoc | **Level 2** — expressible, but compare via `research/analysis/`, never pooled without a stated method |
| Composite target (e.g. flip AND MFE-threshold AND MAE-threshold, as one label) | **Level 3/4 — schema extension needed.** Confirmed absent from `TargetSpec` (§5.1). Requires either a `bespoke` study type with `custom_code_allowed: True` and an explicit `bespoke.reason`, or a `TargetSpec` schema extension. Either path needs researcher approval — **target semantics always require it**, regardless of mechanism |
| Confirmation target consuming another study's frozen score | See §G |

### G. New derived input — frozen upstream model score

Distinguish explicitly:

- **Canonical market `FeatureInstance`** — resolved through `features/registry.py`, has a
  provider, is promotable, lives in `features/authority/active.json`.
- **Derived causal model input** — a frozen *other study's* model score. This is not a
  `FeatureInstance` at all; it has no provider, no promotion path, and — confirmed in §5.1 —
  **no `FeaturesSpec` field to represent it today.**

Required provenance regardless of schema support (this is what `clean_tradable_reversal`
actually recorded by hand in `research_decision.yaml`, verbatim structure):

```yaml
stage1_dependency:
  parent_study: <study_id>
  frozen: true
  retrain_prohibited: true
  frozen_execution_composite_sha256: <sha256>
  train_experiment_freeze_artifact: artifacts/train_experiment_freeze.json
  model_artifact: artifacts/<model>.joblib
  model_hashes: {<arm>: <sha256>, ...}
  preprocessing_hash: <sha256>
derived_causal_inputs:
  - name: <input_name>
    kind: frozen_external_model_score
    not_a_feature_instance: true
    binds_to: [stage1_dependency.model_hashes, stage1_dependency.preprocessing_hash,
               stage1_dependency.train_experiment_freeze_artifact]
```

**Always Level 3 (schema gap) today** — flag it in the request template's `SCHEMA_GAPS` field
rather than declaring it as a feature instance, which would be a semantically-wrong field reuse.

### H. New model family / hyperparameter search (CLOSED — now formalized and executable)

**Level 1 for a study that stays within `ModelSpec.selection`'s bounded protocol; Level 3
for anything it cannot express (a search method or metric this module does not implement).**

- `ModelSpec.selection` (`ModelSelectionSpec`) declares `allowed_families`, bounded
  `tunable_hyperparameters` domains (`choice`/`int_range`/`float_range`, `log_scale`),
  `search_method` (`grid`\|`random`\|`none`), `max_trials`, `random_seed`,
  `tuning_years`/`final_train_validation_years` (a new inner-TRAIN concept, distinct from
  `chronology.dev` which already means OOS), `primary_selection_metric`(+direction),
  `secondary_metrics`, `simpler_model_tie_preference`, and `final_validation_policy`
  (`gated`\|`report_only`) with typed `final_validation_requirements` bounds.
- `research_workflow/model_selection.py::run_model_selection` **executes** the declared
  search — grid over `choice` domains only (refuses rather than truncates a grid exceeding
  `max_trials`); random search where `max_trials` counts unique configurations, deduplicated
  deterministically from `random_seed`, stopping cleanly (not an error) if a small declared
  space is exhausted first. TRAIN-only enforcement is now mechanical, not just the pre-existing
  guards: every row's `_selection_role`/`_year` is checked against the declared year sets
  (`SelectionPartitionMismatch`), on top of the compile-time chronology cross-check that
  already rejects an OOS/prohibited year being declared as a tuning year.
- Final TRAIN validation may only accept or reject the already-selected winner — the function
  that evaluates it takes the winner as its sole argument and cannot re-enter the search loop.
  `modeling.freeze_train_artifacts` refuses outright on a gated `FAIL`
  (`ModelSelectionFinalValidationFailed`) or a hyperparameter/seed mismatch against the
  selection manifest (`ModelSelectionBindingMismatch`) — the freeze cannot accept a model whose
  family/hyperparameters cannot be traced to the declared protocol.
- Full design and the review corrections that shaped it: `docs/RESEARCH_WORKFLOW.md` §20.4.

### I. New forward outcome / economic label

`forward_outcomes/` is study-agnostic (§1.4). A new economic label is:

- **Level 1–2** if it's a new `ForwardOutcomeSpec` (horizon, ATR normalization, censoring policy,
  entry reference) — the schema already generalizes over these via `build_outcome_columns()`.
- Any attempt to move a forward-outcome column into a causal feature set (`X`) is **prohibited
  by construction** — `guard.py`'s `OUTCOME_COLUMN_PATTERNS` (21 anchored regexes) plus
  `assert_causal_feature_surface()` fail closed at both fit time and freeze time. This is not a
  novelty-routing decision; it is never permitted regardless of researcher intent, full stop.

### J. Changing TRAIN/OOS years

**Always Level 5.** Chronology in `study.yaml` is content-hashed by `authorize_experiment()`; a
stale authorization is refused. Changing TRAIN/OOS years after any collection, fit, or freeze
invalidates that freeze and risks OOS contamination if the new TRAIN window overlaps prior OOS
observation. Requires explicit researcher approval every time, never inferred from "the study
needs more data."

### K. Changing session/RTH/ETH semantics

**Always Level 4, requires explicit approval + parity testing.** This is causal behavior, not a
cosmetic filter: candidate *emission* may be restricted to RTH while providers must still *see*
ETH bars to maintain correct running state (`RESEARCH_WORKFLOW.md` §7 — "ETH state may remain
causally necessary even when candidate emission is RTH"). Cutting ETH history out of the replay
as an "optimization" is exactly the mistake this rule exists to prevent.

### L. Changing reset/null/state semantics

**Always Level 4.** A reset policy, null policy, or state-machine change to a canonical
definition is a semantic identity change, not a parameter — it changes what the feature *means*,
not merely when it's read. Requires researcher approval and re-promotion (§B), never a silent
edit to an existing `verified` definition.

---

## 8. Novelty severity levels

| Level | Meaning | Agent proceeds automatically? | Tests required | Clarification? | Approval? | Freeze/seal staleness |
|---|---|---|---|---|---|---|
| **0 — Existing** | Already supported exactly | Yes | none beyond existing suite | No | No | No |
| **1 — Parameter variation** | Existing verified feature/provider within declared semantics | Yes | targeted (`select_required_tests.py`) | No | No | Recompile only if instance list changed |
| **2 — Verification/promotion** | Implementation exists, requested instance not yet verified | Yes, but blocks at PREFLIGHT's `FEATURE_PROMOTION` check until promoted | promotion evidence test naming the feature | Sometimes (if semantics genuinely ambiguous) | No, unless promotion requires an audit artifact | Stages 1–3 must be redone after promotion |
| **3 — New capability** | New feature/provider/target/data-plan/model integration required | No — implement, then re-enter lifecycle at STEP 4 | new implementation tests + promotion evidence | Usually | Yes, if it changes research semantics | Yes — full stages 1–6 |
| **4 — Research semantic change** | Target, population, chronology, session semantics, causal meaning changes | No | full targeted + affected causal/contract re-audit | Yes, always | Yes, always | Yes — always stales an existing freeze/seal |
| **5 — Safety/authorization** | New data source, prohibited years, destructive storage operation, OOS boundary | No — terminal stop | N/A until authorized | Yes, always | Yes, always, explicit | N/A — nothing proceeds until authorized |

---

## 9. When the researcher will be asked — vs. when the agent should not ask

### When the researcher will be asked

- Target meaning is ambiguous (composite condition, unclear horizon, unclear censoring).
- A requested feature has no canonical semantic definition and none can be inferred safely.
- A requested timeframe could mean rolling window or completed calendar bar and the request
  doesn't say which.
- Forming/completed bar state is unspecified for a request that matters causally.
- Contract/instrument semantics differ from what's governed today (§7.D).
- A genuinely new data source is proposed (§7.E).
- TRAIN/OOS chronology would change (§7.J).
- Session/reset/null-state semantics would change (§7.K, §7.L).
- A new external-model dependency is proposed (§7.G).
- The schema cannot truthfully express the design (§5.1, §5.3) — report the gap, do not invent a
  workaround that produces a misleading contract.
- Data safety or authorization is uncertain in any way.

### When the agent should NOT ask — fix it

- A stale generated artifact (recompile/re-run the resolving script).
- A broken import.
- A missing deterministic manifest (re-run the script that produces it).
- A resolver bug in `research_workflow`/`research`/`features` code.
- A failing targeted test with an obvious fix.
- A stale seal after an execution-affecting code edit — this is the expected consequence of
  `RESEARCH_WORKFLOW.md` §3.2, not a new decision; re-run stage 1 then redo 3–6.
- A missing directory that a scaffold step should have created.
- A shim path defect (e.g. one of the seven `scripts/` compatibility shims misrouting).

These map exactly onto `AGENTS.md` §6's six terminal-stop conditions (genuine semantic
ambiguity, data safety risk, authorization ambiguity, cannot preserve causality/TRAIN-OOS
correctness, capability gap, prohibited data access risk) versus everything else, which is a
gate failure to fix, not a reason to stop.

---

## 10. Worked example — `clean_tradable_reversal`

Had `docs/templates/RESEARCH_STUDY_REQUEST_TEMPLATE.md` existed when this study was scoped, the
`AGENT INTAKE RESULT` section would have read approximately as follows (reconstructed from the
actual `research_decision.yaml` — no research results beyond what's needed to show the process):

```
EXISTING_CAPABILITIES:
  - Stage-1 parent study (clean_maturity_flip_model_rolling_productivity) fully sealed,
    TRAIN+OOS complete, 16 causal-audit passes, frozen composite
    7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8
  - forward_outcomes module can compute MFE_300s_atr / MAE_300s_atr for the primary
    population once TRAIN collection exists
  - 21-input Arm C feature surface: standard canonical FeatureInstances, no new providers needed

NOVELTY_LEVELS:
  - Primary population (2,702 TRAIN P90 first-crossing regimes): Level 1 (existing population
    definition, parameter selection)
  - Arm C feature surface: Level 0/1 (canonical, already verified)
  - T1 target (composite flip+MFE+MAE): Level 3/4 — schema gap, see below
  - stage1_model_c_score as derived input: Level 3 — schema gap, see below
  - TRAIN_TARGET_BALANCE_PASS pre-freeze gate: Level 3 — schema gap, see below

MISSING_CAPABILITIES / SCHEMA_GAPS:
  1. TargetSpec cannot express a composite MFE/MAE-conditioned excursion target.
  2. FeaturesSpec/ModelSpec cannot express a frozen external model's score as a derived
     causal input with cross-study provenance binding (model hash, preprocessing hash,
     freeze artifact reference).
  3. No StudySpec field can declare a required, machine-enforced pre-freeze gate.

CLARIFICATIONS_REQUIRED: none outstanding — target semantics, entry reference (NEXT_BAR_OPEN),
  horizon (300s), and censoring were fully specified by the researcher in research_decision.yaml.

APPROVAL_REQUIRED:
  - Whether to extend StudySpec (framework change, needs the §1 escalation path in
    RESEARCH_WORKFLOW.md) or accept a `bespoke` study type with documented justification.
  - Confirmation that TRAIN_TARGET_BALANCE_PASS must be run and its output recorded in
    research_decision.yaml BEFORE study.yaml is authored, per the decision document's own
    enforcement_note.

AUTO_FIXABLE_ITEMS: none — this study is correctly blocked on a genuine capability gap, not a
  deterministic defect.

PROPOSED_EXECUTION_PLAN:
  1. Run TRAIN_TARGET_BALANCE_PASS as a bounded, non-authoritative diagnostic against the
     primary population using research_workflow.forward_outcomes (no study.yaml required for
     this — it can run against the frozen Stage-1 model's candidate set directly).
  2. Record required_outputs back into research_decision.yaml.
  3. Decide schema-extension vs. bespoke-type, with researcher sign-off, before scaffolding
     study.yaml.

EXPENSIVE_RUN_NOT_STARTED: true
```

This demonstrates exactly what the template is for: it would have caught all three schema gaps
and the pre-freeze gate requirement **before** any code was written, using only the information
already in the researcher's own decision document.

---

## 11. Current workflow gaps

Proven from current implementation only.

### CLOSED (previously listed here — see `docs/RESEARCH_WORKFLOW.md` §20 for the mechanism)

- ~~StudySpec cannot represent a composite MFE/MAE-conditioned target~~ — closed via
  `TargetSpec.conditions`/`required_forward_outcomes` (§5.1 item 1).
- ~~StudySpec cannot represent a derived causal input bound to another study's frozen
  model~~ — closed via `FeaturesSpec.derived_inputs` + `research_workflow/derived_inputs.py`
  (§5.1 item 2).
- ~~No explicit pre-freeze custom-analysis gate mechanism~~ — closed via
  `StudySpec.required_gates` + `research_workflow/gates.py` (§5.1 item 3).
- ~~Model-selection / hyperparameter-search protocol incompletely formalized~~ — closed via
  `ModelSpec.selection` + `research_workflow/model_selection.py`, including a governance-
  consequential final-validation gate (§7.H).

### SHOULD_FIX_BEFORE_NEXT_TRAIN

- **`clean_tradable_reversal`'s `TRAIN_TARGET_BALANCE_PASS` gate is declared but not yet
  satisfied.** The schema/contract closure above makes the study expressible
  (`studies/clean_tradable_reversal/study.yaml` now exists and compiles — §10); the gate
  artifact itself still needs the actual TRAIN-only MFE/MAE balance diagnostic run before
  `PREPARE` can proceed. This is the study's own next step, not a framework gap.
- **`AcceptanceSpec.criteria` remains optional and unstructured** for anything short of a
  named `required_gates` entry — a study wanting a pre-freeze check *not* worth declaring as a
  full gate still has no lightweight structured place for it. Minor; not blocking.

### NON_BLOCKING_TECH_DEBT

- `scripts/generate_oos_unlock.py` remains present as a historical/superseded OOS path,
  correctly marked as such in `RESEARCH_WORKFLOW.md` §11 and confirmed still on disk — kept only
  for studies built against it before `experiment.assert_oos_open` existed. No action needed
  beyond continuing not to use it for new studies.
- `research_workflow/forward_outcomes/` has no CLI entry point — every invocation is
  library-only, driven from `lifecycle.py` or a study's own analysis step. Not a defect, but
  worth noting for anyone expecting a `scripts/*` wrapper that doesn't exist.
- **`research/study_types/bespoke.py::BespokeStudyCompiler.compile()` never populates a
  `"deliverables_contract"` key**, so `compiler.compile_study()` raises `KeyError` for any
  `study.type: bespoke` study compiled through the directory-writing path (confirmed against
  three real studies in this repo: `bespoke_population_parity_smoke`,
  `test_level_break_collector`, `test_minimal_checkpoint_collector`). Pre-existing, unrelated to
  the §20 closure — discovered while proving backward compatibility (§12) — and out of this
  change's scope to fix.
- **`research_workflow/tests/test_audit_execution_api.py::
  test_contract_api_executes_and_writes_evidence`** fails on the unmodified baseline (confirmed
  via `git stash`) — a synthetic-fixture test whose monkeypatched `contract_audit.run_contract_review`
  call returns `BLOCKED` where the test expects `CLEAR`. Pre-existing, unrelated to this change.

---

## 12. Validation performed

- Every script path cited above was confirmed to exist on disk (`scripts/*.py`,
  `research_workflow/*.py`, `research/**/*.py`, `backtests/nt_runtime/*.py`,
  `features/*.py`).
- Every YAML/JSON artifact named was confirmed present in at least one governed study directory:
  the full lifecycle set (`compiled_study.json` through `artifacts/final_research_decision.md`)
  in `studies/clean_maturity_flip_model_rolling_productivity/`; the single-file design-checkpoint
  state in `studies/clean_tradable_reversal/`.
- Agent roster (`repo-scout`, `lookahead-auditor`, `contract-checker`, `implementer`,
  `research-executor`, `analysis-decider`, `Explore`) cross-checked against `.claude/agents/*.md`
  on disk and matches `AGENTS.md` §11 exactly.
- `data/catalog/NQ_v0_2020_2026/` and `data/catalog/ES_v0_2020_2026/` both confirmed present on
  disk (not just referenced by builder scripts).
- No legacy/V1 feature flow, bespoke per-study collector, or `scripts/generate_oos_unlock.py`
  presented as an active/preferred path anywhere above — all three are explicitly marked
  historical/superseded.
- No 2025/2026 data referenced as usable; the worked examples use 2021–2024 TRAIN/OOS periods
  as recorded in the actual studies.
- The `clean_maturity_flip_model_rolling_productivity` → `clean_tradable_reversal` linkage was
  verified by direct hash comparison, not assumed: the parent's
  `audit/status.json.audited_execution_composite_sha256` and the child's
  `research_decision.yaml.stage1_dependency.frozen_execution_composite_sha256` are the identical
  string `7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8`.

### §20 closure — additional validation

- Every `studies/*/study.yaml` on disk (10 studies) was validated against the extended schema
  directly, not sampled: all 10 pass `StudySpec.model_validate` unchanged
  (`scripts/tests/test_study_spec_extensions.py::test_k_every_existing_study_yaml_still_validates_and_recompiles`).
  `spec_sha256` does change for every study — a one-time, deliberate migration event, not a
  bug — matching the codebase's own documented convention in `ExecutionSpec`
  (`study_spec.py:268–274`).
  `compiled_study.json` was regenerated for the 6 studies that recompile cleanly through the
  directory-writing path; the 3 that hit the pre-existing `bespoke.py` `KeyError` (§11) were
  left at their original committed state rather than partially migrated.
- `derived_inputs.py`, `gates.py`, and `model_selection.py` were each verified end-to-end against
  real repository state, not only synthetic fixtures: `derived_inputs.py` against the actual
  `clean_maturity_flip_model_rolling_productivity` repaired freeze (both the accept and the
  `PARENT_ARTIFACT_INVALIDATED` reject path, using the real original vs. repaired artifacts);
  `check_feature_promotion.py`'s tightened check against the real
  `features/feature_definition_promotions.json` (confirmed a no-op — zero existing records
  declare `verified_parameter_values`, so nothing already promoted is newly rejected).
- Full targeted regression suite after the change: `scripts/tests/test_readiness.py`,
  `scripts/tests/test_generic_contract_audit.py`, `scripts/tests/test_study_factory.py`,
  `research_workflow/tests/`, plus the new `test_study_spec_extensions.py` (30 tests) — 100
  passed, 1 pre-existing failure confirmed present on the unmodified baseline via `git stash`
  (unrelated to this change; logged under §11 tech debt).

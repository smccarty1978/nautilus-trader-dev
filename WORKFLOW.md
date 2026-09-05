# WORKFLOW.md — how research is done here (Platform V2)

**Read this first.** It describes the current way to work. History lives in `docs/DOCUMENT_MAP.md`;
the authoritative system description is `docs/RESEARCH_WORKFLOW.md` (§21 for Platform V2).
Field-by-field YAML: `docs/RESEARCH_YAML_REFERENCE.md`. Ten-minute version: `docs/QUICKSTART.md`.
Agents: `docs/AI_AGENTS.md`. Turning a chat discussion into a spec: `docs/RESEARCH_DISCUSSION_TO_YAML.md`.
Running several studies at once: §M **Concurrent research projects**. Keeping sessions short and cheap: §N **Study session budget, phases and handoffs**.

Platform authority: tag `baseline/2026-09-platform-v2-proven`.

---

## A. Platform V2 in one page

```
research question
  -> python scripts/research.py study new <id>          (branch + sibling worktree + lease + v2 skeleton)
  -> python scripts/research.py cap search / describe   (find registered primitives; never guess ids)
  -> studies/<id>/study.yaml                            (six-kind declarative grammar)
  -> python scripts/research.py study compile --study studies/<id>
       -> compiled_plan.json                            (CompiledPlan: plan_sha256, closure composite, binding proof)
       -> or a typed CapabilityGap                      (MISSING_CAPABILITY, INVALID_PARAMETERIZATION, AMBIGUOUS_TEMPORAL_SEMANTICS,
                                                         UNAVAILABLE_STREAM, UNSUPPORTED_COMPOSITION, SEMANTIC_DECISION_REQUIRED)
  -> python scripts/research.py study run --study studies/<id> --through <stage> --execute-authorized
       compile -> prepare -> readiness -> preflight -> tests -> causal_audit -> contract_audit -> seal
       -> smoke -> collection -> reconcile -> merge -> fit -> freeze -> oos -> analyze -> close
       (`--execute-authorized` is a real gate: every stage after `seal` -- smoke through close --
       is BLOCKED with `EXECUTION_NOT_AUTHORIZED` unless the flag is present; `--through seal` or
       earlier never needs it, and `--inspect`/`--dry-run` are unaffected)
  -> runtime host (research_workflow/host) replays the plan causally; the sink writes columnar frames
  -> collection frames -> fit / score (model store) -> freeze -> authorized OOS -> analysis
  -> one causal auditor + one contract auditor read compact packets; `research audit ingest` binds their reports
  -> close: artifacts/study_closure.json is terminal
```

Two facts define the platform:

* **A normal new study contains zero Python.** Its `study.yaml` composes registered primitives; the
  controller owns every stage; the host executes the compiled plan. If a study needs bespoke Python,
  that is a platform gap: raise it as a typed CapabilityGap and add a reusable primitive (§E).
* **Historical studies are references, not templates.** Sealed studies keep their historical runtime
  authority at their own commit. They are never recompiled, resealed, migrated or copied. The three
  Platform V2 proof studies (`studies/v2_shape_*`) are the closest thing to templates; `docs/examples/`
  holds compile-tested specs.

Old runtime policy: `LEGACY_ONLY_FOR_NEW_RESEARCH` (`research_workflow/policy.py`). `study new` only
creates v2 studies; `study compile` and `study run` refuse a new v1 study.

## B. Golden rules

1. Streaming causal execution only. Bars are delivered in `ts_init` order; nothing reads ahead.
2. `ts_init` (bar close / availability) controls visibility; `ts_event` (bar open) never does.
3. No look-ahead: a coarser bar closing exactly at the epoch is a context stream, visible strictly before the next epoch.
4. No protected OOS until authorized: dev years open only through the `oos` stage after the TRAIN freeze; prohibited years never open.
4a. `chronology.windows` NARROWS an authorized train/dev year to explicit dates; it never opens a year the roles did not authorize.
5. One writing agent per git worktree; `study new` gives every study its own branch and sibling worktree.
6. Canonical sparse 1s data is never forward-filled (Dataset V2 is native rows only).
7. No custom study event loops, collectors, drivers or merge scripts for normal studies.
8. Deterministic work belongs to scripts and the controller, not to model reasoning or prompts.
9. Use a typed CapabilityGap rather than a study-local hack.
10. Existing capability before new capability; reusable capability before bespoke implementation.
11. Historical scientific authority is immutable (seals, target authorities, closures, frozen frames).
12. A model's scientific identity (lineage, contracts, identities) is distinct from its representation (joblib/native/onnx bytes).
13. New studies use Platform V2; the old runtime is historical only.
14. Semantic decisions (horizon anchoring, same-bar collision, session precedence, timeout-as-negative) are declared in YAML, never hidden in code.
15. Long jobs run detached (`nohup python -u ... & disown`) and are resumed with the same command; the controller refuses a second live run on the same study.

## C. Repository map (actual paths)

| Category | Purpose | Canonical path(s) | Edit normally? | Generated? | CLI |
|---|---|---|---|---|---|
| Platform V2 grammar | Six-kind spec models | `research_workflow/grammar/spec.py` | NO (platform change) | NO | `research study compile` |
| Compiler | Static compile, typed gaps, closure | `research_workflow/grammar/compiler.py`, `plan.py`, `gaps.py`, `expansion.py` | NO | NO | `research study compile` |
| Predicates | Tiny predicate language | `research_workflow/grammar/predicates.py`, `research_workflow/host/predicate_eval.py` | NO | NO | — |
| Capability registry (seeds) | Hand-maintained seed entries | `research_workflow/capabilities_index.yaml`, `research_workflow/capabilities.py` | via `cap propose/scaffold/promote` | NO | `research cap list/search/describe` |
| Generated capability registry | Introspected registry | `research_workflow/capabilities/registry.json` | NO | YES | `research cap generate [--check]` |
| Feature implementations | Provider code | `features/library.py`, `features/library_mtf.py`, `features/trackers/generic_*.py` | via capability flow | NO | `research cap list features` |
| Feature metadata / definitions | Canonical identities | `features/registry.py` (`FeatureDefinition`), `features/CANONICAL_FEATURE_REFERENCE.yaml` | NO | YAML yes (`scripts/generate_canonical_feature_reference.py`) | `research cap describe <feature>` |
| Trackers (host bindings) | Stateful causal state | `features/trackers/host_bindings.py` (+ `features/trackers/*.py` engines) | via capability flow | NO | `research cap list trackers` |
| Trigger engine | OBSERVE→WATCH→ARMED→ENTERED | `research_workflow/host/triggers.py` | NO | NO | — |
| Outcome contracts / kernel | Label / trade contracts | `research_workflow/host/outcomes.py`, oracle `research_workflow/target_replay_oracle.py` | NO | NO | — |
| Entry references | Executable vs research marks | `research_workflow/entry_references.py` | NO | NO | `research cap list entry_references` |
| Runtime host | Mux, strategy, sink | `research_workflow/host/`, `research_workflow/host_runner.py`, lint `scripts/lint_host.py` | NO | NO | — |
| Provider bindings | Feature host | `research_workflow/provider_host.py`, `features/trackers/host_bindings.py` (`FeatureHostBinding`) | NO | NO | — |
| Model families | Estimator construction | `research/analysis/modeling.py` (`_build_estimator`, `SUPPORTED_ESTIMATORS`) | NO (add a family = platform change) | NO | `research cap list model_drivers` |
| Preprocessing | Identity (v2 uses none) | recorded as `preprocessing_contract_sha256` in lineage | — | — | — |
| Model store | Bytes + manifests | `research_workflow/model_store.py`; root `~/.nt_research/models/models/<id>/` | NO | YES | `research model list/validate/export` |
| Fit ledger | Every actual fit | `~/.nt_research/models/ledger/<study>/<fit_id>/`, `studies/<id>/artifacts/fits/` | NO | YES | `research model list` |
| Model registry (selected) | Tier `registry`, `selection_status: selected` | model store manifests | NO | YES | `research model list` |
| Tuning ledger | Trials and selection | `studies/<id>/artifacts/tuning_trials.json` (`research_workflow/tuning.py`) | NO | YES | `study run --through fit` |
| Dataset definitions | DatasetSpec authority | `research/datasets/<id>.yaml` | only via builder | builder writes | `research data verify <id>` |
| Dataset V2 manifests | Immutable identity | `<catalog>/dataset_manifest.json`, `<catalog>/build_manifest.json` (catalog root from `~/.nt_research/config.yaml`) | NO | YES | `research data manifest/verify` |
| Calendar / roll / gap tables | Reference tables | `<catalog>/reference/{sessions,holidays,maintenance,rolls,gaps,out_of_calendar}.parquet` | NO | YES | `python scripts/build_dataset_v2.py` |
| Analysis operations | Declarative post-collection statistics | `research/analysis/diagnostic_ops.py` | via capability flow | NO | `research cap list analysis_ops` |
| Study YAML / specs | One study = one spec | `studies/<id>/study.yaml` (+ `compiled_plan.json`) | YES | plan yes | `research study compile` |
| Study workspaces | Branch + worktree + lease | `../<repo>-<id>/` (worktree), `~/.nt_research/leases/` | via CLI | YES | `research study new`, `research ws list` |
| Scripts | Deterministic operators | `scripts/research.py`, `scripts/run_governed_study.py`, `scripts/build_dataset_v2.py`, `scripts/prove_bar_equivalence.py`, `scripts/bench_host.py`, `scripts/lint_host.py`, `scripts/platform_v2_cards.py`, `scripts/gen_yaml_reference.py` | NO | NO | see each `--help` |
| Controller | Stage machine, receipts, run lock | `research_workflow/governed_controller_v2.py` (base `governed_controller.py`) | NO | NO | `research study run/status` |
| Lifecycle leaves | Stage bodies | `research_workflow/lifecycle_v2.py` | NO | NO | — |
| Audit packet generation | Compact auditor inputs | `research_workflow/audit_packets_v2.py` → `studies/<id>/_work/controller/audit_packet_{causal,contract}.json` | NO | YES | `study run --through seal` |
| Causal audit reports | One auditor, one report per pass | `studies/<id>/audit/pass_NN.md` + `studies/<id>/audit/status.json` | auditor writes | status yes | `research audit ingest --type causal` |
| Contract audit reports | Same | `studies/<id>/audit/contract_pass_NN.md` + `studies/<id>/audit/contract_status.json` | auditor writes | status yes | `research audit ingest --type contract` |
| Parity scripts | Frame comparison vs references | `scripts/parity/compare_study_to_reference.py`, `compare_frames.py`, `run_shape.py`, `scripts/find_first_parity_divergence.py` | NO | NO | see §L |
| Benchmarks | Measurement only, never a gate | `bench/baseline_v0.json`, `bench/baseline_v1_host.json`, `scripts/bench_host.py` | NO | YES | `research bench` |
| Tests | Platform tests | `research_workflow/tests/test_{grammar_v2,host_core,golden_fixture,lifecycle_v2,dataset_v2,docs_v2}.py`, `scripts/tests/`, `features/tests/` | YES | NO | `python -m pytest <file> -q` |
| Artifacts / checkpoints | Session evidence | `artifacts/platform_v2_do_soon/` (cards, checkpoints, proofs) | NO | YES | `python scripts/platform_v2_cards.py` |
| Templates | Prompts and skeletons | `research_workflow/templates/`, `docs/templates/`, `docs/examples/*.yaml` | YES | NO | — |
| Documentation | Authority and manuals | `WORKFLOW.md`, `docs/QUICKSTART.md`, `docs/RESEARCH_YAML_REFERENCE.md`, `docs/RESEARCH_DISCUSSION_TO_YAML.md`, `docs/AI_AGENTS.md`, `docs/RESEARCH_WORKFLOW.md`, `docs/GOVERNED_STUDY_CONTROLLER.md`, `docs/DOCUMENT_MAP.md` | YES | reference yes | `python scripts/gen_yaml_reference.py --check` |

A DatasetSpec (`research/datasets/<id>.yaml`) declares `reference_tables` (which of
`sessions`/`holidays`/`maintenance`/`rolls`/`gaps`/`out_of_calendar` the dataset carries) and
`reference_digest` (their combined content hash); verification is fail-closed -- a hash mismatch at
load refuses the study rather than reading a drifted table. A `sessions` reference table selects the
calendar session kind used for outcome/population censoring; ETH is `(open, 08:30 CT]` pre-open plus
`(15:15 CT or halt end, day close]` post-close, and legacy ETH censoring without a declared `sessions`
table is refused (`SEMANTIC_DECISION_REQUIRED`). For NQ/ES the session calendar is the CME Globex
equity-index product schedule (12:15 CT holiday-eve closes), reconciled against the tape at build time;
the trading-floor calendar is refused. Bind new studies to `NQ_1S_V2_GLOBEX` / `ES_1S_V2_GLOBEX`
(`NQ_1S_V2` / `ES_1S_V2` carry floor-calendar sessions and exist only for the closed proof studies) --
see `docs/RESEARCH_WORKFLOW.md` §21.7.

Research Supervisor (§O): `research_workflow/supervisor/` (state, derive, packets, providers, resources, core, cli),
`scripts/research_supervisor.py` (thin entrypoint), `scripts/tests/test_supervisor_blackbox.py` (proof).

## D. A normal new study

> Manual / debug path. The default way to run a study is the Research Supervisor (§O); use this section
> when you drive the controller by hand or debug one stage.

```bash
# 1. question -> workspace (branch study/<id>, worktree ../<repo>-<id>, lease, v2 skeleton)
python scripts/research.py study new my_flip_study --from-question question.md
cd "../Nautilus Trader-my_flip_study"

# 2. find primitives (never guess ids)
python scripts/research.py cap search regime
python scripts/research.py cap describe tracker.regime.dual_ema
python scripts/research.py cap list features | head

# 3. edit studies/my_flip_study/study.yaml (start from docs/examples/*.yaml)

# 4. compile: CompiledPlan or typed CapabilityGap
python scripts/research.py study compile --study studies/my_flip_study

# 5. run the controller stage by stage (each call is idempotent and resumable)
python scripts/run_governed_study.py --study studies/my_flip_study --through seal --execute-authorized
#    -> NEEDS_CAUSAL_AUDIT with _work/controller/audit_packet_causal.json  (auditor writes audit/pass_01.md)
python scripts/research.py audit ingest --study studies/my_flip_study --type causal --report studies/my_flip_study/audit/pass_01.md
python scripts/run_governed_study.py --study studies/my_flip_study --through seal --execute-authorized
#    -> NEEDS_CONTRACT_AUDIT with audit_packet_contract.json                (auditor writes audit/contract_pass_01.md)
python scripts/research.py audit ingest --study studies/my_flip_study --type contract --report studies/my_flip_study/audit/contract_pass_01.md
python scripts/run_governed_study.py --study studies/my_flip_study --through seal --execute-authorized   # READY_TO_SMOKE

# 6. long stages detached (smoke -> collection -> reconcile -> merge -> fit -> freeze -> oos -> analyze)
nohup python -u scripts/run_governed_study.py --study studies/my_flip_study --through analyze --execute-authorized --max-runtime 14400 > studies/my_flip_study/_work/run_analyze.log 2>&1 & disown

# 7. status at any time (non-mutating)
python scripts/research.py study status --study studies/my_flip_study

# 8. close with an explicit decision
python scripts/run_governed_study.py --study studies/my_flip_study --through close --execute-authorized \
  --closure-outcome "..." --closure-decision "..."
```

`research study run ...` forwards to `scripts/run_governed_study.py` (same flags). Useful flags:
`--smoke-date`, `--years 2021`, `--studies-root <dir>` (frozen external scores), `--max-runtime`,
`--stale-progress-timeout`, `--inspect`, `--json`.

**When compile succeeds** you get `compiled_plan.json` and a card with `plan_sha256`, `closure_sha256`,
feature count and streams. Commit `study.yaml` + `compiled_plan.json` on the study branch.

**When compile returns a CapabilityGap** the card lists `gaps: [{kind, where, message, closest}]`:

| kind | what it means | do |
|---|---|---|
| MISSING_CAPABILITY | no such primitive; `closest` names the nearest registered ids | `cap search`; compose from existing primitives; else §E |
| INVALID_PARAMETERIZATION | wrong parameter, label, reference or id format | fix the YAML (`cap describe` shows parameters) |
| AMBIGUOUS_TEMPORAL_SEMANTICS | a timing choice was left open (e.g. `atr_availability`) | declare it |
| UNAVAILABLE_STREAM | dataset/timeframe not resolvable | `research data verify <id>`; use a committed DatasetSpec |
| UNSUPPORTED_COMPOSITION | e.g. an event test inside `population.qualify` | restructure (events belong in triggers/outcome) |
| SEMANTIC_DECISION_REQUIRED | a scientific decision (direction, primary arm, year double-use, tuning folds) | decide and declare |

Never patch around a gap with study Python. A gap that needs shared platform work ends the study
session: the CLI writes `CAPABILITY_GAP_HANDOFF.json` and a fresh capability session takes it (§N.1).
End every session with `python scripts/research.py study handoff --study studies/<id> --phase <A|B|C|D>` (§N.2).

## E. Adding a new feature

First question: **can it be composed from existing features and trackers?** Most "new features" are
an existing identity with different parameters (`timeframe`, `window`, `context`, `over:` expansion) or a
tracker field exposed through `features.metadata`. If yes, use YAML composition and stop.

If no: `python scripts/research.py cap search <words>` and `cap list features`. The registry has 143
canonical feature identities; check aliases and parameter schemas before proposing anything.

If truly absent, the capability flow (anti-bloat gates included):

```bash
# 1. proposal (kind.name, semantics, availability_rule, parameters, serves_studies, closest_existing, composition_attempted,
#    reset_policy, null_policy, gap_policy, inputs, fields, events, update_cadence)
python scripts/research.py cap propose research_workflow/capabilities/proposals/tracker.volume.imbalance_60s.yaml
# 2. scaffold: features/trackers/<slug>.py + features/tests/test_<slug>.py + a `candidate` registry seed
python scripts/research.py cap scaffold tracker.volume.imbalance_60s
# 3. implement the binding; keep its declarations truthful (the compiler and registry read them)
# 4. synthetic causal test (features/tests/test_<slug>.py) + parity/oracle evidence (a JSON artifact)
# 5. promote: flips the seed to `verified` only with the parity artifact and green tests
python scripts/research.py cap promote tracker.volume.imbalance_60s --parity artifacts/parity/<slug>.json
# 6. regenerate and check the registry, then consume it from study.yaml
python scripts/research.py cap generate --check
```

What a primitive must declare (actual contracts):

* **Tracker binding** (`features/trackers/host_bindings.py`, subclass `BaseBinding`): `CAPABILITY`
  (`tracker.<group>.<name>`), `PARAMS` (name → default or `REQUIRED`), `INPUTS` (`bars: stream`,
  `regime: tracker`, ...), `FIELDS` (state readable in predicates), `EPOCH_FIELDS` (computed at the
  epoch, e.g. `age_s`), `EVENTS` (edge events: `changed`, `flipped`, `new_leg`, ...), `SUBSCRIBES`
  (events of input trackers), `WARMUP_BARS`, `CADENCE`. Methods: `on_bar`, `on_event`, `epoch_value`.
* **Feature definition** (`features/registry.py` `FeatureDefinition`): `name`, `aliases`, `version`,
  `status`, `family`, `stateful`, `source_timeframe`, `update_anchor`, `snapshot_anchor`, `warmup`,
  `normalizer`, `direction_normalized`, `dtype`, `null_policy`, `implementation`, `tests`,
  `parity_tolerance`, `window`, `window_unit`, `reset_policy`, `parameter_schema`,
  `supported_bar_states`, `supported_timeframes`, `supported_update_every`,
  `supported_parameter_values`, `required_parameters`, `supported_parameter_combinations`,
  `temporal_identity_exception`, `coverage_family`. Availability is `update_anchor` +
  `snapshot_anchor` (what input it may see and when); `warmup` is bars before the first valid value;
  `null_policy` and `reset_policy` are explicit; gaps are handled by the host (`outcome.max_gap` for
  labels) and by the tracker's own declaration in a proposal (`gap_policy`).

Examples:

* Simple scalar: `{feature: ema_slope, ema_role: short, lookback: 20}`.
* Parameterized: `{feature: rolling_giveback_atr, window: 300s, update_every: 1s}`.
* Timeframe-expanded family: `{feature: regime_efficiency, over: {timeframe: [1m, 5m]}, context: prior}` → `prior_1m_regime_efficiency`, `prior_5m_regime_efficiency`.
* Stateful tracker-derived: declare the tracker in `context` and expose a field via `features.metadata: {running_mfe_atr: excursion.mfe_atr}` or a bundle feature that binds it (`pullback_max_depth_atr` with `scope: current_deep_pullback_episode`).

## F. Adding a novel study metric

| It is a … | if | where it belongs |
|---|---|---|
| population / trigger semantic | it changes who is a candidate or when | `population.qualify`, `triggers` |
| feature | observed at the decision epoch and used by the model | `features.instances` / `metadata` (§E) |
| outcome / label | resolved from the future path | `outcome` (§J) |
| diagnostic / modeling metric | computed after prediction for evaluation | `research/analysis/metrics.py`; consumed by the fit/analyze stages |
| economic metric | computed from trades | `outcome.kind: trade` (typed only today) / `research_workflow/forward_outcomes/` |
| analysis metric | report aggregation only | a declared `analysis:` step composing registered `analysis_ops` (§F.1); never a runtime primitive, never a study-local script |

Rules that keep future information out of features: a feature may only read the tracker/bar state
delivered at or before the epoch; anything that needs the path after T is an outcome; anything computed
from outcome columns is analysis. `research_workflow/forward_outcomes/guard.py` rejects outcome-like
column names in the feature surface at preflight and fit. Example: "time since the pullback started" is
a feature (`pullback_elapsed_seconds`); "did price recover to the pre-pullback extreme within 300 s" is an
outcome (barrier/event); "recovery rate by regime age decile" is analysis.

### F.1 Declarative analysis (`analysis:`)

Anything past `roc_auc` / `pr_auc` / `brier` and disposition counts is declared, not scripted. A
study's `analysis:` section composes registered `analysis_ops` over its OWN collected frame:

```yaml
analysis:
  source: train                     # or oos (opens the protected period through assert_oos_open)
  steps:
    - {id: anchors,   op: analysis.anchor.first_threshold_crossing, params: {...}}
    - {id: incidence, op: analysis.incidence.cumulative, rows: anchors, params: {...}}
    - {id: controls,  op: analysis.control.cell_matched, inputs: {anchors: anchors}, params: {...}}
  artifacts:
    - {name: cumulative_incidence.json, source: incidence, kind: json}
    - {name: anchors.parquet,           source: anchors,   kind: frame}
```

Six operations today (`research cap list analysis_ops`): `anchor.first_threshold_crossing`,
`incidence.cumulative`, `decomposition.buckets`, `control.cell_matched`, `path.anchored_offsets`,
`classify.precedence`. They are study-agnostic -- the science is in the declared parameters -- and
the compiler proves, before execution, that every op is registered, that the pipeline is a DAG in
declaration order, and that every declared artifact names a declared step. Steps run after
collection and may read outcome columns; they are never a feature surface.

If a required statistic cannot be expressed, that is an `ANALYSIS_HARNESS_GAP`: name the missing
operation and add it through the capability flow (§E). Never write a study-local authoritative
pandas script.

## G. Adding a new ML model family

Families are `research/analysis/modeling.py` `SUPPORTED_ESTIMATORS` built by `_build_estimator(family,
seed, params)`: `lightgbm` (LGBMClassifier), `gradient_boosting` and `logistic_regression` (sklearn).
XGBoost and CatBoost are not supported today; adding one is a platform change: extend
`_build_estimator`, add `FAMILY_AUTHORITY` in `research_workflow/model_store.py` (native representation,
joblib fallback, export equivalence), a registry seed `model.<family>` in
`research_workflow/capabilities_index.yaml`, and tests.

Contract of every fit (v2 `fit` stage): deterministic seed (`params.random_state`), fixed feature order
(`ModelLineage.ordered_inputs`), `preprocessing_contract_sha256` (identity today), `target_contract_sha256`,
population identity, closure identities, hyperparameters. `store_model` writes canonical bytes plus a
golden validation frame (`research model validate <id>`), optional exports with equivalence checks
(`research model export <id> --format ...`), and a `model_id` = sha256 of the lineage.

Three separate states: **training succeeded** (bytes in the fit ledger) → **model selected**
(`selection_status: selected`, tier `registry`, hash bound into `train_experiment_freeze.json`) →
**scientifically validated** (`scientific_status`, decided at closure / OOS analysis, never by the fit).
OOS is gated by `experiment.assert_oos_open` after the freeze.

## H. Hyperparameter tuning (governed, TRAIN-only)

Declare it in the study (no scripts, no notebooks):

```yaml
model:
  family: lightgbm
  params: {n_jobs: 1, deterministic: true, verbosity: -1, random_state: 42}
  search_space:
    n_estimators: [100, 200, 400]
    max_depth: {low: 2, high: 6, int: true}
    learning_rate: {low: 0.01, high: 0.2, log: true}
  validation:
    protocol: model_selection.random      # or model_selection.optuna (needs the optuna package)
    tuning_years: [2021, 2022]            # walk-forward: fit 2021 -> validate 2022
    final_train_validation_years: []
    max_trials: 24
    random_seed: 42
    primary_metric: roc_auc
```

Flow (implemented in `research_workflow/tuning.py`, called by the `fit` stage): TRAIN chronology →
expanding walk-forward folds over `tuning_years` (fit on every earlier tuning year, validate on the next)
→ objective = mean primary metric over folds → trial ledger `artifacts/tuning_trials.json` (study id,
target/population/feature/preprocessing identities, feature order, folds, sampler, seed, search space,
objective, every trial's params and fold scores, selected trial, environment versions) → selected
configuration refit on all tuning years → `freeze` → OOS exactly once when the gate permits.

Prohibited by construction: random row cross-validation, tuning on dev/prohibited years (compiler
SEMANTIC_DECISION_REQUIRED), selecting with future years, silent use of reserved years. Bounded trials,
deterministic sampler seed, pruning (Optuna median pruner across folds), resume from
`artifacts/tuning_optuna.db`, sequential trials (parallelism is not enabled: determinism first).
Optuna is optional: `model_selection.optuna` raises `OPTUNA_NOT_INSTALLED` if the package is absent;
`model_selection.random` needs nothing. Regression targets are not supported by the v2 fit stage today
(binary labels only).

## I. Tuning decision rules (recommendations, not platform semantics)

Do not tune before proving the population, the target, the causal features and a basic signal with a
baseline model. Sequence: baseline model → chronology validation (walk-forward folds) → feature
diagnostics → limited tuning (tens of trials) → stability checks across years → freeze → OOS.
Hundreds of trials against a weak target select noise: with fold AUCs near 0.51 the best trial of
1,000 is the luckiest, not the best. Bounded defaults: 12–24 trials, 2–3 walk-forward folds, one primary
metric, stop when the selected configuration's fold spread exceeds its gain over the baseline.

## J. Adding a new outcome / target

`outcome.kind: label` compiles to a `LabelOutcomeContract` executed by
`research_workflow/host/outcomes.py` (`LabelOutcomeKernel`) and cross-checked by the independent oracle
`research_workflow/target_replay_oracle.py`. `kind: trade` compiles to a typed
`TradeExecutionContract` (fill model) with no sink in this phase.

Declare, explicitly:

* barriers (`favorable_atr`, `adverse_atr`, ATR reference and `atr_availability`), arms with prefixes and a `primary`;
* horizons (measured from the entry instant) and `horizon_end_rule` (`strict` | `first_bar_at_or_after`);
* censoring: `session_end` (censor|ignore), `session` (censor session), `max_gap`, expiry policy (`censor` → TIMEOUT, `negative` → label 0);
* same-bar collision: `same_bar_rule` (`ambiguous_censor` | `adverse_first`);
* precedence and `composition` (AND/OR with monotone censoring) for multi-item outcomes;
* `entry_reference` (only `next_bar_open` / `next_printed_bar_open` are executable for labels);
* `relation` (continuation | fade) and `direction`.

Resolution precedence at every bar (in-horizon, or the first post-horizon bar under
`horizon_end_rule: first_bar_at_or_after`) is fixed: `SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY`
-- a bar past the censoring session close is CENSORED `SESSION_END` before `max_gap`/touch are ever
evaluated, so `expiry: negative` can never manufacture a directional label out of a session-boundary
data gap. This is compiled into every outcome contract as `outcome.semantics.resolution_precedence` and
enforced identically by the kernel and the independent oracle (see `docs/RESEARCH_YAML_REFERENCE.md`).

Shape C lesson: the sealed reference resolved 25 of 453,768 rows one second past the horizon on sparse
seconds and keyed its model cells by the prevailing regime direction. Both were invisible in a study
driver and became explicit YAML (`horizon_end_rule`, `model.models[].subset`) with tests and audits.
Any semantic decision that changes labels must be a declared field, never code in a study.

## K. Adding a new trigger / stateful study

The trigger engine (`research_workflow/host/triggers.py`) runs one graph per candidate stream:
OBSERVE → named states → entry. Patterns (see `docs/examples/watch_trigger.yaml`):

* checkpoint: `triggers: every_candidate` with a grid cadence;
* watch → trigger: `WATCH.enter_when` on tracker state, `entry.when` on an edge test (`x.turned(...)`);
* watch → expiry: `expire_when: "age(WATCH) > 600s"`;
* re-arm: `reset_when: "regime_1m.changed or pullback.new_leg"` (graph-level, consumes the epoch);
* cooldown / re-entry: `entry.cooldown`, `entry.max_per_watch`;
* add / exit: `triggers.add` and trade exits are typed but not executed by the label kernel today (MISSING_CAPABILITY).

A new tracker capability is warranted only when the state cannot be expressed by existing tracker
fields plus predicates (e.g. a genuinely new stateful quantity with its own reset and warmup semantics).
Composition first; then §E.

## L. Debugging / parity

| Symptom | First artifact / command |
|---|---|
| candidate-count mismatch | `python scripts/parity/compare_study_to_reference.py --study <dir> --shape a\|b\|c --partition train --year 2021` → `only_in_reference_examples`; then `_work/controller/partitions/train/<year>/manifest.json` |
| feature-value mismatch | the report's `first_divergence` (timestamp, key, column, reference vs runtime); `python scripts/find_first_parity_divergence.py` |
| timestamp mismatch | `compiled_plan.json` → `streams[].visibility` and `availability`; `session_close_ts` in observations |
| outcome mismatch | `observations` per-column report; check `outcome.horizon_end_rule`, `same_bar_rule`, `session`, `max_gap` in the plan |
| model-score mismatch | `artifacts/experiment_models.json` (`score_digest`, `inputs`), `research model validate <id>` |
| DST / session mismatch | `<catalog>/reference/sessions.parquet`; `session_close_ts` deltas of ±3600 s are the reference's known DST defect |
| dataset digest mismatch | `python scripts/research.py data verify <id> --recompute` |
| closure changed | `audit/readiness.json` R9 (`current=` vs `frozen=`); re-run `--through tests`, then delta audits |
| run already active | `_work/controller/run.lock` (pid); `STUDY_RUN_ALREADY_LIVE` card |
| CapabilityGap | the compile card's `gaps[]` (`kind`, `where`, `closest`) |
| audit blocked | `audit/status.json` / `audit/contract_status.json`: verdict and `audited_execution_composite_sha256` must equal the frozen manifest composite |

Every failure is a card on stdout; stage logs are in `studies/<id>/_work/controller/logs/<stage>.log`.

### L.1 Reference parity semantics (fresh V2 population vs. a historical parent)

When a study's scientific experiment is a comparison of arms on ONE fresh Platform V2 population and a
historical study is named as the reference, the parent is a **reference-integrity diagnostic**, not the
population authority:

- require an **exact match over the common eligible calendar interval** where the two contracts are
  semantically identical;
- enumerate separately the **valid Globex-only candidates** that exist solely because the corrected
  product calendar (`NQ_1S_V2_GLOBEX`: 12:15 CT holiday-eve closes, mourning days, Good Fridays without a
  session) contains rows a floor-calendar parent could never emit -- descriptive, never blocking;
- BLOCK only for unexplained candidate differences inside the common interval, key/identity
  inconsistencies, or population-contract violations;
- never weaken the fresh V2 population contract to reproduce the parent.

`autonomy_decisions.calendar_reference_parity: common_interval_exact` declares this policy; a study whose
declared question makes the parent the population authority must say so explicitly instead.

## M. Concurrent research projects

**EVERY NEW RESEARCH PROJECT GETS ITS OWN BRANCH + WORKTREE.**
**ONE WRITING AGENT = ONE WORKTREE.**
**NEVER START A NEW RESEARCH STUDY BY EDITING MAIN DIRECTLY.**

The mechanism is `research study new`; do not create study branches or worktrees by hand
(the CLI also writes the skeleton, the writer lease, the ownership metadata and the branch name).

### M.1 Normal start sequence

```bash
# 1. start from a clean checkout of main (the canonical repo checkout, not a study worktree)
git switch main
git status --short                      # must be empty: study new refuses a dirty source tree
# 2. confirm main is at the intended Platform V2 authority
git log --oneline -1
git describe --tags --abbrev=0          # e.g. baseline/2026-09-platform-v2-proven
# 3. create the study
python scripts/research.py study new regime_breakout_context --from-question question.md
# 4. the card names what was created:
#      branch:    study/regime_breakout_context
#      worktree:  <worktree_root>/<repo-name>-regime_breakout_context   (default: sibling of the repo, e.g. ../Nautilus Trader-regime_breakout_context)
#      study dir: studies/regime_breakout_context/   (research_decision.yaml, SPEC.md, study.yaml, runs/, _work/)
#      lease:     ~/.nt_research/leases/regime_breakout_context.json   {study_id, branch, worktree, pid, owner, created_at_utc}
# 5. work ONLY in the generated worktree
cd "../Nautilus Trader-regime_breakout_context"
# 6. every study write happens there (study.yaml, compiled_plan.json, audit/, artifacts/, runs/, _work/)
# 7. other studies live in their own branches and worktrees (repeat 1-6 per study)
# 8. inspect who owns what
python scripts/research.py ws list
# 9. resuming an EXISTING study in a later session: claim it before writing (idempotent for the same
#    agent/session; a live lease held by another agent is refused -- same OS user or not)
python scripts/research.py ws whoami                       # the identity this shell writes as (user@host, agent, session)
python scripts/research.py ws claim regime_breakout_context
```

Writer identity is `user@host` + `owner_agent` + `owner_session_id`. Every coding agent on this
machine (Claude, Codex, Antigravity) runs as the same OS user, so the agent and per-session id are
what tell writers apart. `study new` records the identity of the initiating agent/session on the
lease; the launcher supplies it through `NT_RESEARCH_AGENT` / `NT_RESEARCH_AGENT_SESSION` (or the
harness's own variables -- see `docs/AI_AGENTS.md` *Writer identity*).

`study new` branches from the **current checkout's HEAD**. That is why step 1 is `git switch main`
on the canonical checkout: a study created from a stale or experimental worktree is bound to that
platform state. If you intentionally branch from a platform branch (`chore/*`), say so in
`research_decision.yaml`, record the source commit (`base_commit` in the `study new` card), and expect
the study's closure to be bound to that platform state.

### M.2 What is shared and what is isolated

| Shared, machine-local, read-only or governed | Isolated per study (writes) |
|---|---|
| configured catalog roots (`~/.nt_research/config.yaml`) and the Dataset V2 catalogs (immutable, digest-verified) | branch `study/<id>` |
| the durable model store (`~/.nt_research/models`; content-addressed `model_id`s, idempotent writes) | the sibling worktree |
| the capability registry and platform source at the study's source commit | `studies/<id>/` (spec, plan, `audit/`, `artifacts/`, `runs/`, `_work/`) |
| the leases directory (`~/.nt_research/leases`, one file per study) | controller receipts, audit packets, run lock (`_work/controller/`) |
| | the study closure (`artifacts/study_closure.json`) |

Controller isolation: one live controller per study (`_work/controller/run.lock`; a second run returns
`STUDY_RUN_ALREADY_LIVE`). Writer isolation: one writing agent per worktree. Two studies never write
into the same worktree or the same `studies/<id>` tree; read-only auditors may read any worktree.

### M.3 Platform change vs research change

| | Research change | Platform change |
|---|---|---|
| branch | `study/<id>` | `chore/<topic>` |
| worktree | the study's sibling worktree | a separate `chore` worktree (`git worktree add "../<repo>-<topic>" -b chore/<topic> main`) |
| examples | `study.yaml`, the research question, artifacts, model configuration, analysis declarations, closure | a reusable feature or tracker capability, compiler, host, outcome kernel, controller, dataset builder, docs of the platform |

A study agent must not modify shared Platform V2 infrastructure inside its study branch as a
study-local workaround. When a genuine `CapabilityGap` needs platform work the study session STOPS and
hands off (§N.1 STOP-AT-CAPABILITY-GAP: `CAPABILITY_GAP_HANDOFF.json`, a fresh capability session, a fresh
study session). The sanctioned platform sequence is:

1. `research cap propose <yaml>` (the proposal records the gap and the closest existing primitives);
2. create an isolated `chore/<topic>` worktree from `main`;
3. `research cap scaffold <id>`, implement, synthetic causal test, parity/oracle evidence, `research cap promote <id> --parity <json>`, `research cap generate --check`;
4. merge the platform change into `main` with `--no-ff`;
5. in the study worktree: `git merge --no-ff main` (or the chore branch, if the platform change is not yet on main and that is recorded);
6. re-run `python scripts/run_governed_study.py --study studies/<id> --through tests --execute-authorized`: the closure composite changed, so compile/prepare/readiness/preflight/tests re-execute and
7. the causal and contract audits are redone as delta passes on the new composite (`research audit ingest`), then reseal.

This is exactly how the three proof studies absorbed platform fixes.

### M.4 Lease semantics (as implemented in `research_workflow/workspace.py`)

Three independent mechanisms keep concurrent studies safe, and all three must pass:

| Mechanism | Prevents | Where |
|---|---|---|
| **branch + worktree isolation** | cross-study file conflicts (two studies never write the same tree) | `study/<id>` + `<worktree_root>/<repo>-<id>` |
| **WRITER LEASE** | cross-agent ownership conflicts: who may edit this study worktree | `~/.nt_research/leases/<id>.json` |
| **CONTROLLER RUN LOCK** | duplicate study execution: is a run of this study already live | `studies/<id>/_work/controller/run.lock` (`STUDY_RUN_ALREADY_LIVE`) |

A lease is durable ownership of a workspace by one **writer identity** for the duration of actual
work, not just for the lifetime of the short-lived `study new` CLI process that created it. Lease
schema v3:

| field | meaning |
|---|---|
| `study_id`, `branch`, `worktree` | the study and its sibling worktree |
| `owner` (`owner_user@owner_host`), `owner_user`, `owner_host` | the OS user -- **not sufficient for ownership** |
| `owner_agent` | `claude` / `codex` / `antigravity` / `gemini` / `human` |
| `owner_session_id` | unique per active coding-agent session (never a bare PID) |
| `created_at_utc`, `renewed_at_utc`, `holder {pid, kind: cli|controller, renewed_at_utc}`, `ttl_seconds` (default 72h) | renewal window; every governed `research study run` renews the lease while it runs |
| `released_at_utc`, `reclaimed_from`, `forced_release_by` | audit trail of release / reclaim |

| state | meaning | writing allowed? |
|---|---|---|
| `live` | worktree exists, not released, and (holder pid alive OR still inside the ttl window since the last renewal) | only the writer identity on the lease. A different agent or session -- **even under the same `user@host`** -- is refused: `study new` on the same worktree (`WRITER_LEASE_HELD`), `ws claim`, `research study run` and any lease renewal (`STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`). The same identity re-entering is idempotent |
| `stale` | worktree exists, holder pid dead, ttl window expired | unowned; `ws claim <id>` takes it (records `reclaimed_from`), or `ws list --reclaim` deletes the record |
| `dead` | the lease's worktree no longer exists | nothing to write; `ws list --reclaim` deletes the record |
| `released` | the owner ran `ws release <id>` | unowned; `ws claim <id>` takes it |

Claim rule, applied before any WRITE-capable operation on an existing study worktree (`ws claim`,
the controller's writer gate, lease renewal): verify the lease, the `study_id`, the `owner_agent`
and the `owner_session_id`. Live foreign writer -> fail closed. Stale/dead/released -> sanctioned
claim. Same identity -> idempotent. Claims are serialized per study by an O_EXCL claim lock, so two
simultaneous claims have exactly one winner (the loser sees `STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`
or `STUDY_CLAIM_IN_PROGRESS`). Legacy schema-1/2 leases carry no agent/session and are never "the
same writer": clear them with `ws release <id> --force` (same `user@host`, recorded on the lease) or
`ws list --reclaim` once stale/dead/released.

```bash
python scripts/research.py ws whoami                 # user@host, agent, session id, and how each was inferred
python scripts/research.py ws claim <study_id>       # take / re-enter ownership of an existing study worktree
python scripts/research.py ws release <study_id>     # release a lease you hold (--force: same user@host, e.g. a dead session)
python scripts/research.py ws list --reclaim         # per worktree: branch, HEAD, dirty, owner, agent, session, state; --reclaim clears stale/dead/released
```

Never delete or edit lease files by hand and never take over a `live` lease: if two agents must
work on the same study, the second one waits or takes a different study, or the owner releases.
Read-only agents (auditors, scouts, triagers) need no writer claim: they inspect source, artifacts,
audit packets and results in any worktree and mutate nothing but their own audit report.

### M.5 Example: three concurrent studies

```bash
cd "C:/Users/<you>/Projects/Nautilus Trader" && git switch main && git status --short
python scripts/research.py study new regime_breakout_context   --from-question q_breakout.md
python scripts/research.py study new pullback_quality_target   --from-question q_pullback.md
python scripts/research.py study new cross_market_context      --from-question q_cross.md
python scripts/research.py ws list          # three live leases, three worktrees, three branches
# agent A
cd "../Nautilus Trader-regime_breakout_context" && python scripts/research.py study compile --study studies/regime_breakout_context
# agent B
cd "../Nautilus Trader-pullback_quality_target" && python scripts/research.py study compile --study studies/pullback_quality_target
# agent C
cd "../Nautilus Trader-cross_market_context" && python scripts/research.py study compile --study studies/cross_market_context
```

They run concurrently because they have separate branches, worktrees, study directories and
controller locks, while sharing the immutable catalogs, the platform code at their source commits and
the durable model store (content-addressed; concurrent stores of different models never collide).

### M.6 Closure and merge back

```bash
python scripts/research.py study status --study studies/<id>         # state STUDY_CLOSED
git -C "../Nautilus Trader-<id>" status --short                       # clean
git -C "../Nautilus Trader-<id>" add studies/<id> && git -C "../Nautilus Trader-<id>" commit -m "study(<id>): STUDY_CLOSED ..."
git switch main && git merge --no-ff study/<id>                        # history preserved; never squash
python scripts/research.py ws list --reclaim                           # the finished study's lease is stale once its session ended
```

The merged `studies/<id>/` on `main` is the study's persisted authority (closure, audits, seal, parity).

## N. Study session budget, phases and handoffs

> These are the rules a human-driven or attended session follows. The Research Supervisor (§O) enforces
> them mechanically: one fresh worker process per phase, no long-job polling, handoffs written by the loop.

Two measured study sessions (2026-09-04) ran 4.5 h and 11 h, 735 and 773 assistant messages, and re-read
~390 M and ~356 M cached input tokens: each session accumulated ~500k tokens of context and re-read it on
every one of hundreds of small tool calls. The rules below make sessions short, resumable and cheap.
They are agent operating policy, not runtime enforcement, except where a CLI verb is named.

### N.1 STOP-AT-CAPABILITY-GAP

When `research study compile` returns a typed CapabilityGap that needs shared Platform V2 work
(MISSING_CAPABILITY, UNSUPPORTED_COMPOSITION, an UNAVAILABLE_STREAM that needs a dataset build, ...),
the **study owner stops implementation work**. The CLI writes
`studies/<id>/CAPABILITY_GAP_HANDOFF.json` + `.md` (`research_workflow/handoff.py`) with: study id,
source platform commit, research question, exact gap kind/where/message, requested semantics (the YAML
at each gap), compiler evidence, affected YAML fields, nearest existing capabilities, scientific
decisions already resolved, prohibited changes, suggested platform files, study branch/worktree and the
next action. The owner commits `study.yaml` + `research_decision.yaml` + the handoff and **ends the
session**. It must NOT modify `research_workflow/`, the grammar/compiler or `features/`, build the
capability itself, patch around the gap with study Python, or keep accumulating context.

A **new short capability session** (fresh context) then:

1. `python scripts/research.py ws chore claim <topic> --paths <modules> --surface "<one line>" --as <agent>` (§N.6)
2. creates `chore/<topic>` from `main` in its own worktree, implements ONLY that capability, targeted tests,
   `research cap generate --check`, audit/promotion when the capability flow requires it
3. merges to `main` with `--no-ff`, writes a `CAPABILITY_COMPLETE` note
   (`research study handoff --study studies/<id> --phase A --note CAPABILITY_COMPLETE:<topic>`), releases the chore claim, ends.

A **new study session** merges `main` into the study worktree, `ws claim`s the study, recompiles and resumes.

INVALID_PARAMETERIZATION, AMBIGUOUS_TEMPORAL_SEMANTICS and SEMANTIC_DECISION_REQUIRED are study-side:
fix or declare in the YAML / decision contract and recompile; no handoff needed.

### N.2 One lifecycle phase per owner session

| session | does | ends when | handoff |
|---|---|---|---|
| **A — design / compile** | intake, capability discovery (`cap search/describe`), `research_decision.yaml`, `study.yaml`, compile | `compiled_plan.json` written, or `CAPABILITY_GAP_HANDOFF` emitted | `research study handoff --study studies/<id> --phase A` |
| **B — prepare / seal** | readiness, preflight, tests, causal audit, contract audit, seal | `READY_TO_SMOKE` | `--phase B` |
| **C — execution** | smoke, authorized collection, reconcile, merge, pre-fit gates, fit/score, freeze, OOS only if authorized | deterministic execution artifacts exist | `--phase C` |
| **D — analysis / decision** | analysis, scientific interpretation, study report, closure | `STUDY_CLOSED` | `--phase D`, then merge (§M.6) |

A trivially short adjacent phase may be finished in the same session; these are the default handoff
boundaries, not prohibitions. Every phase ends by writing `studies/<id>/_work/handoff/SESSION_HANDOFF.json`
+ `.md` (branch, head, dirty count, controller status card, artifacts and audits present, decisions,
the exact next command). The next owner session reads that card first and does not re-discover the
repository.

### N.3 Committed test-failure baseline

`config/test_failure_baseline.json` records, per exact pytest node id, the failures that pre-exist on
`main` (platform commit, classification `pre_existing` / `environmental` / `expected_change`, reason,
scopes, environment requirements). Never re-derive it by running the suite on the branch and on clean
`main`. Instead:

```bash
python scripts/test_delta.py scripts/tests/test_workspace.py            # targeted, during implementation
python scripts/test_delta.py research_workflow/tests scripts/tests      # ONE broad relevant run before commit
python scripts/test_delta.py <scopes> --update-baseline --reason "..."  # explicit, reviewed change of the baseline
```

The card shows `NEW_FAILURE` prominently and classifies the rest as `KNOWN_BASELINE_FAILURE`,
`BASELINE_FAILURE_NOW_FIXED` (update the baseline when you commit the fix) or
`ENVIRONMENTAL_MISSING_ARTIFACT`. A failure outside every baselined scope is
`NEW_FAILURE_OUTSIDE_BASELINE_SCOPE`, never silently allowed. Agents act only on NEW failures.
`@pytest.mark.slow` tests (real data replay; `scripts/tests` carries several that run for tens of minutes)
are excluded by default so one broad run stays in minutes; `--include-slow` lifts the filter.

### N.4 Predeclared fork policy (`autonomy_decisions`)

`research_decision.yaml` carries an optional `autonomy_decisions:` block (the skeleton written by
`study new` declares the defaults). Agents follow it instead of asking again:

| key | values | meaning |
|---|---|---|
| `on_capability_gap` | `stop_and_handoff` | §N.1 |
| `platform_change_required` | `chore_branch_and_fresh_session` | never in the study branch or session |
| `deterministic_defect` | `auto_fix` | fix, add a targeted test, re-run the bounded check |
| `calendar_reference_parity` | `common_interval_exact` (+ `known_globex_extension_descriptive`) | §L.1 |
| `frozen_parent_model` | `rescore_if_authenticated`, `never_retrain` | a frozen parent is re-scored, never retrained |
| `protected_period` | `never_expand_authority` | OOS/prohibited years never widen |

A genuine semantic choice that no declared policy resolves is still a `SEMANTIC_DECISION_REQUIRED`
question -- scientific defaults are never taken silently.

### N.5 Long-run policy

The owner model never babysits deterministic jobs. Long stages are launched detached through the
canonical controller (§D step 6), the controller persists its status card, and the owner **ends the
session** when no reasoning remains. A later fresh session reads `research study status` and the
handoff card. No foreground waits of minutes, no repeated polling, no tailing raw logs.

### N.6 Chore-worktree ownership

Platform work registers its write surface before it starts:

```bash
python scripts/research.py ws chore claim <topic> --paths research_workflow/grammar/ features/trackers/host_bindings.py --surface "<one line>" --capabilities <ids> --as <agent>
python scripts/research.py ws chore list
python scripts/research.py ws chore release <topic>
```

The claim (`~/.nt_research/leases/chore/<topic>.json`) records chore branch, owner agent/session,
capability ids, expected write paths, semantic surface and status. A second writer whose paths overlap a
live claim (directory containment or glob match) is refused with
`PLATFORM_SURFACE_OWNED_BY_ANOTHER_AGENT` before it implements anything; disjoint surfaces proceed
concurrently. It is a claim registry, not a scheduler.

### N.7 STUDY SESSION BUDGET

- owner context target: **<= ~50k tokens preferred; hand off before ~100k**
- one bounded objective per session (one phase, one capability, one repair packet)
- no repeated repository discovery: read the handoff card and `research study status`, not the tree
- no repeated baseline test classification: `scripts/test_delta.py`
- no platform implementation inside a study session after a CapabilityGap (§N.1)
- no long-job polling (§N.5)
- targeted tests while implementing; one broad relevant run before commit

These are recommended limits for agents; the runtime enforces none of them.

## O. Supervised research (default)

The **Research Supervisor** (`research_workflow/supervisor/`, `python scripts/research.py supervise ...`) turns one
research question into a chain of short, disposable AI worker sessions plus detached deterministic controller jobs.
It is a thin, deterministic, file-state loop above the governed controller (§A): it never runs a lifecycle stage
itself, never replaces or wraps `governed_controller_v2`, and holds no scientific state of its own.

```bash
python scripts/research.py supervise start --question question.md --study-id my_study --provider claude --execute-authorized
python scripts/research.py supervise status my_study
python scripts/research.py supervise list
python scripts/research.py supervise providers
python scripts/research.py supervise resume my_study
python scripts/research.py supervise stop my_study
python scripts/research.py supervise tick my_study
python scripts/research.py supervise decide my_study --answer answer.json
python scripts/research.py supervise adopt --study studies/my_study --execute-authorized
```

`start` runs `study new` under the supervisor's own writer identity (`<provider>` + a fresh session id), persists
state under `~/.nt_research/supervisor/<id>/` (`state.json`, `events.jsonl`, `packets/`, `results/`, `logs/`, `pid`)
and DETACHES the loop; the terminal returns at once. `--execute-authorized` is the only way post-seal stages ever run
(forwarded to the controller, persisted per study); without it the supervisor stops at `READY_TO_SMOKE` with an
`AUTHORIZATION_AMBIGUITY` card. `--provider` defaults to the shell's writer identity; ONE provider per supervisor run.
`adopt` supervises an EXISTING study: its position is derived from artifacts, nothing is recreated or re-run, and a
live writer lease held by another session makes it wait (`WAIT_STUDY_LEASE`) rather than take over.

**State principle: derive, do not invent.** Every tick recomputes the study's position from artifacts -- closure,
`CAPABILITY_GAP_HANDOFF.json`, `compiled_plan.json`, the controller's `_work/controller/status.json` (honoured only
while its fingerprints still match `study.yaml` / `compiled_plan.json`), `run.lock`, `audit/*status.json` vs the frozen
composite, `artifacts/analysis_decision.json`, the writer lease and git. The state file persists only attempt
counters, active worker/job identity, task ids, timestamps and user-decision cards.

| derived state | action (exactly one per tick) |
|---|---|
| `NO_SPEC` | fresh `STUDY_DESIGN_COMPILE` worker (phase A) |
| `CAPABILITY_GAP` MISSING_CAPABILITY / UNSUPPORTED_COMPOSITION / UNAVAILABLE_STREAM | capability flow (below) |
| `CAPABILITY_GAP` INVALID_PARAMETERIZATION | fresh design worker |
| `CAPABILITY_GAP` AMBIGUOUS_TEMPORAL_SEMANTICS / SEMANTIC_DECISION_REQUIRED | design worker if `research_decision.yaml` names the decision, else a `SCIENTIFIC_SEMANTIC_DECISION_REQUIRED` card |
| `COMPILED` / `CONTROLLER_STEP` | detached `run_governed_study.py --through seal` (no AI alive) |
| `NEEDS_CAUSAL_AUDIT` / `NEEDS_CONTRACT_AUDIT` | fresh read-only auditor; its report is copied into `audit/pass_NN.md` / `contract_pass_NN.md` and ingested by the supervisor |
| `DETERMINISTIC_BLOCKER` / `AUDIT_BLOCKER` | bounded `DETERMINISTIC_REPAIR` worker (2 attempts per blocker code) |
| `READY_TO_EXECUTE` (sealed, authorized) | detached `--through analyze` job holding a heavy-job slot; no AI alive while it runs |
| `EXECUTION_BLOCKER` | read-only `EXECUTION_TRIAGE` worker |
| `READY_FOR_ANALYSIS` | fresh `ANALYSIS_DECISION` worker -> `artifacts/analysis_decision.json` -> detached `--through close` |
| `STUDY_CLOSED` | terminal: phase-D `SESSION_HANDOFF`; merge to `main` per §M.6 (automatic only with `autonomy_decisions.closed_study_merge: auto_if_clean`) |
| `RUNNING` / `WAIT_STUDY_LEASE` / `WAIT_CHORE` / `WAIT_MERGE_LOCK` / `WAIT_RESOURCE` | wait on a backoff; nothing is launched |

**Workers** are fresh processes with a small pointer packet (`packets/<task_id>.md`: role, task, files to read,
allowed write surface, stop conditions, result-card path, identity) -- never a conversation replay. Session types
map to the canonical roles in `docs/AI_AGENTS.md` (`implementer`, `lookahead-auditor`, `contract-checker`,
`analysis-decider`, `results-triager`, the primary-owner rules). Each write-capable worker gets its own
`NT_RESEARCH_AGENT_SESSION`; the supervisor hands it the study's writer lease for the duration of the task and takes it
back afterwards. Read-only auditors write nothing inside `studies/<id>/` (their report goes to the supervisor's
`results/` dir and is copied in on ingest) and any mutation of the study worktree fails the worker. A worker MUST write
`results/<task_id>.result.json` through `research study result --packet <packet> --status DONE|BLOCKED|FAILED ...`;
its stdout is never parsed. Every packet carries `task_id, packet_sha256, study_id, study_contract_sha256,
compiled_plan_sha256, source_commit, platform_commit, expected_branch, expected_worktree`; the card repeats them and any
mismatch is `STALE_WORKER_RESULT` (never ingested; counts as a failed attempt). A worker past its wall-clock cap is
killed (`WORKER_TIMEOUT`).

**Capability flow** (the only place shared platform code is written): the design worker's compile writes the
handoff and exits -> the supervisor runs `ws chore claim <topic>` (an overlapping live claim -> `WAIT_CHORE`, never a
competitor) -> creates `chore/<topic>` from `main` -> launches a `CAPABILITY_IMPLEMENTATION` worker whose write surface
is the claimed paths -> **merge gate**: result `DONE`, diff confined to the claimed surface, `test_delta` new
failures 0, `cap generate --check` clean, chore worktree clean; merged `--no-ff` only if the study declares
`autonomy_decisions.platform_merge: auto_if_green`, otherwise a `DESTRUCTIVE_ACTION_REQUIRES_APPROVAL` card
(answer file `{"approve": true}`) -> release the claim, `git merge --no-ff main` into the study worktree,
`CAPABILITY_COMPLETE` handoff, fresh design worker. A capability merged by hand while the supervisor was offline is
detected from git. Every read-then-mutate of `main` holds `~/.nt_research/locks/main_merge.lock`.

**Retry / escalation**: two attempts per repair, capability or worker task; a worker timeout gets one retry; the same
blocker code after an independent repair, or any second failure of the same task, raises
`SUPERVISOR_ESCALATION_REQUIRED` (answer `{"retry": true}` to reset the counters). User intervention exists ONLY for
the typed codes `SCIENTIFIC_SEMANTIC_DECISION_REQUIRED`, `AUTHORIZATION_AMBIGUITY`, `PROTECTED_OOS_AUTHORIZATION_REQUIRED`,
`DATA_SAFETY_RISK`, `CAUSAL_DEFINITION_AMBIGUOUS`, `RESEARCH_CONTRACT_CONFLICT`, `DESTRUCTIVE_ACTION_REQUIRES_APPROVAL`,
`SUPERVISOR_ESCALATION_REQUIRED`; a scientific answer is stored in the study (`_work/handoff/USER_DECISION_NN.json`),
never only in supervisor state. Deterministic bugs, test failures, stale freezes, audit regeneration, merges and
long-job completion are never asked.

**Multi-study and resources**: the loop ticks every study under `~/.nt_research/supervisor/`; a study waiting on a
decision stops, the others continue. `max_workers` and `max_heavy_jobs` (default 2 each) are machine-wide O_EXCL slot
files under `~/.nt_research/locks/slots/`; a dead holder's slot is reclaimable. A study worktree whose live lease
belongs to another writer is never touched (`WAIT_STUDY_LEASE`). Decisions raise a Windows toast plus the status card.

**Providers**: `supervise providers` probes each installed CLI (`--version`, `--help`) and records AVAILABLE /
HEADLESS_SUPPORTED / WRITE_SUPPORTED / READ_ONLY_SUPPORTED / CLI_VERSION / probe sha256; only flags the installed
binary prints are ever used, and a worker whose required capability is absent fails before launch with
`PROVIDER_CAPABILITY_UNAVAILABLE`. `claude` (print mode), `codex` (`codex exec`) and `gemini` run headless;
`antigravity` and `human` are ATTENDED: the supervisor writes `packets/<task_id>.INSTRUCTIONS.md`, prints it and waits
for the result card. A human-attended session of any provider can act as a worker by following the same packet.
The `scripted` provider exists for tests only (`research_workflow/tests/supervisor_support.py`;
`scripts/tests/test_supervisor_blackbox.py` is the black-box proof).

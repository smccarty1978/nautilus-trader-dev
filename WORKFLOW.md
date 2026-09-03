# WORKFLOW.md — how research is done here (Platform V2)

**Read this first.** It describes the current way to work. History lives in `docs/DOCUMENT_MAP.md`;
the authoritative system description is `docs/RESEARCH_WORKFLOW.md` (§21 for Platform V2).
Field-by-field YAML: `docs/RESEARCH_YAML_REFERENCE.md`. Ten-minute version: `docs/QUICKSTART.md`.
Agents: `docs/AI_AGENTS.md`. Turning a chat discussion into a spec: `docs/RESEARCH_DISCUSSION_TO_YAML.md`.
Running several studies at once: §M **Concurrent research projects**.

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

## D. A normal new study

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

Never patch around a gap with study Python.

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
| analysis metric | report aggregation only | `research/analysis/` reporting; never a runtime primitive |

Rules that keep future information out of features: a feature may only read the tracker/bar state
delivered at or before the epoch; anything that needs the path after T is an outcome; anything computed
from outcome columns is analysis. `research_workflow/forward_outcomes/guard.py` rejects outcome-like
column names in the feature surface at preflight and fit. Example: "time since the pullback started" is
a feature (`pullback_elapsed_seconds`); "did price recover to the pre-pullback extreme within 300 s" is an
outcome (barrier/event); "recovery rate by regime age decile" is analysis.

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
```

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
study-local workaround. When a genuine `CapabilityGap` needs platform work, the sanctioned sequence is:

1. `research cap propose <yaml>` (the proposal records the gap and the closest existing primitives);
2. create an isolated `chore/<topic>` worktree from `main`;
3. `research cap scaffold <id>`, implement, synthetic causal test, parity/oracle evidence, `research cap promote <id> --parity <json>`, `research cap generate --check`;
4. merge the platform change into `main` with `--no-ff`;
5. in the study worktree: `git merge --no-ff main` (or the chore branch, if the platform change is not yet on main and that is recorded);
6. re-run `python scripts/run_governed_study.py --study studies/<id> --through tests --execute-authorized`: the closure composite changed, so compile/prepare/readiness/preflight/tests re-execute and
7. the causal and contract audits are redone as delta passes on the new composite (`research audit ingest`), then reseal.

This is exactly how the three proof studies absorbed platform fixes.

### M.4 Lease semantics (as implemented in `research_workflow/workspace.py`)

A lease is durable ownership of a workspace for the duration of actual work, not just for the
lifetime of the short-lived `study new` CLI process that created it: the lease carries a `holder`
(pid, kind `cli`|`controller`, `renewed_at_utc`) and a `ttl_seconds` (default 72h). Every governed
`research study run` on a leased worktree renews the lease (kind `controller`) while it runs, so a
long controller run keeps the lease `live` long past the creating CLI process's exit.

| state | meaning | writing allowed? |
|---|---|---|
| `live` | the lease's worktree exists, not released, and (holder pid alive OR still inside the ttl window since the last renewal) | only that writer; `study new` refuses a second live lease on the same worktree (`WRITER_LEASE_HELD`); a `research study run` on the worktree by a different owner is refused (`WRITER_LEASE_HELD_BY_OTHER`) |
| `stale` | the worktree exists, the holder pid is dead, and the ttl window has expired | the worktree is unowned; `research ws list --reclaim` deletes the stale lease, after which one writer may take the worktree |
| `dead` | the lease's worktree no longer exists | nothing to write; `research ws list --reclaim` deletes the record |
| `released` | the owner ran `research ws release <study_id>` | the worktree is unowned; `research ws list --reclaim` deletes the record |

Ownership is the `owner` (user@host) in the lease file, written once by `study new`. Never delete or
edit lease files by hand and never take over a `live` lease: if two agents must work on the same
study, the second one waits or takes a different study, or the owner runs `research ws release
<study_id>` when done. `research ws list` shows, per worktree, the branch, HEAD, dirty state, owner
and lease state; `research ws list --reclaim` is the only sanctioned reclaim command and touches only
`stale`/`dead`/`released` leases, never `live`. The controller's `run.lock` independently prevents two
live runs of the same study.

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


# Research Workflow — Authoritative Manual

**This describes the system as implemented.** It is the single authoritative statement of
where code belongs, how features are identified, what the lifecycle is, and which scripts to
run. `CLAUDE.md`, `CODEX.md` and `AGENTS.md` are short agent manuals that link here.

If another document contradicts this one, this one wins. Classification of every doc:
`docs/DOCUMENT_MAP.md`. Current-state numbers deliberately kept out of this file:
`docs/WORKFLOW_REFERENCE_FACTS.md`.

## 0. Index

| Question | § |
|---|---|
| Where does shared research code go? | 1 |
| How do I declare a 5m completed regime-efficiency feature? | 2 |
| Can I copy an old collector? | 7 |
| Can a population be defined by an externally frozen identity list instead of a live filter? | 7 |
| What happens after READINESS fails? | 4, 12 |
| When can OOS open? | 3 |
| What does the lookahead auditor prove? | 6.1 |
| What does model integrity prove? | 6.2 |
| Where do forward outcomes live? | 9 |
| Can forward outcomes enter model X? | 10 |
| Which script should I run for a new study? | 3, 11 |
| What should I do before recursive deletion? | 13 |
| Is this a governed study or an ordinary backtest? | 8 |
| Can a target combine several conditions? | 20.1 |
| Can a study consume another study's frozen model score? | 20.2 |
| Can a study declare a machine-enforced pre-freeze gate? | 20.3 |
| Is hyperparameter search governed the same way as everything else? | 20.4 |

---

## 1. Repository architecture

```
features/                 CANONICAL FEATURE IDENTITY
  authority/                active.json pointer + candidate/ bundle (registry, aliases, promotion facts)
  registry.py               FeatureInstance, validate_feature_instance, resolvers
  candidate_authority.py    bundle load / freeze / atomic activation
  trackers/generic_*.py     parameterized providers
  CANONICAL_FEATURE_REFERENCE.yaml   generated canonical vocabulary
  archive/                  Feature System V1. Non-runtime, rollback only.

research_workflow/        REUSABLE GOVERNED RESEARCH LIFECYCLE
  study_factory  compiler        scaffold + compile a declarative study
  prepare  phase0               PREPARE + FREEZE, phase-zero authorization
  readiness  preflight          R1-R10 gate, deterministic preflight
  causal_audit  contract_audit  executable structured reviews
  seal  smoke                   pre-execution seal, bounded NT smoke
  generic_collector             THE collector strategy (NT event loop)
  execution_plan                compiled callback groups for one study
  output_manager                persistence, schema + surface enforcement
  experiment                    TRAIN/OOS authorization, freeze, OOS gate
  collection  partitioning      period + year-partitioned collection, merge, parity
  modeling  analysis            governed fit, TRAIN freeze, bound analysis
  forward_outcomes/             proposed entry -> future path (§9)
  hooks/                        tiny study hook Protocols
  lifecycle                     one small facade over all of the above

research/                 ANALYSIS + SCHEMA LAYER (consumed by research_workflow)
  analysis/                 loader, spec, slices, metrics, modeling, reporting, identity
  schemas/                  StudySpec, DatasetSpec
  engines/                  feature binding, target, lineage, population, timestamp
  study_types/              flip_prediction, bespoke, base

studies/<id>/             STUDY-SPECIFIC ONLY — contracts, audits, artifacts (§16)

strategies/               EXECUTABLE TRADING STRATEGIES ONLY
                          (STRATEGY_REGISTRY lives in backtests/nt_runtime/strategy_binding.py)

backtests/                NT RUNTIME
  nt_runtime/               engine_builder, data_plan, run_plan, strategy_binding,
                            compiled_study_loader, telemetry, modes/
  run_nt_study.py           collect entrypoint
  run_backtest.py           standalone backtest entrypoint (§8)
  run_*.py (other)          FROZEN references. Not templates.

scripts/                  OPERATIONAL / GOVERNANCE / DIAGNOSTIC CLIs (§11)

archive/  scratch/  runs/  features/archive/    Historical or generated. Never active.
```

### Repository layout policy

To prevent clutter and folder creep, the repository layout obeys strict containment rules:
*   **root**: Contains only operational entry points, environment setups, and active configuration files. No research logs, data, or point-in-time forensic CSVs belong at the root.
*   **studies/<id>**: Contains all files, logic, tests, and artifacts owned by a specific study, including local execution run outputs (placed under `studies/<id>/runs/`).
*   **scripts**: Houses reusable operational, governance, and diagnostic tooling.
*   **archive**: Retains historical, stale, or non-authoritative documents and forensic data (under `archive/docs/` and `archive/forensics/`).
*   **scratch**: Reserved for disposable developer work and local non-committed playground code.

### Core invariant

```
NEW STUDY != NEW INFRASTRUCTURE
```

A new study adds: `research_decision.yaml`, `SPEC.md`, `study.yaml`, compiled contracts,
study tests, and rarely a small declarative hook. If you are writing a collector, an engine
bootstrap, a catalog loader, an analysis loader, or a `run_*.py`, stop — it exists.

**Escalation rule.** You may modify `research_workflow/`, `research/`, `backtests/nt_runtime/`,
`utils/runner/`, `features/` or `scripts/` only if all three hold: (1) a concrete study cannot
be expressed by the existing capability; (2) the failure is *not* a missing feature instance,
a missing strategy registration, YAML/CLI misuse, a stale audit or seal, or caller misuse;
(3) you document the missing capability (`BESPOKE_JUSTIFICATION`, or the study `SPEC.md`).

---

## 2. Feature System V2 — canonical, timeframe-agnostic identity

**The runtime is canonical-only.**

A canonical feature definition names exactly five things: the **formula**, the **provider**,
its **causal semantics**, its **reset semantics**, its **null semantics**.

Everything else is a **parameter of a `FeatureInstance`**:

```
timeframe  window  lookback  period  context  bar_state  update_every
source_timeframe  reference_timeframe  input_timeframe  ema_role
```

> **"1m EMA" is NOT a separately named feature.** Timeframe belongs in the parameters.

Declare instances in `study.yaml`:

```yaml
features:
  source: canonical_verified_definition_universe
  instances:
    - feature: regime_efficiency                     # a 5m completed regime efficiency
      parameters: {timeframe: 5m, context: prior, bar_state: completed}
    - feature: rolling_giveback_atr
      parameters: {window: 300s, update_every: 1s}
    - feature: arrival_velocity
      parameters: {input_timeframe: 1s, lookback: 20, bar_state: completed}
```

`prior_5m_regime_efficiency` and `rolling_300s_giveback_atr` are **output column aliases**,
generated by `generate_physical_alias()`. Never write one into a study contract. Verification
status lives on the canonical definition, never on the alias.

### Bar-state semantics

Three different things that must never collapse into one another:

| Meaning | Parameters |
|---|---|
| Completed calendar bar | `timeframe: 1m, bar_state: completed` |
| Forming calendar bar | `timeframe: 1m, bar_state: forming, update_every: 5s` |
| True rolling window | `window: 300s, update_every: 1s` |

`validate_feature_instance()` raises rather than guessing. **Ambiguous timeframe semantics
fail closed — never resolve one of these by adding a default.**

| Code | Meaning |
|---|---|
| `AMBIGUOUS_TEMPORAL_SEMANTICS` | `timeframe` + `update_every` without `bar_state`; or `timeframe` + `window` together |
| `FORMING_BAR_UPDATE_REQUIRED` / `_INVALID` | forming without `update_every`; `update_every` exceeds `timeframe` |
| `COMPLETED_BAR_UPDATE_FREQUENCY_INVALID` | `update_every` on a completed calendar bar |
| `ROLLING_WINDOW_UPDATE_REQUIRED` | `window` without `update_every` |
| `FORMING_BAR_UNSUPPORTED` | provider supports completed bars only |
| `UNSUPPORTED_TIMEFRAME_PARAMETER` / `UNSUPPORTED_UPDATE_CADENCE` | outside declared support |
| `UNKNOWN_CANONICAL_FEATURE` / `UNKNOWN_FEATURE_PARAMETER` | not in the active bundle / not in the parameter schema |
| `MISSING_REQUIRED_FEATURE_PARAMETER` | required parameter omitted |
| `UNVERIFIED_CANONICAL_FEATURE` | definition exists but is not `verified` |
| `LEGACY_FEATURE_ALIAS_NOT_ALLOWED` | you used a physical alias — declare a canonical instance |

### Authority and legacy policy

The active bundle is selected by an atomic pointer, `features/authority/active.json`.
`features.candidate_authority.load_authority()` is the only loader — a candidate is never
selected by environment variable, ambient state, or fallback.

| | |
|---|---|
| Active runtime | canonical only |
| `source: canonical_verified_definition_universe` | the active path |
| `source: verified_registry_numeric_universe` | legacy; raises unless `legacy_mode=True` |
| Active fallback to legacy aliases | **prohibited** — there is none, and none may be added |
| New studies using physical alias names | **prohibited** |
| Historical replay | explicit, isolated `legacy_mode=True` only |
| `features/archive/legacy_registry_*/` | V1 rollback archive, non-runtime |

Legacy alias behaviour reproduces historical datasets. It is never a development option.

### Adding a feature

1. Resolve the request first: `python scripts/feature_ctl.py`, or read
   `features/CANONICAL_FEATURE_REFERENCE.yaml`. If it resolves, declare an instance — done.
2. **Do not add a provider to support another timeframe, window, or period.** That is a
   parameter. Extend or add a parameterized provider in `features/trackers/generic_*.py`
   only when the formula or state-transition semantics genuinely differ.
3. Declare the canonical definition with `parameter_schema`, `supported_bar_states`,
   `supported_timeframes`, null and reset policies — those fields are what let validation
   fail closed.
4. Add tests in `features/tests/` that **name the feature**.
5. Promote via `scripts/check_feature_promotion.py`: the implementation must resolve, a test
   must name the feature, and an explicit promotion record must name the causal-audit
   artifact and audited execution composite. Contract: `features/FEATURE_REGISTRY_CONTRACT.md`.
6. Declare the instance, recompile, re-run preflight.

Never bypass an unresolved feature with a hand-built script or inline pandas.

---

## 3. The lifecycle

One sequence. `research_workflow/lifecycle.py` is the facade over it.

| # | Stage | Entry point | Artifact | Fails when |
|---|---|---|---|---|
| 0 | **AUTHOR** the contract | write `research_decision.yaml`, derive `SPEC.md`, then `study.yaml` (§16) | those three files | decision contract missing or SPEC not derived from it |
| 0b | **SCAFFOLD** | `python -m research_workflow.study_factory --config study.yaml` | `studies/<id>/` tree | schema validation error |
| 1 | **PREPARE + FREEZE** (compiles) | `python -m research_workflow.prepare --study studies/<id>` | `compiled_study.json`, `audit/frozen_execution_manifest.json` | compile or phase0 regeneration error |
| 2 | **READINESS** (R1–R10, §4) | `python -m research_workflow.readiness --study studies/<id>` | `audit/readiness.json` | any check fails |
| 3 | **PREFLIGHT** (§5) | `python -m research_workflow.preflight --study studies/<id>` | `audit/preflight.json`, `audit/failure_packet.json` | any required check missing **or** failing |
| 4 | **CAUSAL REVIEW** (§6.1) | `lookahead-auditor` agent, or `research_workflow.causal_audit.run_causal_review` | `audit/pass_NN.md` + `audit/status.json` | CRITICAL > 0, or stale freeze |
| 5 | **CONTRACT REVIEW** (§6.1) | `contract-checker` agent, or `research_workflow.contract_audit.run_contract_review` | `audit/contract_pass_NN.md` + `audit/contract_status.json` | missing deliverable, unreachable terminal label |
| 6 | **SEAL** | `research_workflow.seal.generate_preexec_audit_seal` | `artifacts/preexec_audit_seal.json` | `PREEXEC_AUDIT_STALE` |
| 7 | **NT SMOKE** (1 day) | `python backtests/run_nt_study.py --study studies/<id> --mode collect --stage day` | `studies/<id>/runs/` | `PREEXEC_AUDIT_STALE` or schema/surface failure |
| 8 | **RECONCILE** | `python scripts/reconcile_runs.py` | `lifecycle.json` sidecar | — (classification only) |
| 9 | **AUTHORIZE** | `experiment.authorize_experiment` | `artifacts/experiment_authorization.json` | chronology missing or overlapping |
| 10 | **TRAIN COLLECT** (partitioned, §7) | `collection.collect_period_partitioned(..., execute=True)` | one run dir per year | authorization mismatch, prohibited year |
| 11 | **MERGE** | `partitioning.reconcile_partitions` → `merge_partition_outputs` | merged frame | overlap, schema/dtype drift |
| 11b | **REQUIRED PRE-FIT GATES** | `gates.assert_gates_satisfied(..., stage="pre_fit")` | gate evidence bound to merged TRAIN identity | missing/failed/stale gate or changed merge identity |
| 12 | **FIT** | `modeling.fit_models` | `artifacts/experiment_models.json` | non-TRAIN partition, outcome column in X, unsatisfied pre-fit gate |
| 13 | **TRAIN FREEZE** | `modeling.freeze_train_artifacts` | `artifacts/train_experiment_freeze.json` | non-TRAIN meta, outcome column in a frozen feature set |
| 14 | **OOS OPEN** | `experiment.assert_oos_open` | (returns the freeze) | `TrainFreezeRequired` |
| 15 | **OOS** | `collection.collect_period(..., "oos")` | run dirs | freeze absent or stale |
| 16 | **ANALYSIS** | `analysis.analyze_results` | `artifacts/experiment_analysis.json` | missing columns, OOS not open |
| 17 | **DECISION** | — | `results/STUDY_REPORT.md`, next `research_decision.yaml` | — |

**Nothing executes before stage 6.** No collection, label build, training, backtest or staged
run happens before preflight is `CLEAR` and both reviews have issued a status.

### Three properties of this order

1. **Expensive work happens late.** READINESS sits before PREFLIGHT, the audits and the seal
   because it proves the real NT runtime path is safe on bounded real samples. Failing R1
   costs seconds; failing after an audit round costs a re-audit.
2. **FREEZE goes stale on any execution-affecting change.** The composite is resolved from the
   study's whole execution closure (`scripts/resolve_execution_manifest.py`). Both reviews
   re-resolve it and refuse with `STALE_FREEZE` if it moved. After fixing anything inside the
   closure, re-run stage 1 and redo 3–6.
3. **Targeted tests beat global CI.** `research_workflow/test_selection.py` picks the tests a
   change requires. Running the whole suite repeatedly is latency, not diligence.

### TRAIN / OOS discipline

`research_workflow/experiment.py` is the whole authority.

- `chronology.train` / `.dev` / `.prohibited` in `study.yaml` must be non-empty (train, dev)
  and pairwise disjoint. The authorization is content-hashed; a stale artifact is refused.
- `runtime_authorization(study, "oos")` calls `assert_oos_open` *before* producing dates and
  stamps `train_freeze_sha256` into the plan. `verify_runtime_authorization` re-checks that
  binding at the NT boundary and rejects prohibited years.
- **OOS opens only at stage 14**, and only when `artifacts/train_experiment_freeze.json`
  exists and binds to the current authorization.
- **OOS may not influence** feature selection, preprocessing, model class, hyperparameters,
  calibration, thresholds, or deciles — all are fields of the TRAIN freeze, frozen at stage 13.
  Thresholds and deciles carry `derivation_population: "train"`.
- **Smoke acceptance must use the authoritative population.** `scripts/validate_smoke.py` and
  `OutputManager` re-derive the feature surface independently for that reason.

---

## 4. READINESS gate (R1–R10)

`research_workflow/readiness.py`. Every check fails closed with a specific exception. A failed
R1 short-circuits R2–R7 as `R1_PREREQUISITE_FAILED` (all depend on `DataPlan`); R8 and R9 are
independent and always run.

| Check | Proves |
|---|---|
| R1 | exact physical dataset identity — declared == `DatasetSpec` == resolved == opened, with warmup-through-run coverage |
| R2 | 1s / 1m `ts_init - ts_event` contracts on real bounded samples; derived 5m via `CompletedMinuteFiveMinuteAggregator`, no external 5m stream |
| R3 | loaded bars are precision-compatible with the governed instrument |
| R4 | callback causal order, via a probe strategy and the existing verifier |
| R5 | the real collector constructs under real phase0 authorization (construction only, no `engine.run()`) |
| R6 | the `STRATEGY_OUTPUT_INTERFACE_MISSING` contract |
| R7 | a synthetic candidate/observation fixture validates through the real `OutputManager` |
| R8 | the execution identity resolves twice with exact equality and no mutation |
| R9 | zero alternate (ungoverned) catalog openers under `studies/<id>/**/*.py` |
| R10 | bounded real first-nonempty collector output parity against the collection-time feature contract |

**When READINESS fails:** it is a defect to fix, not a stop (§12). Read the named exception in
`audit/readiness.json`, fix at the owning layer, re-run stage 2 only. If the fix touched the
execution closure, re-run stage 1 first.

`audit/readiness.json` is additive evidence. It never rewrites `frozen_execution_manifest.json`,
`status.json` or any other stage artifact, and is not a second execution-identity authority.

---

## 5. Deterministic PREFLIGHT

`research_workflow/preflight.py`. Required checks:

```
EXECUTION_MANIFEST  CAUSAL_LINT  ARTIFACT_SCHEMA
FEATURE_PROMOTION   RESEARCH_DECISION_FIDELITY   CAUSAL_INVARIANTS
```

Readiness is a **two-part claim**: every required check *executed*, **and** every one passed.
`--skip-tests` stays available for diagnostics but cannot report `READY_FOR_AUDIT` — a check
that never ran cannot fail, and skipping one used to *increase* the reported readiness.

On failure read `audit/failure_packet.json`. Do not re-derive the failure by hand.

---

## 6. Causal audit vs. model integrity

Two different questions. Never merged, never duplicated.

```
LOOKAHEAD / CAUSAL AUDIT   "Could this information legally be known at T?"
MODEL INTEGRITY            "Is the feature/model surface scientifically sane and nondegenerate?"
```

### 6.1 The causal system — it exists, do not build another

| Layer | Implementation |
|---|---|
| AST lint | `scripts/causal_lint.py` (inside preflight) |
| Ruleset A1–H4 | `docs/CAUSAL_CHECKLIST.md` — single source of truth for all three harnesses |
| Causal reviewer | `lookahead-auditor` — owns **A, B, C1–C3, F, G, H** |
| Contract reviewer | `contract-checker` — owns **C4, D, E**, deliverables, seals, lifecycle state, model-integrity declarations |
| Executable review | `research_workflow/causal_audit.py`, `contract_audit.py` |
| Provenance | `scripts/run_preexec_audits.py`, `research_workflow/seal.py` — binds report bytes to the audited composite |

The two reviewers have **disjoint scope** and neither may report the other's category. That
boundary is what stopped multi-pass audit loops. Re-audits: pass 2+ adjudicates every prior
finding before raising new ones, at most 3 new CRITICALs per pass, always a **new**
`audit/pass_NN.md` — never an append. Gates read the status JSON, never prose.

Causal and contract reviews must be authored by **distinct declared reviewer identities**.

### 6.2 Model integrity — gate, diagnostic, or recommendation

Be precise about which of the three a control actually is.

**Implemented hard gates** (fail closed, inside the lifecycle):

| Control | Where |
|---|---|
| Declared feature contract == produced surface; an **all-null column is refused under either null policy** | `scripts/check_feature_surface.py`, in `OutputManager.persist_collection` and re-derived in `scripts/validate_smoke.py` |
| Forward-outcome columns may not enter a fit matrix or a frozen feature set | `forward_outcomes/guard.py` via `modeling.fit_models` and `freeze_train_artifacts` (§10) |
| Outcome columns in `X` rejected at fit time | `research/analysis/modeling.fit_model` (`SchemaSurplus`) |
| TRAIN and DEV may not appear in one fit | `fit_model` (`PartitionMixing`) |
| Refuses to fit without partition provenance | `fit_model` (`PartitionProvenanceMissing`) — a missing `_partition` column is not evidence of a single partition |
| Threshold freeze requires TRAIN-only scores, records `derivation_population` | `research/analysis/modeling.freeze_threshold` |
| Declared arms must request features the collection provides | `resolve_arms` (`SchemaMissing`) |
| Model/feature-order binding, binary classes, `predict_proba` | `scripts/check_model_binding.py` |
| `train_test_split(shuffle=True)` on temporal data | `causal_lint.py` rule C3, CRITICAL |
| Degenerate slice surfaces a caveat, not a silent single group | `research/analysis/slices.py`, `reporting.py` |

**Available diagnostics** (real, but not unconditional gates): see §11 diagnostics table.

**Recommended integrity checks** — the study performs and reports these; they are **not**
mechanically enforced, and must not be described as gates:

- every declared feature is populated where its semantics require a value
- every required feature has variance on the fitted population
- each arm has the feature surface it claims — two arms with identical
  `fit_identity_sha256` / `prediction_identity` mean the added block is dead
- score surfaces are nondegenerate; frozen thresholds and deciles are nondegenerate
- a shuffled-label run behaves near chance when performed
- temporal validation is chronological
- suspiciously strong single-feature power triggers inspection before it is reported

A study reporting an arm delta must state which of these it verified. An unverified delta is a
hypothesis, not a result.

---

## 7. The generic collector

**The authoritative collection path is `research_workflow/generic_collector.py`, executed
through `backtests/run_nt_study.py --mode collect`.**

**No, you may not copy an old collector.** Not copy, not subclass, not wrap, not
`sys.path.insert` into a sibling study. Anything under `collectors/`,
`strategies/*_collector.py` or `studies/*/implementation/collector.py` is historical.

How a study drives it:

1. `study.yaml` declares canonical `FeatureInstance`s.
2. `research_workflow/compiler.py` compiles them; the **provider dependency closure** is
   derived from the declared instances, not discovered at runtime.
3. `research_workflow/phase0.py` builds the phase-zero authorization manifest from the
   compiled instances — no study module imported, no historical alias catalog consulted.
4. `research_workflow/execution_plan.py` binds resolved provider methods and the output
   surface **once**, at strategy construction, into fixed callback groups. A declared instance
   whose provider has no output binding is kept as a null column without paying for an unused
   calculation at every checkpoint.
5. `research_workflow/output_manager.py` persists and enforces schema and feature surface.

Compact snapshot paths and callback grouping are **implementation details**. Canonical output
parity is **mandatory**.

**ETH state may remain causally necessary even when candidate emission is RTH.** Session
filtering governs which candidates are *emitted*, not which bars providers may *see*. Do not
cut ETH history out of the replay as an optimization.

### Population qualification: established filter vs. identity allowlist

Candidate declaration in `_evaluate_checkpoint` is gated by exactly one of two mutually
exclusive tests — they express different population definitions and are never combined:

- **Established filter** (`established_required: true`, the default): a live threshold/
  persistence rule over `age_gate_seconds`, `running_mfe_atr_gte`, `new_progress_windows_gte`,
  `retained_mfe_ratio_gte`. This is what most existing studies use.
- **Identity allowlist** (`required_checkpoint_identities_path`, a `population.qualification`
  key in `study.yaml`): when set, it is the *only* qualification test applied, and the
  established filter is not evaluated at all. Membership comes from an externally frozen
  `(regime_start_ns, checkpoint_index)` table loaded once at strategy construction
  (`FlipPredictionCollectorConfig.required_checkpoint_identities_path`, resolved relative to
  the study directory by `build_collector_config_kwargs` in
  `backtests/nt_runtime/modes/collect.py`) — fails closed on a missing identity/checkpoint
  column or a duplicate identity.

Use the identity allowlist when a population's selection logic was itself computed once,
offline, against an already-collected checkpoint stream (e.g. a derived-score threshold-
upcross rule scored against a frozen upstream model — see `clean_tradable_reversal`'s
`STAGE2_P90_UPCROSS_V1`) — the live collector's job then is to reproduce that exact
checkpoint's feature surface, not to rediscover membership. `checkpoint_index` numbering is
driven purely by wall-clock grid alignment relative to `regime_start_ns` (unconditional in
`_handle_1s_bar`, independent of which qualification path is active), so it reproduces
identically across studies sharing this collector and the same market data. This is a
generic, declarative mechanism — any study can plug into it by declaring
`population.qualification.required_checkpoint_identities_path` in `study.yaml`; it is not
specific to any one study.

**Build that identity table with `scripts/build_derived_score_upcross_population.py`**, not a
bespoke per-study script — it was extracted after being independently reimplemented twice with
subtly different results. The pitfall it exists to prevent: `left_censored_above_threshold`
(a regime whose first eligible checkpoint is already at/above threshold) is a **diagnostic
label only**. It does not remove the regime from later selection. That regime's own first
checkpoint can never be selected as an upcross regardless (its `prev_above` is undefined, not
`False`), but a genuine later dip-then-recross within the *same* regime is a real, fully
observed, non-censored crossing and stays eligible. Filtering the whole regime out once it is
flagged left-censored silently drops real population members (~0.4% of `clean_tradable_reversal`'s
TRAIN population when this was gotten wrong) — verify any new use against a population with a
known frozen count before trusting it.

### Partitioned TRAIN collection

`research_workflow/partitioning.py` + `collection.collect_period_partitioned`. A
`PartitionSpec` carries three intervals:

```
warmup prefix      [warmup_start, primary_end]    causal context only
primary emission   [primary_start, primary_end]   the ONLY rows retained
forward lookahead  [primary_end, lookahead_end]   target / outcome resolution
```

- `lookahead_seconds` defaults to `target.horizon_seconds`. At a chronology boundary the
  lookahead replays only if it stays inside an authorized year; otherwise the lower-level
  authorization stays fail-closed and the target contract's censoring handles the tail.
- Each year runs in its **own process** (one worker created and torn down per partition).
  NautilusTrader's Rust logger is process-global and cannot initialize twice in one
  interpreter, so a reused worker panics on the second year — and per-process isolation is
  what makes partitioning genuinely memory-bounded.
- `retain_primary_rows()` drops warmup/lookahead rows **after** replay, so filtering cannot
  change causal state.
- `reconcile_partitions()` rejects duplicate ids, overlapping primary intervals, and
  incompatible authority hashes.
- `merge_partition_outputs()` is deterministic: identical column order, lossless numeric dtype
  promotion only, duplicate primary keys rejected, stable `mergesort` ordering.
- **Partitioned vs. monolithic parity is mandatory.** A divergence is a defect, not a variant.

### Telemetry must not change what it measures

`tracemalloc` is **opt-in** (`NT_TELEMETRY_TRACEMALLOC=1`) because it instruments every
allocation; left on it dominates replay wall time. Process RSS telemetry is always collected
and is cheap. Benchmark harnesses must separate replay cost from instrumentation cost, and
comparisons run through `scripts/benchmark_historical_same_harness.py` under the same harness.
Measured figures: `docs/WORKFLOW_REFERENCE_FACTS.md`.

---

## 8. Standalone backtests vs. governed studies

Two different activities. Do not mix their rules.

| | Governed ML study | Standalone strategy backtest |
|---|---|---|
| Question | does a signal exist, and does it survive OOS? | how does this strategy perform? |
| Entry point | `backtests/run_nt_study.py --mode collect` | `backtests/run_backtest.py` |
| Contract | `research_decision.yaml` → `study.yaml` → `compiled_study.json` | a config YAML or `--param` flags |
| Lifecycle | all 17 stages (§3) mandatory | not applicable |
| Data plan | `resolve_data_plan(...)` — adds collector chronology and OOS gates | `resolve_catalog_plan(...)` — generic catalog/instrument/warmup |
| Manual | this document | `docs/BACKTEST_EXECUTION.md` |

A standard backtest is `python backtests/run_backtest.py --strategy <id> --param k=v`. **Never
a new `run_*.py`** for an ordinary parameter, date range, or strategy variation. Do not call
`resolve_data_plan` for a non-collector backtest. `--strategy` must never override a sealed
study's declared `strategy_class`.

---

## 9. Forward outcomes / economic path

`research_workflow/forward_outcomes/` — study-agnostic. It imports no regime engine, no flip
definition, no instrument, no classifier.

### The separation this package exists to enforce

```
causal features   what was knowable at decision time    -> model INPUTS
proposed entry    immutable decision/entry anchor       -> the boundary
forward outcome   what happened afterwards              -> LABELS, never inputs
```

| Module | Role |
|---|---|
| `contracts.py` | `ProposedEntry` (frozen, `entry_sha256`), `ForwardOutcomeSpec` (frozen, `spec_sha256`); `build_outcome_columns()` **derives** the output schema from the spec |
| `tracker.py` | streaming observation of active entries |
| `selection.py` | build entries from frozen scores — threshold crossings, deciles, local maxima |
| `partition.py` | `required_lookahead_seconds`, partition build/merge, `assert_partition_parity` |
| `guard.py` | the causal guard (§10) |
| `governance.py` | artifact writing, reconciliation, provenance |
| `analysis.py` | descriptive summaries only |
| `smoke.py` | streaming-vs-bruteforce infrastructure smoke |

**Architectural guarantees:**

- **Immutable proposed entry.** Every field is knowable at `decision_ts`/`entry_ts`; the frozen
  `entry_sha256` covers all of it, so an entry set cannot be re-anchored after its outcomes are
  measured. ATR is taken at the entry anchor, never recomputed from the future path.
- **Separate post-event artifact.** Candidate features, model scores, `proposed_entries.parquet`
  and `forward_outcomes.parquet` are four distinct files. Every outcome artifact carries
  `forward_outcome_manifest.json` declaring `data_class: OUTCOME_LABEL_POST_EVENT`,
  `causal_relative_to_entry: false`, `usable_as_model_input: false`.
- **Streaming tracker.** One small observation per live entry; work per bar is O(active
  observations). **Full future paths are never retained**, and nothing scans the historical
  entry set.
- **Partition-safe lookahead.** The spec sizes the lookahead; `assert_partition_parity` proves
  the partitioned result equals the monolithic one.
- **Explicit censoring, no silent shortening.** A record's status is the **worst** any part
  reached, so one unobservable horizon can never report as `RESOLVED`. A horizon exceeding the
  tracking budget raises at spec construction rather than being quietly truncated.
- **Signal-entry vs. confirmation-entry** are separate entry families in separate artifact
  directories, compared explicitly — never pooled.
- **Production causal guard** — §10.

Metric definitions and censoring codes are generated from the spec; read
`build_outcome_columns()` and `OutcomeStatus`, not a list in this manual.

---

## 10. Production causal outcome guard

`research_workflow/forward_outcomes/guard.py`. **Fail-closed** — it raises `OutcomeLeakError`;
there is no warning mode.

**Can a forward outcome enter model X? No.** Two production surfaces enforce it:

1. **Fit time** — `modeling.fit_models` calls `guard_training_frame(X, list(X.columns))`. It
   checks the declared feature list **and** any outcome columns riding along in the frame,
   because the common accident is a frame joined with outcomes and a fitter that re-derives
   its column list from the frame.
2. **TRAIN freeze** — `modeling.freeze_train_artifacts` calls `assert_causal_feature_surface`
   on **every arm's frozen feature set**. A set can be frozen without passing through a
   fitter, and a leak frozen into the contract outlives the run.

Three barriers, none of them naive substring matching:

- **Exact** — `outcome_column_namespace(spec)` regenerates the schema from the spec.
- **Structural** — `OUTCOME_COLUMN_PATTERNS`, anchored regexes matching the *generated naming
  grammar*.
- **Registry** — `assert_outcome_columns_not_registrable(spec)` asserts no outcome column
  resolves through `features.registry`. If one did, a study contract could legally declare it.

### The constraint that must not be broken

`prior_1m_regime_mfe_atr`, `rolling_300s_giveback_atr`, `rolling_300s_max_progress_atr`,
`running_mfe_atr` and `current_progress_atr` are **legitimate causal features** — they describe
the past as of the decision. `mfe_300s`, `max_mfe_atr` and `time_to_max_mfe` describe the
future after the entry. The patterns are anchored to the generated grammar precisely so the
first group passes and the second is caught.

**Do not "tighten" the guard with an unanchored substring match** — it would reject the study's
own inputs. Identity columns shared with the entry table are exempt by name, so joining
outcomes back to entries does not trip it.

---

## 11. Scripts

55 scripts, classified. **Authoritative** = run this. **Shim** = redirects to a module; prefer
the module. **Diagnostic** = never a gate. **Historical** = a completed migration or a
superseded path; do not use for new work.

`sealed-safe` = cannot change the execution composite or a stage artifact, so it is safe while
a study is sealed and in flight.

### Authoritative — lifecycle and governance

| Script | Purpose | Mutates | Sealed-safe |
|---|---|---|---|
| `resolve_execution_manifest.py` | resolve the execution closure + composite | no | yes |
| `run_preexec_audits.py` | ingest an audit report, verify provenance, issue status | `audit/status.json` | yes |
| `run_bounded_study.py` | run a stage under time/memory/stale-progress limits, emit a JSON status card | `studies/<id>/runs/` | yes |
| `reconcile_runs.py` | classify run lifecycle; `ABANDONED` by PID liveness. Never rewrites `run_manifest.json` | `lifecycle.json` sidecar | yes |
| `validate_smoke.py` | canonical smoke acceptance; re-derives the feature surface | `validation_report.json` | yes |
| `causal_lint.py` | AST lint for recurring causal defects | no | yes |
| `check_artifact_schema.py` | artifact + seal manifest schema and DAG validation | no | yes |
| `check_model_binding.py` | model sha, feature count/order, binary classes, `predict_proba` | no | yes |
| `check_feature_surface.py` | declared contract == produced surface; all-null refusal | no | yes |
| `check_feature_promotion.py` | feature lifecycle promotion evidence | no | yes |
| `check_candidate_promotion.py` | promotion facts for an inactive canonical authority | no | yes |
| `check_research_decision_fidelity.py` | decision contract → SPEC/study fidelity | no | yes |
| `check_spec_fidelity.py` | SPEC → `StudySpec` fidelity | no | yes |
| `check_collect_equivalence.py` | full-collection equivalence against a reference | no | yes |
| `scan_alternate_catalog_openers.py` | static guard: ungoverned catalog opens under a study | no | yes |
| `validate_data.py` | raw file and catalog integrity | no | yes |
| `build_audit_packet.py` | assemble the contextual diff packet for an auditor | yes | yes |
| `describe_study_diff.py` | describe what changed between study states | no | yes |
| `bootstrap_audit_lineage.py` | record a study's durable audit lineage anchor | yes | **no** |
| `safe_cleanup.py` | fail-closed guard for recursive deletion (§13) | deletes | — |
| `sync_agents.py` | regenerate Codex + Antigravity agent defs | yes | yes |
| `build_derived_score_upcross_population.py` | build a frozen identity+score population from a checkpoint stream, a frozen model, and per-direction thresholds (feeds the generic collector's identity-allowlist mode, §7) | no | yes |

### Authoritative — feature system

| Script | Purpose | Sealed-safe |
|---|---|---|
| `feature_ctl.py` | V2 canonical feature governance CLI: check and promote | yes (check) |
| `generate_canonical_feature_reference.py` | regenerate `CANONICAL_FEATURE_REFERENCE.yaml` | yes |
| `prepare_feature_candidate.py` | prepare + freeze an inactive candidate authority | yes |
| `materialize_feature_candidate.py` | materialize the final candidate bundle | yes |
| `authorize_feature_candidate_activation.py` | bind review evidence to candidate bytes | yes |
| `activate_feature_pipeline_v2.py` | verify parity, then atomically flip the active pointer | **no** |

### Authoritative — data and catalog

| Script | Purpose |
|---|---|
| `build_v0_catalog.py` | generic raw-parquet → NT catalog materializer |
| `build_es_v0_2020_2026_catalog.py` | ES.v.0 2020–2026 catalog |
| `build_dense_1s.py` | calendar-aligned dense 1s parquet from immutable raw bars |
| `preflight_dense_1s.py` | preflight for the dense-1s utility |
| `check_mbp1_cost.py` | Databento MBP-1 download cost preflight |

### Compatibility shims — not primary entry points

| Shim | Use instead |
|---|---|
| `scripts/research_preflight.py` | `research_workflow.preflight` |
| `scripts/compile_study.py` | `research_workflow.compiler` |
| `scripts/create_study.py` | `research_workflow.study_factory` |
| `scripts/prepare_and_freeze.py` | `research_workflow.prepare` |
| `scripts/preexec_audit_seal.py` | `research_workflow.seal` |
| `scripts/build_phase0_manifest.py` | `research_workflow.phase0` |
| `scripts/select_required_tests.py` | `research_workflow.test_selection` |
| `backtests/nt_runtime/output_manager.py` | `research_workflow.output_manager` |
| `backtests/nt_runtime/readiness.py` | `research_workflow.readiness` |

### Diagnostics — never a gate

| Script | Purpose |
|---|---|
| `find_first_parity_divergence.py` | first-divergence localization — **mandatory first step for any parity failure** |
| `verify_collector_parity.py` | full collector run vs. every persisted field |
| `diagnose_collector_gap.py` | locate the replay-time gap between collectors |
| `run_collector_ablation_matrix.py` | benchmark-only ablation matrix on one replay day |
| `benchmark_historical_same_harness.py` | historical controls through the canonical harness |
| `run_vertical_slice.py` | 10-stage end-to-end composition gate on a synthetic partition |
| `run_isolated_sweeps.py` | isolated parameter sweeps |
| `capture_baseline_fixtures.py` | capture baseline fixtures |
| `export_notebook_knowledge_base.py` | export a knowledge-base bundle |

### Historical — completed migrations and superseded paths

| Script | Status |
|---|---|
| `generate_oos_unlock.py` | superseded by `experiment.assert_oos_open` + the TRAIN freeze; kept for studies built against it |
| `archive_legacy_feature_registry.py` | V1 archive creation — done |
| `restore_legacy_feature_file.py` | V1 rollback operator tool |
| `migrate_cleanflip_feature_instances.py` | one-off V1→V2 study migration |
| `audit_full_feature_system_v2_inventory.py` | V1→V2 normalization — done |
| `build_canonical_promotion_inventory.py` | V2 promotion evidence build — done |
| `run_full_legacy_feature_parity.py` | legacy→canonical parity matrix — evidence produced |

---

## 12. Autonomy policy

**A gate failure means: do not advance past the gate. It does not mean: stop and report
`BLOCKED`.**

Autonomously, without asking: diagnose the deterministic defect (read
`audit/failure_packet.json`, the exception, the diff), fix it at the owning layer, add or
update a **targeted** test, re-run the affected **bounded** check, regenerate stale
deterministic artifacts, and resume from the correct stage — not from the beginning.

### Terminal stop conditions

Stop only for these, and say which one:

1. **Genuine semantic ambiguity** — two defensible readings producing materially different
   experiments.
2. **Data safety risk** (§13).
3. **Authorization ambiguity** — unclear whether a period, dataset or action is authorized.
4. **Cannot preserve causality or TRAIN/OOS correctness** — the only fix would require
   look-ahead, OOS tuning, or breaking a freeze.
5. **Capability gap** — name it (`ANALYSIS_HARNESS_GAP`, `BESPOKE_JUSTIFICATION`), do not say
   "it didn't work".
6. **Prohibited data access risk** — the next step would touch a prohibited year or source.

### Failure routing

| Error | Fix at |
|---|---|
| any feature-instance code (§2) | `study.yaml` instance parameters, or the canonical bundle |
| `FEATURE_LIST_MISMATCH` | recompile the study |
| `UNREGISTERED_STRATEGY`, `STRATEGY_NOT_BOUND` | `STRATEGY_REGISTRY` in `backtests/nt_runtime/strategy_binding.py` |
| `CONFIG_UNKNOWN_KEYS` | align the YAML key with the config schema |
| `STALE_FREEZE`, `PREEXEC_AUDIT_STALE` | re-run stage 1, then redo 3–6 |
| `MANIFEST_RESOLUTION_FAILED` | `scripts/resolve_execution_manifest.py` |
| `OUTCOME_COLUMN_IN_CAUSAL_SURFACE` / `_IN_TRAINING_FRAME` | drop the columns; never loosen the guard |
| `PartitionProvenanceMissing` | pass `meta` with `_partition`, or an explicit recorded `SplitPolicy` opt-out |
| `PartitionMixing` | you are fitting across TRAIN and DEV |
| `TrainFreezeRequired` | OOS is locked; freeze TRAIN artifacts first |
| any parity failure | run `scripts/find_first_parity_divergence.py` **before** any investigation |

---

## 13. Data safety

**Before any recursive deletion or cleanup:**

1. Inspect every descendant for **symlinks, junctions, mount points and Windows reparse
   points** that escape the intended root. `os.path.islink()` returns `False` for a Windows
   directory junction — check reparse points, not just symlinks.
2. Resolve before you delete. `Path.resolve()` decides, not the string prefix.
3. Confirm the target is inside repository-owned storage. `data/catalog/` in particular may
   link to storage outside the repository.
4. **Fail closed.** If any descendant resolves outside the intended disposable root, abort the
   whole operation. Do not delete "the safe part".

`scripts/safe_cleanup.py::assert_safe_to_delete` implements this. Use it, or replicate it,
before any recursive removal of a directory you did not create in this session.

**Never junction live `data/` into a disposable worktree.**

**Never silently substitute a dataset.** If the authorized source is unavailable, fail closed
and report it. A substituted source produces a result nothing downstream will flag.

---

## 14. Research pattern

Prediction of a **structural** event and prediction of a **tradable** event are distinct
research questions. Do not mix them.

| Study | Does | Prohibited |
|---|---|---|
| **1 — Prediction** | collect causal features, train and freeze a predictor, validate clean OOS signal | — |
| **2 — Economics (observational)** | use the *frozen* scores/thresholds/deciles to create immutable proposed-entry anchors; observe the forward path with `forward_outcomes`; ask only whether confidence **ranks** economic quality | `model_fit`, `strategy_optimization` |
| **3 — Economic-quality model** | only if 2 warrants it: train against a declared economic target (P(clean reversal), E[MFE], E[MAE], target-before-stop) | — |
| **4 — Strategy optimization** | last | — |

`studies/frozen_flip_score_forward_path_2024/` is the reference Study 2: it consumes the frozen
artifacts of another study, declares `model_fit: prohibited` and
`economic_use: observational_only`, and produces separate signal-entry and confirmation-entry
artifact sets.

Observation is not optimization. A Study 2 is never licensed to tune anything on OOS.

---

## 15. Analysis discipline

Pandas and Polars are computation libraries, **not** a second governed workflow.

```
validated collection -> research/analysis/ -> AnalysisSpec + validation contracts -> authoritative result
```

Scratch pandas work is encouraged for **debugging and forensic inspection**. Its outputs are
**NON-AUTHORITATIVE** and must be labelled so: they may not be quoted as a study result,
entered into a report as a finding, or used to close a research question.

If `research/analysis/` cannot express what a study requires, that is a harness gap. Stop and
report `ANALYSIS_HARNESS_GAP` naming the missing capability.

**Do not wrap a canonical runner** to retry, monitor or babysit it — a wrapper becomes a second
runner with none of the governance. Use `scripts/run_bounded_study.py` and read its JSON status
card. Do not launch a second identical run while one is `RUNNING`; confirm terminal state with
`scripts/reconcile_runs.py`.

---

## 16. Study directory and contract authority

```
studies/<study_id>/
├── research_decision.yaml    AUTHORITATIVE decision contract      [git]
├── SPEC.md                   derived from research_decision.yaml  [git]
├── study.yaml                machine contract, FeatureInstances   [git]
├── compiled_study.json       compiled, sha256-bound               [git]
├── config/                   feature/population/target/deliverables contracts [git]
├── implementation/           small declarative hooks only, often absent       [git]
├── tests/                    study contract tests                 [git]
├── audit/                    frozen_execution_manifest, readiness, preflight,
│                             failure_packet, pass_NN + status, contract_pass_NN
│                             + contract_status                    [git]
├── artifacts/                phase0_source_manifest, preexec_audit_seal,
│                             experiment_authorization, experiment_models,
│                             train_experiment_freeze, experiment_analysis  [git]
└── results/STUDY_REPORT.md                                        [git]
```

**Contract authority:** `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.

Create or verify `research_decision.yaml` **before** drafting or modifying `SPEC.md`. Nothing
compiles or passes preflight unless
`python scripts/check_research_decision_fidelity.py --study studies/<id>` passes.

**Behavioural rule:** never improve, broaden, clean up, or make a study more statistically pure
by changing a fixed baseline or adding feature discovery unless the decision contract
explicitly permits it. Surface a design concern as a caveat; do not silently alter the
experiment.

**Never commit generated data** — `runs/`, `canonical_*/`, `_work/`, `*.parquet`, `*.joblib`,
`*.onnx`. Commit the manifests.

---

## 17. Timestamps

- Raw Databento OHLCV bars are **OPEN-stamped** (`ts_event`). Complete OHLCV is usable only at
  interval close.
- Offline research normalizes derived bars to **CLOSE-stamped** indices
  (`label='right', closed='left'`).
- NT catalogs preserve open-stamped `ts_event` and set `ts_init = ts_event + bar_duration_ns`
  (1s +1s, 1m +60s, 3m +180s, 5m +300s), so the event loop dispatches completed bars at
  interval close.
- **1s bars therefore arrive before their parent 1m bar** (`add_bars_causal_order`,
  `verify_callback_causal_order`; proven per-study by R4). Buffer recent 1s bars and replay
  them retroactively from fill time, or you will miss the first minute of price action.
- Derived timeframes are aggregated from **completed** lower-timeframe bars, never loaded as an
  independent stream.
- Per-event callback ordering beyond these guarantees is a property of a study family and
  belongs in that study's `SPEC.md`, not here.
- Display and analysis in Central Time (`America/Chicago`); NT internals are UTC.
  RTH 08:30–15:15 CT.

---

## 18. Deprecated — use instead

| Deprecated | Use instead |
|---|---|
| Feature System V1 physical names; `features/FEATURES.md` | canonical instances (§2); `features/CANONICAL_FEATURE_REFERENCE.yaml` |
| Legacy alias resolution as an active path | `canonical_verified_definition_universe` |
| Bespoke per-study collectors | `research_workflow/generic_collector.py` (§7) |
| Legacy `backtests/run_*.py` scripts | `run_backtest.py` / `run_nt_study.py` (§8) |
| `scripts/generate_oos_unlock.py` as the OOS authority | `experiment.assert_oos_open` (§3) |
| The seven `scripts/` shims | the `research_workflow` modules (§11) |
| Root-level `*_HARDENING_*`, `*_HARNESS_*_REPORT`, `*RFC*`, `*PLAYBOOK*`, `PROPOSED_*` docs | this document; see `docs/DOCUMENT_MAP.md` |

---

## 19. Deeper references

| Topic | Document |
|---|---|
| Causal/contract audit ruleset A1–H4 | `docs/CAUSAL_CHECKLIST.md` |
| Current-state numbers, closure membership, troubleshooting facts | `docs/WORKFLOW_REFERENCE_FACTS.md` |
| Which docs are current vs. stale | `docs/DOCUMENT_MAP.md` |
| Subagent roster and rationale | `docs/SUBAGENT_ROSTER.md` |
| Feature lifecycle and promotion | `features/FEATURE_REGISTRY_CONTRACT.md` |
| Canonical feature vocabulary | `features/CANONICAL_FEATURE_REFERENCE.yaml` |
| Catalog and data | `docs/DATA_CATALOG.md` |
| Standalone backtest execution | `docs/BACKTEST_EXECUTION.md` |
| Study methodology, MFE/MAE replay | `docs/STUDY_METHODOLOGY.md` |
| SPEC templates, Deliverables Manifest | `docs/TEMPLATES.md` |
| Reporting and tearsheets | `docs/ANALYSIS_REPORTING.md` |
| Profiling and ONNX | `docs/PERFORMANCE.md` |
| Error registry | `docs/ERROR_REGISTRY.md` |
| Analysis harness contract | `ANALYSIS_HARNESS_A0_CONTRACT.md` |
| Backtest harness boundary | `BACKTEST_HARNESS_B0_BOUNDARY.md` |
| READINESS R1–R10 design | `ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md` §8 |
| Composite targets, derived inputs, gates, model selection | §20, below |
| Researcher-facing implementation map, novelty routing | `docs/RESEARCH_STUDY_BLUEPRINT.md` |

---

## 20. Composite targets, derived causal inputs, pre-freeze gates, and model selection

Four generic extensions to `StudySpec` (`research/schemas/study_spec.py`), added to close
gaps documented in `docs/RESEARCH_STUDY_BLUEPRINT.md` §5. All four are additive —
`Optional` fields, absent by default — and none force `study.type: bespoke` on their own.

### 20.1 Composite targets

`TargetSpec.conditions` is a discriminated union (`kind`: `flip` | `excursion` | `return`)
composed by `condition_logic` (`AND`/`OR`). An `excursion`/`return` condition never embeds
its own generation parameters — it references a `TargetSpec.required_forward_outcomes`
entry by id, and `research/engines/target_engine.py::compile_target_contract` constructs
a **real** `research_workflow.forward_outcomes.contracts.ForwardOutcomeSpec` from that
entry, not an approximation of its shape. This is why a composite target's excursion
conditions are causally label-only "for free": the generated column names come from the
same `build_outcome_columns()` the forward-outcome guard already protects, so
`causal_audit`'s `composite_target_label_only` check verifies them against
`forward_outcomes.guard.OUTCOME_COLUMN_PATTERNS` directly, rather than a second scanner.
A target declaring no `conditions` compiles exactly as it always has.

### 20.2 Derived causal inputs

`FeaturesSpec.derived_inputs` (`DerivedCausalInputSpec`, initial `kind:
frozen_external_model_score`) declares a non-`FeatureInstance` causal input — another
study's frozen TRAIN score. It is never resolvable through `features.registry` and never
enters `resolved_feature_instances`/`feature_list`; the compiled feature contract carries
it under a separate `derived_causal_inputs` key.

Provenance is pinned exactly, not by convention: `parent_train_freeze_artifact_sha256` is
the sha256 of the parent artifact's file bytes (not an internal field — some legacy
freezes predate `experiment.write_train_freeze`'s auto-hash), plus per-arm `model_hashes`,
`preprocessing_hash`, and the parent's `audit/status.json.audited_execution_composite_sha256`.
`research_workflow/derived_inputs.py::verify_derived_causal_inputs` re-derives all of this
against on-disk state at PREPARE time (`research_workflow/phase0.py` and
`research_workflow/prepare.py`, both — the wiring is defense-in-depth across the two
documented ways PREPARE can be invoked) and fails closed
(`DerivedInputBindingError`) on a missing, invalidated, or mismatched upstream artifact.
"Invalidated" is detected generically by scanning the parent study's existing
`artifacts/*_INVALIDATION.md` convention (already used by real studies) — not a new
mechanism invented for one study.

**Availability must be causally ordered against the child's own decision point, not just
enum membership.** `TargetSpec.decision_reference` and
`DerivedCausalInputSpec.availability_reference` share one ordering,
`TIMESTAMP_CAUSAL_ORDER = {decision_ts: 0, entry_ts: 1, confirmation_ts: 2}`. A `StudySpec`
validator rejects an input whose availability index exceeds the child's decision index at
compile time; `causal_audit`'s `derived_input_availability_causal` check re-derives the
same comparison from the compiled contract as a second, independent layer. A later-deciding
study (`decision_reference: confirmation_ts`) may legitimately consume a
`confirmation_ts`-available input — this is a real ordering check, not a `decision_ts`-only
special case.

### 20.3 Machine-enforced pre-freeze gates

`StudySpec.required_gates` (`RequiredGateSpec`) declares a gate — e.g.
`TRAIN_TARGET_BALANCE_PASS` — bound to a specific, schema-versioned artifact and a typed
`scope_fields` list (`GateScopeField`: `population` | `target` | `chronology` | `features`
| `instrument`). Never an arbitrary shell command: `research_workflow/gates.py`'s
`assert_gates_satisfied` loads the declared artifact, validates it carries at minimum
`gate_id`, `schema_version`, `status`, `scope_sha256`, `producer`, `created_at_utc`, and
compares `scope_sha256` against a fresh hash of the study's *current* declared
scope — that recomputation **is** the staleness check, not a separate mechanism. Wired
fail-closed at every stage a gate may declare (`prepare`, `readiness`, `preflight`, `seal`,
`pre_fit`, `train_freeze`). A `pre_fit` artifact must additionally carry the exact merged
TRAIN `dataset_identity_sha256`; `modeling.fit_models` checks it before estimator construction,
so a re-merge makes the gate stale. Wiring lives in `research_workflow/phase0.py`,
`research_workflow/prepare.py`,
`research_workflow/readiness.py`, `research_workflow/preflight.py` (new required check
`REQUIRED_GATES`), `research_workflow/seal.py`, and `research_workflow/modeling.py`.

### 20.4 Model selection

`ModelSpec.selection` (`ModelSelectionSpec`) declares a bounded TRAIN-only hyperparameter
search — never an unbounded AutoML system. `search_method: grid` enumerates only `choice`
domains and refuses (`SearchSpaceExceedsMaxTrials`) rather than silently truncating a grid
exceeding `max_trials`. `search_method: random` treats `max_trials` as a count of **unique**
configurations: `research_workflow/model_selection.py` de-duplicates deterministically from
`random_seed` and stops cleanly (`search_space_exhausted: true`, not an error) if a small
declared finite space is exhausted first; `log_scale` sampling requires a positive `low`.

`tuning_years`/`final_train_validation_years` are a **new, distinct, inner-TRAIN** concept
— `chronology.dev` already means OOS in this codebase (`experiment.py` binds it to
`oos_years`). A `StudySpec` cross-field validator rejects any overlap with
`chronology.dev`/`prohibited`, and the runner independently re-checks every row's
`_selection_role`/`_year` against the declared sets (`SelectionPartitionMismatch`) — OOS
data cannot enter tuning by declaration, and cannot enter it through the data either.

**Final TRAIN validation may only ACCEPT or REJECT the already-selected configuration —
it never triggers a second search.** The function that evaluates
`final_train_validation_years` rows takes the winner as its only argument and has no code
path back into the candidate loop. `final_validation_policy` defaults to `gated` (a study
opting out must say `report_only` explicitly — never implicit); a gated `FAIL` status makes
`modeling.freeze_train_artifacts` refuse outright (`ModelSelectionFinalValidationFailed`),
with no re-derivation attempted. Every frozen arm's hyperparameters and seed are
cross-checked against the selection manifest's winner
(`ModelSelectionBindingMismatch` on any drift) — the freeze refuses a model whose
family/hyperparameters cannot be traced to the declared selection protocol.

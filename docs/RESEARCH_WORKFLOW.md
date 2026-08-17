# Research Workflow

## 1. Purpose

This repository operates under strict methodology to ensure that all quantitative studies, machine learning models, feature collection, and backtests produce trustworthy, reproducible, look-ahead-free results.

The purpose of this workflow specification is to:

- Preserve **causal integrity** (bar completion, timestamp dispatch, zero look-ahead bias).
- Preserve **research-decision fidelity** (`research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`).
- Prevent **DEV / OOS leakage** (strict temporal partitioning, locked evaluation gates).
- Mandate **reusability of canonical infrastructure** (`backtests/nt_runtime/`, `utils/runner/`, `features/registry.py`).
- Minimize **agent and token waste** (deterministic preflights, compact handoffs, diff-first auditing).
- Separate **deterministic computation** (AST linting, schema validation, backtest execution) from **AI reasoning** (spec drafting, audit adjudication, result interpretation).
- Prevent **one-off runner proliferation**.

### Core Invariant

```
NEW STUDY != NEW INFRASTRUCTURE
```

A new study should normally add or configure only:

- Research decision contract (`research_decision.yaml`)
- Study configuration (`study.yaml`) and compiled contract (`compiled_study.json`)
- Strategy-specific logic (`strategies/<strategy_name>/`) if genuinely new
- Feature tracker(s) (`features/trackers/`) if genuinely new
- Study-specific unit and contract tests (`studies/<name>/tests/`)
- Study execution specifications and reports (`SPEC.md`, `STUDY_REPORT.md`)

A new study MUST NOT create:

- Another NautilusTrader engine bootstrap script
- Another instrument or catalog data loader
- Another generic analysis/result loader
- Another `run_*.py` execution script for a standard backtest or collection
- Sibling-study imports (`sys.path.insert` into another study directory) to reuse execution code

---

## 2. Canonical End-to-End Flow

Every research study moves through 16 distinct operational stages in sequence:

```
RESEARCH QUESTION
    ↓
RESEARCH_DECISION / CONTRACT
    ↓
STUDY SPEC
    ↓
FEATURE SURFACE / STRATEGY CONFIGURATION
    ↓
DETERMINISTIC PREFLIGHT
    ↓
CAUSAL AUDIT
    ↓
CONTRACT AUDIT
    ↓
PREEXEC AUDIT SEAL
    ↓
BOUNDED SMOKE
    ↓
SMOKE VALIDATION
    ↓
AUTHORIZED COLLECTION / BACKTEST
    ↓
COLLECTION / RUN VALIDATION
    ↓
ANALYSIS CONTRACT
    ↓
TRAIN ANALYSIS
    ↓
MODEL / THRESHOLD FREEZE
    ↓
AUTHORIZED OOS ANALYSIS
    ↓
RESULT VALIDATION
    ↓
STUDY REPORT / NEXT DECISION
```

### Stage Details

| Stage | Purpose | Primary Input | Canonical Tool / Script | Output Artifact | Fail Condition | Next Permitted Stage |
|---|---|---|---|---|---|---|
| **1. Research Question** | Define target anomaly or hypothesis | Natural language prompt | Orchestrator / User | `research_decision.yaml` draft | Underspecified goal | Research Decision |
| **2. Research Decision Contract** | Freeze baseline, arms, chronology, feature selection mode | Research question | `research_decision.yaml` | `studies/<name>/research_decision.yaml` | Missing baseline or unconstrained scope | Study Spec |
| **3. Study Spec & Compilation** | Scaffold study tree and compile machine contract | `research_decision.yaml` | `python scripts/create_study.py --config study.yaml` & `python scripts/compile_study.py --study studies/<name>` | `SPEC.md`, `compiled_study.json`, `config/*.json`, `tests/` | Schema validation error or contract mismatch | Feature Surface / Strategy Config |
| **4. Feature & Strategy Implementation** | Implement feature trackers and strategy logic | `compiled_study.json` | `features/registry.py`, `strategies/<name>/` | Strategy code, feature trackers, registry entries | Unregistered feature or syntax error | Deterministic Preflight |
| **5. Deterministic Preflight** | Execute AST lint, schema check, fidelity check, invariant tests | `studies/<name>` | `python scripts/research_preflight.py --study studies/<name>` | `audit/preflight.json` | Exit code != 0 (`status: BLOCKED`) | Causal Audit / Contract Audit |
| **6. Causal Audit** | Audit look-ahead, timestamp, bar dispatch causality | Code diff, `audit/preflight.json` | `lookahead-auditor` agent | `audit/pass_<NN>.md`, `audit/status.json` | Critical findings > 0 | Contract Audit / Preexec Seal |
| **7. Contract Audit** | Verify deliverable manifest, label reachability, contract fidelity | `SPEC.md`, `research_decision.yaml` | `contract-checker` agent | `audit/contract_pass_<NN>.md`, `audit/contract_status.json` | Deliverable missing or label unreachable | Preexec Audit Seal |
| **8. Preexec Audit Seal** | Authenticate freshness of execution code & audit reports | Audit reports & execution manifest | `python scripts/run_preexec_audits.py --study studies/<name>` & `preexec_audit_seal.py` | `artifacts/preexec_audit_seal.json` | Code drift or stale audit (`PREEXEC_AUDIT_STALE`) | Bounded Smoke |
| **9. Bounded Smoke** | Run 1-day execution to verify runtime stability | `artifacts/preexec_audit_seal.json` | `python backtests/run_nt_study.py --study studies/<name> --mode collect --stage day` | `runs/<timestamp>_collect_day/` | Runtime exception or zero events | Smoke Validation |
| **10. Smoke Validation** | Verify candidate parquet schema, row counts, event order | Smoke run output | `python scripts/validate_smoke.py --run-dir runs/...` | `validation_report.json` | Schema mismatch or NaN targets | Authorized Collection / Backtest |
| **11. Authorized Collection / Backtest** | Run full authorized train/dev dataset | Validated smoke run | `python backtests/run_nt_study.py --study studies/<name> --mode collect --stage full` or `python backtests/run_backtest.py` | `runs/<timestamp>_collect_full/` | Engine error or memory overflow | Collection / Run Validation |
| **12. Collection / Run Validation** | Verify full dataset integrity and equivalence against reference | Collection run outputs | `python scripts/check_collect_equivalence.py` | `equivalence_report.json` | Divergence from reference or missing data | Analysis Contract |
| **13. Analysis Contract & Specs** | Bind collection artifacts to analysis schema | Collection data | `research/schemas/study_spec.py` | `analysis_spec.json` | Missing join keys or partition leak | Train Analysis |
| **14. Train Analysis & Model Fitting** | Fit model / compute feature ranks on TRAIN split only | `analysis_spec.json` | `research/engines/` | Model artifacts, feature ranks, threshold freeze | fitting on OOS data | Model / Threshold Freeze |
| **15. Model / Threshold Freeze** | Lock hyper-parameters, thresholds, and feature lists | Fitted model | `models/artifacts/` | Frozen model joblib / ONNX | Modifying model post-freeze | Authorized OOS Analysis |
| **16. Authorized OOS Analysis** | Evaluate frozen model on authorized DEV / OOS partitions | Frozen model & OOS data | `python scripts/generate_oos_unlock.py` + analysis runner | `OOS_EVALUATION_REPORT.md` | Evaluating OOS without authorization | Study Report / Next Decision |

---

## 3. New Feature Workflow

When a study requires a feature that is not currently available in the repository, follow this exact workflow:

1. **Check Existing Registry**: Inspect `features/registry.py` and `features/FEATURE_REGISTRY_CONTRACT.md` to confirm the feature or an alias does not already exist.
2. **Identify Family**: Determine the correct feature family (e.g., `arrival_velocity`, `relative_volume`, `orderbook_imbalance`).
3. **Implement Minimal Tracker**: Add or extend a stateful feature tracker in `features/trackers/`. The tracker must compute strictly on COMPLETED 1s or bar updates without future information.
4. **Register Feature**: Add the `FeatureDefinition` entry to `FEATURE_REGISTRY` in `features/registry.py` specifying:
   - `name`: Canonical feature identifier (e.g., `rvol_5s`)
   - `status`: `'verified'` or `'provisional'`
   - `family`: Feature family string
   - `implementation`: Full module import path to the tracker class
   - `window`, `window_unit`, `reset_policy`, `update_anchor`
5. **Update Study Feature Contract**: Declare the new feature in `study.yaml` under `features.feature_list`.
6. **Add Unit Tests**: Write targeted unit tests in `tests/test_feature_library.py` verifying state updates, reset behavior, and deterministic values.
7. **Compile & Preflight**: Run `python scripts/compile_study.py --study studies/<name>` and `python scripts/research_preflight.py --study studies/<name>`.
8. **Fail-Closed Rule**: If the runner or preflight reports:
   - `FEATURE_NOT_REGISTERED`
   - `FEATURE_LIST_MISMATCH`
   - `SCHEMA_MISSING`
   - `UNKNOWN_PARAMETER`
   - `MISSING_TRACKER_SOURCE`

   **DO NOT** bypass the error by creating a custom hand-built collection script or inline pandas calculation.
   Fix the registration, tracker implementation, or study contract declaration at the canonical layer in `features/registry.py` and `study.yaml`.

---

## 4. Collector Workflow

Feature collection extracts dataset matrices directly from the NautilusTrader event loop during market replay.

### Execution Sequence

1. **Define & Compile Study**:
   ```bash
   python scripts/create_study.py --config study.yaml
   python scripts/compile_study.py --study studies/<id>
   ```
2. **Run Deterministic Preflight**:
   ```bash
   python scripts/research_preflight.py --study studies/<id>
   ```
   Must yield `RESEARCH PREFLIGHT VERDICT: CLEAR` (`audit/preflight.json`).

3. **Split Pre-Execution Audit**:
   - **Causal Audit**: Invoke `lookahead-auditor`. Report filed via:
     ```bash
     python scripts/run_preexec_audits.py --study studies/<id> --pass-num 1 --type causal --ingest audit/pass_01.md --author <declared_causal_reviewer_id>
     ```
   - **Contract Audit**: Invoke `contract-checker`. Report filed via:
     ```bash
     python scripts/run_preexec_audits.py --study studies/<id> --pass-num 1 --type contract --ingest audit/contract_pass_01.md --author <declared_contract_reviewer_id>
     ```
   *Requirement*: Causal and contract reviews MUST be conducted by distinct declared auditor identities. Each report MUST declare:
   - `audit_type`: (`causal` | `contract`)
   - `auditor`: `<actual declared reviewer identity>`
   - `study`: `<study id>`
   - `audited_execution_composite_sha256`: `<declared composite>`

   > [!IMPORTANT]
   > - `lookahead-auditor` and `contract-checker` are audit **ROLES**, not mandatory reviewer identity strings.
   > - Do not substitute the role name for reviewer identity unless that role name is genuinely the externally declared identity for the invocation.
   > - Causal and contract reviews MUST use **DISTINCT** declared reviewer identities.
   > - One reviewer/session must NOT author both audit roles.
   > - The reviewer declares the composite; tooling verifies it against `resolve_execution_manifest.py` and must never self-generate or stamp it.

4. **Generate Preexec Cryptographic Seal**:
   `run_preexec_audits.py` verifies report hashes and code composite hashes, issuing `artifacts/preexec_audit_seal.json`.

5. **Bounded Smoke Run & Validation**:
   ```bash
   python backtests/run_nt_study.py --study studies/<id> --mode collect --stage day
   python scripts/validate_smoke.py --run-dir runs/<latest_smoke_dir>
   ```

6. **Authorized Full Collection**:
   ```bash
   python backtests/run_nt_study.py --study studies/<id> --mode collect --stage full
   ```

---

## 5. Backtest Workflow

The standalone backtest harness executes strategies against historical catalog data.

### Canonical CLI Syntax

Standard execution using a config YAML:
```bash
python backtests/run_backtest.py --config backtests/configs/w4_exit_b1_2023.yaml
```

Standard execution using CLI flags:
```bash
python backtests/run_backtest.py \
    --strategy w4_exit_strategy \
    --symbol NQ \
    --start-date 2023-01-01 \
    --end-date 2023-12-31 \
    --order-handling simulated_orders \
    --run-window from_start \
    --param policy=B1 \
    --param theta=0.62 \
    --param N=10
```

Dry-run resolution (prints execution plan without running backtest):
```bash
python backtests/run_backtest.py --config backtests/configs/w4_exit_b1_2023.yaml --dry-run
```

### Infrastructure Responsibilities

- **Shared Harness (`backtests/nt_runtime/` & `utils/runner/`) owns**:
  - NautilusTrader engine bootstrap (`engine_builder.py`)
  - Instrument creation (`xcme_futures_instrument`)
  - Catalog bar loading & timestamp conversion (`utils/runner/data.py` -> `CausalDataLoader`)
  - 1s-before-1m bar dispatch ordering (`utils/causal_registration.py`)
  - Execution mode validation (`virtual` vs `simulated_orders`)
  - Parameter parsing and strategy instantiation (`strategy_binding.py`)
  - Standard run artifacts (`run_manifest.json`, `trades.parquet`, `metrics.json`)

- **Strategy (`strategies/<strategy_name>/`) owns**:
  - Signal detection and state machine transitions
  - Order submission (`submit_order`, `cancel_order`)
  - Indicator and feature updates on bar close
  - Strategy-specific parameters (`StrategyConfig`)

*Rule*: **DO NOT** create a new `run_*.py` script for an ordinary parameter, date range, or strategy variation. Create new runner code only when the canonical runner provably cannot represent the required execution semantics.

---

## 6. Analysis Workflow

Post-backtest and post-collection analysis processes candidate parquet matrices, fits ML models, and evaluates out-of-sample performance under strict partition guards.

### Pandas/Polars are libraries, not an alternate governed workflow

Pandas and Polars are computation libraries. They are **not** a second, parallel route to
an authoritative research result. The governed path is the only one that produces one:

```
validated collection
    ↓
research/analysis/
    ↓
AnalysisSpec / validation contracts
    ↓
authoritative result
```

Scratch pandas/Polars work is legitimate and encouraged for **debugging, forensic
inspection and diagnostics**. Its outputs are **NON-AUTHORITATIVE** and must be labelled
as such — they may not be quoted as a study result, entered into a report as a finding, or
used to close a research question.

If `research/analysis/` cannot express the analysis a study requires, that is a gap in the
harness, not a licence to route around it. Stop and report:

    ANALYSIS_HARNESS_GAP

naming the specific capability that is missing. Do not silently substitute scratch
analysis for the governed path — a result nobody can reproduce through the contracts is
not a result.

### Do not wrap or duplicate canonical runners

- **No scratch wrappers around canonical runners** merely to retry, monitor, or babysit a
  run. Use `scripts/run_bounded_study.py` and read its status card. A wrapper becomes a
  second runner with none of the governance the first one carries.
- **Do not launch another identical run while one is `RUNNING`** unless the previous
  process is confirmed terminal. Confirm with `python scripts/reconcile_runs.py`, which
  classifies a run as `RUNNING` only when its recorded PID is genuinely alive; anything
  else is `ABANDONED`, `FAILED`, `ABORTED` or `SUCCESS`. Concurrent identical runs produce
  two run directories competing for the same identity and make the resulting evidence
  ambiguous.

```
VALIDATED COLLECTION / TRADES PARQUET
    ↓
ANALYSIS SPEC (`research/schemas/study_spec.py`)
    ↓
SPEC & PROVENANCE VALIDATION
    ↓
FEATURE / TARGET EXTRACTION (`research/engines/`)
    ↓
TRAIN-ONLY ANALYSIS & FEATURE RANKING
    ↓
MODEL FITTING & HYPERPARAMETER TUNING
    ↓
THRESHOLD & MODEL FREEZE (`models/artifacts/`)
    ↓
AUTHORIZED OOS UNLOCK (`scripts/generate_oos_unlock.py`)
    ↓
OOS EVALUATION & METRIC CALCULATION
    ↓
STUDY REPORT (`STUDY_REPORT.md`)
```

### Canonical Analysis Package Location

```
Canonical validated analysis package:
    research/analysis/

If it is not present in the current checkout, it is maintained on the
analysis-harness branch/worktree pending integration.

Do NOT recreate equivalent analysis loading/modeling/reporting plumbing
locally. Use/integrate the validated harness rather than building a
parallel implementation.
```

> [!NOTE]
> Low-level engines in `research/engines/` (`feature_binding_engine.py`, `target_engine.py`, `lineage_engine.py`) provide specific data transformation utilities consumed by the analysis harness, but are not a standalone replacement for the complete `research/analysis/` package.

### Analysis Harness Controls

- **Harness owns**: Collection identity, schema validation, partition provenance, OOS lock enforcement, join-key validation, target alignment, standard slicing, row reconciliation, metrics computation, and model freeze verification.
- **Study owns**: Research question, experimental arms, requested feature list, custom slices, model class selection, and success criteria.

---

## 7. Failure Handling

When a command or script fails, locate the specific error code and resolve the issue at the owning architectural layer:

```
                  ┌───────────────────────────────┐
                  │      COMMAND / RUN FAILURE    │
                  └───────────────┬───────────────┘
                                  │
               Read explicit error code / traceback
                                  │
    ┌─────────────────────────────┼─────────────────────────────┐
    │                             │                             │
┌───▼──────────────────────┐ ┌────▼──────────────────────┐ ┌────▼──────────────────────┐
│  FEATURE_NOT_REGISTERED  │ │   UNREGISTERED_STRATEGY   │ │    INVALID_PARAM     │
│  FEATURE_LIST_MISMATCH   │ │   STRATEGY_NOT_BOUND      │ │  CONFIG_UNKNOWN_KEYS    │
└───────────┬──────────────┘ └───────────┬──────────────┘ └───────────┬──────────────┘
            │                            │                            │
   Fix in features/              Fix in strategies/           Fix in study.yaml or
   registry.py or                registry.py or               StrategyConfig schema
   study.yaml                    strategy.py
            │                            │                            │
    ┌───────▼────────────────────┴────────────▼───────────────────────▼──────────────┐
    │  Re-run preflight: `python scripts/research_preflight.py --study studies/<id>`  │
    └────────────────────────────────────────────────────────────────────────────────┘
```

| Failure Error Code | Root Cause | Owning Layer / Required Fix |
|---|---|---|
| `FEATURE_NOT_REGISTERED` | Feature string missing from `FEATURE_REGISTRY` | Add `FeatureDefinition` to `features/registry.py` |
| `FEATURE_LIST_MISMATCH` | `study.yaml` feature list SHA-256 != compiled SHA-256 | Re-compile study via `python scripts/compile_study.py` |
| `UNREGISTERED_STRATEGY` | Strategy ID not in `STRATEGY_REGISTRY` | Register strategy class in `strategies/registry.py` |
| `CONFIG_UNKNOWN_KEYS` | YAML config contains undeclared key | Align YAML key with `CONFIG_KEYS` or `StrategyConfig` |
| `PREEXEC_AUDIT_STALE` | Code or config modified after audit seal | Re-run deterministic preflight and split pre-execution audit |
| `OOS_LOCKED` | Attempted analysis on DEV/OOS partition without authorization | STOP. Obtain OOS unlock token via `generate_oos_unlock.py` |
| `SCHEMA_MISMATCH` | Parquet columns do not match `compiled_study.json` schema | Re-verify study contracts and collector output fields |
| `MANIFEST_RESOLUTION_FAILED` | Execution manifest hash mismatch | Re-resolve manifest via `scripts/resolve_execution_manifest.py` |

---

## 8. Escalation Rule

An AI agent or developer **MAY** modify shared framework code (`backtests/nt_runtime/`, `utils/runner/`, `research/engines/`, `scripts/`) ONLY IF ALL of the following conditions are met:

1. A concrete study cannot be expressed by the existing harness capabilities.
2. The failure is **NOT** caused by:
   - Missing feature registration or tracker declaration
   - Missing strategy registration or config binding
   - Incorrect YAML syntax or unsupported CLI arguments
   - Stale audit status or missing audit seal
   - Caller misuse or improper path syntax
3. The agent explicitly documents the missing capability in `BESPOKE_JUSTIFICATION` or the study `SPEC.md`.

Otherwise, the agent **MUST** resolve the issue strictly by configuring or extending the canonical user-space layers (`study.yaml`, `features/registry.py`, `strategies/`, `tests/`).

---

## 9. Token-Efficient Agent Workflow

To maximize reasoning quality and minimize context/token consumption, agents must execute within structured, bounded sessions:

```
SESSION START
    ↓
1. Read `docs/RESEARCH_WORKFLOW.md` (or relevant section)
    ↓
2. Read study `SPEC.md` / task packet
    ↓
3. Read ONLY named canonical files (avoid broad scans)
    ↓
4. Perform ONE bounded task (e.g., implement tracker, run preflight)
    ↓
5. Write compact status JSON / Markdown artifacts
    ↓
6. Update session handoff
    ↓
END SESSION
```

### Rules of Token Discipline

- **No Repo-Wide Archaeology**: Do not run broad grep/glob searches across historical folders (`archive/`, `scratch/`, `runs/`, old result trees) unless explicitly instructed.
- **Targeted File Reads**: Use line-bounded reads (`view_file` with `StartLine`/`EndLine`) for specific symbols rather than dumping 1000-line files into chat.
- **Compact Chat Responses**: Keep responses concise. Detailed logs, failure packets, and tracebacks belong in artifact files (`audit/failure_packet.json`, `audit/pass_NN.md`), not chat text.
- **Deterministic Scripts Over Reasoning**: Use `scripts/research_preflight.py` and `scripts/sync_agents.py` to evaluate code mechanically rather than manually inspecting ASTs in LLM prompts.

---

## 10. Canonical Script & Module Reference

| Stage / Purpose | Canonical Path | Primary Class / Function | Typical Invocation Syntax | Primary Output Artifact |
|---|---|---|---|---|
| **Study Scaffolding** | `scripts/create_study.py` | `create_study()` | `python scripts/create_study.py --config study.yaml` | `studies/<id>/` tree & `SPEC.md` |
| **Study Compilation** | `scripts/compile_study.py` | `compile_study()` | `python scripts/compile_study.py --study studies/<id>` | `compiled_study.json` |
| **Fidelity Check** | `scripts/check_research_decision_fidelity.py` | `check_decision_fidelity()` | `python scripts/check_research_decision_fidelity.py --study studies/<id>` | Fidelity stdout / exit code |
| **Research Preflight** | `scripts/research_preflight.py` | `run_preflight()` | `python scripts/research_preflight.py --study studies/<id>` | `audit/preflight.json` |
| **Audit Report Filing** | `scripts/run_preexec_audits.py` | `_extract_v2_summary()` | `python scripts/run_preexec_audits.py --study studies/<id> --type causal --ingest audit/pass_01.md --author <declared_reviewer_id>` | `audit/status.json` |
| **Preexec Audit Seal** | `scripts/preexec_audit_seal.py` | `generate_preexec_audit_seal()` | `python scripts/preexec_audit_seal.py` (called via preexec parser) | `artifacts/preexec_audit_seal.json` |
| **Collector Runner** | `backtests/run_nt_study.py` | `run_collect_mode()` | `python backtests/run_nt_study.py --study studies/<id> --mode collect --stage day` | `runs/<timestamp>_collect_day/` |
| **Smoke Validation** | `scripts/validate_smoke.py` | `validate_smoke_run()` | `python scripts/validate_smoke.py --run-dir runs/...` | `validation_report.json` |
| **Standalone Backtest** | `backtests/run_backtest.py` | `run_backtest_mode()` | `python backtests/run_backtest.py --config backtests/configs/<name>.yaml` | `runs/<timestamp>_<strategy>/` |
| **Analysis Harness** | `research/analysis/` | Analysis package API | Python import (`research.analysis`) | Fit models, thresholds, reports |
| **Agent Parity Sync** | `scripts/sync_agents.py` | `main()` | `python scripts/sync_agents.py` (`--check` to verify) | `.agents/` and `.codex/` agent files |
| **Feature Registry** | `features/registry.py` | `FEATURE_REGISTRY` | Python import `from features.registry import FEATURE_REGISTRY` | Feature metadata dictionary |
| **Engine Construction** | `backtests/nt_runtime/engine_builder.py` | `build_engine()` | Python import in runtime harness | `BacktestEngine` instance |
| **Catalog Data Loading** | `utils/runner/data.py` | `CausalDataLoader.load_bars()` | Python import in runtime harness | List of NT Bar objects |

---

## 11. Study Directory & Artifact Convention

Every research study follows a standardized directory structure:

```
studies/<study_id>/
├── research_decision.yaml   # Canonical Research Decision Contract (AUTHORITATIVE)
├── study.yaml               # Machine-readable study specification
├── SPEC.md                  # Human-readable study specification (derived from research_decision.yaml)
├── compiled_study.json      # Compiled study contract (sha256 bound)
├── config/                  # Sub-component contract JSONs (feature, population, target)
│   ├── feature_contract.json
│   ├── population_contract.json
│   └── target_contract.json
├── implementation/          # Study-specific strategy or custom collectors (if bespoke)
├── tests/                   # Auto-generated & study-specific contract tests
│   └── test_study_contracts.py
├── audit/                   # Machine-parsed audit artifacts & status files
│   ├── preflight.json
│   ├── pass_01.md
│   ├── status.json          # Causal audit status
│   ├── contract_pass_01.md
│   └── contract_status.json # Contract audit status
├── artifacts/               # Sealed execution artifacts & frozen model weights
│   └── preexec_audit_seal.json
└── results/                 # Post-analysis summary reports and metrics JSONs
    └── STUDY_REPORT.md
```

### Artifact Categorization

- **Source / Config (Tracked in Git)**: `research_decision.yaml`, `study.yaml`, `SPEC.md`, `strategies/`, `features/`, `tests/`.
- **Generated Contracts (Tracked in Git)**: `compiled_study.json`, `config/*.json`.
- **Audit Evidence (Tracked in Git)**: `audit/pass_NN.md`, `audit/status.json`, `audit/contract_pass_NN.md`, `audit/contract_status.json`.
- **Run Evidence (Untracked / Gitignored)**: `runs/`, `canonical_*/`, `_work/`, `*.parquet`.
- **Model Artifacts (Untracked / Gitignored)**: `models/artifacts/*.joblib`, `models/artifacts/*.onnx`.

---

## 12. Stopping Rules

To prevent scope creep and unnecessary refactoring, strictly enforce these stopping rules:

1. **Collector Framework**: Frozen. No modifications permitted unless a demonstrated defect is identified or a new study contract requires a feature that cannot be represented.
2. **Backtest Harness**: Frozen. No modifications permitted unless an explicit execution mode or order handling semantics cannot be represented.
3. **Analysis Harness**: Frozen. Partition provenance, OOS lock enforcement, and metric computation logic are immutable.
4. **Shared Feature Infrastructure**: Add new feature definitions and stateful trackers normally in `features/registry.py` and `features/trackers/`. Do not rewrite the registry schema or lookup engine.
5. **Research Agents**: Once the assigned research question is answered and validated, produce the final study report (`STUDY_REPORT.md`) or next decision contract (`research_decision.yaml`). Do not alter an accepted study's parameters post-hoc.

---

## 13. Workflow Acceptance Test

The canonical workflow validation test verifies that an agent handles a missing feature correctly under fail-closed governance:

### Test Protocol

1. **Scenario Setup**: Introduce a study configuration (`study.yaml`) referencing a new feature `arrival_vel_45s` that is intentionally absent from `features/registry.py`.
2. **Deterministic Preflight Failure**: `python scripts/research_preflight.py --study studies/<test_study>` fails with `FEATURE_NOT_REGISTERED`.
3. **Agent Remediation Action**:
   - The agent MUST diagnose `FEATURE_NOT_REGISTERED` from `audit/failure_packet.json`.
   - The agent MUST add the canonical `FeatureDefinition` for `arrival_vel_45s` to `FEATURE_REGISTRY` in `features/registry.py`.
   - The agent MUST update or verify the tracker implementation in `features/trackers/velocity.py`.
   - The agent MUST add unit tests for `arrival_vel_45s` in `tests/test_feature_library.py`.
   - The agent MUST re-compile the study via `python scripts/compile_study.py` and re-run preflight.
4. **Success Criteria**:
   The workflow test succeeds if and only if the agent fixes the feature definition at the canonical layer (`features/registry.py`) and passes preflight WITHOUT:
   - Creating a replacement collector script
   - Creating a replacement backtest runner
   - Copying engine/catalog setup inline
   - Bypassing preflight or audit validation
   - Manually constructing custom analysis code

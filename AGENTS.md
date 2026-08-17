# NautilusTrader Development Framework - AGENTS.md

## PURPOSE

This repository follows strict methodology to ensure all backtests, studies, and models produce trustworthy, reproducible results. Any NT user should be able to clone this repo and replicate results exactly.

---

## CORE PRINCIPLES

### 1. NautilusTrader is the ONLY execution environment
- ALL signal detection happens in NT event loop
- ALL feature computation happens in NT event loop
- ALL backtesting uses NT BacktestEngine
- NO pandas for signal detection, validation, or "quick checks"
- Pandas is ONLY for:
  - Loading raw data into NT catalog
  - Post-backtest analysis of NT-generated results (use NT reports first)
  - Visualization of NT-generated results (use NT tearsheets first)

### 2. No look-ahead bias
- Indicators compute on COMPLETED bars only
- Decisions at bar N cannot use data from bar N+1
- All features must be computable in real-time

### 3. Reproducibility
- All parameters in config files (YAML)
- All random seeds fixed and documented
- All data sources versioned
- Results include exact config used

### 4. Separation of concerns
- Indicators: Reusable, strategy-agnostic
- Strategies: Config-driven, indicator-agnostic
- Backtests: Strategy-agnostic runners
- Analysis: Works on any backtest output

### 5. Factory-first study creation
- Every new study MUST be configured via `study.yaml`, scaffolded via `python scripts/create_study.py --config <study.yaml>`, and validated via `python scripts/compile_study.py`.
- Coding agents MUST NOT create study-specific implementations for behavior already representable by a canonical study type (e.g. `flip_prediction`).
- A coding agent proposing bespoke code must provide `BESPOKE_JUSTIFICATION` before implementation.

### 6. Research Decision Contract Authority & Fidelity
- Precedence: `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.
- BEFORE drafting or modifying `SPEC.md`: Create or verify `research_decision.yaml`.
- `SPEC.md` must be derived from `research_decision.yaml`. No study may compile or pass preflight unless decision-contract fidelity passes (`python scripts/check_research_decision_fidelity.py --study studies/<name>`).
- Behavioral Rule: Never improve, broaden, clean up, or make a study more statistically pure by changing a fixed baseline or adding feature discovery unless the Research Decision Contract explicitly permits it. If a design concern exists, surface it as a caveat; do not silently alter the experiment.
---

## DOCUMENTATION INDEX

Implementation detail lives in `docs/`. Do not guess — read the relevant spec
before writing code. These files are canonical; this document intentionally does
not restate them.

| Topic | Spec |
|---|---|
| End-to-end research workflow, stage gates, CLI reference, escalation rules | `docs/RESEARCH_WORKFLOW.md` |
| Wrangling, catalog build, validation, timestamp convention | `docs/DATA_CATALOG.md` |
| Runner setup, StrategyConfig, parameter sweeps, logging | `docs/BACKTEST_EXECUTION.md` |
| NT built-in reports, tearsheets, key metrics | `docs/ANALYSIS_REPORTING.md` |
| Feature collection, MFE/MAE replay, ML requirements, pitfalls | `docs/STUDY_METHODOLOGY.md` |
| Indicator and Strategy `SPEC.md` templates | `docs/TEMPLATES.md` |
| Profiling, Cython/Rust thresholds, ONNX inference | `docs/PERFORMANCE.md` |
| Feature registry contract | `features/FEATURE_REGISTRY_CONTRACT.md` |


---

## AGENT GOVERNANCE

### Audit gates (mandatory: pre-execution and completion)

For any of the following, the split audit is required **before the first study
collector, label builder, model-training script, backtest, or staged runner is
executed**. Unit tests and deterministic lint may run first so the audit has a
testable code surface. After execution, `contract-checker` verifies the
materialized deliverables; a completion causal re-audit is required only if the
audited code/configuration surface changed.

- A new strategy file or material edit to an existing one
- A new study/research script that produces results you'll act on
- Any change to data loading, feature engineering, or label construction

**The gate is split.** Two agents with disjoint scope, defined in
`docs/CAUSAL_CHECKLIST.md` § SCOPE SPLIT:

| Agent | Owns | Must not report |
|---|---|---|
| `lookahead-auditor` | A, B, C1–C3, F, G, H — causality and timestamps | deliverables, manifests, seal design, test quality |
| `contract-checker` | C4, D, E + the SPEC's Deliverables Manifest | novel causal theories |

Splitting them is deliberate. Across ~100 historical audits, ~60% of blocking
findings were completeness issues raised by the causal auditor, which has no
natural stopping point for them —
`studies/codex_5.6_short_rth_enriched_volume_level_retrain/` ran **18 passes**
and produced a 1,240-line append-only `audit.md`.

Pre-execution workflow:

1. Freeze the SPEC/config and implement the smallest testable code surface. Do
   not run collection, label construction, model fitting, backtesting, or a
   staged runner yet.
2. **Run deterministic preflight first.** `python scripts/research_preflight.py --study studies/<name>`.
   It orchestrates AST causal linting (`causal_lint.py`), artifact schema checks (`check_artifact_schema.py`),
   model/feature binding (`check_model_binding.py`), and fast causal canaries (`select_required_tests.py` -> pytest)
   deterministically and for free.
   - If preflight is `BLOCKED`, inspect `audit/failure_packet.json` and resolve all issues locally.
   - Coding agents may NOT bypass a `BLOCKED` preflight or request an audit while preflight is failing.
3. Once preflight is `CLEAR`, invoke `lookahead-auditor` on the causal contract; invoke `contract-checker`
   on the Deliverables Manifest. They are independent and may run in parallel.
4. Each writes a **new** `audit/pass_<NN>.md` plus a machine-readable
   `audit/status.json` (`contract_status.json` for the contract-checker).
   **Never append to a previous pass's report** — append-only files make the
   verdict unparseable, and a gate that greps for "critical" and "0" will pass
   on a failing report that merely contains an earlier clean summary.
5. Address every CRITICAL finding by editing the code (do not dismiss without
   explicit user approval). Address WARNINGs unless out of scope or waived.
6. Re-invoke on the same scope, **passing the previous pass's findings**. The
   auditor must adjudicate every prior finding (`FIXED` / `NOT FIXED` /
   `WITHDRAWN`) *before* raising anything new, and may raise **at most 3 new
   CRITICAL findings per pass.**
7. Repeat 5–6 until `status.json` shows `critical: 0` and either zero WARNING or
   user-acknowledged WARNING.
8. Only after both statuses are clean may the study/model execution begin. If
   code or configuration changes afterward, re-run lint and the affected audit
   before executing the changed pipeline. Before acceptance, run
   `contract-checker` against the materialized deliverables and re-run the causal
   audit if the audited code/configuration surface changed.

Gates read `audit/status.json`. Do not parse prose for a verdict.

Do not skip the audit because the change "looks small". Look-ahead bugs are most often introduced by small edits to previously-clean code.

### Commit protocol (mandatory)

Every phase gate ends with a commit. A study that runs for days without commits
cannot be bisected when a defect is found late, and audit reports lose their
anchor to the code they audited.

**Commit at these points, and only these:**

| Trigger | Message prefix | Must include |
|---|---|---|
| SPEC frozen (before implementation) | `spec(<study>):` | `SPEC.md`, `config/*.yaml` |
| Phase gate passed (`status.json` clean) | `phase(<study>): <phase> <verdict>` | code + `audit/pass_NN.md` + `audit/status.json` |
| Study accepted | `study(<study>): ACCEPTED` | `BUILD_REPORT.md` / `STUDY_REPORT.md` + manifests |
| Tooling / governance change | `chore:` or `docs:` | — |

Rules:

1. **Never commit on `main`.** Branch first: `study/<study_name>` or
   `chore/<topic>`. Open a PR when the study is accepted.
2. **The audit artifact commits with the code it audited.** A `pass_NN.md`
   committed separately from its code is unanchored — the scope hash it records
   must correspond to the tree in that same commit.
3. **Never commit generated data.** `canonical_*/`, `_work/`, `results/*.parquet`,
   `artifacts/**/model.joblib` stay untracked. Commit the *manifests* and hashes
   that identify them, not the bytes.
4. Run `python scripts/causal_lint.py` and `python scripts/sync_agents.py --check`
   before committing. Both must exit 0.
5. Do not use `--no-verify` or skip hooks.

### Agent definition parity (all three harnesses)

`.claude/agents/*.md` is the **canonical** source. `.agents/agents_staging/*.md`
(Antigravity) and `.codex/agents/*.toml` (Codex) are **generated** — do not edit
them by hand.

```bash
python scripts/sync_agents.py           # regenerate from canonical
python scripts/sync_agents.py --check   # verify in sync
```

This exists because the harnesses silently drifted: the Codex auditor was
missing 14 checklist rules including `C4` and `D4`, the #2 and #4 most frequent
finding categories in the repository. An audit that passed under Codex would
fail under Claude, causing rework on every harness switch. Agent definitions
must **reference** `docs/CAUSAL_CHECKLIST.md`, never restate rules inline;
`sync_agents.py` warns when a definition inlines rule text.

### Standing Authorization for Named Mandatory Agent Gates

Named mandatory gates in this repository constitute standing user authorization for the main orchestrator to invoke the specifically named agent when that gate condition is reached.

This authorization applies only to:

- `repo-scout` / Codex `repo_scout` where the selected risk tier requires it
- `contract-checker` / Codex `contract_checker` where the selected risk tier requires it
- `results-triager` / Codex `results_triager` for exact approved test commands
- `lookahead-auditor` / Codex `lookahead_auditor` at mandatory causal or look-ahead audit gates

The invocation must remain limited to the scope of the named gate.

This standing authorization does not permit:

- discretionary agent use
- unnamed or general-purpose agents
- broad parallel fan-out
- nested delegation
- workers spawning subagents
- expanding the audit into implementation work
- code modifications by an audit-only agent

Session-level instructions prohibiting discretionary agent spawning remain in force. They do not prevent execution of a specifically named mandatory repository gate covered by this standing authorization.

If a mandatory gate and a session-level restriction appear to conflict, the orchestrator should:

1. invoke only the specifically named mandatory gate;
2. keep the scope limited to the gate’s defined responsibilities;
3. avoid all additional agent delegation; and
4. record the invocation and resulting verdict in the study artifacts.

Passing criteria remain governed by the applicable frozen contract or SPEC. Standing authorization to invoke an auditor does not relax the audit acceptance standard. Do not mark the work finalized unless the audit satisfies the acceptance gate defined by the applicable frozen SPEC. At minimum, any CRITICAL finding blocks finalization. Any WARNING must either be remediated or explicitly adjudicated according to the SPEC; do not silently treat an unresolved WARNING as cleared.

**Immediate component audit for high-risk logic.** The universal pre-execution
gate above applies to every study and model-training pipeline. For the following
components, invoke the harness-specific lookahead auditor immediately after that
component is implemented, before any dependent code is added or any execution
occurs:
- state-smoothing / hysteresis state machines
- matched-donor or nearest-neighbor selection logic (placebos, controls)
- any shuffle/permutation/circular-shift control
- stop/exit fill-timing mechanics (new or reused from another study)

If the component reuses another study's execution stack "verbatim," audit it anyway — a bug inherited from upstream is still a bug in your results. (See `studies/rl_regime_feasibility/contextual_runner_exit_v3/`: a completion-gate-only audit found 4 CRITICAL issues — a phantom stop-fill price inherited from a reused sim stack, a matched-placebo geometry mismatch, and two matched-donor/shuffle controls that leaked outcome-correlated or future information — only after the entire pipeline had already been run once and was partway through a second run.)

---

## DIRECTORY STRUCTURE

```
{repo_root}/
│
├── AGENTS.md                    # Framework rules & governance
├── CLAUDE.md                    # Core invariants & quick reference
│
├── docs/                        # Operational specs & workflow manuals
│   ├── RESEARCH_WORKFLOW.md     # Primary end-to-end research workflow manual
│   ├── CAUSAL_CHECKLIST.md      # Disjoint ruleset for causal & contract auditors
│   └── DATA_CATALOG.md          # Catalog wrangling & timestamp conventions
│
├── backtests/                   # Standalone & generic study backtest execution
│   ├── nt_runtime/              # Canonical NT engine builder & modes
│   ├── run_backtest.py          # Supported standalone CLI entrypoint
│   ├── run_nt_study.py          # Supported declarative study collection CLI
│   └── configs/                 # Config YAMLs for standalone runs
│
├── features/                    # Central feature registry & stateful trackers
│   ├── registry.py              # Canonical feature definitions & metadata
│   ├── FEATURE_REGISTRY_CONTRACT.md
│   └── trackers/                # Real-time stateful feature tracker implementations
│
├── indicators/                  # Reusable indicator definitions & registry
│   └── registry.py
│
├── strategies/                  # Reusable NT strategy implementations & registry
│   └── registry.py
│
├── research/                    # Analysis schemas, contract compilers, engines & harness
│   ├── analysis/                # Canonical validated analysis package (on analysis-harness branch if unmerged)
│   ├── schemas/study_spec.py    # Authoritative StudySpec pydantic model
│   └── engines/                 # Low-level feature binding, target & lineage engines
│
├── studies/                     # Declarative research studies
│   └── {study_name}/
│       ├── research_decision.yaml # Authoritative decision contract
│       ├── study.yaml           # Machine-readable spec
│       ├── SPEC.md              # Rendered specification
│       ├── compiled_study.json  # Compiled sha256-bound contract
│       ├── audit/               # Audit pass reports & status.json
│       ├── artifacts/           # Sealed execution manifests & frozen weights
│       └── results/             # Study reports & analysis artifacts
│
├── models/                      # Trained models & frozen artifacts
│   └── artifacts/               # Joblib / ONNX weights
│
└── scripts/                     # Preflight, audit, sync, and orchestration scripts
    ├── create_study.py          # Scaffold new study from study.yaml
    ├── compile_study.py         # Compile & validate study contracts
    ├── research_preflight.py    # Deterministic AST lint, schema & test preflight
    ├── run_preexec_audits.py    # Deterministic audit provenance & status parser
    ├── preexec_audit_seal.py    # Cryptographic pre-execution seal manager
    └── sync_agents.py           # Cross-harness agent definition generator
```
---

## TIMEZONE & TIMESTAMP CONVENTION

All timestamps in Central Time (America/Chicago) for display/analysis.
Internal NT uses UTC. Convert for human-readable output.

```python
import pytz
CT = pytz.timezone('America/Chicago')

def to_ct(utc_timestamp):
    return utc_timestamp.astimezone(CT)
```

RTH (Regular Trading Hours): 08:30 CT - 15:15 CT

### Canonical Bar-Availability & Timestamp Contract
- **Raw Databento OHLCV:** OPEN-stamped (`ts_event`). Complete OHLCV becomes usable only at interval close.
- **Offline Research:** Normalize derived bars to CLOSE-stamped indices (`label='right', closed='left'`).
- **NautilusTrader Catalog:** Preserve open-stamped `ts_event` and set `ts_init = ts_event + bar_duration_ns` (1s: +1s, 1m: +60s, 3m: +180s, 5m: +300s) so the NT event loop dispatches completed bars at interval close.

---

## VERSION CONTROL

### What to commit
- All code (strategies, indicators, scripts)
- All configs (YAML)
- All SPEC.md files
- requirements.txt / pyproject.toml
- This AGENTS.md

### What to .gitignore
```
data/raw/           # Large data files
data/catalog/       # Generated
backtests/results/  # Generated (archive important ones)
models/artifacts/   # Large model files
logs/               # Generated
__pycache__/
*.pyc
.env
```

### Results archiving
For significant results, create a tagged release with:
- Config used
- Summary metrics
- Link to full results (external storage if large)
---

## LESSONS LEARNED

1. **Pandas validation is invalid** - Breakdown strategy showed 63% WR in pandas, 11% in NT due to look-ahead
2. **Timestamp handling is critical** - Databento OPEN timestamps require ts_init = ts_event + bar_duration_ns in NT catalog to prevent look-ahead bias
3. **MFE/MAE from pandas may be inflated** - Only trust NT backtest results
4. **CTB checked at touch time, not breach time** - Order of operations matters
5. **Regime change bar can be breach bar** - Don't return early on regime change
6. **Touch counting resets only on regime change** - Not on new breaches
7. **Collector MFE/MAE blind spot** - 1s bars process before parent 1m bar in NT. Swing breakout collector showed +$70/trade but NT backtest showed -$3/trade. Root cause: 44% of trades hit SL in the first 60s that were invisible to the collector. Trades surviving 60s matched collector exactly (62% WR, +$63/trade). Fix: buffer 1s bars and replay from fill time.
8. **Recursive deletion escaped a disposable workspace and destroyed real data** - a cleanup of what was believed to be a throwaway worktree followed a link out of it. On Windows this is easy to miss: junctions and other reparse points are not symlinks and do not look like them.

---

## DESTRUCTIVE FILESYSTEM SAFETY (mandatory)

**Never recursively delete, clean up, or remove a worktree/path without first checking
every descendant for symlinks, junctions, mount points, or Windows reparse points that
escape the disposable workspace.**

Recursive deletion must **fail closed**: if any descendant resolves outside the intended
disposable root, abort the whole operation rather than deleting "the safe part". A partial
delete of a tree you did not fully understand is how the incident above happened.

Concretely:

- **Do not use `rm -rf` against repo or worktree trees containing external data
  junctions.** `data/catalog/` in particular may be a link to storage that lives outside
  the repository.
- Resolve before you delete. A path that *looks* inside the root is not necessarily
  inside it — `Path.resolve()` is what decides, not the string.
- On Windows, check for reparse points, not just symlinks. `os.path.islink()` returns
  False for a directory junction.
- `scripts/safe_cleanup.py::assert_safe_to_delete` implements this check. Use it, or
  replicate it, before any recursive removal of a directory you did not create in this
  session.

This is a safety rule, not a framework. It is deliberately one function and one
prohibition.

<!-- BEGIN SUBAGENT ROUTING -->
## Subagent Routing & Lean Workflow

Keep architecture, causal interpretation, integration, and final approval in the main session. Claude agent names are hyphenated. Codex `name` / `agent_type` values use underscores; filenames may remain hyphenated for easy cross-harness comparison. Use the exact harness-specific identifier below when invoking an agent.

### Roster

| Agent | Codex `agent_type` | Role | Model tier | Output cap | Available in |
|---|---|---|---|---|---|
| `repo-scout` | `repo_scout` | Locate files, trace execution paths | Haiku / low | 700w — paths, symbols, line ranges only | Claude, Codex |
| `contract-checker` | `contract_checker` | Compare code/tests against explicit specs | Sonnet / medium | 1,000w — compliance table + findings only | Claude, Codex |
| `results-triager` | `results_triager` | Run exact approved pytest commands | Haiku / low | 500w — failures, root-cause tracebacks, commands | Claude, Codex |
| `lookahead-auditor` | `lookahead_auditor` | Internal causal / look-ahead review (self-attested) | Sonnet / high | 1,500w — complete Markdown report, parent persists | Claude, Codex |
| `Explore` | — | Broad fan-out location sweep; prefer `repo-scout` | Haiku / low | 700w — paths and symbols only | **Claude only** |
| `implementation-worker` | `implementation_worker` | Implement one frozen, bounded task packet | Sonnet-class / medium | — | **Codex only** |

Tier rationale and the no-escalate-for-length rule: `CLAUDE.md` § LEAN WORKFLOW
(*Model tiering*). Exact model ids live in the `.claude/agents/*.md` frontmatter
(canonical) and in `CODEX_META` in `scripts/sync_agents.py` (per-harness). The
`Explore` definition exists only to pin the model — the built-in agent inherits
the orchestrator's model, which is Opus.

### Risk tiers

Not every task needs the full ceremony.

* **Tier 1 — small diagnostic / local fix:** main session → deterministic tests → local smoke. No planning agent or auditor unless the change touches core causal or timing logic.
* **Tier 2 — normal research study:** planning → freeze SPEC → main-session implementation + tests → split pre-execution audit → staged runner → completion contract check; causal re-audit only if the audited surface changes.
* **Tier 3 — model freeze / deployment:** `repo-scout` → freeze SPEC → main-session implementation + tests → split pre-execution audit → staged runner → completion contract check; causal re-audit only if the audited surface changes.

### Coordination rules

* Spawn `repo-scout` and `contract-checker` (Codex: `repo_scout`, `contract_checker`) in parallel only when their assignments are independent; wait for both before freezing the task packet.
* Never run multiple writing agents in the same worktree concurrently.
* Do not duplicate searches or tests a subagent already completed.
* Subagent prompts must be self-contained — child agents do not inherit the parent conversation.

### Diff-first auditing

* Auditors use the contextual diff (`git diff -U20`) as the primary review surface.
* Open full files only to resolve state flow, causality, base-class dependencies, or import behavior.
* Do not reopen unchanged files to repeat discovery — only when full context is needed to resolve a live causal, structural, or audit question.

### Deterministic process control

* Never use an LLM or agent for process monitoring or status reporting.
* Use `scripts/run_bounded_study.py` to enforce time limits, log capture, CPU/memory limits, and stale-progress detection, and to emit a status JSON card.
* The main session reviews the compact JSON status card, not raw output logs.
<!-- END SUBAGENT ROUTING -->

## Central Feature System

See `CLAUDE.md` § Central Feature System (canonical). In short: check
`features/FEATURE_REGISTRY_CONTRACT.md` and `features/registry.py` before
creating, modifying, or locally reimplementing any feature.

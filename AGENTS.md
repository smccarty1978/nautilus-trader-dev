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
---

## DOCUMENTATION INDEX

Implementation detail lives in `docs/`. Do not guess — read the relevant spec
before writing code. These files are canonical; this document intentionally does
not restate them.

| Topic | Spec |
|---|---|
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
2. **Run the free lint first.** `python scripts/causal_lint.py --study studies/<name> --json studies/<name>/audit/lint.json`.
   It catches the known-recurring defect classes (H4 trigger-price fills, session
   gates on `ts_event`, `center=True`, `.shift(-N)`, `bfill`, `merge_asof`
   without `direction=`, non-`*.v.0` symbols) deterministically and for free.
   Fix everything it reports before spending an agent turn.
3. Invoke `lookahead-auditor` on the causal contract; invoke `contract-checker`
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
├── AGENTS.md                    # This file - framework rules
│
├── data/
│   ├── raw/                     # Raw parquet from Databento
│   └── catalog/                 # NT catalog (generated)
│
├── indicators/
│   ├── __init__.py
│   ├── {indicator_name}/
│   │   ├── indicator.py         # NT Indicator class
│   │   ├── config.py            # IndicatorConfig if needed
│   │   └── SPEC.md              # Indicator specification
│   └── registry.py              # Indicator registry
│
├── strategies/
│   ├── __init__.py
│   ├── {strategy_name}/
│   │   ├── strategy.py          # NT Strategy class
│   │   ├── config.py            # StrategyConfig dataclass
│   │   └── SPEC.md              # Strategy specification
│   └── registry.py              # Strategy registry
│
├── backtests/
│   ├── engine.py                # Reusable backtest runner
│   ├── configs/
│   │   └── {strategy}_{version}.yaml
│   └── results/
│       └── {timestamp}_{strategy}_{config}/
│           ├── config.yaml      # Exact config used
│           ├── trades.parquet   # All trades
│           ├── metrics.yaml     # Summary metrics
│           ├── equity.parquet   # Equity curve
│           └── tearsheet.html   # Interactive report
│
├── studies/
│   ├── {study_name}/
│   │   ├── SPEC.md              # Study design document
│   │   ├── collect.py           # Data collection (IN NT)
│   │   ├── analyze.py           # Analysis (on NT output)
│   │   └── results/
│
├── models/
│   ├── {model_name}/
│   │   ├── SPEC.md              # Model specification
│   │   ├── train.py             # Training script
│   │   ├── config.yaml          # Hyperparameters
│   │   └── artifacts/           # Saved models
│
├── logs/                        # Log files (generated)
│
└── scripts/
    ├── download_data.py         # Databento download
    ├── build_catalog.py         # Build NT catalog
    └── validate_data.py         # Data validation
```
---

## TIMEZONE CONVENTION

All timestamps in Central Time (America/Chicago) for display/analysis.
Internal NT uses UTC. Convert for human-readable output.

```python
import pytz
CT = pytz.timezone('America/Chicago')

def to_ct(utc_timestamp):
    return utc_timestamp.astimezone(CT)
```

RTH (Regular Trading Hours): 8:30 CT - 15:00 CT

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
2. **Timestamp handling is critical** - Databento OPEN timestamps caused massive look-ahead bias
3. **MFE/MAE from pandas may be inflated** - Only trust NT backtest results
4. **CTB checked at touch time, not breach time** - Order of operations matters
5. **Regime change bar can be breach bar** - Don't return early on regime change
6. **Touch counting resets only on regime change** - Not on new breaches
7. **Collector MFE/MAE blind spot** - 1s bars process before parent 1m bar in NT. Swing breakout collector showed +$70/trade but NT backtest showed -$3/trade. Root cause: 44% of trades hit SL in the first 60s that were invisible to the collector. Trades surviving 60s matched collector exactly (62% WR, +$63/trade). Fix: buffer 1s bars and replay from fill time.

---

<!-- BEGIN SUBAGENT ROUTING -->
## Subagent Routing & Lean Workflow

Keep architecture, causal interpretation, integration, and final approval in the main session. Claude agent names are hyphenated. Codex `name` / `agent_type` values use underscores; filenames may remain hyphenated for easy cross-harness comparison. Use the exact harness-specific identifier below when invoking an agent.

### Roster

| Agent | Codex `agent_type` | Role | Output cap | Available in |
|---|---|---|---|---|
| `repo-scout` | `repo_scout` | Locate files, trace execution paths | 700w — paths, symbols, line ranges only | Claude, Codex |
| `contract-checker` | `contract_checker` | Compare code/tests against explicit specs | 1,000w — compliance table + findings only | Claude, Codex |
| `results-triager` | `results_triager` | Run exact approved pytest commands | 500w — failures, root-cause tracebacks, commands | Claude, Codex |
| `lookahead-auditor` | `lookahead_auditor` | Independent causal / look-ahead audit | 1,500w — complete Markdown report, parent persists | Claude, Codex |
| `implementation-worker` | `implementation_worker` | Implement one frozen, bounded task packet | — | **Codex only** |

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

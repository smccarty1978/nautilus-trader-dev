# Document Map

Every Markdown document in this repository, classified. Written 2026-08-25.

**Read order for a new agent:** `CLAUDE.md` or `CODEX.md` → `docs/RESEARCH_WORKFLOW.md` →
the specific deeper doc you need.

## Classes

| Class | Meaning |
|---|---|
| **AUTHORITATIVE** | Describes the current system. If something contradicts it, the other thing is wrong. |
| **CURRENT** | Accurate supporting reference for a narrower area. |
| **DESIGN CONTRACT** | A frozen contract that live code cites by section number. Do not edit casually; do not delete. |
| **HISTORICAL** | A record of what was done or proposed at a point in time. Not an instruction. May contradict the current system. |
| **STALE** | Materially conflicts with the current system and is superseded. Marked with a banner. |

Historical and stale documents carry a `> **[HISTORICAL]**` / `> **[STALE]**` banner at the
top. They are kept because they hold reasoning that is still worth reading, and because
some are cited from git history and audit trails. **They are never a source of instructions.**

---

## AUTHORITATIVE

| Document | Scope |
|---|---|
| `docs/RESEARCH_WORKFLOW.md` | The end-to-end research system: architecture, Feature V2, lifecycle, collector, forward outcomes, scripts, autonomy, data safety |
| `AGENTS.md` | Shared cross-harness agent operating core |
| `CLAUDE.md` | Claude-specific operating manual |
| `CODEX.md` | Codex-specific operating manual |
| `docs/CAUSAL_CHECKLIST.md` | Causal + contract audit ruleset A1–H4; single source of truth for all three harnesses |
| `features/FEATURE_REGISTRY_CONTRACT.md` | Feature lifecycle, canonical identity, promotion evidence |
| `features/CANONICAL_FEATURE_REFERENCE.yaml` | Generated canonical feature vocabulary (the active V2 bundle) |
| `.claude/agents/*.md` | Canonical subagent definitions (Codex/Antigravity are generated from these) |
| `docs/SUBAGENT_ROSTER.md` | The subagent roster and why it is this set — including why certain roles deliberately do not exist |
| `docs/WORKFLOW_REFERENCE_FACTS.md` | Current-state numbers, closure membership, hashing convention, measured benchmarks. Goes stale by design — each entry names the command that re-derives it |

## CURRENT

| Document | Scope |
|---|---|
| `docs/DATA_CATALOG.md` | Catalog wrangling, building, validation |
| `docs/BACKTEST_EXECUTION.md` | Backtest runner, sweeps, YAML configs |
| `docs/STUDY_METHODOLOGY.md` | Feature collection, MFE/MAE replay pattern |
| `docs/TEMPLATES.md` | SPEC templates, Deliverables Manifest |
| `docs/ANALYSIS_REPORTING.md` | NT reports, tearsheets |
| `docs/PERFORMANCE.md` | Profiling, ONNX inference |
| `docs/ERROR_REGISTRY.md` | Error code registry |
| `docs/DOCUMENT_MAP.md` | This file |
| `docs/RESEARCH_STUDY_BLUEPRINT.md` | Researcher-facing implementation map of the lifecycle in §1 of `docs/RESEARCH_WORKFLOW.md` — exact paths/functions, a worked study example, agent-role and CLI entry-point maps, StudySpec schema-gap inventory, and the novelty routing matrix. Defers to `docs/RESEARCH_WORKFLOW.md` on any conflict |
| `docs/templates/RESEARCH_STUDY_REQUEST_TEMPLATE.md` | Fill-in research request form + agent intake result block, used at STEP 0-2 of `docs/RESEARCH_STUDY_BLUEPRINT.md` §6 |
| `docs/BACKTEST_DATA_LOGGING.md` | Logging conventions that make outputs visualizable |
| `docs/VISUALIZER_EXTENSIONS.md` | How to add an overlay to the TradingView visualizer |

## DESIGN CONTRACT (cited by live code — keep)

| Document | Cited by |
|---|---|
| `ANALYSIS_HARNESS_A0_CONTRACT.md` | `research/analysis/__init__.py`, `research/analysis/errors.py` §7, `scripts/tests/test_analysis_reproducibility.py` §6 |
| `BACKTEST_HARNESS_B0_BOUNDARY.md` | `backtests/nt_runtime/engine_builder.py` §6.3 |
| `ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md` | `research_workflow/readiness.py` §8, `scripts/tests/test_readiness.py` — the R1–R10 design |

## STALE — superseded, banner applied

| Document | Superseded by | Why |
|---|---|---|
| `features/FEATURES.md` | `features/CANONICAL_FEATURE_REFERENCE.yaml` | A Feature System V1 catalogue of physical names (`ema_21_slope`, `arrival_vel_30s`). Those are instance aliases, not canonical identities |
| `docs/INFRASTRUCTURE_FREEZE.md` | `docs/RESEARCH_WORKFLOW.md` §1, §11 | Freezes paths that have moved (`scripts/study_spec.py`, `backtests/nt_runtime/output_manager.py` is now a shim) |
| `archive/docs/ML_Research_Workflow_Current_State_and_Redesign.md` | `docs/RESEARCH_WORKFLOW.md` | Pre-migration state assessment and redesign proposal |
| `archive/docs/ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC.md` | `..._Phase1_FINAL.md` | Superseded RFC draft |
| `archive/docs/ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC_v2.md` | `..._Phase1_FINAL.md` | Superseded RFC draft |
| `archive/docs/ml_trend_analysis_workflow_v2_spec.md` | `..._Phase1_FINAL.md` | Superseded RFC draft |
| `archive/docs/NautilusTrader_AI_Workflow_Reference.md` | `docs/RESEARCH_WORKFLOW.md` | A parallel workflow reference; describes the pre-V2 feature system and pre-`research_workflow` layout |
| `archive/docs/PROPOSED_COLLECTION_TO_ANALYSIS_WORKFLOW.md` | `docs/RESEARCH_WORKFLOW.md` §3 | A proposal that was implemented differently |
| `archive/docs/RESEARCH_AGENT_WORKFLOW_PLAYBOOK.md` | `AGENTS.md`, `CLAUDE.md`, `CODEX.md` | A second agent operating manual |
| `archive/docs/RESEARCH_PARQUET_PLATFORM_BLUEPRINT.md` | `docs/RESEARCH_WORKFLOW.md` §15 | Blueprint for a storage platform superseded by `research/analysis/` |
| `archive/docs/RESEARCH_PARQUET_WORKFLOW_README.md` | `docs/RESEARCH_WORKFLOW.md` §15 | As above |
| `archive/docs/REPO_ANALYSIS.md` | `docs/RESEARCH_WORKFLOW.md` §1 | Point-in-time repository analysis, pre-consolidation |
| `archive/docs/PROJECT_CONTINUATION_BACKTEST_ANALYSIS_ROADMAP.md` | `docs/RESEARCH_WORKFLOW.md` §14 | Superseded roadmap |
| `archive/docs/STUDIES.md` | `studies/` | A one-entry study register that was never maintained |

## HISTORICAL — records, not instructions

| Document | What it records |
|---|---|
| `archive/docs/WORKFLOW_HARDENING_REMEDIATION_REPORT.md` | Workflow hardening remediation |
| `archive/docs/WORKFLOW_HARDENING_FINAL_REMEDIATION.md` | " |
| `archive/docs/WORKFLOW_HARDENING_FINAL_RED_TEAM.md` | Red-team findings against the hardened workflow |
| `archive/docs/WORKFLOW_HARDENING_LAST_FIX_REPORT.md` | " |
| `archive/docs/ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md` | Build report for `research/analysis/` |
| `archive/docs/BACKTEST_HARNESS_IMPLEMENTATION_REPORT.md` | Build report for the backtest harness |
| `archive/docs/BACKTEST_HARNESS_REMEDIATION_REPORT.md` | " |
| `archive/docs/NT_RESEARCH_FLOW_INDEPENDENT_AUDIT_BRIEF.md` | An independent audit brief |
| `archive/docs/BASELINE_CAPTURE_RERUN_PLAN.md` | A one-off rerun plan |
| `archive/docs/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC.md` | Superseded spec draft |
| `archive/docs/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_REVISED.md` | Superseded spec draft |
| `studies/full_trade_path_builder/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_FINAL.md` | Spec for `studies/full_trade_path_builder` |
| `archive/docs/audit.md`, `archive/docs/audit_5s_scalps.md`, `archive/docs/audit_keltner.md`, `archive/docs/audit_stall_parity.md` | Individual historical audits |
| `.claude/scratch/*.md` | Session scratch |

## Duplicated agent workflow docs

`.claude/AGENT_WORKFLOW.md`, `.agents/AGENT_WORKFLOW.md` and `.codex/AGENT_WORKFLOW.md`
were three hand-maintained near-copies of the same content. They are now thin harness-launch
notes pointing at `AGENTS.md` and `docs/RESEARCH_WORKFLOW.md`. Do not re-expand them.

## Per-study documents

`studies/<id>/SPEC.md`, `research_decision.yaml`, `audit/*.md`, `results/*.md`, and
`CLOSURE.md` (present only on a closed study — its terminal record) are
**authoritative for that study** and historical for everything else. A finding in one
study's report is not a repository rule. Repository rules live in
`docs/RESEARCH_WORKFLOW.md`. Cross-study framework defects a study surfaces are lifted
into `docs/WORKFLOW_REFERENCE_FACTS.md` → "Known defects".

## Rules for adding a document

1. If it describes how the repository works, it belongs **in** `docs/RESEARCH_WORKFLOW.md`,
   not beside it.
2. If it is a point-in-time report, name it as one and expect it to become HISTORICAL.
3. Do not create a second workflow manual. That is what produced this table.
4. Add new documents to this map in the same change.

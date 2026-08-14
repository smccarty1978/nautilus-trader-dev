# NautilusTrader Development Framework

## CORE INVARIANTS (NEVER VIOLATE)
1. **NT is the ONLY execution environment.** NO pandas for signal detection, validation, or backtesting. Pandas is strictly for loading raw data and post-analysis of NT outputs.
2. **No Look-Ahead Bias.** Indicators compute on COMPLETED bars only.
3. **Timestamp Convention.** Databento timestamps at OPEN. You MUST apply `ts_init_delta` when wrangling (e.g., `60_000_000_000` for 1m bars). 1s bars need no adjustment.
4. **MFE/MAE Blind Spot.** 1s bars process before their parent 1m bar in NT. To avoid missing the first minute of price action, you MUST buffer recent 1s bars and replay them retroactively from fill time when a signal triggers.
5. **Mandatory Pre-Execution Audit Gate.** After a study/model pipeline is implemented and unit-tested, but before its first collection, label-build, training, backtest, or staged-runner execution, run `scripts/causal_lint.py`, then invoke `lookahead-auditor` (causality) and `contract-checker` (deliverables). Clear all CRITICAL findings before execution. Before acceptance, re-run `contract-checker` on materialized outputs and re-run causality only when the audited surface changes; gates read `audit/status.json`, never prose.

## LEAN WORKFLOW (token discipline)
- **Cheapest thing first.** `python scripts/causal_lint.py --study studies/<name>` before any agent turn. It catches the repeat offenders (H4 trigger-price fills, `ts_event` session gates, `center=True`, `.shift(-N)`, `bfill`, bare `merge_asof`, non-`*.v.0` symbols) for zero tokens.
- **Split audit gate.** `lookahead-auditor` = causality only (A, B, C1–C3, F, G, H). `contract-checker` = deliverables, seals, C4/D/E. Scope defined in `docs/CAUSAL_CHECKLIST.md`. Neither may report the other's category — that boundary is what stops multi-pass loops.
- **Bounded re-audits.** Pass 2+ must adjudicate all prior findings before raising new ones, max 3 new CRITICALs per pass. New file per pass (`audit/pass_NN.md`), never append.
- **Freeze deliverables up front.** Every study SPEC needs the Deliverables Manifest and Domain/Completeness sections from `docs/TEMPLATES.md`. An auditor cannot verify a deliverable set that was never written down — it invents one finding at a time instead.
- **Agent defs are generated.** Edit `.claude/agents/*.md` only; run `python scripts/sync_agents.py` to propagate to Codex and Antigravity.
- **Commit at every phase gate.** Branch (`study/<name>` or `chore/<topic>`) — never commit on `main`. Commit code together with the `audit/pass_NN.md` + `status.json` that audited it, so the scope hash matches the tree. Never commit generated data (`canonical_*/`, `_work/`, `*.parquet`, `model.joblib`) — commit the manifests instead. Full protocol: `AGENTS.md` § Commit protocol.
- **Risk tiers.** Tier 1 (small fix / diagnostic): main session + deterministic tests, no agents. Tier 2 (research study): plan → implement/tests → split pre-execution audit → staged runner. Tier 3 (model freeze / deploy): add `repo-scout`, then implement/tests → split pre-execution audit → staged runner.
- **Diff-first.** Review `git diff -U20` as the primary surface. Open full files only to resolve causality, state flow, base classes, or imports — never to repeat discovery already done.
- **No agents for process monitoring.** Use `scripts/run_bounded_study.py` and read its JSON status card, not raw logs.
- **Subagent output caps.** `repo-scout` 700w (paths/symbols only) · `contract-checker` 1,000w (compliance table) · `results-triager` 500w (failures + root cause) · `lookahead-auditor` 1,500w (findings by severity).
- **Standing authorization.** The named mandatory gates above may be invoked without asking, scoped strictly to the gate. No discretionary, general-purpose, nested, or fan-out agent use. Full text: `AGENTS.md` § Standing Authorization.

## DOCUMENTATION INDEX
Do not guess implementation details. Use your `Read` tool to read the relevant spec before writing code:

- **Catalog & Data:** `docs/DATA_CATALOG.md` (Wrangling, building, validation)
- **Backtest & Config:** `docs/BACKTEST_EXECUTION.md` (Runner setup, parameter sweeps, yaml configs)
- **Reporting & Tearsheets:** `docs/ANALYSIS_REPORTING.md` (NT built-in reports, TearsheetConfigs)
- **Studies & ML Data:** `docs/STUDY_METHODOLOGY.md` (Feature collection, MFE/MAE replay pattern)
- **Templates:** `docs/TEMPLATES.md` (Indicator and Strategy SPEC.md templates)
- **Optimization:** `docs/PERFORMANCE.md` (Profiling, ONNX ML inference)

<!-- BEGIN CENTRAL FEATURE SYSTEM -->
## Central Feature System

Before creating, modifying, or locally reimplementing a feature:

1. Read `features/FEATURE_REGISTRY_CONTRACT.md`.
2. Inspect `features/registry.py` for the canonical name, implementation,
   lifecycle, aliases, and verification status.
3. Reuse a verified registered feature when available.
4. Do not add a study-local duplicate without a documented exemption.
5. A central implementation defines how a feature is calculated; the
   study contract must still define when it is updated and snapped.
6. New or changed features require registry metadata, focused tests,
   provenance review, and parity evidence where applicable.
<!-- END CENTRAL FEATURE SYSTEM -->


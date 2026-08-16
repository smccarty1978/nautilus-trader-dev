# NautilusTrader Development Framework

## CORE INVARIANTS (NEVER VIOLATE)
1. **NT is the ONLY execution environment.** NO pandas for signal detection, validation, or backtesting. Pandas is strictly for loading raw data and post-analysis of NT outputs.
2. **No Look-Ahead Bias.** Indicators compute on COMPLETED bars only.
3. **Timestamp Convention.** Raw Databento OHLCV bars are OPEN-stamped. Offline research normalizes derived bars to CLOSE-stamped indices (`label='right', closed='left'`). NautilusTrader catalogs preserve open-stamped `ts_event` and set `ts_init = ts_event + bar_duration_ns` (1s: +1s, 1m: +60s, 3m: +180s, 5m: +300s) so the NT event loop dispatches completed bars at interval close.
4. **MFE/MAE Blind Spot.** 1s bars process before their parent 1m bar in NT. To avoid missing the first minute of price action, you MUST buffer recent 1s bars and replay them retroactively from fill time when a signal triggers.
5. **Mandatory Preflight & Pre-Execution Audit Gate.** After a study/model pipeline is implemented and unit-tested, but before its first collection, label-build, training, backtest, or staged-runner execution:
   - Run `python scripts/research_preflight.py --study studies/<name>`. Preflight must be `CLEAR` (0 CRITICAL, exit code 0). Coding agents may NOT bypass a `BLOCKED` preflight.
   - If preflight is `BLOCKED`, inspect `audit/failure_packet.json` and fix locally before requesting an audit.
   - Only after preflight is `CLEAR`, invoke `lookahead-auditor` (causality) and `contract-checker` (deliverables). Clear all CRITICAL findings before execution. Before acceptance, re-run `contract-checker` on materialized outputs and re-run causality only when the audited surface changes; gates read `audit/status.json`, never prose.
6. **Factory-First Study Creation.** Every new study MUST be configured via `study.yaml`, scaffolded via `python scripts/create_study.py --config <study.yaml>`, and validated via `python scripts/compile_study.py`. Coding agents MUST NOT create study-specific implementations for behavior already representable by a canonical study type (e.g. `flip_prediction`). A coding agent proposing bespoke code must provide `BESPOKE_JUSTIFICATION` before implementation.
7. **Research Decision Contract Authority & Fidelity.**
   - Hierarchy: `research_decision.yaml > SPEC.md > study.yaml > compiled_study.json > code`.
   - BEFORE drafting or modifying `SPEC.md`: Create or verify `research_decision.yaml`. `SPEC.md` must be derived from `research_decision.yaml`. No study may compile or pass preflight unless decision-contract fidelity passes (`python scripts/check_research_decision_fidelity.py --study studies/<name>`).
   - Behavioral Rule: Never improve, broaden, clean up, or make a study more statistically pure by changing a fixed baseline or adding feature discovery unless the Research Decision Contract explicitly permits it. If a design concern exists, surface it as a caveat; do not silently alter the experiment.

## LEAN WORKFLOW (token discipline)
- **Deterministic Preflight First.** `python scripts/research_preflight.py --study studies/<name>` before any agent turn. It orchestrates AST causal linting, schema validation, model binding, and fast causal canaries for zero LLM tokens.
- **Worker Subagent Boundary.** Worker and coding agents cannot spawn additional subagents. Only the main orchestrator may invoke named mandatory repository gates.
- **Split audit gate.** `lookahead-auditor` = causality only (A, B, C1–C3, F, G, H). `contract-checker` = deliverables, seals, C4/D/E. Scope defined in `docs/CAUSAL_CHECKLIST.md`. Neither may report the other's category — that boundary is what stops multi-pass loops.
- **Bounded re-audits.** Pass 2+ must adjudicate all prior findings before raising new ones, max 3 new CRITICALs per pass. New file per pass (`audit/pass_NN.md`), never append.
- **Freeze deliverables up front.** Every study SPEC needs the Deliverables Manifest and Domain/Completeness sections from `docs/TEMPLATES.md`. An auditor cannot verify a deliverable set that was never written down — it invents one finding at a time instead.
- **Agent defs are generated.** Edit `.claude/agents/*.md` only; run `python scripts/sync_agents.py` to propagate to Codex and Antigravity.
- **Commit at every phase gate.** Branch (`study/<name>` or `chore/<topic>`) — never commit on `main`. Commit code together with the `audit/pass_NN.md` + `status.json` that audited it, so the scope hash matches the tree. Never commit generated data (`canonical_*/`, `_work/`, `*.parquet`, `model.joblib`) — commit the manifests instead. Full protocol: `AGENTS.md` § Commit protocol.
- **Risk tiers.** Tier 1 (small fix / diagnostic): main session + deterministic tests, no agents. Tier 2 (research study): plan → implement/tests → deterministic preflight CLEAR → split pre-execution audit → staged runner. Tier 3 (model freeze / deploy): add `repo-scout`, then implement/tests → deterministic preflight CLEAR → split pre-execution audit → staged runner.
- **Parity Failure First-Divergence Rule.** For any parity failure, no broad repository investigation is allowed until first-divergence localization (`python scripts/find_first_parity_divergence.py --reference ledger_a.jsonl --runtime ledger_b.jsonl`) has pinpointed the exact earliest failing timestamp, stage, and field difference.
- **Diff-first.** Review `git diff -U20` as the primary surface. Open full files only to resolve causality, state flow, base classes, or imports — never to repeat discovery already done.
- **No agents for process monitoring.** Use `scripts/run_bounded_study.py` and read its JSON status card, not raw logs.
- **Subagent output caps.** `repo-scout` 700w (paths/symbols only) · `contract-checker` 1,000w (compliance table) · `results-triager` 500w (failures + root cause) · `lookahead-auditor` 1,500w (findings by severity).
- **Standing authorization.** The named mandatory gates above may be invoked without asking, scoped strictly to the gate. No discretionary, general-purpose, nested, or fan-out agent use. Full text: `AGENTS.md` § Standing Authorization.

## BACKTEST / COLLECT — IMPORT, DON'T REGENERATE
Engine setup, instrument construction, catalog loading and the `sys.path`/`os.chdir` preamble
are already implemented. Import them; never re-type them into a new script.

| Concern | Canonical import |
| --- | --- |
| Engine + venue + instrument | `backtests/nt_runtime/engine_builder.py` → `build_engine`, `create_futures_instrument` |
| Catalog bar loading | `utils/runner/data.py` → `CausalDataLoader.load_bars` (never open `ParquetDataCatalog` inline) |
| 1s-before-1m dispatch order | `utils/causal_registration.py` → `add_bars_causal_order` |
| Study / stage / output / telemetry | `backtests/nt_runtime/{compiled_study_loader,data_plan,run_plan,output_manager,telemetry}.py` |
| Collect entrypoint | `backtests/run_nt_study.py --mode collect` |
| Standalone backtest entrypoint | `backtests/run_backtest.py` (non-collector strategies) |

- A standard backtest is `python backtests/run_backtest.py --strategy <id> --param k=v`, **not** a new `run_*.py`.
  Legacy `backtests/run_*.py` scripts are frozen references, not templates to copy.
- `resolve_catalog_plan(...)` is the generic catalog/instrument/warmup resolver.
  `resolve_data_plan(...)` is the study-bound wrapper that additionally applies collector chronology
  and OOS gates — do not call it for a non-collector backtest.
- `--strategy` must NEVER override a sealed study's declared `strategy_class`. If a study is sealed,
  the strategy it seals is the only strategy permitted to run under that study identity.
- Shared helpers go in `backtests/nt_runtime/`, `utils/runner/`, or `features/`. NEVER `sys.path.insert`
  into a sibling study directory.

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

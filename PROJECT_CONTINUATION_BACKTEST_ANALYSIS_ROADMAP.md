# Project Continuation: Collector Hardening, Backtests, and Analysis

## Purpose

This is the durable handoff for the NautilusTrader (NT) collector hardening work and its next phase: reusable backtests and post-collection analysis. It is a planning/control document, not a replacement for source-of-truth contracts, manifests, audit records, or test artifacts.

The ChatGPT project mirror used to create this document did not contain a synced `REPO_ANALYSIS.md`. The repository counts below are preserved from the previous review of that report and must be re-verified in the live repository before implementation.

## Current status

The collector's causal behavior is considered sound for the hardened maturity/flip study.

- Red Team Round 6 reported `FLOW_CLEAR_WITH_WARNINGS`, with no critical findings or landed bypasses.
- The sealed dependency closure was reported as 53 files, AST/dependency coverage complete, and causal lint at 100%.
- The smoke fixture independently verified 2,002 / 2,002 observations had exact source/observation timestamp alignment and zero future-source violations.
- The regression suite was reported as 131 passing tests.

The immediate posture is: complete the small documented close-out below, preserve the evidence, then freeze collector-framework development. Do not start a broad collector refactor while backtest and analysis consolidation are underway.

## Collector-framework hardening completed so far

### Causal defect repaired

The collector had evaluated a nominal checkpoint after its required source second had passed, creating look-ahead contamination. The fix requires a candidate to be evaluated only when its source bar is available at its observation timestamp. The smoke population moved from 2,032 to 2,002—matching the 30 late checkpoints independently identified by Red Team.

The durable causal invariant is:

```text
latest_source_ts_init <= observation_ts
```

For this exact-grid collector, the stronger fixture-specific property was measured:

```text
triggering_1s_ts_init == observation_ts
```

### Governance strengthened across the Red Team rounds

```text
Research decision / SPEC
  -> StudySpec and compiled study
  -> deterministic preflight and closure resolution
  -> independent causal and contract audits
  -> audit provenance and pre-execution seal
  -> sealed smoke run
  -> deterministic smoke validation
  -> authorized full TRAIN collection
  -> model and threshold freeze
  -> controlled OOS unlock and evaluation
```

The project now has, or materially improved, the following controls:

- Explicit causal registration and same-timestamp ordering.
- Ordered feature-list and SHA checks, not just a feature count.
- Resolved causal-lint coverage that fails closed if coverage is incomplete.
- Sealing of runtime, contract-authority, and governance dependency paths rather than a manually maintained “important files” list.
- A full run gate requiring current smoke acceptance tied to the study, seal, and manifest.
- OOS and warmup chronology treated as authorization controls that fail closed.
- Audit evidence intended to be derived from actual auditor artifacts rather than an orchestrator writing its own `CLEAR` status.
- Clear separation of current hardened lineage from old pre-remediation runs.

### Lessons learned

1. Enforce invariants, not named examples. A hardcoded filename list is not a dependency resolver; a JSON zero is not a measured causal result.
2. Authorization code is execution code. OOS checks, smoke gates, compilers, resolvers, and seal verifiers belong in the authority closure.
3. Required authorization fields must not use permissive defaults or `.get()` behavior that can skip enforcement.
4. High-value tests need independent computation or mutation attacks; production code comparing its output to itself is not enough.
5. A smoke record is evidence only when its claims are calculated from persisted artifacts and bound to the current execution identity.
6. Keep the generic runtime thin. Availability, sealing, chronology, output contracts, and authorization are framework concerns; feature formulas, population gates, targets, and strategy semantics are collector concerns.
7. Freeze a framework once it is proven for the next use case. Reopen it only for a demonstrated future failure.

### Remaining collector close-out

Round 6 found one small consistency issue: the validator defaults a missing `required_source_relation` to `equal`, while the full-stage gate effectively treated a missing value as `None` and skipped the exact-equality requirement.

Make the gate apply the same strict default, then add a regression test:

```text
missing relation config
+ zero future-source violations
+ exact timestamp equality not verified
=> full-stage gate rejects
```

Run the bounded smoke and mutation set again. If it passes, freeze this framework; do not turn the close-out into another hardening campaign.

## Findings preserved from `REPO_ANALYSIS.md`

The primary token loss is repeated rediscovery and regeneration of plumbing, rather than research reasoning itself.

| Repeated pattern | Reported scale | Cost |
| --- | ---: | --- |
| `sys.path` / `os.chdir` bootstrap | 471 files | Agents repeatedly rediscover how scripts run. |
| NT engine construction | 101 files | Backtest setup is copied and drifts. |
| `create_instrument()` implementations | 28, with 8+ variants | Instrument and venue metadata is recreated. |
| Catalog work outside `CausalDataLoader` | roughly 191-195 files | Data-loading and causality behavior is not reused. |
| Cross-study imports | 184 files | Small tasks trigger historical dependency hunts. |
| Existing `utils/runner/` use | 4 files | Proven shared infrastructure is mostly bypassed. |
| Analysis files | 212 studies, 187 backtests, 69 scratch | Loading, slicing, metrics, and reporting are regenerated. |

The conclusion is not “refactor the repository.” It is:

> Create a small canonical path for new work. Migrate only a study that is being reopened. Leave historical work alone.

## Token-efficiency goals

### Target operating model

```text
Deterministic code
  loads, validates, slices, fits, calculates, and summarizes
        -> compact JSON/CSV/tables
        -> reasoning agent interprets results and proposes the next experiment
```

| Today | Target |
| --- | --- |
| Agents search for runners, loaders, and prior scripts. | Agents use one documented command plus a small context packet. |
| Agents hand-code dates, venue, instrument, catalog, and output paths. | Configuration supplies variable inputs; runtime owns standard setup. |
| Agents repeatedly write grouping and metric code. | Shared analysis primitives emit validated standard tables. |
| High-reasoning capacity debugs plumbing. | High-reasoning capacity designs studies and interprets results. |

### Measurable goals

- A standard backtest launches without copying a `run_*.py` script.
- Standard analysis is reproducible from a study/run ID and analysis specification.
- A reviewer gets a compact context artifact, not a raw multi-million-row dataset or a repository search assignment.
- New work has no sibling-study imports and no new bootstrap boilerplate.
- Changing an ordinary parameter requires a config/CLI change, not a new script.
- Failures guide a narrow inspection path, not open-ended repo scouting.

## Architecture principles

1. Reuse existing proven components first: `backtests/nt_runtime/`, `utils/runner/`, `StudySpec`, and `CausalDataLoader`. Do not introduce a parallel `common/` package unless a concrete constraint requires it.
2. One canonical implementation owns each shared concern: engine creation, instruments, catalog loading, standard export, collection validation, and analysis result validation.
3. Harnesses are thin and explicit; they do not hide strategy semantics or become a universal research DSL.
4. Normal variation belongs in configuration: symbol, dates, policy, strategy, params, catalog, and output location.
5. Adopt forward only. New work uses the harness; a legacy study migrates only if reopened.
6. Prefer machine-readable artifacts to prose. Emit manifests, metrics, tables, hashes, and context packets.
7. Fail closed when validity matters: collection identity, schema, feature order, chronology, and split contracts must be present and consistent.
8. Do not automate research judgment. Hypotheses, strategy logic, feature formulas, and interpretation remain study-specific.

### Shared versus study-specific

| Shared infrastructure | Study-specific research |
| --- | --- |
| NT engine, venue/account, and instrument setup | Entry/exit and strategy state machine |
| Catalog resolution, warmup, causal stream registration | Population gates, targets, feature formulas, trackers |
| Run lifecycle, manifests, output layout, standard metrics | Hypotheses, uncommon slices, economic interpretation |
| Collection identity validation and model reproducibility | Model choices that are part of an experiment |
| Common slices, reporting tables, compact context packets | Promotion/rejection decisions |

## Backtest consolidation roadmap

### Desired interface

Ordinary work should resemble this (exact syntax may change):

```bash
python backtests/run_backtest.py \
  --study <study-id> --strategy <strategy-id> \
  --start 2025-03-01 --end 2025-03-31 \
  --param sl_atr=1.0 --param threshold=0.90
```

The runner owns engine/instrument construction, catalog resolution, warmup, causal registration, lifecycle, artifacts, and basic execution metrics. The strategy owns logic, state, and declared parameters.

### B0 — inventory and boundary decision (read-only)

1. Trace the canonical existing paths in `backtests/nt_runtime/` and `utils/runner/`.
2. Identify one known-good engine builder, instrument factory, catalog loader, output manager, and study/runtime contract.
3. Select the smallest existing package location for the canonical facade.
4. Pick two legacy fixtures: one simple and one with realistic warmup/strategy setup.
5. Write a one-page interface contract: inputs, outputs, failures, and explicitly unsupported cases.

**Exit criterion:** approved minimal boundary plus two reproducible fixture commands. No production migration yet.

### B1 — canonical runtime facade

Create/adapt small interfaces equivalent to:

```text
resolve_study_and_params(...)
create_instrument(...)
build_engine(...)
load_causal_data(...)
run_backtest(...)
write_run_artifacts(...)
```

Requirements:

- Reuse or promote the validated `CausalDataLoader` behavior; do not create a second normal catalog path.
- Accept structured config and type-checked CLI `--param key=value` overrides.
- Emit a run manifest with code/version identity, data range, warmup, inputs, parameters, and output locations.
- Use package/repository-relative paths; no new script-local `chdir` or `sys.path` bootstraps.
- Return actionable errors for missing contract fields, data, or strategy/module resolution.

**Exit criterion:** both fixtures run through the facade and produce comparable valid artifacts.

### B2 — thin CLI and strategy contract

1. Add one supported CLI entrypoint.
2. Define a small strategy adapter: strategy class/ID, parameter schema/defaults, data types, and optional warmup needs.
3. Put symbol, dates/partitions, catalog, output tag, and parameters in config or CLI.
4. Label bespoke old runners as legacy/experimental instead of treating them as templates.
5. Add `--dry-run` to print the resolved run plan, data plan, and output identity without replay.

**Exit criterion:** a standard new test is configuration plus CLI flags, without runner code.

### B3 — outputs, comparison, and instructions

Every run should emit:

```text
run_manifest.json
resolved_config.json
implementation/environment identity
execution_metrics.json
trades or events output (when applicable)
summary.json
log locations
```

Add deterministic run comparison for configuration identity, data window, aggregate metrics, and key output hashes. Update agent instructions: normal backtests must use the CLI and must not repo-scout unless the runner fails.

**Exit criterion:** a reviewer understands what ran and why two runs differ from artifacts alone.

### B4 — forward adoption and stopping rule

- Require the canonical runner for ordinary new backtests.
- Migrate only the next actively reopened old study.
- Do not convert all 101 runners.

**Stop when:** two legacy-equivalence fixtures and two new backtests are stable through the harness. Extract more only after a demonstrated repeated problem.

## Post-collection analysis consolidation roadmap

### Desired interface and outputs

```bash
python research/run_analysis.py \
  --study <study-id> --collection-run <run-id> \
  --analysis-spec analyses/<name>.yaml
```

Expected artifacts:

```text
analysis_manifest.json
validation.json
metrics.json
tables/*.csv or parquet
model manifests and serialized models
analysis_context.json
plots/ (only where useful)
```

### A0 — analysis contract and fixtures

1. Select two collections: the hardened collector and one structurally different collection.
2. Define analysis identity: collection manifest hash, schema, feature-list hash, target, partitions, split policy, seed, and analysis-spec hash.
3. Define the smallest artifact layout and schema-version rule.
4. Require an explicit immutable collection run/alias. An analysis must never silently choose `latest`.

**Exit criterion:** an analysis detects a mismatched run, schema, feature order, or partition before model fitting.

### A1 — validated dataset loader

Implement/adapt `datasets.py` that:

- Resolves a collection run and reads its manifest.
- Validates schema, duplicate keys, expected partitions, feature list/order/hash, target availability, and collection status.
- Exposes features, targets, metadata, and declared partitions without re-discovering file locations or columns.
- Returns an immutable dataset identity recorded by all downstream artifacts.

**Exit criterion:** equivalent requests produce the same identity; mismatched artifacts are rejected.

### A2 — standard slices and metrics

Implement only recurring slices:

```text
by_direction
by_year / partition
by_maturity
by_score_decile
by_regime
by_session
```

Define canonical edge-case behavior for recurring metrics:

```text
sample count, positive rate, ROC AUC, PR AUC, Brier score,
win rate, expected value, MFE, MAE, drawdown, quantiles,
and Sharpe only when return construction supports it.
```

Each table records sample count, filters, missing-data treatment, and uncertainty treatment where relevant.

**Exit criterion:** the two fixtures reproduce agreed tables without study-specific grouping code for common views.

### A3 — reproducible model and threshold wrappers

Build thin explicit wrappers around current models (for example LightGBM and basic sklearn), not a generic ML platform. A fit records:

- ordered features and dataset identity;
- split policy and leakage checks;
- seed, library/version, and hyperparameters;
- model checksum/location and prediction identity;
- threshold derivation population and freeze identity.

Support the current predeclared ablation:

```text
A = frozen directional base Top-25
B = A + structural features
C = B + rolling-productivity features
```

Retain the required caveat: 2024 can be OOS for fitting and the predeclared A/B/C comparison, but is not pristine relative to historical information used to choose the frozen base Top-25 lists.

**Exit criterion:** same inputs/spec/seed reproduce equivalent artifacts within documented deterministic tolerances.

### A4 — reporting and context packet

Generate a compact `analysis_context.json` for reasoning agents. It should include study/question, collection identity, partitions, target, feature-set sizes/hashes, primary metrics, key table paths, and caveats. Add standard A/B/C, direction, year, maturity, and decile tables.

The analysis agent should consume this packet and selected tables—not raw parquet or the collector implementation—unless validation identifies an anomaly.

**Exit criterion:** a reviewer can answer the stated research question from the packet and tables, with raw-data inspection reserved for anomalies.

### A5 — forward adoption and stopping rule

- New analysis begins with a declared analysis spec and validated context packet.
- Do not consolidate every notebook or historical script.
- Promote a helper when a second active study needs it; add no new sibling-study imports.

**Stop when:** two distinct studies load, validate, slice, fit, and report through the harness, while the next one requires only a spec and study-specific interpretation code.

## Acceptance tests

### Backtest harness

- Golden-run equivalence against each selected legacy fixture within defined tolerances.
- Declared parameter isolation; undeclared parameters fail.
- Deterministic dry-run plan/output identity.
- Exact date and authorized-warmup enforcement; locked partitions cannot enter through warmup or alternate loading.
- Canonical instrument resolution or explicit conflict failure.
- Supported launch-location equivalence without working-directory mutation.
- No successful status without complete required artifacts.
- A new fixture contains no copied engine/catalog/bootstrap code.

### Analysis harness

- Reject unknown, stale, or mismatched collection identity.
- Reject reordered/missing features, duplicate keys, or wrong partitions.
- Block TRAIN/DEV/OOS mixing from slice, join, typo, or default.
- Test metrics on small hand-checked fixtures, including empty, one-class, and NaN cases.
- Same data/spec/seed gives equivalent output manifests.
- A/B/C ordered feature sets and hashes match their declared contract.
- All tables include N, filters, identity, and metric definitions.
- Context packet is compact and references artifacts rather than raw data.

## Red-team plan

Use Claude's remaining pre-reset capacity as a reviewer after a small NinjaTec increment exists. Give it the harness contract, fixture commands, and clean state—not an implementation narrative.

### Backtest attack cases

1. Add a strategy/adapter dependency and verify it is resolved/manifested or errors explicitly.
2. Request conflicting historical instrument metadata; require a canonical resolution or hard failure.
3. Request unauthorized data through warmup, CLI, or config override; ensure no access occurs.
4. Run from two supported locations; compare resolved plan and artifacts.
5. Mutate parameter types/values and catalog path; require actionable failure, never fallback.
6. Compare each legacy fixture to its harness equivalent and explain intentional differences.
7. Attempt a copied normal `run_*.py`; require agent guidance/review to identify it as a bypass.

### Analysis attack cases

1. Point analysis at a compatible-looking but different run; identity/feature/partition validation must fail.
2. Reorder features without changing count; fit/inference must fail before use.
3. Mix OOS into training through a slice, join, warmup field, or alias; validation must block.
4. Produce a zero/one-class metric table; report `not computable`, not a misleading score.
5. Change seed, threshold population, or feature set; manifest/comparison output must expose it.
6. Give a reviewer only the context packet/tables; identify fields that still force repo scouting.
7. Delete a referenced artifact; require a precise missing-identity failure, never fallback to `latest`.

### Verdicts and stopping rules

```text
FLOW_BLOCKED              validity, reproducibility, or authorization bypass landed
FLOW_CLEAR_WITH_WARNINGS  no blocker; bounded usability/documentation issue remains
FLOW_CLEAR                acceptance matrix passes and no bypass lands
```

Happy-path execution is insufficient. The harness is ready only after representative fixtures pass, negative/mutation tests block, and a reviewer can reconstruct the work from artifacts alone.

## Recommended allocation of NinjaTec AI, Claude, Codex, and Gemini

| Agent | Best use now | Avoid | Specific near-term assignment |
| --- | --- | --- | --- |
| NinjaTec AI (fresh) | Main implementation of a narrow Backtest Harness MVP and deterministic tests | Broad refactor, live collector redesign, mass migration | B0-B2: inventory canonical components, implement/adapt facade and CLI, add two fixtures and artifacts. |
| Claude (about 7% pre-reset; fresh after) | Independent red-team review now; later research design and results interpretation | Long plumbing discovery; sole implementer and reviewer | Before reset, attack B1/B2 contract and fixtures. After reset, review A0/A1 and interpret compact result artifacts. |
| Codex (about 10%, reset in five days) | Narrow, test-bounded repair or evidence-based review | Open-ended repo scouting, broad consolidation, raw-data exploration | Fix one confirmed finding, add a targeted regression, or independently review a focused patch. |
| Gemini (about 20%, reset in five days) | Collector maintenance, bounded smoke/validation/performance work | More collector-framework expansion while harnesses are built | Apply/verify the Round-6 default-policy close-out, run bounded acceptance, then keep collector stable. |

### Recommended next sequence

1. Gemini makes the single Round-6 gate-default fix, executes its regression and bounded smoke/mutation checks, then stops.
2. NinjaTec completes Backtest B0 and the deliberately small B1/B2 MVP; no bulk migration.
3. Claude red-teams that patch with remaining pre-reset tokens; it attacks invariants rather than implements features.
4. NinjaTec addresses only confirmed findings and reaches the Backtest acceptance gate.
5. After Claude resets, use it for Analysis A0/A1 design/review and later interpretation of generated tables.
6. Use Codex only for a specific repair or independent patch verification.

## Handoff checklist

Before changing anything, the next agent must:

1. Read this document, the live `REPO_ANALYSIS.md`, current `AGENTS.md`, and latest collector audit/seal/smoke evidence.
2. Confirm actual paths for `backtests/nt_runtime/`, `utils/runner/`, `CausalDataLoader`, `StudySpec`, and the two fixture runs.
3. State the exact phase and its exit criterion. Do not begin a later phase early.
4. Preserve the collector framework except for the stated close-out.
5. Prefer a small importable interface over copied code; do not add a new abstraction package without a written reason existing code cannot host it.
6. Add acceptance and negative tests with the implementation.
7. Produce a short handoff with changed files, commands, fixture results, outstanding findings, and next phase.

## Final decision rule

Do not spend scarce token budget cleaning history. Build the smallest trusted forward path, prove it with representative fixtures and adversarial tests, then reserve expensive reasoning capacity for valid experiment design and interpretation.

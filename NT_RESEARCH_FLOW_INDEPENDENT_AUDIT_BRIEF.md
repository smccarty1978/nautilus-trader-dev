<!-- DOC-STATUS-BANNER -->
> **[HISTORICAL]**
>
> A point-in-time record of an independent audit brief. It is not a description of the current system
> and not a source of instructions.
>
> Current authority: **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# NautilusTrader ML Research Framework — Independent Audit Brief

**Purpose:** Give an independent agent enough context to audit the research workflow, scripts, execution gates, and agent/subagent responsibilities without relying on the implementer's interpretation.

**Important instruction to reviewer:** Treat this document as a map, not as proof. Verify every material claim against the current repository. If repository behavior conflicts with this document, report the repository behavior and classify the discrepancy.

---

# 1. What this framework is trying to accomplish

The project is building research studies for NQ using NautilusTrader as the authoritative event-driven runtime. The framework exists to make common study mechanics deterministic while keeping research judgment explicit and auditable.

The intended separation is:

```text
Human research intent
        ↓
small Research Decision Contract
        ↓
detailed SPEC
        ↓
machine StudySpec / compiled contract
        ↓
deterministic preflight
        ↓
independent causal + contract audits
        ↓
cryptographic pre-execution seal
        ↓
bounded NautilusTrader smoke
        ↓
deterministic smoke validation
        ↓
authorized full run
        ↓
post-run validation / model work / OOS gate
```

The core philosophy is:

- LLMs reason about research questions, ambiguities, and interpretation.
- Python handles repeatable mechanical validation, manifests, hashes, schema checks, chronology locks, and execution gating.
- NautilusTrader handles market-event replay and study-time feature/candidate generation.
- An LLM must not silently broaden or “improve” the experiment after the user has frozen the baseline.
- An audit must occur before expensive execution, not after.
- A code/configuration change after an audit invalidates the audit authorization.

---

# 2. Authority hierarchy

The intended precedence is:

```text
1. research_decision.yaml
2. SPEC.md
3. study.yaml / StudySpec
4. compiled_study.json
5. audit artifacts + preexec seal
6. runtime outputs
```

If a downstream layer conflicts with an upstream layer, the workflow should fail closed.

## 2.1 `research_decision.yaml`

This is the smallest, human-reviewable statement of what the study is actually trying to learn.

It should capture, at minimum:

- research question;
- fixed baseline;
- fixed inputs;
- feature-selection policy;
- variable(s) being tested;
- allowed changes;
- prohibited changes;
- chronology / train / OOS restrictions;
- primary comparison;
- terminal decision question.

It exists specifically to prevent an LLM from turning a narrow ablation into a different study while writing `SPEC.md`.

Example failure that this layer is designed to prevent:

```text
User intent:
  reuse frozen Top-25 baseline
  + structural features
  + rolling productivity

LLM expansion:
  scan 502 baseline features
  re-rank a new Top-25
  + structural
  + rolling

Expected outcome:
  RESEARCH_INTENT_CONFLICT / fail closed
```

## 2.2 `SPEC.md`

Detailed research design. It explains the exact population, target, feature semantics, chronology, model arms, deliverables, validation requirements, terminal labels, and audit gates.

The LLM may elaborate details, but it must not change decisions frozen in `research_decision.yaml`.

## 2.3 `study.yaml`

Machine configuration used by the Study Factory. It must faithfully encode the Decision Contract + SPEC.

## 2.4 `compiled_study.json`

Deterministic compiled execution contract. Runtime should consume this artifact rather than reconstructing a long set of ad-hoc CLI arguments or reinterpreting prose.

---

# 3. Non-negotiable runtime / causal invariants

The independent reviewer should verify the current repository version of these invariants rather than trusting old documentation.

1. **NautilusTrader is the authoritative market-event execution environment.** No pandas/vectorized simulation substitutes for event-driven candidate generation, regime transitions, or trading execution.
2. **Completed-bar causality:** a feature at observation time `T` may use only source state whose availability time is `<= T`.
3. **Current canonical availability form:**

```text
latest_source_ts_init <= observation_ts
```

4. **Databento timestamp semantics are source-specific and must not be guessed.** Current project evidence has used OPEN-stamped `ts_event` with close availability represented by `ts_init`. The reviewer must verify the current catalog builder and docs, especially 1s handling; historical `CLAUDE.md` text may be stale.
5. **Coincident multi-timeframe ordering is a calling convention, not an NT guarantee.** `add_bars_causal_order()` (or equivalent exact ordering) must register the faster stream before the coincident parent timeframe. A prior audit proved reversing `engine.add_data()` order reverses same-`ts_init` callback order.
6. **No forming higher-timeframe bars in completed-bar features.**
7. **No feature path may read forward labels/outcomes.** Intentional future data belongs only in label construction.
8. **Warmup data may precede the active study window, but must not create active-window rows outside the authorized partition or contaminate chronological selection/OOS rules.**
9. **Exact ordered feature contracts matter.** Count-only checks are insufficient; ordered feature list and SHA-256 must match.
10. **Any execution-affecting change after an audit invalidates authorization.**

---

# 4. Study Factory: canonical scripts and packages

These tools convert a frozen research contract into a deterministic study configuration. The factory should not run market replay itself.

## 4.1 `research/schemas/study_spec.py`

Purpose:
- Pydantic schema for the canonical machine contract.
- Validates fields, chronology, feature-selection policy, study type, and other contract-level constraints.

Reviewer checks:
- Can the schema express the research decision without lossy translation?
- Does it distinguish fixed feature lists from fresh feature discovery?
- Are forbidden lineage and conditional OOS locks represented structurally rather than only in prose?

## 4.2 `research/study_types/base.py`

Purpose:
- Shared canonical study-type interface / common behavior.

## 4.3 `research/study_types/flip_prediction.py`

Purpose:
- Canonical compiler for flip-prediction studies.
- Current Study Factory MVP initially supports this canonical family.

Reviewer checks:
- Does it reject unsupported operations rather than silently approximate them?
- Does it preserve the Decision Contract's baseline/feature-selection semantics?

## 4.4 `research/study_types/bespoke.py`

Purpose:
- Explicit escape hatch for non-canonical studies.
- Bespoke studies still inherit global chronology, causality, audit, and provenance rules.

Reviewer check:
- Is bespoke use explicit and justified, or is it being used to bypass missing reusable capabilities?

## 4.5 `research/engines/population_engine.py`

Purpose:
- Compile/validate population rules.

## 4.6 `research/engines/target_engine.py`

Purpose:
- Compile/validate target definitions.

## 4.7 `research/engines/feature_binding_engine.py`

Purpose:
- Bind feature lists / feature sources to the registry and enforce feature-lineage rules.
- Should reject prohibited legacy feature sources when the Decision Contract disallows them.

Important failure code used during hardening:

```text
FORBIDDEN_FEATURE_LINEAGE
```

## 4.8 `research/engines/lineage_engine.py`

Purpose:
- Validate dataset/model/artifact lineage and authorized source relationships.

## 4.9 `research/engines/baseline_engine.py`

Purpose:
- Validate/freeze baseline identity and hashes.

## 4.10 `research/engines/timestamp_engine.py`

Purpose:
- Validate the study's timestamp/availability contract.

## 4.11 `research/capabilities.json`

Purpose:
- Compact machine-readable description of supported canonical capabilities.
- Helps agents decide whether a study is canonical, requires a reusable extension, or must be bespoke.

## 4.12 `scripts/create_study.py`

Purpose:
- Create/scaffold a study from validated configuration.
- Generates standard study files/tests/contracts.

Expected use:

```bash
python scripts/create_study.py --config <config.yaml>
```

Not responsible for:
- market replay;
- model fitting;
- economic simulation.

## 4.13 `scripts/compile_study.py`

Purpose:
- Compile `study.yaml` into `compiled_study.json`.
- Deterministically validate canonical type and executable contract.

Expected use:

```bash
python scripts/compile_study.py --study studies/<study>
```

## 4.14 `scripts/describe_study_diff.py`

Purpose:
- Semantic comparison of study contracts.
- Useful for proving a proposed study change alters only intended dimensions.

## 4.15 `scripts/tests/test_study_factory.py`

Purpose:
- Regression/mutation tests for Study Factory behavior, invalid inputs, stale hashes, unsupported capabilities, lineage mutations, etc.

---

# 5. Research-intent and SPEC fidelity scripts

## 5.1 `scripts/check_research_decision_fidelity.py`

Purpose:
- Validate `research_decision.yaml`.
- Check baseline binding, feature-selection policy, chronology, and downstream consistency.
- Prevent `SPEC.md` / `study.yaml` from broadening the approved research question.

Key principle encoded in agent governance:

> Never improve, broaden, clean up, or make a study more statistically pure by changing a fixed baseline or adding feature discovery unless the Research Decision Contract explicitly permits it. Surface the concern as a caveat; do not silently alter the experiment.

Reviewer checks:
- Is the check truly semantic, or can contradictory prose in SPEC still pass?
- Does it fail when `baseline_feature_selection.mode: none` is combined with a registry-wide ranking source?
- Are all material Decision Contract fields represented in the check?

## 5.2 `scripts/check_spec_fidelity.py`

Purpose:
- Map mandatory SPEC clauses to machine-readable StudySpec/Study YAML fields.
- Emit a contract map such as `artifacts/spec_contract_map.json`.
- Required-clause coverage should be 100%; required unmapped clauses should block execution.

Reviewer checks:
- Is this checking fidelity to the current SPEC, not merely syntax?
- Does it distinguish mandatory from descriptive prose?
- Can required A/B/C arms, chronology, terminal-label restrictions, etc. be omitted while still passing?

---

# 6. Phase-0 / source manifest tooling

## 6.1 `scripts/build_phase0_manifest.py`

Purpose:
- Deterministically capture source/authenticity information before data collection or fitting.
- Should hash the study contracts, relevant feature definitions/implementations, runtime sources, and authorized/forbidden data domains.

The current study initially used scratch variants during development; the independent reviewer should confirm that the final workflow has one canonical repository script and does not secretly depend on scratch utilities.

Expected contents can include:
- `research_decision.yaml` hash;
- `SPEC.md` hash;
- `study.yaml` hash;
- compiled contract hash;
- feature names + ordered hash;
- implementation hashes;
- test paths;
- data-domain authorization;
- explicit invalidated-run/quarantine acknowledgement where needed.

Reviewer checks:
- Is the manifest generated from repository state rather than hand-authored assertions?
- Are claims such as “2024 not accessed in valid lineage” measurable/proven rather than manually typed?

---

# 7. Deterministic preflight layer

## 7.1 `scripts/research_preflight.py`

Purpose:
- Umbrella deterministic gate before independent LLM audits and before runtime.
- Current flow integrates checks such as decision fidelity, SPEC fidelity, causal lint, artifact schema, domain/chronology guards, and causal invariants.

Expected outcome:

```text
RESEARCH PREFLIGHT VERDICT: CLEAR
```

Anything else blocks advancement.

Reviewer check:
- Enumerate every check actually invoked now. Do not rely on old lists from walkthroughs.

## 7.2 `scripts/causal_lint.py`

Purpose:
- Cheap deterministic static lint for recurring causal/look-ahead defects already observed historically.
- Runs before paid/LLM auditor passes.
- Supports study/path scoped operation and machine-readable output.

Typical use:

```bash
python scripts/causal_lint.py --study studies/<study>
python scripts/causal_lint.py --path strategies/ backtests/ scripts/
```

Reviewer checks:
- Does preflight call it against every execution-affecting file?
- Are suppressions reasoned and audited?
- Is lint treated as a supplement, not a replacement for causal audit?

## 7.3 `scripts/check_artifact_schema.py`

Purpose:
- Validate required artifact structures and required fields.

## 7.4 `scripts/check_model_binding.py`

Purpose:
- Validate model ↔ feature ↔ preprocessing binding where applicable.
- More relevant after model artifacts exist.

## 7.5 `scripts/verify_feature_surface.py`

Purpose:
- Verify that the requested feature contract is registered, runtime-bound, and causally supported before an expensive collection.

Important note:
- For the current maturity/productivity study the final requested surface is 60 unique features (25 frozen base + 27 structural + 8 rolling), not the earlier 502/537 discovery surface.
- The framework must not hardcode “60”; that count is study-specific.

## 7.6 `scripts/sync_agents.py`

Purpose:
- Synchronize canonical agent definitions across `.claude`, `.agents`, `.codex`, etc.
- `--check` should fail if generated harness definitions drift.

Typical use:

```bash
python scripts/sync_agents.py
python scripts/sync_agents.py --check
```

---

# 8. Independent audit layer

The project now requires **both** a causal/look-ahead audit and a research-contract audit before market replay.

These are deliberately separate questions:

```text
Causal audit:
  Is the implementation knowable/causal at time T?

Contract audit:
  Is this actually the study we said we were going to run?
```

## 8.1 `scripts/run_preexec_audits.py`

Purpose:
- Coordinate/record actual independent subagent audits.
- Produce authenticated audit status records with provenance.
- Must never substitute “write CLEAR JSON” for a real auditor invocation.

Current provenance requirements introduced during hardening include:
- audit provenance version;
- auditor identity;
- report SHA-256;
- execution-file composite SHA-256;
- timestamps/scope metadata;
- actual verdict counts.

Reviewer checks:
- Can the main orchestrator manufacture a PASS without invoking the independent agents?
- Are auditor outputs immutable/authenticated enough for the seal generator to trust?
- Are audit reports generated before execution and against the exact current code?

## 8.2 `scripts/preexec_audit_seal.py`

Purpose:
- Cryptographically bind the exact execution-affecting repository state to the two independent audit passes.
- Refuse to generate/verify a seal if code changed after either audit.

Core intended invariant:

```text
CURRENT_EXECUTION_HASH
== CAUSAL_AUDITED_EXECUTION_HASH
== CONTRACT_AUDITED_EXECUTION_HASH
```

Expected failures:

```text
PREEXEC_AUDIT_STALE
PREEXEC_AUDIT_PROVENANCE_INVALID
```

The seal should bind current study authority and execution state, including `research_decision.yaml`.

Reviewer checks:
- Enumerate the exact files included in the composite hash.
- Are any execution-affecting files omitted?
- Are `run_preexec_audits.py`, seal verification logic, feature registry, relevant tracker code, collector code, run/data/engine plans, compiled contract, Decision Contract, and audit reports all covered appropriately?
- Can changing seal logic itself bypass stale-audit protection?
- Is verification performed before any catalog data is loaded?

## 8.3 `scripts/tests/test_audit_seal_guard.py`

Purpose:
- Canary/regression tests that the seal rejects stale audited state and provenance tampering.

Critical expected test class:
- change an execution file after audit → seal generation/verification must fail.

---

# 9. NautilusTrader generic collect runner

The generic runner is **Phase 1 collect mode**. It is not yet a universal execution/economics engine.

Canonical architecture:

```text
compiled_study.json
        ↓
backtests/run_nt_study.py
        ↓
backtests/nt_runtime/*
        ↓
NautilusTrader BacktestEngine
        ↓
strategies/flip_prediction_collector.py
        ↓
runs/<run_id>/...
```

## 9.1 `backtests/run_nt_study.py`

Purpose:
- Canonical CLI entry point for generic NT study replay.

Typical smoke:

```bash
python backtests/run_nt_study.py \
  --study studies/<study> \
  --mode collect \
  --stage day \
  --date YYYY-MM-DD
```

Typical authorized full TRAIN collection:

```bash
python backtests/run_nt_study.py \
  --study studies/<study> \
  --mode collect \
  --stage full
```

Reviewer check:
- Confirm this is the only canonical current CLI for this flow. Several older/experimental commands were tried during development and should not remain implicit dependencies.

## 9.2 `backtests/nt_runtime/compiled_study_loader.py`

Purpose:
- Load and validate `compiled_study.json`.
- Reject stale/tampered `study.yaml` / compiled artifacts.

## 9.3 `backtests/nt_runtime/data_plan.py`

Purpose:
- Resolve catalog, instrument, bar types, active and warmup date windows.
- Enforce authorized chronology and OOS locks **before data access**.

Important failure:

```text
OOS_LOCKED_UNTIL_FREEZE
```

Reviewer checks:
- Does the lock happen before any DEV/OOS files are opened?
- Does warmup accidentally cross a forbidden future boundary?
- Are 2025/2026 prohibited when the study says so?

## 9.4 `backtests/nt_runtime/run_plan.py`

Purpose:
- Resolve bounded stages (`fixture`, `day`, `week`, `month`, `full`).
- `auto_expand` should remain false; a smoke should not silently become a full run.

Reviewer checks:
- Does `full` resolve exactly to the authorized partition from the compiled contract?
- Does a run-plan edit invalidate pre-execution authorization?

## 9.5 `backtests/nt_runtime/strategy_binding.py`

Purpose:
- Resolve strategy key to the approved collector class/configuration.

## 9.6 `backtests/nt_runtime/engine_builder.py`

Purpose:
- Instantiate NautilusTrader `BacktestEngine`.
- Register data streams using the causal ordering helper.

Critical dependency:
- `add_bars_causal_order()` (shared helper, historically under `utils/causal_registration.py`).

Reviewer check:
- Confirm 1s stream is registered before coincident 1m/parent streams according to the current helper contract.

## 9.7 `backtests/nt_runtime/telemetry.py`

Purpose:
- Wall time, RSS/peak memory, throughput, other run telemetry.

## 9.8 `backtests/nt_runtime/output_manager.py`

Purpose:
- Deterministic run directories, manifests, parquet outputs, hashes.
- Current hardening validates exact emitted feature names and ordered SHA-256, not feature count alone.

Reviewer checks:
- A 59-correct + 1-wrong schema must fail.
- Metadata columns must be distinguished deterministically from model features.

## 9.9 `backtests/nt_runtime/modes/collect.py`

Purpose:
- Orchestrate collection mode.
- Must verify the pre-execution audit seal before catalog loading / engine replay.

Reviewer check:
- Confirm the seal check truly occurs before any expensive or unauthorized data access.

---

# 10. Canonical NT collector and feature state

## 10.1 `strategies/flip_prediction_collector.py`

Purpose:
- NautilusTrader `Strategy` handling event-driven regime state, candidate gating, and feature snapshots.
- Current optimized path uses a targeted feature contract and a fast ring-buffer state path rather than computing hundreds of unused features.

Current maturity/productivity study example:

```text
Model A = frozen base Top-25          = 25
Model B = A + structural geometry     = 52
Model C = B + rolling productivity    = 60
```

The same frozen Top-25 is currently used for SHORT and LONG in that study, so the collector union is exactly 60.

Current measured fixture performance after targeting:

```text
~25,944 bars/sec
unrequested feature calculations = 0
2,032 target-date candidates on 2023-03-03
60 feature columns
exact feature-list SHA match
```

These figures are study evidence, not framework invariants.

Reviewer checks:
- Are only requested calculations actually performed, or are full families still computed then filtered?
- Is population evaluation on exact intended 5s cadence?
- Are feature snapshots immutable after emission?
- Are labels/outcomes populated only after future events and never fed back into feature state?

## 10.2 `features/registry.py`

Purpose:
- Versioned canonical feature definitions and contracts.

Reviewer checks:
- Every selected feature has an implementation, version, units/window semantics, warmup/reset policy, and tests.
- No semantic change occurs under an unchanged canonical name.

## 10.3 `features/trackers/structural_regime_geometry.py`

Purpose:
- Structural regime geometry family (27 features in the current study).

## 10.4 `features/trackers/rolling_5m_productivity.py`

Purpose:
- Rolling five-minute productivity family (8 features in the current study).

Current intended causal semantics for that study include:
- completed 1s state only in `[T-300s, T]`;
- exact boundary anchor at `T-300s`;
- no nearest-boundary search/interpolation;
- no forming 5m bars;
- invalid denominators → unavailable, not clamps.

## 10.5 Other trackers / fast path

The current targeted collector may use only the base feature calculations needed by the frozen Top-25. Historical full-family trackers include OHLCV/delta and price-level families. The independent reviewer should verify the current targeted path rather than assuming all registry trackers run.

---

# 11. Smoke test and expansion policy

A smoke test is a formal stage of the workflow, but **only after pre-execution audits and the seal are valid**.

Correct ordering:

```text
CODE COMPLETE
  ↓
Decision/SPEC fidelity
  ↓
phase-0 / deterministic preflight
  ↓
independent causal audit
  ↓
independent contract audit
  ↓
preexec seal
  ↓
SMOKE
  ↓
deterministic smoke checks
  ↓
FULL authorized run
```

Never:

```text
full run
  ↓
audit discovers simple defect
```

## Smoke should verify at least

- bars loaded > 0;
- expected population exists;
- all required directions populate where expected;
- required maturity/stratification buckets populate where expected;
- exact feature list and ordered hash;
- duplicates == 0;
- timestamp/availability violations == 0;
- no forbidden data-domain access;
- runtime/memory are sane enough for expansion;
- deterministic expected fixture population when a golden fixture exists.

For the current study, the sealed fixture check is:

```text
2023-03-03
2,032 candidates
60 features
exact ordered feature SHA
```

A code/config change after the smoke invalidates the audit/seal and therefore invalidates the smoke authorization chain.

---

# 12. Supporting parity / diagnostic scripts

These tools are useful, but are not the normal path for every study.

## 12.1 `scripts/check_collect_equivalence.py`

Purpose:
- Compare independent reference candidate artifacts against generic NT runner output.
- Separates population overlap, feature-list/hash, and feature-value differences.
- Has a self-comparison guard so the same file cannot be compared to itself and called parity.

Important historical acceptance:
- Generic runner achieved canonical causal parity even where legacy offline semantics drifted at boundaries.

## 12.2 `scripts/find_first_parity_divergence.py`

Purpose:
- Localize the first differing checkpoint/field between two candidate surfaces.

## 12.3 `scripts/tests/test_nt_runner_collect.py`

Purpose:
- Unit/integration/regression coverage for generic runner collect mode, output manager, equivalence checker, etc.

## 12.4 `scripts/select_required_tests.py`

Purpose:
- Select relevant bounded tests for a study/change set where applicable.

## 12.5 Scratch profilers / reconciliation scripts

Many `scratch/` scripts were used during development to diagnose performance, feature-count differences, candidate warmup discrepancies, etc.

**They should not be hidden required steps in the production workflow.**

Independent reviewer task:
- identify any scratch script whose logic is now required for correctness;
- if required, require it to be promoted to a canonical tested repository script;
- otherwise classify scratch utilities as disposable diagnostics.

---

# 13. Post-collection / model / OOS flow

The generic NT runner MVP currently focuses on collection. The independent reviewer should verify the current repository implementation of downstream training/evaluation rather than assuming it is generalized.

The intended state machine is:

```text
TRAIN collection complete
        ↓
deterministic collection validation + hash freeze
        ↓
fit/preprocess using TRAIN only
        ↓
freeze model/preprocessing/threshold contracts
        ↓
generate OOS unlock artifact
        ↓
DEV/OOS data becomes readable
        ↓
score/evaluate
        ↓
validation.json
        ↓
result_seal.json
        ↓
promotion_gate.json / terminal result
```

For the current maturity/productivity study specifically:

```text
No fresh baseline feature selection.

A = frozen Top-25
B = A + 27 structural
C = B + 8 rolling

Fit/freeze on 2021-2023.
2024 is opened only after model/config freeze.
2025 unused.
2026 sealed/prohibited.
```

Important lineage caveat for that study:
- 2024 is OOS relative to this study's fitting and new A/B/C comparison;
- it is not pristine with respect to the historical provenance of the already-frozen base Top-25 list.

Reviewer checks:
- Is this caveat actually preserved in the current Decision Contract/SPEC/reporting plan?
- Does any code still contain obsolete “fresh Top-25 ranking” logic?
- Can any fitting/threshold/model-choice code read 2024 before OOS unlock?

---

# 14. Agent governance: what `CLAUDE.md` / `AGENTS.md` should enforce

The independent reviewer should inspect the current versions of `CLAUDE.md`, `AGENTS.md`, and `.claude/AGENT_WORKFLOW.md`. Historical copies may be stale.

They should encode at least these behavioral rules:

1. **Research Decision Contract authority.** Never silently broaden or improve a frozen experiment.
2. **NT-only market execution/replay authority.** No pandas substitute for candidate generation/backtest behavior.
3. **Causal completed-bar semantics.** Use availability (`ts_init`) rather than guessing from raw timestamp labels.
4. **Coincident timeframe ordering.** Use the shared causal registration helper; do not assume NT has a built-in 1s-before-1m tie-break.
5. **Deterministic scripts before LLM work.** Do not spend expensive agent calls on checks a script can prove.
6. **All required audits pass before any market replay or expensive study execution.**
7. **Audit independence.** Main implementer/orchestrator may not self-author an audit PASS.
8. **Code drift invalidates audit authorization.** Re-audit after execution-affecting changes.
9. **Smoke before full run.** No automatic stage expansion.
10. **No background-monitoring claims unless an actual tool/task exists.**
11. **Do not create parallel study frameworks.** Extend canonical machinery only when the missing capability is reusable; otherwise use explicit bespoke mode.
12. **Stop infrastructure work once the real study is unblocked.** Only extend again when a concrete future study demonstrates a missing capability.

## Important current-doc audit point

Historical `CLAUDE.md` text said “1s bars need no adjustment.” Current project understanding uses source/catalog availability semantics and has treated 1s close availability as `ts_init = ts_event + 1s` in the current catalog. The independent reviewer should verify the **current** `CLAUDE.md` / data docs and flag any stale invariant that conflicts with the actual catalog-building code.

---

# 15. Subagent responsibilities

## 15.1 Main orchestrator (Claude/Codex/Gemini flagship agent)

Should:
- capture user intent into `research_decision.yaml` before elaborating a complex SPEC;
- use deterministic checks instead of manually asserting facts;
- invoke support agents with narrow self-contained assignments;
- synthesize evidence and implement the smallest approved change;
- never manufacture independent-audit verdicts;
- stop on blocking ambiguity instead of silently changing the experiment;
- after any execution-affecting edit: preflight → independent audits → seal → smoke again;
- keep full runs bounded/authorized and avoid unnecessary reruns.

Should not:
- reinterpret fixed baselines;
- add feature discovery because it seems statistically cleaner;
- write `status.json: CLEAR` on behalf of auditors;
- compare an artifact with itself to prove parity;
- run a full study before required audits;
- use an old audit after code changes;
- silently move execution logic into study-specific one-offs when canonical tools should handle it.

## 15.2 `repo-scout`

Role:
- read-only codebase mapper;
- locate files/symbols/call paths/dependencies before planning;
- cite exact paths and line ranges;
- separate confirmed behavior from inference;
- stop once requested evidence is found.

Should not:
- edit files;
- design architecture;
- make final research judgments;
- explore the entire repo unnecessarily.

## 15.3 `contract-checker`

Role:
- read-only compliance reviewer against supplied explicit contracts.

Checks can include:
- timestamp/callback ordering;
- future-data access;
- snapshot immutability;
- feature/label separation;
- population construction;
- train/dev/test discipline;
- warmup/session handling;
- replay/runtime parity;
- feature tracker parameterization;
- deliverables and terminal-label reachability.

Required behavior:
- direct code evidence + test evidence;
- `PASS`, `FAIL`, `WARNING`, `NOT VERIFIED`, or `N/A` per requirement;
- no approval if blocking items are FAIL/NOT VERIFIED;
- smallest remediation only, not redesign.

## 15.4 `lookahead-auditor`

Role:
- independent skeptical causal/timestamp/train-serve audit;
- inspect data loading, features/labels, strategy logic, runtime configuration, and train/serve consistency;
- report exact file:line findings;
- maintain independence from the implementer's reasoning.

Should not:
- edit production code;
- run the study/backtest as proof;
- propose alternative strategies/features;
- assume benign semantics when evidence is ambiguous.

Expected audit topics include:
- `ts_event` vs `ts_init` semantics;
- rolling/EMA/ATR availability;
- negative shifts only in labels;
- temporal splits;
- live/offline feature parity;
- order/fill timing when trading is in scope;
- session/DST/warmup;
- same-timestamp ordering.

## 15.5 `results-triager`

Role:
- bounded test runner / failure summarizer.
- Execute only the exact pytest commands assigned by the parent.
- Uses guarded Bash hook to prevent arbitrary shell execution.

Should not:
- edit production/tests;
- run arbitrary Python scripts;
- run Git/shell utilities;
- retry with unrelated options;
- diagnose unrelated failures.

Expected output:
- exact command;
- exit status;
- pass/fail/skip/error counts;
- first root failure;
- relevant source location;
- existing artifact paths;
- final `PASS` / `FAIL` / `INCOMPLETE`.

## 15.6 Any legacy `test-runner` agent

The current documented workflow emphasizes `results-triager`. If a separate `test-runner` still exists, the reviewer should determine whether it has a distinct necessary role or is redundant/deprecated. Duplicate agents with overlapping write/execute permissions are a governance risk.

---

# 16. Recommended subagent coordination

Canonical planning/execution pattern:

```text
Need/change identified
      ↓
repo-scout (where/how does it work?)
contract-checker (what must remain true?)
      ↓
main orchestrator synthesizes bounded plan
      ↓
main implementation agent edits
      ↓
results-triager runs exact tests
      ↓
deterministic preflight
      ↓
independent lookahead-auditor
independent contract-checker
      ↓
authenticated audit provenance
      ↓
preexec seal
      ↓
smoke
      ↓
full run if smoke passes
```

Important independence rule:
- Do not give the final auditor the implementer's persuasive argument for why the code is correct. Give it the contract, changed files, tests, and required scope.

---

# 17. Invalidation matrix

The reviewer should verify that the repository actually enforces an invalidation graph equivalent to this.

| Change | Recompile | Preflight | Re-audit | New seal | New smoke |
|---|---:|---:|---:|---:|---:|
| `research_decision.yaml` | YES | YES | YES | YES | YES |
| `SPEC.md` material contract | YES | YES | YES | YES | YES |
| `study.yaml` | YES | YES | YES | YES | YES |
| `compiled_study.json` | n/a/generated | YES | YES | YES | YES |
| feature implementation / registry | maybe | YES | YES | YES | YES |
| collector / runtime / run plan / data plan / engine builder | maybe | YES | YES | YES | YES |
| audit tooling / seal verification logic | investigate | YES | YES | YES | YES |
| report prose only, no execution impact | usually NO | targeted | usually NO | depends | NO |
| new authorized TRAIN partition with unchanged sealed state | NO | NO | NO | verify existing | deterministic partition checks only |

A critical independent-audit question is whether this invalidation behavior is encoded or merely expected socially.

---

# 18. Current study as a concrete end-to-end example

Study:

```text
Gemini_clean_maturity_flip_rolling_5m_productivity
```

Current intended Decision Contract after remediation:

```text
No baseline feature discovery.
Reuse frozen base Top-25.
Test incremental structural geometry and rolling 5m productivity.

A = 25
B = 52
C = 60
```

The earlier 502/537 feature universe was removed because it represented a different research question.

Current optimized collector evidence:

```text
Fixture: 2023-03-03
Bars replayed incl. warmup: ~259k
Target-date candidates: 2,032
Features emitted: 60
Ordered feature hash: exact
Throughput: ~25.9k bars/sec
Unrequested calculations: 0
```

The current audit flow reached Pass 06 using independently invoked:
- `lookahead_auditor`;
- `contract_checker`;
- authenticated audit provenance;
- execution-composite hash equality;
- pre-execution seal;
- sealed smoke.

Full TRAIN collection target:

```text
2021-01-01 through 2023-12-31
2024 remains OOS-locked until downstream model/config freeze
2025 unused
2026 sealed/prohibited
```

Reviewer should use this study as a concrete trace through the framework, while also checking that framework code remains study-agnostic.

---

# 19. Questions the independent agent should answer

The outside review should explicitly answer these rather than simply saying “looks good.”

1. **Intent fidelity:** Can an LLM still change a fixed baseline or add feature discovery without deterministic failure?
2. **Authority:** Is `research_decision.yaml` truly upstream of SPEC/StudySpec in enforcement, not just prose?
3. **Factory scope:** Does the canonical Study Factory reject unsupported semantics rather than approximate them?
4. **Scratch dependency:** Does any required step still depend on `scratch/` code?
5. **Preflight completeness:** What exact scripts/checks run under `research_preflight.py` today?
6. **Audit independence:** Can the main orchestrator create a valid “CLEAR” status without an actual subagent audit?
7. **Audit provenance:** Are report hashes, auditor identity, execution composite, and timestamps verified?
8. **Seal completeness:** Are all execution-affecting files included? Which files are intentionally excluded and why?
9. **Seal self-protection:** Could a change to seal/audit tooling itself allow stale evidence to be accepted?
10. **Before-data guarantee:** Does collect mode verify audits/seal before loading catalog data?
11. **OOS lock:** Can any code path read DEV/OOS before unlock, including warmup or helper scripts?
12. **Timestamp truth:** Does current documentation match actual catalog `ts_event`/`ts_init` semantics for 1s, 1m, 3m, 5m?
13. **Coincident ordering:** Does every multi-timeframe NT runner use `add_bars_causal_order()` or an equivalent proven ordering?
14. **Feature computation:** Does the collector compute only requested feature dependencies, not full unused families?
15. **Feature contract:** Does output persistence enforce ordered list/hash, not only count?
16. **Population:** Are checkpoint cadence, gate rules, regime state, session logic, and warmup identical between smoke/full/live use?
17. **Smoke gate:** Can a full run occur without a current sealed smoke?
18. **No auto expansion:** Can `day`/`month` silently expand to `full`?
19. **Post-collection state:** Is there a deterministic `TRAIN_COLLECTION_COMPLETE` validation before model fitting?
20. **OOS state machine:** Are preprocessing/model parameters frozen before OOS unlock?
21. **Terminal evidence:** Are result seals/promotion gates based only on allowed directional evidence and required complete cells?
22. **Agent permissions:** Are read-only agents truly prevented from implementation changes? Is `results-triager` shell access narrowly guarded?
23. **Agent parity:** Do `.claude`, `.agents`, `.codex` harnesses actually match canonical source after `sync_agents.py --check`?
24. **Documentation drift:** Are old instructions (especially timestamp semantics and retired flow commands) still present and capable of misleading agents?
25. **Complexity:** Which safeguards are redundant, and which are actually load-bearing? Recommend simplification only if it preserves fail-closed behavior.

---

# 20. Desired independent-audit output format

Ask the reviewer to return:

## A. Executive verdict

Exactly one:

```text
FLOW_CLEAR
FLOW_CLEAR_WITH_WARNINGS
FLOW_BLOCKED
```

## B. Architecture map

Show the actual call/dependency path found in code, with file:line evidence.

## C. Control matrix

| Risk | Intended control | Actual implementation | Test/canary | Verdict |
|---|---|---|---|---|

At minimum cover:
- intent drift;
- SPEC drift;
- lineage drift;
- lookahead;
- stale audits;
- fake audit provenance;
- code changes after audit;
- OOS access;
- timestamp semantics;
- coincident timeframe ordering;
- feature-order/hash drift;
- scratch-script dependency;
- unauthorized full-run expansion.

## D. Findings by severity

```text
CRITICAL
WARNING
NOTE
```

Every finding must include:
- exact file and line range;
- failure mechanism;
- why the existing control does not catch it;
- smallest remediation;
- regression test that should prove the fix.

## E. Red-team bypass attempts

The reviewer should actively try to reason through or test:
- stale audit + new code;
- manually forged audit status;
- modified research decision + unchanged SPEC;
- modified SPEC + stale compiled artifact;
- wrong feature with same feature count;
- OOS date requested before unlock;
- full run without smoke;
- reversed 1s/1m data registration;
- use of an old/alternate runner;
- scratch script bypassing canonical gates.

## F. Complexity / simplification recommendations

Only recommend removing a control after proving another control covers the same failure class.

---

# 21. Copy/paste prompt for the independent agent

```text
You are performing an independent architecture, causal-safety, and governance audit of a NautilusTrader ML research framework.

Do not trust prior walkthroughs, PASS labels, or this brief as proof. Verify current repository behavior directly with file:line evidence and bounded tests where appropriate.

Primary objective:
Determine whether the workflow makes it mechanically difficult to (a) change the user's research intent, (b) introduce look-ahead/timestamp errors, (c) run unaudited or stale code, (d) access OOS data prematurely, or (e) bypass the canonical NautilusTrader execution path.

Start by reading:
- CLAUDE.md
- AGENTS.md
- .claude/AGENT_WORKFLOW.md
- .claude/agents/repo-scout.md
- .claude/agents/contract-checker.md
- .claude/agents/lookahead-auditor.md
- .claude/agents/results-triager.md
- scripts/sync_agents.py

Then trace the authority/configuration path:
- studies/<current study>/research_decision.yaml
- studies/<current study>/SPEC.md
- studies/<current study>/study.yaml
- studies/<current study>/compiled_study.json
- research/schemas/study_spec.py
- research/study_types/flip_prediction.py
- research/study_types/bespoke.py
- research/engines/*.py
- scripts/check_research_decision_fidelity.py
- scripts/check_spec_fidelity.py
- scripts/build_phase0_manifest.py
- scripts/research_preflight.py
- scripts/causal_lint.py

Then trace audit authorization:
- scripts/run_preexec_audits.py
- scripts/preexec_audit_seal.py
- scripts/tests/test_audit_seal_guard.py
- studies/<current study>/audit/*
- studies/<current study>/artifacts/preexec_audit_seal.json

Then trace the NT execution path:
- backtests/run_nt_study.py
- backtests/nt_runtime/compiled_study_loader.py
- backtests/nt_runtime/data_plan.py
- backtests/nt_runtime/run_plan.py
- backtests/nt_runtime/strategy_binding.py
- backtests/nt_runtime/engine_builder.py
- backtests/nt_runtime/modes/collect.py
- backtests/nt_runtime/output_manager.py
- strategies/flip_prediction_collector.py
- utils/causal_registration.py (or current location of add_bars_causal_order)
- features/registry.py
- feature tracker files directly used by the current 60-feature contract

Also inspect:
- scripts/check_collect_equivalence.py
- scripts/find_first_parity_divergence.py
- scripts/tests/test_nt_runner_collect.py
- scripts/select_required_tests.py
- any current downstream training/OOS-unlock scripts

Explicitly determine which scratch scripts are diagnostics only and whether any are hidden required dependencies.

Hard questions you must answer:
1. Can an LLM change a frozen baseline or add feature discovery without failure?
2. Can a study run with a stale/forged audit?
3. Can audit status be manufactured without an independent auditor?
4. Does a code change after audit always invalidate the seal?
5. Does seal verification occur before catalog access?
6. Can DEV/OOS be read before unlock through any path?
7. Do current timestamp docs match actual catalog semantics?
8. Is coincident 1s-before-1m ordering structurally enforced everywhere it matters?
9. Is exact ordered feature identity enforced?
10. Can an alternate/legacy runner bypass the gates?
11. Can a full run happen without a current sealed smoke?
12. Are downstream model fitting and OOS evaluation governed by the same state-machine discipline?

Red-team the controls; do not merely inspect the happy path.

Return:
- FLOW_CLEAR / FLOW_CLEAR_WITH_WARNINGS / FLOW_BLOCKED
- actual architecture/call path with file:line citations
- control matrix
- findings by CRITICAL/WARNING/NOTE
- bypass attempts and results
- smallest remediations + regression tests
- any redundant complexity that can safely be removed

Do not redesign the research study itself. The goal is to audit the framework and governance that execute approved studies.
```

---

# 22. What “good” looks like

The framework is mature enough when an independent reviewer can demonstrate:

```text
Research intent cannot drift silently.
SPEC cannot drift from intent silently.
Study YAML cannot drift from SPEC silently.
Compiled contract cannot be stale silently.
Causal defects are linted and independently audited before replay.
Contract defects are independently audited before replay.
Audit provenance cannot be forged by normal orchestrator workflow.
Audited code cannot change without authorization becoming stale.
NT runner cannot load market data without valid authorization.
OOS cannot be opened before its explicit unlock state.
Smoke cannot be skipped before an expensive full run.
Exact feature identity is enforced.
Multi-timeframe causal ordering is enforced.
Scratch tools are never hidden production dependencies.
Downstream model/evaluation steps inherit the same provenance discipline.
```

The objective is **not** to make the framework impossible to change. The objective is to ensure that every material change is explicit, reviewable, and causes the correct downstream gates to become stale.

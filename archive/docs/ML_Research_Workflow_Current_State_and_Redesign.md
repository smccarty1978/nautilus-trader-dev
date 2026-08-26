<!-- DOC-STATUS-BANNER -->
> **[STALE — SUPERSEDED]**
>
> Superseded by **docs/RESEARCH_WORKFLOW.md**.
>
> A pre-migration state assessment and redesign proposal. The redesign was implemented; this describes the system before it.
>
> Kept for its reasoning and for the audit trail. **Not a source of instructions.**
> Classification: `docs/DOCUMENT_MAP.md`.

---
title: "ML Trend Analysis Research Workflow"
subtitle: "Current State, Failure Analysis, and Proposed Modular Redesign"
author: "Architecture Review Brief"
date: "August 21, 2026"
---

## 1. Executive Summary

The ML Trend Analysis project has reached a point where the **research methodology is stronger than the workflow that is supposed to execute it**. The project has developed meaningful safeguards around causal timing, frozen research contracts, out-of-sample discipline, execution identity, feature provenance, population reconciliation, and NautilusTrader streaming validation. Those controls should not be discarded.

However, the orchestration layer around those controls has become operationally dysfunctional. A single bounded study—`Codex_clean_maturity_flip_rolling_5m_productivity`—has consumed roughly a week of iterative work and multiple large agent-token windows without completing a stable one-day smoke in a repeatable way. The dominant failure mode has not been model research. It has been **validation loops, identity churn, late discovery of basic runtime defects, over-broad test selection, and unclear boundaries between preparation, governance evidence, and execution state**.

Two independent architecture reviews now broadly agree on the direction of repair:

- Keep the **research contracts, causal guarantees, NT runtime, independent reviews, and result reconciliation**.
- Replace or substantially simplify the **workflow orchestration, execution-identity boundary, test-selection logic, and readiness process**.
- Add a **cheap readiness gate** that catches data-path, schema, import, output-interface, and basic event-dispatch errors before expensive validation.
- Split **repository/framework certification** from **study-specific preflight**.
- Make **PREPARE** the only stage that may mutate execution-affecting generated artifacts.
- Make **FREEZE** a true read-only identity boundary.
- Require one unchanged study state to proceed through **one preflight, one causal review, one contract review, one seal, and one smoke**.

The central design question is no longer whether more checks are needed. It is:

> **What is the minimum modular workflow that preserves causal and research integrity while allowing collectors and backtests to be spun up quickly, cheaply, and repeatably?**

This report documents where the project stands, what failed, what should be preserved, the proposed modular framework, machine/human-readable tracking requirements, and the questions that should be put to external reviewers.

---

## 2. What the Workflow Must Optimize For

The desired workflow is not simply “fast.” It must optimize several goals simultaneously.

### 2.1 Research integrity

The workflow must preserve:

- causal completed-bar semantics;
- no use of future information (`latest_source_ts_init <= observation_ts`);
- frozen population, target, censoring, and OOS contracts;
- explicit data provenance;
- explicit feature provenance;
- deterministic execution identity;
- candidate-to-terminal-observation reconciliation;
- independent causal and contract review before expensive research;
- human-readable evidence sufficient for research interpretation.

### 2.2 Research velocity

A normal study should not spend more time proving the workflow than performing the research. The target steady-state should be approximately:

| Stage | Desired operational target |
|---|---:|
| PREPARE | < 2 minutes |
| Cheap readiness | < 1 minute |
| FREEZE | < 30 seconds |
| Study-specific preflight | 1–5 minutes; hard target < 10 minutes |
| Causal review | 1 per unchanged frozen state |
| Contract review | 1 per unchanged frozen state |
| Seal | < 30 seconds |
| Re-freezes without deliberate execution change | 0 |
| Repeated full framework suites for ordinary study changes | 0 |

These are design targets, not yet proven benchmarks.

### 2.3 Token efficiency

Expensive reasoning models should be reserved for:

- ambiguous research design;
- independent causal review;
- contract adjudication;
- adversarial red-team review;
- interpretation of substantive results.

Cheap agents and deterministic scripts should handle:

- repository inventory;
- path resolution;
- hash comparisons;
- schema checks;
- test execution;
- progress monitoring;
- extraction of result summaries;
- formatting machine-readable status artifacts.

### 2.4 Error learning

Every error should improve future runs. The system needs an explicit **error registry / failure map** so that a defect discovered once becomes either:

1. a cheap readiness check;
2. a targeted test;
3. a framework certification invariant;
4. a contract rule; or
5. a documented non-issue/warning.

The goal is to prevent recurrence without turning every historical defect into a global blocker.

### 2.5 Human and machine readability

Every major stage should emit a compact machine-readable artifact and a concise human-readable summary derived from the same source of truth.

The system should not require an LLM to infer state from long logs.

---

## 3. Current Project Foundation That Is Worth Preserving

The current workflow contains substantial valuable work. The redesign should **not** throw away the following.

### 3.1 Declarative research authority

The intended authority chain is:

```text
research_decision.yaml
    > SPEC.md
    > study.yaml
    > compiled_study.json
    > runtime artifacts
```

The research decision should remain the authoritative definition of:

- population;
- target;
- censoring;
- session;
- instrument;
- train/dev/OOS years;
- feature policy;
- execution assumptions.

### 3.2 NautilusTrader streaming execution

The project correctly moved away from point-in-time joins toward streaming simulation. The intended validation standard is:

- NT BacktestEngine event loop for research validation;
- 1-second bars for fast strategy/feature validation;
- MBP-1 streamed execution where deployment realism is required;
- completed-bar timing and deterministic same-timestamp ordering.

This should remain central.

### 3.3 Causal runtime foundation

Useful primitives already exist:

- completed-bar registry/state;
- timeframe aggregation;
- sticky regime engine;
- central feature engine/registry;
- timestamp and chronology checks;
- same-timestamp ordering rules;
- causal lint and look-ahead review.

These are real research assets and should survive the redesign.

### 3.4 Feature governance and provenance

The project has a centralized feature library and lifecycle concepts. Feature definitions, tracker code, ordering, availability, and promotion history matter for reproducibility and model persistence.

### 3.5 Independent review roles

The distinction between:

- **causal/look-ahead review**, and
- **contract/research-fidelity review**

is valuable. The format can be simplified, but the independent reasoning roles should remain.

### 3.6 Result reconciliation

The project has correctly recognized that a candidate population can silently disappear or be retimed unless explicitly reconciled. Candidate/observation population accounting should remain a hard post-smoke invariant.

---

## 4. Canonical Data Layer: Major Recent Improvement

A significant portion of recent work resolved ambiguity caused by sparse 1-second trade bars.

### 4.1 Canonical dense 1-second sources

The project now has validated dense 1-second datasets for NQ, ES, and YM.

The canonical contract is:

```text
If a native 1s row exists:
    preserve OHLCV exactly
    is_fill = false

If an expected tradable second is absent:
    O = previous canonical close
    H = previous canonical close
    L = previous canonical close
    C = previous canonical close
    V = 0
    is_fill = true
```

No future interpolation is allowed.

Native rows override generic calendar conflicts. Calendar logic determines where synthetic fills are allowed; it does not delete source observations.

### 4.2 Current canonical datasets

| Instrument | Native rows | Fill rows | Total rows | Fill % |
|---|---:|---:|---:|---:|
| NQ | 111,274,121 | 106,911,484 | 218,185,605 | ~49.0% |
| ES | 103,735,591 | 114,443,786 | 218,179,377 | ~52.45% |
| YM | 73,630,462 | 144,531,225 | 218,161,687 | ~66.25% |

For all three, reported validation included:

- raw hashes unchanged;
- zero native mismatches;
- zero fill violations;
- zero duplicates;
- zero out-of-order rows;
- zero missing expected seconds;
- zero YTD overruns;
- 5s / 30s / 1m aggregation smoke PASS.

### 4.3 Important unresolved workflow lesson

Despite building the canonical NQ dense source, the later NT smoke still resolved to an old sparse NQ catalog. A 1-second continuity checker then failed on missing trade-print seconds, and the immediate remediation was to relax the checker.

This revealed a workflow defect more important than the checker itself:

> **The workflow did not prove that the physical data source reaching NautilusTrader was the data source declared by the research design.**

The redesigned readiness gate must verify actual runtime data binding, not merely configuration intent or catalog existence.

---

## 5. The Study That Exposed the Workflow Failure

The current bounded study is:

`Codex_clean_maturity_flip_rolling_5m_productivity`

Its intended purpose is to test clean maturity / rolling productivity context around regime flips under governed TRAIN/OOS rules.

This study became an effective stress test for the workflow because it exposed defects across multiple layers:

- data representation;
- collector population semantics;
- output interface;
- freeze identity;
- preflight scope;
- audit remediation authority;
- runtime source resolution.

The important point is that the study itself is no longer the primary problem. The fact that one bounded study exposed so many workflow loops means the orchestration should be redesigned before scaling research.

---

## 6. Chronology of Major Failure Classes

This section is intentionally framed as **failure classes**, not an exhaustive minute-by-minute log.

### 6.1 Undeclared population suppression

`CleanFlipCollector` accumulated several causal-audit remediations:

- `volume <= 1` rejection;
- `_last_rejected_feature_ns`;
- 1800-second cooldown;
- `_baseline_gap_needs_regime_reset`;
- `_baseline_gap_needs_rth_reset`.

Each remediation was locally conservative, but together they changed the effective research population without being declared in the authoritative research contract.

On a real 2023-10-02 diagnostic:

- 91,144 RTH 1-second decisions were observed;
- 36,776 satisfied the four stated established-regime gates;
- 0 candidates were emitted because implementation-only suppression remained active.

This was a governance failure: an auditor had effectively authored population policy through remediation.

**Lesson:** causal remediation may block execution, but it may not silently alter candidate identity, timing, population, target, or censoring. Such changes must escalate to `RESEARCH_DECISION_REQUIRED`.

### 6.2 Sparse-versus-dense data confusion

Raw trade bars were treated as though absence of a bar necessarily implied data corruption. This drove cooldown/reset logic and feature invalidation.

Forensic analysis showed most gaps were ordinary no-trade sparsity, roll/schedule effects, or benign historical conditions. This led to the canonical dense data layer described above.

**Lesson:** normalize market-clock semantics once at ingestion; do not make every collector reinterpret sparse source behavior.

### 6.3 Runtime still used the old sparse catalog

After the dense NQ parquet was built, the NT runtime still resolved the old NQ catalog path. This should have been caught before freeze/preflight/audit.

**Lesson:** readiness must prove the exact physical source used by the real loader.

### 6.4 Output schema failure hidden by zero candidates

The custom collector returned extra internal structural columns. The output manager correctly rejected unregistered columns, but early runs emitted zero candidates, so the invalid non-empty schema path was never exercised.

Once candidates appeared, the run crashed at output validation.

**Lesson:** readiness must test a synthetic or fixture-based **non-empty candidate and observation output surface**, not only empty dataframe behavior.

### 6.5 PREPARE/FREEZE identity churn

Generated execution-affecting artifacts such as:

- `compiled_study.json`;
- `phase0_source_manifest.json`

were regenerated after prior evidence had been produced. Because they were part of the execution hash, the composite changed and invalidated preflight/audit/seal evidence.

This caused repeated “fresh” composite hashes and repeated validation cycles.

**Lesson:** PREPARE is allowed to mutate execution inputs; FREEZE is not.

### 6.6 Preflight ran an over-broad framework suite

Recent analysis found that study preflight could select approximately:

- 46 framework test files;
- 789 static test definitions;
- while selecting 0 direct study tests in the current mapping state;
- the current study itself has roughly 38 study test definitions.

A mapping miss on changed study Python files caused fallback to the entire framework test population.

On the Windows VM, repository-wide deterministic preflight runs took roughly 13–15 minutes and involved 900+ pytest cases in prior runs.

**Lesson:** framework certification and study validation are different concerns and should have different invalidation boundaries.

### 6.7 Governance tooling was included in execution identity

The current execution closure has included files such as:

- preflight scripts;
- audit orchestration;
- seal tooling;
- smoke validation tooling;
- study tests;
- compile utilities.

Some of these validate or authorize runtime behavior but do not themselves execute the research strategy.

Meanwhile some actual runtime-affecting items, such as physical data/catalog authorization, were not adequately represented in the identity.

**Lesson:** execution identity currently hashes too much governance and too little execution reality.

---

## 7. Root Cause Taxonomy

The workflow problems can be grouped into five categories.

### A. Late feedback

Basic errors are discovered only after expensive stages.

Examples:

- wrong catalog;
- invalid non-empty output schema;
- missing runtime output interface;
- collector instantiation issues;
- stale generated manifests.

**Solution direction:** Cheap Readiness Gate.

### B. Over-broad invalidation

Changes unrelated to study runtime can invalidate the execution composite or trigger repository-wide validation.

Examples:

- study-test edits inside execution identity;
- governance-tool edits inside runtime identity;
- unmapped study changes triggering all framework tests.

**Solution direction:** minimal execution identity + framework certification.

### C. Under-inclusive runtime identity

Some things that can materially alter the run are not sufficiently bound.

Examples:

- actual physical data source/catalog;
- data provenance/version;
- OOS authorization artifacts;
- model artifact in ML-scoring studies.

**Solution direction:** include all true runtime inputs in the frozen identity.

### D. Blurred authority

Auditors, implementation code, and research contracts have not always had clearly enforced roles.

**Solution direction:** explicit authority matrix and escalation rules.

### E. Evidence fragmentation

State is spread across long logs, markdown reports, JSON status files, manifests, ledgers, and seal artifacts.

**Solution direction:** a compact stage-result schema with one machine-readable state record and generated human summary.

---

## 8. Independent Architecture Reviews: Current Consensus

Two independent architecture reviews have now been performed.

### 8.1 Antigravity conclusion

Antigravity's verdict was:

`CURRENT_FLOW_VIABLE_WITH_SIMPLIFICATION`

Its central recommendations were:

- add Cheap Readiness;
- split repository certification from study preflight;
- enforce PREPARE/FREEZE;
- keep execution hashing and independent audits;
- simplify phase0/audit handling;
- return quickly to research after the current smoke.

### 8.2 Codex conclusion

Codex's verdict was:

`PARTIAL_REBUILD_REQUIRED`

Codex argued that the research system should be retained but the **orchestration, identity definition, and test-selection model should be replaced**. It found concrete evidence that:

- preparation could mutate hashed files after prior evidence;
- preflight test selection fell back to broad framework testing;
- the dense source was not actually bound into runtime data resolution;
- zero-candidate execution masked output-schema defects;
- governance/tests were overrepresented in execution identity;
- actual data/runtime authorization was underrepresented.

### 8.3 Current synthesis

The most defensible combined position is:

> **Retain the research architecture; partially rebuild the workflow orchestration.**

This is narrower than a full rewrite but stronger than incremental tuning of the current preflight.

---

## 9. Proposed Modular Framework

The framework should be modular in **small, explicit stages**, with each stage owning one responsibility and emitting one stable contract.

### Module 1 — Research Contract

**Purpose:** define what is being studied.

**Primary artifact:** `research_decision.yaml`

Contains:

- study ID/version;
- instrument/session;
- population definition;
- target definition;
- censoring;
- train/dev/OOS windows;
- feature policy;
- data requirements;
- execution assumptions;
- declared exclusions.

**Rule:** implementation cannot silently override these semantics.

---

### Module 2 — PREPARE

**Purpose:** materialize every execution-affecting generated input exactly once.

Potential outputs:

- `compiled_study.json`;
- resolved strategy binding;
- resolved feature list/order;
- prepared feature/runtime manifest;
- model binding manifest where applicable;
- exact data-source declaration;
- any phase0 functionality that remains necessary.

**Rule:** PREPARE is the only stage allowed to mutate generated execution inputs.

**Design preference:** phase0 should likely be **merged** into PREPARE rather than maintained as an independent mutable identity layer, unless an external review establishes a unique invariant that requires it separately.

---

### Module 3 — Cheap Readiness Gate

**Purpose:** catch routine integration errors before expensive validation.

**Target:** ideally < 60 seconds.

Required checks:

1. Contract compiles deterministically.
2. Exact physical data source resolves.
3. Dense source requirement is satisfied where declared.
4. Requested dates are available.
5. Small data sample loads through the **same runtime loader** NT will use.
6. 1s/1m timestamp semantics are correct.
7. Strategy imports.
8. Strategy/config/collector instantiates.
9. Declared features resolve from the registry in the frozen order.
10. Output interface exists.
11. Synthetic/fixture **non-empty** candidates schema validates.
12. Synthetic/fixture non-empty observations schema validates.
13. Terminal-disposition interface reconciles.
14. Bounded NT event dispatch works.
15. Execution identity resolves twice read-only and produces the same hash.
16. No execution-affecting generated artifact is stale.

**Output:** `readiness.json` plus a short human summary.

**Failure rule:** stop here. Do not consume causal-audit or preflight tokens until readiness is clear.

---

### Module 4 — FREEZE

**Purpose:** create a stable identity for exactly what can affect the study execution.

**Output:** `frozen_execution_manifest.json`

This evidence artifact should itself be outside the execution identity.

The frozen identity should include at least:

- runtime/strategy code actually executed;
- compiled research contract;
- feature definitions/order actually used;
- model artifact/hash where applicable;
- target/population implementation bindings;
- physical data source/catalog/version/hash or provenance manifest;
- session/calendar semantics that affect runtime;
- OOS authorization artifacts;
- relevant execution parameters.

It should generally **exclude**:

- tests;
- audit reports;
- preflight scripts;
- audit orchestration code;
- seal generation code;
- log files;
- run IDs;
- timestamps that do not affect runtime;
- analysis reports.

**Hard invariant:** after FREEZE, no execution-bound file changes.

---

### Module 5 — Framework Certification

**Purpose:** certify shared infrastructure independently of ordinary study execution.

Triggered when shared framework closure changes, such as:

- NT runtime;
- central FeatureEngine;
- compiler;
- data loader;
- session/timestamp engine;
- shared output manager;
- governance-critical infrastructure.

Runs:

- broad framework tests;
- relevant mutation/red-team tests;
- shared schema contracts;
- feature registry lifecycle tests;
- core causal invariants.

**Output:** a durable framework certificate bound to a shared-framework hash.

Ordinary studies reuse this certificate until its certified closure changes.

---

### Module 6 — Study Preflight

**Purpose:** validate the frozen study, not recertify the whole repository.

Runs:

- study-specific unit/integration tests;
- targeted shared tests selected from the frozen execution dependency closure;
- study causal lint;
- research-decision/spec fidelity;
- selected-feature resolution;
- readiness artifact verification;
- framework certificate applicability.

**Target:** 1–5 minutes.

**Selection rule:** do not use broad dirty-repo `git diff HEAD` fallback as the principal selector. Selection should be based on the frozen study dependency closure and applicable framework certificate.

---

### Module 7 — Independent Reviews

Run in parallel when possible.

#### Causal review

Checks:

- timing;
- completed-bar semantics;
- future-source usage;
- same-timestamp ordering;
- causal feature availability;
- target observation ordering.

#### Contract review

Checks:

- population;
- target;
- censoring;
- session/instrument;
- feature binding;
- OOS split;
- deliverable fidelity.

**Authority rule:** reviewers may return:

- `CLEAR`;
- `BLOCKED`;
- `RESEARCH_DECISION_REQUIRED`.

They may not silently implement semantic changes.

**Evidence format:** JSON is preferable for machine state, with optional Markdown narrative. Format simplification must not eliminate independent reasoning.

---

### Module 8 — Attestation Seal

**Purpose:** attest that one frozen identity has:

- readiness CLEAR;
- applicable framework certification;
- study preflight CLEAR;
- causal review CLEAR;
- contract review CLEAR.

The seal must not regenerate or modify execution inputs.

---

### Module 9 — Bounded NT Smoke

**Purpose:** prove real runtime behavior on a small representative window before full research.

Required telemetry should include a population funnel:

```text
runtime decisions
→ authoritative population gates
→ declared_population_eligible
→ candidates_emitted
→ declared exclusions
→ implementation-only exclusions
→ feature-ready / feature-unavailable
→ terminal dispositions
```

Hard invariants:

```text
implementation_only_exclusions == 0

declared_population_eligible
    ==
candidates_emitted + declared_contract_exclusions

future_source_violations == 0
```

The smoke must exercise non-empty outputs when the study is expected to produce candidates.

---

### Module 10 — Result Reconciliation and Analysis

**Purpose:** convert runtime outputs into authoritative research evidence.

Should produce:

- candidate population summary;
- observation/disposition summary;
- feature availability summary;
- target prevalence;
- data period/coverage;
- model metrics where applicable;
- economic metrics where applicable;
- warnings/limitations;
- exact hashes for code/contract/data/model/features.

The Analysis Harness should operate on result manifests tied to the frozen execution identity.

---

## 10. Proposed Error Registry / “Map for Removing Errors from Future Runs”

A central design requirement should be an **Error Knowledge Base**.

Each failure receives a stable `failure_id`, for example:

```text
DATA_SOURCE_MISMATCH
NONEMPTY_OUTPUT_SCHEMA_MISMATCH
POST_FREEZE_MUTATION
STUDY_TEST_SELECTOR_FALLBACK
UNDECLARED_POPULATION_EXCLUSION
DENSE_TIMELINE_GAP
FEATURE_BINDING_MISMATCH
FUTURE_SOURCE_VIOLATION
```

Each registry entry should record:

| Field | Purpose |
|---|---|
| `failure_id` | Stable machine identifier |
| `first_seen` | Historical provenance |
| `symptom` | Human explanation |
| `root_cause` | Verified cause |
| `detection_stage` | Where it was discovered |
| `ideal_detection_stage` | Where it should be detected in future |
| `prevention_control` | Readiness/test/certification/contract |
| `test_id` | Regression test if applicable |
| `severity` | BLOCK / WARN / INFO |
| `execution_semantics_affected` | population/data/target/etc. |
| `owner_module` | module responsible |
| `status` | OPEN / PREVENTED / ACCEPTED |
| `notes` | concise context |

### Example mappings from this week

| Failure | Was found at | Should be found at |
|---|---|---|
| Runtime using old sparse catalog | NT smoke | Cheap readiness |
| Extra collector output columns | End-of-day output validation | Cheap readiness non-empty schema probe |
| Post-freeze regenerated phase0 | Preflight/audit churn | FREEZE mutation guard |
| 900+ tests due selector fallback | Full preflight | Preflight selector self-check |
| Undeclared population suppression | Real population diagnostic | Contract audit + population reconciliation |

This converts painful incidents into permanent workflow improvements without adding global blockers indiscriminately.

---

## 11. Human- and Machine-Readable Tracking

The workflow needs one common stage-status schema.

### 11.1 Machine-readable run state

Example conceptual structure:

```json
{
  "study_id": "...",
  "workflow_version": "vNext",
  "execution_id": "sha256...",
  "framework_certificate": "sha256...",
  "current_stage": "STUDY_PREFLIGHT",
  "stages": {
    "prepare": {"status": "PASS", "artifact": "...", "elapsed_s": 12.4},
    "readiness": {"status": "PASS", "artifact": "...", "elapsed_s": 8.1},
    "freeze": {"status": "PASS", "composite": "..."},
    "study_preflight": {"status": "RUNNING"},
    "causal_review": {"status": "PENDING"},
    "contract_review": {"status": "PENDING"},
    "seal": {"status": "PENDING"},
    "smoke": {"status": "PENDING"}
  },
  "blocking_failure_ids": [],
  "warnings": [],
  "next_action": "WAIT_FOR_STUDY_PREFLIGHT"
}
```

### 11.2 Human-readable status card

Generated from the same state:

```text
STUDY: Codex_clean_maturity_flip_rolling_5m_productivity
EXECUTION: 948c22...

PREPARE       PASS   12s
READINESS     PASS    8s
FREEZE        PASS    2s
PREFLIGHT     RUNNING
CAUSAL AUDIT  PENDING
CONTRACT      PENDING
SEAL          PENDING
SMOKE         PENDING

BLOCKERS: none
NEXT: wait for study preflight
```

A human should be able to answer “where are we?” in under 10 seconds.

### 11.3 Compact agent handoff card

Every agent session should receive only:

- study ID;
- current execution hash;
- current stage;
- exact task;
- relevant file list;
- current blockers;
- forbidden actions;
- expected output schema.

This reduces cache/context/token waste.

---

## 12. Human- and Machine-Readable Research Results

Each completed study should produce a **Result Manifest** as the machine authority and a generated **Research Summary** for humans.

### 12.1 Result Manifest

Suggested sections:

```json
{
  "study": {},
  "execution_identity": {},
  "data": {},
  "population": {},
  "features": {},
  "target": {},
  "model": {},
  "validation": {},
  "results": {},
  "economics": {},
  "limitations": [],
  "artifacts": {}
}
```

For ML studies, `model` should include:

- algorithm;
- serialized model path/hash;
- feature order/hash;
- training years;
- threshold/calibration;
- training code hash;
- metrics by split.

For trading studies, `economics` should include:

- trade count;
- cost assumptions;
- EV/trade;
- total PnL;
- win rate;
- drawdown;
- exposure;
- year/session/direction breakdowns;
- sensitivity if predeclared.

### 12.2 Human Research Summary

A concise report generated from the manifest:

1. Executive verdict.
2. Research question.
3. Population and target.
4. Data and OOS split.
5. Method.
6. Primary findings.
7. Robustness/caveats.
8. What the finding does not establish.
9. Decision.
10. Next experiment.

No substantive metric should appear only in prose without machine-readable backing.

---

## 13. Token-Efficient Agent Architecture

The workflow should route tasks by reasoning need.

### Tier 0 — deterministic scripts

Use for:

- hashes;
- schema validation;
- manifest creation;
- test selection;
- test execution;
- data coverage;
- readiness checks;
- population arithmetic;
- report rendering.

### Tier 1 — cheap read-only agents

Use for:

- repo scanning;
- locating definitions;
- extracting changed files;
- summarizing logs;
- comparing manifests;
- result triage.

### Tier 2 — bounded coding agents

Use for:

- known, already-adjudicated implementation tasks;
- small module changes;
- adding regression tests;
- refactoring within a frozen specification.

### Tier 3 — expensive reasoning agents

Use only for:

- research design ambiguity;
- causal audit;
- contract audit;
- red-team architecture review;
- deciding whether a finding changes research semantics;
- interpreting empirical results.

### Token control rule

If a deterministic or cheap agent can answer a question with file paths/hashes/tests, a high-reasoning model should not be asked to rediscover it.

---

## 14. Framework Certification Invalidation Model

A key unresolved design detail is how framework certificates become stale.

A practical model is dependency-based.

### Framework certificate should invalidate when:

- shared NT runtime changes;
- central feature engine/registry semantics change;
- compile schema changes;
- data loader/catalog resolver changes;
- timestamp/session engine changes;
- output manager changes;
- core target/population engines change;
- certification tests themselves change materially.

### Framework certificate should not invalidate merely because:

- a study parameter changes;
- a study-specific collector changes;
- a study test changes;
- an audit report is written;
- a result file is generated;
- a log/run ID changes.

A study preflight then checks whether its frozen dependency closure is covered by a valid certificate.

---

## 15. Proposed Execution Identity Boundary

The execution identity must be minimal but complete.

### Include

- exact research contract/compiled representation;
- executable strategy/collector code;
- shared runtime code actually imported by the study;
- feature implementation files actually bound;
- feature list/order;
- target implementation;
- population implementation;
- actual physical data source/provenance identity;
- session/calendar semantics;
- model artifact and model runtime where applicable;
- OOS authorization;
- cost/execution assumptions where relevant.

### Exclude

- tests;
- preflight implementation;
- causal-audit implementation;
- contract-audit implementation;
- seal implementation;
- result validation implementation;
- audit reports;
- logs;
- human reports;
- run timestamps/IDs.

### Important nuance

Governance tooling must still be versioned and certified; it simply should not cause the **research execution identity** to change when it does not alter the execution itself.

---

## 16. Proposed Migration Strategy

A large rewrite would create another long infrastructure project. The migration should be bounded.

### Phase 1 — Specify boundaries, no behavior change

Write and independently review:

- execution identity specification;
- PREPARE/FREEZE contract;
- framework certificate invalidation contract;
- auditor authority contract;
- readiness gate contract;
- stage status/result schemas.

No study semantics should change in this phase.

### Phase 2 — Replace orchestration only

Implement:

- PREPARE command;
- Cheap Readiness Gate;
- read-only FREEZE;
- targeted Study Preflight;
- framework certification reuse;
- simplified review ingestion/attestation;
- common workflow status card.

Do not rewrite the NT runtime, FeatureEngine, regime engine, or Analysis Harness unless a concrete blocker requires it.

### Phase 3 — Prove with one representative study

From a clean checkout, run:

`Codex_clean_maturity_flip_rolling_5m_productivity`

for 2023-10-02 with:

- one PREPARE;
- one readiness PASS;
- one FREEZE;
- two identical read-only identity resolutions;
- one targeted preflight;
- one causal review;
- one contract review;
- one seal;
- one NT smoke;
- one deterministic reconciliation;
- zero manual execution-affecting intervention after FREEZE;
- zero repeated preflight/audit cycles.

If that succeeds, **stop infrastructure work and resume research**.

---

## 17. Decisions That Should Not Be Made Yet

Several ideas are promising but should remain open until external review.

### 17.1 Delete phase0 vs merge phase0

Current preference: **MERGE**, unless it is shown to enforce no unique invariant.

### 17.2 JSON-only audits

Simplifying report format is desirable, but independent causal and contract reasoning must remain. The format is secondary to reviewer independence and explicit findings.

### 17.3 Exact runtime budgets

Targets such as readiness <15 seconds or study preflight <30 seconds are useful aspirations, but should not be contractual until measured.

### 17.4 One collector architecture vs custom collectors

The long-term preference is generic reusable population/feature/target engines, but custom collector support may remain necessary for genuinely distinct semantics. The workflow should make those distinctions explicit instead of hiding them in implementation.

### 17.5 Scope of framework certification

The correct shared closure and invalidation mechanism needs adversarial review to avoid either stale certification or a return to “rerun everything.”

---

## 18. Questions for External Reviewers

The following are the questions on which further advice would be most valuable.

### Architecture

1. Is the proposed modular stage architecture the minimum safe design, or are there still redundant stages?
2. Should PREPARE and FREEZE be separate commands or one command with a hard internal transaction boundary?
3. Should framework certification be repository-wide, dependency-closure based, or layered by subsystem?
4. Is there a better way to manage generated execution artifacts than the proposed PREPARE-only rule?

### Execution identity

5. What exactly belongs in a reproducible research execution identity?
6. How should large market-data artifacts be bound—full file hash, immutable manifest, partition hashes, catalog version, or another method?
7. Should governance tool versions be part of execution identity, framework certification, or both?

### Testing

8. What is the safest mechanism for selecting targeted tests from a frozen dependency closure?
9. How should the system behave when a changed file is unmapped to tests—block, certify broader scope, or require explicit mapping?
10. How can non-empty output/schema paths be validated cheaply and generically?

### Agent orchestration / token use

11. What information should an agent receive at each stage to minimize context while remaining safe?
12. How should deterministic findings be packaged so expensive reasoning agents never need to reread the repository?
13. What tasks should be explicitly prohibited from high-reasoning models?

### Error learning

14. Is the proposed failure registry sufficient to turn one-off defects into future preventative controls?
15. How can the registry avoid becoming another over-broad governance layer?
16. Should every fixed failure require a regression test, or should some be documented warnings/readiness checks only?

### Research results

17. Is one canonical machine-readable Result Manifest plus a generated human report the right output contract?
18. What fields are essential for reproducible ML/trading research but currently missing from the proposed manifest?

### Governance

19. Is one independent causal review and one independent contract review sufficient for bounded studies?
20. What controls are necessary to prevent auditors from changing research semantics while still allowing them to require causal remediation?

---

## 19. Proposed Non-Negotiable Design Principles

Regardless of the final implementation, the following principles appear justified by the failures observed.

1. **Fail early, cheaply.** Integration failures should occur before expensive review.
2. **Normalize data semantics once.** Collectors should not repeatedly reinterpret sparse market data.
3. **Research contract owns semantics.** Implementation and auditors cannot silently redefine population or target.
4. **PREPARE mutates; FREEZE does not.**
5. **Identical execution state must produce identical identity.**
6. **Framework validation and study validation are separate concerns.**
7. **Execution identity includes everything that affects the run and excludes evidence that merely validates the run.**
8. **No silent candidate loss.** Population must reconcile deterministically.
9. **Every recurring error gets moved earlier in the pipeline.**
10. **One source of truth, two views.** Machine JSON drives concise human reporting.
11. **Use expensive reasoning only where judgment is required.**
12. **Infrastructure work has a stop condition.** Once one representative study runs end-to-end without validation loops, research resumes.

---

## 20. Current Recommended Position

The current recommendation is:

**`PARTIAL_REBUILD_REQUIRED`**

But the phrase should be interpreted narrowly:

> **Retain the research architecture. Rebuild the orchestration boundary.**

Preserve:

- research decision contracts;
- NT runtime;
- causal completed-bar semantics;
- feature registry/engine;
- OOS discipline;
- causal review;
- contract review;
- result reconciliation;
- Analysis Harness.

Redesign:

- execution identity;
- PREPARE/FREEZE lifecycle;
- readiness checks;
- framework certification;
- study preflight selection;
- audit evidence ingestion;
- workflow state tracking.

The redesign should be considered successful only when the current representative study can proceed from a clean state to a valid one-day NT smoke with **no repeated validation cycle and no manual execution-affecting changes after FREEZE**.

---

## Appendix A — Proposed End-to-End State Machine

```text
RESEARCH DECISION
        |
        v
PREPARE
  - compile
  - bind features/model/data
  - generate execution-affecting derived inputs
        |
        v
CHEAP READINESS
  - real data path
  - sample loader
  - timestamp semantics
  - instantiate collector
  - non-empty schema
  - bounded NT dispatch
  - double identity resolution
        |
        v
FREEZE
  - minimal execution identity
        |
        +--------------------------+
        |                          |
        v                          v
FRAMEWORK CERTIFICATE CHECK    STUDY PREFLIGHT
(reuse if applicable)          (targeted only)
        |                          |
        +-------------+------------+
                      |
                      v
           CAUSAL + CONTRACT REVIEWS
                      |
                      v
                 ATTESTATION SEAL
                      |
                      v
                ONE-DAY NT SMOKE
                      |
                      v
              RESULT RECONCILIATION
                      |
             +--------+--------+
             |                 |
             v                 v
       FULL COLLECTION       BLOCK
             |
             v
      GOVERNED ANALYSIS
             |
             v
       RESULT MANIFEST
             |
             v
    HUMAN RESEARCH SUMMARY
```

---

## Appendix B — Source Basis for This Brief

This brief synthesizes:

- the current project history and recent workflow failures;
- the Antigravity operational governance/architecture audit (`CURRENT_FLOW_VIABLE_WITH_SIMPLIFICATION`);
- the independent Codex architecture audit (`PARTIAL_REBUILD_REQUIRED`);
- recent canonical dense 1-second data work for NQ/ES/YM;
- recent CleanFlipCollector suppression, runtime source, output-schema, preflight, freeze, and audit findings.

It intentionally distinguishes **current evidence** from **proposed architecture**. Performance targets and final component dispositions remain proposals until independently reviewed and benchmarked.

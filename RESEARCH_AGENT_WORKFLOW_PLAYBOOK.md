# ML Trend Analysis — Research Agent Workflow Playbook

**Purpose:** Give a research/orchestration agent enough context to route each task through the repo's governed workflow with minimal unnecessary Opus usage, minimal repeated discovery, and clear stop conditions.

**Current workflow-hardening commit:** `42d9ec5f55e9cbaee74cbf8a353daeaf5c6fc778`

**Current workflow verdict:** `RED_TEAM_CLEAR_WITH_WARNINGS`

**Interpretation:** The governed workflow is considered ready to freeze and use. The remaining known limitations are explicit and bounded; they should not trigger another generalized infrastructure-hardening cycle unless a concrete research-invalidating bypass is demonstrated.

## Current repo state at this handoff

- Hardened implementation is committed and pushed at `42d9ec5f55e9cbaee74cbf8a353daeaf5c6fc778`.
- Working tree was clean at final verification.
- Full deterministic preflight on `studies/es_wick_imbalance_acceptance_v2` has achieved genuine `CLEAR / Audit Ready: True` without bypass flags.
- Current preflight evidence schema v2 is self-bound and matches the current execution composite (`2f2cd651…ba00787` at the time of final verification).
- The previously issued causal audit, contract audit, and `artifacts/preexec_audit_seal.json` still bind the older composite (`a580bc38…`) and are therefore **stale by design**. Seal generation and seal verification correctly refuse them.
- No fresh causal/contract audits or new PREEXEC seal have yet been issued against the hardened composite.
- Therefore the next operational step is **fresh independent causal audit + fresh independent contract audit → fresh PREEXEC seal → one authorized Sep-03 ES acceptance smoke → deterministic validation**.
- Do not run Sep-04/Sep-05 or resume NQ research until that one-day acceptance path clears.

---

# 1. Primary operating principle

The repo exists to answer research questions, not to maximize governance sophistication.

Use this default rule:

> **Fix only defects capable of invalidating causal correctness, research population, OOS separation, authoritative contracts, execution identity, or mandatory gate enforcement. Everything else goes to backlog.**

The normal direction of work should be:

```text
RESEARCH QUESTION
    ↓
research_decision.yaml
    ↓
study specification / compilation
    ↓
feature/runtime readiness
    ↓
deterministic preflight
    ↓
independent causal + contract audits
    ↓
PREEXEC_AUDIT_SEAL
    ↓
NO CODE CHANGES
    ↓
bounded NT smoke
    ↓
deterministic smoke validation
    ↓
governed analysis
    ↓
research conclusion
    ↓
next hypothesis
```

Do not turn every warning, stylistic concern, or future-proofing idea into a new infrastructure project.

---

# 2. Canonical authority hierarchy

For governed studies, use the following authority order:

```text
research_decision.yaml
    > SPEC.md
    > study.yaml
    > compiled_study.json
    > runtime artifacts
```

`research_decision.yaml` defines the research intent and must be treated as upstream of implementation.

It should capture at minimum:

- research question;
- fixed baseline;
- variables allowed to change;
- feature policy;
- chronology / TRAIN-DEV-OOS policy;
- allowed and prohibited changes;
- comparison logic;
- terminal decision question.

Agents must not silently redesign the experiment when implementing it.

If the requested analysis cannot be expressed under the declared decision contract, stop with an explicit contract gap rather than improvising a new study.

---

# 3. Canonical workflow — full sequence

## Stage 0 — Frame the research question

Before code or execution, define the exact question.

A good research question should identify:

- instrument;
- population;
- observation timestamp;
- target/event;
- horizon;
- feature set or feature family;
- fixed baseline;
- comparison;
- chronology;
- terminal decision.

Example pattern:

```text
Question:
Does <feature/family> improve discrimination of <target>
within <population> at <observation time>, relative to <baseline>,
using TRAIN <dates>, DEV <dates>, OOS <dates>?

Allowed changes:
- ...

Prohibited changes:
- ...

Stop condition:
- ...
```

Do not begin implementation until the research question is sufficiently bounded.

---

## Stage 1 — Create or verify `research_decision.yaml`

The research agent should ensure the decision contract exists before implementation.

The agent should verify:

- the question is precise;
- the baseline is frozen;
- only declared variables may change;
- chronology is explicit;
- OOS is protected;
- no hidden tuning path exists;
- terminal decision is defined.

If ambiguity remains that could materially alter the study, ask one focused clarification question rather than allowing the coding agent to decide.

---

## Stage 2 — Compile the study contract

Use the canonical study factory / schema path.

Relevant generic infrastructure includes:

- `research/schemas/study_spec.py`
- `research/study_types/`
- `research/engines/`
- `scripts/create_study.py`
- `scripts/compile_study.py` or the repo's current canonical compiler entrypoint

Expected study authority includes:

- `research_decision.yaml`
- `SPEC.md`
- `study.yaml`
- `compiled_study.json`
- machine-readable deliverables contract
- generated study contract tests where applicable

Do not create a bespoke study runner or collector when the generic framework can express the study.

If the generic framework cannot express the required study, stop with a capability-gap report rather than creating a parallel workflow.

---

## Stage 3 — Feature readiness

Before execution, verify the feature surface.

Requirements:

1. Search for a semantic duplicate before creating a new feature.
2. Use the centralized feature library / registry.
3. Bind the feature to the actual runtime tracker.
4. Define source timeframe, availability semantics, warmup, reset policy, and null policy.
5. New features remain `provisional` until valid promotion evidence exists.
6. Do not self-promote a feature to `verified` merely because implementation tests pass.

Current important feature-governance controls:

- feature lifecycle baseline is pinned and sealed;
- the grandfather set may shrink but cannot silently expand;
- promotion evidence is bound to reviewed implementation identity;
- all-null declared features fail closed;
- undeclared feature outputs are rejected;
- declared feature order/identity is checked;
- registry/contract disagreement fails closed.

### Feature lifecycle principle

```text
new feature
    ↓
provisional
    ↓
implementation tests
    ↓
causal/runtime validation
    ↓
recorded promotion evidence
    ↓
verified
```

Do not skip this sequence.

---

## Stage 4 — Execution closure and source identity

Before any audit or run, the repo resolves the actual execution closure.

The closure must include:

- runtime code;
- transitive repo-local imports;
- ancestor package `__init__.py` files;
- relative imports;
- namespace-package imports;
- multi-alias imports such as `from pkg import a, b`;
- subprocess-invoked mandatory governance scripts;
- authoritative static governance files that can alter gate behavior;
- sealed study authority / deliverables authority.

Current hardening explicitly covers the previously discovered failure where multi-alias namespace imports could execute more modules than were included in `file_hashes`.

The execution composite is derived from the sealed file set.

Required invariant:

> If code or authoritative configuration capable of changing governed execution changes, the execution composite must change.

If closure coverage is incomplete or unresolved dependencies exist, the workflow must not report 100% governance coverage.

---

## Stage 5 — Deterministic preflight

Run the canonical research preflight.

The preflight is mandatory before audit readiness.

A valid preflight must prove:

- required check set is complete;
- every mandatory check actually executed;
- every mandatory check passed;
- no mandatory check was skipped;
- no mandatory check timed out;
- evidence is bound to the current study;
- evidence is bound to the current execution composite;
- the evidence schema is current;
- no active contradictory BLOCKED failure packet exists.

Important current behavior:

- `--skip-tests` may exist for diagnostics, but it cannot produce audit-ready evidence.
- `{"audit_ready": true}` is not sufficient evidence.
- stale preflight evidence from another composite is refused.
- stale preflight evidence from another study is refused.

The current mandatory preflight was measured at roughly 6–7 minutes on the acceptance fixture and has a measured timeout budget of 900 seconds.

Do not optimize this unless it becomes a material workflow bottleneck.

---

## Stage 6 — Independent causal and contract audits

After deterministic preflight clears, run two independent reviews:

1. **Causal audit**
2. **Contract audit**

These are distinct roles and should use distinct declared reviewer identities.

### Causal audit asks

- Is every feature available at the declared observation time?
- Is there any look-ahead or future-source dependency?
- Are same-timestamp event-order rules causal?
- Are targets/censoring defined causally?
- Are session boundaries correct?
- Are source timestamps measured from the correct instrument/catalog?
- Can any runtime path use information unavailable in live execution?

### Contract audit asks

- Does implementation match `research_decision.yaml` and the compiled study?
- Are deliverables reachable and complete?
- Are authorized dates/modes respected?
- Is the actual population the declared population?
- Does the runtime feature surface match the declared feature surface?
- Are prohibited changes absent?

### Provenance limitation

Current audit provenance is intentionally conservative:

```text
provenance_strength = DECLARED_IDENTITY_ONLY
independence_proven = false
```

An attached transcript/artifact may be hashed for reference, but the repo does not claim that a hash proves a real independent human review session occurred.

Do not upgrade this claim without a genuine authenticated session-evidence contract.

---

## Stage 7 — Audit lineage

Audit pass history is protected by committed Git/HEAD lineage state.

Current design:

- lineage anchor lives under `audit_lineage/`;
- the real acceptance study has a committed lineage anchor;
- anchor carries monotonic issuance information / hash-chain state;
- working-tree deletion of anchor or ledger fails closed;
- working-tree rollback of anchor and ledger fails closed against committed HEAD;
- corrupt or foreign lineage state fails closed;
- production lineage cannot be silently redirected with the former environment override;
- legitimate new-study identity has explicit bootstrap semantics.

### Known limitation: Git HEAD is the durability boundary

The workflow protects lineage relative to the current committed `HEAD`.

It does **not** protect against an authorized forward commit that deliberately replaces/reset lineage state, nor does it protect against rewritten Git history.

Example:

```text
committed lineage
    ↓
working-tree reset
    ↓
workflow refuses
    ↓
operator explicitly commits reset
    ↓
new HEAD becomes authority
```

This is considered a repository change-governance issue, not an automated runtime bypass.

Do not reopen the lineage design solely to eliminate this limitation unless the project adopts an external append-only trust anchor, signed history, protected service, or similar stronger infrastructure.

---

## Stage 8 — PREEXEC audit seal

After both audits clear, issue the pre-execution seal.

The seal binds audit authority to the execution composite.

Required behavior:

- stale causal audit → refuse;
- stale contract audit → refuse;
- changed code/config after audit → refuse;
- changed execution composite → refuse;
- incomplete audit evidence → refuse;
- seal generation must fail before writing when the audited surface is stale.

### Critical operating rule

```text
AUDITS CLEAR
    ↓
PREEXEC_AUDIT_SEAL
    ↓
NO EXECUTION-AFFECTING CODE CHANGES
```

Any execution-affecting change after audit invalidates the audits and smoke authorization.

Do not “patch one thing” after seal and continue.

---

## Stage 9 — Bounded NautilusTrader smoke

Run the smallest authorized live-runtime smoke sufficient to prove end-to-end behavior.

For acceptance-style work:

- one authorized day is usually enough initially;
- do not immediately expand to more dates;
- do not use DEV/OOS for framework debugging;
- do not perform economic interpretation during an infrastructure acceptance smoke.

The smoke must run through the canonical NautilusTrader runtime / BacktestEngine path.

Do not replace it with pandas joins or point-in-time reconstruction.

Expected path:

```text
streamed market data
    ↓
runtime population generation
    ↓
live feature calculation
    ↓
model/target logic if applicable
    ↓
output manager
    ↓
validated run artifacts
```

---

## Stage 10 — Deterministic smoke validation

Validate the run through canonical validators.

Checks should include as applicable:

- current seal is valid;
- run date is authorized;
- required deliverables are present;
- declared feature surface matches produced surface;
- no declared feature is never emitted;
- null policy is respected;
- no undeclared feature columns enter the feature surface;
- candidate/observation identities reconcile;
- no duplicates/orphans/unresolved candidates;
- source timestamps are causal;
- session semantics are correct;
- target terminal dispositions reconcile;
- output identity matches the study contract.

Do not report a smoke as accepted if the validator fails.

---

## Stage 11 — Governed analysis

For authoritative research conclusions, analysis must go through the canonical governed analysis path.

Policy:

```text
validated collection
    ↓
research/analysis/
    ↓
AnalysisSpec / identity / partition / join / completeness contracts
    ↓
authoritative result
```

Pandas/Polars are computation libraries, not alternate governed research workflows.

Allowed scratch usage:

- debugging;
- forensic inspection;
- one-off diagnostics;
- reproducing an isolated calculation.

Scratch/ad-hoc results are **NON-AUTHORITATIVE**.

If the governed analysis harness cannot express the requested analysis, stop with:

```text
ANALYSIS_HARNESS_GAP
```

Do not silently substitute a scratch pandas workflow and publish the result as validated research.

### Current known weakness

The latest Red Team previously reported that `research/analysis/` was absent from the reviewed main tree at that time even though workflow docs referred to it as canonical.

Treat this as a known capability/backlog item unless/until the current branch clearly contains the frozen Analysis Harness implementation.

Before an authoritative study conclusion, verify the governed analysis package actually exists in the branch being used.

---

# 4. Current known weaknesses / backlog

These items are known and should **not** automatically reopen infrastructure hardening.

## A. Git HEAD lineage boundary

Described above.

Severity: known design limitation.

Does not block current research under the declared Git-trust model.

---

## B. `authorized_dates` may be fail-open when omitted

Historical Red Team warning:

- if `execution.data_requirements.authorized_dates` is omitted, some authorization logic may have no date set to enforce.

For any new governed study, require explicit authorized dates in the research/study contract.

Research-agent rule:

> Never submit a governed run prompt with implicit date authorization.

Always state exact authorized dates/modes.

---

## C. Promotion evidence line-ending hashing

Historical warning:

- feature-promotion evidence used raw-byte hashing at one point, which could differ across CRLF/LF checkouts.

The execution/seal identity itself has been hardened for logical line-ending reproducibility.

Before relying on feature promotion across heterogeneous checkouts, verify the promotion implementation uses the current canonical hash semantics.

Do not treat this as a blocker while promotions are absent/unneeded.

---

## D. Generated study contract tests may not be part of mandatory preflight selection

Historical warning:

- generated `studies/<id>/tests/test_study_contracts.py` may not automatically enter the mandatory `CAUSAL_INVARIANTS` test set.

The deterministic contract/fidelity gates remain authoritative.

Do not assume a generated test was executed merely because it exists.

---

## E. Feature metadata fallback duplication

Historical warning:

- feature-surface metadata handling may fall back to a hard-coded metadata list when the study contract does not declare metadata columns;
- related wrapper signatures may not expose `metadata_columns` consistently.

Research-agent rule:

> Prefer explicit feature/metadata schema in the study contract rather than relying on fallback behavior.

---

## F. Governed Analysis Harness availability

As noted above, confirm `research/analysis/` exists in the active branch before authoritative analysis.

If absent:

```text
ANALYSIS_HARNESS_GAP
```

Do not create a parallel scratch analysis pipeline.

---

## G. Historical/stale unrelated study seals

At least one unrelated Gemini study has a known stale seal caused by an older `data_plan.py` hash mismatch.

This is pre-existing debt and should not be “fixed” during unrelated studies merely to make a global test count cosmetically perfect.

Re-seal a study only when that study is intentionally brought back into governed use.

---

## H. `runs/` repository policy is untidy

The repo historically tracks some lightweight run metadata while parquet outputs are ignored.

Do not perform opportunistic cleanup during research.

Treat run-retention/gitignore policy as a separate repository-maintenance decision.

---

# 5. Verified runtime areas that should not be casually reopened

The following areas have already received substantial causal/adversarial validation and should be treated as stable unless a new concrete failure is demonstrated:

- 300-second target horizon semantics;
- exact-horizon same-timestamp race correction;
- candidate terminal reconciliation;
- POSITIVE / NEGATIVE / CENSORED dispositions;
- session-end censoring;
- ES timestamp measurement from ES catalog;
- canonical session boundary semantics;
- feature wick formula;
- run lifecycle classification;
- exact-date enforcement when authorized dates are declared;
- feature surface all-null rejection;
- undeclared feature rejection;
- multi-alias execution closure;
- mandatory governance closure;
- bound preflight evidence;
- committed audit lineage behavior;
- sealed deliverables authority;
- mandatory full-preflight execution budget.

If a coding agent proposes modifying one of these during an unrelated task, require an explicit reason tied to the current research question.

---

# 6. Current session/time semantics

For NQ/ES regime research, the currently intended canonical RTH convention is:

```text
Timezone: America/Chicago
Session: 08:30:00 to 15:15:00 Central
Completed-bar close semantics: (08:30, 15:15]
```

Do not re-derive RTH windows inline. Use the canonical shared session boundary module.

Historical 15:00 definitions existed and were a real source of inconsistency.

---

# 7. Causal runtime rules

Key principles:

1. Full bar OHLCV becomes available only at interval close.
2. Databento bars may be open-stamped in `ts_event`; NT processing uses close availability in `ts_init`.
3. Same timestamp ordering must preserve causal availability.
4. For coincident timestamps, lower timeframe events needed by the established runtime order must be processed consistently before higher timeframe state transitions where the contract says so.
5. No future-source timestamp may exceed the observation timestamp.
6. Point-in-time pandas joins are not final proof of causal/live parity.

For execution validation, use streaming NautilusTrader behavior.

---

# 8. Model / agent routing to minimize Opus usage

The research agent should route tasks by risk, not by habit.

## Use cheap deterministic/search agents for

- locating files/symbols;
- reading exact config values;
- extracting test results;
- checking file presence;
- summarizing run manifests;
- comparing hashes;
- running targeted tests;
- searching for semantic duplicates;
- listing changed files;
- formatting reports.

Preferred role examples:

```text
repo-scout / Haiku-class
results-triager / Haiku-class
simple test-runner
```

## Use mid-tier coding/reasoning agents for

- implementing a known defect with named files;
- adding targeted regression tests;
- integrating a feature into existing generic infrastructure;
- fixing a deterministic contract mismatch;
- bounded workflow changes with explicit acceptance tests.

Typical model class:

```text
Sonnet-class / Codex implementation model / Gemini coding model
```

## Reserve Opus/high-reasoning usage for

- ambiguous research design;
- choosing between competing causal definitions;
- independent causal audit;
- independent contract audit when interpretation is non-trivial;
- adversarial Red Team review;
- interpreting research results and deciding next hypotheses;
- architecture changes where multiple valid trust models exist.

### Do not use Opus for

- known one-line bugs;
- repo search;
- repetitive test execution;
- waiting/polling;
- formatting reports;
- mechanical code edits;
- extracting metrics from artifacts;
- rebuilding context already captured in this document.

---

# 9. Prompt format for implementation tasks

Use this structure to keep coding-agent sessions bounded.

```text
TASK
<one concrete implementation objective>

WHY
<one paragraph explaining the research/governance reason>

AUTHORITATIVE CONTRACT
- research_decision.yaml: <path>
- study: <path>
- exact invariant(s): ...

READ ONLY FIRST
- <specific files>

ALLOWED CHANGES
- <specific shared files>
- targeted tests

DO NOT CHANGE
- <verified-good runtime areas>
- unrelated studies
- research question
- chronology/OOS

REPRODUCE BEFORE FIXING
<exact failing behavior>

REQUIRED TESTS
1. ...
2. ...
3. ...

TEST BUDGET
- targeted tests first
- broader relevant suite once
- no repeated full-suite runs

STOP CONDITIONS
- if generic framework cannot express requirement -> report CAPABILITY_GAP
- if fix requires research redesign -> STOP
- if scope expands materially -> STOP

FINAL RESPONSE ONLY
- reproduced: yes/no
- changed files
- targeted tests
- broader tests
- remaining blocker
- status: READY_FOR_REVIEW / BLOCKED
```

Do not ask the implementation agent to perform its own final independent audit.

---

# 10. Prompt format for causal audit

```text
INDEPENDENT CAUSAL AUDIT

TARGET
<commit + study + execution composite>

QUESTION
Can this study use any information that would not have been available at the
stated live observation time?

DO NOT FIX
Do not modify implementation.

CHECK
- bar availability timestamps
- same-timestamp ordering
- feature source timestamps
- warmup / reset behavior
- session boundaries
- target horizon
- censoring
- future-source violations
- runtime-vs-offline feature parity
- any post-event information entering candidate selection

ATTACK
Use small adversarial mutations/fixtures when useful.

SEVERITY
BLOCK only for a concrete causal/look-ahead defect.

OUTPUT
CLEAR / CLEAR_WITH_WARNINGS / BLOCKED
plus concise evidence.
```

---

# 11. Prompt format for contract audit

```text
INDEPENDENT CONTRACT AUDIT

TARGET
<commit + study + execution composite>

AUTHORITIES
research_decision.yaml > SPEC.md > study.yaml > compiled_study.json

QUESTION
Does the implementation/runtime exactly execute the declared experiment?

DO NOT FIX

CHECK
- population
- target
- feature set
- authorized dates/modes
- chronology
- baseline
- allowed/prohibited changes
- deliverables
- runtime bindings
- feature order/identity
- terminal decision

BLOCK only for a concrete contract mismatch capable of changing the research.

OUTPUT
CLEAR / CLEAR_WITH_WARNINGS / BLOCKED
```

---

# 12. Prompt format for Red Team

Use Red Team only after implementation + deterministic tests are green.

```text
INDEPENDENT RED TEAM

TARGET COMMIT
<immutable SHA>

PRIMARY QUESTION
Can I make the workflow accept, seal, execute, or classify a study whose
actual runtime/data differs materially from the authoritative contract?

DO NOT FIX
Use disposable mutation fixtures only.

ATTACK THE SPECIFIC CHANGES
- omission
- stale evidence
- mutable sidecar
- path/identity substitution
- delete/rollback provenance
- unsealed executable module
- incomplete mandatory gate
- wrong feature binding
- unauthorized date/mode

NEW FINDINGS
Report only concrete reproducible bypasses.

BLOCKING STANDARD
Only defects that can invalidate causal integrity, population/target,
OOS separation, authoritative contracts, execution identity, mandatory gates,
or stale-evidence rejection.

STOP
Do not turn warnings into another architecture project.
```

---

# 13. Prompt format for research execution

Once infrastructure is frozen, research prompts should be concise and decision-centered.

```text
RESEARCH STUDY

QUESTION
<one sentence>

INSTRUMENT / POPULATION
...

TARGET
...

FEATURES
...

BASELINE
...

CHRONOLOGY
TRAIN:
DEV:
OOS:

AUTHORIZED DATES / MODES
...

FIXED ITEMS
...

ALLOWED VARIABLES
...

PROHIBITED CHANGES
...

EXECUTION
Use canonical NT streaming workflow.
Do not create parallel collector/runner/analysis paths.

ANALYSIS
Use governed analysis harness only for authoritative conclusions.
Scratch analysis is diagnostic only.

OUTPUT
- candidate counts
- target/base rate
- requested metrics
- by-direction/slice results where declared
- caveats
- terminal decision

STOP
Do not optimize/tune beyond the declared study.
Do not open DEV/OOS early.
```

---

# 14. Session discipline / token economy

Use one bounded objective per session.

Bad pattern:

```text
read repo
→ redesign
→ implement
→ test
→ wait
→ reread
→ audit own work
→ investigate warnings
→ refactor unrelated code
```

Preferred pattern:

```text
small handoff
→ exact files
→ exact invariant
→ targeted edit/tests
→ compact result
→ END SESSION
```

Rules:

- do not reopen unchanged files unnecessarily;
- prefer exact grep/path reads over repo-wide scans;
- do not scan archive/scratch/runs unless the task specifically requires it;
- do not repeatedly rerun full test suites;
- do not repeatedly restart long-running jobs;
- use compact status cards instead of streaming large logs;
- pass exact commit SHA and study identity into audit prompts;
- use a fresh session for independent review;
- do not let the implementation agent self-certify its own work;
- preserve expensive model tokens for research reasoning.

---

# 15. Destructive filesystem safety

This rule is mandatory after the junction deletion incident.

Before recursive deletion or worktree cleanup, check for:

- symlinks;
- junctions;
- mount points;
- Windows reparse points;
- descendants resolving outside the disposable root.

Required behavior:

> If any descendant escapes the intended disposable workspace, abort the entire recursive deletion.

Never run raw `rm -rf` / equivalent against a worktree or repo tree that may contain external data junctions.

Do not use real market-data directories as deletion-safety test fixtures.

---

# 16. Data protection

The project contains large, expensive market-data stores and derived canonical datasets.

Treat these as external durable assets, not disposable repo contents.

Recommended operating model:

```text
PRIMARY DATA
    +
LOCAL VERSIONED BACKUP ON DIFFERENT PHYSICAL DEVICE
    +
OFF-SITE / CLOUD COPY
```

Highest backup priority:

- `data/canonical/`
- trained/persisted models
- lineage/manifests needed to reproduce research
- unique derived datasets

Raw/catalog data that is deterministically reconstructible from Databento is still valuable, but may have lower backup priority than unique canonical outputs.

VSS/shadow copies are useful recovery layers, not the sole backup system.

---

# 17. Research-specific current direction

The current NQ program is focused on symmetric regime-transition prediction.

Short-side research question:

```text
qualified bullish RTH regime
→ predict bearish prevailing 1m regime flip within 300 seconds
```

Long-side research question:

```text
qualified bearish RTH regime
→ predict bullish prevailing 1m regime flip within 300 seconds
```

Current strategic priority is not broad new-model research.

The intended progression is:

```text
freeze selected model + contracts
    ↓
prove live NT feature parity
    ↓
prove live score parity
    ↓
prove trigger/population parity
    ↓
evaluate simple event-driven trade economics
```

Do not jump to elaborate trade-policy optimization before live scoring and population parity are established.

---

# 18. Current validation principles for trading research

For strategy validation:

- use NautilusTrader BacktestEngine streaming simulation;
- use 1-second bars for fast validation where appropriate;
- use MBP-1 quote/tick streaming for deployment-realistic execution validation;
- do not treat point-in-time MBP-1 lookup as final execution validation;
- account for realistic spread/slippage/commission assumptions;
- keep 2026 reserved for runtime OOS when that study contract says so;
- do not silently leak OOS into feature/model selection.

---

# 19. Stop rules

These rules exist specifically to prevent another token-consuming infrastructure loop.

## Freeze infrastructure when

- deterministic tests pass;
- causal audit clears;
- contract audit clears;
- Red Team finds no concrete research-invalidating blocker;
- remaining issues are warnings/backlog only.

## Reopen infrastructure only when

A concrete defect demonstrates that the current framework can:

- use future information;
- change target/population incorrectly;
- violate OOS chronology;
- execute unsealed code;
- accept stale audits/seals;
- skip a mandatory gate;
- mutate authoritative contract after seal;
- misbind runtime features/models;
- otherwise produce a research conclusion different from the declared experiment.

## Do NOT reopen for

- aesthetic cleanup;
- theoretical stronger provenance;
- API elegance;
- historical migration;
- logging improvements;
- repo organization;
- speculative future capabilities;
- warnings that cannot change a research result.

---

# 20. Research-agent decision tree

Use this before composing any coding prompt.

```text
Is the user asking a RESEARCH QUESTION?
    |
    +-- YES --> Is research_decision.yaml precise?
    |             |
    |             +-- NO --> clarify/design only
    |             |
    |             +-- YES --> Can existing study framework express it?
    |                           |
    |                           +-- NO --> CAPABILITY_GAP
    |                           |
    |                           +-- YES --> feature readiness
    |                                         ↓
    |                                    preflight
    |                                         ↓
    |                                      audits
    |                                         ↓
    |                                       seal
    |                                         ↓
    |                                      NT smoke
    |                                         ↓
    |                                    validation
    |                                         ↓
    |                                 governed analysis
    |
    +-- NO --> Is this a KNOWN IMPLEMENTATION DEFECT?
                  |
                  +-- YES --> cheap/mid-tier coding agent
                  |             targeted fix/tests
                  |             independent review only if material
                  |
                  +-- NO --> Is it an AMBIGUOUS CAUSAL/CONTRACT QUESTION?
                                |
                                +-- YES --> reserve Opus/high reasoning
                                |
                                +-- NO --> cheap deterministic agent
```

---

# 21. Minimal handoff card between sessions

Every agent should leave a compact handoff instead of expecting the next agent to reconstruct history.

```text
TASK
<what was attempted>

TARGET COMMIT
<sha>

STUDY
<path/id>

AUTHORITATIVE CONTRACT
<research_decision path>

STATUS
READY / BLOCKED / RUNNING

CHANGED FILES
...

TESTS
...

KNOWN FAILURE
...

DO NOT REOPEN
...

NEXT EXACT ACTION
...
```

This handoff should normally be enough to start a fresh session without loading the entire project history.

---

# 22. Final philosophy

The workflow has already demonstrated its value by catching real failures, including:

- all-null feature emission despite a superficially successful run;
- inconsistent RTH session definitions;
- target/censoring same-timestamp race behavior;
- execution modules omitted from the sealed closure;
- incomplete mandatory preflight masquerading as ready;
- audit-history reset paths;
- feature grandfather laundering;
- mutable deliverable authority outside the seal;
- stale audit/seal evidence after code changes;
- unsafe recursive deletion through a Windows junction.

Those findings justified hardening.

The next standard is different:

> **Infrastructure changes must now earn their cost by demonstrating a concrete way the current system can make the research wrong.**

Otherwise, record the issue in backlog and return to research.

The intended steady-state loop is:

```text
NQ hypothesis
    ↓
governed study
    ↓
causal NT execution
    ↓
validated analysis
    ↓
result
    ↓
next hypothesis
```

That is the workflow this playbook is designed to protect.

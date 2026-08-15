# Proposed Canonical Workflow — Collection to Analysis

**Project:** NautilusTrader ML Research Framework  
**Status:** PROPOSED — not yet the canonical implemented workflow  
**Purpose:** Define a single auditable lifecycle from causal collector execution through post-collection analysis, model fitting, OOS evaluation, result sealing, and follow-up research.

---

# 1. Executive Summary

The current framework has become increasingly disciplined on the **collection side**:

```text
research question
    ↓
research_decision.yaml
    ↓
SPEC.md / study.yaml
    ↓
compiled_study.json
    ↓
preflight
    ↓
independent audits
    ↓
preexec seal
    ↓
sealed smoke
    ↓
authorized NautilusTrader collection
    ↓
collector artifacts
```

The proposed extension formalizes the **analysis side** so that the same research discipline continues after `candidates.parquet` is produced:

```text
collector artifacts
    ↓
COLLECTION_VALIDATED
    ↓
ANALYSIS_CONTRACT_FROZEN
    ↓
TRAIN_ANALYSIS
    ↓
MODEL_AND_THRESHOLD_FREEZE
    ↓
OOS_UNLOCK
    ↓
OOS_ANALYSIS
    ↓
RESULT_VALIDATION
    ↓
RESULT_SEAL
    ↓
STUDY_REPORT
    ↓
NEXT_RESEARCH_DECISION
```

The goal is **not** to prevent interactive research.

Instead, the framework should clearly separate:

- **Confirmatory analysis** — pre-specified, lineage-bound, allowed to determine the study conclusion.
- **Exploratory analysis** — flexible, interactive, hypothesis-generating, but cannot silently change the current study's terminal conclusion.

The resulting research loop is:

```text
COLLECT
   ↓
VALIDATE
   ↓
ANALYZE
   ↓
UNDERSTAND
   ↓
FORM NEW HYPOTHESIS
   ↓
NEW RESEARCH DECISION
   ↓
NEW STUDY
```

---

# 2. Design Principles

## 2.1 Collector output is evidence, not automatically a valid analysis dataset

A successful NautilusTrader run does not by itself establish that the collection is suitable for research.

The collection must first pass a deterministic validation stage.

## 2.2 Analysis must inherit collection lineage

Every analysis artifact must be traceable back to:

- study identity,
- compiled study contract,
- execution manifest,
- preexec seal,
- collector run,
- collection hash,
- feature list hash,
- chronology partition,
- analysis code version.

## 2.3 Confirmatory and exploratory research must be different states

Interactive investigation is encouraged, but it must not silently rewrite a frozen experiment after results are seen.

```text
CONFIRMATORY
- pre-specified
- reproducible
- lineage-bound
- can affect terminal study verdict

EXPLORATORY
- flexible
- post-hoc allowed
- clearly labeled
- generates future hypotheses
- cannot silently redefine current terminal verdict
```

## 2.4 Pandas / Polars analysis is appropriate after causal collection

NautilusTrader remains the authoritative engine for event sequencing, execution timing, and causal market replay.

Once the collector has emitted causally valid observations, post-collection analysis may use:

- pandas,
- Polars,
- NumPy,
- scikit-learn,
- LightGBM / XGBoost,
- statistical libraries,
- plotting/reporting tools.

The rule is:

> Do not replace event-driven market/execution logic with offline dataframe joins when timing/order matters.

## 2.5 Every gate must report coverage, not only verdict

Bad:

```text
COLLECTION_VALIDATION: PASS
```

Good:

```text
COLLECTION_VALIDATION: PASS
rows expected:                 1,240,221
rows checked:                  1,240,221
schema columns expected:       72
schema columns checked:        72
feature hash match:            true
duplicate keys:                0
future-source violations:      0
unauthorized years observed:   0
coverage:                      100%
```

---

# 3. Canonical End-to-End State Machine

```text
RESEARCH_DECISION_FROZEN
        ↓
STUDY_CONTRACT_COMPILED
        ↓
PREEXEC_VALIDATED
        ↓
SMOKE_ACCEPTED
        ↓
TRAIN_COLLECTION_COMPLETE
        ↓
COLLECTION_VALIDATED
        ↓
ANALYSIS_CONTRACT_FROZEN
        ↓
TRAIN_ANALYSIS_COMPLETE
        ↓
MODEL_AND_THRESHOLD_FREEZE
        ↓
OOS_UNLOCKED
        ↓
OOS_ANALYSIS_COMPLETE
        ↓
RESULT_VALIDATED
        ↓
RESULT_SEALED
        ↓
STUDY_REPORTED
        ↓
NEXT RESEARCH QUESTION
```

---

# 4. Phase A — Research Decision

## Primary artifact

```text
studies/<study>/research_decision.yaml
```

## Purpose

Defines what the research study is actually trying to test before implementation.

## Example fields

```yaml
question: >
  Do structural regime geometry and rolling 5m productivity add
  incremental predictive information beyond the frozen Top-25 baseline?

fixed_baseline:
  short_model_id: FROZEN_SHORT_TOP25
  long_model_id: FROZEN_LONG_TOP25
  short_feature_sha256: "..."
  long_feature_sha256: "..."

variables_tested:
  - structural_geometry
  - rolling_5m_productivity
  - maturity_bucket

feature_selection_policy:
  mode: none

primary_comparison:
  - A_vs_B
  - B_vs_C

prohibited_changes:
  - replace_frozen_top25
  - rerank_baseline_features
  - expand_to_full_registry
  - redesign_from_oos

terminal_question: >
  Do B and/or C improve directional predictive performance over A
  with acceptable stability?
```

## Gate

```text
RESEARCH_DECISION_FIDELITY
```

Unknown / unenforceable prohibitions must fail closed.

---

# 5. Phase B — Study Contract

## Artifacts

```text
SPEC.md
study.yaml
compiled_study.json
```

## Purpose

Translate research intent into machine-readable execution and analysis contracts.

The compiled study should include:

- population definition,
- target definition,
- feature contract,
- metadata contract,
- chronology,
- checkpoint cadence,
- analysis contract,
- model arms,
- evaluation cells,
- terminal metrics,
- prohibited analysis changes.

---

# 6. Phase C — Execution Manifest

## Proposed canonical artifact

```text
artifacts/execution_manifest.json
```

## Purpose

One authoritative resolved set of all execution-affecting code and contracts.

Used by:

- causal lint,
- contract audit,
- preexec seal,
- source tamper tests,
- smoke validation,
- lineage tracking.

## Must include

```text
runtime entrypoint
collector
feature trackers
regime engine
data loader
causal registration helper
timestamp helpers
run plan
data plan
output manager
compiled-study loader
seal implementation
seal caller
study contract files
feature registry/bindings
```

## Principle

There must not be separate hand-maintained lists for:

```text
sealed files
linted files
audited files
runtime files
```

All consume the same resolved manifest.

---

# 7. Phase D — Pre-Execution Validation

## Sequence

```text
FINAL CODE
    ↓
resolve execution manifest
    ↓
deterministic preflight
    ↓
independent causal audit
    ↓
independent contract audit
    ↓
preexec seal
```

## Hard invariant

Any execution-affecting change after audit:

```text
AUDIT_STALE
```

and requires:

```text
audit → seal → smoke
```

again.

---

# 8. Phase E — Sealed Smoke

## Purpose

Prove the audited code works on a bounded real NautilusTrader replay before full collection.

## Proposed artifact

```text
artifacts/smoke_acceptance.json
```

This artifact must be generated by a deterministic validator, not manually authored.

## Required measurements

```text
run completed successfully
correct study
correct seal
correct execution manifest
correct target date
expected feature list
exact ordered feature SHA
candidate schema valid
duplicate candidate keys = 0
future-source violations = 0
checkpoint timestamp contract satisfied
both directions represented when expected
required maturity/population cells represented
```

## Full-run requirement

```text
--stage full
```

must refuse execution unless there is a current accepted smoke bound to the same seal.

---

# 9. Phase F — TRAIN Collection

## Execution

```bash
python backtests/run_nt_study.py \
  --study studies/<study> \
  --mode collect \
  --stage full
```

## Canonical outputs

Suggested layout:

```text
runs/<run_id>/
    run_manifest.json
    status.json
    collection/
        candidates.parquet
        observations.parquet            # optional
        collection_manifest.json
```

## Run manifest should bind

```text
study_name
compiled_study_sha
execution_manifest_sha
preexec_seal_sha
smoke_acceptance_sha
date range
warmup range
catalog identity
candidate count
feature list SHA
runtime code SHA
```

---

# 10. Phase G — TRAIN Collection Validation

This is the first major new stage.

## Proposed script

```text
scripts/validate_collection.py
```

## Proposed artifact

```text
artifacts/train_collection_validation.json
```

## State transition

```text
TRAIN_COLLECTION_COMPLETE
        ↓
COLLECTION_VALIDATED
```

## Required checks

### 10.1 Run integrity

```text
run status == SUCCESS
run seal == current authorized seal
compiled study hash matches
execution manifest hash matches
```

### 10.2 Chronology

```text
TRAIN rows only
warmup correctly identified
no DEV/OOS candidates
no prohibited-year candidates
```

### 10.3 Schema

```text
metadata columns exact
feature columns exact
ordered feature hash exact
dtypes valid
required columns non-missing
```

### 10.4 Population integrity

```text
candidate primary key uniqueness
duplicates = 0
required directions present
required maturity buckets present
required population gates respected
```

### 10.5 Causal lineage

```text
future-source violations = 0
source timestamp contract satisfied
checkpoint timing contract satisfied
```

### 10.6 Dataset health

Report but do not necessarily block on all:

```text
row count
missing-value rates
feature availability rates
constant features
extreme-value counts
direction balance
target prevalence
per-year population
per-cell population
```

## Result

Only a validated collection may become input to confirmatory analysis.

---

# 11. Phase H — Analysis Contract

The analysis plan should be compiled before terminal analysis begins.

## Proposed contract location

Either:

```text
study.yaml -> analysis:
```

or:

```text
studies/<study>/analysis_contract.yaml
```

with the compiled result embedded in:

```text
compiled_study.json
```

## Example

```yaml
analysis:
  primary_dimensions:
    direction:
      - SHORT
      - LONG

    maturity_bucket:
      - 300_600
      - 600_900
      - 900_1800

    model:
      - A
      - B
      - C

  model_arms:
    A:
      description: frozen baseline Top-25
      feature_count: 25

    B:
      description: A + structural geometry
      feature_count: 52

    C:
      description: B + rolling 5m productivity
      feature_count: 60

  primary_metrics:
    - roc_auc
    - pr_auc
    - brier

  descriptive_metrics:
    - target_prevalence
    - candidate_count
    - time_to_flip
    - mae
    - mfe

  thresholds:
    source_partition: TRAIN
    percentiles:
      - 90
      - 95
      - 97.5

  deciles:
    source_partition: TRAIN

  terminal_rules:
    pooled_results_are_descriptive_only: true
    directional_cells_are_authoritative: true

  prohibited_changes:
    - redefine_maturity_buckets_after_results
    - choose_thresholds_on_oos
    - rerank_frozen_baseline
    - replace_primary_metric_after_results
```

---

# 12. Phase I — TRAIN Analysis

## Proposed entrypoint

```bash
python scripts/run_study_analysis.py \
    --study studies/<study> \
    --stage train
```

## Proposed reusable package

```text
research/analysis/
    loader.py
    population.py
    metrics.py
    model_fit.py
    model_score.py
    thresholds.py
    deciles.py
    crossings.py
    diagnostics.py
    validation.py
    artifacts.py
```

Study-specific logic may live in:

```text
studies/<study>/analysis/
```

but must use a standard interface.

---

# 13. TRAIN Analysis Responsibilities

## 13.1 Load only validated collection

Input must match:

```text
train_collection_validation.json
collection SHA
compiled analysis contract
```

## 13.2 Build predefined cells

For example:

```text
A/B/C
× SHORT/LONG
× maturity buckets
```

No silent cell redesign.

## 13.3 Fit predefined models

Example:

```text
SHORT A
SHORT B
SHORT C

LONG A
LONG B
LONG C
```

## 13.4 Produce TRAIN diagnostics

Possible metrics:

```text
ROC AUC
PR AUC
Brier score
target prevalence
sample count
score distribution
calibration
deciles
P90/P95/P97.5 thresholds
time-to-event
MAE / MFE
first threshold crossing
retention / progression diagnostics
```

## 13.5 Freeze train-derived values

Anything needed downstream must be frozen before OOS:

```text
model parameters
feature order
preprocessing
missing-value handling
score transformations
thresholds
decile boundaries
calibration
terminal comparison rules
```

---

# 14. Phase J — Model and Threshold Freeze

## Proposed artifacts

```text
artifacts/model_manifest.json
artifacts/threshold_manifest.json
artifacts/decile_manifest.json
artifacts/train_analysis_manifest.json
```

## Model manifest

Should include:

```text
model type
hyperparameters
feature names ordered
feature SHA
training rows SHA / collection SHA
direction
maturity bucket policy
random seed
library/version
serialized model SHA
```

## Threshold manifest

Should include:

```text
P90 / P95 / P97.5
source partition = TRAIN
population definition
direction
model arm
score distribution SHA
```

## Freeze invariant

After this point:

```text
NO:
- model refitting on OOS
- threshold reselection on OOS
- feature additions
- feature removal
- bucket redesign
- preprocessing changes
```

Any such change creates a new research lineage.

---

# 15. Phase K — OOS Unlock

## Purpose

Allow access only after TRAIN collection, analysis, models, and thresholds are frozen.

## Proposed conditions

```text
TRAIN_COLLECTION_VALIDATED
TRAIN_ANALYSIS_COMPLETE
MODEL_MANIFEST_FROZEN
THRESHOLD_MANIFEST_FROZEN
NO_PRIOR_CURRENT-LINEAGE_OOS_ACCESS
```

## Proposed artifact

```text
artifacts/oos_unlock.json
```

The unlock should be computed from lineage/run history, not a hand-typed assertion.

---

# 16. Phase L — OOS Collection or OOS Scoring

Depending on study design:

```text
Option A:
run the same sealed collector over OOS

Option B:
score previously collected but still locked OOS artifacts

Option C:
run live NT scoring path where execution/runtime parity is the question
```

For predictive research, the important rule is:

```text
frozen TRAIN decisions
        ↓
unchanged OOS evaluation
```

---

# 17. Phase M — OOS Analysis

## Proposed entrypoint

```bash
python scripts/run_study_analysis.py \
    --study studies/<study> \
    --stage oos
```

## Rules

OOS analysis must:

```text
load frozen model manifest
load frozen thresholds
load frozen decile boundaries
use unchanged feature order
use unchanged preprocessing
evaluate predefined primary cells
```

## OOS may calculate

```text
ROC AUC
PR AUC
Brier
calibration
threshold hit rates
decile monotonicity
timing diagnostics
MAE/MFE diagnostics
economic outcomes if pre-specified
```

But may not choose new versions based on OOS.

---

# 18. Phase N — Exploratory Analysis

Interactive exploration is a first-class workflow, not a prohibited activity.

## Proposed modes

```text
TRAIN_EXPLORATORY
OOS_EXPLORATORY
```

with very different interpretation.

### TRAIN exploration

May be used to:

```text
discover patterns
inspect unexpected distributions
generate new features
design a future experiment
```

### OOS exploration

Allowed for understanding, but anything discovered becomes:

```text
POST-OOS HYPOTHESIS
```

and cannot become confirmatory evidence in the current lineage.

---

# 19. Exploratory Artifact

Every exploratory analysis should record minimal provenance.

Example:

```text
explorations/<timestamp>_<name>/
    exploration_manifest.json
    notebook_or_script.py
    tables/
    charts/
    notes.md
```

## Manifest

```json
{
  "mode": "EXPLORATORY",
  "study": "...",
  "source_collection_sha": "...",
  "years_accessed": [2021, 2022, 2023],
  "columns_accessed": ["..."],
  "script_sha": "...",
  "created_at": "...",
  "terminal_evidence_allowed": false
}
```

## Rule

Exploration does **not** silently mutate:

```text
research_decision.yaml
analysis contract
frozen model
frozen threshold
current study terminal verdict
```

Instead:

```text
interesting exploratory result
        ↓
new research_decision.yaml
        ↓
new study / new lineage
```

---

# 20. Phase O — Result Validation

## Proposed script

```text
scripts/validate_study_results.py
```

## Proposed artifact

```text
artifacts/result_validation.json
```

## Checks

### Input lineage

```text
collection SHA valid
model manifest SHA valid
threshold manifest SHA valid
analysis code SHA valid
OOS partition correct
```

### Cell completeness

```text
all required directional cells present
all required maturity buckets present
all A/B/C arms present
pooled rows not substituted for directional rows
```

### Metric completeness

```text
all primary metrics populated
sample counts reported
undefined metrics explicitly flagged
```

### OOS discipline

```text
models unchanged
thresholds unchanged
feature order unchanged
bucket definitions unchanged
```

### Reproducibility

Re-running the analysis should reproduce:

```text
metric tables
threshold results
terminal classification
```

within explicitly defined numeric tolerances.

---

# 21. Phase P — Result Seal

## Proposed artifact

```text
artifacts/result_seal.json
```

## Binds

```text
research decision SHA
compiled study SHA
execution manifest SHA
collection SHA
analysis contract SHA
analysis code SHA
model manifest SHA
threshold manifest SHA
OOS data/run SHA
result validation SHA
primary metric tables SHA
terminal verdict
```

The result seal proves:

> These reported conclusions correspond to these exact inputs, code, models, thresholds, and evaluation data.

---

# 22. Phase Q — Study Report

## Canonical artifact

```text
STUDY_REPORT.md
```

## Suggested structure

```text
1. Executive Summary
2. Research Question
3. Frozen Design
4. Data / Chronology
5. Collection Validation
6. Model Arms
7. TRAIN Results
8. Frozen Thresholds
9. OOS Results
10. Directional / Maturity Cell Results
11. Diagnostics
12. Economic Interpretation
13. Failure Modes / Caveats
14. Exploratory Findings
15. What the Study Does Not Prove
16. Terminal Verdict
17. Next Research Questions
18. Reproducibility / Artifact Hashes
```

---

# 23. Proposed Agent Architecture

The existing agents should remain narrow.

## 23.1 Main orchestrator

### Responsibilities

```text
understand research decision
coordinate agents
make smallest approved implementation
run deterministic tooling
never silently change fixed design
```

### Must not

```text
declare its own audit independent
reinterpret OOS after viewing results
silently add analyses to terminal criteria
```

## 23.2 repo-scout

### Role

Read-only implementation tracing.

### Responsibilities

```text
find actual code paths
trace contracts to runtime
identify relevant scripts
surface architecture drift
```

## 23.3 contract-checker

### Role

Independent read-only contract audit.

### Responsibilities

```text
compare research decision → SPEC → compiled contract → implementation
verify required artifacts
verify analysis cells / metrics / freezes
distinguish PASS / FAIL / WARNING / NOT VERIFIED
```

## 23.4 lookahead-auditor

### Role

Independent causal/data-leakage review.

### Responsibilities

```text
source timestamp causality
window anchoring
target leakage
train/OOS contamination
threshold provenance
feature availability
```

Should audit both:

```text
collection causality
analysis leakage
```

## 23.5 results-triager

Keep narrow.

### Role

```text
run explicitly assigned tests
summarize failures
do not redesign
do not perform open-ended research analysis
```

## 23.6 Proposed new agent: research-analyst

### Role

Run authorized post-collection analysis.

### Responsibilities

```text
load validated collection
produce predefined tables
fit predefined model arms
calculate predefined metrics
generate approved diagnostics
compare cells
summarize evidence
```

### Must not

```text
edit collectors
change research decision
change analysis contract
access locked OOS
select new terminal metrics after results
silently redefine cells
```

## 23.7 Proposed new agent: analysis-auditor

### Role

Independent audit of downstream analysis.

### Responsibilities

```text
verify input lineage
verify train/OOS separation
verify model freeze
verify threshold provenance
verify metric formulas
verify cell completeness
verify pooled vs directional interpretation
verify reproducibility
```

---

# 24. Proposed Script Inventory

## Existing / collection side

```text
scripts/create_study.py
scripts/compile_study.py
scripts/check_research_decision_fidelity.py
scripts/check_spec_fidelity.py
scripts/research_preflight.py
scripts/resolve_execution_manifest.py
scripts/causal_lint.py
scripts/run_preexec_audits.py
scripts/preexec_audit_seal.py

backtests/run_nt_study.py
backtests/nt_runtime/*
strategies/flip_prediction_collector.py
features/*
utils/causal_registration.py
```

## Proposed / analysis side

```text
scripts/validate_collection.py
scripts/run_study_analysis.py
scripts/validate_model_freeze.py
scripts/generate_oos_unlock.py
scripts/validate_study_results.py
scripts/generate_result_seal.py
scripts/run_exploration.py
```

Potential reusable library:

```text
research/analysis/
    loader.py
    population.py
    metrics.py
    model_fit.py
    model_score.py
    thresholds.py
    deciles.py
    crossings.py
    diagnostics.py
    economics.py
    validation.py
    artifacts.py
```

---

# 25. Proposed Artifact Inventory

Per study:

```text
studies/<study>/

    research_decision.yaml
    SPEC.md
    study.yaml
    compiled_study.json

    artifacts/
        execution_manifest.json
        preexec_audit_seal.json
        smoke_acceptance.json

        train_collection_validation.json

        analysis_contract.json
        train_analysis_manifest.json

        model_manifest.json
        threshold_manifest.json
        decile_manifest.json

        oos_unlock.json

        result_validation.json
        result_seal.json

    audit/
        causal_*.md
        contract_*.md
        status.json
        contract_status.json

    explorations/
        <exploration_id>/
            exploration_manifest.json
            analysis.py
            notes.md
            tables/
            charts/

    STUDY_REPORT.md
```

---

# 26. Proposed CLI Flow

## Compile

```bash
python scripts/compile_study.py \
    --study studies/<study>
```

## Preflight

```bash
python scripts/research_preflight.py \
    --study studies/<study>
```

## Audit + seal

```bash
python scripts/run_preexec_audits.py \
    --study studies/<study>

python scripts/preexec_audit_seal.py \
    --study studies/<study>
```

## Smoke

```bash
python backtests/run_nt_study.py \
    --study studies/<study> \
    --mode collect \
    --stage day \
    --date YYYY-MM-DD

python scripts/validate_collection.py \
    --study studies/<study> \
    --run <smoke_run_id> \
    --mode smoke
```

## Full TRAIN collection

```bash
python backtests/run_nt_study.py \
    --study studies/<study> \
    --mode collect \
    --stage full
```

## Validate TRAIN collection

```bash
python scripts/validate_collection.py \
    --study studies/<study> \
    --run <train_run_id> \
    --mode train
```

## TRAIN analysis

```bash
python scripts/run_study_analysis.py \
    --study studies/<study> \
    --stage train
```

## Freeze

```bash
python scripts/validate_model_freeze.py \
    --study studies/<study>
```

## OOS unlock

```bash
python scripts/generate_oos_unlock.py \
    --study studies/<study>
```

## OOS analysis

```bash
python scripts/run_study_analysis.py \
    --study studies/<study> \
    --stage oos
```

## Result validation

```bash
python scripts/validate_study_results.py \
    --study studies/<study>
```

## Result seal

```bash
python scripts/generate_result_seal.py \
    --study studies/<study>
```

---

# 27. Confirmatory vs Exploratory Flow

```text
                    VALIDATED COLLECTION
                           │
             ┌─────────────┴─────────────┐
             │                           │
             ↓                           ↓
      CONFIRMATORY                  EXPLORATORY
        ANALYSIS                      ANALYSIS
             │                           │
    frozen contract                flexible query
             │                           │
    predefined metrics             new patterns
             │                           │
     terminal evidence             hypothesis only
             │                           │
             ↓                           ↓
      RESULT SEAL                NEW RESEARCH IDEA
                                         │
                                         ↓
                              NEW research_decision.yaml
```

---

# 28. What Should Be Automated

Automate deterministic checks:

```text
hash verification
schema verification
partition checks
duplicate detection
feature identity
population counts
cell completeness
metric calculations
threshold provenance
model manifests
artifact lineage
```

Do not try to automate away research judgment.

Humans / research agents should still interpret:

```text
whether an effect is meaningful
whether instability is acceptable
whether a hypothesis is economically plausible
whether a new experiment is worth running
```

---

# 29. Failure-State Rules

## Collection failure

```text
COLLECTION_INVALID
```

No confirmatory analysis.

## Analysis-contract drift

```text
ANALYSIS_CONTRACT_STALE
```

Re-freeze before proceeding.

## Model change after freeze

```text
MODEL_FREEZE_INVALID
```

OOS results invalid.

## Threshold change after freeze

```text
THRESHOLD_FREEZE_INVALID
```

OOS results invalid.

## OOS touched before freeze

```text
OOS_LINEAGE_CONTAMINATED
```

Must be explicitly recorded; cannot be called pristine OOS.

## Exploratory result promoted without new study

```text
POST_HOC_PROMOTION_BLOCKED
```

---

# 30. Minimal Version to Build First

Do not build the entire framework at once.

## Phase 1 — highest value

Build:

```text
validate_collection.py
analysis contract schema
run_study_analysis.py
model_manifest.json
threshold_manifest.json
```

This captures most of the real day-to-day workflow.

## Phase 2

Add:

```text
result validation
result seal
analysis auditor
exploration manifests
```

## Phase 3

Generalize across multiple study families.

---

# 31. Acceptance Criteria for the New Analysis Layer

The new layer is ready when an independent agent can answer YES to all:

1. Can every analysis table be traced to an exact validated collection?
2. Is the collection schema and feature identity cryptographically pinned?
3. Can a model be changed after TRAIN freeze without detection?
4. Can a threshold be changed after TRAIN freeze without detection?
5. Can OOS be accessed before freeze without detection?
6. Can an analyst silently redefine primary cells after seeing results?
7. Are exploratory analyses clearly separated from terminal evidence?
8. Are all terminal metrics reproducible from saved artifacts?
9. Can the report be regenerated from frozen artifacts?
10. Are analysis scripts independent of scratch/manual hidden steps?
11. Does every gate report its coverage?
12. Can a new research hypothesis be created without corrupting the old study?

If any critical answer is NO:

```text
ANALYSIS_FLOW_BLOCKED
```

---

# 32. Recommended Next Step

Once the current collection framework passes independent red-team review:

```text
1. Implement TRAIN_COLLECTION_COMPLETE / validate_collection.py
2. Formalize the analysis contract in the StudySpec
3. Build the generic TRAIN analysis runner
4. Freeze model + threshold manifests
5. Formalize OOS unlock
6. Add result validation and result sealing
7. Add explicit exploratory-analysis mode
```

The objective is not to make research bureaucratic.

The objective is to make the full research lifecycle reproducible while preserving fast interactive investigation.

---

# 33. Final Target Architecture

```text
RESEARCH INTENT
      ↓
STUDY CONTRACT
      ↓
EXECUTION MANIFEST
      ↓
PREEXEC VALIDATION
      ↓
SEALED SMOKE
      ↓
NT COLLECTION
      ↓
COLLECTION VALIDATION
      ↓
ANALYSIS CONTRACT
      ↓
TRAIN ANALYSIS
      ↓
MODEL / THRESHOLD FREEZE
      ↓
OOS UNLOCK
      ↓
OOS ANALYSIS
      ↓
RESULT VALIDATION
      ↓
RESULT SEAL
      ↓
STUDY REPORT
      ↓
EXPLORATION / INTERPRETATION
      ↓
NEXT RESEARCH DECISION
```

**Core principle:**

> Collection integrity and analysis integrity are one continuous research lineage.  
> The framework should protect both without preventing exploratory thinking.

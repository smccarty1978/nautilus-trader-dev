# Research Study Request

## CAPABILITY_ROUTING

```yaml
CAPABILITY_ROUTING:
  EXISTING_VERIFIED: []
  FEATURE_CANDIDATE_REQUIRED: []
  GENERIC_PROVIDER_EXTENSION_REQUIRED: []
  GENERIC_COLLECTOR_EXTENSION_REQUIRED: []
  STUDY_LOCAL_BESPOKE_REQUIRED: []
  SEMANTIC_REVIEW_REQUIRED: []
  CAPABILITY_PROMOTION_BLOCKERS: []
  TRUE_CAPABILITY_GAPS: []
```

A researcher fills in everything above the `AGENT INTAKE RESULT` line and hands this to a
coding/research agent. The agent fills in everything below it and hands it back **before**
scaffolding `study.yaml`. See `docs/RESEARCH_STUDY_BLUEPRINT.md` for the routing rules this
intake applies (§7 Novelty Routing Matrix, §8 Severity Levels, §9 stop/no-stop boundary).

---

## Research Question

<!-- One sentence. What are you actually trying to find out? -->

## Hypothesis

<!-- What you expect, and why. This becomes part of research_decision.yaml. -->

## Study Type

<!-- classification / regression / descriptive / forward-outcome / strategy -->

## Instrument

- Symbol:
- Contract family:
- Roll handling: <!-- continuous (.v.0) / specific expiry / not sure -->

## Data Source

<!-- existing catalog (name it) / new source (name it and why the existing catalog doesn't work) -->

## Candidate Population

<!-- What defines a candidate event? Point to an existing population definition if you know one.

     A population defined by a derived score crossing a frozen threshold (e.g. "the first
     upcross of another study's frozen model score above its TRAIN P90") is an EXISTING,
     SUPPORTED capability -- describe its semantics here (threshold source, crossing rule,
     censoring treatment), not as a schema gap. It is implemented generically via
     `population.qualification.required_checkpoint_identities_path` (the collector's
     identity-allowlist qualification mode, docs/RESEARCH_WORKFLOW.md §7) and built with
     `scripts/build_derived_score_upcross_population.py` -- see
     docs/RESEARCH_STUDY_BLUEPRINT.md for how this fits the wider routing model. Membership
     coming from an external, governed identity artifact rather than a live threshold filter
     is not itself novel. -->

## Event / Decision Timestamp T

<!-- The exact instant "knowable at T" is measured from. -->

## Target

- Exact definition:
- Horizon:
- Censoring:
<!-- If the target combines more than one condition (e.g. a flip AND an MFE threshold AND an
     MAE threshold), say so explicitly here — this is the single most common source of a
     StudySpec schema gap. See BLUEPRINT §5.1, §7.F. -->

## Features

- Required known families:
- Desired new concepts:
- Completed / forming / rolling semantics: <!-- be explicit; ambiguity here fails closed -->

## Timeframes / Windows

## Session Semantics

- RTH / ETH / both:
- State retention across session boundary:
<!-- A session filter changes which candidates EMIT, not which bars providers SEE. If you're
     not sure whether ETH history needs to stay in the replay, say so — this is BLUEPRINT §7.K. -->

## TRAIN Period

## Validation Period

## OOS Period

## Prohibited Periods

## Model Families Allowed

## Hyperparameter Search Allowed

- Yes/No:
- Constraints:

## Evaluation Metrics

## Forward Outcomes Needed

<!-- Any forward-outcome measurement (MFE, MAE, return, time-to-event) this study needs computed
     post-hoc. These are labels, never features — see BLUEPRINT §7.I. -->

## Novel / New Requirements

<!-- Check anything you believe is NOT already supported exactly as-is. Uncertainty is fine —
     that's what STEP 1-2 discovery is for. -->

- [ ] New feature or provider
- [ ] New timeframe/window semantics not covered by an existing verified definition
- [ ] New instrument or contract not in the current catalog registry
- [ ] New data source
- [ ] New/composite target
- [ ] External model dependency (a frozen score from another study)
- [ ] Other:

## Researcher Approval Boundaries

<!-- Anything you want flagged back to you no matter how the agent would otherwise classify it. -->

## Expected Deliverables

## Expensive Run Authorization

<!-- bounded fixture only / TRAIN / OOS — do not assume broader authorization than stated here -->

---

# AGENT INTAKE RESULT

*Filled in by the coding/research agent after STEP 1–2 discovery
(`docs/RESEARCH_STUDY_BLUEPRINT.md` §6). Nothing below this line licenses any collection,
training, or OOS run — see `EXPENSIVE_RUN_NOT_STARTED` at the bottom.*

```
EXISTING_CAPABILITIES:
  <what's already supported exactly as requested — cite the canonical feature/study/artifact>

NOVELTY_LEVELS:
  <each requirement above classified 0-5 per BLUEPRINT §8, one line each>

MISSING_CAPABILITIES:
  <Level 3+ items: what implementation work is actually required>

CLARIFICATIONS_REQUIRED:
  <BLUEPRINT §9 "when the researcher will be asked" items found in this request — genuine
   semantic ambiguity only, not deterministic defects>

APPROVAL_REQUIRED:
  <Level 4/5 items: target/population/chronology/session semantic changes, new data source,
   new instrument, TRAIN/OOS year changes — always explicit, never inferred>

AUTO_FIXABLE_ITEMS:
  <deterministic defects the agent will just fix — stale artifacts, broken imports, resolver
   bugs, obvious test fixes. Not a request for permission; a statement of what will happen.>

SCHEMA_GAPS:
  <anything StudySpec cannot represent today (BLUEPRINT §5.1). Composite targets, derived
   external-model inputs, machine-enforced pre-freeze gates, and bounded model-selection
   search are now expressible (BLUEPRINT §5.1 CLOSED items, RESEARCH_WORKFLOW.md §20). A
   population sourced from an external frozen identity table (derived-score threshold-upcross
   or similar) is also already supported — RESEARCH_WORKFLOW.md §7's identity-allowlist
   qualification mode plus `scripts/build_derived_score_upcross_population.py` — this is a
   Candidate Population description, never a schema gap on its own. Reserve this field for a
   concept the current StudySpec/framework genuinely cannot represent yet; do not invent a
   workaround that produces a misleading contract.>

PROPOSED_EXECUTION_PLAN:
  <ordered steps through docs/RESEARCH_STUDY_BLUEPRINT.md §6, STEP 3 onward>

EXPENSIVE_RUN_NOT_STARTED: true
```

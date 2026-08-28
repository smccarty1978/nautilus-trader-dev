# Study Closure — Deep Pullback / 5s Re-acceleration

> **[HISTORICAL]** Terminal record. This branch is **CLOSED — diagnostic negative**.
> No accepted model lineage was produced. 2024 was never opened; 2025/2026 remain prohibited.
> Researcher decision recorded 2026-08-28.

## Terminal decision

**`P5 — NO_MEANINGFUL_SIGNAL`** (`research_decision.yaml` terminal_decisions).

No stable, economically coherent learnable continuation-ranking signal at the first completed
5s re-alignment after a deep pullback, under the frozen RTH ordered-barrier target.

## What was done

| Stage | Result |
|---|---|
| Generic runtime (ProviderHost + episode population + frozen Model-C scorer) | built, audited, sealed — composite `1a2e54fad3b4c6e0ce4e51b083728573293af5d9977b48037c7d5073555cf5bc`, seal `db288e642155a901330662ea45f48be78368b5f7d781cab9f6dd45b1e0172e1f` |
| Bounded real smoke (2023-03-03) | PASS |
| TRAIN collection 2021–2023 (partitioned) | 59,724 candidates == observations; 0 key/episode duplicates; 1 candidate/episode |
| Pooled BROAD baseline fit + TRAIN freeze | `train_experiment_freeze.json` sha `726b190e5f22cb5b3dc9f5a520000349d58aed78d7ce28e1682a06898d1244bc`, reproduced deterministically |
| Pre-OOS directional diagnostic | **found the collector target defect** (below) |
| Correct-label feasibility fit | **no signal** (below) |
| OOS (2024) | **never accessed** |

## Why the branch closed

### 1. Collector target defect (framework backlog, not fixed for this branch)

`research_workflow/generic_collector.py` never wires the `research_workflow/forward_outcomes`
ordered-barrier tracker. It labelled every candidate with its legacy target:
`LABELED_POSITIVE` ⇔ the prevailing 1m regime flipped to the opposing direction within 300 s;
`LABELED_NEGATIVE` ⇔ no opposing flip. `atr_t` was stored but unused for labelling.

The sealed research target is the ordered barrier: **+1.00 ATR favorable before −0.75 ATR
adverse within 300 s**, entry = first 1s open after candidate T, frozen ATR_T, RTH
`session_end_censoring: true`.

Independent exhaustive replay of the frozen barrier over all 59,724 candidates from
sealed-catalog 1s bars (`implementation/target_replay_diagnostic.py`,
`artifacts/target_replay_diagnostic.json`, `artifacts/target_replay_audit_sample.csv`):

- **28,668 / 55,457 binary-label mismatches (51.7 %)** on rows resolved by both.
- collected positive rate 15.6 % (LONG 29.5 % / SHORT **2.16 %**) vs frozen-target replay
  **39.4 % (LONG 39.1 % / SHORT 39.7 %)** — the extreme LONG/SHORT asymmetry was a labelling
  artefact, not a property of the target.

Recorded as a framework defect in `docs/WORKFLOW_REFERENCE_FACTS.md` → "Known defects". Do
**not** fix it solely to continue this negative branch.

### 2. Correct-label feasibility fit — no signal

`implementation/correct_label_feasibility.py` (`artifacts/correct_label_feasibility.json`).
Same causal 35-input surface, correct ordered-barrier label (1s replay), fit 2021+2022,
evaluate 2023 once, fixed LightGBM baseline (`hyperparameters={}`, seed 0), three arms:

| arm | n(2023) | base rate | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|---|---|
| POOLED_BROAD | 18,760 | 0.384 | **0.514** | 0.393 | 0.238 |
| LONG_BROAD | 9,409 | 0.385 | **0.509** | 0.391 | 0.241 |
| SHORT_BROAD | 9,351 | 0.383 | **0.506** | 0.390 | 0.241 |

2023 success rate is flat/non-monotone across all 10 score deciles (~0.35–0.42). Diagnostic
P90/P95/P97.5 tails (2021–2022 → 2023, not promoted to authority): lift ≈ 1.0 (0.97–1.17,
the >1 cases on n = 78–186). This IS the required test — same causal X + correct y + fresh
TRAIN-only fit — and it independently returns chance-level discrimination.

### 3. Model-C / rolling_300s missingness — `LINEAGE_MATCH_EXPECTED`, not the cause

`artifacts/rolling_300s_parent_parity_audit.json`. `GenericRollingProductivityProvider`
requires an exact contiguous 301 printed 1s bars; NQ 1s bars print only on traded seconds →
~79 % null. The parent `clean_maturity_flip_model_rolling_productivity` uses the identical
collector/instances/tracker and its own TRAIN surface is 72.7 % null on the same four
features; Model-C was fit expecting it (LightGBM native NaN, no complete-case filter). The
~21 % of child rows with Model-C present are also at ROC ≈ 0.50 on the correct target, so
missingness is not the bottleneck.

## Session semantics (confirmed authoritative)

Candidate emission RTH; `session_end_censoring: true`. A candidate whose 300 s ordered-barrier
horizon extends past the canonical RTH close is **CENSORED at session end** — ETH prices are
**not** used to resolve an RTH candidate's economic target. ETH data remains available to
causal providers / regime state. Changing this would be a new Level-4 semantic variant and is
not authorized. The feasibility population already respects this (937 replay-CENSORED rows
excluded).

## Explicitly NOT done (and not authorized to do to continue this branch)

- wiring ordered-barrier labelling into `generic_collector.py`
- recollecting 2021–2023
- tuning / feature selection / threshold optimisation / architecture search
- opening 2024 / touching 2025–2026
- promoting `train_experiment_freeze.json` as an accepted model lineage

## Artifact status

`train_experiment_freeze.json`, `experiment_models.json`, `experiment_authorization.json`,
`model_selection_manifest.json`, `train_freeze_lineage.json` describe a pooled BROAD model fit
against the **wrong** (legacy regime-flip) target. They are retained as reproducible evidence
of what was executed and are **NOT an accepted lineage**; they must not be used to authorize
OOS. `train_fitted_models.joblib` is gitignored/regenerable.

## Related memory

`forward_outcome_target_not_wired_into_collector.md`, `provider_host_adapter_architecture.md`.

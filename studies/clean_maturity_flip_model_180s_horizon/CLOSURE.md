# Study Closure — Clean Maturity Flip Model, 180s Horizon

> **[HISTORICAL]** Terminal record. This branch is **CLOSED — diagnostic negative**.
> `terminal_decision: MIXED` · `outcome: DIAGNOSTIC_NEGATIVE` · **NOT PROMOTED**.
> 2024 OOS was run under the prior lineage and **reused by proven equivalence** (no
> recollection, no rescoring). 2025/2026 never accessed.

## Terminal decision

**`MIXED`** (`research_decision.yaml` `terminal_decision_classes: [A, B, C, D, MIXED]`).

The 180-second Model C classifier improves checkpoint-level discrimination versus the
frozen 300-second parent and **replicates that improvement in 2024 OOS**, but the
economic / actionable half of the compound research question is **not** satisfied:
first-fire / regime-level discrimination is ≈ chance and the frozen P90-tail 2024
economic return is ≈ 0. High checkpoint AUC ≠ PnL discrimination — the frozen 180s models
are a **valid but non-monetizable diagnostic** result.

## Authoritative lineage at closure

| | |
|---|---|
| execution composite | `09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a` |
| PREEXEC seal | LOCKED · composite `09b5c66d…` · artifact `7c1389c15c7192261b33cec25d4f2903abb9ff02e9e2ba424e263e7f84adb24a` |
| causal review | pass 17 · CLEAR · `audit/pass_17.md` (lookahead-auditor) |
| contract review | pass 16 · CLEAR · `audit/contract_pass_16.md` (contract-checker) |
| TRAIN freeze | `26c1b0c958155b8edb403312a61518e720a7f1b96981b064c788dc9ebfafe7a7` |
| LONG_C model_id | `ccd587dfed77d1c87029bcd779abb1f6b70fa63beab5c99f5439653746963b0c` |
| SHORT_C model_id | `209da0ff0c922e02ab02f78408d0591bd0b2e762a71ecd3ed010856ca45051e6` |
| modeling execution closure | `fb4183e49b1223fb5511e92f9b6977a3e1f19f697311ba5b0d3fb637a20d9bda` |
| authorization | `19534de9bec8932da8b5b690c892bb4ea4324741865cae208c0270c8c0dd30fb` (unchanged throughout) |
| OOS lineage reconciliation | identity `9a713d1a11b3e8471ef0fc72fedad5baa840f79700534f630fc4830ee7bc277b` (`artifacts/oos_lineage_reconciliation.json`) |
| OOS reconciled authority | identity `7174bd6885ddef470374c80a03b7a758735b884424e6e720acecb1df820ac21e` (`artifacts/oos_reconciled_authority.json`) |
| Stage 16 analysis | identity `9f4c29e30699bb496575b5488191a944f7e0d6155c69a35e1e91332d5c625382` · FRESH (`artifacts/experiment_analysis.json`) |
| Stage 17 decision | identity `cd8bfb923b23e84658f830e91efee7d4765daed7f16643cfbd41644bee12a6e4` (`artifacts/research_decision_stage17.json`) |
| final report | `results/STUDY_REPORT.md` sha `3efa119bebec67c8aa130548b28060e252004f93493e0051a7a1e2c7164f69e5` |
| closure | `artifacts/study_closure.json` · canonical sha `b0153f3f4e2973f8544f138be97d5bd9a3bd461ae4c7a4ff7b3527f1291d67f1` · identity `eb7407678fe79e8a4594c56b879246c05ee78e37d3b23fdacc9c4191c9d64957` |

## What was done

| Stage | Result |
|---|---|
| Study contract (horizon 300s → 180s, scalar parameter variation) | `research_decision.yaml` / `SPEC.md` / `study.yaml`, parent's exact canonical A/B/C surface |
| Framework reconciliation (2026-08-29) + full TRAIN lifecycle | collection 2021–2023 (1,387,411 rows), two-phase selection, 2023 reject-only gate, per-direction freeze + aggregate freeze |
| 2024 OOS collection + scoring (commit `fa47c4e`, prior lineage `bd2e9cf1`) | 450,973 candidates (66,811 POS / 381,594 NEG / 2,568 CENSORED); checkpoint-level classification + March-2024 first-fire diagnostic |
| Red-Team Remediation Pass 1 merge (`7a1b52c`) + `modeling_driver_relpaths` declaration (`8244a4b`) | moved the execution closure |
| Re-audit + re-seal + **deterministic lineage TRAIN re-freeze** (`b35b17b`) | winners C/C, hyperparameters, fit_identity, **model bytes** all identical; `predict_proba` Δ = 0.00; model_id / freeze_sha256 changed (embed the moved MODELING_EXECUTION_CLOSURE) |
| **OOS lineage reconciliation** (`58b190c`) | 8 equivalence proofs PASS; `predict_proba` Δ = 0.00 over ALL 450,973 already-collected 2024 rows → `REUSABLE_WITH_LINEAGE_REBINDING` |
| Stage 16 analysis (RT-13 identity, FRESH) | primary checkpoint-level classification preserved verbatim; first-fire kept distinct |
| Stage 17 decision | `MIXED` / NOT PROMOTED |

## Why the branch closed

**Classification axis — PASS, OOS-replicated.** 2024 checkpoint-level: LONG_C ROC-AUC
0.6915 / PR-AUC 0.2958 (1.82× base) vs frozen 300s parent 0.6398 / 0.4046; SHORT_C 0.6746
/ 0.2441 (1.77× base) vs 0.6282 / 0.3415. ROC-AUC Δ(180s−300s): +0.0517 LONG, +0.0464
SHORT; the TRAIN→OOS relationship replicates (March 2024 checkpoint ROC-AUC ≈ 0.70 / 0.67).
Calibration ECE < 0.01 (LONG).

**Economic / actionable axis — NOT ESTABLISHED.** March 2024 first-eligible-per-regime
(first-fire): LONG ROC-AUC 0.4954 — chance. Frozen P90-tail 2024 forward path:
`return_atr` ≈ 0 for both 180s and 300s; the 180s window truncates ≈ 0.25 ATR of eventual
favourable excursion.

**Compound research question fails on the economic half.** The 180s horizon produces a
better *classifier*, not a better *signal*.

## Model disposition

The frozen 180s Model C models (`ccd587df…` LONG_C, `209da0ff…` SHORT_C) are **preserved**
— joblib + native booster + golden fixture + `model_registry/*.json` records, feature
order, preprocessing (`96ebac89…`), TRAIN-only thresholds (P90/P95/P97.5), score semantics.

**Scientific assessment: VALID_DIAGNOSTIC.** Valid target, valid model, negative economics.
Explicitly **NOT `INVALID_TARGET`**. The `model_registry` `scientific_status` stays
`UNASSESSED` + `reuse_status: PERMITTED` (no governed function exists to assign
`scientific_status` on an existing record; this closure is the authoritative assessment).
`UNASSESSED` + `PERMITTED` passes the RT-09 derived-input reuse gate; consuming them as a
diagnostic derived input additionally requires an explicit child-study reuse policy
(`assert_scientific_status_reusable`). Never as a primary target.

## Prohibitions

No promotion. No further classifier tuning. No threshold / P90 modification. No further
2024 optimization. No OOS threshold search. No rescue attempt. No 2024 / 2025 / 2026 data
access. There is no governed reopen path.

**Further economic research requires a SEPARATE study with a separately-frozen
`research_decision.yaml` against an economic-quality target** (P(clean reversal) / E[MFE] /
target-before-stop) — not continued work on this classifier.

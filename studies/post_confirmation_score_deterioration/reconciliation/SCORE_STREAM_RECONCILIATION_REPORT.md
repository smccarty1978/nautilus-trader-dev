# Score-Stream Reconciliation — Claude study vs Codex replication

**Date:** 2026-08-10 · **Scope:** provenance / availability / contract only.
Nothing re-optimized, no threshold changed, no policy rerun, canonical collector untouched.

---

# EXECUTIVE VERDICT

```text
B. CLAUDE STUDY USED CAUSALLY AVAILABLE RAW SCORES OUTSIDE THE
   FROZEN MODEL DOMAIN; PREDICTIVE RESULT IS DESCRIPTIVE/EXPLORATORY,
   NOT CURRENTLY DEPLOYABLE
```

**Codex is right, and the two studies never disagreed about a number.** Every one
of Codex's strict in-domain counts reproduces *exactly* through an independent
code path that never touches my derived panel. The disagreement is entirely about
**which score stream** was being counted.

The decisive fact, which my study did not state and should have:

> **At the 60s and 120s landmarks, ZERO of 4,594 and 4,403 evaluated trades had a
> contract-valid in-domain score. Not one.** At 180s it is 61 of 3,908 (1.6%); at
> 300s, 525 of 3,209 (16.4%).

So the AUC figures 0.684 / 0.735 / 0.753 / 0.780 were computed almost entirely on
scores emitted **outside the frozen model's domain contract**.

### Answering the six questions in plain English

**1. What score did the study actually use?**
The raw probability of the model whose *domain* is the newly confirmed regime —
`bullish_probability` when the new regime is bullish, `bearish_probability` when
bearish — taken **without gating on the `*_in_domain` flag**. In
`phase0_gate1.py` this column is literally named `in_domain_score`. **That name is
a misnomer and it is the direct cause of the apparent conflict.** The panel
renames it `score_b` and SPEC §1.2 describes it correctly as "domain-model raw,
ungated", but the misleading name survived in the Gate 1 module.

**2. Was it available causally?**
**Yes, unambiguously.** Three independent checks:
- `*_score_available_ns − checkpoint_decision_ns == 0` for **all 5,665,103** RTH
  rows (min = median = max = 0). The score is available at the instant it is
  decided; there is no lookahead.
- `*_score_is_new` is `true` for **100%** of RTH rows. Every value is a real model
  dispatch, never a carried-forward copy.
- Score age at the landmark is median 0–5s, p90 5s, max 85s. The landmark takes
  the most recent *real* dispatch at or before it; nothing is forward-filled,
  interpolated, or as-of joined from a stale source.

**3. Was it in-domain under the frozen model contract?**
**No — overwhelmingly not.** 0% at 60s, 0% at 120s, 1.6% at 180s, 16.4% at 300s.
In the 76-trade reconciliation sample, 235 of 242 trade×landmark rows had
`in_domain = false`.

**4. Why does Codex see only 159 observable failures while this study evaluates thousands at early landmarks?**
Because the `*_in_domain` flag is a **contract gate**, not an **availability
gate**, and the two studies chose opposite sides of it.

A probability is emitted whenever `*_feature_complete` is true — which holds for
**4,066,691 out-of-domain rows**. The flag gates whether that score may
*qualify a trade under the frozen contract*, not whether a number exists. Codex
counted contract-valid observations (159/2,181 failures with ≥3). I counted
emitted observations (2,181/2,181 with ≥1). Both counts are correct; they measure
different things. The gap is created by the established-regime gate, which opens
a median 352–448s after confirmation while failed trades die at a median
217–300s.

**5. Does AUC 0.684 → 0.780 remain valid?**
**As exploratory out-of-domain evidence: yes.** The arithmetic is sound, the
scores are real causally-available dispatches, the landmark design is intact, and
`lookahead-auditor` cleared the causal logic.

**As deployable evidence: no.** A live system honouring the frozen contract would
not have a score to read at 60s or 120s post-confirmation in *any* of these
trades. The number describes what an uncalibrated out-of-domain model read would
have shown, not what a contract-compliant system could act on.

**As invalid evidence: no.** Nothing is wrong with it except its label.

**6. What needs to be rerun?**
**No analysis needs rerunning.** The study's terminal conclusion is unaffected and
is, if anything, reinforced: the verdict was already
`POST-CONFIRMATION SCORE PREDICTS FAILURE BUT TOO LATE TO MONETIZE`, driven by
the placebo null (no operating point beat a matched random exit), not by the AUC.
A signal that is also not contract-deployable is further from usable, not closer.

What needs **correcting is documentation**, in three places:
1. Rename `in_domain_score` → `domain_model_raw_score` in `phase0_gate1.py`.
2. State the 0% / 0% / 1.6% / 16.4% contract-validity figures wherever the AUC is
   quoted. The study said stream B "reads the model outside its contractual
   domain" but never quantified how total that is at the early landmarks.
3. Label the AUC explicitly as **exploratory out-of-domain**.

---

## Phase 1 — Score column lineage

`score_column_lineage.json`. Empirically asserted, not inferred from naming.

| Column | Defined at | Expression | Gated on `*_in_domain`? | Model / direction |
|---|---|---|:--:|---|
| `in_domain_score` | `phase0_gate1.py:115-117` | `when(direction==1).then(bullish_probability).otherwise(bearish_probability)` | **NO** | model whose domain **is** the new regime |
| `ood_score` | `phase0_gate1.py:112-114` | the opposite column | **NO** | the other model, out of its own domain |
| `score_b` | `build_panel.py:120-123` | identical to `in_domain_score` | **NO** | same |
| `score_c` | `build_panel.py:124-126` | identical to `ood_score` | **NO** | same |
| `stream_a_in_domain` | `build_panel.py:129-131` | the `*_in_domain` flag itself | n/a | diagnostic only, never a predictor |

For all score columns: source table `canonical_regime_scores_all.parquet`;
carried-forward **no**; as-of join **no**; reconstructed **no**; true dispatch at
that timestamp **yes**; causally available at the decision timestamp **yes**;
feature contract valid **yes wherever the probability is non-null** —
`*_feature_complete` and probability-presence agree with **0 mismatches** on both
models across all 5,665,103 rows.

Probability presence by flag — this is the crux of the whole disagreement:

| | rows | probability present | % |
|---|---:|---:|---:|
| `bullish_in_domain = false` | 4,446,640 | 4,066,691 | 91.46 |
| `bullish_in_domain = true` | 1,218,463 | 1,123,834 | 92.23 |
| `bearish_in_domain = false` | 4,677,743 | 4,301,268 | 91.95 |
| `bearish_in_domain = true` | 987,360 | 904,560 | 91.61 |

**The emission rate is essentially identical in and out of domain.** The flag
carries no information about whether a number exists.

---

## Phase 2 — Trade × landmark reconciliation

`sample_trade_timestamp_reconciliation.parquet`. Deterministic (seed 20260810),
**76 trades / 242 trade×landmark rows**, spanning all required strata:

- CONFIRMED_THEN_STOPPED 20 · FINAL_FLIP_EXIT_LOSER 22 · FINAL_FLIP_EXIT_WINNER 29 · SESSION_EXIT 5
- LONG 37 · SHORT 39
- includes trades Codex would call zero-observation, trades both systems accept,
  very short-lived failures (hold ≤ 120s), and long-lived winners (hold ≥ 1200s)

| | count |
|---|---:|
| `score_causally_available_at_landmark = true` | **242 / 242** |
| `contract_valid_at_landmark = true` | **8 / 242** |
| `actual_in_domain_flag = true` | 7 |
| `score_is_new = true` (all sampled rows) | yes |
| max score age at landmark | 15.0s |

Contract validity by landmark: **60s → 0/76 · 120s → 0/65 · 180s → 0/55 ·
300s → 8/46.**

Each row carries the canonical `bullish_probability`, `bearish_probability`, both
`*_in_domain` flags, the true dispatch timestamp, `score_observation_id`, the
expected model for the new regime, and the exact code path that selected the
score.

---

## Phase 3 — Count reconciliation (independent code path)

`canonical_coverage_recompute.json`. Read straight from
`canonical_regime_scores_all.parquet`; the study's derived panel is not used
anywhere in this computation.

| Terminal label | population | strict in-domain ≥3 | **Codex ≥3** | match | raw domain ≥1 |
|---|---:|---:|---:|:--:|---:|
| CONFIRMED_THEN_STOPPED | 822 | **32** | 32 | ✓ | 822 (100%) |
| FINAL_FLIP_EXIT_LOSER | 1,359 | **127** | 127 | ✓ | 1,359 (100%) |
| FINAL_FLIP_EXIT_WINNER | 2,350 | **1,628** | 1,628 | ✓ | 2,350 (100%) |
| SESSION_EXIT | 174 | **72** | 72 | ✓ | 125 (71.8%) |
| **failures total** | **2,181** | **159** | 159 | ✓ | **2,181 (100%)** |

**Every Codex figure reproduces exactly.** The two studies agree completely on
the strict stream. The 159 vs 2,181 gap is the entire substance of the
disagreement, and it is a stream-selection difference, not a defect in either
implementation.

---

## Phase 4 — Landmark availability

`landmark_availability_reconciliation.json`.

| landmark | alive | true dispatch ≤ t | raw domain score | **contract-valid in-domain** | used despite flag = false | carried/as-of | median score age |
|---|---:|---:|---:|---:|---:|---:|---:|
| 60s | 4,594 | 4,594 | 4,594 | **0** | 4,594 | 0 | 5.0s |
| 120s | 4,403 | 4,403 | 4,403 | **0** | 4,403 | 0 | 5.0s |
| 180s | 3,908 | 3,908 | 3,908 | **61** | 3,847 | 0 | 0.0s |
| 300s | 3,209 | 3,209 | 3,209 | **525** | 2,684 | 0 | 0.0s |

Failure vs winner coverage, raw / strict:

| landmark | failures | winners |
|---|---|---|
| 60s | 100% / **0%** | 100% / **0%** |
| 120s | 100% / **0%** | 100% / **0%** |
| 180s | 100% / 0.68% | 100% / 2.11% |
| 300s | 100% / 7.58% | 100% / 19.61% |

Two things this makes obvious.

**The raw stream is outcome-neutral (100% everywhere); the strict stream is
not** — at 300s it covers 19.6% of winners against 7.6% of failures. That
asymmetry is exactly why my study excluded stream A: its availability is
determined by the outcome being predicted. That exclusion decision remains
correct.

**But the price of that exclusion was total loss of contract validity at the
early landmarks**, which my study did not quantify. Both facts are true at once,
and the study reported only the flattering one.

---

## What this changes, and what it does not

**Does not change:**
- Terminal label **B** (`PREDICTS FAILURE BUT TOO LATE TO MONETIZE`). It rests on
  the placebo null — not one of 25 operating points beat a matched random exit —
  which is untouched by this reconciliation.
- The population reconciliation (822 / 1,359 / 2,350 / 174), the landmark design,
  the duration-confound handling, and all nine validation gates.
- The causal-availability claim. It is now verified three ways rather than
  asserted.

**Does change:**
- The AUC 0.684 → 0.780 must be labelled **exploratory out-of-domain**, and cited
  with the 0% / 0% / 1.6% / 16.4% contract-validity figures.
- `in_domain_score` is a misleading name and must be renamed.
- Any future work proposing to *deploy* a post-confirmation score signal must
  first solve the established-gate latency problem — a median 352–448s to
  contract validity against failures that die in 217–300s. No amount of modelling
  on stream B addresses that.

**Honest note on my own reporting.** The study did document the stream choice —
SPEC §1.2/§1.3, README, REPORT §2.2 all state that stream B is read outside its
contractual domain and that frozen thresholds do not transfer. What it did not do
is quantify that **0% of the 60s and 120s evaluations were contract-valid**, and
it left a column named `in_domain_score` that means the opposite. A reader
comparing against Codex would reasonably conclude the two were irreconcilable.
They are not, but the study made that harder to see than it needed to be.

---

## Artifacts

```text
reconciliation/SCORE_STREAM_RECONCILIATION_REPORT.md      this file
reconciliation/score_column_lineage.json                  Phase 1
reconciliation/sample_trade_timestamp_reconciliation.parquet  Phase 2, 76 trades / 242 rows
reconciliation/canonical_coverage_recompute.json          Phase 3, independent path
reconciliation/landmark_availability_reconciliation.json  Phase 4
reconciliation/reconcile.py                               all four phases
```

> **Note on the Phase 2 artifact.** `sample_trade_timestamp_reconciliation.parquet`
> is produced as specified and exists locally, but the repository's
> commit protocol excludes `*.parquet`. Because this table is *evidence* rather
> than regenerable research data, an identical
> `sample_trade_timestamp_reconciliation.csv` (242 rows × 33 columns, 145 KB) is
> committed alongside so the provenance record is version-controlled. Both are
> written by `reconcile.py`.

# Post-Confirmation MFE Monetization — Frozen Specification

**Study:** `top10_post_confirmation_mfe_monetization` · **Frozen:** 2026-08-10, before implementation.
**Substrate:** `data/canonical/regime_complete_v1/`

---

## 0. Objective

The entry architecture is **frozen**: regime age >600s, first true causal Top-10
crossing from below, fade entry, 1.00 ATR initial stop, confirming flip = the
regime flipping into the trade's direction. No model retraining, no entry change,
no initial-stop optimization, no large exit grid.

The problem is **after confirmation**. The accepted excursion work puts roughly
**0.89 ATR per original Top-10 entry** of MFE/giveback currently surrendered.
Economic target: recover **35–50%** of it (≈ +0.31 to +0.45 ATR per original
entry) without destroying the large runners. That is a target, not a validity
criterion.

**Central hypothesis:** the first P90 (Top-10 tail) warning of the fade model
belonging to the NEW confirmed regime marks the point where enough of the runner
has been realised to exit or aggressively protect.

---

## 1. Phase 0 findings that constrain the design

### 1.1 Top-20 / P80 exists — Phase 8 runs

Verified in `canonical_model_threshold_contracts.parquet`: `top_20` is present
for **both** models, `is_frozen = true`, availability
`RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION`
(bullish 0.34374423771129053, bearish 0.3745119841718754). Accepted provenance,
so Phase 8 is enabled and no interpolated level is needed.

### 1.2 Contract-valid P90 is NOT MEASURABLE, not merely non-deployable

Coverage of the first post-confirmation crossing, by eventual outcome:

| Outcome | n | **A** contract-valid | **B** raw causal |
|---|---:|---:|---:|
| CONFIRMED_THEN_STOPPED | 822 | **0.4%** | 97.2% |
| FINAL_FLIP_EXIT_LOSER | 1,359 | **1.0%** | 99.2% |
| FINAL_FLIP_EXIT_WINNER | 2,350 | **47.9%** | 99.6% |
| SESSION_EXIT | 174 | 13.2% | 51.7% |

Stream A fires on **48–120× more winners than losers**, because the in-domain
flag requires the new regime to be *established* — a median 352–448s after
confirmation — and only long-lived trades survive that long. Long-lived means
winner.

**Consequence.** A policy "exit at contract-valid P90" does nothing on 99% of
losers and truncates roughly half the winners. Its existence is almost perfectly
correlated with the outcome it is meant to predict, so any PnL it shows is a
survivorship artifact rather than a measurement.

Stream A is therefore evaluated **because the brief asks for it**, but every
result carries `NOT INTERPRETABLE — SURVIVORSHIP`, which is a stronger warning
than "not deployable". P80 stream A behaves identically (1.6% / 3.3% of losers vs
58.9% of winners) and inherits the same label.

**Stream B is the primary object of study.** It has 97–99.6% coverage on every
outcome group, so it is at least measurable. Every stream-B result carries
`EXPLORATORY_OUT_OF_DOMAIN`. A and B are never combined or averaged.

---

## 2. Frozen contract

```text
entry              the frozen Top-10 arm; entry price checkpoint_reference_price,
                   ATR atr_at_checkpoint, both frozen for the trade
initial stop       1.00 ATR from entry, LIVE IN EVERY POLICY (not optimized)
confirming flip    next_start_after(entry_ns, direction, inclusive=True)
new-regime model   the model whose domain IS the new regime: bullish when the
                   new regime direction is +1, else bearish. A RISING score means
                   the new regime is likely to end, i.e. danger to our position.
natural exit       first of: 1 ATR stop, opposing regime flip, 15:00 CT
fills              a trigger observed on a completed 1s bar (or at a score
                   decision ns) fills at the FOLLOWING bar's open; the trigger
                   price is never credited
session            RTH only, clamped to the entry's own session, no overnight
cost               2 ticks round-turn = 0.50 points
same-bar ties      resolved adversely, flagged, both bounds reported
```

Every excursion is normalised by the **entry** ATR so all phases are
commensurable.

---

## 3. Populations and the two denominators

Primary management population = confirmed trades (reached the confirming flip
before the initial stop). **Every economic result is ALSO reported per ORIGINAL
Top-10 entry**, so nothing is inflated by conditioning on survivors.

---

## 4. Policies — cap 16 including baseline (14 + baseline run)

| # | Policy | Stream |
|---|---|---|
| 0 | `BASELINE` natural exit | — |
| 1 | `P90A_EXIT` exit at first contract-valid P90 | A |
| 2 | `P90B_EXIT` exit at first raw-causal P90 | B |
| 3–6 | `PRICE_A/B/C/D` MaxMFE ≥1.0/1.5/2.0/2.0 ATR then 0.75/0.75/0.75/1.00 giveback | price only |
| 7 | `P90ARM_GB050` P90(B) arms, exit on 0.50 ATR giveback from running MaxMFE | B |
| 8 | `P90ARM_GB075` same at 0.75 ATR | B |
| 9 | `P90ARM_PRICE` exit if price crosses back adversely through the P90 observation price | B |
| 10 | `P90ARM_PRICE_BUF` same with ONE buffer, justified by observed retracement geometry | B |
| 11–13 | `P80ARM_075`, `P80ARM_100`, `P80ARM_P90EXIT` | B (A reported separately) |
| 14 | `STAIRSTEP` one landmark-adaptive ladder derived from Phase 2 bands | price only |

No grid. Buffers and rungs are derived from observed geometry, not tuned.

---

## 5. Mandatory analyses

**Phase 1** baseline geometry, reconciled against the accepted excursion study.
**Phase 2** landmark/runner geometry from ORIGINAL ENTRY at
+0.50/0.75/1.00/1.50/2.00/2.50/3.00 ATR.
**Phase 3** first P90 event location, A and B separately.
**Phase 4** does P90 sit near MaxMFE — `realised fraction of final MFE at P90`,
remaining MFE, seconds P90→MaxMFE, and the ≥50/60/70/80/90% shares. **This is the
hinge the whole economic case turns on.**
**Phases 5–9** the policies above.
**Phase 10** runner destruction — for baseline MaxMFE ≥2.0/2.5/3.0/4.0 ATR, the
share exited before reaching that landmark and the ATR surrendered. **Mandatory
for every policy.**
**Phase 11** giveback recovery as a % of the baseline pool, over confirmed trades
and over original entries; bands ≥25% / ≥35% / ≥50%.
**Phase 12** loss containment on confirmed trades that finished negative.

**Counterfactual, mandatory.** Every model finalist is compared against the
closest price-only trail of similar aggressiveness. If the price-only rule does
as well, the report says so plainly. This research line has twice mistaken
"exiting earlier than a bad exit" for an edge.

---

## 6. Deliverables

`SPEC.md` · `README.md` · `REPORT.md` and, under `results/`:
`baseline_geometry`, `runner_landmarks`, `p90_event_geometry`,
`p90_mfe_location`, `policy_results`, `runner_destruction`, `loss_containment`,
`giveback_recovery`, `year_direction_stability` (parquet + CSV mirrors),
`finalist_shortlist.json`, `validation_report.json`, `partition_manifest.json`.

## 7. Final classification

Exactly one of: **A** P90 direct exit materially improves MFE capture · **B** P90
better as a protection arm than an exit · **C** P80 arm → P90 exit/protection
warrants validation · **D** price-only protection outperforms model-based
management · **E** multiple architectures warrant bounded validation · **F** no
robust post-confirmation MFE monetization found · **G** result invalid / contract
failure.

Advancement requires: material ATR/original-entry improvement; meaningful
giveback recovered; ≥2.5/≥3 ATR runners preserved; confirmed losers improved;
stable across years and directions; not dependent on few trades; audit clean;
out-of-domain use disclosed. **≤3 finalists.**

## 8. Validation

```text
 1 frozen Top-10 entry population reproduced exactly
 2 confirmed population reproduced exactly
 3 accepted excursion/giveback baseline reconciled
 4 post-confirm score belongs to the correct NEW regime and model
 5 score causally available at its decision timestamp
 6 in-domain vs raw-causal distinguished everywhere
 7 P90 crossing uses the previous true observation from the same regime
 8 no carry-forward counted as a crossing
 9 exit fills strictly causal (following bar's open)
10 no overnight stitching; session containment
11 same-bar stop/exit ambiguity flagged and resolved adversely
12 >= 200 trades replayed independently from raw 1s
13 causal_lint · 14 lookahead-auditor · 15 contract-checker
```

Any CRITICAL finding blocks conclusions.

## 9. Domain and non-goals

NQ `*.v.0`, 2021–2025, RTH. **2025 is NOT threshold-OOS** (inherited waiver).
2026 untouched. No retraining, no entry change, no initial-stop optimization, no
grid, no new threshold, no promotion of a stream-B result to deployable.

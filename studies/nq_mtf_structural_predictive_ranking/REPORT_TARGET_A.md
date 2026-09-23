# DID THE FULL T0 MODEL RANK 2024 TRADES?

**No.**

The 78-variable T0 MTF + structural-geometry model, trained only on 2023 and applied once to 2024 under
boundaries frozen before any 2024 row was scored, produced an out-of-sample ROC AUC of **0.5137, 95% CI
[0.4996, 0.5284]** — an interval that contains chance. It did not beat any of the three simple controls, and
it produced **no monotonic economic concentration**: the Spearman correlation between its frozen score decile
and mean terminal gross PnL (ATR) in 2024 is **−0.33**. Its highest-score decile earned **+0.143 A** per trade;
its lowest-score decile earned **+0.159 A**.

The same model scores **0.9783** on the 2023 rows it was fitted on. That gap — 0.978 in-sample to 0.514
out-of-sample — is the finding. The surface is rich enough to memorise a year and carries essentially no
transferable T0 rank information about whether a regime-flip trade ends gross-positive.

---

## 1. Target, population, prevalence (declared before fitting, never changed)

`target_A_win` = `terminal_gross_pnl_atr > 0`, expression SHA256
`edb73ed2b2d0a79ad955d595a8b6cb00307b16974e19956adf0b39d82e7986f1`.

| | 2023 (fit + development) | 2024 (frozen evaluation) |
|---|---|---|
| eligible N (T0, `checkpoint_index == 0`) | 7,475 | 7,047 |
| positive | 2,475 | 2,378 |
| negative | 5,000 | 4,669 |
| null (no terminal gross PnL) | 14 | — excluded, same rule |
| prevalence | 0.3311 | 0.3374 |
| session days | 257 | 258 |
| trades / session | 29.09 | 27.31 |

Pooled 2024 baseline: **win 33.74%** (CI [32.73, 34.82]), mean gross **+0.042 A**, median **−0.703 A**,
reach +2A 38.3%, reach +3A 25.6%. The median trade loses; the mean is carried by a right tail.

## 2. The four frozen surfaces, as fitted

All four fitted on the **7,475 2023 T0 rows only**. `tuning_years: [2023]`,
`final_train_validation_years: []` — 2024 took no part in fitting, validation-during-fit, or any selection of
feature, hyperparameter, threshold, model or score boundary. Model lineage records `train_years: [2023]`.
All four authenticated (`authenticate_model`) at scoring time and their ordered feature lists re-checked
against the freeze receipt.

| arm | features | model SHA256 (16) | fit rows |
|---|---|---|---|
| `full` | 78 | `3cf8c5493fef66a7` | 7,475 |
| `geometry_no_direction` | 71 | `410e6146680484b6` | 7,475 |
| `mtf_state_only` | 4 (`dir_1m/5m/15m/1h`) | `48e72fc1509d6547` | 7,475 |
| `direction_only` | 1 (`dir_1m`) | `042c613e66214a54` | 7,475 |

## 3. The freeze, before the first 2024 score

`artifacts/evaluation_freeze.json`, `freeze_sha256`
`357302cbc632f504dbf4acafa4877c88bb65aafef4f7be878d9ab955eedd28cd`, written and hashed **before** any 2024
row was scored. It fixes, per arm: model id and SHA, ordered feature list and its SHA, target expression SHA,
training years and N, 2023 class balance, score orientation, coverage and trades/session definitions, the
metric list, the **2023 score deciles (q0.1…q0.9)** and the **top 50/30/20/10 boundaries**. The 2024 scoring
pass refuses to run if that file is absent, and records its byte hash in its own receipt
(`artifacts/oos_2024_evaluation.json`).

2024 rows were assigned to deciles and top-k surfaces with **those** 2023 boundaries. Nothing was re-quantiled,
recalibrated, refitted, or re-chosen after 2024 was seen.

## 4. 2024 result, per model

| arm | dev 2023 AUC (in-sample) | **2024 AUC** | 95% CI | beats chance | ρ(decile, win) | ρ(decile, mean A) |
|---|---|---|---|---|---|---|
| `full` | 0.9783 | **0.5137** | [0.4996, 0.5284] | **no** | 0.50 | **−0.33** |
| `geometry_no_direction` | 0.9728 | 0.5112 | [0.4975, 0.5247] | **no** | 0.78 | −0.15 |
| `direction_only` | 0.5263 | 0.5168 | [0.5036, 0.5301] | marginally | 1.00 | 1.00 |
| `mtf_state_only` | 0.5376 | 0.5208 | [0.5057, 0.5355] | marginally | 0.77 | 0.18 |

Intervals are a **day-blocked bootstrap** (2,000 resamples over the 258 session days): T0 rows inside one
session are not independent, and a row-level bootstrap would overstate precision.

**`full` against each control**, paired on the same rows:

| comparison | ΔAUC | 95% CI |
|---|---|---|
| `direction_only` − `full` | +0.0026 | [−0.0152, +0.0206] |
| `geometry_no_direction` − `full` | −0.0025 | [−0.0121, +0.0073] |
| `mtf_state_only` − `full` | +0.0064 | [−0.0124, +0.0261] |

Every interval straddles zero. **The 78-variable surface did not beat a single binary 1m-direction flag.**
Nominally it lost to two of the three controls.

### `full` — win rate and economics by frozen 2023 decile

| decile | N | coverage | win % | mean A | median A | +2A % | +3A % | trades/session |
|---|---|---|---|---|---|---|---|---|
| D1 | 111 | 1.6% | 32.4 | +0.159 | −0.679 | 36.9 | 25.2 | 0.43 |
| D2 | 293 | 4.2% | 33.8 | +0.206 | −0.727 | 39.6 | 27.6 | 1.14 |
| D3 | 480 | 6.8% | 33.1 | +0.140 | −0.692 | 37.3 | 26.0 | 1.86 |
| D4 | 743 | 10.5% | 32.3 | −0.052 | −0.714 | 37.4 | 24.4 | 2.88 |
| D5 | 1,102 | 15.6% | 33.1 | +0.068 | −0.730 | 37.4 | 25.0 | 4.27 |
| D6 | 1,352 | 19.2% | 32.1 | +0.007 | −0.764 | 37.3 | 24.8 | 5.24 |
| D7 | 1,604 | 22.8% | 34.3 | −0.023 | −0.683 | 39.5 | 26.1 | 6.22 |
| D8 | 968 | 13.7% | 36.5 | +0.132 | −0.650 | 38.7 | 27.0 | 3.75 |
| D9 | 313 | 4.4% | 36.7 | +0.011 | −0.561 | 39.9 | 24.9 | 1.21 |
| D10 | 81 | 1.1% | 33.3 | +0.143 | −0.702 | 43.2 | 24.7 | 0.31 |

Win rate drifts up about 4 points from D1 to D9 and then falls back at D10. Mean gross ATR does not order at
all. Note also the **coverage collapse**: the 2023 boundaries put only 1.6% and 1.1% of 2024 rows in D1 and
D10, with the mass piled into D5–D8 — the 2024 score distribution is much narrower than 2023's, which is
itself evidence that what the model learned in 2023 did not recur.

### Top-k surfaces under the frozen 2023 thresholds

| arm | surface | threshold | N | coverage | win % | mean A | +2A % | trades/session |
|---|---|---|---|---|---|---|---|---|
| `full` | top 50 | 0.2748 | 4,318 | 61.3% | 34.3 | +0.027 | 38.7 | 16.74 |
| | top 30 | 0.4278 | 1,362 | 19.3% | 36.3 | +0.105 | 39.3 | 5.28 |
| | top 20 | 0.5357 | 394 | 5.6% | 36.0 | +0.038 | 40.6 | 1.53 |
| | top 10 | 0.6407 | 81 | 1.1% | **33.3** | +0.143 | 43.2 | 0.31 |
| `geometry_no_direction` | top 30 | 0.4211 | 1,392 | 19.8% | 35.8 | +0.110 | 40.2 | 5.40 |
| | top 10 | 0.6337 | 104 | 1.5% | 36.5 | +0.019 | 45.2 | 0.40 |
| `mtf_state_only` | top 30 | 0.3559 | 2,507 | 35.6% | 35.6 | +0.086 | 37.2 | 9.72 |
| | top 10 | 0.3763 | 984 | 14.0% | 36.1 | +0.111 | 38.0 | 3.81 |
| `direction_only` | top 10/20/30/50 | 0.3543 | 3,521 | 50.0% | 35.2 | +0.074 | 37.2 | 13.65 |

Top-10 win lift over the pooled 33.74% baseline, day-blocked bootstrap:

| arm | lift | 95% CI | |
|---|---|---|---|
| `full` | **−0.4 pp** | [−10.8, +11.3] | not significant |
| `geometry_no_direction` | +2.8 pp | [−7.8, +12.9] | not significant |
| `mtf_state_only` | +2.3 pp | [−0.5, +5.0] | not significant |
| `direction_only` | +1.5 pp | [+0.3, +2.7] | nominally significant |

The single interval that clears zero belongs to the **one-bit control**, is worth 1.5 percentage points, and
is one of twenty nominal comparisons made here (4 arms × AUC + 4 surfaces). It does not survive any
multiplicity adjustment, and it is not the hypothesis under test. Read plainly, it says only that one of the
two 1m directions won slightly more often in 2024 — and that fact was already visible without a model.

Two arms have **degenerate deciles**, which is arithmetic, not a defect: `direction_only` has one binary input
and therefore exactly two distinct scores, so all four of its top-k surfaces collapse onto the same 50% of
rows; `mtf_state_only` has 16 reachable states and leaves D1 empty.

## 5. FULL vs the three controls — the actual comparison

The study was designed to answer whether **joint** T0 MTF state plus structural geometry ranks better than
crude direction. It does not:

- against `direction_only` (1 feature): **−0.0026 AUC**, interval straddling zero; and `direction_only`'s
  economic lift is the only one that clears zero.
- against `mtf_state_only` (4 features): **−0.0064 AUC**, interval straddling zero.
- against `geometry_no_direction` (71 features): **+0.0025 AUC**, interval straddling zero — the 7 direction
  columns add nothing to the 71 geometry columns, and the 71 geometry columns add nothing to nothing.

The two high-capacity arms (78 and 71 features) memorised 2023 to 0.978/0.973 and both landed below the two
low-capacity controls out of sample. That ordering — capacity inversely related to OOS performance — is the
signature of a feature surface with no transferable structure for this target.

## 6. The one weak gradient, and why it is not money

The only quantity that orders at all consistently across the high-capacity arms is **+2A reach**:
`full` D10 reaches +2A 43.2% of the time against a 38.3% pooled rate; `geometry_no_direction` D10 reaches
45.2%. But this does not convert: those same deciles' mean gross ATR is flat or lower, and both arms' extreme
deciles — top **and** bottom — show elevated mean ATR (`full`: D1 +0.159, D10 +0.143, against +0.042 pooled).

Extreme scores in either direction mark **higher-variance** trades, not better ones. That is the same
"predicts spread, not drift" pattern the frozen 2023 atlas recorded for this surface, now reproduced
out-of-sample in 2024 under a model that never saw 2024. It is a consistent structural fact about the T0
surface, and it is not tradeable as a directional edge.

## 7. Feature interpretation (explanatory only, produced after the evaluation above was frozen and reported)

No retraining, no re-scoring, no change to anything above. LightGBM gain importance for `full`:

| rank | feature | gain |
|---|---|---|
| 1 | `age_s_5m` | 5.13% |
| 2 | `retained_5m` | 4.93% |
| 3 | `retained_15m` | 4.85% |
| 4 | `atr_entry_1m` | 4.70% |
| 5 | `atr_5m` | 4.11% |
| 6 | `age_s_15m` | 4.06% |
| 7 | `pnl_atr_5m` | 4.05% |
| 8 | `retained_1h` | 3.67% |
| 9 | `pnl_atr_15m` | 3.38% |
| 10 | `atr_15m` | 3.10% |

Importance is **diffuse** — the top feature carries 5.1% and the top fifteen about 55% of total gain across 78
features. Nothing dominates. The leaders are all high-cardinality continuous columns (`age_s`, `atr`,
`retained`, `pnl_atr`), which is what a tree ensemble selects when it is fitting noise: they simply offer the
most valid split points. No MTF direction column and no discrete structural-geometry variable ranks near the
top. This is consistent with, not additional to, the null result — it explains *how* the model memorised
2023, not *what it knows*.

## 8. Method limitations, stated plainly

1. **The 2023 development AUCs are in-sample and carry no information.** With one tuning year and no
   within-2023 holdout, the models were scored on the same 7,475 rows they were fitted on. 0.978 is a
   memorisation measurement. It is reported here only to quantify the in-sample/out-of-sample gap, and it was
   never used to select anything. Any future run on this surface should carve a within-2023 holdout so the
   development number means something before a year is spent.
2. **2024's protection came from the freeze receipt, not from the chronology gate.** Because both years were
   re-attested as reused `train:`-role partitions (`chronology.train: [2023, 2024]`, `oos: []`), the platform's
   chronological OOS gate was not the mechanism keeping 2024 dark. The mechanisms that were: `tuning_years:
   [2023]`, `final_train_validation_years: []`, model lineage `train_years: [2023]`, `final_fit_rows` = 7,475 =
   exactly the 2023 T0 count, and a boundary freeze hashed before the first 2024 score. Declaring 2024 as an
   `oos:` year would change the authorised year roles and break partition re-attestation, forcing a full replay
   of both years — which the brief forbids. Consequence: the governed `analyze` stage cannot run for a study of
   this shape (`ExperimentAuthorizationError: chronology must declare non-empty train and OOS years`), and the
   study halts at `READY_TO_ANALYZE`. The research is complete; the lifecycle stage is not reachable.
3. **No costs were applied.** Every figure is gross. The pooled median trade is −0.703 A before friction.
4. **One target only.** Targets B–E were frozen and not run, per the brief.

## 9. Recommendation on Targets B–E

**Do not launch B–E as a batch.** The evidence against this feature surface is strong and cheap to state: a
78-feature model that memorised a full year to 0.978 delivered 0.514 on the next year and lost to a one-bit
control. Labels B–E are different outcomes read off the *same* T0 rows through the *same* feature surface, so
the prior that they are also null is high, and running four more targets against one already-opened evaluation
year invites exactly the multiplicity problem that makes the one nominally-significant number above
uninterpretable.

If one further probe is judged worthwhile, the defensible choice is **a single, pre-registered reach-based
target** (+2A before terminal flip), because reach is the only quantity that showed any consistent gradient
(§6) — run with a within-2023 holdout so the development metric is informative, and with the explicit prior
that the 2023 atlas and §6 both say this surface predicts *spread*, not *drift*. A positive result there would
be a volatility/target-selection input, not a directional entry filter.

The honest reading of this study is that **T0 is too early**. Everything in this surface is observable at the
moment of the flip, and at that moment the eventual sign of the trade is close to unknowable from structure.

---

### Artifacts

| file | sha256 / id |
|---|---|
| `study.yaml` compiled plan | `c5737cb1d2cca831430a349ddcf631f150928a6956cc65ca869058ba56fac4f0` |
| `artifacts/partition_reattestation.json` | both partitions `REUSABLE_BY_CLOSURE_ATTESTATION`, replay plan `d917443a…`, neither year replayed |
| `artifacts/experiment_models.json` | fit receipt, target counts, 4 model SHAs |
| `artifacts/evaluation_freeze.json` | `357302cbc632f504dbf4acafa4877c88bb65aafef4f7be878d9ab955eedd28cd` |
| `artifacts/oos_2024_evaluation.json` | one-time 2024 scoring receipt, records the freeze byte hash |
| `artifacts/oos_2024_uncertainty.json` | day-blocked bootstrap intervals + gain importances |

2025 and 2026 were not touched. Neither year was recollected or replayed. No threshold was moved after 2024
was seen.

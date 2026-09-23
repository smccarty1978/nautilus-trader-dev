# Target A — constrained, stationary model methodology study (2023 only)

**Verdict: `NO_DEVELOPMENT_SIGNAL`.** The final 20% of 2023 was **not opened**. 2024, 2025 and 2026 were not
touched: no 2024 row is loaded by this study.

This time the experiment itself worked. Capacity was constrained enough that shuffled labels fit to only
0.58–0.68 training AUC (the old model reached 0.97). With that capacity, the 56-feature stationary surface
shows no chronological Target-A information from early to middle 2023. Every configuration's validation 95% CI
contains 0.50. None of them beats knowing the trade direction alone.

## The ten questions

| # | question | answer |
|---|---|---|
| 1 | Did removing absolute-price coordinates materially reduce non-stationarity? | **Yes, for the 22 price levels.** In the forensic artifact those 22 had 94.8–96.0% of 2024 rows outside the 2023 range; every kept column is ≤3.6%. **A residual remains:** `prior_rotation_seq_{5m,15m,1h}` are monotone counters within the year (Spearman vs. time = 1.00), and 100% of validation rows fall outside their training range. See §6. |
| 2 | Can the constrained model still memorise shuffled labels? | **No.** Random-label training AUC is 0.584 / 0.637 / 0.681, against 0.971 for the old model. However, the real-label training AUC is only 0.003–0.008 above the random-label value, so even the small in-sample fit that remains is capacity rather than structure. |
| 3 | Does `stationary_full` generalise from early to middle 2023? | **No.** Validation AUCs are 0.512, 0.518 and 0.522, and every 95% CI contains 0.50. |
| 4 | Did the development gate permit opening final 2023? | **No.** No configuration was eligible. |
| 5 | If opened, does the final holdout retain skill? | Not evaluated. The holdout is still dark and its labels were never read. |
| 6 | Does `stationary_full` beat `direction_only`? | Not evaluated on the holdout. **On validation, every configuration scores below `direction_only`** (0.528). |
| 7 | Does `stationary_full` beat `mtf_state_only`? | Not evaluated on the holdout. On validation the configurations are +0.005 to +0.015 above 0.506, which is within noise. |
| 8 | Is score concentration monotonic? | **No** on validation. Spearman(quintile, Target-A rate) = 0.6 / 0.8 / 0.5. Spearman(quintile, mean terminal gross ATR) = **−0.7 / −0.7 / −0.3**. |
| 9 | Does the score rank quality or excursion/variance? | **Neither** on validation. +2A and −1A reach are both flat across quintiles, so there is no variance signature either. |
| 10 | Is there enough evidence to justify another untouched-year evaluation? | **No.** |

## 0. Reuse — the exact forensic population, not a replay

Source: the prior study's merged controller frame (`nq_mtf_structural_predictive_ranking/_work/controller/merged`),
read-only. The parquet SHA-256s match its `identity.json` (`candidates 475209b4…`, `observations 98e03dc4…`).
The merge is the same as `lifecycle_v2._train_frame_all_labels`, and the population rule is the forensic one.

| N | positives | negatives | nulls | unique trade keys | duplicates | sessions |
|---|---|---|---|---|---|---|
| 7,475 | 2,475 | 5,000 | 14 | 7,475 | 0 | 257 |

All of these match `TARGET_A_POPULATION_PARITY.csv` and the fit receipt. As a stronger check, the frozen FULL
model (`3cf8c549…`) re-scored over this population reproduces the forensic 2023 score digest `8fa2031cd01d9a7a`
and AUC 0.9782538989898989. That match confirms rows, order and feature values are identical.
Evidence: `artifacts/PHASE0_REUSE_PROOF.json`.

## 1. Stationary surface

The exclusion was derived mechanically from the forensic `TARGET_A_FEATURE_PARITY.csv`. A column is excluded
if and only if `pct_2024_outside_2023_range ≥ 50`. The distribution is bimodal: the highest kept column is
3.6% and the lowest excluded column is 94.8%. The rule produces exactly the 22 columns the audit named: `start_price_*`, `highest_high_*`,
`lowest_low_*`, and `prior_{start,end,mfe,mae}_price_*`. The script refuses to continue if the two lists differ.
The exclusion reads an artifact that already existed; no 2024 data is loaded.

| arm | features | ordered-list SHA-256 (16) |
|---|---|---|
| `stationary_full` | 56 | in `STATIONARY_FEATURE_SURFACE.json` |
| `stationary_geometry_no_direction` | 49 | `stationary_full` ∩ the audited `geometry_no_direction` arm |
| `direction_only` | 1 | `dir_1m` |
| `mtf_state_only` | 4 | `dir_1m/5m/15m/1h` |

No features were added. The two columns that are constant in 2023 were kept; a tree cannot split on them.

## 2. Split (declared and committed before any fit)

The split is by ordered unique sessions: floor(0.6·257) = 154, then floor(0.8·257) − 154 = 51, then the
remaining 52. The boundaries were not searched.

| block | sessions | dates | N | positive rate |
|---|---|---|---|---|
| development train | 154 | 2023-01-03 → 2023-08-07 | 4,521 | 0.3324 |
| development validation | 51 | 2023-08-08 → 2023-10-17 | 1,503 | 0.3320 |
| final holdout | 52 | 2023-10-18 → 2023-12-29 | 1,451 | **dark** |

Disclosure: the forensic 70/30 diagnostic already opened late 2023 from 2023-09-11 onward. The final block
therefore falls inside a window that has been seen before. Nothing in this study was chosen with that window in view.

## 3. Capacity contract

**Old configuration (reported only):** `LGBMClassifier` with n_estimators 400, lr 0.05, num_leaves 31,
min_child_samples 100, subsample 0.8 (**inert**, because subsample_freq was unset), colsample 0.8, seed 42.
This produced 12,400 leaves for 7,475 rows, with no early stopping.

**Ladder (frozen in `CAPACITY_LADDER.json`, commit `8efcc675`, before any fit).** The shared settings are 100
rounds, lr 0.05, min_data_in_leaf 200, L2 10, L1 0, feature_fraction 0.7, bagging_fraction 0.7,
**bagging_freq 1**, seed 42, and no early stopping. Only tree complexity varies between configurations:

| config | num_leaves / max_depth | leaves used | bagging proven active (max pred Δ vs freq=0) |
|---|---|---|---|
| L1_stumps | 2 / 1 | 200 | 0.060 |
| L2_depth2 | 4 / 2 | 371 | 0.081 |
| L3_depth3 | 8 / 3 | 591 | 0.107 |

Each configuration was refit with `subsample_freq=0`, and the predictions differ. That proves the declared
bagging actually applies; the old configuration's inert-subsample defect is not repeated here.

Both controls are exact-cell empirical Target-A rates, smoothed toward the training prevalence with m = 20.
This is the strongest possible use of "knowing the direction / the exact state", and a capacity limit cannot handicap it.

## 4. Random-label canary and real-label development

Target A was shuffled once with the forensic seed **20260923**, on development-train rows only. The
shuffled-label models were never scored anywhere else.

| config | random-label train AUC | real train AUC | real − random | **validation AUC** | 95% CI (session-blocked) | canary | eligible |
|---|---|---|---|---|---|---|---|
| L1_stumps | 0.584 | 0.592 | 0.008 | **0.512** | [0.477, 0.547] | pass | no |
| L2_depth2 | 0.637 | 0.640 | 0.003 | **0.518** | [0.486, 0.550] | pass | no |
| L3_depth3 | 0.681 | 0.683 | 0.003 | **0.522** | [0.491, 0.552] | pass | no |
| control `direction_only` | — | 0.532 | — | **0.528** | [0.496, 0.559] | — | — |
| control `mtf_state_only` | — | 0.553 | — | **0.506** | [0.469, 0.543] | — | — |
| *old model (forensic)* | *0.971* | *0.978* | *0.007* | *(70/30 holdout 0.517)* | | | |

This table is the main result. With capacity constrained, the real-label fit is still indistinguishable from
the random-label fit, and validation stays at chance. Constraining capacity did not uncover a masked signal;
it only removed the memorisation. The only feature that separates at all is `dir_1m`, which carries the most
gain in the stump model. The direction-only control, with no geometry, is the best validation ranker.

### Validation concentration (quintile boundaries come from each model's development-train scores)

| config | Q1 → Q5 Target-A win % | mean terminal gross ATR Q1 → Q5 | +2A-before-terminal % | −1A-before-terminal % |
|---|---|---|---|---|
| L1 | 31.2 · 34.5 · 32.8 · 31.7 · 35.2 | +0.23 · +0.22 · −0.00 · −0.28 · +0.05 | 35.7 · 38.2 · 36.2 · 35.3 · 36.1 | 56.3 · 61.4 · 57.4 · 59.2 · 54.9 |
| L2 | 29.6 · 33.7 · 30.8 · 36.0 · 34.3 | +0.17 · +0.14 · −0.10 · +0.02 · −0.06 | 35.2 · 36.9 · 34.2 · 38.6 · 36.1 | 58.1 · 59.0 · 61.5 · 55.6 · 55.0 |
| L3 | 32.5 · 31.3 · 30.4 · 36.5 · 34.4 | +0.38 · −0.11 · +0.01 · −0.00 · +0.01 | 37.7 · 34.9 · 33.9 · 38.7 · 36.7 | 55.2 · 64.5 · 57.6 · 57.5 · 53.6 |

The top quintile's win rate is 1–4 points above the pooled 33.2%, which is inside the noise for bins of about
300 rows. Mean gross ATR is **inversely** ordered in all three configurations. There is also no
volatility or excursion ranking: both reach rates are flat. Full table: `artifacts/DEVELOPMENT_VALIDATION_BINS.csv`.

## 5. Gate

The predeclared rule is: canary ≤ 0.70 **and** validation-AUC CI lower bound > 0.50. All three configurations
pass the canary and none passes the CI condition. The eligible set is empty, so the result is
**`NO_DEVELOPMENT_SIGNAL`**. No "least bad" configuration was selected, and the final stage refuses to run
(`FINAL_HOLDOUT_LOCKED`). Deliverables 6 and 7 (`FINAL_HOLDOUT_RESULTS`, `SCORE_CONCENTRATION`) were
therefore **not produced**. The contract did not permit them.

## 6. A defect the forensic exclusion rule could not see

`prior_rotation_seq_5m/15m/1h` are **monotone within-year counters**. In development train they run
87→3,113, 25→1,019 and 6→232, all perfectly ordered with time; validation starts above each training
maximum. Their values restart each year, so the 2024-vs-2023 range test in the forensic artifact did not flag
them. That test is the only rule this study was allowed to use.

This does not explain the null result:
- their gain share is small: 0.7%, 1.6% and 2.9% in L1, L2 and L3;
- out of sample they are constant, because every validation row falls on the far side of every split, so they
  cannot rank validation rows.

They are still a time index inside a year and should not be model inputs. The contract was not changed after
results were visible. For any future surface, the fix is a within-year range and monotonicity check next to
the cross-year one. The absolute-price columns themselves showed 0.0% validation-out-of-range inside
Jan–Oct 2023: price extrapolation was not operating in this development window either way.

## 7. What this does and does not license

**It does:** close the question the forensic audit left open. With the audit's two known defects removed
(absolute-price coordinates, and over-capacity with inert bagging), the T0 MTF + structural-geometry surface
still shows no Target-A information when tested chronologically inside 2023. The earlier null was not caused
by a broken experiment. The same answer comes back from a methodologically clean one.

**It does not:** say anything about other targets. The old report found a weak +2A-reach gradient in 2024, and
reach may still be learnable. Testing it would need a new, separately declared study; this one does not change
targets. It also does not reuse or open 2024, which remains contaminated for any future evaluation.

## Artifacts

`artifacts/`: `PHASE0_REUSE_PROOF.json`, `STATIONARY_FEATURE_SURFACE.json`, `TEMPORAL_SPLIT_2023.json`,
`CAPACITY_LADDER.json`, `CONTRACT_FREEZE.json`, `RANDOM_LABEL_CAPACITY.{csv,parquet}`,
`DEVELOPMENT_RESULTS.{csv,parquet}`, `DEVELOPMENT_VALIDATION_BINS.{csv,parquet}`, `DEVELOPMENT_GATE.json`,
`TARGET_A_CONSTRAINED_MODEL_VERDICT.json`. Code: `constrained_model.py` (`contract` → `develop` → `final`;
each stage checks the previous stage's hashes).

```
NO_DEVELOPMENT_SIGNAL
```

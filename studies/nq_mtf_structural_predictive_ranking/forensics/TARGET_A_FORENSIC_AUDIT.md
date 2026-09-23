# Target A forensic audit — is 0.9783 → 0.5137 a real result or a broken experiment?

**Verdict: `PIPELINE_CORRECT_OVERFIT_CONFIRMED`.**

The pipeline is correct. Every parity check is exact — not "within tolerance", exact, to a maximum absolute
difference of **0.0**. Both reported AUCs reproduce from first principles under three independent
implementations. The collapse is real, and two independent diagnostics explain it:

1. **The model reaches AUC 0.9711 on randomly shuffled labels.** The 0.9783 on real labels is therefore not
   evidence of structure. It is a measurement of capacity.
2. **It already fails inside 2023.** On a predeclared chronological split, the FULL model trains to 0.9899 and
   scores **0.5169** on the held-out final 30% of 2023 sessions — statistically indistinguishable from its
   0.5137 on 2024.

The 2024 result was never the moment of failure. Generalisation was already gone months earlier, inside the
training year, where the data is most similar to what the model saw.

This audit changes no frozen artifact, fit none of the frozen models, tuned nothing, selected no features,
opened no Target B–E, and did not touch 2025/2026.

---

## Phase 1–2 — what was trained and what was scored

The merged frame was rebuilt two ways — the platform's own merge semantics
(`lifecycle_v2._train_frame_all_labels`: inner join on `(observation_ts, regime_start_ns, checkpoint_index)`
after dropping duplicated observation columns) and an independent index-aligned join. Both produce **261,997
rows × 211 columns** with **identical row hashes**.

Target A was derived two ways — through the platform's bounded expression grammar
(`research.analysis.expressions`, the exact path the fit stage uses) and as raw pandas
`terminal_gross_pnl_atr > 0`.

| target parity | |
|---|---|
| rows compared | 261,997 |
| **mismatches** | **0** (0.0000%) |
| null differences | 0 |
| recomputed vs fit receipt | `eligible 261,552 / positive 85,458 / negative 176,094 / null 445` — **identical** |

Populations, both years, under one filter applied identically: `_year == Y AND checkpoint_index == 0 AND
derived target ∈ {0,1}`.

| | 2023 | 2024 |
|---|---|---|
| T0 rows in year | 7,489 | 7,060 |
| **eligible N** | **7,475** | **7,047** |
| positive / negative | 2,475 / 5,000 | 2,378 / 4,669 |
| null (excluded) | 14 | 13 |
| prevalence | 0.3311 | 0.3374 |
| unique `regime_start_ns` | 7,475 | 7,047 |
| **duplicate key rows** | **0** | **0** |
| duplicate regime rows | 0 | 0 |
| checkpoint values present | `[0]` | `[0]` |
| session days | 257 | 258 |
| terminal disposition | `LABELED_POSITIVE 7,477 / CENSORED 12` | `LABELED_POSITIVE 7,051 / CENSORED 9` |
| disposition of the excluded nulls | `CENSORED 12 / LABELED_POSITIVE 2` | `CENSORED 9 / LABELED_POSITIVE 4` |
| null rule = "gross PnL is null" | yes | yes |

2023 eligible N equals the fit receipt's `final_fit_rows` (7,475); 2024 eligible N equals the scoring receipt's
`eligible_n` (7,047). **No duplicate removal, join fan-out, disposition handling, null handling, checkpoint
filtering or population-definition difference exists between the two years.** The 12 vs 9 censored rows are
excluded by the same rule in both years, and are too few to matter either way.

Artifact: `TARGET_A_POPULATION_PARITY.csv`.

## Phase 3 + 5 — frame → matrix → model → score parity

Stronger than golden authentication, as requested. Three independent checks per arm:

- **Fit-time matrix parity.** `store_model` persists a golden frame: a deterministic 256-row sample of the
  *actual fit matrix*, drawn with a seed derived from the `model_id`. I rebuilt the fit population
  independently, reproduced that seeded sample, and compared cell by cell.
- **Scoring-path parity.** `model_store.score()` (the path that produced the reported AUCs) against a raw
  `lightgbm.Booster` loaded directly from the canonical bytes, with those bytes re-hashed against the manifest
  first.
- **Feature-position parity.** declared order → manifest `ordered_inputs` → golden frame column order →
  scoring matrix column order, plus the SHA of the ordered list against the manifest's
  `feature_contract_sha256`.

| arm | order == freeze | order SHA == manifest | golden frame max abs diff | NaN pattern | golden score max abs diff | 2023 score max abs diff | 2024 score max abs diff |
|---|---|---|---|---|---|---|---|
| `full` | yes | yes | **0.0** | identical | **0.0** | **0.0** | **0.0** |
| `geometry_no_direction` | yes | yes | **0.0** | identical | **0.0** | **0.0** | **0.0** |
| `mtf_state_only` | yes | yes | **0.0** | identical | **0.0** | **0.0** | **0.0** |
| `direction_only` | yes | yes | **0.0** | identical | **0.0** | **0.0** | **0.0** |

Zero rows differ above a 1e-12 tolerance in any arm, in either year. Feature #37 (`mae_atr_1h`) — and every
other position — is provably the same column in training, in the persisted model, and in scoring.

Artifact: `TARGET_A_PREDICTION_PARITY.csv`.

## Phase 6 — both reported AUCs reproduce

Computed three ways: the platform metric (`research.analysis.metrics.roc_auc`), a hand-rolled Mann-Whitney
rank AUC with tie handling, and `sklearn.metrics.roc_auc_score`.

| arm | 2023 reported | platform | hand-rolled | sklearn | 2024 reported | platform | hand-rolled | sklearn |
|---|---|---|---|---|---|---|---|---|
| `full` | 0.9783 | 0.9783 | 0.9783 | 0.9783 | 0.5137 | 0.5137 | 0.5137 | 0.5137 |
| `geometry_no_direction` | 0.9728 | 0.9728 | 0.9728 | 0.9728 | 0.5112 | 0.5112 | 0.5112 | 0.5112 |
| `direction_only` | 0.5263 | 0.5263 | 0.5263 | 0.5263 | 0.5168 | 0.5168 | 0.5168 | 0.5168 |
| `mtf_state_only` | 0.5376 | 0.5376 | 0.5376 | 0.5376 | 0.5208 | 0.5208 | 0.5208 | 0.5208 |

Every reported number reproduces. Nothing was mis-measured.

## Phase 4 — feature semantics and distribution

Full per-feature table (dtypes, nulls, finite counts, cardinality, min/p01/p10/p25/p50/p75/p90/p99/max,
mean, std, both years): `TARGET_A_FEATURE_PARITY.csv`.

- **dtype changes: 0.** No sentinel changes, no scale/unit changes, no changed category domains.
- **Constant in 2023: `checkpoint_seconds_since_flip`, `bars_1m`** — zero-information columns at T0, carried in
  the surface. Harmless but pointless.
- **Null shifts:** four columns (`prior_frozen_atr_1h`, `prior_mfe_atr_1h`, `prior_mae_atr_1h`,
  `prior_terminal_displacement_atr_1h`) go from 0.0% null in 2023 to 1.206% in 2024. Small, consistent with 1h
  regimes lacking a prior, not material.
- **Sign reversals:** none, other than `dir_1m`'s median moving +1 → −1, which only reflects a shift either
  side of a 50/50 split in flip direction. Not drift.

### The distribution finding

`pct_2024_outside_2023_range` across the 78 features is sharply bimodal — median **0.85%**, 75th percentile
**94.8%**:

| group | features | 2024 rows outside the entire 2023 range |
|---|---|---|
| everything else | 56 | ≤ 3.6% (median 0.85%) |
| **absolute price levels** | **22** | **94.8% – 96.0%** |

The 22 are `start_price_{1m,5m,15m,1h}`, `highest_high_{5m,15m,1h}`, `lowest_low_{5m,15m,1h}`,
`prior_start_price_*`, `prior_end_price_*`, `prior_mfe_price_*`, `prior_mae_price_*`. NQ traded roughly
**10,750–17,165 in 2023** and **16,334–22,152 in 2024**. The ranges barely touch.

Two consequences, both real:

- **Within 2023 these columns are near-perfect memorisation handles** — an absolute price level is close to a
  row identifier.
- **In 2024 they are pure extrapolation.** For ~95% of 2024 rows every price split in every tree resolves the
  same way, because the value is beyond anything the tree ever saw. That is why the 2024 score distribution is
  compressed (sd ratio 2024/2023 = **0.616**) and the frozen 2023 deciles left D1 and D10 nearly empty.

Absolute price levels are non-stationary and should not have been model inputs. **This is a genuine design
defect in the declared feature surface** — but Phase 7 shows it is *not* the primary cause of the collapse, so
it does not rescue Target A. See "What this does and does not license" below.

The next tier of drift is volatility, not structure: `atr_1h` median moves 0.72 of a 2023 SD (45.1 → 53.9),
`atr_15m` 0.57, `atr_5m` 0.54. Real, modest, and 2024 is a higher-volatility year — but at ≤3.6% out-of-range
these columns remain inside the trained domain.

## Phase 7 — one predeclared chronological 2023 holdout

Split declared before any result was observed: **first 70% of 2023 session days train, final 30% holdout,
split by complete trading session, never by row.** One split. Not searched. Exact frozen model class,
hyperparameters, feature surface, target, preprocessing and seed.

Split date **2023-09-11**: train 5,231 rows / 179 sessions (pos 0.3361), holdout 2,244 rows / 78 sessions
(pos 0.3195).

| arm | features | train AUC | **holdout AUC** | frozen 2024 AUC |
|---|---|---|---|---|
| `full` | 78 | 0.9899 | **0.5169** | 0.5137 |
| `geometry_no_direction` | 71 | 0.9865 | **0.5147** | 0.5112 |
| `direction_only` | 1 | 0.5335 | **0.5091** | 0.5168 |
| `mtf_state_only` | 4 | 0.5486 | **0.4985** | 0.5208 |

**This is the decisive result.** The holdout AUC (0.5169) and the 2024 AUC (0.5137) are the same number. The
model does not generalise three months forward inside its own training year.

And the price-extrapolation confound is largely absent here: on the holdout, only **25.2% on average** (range
20.3–35.8%) of rows fall outside the early-2023 range on the 22 price columns, against ~95% for 2024. Skill
does not survive even at a quarter of the extrapolation. That rules out domain shift as the explanation —
`PIPELINE_CORRECT_TEMPORAL_SHIFT` is not supported.

Detail: `TARGET_A_2023_TEMPORAL_HOLDOUT.md`.

## Phase 8 — random-label capacity

Target A shuffled once, seed **20260923** (recorded before running). Same 2023 matrix, same frozen
configuration. Training AUC only; 2024 not scored.

| | training AUC |
|---|---|
| **shuffled labels** | **0.9711** |
| real labels | 0.9783 |

The model fits *random noise* on this sample to 0.9711. The real-label 0.9783 is 0.0072 above it. **In-sample
AUC on this population carries essentially no information about signal**, and the 0.9783 reported as a
development metric should never have been read as anything but capacity.

Detail: `TARGET_A_RANDOM_LABEL_CAPACITY.md`.

## Phase 9 — capacity

`LGBMClassifier`, lightgbm 4.6.0, scikit-learn 1.7.2, seed 42. Frozen params:
`n_estimators 400, learning_rate 0.05, num_leaves 31, min_child_samples 100, subsample 0.8,
colsample_bytree 0.8, verbosity -1`. Unchanged; reported only.

| | |
|---|---|
| trees persisted | 400 |
| total leaves | 12,400 (31 per tree, every tree at the cap) |
| training rows | 7,475 |
| **training rows per leaf** | **0.603** |
| leaves per training row | 1.66 |
| early stopping | none — no validation set is passed to `fit` |
| class weighting | none |
| L1/L2 (`reg_alpha`/`reg_lambda`) | unset — library defaults |
| max_depth | unset — unlimited, bounded only by `num_leaves` |
| **row subsampling (`subsample: 0.8`)** | **INERT** |

Two capacity findings worth stating plainly:

- **The ensemble has more leaves than training rows.** `min_child_samples: 100` bounds any single tree's leaf
  to ≥100 rows, but 400 additively boosted trees give each row a distinctive leaf-membership *combination*.
  That is exactly the capacity the shuffled-label test measured.
- **`subsample: 0.8` never took effect.** LightGBM applies bagging only when `subsample_freq` > 0, and it is
  unset here (default 0). One of the two declared regularisers silently did nothing — the same class of
  silent-hyperparameter-default problem that `CLAUDE.md` §5 warns about. It is recorded honestly rather than
  fixed: changing it would be tuning, which this audit is forbidden from doing.

## Phase 10 — score behaviour

FULL, score distributions:

| population | n | min | p10 | p50 | p90 | max | mean | sd |
|---|---|---|---|---|---|---|---|---|
| 2023 in-sample (frozen model) | 7,475 | 0.018 | 0.116 | 0.275 | 0.641 | 0.922 | 0.331 | 0.197 |
| late-2023 holdout (early-2023 model) | 2,244 | 0.037 | 0.197 | 0.384 | 0.619 | 0.849 | 0.397 | 0.160 |
| 2024 frozen OOS | 7,047 | 0.054 | 0.175 | 0.309 | 0.490 | 0.816 | 0.323 | 0.121 |

Actual Target-A rate by within-population score decile:

| decile | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---|---|---|---|---|---|---|---|---|---|
| **2023 in-sample** | 0.00 | 0.00 | 0.00 | 0.01 | 0.03 | 0.10 | 0.39 | 0.81 | 0.98 | 1.00 |
| **late-2023 holdout** | 0.30 | 0.31 | 0.32 | 0.28 | 0.25 | 0.38 | 0.34 | 0.41 | 0.29 | 0.31 |
| **2024 frozen OOS** | 0.34 | 0.33 | 0.32 | 0.33 | 0.34 | 0.31 | 0.34 | 0.34 | 0.36 | 0.36 |

In-sample the model has sorted the training rows almost perfectly — bottom four deciles at a 0–1% win rate,
top two at 98–100%. That is memorisation rendered visually.

Out of sample, in **both** the holdout and 2024, the relationship is flat. The diagnosis is **complete loss of
the ranking relationship**, not calibration shift and not merely score compression. Compression (sd 0.197 →
0.121) is a real secondary symptom of price extrapolation, but even *within* the compressed 2024 range the
ordering carries nothing.

---

## Interpretation matrix

| case | required evidence | status |
|---|---|---|
| CASE 1 `PIPELINE_DEFECT_FOUND` | any parity failure | **not met** — population, target, feature order/semantics, golden matrix and prediction parity are all exact at 0.0 |
| **CASE 2 memorisation / over-capacity** | parity passes; real train ≈0.98; random-label train also very high; late-2023 holdout ≈0.50; 2024 ≈0.51 | **all five met** (0.9783 / 0.9711 / 0.5169 / 0.5137) |
| CASE 3 `PIPELINE_CORRECT_TEMPORAL_SHIFT` | holdout retains substantial skill, 2024 collapses | **contradicted** — the holdout collapses too, at a quarter of the price extrapolation |
| CASE 4 `INCONCLUSIVE` | conflicting or insufficient evidence | not applicable — the discriminators agree |

## What this does and does not license

**Does:** the reported numbers are correct measurements. `0.9783 → 0.5137` is a real, correctly executed
result, and the study's `NO_INFORMATION` verdict for Target A stands — strengthened, because the two controls
that carry no price columns and almost no capacity (`direction_only`, 1 binary feature; `mtf_state_only`, 4)
also show no within-2023 holdout skill (0.5091, 0.4985). There is no hidden signal being masked by the
memorisation.

**Does not:** this experiment did not cleanly *test* whether T0 MTF + structural geometry carries information,
because it was run at a capacity that fits random labels to 0.97 on a surface containing 22 non-stationary
absolute price columns. A correctly specified version of the question — price levels removed or differenced to
ATR-relative distances, capacity cut to the sample size, `subsample_freq` set so the declared bagging actually
applies, and a within-2023 holdout — remains untested.

Two corrections to how the original report framed things, neither changing its conclusion:

- It reported the in-sample AUC "to quantify the in-sample/out-of-sample gap". Phase 8 shows that gap is
  mostly capacity, not lost signal; the honest statement is that the in-sample number measures nothing else.
- It attributed the collapse to the surface not transferring. More precisely: generalisation fails inside
  2023, and the 2024 number adds price extrapolation on top of an already-absent relationship.

**Recommendation (not executed — it is new research and outside this audit's scope):** if the underlying
question is still worth asking, the next run should be a re-specification, not a re-evaluation. That means
dropping or ATR-normalising the 22 price columns, dropping the two 2023-constant columns, cutting capacity to
the sample, and carrying a within-2023 chronological holdout so the development metric is informative *before*
a year is spent. I have not done any of that here.

## Final verdict

```
PIPELINE_CORRECT_OVERFIT_CONFIRMED
```

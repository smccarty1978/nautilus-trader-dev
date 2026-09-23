# Target A — random-label capacity test (Phase 8)

Purpose: establish whether an in-sample AUC of 0.9783 on 7,475 rows × 78 mostly-continuous features is
evidence of structure, or a measurement of the estimator's ability to memorise this sample.

## Protocol

| | |
|---|---|
| population | 2023 T0 eligible rows only, n = 7,475 |
| feature matrix | the FULL 78-column surface, unchanged |
| labels | Target A **shuffled once**, `numpy.random.default_rng(20260923).permutation(y)` |
| **seed (recorded)** | **20260923** — declared before the run; the shuffle was not repeated or selected |
| model | the exact frozen configuration (`LGBMClassifier`, 400 trees, lr 0.05, 31 leaves, min_child_samples 100, subsample 0.8, colsample_bytree 0.8, seed 42) |
| measured | **training AUC only** |
| 2024 | **not scored** |

Shuffling preserves the class balance exactly (positive rate 0.3311 in both), so the only thing removed is
the association between features and label.

## Result

| labels | training AUC |
|---|---|
| **shuffled (pure noise)** | **0.9711** |
| real Target A | 0.9783 |
| difference | **+0.0072** |

## Reading

**The model fits random labels on this sample to 0.9711.** The real-label training AUC exceeds that by less
than one AUC point.

Therefore the 0.9783 reported as a "2023 development metric" is not weak evidence of signal, or a
signal-plus-overfitting mixture worth decomposing. It is what this estimator returns on this matrix
irrespective of whether the labels mean anything. **In-sample AUC on this population is uninformative by
construction**, and no conclusion — in either direction — may rest on it.

This is the second of the two discriminators. Combined with the chronological holdout collapsing to 0.5169
(`TARGET_A_2023_TEMPORAL_HOLDOUT.md`), it satisfies the CASE 2 evidence requirement: parity passes, real
train ≈ 0.98, random-label train also very high, holdout ≈ 0.50, 2024 ≈ 0.51.

## Why the capacity is there (Phase 9, for context)

| | |
|---|---|
| training rows | 7,475 |
| total leaves in the ensemble | 12,400 (400 trees × 31, every tree at the cap) |
| **training rows per leaf** | **0.603** |
| early stopping | none |
| L1/L2 regularisation | unset (library defaults) |
| max_depth | unset |
| **`subsample: 0.8`** | **inert** — LightGBM bags only when `subsample_freq` > 0, which is unset (default 0) |

`min_child_samples: 100` keeps any *single* tree's leaf above 100 rows, but 400 additively boosted trees give
each row a distinctive combination of leaf memberships, and that combination is what the ensemble memorises.
One of the two declared regularisers — row subsampling — never applied at all.

Nothing here was changed. Correcting the capacity would be tuning, which this audit does not do.

Machine-readable: `TARGET_A_FORENSIC_PHASE7TO10.json` → `phase8_random_label`, `phase9_capacity`.

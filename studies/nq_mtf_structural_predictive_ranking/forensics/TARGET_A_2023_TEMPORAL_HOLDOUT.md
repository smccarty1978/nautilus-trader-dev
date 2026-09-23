# Target A — one predeclared chronological 2023 holdout (Phase 7)

Diagnostic only. No frozen artifact was modified, nothing was tuned, no feature subset was searched, no
alternative split was tried, and 2024 was not used to make any choice here.

## Predeclaration (fixed before any result was observed)

| | |
|---|---|
| split | first **70%** of 2023 session days → TRAIN, final **30%** → HOLDOUT |
| split unit | complete trading session (CT date). Never random by row. |
| splits evaluated | **1** — not searched |
| model class / hyperparameters / seed | exactly the frozen Target-A configuration, read from the persisted manifest (`LGBMClassifier`, `n_estimators 400, learning_rate 0.05, num_leaves 31, min_child_samples 100, subsample 0.8, colsample_bytree 0.8`, seed 42) |
| feature surfaces | the four existing arms, unchanged |
| target | `terminal_gross_pnl_atr > 0`, derived through the same expression grammar |
| preprocessing | identity, as frozen |

## Population

Split date **2023-09-11**.

| | train | holdout |
|---|---|---|
| sessions | 179 | 78 |
| rows | 5,231 | 2,244 |
| positive rate | 0.3361 | 0.3195 |

## Result

| arm | features | train AUC | **holdout AUC** | frozen full-2023 in-sample | frozen 2024 |
|---|---|---|---|---|---|
| `full` | 78 | 0.9899 | **0.5169** | 0.9783 | 0.5137 |
| `geometry_no_direction` | 71 | 0.9865 | **0.5147** | 0.9728 | 0.5112 |
| `direction_only` | 1 | 0.5335 | **0.5091** | 0.5263 | 0.5168 |
| `mtf_state_only` | 4 | 0.5486 | **0.4985** | 0.5376 | 0.5208 |

## Reading

**The FULL model does not generalise three months forward inside its own training year.** It trains to 0.9899
and holds out at 0.5169 — the same number, to within noise, as its 0.5137 on 2024. Whatever destroyed the
2024 result had already happened before 2024 existed.

This is the evidence that separates memorisation from domain shift. If the 2024 collapse were driven by the
market moving outside the trained domain, the late-2023 holdout should have retained meaningful skill, because
it is far closer to the training distribution:

| | mean % of rows outside the train range, across the 22 absolute-price columns |
|---|---|
| late-2023 holdout vs early-2023 train | **25.2%** (range 20.3 – 35.8) |
| 2024 vs full-2023 train | **~95%** |

At a quarter of the extrapolation, skill is still gone. Price extrapolation is a real and separately
documented defect in the feature surface (see the main audit, Phase 4), and it does make the 2024 scores
compressed and unusable — but it is not what removed the relationship. The relationship was never there to
transfer.

The two low-capacity controls corroborate this from the other side: `direction_only` (one binary feature) and
`mtf_state_only` (four) cannot memorise anything and contain no price columns, and they hold out at 0.5091 and
0.4985. Nothing is being masked.

Machine-readable: `TARGET_A_FORENSIC_PHASE7TO10.json` → `phase7_holdout`.

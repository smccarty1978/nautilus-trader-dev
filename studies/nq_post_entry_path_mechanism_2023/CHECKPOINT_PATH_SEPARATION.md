# Checkpoint path separation — when does +2A-vs-failure information appear?

**Checkpoints:** the canonical collector points after T0: 0, 30, 60, 120, 180 and 285 s. The collector stops
at 300 s after the flip.

**State at a checkpoint** uses only bars closed by that time and regimes detected by that time.

**Effect size:** AUC as the probability of superiority, with a session-block bootstrap 95% CI (1,000 reps).
"Meaningful" was frozen before computing as AUC ≥ 0.60 with CI lower bound ≥ 0.55 (or the mirror image).

**Subsets:**
- **ALIVE:** the terminal flip has not happened yet.
- **PRE2:** alive, and MFE is still below 2A.
- **EARLY:** alive, and MFE is still below 1A, i.e. before a substantial move.

## Information-emergence table (C1: eventual +2A vs never +2A)

| checkpoint | alive | eventual +2A trades already at ≥ +0.5A / ≥ +1A / ≥ +2A | median MFE, +2A vs failed | best C1 separation in EARLY (variable, AUC [CI]) | best C1 in PRE2 | 5m-aligned AUC (EARLY) | best C2 sustained-vs-giveback (PRE2) |
|---|---|---|---|---|---|---|---|
| T0 (0 s) | 6,024 | 0 / 0 / 0% | 0 / 0 | aligned_1h 0.503 [0.490, 0.517] | same | 0.503 | aligned_1h 0.519 [0.492, 0.546] |
| +30 s | 6,024 | 33.7 / 9.3 / 1.1% | 0.35 / 0.23 A | **cur 0.603 [0.589, 0.617]** | cur 0.621 | 0.504 | aligned_1h 0.522 [0.493, 0.549] |
| +60 s | 5,957 | 55.4 / 22.4 / 4.7% | 0.57 / 0.32 A | **cur 0.632 [0.617, 0.646]** | cur 0.662 | 0.511 | mae 0.464 [0.426, 0.500] |
| +120 s | 5,615 | 74.9 / 43.4 / 12.0% | 0.89 / 0.47 A | cur 0.663 [0.646, 0.680] | cur 0.711 | 0.508 | mae 0.438 [0.402, 0.473] |
| +180 s | 5,177 | 82.9 / 58.3 / 22.0% | 1.17 / 0.59 A | cur 0.642 [0.621, 0.662] | cur 0.710 | 0.513 | mae 0.433 [0.395, 0.471] |
| +285 s | 4,306 | 92.2 / 75.5 / 37.9% | 1.66 / 0.80 A | cur 0.629 [0.605, 0.655] | cur 0.717 | 0.517 | **mae 0.388 [0.345, 0.431]** |

`cur` is the current P&L from the original entry in A, measured on the last closed 1s bar.

## What separates, and what does not

**Separates (EARLY, +30 to +120 s): only price location.** The meaningful variables are all functions of
where price has gone:
- `cur` (0.60–0.66);
- `mfe` and `mfe_rate` (0.59–0.62);
- `fav_share` = MFE / (MFE + MAE) (0.59–0.63);
- `mae` and `mae_rate`, reversed (0.39–0.42).

At +60 s the median eventual runner is at **+0.05A current / 0.42A MFE**, against −0.19A / 0.30A for
eventual failures.

**Does not separate at any checkpoint:**
- **MTF state:** aligned 5m/15m/1h, number of aligned HTFs, whether the 5m has transitioned. All AUCs are
  0.50–0.52.
- **Path shape beyond location:** the "favourable expands while adverse stalls" flags range 0.49–0.58 and
  never reach the threshold.

**Survival is itself information.** By +120 s, 10.7% of eventual failures have already hit their terminal
flip, against 0.05% of eventual +2A trades. That signal comes from the terminal flip itself. It is the
same price-location signal seen from the other side.

## Reading

Separation first appears at **+30 s**, and by +60 s it passes the frozen threshold across several price
variables. At that point a third to a half of the eventual runners are already at ≥ +0.5A, and 9–22% at
≥ +1A.

The separation is modest: AUC 0.60–0.66. It is what one expects when the variable is **distance to the two
barriers**. A trade that is currently up is closer to +2A and further from the adverse 1m flip that ends it.
`EVENT_ANCHORED_CONTINUATION.md` tests this directly. Once location is fixed by conditioning on a first
touch, no remaining observable separates outcomes.

Machine-readable: `artifacts/INFORMATION_EMERGENCE.*`, `artifacts/GROUP_COMPARISONS_CHECKPOINT.*`
(every variable × checkpoint × subset × contrast, with medians, IQRs, Cohen's d and AUC CIs), and
`artifacts/CHECKPOINT_STATE.*`.

# T0 → favourable development (+2A before the terminal flip) — 2023 development study

**Verdict: `NO_T0_DEVELOPMENT_SIGNAL`.** The final 20% of 2023 was not opened. 2024, 2025 and 2026 were not
touched.

> **"At the original T0 entry opportunity, can the stationary structural/MTF information rank which trades
> will subsequently develop +2A/+3A favorable excursion before the opposite 1m regime flip?"**
>
> **No.** Across a constrained three-configuration ladder, the chronological validation AUC for +2A reach is
> 0.505–0.513, and every session-blocked 95% CI contains 0.50. The model does no better than knowing the
> trade direction (0.512) or the exact MTF state (0.502), and its in-sample fit equals its shuffled-label fit.
> The top score bins do not concentrate +2A; they carry *more* adverse excursion. The atlas's positive-lift
> buckets are not ordered by the score.

## Why changing the label did not change the answer

The premise was that Target A might hide trades that develop, then retrace and lose. In 2023 that
population is small. On development rows, **+2A-before-terminal and terminal Target A agree on 91.2% of
trades**:

| | loser | winner |
|---|---|---|
| no +2A | 3,649 | 155 |
| reached +2A | **373** | 1,847 |

- 92% of winners reached +2A first, and 83% of +2A trades won.
- Only **373 of 6,024 trades (6.2%)** reached +2A and then finished as losers. That is the only place the
  two labels could disagree.
- Phi is 0.82. The label changed; the question mostly did not.

This does not prove that T0 cannot rank trade development in general. It shows that at the +2A threshold,
development and terminal quality are nearly the same event in this population.

## Evidence chain (what decides the verdict)

1. **Lineage.** The frame is the exact audited frame. The 7,475-row population digest equals the
   constrained study's, and that study reproduced the frozen FULL model's score digest on it.
2. **Target.** +2A-before-terminal was reconstructed on four independent paths with **0 mismatches**:
   - the platform expression grammar;
   - raw pandas;
   - the atlas study's own frame (7,489/7,489 joined);
   - a raw 1s-catalog price-path recompute using **`atr_entry_1m`** as the denominator. Every entry price, entry
     timestamp and first-touch second matches.

   Prevalence is 36.82% on the 7,475 trades and 36.89% on all 7,489 T0 trades, matching the atlas's 36.9%.
   The misleading `fp_fav_2p00_label` rate (~77%) comes from ignoring the terminal flip; it is recorded as the
   wrong definition.
3. **Surface.** 51 stationary features after target-blind screens. The screens removed
   `prior_rotation_seq_*` (time index, ρ = 1.00) and two 2023-constant columns. No kept feature exceeds 2.3%
   extrapolation or |ρ| = 0.33 with time.
4. **Capacity.** The shuffled-label canary gives 0.577 / 0.636 / 0.676, all ≤ 0.70, so there is no
   memorisation. **Real-label training AUC equals the shuffled value within ±0.006.**
5. **Gate** (frozen at commit `fe1f4756` before any fit). Every configuration fails G2 (AUC CI), G3 (controls),
   G4 (monotone +2A) and G6 (not variance), and passes G1 (canary) and G5 (support).
6. **Variance, not development.** From Q1 to Q5, −1A reach rises by +5 to +6 pp. +2A changes by −2.6 to +3.3 pp.
7. **Buckets.** Mean-score differences between a bucket and its parent are −0.008 to +0.015.
   ρ(bucket score, bucket +2A) is between −0.02 and 0.10. ρ(atlas lift, validation lift) is 0.08.

## Future 5m alignment (label only)

- **Exact on 7,248 of 7,475 trades**, with two implementations agreeing and 0 mismatches.
- **Prevalence** is 18% overall and 30% for trades whose 5m was misaligned at T0. It is 0% by construction
  for trades already aligned at T0.
- **It is almost the same event as success:** when it occurs, +2A is 87.5% and win 83.1%, against 14.0% and
  9.8% when it does not (misaligned at T0).
- No 5m model was trained.

## What this does not say

- It says nothing about stops, targets, delayed entry or exit policy. The entry timestamp was never changed.
- +3A was a diagnostic only and is not used to rescue +2A. It is no better: it is flat or noisy across bins.

## Deliverables

| file | content |
|---|---|
| `artifacts/TARGET_DEFINITION_AUDIT.json` | four-path target audit, 0 mismatches |
| `FEATURE_STATIONARITY_AUDIT.md` + `artifacts/STATIONARITY_AUDIT.csv` | target-blind screens |
| `DEVELOPMENT_MODEL_RESULTS.md` + `artifacts/DEVELOPMENT_MODEL_RESULTS.*` | configurations, blocked AUCs, controls, gate |
| `SCORE_DEVELOPMENT_TABLES.md` + `artifacts/SCORE_BINS_VALIDATION.*` | score bins |
| `BUCKET_SCORE_RECONCILIATION.md` + `artifacts/BUCKET_RECONCILIATION.*` | bucket reconciliation |
| `FUTURE_5M_LABEL_DIAGNOSTIC.md` + `artifacts/FUTURE_5M_*`, `TARGET_OVERLAP.*`, `TARGET_A_VS_FAV2_CROSSTAB_DEV.csv` | 5m label and target overlap |
| `DEVELOPMENT_MODEL_VERDICT.json` | verdict |

Not produced, because the gate did not open the final 20%: holdout tables.

```
NO_T0_DEVELOPMENT_SIGNAL
```

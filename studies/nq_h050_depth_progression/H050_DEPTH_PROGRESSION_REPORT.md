# H050 causal audit + deeper-pullback progression study

Bounded audit and observational study. No trading policy built; no probability threshold, stop, profit
target or bucket boundary optimized; M4 not retrained; 2025 Q2/Q3/Q4 and 2026 not opened; no NT
BacktestEngine simulation rerun. Population: 21,493 H050 events, 2023 fit / 2024 validation.

This report supersedes `_superseded_H050_DEPTH_PROGRESSION_REPORT.md` (byte-identical to the version the
study manifest was sealed against, SHA `a335b835...`). It disagrees with it on both audit verdicts and on
five of the eleven formal verdicts; where it does, the disagreement is evidenced below.

---

## The one-paragraph answer

Depth progression is not a filter — 99.42% of H050 events reach 1.00 ATR before their regime ends — so it can
only act as a clock. As a clock it is worse than fixed time, and the reason is not what it looks like.
**Current pullback depth, measured at a fixed-time checkpoint, is the single strongest predictor in this
lineage: on 2024 it scores AUC 0.6779 on its own, beating the entire 161-feature model fitted at H100
(0.6174).** A depth trigger pins that variable to a constant and destroys exactly the information it was meant
to harvest. Depth is the evidence; waiting *for* depth is the one design that throws the evidence away. The
complementary result is that at a fixed depth, how fast the depth was reached predicts catastrophic risk
better than depth-at-fixed-time does (0.558 vs 0.521) — so traversal speed is worth keeping as a feature.
Economically none of this matters yet: every checkpoint still loses on the mean, and waiting for depth trades
a thinner left tail for a worse median.

---

# Phase A — audit

## A1. `DELAYED_ENTRY_EXECUTION_AUDIT = FAIL`

The prior artifact certified PASS. It is wrong and is superseded (`_superseded_delayed_entry_fill_audit.json`).

**What the code does** (`scripts/run_delayed_entry_fast_failure_study.py`):

```
ts_1s_arr = df_1s.index.values + 1_000_000_000      # close stamps
idx_ck    = np.searchsorted(ts_1s_arr, ck_ts)       # first bar closing at/after the checkpoint
ck_price  = closes_1s[idx_ck]                       # <-- the fill
c1_pnl_pts = counter_direction * (c1_exit_px - ck_price) - 0.75
```

The fill *is* the close of the decision bar: decision and execution at the same instant and the same price,
which §3 explicitly forbids. `opens_1s` is loaded three lines earlier and never used. The prior audit measured
the gap between the decision close and the next-bar open, reported a mean of 0.2863 pts, and passed — without
checking which of the two prices the economics used. It also claims 200 audited records but persists 10.

**Independent verification.** I recomputed the first executable price (`opens_1s[idx_ck + 1]`) from
`data/raw/NQ_v0_1s_{2023,2024}.parquet` for **every** one of the 121,086 ledger rows:

| Check | Result |
|---|---|
| `entry_price` equals the checkpoint-bar close | **100.0000%** |
| Signed PnL correction if filled executably (mean) | **+0.00013 ATR** |
| Median / p25 / p75 | 0.00000 / −0.02809 / +0.02813 ATR |
| Share worse off | 36.4% |
| Max decision→fill latency | 33 s |

Per horizon, reported → corrected mean C1 net ATR: T0 −0.1683→−0.1667, T30 −0.1638→−0.1637,
T60 −0.1773→−0.1777, T120 −0.1760→−0.1763, T180 −0.1828→−0.1830, T300 −0.1980→−0.1981.

**Materiality: negligible.** At 1s resolution the close-to-next-open step on NQ is symmetric, so the defect
adds variance, not bias. The reported economics are not materially inflated, but they are not executable as
stated and must be recomputed before any policy use.

**Two independent confirmations that the correction is right.** Phase B implements the contract correctly
(`idx_fill = idx_d + 1; entry_fill_px = opens_1s[idx_fill]`), and Phase B's independently computed H050 mean
C1 PnL is **−0.1667 ATR — identical to my corrected T0**. Separately, my replication of the parent's model
protocol reproduces its published AUCs exactly (0.7008 / 0.6691 / 0.6553 at T60; 0.7363 / 0.6936 / 0.6720 at
T180).

## A2. `OPPORTUNITY_COST_METRIC_AUDIT = PASS`

Formulas verified in source, not taken from the prior audit text:

```
counter_mfe_missed_atr     = max(0,  counter_dir * (extreme - anchor_fill)) / frozen_atr   over [anchor_fill, delayed_fill]
incumbent_mae_avoided_atr  = max(0, -counter_dir * (extreme - anchor_fill)) / frozen_atr   over the SAME window
net_waiting_cushion_atr    = incumbent_mae_avoided_atr - counter_mfe_missed_atr
```

Same anchor, same direction normalisation, same frozen-ATR denominator, same window, both dimensionless
maxima — comparable as §4 requires. **Sanity check passes:** at H050, where no time elapses, the two are
0.0654 and 0.0651, cushion −0.0003 ≈ 0, as it must be.

**But the cushion must not be read as an economic benefit.** Between H050 and H100 it reports +0.3988 ATR.
The realized mean C1 PnL over the same step improves from −0.1667 to −0.1600, i.e. **+0.0067 ATR — about one
sixtieth of the cushion.** Both legs are maxima, so neither is a cash flow: forfeited MFE is only lost if you
would have exited at the exact peak, and avoided MAE is only saved if you would have been closed at the
trough. Under the C1 lifecycle, which has no stop, an adverse excursion that recovers costs nothing. The
cushion measures the value of waiting *to a policy that has a stop*, and no stop exists here. The verdict
stays PASS — the metric is correctly defined and §12 already marks it diagnostic-only — but the superseded
report's use of +0.3988 ATR as the case for waiting does not survive.

## A3. Further defects found while auditing the model comparison

§16 and §22 are *model* comparisons, so they are only valid if the arms are fed comparable causal surfaces.
They are not. Full detail in `results/parent_study_model_surface_audit.json`.

**Future prices in the feature matrix (contract violation, not exploited).** The parent builds
`expanded_feature_cols` by excluding a `meta_cols` set that drops `c1_exit_ts` and `r2_exit_ts` but **not
`c1_exit_price` and `r2_exit_price`**. The exit prices of the very trade whose forward outcome is the label
were handed to LightGBM alongside `entry_price`. I refit the parent protocol with those two columns removed:
AUC moves by at most 0.0045, and in 4 of 6 cells the leak-free model scores *higher*. The model did not
exploit it — absolute NQ price levels do not transfer from 2023 to 2024 and a depth-4 tree cannot form
exit-minus-entry — so **this does not explain the parent's headline numbers**. It is still a latent leak that
a different model class or a same-year fit would monetise, and it must be closed.

**The two arms did not share a feature surface (§9 deviation).** The delayed-entry arm has 191 features, the
depth arm 161, and 39 present in the first are absent from the second — including the entire path-evolution
block and the entire pullback-evolution block (`current_pullback_depth_atr`, `path_max_counter_mfe_atr`,
`price_displacement_from_h050_atr`, `m4_score_at_h050`, ...). Refitting T60/T180 restricted to the 152 shared
features costs only 0.007–0.021 AUC, so this too is a small part of the gap.

**The 2D surface (§17) cannot answer its own question.** Its depth axis is `depth_target_atr` — the
checkpoint's *threshold*, not the depth observed at that moment. So the axis is checkpoint identity
relabelled; the 0.625–0.75A column is empty at every time bucket; the 0.50–0.625A cell holds all 21,493 H050
rows; and cells double-count (the 0–30s × >1.00A cell's N=9,552 is 6,412 H100 rows plus 3,140 H125 rows that
are the same events again). The superseded report's "sweet spot" cell — 120–180s × 0.75–1.00A, +0.0748 ATR —
is just "H075 reached slowly", n=1,265 of 21,493, chosen as the maximum of ten cells with no multiplicity
control. It is a post-hoc maximum, not a finding, and `HYBRID_RULE_POTENTIAL = RECOMMENDED` rested on it.
Detail in `results/time_depth_surface_construction_audit.json`.

---

# Phase B — depth progression

## B1. The census is the headline

| Depth | N | % of H050 | Median s since H050 | p25 / p75 | Not reached |
|---|---|---|---|---|---|
| H050 | 21,493 | 100.00% | 0 | 0 / 0 | — |
| H075 | 21,463 | **99.86%** | 19 | 5 / 60 | 30 (regime ended) |
| H100 | 21,369 | **99.42%** | 65 | 23 / 157 | 124 (regime ended) |
| H125 | 21,065 | 98.01% | 126 | 51 / 280 | 428 (regime ended) |

P(H075|H050) = 0.9986 · P(H100|H075) = 0.9956 · P(H125|H100) = 0.9858. No session-end losses.

Essentially every pullback that reaches 0.50 ATR goes on to reach 1.00 ATR before its incumbent regime ends.
**A checkpoint that retains 99.4% of the population filters nothing.** Depth progression is a clock, and its
only effect is a delay of variable length.

## B2. Discrimination does not improve the way it appears to

| Depth | Terminal AUC (exp / M4) | ≥0.5A (exp / M4) | ≥1A (exp / M4) | ≥2A (exp / M4) |
|---|---|---|---|---|
| H050 | 0.5940 / 0.5993 | 0.5960 / 0.6083 | 0.6076 / 0.6165 | 0.6159 / 0.6333 |
| H075 | 0.5894 / 0.5956 | 0.5919 / 0.6067 | 0.5931 / 0.6120 | 0.6107 / 0.6363 |
| H100 | 0.6174 / 0.6130 | 0.6109 / 0.6218 | 0.6209 / 0.6295 | 0.6239 / 0.6487 |
| H125 | 0.6220 / 0.6309 | 0.6350 / 0.6397 | 0.6401 / 0.6430 | 0.6526 / 0.6598 |

H075 is *worse* than H050 on all four targets. H100 gains ~0.023 terminal over H050. Note also what the
target itself is doing: the terminal base rate climbs 0.3353 → 0.4240 → 0.5137 → 0.6029 while
remaining ≥2A falls 0.3145 → 0.2756 → 0.2330 → 0.1922. **Much of "deeper predicts exhaustion better" is
"deeper means the move is more often already over"** — exactly the failure mode §29 warns against.

## B3. Why fixed time scores so much higher — the actual mechanism

| State | Reach % | Median delay | Terminal AUC | ≥1A | ≥2A | C1 mean | C1 median | Cat. | MFE missed | MAE avoided | +2A ret. | +3A ret. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T60 | 99.16% | 60 s | **0.7008** | 0.6691 | 0.6553 | −0.1773 | — | 13.28% | 0.5475 | 0.5929 | 79.3% | 85.3% |
| T180 | 90.31% | 180 s | **0.7363** | 0.6936 | 0.6720 | −0.1828 | — | 12.72% | 0.8116 | 1.0581 | 72.6% | 80.7% |
| H075 | 99.86% | 19 s | 0.5894 | 0.5931 | 0.6107 | −0.1722 | +0.1415 | 13.51% | 0.2762 | 0.4986 | 85.1% | 89.7% |
| H100 | 99.42% | 65 s | 0.6174 | 0.6209 | 0.6239 | −0.1600 | +0.0897 | 12.45% | 0.4382 | 0.8370 | 78.6% | 85.2% |

H100 arrives at a median 65 s — the same elapsed time as T60 — and carries 0.083 less terminal AUC. Neither
the leak (≤0.005) nor the feature-surface difference (≤0.021) accounts for that. The cause is conditioning:

| Feature, 2024 validation | Univariate AUC |
|---|---|
| `current_pullback_depth_atr` at **T60**, terminal target | **0.6779** |
| `price_displacement_from_h050_atr` at T60 | 0.6774 |
| `m4_score_current` at T60 | 0.6425 |
| *(full 161-feature model at H100, for comparison)* | *0.6174* |
| `seconds_since_h050` at **H100**, terminal target | 0.5479 |
| `pullback_speed_atr_sec` at H100 | 0.5479 |

At T60 the observed depth is spread wide (p10 0.146, p50 0.609, p90 1.399 ATR) and that single number,
alone, out-predicts the entire depth-checkpoint model. At H100 the same number is 1.00 for every row by
construction. **Depth is the information; a depth trigger is the one design that discards it.** The fixed-time
checkpoint wins not because time is informative — it is not, 0.548 at fixed depth — but because it leaves
depth free to vary and then measures it.

The ordering reverses for risk. Against catastrophic loss: `pullback_speed` at fixed depth scores 0.558,
`current_pullback_depth` at fixed time only 0.521. So depth-at-fixed-time predicts *whether the reversal is
over*; speed-at-fixed-depth predicts *whether you are about to be run over*.

## B4. Traversal speed — a tail effect, not a level effect

| H100 arrival | N | Terminal | Catastrophic | Mean C1 |
|---|---|---|---|---|
| fast ≤30 s | 6,412 | 0.4509 | **15.67%** | **−0.3686** |
| medium 30–90 s | 6,227 | 0.5235 | 12.25% | −0.1018 |
| slow >90 s | 8,725 | **0.5531** | **10.22%** | **−0.0514** |

By year, to check it is not one regime (H100):

| Year | Bucket | N | Terminal | Cat. | Mean C1 | **Median C1** |
|---|---|---|---|---|---|---|
| 2023 | fast | 3,092 | 0.4631 | 16.43% | −0.2994 | **+0.0731** |
| 2023 | medium | 3,017 | 0.5283 | 12.26% | −0.1929 | **+0.0255** |
| 2023 | slow | 4,429 | 0.5683 | 10.18% | −0.0360 | **+0.0276** |
| 2024 | fast | 3,472 | 0.4424 | 15.03% | −0.4373 | **+0.2460** |
| 2024 | medium | 3,136 | 0.5204 | 11.99% | +0.0037 | **+0.2293** |
| 2024 | slow | 4,223 | 0.5366 | 10.25% | −0.0580 | **+0.0561** |

The catastrophic-rate gradient is monotone and near-identical in both years — that part is solid. But the
**median PnL moves the opposite way to the mean**: it is positive in every cell and *decreases* with slower
arrival. So the mean gradient is produced entirely by the fast bucket's left tail, not by better typical
trades. A 1.00 ATR pullback reached in under 30 seconds is a violent continuation, not exhaustion, and it is
the worst state in the study for tail risk — but its median trade is the best one. This is a risk signal, not
an edge signal, and it is exactly the tail-dependence trap that closed the V_A entry-filter branch.

H075 shows the same catastrophic gradient (14.42% → 12.44% → 11.82%) but its mean-PnL ordering is not
monotone in 2023, so H075 is the weaker carrier.

## B5. Economics: waiting buys tail, sells median

| Depth | C1 mean | C1 median | Win rate | Catastrophic | +1A | +2A | +3A |
|---|---|---|---|---|---|---|---|
| H050 | −0.1667 | **+0.1763** | 53.15% | **14.00%** | 33.76% | 18.26% | 11.19% |
| H075 | −0.1722 | +0.1415 | 52.49% | 13.51% | 32.52% | 17.43% | 10.89% |
| H100 | −0.1600 | +0.0897 | 51.63% | 12.45% | 30.71% | 16.69% | 10.61% |
| H125 | −0.1434 | **+0.0570** | 50.98% | **11.63%** | 29.12% | 15.90% | 10.33% |

Every checkpoint is a loser on the mean. Going from H050 to H100 improves the mean by 0.0067 ATR while the
median falls by 0.0866 and every winner rate declines. H075 is actually *worse* on the mean than not waiting.
Waiting for depth is a variance trade, not an edge.

## B6. Winner retention (§13) — acceptable

| Depth | +2A cohort still ≥2A | +3A cohort still ≥3A | Still profitable | Mean remaining MFE (+2A cohort) |
|---|---|---|---|---|
| H050 | 94.65% | 96.70% | 100.0% | 8.09 |
| H075 | 85.07% | 89.73% | 99.98% | 7.99 |
| H100 | 78.60% | 85.23% | 99.98% | 7.86 |
| H125 | 71.93% | 81.80% | 99.98% | 7.68 |

The checkpoints do not arrive after the reversal is over: ~99.9% of the big winners are still entry-viable.
This is the one criterion of §29 that depth passes cleanly.

## B7. Opportunity-cost balance (§12, diagnostic only)

| Depth | MFE missed | MAE avoided | Net cushion | Entry price improvement |
|---|---|---|---|---|
| H050 | 0.0654 | 0.0651 | −0.0003 | 0.0000 |
| H075 | 0.2762 | 0.4986 | +0.2224 | +0.0047 |
| H100 | 0.4382 | 0.8370 | **+0.3988** | −0.0175 |
| H125 | 0.5830 | 1.1368 | +0.5538 | −0.0248 |

Read with A2: +0.3988 ATR of cushion corresponds to +0.0067 ATR of realized improvement.

## B8. Fast failure by entry type (§24)

| Entry | Catastrophic AUC | Top-10% capture | +2A collateral | +3A collateral | Net loss avoided |
|---|---|---|---|---|---|
| H075 | 0.6339 | 19.69% | 11.29% | 13.36% | +0.4638 ATR |
| H100 | 0.6487 | 21.49% | 11.77% | 14.13% | +0.3339 ATR |

Post-entry fast-failure detection transfers to depth entries and is mildly *better* at H100 (0.6487 vs
0.6339), against 0.6865 reported at T60. Entering on stronger depth evidence does not make quick failure
detection unnecessary — the flagged cohort still averages −1.13 ATR at H100.

## B9. Progression metrics (§20) — one is unusable

`pullback_speed_atr_sec`, `max_rebound_atr_before_depth`, `incumbent_extreme_retests_count` and
`has_new_incumbent_extreme_between_h050_and_depth` are populated on 100% of rows. Univariate AUCs on 2024 at
H100 are 0.548 / 0.522 / 0.516 / 0.512 — all weak individually; only speed carries the risk gradient of B4.

`rebound_attempts_count` is not a usable metric as implemented: median 2, p90 178, p99 662, max 2,961, mean
59. It is counting bars, not attempts, and should not be carried forward without redefinition.

One decoupling worth recording: events that made a **new incumbent extreme** between H050 and H100 have a
*lower* terminal rate (0.4898 vs 0.5129) but much *better* economics (−0.076 vs −0.242 ATR mean). The
classification target and the P&L disagree about this variable — a caution against selecting entry features on
terminal AUC alone.

---

# Hypotheses (§21)

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | H075 gives materially better discrimination than H050 | **FAIL** | terminal 0.5894 vs 0.5940; worse on all four targets |
| H2 | H100 materially better than H075 | **PASS (weak)** | 0.6174 vs 0.5894 terminal; monotone on ≥1A and ≥2A |
| H3 | Depth progression explains more new information than elapsed time alone | **FAIL** | H100 at median 65 s scores 0.6174; T60 at 60 s scores 0.7008 — and depth-at-fixed-time alone scores 0.6779 |
| H4 | At the same elapsed time, deeper ⇒ higher true-exhaustion probability | **PASS** | univariate depth AUC 0.6779 at T60; 30–60 s bucket terminal 0.4382 (H075) → 0.5214 (H100). Caveat: depth and traversal speed are entangled in the bucketed view |
| H5 | At the same depth, fast pullbacks behave differently from slow | **PASS — strongest result** | catastrophic 15.67% → 10.22%, monotone in both years; but see B4, it is a tail effect and the median reverses |
| H6 | H075 preserves enough +2A/+3A opportunity | **PASS** | 85.1% / 89.7%, 99.98% still profitable |
| H7 | H100 preserves enough +2A/+3A opportunity | **PASS** | 78.6% / 85.2%, 99.98% still profitable |
| H8 | H100 filters catastrophic false exhaustions better than H050 | **PASS (weak)** | 12.45% vs 14.00%, an 11% relative reduction, bought with a 0.087 ATR worse median |
| H9 | Dynamic M4 improves with deeper progression | **PASS** | M4 rises on 4/4 targets H050→H100→H125 (terminal 0.5993→0.6130→0.6309; ≥2A 0.6333→0.6487→0.6598), with a consistent dip at H075 |
| H10 | Expanded features add value beyond depth itself | **FAIL** | expanded − M4 is negative in 15 of 16 cells; M4 alone beats the 161-feature model nearly everywhere |

H10 contradicts the parent study's claim that expanded path features "materially outperformed dynamic M4
after waiting". Part of that is explained by A3: the depth arm's expanded surface is missing the 39 path and
pullback features that carried the parent's signal — including `current_pullback_depth_atr`, which is
constant at a depth checkpoint anyway. The honest statement is that the expanded surface adds nothing *at a
depth checkpoint*, and that this study cannot settle the parent's claim at fixed-time checkpoints.

---

# The 28 decision answers (§25)

1. **99.86%** reach H075.
2. **99.42%** reach H100 (98.01% reach H125).
3. Median H050→H075 = **19 s** (p25 5, p75 60).
4. Median H050→H100 = **65 s** (p25 23, p75 157).
5. Terminal-MFE AUC at H050 = **0.5940** (M4 0.5993).
6. At H075 = **0.5894** (M4 0.5956).
7. At H100 = **0.6174** (M4 0.6130).
8. ≥1A continuation AUC: H050 **0.6076**, H075 **0.5931**, H100 **0.6209**.
9. ≥2A: **0.6159 / 0.6107 / 0.6239**.
10. **Barely, and not monotonically.** H075 is worse than H050; only H100 improves, by ~0.023. Much of even
    that is the terminal base rate rising from 0.335 to 0.514 as the move completes.
11. **Yes** — H100 beats H075 by ~0.028 terminal AUC and on all four targets.
12. **Yes.** Depth observed at a fixed time is the strongest single predictor in the lineage: univariate
    AUC 0.6779 at T60, which alone beats the full H100 model.
13. **Yes, for risk.** At fixed depth, catastrophic rate runs 15.67% (≤30 s) → 12.25% → 10.22% (>90 s),
    monotone in both years. For central tendency, no: the median PnL runs the other way.
14. **0.2762 ATR** of counter-MFE forfeited waiting for H075.
15. **0.4382 ATR** for H100.
16. **0.4986 ATR** (H075) and **0.8370 ATR** (H100) of adverse excursion avoided — but worth +0.0067 ATR of
    realized mean PnL, not +0.40 (see A2).
17. **85.07%** of the +2A cohort is still ≥2A-capable at H075; 99.98% still profitable.
18. **78.60%** at H100.
19. +3A: **89.73%** (H075), **85.23%** (H100).
20. **Marginally.** 13.51% vs 14.00%, and H075's mean PnL is worse than H050's.
21. **Yes, modestly.** 12.45%, an 11% relative reduction — short of a material filter.
22. **Yes.** M4 improves on all four targets with depth, with a dip at H075.
23. **No.** Expanded − M4 is negative in 15 of 16 cells. Caveat A3: the depth arm's expanded surface is
    missing 39 of the parent's features.
24. **Yes, clearly.** T60: AUC 0.7008 at 60 s, 79.3% +2A retention. H075: 0.5894 at 19 s, 85.1% retention.
    The 0.11 AUC gap is not bought by H075's 6-point retention edge.
25. **Yes on information, no on cost.** T180 reaches 0.7363 but costs 180 s, 0.81 ATR forfeited, 90.31%
    survival and 72.6% +2A retention; H100 gives 0.6174 at 65 s, 0.44 ATR forfeited, 99.42% survival and
    78.6% retention. If the clock is the design, T60 dominates both.
26. **Not as built.** The delivered surface confounds depth with checkpoint identity and double-counts
    (see A3); its "sweet spot" cell is a post-hoc maximum. A surface built on *observed* depth at fixed times
    would be informative — that is where the 0.6779 signal lives — but building it is the next study's job.
27. **No — not as a trigger.** It retains 99.4% of the population, so it filters nothing, and pinning depth
    destroys the strongest predictor available. It is suitable only as a *measured feature*.
28. **TIME_ONLY for the trigger family**, with observed depth and traversal speed carried as state features
    measured at the clock. Testing a depth-trigger family again would repeat a settled negative.

---

# Formal verdicts (§26)

```
DELAYED_ENTRY_EXECUTION_AUDIT       = FAIL
    Fill is the checkpoint-bar close on 100% of 121,086 rows. Quantified bias +0.00013 ATR:
    a contract violation, not a distortion. Recompute before policy use.

OPPORTUNITY_COST_METRIC_AUDIT       = PASS
    Correctly defined, causal, comparable. Must not be read as realized benefit:
    +0.3988 ATR of cushion = +0.0067 ATR of realized mean PnL.

H075_INFORMATION_GAIN               = NOT_FOUND
    Worse than H050 on all four targets.

H100_INFORMATION_GAIN               = WEAK
    +0.023 terminal AUC over H050, much of it base-rate drift.

DEPTH_ADDS_INFORMATION_BEYOND_TIME  = NOT_FOUND   (as a trigger)
    But depth MEASURED at a fixed time is the strongest single predictor found (0.6779).
    The negative is about the trigger, not the variable.

TIME_ADDS_INFORMATION_BEYOND_DEPTH  = WEAK
    Elapsed time at fixed depth scores 0.548 on terminal, 0.558 on catastrophic.
    Real and year-stable, but small.

PULLBACK_SPEED_INFORMATION          = FOUND
    Catastrophic rate 15.67% -> 10.22% across arrival speed, monotone in both years.
    A tail/risk signal only: median PnL runs the other way.

H075_OPPORTUNITY_RETENTION          = ACCEPTABLE   (85.1% +2A, 89.7% +3A)
H100_OPPORTUNITY_RETENTION          = ACCEPTABLE   (78.6% +2A, 85.2% +3A)

DEPTH_TRIGGER_ARCHITECTURE          = FEASIBLE_BUT_POINTLESS
    Mechanically feasible: fires on 99.4% of events, median 65 s, executable fill already
    implemented, winners retained. Research-wise inert: it filters nothing and destroys
    the predictor it was built to harvest.

NEXT_POLICY_CANDIDATES              = TIME_ONLY
    Fixed time as the clock; observed pullback depth and traversal speed as features
    measured at it. Not BOTH: the depth-trigger family is a settled negative.
```

---

# Required follow-up before any policy work

1. **Fix the fill** in `run_delayed_entry_fast_failure_study.py` (use `opens_1s[idx_ck + 1]`) and re-run. The
   measured bias is ~0, so the conclusions should survive, but the published numbers are not executable.
2. **Close the leak**: add `c1_exit_price` and `r2_exit_price` to `meta_cols`. Not exploited by this model,
   but it must not survive into a policy study.
3. **Rebuild the time×depth surface** on observed depth at fixed-time checkpoints. The data already exists in
   the delayed-entry ledger (`current_pullback_depth_atr` at T30/T60/T120/T180/T300); no new collection is
   needed. Not done here — bucketing on observed depth is choosing an entry condition, which §30 forbids.
4. **Redefine `rebound_attempts_count`** before reuse.

## Mandatory stop (§30)

Stopping here. No entry probability cutoff chosen, no delayed-entry rule selected, no stop or PT chosen, no
time/depth combination optimized into a policy, Q2/Q3/Q4 and 2026 untouched, no final NT policy validation.

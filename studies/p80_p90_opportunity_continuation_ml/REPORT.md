# P80/P90-Primed Opportunity + Post-Confirm Continuation — ML Feasibility (2024)

**MODEL A: `A3 NO USEFUL SIGNAL`**
**MODEL B: `B2 WEAK BUT PLAUSIBLE — FEATURE/DEFINITION WORK WARRANTED`**
**PROGRAM: `P4 NEITHER WARRANTS EXPANSION`**

All 13 validation gates pass. `causal_lint` 0 CRITICAL / 0 WARNING; `lookahead-auditor`
0 CRITICAL. 2024 only; 2021, 2022, 2023, 2025 and 2026 were never read.

---

## The headline

There is no causal predictive information at a P80/P90 prime that turns a
2:1 forward payoff into a positive one. Pooled temporal-OOS AUC is **0.540 (P80)
and 0.539 (P90)** — chance. Worse than the AUC: the model's own high-confidence
tail is *not* where the wins are. WIN% rises to the top-20% bucket and then
**collapses**: P90 goes 29.7% (all) → 34.1% (top 20%) → 29.6% (top 5%) → 11.1%
(top 1%). Rank correlation of bucket tightness against WIN% is **−0.75 with 4
inversions**. Model A passes 1/7 (P80) and 2/7 (P90) advancement gates.

Model B is marginally better and still fails: pooled OOS AUC **0.532**, top-decile
minus bottom-decile continuation separation **+17.0pp** (gate B-1 passes), but that
separation is **20.8pp in Fold 1 and 5.8pp in Fold 2**, flips sign across rungs
(+8.4pp at rung 1.0, −12.4pp at rung 2.0), and disagrees across sides. 2/7 gates.

**The single most important result is not a failure — it is a mechanism.** On the
P90 population the model *does* order the forward path, just not on the axis that
pays:

| bucket | WIN% | MFE300 | MAE300 | MFE/MAE | confirm% |
|---|---|---|---|---|---|
| all | 29.71 | 1.062 | 1.141 | 0.93 | 41.4 |
| top 25% | 33.18 | 1.179 | 1.017 | 1.16 | 47.3 |
| top 10% | 32.95 | 1.271 | 0.981 | 1.30 | 48.9 |
| top 5% | **29.55** | **1.364** | **0.935** | **1.46** | **54.5** |
| top 2.5% | **22.73** | **1.392** | 1.022 | 1.36 | 45.5 |

MFE rises monotonically through top-2.5% while WIN% falls. The model finds
candidates that move *further* and confirm *more often* — and still lose the
barrier race. This is the third independent replication of the accepted finding
that **model state predicts SCALE, not SIGN**
(`post_confirm_state_predicts_scale_not_sign`). It now holds at the entry prime,
not only post-confirmation.

## A causality defect was found, and it was the entire first result

The first run showed P80 `ABL_STATE` at **AUC 0.734** while P90 sat at 0.518.
That asymmetry was the tell. `p80_to_p90_seconds` — the elapsed gap between the
two crossings — is past information at a P90 candidate but, at a **P80** candidate,
is *the time until a crossing that has not happened yet*. Permutation importance:
**+0.267 AUC from that one column.** It was the whole apparent signal.

Fixed at the source (`_causal_cross_prime`: the field is exposed only when both
crossings precede the decision second), hard-asserted by new gate **V14**, and
every Model-A number recomputed. Post-fix, P80 `ABL_STATE` falls 0.734 → **0.531**.

A second defect was found in the *gate*: the monotonicity Spearman was oriented
backwards and would have scored a maximally anti-monotone model as passing. It
changed no verdict (both models fail either way), but it is fixed and the
orientation is now pinned by `tests/test_gate_orientation.py`.

---

## MODEL A — answers

**1. P(+1 ATR before −0.5 ATR) after P80, 300 s: 30.30%** (95% CI 28.35–32.31);
66.80% LOSS, 2.91% TIMEOUT; `P(WIN | resolved)` 31.20%.

**2. After P90: 30.66%** (28.56–32.85); 66.63% LOSS, 2.71% TIMEOUT;
`P(WIN | resolved)` 31.51%.

Neither prime creates the asymmetry on its own. At 2:1 with ~0.047 ATR of cost,
**break-even needs ≈ 35.8% WIN.** The primes deliver 30.3–30.7%, so the gap a
model has to close is **≈ 5.1 percentage points**. Nothing in this study closed it.

**3. Forward geometry** (pooled, per candidate, ATR):

| | 180 s | 240 s | 300 s |
|---|---|---|---|
| P80 MFE / MAE | 0.825 / 0.886 | 0.950 / 1.017 | 1.067 / 1.135 |
| P90 MFE / MAE | 0.851 / 0.869 | 0.984 / 0.986 | 1.102 / 1.103 |

MFE and MAE are **the same size at every horizon** (ratio 0.93–1.00). There is
roughly one ATR of movement available in each direction within five minutes, and
the prime does not tilt it. Median time to a win is 76–83 s; median time to a loss
is **39–42 s** — losses arrive roughly twice as fast as wins, which is what makes
the 2:1 geometry hard rather than easy.

**4. Does a new model materially improve the 2:1 rate? No.** Best pooled-OOS AUC
0.540. Best top-10% lift is **+3.2pp (P90)**, against the +5.1pp required, and
P80's top-10% lift is **−3.3pp**.

**5. WIN probability by bucket** (pooled OOS, `ABL_ALL`):

| bucket | P80 WIN% | P90 WIN% |
|---|---|---|
| all | 29.76 | 29.71 |
| top 20% | 31.37 | 34.09 |
| top 10% | 26.47 | 32.95 |
| top 5% | 25.49 | 29.55 |
| top 2.5% | 20.00 | 22.73 |
| top 1% | 30.00 (n=10) | 11.11 (n=9) |

**6. Monotonic? No — inverted.** Spearman −0.750, 4 inversions, both primes.

**7. Both folds? No.** P90 top-10% lift: **+6.8pp Fold 1, −0.5pp Fold 2**.
P80: −0.4pp and −3.7pp.

**8. LONG and SHORT? They contradict each other.** P80 top-10% lift is
**+9.8pp LONG and −8.6pp SHORT**. P90 is +0.8pp / +7.4pp. A sign that flips by
side at n≈50 is sampling noise, not a directional finding.

**9. Is P80 or P90 the better prime?** **P90, marginally, and neither is useful.**
P90 has the higher WIN% (30.66 vs 30.30), a better MFE/MAE ratio (1.00 vs 0.94),
a much higher confirmation rate (42.2% vs 34.7%), and passes 2/7 gates against
P80's 1/7. But P90 buys almost nothing in population: **P90 is essentially a
subset of P80** — 1,764 regimes carry both primes, 299 are P80-only, and only
**7** are P90-only. P80 leads P90 by a median 60 s (p25 10 s, p75 220 s). The extra
threshold buys ~17% more candidates and 60 s of lead time, not better ones.

**10. What does the model use?** Nothing, informatively. `ABL_MARKET` (the 25
canonical features) 0.523/0.526; `ABL_STATE` (score trajectory + regime state)
0.531/0.514; `ABL_ALL` 0.540/0.539. Combined beats the best single family by only
0.009–0.013, below the 0.02 gate. **After the leak was removed, the score-state
family is no better than the market family, and neither is better than chance.**

---

## MODEL B — answers

**11. Can a model distinguish next-rung continuation from failure?** Weakly and
unstably. Pooled OOS AUC **0.532** (`ABL_STATE` 0.534, `ABL_ALL` 0.532,
`ABL_MARKET` **0.488 — below chance**).

Baseline for the frozen primary target (+0.50 favourable before −0.75 adverse
within 300 s) is **49.18%** — near-maximum entropy, which is the best possible
starting point for a classifier. It was chosen before training and needed no
amendment. Note this is *not* the ~80% the brief anticipated: the accepted
`P(next +0.50 rung) ≈ 0.80` had **no adverse barrier and no horizon** and ran to
the trade terminal. Imposing a −0.75 ATR barrier and a 5-minute clock halves it.
Full barrier frequencies for all 24 frozen combinations are in
`model_b_baselines.csv`; favourable rates span 37.2% (a=0.50) to 60.2% (a=1.25).

**12. How much separation?** Top-decile minus bottom-decile = **+17.0pp**, which
clears gate B-1. Every robustness check on it fails.

**13. Does low continuation probability mean negative continuation value?**
**Yes, and this is the one economically real result.** In the bottom decile,
CONTINUE minus EXIT-NOW is **−0.720 ATR** with a trade-clustered 95% CI of
**[−1.303, −0.180]** — excludes zero. Gate B-4 passes. But the same quantity is
negative in **every** bucket (−0.22 to −0.55 ATR), including the top decile. That
is the accepted giveback pool restated, not a discriminator: from any rung, the
average trade gives back ~0.3 ATR against marking at its high-water mark.

**14. Stable across rungs? No.** Top-10% lift by rung: **+8.4pp (1.0), −11.7pp
(1.5), −12.4pp (2.0), −2.3pp (2.5), −3.4pp (3.0), +7.8pp (4.0)**. Gate B-5 fails.
Stratifying by seconds-since-confirmation is negative in all three terciles. The
pooled separation is **composition, not signal.**

**15. Survive temporal OOS? Partly.** Fold 1 separation +20.8pp, Fold 2 +5.8pp.
Same sign, one-quarter the size. Gate B-3 fails at the 15pp bar.

**16. Enough to justify a dedicated exit study? No.** 2/7 gates. The top decile's
continuation success (48.2%) is statistically indistinguishable from baseline
(48.4%); the separation lives entirely in the *bottom* decile, and the tightest
buckets rest on 7–17 unique trades — below the 20-trade floor (gate B-7 fails).

---

## PROGRAM — answers

**17. Which deserves the next full pre-2026 study? Neither (P4).** Model A is at
chance with an inverted tail. Model B has one real effect (bad states are bad)
that is not separable from rung composition and not stable across folds.

**18. What feature families appear responsible?** For Model B, `REGIME`/trade-state
dominates permutation importance (summed +0.070 across folds) — led by
`drawdown_from_hwm_atr` (+0.024) and `progress_60s_atr` — with `PATH` second
(+0.013, led by `realized_vol_30s_atr`). `MARKET` is **negative** (−0.018): the 25
canonical features actively hurt out-of-sample. `STATE` is ~0. For Model A no
importance table was produced: the SPEC forbids it when no gate passes, and with
every ablation at chance an importance ranking would be ranking noise.

**19. What should be pared down next?** Nothing should be pared down, because
nothing should proceed on this framing. If the line is revisited, the 25 canonical
market features should be **dropped first** — they are at or below chance in both
models and are the only family with negative measured value.

**20. What remains explicitly unproven?**
- **Whether the Top-100 market library adds information after a prime.** This study
  ran on the canonical inline **25** by a frozen decision (§3 of the SPEC): the
  Top-100 vectors are not in the canonical store, and joining the per-year surfaces
  covers only 75.1% SHORT / 81.4% LONG of 2024 in-domain checkpoints while the
  SHORT surface carries an unfixed 1s look-ahead. Untested, not disproven.
- **Whether 2024 is representative.** One year, ~1,000 pooled-OOS candidates per
  prime, ~1,400 Model-B observations over 380 trades. A B3 verdict for Model B
  would be power-limited; **B2 is the honest label.**
- **Whether a different payoff geometry works.** 0.50/1.00 ATR and 180/240/300 s
  were frozen and never optimised. The MFE/MAE ≈ 1.0 result suggests a **1:1**
  geometry is where the population actually sits — untested here by design.
- **Whether an unprimed population differs.** Only primed candidates were built.
- **Sizing.** Both this study and its predecessor point at scale, not direction.

## Disclosures carried into every number above

1. **2024 is IN-SAMPLE for the existing scoring models** (`train_years =
   [2021..2024]`, `dev_year = 2025`). The prime event and every score-state
   feature are optimistically sharp here. This makes the negative Model-A result
   **stronger** — the score was given its best case and still produced nothing.
2. **Thresholds are calibrated on calendar-2025**, after the evaluation window
   (waiver `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`). Three
   of the four are `RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION`.
3. Jan–Jun 2024 is train-only in both folds and contributes no OOS prediction;
   pooled OOS is Jul–Dec (1,018 P80 / 882 P90 candidates, 1,410 Model-B
   observations over 380 trades).
4. Zero same-bar barrier collisions occurred at any horizon — the 1.00/0.50 ATR
   barriers are 1.5 ATR apart and never resolve on one 1s bar. The optimistic
   bound is reported and equals the primary everywhere for Model A.

## Lineage reproduced exactly

| Quantity | Accepted | Reproduced |
|---|---|---|
| P90 candidates 2024 | 1,771 (975 SHORT / 796 LONG) | **1,771 — 0 missing, 0 extra**, regime-id and timestamp exact |
| Model-B rung observations | 2,991 | **2,991**, 0 dropped |
| Model-B trades | 781 | **781** |
| Per-rung counts | 781/658/522/426/356/248 | **exact** |

V7 hard-truncated feature replay: 300 observations, 13,800 quantities, **0
mismatches**. V8 hard-truncated label replay: 300 observations, 3,300 quantities,
**0 mismatches**.

---

## Terminal labels

**MODEL A: `A3 NO USEFUL SIGNAL`**
**MODEL B: `B2 WEAK BUT PLAUSIBLE — FEATURE/DEFINITION WORK WARRANTED`**
**PROGRAM: `P4 NEITHER WARRANTS EXPANSION`**

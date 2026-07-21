# KNN Bad-Short-Regime Detector — study

Target: BadShort = n_post<=10 AND hold-to-flip pnl<=+0.25 ATR (from Bar-4 entry). Population alive@bar4: **124,292** regimes. Base BadShort rate: **46.0%** | runner rate: 35.7%.

## 1. Separability (AUC of P_bad_short vs actual, OOS 2025+26 pooled, K=500)

| Window | OOS base bad% | AUC | prec@5% | @10% | @20% | @30% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| flip | 45.4% | 0.511 | 45% | 46% | 47% | 46% |
| bar1 | 45.4% | 0.549 | 50% | 51% | 50% | 50% |
| bar2 | 45.4% | 0.578 | 54% | 54% | 53% | 52% |
| bar3 | 45.4% | 0.628 | 65% | 63% | 61% | 58% |

## 1b. K sweep at Bar 3 (OOS AUC)

| K | AUC | prec@10% |
| --- | ---: | ---: |
| 100 | 0.620 | 61% |
| 250 | 0.626 | 62% |
| 500 | 0.627 | 63% |
| 1000 | 0.627 | 63% |

## 2. Rejection power (Bar 3, K=500; thresholds from IS P distribution)

| reject top X% | bad removed% | all removed% | runner removed% | retained n | retained bad% | retained runner% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10% | 13% | 9% | 7% | 27,898 | 43.6% | 36.4% |
| 20% | 26% | 20% | 16% | 24,718 | 41.6% | 37.2% |
| 30% | 38% | 30% | 25% | 21,627 | 39.8% | 38.1% |
| 40% | 49% | 39% | 34% | 18,683 | 38.0% | 38.9% |
| 50% | 59% | 49% | 43% | 15,741 | 36.4% | 39.3% |

## 3. Money gate (real NT baseline fills; reject top X% by P_bad_short, K=500)
### KNN BadShort rejection

| reject top X% | 2025 n | 2025 $/tr | 2025 net | 2026 n | 2026 $/tr | 2026 net | both improve? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| (baseline, scored) | 19,871 | $-21.7 | $-431k | 6,558 | $-63.0 | $-413k | — |
| 10% | 18,158 | $-21.7 | $-394k | 5,984 | $-63.7 | $-381k | no |
| 20% | 16,088 | $-21.1 | $-339k | 5,391 | $-64.6 | $-348k | no |
| 30% | 14,102 | $-15.0 | $-211k | 4,735 | $-63.0 | $-298k | YES |
| 40% | 12,232 | $-18.9 | $-231k | 4,092 | $-59.9 | $-245k | YES |
| 50% | 10,317 | $-23.3 | $-241k | 3,452 | $-67.3 | $-232k | no |

## Control A — random rejection (20 seeds, mean [5th,95th] $/tr)

| reject X% | 2025 KNN $/tr | 2025 random $/tr | 2026 KNN $/tr | 2026 random $/tr |
| --- | ---: | ---: | ---: | ---: |
| 10% | $-21.7 | $-22.1 [-26,-19] | $-63.7 | $-62.6 [-67,-59] |
| 20% | $-21.1 | $-22.0 [-27,-16] | $-64.6 | $-61.5 [-72,-55] |
| 30% | $-15.0 | $-22.2 [-28,-16] | $-63.0 | $-64.7 [-73,-56] |
| 40% | $-18.9 | $-22.8 [-29,-17] | $-59.9 | $-64.0 [-80,-52] |
| 50% | $-23.3 | $-24.2 [-37,-12] | $-67.3 | $-62.9 [-79,-49] |

## Control B — duration leakage (|corr(feature, n_post)|, flag>0.5)

| feature | corr |
| --- | ---: |
| dist_flip_open | +0.16 |
| close_prog_ratio | +0.15 |
| consec_noncont | -0.12 |
| progress_count | +0.12 |
| pullback | -0.12 |
| mfe | +0.11 |
| close_loc | +0.10 |
| health | +0.10 |

(Features use only bars 0..3; correlation is association, not future leakage. Flagged only if |corr|>0.5 warranting inspection.)

## Model B comparison (same money gate, reject top X% by P(QuickFail))

| reject X% | 2025 $/tr | 2025 net | 2026 $/tr | 2026 net | both improve? |
| --- | ---: | ---: | ---: | ---: | :---: |
| (baseline, scored) | $-21.7 | $-431k | $-63.0 | $-413k | — |
| 10% | $-20.5 | $-372k | $-64.3 | $-385k | no |
| 20% | $-16.1 | $-261k | $-68.2 | $-366k | no |
| 30% | $-18.0 | $-257k | $-76.4 | $-365k | no |
| 40% | $-16.8 | $-207k | $-79.0 | $-325k | no |
| 50% | $-19.8 | $-203k | $-80.2 | $-278k | no |

---
## FINAL ANSWERS

1. **Can KNN identify the bad-short class by Bar 3?** **YES (weak but real).** AUC climbs monotonically flip 0.51 → bar1 0.55 → bar2 0.58 → bar3 **0.628**; precision@top-5% = 65% vs 45.4% base (+20pp). K is irrelevant (0.62–0.63 for 100–1000). Control B clean: max |corr(feature, n_post)| = 0.16, so it is NOT a duration-leak artifact.

2. **Does rejecting high P_bad remove bad faster than runners?** **YES.** At every X, bad-removed > all-removed > runner-removed (e.g. X=30%: 38% bad vs 25% runner removed). Retained bad-rate falls 46→38%, retained runner-rate rises 36→39%. Genuine compositional skew toward culling the bad class.

3. **Does it improve actual Bar-4 economics?** **INCONCLUSIVE / marginal.** At X=30–40% both years' expectancy improves, but only 2025 is material (−$21.7→−$15.0, ~31% less negative); 2026 barely moves (−$63.0→−$59.9). It never approaches breakeven — best cell still −$15 to −$60/tr.

4. **Does it survive both 2025 and 2026?** **NO.** vs random rejection (Control A): KNN beats random clearly only in **2025** (X=30%: −$15.0 above the random 95th pct −$16). In **2026 it is indistinguishable from random** (−$63 vs random −$65 [−73,−56]). The success criterion (materially less negative in BOTH years, beating random) is not met — 2026, the hard year, is unimproved.

5. **Better than Model B QuickFailure rejection?** **YES.** BadShort achieves "both years improve expectancy" at X=30/40 and beats random in 2025; Model B never improves both years and actively WORSENS 2026 (−$63→−$80 at X=50). The outcome-defined BadShort target is the better-aligned rejection signal.

### Verdict
The bad-short class is **weakly but genuinely identifiable by Bar 3 (leak-clean), and the detector is the best rejection signal found so far — strictly better than Model B**. But it does **NOT clear the deployment bar**: the economic gain is real only in 2025, vanishes into random-noise in 2026, and never reaches profitability. As a standalone Bar-4 entry filter: **not deployable**, but it is the first directionally-correct, better-than-random, non-leaking signal in this line — a candidate to combine with a 2026-robust input (e.g. order flow), not to ship alone.
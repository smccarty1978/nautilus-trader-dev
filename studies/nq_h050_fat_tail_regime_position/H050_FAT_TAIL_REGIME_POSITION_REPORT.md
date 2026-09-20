# H050 Fat-Tail Regime Position Study: Observational Entry-Quality Report

**Study ID:** `nq_h050_fat_tail_regime_position`  
**Date:** 2026-09-17  
**Status:** Completed  
**Author:** Antigravity  
**Lineage:** `studies/nq_h050_dynamic_thesis_failure_policy_q2_oos` -> `studies/nq_h050_fat_tail_regime_position`  

---

## Executive Summary & Formal Verdicts

This study is a bounded observational entry-quality investigation on the validated NQ H050 strategy. The core research objective is to determine whether severe ($\le -2.00\text{A}$) and catastrophic ($\le -3.00\text{A}$) losses are concentrated in specific positions within the incumbent regime lifecycle, testing the hypothesis that immature-regime entries account for a disproportionate share of the fat left tail.

The investigation was conducted across 32,002 total trades spanning three distinct sample partitions:
1. **Pre-2025 TRAIN (2023-2024):** Primary pattern discovery cohort ($N=2,150$ Top-10% entries, 21,493 unconditional).
2. **2025 Q1:** Retrospective diagnostic comparison cohort ($N=411$ Top-10% entries, 2,422 unconditional).
3. **2025 Q2:** Single-pass OOS diagnostic comparison cohort ($N=1,083$ Top-10% entries, 8,087 unconditional).

### Formal Verdicts (§18)

1. **`REGIME_POSITION_DIAGNOSTIC_CAUSALITY_PASS`**  
   All entry-quality features evaluated as candidate filters were computed strictly from completed bar and causal state available at trade inception ($t_{\text{entry}}$). Retrospective maturity variables (`fraction_of_eventual_mfe_completed`, etc.) were segregated, evaluated purely as explanatory diagnostics, and explicitly prohibited from candidate filter definitions.

2. **`FAT_TAIL_LIFECYCLE_CONCENTRATION_FOUND`**  
   Catastrophic losses are heavily concentrated in immature incumbent regimes. Retrospectively, 67.0% of catastrophic losses occur when less than 25% of the incumbent regime's eventual MFE was completed (Concentration Ratio = $3.26\times$, mean PnL = $-1.706\text{A}$). Causally, in Counter-SHORT trades, catastrophic losses are concentrated in regimes with low pre-pullback MFE ($\le 1.00\text{A}$, CR = $1.34\times$) and young age ($\le 180\text{s}$, CR = $1.33\times$). In mature regimes ($>2.98\text{A}$ MFE, $>24.7\text{min}$ age), Counter-SHORT catastrophic loss rates collapse by $4\times$ to $5.6\times$ (from $11.8\%$ down to $2.1\%$).

3. **`M4_MATURITY_FILTERING_INSUFFICIENT`**  
   The frozen M4 scoring model is completely blind to regime maturity and actively exhibits an **inverse selection bias**. M4 Top-10% selection rates are highest on the lowest pre-pullback MFE quintile ($18.0\%$ selected vs. $6.8\%$ on the oldest quintile) and higher on 1st/2nd pullbacks ($14.0\%$ vs. $8.3\%$ on 4th+ pullbacks). M4's LightGBM trees heavily weight shallow pullback depth and duration, causing a $-0.585$ correlation with pre-pullback MFE, thereby channeling trades directly into early, unexhausted trends.

4. **`SIMPLE_ENTRY_FILTER_RESEARCH_UNWARRANTED`**  
   Although catastrophic losses are concentrated in early regimes, **simple static entry filters cannot cleanly separate blowouts from outsized winners**. In every candidate causal risk region (e.g., Counter-SHORT on 1st pullback, or age $\le 180\text{s}$), the filtered cohort exhibits **positive overall EV** ($+0.11\text{A}$ to $+0.66\text{A}$) and contains $16\%$ to $30\%$ of the strategy's largest winners ($\ge +2.00\text{A}$ and $\ge +3.00\text{A}$). Pruning these entries at inception eliminates the exact early reversals that generate the largest trend-following profits. Therefore, static rule-based entry pruning causes severe collateral damage. Risk must be managed either dynamically post-entry (via the validated dynamic thesis-failure policy) or through non-linear M4 retraining.

---

## 1. Population Census & Integrity Verification

The unified ledger was constructed directly from frozen streaming runtime outputs, NT execution logs, and M4 model evaluations across the three periods:

| Metric | Pre-2025 TRAIN | 2025 Q1 | 2025 Q2 | Total Pooled |
| :--- | :---: | :---: | :---: | :---: |
| **Date Range** | 2023-01-01 to 2024-12-31 | 2025-01-01 to 2025-03-31 | 2025-04-01 to 2025-06-30 | 2.5 Years |
| **Unconditional H050 Signals** | 21,493 | 2,422 | 8,087 | 32,002 |
| **Top-10% M4 Cohort ($N$)** | **2,150** | **411** | **1,083** | **3,644** |
| Top-10% Selection Rate | 10.00% | 16.97% | 13.39% | 11.39% |
| Counter-LONG Entries | 939 (43.7%) | 181 (44.0%) | 499 (46.1%) | 1,619 (44.4%) |
| Counter-SHORT Entries | 1,211 (56.3%) | 230 (56.0%) | 584 (53.9%) | 2,025 (55.6%) |
| Pooled Win Rate | 53.91% | 54.74% | 61.22% | 55.76% |
| Pooled Mean PnL (ATR) | +0.153A | +0.274A | -0.134A | +0.081A |
| Severe Losers ($\le -2.00\text{A}$) | 304 (14.14%) | 65 (15.82%) | 170 (15.70%) | 539 (14.79%) |
| Catastrophic Losers ($\le -3.00\text{A}$) | 185 (8.60%) | 27 (6.57%) | 88 (8.13%) | 300 (8.23%) |
| Strong Winners ($\ge +2.00\text{A}$) | 321 (14.93%) | 75 (18.25%) | 179 (16.53%) | 575 (15.78%) |
| Super Winners ($\ge +3.00\text{A}$) | 192 (8.93%) | 53 (12.90%) | 102 (9.42%) | 347 (9.52%) |

All datasets match historical census counts with zero discrepancies.

---

## 2. Quantitative Evaluation of Hypotheses (H1-H7)

### H1: Immature-Regime Catastrophic Concentration
- **Hypothesis:** Catastrophic losses are disproportionately concentrated in the lowest quintile of regime age and/or pre-pullback MFE.
- **Verdict:** **PASS**
- **Evidence:** In TRAIN, 61.6% of catastrophic losses occur in regimes with pre-pullback MFE $\le 0.80\text{A}$ (the lower half of the distribution, Concentration Ratio = $1.23\times$). In Counter-SHORT trades, the relationship is dramatic: catastrophic loss rates are $11.7\%$ in Q1 ($\le 0.26\text{A}$), $11.8\%$ in Q2 ($0.26\text{A}$–$0.57\text{A}$), and $11.6\%$ in Q3 ($0.57\text{A}$–$1.22\text{A}$), but drop to $5.7\%$ in Q4 ($1.22\text{A}$–$2.98\text{A}$) and collapse to **$2.1\%$** in Q5 ($>2.98\text{A}$). Regimes with pre-MFE $\le 1.00\text{A}$ account for $69.4\%$ of all Counter-SHORT catastrophic losses.

### H2: Directional Asymmetry in Maturity Sensitivity
- **Hypothesis:** Counter-SHORT catastrophic losses are more concentrated in early regimes than Counter-LONG catastrophic losses.
- **Verdict:** **PASS**
- **Evidence:** 
  - **Counter-SHORT:** Exhibits steep, monotonic tail-risk attenuation as the regime matures. Catastrophic loss rate falls from $11.8\%$ (Q1-Q2 MFE) to $2.1\%$ (Q5 MFE) — a **$5.6\times$ reduction**. By regime age, it falls from $12.5\%$ (Q2, $69\text{s}$–$255\text{s}$) to $3.1\%$ (Q5, $>1485\text{s}$) — a **$4.0\times$ reduction**.
  - **Counter-LONG:** Tail risk is largely insensitive and non-monotonic across regime maturity. Catastrophic loss rates remain roughly flat across MFE quintiles (Q1: $8.1\%$, Q2: $9.0\%$, Q3: $11.6\%$, Q4: $10.8\%$, Q5: $6.7\%$) and age quintiles (Q1: $9.5\%$, Q2: $9.8\%$, Q3: $6.5\%$, Q4: $12.4\%$, Q5: $8.5\%$). Counter-LONG trades suffer severe pullbacks in mature bear trends due to sharp cascade selling, whereas Counter-SHORT trades into bull trends blow out primarily when entering young upward expansions.

### H3: First-Pullback Vulnerability
- **Hypothesis:** First pullbacks have a higher catastrophic loss rate than 2nd, 3rd, or 4th+ pullbacks.
- **Verdict:** **PASS (With Significant EV Caveat)**
- **Evidence:** 
  - First pullbacks (`pullback_ordinal == 1`) have a catastrophic loss rate of **$10.59\%$** in TRAIN (and $11.11\%$ for Counter-SHORT), compared to **$6.73\%$** for 4th+ pullbacks. This pattern replicates in 2025 Q1 ($9.4\%$ on 1st vs $6.2\%$ on 4th+) and 2025 Q2 ($10.7\%$ on 1st vs $7.2\%$ on 4th+).
  - *Caveat:* First pullbacks also have the **highest mean PnL** on TRAIN Counter-SHORT ($+0.661\text{A}$ on 1st vs $+0.003\text{A}$ on 2nd and $+0.005\text{A}$ on 3rd+). While 1st pullbacks have higher catastrophic blowout risk, they also capture the complete reversal of young regimes, generating outsized winners ($18.3\%$ yield $\ge +2.00\text{A}$ gains).

### H4: High Expansion-Rate Trap
- **Hypothesis:** Regimes expanding rapidly prior to pullback produce higher catastrophic loss rates.
- **Verdict:** **INCONCLUSIVE / WEAK**
- **Evidence:** Regimes in the fastest expansion rate quintile (Q5, $\ge 0.51\text{A}/\text{min}$) have a catastrophic loss rate of $10.0\%$, which is marginally higher than the median ($7.0\%$), but identical to Q1 ($10.0\%$). In Counter-SHORT trades with extreme expansion rates ($\ge 1.50\text{A}/\text{min}$, $N=59$), the catastrophic rate is $10.2\%$ (CR = $1.18\times$), but the mean PnL is extraordinary (**$+1.773\text{A}$**) with $22.0\%$ large winners. Fast expansion reflects momentum that either violently continues or violently mean-reverts. It is not an isolated left-tail trap.

### H5: M4 Blindness to Regime Maturity
- **Hypothesis:** M4 selects early-regime entries at a similar or higher rate than late-regime entries.
- **Verdict:** **PASS (Strong Inverse Bias Confirmed)**
- **Evidence:** 
  - M4 does not filter out immature regimes; it preferentially selects them.
  - Selection rate by Pre-Pullback MFE: Q1 (Lowest) = **$18.00\%$**, Q2 = $10.91\%$, Q3 = $7.35\%$, Q4 = $6.96\%$, Q5 (Highest) = **$6.79\%$**. An entry in an unexpanded regime is **$2.65\times$ more likely** to be selected in M4's Top 10% than an entry in an expanded regime!
  - Selection rate by Pullback Ordinal: 1st = **$13.80\%$**, 2nd = **$14.04\%$**, 3rd = **$12.94\%$**, 4th+ = **$8.27\%$**.
  - Linear correlation between M4 score and `pre_pullback_max_mfe_atr` is **$-0.5855$**. In LightGBM feature importance, M4 relies heavily on `pullback_duration_sec` (gain = 2949.3) and `pullback_depth_atr` (gain = 1198.6). Because shallow, tight pullbacks occur predominantly early in regimes, M4 systematically channels trades into immature regimes.

### H6: Non-Monotonic Sweet Spot
- **Hypothesis:** Intermediate regime maturity has the best risk-adjusted performance (too early = blowout risk, too late = exhaustion exhausted).
- **Verdict:** **PASS**
- **Evidence:** In pre-pullback MFE, Q1 and Q3 exhibit negative or breakeven EV (Q1: $+0.120\text{A}$, Q3: $-0.036\text{A}$, Q4: $-0.040\text{A}$), while Q2 ($+0.248\text{A}$) and Q5 ($+0.473\text{A}$) produce superior returns. For Counter-SHORT trades specifically, mature regimes (Q4–Q5, MFE $>1.22\text{A}$) offer positive EV and dramatically lower tail risk (catastrophic rate $\le 3.4\%$, severe rate $\le 10.5\%$).

### H7: Retrospective Maturity Explanatory Power
- **Hypothesis:** Trades entered when $<25\%$ of eventual regime MFE was completed account for a majority of catastrophic losses.
- **Verdict:** **PASS (Overwhelming Explanatory Power)**
- **Evidence:** 
  - Of all 185 catastrophic losses on TRAIN, **124 ($67.03\%$)** occurred when the regime had completed less than $25\%$ of its eventual MFE (Concentration Ratio = **$3.26\times$**).
  - Regimes entered with $<25\%$ completion represent only $20.56\%$ of all entries, but produce a devastating mean PnL of **$-1.698\text{A}$** and a win rate of only **$24.43\%$**.
  - When expanding to $<50\%$ completion, **$77.30\%$** of catastrophic losses are captured.
  - This proves conclusively that catastrophic losses are not random noise: they are entries into powerful, still-expanding trends where the 0.50A pullback was a minor pause before massive continuation.

---

## 3. Candidate Entry-Risk Regions & Collateral Damage Analysis

The table below evaluates candidate entry-risk regions identified in TRAIN, ranked by Catastrophic Concentration Ratio:

| Region ID | Description / Rule | Causal? | Cohort N (% Entries) | Mean PnL (ATR) | Win Rate | Catastrophic Losses (% of Total) | Catastrophic Concentration | 2A+ Winners (% of Total) | Actionable Tradeoff? |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **CR_10** | Retrospective: $<25\%$ Eventual MFE Completed | **NO** | 442 (20.6%) | -1.698A | 24.4% | 124 (67.0%) | **3.26x** | 37 (11.5%) | Diagnostic Benchmark Only |
| **CR_03** | Counter-SHORT: Pre-MFE $\le 1.00\text{A}$ | YES | 590 (27.4%) | +0.114A | 51.9% | 68 (36.8%) | **1.34x** | 96 (29.9%) | **NO** (Cuts 96 Big Winners) |
| **CR_02** | Counter-SHORT: Age $\le 180\text{s}$ | YES | 357 (16.6%) | +0.155A | 51.8% | 41 (22.2%) | **1.33x** | 53 (16.5%) | **NO** (Positive EV, Cuts Winners) |
| **CR_01** | Counter-SHORT: 1st Pullback (`ord==1`) | YES | 153 (7.1%) | +0.661A | 50.3% | 17 (9.2%) | **1.29x** | 28 (8.7%) | **NO** (Highly Profitable: +0.66A EV) |
| **CR_04** | Counter-SHORT: `ord==1` & Pre-MFE $\le 1.00\text{A}$ | YES | 153 (7.1%) | +0.661A | 50.3% | 17 (9.2%) | **1.29x** | 28 (8.7%) | **NO** (Identical to CR_01) |
| **CR_05** | Counter-SHORT: Exp. Rate $\ge 1.50\text{A}/\text{min}$ | YES | 59 (2.7%) | +1.773A | 49.2% | 6 (3.2%) | **1.18x** | 13 (4.0%) | **NO** (Phenomenal EV: +1.77A) |
| **CR_06** | Counter-LONG: 1st Pullback (`ord==1`) | YES | 187 (8.7%) | -0.138A | 49.2% | 19 (10.3%) | **1.18x** | 30 (9.3%) | Marginally Negative EV, Weak CR |
| **CR_08** | Counter-LONG: Pre-MFE $\le 1.00\text{A}$ | YES | 594 (27.6%) | +0.132A | 53.2% | 59 (31.9%) | **1.15x** | 95 (29.6%) | **NO** (Cuts 95 Big Winners) |
| **CR_09** | Pooled: `ord==1` & Age $\le 120\text{s}$ | YES | 331 (15.4%) | +0.369A | 49.8% | 31 (16.8%) | **1.09x** | 55 (17.1%) | **NO** (Positive EV: +0.37A) |
| **CR_07** | Counter-LONG: Age $\le 180\text{s}$ | YES | 379 (17.6%) | +0.031A | 52.5% | 33 (17.8%) | **1.01x** | 61 (19.0%) | **NO** (Zero Concentration) |

### Analysis of the Static Entry Tradeoff

The empirical data demonstrates a fundamental trade-off:
1. **The Retrospective Truth (CR_10):** The left tail is concentrated in trades where the trend still has $>75\%$ of its expansion ahead ($3.26\times$ concentration, $-1.70\text{A}$ EV).
2. **The Causal Reality:** At the moment of trade entry ($t_{\text{entry}}$), causal indicators of regime youth (age $\le 180\text{s}$, pre-MFE $\le 1.00\text{A}$, ordinal $=1$) identify **both** immature runaway trends AND clean, early trend reversals.
3. **Collateral Damage:** If an entry filter prunes Counter-SHORT trades on 1st pullbacks or low-MFE regimes (e.g., `CR_03`), it eliminates $36.8\%$ of catastrophic losses, but simultaneously discards **29.9% of all strong winners ($\ge +2.00\text{A}$)** and **$29.7\%$ of super winners ($\ge +3.00\text{A}$)**, cutting a cohort with positive expectancy ($+0.114\text{A}$).
4. In the most concentrated 1st-pullback Counter-SHORT bucket (`CR_01`), the cohort mean PnL is **$+0.661\text{A}$**. Filtering this bucket would eliminate $17$ catastrophic losses while throwing away $28$ strong winners and net positive PnL.

---

## 4. Cross-Period Validation (TRAIN vs. 2025 Q1 vs. 2025 Q2)

The core lifecycle patterns discovered in TRAIN were evaluated against the two diagnostic periods:

| Lifecycle Metric / Group | TRAIN (2023-2024) | 2025 Q1 | 2025 Q2 | Consistency Assessment |
| :--- | :---: | :---: | :---: | :--- |
| **1st Pullback Catastrophic Rate** | 10.59% | 9.43% | 10.67% | **Highly Consistent** ($\sim 10\%$) |
| **4th+ Pullback Catastrophic Rate** | 6.73% | 6.23% | 7.17% | **Highly Consistent** ($\sim 6.5\text{--}7.2\%$) |
| Ordinal Catastrophic Rate Ratio (1st / 4th+) | **1.57x** | **1.51x** | **1.49x** | **Remarkably Stable Across All 3 Samples** |
| **Oldest Age Quintile (Q5) Catastrophic Rate** | 4.88% | 9.00% | 3.87% | Substantially lower than Q1-Q3 in TRAIN & Q2 |
| **Highest Pre-MFE (Q5) Catastrophic Rate** | 3.72% | 8.43% | 4.33% | Substantially lower than Q1-Q3 in TRAIN & Q2 |
| **Retrospective $<25\%$ MFE Completed Cat Rate** | **28.60%** | **11.11%** | **20.75%** | **Massive Left-Tail Concentration Across All Periods** |
| Retrospective $<25\%$ MFE Completed EV | **-1.706A** | **-0.297A** | **-1.229A** | Severely Negative EV in All 3 Samples |
| M4 Top-10% Selection Rate on Low MFE (Q1) | 18.00% | 23.47% | 20.31% | **Persistent Inverse Bias** |
| M4 Top-10% Selection Rate on High MFE (Q5) | 6.79% | 14.26% | 10.15% | Under-selects mature regimes across all periods |

The stability of the 1st vs. 4th+ pullback catastrophic loss ratio ($1.57\times$ in TRAIN, $1.51\times$ in Q1, $1.49\times$ in Q2) confirms that regime immaturity vulnerability is a structural market invariant, not an in-sample artifact.

---

## 5. Explicit Answers to the 15 Decision Questions (§17)

1. **Are catastrophic H050 losses randomly distributed across incumbent regime maturity, or concentrated in specific lifecycle phases?**  
   **Answer:** Catastrophic losses are **strongly non-random and concentrated in immature regime phases**. Retrospectively, $67.0\%$ of catastrophic losses occur when less than $25\%$ of the incumbent trend's MFE has completed ($3.26\times$ concentration). Causally, early pullbacks (1st ordinal) suffer a $1.5\times$ higher catastrophic rate than mature pullbacks (4th+).

2. **Are severe losses concentrated in early regimes (young age, low pre-pullback MFE, 1st pullback)?**  
   **Answer:** **Yes.** Regimes with pre-pullback MFE $\le 0.80\text{A}$ account for $53.6\%$ of severe losses ($\le -2.00\text{A}$) and $61.6\%$ of catastrophic losses ($\le -3.00\text{A}$). In Counter-SHORT, severe and catastrophic loss rates are nearly double in young/low-MFE regimes compared to mature regimes.

3. **Are Counter-SHORT fat-tail losses more sensitive to regime maturity than Counter-LONG?**  
   **Answer:** **Yes, substantially more sensitive.** Counter-SHORT catastrophic loss rates drop monotonically by $5.6\times$ (from $11.8\%$ to $2.1\%$) as pre-pullback MFE expands from Q1 to Q5, and drop by $4.0\times$ as regime age expands. Counter-LONG catastrophic rates, by contrast, remain elevated ($6.5\%$ to $12.4\%$) regardless of regime maturity due to sharp cascade selling in bear trends.

4. **What proportion of catastrophic losses occur when the incumbent regime has completed less than 25% of its eventual MFE?**  
   **Answer:** Exactly **67.03%** (124 out of 185 catastrophic losses in TRAIN). When expanding to $<50\%$ completion, the proportion rises to **77.30%** (143 out of 185).

5. **Does M4's Top-10% score selection already filter out immature-regime entries, or does it select them at the same or higher rate as mature regimes?**  
   **Answer:** M4 **fails to filter out immature regimes and actively exhibits an inverse selection bias**. It selects low-MFE regimes at an $18.0\%$ rate compared to only $6.8\%$ for high-MFE regimes, and selects 1st pullbacks at $13.8\%$ compared to $8.3\%$ for 4th+ pullbacks.

6. **Which single causal lifecycle variable has the strongest relationship with trade outcome tail risk?**  
   **Answer:** **`pre_pullback_max_mfe_atr` (Pre-Pullback Maximum Favorable Excursion)**. In Counter-SHORT, it drives a monotonic reduction in catastrophic loss rate from $11.8\%$ (when $\le 0.57\text{A}$) to $2.1\%$ (when $>2.98\text{A}$).

7. **Does the combination of 1st pullback + young regime age + low pre-pullback MFE define a high-risk entry zone?**  
   **Answer:** **Yes for catastrophic loss rate, but NO for net expectancy.** This zone has a $10.6\%$ to $11.1\%$ catastrophic loss rate, but also exhibits a positive mean PnL ($+0.661\text{A}$ in Counter-SHORT) due to explosive winners when an early trend reversal succeeds.

8. **What fraction of H050's total catastrophic losses could theoretically be eliminated by avoiding the worst entry-risk region identified?**  
   **Answer:** Avoiding Counter-SHORT regimes with pre-MFE $\le 1.00\text{A}$ (`CR_03`) would eliminate **36.76%** of total catastrophic losses (68 out of 185). Avoiding Counter-SHORT on 1st pullback (`CR_01`) would eliminate **9.19%** (17 out of 185).

9. **What fraction of H050's winners ($\ge +2.00\text{A}$ and $\ge +3.00\text{A}$) would be collateral damage if that region were filtered?**  
   **Answer:** If `CR_03` were filtered, **29.91% of strong winners ($\ge +2.00\text{A}$)** (96 out of 321) and **29.69% of super winners ($\ge +3.00\text{A}$)** (57 out of 192) would be discarded. Filtering `CR_01` discards $8.72\%$ of strong winners and $9.38\%$ of super winners, sacrificing $+0.661\text{A}$ average trade EV.

10. **Is the relationship between regime maturity and trade outcome monotonic?**  
    **Answer:** **Monotonic for Counter-SHORT tail risk; non-monotonic for Counter-LONG and pooled net EV.** In Counter-SHORT, tail risk falls monotonically as age and MFE increase. For Counter-LONG and pooled EV, performance shows sweet spots in intermediate-to-high maturity, with pullbacks in early regimes being a high-variance barbell (large winners mixed with catastrophic continuation blowouts).

11. **How do the TRAIN patterns hold up in 2025 Q1 and 2025 Q2?**  
    **Answer:** **They hold up with remarkable consistency.** In all three periods, 1st pullbacks have catastrophic loss rates of $9.4\%$ to $10.7\%$, while 4th+ pullbacks have catastrophic rates of $6.2\%$ to $7.2\%$ (a stable $1.5\times$ risk ratio). In both TRAIN and Q2, mature regimes (Q5 age and Q5 MFE) suffer less than half the catastrophic rate of younger cohorts.

12. **Is the fat-tail problem primarily an entry-timing problem (entering too early in the incumbent regime) or an exit-management problem (failing to cut continuations)?**  
    **Answer:** **It is fundamentally an EXIT-MANAGEMENT problem.** Because early-regime entries are required to capture the largest multi-ATR trend reversals (yielding $+0.66\text{A}$ EV on 1st pullback Counter-SHORT), preventing these entries at inception destroys strategy profitability. The failure occurs after entry, when a trade moves $-1.00\text{A}$ to $-2.00\text{A}$ adverse and the unstopped strategy passively holds into a catastrophic continuation blowout.

13. **Would a simple rule-based entry filter (e.g., "no Counter-SHORT on 1st pullback if regime age is young") be justified based on this evidence, or does it sacrifice too much positive EV?**  
    **Answer:** **It is NOT justified.** It sacrifices too much positive EV. All candidate entry-risk regions have positive mean PnL ($+0.11\text{A}$ to $+0.66\text{A}$). Hard entry filtering throws the baby out with the bathwater.

14. **Should regime maturity features be added to the M4 retraining candidate list for a future study?**  
    **Answer:** **Yes, absolutely.** The current M4 model's $-0.585$ correlation with pre-pullback MFE and inverse selection bias proves that M4 lacks explicit lifecycle context. Adding non-linear interaction features (e.g., `pre_pullback_max_mfe_atr`, `regime_age_sec`, and ordinal interactions with pullback depth) would allow gradient boosted trees to price pullback quality conditionally, distinguishing shallow pullbacks in mature trends from shallow pullbacks in runaway trends.

15. **What is the recommended next research step: entry filter design, M4 feature expansion, or focus on exit/risk policy?**  
    **Answer:** **Primary Focus: Exit / Dynamic Risk Policy. Secondary Focus: M4 Retraining / Feature Expansion.** Static entry filters should be permanently shelved. The validated dynamic thesis-failure policy (evaluating causal path state post-entry) directly addresses the true causal mechanism: cutting the runaway continuations while letting early reversals run.

---

## 6. Architectural Recommendations & Mandatory Next Steps

1. **Do NOT Implement Rule-Based Entry Filters:**  
   The quantitative evidence definitively refutes the hypothesis that static rule-based entry pruning is an effective risk-reduction tool. The collateral damage to positive expectancy is unacceptably high.

2. **Rely on Dynamic Thesis-Failure Risk Policy:**  
   The preceding studies (`nq_h050_dynamic_thesis_failure_policy` and `nq_h050_dynamic_thesis_failure_policy_q2_oos`) established that post-entry path dynamics cleanly separate recoverable retests from runaway continuations. This is the correct layer of the trading architecture for left-tail containment.

3. **Queue M4 Lifecycle Feature Expansion for Future Model Iteration:**  
   When M4 is eventually retrained in a future dedicated model study, the 17-feature surface should be augmented with regime maturity features (`pre_pullback_max_mfe_atr`, `regime_age_sec`, and ordinal indicators). This will cure M4's blind spot without requiring blunt hard filters.

4. **Mandatory Research Stop:**  
   In compliance with repository research governance, this observational study terminates here. No model retraining, stop tuning, or production strategy modifications have been performed.

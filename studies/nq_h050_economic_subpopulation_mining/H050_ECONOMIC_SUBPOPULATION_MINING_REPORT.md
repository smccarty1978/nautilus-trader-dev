# H050 Economic Subpopulation Mining Study: Final Report

**Study ID:** `nq_h050_economic_subpopulation_mining`  
**Date:** 2026-09-17  
**Lineage:** `studies/nq_h050_mtf_regime_context_features` $\rightarrow$ `studies/nq_h050_economic_subpopulation_mining`  
**Temporal Split:** 2023 Discovery / OOF Fitting ($N=10,605$) | 2024 Untouched Validation ($N=10,888$) | 2025 Q1 Frozen Forward Diagnostic ($N=2,422$)  
**Status:** Completed  

---

## Executive Answer

### 1. Was the "Unicorn" Subpopulation Found?
**NO.** No subpopulation on the existing causal H050 feature surface simultaneously achieves the user-level economic target of **5–10 trades/day** at **$\ge +0.30$ ATR/trade net** with **materially controlled drawdown** and **non-tail-dependent** robustness on untouched held-out data.

While select subsets ostensibly print $\ge +0.30$ ATR/trade on 2024 (e.g. `LONG_x_Young` at $+0.3831$ ATR/trade, or `ML_10_day_EV_LowCat` at $+0.3931$ ATR/trade):
1. **Severe Tail Dependence:** Every candidate fails the mandatory tail-dependence stress test. For `LONG_x_Young`, dropping the top 1% of winners drops net expectancy from $+0.3831$ to **$-0.0162$ ATR/trade** (a complete collapse into negative territory).
2. **Extreme Drawdown & Inconsistency:** The drawdown profile across all subsets remains massive. `LONG_x_Young` suffers a max drawdown of **$783.4$ ATR** ($\$128,910$ / $929$ trades duration) and collapses in 2025 Q1 to **$-0.4041$ ATR/trade**. `ML_10_day_EV_LowCat` endures a max drawdown of **$373.8$ ATR** ($\$68,660$).
3. **Temporal Inversion:** The structural subsets invert completely across market regimes: `LONG_x_Young` is $+0.05$A in 2023, $+0.38$A in 2024, and **$-0.40$A in 2025 Q1**. Conversely, `LONG_x_Mature` is $+0.32$A in 2023, collapses to **$-2.13$A in 2024**, and then explodes to $+6.50$A in 2025 Q1.

### 2. Best Candidate Summary Card

| Metric | Best Frequency Subpopulation (`ML_10_day_EV_LowCat`) | Best Structural Leaf (`Interpretable_Leaf_4`) |
| :--- | :---: | :---: |
| **Type** | Risk-Adjusted ML Filter (Top 24% EV $\cap$ Low Catastrophic) | Shallow Decision Tree Leaf |
| **Rule / Definition** | `pred_ev >= -0.0617 AND pred_p_cat < 0.1265` | `minutes_from_rth_open <= 380.65` & `range_15m <= 9.34A` & `dist_prior_mfe <= 1.74A` |
| **2024 Trades / Day** | **$4.53$ trades/day** | **$1.75$ trades/day** (Fails Frequency Target) |
| **2023 OOF EV** | **$-0.4976$ ATR/trade** | **$+0.7040$ ATR/trade** |
| **2024 Validation Net ATR** | **$+0.3931$ ATR/trade** | **$+0.4166$ ATR/trade** |
| **2025 Q1 Forward Diagnostic**| **$+0.7048$ ATR/trade** | **$+0.0974$ ATR/trade** |
| **2024 Win Rate** | $57.53\%$ | $51.00\%$ |
| **2024 Avg Win / Avg Loss** | $3.084\text{A} / -3.286\text{A}$ ($0.94\times$) | $2.417\text{A} / -1.704\text{A}$ ($1.42\times$) |
| **2024 Profit Factor** | $1.2846$ | $1.5104$ |
| **2024 Catastrophic Rate** | $15.15\%$ | $8.65\%$ |
| **2024 Max Drawdown** | **$373.8$ ATR** ($\$68,660$) | **$49.6$ ATR** ($\$9,545$) |
| **Tail Stress Test (Ex-Top 1%)**| **$-0.0055$ ATR/trade** (**FAIL**) | **$+0.0714$ ATR/trade** (**FAIL**) |
| **Top 1% PnL Share** | $101.4\%$ (100% of profit from top 1%) | $83.1\%$ |

### 3. Core Technical Findings
* **Direct ML EV Ranking Fails Completely:** Fitting a regression model to predict `c1_net_pnl_atr` produces negative out-of-fold and held-out expectancy across all top deciles (Top 10% EV is $-0.81$A in 2023 OOF, $-0.43$A in 2024). Standard MSE/tree regression prioritizes extreme volatility regimes where trades have large positive upside *potential*, but simultaneously experience massive catastrophic blowout losses (catastrophic rate $>20\%$).
* **Catastrophic Tail Filtering Adds Value, But Unstable:** Adding a secondary model to exclude trades with above-median predicted catastrophic risk flips the top EV bucket from negative ($-0.01$A) to positive ($+0.39$A in 2024, $+0.70$A in 2025 Q1). However, the 2023 OOF discovery score was **$-0.4976$A**, demonstrating that the ranking criteria were not stable out-of-sample in discovery.
* **Structural Asymmetry:** The SHORT side of H050 is structurally broken. Across all years and age buckets, counter-trend SHORT entries average **$-0.21$A (2023)**, **$-0.35$A (2024)**, and **$-0.01$A (2025 Q1)**. Conditioning on mature regimes, slow pullbacks, or deep pullbacks does not rescue SHORT counter-trend trading.
* **The "Mature Regime Edge" is an Unstable Artifact:** Mature regimes ($>1800$s) produced $+0.32$A in 2023, collapsed catastrophically to **$-2.13$A in 2024** (with average loss of $-8.42$A and max DD of $849$A), before rebounding to $+6.50$A in 2025 Q1 due to massive macro runaway trends. It is not an investable, stationary subpopulation.

---

## Master Candidate Subpopulation Matrix

All metrics below are computed on the **2024 Untouched Validation** split unless noted:

| Candidate | Type | 2024 Tr/Day | 2023 OOF EV | 2024 Net ATR | 2025 Q1 EV | Win Rate | Avg Win / Loss | PF | Cat Rate | Max DD (ATR) | Ex-Top 1% Net ATR | Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Broad H050** | Baseline | $42.20$ | $-0.0696\text{A}$ | $-0.0884\text{A}$ | $+0.1739\text{A}$ | $55.8\%$ | $2.59 / -3.52$ | $0.94$ | $13.6\%$ | $2,296.5\text{A}$ | $-0.3777\text{A}$ | NOT_USEFUL |
| **LONG Only** | Baseline | $20.95$ | $+0.0799\text{A}$ | $+0.1809\text{A}$ | $+0.3437\text{A}$ | $60.2\%$ | $2.87 / -3.93$ | $1.12$ | $12.3\%$ | $1,665.4\text{A}$ | $-0.1737\text{A}$ | WEAK |
| **SHORT Only** | Baseline | $21.25$ | $-0.2101\text{A}$ | $-0.3539\text{A}$ | $-0.0063\text{A}$ | $51.5\%$ | $2.27 / -3.18$ | $0.77$ | $14.8\%$ | $2,458.6\text{A}$ | $-0.5742\text{A}$ | NOT_USEFUL |
| **Young ($\le 600$s)** | Baseline | $28.65$ | $-0.0570\text{A}$ | $+0.1001\text{A}$ | $-0.1612\text{A}$ | $56.6\%$ | $2.69 / -3.32$ | $1.07$ | $13.3\%$ | $861.0\text{A}$ | $-0.2174\text{A}$ | WEAK |
| **Middle ($600\text{--}1800$s)**| Baseline | $10.78$ | $-0.1048\text{A}$ | $-0.3958\text{A}$ | $+0.0229\text{A}$ | $54.4\%$ | $2.39 / -3.75$ | $0.77$ | $14.6\%$ | $1,282.9\text{A}$ | $-0.6102\text{A}$ | NOT_USEFUL |
| **Mature ($>1800$s)** | Baseline | $2.78$ | $-0.0626\text{A}$ | $-0.8404\text{A}$ | $+4.2586\text{A}$ | $53.6\%$ | $2.26 / -4.48$ | $0.59$ | $12.7\%$ | $849.0\text{A}$ | $-1.1313\text{A}$ | NOT_USEFUL |
| **LONG $\times$ Young** | Structural | $15.02$ | $+0.0547\text{A}$ | $+0.3831\text{A}$ | $-0.4041\text{A}$ | $60.5\%$ | $2.94 / -3.58$ | $1.27$ | $11.9\%$ | $783.4\text{A}$ | $-0.0162\text{A}$ | TAIL_DEPENDENT |
| **LONG $\times$ Mature** | Structural | $0.96$ | $+0.3248\text{A}$ | $-2.1254\text{A}$ | $+6.5014\text{A}$ | $53.0\%$ | $3.45 / -8.42$ | $0.46$ | $19.4\%$ | $849.0\text{A}$ | $-2.6008\text{A}$ | NOT_USEFUL |
| **ML Top 10% EV** | ML Ranker | $3.28$ | $-0.8144\text{A}$ | $-0.4267\text{A}$ | $+0.2319\text{A}$ | $58.0\%$ | $4.07 / -6.77$ | $0.85$ | $21.2\%$ | $767.7\text{A}$ | $-0.9608\text{A}$ | NOT_USEFUL |
| **ML 5 trades/day EV**| ML Ranker | $3.95$ | $-0.6879\text{A}$ | $-0.4218\text{A}$ | $-0.3322\text{A}$ | $57.4\%$ | $3.84 / -6.27$ | $0.84$ | $20.6\%$ | $889.5\text{A}$ | $-0.9024\text{A}$ | NOT_USEFUL |
| **ML 10 trades/day EV**| ML Ranker | $8.48$ | $-0.2888\text{A}$ | $-0.0147\text{A}$ | $+0.0463\text{A}$ | $58.8\%$ | $3.15 / -4.61$ | $0.99$ | $16.2\%$ | $915.3\text{A}$ | $-0.3781\text{A}$ | NOT_USEFUL |
| **ML 5/day EV $\cap$ LowCat** | ML Risk-Adj | $1.98$ | $-1.0060\text{A}$ | $+0.6169\text{A}$ | $+0.4472\text{A}$ | $58.5\%$ | $4.11 / -4.36$ | $1.34$ | $17.6\%$ | $408.0\text{A}$ | $+0.0451\text{A}$ | TAIL_DEPENDENT |
| **ML 10/day EV $\cap$ LowCat**| ML Risk-Adj | $4.53$ | $-0.4976\text{A}$ | $+0.3931\text{A}$ | $+0.7048\text{A}$ | $57.5\%$ | $3.08 / -3.29$ | $1.28$ | $15.2\%$ | $373.8\text{A}$ | $-0.0055\text{A}$ | TAIL_DEPENDENT |
| **Interpretable Leaf 4** | Rule Tree | $1.75$ | $+0.7040\text{A}$ | $+0.4166\text{A}$ | $+0.0974\text{A}$ | $51.0\%$ | $2.42 / -1.70$ | $1.51$ | $8.7\%$ | $49.6\text{A}$ | $+0.0714\text{A}$ | FREQ_TOO_LOW |

---

## Explicit Answers to the 27 Decision Questions (§31)

1. **How many H050 opportunities/day exist?**  
   - 2023: $41.10$ opportunities/day ($10,605$ events over $258$ days).  
   - 2024: $42.20$ opportunities/day ($10,888$ events over $258$ days).  
   - 2025 Q1: $39.06$ opportunities/day ($2,422$ events over $62$ days).  
   - Overall average: **$\approx 41.5$ opportunities/day**.
2. **What coverage corresponds to 5 trades/day?**  
   - **$12.16\%$** (2023), **$11.85\%$** (2024), **$12.80\%$** (2025 Q1). Approximately **$12.0\%$**.
3. **What coverage corresponds to 10 trades/day?**  
   - **$24.33\%$** (2023), **$23.70\%$** (2024), **$25.60\%$** (2025 Q1). Approximately **$24.0\%$**.
4. **Does any 2023 OOF subset achieve $\ge +0.30$A?**  
   - Yes: `Interpretable_Leaf_4` ($+0.7040$A), `LONG_x_Mature` ($+0.3248$A), and very narrow high-right-tail filters. Direct ML EV models failed completely in 2023 OOF ($-0.28$A to $-0.81$A).
5. **Does it survive unchanged in 2024?**  
   - `Interpretable_Leaf_4` survives with $+0.4166$A, but `LONG_x_Mature` collapses catastrophically to **$-2.1254$A**.
6. **Does any 2024 subset simultaneously achieve 5–10 trades/day and $\ge +0.30$A?**  
   - **NO.** Only `LONG_x_Young` ($15.02$ trades/day, $+0.3831$A) exceeded $+0.30$A, but it generates $15$ trades/day and is completely tail-dependent ($-0.016$A ex-top 1%). `ML_10_day_EV_LowCat` achieved $+0.3931$A but produced only **$4.53$ trades/day** and also collapsed ex-top 1%.
7. **If not, what is the best robust 5–10/day subset?**  
   - There is none that meets robustness criteria. The closest is `LONG_Only` ($20.95$ trades/day, $+0.1809$A) and `ML_10_day_EV_LowCat` ($4.53$ trades/day, $+0.3931$A), both severely tail-dependent.
8. **Is its edge high-win or asymmetric-R/R?**  
   - For `ML_10_day_EV_LowCat`: Win rate is $57.5\%$, Avg Win/Loss is $0.94\times$ (modest win rate, symmetric payout).  
   - For `Interpretable_Leaf_4`: Win rate is $51.0\%$, Avg Win/Loss is $1.42\times$ (asymmetric risk/reward archetype).
9. **What is its max drawdown?**  
   - `ML_10_day_EV_LowCat`: **$373.79$ ATR** ($\$68,660$).  
   - `LONG_x_Young`: **$783.44$ ATR** ($\$128,910$).  
   - `Interpretable_Leaf_4`: **$49.58$ ATR** ($\$9,545$).
10. **What is its worst month?**  
    - `ML_10_day_EV_LowCat`: October 2024 ($-0.6480$ ATR/trade, $-\$24,700$) and December 2024 ($-1.1029$ ATR/trade).  
    - `LONG_x_Young`: April 2024 ($-1.5446$ ATR/trade, $-\$95,340$) and December 2024 ($-0.9623$ ATR/trade, $-\$66,430$).
11. **How much PnL comes from the top 1% of winners?**  
    - `ML_10_day_EV_LowCat`: **$101.38\%$** of total PnL.  
    - `LONG_x_Young`: **$104.17\%$** of total PnL.  
    - `Interpretable_Leaf_4`: **$83.05\%$** of total PnL.
12. **Does removing the top 1% destroy the edge?**  
    - **YES.** In every candidate, removing the top 1% turns net expectancy negative or cuts it to near zero (`ML_10_day_EV_LowCat` goes from $+0.393$A to **$-0.0055$A**; `LONG_x_Young` goes from $+0.383$A to **$-0.0162$A**).
13. **Is LONG-only genuinely positive in 2023?**  
    - Yes, marginally: **$+0.0799$ ATR/trade** ($56.0\%$ win rate, PF $1.06$).
14. **In 2024?**  
    - Yes: **$+0.1809$ ATR/trade** ($60.2\%$ win rate, PF $1.12$).
15. **In 2025 Q1?**  
    - Yes: **$+0.3437$ ATR/trade** ($53.1\%$ win rate, PF $1.20$).
16. **Does mature LONG outperform LONG overall?**  
    - **NO.** In 2024, `LONG_x_Mature` suffered a disastrous **$-2.1254$ ATR/trade** (vs $+0.1809$A for LONG overall). In 2023 it was $+0.32$A and 2025 Q1 $+6.50$A. It is wildly volatile and regime-inconsistent.
17. **Does ML add value beyond LONG/maturity filtering?**  
    - ML regression alone *detracts* value (selects high-volatility blowouts). ML risk-tail filtering (`LowCat`) recovers value ($+0.39$A vs $+0.18$A), but fails the 2023 OOF stability test.
18. **Is there a viable SHORT subgroup?**  
    - **NO.** SHORT unconditional expectancy is $-0.21$A (2023), $-0.35$A (2024), and $-0.01$A (2025 Q1). No structural age or velocity subgroup survives.
19. **Does pullback depth materially help once direction/age are controlled?**  
    - **NO.** Correlation of `pullback_depth_atr` with `c1_net_pnl_atr` within LONG is virtually zero ($r = +0.0011$).
20. **Does pullback speed materially help?**  
    - **NO.** Correlation of `pullback_velocity_atr_sec` with PnL within LONG is slightly negative ($r = -0.0217$).
21. **Does time $\times$ depth interaction improve the candidate population?**  
    - **NO.** Adding depth or velocity interactions did not separate profitable regimes.
22. **Which features define the strongest interpretable leaf?**  
    - RTH time (`minutes_from_rth_open <= 380.65`, i.e. before the final 10 minutes of trading), realized range volatility (`realized_range_15m_atr <= 9.34A`), and distance from prior regime extreme (`current_price_from_prior_mfe_atr__tf_1m <= 1.74A`).
23. **How many trades/day does that leaf generate?**  
    - **$1.75$ trades/day** in 2024 ($451$ trades over $258$ days).
24. **Does the leaf validate in 2024 unchanged?**  
    - Yes, economically: $+0.7040$A (2023) $\rightarrow$ **$+0.4166$A (2024)**. But it generates only $1.75$ trades/day, failing the $5\text{--}10$/day requirement by $\approx 65\%$.
25. **Does any candidate meet the user's full economic target?**  
    - **NO.** Every candidate fails on either frequency ($<5$/day), drawdown/tail concentration, or 2023-2024 stability.
26. **If no, is there a $+0.20$A–$+0.30$A near-miss worth one further study?**  
    - No candidate demonstrates a non-tail-dependent edge at 5–10 trades/day.
27. **Or should broad H050 research be stopped?**  
    - **Broad H050 strategy development should be STOPPED.**

---

## Formal Verdicts (§32)

| Gate / Dimension | Formal Verdict | Empirical Justification |
| :--- | :---: | :--- |
| **`TARGET_FREQUENCY_FEASIBLE`** | **NO** | Subpopulations that demonstrate positive expectancy generate only $1.75$ to $4.53$ trades/day. The only subset producing $>10$/day (`LONG_x_Young`, $15.0$/day) has a $783$A max DD and turns negative ex-top 1%. |
| **`H050_SUBPOPULATION_0P30A`** | **NOT_FOUND** | No robust candidate achieves $\ge +0.30$A without total dependence on the top 1% of winners. |
| **`H050_SUBPOPULATION_0P20A`** | **NOT_FOUND** | No robust candidate achieves $\ge +0.20$A at the target 5–10 trades/day frequency without tail dependence. |
| **`LONG_COUNTER_REGIME_EDGE`** | **WEAK** | LONG counter-trend is positive across all splits ($+0.08$A, $+0.18$A, $+0.34$A), but suffers $>1,600$A max DD and extreme win concentration. |
| **`SHORT_COUNTER_REGIME_EDGE`** | **NOT_FOUND** | Consistently negative ($-0.21$A in 2023, $-0.35$A in 2024, $-0.01$A in 2025 Q1). No viable subpopulation exists. |
| **`MATURE_REGIME_EDGE`** | **NOT_FOUND** | Wildly unstable across years ($+0.32$A in 2023, $-2.13$A in 2024, $+6.50$A in 2025 Q1). Fails temporal invariance. |
| **`LONG_MATURE_INTERACTION`** | **NOT_FOUND** | Produced an unacceptable $-2.13$A in 2024 with a $45$-trade losing streak and $-8.42$A average loss. |
| **`ML_ADDS_BEYOND_SIMPLE_FILTERS`** | **NOT_FOUND** | Unconstrained ML regression worsens tail losses. Risk-adjusted ML fails 2023 OOF stability and produces $<5$ trades/day. |
| **`HIGH_WIN_ARCHETYPE`** | **NOT_FOUND** | No subpopulation naturally emerged with $>65\%$ win rate and controlled losses. |
| **`ASYMMETRIC_RR_ARCHETYPE`** | **FOUND** | `Interpretable_Leaf_4` demonstrated $1.42\times$ win/loss ratio with low drawdown ($49.6$A), but frequency is only $1.75$/day. |
| **`DRAWDOWN_PROFILE`** | **POOR** | All 5–10 trades/day candidates experience max drawdowns exceeding $370$ to $780$ ATR ($\$68\text{k}\text{--}\$128\text{k}$). |
| **`TAIL_DEPENDENCE`** | **HIGH** | In every candidate, $>80\%\text{--}100\%$ of total net PnL originates from the top 1% of trades. Edge collapses to zero or negative without them. |
| **`H050_LINEAGE_CONTINUE`** | **STOP** | Per §33 kill condition: Untouched 2024 validation confirms that no robust, non-tail-dependent subpopulation exists at 5–10 trades/day. |

---

## Conclusion & Recommendation

The empirical findings are definitive:
1. **The Core Hypothesis is Refuted:** The causal H050 feature surface does **not** contain an unmined subpopulation capable of supporting 5–10 trades/day at $+0.30$ ATR/trade net with controlled drawdown.
2. **Structural Defect in H050 Inception:** The entry trigger (pullback to H050) is fundamentally counter-trend. It suffers from an unavoidable left-tail blowout risk when incumbent trends continue. To achieve positive expectancy, any subpopulation must capture occasional massive runaway reversal winners ($\ge +3\text{A}$ to $+10\text{A}$), making the resulting strategy severely tail-dependent and prone to massive multi-month drawdowns when those rare runners do not appear.
3. **Execution Decision:** Stop broad H050 strategy development immediately. Do not attempt further feature engineering, threshold optimization, or alternative model architectures on this lineage.

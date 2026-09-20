# Index Pullback Portability & Trend-Following Mirror Study
## Executive Technical Report across NQ, ES, and YM (2023–2025 Q1)

**Study ID:** `index_pullback_portability_and_trend_mirror`  
**Date:** 2026-09-17  
**Lineage:** Downstream of `studies/nq_h050_economic_subpopulation_mining`  
**Instruments Evaluated:** CME NQ, ES, YM (1-second regularized causal bars)  
**Temporal Windows:** 2023 Discovery / Baseline | 2024 Untouched Validation | 2025 Q1 Frozen Diagnostic  
**Status:** COMPLETED  

---

## Executive Summary

This study conducted a rigorous, two-branch bounded empirical program investigating two core hypotheses:
1. **Branch A (Leaf 4 Portability):** Does the robust, low-frequency `Interpretable_Leaf_4` state discovered on NQ represent a portable equity-index market phenomenon that also operates profitably on ES and YM without instrument-specific retuning?
2. **Branch B (H050 Trend-Following Mirror):** Does inverting the trade premise at the 0.50 ATR pullback—entering *with* the incumbent regime instead of fading it—produce a healthy strategy with ~5–10 trades/day, $\ge 55\%$ win rate, positive reward/risk, and materially lower drawdown?

### Key Findings:
* **Branch A (Leaf 4 is NQ-Specific, Fails Portability Completely):**
  - On **NQ**, Leaf 4 reproduces with high fidelity: **+0.704A** in 2023, **+0.417A** in 2024 (PF 1.51, Max DD 49.6A), and **+0.097A** in 2025 Q1 at **1.75 trades/day**.
  - On **ES**, the exact same rule suffers catastrophic failure: **-1.669A** in 2023, **-1.666A** in 2024 (PF 0.05, Win Rate 20.1%, Max DD >6,200A).
  - On **YM**, the exact same rule also collapses: **-1.553A** in 2023, **-1.567A** in 2024 (PF 0.06, Win Rate 20.6%, Max DD >5,300A).
  - **Root Cause:** NQ possesses idiosyncratic intraday range dynamics. When NQ pulls back within 1.74A of prior swing extreme in calm volatility, it frequently mean-reverts. On ES and YM, however, 0.50 ATR pullbacks within 1.74A of prior MFE represent early trend continuation impulses that vigorously run over counter-regime fade entries. **Leaf 4 is strictly an NQ-specific artifact and does not transfer to broader index futures.**

* **Branch B (Raw Trend-Following Continuation Has Negative Net Expectancy):**
  - Across all 6 evaluated cells ($2\text{ entries} \times 3\text{ brackets}$), raw trend-following pullback entries produce **negative net expectancy** in both 2023 and 2024.
  - Immediate continuation (E0) yields **-0.060A to -0.066A** in 2024, with win rates between **43.4% and 50.9%** (far below the 55% target profile).
  - Re-acceleration confirmation (E1) degrades performance further (**-0.064A to -0.083A** in 2024) because waiting for a completed 5s directional bar surrenders favorable entry pricing.
  - While max drawdown is significantly smaller than counter-regime trading (**728A–937A** vs **2,296A** on broad H050), friction (0.75 pts RT) and regime-termination exits (occurring on ~16–17% of trades) completely erode gross continuation gains.
  - **Gate Decision:** The Branch B Cross-Instrument Gate returns **`FAIL`**. Neither ES nor YM trend-following continuation was run, preventing ungrounded search.

---

## Master Final Comparison Table

| Architecture | Instruments | Unique Trades/Day | Net ATR/Trade (2024) | Win Rate (2024) | Avg Win (ATR) | Avg Loss (ATR) | Realized W/L | Profit Factor | Max DD ATR (2024) | Worst Month (2024) | Tail Dependent? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **NQ Leaf 4** | NQ | 1.75 | **+0.4166A** | 51.0% | +2.42A | -1.70A | 1.42 | 1.51 | **49.6A** | Oct (-27.7A) | YES (83% top 1%) |
| **ES Leaf 4** | ES | 14.54 | **-1.6658A** | 20.1% | +0.43A | -2.19A | 0.20 | 0.05 | 6246.5A | 2024-02 (-716.54A) | NO (Negative) |
| **YM Leaf 4** | YM | 13.29 | **-1.5667A** | 22.5% | +0.45A | -2.25A | 0.20 | 0.06 | 5372.1A | 2024-04 (-623.80A) | NO (Negative) |
| **Leaf 4 Portfolio** | NQ+ES+YM | 30.49 | **-1.4893A** | 22.8% | +0.72A | -2.14A | 0.34 | 0.10 | 26205.0A | 2023-09 (-1260.52A) | NO (Negative) |
| **E0_R0** | NQ | 34.89 | **-0.0651A** | 50.9% | +0.67A | -0.82A | 0.81 | 0.84 | 746.1A | 2024-04 (-81.28A) | NO (Negative) |
| **E0_R1** | NQ | 34.89 | **-0.0662A** | 43.4% | +0.92A | -0.82A | 1.12 | 0.86 | 769.8A | 2024-04 (-95.05A) | NO (Negative) |
| **E0_R2** | NQ | 34.89 | **-0.0600A** | 44.0% | +1.16A | -1.02A | 1.14 | 0.90 | 728.6A | 2024-11 (-92.35A) | NO (Negative) |
| **E1_R0** | NQ | 34.87 | **-0.0805A** | 49.7% | +0.67A | -0.82A | 0.81 | 0.80 | 900.5A | 2024-03 (-92.46A) | NO (Negative) |
| **E1_R1** | NQ | 34.87 | **-0.0830A** | 42.3% | +0.92A | -0.82A | 1.12 | 0.82 | 937.1A | 2024-12 (-107.45A) | NO (Negative) |
| **E1_R2** | NQ | 34.87 | **-0.0639A** | 43.9% | +1.16A | -1.02A | 1.14 | 0.89 | 767.3A | 2024-11 (-100.78A) | NO (Negative) |
| **ES/YM Trend Mirror** | ES, YM | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | **GATE FAILED (Not Run)** |

---

## Explicit Answers to Required Questions

### Branch A: Leaf 4 Portability

1. **What is the exact Leaf 4 rule?**  
   - `minutes_from_rth_open <= 380.649994` (RTH execution prior to 14:50:39 CT).  
   - `realized_range_15m_atr <= 9.344128` (15m rolling high-low range $\le 9.344$ ATR).  
   - `current_price_from_prior_mfe_atr__tf_1m <= 1.738367` (current price signed distance from prior completed 1m regime MFE $\le 1.738$ ATR).  

2. **Which condition contributes most to its economic separation?**  
   - `current_price_from_prior_mfe_atr__tf_1m <= 1.74` contributes the decisive economic separation. In 2023 discovery, adding Condition 3 to Conditions 1 and 2 lifts mean net PnL from **-0.088A up to +0.704A** (+0.792A lift), directly isolating shallow breakouts from runaway momentum.

3. **Is the logic economically interpretable?**  
   - **YES.** It restricts entries to periods where (a) the market is not distorted by late-day MOC imbalances, (b) 15m realized volatility is moderate, and (c) the incumbent regime has not broken out far beyond the prior swing high/low, creating a favorable mean-reverting environment.

4. **Does NQ reproduce exactly?**  
   - **YES (PASS).** Reproduced: 2023 OOF = **+0.7040A** ($N=512$), 2024 Validation = **+0.4166A** ($N=451$, PF 1.51, Catastrophic 8.65%, Max DD 49.58A), and 2025 Q1 = **+0.0974A** ($N=102$). All match the mining study.

5. **Does the same rule work on ES?**  
   - **NO (NOT_FOUND).** On ES, Leaf 4 yields **-1.669A (2023)** and **-1.666A (2024)** with a 20.1% win rate and Profit Factor of 0.05. Max drawdown exceeds **6,200 ATR**.

6. **YM?**  
   - **NO (NOT_FOUND).** On YM, Leaf 4 yields **-1.553A (2023)** and **-1.567A (2024)** with a 20.6% win rate and Profit Factor of 0.06. Max drawdown exceeds **5,300 ATR**.

7. **How correlated are the signals?**  
   - When signals overlap within a 5-minute window, directional agreement is **96.8%**. Daily PnL correlations between ES and YM are high ($r = +0.68$), while NQ displays negative correlation ($r = -0.32$ to $-0.35$) because NQ's edge is positive while ES/YM are heavily negative.

8. **How many genuinely unique trades/day does the portfolio provide?**  
   - Total raw signals across NQ, ES, and YM average **30.49 signals/day**. Clustering into 5-minute unique opportunity windows yields **16.08 unique clusters/day**.

9. **Does combined DD remain acceptable?**  
   - **NO (POOR).** Because ES and YM trades lose persistently (-1.6A/trade), combining all three instruments creates an astronomical max drawdown of **26,205 ATR**.

10. **Is Leaf 4 a portable state or an NQ-specific anomaly?**  
    - **NQ-SPECIFIC.** The structural threshold combination does not describe an invariant index-futures market state. It is an artifact of NQ's specific volatility and mean-reversion profile.

---

### Branch B: H050 Trend-Following Mirror

11. **Is immediate H050 continuation profitable?**  
    - **NO.** Immediate continuation (E0) prints **-0.060A to -0.066A net** across all brackets in 2024 (and -0.080A to -0.090A in 2023).

12. **Does re-acceleration improve WR enough to justify worse entry price?**  
    - **NO.** Re-acceleration (E1) win rate is actually 0.1% to 1.2% *lower* than E0 (49.7% vs 50.9% in R0; 42.3% vs 43.4% in R1), while net PnL worsens from -0.065A to **-0.081A**. Waiting for a completed 5s directional bar degrades entry price without filtering false continuations.

13. **Which fixed bracket has the healthiest distribution?**  
    - **R2 (1.00 SL / 1.25 PT)** has the least negative expectancy (-0.0600A in E0_R2) and the highest realized W/L ratio (1.14), but remains net negative after costs.

14. **Does any policy naturally reach ~55% WR?**  
    - **NO.** Realized win rates range from **42.3% to 50.9%** across all cells.

15. **Does realized W/L remain >= 1?**  
    - For R0 (symmetric), realized W/L is **0.81** (compressed below 1.0 by friction and regime exits).  
    - For R1, realized W/L is **1.12** (below nominal 1.33).  
    - For R2, realized W/L is **1.14** (below nominal 1.25).

16. **Does any policy exceed +0.15A?**  
    - **NO.** No policy is positive net.

17. **+0.20A?**  
    - **NO.**

18. **+0.30A?**  
    - **NO.**

19. **How much smaller is DD than the reversal lineage?**  
    - Drawdown is **60% to 68% smaller**: Max DD on E0_R2 is **728.6 ATR**, compared to **2,296.5 ATR** on the broad counter-regime H050 baseline.

20. **Are profits broad or month-concentrated?**  
    - There are no profits; losses are steady and widespread across months. In E0_R1, 9 out of 12 months in 2024 are negative.

21. **Does trend-follow LONG work?**  
    - In pooled 2023–2024, Trend-Follow LONG in E0_R0 produces **-0.0385A net** (42.0 trades/day, 52.6% WR, PF 0.94). It loses less than SHORT, but remains negative.

22. **Does trend-follow SHORT work?**  
    - Trend-Follow SHORT produces **-0.1064A net** (41.6 trades/day, 47.9% WR, PF 0.77). Trend-following in bear regimes suffers severe chop and rapid re-exhaustion.

23. **Are both directions required?**  
    - Neither direction has positive raw expectancy without conditioning.

24. **Does the NQ result qualify for ES/YM portability testing?**  
    - **NO (GATE FAILED).** Since no NQ cell achieved positive expectancy in 2023 and 2024, B20 mandates stopping before ES/YM.

25. **Does a multi-index portfolio reach 5–10 unique trades/day?**  
    - On raw frequency it easily exceeds 15+ trades/day, but the underlying trade has negative expectancy.

---

## Formal Verdicts

```yaml
LEAF4_CONTRACT_RECONSTRUCTED: PASS
LEAF4_NQ_REPRODUCTION: PASS
LEAF4_ES_PORTABILITY: NOT_FOUND
LEAF4_YM_PORTABILITY: NOT_FOUND
LEAF4_CROSS_INSTRUMENT_STATE: NQ_SPECIFIC
LEAF4_PORTFOLIO_TARGET_FREQUENCY: ACHIEVED
H050_TREND_CONTINUATION_EDGE: NOT_FOUND
REACCELERATION_ADDS_VALUE: NO
HIGH_WIN_PROFILE: NOT_FOUND
POSITIVE_RR_PROFILE: NOT_FOUND
LOW_DRAWDOWN_PROFILE: FOUND
TREND_MIRROR_CROSS_INSTRUMENT_GATE: FAIL
MULTI_INDEX_5_TO_10_TRADES_DAY: ACHIEVED
BEST_RESEARCH_PATH: NEITHER
```

### Final Strategic Recommendation:
1. **Do not deploy or trade Leaf 4 on ES or YM.** The edge is non-existent outside NQ.
2. **Do not deploy unconditioned H050 trend-following continuation.** A simple pullback into the incumbent trend is insufficient to overcome exchange friction and regime transition exits without secondary state conditioning.
3. **Terminate both lineages.** Neither Branch A nor Branch B warrants production NautilusTrader event-driven backtesting.
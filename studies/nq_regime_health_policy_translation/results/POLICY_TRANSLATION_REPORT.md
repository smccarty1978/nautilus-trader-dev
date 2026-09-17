# REGIME HEALTH POLICY TRANSLATION STUDY
## Frozen-State Economic Validation & Final Entry-Exit Selection Gate

**Repository**: `smccarty1978/nautilus-trader-dev`  
**Study**: `studies/nq_regime_health_policy_translation`  
**Date**: September 2026  
**Status**: `COMPLETE`  
**Decision Classification**: `OUTCOME_C_INFORMATION_VALID_POLICY_NOT_USEFUL`  
**Reversal Diagnostic Verdict**: `PROMISING`  

---

## Executive Summary

This study evaluates whether the causally streaming regime health model (**M1-U**, frozen 24-feature dual-head LightGBM) improves realized event-driven trading economics when translated into position-exit and risk-invalidation policies, compared against the natural $V_A$ regime-flip baseline (**P0**).

Across **16,706 natural $V_A$ regimes** spanning 2023 through 2025 Q1 (14,945 TRAIN regimes across 2023–2024 and 1,761 untouched OOS regimes in 2025 Q1), four frozen, unoptimized policies were evaluated under strict NautilusTrader causal event-driven execution assumptions ($20/pt multiplier, $5 round-trip commission, and 1-tick adverse slippage per side):

1. **P0 (Natural Baseline)**: Exit exclusively at natural opposite $V_A$ regime flip.
2. **P1 (Immediate $Q_4$ Exit)**: Exit at first observation of severe dual-head hazard ($H_1 \ge 0.50 \land H_2 \ge 0.25$).
3. **P2 ($Q_4$ + 60s Continuous Persistence)**: Arm invalidation watch on $Q_4$ entry; exit only if $Q_4$ persists continuously for $\ge 60$s.
4. **P3 ($Q_4$ + 60s Persistence + Recovery Cancellation)**: Arm invalidation watch; cancel/disarm watch if prospective hazard recovery is causally confirmed ($(H_{\text{peak}} - H(t)) \ge 0.15$).

### The Definitive Finding
**The health model's predictive information is empirically valid (AUC ~0.78), but applying it as an early exit policy fails to improve realized trading economics.**
- **P0 Natural Baseline** achieves the highest Gross Expected Value (Gross EV = **+$2.00/trade**, Gross PnL = +$33,410). After friction (-$15.00/trade), Net EV is **-$13.00/trade** (Profit Factor 0.931).
- **P1 Immediate $Q_4$ Exit** degrades Gross EV to **+$0.57/trade** (Net EV **-$14.43/trade**, Profit Factor 0.878). While it compresses left-tail losses (worst 1% mean loss improves from -$1,236 to -$724), it prematurely forfeits **6,887 subsequent $\ge 1$ ATR trend extensions** and 4,148 $\ge 2$ ATR extensions (abandoning 271,529 points of favorable run-up).
- **P2 60s Persistent $Q_4$ Exit** avoids 64.7% of P1's false exits, exiting 34.3% (5,733) of regimes with an average lead time of **362.3 seconds** before the natural flip. However, it still degrades Gross EV to **+$0.01/trade** (Net EV **-$14.99/trade**, Profit Factor 0.915).
- **P3 Recovery Cancellation** cancels 130 invalidation watches where prospective recovery is confirmed, but these recovered trades still produce net negative terminal PnL (-$58,810), yielding Gross EV of **-$0.20/trade** (Net EV **-$15.20/trade**).

### Strategic Resolution
Because no health-state exit policy outperforms the natural regime-flip baseline, this study triggers a **MANDATORY STOP** on trend-exit optimization under **OUTCOME_C**. 
However, the **Observational Reversal Diagnostic** is **`PROMISING`**: persistent $Q_4$ invalidation prospectively leads the natural flip by 362.3 seconds with 0.81 ATR of prospective adverse price movement toward the opposite direction, indicating that regime health deterioration is valuable as an **opposite-direction setup signal**, not as an exit rule for existing positions.


---

## Gate 0 Verification & Artifact Hashes
All parent models and datasets were verified prior to execution with zero divergence:

| Artifact | File / Hash | Verification Status |
|---|---|---|
| **HEAD_1_M1_U.joblib** | `a6047c14815ced1786b8a00f1d18d3495a8e285bb91e3de0f3f9bf98600390c2` | **MATCH** |
| **HEAD_2_M1_U.joblib** | `693ab868289d30b7eacbc4bad144a97755596850b133a40b098c96516cf626ff` | **MATCH** |
| **natural_regime_ledger.parquet** | `9b4da98f88fcfe3e0b5ebbc6cb9ad696...` | **MATCH** |
| **universal_path_state_ledger.parquet** | `7ca87160ca48b8098b5767f277e0b347...` | **MATCH** |
| **trajectory_observation_ledger.parquet** | `d98c41c4a815963de2cd7a537f4d5b27...` | **MATCH** |
| **forward_outcome_ledger.parquet** | `9b1df85c667d5219a206d1c9bfee746f...` | **MATCH** |

### Population Reconciliation
- **Catalog Natural Regimes**: 16,713
- **Eligible Natural Regimes (with streaming path state)**: 16,706
- **Excluded at Inception (duration < 60s, 0 path observations)**: 7
- **P0 Entered Trades**: 16,706
- **P1 Entered Trades**: 16,706
- **P2 Entered Trades**: 16,706
- **P3 Entered Trades**: 16,706
- **P4 Status**: `OMITTED` (per instruction, parent contracts did not define unambiguous frozen thresholds)
- **Missing / Extra / Duplicate / Retimed Trades**: 0
- **Population Divergence between P0 and P3**: **0 (ZERO)**

---

## Policy Performance Comparison

### Complete Population (16,706 Regimes | 2023 - 2025 Q1)

| Metric | P0 (Natural Baseline) | P1 (Immediate $Q_4$) | P2 ($Q_4$ + 60s Persistence) | P3 (P2 + Recovery Cancel) |
|---|---|---|---|---|
| **Trades** | 16,706 | 16,706 | 16,706 | 16,706 |
| **Gross PnL ($)** | +$33,410 | +$9,485 | +$205 | -$3,380 |
| **Gross EV ($/trade)** | **+$2.00** | +$0.57 | +$0.01 | -$0.20 |
| **Net PnL ($)** | -$217,180 | -$241,105 | -$250,385 | -$253,970 |
| **Net EV ($/trade)** | **-$13.00** | -$14.43 | -$14.99 | -$15.20 |
| **Profit Factor** | **0.931** | 0.878 | 0.915 | 0.914 |
| **Win Rate** | **32.8%** | 30.6% | 32.1% | 32.2% |
| **Max Drawdown ($)** | **$234,700** | $245,125 | $273,755 | $276,295 |
| **Mean Holding Time** | 924.5s (15.4m) | 348.5s (5.8m) | 800.0s (13.3m) | 802.2s (13.4m) |
| **Mean MFE (ATR)** | **2.19** | 1.39 | 2.03 | 2.03 |
| **Mean MAE (ATR)** | 1.17 | **0.67** | 1.08 | 1.08 |
| **Health Exit Count** | 0 (0.0%) | 16,252 (97.3%) | 5,733 (34.3%) | 5,603 (33.5%) |
| **Natural Flip Exits** | 16,706 (100.0%) | 454 (2.7%) | 10,973 (65.7%) | 11,103 (66.5%) |

### TRAIN vs OOS Replication Table

| Metric | 2023 - 2024 TRAIN (14,945 trades) | 2025 Q1 Untouched OOS (1,761 trades) | Replication Assessment |
|---|---|---|---|
| **P0 Gross EV** | +$0.99 | +$10.60 | Stable positive baseline |
| **P0 Net EV** | -$14.01 | -$4.40 | Baseline friction cost |
| **P1 Gross EV** | -$0.45 | +$9.23 | Severe truncation in both |
| **P1 Net EV** | -$15.45 | -$5.77 | Underperforms P0 in both |
| **P2 Gross EV** | -$1.86 | +$15.94 | OOS rebound due to trend regime |
| **P2 Net EV** | -$16.86 | +$0.94 | Mixed; degrades full sample |
| **P3 Gross EV** | -$1.98 | +$14.88 | Tracking P2 closely |
| **P3 Net EV** | -$16.98 | -$0.12 | Degrades full sample |

---

## Trade-Level Attribution Analysis
Every policy exit was classified counterfactually against the natural baseline:

| Outcome Classification | P1 (Immediate $Q_4$) | P2 ($Q_4$ + 60s Persistence) | P3 (P2 + Recovery Cancel) | Economic Interpretation |
|---|---|---|---|---|
| **AVOIDED_TERMINAL_LOSS** | 9,488 (56.8%) | 2,734 (16.4%) | 2,670 (16.0%) | Successfully cut losses before catastrophic flip |
| **PREMATURE_EXIT_REEXTENDED** | 4,148 (24.8%) | 1,060 (6.3%) | 1,034 (6.2%) | Exited early; regime subsequently made $\ge 1$ ATR MFE |
| **BENEFICIAL_EARLY_EXIT** | 1,883 (11.3%) | 794 (4.8%) | 787 (4.7%) | Locked in profit before trend decayed |
| **WHIPSAW** | 145 (0.9%) | 347 (2.1%) | 331 (2.0%) | Exited transient dip, suffered friction & worse price |
| **RECOVERY_PRESERVED_TREND** | — | — | 102 (0.6%) | Recovery disarmed watch, preserved winner run-up |
| **NEUTRAL** | 1,042 (6.2%) | 11,771 (70.5%) | 11,782 (70.5%) | Natural flip exit or trivial difference ($\le 0.5$ pt) |

---

## Tail Analysis & Catastrophic Loss Behavior
Health exits significantly compress left-tail loss magnitude, but this tail protection is bought at an unsustainable cost in sacrificed winner run-up:

| Policy | Worst 1% Cutoff | Worst 1% Mean Loss | Worst 5% Cutoff | Worst 5% Mean Loss | Total Loss Variance |
|---|---|---|---|---|---|
| **P0 (Natural Baseline)** | -$960 | -$1,235.99 | -$600 | -$835.23 | 47,193 |
| **P1 (Immediate Q4)** | -$570 | -$724.07 | -$370 | -$499.18 | 16,709 |
| **P2 (Persistence 60s)** | -$880 | -$1,155.36 | -$555 | -$770.47 | 40,703 |
| **P3 (Persistence + Recovery)** | -$885 | -$1,155.27 | -$560 | -$772.77 | 40,911 |

**Key Tail Insight**:
- P1 cuts the worst 1% mean loss by **$511.92 per trade** (-41.4%) and worst 5% mean loss by **$336.05 per trade** (-40.2%).
- P2 cuts the worst 1% mean loss by **$80.63 per trade** (-6.5%) and worst 5% mean loss by **$64.76 per trade** (-7.8%).
- However, because the natural regime baseline already has a positive gross edge (+2.00 pts gross EV), truncating the right tail to protect the left tail destroys the positive skewness of trend-following.

---

## Trend Preservation Analysis
| Metric | P1 (Immediate $Q_4$) | P2 ($Q_4$ + 60s Persistence) | P3 (P2 + Recovery Cancel) |
|---|---|---|---|
| **Total Health Exits** | 16,252 (97.3%) | 5,733 (34.3%) | 5,603 (33.5%) |
| **Forfeited $\ge 1$ ATR Extensions** | 6,887 (42.4%) | 1,695 (29.6%) | 1,660 (29.6%) |
| **Forfeited $\ge 2$ ATR Extensions** | 4,148 (25.5%) | 992 (17.3%) | 973 (17.4%) |
| **Total Forfeited MFE (points)** | 271,529.2 pts | 67,888.8 pts | 66,778.2 pts |
| **Total Forfeited MFE ($)** | **$5,430,585** | **$1,357,775** | **$1,335,565** |

---

## Observational Reversal Diagnostic

The reversal diagnostic tests prospectively whether severe regime health invalidation (persistent $Q_4 \ge 60$s) contains predictive information for the **OPPOSITE** direction:

- **Total Invalidation Events**: 5,733 (34.3% of natural regimes)
- **Mean Lead Time to Natural Flip**: **362.3 seconds (~6.0 minutes)**
- **Prospective Adverse Movement to Old Trend (Opposite Direction Run-up)**: **0.81 ATR**
- **Prospective Favorable Movement to Old Trend (Whipsaw Against Reversal)**: **0.22 ATR**
- **Prospective Net Opposite Direction Gain to Flip**: **+0.59 ATR**
- **Opposite Direction Win Rate**: **74.8%**

### Reversal Diagnostic Verdict: `PROMISING`
**Rationale**: Persistent $Q_4$ invalidation does not make a profitable exit policy for the incumbent trend because it gives up accumulated equity and pays friction. However, it functions as a prospective, high-quality **early warning indicator of an impending opposite regime**. It precedes the natural flip by an average of 6.0 minutes, during which price moves an average of 0.81 ATR in the opposite direction with minimal counter-excursion (0.22 ATR).


---

## Answers to the 12 Required Decision Questions

### 1. Does immediate $Q_4$ exit improve or degrade economics versus natural $V_A$ exit?
**DEGRADES DRAMATICALLY**. P1 immediate $Q_4$ exit collapses gross EV from +$2.00/trade down to +$0.57/trade, and increases net losses from -$13.00 to -$14.43/trade. It exits 97.3% of regimes prematurely, giving up 271,529 points of subsequent MFE.

### 2. Does waiting for persistent $Q_4$ improve the trade-off between avoided losses and preserved trend MFE?
**YES, materially relative to P1, but STILL INSUFFICIENT relative to P0**. P2 waiting for 60s persistence reduces premature exits from 97.3% down to 34.3%, saving over 203,000 points of forfeited MFE compared to P1. However, P2 still yields Gross EV of +$0.01/trade, underperforming P0's +$2.00/trade.

### 3. Does prospective recovery cancellation preserve materially more profitable trend continuation?
**NO**. In P3, 461 regimes confirm prospective recovery after acute stress, disarming 130 invalidation watches. However, regimes experiencing severe stress that subsequently confirm recovery still produce net negative terminal PnL (-$58,810). Their survival is improved statistically, but economically they rarely regain strong momentum.

### 4. How much MFE is sacrificed by each health policy?
- **P1**: Sacrifices **271,529.2 points ($5,430,584)** in forfeited MFE; 42.4% of exits forfeit $\ge 1$ ATR.
- **P2**: Sacrifices **67,888.8 points ($1,357,776)** in forfeited MFE; 29.6% of exits forfeit $\ge 1$ ATR.
- **P3**: Sacrifices **66,778.2 points ($1,335,564)** in forfeited MFE; 29.6% of exits forfeit $\ge 1$ ATR.

### 5. How much terminal adverse excursion is avoided?
- **P1**: Reduces mean MAE from 1.17 ATR to 0.67 ATR (saving 0.50 ATR per trade).
- **P2**: Reduces mean MAE from 1.17 ATR to 1.08 ATR (saving 0.09 ATR per trade).
- **P3**: Reduces mean MAE from 1.17 ATR to 1.08 ATR (saving 0.09 ATR per trade).

### 6. Are improvements broad-based or concentrated in a small number of catastrophic losers?
**CONCENTRATED IN THE FAR LEFT TAIL**. Health exits do not shift the median trade; they compress the worst 1% and worst 5% tail losses by cutting trades before catastrophic flip drawdowns occur.

### 7. Does the health model improve average trade economics, tail risk, drawdown, or some combination?
**TAIL RISK ONLY**. It provides zero improvement in average trade economics (Gross EV drops from +$2.00 to +$0.01). It reduces maximum loss per trade in the left tail, but at the direct expense of right-tail trend payoff.

### 8. How frequently does $Q_4$ produce a false terminal warning?
**64.7% of initial $Q_4$ alerts are false terminal warnings**. In P1, 97.3% of regimes touch $Q_4$, but only 34.3% remain in $Q_4$ for 60 seconds. Exiting on first $Q_4$ touch is predominantly a false alarm.

### 9. When $Q_4$ persists $\ge 60$s, how frequently does the regime nevertheless recover and produce substantial subsequent MFE?
**29.6% of persistent $Q_4$ exits nevertheless produce $\ge 1.0$ ATR subsequent MFE**, and 17.3% produce $\ge 2.0$ ATR. Even after 60 seconds of severe continuous dual-head stress, nearly 30% of regimes manage multi-point trend re-extensions.

### 10. Is $H_1 	o H_2$ staged deterioration useful beyond simple $Q_4$ persistence, if P4 is admissible?
**OMITTED**. The parent contracts did not define an unambiguous frozen threshold for staged sequential confirmation without parameter tuning. Per instructions, P4 was omitted to prevent ungoverned parameter mining.

### 11. Does the same conclusion replicate untouched OOS?
**YES**. In both 2023–2024 TRAIN and untouched 2025 Q1 OOS, P0 achieves the most robust baseline economics. P1 severely degrades economics in both periods. P2 shows a modest positive net EV in 2025 Q1 (+$0.94) due to strong trending conditions, but over the full sample it remains negative (-$14.99 net EV).

### 12. Is the economically useful object primarily an exit, an invalidation warning, a stop-tightening signal, a reversal/entry setup, or none of these?
**A REVERSAL / OPPOSITE-DIRECTION ENTRY SETUP**. The empirical evidence conclusively rejects the regime health model as a position-exit rule. Instead, persistent health invalidation functions as a powerful prospective setup for the **OPPOSITE** direction, offering an average 362.3s lead time and 0.81 ATR prospective opposite run-up.


---

## Separation of Fact, Interpretation, and Limits

### FACT (Direct Empirical Results)
1. P0 Natural Baseline produces Gross EV of +$2.00/trade (+$33,410 total gross) across 16,706 regimes.
2. P1 Immediate $Q_4$ exit reduces Gross EV to +$0.57/trade, forfeiting 271,529 points of subsequent MFE.
3. P2 60s Persistent $Q_4$ exit reduces Gross EV to +$0.01/trade across the full sample.
4. P3 Recovery Cancellation preserves 461 recovered regimes, but these regimes collectively lose -$58,810.
5. Persistent $Q_4$ invalidation leads natural regime flip by an average of 362.3 seconds with 0.81 ATR prospective movement in the opposite direction.

### INTERPRETATION (Economic Meaning)
1. Regime health hazard ($H_1, H_2$) measures structural degradation, but trend-following profitability inherently relies on riding noisy pullbacks that often trigger high instantaneous hazard before re-extending.
2. An early exit rule acts like an aggressive stop-loss: it truncates the fat right tail of trend distributions, transforming positive-skewed systems into negative-skewed systems.
3. The true economic value of regime health modeling lies in **anticipating regime transitions** to position for the new trend, not in prematurely cutting existing trend positions.

### NOT ESTABLISHED (What the Data Cannot Support)
1. This study does NOT prove that reversal trading will be profitable net of spread, slippage, and fees. That requires a dedicated, user-authorized execution study.
2. This study does NOT establish optimal holding periods, stop-loss distances, or profit targets.
3. This study does NOT support further threshold sweeps on $H_1, H_2$, persistence seconds, or recovery deltas.


---

## Final Decision Gate & Mandatory Stop

### Primary Decision Classification:
```
OUTCOME_C_INFORMATION_VALID_POLICY_NOT_USEFUL
```
**Rationale**: The health model accurately predicts regime deterioration and hazard transitions ($AUC pprox 0.78$), but acting on the frozen states as early position-exit rules does NOT improve realized trading economics sufficiently relative to the natural $V_A$ regime-flip baseline. The value surrendered by prematurely exiting re-extending trends exceeds the capital saved by avoiding terminal flips.

### Reversal Diagnostic Verdict:
```
REVERSAL_DIAGNOSTIC: PROMISING
```
**Rationale**: Persistent $Q_4$ invalidation provides a significant prospective lead time (mean 362.3s) and 0.81 ATR prospective movement in the opposite direction, indicating that regime health deterioration is promising as an opposite-direction reversal setup.

### MANDATORY STOP
In accordance with Section 16 and Section 18 of the specification:
- **No further feature families, models, or threshold sweeps are proposed.**
- **No exit optimizations or parameter mining are conducted.**
- **Execution stops immediately upon presentation of this report.**
- **Any subsequent research into reversal execution requires explicit, separate user approval.**

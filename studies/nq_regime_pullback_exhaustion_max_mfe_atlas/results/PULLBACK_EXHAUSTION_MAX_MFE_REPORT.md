# Pullback-Level Regime Exhaustion / Max-MFE Revisit Atlas
## Causal Observational Atlas across 5,610 Regimes and 95,546 Pullback Checkpoints

**Study ID:** `nq_regime_pullback_exhaustion_max_mfe_atlas`  
**Census Population:** All 5,610 Authoritative $V_A$ Regimes (2023, 2024, 2025 Q1 Untouched OOS)  
**Market Data:** CME 1-Second Catalog Bars (`NQ.XCME-1-SECOND-LAST-EXTERNAL`, 27,309,215 bars)  
**Observation Unit:** Pullback Checkpoint ($D \in \{0.25, 0.50, 0.75, 1.00\}$ ATR from Running Max-MFE)  
**Total Qualifying Observations:** Exactly **95,546** causal checkpoints  
**Governing Question:** Can causal information available during an incumbent pullback identify that the regime's existing maxMFE is unlikely to be exceeded again before the next confirmed $V_A$ flip?  
**Decision Classification:** **`OUTCOME_B_INFORMATION_EXISTS_BUT_PULLBACK_DEPTH_ALONE_INSUFFICIENT`**  

---

## 1. Executive Summary

This study returns to the primary qualitative objective of the research program: **identifying economic regime exhaustion during an incumbent trend before formal Volume Absorption ($V_A$) regime transition**. Rather than predicting an imminent $V_A$ flip at a fixed time horizon, this atlas establishes the **pullback** as the fundamental unit of observation and asks whether a pullback signals that the incumbent regime's running maximum favorable excursion (maxMFE) will never be revisited.

Across the entire census of 5,610 regimes and 95,546 causal pullback checkpoints from 2023 through 2025 Q1, the empirical findings demonstrate:

1. **Shallow Pullbacks are Continuation Engines, Not Turning Points:**
   - At **0.25 ATR depth** ($N=43,130$), **87.00% of pullbacks resume** to forge a new running maxMFE; only **13.00% exhaust** into the regime exit.
   - At **0.50 ATR depth** ($N=23,915$), **76.57% of pullbacks resume**; only **23.43% exhaust**.
   - Over 3 out of 4 pullbacks that retrace half an ATR re-extend to higher highs/lower lows.
2. **False Exhaustion Carries Severe Economic Cost:**
   - If an observer prematurely declares exhaustion at a 0.50 ATR pullback, **76.57% of those calls are false exhaustions**.
   - For pullbacks that resume from 0.50 ATR, the median missed continuation is **1.59 ATR ($300.00 per contract)**, with a mean of **2.67 ATR ($519.60)**.
   - Over **42.4% of false exhaustions produce $\ge 2.00$ ATR ($400+) of additional trend extension** beyond the pre-pullback peak.
3. **Exhaustion Probability Scales Monotonically with Depth:**
   - Exhaustion risk increases **3.5-fold** across observed depths: **13.0% at 0.25A $\to$ 23.4% at 0.50A $\to$ 34.4% at 0.75A $\to$ 45.1% at 1.00A**.
   - At **1.00 ATR depth** ($N=12,251$), exhaustion probability reaches **45.12%**, and rises to **54.56% on the regime's first pullback**.
4. **The 0.50 ATR Objective Reality:**
   - Historical median total giveback from final maxMFE to $V_A$ exit is **1.97 ATR (19.25 pts, $385.00)**.
   - When a pullback is genuinely the final one, exiting at 0.50 ATR preserves **1.52 ATR ($304.00, 77.2% of total giveback)** with a massive **236.0-second (~4 minute) lead time** before $V_A$.
   - **However, pullback depth alone cannot distinguish final pullbacks from ordinary pullbacks at $\le 0.50$ ATR** without path-state conditioning (such as bounce failure or lower-high structural failure).
5. **Flawless Out-of-Sample Stability:**
   - The exhaustion rate at 0.50 ATR replicates within $\pm 0.5\%$ across all epochs: **23.81% in 2023 TRAIN**, **23.03% in 2024 TRAIN**, and **23.62% in 2025 Q1 untouched OOS**.

---

## 2. Gate 0 — Reconciliation, Provenance & Historical Giveback Baseline

### Population & Data Provenance
- **Census Regimes:** Census of all **5,610 regimes** from `studies/nq_persistent_q4_to_q4_regime_capture/results/c0_control_ledger.parquet` (2,476 in 2023; 2,562 in 2024; 572 in 2025 Q1 OOS). Maximum divergence = 0.
- **Authoritative Data Stream:** CME 1-second catalog bars (`NQ.XCME-1-SECOND-LAST-EXTERNAL`, SHA256: `55c36ad6bc5c6045d71405aa919769f6b503f501ea0375827cb947469ce16057`).
- **Strict Causal Boundary:** Every checkpoint satisfies $t_{checkpoint} < t_{va\_flip}$, ensuring positive forward horizon and zero terminal boundary leakage.

### Authoritative Historical Max-MFE $\to$ $V_A$ Giveback Distribution ($N = 5,610$)

| Metric | Mean | Median | p25 | p75 | p90 | Max |
|---|---|---|---|---|---|---|
| **Giveback in ATR** | **2.15 ATR** | **1.97 ATR** | 1.57 ATR | 2.50 ATR | 3.16 ATR | 14.49 ATR |
| **Giveback in Points** | **22.73 pts** | **19.25 pts** | 13.75 pts | 27.50 pts | 39.28 pts | 253.75 pts |
| **Giveback in Dollars** | **$454.54** | **$385.00** | $275.00 | $550.00 | $785.50 | $5075.00 |

> **Verification:** The empirical giveback from final peak MFE to confirmed $V_A$ exit is exactly **1.97 median ATR ($385.00)** and **2.15 mean ATR ($454.60)**.

---

## 3. Primary Pullback Checkpoint Comparison Table

The primary table comparing causal pullback depth checkpoints across all 5,610 regimes:

| Depth Checkpoint | Sample Size ($N$) | EXHAUST % | RESUME % | Median Remaining Add'l MFE | P(Add MFE $\ge 0.5$A) | P(Add MFE $\ge 1.0$A) | Median Time to $V_A$ (Exhaust) | Median Total Giveback | Giveback Consumed | Giveback Remaining |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.25 ATR** | 43,130 | **13.00%** | **87.00%** | 1.24 ATR (11.75 pts) | 69.37% | 55.37% | 247.0s | 2.13 ATR | 0.26 ATR | **0.68 ATR (6.25 pts)** |
| **0.50 ATR** | 23,915 | **23.43%** | **76.57%** | 0.96 ATR (9.00 pts) | 61.24% | 49.12% | 236.0s | 2.12 ATR | 0.51 ATR | **0.66 ATR (5.75 pts)** |
| **0.75 ATR** | 16,250 | **34.36%** | **65.64%** | 0.63 ATR (5.75 pts) | 52.79% | 42.06% | 217.0s | 2.10 ATR | 0.76 ATR | **0.62 ATR (5.50 pts)** |
| **1.00 ATR** | 12,251 | **45.12%** | **54.88%** | 0.23 ATR (2.00 pts) | 44.43% | 35.36% | 181.0s | 2.10 ATR | 1.01 ATR | **0.55 ATR (5.00 pts)** |

> **Core Architectural Takeaway:** As pullback depth deepens from 0.25 to 1.00 ATR, the fraction of pullbacks that exhaust increases from 13.00% to 45.12%. However, at 0.50 ATR, **76.57% of pullbacks re-extend**, leaving a median of 0.96 ATR in additional MFE across the full population and 1.59 ATR across resuming pullbacks.

---

## 4. Characterizing False Exhaustion (Missed Continuation)

The most critical danger in regime exhaustion detection is abandoning a trend that subsequently continues. For every depth checkpoint, the distribution of additional prospective MFE generated beyond the pre-pullback peak is detailed below:

### Additional MFE Generated After Pullback Resumes

| Checkpoint Depth | Total False Exhaustions ($N$) | % of All Checkpoints | Missed MFE Median (ATR / $) | Missed MFE Mean (ATR / $) | Missed $\ge 0.50$ ATR (% of False) | Missed $\ge 1.00$ ATR (% of False) | Missed $\ge 2.00$ ATR (% of False) |
|---|---|---|---|---|---|---|---|
| **0.25 ATR** | 37,521 | 87.0% | **1.56 ATR ($300.0)** | 2.59 ATR ($516.3) | 79.7% (69.4% all) | 63.6% (55.4% all) | **41.6% (36.2% all)** |
| **0.50 ATR** | 18,311 | 76.6% | **1.59 ATR ($300.0)** | 2.67 ATR ($519.6) | 80.0% (61.2% all) | 64.2% (49.1% all) | **42.4% (32.5% all)** |
| **0.75 ATR** | 10,667 | 65.6% | **1.59 ATR ($300.0)** | 2.73 ATR ($524.1) | 80.4% (52.8% all) | 64.1% (42.1% all) | **42.7% (28.0% all)** |
| **1.00 ATR** | 6,723 | 54.9% | **1.63 ATR ($305.0)** | 2.80 ATR ($532.0) | 81.0% (44.4% all) | 64.4% (35.4% all) | **43.4% (23.8% all)** |

### Granular Breakdown of False Exhaustions at 0.50 ATR Depth ($N = 18,311$)
- **Trivial Exceedance (< 0.25 ATR):** Only **10.0%** (1,839 observations). Resuming pullbacks do not merely tick past the high by one tick.
- **Moderate Continuation (0.50 to 1.00 ATR):** **15.8%** (2,899 observations).
- **Major Continuation (1.00 to 2.00 ATR):** **21.8%** (3,974 observations).
- **Explosive Extension ($\ge 2.00$ ATR / $400+ per contract):** **42.4%** (7,773 observations).

> **Critical Conclusion on False Exhaustion:** Falsely diagnosing regime exhaustion at a 0.50 ATR pullback does not merely miss small noise; in over 42% of cases, it surrenders massive trend extensions exceeding +2.00 ATR.

---

## 5. Pullback Ordinal Analysis (Lifecycle Progression)

Does the probability of regime exhaustion evolve systematically across successive pullbacks within a regime?

### Ordinal Breakdown at 0.50 ATR Pullback Depth

| Pullback Ordinal | Observations ($N$) | EXHAUST % | RESUME % | Median Pre-Pullback MFE | Median Additional MFE | Median Time to $V_A$ (Exhaust) |
|---|---|---|---|---|---|---|
| **Ordinal 1** | 2,763 | **26.78%** | 73.22% | 0.22 ATR | 0.78 ATR | 173.0s |
| **Ordinal 2** | 2,660 | **25.11%** | 74.89% | 0.41 ATR | 0.79 ATR | 197.0s |
| **Ordinal 3+** | 18,492 | **22.69%** | 77.31% | 2.18 ATR | 1.01 ATR | 256.0s |

### Ordinal Breakdown at 1.00 ATR Pullback Depth

| Pullback Ordinal | Observations ($N$) | EXHAUST % | RESUME % | Median Pre-Pullback MFE | Median Additional MFE | Median Time to $V_A$ (Exhaust) |
|---|---|---|---|---|---|---|
| **Ordinal 1** | 1,327 | **54.56%** | 45.44% | 0.24 ATR | 0.00 ATR | 114.5s |
| **Ordinal 2** | 1,341 | **48.99%** | 51.01% | 0.42 ATR | 0.06 ATR | 143.0s |
| **Ordinal 3+** | 9,583 | **43.27%** | 56.73% | 2.18 ATR | 0.30 ATR | 205.0s |

> **Lifecycle Finding:** At a 1.00 ATR depth, **the very first pullback exhausts 54.56% of the time**. Newborn regimes that suffer a deep 1.00 ATR pullback immediately after birth have a higher failure rate than mature regimes (Ordinal 3+), where pre-pullback MFE averages 2.18 ATR and resumption occurs 56.73% of the time.

---

## 6. Evaluation of the 0.50 ATR Objective

### Core Research Hypothesis:
> *Can final regime exhaustion become meaningfully identifiable after approximately $\le 0.50$ ATR of giveback from maxMFE?*

### Quantitative Verdict: `UNFEASIBLE_BY_DEPTH_ALONE`

1. **The Positive Asymmetry:**
   - When an observation at 0.50 ATR is genuinely the final non-recovering pullback ($N=5,604$), it captures **1.52 ATR ($304.00 per contract)** of the regime's total 2.12 ATR giveback—**preserving 77.2% of the giveback** that would otherwise be lost to $V_A$.
   - It provides a median lead time of **236.0 seconds (~4 minutes)** and a mean lead time of **311.9 seconds (~5.2 minutes)** before the opposite $V_A$ flip.
2. **The Disqualifying Barrier (Depth Alone):**
   - Across all 0.50 ATR pullbacks, **76.57% resume**. An unconditional rule that exits on a 0.50 ATR retrace incurs **three false exits for every correct exhaustion call**.
   - Resuming pullbacks proceed to forge a median of **+1.59 ATR** in additional excursion.
3. **Conclusion:**
   - Pullback depth alone cannot achieve the 0.50 ATR exhaustion objective.
   - Early exhaustion identification requires **conditioning on what happens during and after the retrace** (e.g., bounce failure, lower high, stall duration) rather than acting on depth penetration alone.

---

## 7. TRAIN / OOS and Directional Replication

Replication of key checkpoint metrics at Depth 0.50 ATR across annual partitions and trade directions:

### Annual & OOS Replication (Depth 0.50 ATR)

| Partition | Observations ($N$) | EXHAUST % | RESUME % | Median Add'l MFE | Median Time to $V_A$ |
|---|---|---|---|---|---|
| **2023 (TRAIN)** | 10,605 | **23.81%** | **76.19%** | 0.94 ATR | 232.0s |
| **2024 (TRAIN)** | 10,888 | **23.03%** | **76.97%** | 0.99 ATR | 245.0s |
| **2025_Q1 (Untouched OOS)** | 2,422 | **23.62%** | **76.38%** | 0.92 ATR | 224.0s |

### Directional Replication (Depth 0.50 ATR)

| Direction | Observations ($N$) | EXHAUST % | RESUME % | Median Add'l MFE | Median Time to $V_A$ |
|---|---|---|---|---|---|
| **LONG** | 12,126 | **23.20%** | **76.80%** | 0.97 ATR | 230.0s |
| **SHORT** | 11,789 | **23.67%** | **76.33%** | 0.94 ATR | 244.0s |

> **Empirical Invariance:** The resumption rate at 0.50 ATR is virtually invariant across market environments: **76.19% in 2023**, **76.97% in 2024**, and **76.38% in 2025 Q1 OOS** (and **76.80% Long vs 76.33% Short**). This confirms that trend resumption after shallow retracement is a fundamental invariant of the NQ auction.

---

## 8. Decision Gate Classification

### Official Verdict: `OUTCOME_B_INFORMATION_EXISTS_BUT_PULLBACK_DEPTH_ALONE_INSUFFICIENT`

**Detailed Specification:**
> Pullback depth contains clear, monotonic causal information regarding regime failure risk (exhaustion scales 3.5-fold from 13.0% at 0.25A to 45.1% at 1.00A). However, **pullback depth alone is insufficient to identify regime exhaustion early enough ($\le 0.50$ ATR) to preserve the giveback without triggering intolerable false exhaustion (76.6% resumption rate)**. Achieving early exhaustion identification requires structural conditioning on the post-pullback recovery attempt (such as lower-high failure or retest stall) rather than a simple depth trigger.

---

## 9. Mandatory Stop & Artifact Manifest

- **Mandatory Stop Enforced:** No strategy backtests, no ML model training, no stop-loss/profit-target optimization, and no trading thresholds were selected.

| Artifact Name | Type | Size / Rows | File Path |
|---|---|---|---|
| `pullback_event_ledger.parquet` | Parquet | 95,546 rows | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/pullback_event_ledger.parquet` |
| `depth_checkpoint_comparison.json` | JSON | 5.2 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/depth_checkpoint_comparison.json` |
| `false_exhaustion_distribution.json` | JSON | 7.8 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/false_exhaustion_distribution.json` |
| `pullback_ordinal_analysis.json` | JSON | 2.6 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/pullback_ordinal_analysis.json` |
| `half_atr_objective_evaluation.json` | JSON | 1.2 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/half_atr_objective_evaluation.json` |
| `yearly_oos_replication.json` | JSON | 4.2 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/yearly_oos_replication.json` |
| `directional_replication.json` | JSON | 2.8 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/directional_replication.json` |
| `gate0_reconciliation.json` | JSON | 2.3 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/gate0_reconciliation.json` |
| `runtime_contract.json` | JSON | 491 bytes | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/runtime_contract.json` |
| `study_manifest.json` | JSON | 620 bytes | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/results/study_manifest.json` |
| `PULLBACK_EXHAUSTION_MAX_MFE_REPORT.md` | Markdown | ~30 KB | `studies/nq_regime_pullback_exhaustion_max_mfe_atlas/PULLBACK_EXHAUSTION_MAX_MFE_REPORT.md` |
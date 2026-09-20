# P0_F30 Forensic Reconciliation Audit Report
**Lineage:** NQ H050 Counter-Regime Delayed-Entry Research  
**Target Policy:** $P0\_F30$ (H050 Entry + 30-Second Fast-Failure Exit Overlay)  
**Baseline Control:** $P0\_F0$ (H050 Entry + Canonical C1 Opposing-H050 Exit)  
**Author:** Antigravity (Governed Autonomous Quantitative Agent)  
**Evaluation Cohort:** 2023 TRAIN ($N=10,605$), 2024 Validation ($N=10,888$), 2025 Q1 Diagnostic ($N=2,422$), Pooled ($N=23,915$)  
**Audit Status:** **COMPLETED**  
**Root-Cause Verdict:** `F30_CAUSALITY_LEAKAGE` (Primary)  
**Promotion Verdict:** `P0_F30_PROMOTION_STATUS = BLOCKED_PENDING_FIX`

---

## 1. Executive Summary & The Core Discovery

This forensic reconciliation audit resolves the material discrepancy between the prior observational fast-failure study (`studies/nq_h050_delayed_entry_fast_failure`) and the executable policy study (`studies/nq_h050_delayed_entry_policy`).

### The Discrepancy Under Audit:
* **Prior Observational Study (+30s):**
  * Catastrophic AUC $\approx 0.6063$
  * Top 10% Risk Catastrophic Capture $\approx 18.34\%$
  * +2A Winner Collateral $\approx 11.55\%$
  * Net Loss Avoided on Flagged Trades $\approx +0.6072\text{ ATR}$
* **Executable Policy Study ($P0\_F30$ as reported):**
  * Catastrophic AUC $\approx 0.9279$
  * Catastrophic Capture $\approx 67.51\%$
  * +2A Winner Collateral $\approx 2.51\%$
  * Net Loss Avoided on Flagged Trades $\approx +5.9478\text{ ATR}$
  * Aggregate Policy Improvement $\approx +0.6577\text{ ATR/trade}$
  * Catastrophic Rate dropped from $14.00\%$ ($F0$) to $5.23\%$ ($F30$)

### The Decisive Forensic Finding:
The massive apparent performance jump of $P0\_F30$ is **NOT** a real market anomaly, nor is it driven by sample selection or denominator confusion. It is caused by **direct future lookahead feature leakage** in `scripts/run_delayed_entry_policy_study.py`.

Specifically:
1. In lines 177–183 of `run_delayed_entry_policy_study.py`, the variable `cur_peak` was updated inside a loop scanning from $t_{H050}$ to `idx_reg_end` (the terminal end of the multi-hour incumbent regime).
2. Consequently, by the time the loop finished, `cur_peak` held the **absolute extreme price of the entire regime** (hours or days into the future).
3. In lines 367–375, the +30s fast-failure feature `magnitude_new_incumbent_extreme_post_entry` was computed using this terminal `cur_peak`:
   $$\text{ext\_mag} = \frac{\max(0.0, \text{cur\_peak} - \min(\text{ff\_lows}))}{\text{frozen\_atr}}$$
4. For a short counter-regime trade, `cur_peak - min(ff_lows)` was literally measuring **how far the future runaway trend would advance against the trade**!
5. This leaked the exact severity of the future continuation into the 30-second decision. LightGBM assigned this single feature **486 split decisions** (over 30% of the entire model).
6. When this lookahead leakage is eliminated and features are evaluated **strictly causally up to $t_{\text{fill}} + 30\text{s}$**, the model's true performance on the identical $P0$ rows returns to:
   * **Catastrophic AUC:** $\mathbf{0.5910}$ (reconciling with prior $\mathbf{0.6063}$)
   * **Catastrophic Capture:** $\mathbf{17.80\%}$ (reconciling with prior $\mathbf{18.34\%}$)
   * **+2A Winner Collateral:** $\mathbf{11.40\%}$ (reconciling with prior $\mathbf{11.55\%}$)
   * **Mean Loss Avoided on Flagged Trades:** $\mathbf{+0.4137\text{ ATR}}$ (reconciling with prior $\mathbf{+0.6072\text{ ATR}}$)
   * **True Causal Policy Improvement:** $\approx \mathbf{+0.0422\text{ ATR/trade}}$ (rather than $+0.6577\text{ ATR/trade}$).

Because this represents an unmitigated violation of Causal Rules A1–A4 and Feature System Contract V2, $P0\_F30$ is **BLOCKED** from production promotion until the feature calculation is fixed and the policy ledger is regenerated.

---

## 2. Master Reconciliation Table

Every metric from the earlier observational study, the reported policy study, and the recomputed causal replication is presented below:

| Metric | Prior Observational F30 | Original Policy Report P0_F30 | Recomputed Causal P0_F30 | Reconciliation Explanation |
| :--- | :---: | :---: | :---: | :--- |
| **Catastrophic Loss AUC** | $0.6063$ | $0.9279$ | $\mathbf{0.5910}$ | Leakage of future `cur_peak` inflated AUC to 0.9279. Causal evaluation achieves 0.5910, matching prior study. |
| **Top 10% Catastrophic Capture** | $18.34\%$ | $67.51\%$ | $\mathbf{17.80\%}$ | Leaked future trend peak allowed model to identify 67.5% of catastrophic losers. True causal capture is 17.80%. |
| **+2A Winner Collateral Rate** | $11.55\%$ | $2.51\%$ | $\mathbf{11.40\%}$ | Future trend knowledge artificially suppressed collateral damage to 2.51%. True causal collateral is 11.40%. |
| **Mean Loss Avoided / Flagged Trade** | $+0.6072\text{ ATR}$ | $+5.9478\text{ ATR}$ | $\mathbf{+0.4137\text{ ATR}}$ | Leaked model selected runaway losers (mean C1 loss $-6.21\text{A}$). True causal loss avoided is $+0.4137\text{ ATR}$. |
| **Realized Flag Rate** | $10.00\%$ | $11.49\%$ | $\mathbf{10.20\%}$ | Both calibrated to 90th percentile threshold on 2023 TRAIN; stable near 10–11% across all cohorts. |
| **F0 Baseline Catastrophic Rate** | $14.03\%$ | $14.00\%$ | $\mathbf{14.00\%}$ | Exact census agreement on H050 counter-regime baseline across all artifacts. |
| **F30 Realized Catastrophic Rate** | *N/A (Obs)* | $5.23\%$ | $\mathbf{11.50\%}$ | Reported drop to 5.23% was artifact of leakage. True causal reduction is $\approx 2.5\text{ pp}$ ($14.00\% \to 11.50\%$). |
| **Aggregate Expectancy Delta** | *N/A (Obs)* | $+0.6577\text{ ATR}$ | $\mathbf{+0.0422\text{ ATR}}$ | True causal policy expectancy improvement is $\approx +0.042\text{ ATR/trade}$ ($10.2\% \times +0.414\text{A}$), not $+0.658\text{A}$. |
| **Flagged Held-to-C1 Mean PnL** | $-1.4206\text{ ATR}$ | $-6.2137\text{ ATR}$ | $\mathbf{-1.1666\text{ ATR}}$ | Leakage cherry-picked extreme runaway losers. Causally flagged trades average $-1.17\text{ ATR}$ at C1. |
| **Flagged Immediate Exit Mean PnL** | $-0.8134\text{ ATR}$ | $-0.2659\text{ ATR}$ | $\mathbf{-0.7528\text{ ATR}}$ | Under causal execution, exiting at +30s locks in an immediate mark of $-0.75\text{ ATR}$ (vs $-0.81\text{ ATR}$ obs). |

---

## 3. Mathematical & Accounting Proofs

### A. Primary Expectancy Accounting Identity (Section 8 & 9)
For every cohort, the aggregate policy expectancy satisfies:
$$\mathbb{E}[\text{PnL}_{F30}] = \mathbb{E}[\text{PnL}_{F0}] + \text{flag\_rate} \times \mathbb{E}[\Delta\text{PnL} \mid \text{flagged}]$$

* **Pooled TRAIN (2023–2024, $N=21,493$):**
  * $\mathbb{E}[\text{PnL}_{F0}] = -0.167098\text{ ATR}$
  * $\mathbb{E}[\text{PnL}_{F30}] = +0.490587\text{ ATR}$
  * $\Delta\text{PnL} = \mathbf{+0.657685\text{ ATR}}$
  * Realized Flag Rate $= 2,469 / 21,493 = \mathbf{0.114875}$ ($11.49\%$)
  * Direct Flagged Trades Mean Delta $= \mathbf{+5.725559\text{ ATR}}$
  * Right Hand Side: $-0.167098 + 0.114875 \times 5.725559 = \mathbf{+0.490587\text{ ATR}}$
  * Absolute Discrepancy $= \mathbf{0.000000000000}$ ($< 10^{-15}$)
  * Sum Totals: $\sum\text{PnL}_{F30} = +10,544.18\text{ ATR} = \sum\text{PnL}_{F0} (-3,591.43) + \sum\Delta_{\text{flagged}} (+14,135.61)$
  * **Verdict:** `F30_EXPECTANCY_ACCOUNTING_PASS`

### B. Catastrophic-Rate Accounting Identity (Section 10)
$$\text{CatRate}_{F30} = \text{CatRate}_{F0} - \text{RescuedRate} + \text{NewCatRate}$$
* **Pooled TRAIN ($N=21,493$):**
  * Original $F0$ Catastrophics: $3,009$ ($14.0000\%$)
  * Flagged Original Catastrophics: $1,916$
  * Rescued by $F30$ (held $\le -3\text{A}$ under $F0$, but exited $> -3\text{A}$ under $F30$): **$1,885$ trades** ($8.7703\text{ pp}$)
  * Flagged but still catastrophic (exited $\le -3\text{A}$ at $+30$s): $31$ trades
  * Newly created catastrophics ($>-3\text{A}$ at C1, but $\le -3\text{A}$ at $+30$s): **$0$ trades** ($0.0000\text{ pp}$)
  * Final $F30$ Catastrophics: $3,009 - 1,885 + 0 = \mathbf{1,124\text{ trades}}$ ($\mathbf{5.2296\%}$)
  * Identity Check: $14.0000\% - 8.7703\% + 0.0000\% = \mathbf{5.2297\%}$ (Difference: $< 10^{-14}$)
  * **Verdict:** `F30_CATASTROPHIC_ACCOUNTING_PASS`

---

## 4. Root-Cause Localization: The Lookahead Bug

### The Source Code Defect
In `scripts/run_delayed_entry_policy_study.py`:
```python
# Lines 160-161: Initialize peak at T0
cur_peak = regime_entry_px + direction * pre_pb_mfe_pts

# Lines 176-190: Depth scanning loop to regime end
for b_i in range(idx_t0, idx_reg_end):  # idx_reg_end is the FUTURE end of the regime!
    if direction == 1:
        cur_peak = max(cur_peak, highs_1s[b_i])
        pb_pts = max(0.0, cur_peak - lows_1s[b_i])
    else:
        cur_peak = min(cur_peak, lows_1s[b_i])
        pb_pts = max(0.0, highs_1s[b_i] - cur_peak)
```
After this loop, `cur_peak` is no longer the peak at $t_{H050}$; it has been overwritten by the **global maximum/minimum of the entire multi-hour regime**.

Then, at line 364:
```python
# Lines 364-375: Evaluating fast-failure at +30s
if counter_direction == 1:
    adv_pts = max(0.0, fill_px - np.min(ff_lows)) if len(ff_lows) > 0 else 0.0
    fav_pts = max(0.0, np.max(ff_highs) - fill_px) if len(ff_highs) > 0 else 0.0
    new_ext = 1 if (np.max(ff_highs) > cur_peak) else 0
    ext_mag = max(0.0, np.max(ff_highs) - cur_peak) / max(frozen_atr, 1e-4)
else:
    adv_pts = max(0.0, np.max(ff_highs) - fill_px) if len(ff_highs) > 0 else 0.0
    fav_pts = max(0.0, fill_px - np.min(ff_lows)) if len(ff_lows) > 0 else 0.0
    new_ext = 1 if (np.min(ff_lows) < cur_peak) else 0
    ext_mag = max(0.0, cur_peak - np.min(ff_lows)) / max(frozen_atr, 1e-4)
```

### The Exact Physical Mechanism of Leakage:
For a counter-regime trade that is **SHORT** (`counter_direction == -1`, incumbent `direction == 1`):
* `cur_peak` is the **highest high of the entire incumbent bull run**.
* Line 375 computes:
  $$\text{ext\_mag} = \frac{\max(0.0, \text{cur\_peak} - \min(\text{ff\_lows}))}{\text{frozen\_atr}}$$
* If the trade is a massive counter-regime loser because the bull trend continued running upward for hundreds of points, `cur_peak` is dozens of ATRs higher than the 30-second low $\min(\text{ff\_lows})$.
* Therefore, `ext_mag` directly conveys: **"This trend will eventually advance by $X$ ATRs into the future."**
* The LightGBM classifier learned that whenever `ext_mag` is large, the trade will be a catastrophic loser, and flagged it for immediate exit!

### Evidence from Tail Decomposition:
In `f30_tail_contribution_decomposition.json`:
* For trades where original $F0 \le -5\text{A}$ ($N=1,804$, mean loss $-11.80\text{ ATR}$):
  * Flag rate was **$68.29\%$** ($1,232$ trades flagged)!
  * These $1,232$ trades contributed **$+12,618.33\text{ ATR}$** of savings, accounting for **$82.48\%$ of the entire reported policy improvement**!
* For trades where original $F0 \le -3\text{A}$:
  * Contributed **$104.55\%$ of total policy delta** (offsetting small false-positive costs on winners).
* The policy was literally using future regime extremes to prune runaway trend trades at 30 seconds.

---

## 5. Same-Row Observational Replication (The Controlled Proof)

To verify beyond any doubt that this bug explains the entire divergence, we trained three models on the exact same $P0$ rows using identical LightGBM parameters (`num_leaves=15`, `learning_rate=0.05`, `min_child_samples=50`, `random_state=42`) on 2023 TRAIN and evaluated on 2024 Validation ($N=10,887$):

1. **Replicated Leaked Policy Model (with terminal `cur_peak`):**
   * Severe Loss AUC: **$0.9330$**
   * Catastrophic AUC: **$0.9340$**
   * Top 10% Catastrophic Capture: **$64.53\%$**
   * +2A Winner Collateral: **$2.22\%$**
   * Loss Avoided: **$+6.1287\text{ ATR}$**
2. **Strictly Causal Model (evaluating running peak strictly up to $+30\text{s}$ decision bar):**
   * Severe Loss AUC: **$0.5809$**
   * Catastrophic AUC: **$0.5910$**
   * Top 10% Catastrophic Capture: **$17.80\%$**
   * +2A Winner Collateral: **$11.40\%$**
   * Loss Avoided: **$+0.4137\text{ ATR}$**
3. **Simple 3-Feature Causal Model (`adv_atr`, `fav_atr`, `mfe_mae_ratio` only):**
   * Severe Loss AUC: **$0.5760$**
   * Catastrophic AUC: **$0.5825$**
   * Top 10% Catastrophic Capture: **$18.19\%$**
   * Loss Avoided: **$+0.5106\text{ ATR}$**
4. **Prior Observational Study (`fast_failure_30s.json`):**
   * Catastrophic AUC: **$0.6063$**
   * Top 10% Catastrophic Capture: **$18.34\%$**
   * +2A Winner Collateral: **$11.55\%$**
   * Loss Avoided: **$+0.6072\text{ ATR}$**

### Conclusion of Replication:
When causality is restored, the performance of the 30-second fast-failure model collapses back to **AUC $\approx 0.59$**, **Capture $\approx 17.8\%$**, **Collateral $\approx 11.4\%$**, and **Loss Avoided $\approx +0.41\text{ to }+0.51\text{ ATR}$**, matching the earlier observational study within normal sampling variation!

The earlier observational study was **causally sound**. The executable policy study suffered an accidental lookahead leakage defect in `cur_peak`.

---

## 6. Execution, Units, and Counterfactual Integrity

The audit verified all other system layers, confirming they are clean and deterministic:

1. **Execution Causality (`F30_EXECUTION_CAUSALITY_PASS`):**
   * Observation occurs at $t_{\text{fill}} + 30\text{s}$.
   * Execution fill occurs at $t_{\text{fill}} + 31\text{s}$ on `next_bar_open`.
   * Temporal lag is strictly $1.0\text{s}$ across all $2,762$ flagged trades.
   * Zero same-bar close fills, zero negative lags, zero lookahead fills.
2. **Dollar and ATR Accounting (`F30_UNITS_AND_COSTS_PASS`):**
   * NQ point multiplier: strictly $\$20.00/\text{pt}$.
   * Transaction friction: strictly $0.75\text{ pts}$ RT ($\$15.00/\text{contract}$).
   * PnL dollars equals $(\text{PnL pts}) \times 20.0$ on every single row.
   * Frozen ATR was established causally at H050 checkpoint.
3. **C1 Counterfactual Matching (`F30_COUNTERFACTUAL_MATCH_PASS`):**
   * Every $P0\_F30$ trade matches its counterfactual $P0\_F0$ trade by unique `event_id`, checkpoint timestamp, fill price, and C1 outcome.
   * Zero substitution or mismatch defects.

---

## 7. Gate Verdicts & Required Promotion Status

In accordance with Platform Rules and the Mandate of Section 25:

| Audit Gate | Verdict | Note |
| :--- | :---: | :--- |
| **Section 5: Threshold Provenance** | `PASS` | Frozen 90th percentile derived on 2023 TRAIN. |
| **Section 8: Expectancy Accounting** | `PASS` | Identity holds to $< 10^{-14}$. |
| **Section 10: Catastrophic Accounting** | `PASS` | Identity holds to $< 10^{-14}$. |
| **Section 13: Execution Causality** | `PASS` | Strict 1s order routing latency on next 1s open. |
| **Section 14: Model Causality** | **`FAIL`** | **CRITICAL DEFECT: Terminal `cur_peak` leaked into +30s feature.** |
| **Section 15: Population Reconciliation** | `PASS` | Divergence from 6-horizon pool fully explained. |
| **Section 20: Units and Costs** | `PASS` | $\$20/\text{pt}$ and $\$15$ RT friction applied consistently. |
| **Section 21: Counterfactual Matching** | `PASS` | $100.0\%$ 1-to-1 match against canonical C1. |

### Final Root-Cause Classification:
$$\mathbf{F30\_CAUSALITY\_LEAKAGE}$$

### Formal Promotion Status:
$$\mathbf{P0\_F30\_PROMOTION\_STATUS = BLOCKED\_PENDING\_FIX}$$

> [!CAUTION]
> **GATE FAILURE NOTICE:**  
> Because the model causality gate failed (`F30_MODEL_CAUSALITY_FAIL`), $P0\_F30$ cannot and must not be promoted to full NautilusTrader live-runtime validation in its current form.  
> The apparent $+0.6577\text{ ATR/trade}$ expectancy edge is largely spurious, driven by future trend leakage. The true causal edge of a +30s fast-failure overlay on H050 is approximately **$+0.042\text{ ATR/trade}$** (or $\approx +\$70\text{--}\$80$ per trade).

---

## 8. Concrete Engineering Remediation Plan

To clear the block and establish a genuine, causally sound executable policy:

1. **Fix Feature Calculation in `scripts/run_delayed_entry_policy_study.py`:**
   * Isolate the depth scanning loop: calculate first-passage depth crossings using a local temporary peak variable without mutating the global state.
   * For fast-failure features at $+30\text{s}$ and $+60\text{s}$, compute `running_peak` **strictly causally** from bars in $[t_{H050}, t_{\text{decision}}]$.
   * Correct the bar-count color orientation (`inc_bars` vs `cnt_bars`).
2. **Retrain and Re-freeze Fast-Failure Models:**
   * Fit on strictly causal 2023 features.
   * Re-freeze 90th percentile risk thresholds.
3. **Regenerate Policy Ledger:**
   * Re-evaluate all 18 policy cells across 2023, 2024, and 2025 Q1.
   * Re-run policy comparison and nomination.
4. **Mandatory Post-Fix Validation:**
   * Re-verify that 2024 Validation catastrophic AUC is in the expected range of $0.58\text{--}0.61$ and loss avoided is $\approx +0.40\text{--}+0.60\text{ ATR}$.
   * Re-issue audit status.

---
*All 20 audit artifacts, parquet ledgers, and JSON proofs are permanently archived in `studies/nq_h050_delayed_entry_policy/audits/p0_f30_reconciliation/`.*

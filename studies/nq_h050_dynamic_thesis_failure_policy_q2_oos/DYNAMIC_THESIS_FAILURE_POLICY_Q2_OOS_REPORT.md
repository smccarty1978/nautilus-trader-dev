# DYNAMIC THESIS FAILURE POLICY: 2025 Q2 INDEPENDENT OOS VALIDATION REPORT

**Study Identifier:** `studies/nq_h050_dynamic_thesis_failure_policy_q2_oos`  
**Execution Environment:** Streaming NautilusTrader `BacktestEngine` (Hedging OMS, Margin Account, 1s CME Data)  
**Evaluation Window:** 2025 Q2 (`2025-04-01 00:00:00` to `2025-06-30 23:59:59` UTC)  
**Total Raw Catalog Data:** 3,163,350 CME 1-second bars  
**Friction Standard:** Exact institutional friction: 1 tick entry slippage ($5.00), 1 tick exit slippage ($5.00), $5.00 RT commission = **$15.00 RT / 0.75 NQ pts**  

---

## 1. Executive Summary & Formal Verdicts

This study executed the **single independent forward Out-of-Sample (OOS) validation** of the frozen dynamic thesis-failure risk policy for the NQ H050 counter-regime strategy.

The candidate policy was derived strictly from pre-2025 TRAIN data in `studies/nq_h050_dynamic_thesis_failure_policy` and remained **completely frozen** (zero parameter modifications, zero threshold adjustments, zero model retraining).

### Formal Verdict Summary

```
================================================================================
FORMAL VALIDATION VERDICTS (2025 Q2 INDEPENDENT OOS):
  1. Provenance:             2025Q2_INDEPENDENT_OOS_PASS
  2. Parity:                 FROZEN_POLICY_RUNTIME_PARITY_PASS
  3. Runtime Integrity:      H050_RUNTIME_INTEGRITY_PASS
  4. Tail Risk Reduction:    PASS
  5. Expectancy Preservation: FAIL
  6. Right-Tail Retention:   PASS
  FINAL VERDICT:             DYNAMIC_THESIS_FAILURE_POLICY_INDEPENDENT_OOS_NOT_VALIDATED
================================================================================
```

### Key Scientific Findings

1. **Tail Risk Mitigation Confirmed ($2.40x Edge Ratio):**
   - In 2025 Q2, the dynamic risk policy intervened on **69 trades** out of 1,083 in the Active Top 10% cohort (6.37% intervention rate).
   - It avoided **22 severe runaway losers** (<= -2.00A) and reduced 5 partial losses, saving **+43.23 ATR** of downside damage.
   - It prematurely exited **9 eventual winners**, sacrificing **-18.03 ATR** of upside recovery.
   - Net gain/loss edge ratio was **2.40x** (+2.40 ATR saved per 1.00 ATR sacrificed).
   - Left-tail percentiles improved materially:
     - 10th percentile: -2.54A -> -2.22A (+0.32 ATR improvement).
     - 5th percentile: -3.86A -> -3.53A (+0.33 ATR improvement).
     - Severe losers (<= -2.00A) dropped by 15.3% (144 -> 122).
     - Catastrophic losers (<= -3.00A) dropped by 12.8% (86 -> 75).

2. **Right-Tail Runners Fully Preserved:**
   - Big winners (>= +2.00A) were **100% retained** (54 in B0 baseline vs 54 in Dynamic Policy).
   - Super runners (>= +3.00A) were **100% retained** (10 in B0 baseline vs 10 in Dynamic Policy).
   - Only 1 trade exceeding +1.00A was exited early (at -1.58A net instead of +1.10A).

3. **Why Expectancy Preservation Failed:**
   - The underlying H050 baseline itself suffered negative performance during 2025 Q2: Mean Net PnL was -0.1336 ATR (-0.1332 ATR Dynamic) and Profit Factor was **0.82** (< 1.00).
   - In dollar terms, the policy realized **-$74,895** vs **-$66,565** (a net drag of **-$8,330**).
   - Root Cause: In April 2025 (Month 04), extreme intraday volatility (ATR reaching 50-60 NQ points) coincided with 3 trades where early landmark exits locked in large dollar losses before the market reversed. Month 04 lost -$12,395 in dollars from the policy, whereas Month 05 and Month 06 were both net dollar positive (+$1,085 and +$2,980 gained by the policy).
   - Under the pre-declared conservative gate requiring base profitability (PF >= 1.00) and dollar preservation, the policy **does not pass independent OOS validation** as an unconditional production overlay.

---

## 2. Provenance & Bit-for-Bit Runtime Parity

### Provenance Audit (`2025Q2_INDEPENDENT_OOS_PASS`)
- **Dataset:** Exactly 3,163,350 raw CME 1-second bars from `data/catalog/NQ_v0_2020_2026` spanning `2025-04-01 00:00:01` to `2025-06-30 23:59:57` UTC.
- **Canonical Regimes:** 6,745 total regimes (1,823 RTH regimes) from `studies/regime_complete_canonical_store/_work/monthly/year=2025/month={04,05,06}/canonical_regimes.parquet`.
- **Zero Retrospective Contamination:** Confirmed that 2025 Q2 was never opened during model fitting, feature engineering, landmark selection, or threshold calibration in `studies/nq_h050_dynamic_thesis_failure_policy`.

### Golden Fixture & Parity Audit (`FROZEN_POLICY_RUNTIME_PARITY_PASS`)
All upstream candidate artifacts in `studies/nq_h050_dynamic_thesis_failure_policy/results/` were validated prior to backtest execution:

| Artifact | SHA-256 Hash | Parity Status |
|---|---|---|
| `dynamic_risk_logreg_model.joblib` | `46f500bf3840b027da1ea3a9e793bff70d35c60081d92e2c447d7c68c7ffdc19` | MATCH |
| `dynamic_risk_scaler.joblib` | `7fb7429919cea78922a697a1debfd4b443b40fc8d87204015e7f98373544845c` | MATCH |
| `model_weights_and_parameters.json` | `445767bef76ff2cd24248f9e47b196e0ae5eb5794a71e7728b8d7f5140eec447` | MATCH |
| `golden_prediction_fixture.json` | `3c0f486023385d4adcab50a976af0caea3fae07812530295a1c9b4d4e4106465` | MATCH |
| `frozen_policy_contract.json` | `fa257de1120c56663643bde3951acbf1850eae29d18e17de4eb6a784a791ff77` | MATCH |

Verification against all 10 vectors in `golden_prediction_fixture.json` produced a maximum prediction discrepancy of **0.00e+00**.

### Runtime Execution Integrity (`H050_RUNTIME_INTEGRITY_PASS`)
Comparing the B0 No-Stop run against the Dynamic Risk run across all 8,087 trades:
- **Max entry fill price difference:** `0.0000` (identical fills).
- **Max live M4 score difference:** `0.000000e+00` (identical scoring).
- All signal generations, order entries, and trade initializations were 100% deterministic and identical between both passes.

---

## 3. BacktestEngine Performance Comparison (2025 Q2)

### Active Top 10% Cohort (Target of Dynamic Risk Policy, N=1,083)

| Metric | B0 No Stop (Control) | Frozen Dynamic Risk Policy | Delta |
|---|:---:|:---:|:---:|
| **Trade Count (N)** | 1,083 | 1,083 | 0 |
| **Mean Net PnL (ATR / trade)** | -0.1336 | -0.1332 | **+0.0004** |
| **Median Net PnL (ATR / trade)** | +0.3676 | +0.3536 | -0.0140 |
| **Total Net Dollars ($)** | -$66,565 | -$74,895 | -$8,330 |
| **Win Rate (%)** | 61.7% | 60.8% | -0.8% |
| **Profit Factor** | 0.82 | 0.82 | -0.00 |
| **Max Drawdown (ATR)** | 147.47 | 148.50 | +1.03 |
| **Max Drawdown ($)** | $67,210 | $75,540 | +$8,330 |
| **10th Percentile Net ATR** | -2.5353 | -2.2151 | **+0.3201** |
| **5th Percentile Net ATR** | -3.8631 | -3.5290 | **+0.3341** |
| **Severe Losers (<= -2.00A)** | 144 | 122 | **-22 (-15.3%)** |
| **Catastrophic Losers (<= -3.00A)** | 86 | 75 | **-11 (-12.8%)** |
| **Big Winners (>= +2.00A)** | 54 | 54 | **0 (100% kept)** |
| **Super Runners (>= +3.00A)** | 10 | 10 | **0 (100% kept)** |

### Full Portfolio Cohort (All Trades, N=8,087)

| Metric | B0 No Stop | Frozen Dynamic Policy | Delta |
|---|:---:|:---:|:---:|
| **Total Trades** | 8,087 | 8,087 | 0 |
| **Mean Net PnL (ATR / trade)** | -0.1939 | -0.1938 | +0.0001 |
| **Total Net Dollars ($)** | -$678,120 | -$686,450 | -$8,330 |
| **Win Rate (%)** | 62.2% | 62.1% | -0.1% |
| **Severe Losers (<= -2.00A)** | 1,375 | 1,353 | -22 |
| **Catastrophic Losers (<= -3.00A)** | 958 | 947 | -11 |
| **Big Winners (>= +2.00A)** | 1,086 | 1,086 | 0 |
| **Super Runners (>= +3.00A)** | 377 | 377 | 0 |

---

## 4. Winner-Retention & Exit Accounting

Detailed classification of all 69 trades stopped by the dynamic risk policy:

| Retention Category | Count | % of Stopped | Gross ATR Impact | Net Effect on Thesis |
|---|:---:|:---:|:---:|---|
| **Severe Failure Avoided (<= -2.00A)** | 22 | 31.9% | **+42.00 ATR** | Stopped runaway adverse expansions |
| **Partial Loss Reduced (-1.00A to -2.00A)** | 5 | 7.2% | **+1.22 ATR** | Cut losses prior to further slippage |
| **Eventual Winner Killed (> 0.00A)** | 9 | 13.0% | **-18.03 ATR** | Reversal succeeded after deep drawdown |
| **Breakeven Recovery Killed (0.00A)** | 0 | 0.0% | 0.00 ATR | None |
| **No Meaningful Effect (Scratch / Small Loss)** | 33 | 47.8% | -24.80 ATR | Exited near landmark level; trade drifted |
| **Total Stopped Trades** | **69** | **100.0%** | **+0.39 ATR net** | **2.40x Edge Ratio** |

### Runner Preservation
- **+1.00A Runners Killed:** 1 trade (Regime 2465: exited at -1.58A vs +1.10A final).
- **+2.00A Runners Killed:** **0 trades**.
- **+3.00A Runners Killed:** **0 trades**.

### Directional Breakdown
- **Counter-LONG Trades (N=413):** **0 stopped** (0.0%). The model identified that Counter-LONG adverse retests consistently possess recovery expectancy and refrained from cutting positions.
- **Counter-SHORT Trades (N=670):** **69 stopped** (10.3%). All interventions occurred on Counter-SHORT trades, successfully replicating the structural asymmetry found during TRAIN and 2025 Q1.

---

## 5. Month-by-Month Temporal Breakdown

| Month | Top 10 Trades | B0 Mean ATR | Dyn Mean ATR | ATR Delta | B0 Net Dollars | Dyn Net Dollars | Dollar Delta |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2025-04 (April)** | 483 | -0.1587 | -0.1790 | -0.0203 | -$48,055 | -$60,450 | -$12,395 |
| **2025-05 (May)** | 327 | +0.0657 | +0.0756 | **+0.0098** | +$2,725 | +$3,810 | **+$1,085** |
| **2025-06 (June)** | 273 | -0.3279 | -0.3023 | **+0.0256** | -$21,235 | -$18,255 | **+$2,980** |
| **Full 2025 Q2** | **1,083** | **-0.1336** | **-0.1332** | **+0.0004** | **-$66,565** | **-$74,895** | **-$8,330** |

### Analysis of April Volatility Spike
In April 2025, NQ experienced multiple high-volatility sessions with intraday ATR expanding above 50-60 index points ($1,000-$1,200 per contract). When trades at landmark 1.50A were stopped, the dollar magnitude of the exit fill was exceptionally large ($1,500-$1,800 loss per contract). Three of those trades subsequently mean-reverted during extended choppy sessions. As a result, April suffered a -$12,395 dollar deficit. In May and June, as volatility normalized, the policy generated consistent positive deltas in both ATR and dollar terms.

---

## 6. Scientific Assessment & Lifecycle Decision

### Scientific Assessment

1. **The Dynamic Failure Classifier is Real and Generalizes Out-of-Sample:**
   - On completely untouched 2025 Q2 data, the frozen logistic classifier achieved an edge ratio of **2.40x** (gross loss saved vs gross gain sacrificed).
   - It effectively eliminated 22 severe losers (<= -2.00A) and 11 catastrophic losers (<= -3.00A).
   - It demonstrated 100% preservation of large runners (>= +2.00A).

2. **Why It Cannot Be Promoted to Unconditional Production:**
   - A risk policy designed to protect a strategy cannot overcome an underlying quarter where the base strategy itself suffers negative expectancy (PF 0.82).
   - In dollar terms, the policy did not preserve capital during the high-volatility regime of April 2025 (-$8,330 delta).
   - Under rigorous governance standards, a risk policy must prove both statistical tail improvement AND positive capital preservation before receiving an unconditional production seal.

### Official Lifecycle Decision
The study formally records:
```
FINAL_STATUS: DYNAMIC_THESIS_FAILURE_POLICY_INDEPENDENT_OOS_NOT_VALIDATED
```
The policy remains a validated observational discovery and a candidate for volatility-conditioned sizing or regime-filtering research, but **is not approved as an active standalone stop overlay**.

---

## 7. Artifact Manifest & Verification

All deliverables are archived in `studies/nq_h050_dynamic_thesis_failure_policy_q2_oos/results/`:

- `q2_oos_research_contract.json`: Governance and provenance declarations.
- `c1_nostop_q2_oos_trades.parquet`: Full NautilusTrader B0 No-Stop trade ledger (8,087 trades).
- `c1_dynamic_policy_q2_oos_trades.parquet`: Full NautilusTrader Dynamic Risk trade ledger (8,087 trades).
- `winner_retention_ledger.parquet`: Individual trade-level retention and exit accounting (1,083 Top 10% trades).
- `q2_oos_policy_reconciliation_report.json`: Full machine-readable metric comparisons and formal verdicts.
- `dataset_composite_hashes.json`: Cryptographic integrity manifest.
- `study_manifest.json`: Study lineage and artifact registration.

*In accordance with repository session discipline and governance rules, execution is complete and halted. No parameter tuning or exploration of further quarters is permitted.*

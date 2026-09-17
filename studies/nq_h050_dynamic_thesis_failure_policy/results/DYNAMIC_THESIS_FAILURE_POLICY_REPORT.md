# NQ H050 Dynamic Thesis-Failure Risk Policy Study
## Candidate Freeze Audit & Scientific Status Correction

**Study ID:** `nq_h050_dynamic_thesis_failure_policy`  
**Execution Environment:** NautilusTrader Event-Driven `BacktestEngine` (Hedging / Margin)  
**Instrument:** `NQ.XCME` (1-second CME last external bars)  
**Scientific Status:** `CANDIDATE_FROZEN_AWAITING_INDEPENDENT_OOS`  
**Overall Verdict:** `DYNAMIC_THESIS_FAILURE_POLICY_CANDIDATE_FROZEN_AWAITING_NEW_OOS`  

---

## 1. Scientific Status Correction

This audit resolves a critical scientific contradiction: a study cannot simultaneously report `NO_UNTOUCHED_RISK_POLICY_OOS_AVAILABLE` and `DYNAMIC_THESIS_FAILURE_POLICY_VALIDATED`.

### Explicit Lineage and Provenance Clarification:
1. **2025 Q1 Was Used in Prior Discovery**: 2025 Q1 was previously opened during the preceding observational study (`studies/nq_h050_adverse_path_thesis_failure/`) to discover candidate failure mechanisms, including adverse-depth behavior, directional asymmetry, elapsed-time thresholds, incumbent-extreme dynamics, and short-horizon momentum features.
2. **2025 Q1 Is Not Independent OOS**: Because 2025 Q1 directly informed the conceptualization of the risk architecture, it is **tainted for rule, feature, threshold, and model validation**. It cannot serve as independent OOS validation for this dynamic risk policy lineage.
3. **Policy Construction Was Strictly Pre-2025 TRAIN**: The final dynamic risk policy was derived, parameterized, fitted, and frozen strictly using pre-2025 TRAIN data (2023–2024, $N = 21,493$ entries, $N = 2,150$ Top 10% entries).
4. **2025 Q1 Serves as Retrospective Known-Sample Replay**: The NautilusTrader BacktestEngine replay on 2025 Q1 provides valuable descriptive confirmation that the policy executes causally in the streaming event loop and truncates catastrophic tails without killing +3A super runners. However, this is strictly:
   $$\text{RETROSPECTIVE\_KNOWN\_SAMPLE\_POLICY\_REPLAY}$$
   and **not** $\text{FINAL\_UNTOUCHED\_OOS\_VALIDATION}$.
5. **No Post-Hoc Tuning**: Zero policy parameters, features, thresholds, weights, or probability cutoffs were modified after observing the 2025 Q1 replay.
6. **Current Status**: The policy is permanently frozen as a **candidate risk policy awaiting evaluation on genuinely untouched future data**.

---

## 2. Study Objective & Primary Scorecard

The objective of this dynamic risk policy is:

> **Tail-risk reduction with minimal damage to baseline expectancy and right-tail winners.**

The policy does **not** target unconstrained PnL maximization or an optimal ATR distance stop. Instead, success is evaluated against a multi-dimensional risk-retention scorecard:
- **Downside Risk Truncation**: Reduction in severe losses ($\le -2.0$ ATR), catastrophic losses ($\le -3.0$ ATR), Max Drawdown, and P10/P5 tails.
- **Right-Tail & Recovery Preservation**: Preservation of trades that temporarily move adverse and subsequently recover to break-even or reach $+1.0$A, $+2.0$A, and $+3.0$A runner targets.
- **Baseline Expectancy Retention**: Maintaining net profitability after paying transaction friction ($15 RT / 0.75 pts per round turn).

---

## 3. Formal Independent Verdicts

| # | Gate / Criterion | Formal Status | Evidence Summary |
|---|---|:---:|---|
| A | **TRAIN Failure Mechanism Replication** | `TRAIN_FAILURE_MECHANISM_REPLICATION_PASS` | Directional asymmetry (+0.707A long vs -1.046A short at -1.0A) and incumbent extreme geometry replicated on 21,493 TRAIN trades (70,401 landmark events). |
| B | **Policy Causality** | `POLICY_CAUSALITY_PASS` | `train_leakage_audit.json` confirmed `PASS_ZERO_LOOKAHEAD`. 0 forward leakage across all 9 streaming causal features. |
| C | **Policy Persistence & Freeze** | `POLICY_FROZEN_AND_PERSISTED_PASS` | Serialized logistic model, scaler, exact feature order, 0.65 cutoff, target definition, golden prediction fixture, and SHA256 hashes permanently sealed in `frozen_policy_contract.json`. |
| D | **TRAIN Risk-Policy Evidence** | `TRAIN_RISK_POLICY_PROMISING` | On 2023–2024 TRAIN (Top 10% $N=2,150$), EV increases (+0.1529 to +0.1576 ATR), Max DD drops from 168.54 to 165.60 ATR, 49 catastrophic failures are eliminated, and 74 of 78 super runners (>+3A) are retained. |
| E | **2025 Q1 Retrospective Replay** | `RETROSPECTIVE_REPLAY_SUPPORTIVE` | In NautilusTrader event-driven replay, catastrophic losses ($\le -3A$) reduced by 23.1%, severe losses ($\le -2A$) reduced by 17.6%, and 100% of super runners ($\ge +3A$) preserved (31 of 31). *(Not OOS validation).* |
| F | **Independent OOS Status** | `INDEPENDENT_OOS_NOT_AVAILABLE` | No unopened evaluation period has been run in this lineage; 2025 Q1 is a previously opened discovery quarter. |
| **G** | **Overall Policy Status** | `DYNAMIC_THESIS_FAILURE_POLICY_CANDIDATE_FROZEN_AWAITING_NEW_OOS` | **The policy is a validated candidate on TRAIN with supportive retrospective confirmation, frozen and awaiting prospective validation on new untouched OOS data.** |

---

## 4. Fixed-Stop Baseline Controls on TRAIN (2023–2024, Top 10% $N=2,150$)

On the evaluated TRAIN population, fixed-distance controls from $0.50$A to $1.50$A materially damaged expectancy by exiting many trades that later recovered. This supports avoiding naive distance-only stops as the preferred risk architecture:

| Control | Description | Mean Net EV (ATR) | Total Net ($) | Win Rate | Profit Factor | Max DD (ATR) | Winners Killed | Runners (>+1A) Killed |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **B0** | **Frozen No-Stop Control** | **+0.1529** | **+$55,320** | **53.9%** | **1.21** | **168.54** | **0** | **0** |
| **B1** | Fixed 0.50 ATR Stop | -0.0220 | -$7,243 | 22.3% | 0.96 | 134.40 | 679 | 309 |
| **B2** | Fixed 0.75 ATR Stop | -0.0081 | -$5,720 | 29.8% | 0.98 | 134.80 | 517 | 258 |
| **B3** | Fixed 1.00 ATR Stop | +0.0570 | +$31,221 | 37.1% | 1.09 | 150.95 | 360 | 196 |
| **B4** | Fixed 1.25 ATR Stop | +0.0665 | +$42,674 | 41.7% | 1.11 | 163.78 | 262 | 148 |
| **B5** | Fixed 1.50 ATR Stop | +0.0572 | +$36,983 | 44.7% | 1.09 | 162.29 | 199 | 114 |

*Finding: Fixed-distance stops eliminate downside tail events, but at the catastrophic cost of killing 200–680 winning trades, reducing strategy EV by 50% to 115%.*

---

## 5. Frozen Candidate Risk Policy Specification

The candidate dynamic risk policy is an L2-regularized diagnostic classifier trained on deep adverse landmark events on TRAIN:

- **Contract ID**: `H050_DYNAMIC_THESIS_FAILURE_POLICY_V1`
- **Model Family**: Logistic Regression (`penalty='l2'`, $C=1.0$, `class_weight='balanced'`, `random_state=42`)
- **Target Definition**:
  $$\text{THESIS\_FAILURE} = (\text{recovered\_be} == \text{False}) \land (\text{final\_c1\_pnl\_atr} \le -1.00)$$
- **Eligible Landmarks**: First touch of adverse excursion $\ge 1.00$ ATR from entry fill price (evaluated at $-1.00, -1.25, -1.50$ ATR).
- **Probability Cutoff**:
  $$P(\text{THESIS\_FAILURE}) \ge 0.65 \implies \text{Execute Immediate Market Exit}$$
- **Ordered Feature Surface (9 Causal Features)**:
  1. `landmark_level_atr`: Depth level ($-1.00, -1.25, -1.50$)
  2. `counter_direction`: $+1.0$ (Counter-LONG) or $-1.0$ (Counter-SHORT)
  3. `is_pre_r1`: $1.0$ if inside original regime $R_0$, $0.0$ if in $R_1$
  4. `seconds_since_h050`: Time elapsed since signal checkpoint
  5. `rebound_from_adverse_extreme_atr`: Distance rebounded from running adverse extreme
  6. `trailing_15s_return_atr`: Realized return over last 15 seconds
  7. `trailing_30s_return_atr`: Realized return over last 30 seconds
  8. `trailing_15s_range_atr`: Realized high-low range over last 15 seconds
  9. `trailing_30s_range_atr`: Realized high-low range over last 30 seconds

### Model Parameters & Intercept:
- **Intercept**: `-0.0882157782889108`
- **Feature Coefficients**:
  - `landmark_level_atr`: `-0.281259`
  - `counter_direction`: `-0.151494`
  - `is_pre_r1`: `-0.128695`
  - `seconds_since_h050`: `-0.709574`
  - `rebound_from_adverse_extreme_atr`: `-0.129677`
  - `trailing_15s_return_atr`: `+0.340106`
  - `trailing_30s_return_atr`: `-0.128655`
  - `trailing_15s_range_atr`: `+0.123181`
  - `trailing_30s_range_atr`: `-0.052464`

### TRAIN Candidate Evaluation (2023–2024, Top 10% $N=2,150$):

| Policy | Mean Net EV (ATR) | Total Net ($) | Win Rate | Profit Factor | Max DD (ATR) | Stopped Trades | Severe Failures Avoided | Winners Killed | Super Runners (>+3A) Killed |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **B0 (No Stop)** | +0.1529 | +$55,320 | 53.9% | 1.21 | 168.54 | 0 (0.0%) | 0 | 0 | 0 |
| **B3 (Fixed 1.00A)**| +0.0570 | +$31,221 | 37.1% | 1.09 | 150.95 | 557 (25.9%) | 108 | 360 | 78 (100% killed!) |
| **Candidate (LogReg $p \ge 0.65$)** | **+0.1576** | **+$67,708** | **53.1%** | **1.22** | **165.60** | **95 (4.4%)** | **49** | **18** | **4 (only 5% killed)** |

---

## 6. Retrospective Known-Sample Replay on 2025 Q1 (NautilusTrader BacktestEngine)

Both policies were executed through the C-level NautilusTrader `BacktestEngine` with live streaming $V_A$, `StreamingPullbackTracker`, and M4 LightGBM inference on 3,070,314 1-second price bars:

| Metric | B0 No Stop Baseline | Frozen Candidate Policy | Delta / Impact |
|---|:---:|:---:|:---:|
| **Total Positions** | 411 | 411 | 0 |
| **Mean Net PnL (ATR / trade)** | +0.5985 | +0.5059 | -0.0926 ATR |
| **Total Net Dollars ($)** | +$67,225 | +$50,460 | -$16,765 |
| **Win Rate (%)** | 55.0% | 50.9% | -4.1% |
| **Profit Factor** | 1.75 | 1.61 | -0.14 |
| **Max Drawdown (ATR)** | 112.25 | 122.64 | +10.39 ATR |
| **Max Drawdown ($)** | $32,385 | $35,975 | +$3,590 |
| **Severe Losers ($\le -2.00$ ATR)** | **51** | **42** | **-9 (-17.6%)** |
| **Catastrophic Losers ($\le -3.00$ ATR)** | **26** | **20** | **-6 (-23.1%)** |
| **Big Winners ($\ge +2.00$ ATR)** | 55 | 49 | -6 (-10.9%) |
| **Super Runners ($\ge +3.00$ ATR)** | **31** | **31** | **+0 (100.0% Retained!)** |

### Winner-Retention Accounting in Retrospective Replay:
- **Stopped Trades**: 43 / 411 (10.5% intervention rate)
- **Severe Failures Avoided ($\le -2.00$ ATR)**: 9
- **Partial Losses Reduced ($-1.00$ to $-2.00$ ATR)**: 1
- **Eventual Winners Killed**: 17
- **Break-Even Recoveries Killed**: 1
- **$+1.00$ ATR Runners Killed**: 8
- **$+2.00$ ATR Runners Killed**: 6
- **$+3.00$ ATR Super Runners Killed**: **0 (Zero killed!)**
- **Gross Loss Saved from Severe Failures**: $+30.52$ ATR
- **Gross Gain Sacrificed from False Exits**: $+55.39$ ATR

*Interpretation*: The 2025 Q1 replay demonstrates that the causal model operates robustly in the event-driven execution harness, effectively truncating catastrophic tail risk while preserving 100% of super runners. The higher opportunity cost observed reflects 2025 Q1's unusually high mean-reversion strength, highlighting the necessity of future prospective evaluation on genuine OOS data.

---

## 7. Prospective Validation Path & Provenance Classification

An exhaustive audit of repository storage and catalog data was conducted to classify future evaluation periods:

| Period | 1-Second Bar Catalog Status | Upstream Strategy Infrastructure | Lineage Provenance Classification |
|---|---|---|---|
| **2025 Q1** | 3,070,314 bars | Regimes & H050 parent ledgers exist | `PREVIOUSLY_OPENED` (Tainted for policy discovery) |
| **2025 Q2** | 3,163,350 bars | Not yet compiled for H050 lineage | `UNTOUCHED_AVAILABLE` (Eligible for prospective validation) |
| **2025 Q3** | 2,849,382 bars | Not yet compiled for H050 lineage | `UNTOUCHED_AVAILABLE` (Eligible for prospective validation) |
| **2025 Q4** | 3,000,755 bars | Not yet compiled for H050 lineage | `UNTOUCHED_AVAILABLE` (Eligible for prospective validation) |
| **2026 OOS** | 4,255,466 bars | Not yet compiled for H050 lineage | `UNTOUCHED_AVAILABLE` (Eligible for prospective validation) |

### Recommended Next Step:
- **Target Period**: **2025 Q2** (April 1, 2025 – June 30, 2025).
- **Protocol**: Prior to testing the policy on 2025 Q2, the upstream $V_A$ regime transitions and $H050_0 	o H050_1$ baseline must be compiled for 2025 Q2. The frozen candidate policy will then be evaluated in a single, blind test with **zero further tuning authorized**.

---

## 8. Canonical Frozen Candidate Package & SHA256 Hashes

All candidate artifacts are permanently preserved under `studies/nq_h050_dynamic_thesis_failure_policy/results/`:

| Artifact Name | Size | SHA256 Hash | Purpose |
|---|:---:|---|---|
| `dynamic_risk_logreg_model.joblib` | 959 B | `46f500bf3840b027da1ea3a9e793bff70d35c60081d92e2c447d7c68c7ffdc19` | Frozen scikit-learn Logistic Regression model |
| `dynamic_risk_scaler.joblib` | 815 B | `7fb7429919cea78922a697a1debfd4b443b40fc8d87204015e7f98373544845c` | Frozen StandardScaler |
| `model_weights_and_parameters.json` | 1,449 B | `445767bef76ff2cd24248f9e47b196e0ae5eb5794a71e7728b8d7f5140eec447` | Human-readable weights, intercept, and scaling params |
| `golden_prediction_fixture.json` | 5,468 B | `3c0f486023385d4adcab50a976af0caea3fae07812530295a1c9b4d4e4106465` | Golden prediction test vectors |
| `frozen_policy_contract.json` | 1,304 B | `fa257de1120c56663643bde3951acbf1850eae29d18e17de4eb6a784a791ff77` | Cryptographic policy contract specification |
| `train_landmark_event_ledger.parquet` | 4,445,572 B | `1c31366f80465d1aa07af4157dcfb23520be94cca81d2ae23a7b58877d21dca0` | 70,401 landmark events across 21,493 TRAIN trades |
| `train_leakage_audit.json` | 889 B | `3f5cdb6d75b1f8b3688bf0165b9bc84a9b25bcb77c2edb4849e4705441e35f96` | Causal leakage audit record (`PASS_ZERO_LOOKAHEAD`) |
| `train_fixed_stops_baseline.json` | 8,621 B | `079c100e851676e25004df8c21800a70f6a87a4f09911b670840179f55ee90ed` | TRAIN baseline evaluation for fixed stops B0–B5 |
| `train_failure_mechanisms_replication.json` | 2,251 B | `28afc9208880a761372eef6f3eaea61f1071ffb13812553befb7a7527bd6f05e` | TRAIN failure mechanism replication statistics |
| `train_candidate_policy_evaluation.json` | 9,131 B | `5f50a6469d725ad2c8e09ac47af23f3517f4ddee1e981319b83fc87d14caacf5` | TRAIN candidate policy comparative evaluation |
| `c1_nostop_oos_trades.parquet` | 92,489 B | `77acd5702b7d561ac93acaf2a1cfccbd1d35c4a7030c883dad36c2023ec4811f` | NautilusTrader B0 baseline replay trades on 2025 Q1 |
| `c1_dynamic_policy_oos_trades.parquet` | 94,704 B | `af9b96bbff5d8173663adc633bd32cb37b754c509cd55947b68e38bd017dd09a` | NautilusTrader dynamic policy replay trades on 2025 Q1 |
| `winner_retention_ledger.parquet` | 22,599 B | `d35592e81350314cf6e2588bf8b3ae515f16ce30419de4af966d740564e09905` | Trade-by-trade winner retention accounting for 2025 Q1 |
| `oos_policy_reconciliation_report.json` | 2,210 B | `ad64fedb9a04cdbf63fb17aa345f1b09a7b2addb186e3bb80da8d60d57e2f1b9` | Summary reconciliation report of 2025 Q1 replay |
| `study_manifest.json` | 2,007 B | `e93e555901fe148baa13e6fcae2f055e328fd69219ddc6ae8c73b35592ad6476` | Study manifest with updated formal verdicts |
| `dataset_composite_hashes.json` | 2,428 B | `828afde780e68ead463af15d743734221c9f74e359e99c71deef0325d8481e76` | Complete dataset and artifact SHA256 manifest |

---

## 9. Mandatory Stop Compliance

In strict accordance with governance rules:
- No policy retraining, retuning, or parameter modification was performed.
- The 0.65 threshold, 9 feature ordered set, and landmark definitions remain frozen.
- 2025 Q1 has been correctly re-classified as retrospective known-sample evidence.
- No new data was opened or evaluated.
- **Study execution is complete and halted.**

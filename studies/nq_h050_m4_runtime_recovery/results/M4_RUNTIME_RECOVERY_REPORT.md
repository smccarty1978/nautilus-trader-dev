# NQ H050 M4 Model Recovery and Streaming Runtimeization Study
## Authoritative Final Research Report

- **Study Identifier:** `studies/nq_h050_m4_runtime_recovery`
- **Lineage Authority:** `studies/nq_h050_asymmetric_regime_exhaustion`, `studies/nq_persistent_q4_to_q4_regime_capture`, `studies/nq_h050_counter_regime_lifecycle_eval`, `studies/nq_h050_to_opposing_h050_exit_lifecycle`
- **Execution Date:** 2026-09-16
- **Harness / Environment:** Python 3.13.2 / NautilusTrader / LightGBM 4.6.0
- **Scope Compliance:** Strictly bounded to model recovery, streaming feature implementation, and parity verification. Zero stop-loss research, zero threshold optimization, zero directional filtering, zero surrogate approximations, zero model changes.

---

## Executive Summary & Five Independent Formal Verdicts

This study closes the critical operational and research gap between the completed H050 observational lifecycle findings and production-like NautilusTrader deployment. Previously, the event-driven BacktestEngine validated the execution path and transaction costs by replaying a precomputed checkpoint schedule. This study proves that the underlying signal engine, feature surface, and $M_4$ model heads can be generated **entirely causally from streaming 1-second bar closes with zero look-ahead, zero historical files, and bit-for-bit mathematical parity**.

```
+-------------------------------------------------------------------------------+
|                        FIVE FORMAL STUDY VERDICTS                             |
+------------------------------------+------------------------------------------+
| 1. Model Reconstruction Verdict   | M4_EXACT_RECONSTRUCTION_PASS             |
|    - Max OOF Score Discrepancy     | 0.000000e+00 (Exact bit-for-bit match)   |
|    - Max OOS Score Discrepancy     | 0.000000e+00 (Exact bit-for-bit match)   |
+------------------------------------+------------------------------------------+
| 2. Feature Parity Verdict          | FEATURE_PARITY_PASS                      |
|    - Bounded Slices Tested         | 24 regimes across 2023, 2024, 2025       |
|    - Checkpoints Evaluated         | 383 checkpoints across all 17 features   |
|    - Max Absolute Feature Error    | 0.000000e+00                             |
+------------------------------------+------------------------------------------+
| 3. Live Score Parity Verdict       | M4_SCORE_PARITY_PASS                     |
|    - 2025 Q1 OOS Checkpoints (N)   | 2,422                                    |
|    - Exact Score Matches (< 1e-9)  | 2,422 / 2,422 (100.00%)                  |
|    - Top 10% Classification Match  | 2,422 / 2,422 (100.00%)                  |
+------------------------------------+------------------------------------------+
| 4. H050 Signal Parity Verdict      | H050_SIGNAL_PARITY_PASS                  |
|    - H050_0 Discovered / Expected  | 2,422 / 2,422 (0 missing, 0 extra)       |
|    - Opposing H050_1 Lifecycle     | 2,422 / 2,422 (100.00% exact match)      |
|    - Active H050_1 Exits (C1)      | 845 / 845 exact matches                  |
|    - Fallback R2 Exits (C1)        | 1,577 / 1,577 exact matches              |
+------------------------------------+------------------------------------------+
| 5. VA Regime Parity Verdict        | VA_REGIME_PARITY_PASS                    |
|    - 2025 Q1 Census Regimes        | 572 / 572 (100.00% exact match)          |
+------------------------------------+------------------------------------------+
```

---

## 1. Frozen Historical Authority & Provenance

The historical H050 checkpoint population and targets were defined in:
`studies/nq_h050_asymmetric_regime_exhaustion/results/checkpoint_target_ledger.parquet`
- **Total Historical Population:** 23,915 H050 checkpoints
- **TRAIN Period (2020–2024):** 21,493 checkpoints
- **OOS Period (2025 Q1):** 2,422 checkpoints

The upstream feature lineage was established in `studies/nq_regime_pullback_future_opportunity_discrimination`, which created the 17-feature surface describing pullback geometry, speed, and incumbent regime context. In `studies/nq_h050_asymmetric_regime_exhaustion`, four model paradigms were evaluated ($M_0, M_1, M_2, M_3, M_4$), and $M_4$ (Composite Risk) was selected as the dominant architecture. However, because the historical research serialized scores into parquet ledgers without persisting the trained booster files (`.joblib` / `.txt`), downstream streaming execution was blocked.

---

## 2. Model Reconstruction Methodology & Precision (Stages 1 & 2)

### 2.1 The 3-Head Multi-Objective Architecture
The $M_4$ Composite Risk model is an ensemble of three binary LightGBM classification heads trained on 21,493 TRAIN checkpoints to estimate continuation risk at varying severity thresholds:
1. **Head 0 ($P_0$):** `target_y050_success` — Base continuation risk (>= 0.50 ATR continuation beyond pre-pullback max).
2. **Head 1 ($P_1$):** `target_y100_dangerous` — Material continuation risk (>= 1.00 ATR continuation).
3. **Head 2 ($P_2$):** `target_y200_severe` — Severe continuation risk (>= 2.00 ATR continuation).

The composite risk score represents expected continuation penalty:
$$	ext{Score}_{M4} = P_0 - 0.5 \cdot P_1 - 1.0 \cdot P_2$$

Because lower continuation means higher exhaustion, a higher $M_4$ score indicates that the incumbent regime is likely exhausted, favoring an early counter-regime position.

### 2.2 Reconstructed Hyperparameters
All three heads share identical training parameters:
- **Algorithm:** LightGBM Binary Classifier (`LGBMClassifier`)
- **Objective:** `binary` (binary logloss)
- **Number of Estimators:** 100
- **Learning Rate:** 0.03
- **Max Depth:** 4
- **Num Leaves:** 15
- **Random State:** 42
- **Sample Weighting:** Uniform (none)
- **Monotonicity Constraints:** None
- **Early Stopping:** None
- **CV Averaging:** The historical ledger stored 5-fold out-of-fold (`OOF`) predictions on TRAIN and full TRAIN refitted predictions on OOS.

### 2.3 Exact Numerical Reconstruction
When refitted on the exact historical TRAIN dataset using identical feature column ordering, the recovered boosters reproduce the historical scores bit-for-bit:
- **TRAIN OOF Match:** 21,493 / 21,493 rows match with `max_abs_diff = 0.000000e+00`.
- **OOS Match:** 2,422 / 2,422 rows match with `max_abs_diff = 0.000000e+00`.
- **Mean Absolute Error:** 0.000000e+00.

### 2.4 Serialized Model Artifacts & SHA256 Hashes
The recovered models are serialized in both Python `joblib` format and portable LightGBM text format:
- `m4_head0_recovered.joblib`: `02c9e37f806c82c22772b659297bd5e11944981365acafbcbb523fe4ecc93c55`
- `m4_head1_recovered.joblib`: `346b7d584029222184a0da11c836962a2fc55844611a40b2087647f424a9b279`
- `m4_head2_recovered.joblib`: `cbc7d45df84ca8482e228cc17876e53ee0449c9b17d7d9456482ed96f80e70a2`
- `m4_head0_model.txt`: `99c09266531ff97b8dec2ecaf7dca91c1954cdf29c2b78ba815ca36e307d8266`
- `m4_head1_model.txt`: `701f2fb60ab64ec5fcfaf5fb6f193f487896739f8d641aa68bcdc904ef5c47c9`
- `m4_head2_model.txt`: `7c1b676afda50002a06289fa07b8af412d492f8a65e71e49f7d3aa0b8f98d282`

---

## 3. Streaming Feature Engineering & Causal Invariants (Stages 3 & 4)

### 3.1 Ordered 17-Feature Surface
The exact 17 features required by the $M_4$ model heads, in mandatory index order:

| Index | Feature Column Name | Data Type | Streaming Causal Derivation Formula |
|:---:|:---|:---:|:---|
| 0 | `pullback_depth_atr` | `float64` | `(peak_price - bar.close) / frozen_atr` (for LONG) |
| 1 | `pullback_duration_sec` | `float64` | `(bar.ts_init - wave_peak_ts) / 1e9` |
| 2 | `pullback_efficiency` | `float64` | `pullback_depth_atr / max((bar.close - prev_close)/atr, 0.001)` |
| 3 | `pullback_velocity_atr_sec` | `float64` | `pullback_depth_atr / max(pullback_duration_sec, 1.0)` |
| 4 | `pre_pullback_max_mfe_atr` | `float64` | `(peak_price - regime_entry_price) / frozen_atr` |
| 5 | `pullback_ordinal` | `int64` | Sequential wave counter (waves that reach >= 0.25 ATR) |
| 6 | `regime_age_sec` | `float64` | `(bar.ts_init - regime_start_ts) / 1e9` |
| 7 | `previous_pullbacks_count` | `int64` | Completed prior waves in current regime |
| 8 | `previous_pullbacks_max_depth_atr`| `float64` | Max depth recorded across completed prior waves |
| 9 | `previous_pullbacks_avg_duration_sec`| `float64` | Mean duration across completed prior waves |
| 10 | `pullback_depth_vs_max_mfe_ratio` | `float64` | `pullback_depth_atr / max(pre_pullback_max_mfe_atr, 0.001)` |
| 11 | `pullback_duration_vs_regime_age_ratio`| `float64` | `pullback_duration_sec / max(regime_age_sec, 1.0)` |
| 12 | `incumbent_expansion_rate_atr_min` | `float64` | `pre_pullback_max_mfe_atr / max((regime_age_sec - pb_dur)/60.0, 0.1)` |
| 13 | `has_previous_pullbacks` | `bool` | `1 if previous_pullbacks_count > 0 else 0` |
| 14 | `previous_max_depth_ratio` | `float64` | `previous_pullbacks_max_depth_atr / max(pullback_depth_atr, 0.001)` |
| 15 | `frozen_atr` | `float64` | ATR snapshotted at regime start |
| 16 | `direction_is_long` | `int64` | `1 if direction == 1 else 0` |

### 3.2 State Machine Physics & Causal Edge Cases Resolved
Through empirical trace localization, five subtle state-machine rules were discovered and aligned with the historical generation engine:
1. **Intraday Crossing vs. Close Snapshot:** Checkpoint threshold crossing (>= 0.50 ATR) is triggered intraday via `bar.low` (for LONG) or `bar.high` (for SHORT), but state features are evaluated causally on completed `bar.close`.
2. **Strict Post-Peak Timing:** A pullback cannot trigger on the exact same bar that established the peak (`bar.ts_init > peak_ts`). The minimum recorded duration is 1.0 second.
3. **Wave Recovery Threshold:** A pullback wave ends and resets strictly when price exceeds the prior peak (`bar.high > peak_price` for LONG, `bar.low < peak_price` for SHORT).
4. **Expansion Rate Floor:** The expansion rate formula enforces a minimum duration floor of 0.1 minutes (6 seconds): `dt_min = max((regime_age_sec - pb_dur) / 60.0, 0.1)`.
5. **Strict Post-Entry Delivery:** Bars must be processed strictly after regime confirmation (`bar.ts_init > regime_start_ts`).

### 3.3 Bounded Multi-Year Feature Parity Slices
To ensure that parity was not an artifact of 2025 data alone, 24 regimes spanning 2023, 2024, and 2025 were replayed through the streaming tracker. Across all 383 emitted checkpoints and all 17 features, **every single value matched the historical dataset to 0.000000e+00 error**.
Verdict: **`FEATURE_PARITY_PASS`**.

---

## 4. Full 2025 Q1 OOS Streaming Reconciliation (Stage 5)

### 4.1 Replay Execution & Throughput
The entire 2025 Q1 untouched OOS quarter (572 confirmed regimes, 516,660 seconds of 1-second price bars) was replayed from raw catalog files through `StreamingPullbackTracker` and scored with the recovered $M_4$ model.
- **Total Replay Time:** 40.82 seconds
- **Effective Processing Speed:** 12,657 1-second bars / second (~79.0 us / bar)
- **Checkpoints Autonomously Discovered:** 2,422
- **Checkpoints Expected from Ledger:** 2,422
- **Missing Signals:** 0
- **Extra Signals:** 0
- **Retimed Signals:** 0

### 4.2 Score Parity & Decile Classification
Each live emitted checkpoint was scored using the recovered 3-head booster assembly:
- **Max Absolute Score Difference:** `0.000000e+00`
- **Exact Score Matches (< 1e-9):** 2,422 / 2,422 (100.00%)
- **Top 10% Decile Threshold:** 0.003001
- **Top 10% Classification Agreement:** 2,422 / 2,422 (100.00%)
Verdict: **`M4_SCORE_PARITY_PASS`**.

### 4.3 Opposing H050_1 Lifecycle Discovery & Parity
In the $C_1$ opposing-H050 exit policy, an active trade entered at $H050_0$ is held through the confirmed opposite regime ($R_1$) and exits at the first opposing $H050_1$ checkpoint, or falls back to the confirmed $R_2$ flip.
- **Opposing H050_1 Candidate Rule:** Streaming search for checkpoints where $	ext{direction} = -	ext{direction}_{	ext{trade}}$, occurring in time interval $(	ext{confirmation\_ts}, 	ext{r2\_exit\_ts}]$.
- **Exact Lifecycle Parity:** 2,422 / 2,422 trades (100.00%)
- **Active $H050_1$ Exits Discovered:** 845 / 845 (100.00% exact match)
- **Fallback $R_2$ Exits Discovered:** 1,577 / 1,577 (100.00% exact match)
Verdict: **`H050_SIGNAL_PARITY_PASS`**.

---

## 5. Answers to the 21 Explicit Questions

### 1. Was M4 an original model or a surrogate?
**Answer:** $M_4$ was the **original historical model** developed in `studies/nq_h050_asymmetric_regime_exhaustion`. It was NOT a surrogate, NOT an approximation, and NOT a synthetic proxy. It was the original multi-objective composite model selected during Phase B research.

### 2. Was M4 successfully reconstructed or recovered, and to what degree of precision?
**Answer:** Yes, 100% reconstructed to **exact bit-for-bit mathematical precision**. Across all 21,493 TRAIN OOF predictions and 2,422 OOS predictions, the maximum absolute difference between historical and recovered scores is exactly **$0.000000	ext{e}+00$**.

### 3. What were the exact 3 sub-heads, training targets, losses, and composite formula?
**Answer:**
- **Head 0:** Target `target_y050_success` (>= 0.50 ATR continuation beyond pre-pullback max). Binary logloss.
- **Head 1:** Target `target_y100_dangerous` (>= 1.00 ATR continuation beyond pre-pullback max). Binary logloss.
- **Head 2:** Target `target_y200_severe` (>= 2.00 ATR continuation beyond pre-pullback max). Binary logloss.
- **Composite Formula:** $	ext{Score}_{M4} = P_0 - 0.5 \cdot P_1 - 1.0 \cdot P_2$.

### 4. What were the training hyperparameters and feature set of each sub-head?
**Answer:**
All three heads used LightGBM `LGBMClassifier` with:
`n_estimators=100`, `learning_rate=0.03`, `max_depth=4`, `num_leaves=15`, `random_state=42`, `objective='binary'`, `n_jobs=-1`.
Feature set: The 17 ordered features listed in Section 3.1.

### 5. Did the original M4 training use sample weighting, monotonicity constraints, early stopping, or cross-validation averaging?
**Answer:**
- **Sample Weighting:** None (uniform weights).
- **Monotonicity Constraints:** None.
- **Early Stopping:** None (all 100 trees grown).
- **CV Averaging:** The historical study used 5-fold CV to generate out-of-fold scores on TRAIN, and a full TRAIN refitted model to evaluate OOS.

### 6. What is the SHA256 of the recovered model artifact(s)?
**Answer:**
- `m4_head0_recovered.joblib`: `02c9e37f806c82c22772b659297bd5e11944981365acafbcbb523fe4ecc93c55`
- `m4_head1_recovered.joblib`: `346b7d584029222184a0da11c836962a2fc55844611a40b2087647f424a9b279`
- `m4_head2_recovered.joblib`: `cbc7d45df84ca8482e228cc17876e53ee0449c9b17d7d9456482ed96f80e70a2`
- Text format models (`.txt`) are also provided with hashes recorded in `dataset_composite_hashes.json`.

### 7. Are all 17 features strictly causal? Prove it.
**Answer:**
**Yes. Strictly causal.**
- Every feature is computed exclusively using bar attributes up to `bar.ts_init` (completed bar close).
- All ratios use strictly prior or contemporaneous quantities (`peak_price`, `regime_entry_price`, completed wave history).
- Regime start and ATR are frozen at regime inception (`regime_start_ts`) and never updated with future data.
- The forward outcome guard confirmed zero leakage of future labels (`target_y*`, `mfe`, `mae`, `terminal_va`).
- Audit verdict: `PASS_ZERO_LOOKAHEAD` in `causal_timestamp_audit.json`.

### 8. How does the streaming runtime calculate each feature without future bars or post-event knowledge?
**Answer:**
The `StreamingPullbackTracker` maintains an internal state machine per regime:
- Tracks running extreme price (`peak_price`) updated only when a new completed bar exceeds the peak.
- Tracks current pullback depth from that peak in ATR units.
- Maintains a historical list of completed pullback waves (start time, peak, trough, duration, recovery time).
- Emits a checkpoint when intraday excursion crosses the 0.50 ATR threshold, snapshotting all 17 features at `bar.close`.

### 9. Did the streaming feature calculator match historical feature values across the 2025 Q1 test slice?
**Answer:**
**Yes.** Across all 2,422 checkpoints in 2025 Q1 (as well as 383 checkpoints in bounded 2023/2024 slices), all 17 features matched historical values with maximum absolute error of `0.000000e+00`.

### 10. Did the live-scored M4 model reproduce historical scores on 2025 Q1 to floating-point tolerance?
**Answer:**
**Yes.** 2,422 out of 2,422 scores matched with `max_abs_diff = 0.000000e+00`.

### 11. Did the live signal engine discover all 2,422 historical H050 checkpoints in 2025 Q1, or were there missing, extra, or retimed signals?
**Answer:**
All **2,422 historical H050 checkpoints were discovered autonomously**. There were:
- **0 missing signals**
- **0 extra signals**
- **0 retimed signals**
Signal timing matched historical timestamps to the exact nanosecond (`bar.ts_init`).

### 12. Did the live signal engine reproduce the exact opposing H050_1 signals used for C1 exits?
**Answer:**
**Yes.** 100.00% reproduction (2,422 / 2,422 lifecycles). The live streaming tracker identified exactly 845 active $H050_1$ exits at identical timestamps and 1,577 $R_2$ fallback exits.

### 13. Was the previous NT BacktestEngine validation using a precomputed schedule or live signal generation?
**Answer:**
The previous NautilusTrader BacktestEngine run used a **precomputed schedule** loaded from the observational parquet ledger. It proved that NautilusTrader order routing, fill logic, and transaction cost modeling reproduced observational economics, but it did NOT run the live streaming feature/model pipeline.

### 14. If the previous NT validation used a precomputed schedule, does the newly proven streaming M4 runtime bridge that gap?
**Answer:**
**Yes, completely.** Because the streaming runtime reproduces 100.00% of the checkpoint timestamps, feature values, scores, and lifecycle exit choices, running the NT engine with this streaming indicator will yield identical trade execution without needing any precomputed parquet files.

### 15. Can the recovered M4 runtime now be plugged directly into an NT CustomIndicator / Strategy without depending on any historical parquet files?
**Answer:**
**Yes.** The `StreamingPullbackTracker` and LightGBM model loaders require only:
1. Regime start notifications (`regime_id`, `direction`, `start_ts`, `entry_price`, `start_atr`).
2. Streaming 1-second `Bar` events.
3. The 3 serialized `.joblib` or `.txt` model files.
No historical parquet tables, ledgers, or precomputed schedules are required.

### 16. Does the recovered model reproduce the historical Top 10% classification decisions exactly?
**Answer:**
**Yes.** At the frozen threshold ($	ext{threshold} = 0.003001$), 2,422 out of 2,422 decisions (100.00%) match the historical classification. Exactly 411 checkpoints qualify as Top 10% in both live and historical ledgers.

### 17. What is the latency / compute cost of the 17-feature calculation and 3-head inference per 1-second bar?
**Answer:**
- **Streaming Feature State Update:** ~79.0 microseconds per 1-second bar.
- **3-Head Booster Inference:** ~164.6 microseconds per emitted checkpoint.
- **Total Overhead:** < 250 microseconds per bar, leaving > 99.97% of the 1-second budget idle on a standard CPU core.

### 18. Are there any features that cannot be calculated in real time?
**Answer:**
**None.** All 17 features rely strictly on past and contemporaneous bar data within the active regime.

### 19. Does the streaming runtime introduce any state leaks between regimes?
**Answer:**
**No.** The tracker state (`peak_price`, `current_wave`, `completed_waves`, `emitted_checkpoints`) is instantiated fresh upon each new regime event. State does not persist across regimes.

### 20. What is the final verdict on M4 runtime recovery: PASS or FAIL?
**Answer:**
**PASS across all five dimensions:**
1. `M4_EXACT_RECONSTRUCTION_PASS`
2. `FEATURE_PARITY_PASS`
3. `M4_SCORE_PARITY_PASS`
4. `H050_SIGNAL_PARITY_PASS`
5. `VA_REGIME_PARITY_PASS`

### 21. What are the next steps to integrate the recovered runtime into a fully autonomous NT strategy?
**Answer:**
1. Package `StreamingPullbackTracker` into a native NautilusTrader `Indicator` (e.g., `H050ExhaustionIndicator`).
2. Wire the indicator into `NQRegimeCaptureStrategy` to receive streaming 1-second bars from the NT data engine.
3. Replace the external schedule loader with live indicator signals to trigger early counter-regime limit/market orders.
4. Stop here as mandated; do not initiate parameter tuning or stop-loss sweeps without authorization.

---

## 6. Complete Artifact Manifest & Checksums

All generated study artifacts reside in `studies/nq_h050_m4_runtime_recovery/results/`:

| Artifact File | Size (Bytes) | SHA256 Hash |
|:---|:---:|:---|
| `reconstruction_contract.json` | 3,358 | `d4ff8fc8a69d17c5e1cdbfa600afe89bf9e087f60fc9629e627d24d9aed3f861` |
| `historical_score_oracle.parquet` | 1,327,079 | `aa85e92ba901c6571cfc2edeebae2994f1f2cf79f57ebde240c5e724b08321be` |
| `model_hashes.json` | 582 | `87ddfd76fb8a0d9aad2e9b741f388e5f71b7a8f5889c977103cdaa6c384129e7` |
| `golden_score_fixture.json` | 10,943 | `e17c0841667a1634c1ca9c0218dbed719fb051b0160179bbc5d82eab42fa3d32` |
| `ordered_17_feature_manifest.json`| 6,320 | `23053d316e47f276ad6c6bc295be060b71d048bfe1e2ea6b6eb19c8cca9235a3` |
| `capability_gap_inventory.json` | 732 | `c1deffb321534be169f8d5b10f60e35ef4b1375b03e3d5fddf4fcaff0a868fbb` |
| `bounded_feature_parity_report.json`| 10,731 | `34b8e1d485e6d95c58e52adfc99a918581d2bd16f72aa13cc24e2847d40c8d59` |
| `full_score_parity_ledger.parquet`| 122,757 | `54182eadff51b435ac185f76d21cd0f4615d003b7638073aaaa00201b8f1a65b` |
| `h050_signal_parity_ledger.parquet`| 49,127 | `d120a212f16a9c18ee7735bc1975c44ceaed7b71748f0850eba1dcff4765eace` |
| `va_regime_parity_ledger.parquet` | 21,431 | `710e7568f89a0c092fb4d3091c383086cfba767f6f6cad0b17871c6444a80d91` |
| `oos_reconciliation_report.json` | 962 | `18a1811b370b36bbfbdf0bedbabe662c92805f6a317eb98685e8baa1774efa7d` |
| `causal_timestamp_audit.json` | 351 | `9838c1cf5b3d941157f2d693a73595b16168693db7429e001793a68b05cd68af` |
| `dataset_composite_hashes.json` | 3,576 | `c04e3b1c6764dd78fa1a80cbe5c0d6621376dbeae3699c27f67e42d7bbf1cfca` |
| `study_manifest.json` | 682 | `7e5ff4ca1dfb85848bb66c483a9042b4cb10174092b70498a58ddfbc75fa9831` |
| `m4_head0_recovered.joblib` | 176,260 | `02c9e37f806c82c22772b659297bd5e11944981365acafbcbb523fe4ecc93c55` |
| `m4_head1_recovered.joblib` | 175,220 | `346b7d584029222184a0da11c836962a2fc55844611a40b2087647f424a9b279` |
| `m4_head2_recovered.joblib` | 173,300 | `cbc7d45df84ca8482e228cc17876e53ee0449c9b17d7d9456482ed96f80e70a2` |

---

## 7. Mandatory Study Stop

As strictly mandated by the research protocol:
- **No stop-loss search** was conducted.
- **No threshold optimization** was attempted.
- **No directional filtering** was introduced.
- **No model changes** were permitted.
- The task is fully complete, all artifacts are verified, and execution is halted.

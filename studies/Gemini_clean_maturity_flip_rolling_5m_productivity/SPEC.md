# SPEC: Gemini_clean_maturity_flip_rolling_5m_productivity

**Study:** `Gemini_clean_maturity_flip_rolling_5m_productivity`  
**Status:** frozen design, pre-implementation  
**Risk Tier:** `2`  
**Execution Runtime:** `NautilusTrader` (`strategies.flip_prediction_collector.FlipPredictionCollector`)  
**Lineage:** Derived from `studies/Codex_clean_maturity_flip_rolling_5m_productivity/SPEC.md`  
**Clean Lineage Reset Start:** `2026-08-15T00:45:00Z`

---

## 1. Decision & Research Question

Determine whether causal structural geometry (27 features) and rolling five-minute productivity (8 features) add incremental predictive power to the existing frozen reference base models (25 features) across regime maturity stages without degrading opposite-direction diagnostic economics. This is a model training, stratification, and evaluation study.

---

## 2. Split and Lineage

- **TRAIN:** `[2021, 2022, 2023]` (Model training on frozen feature allocations)
- **OOS / DEV:** `[2024]` (Untouched out-of-sample evaluation, locked until feature & model freeze)
- **UNUSED:** `[2025]`
- **SEALED / PROHIBITED:** `[2026]`

Baseline models use the frozen reference Top-25 feature contracts (`BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1` for SHORT and `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2` for LONG). Collection is strictly scoped to the 60-feature union (25 Base Top-25 + 27 Structural + 8 Rolling).

### Lineage Quarantine Ledger
Prior premature dry-run (`runs/20260815_003408_...`, year 2024) is quarantined in `audit/invalidated_runs.json` with status `INVALIDATED`. It is strictly excluded from training and evaluation. Within the current valid lineage starting at `2026-08-15T00:45:00Z`, 2024 has not been read prior to freeze.

---

## 3. Population and Target

- **Session:** RTH (08:30 - 15:00 CT)
- **Instrument:** NQ.XCME
- **Cadence:** Exact 5s candidate grid ($T = \text{regime\_start} + k \times 5\text{s}$)
- **Established Regime Qualification Gate:**
  - `regime_age_seconds > 120`
  - `running_mfe_atr >= 1.0`
  - `new_progress_windows >= 2`
  - `retained_mfe_ratio >= 0.5`
- **Directions:**
  - Bullish prevailing regime -> SHORT (flip to bearish)
  - Bearish prevailing regime -> LONG (flip to bullish)
- **Fit Target:** Prevailing 1m EMA flip occurring in `(T, T+300s]`.

---

## 4. Feature Blocks & Stratification

### Feature Blocks
- **Model A (Baseline Top-25, 25 Features):** Frozen reference Top-25 features.
- **Model B (Baseline + Structural, 52 Features):** Model A + 27 audited causal structural geometry features.
- **Model C (Baseline + Structural + Rolling Productivity, 60 Features):** Model B + 8 rolling 5m productivity features:
  - Evaluated on completed 1s bars in `[T-300s, T]`.
  - Bullish anchor: exact causal low at $T-300\text{s}$; Bearish anchor: exact causal high at $T-300\text{s}$.
  - Normalizer: current-regime-start 1m ATR.
  - No boundary search (emit unavailable if exact anchor missing).

### Maturity Stratification Buckets
1. **Young / Mid-Maturity:** `300s - 600s`
2. **Mature:** `600s - 900s`
3. **Late Maturity:** `900s - 1800s`
4. **Extrapolation (Descriptive):** `>= 1800s`

---

## 5. Evaluation Matrix & Outcome Labels

- **18 Directional Model Cells:** $(A, B, C) \times (\text{SHORT}, \text{LONG}) \times (300\text{--}600\text{s}, 600\text{--}900\text{s}, 900\text{--}1800\text{s})$.
- **9 Pooled Descriptive Cells:** $(A, B, C) \times \text{bucket}$ (descriptive diagnostics only).
- **Outcome Labels:**
  - `R1`: Broad clean improvement
  - `R2`: Young-regime improvement
  - `R3`: Timing only
  - `R4`: Economic tail only
  - `R5`: Rolling block adds nothing
  - `R6`: No clean incremental information
  - `ABORT`: Any selection, causal, coverage, audit, or seal failure.

---

## 6. Deliverables Manifest

| Path | Required contents / exact checks |
|---|---|
| `artifacts/spec_contract_map.json` | 100% SPEC clause machine mapping verification. |
| `artifacts/phase0_source_manifest.json` | Verified candidate inventory from central registry, definition/AST hashes, quarantined runs ledger, explicit proof that F3 tables, 2024+, 2025, 2026 were not used. |
| `artifacts/train_collection_manifest.json` | 2021–2023 TRAIN-only NT collection manifest. |
| `artifacts/frozen_feature_manifest.json` | Separate SHORT and LONG Top-25 feature lists frozen on TRAIN only with `2024_not_read_in_current_valid_lineage_before_freeze: true`. |
| `artifacts/preprocessing_manifest.json` | Preprocessing / scalers fitted on TRAIN only. |
| `artifacts/model_manifest.json` | Models A, B, C fitted and frozen on TRAIN only. |
| `artifacts/oos_unlock.json` | Cryptographic dependency-chain token authorizing 2024 OOS evaluation. |
| `artifacts/score_manifest.json` | 2024-only score partitions, 18 directional cells, PR AUC, ROC AUC, Brier. |
| `artifacts/decile_manifest.json` | 2024 OOS directional bucket deciles, confirmation rates, MAE, MFE diagnostics. |
| `artifacts/validation.json` | Fail-closed checks for 2021-2023 TRAIN, 2024 OOS, no 2025/2026 access. |
| `artifacts/result_seal.json` | SHA-256 bindings across all artifacts and manifests. |
| `STUDY_REPORT.md` | Final R1-R6/ABORT label and directional performance matrix. |

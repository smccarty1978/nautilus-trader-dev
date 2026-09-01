# PHASE C FREEZE CARD — STUDY HANDOFF STATE

```
========================================================================================
STUDY: regime_transition_target_before_stop_v1
FROZEN AT: PHASE_C_COMPLETE
NEXT PHASE: PHASE_D_MODELING (NOT AUTHORIZED)
DATE (UTC): 2026-09-01
========================================================================================
```

## 1. Study Identity & Chronology
- **Study ID:** `regime_transition_target_before_stop_v1`
- **Spec Hash (`spec_sha256`):** `1f1e6f9e4eda502b3d4b538ffefb774564eb33304ff5b5b7dd388ed8a89e9df8`
- **Seal Composite SHA-256:** `4dcdc0307cbf90e0ef0d16bb1f7d805cf6770857d7cfcd649f2019976c0c8f7f`
- **Seal Status:** `PREEXEC_AUDIT_SEAL_VALID`
- **TRAIN Chronology:** `[2021, 2022, 2023]` ($N = 1,387,411$ candidates)
- **OOS Chronology (2024):** `LOCKED` (Zero access, zero files opened)
- **Prohibited Chronology:** `[2025, 2026]`

---

## 2. Authoritative Target Dataset
- **Path:** `studies/regime_transition_target_before_stop_v1/_work/train_merged_collection/phase_c2_reconciled_targets.parquet`
- **SHA-256:** `21d598a823fd6430459380b3c9f6a75f2b90b61048d78cd7ff840b3f54218b0e`
- **Row Count:** `1,387,411`
- **Target Arms Evaluated:**
  1. `TP 1.0 / SL 0.5`: $N_{\text{resolved}} = 1,320,608$, $P(\text{TP} \mid \text{resolved}) = 32.94\%$, $P(\text{TIMEOUT}) = 3.80\%$
  2. `TP 1.0 / SL 1.0`: $N_{\text{resolved}} = 1,152,884$, $P(\text{TP} \mid \text{resolved}) = 50.13\%$, $P(\text{TIMEOUT}) = 15.90\%$
  3. `TP 1.0 / SL 1.5`: $N_{\text{resolved}} = 962,625$, $P(\text{TP} \mid \text{resolved}) = 64.04\%$, $P(\text{TIMEOUT}) = 29.61\%$

---

## 3. Approved Target Semantics (Phase C.2 & C.3)
- **Favorable First:** $y = 1.0$ (`POSITIVE`)
- **Adverse First:** $y = 0.0$ (`NEGATIVE`)
- **300s Horizon Expiry:** $y = \text{null}$, `censor_reason = TIMEOUT` (`CENSORED`)
- **Session End:** $y = \text{null}$, `censor_reason = SESSION_END` (`CENSORED`)
- **Same-Bar Touch:** $y = \text{null}$, `censor_reason = AMBIGUOUS_SAME_BAR_TOUCH` (`CENSORED`)
- **Source Gap:** $y = \text{null}$, `censor_reason = GAP` (`CENSORED`)
- **Data End:** $y = \text{null}$, `censor_reason = DATA_END` (`CENSORED`)

---

## 4. Phase C Audit & Reconciliation Summary
- **Phase C.2 Target Feasibility:** `PASS` (All accounting identities hold; cross-arm monotonicity passes 100%)
- **Phase C.3 Differential Reconciliation:** `PASS` (All non-timeout deltas diagnosed to C1 script defects; independent oracle agreement = 100.00% [639/639])
- **Recollection Required:** `false`
- **Feature & Population Immutability:** `PASS` (13 Model-C canonical features, 1,387,411 rows unchanged)
- **Pre-Execution Audits:** Pass 05 Causal (`CLEAR`) & Pass 05 Contract (`CLEAR`)

---

## 5. Phase D Modeling Status
- **Next Phase:** `PHASE_D_MODELING`
- **Phase D Authorization:** `false` (Awaiting explicit study owner authorization)
- **Execution State:** All study background tasks terminated; zero active processes.

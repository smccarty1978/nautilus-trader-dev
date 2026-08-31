<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker", "critical": 0, "warning": 0, "note": 0, "study": "regime_transition_target_before_stop_v1", "audited_execution_composite_sha256": "74a27cbe644b9ae538b86a6e492d6551f88e30f3bb9fec2b289d3df5510704ee"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit — Pass 01

**Study:** `regime_transition_target_before_stop_v1`  
**Auditor:** `contract-checker`  
**Audited Execution Composite:** `74a27cbe644b9ae538b86a6e492d6551f88e30f3bb9fec2b289d3df5510704ee`  
**Date:** 2026-08-31  
**Verdict:** CLEAR  

---

## 1. Governance & Chronology Review

- [PASS] **Chronology Partitioning:**
  - TRAIN years: `[2021, 2022, 2023]`
  - DEV / OOS slot: `[2024]` (locked until explicit OOS authorization post-TRAIN freeze)
  - Prohibited years: `[2025, 2026]`
  - Disjoint partitions verified.
- [PASS] **Deliverables Contract:** `config/deliverables_contract.json` is generated, rendered in `SPEC.md`, and validated.
- [PASS] **Population Contract:** Qualified prevailing 1m regime checkpoint population (cadence=5s, age_gate>=120s, running_mfe_atr>=1.0, new_progress_windows>=2, retained_mfe_ratio>=0.5, RTH).
- [PASS] **Target Contract:** Three predefined ordered-barrier arms bound under `required_forward_outcomes`:
  - `barrier_tp_1_0_sl_0_5` (TP 1.00 / SL 0.50 ATR, 300s)
  - `barrier_tp_1_0_sl_1_0` (TP 1.00 / SL 1.00 ATR, 300s)
  - `barrier_tp_1_0_sl_1_5` (TP 1.00 / SL 1.50 ATR, 300s)
- [PASS] **Feature Contract:** 13 canonical raw causal features from Model-C verified against canonical registry.
- [PASS] **Arm B Status:** Diagnostic reuse is `DISABLED_PENDING_REUSE_AUTHORITY` for baseline Phase B execution.

---

## 2. Requirement Compliance Table

| Section | Check | Verdict | Evidence |
|---|---|---|---|
| C4 | TRAIN/OOS Separation | PASS | Chronology strictly partitions 2021-2023 (TRAIN), 2024 (DEV/OOS locked), 2025-2026 (prohibited). |
| D1 | Feature Invariants | PASS | 13 canonical features verified against canonical definition universe. |
| D2 | Model Family & Seeds | PASS | LightGBM binary classifier, fixed seed 42, deterministic=true. |
| E1 | Disposition / Censoring | PASS | Explicit POSITIVE, NEGATIVE, TIMEOUT, SESSION_END, GAP, and AMBIGUOUS dispositions. |
| E2 | Independent Replay Oracle | PASS | Independent `target_replay_oracle.py` replay passes 30/30 unit tests with 0 mismatches. |

---

## 3. Verdict

**CLEAR.** Zero critical findings, zero warnings, zero notes. All governance contracts satisfied.

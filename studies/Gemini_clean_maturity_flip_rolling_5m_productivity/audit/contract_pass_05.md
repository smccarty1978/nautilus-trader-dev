# Contract & Deliverables Audit Report (Pass 05)

**Study:** `Gemini_clean_maturity_flip_rolling_5m_productivity`  
**Date:** `2026-08-15T01:40:00Z`  
**Verdict:** `CLEAR` (0 Critical, 0 Warning)  
**Audited Scope:** Execution Code Hash Verification, Output Manager Strict SHA-256 Validation, Deliverables Manifest, and Research Decision Contract Fidelity.

---

## 1. Research Decision Contract Fidelity

| Requirement | Contract Clause | Implementation Status | Verdict |
|---|---|---|---|
| Baseline Model Contract | `frozen_top25` (25 features) | `BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1` & `BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2` | `PASS` |
| Feature Selection Mode | `mode: none` | No unapproved discovery or 502-ranking loops | `PASS` |
| Scoped Feature Union | 60 unique features | 25 Base Top-25 + 27 Structural + 8 Rolling | `PASS` |
| Exact Hash Guard | SHA-256 enforcement on persistence | `output_manager.py` verifies exact emitted feature order & hash | `PASS` |
| Model Arms | A (25), B (52), C (60) | Mapped in `study.yaml`, `SPEC.md`, and `research_decision.yaml` | `PASS` |
| Chronology Partition | Train `[2021-2023]`, Dev `[2024]`, Prohibited `[2025, 2026]` | Strictly partitioned in `study.yaml` and `run_plan.py` | `PASS` |
| Clean Lineage Reset | Declared at `2026-08-15T00:45:00Z` | Invalidated 2024 dry-run quarantined in `invalidated_runs.json` | `PASS` |

---

## 2. Feature Set Arithmetic Verification

- SHORT Top-25 Count: **25**
- LONG Top-25 Count: **25**
- SHORT / LONG Overlap: **25**
- Structural Regime Geometry: **27**
- Rolling 5m Productivity: **8**
- Overlap with Base: **0**
- Total Scoped Collector Features: **60**
- SHA-256 Hash: `2a744cfa3acfa437ae0ff8219c56451e176a170ae83450c52b8ca42842b0cba5`

---

## 3. Pass 05 Summary
- Blocking Findings: 0
- Warnings: 0
- Audited Execution Composite SHA-256: `15ee196de2f050dc201431793e860fe6852377080b3216cd761cb14b3541d4e3`
- Final Verdict: **CLEAR**

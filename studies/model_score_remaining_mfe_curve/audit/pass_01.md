# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T00:00:00-05:00
**Scope:** `studies/model_score_remaining_mfe_curve/{SPEC.md,config/study.yaml,implementation/run.py}`; direct imports `studies/armed_fade_score_path_progression/implementation/walks.py` and `studies/model_driven_entry_exit_discovery/implementation/{candidates.py,engine.py}`
**Scope hash:** `9b5b1e87860b5a4b1a0685bf94bec45677dcf8b8226f0855a23d0e946ff16137`
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 1
- Warning: 0
- Note: 0
- Verdict: **BLOCK — do not execute**

The pre-execution causal lint is clean (`audit/lint.json`: 0 critical, 0 warning), but it cannot detect an unbounded input scan.

## Critical findings

### [G1 / sealed-population] `studies/model_score_remaining_mfe_curve/implementation/run.py:127`; `studies/model_driven_entry_exit_discovery/implementation/engine.py:144-149` — the regime table reads sealed 2026 data

`run()` bounds score and 1-second path loads to 2021–2025, then calls `load_regimes()` with no year argument. That loader scans and collects every row of `canonical_regimes_all.parquet`, including 2026. This directly contradicts the frozen study contract's “does not … access 2026” guarantee and makes `sealed_2026_accessed: false` at `run.py:150` false by construction.

Concrete failure path: a 2025 candidate near the end of the sample invokes `next_start_after` in `walks.py:151` or `run.py:48`; its resolver searches the in-memory, all-year regime index. Even where the own-session horizon happens to clamp the resulting outcome before a 2026 timestamp, the sealed data have already been accessed and can affect boundary resolution if a session/horizon invariant changes. The study cannot claim an isolated 2021–2025 population.

**Required remediation before execution (do not apply in this audit):** make the regime loader’s year restriction explicit and enforce the sealed-year invariant on all three inputs (scores, paths, and regimes).

## Clean checks

- A1: score selection uses `checkpoint_decision_ns`; path replay uses accepted close-time `path_init_ns`, not an open-time event timestamp (`candidates.py:30,52`; `engine.py:52,115-126`).
- A5/F3/F4: RTH session close is computed after conversion to named `America/Chicago`, preserving DST-aware 15:00 local semantics (`engine.py:126-132`).
- B1/B4/B5/B6/B7: no centered window, negative shift, fill, backward fill, temporal merge, or full-sample normalization occurs in the new selection path (`run.py:61-81`).
- B2/B3/B9: candidates are selected from true, in-domain score dispatch rows, time-sorted by decision timestamp; the checkpoint’s own frozen ATR and reference mark are passed to both outcome measurements (`candidates.py:39-67`; `run.py:123,130-142`).
- C1/C2: future regime/path data is used only after candidate selection to measure confirmation and remaining MFE, beginning strictly after the score checkpoint (`run.py:40-54,127-142`; `walks.py:146-172`).
- F1/F2/G2: RTH-only market rows and same-session `day_close_ns` bounds prevent path windows from stitching 14:59:59 to the next session (`engine.py:113-140`; `run.py:44-50`; `walks.py:68-74,146-163`).
- H1/H2/H4: inherited stop logic tests excursion high/low on 1-second bars and resolves a touch at the following 1-second open, never at the trigger price (`walks.py:77-111,167-191`).
- Confirmation/opposing-flip semantics: the inclusive resolver makes a flip stamped at the same decision second future to that decision under the documented 1s-before-1m dispatch convention; replay begins at the first strictly later path bar (`engine.py:77-105`; `walks.py:146-172`; `run.py:44-50`).

## Compliance matrix

| Rule | Status | Basis |
|---|---|---|
| A1 | PASS | Close/decision-time canonical fields used. |
| A2 | N/A | This scope does not construct raw `BarType` data. |
| A3 | N/A | No Nautilus strategy callback in scope. |
| A4 | N/A | No timer/event callback in scope. |
| A5 | PASS | Named-zone session conversion; no resample. |
| B1 | PASS | No centered rolling computation. |
| B2 | PASS | Selection is time-sorted, first qualifying true dispatch. |
| B3 | PASS | ATR is the selected checkpoint field. |
| B4 | PASS | No negative lag in feature/selection path. |
| B5 | PASS | No fill operation. |
| B6 | PASS | No time-series join/merge. |
| B7 | PASS | Frozen levels/ATR; no fitted scaler. |
| B9 | PASS | Dispatch-based selection has explicit 600s age gate. |
| B10 | N/A | No multi-timeframe tracker. |
| C1 | PASS | Future data is outcome-only. |
| C2 | PASS | Outcome origin is the selected score timestamp. |
| C3 | N/A | Descriptive study; no train/test split. |
| C4 | N/A | Contract-checker scope. |
| D1–D4 | N/A | Contract-checker scope. |
| E1–E5 | N/A | Contract-checker scope. |
| F1 | PASS | RTH canonical input and close-time fields. |
| F2 | PASS | Per-entry same-session clamp. |
| F3 | PASS | Explicit `America/Chicago`. |
| F4 | PASS | Named timezone, no fixed UTC offset. |
| G1 | CRITICAL | Unbounded regime scan accesses sealed 2026 data. |
| G2 | PASS | No overnight path stitch; no price forward fill. |
| G3 | N/A | No 1s-to-1m resampler in scope. |
| G4 | N/A | No indicator is calculated from raw volume/ticks here. |
| H1 | PASS | Stop excursion is based on high/low. |
| H2 | PASS | Stop replay is 1-second. |
| H3 | N/A | This study selects one observation per view/regime, not re-entries. |
| H4 | PASS | Stop fill uses the next same-session open. |

## Referred to contract-checker

None.

---

*Audit complete. Findings reflect read-only static analysis; no pipeline was executed.*

# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T00:00:00-05:00
**Scope:** `studies/model_score_remaining_mfe_curve/{SPEC.md,config/study.yaml,implementation/run.py}`; direct imports `studies/armed_fade_score_path_progression/implementation/walks.py` and `studies/model_driven_entry_exit_discovery/implementation/{candidates.py,engine.py}`
**Scope hash:** `8f569de0d8f55091b10aae915a36542749e9789f9fc5db6c1cafa3386393aeb7`
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS — causal execution permitted**

The pre-execution causal lint remains clean (`audit/lint.json`: 0 critical, 0 warning). The summary-statistic correction in `run.py:100-132` does not change candidate selection, timestamps, feature construction, or path measurement.

## Prior finding adjudication

### [G1 / sealed-population] — FIXED

Pass 01 found that `run.py` called the unbounded `engine.load_regimes()`. The runner now calls `load_regimes_pre_2026()` at `run.py:143`. That loader applies the explicit `entry_year in [2021, 2022, 2023, 2024, 2025]` predicate before collection, sorts by decision timestamp, and rejects an empty or non-strictly ordered timeline (`run.py:24-37`). Scores and 1-second paths remain separately bounded to the same years (`run.py:139-143`). The sealed 2026 regime population is no longer collected or passed to a resolver.

## Clean checks

- A1: candidate decisions use `checkpoint_decision_ns`; path replay uses the accepted close-time `path_init_ns` field (`candidates.py:30,52`; `engine.py:52,115-126`).
- B1–B7/B9: selection uses sorted, true in-domain score dispatches and fixed probability levels; no centered window, negative lag, fill, temporal merge, fitted normalizer, or future score/path is used to select candidates (`candidates.py:39-67`; `run.py:77-97`). The ATR and mark are copied from the selected checkpoint (`run.py:146-158`).
- C1/C2: confirmation and remaining-MFE replay starts strictly after the selected checkpoint and is outcome-only (`run.py:56-70,143-158`; `walks.py:146-172`). C3 is not applicable: this is a descriptive, non-training study.
- F1–F4/G2: named `America/Chicago` conversion and entry-session bounds prevent any RTH-only path window from spanning the overnight gap (`engine.py:113-140`; `run.py:60-66`; `walks.py:68-74,146-163`).
- H1/H2/H4: inherited stop detection uses 1-second high/low excursions and fills at the next same-session open; it neither detects on close nor credits a trigger price (`walks.py:77-111,167-191`). H3 is not applicable because this study does not simulate re-entry episodes.
- Same-second confirmation/opposing-flip handling remains causal: the inclusive resolver treats a regime flip stamped at the decision second as subsequent to the score decision under the documented 1s-before-1m dispatch convention, while the 1-second path begins strictly later (`engine.py:77-105`; `walks.py:146-172`; `run.py:60-66`).

## Compliance matrix

| Rule | Status | Basis |
|---|---|---|
| A1 | PASS | Canonical decision/close-time fields. |
| A2–A4 | N/A | No raw `BarType`, strategy callback, or timer in scope. |
| A5 | PASS | Explicit named-zone conversion; no resampling. |
| B1–B7 | PASS | Causal dispatch selection; no listed leak mechanism. |
| B9 | PASS | Explicit dispatch and 600-second age semantics. |
| B10 | N/A | No multi-timeframe tracker. |
| C1–C2 | PASS | Future paths are labels/outcomes only. |
| C3 | N/A | No model split. |
| C4 | N/A | Contract-checker scope. |
| D1–D4 | N/A | Contract-checker scope. |
| E1–E5 | N/A | Contract-checker scope. |
| F1–F4 | PASS | RTH, own-session clamp, named zone/DST safe. |
| G1 | PASS | All three input populations explicitly limited to 2021–2025. |
| G2 | PASS | No stale fill or overnight stitch. |
| G3–G4 | N/A | No resample or raw-volume indicator in scope. |
| H1–H2 | PASS | High/low, 1-second path resolution. |
| H3 | N/A | No re-entry replay. |
| H4 | PASS | Next-bar-open stop fill. |

## Referred to contract-checker

None.

---

*Audit complete. Findings reflect read-only static analysis; no pipeline was executed.*

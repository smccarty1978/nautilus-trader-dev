# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T14:20:12-05:00  
**Scope:** `studies/model_score_remaining_mfe_curve/{SPEC.md,config/study.yaml,implementation/run.py}`; direct replay and source-contract dependencies `studies/armed_fade_score_path_progression/implementation/walks.py`, `studies/model_driven_entry_exit_discovery/implementation/{candidates.py,engine.py}`, and `studies/regime_complete_canonical_store/implementation/{writer.py,consolidate.py}`  
**Scope hash:** `a76af06d68524c921f9cf49d2b69adbce357213097b3bda2518857356d8433d2`  
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS — causal rerun accepted**

## Prior verdict adjudication

### Pass 04 PASS — STILL VALID

No prior finding was open. The Pass 04 findings of no causal defect remain valid: the unchanged candidate selector is chronological and outcome-blind, and the shared one-second replay continues to start strictly after the selected checkpoint, resolve same-second regime flips as future events under the documented dispatch order, and clamp every path to its own RTH session.

## Changed-scope review

The validation-parity update is after all selection and forward measurement: `run.py:150-164` builds the complete measured population, `run.py:165-169` writes the summaries, and `run.py:173-194` merely compares three independent first-qualified counts with frozen reference counts. The added expected/observed values neither select candidates nor alter threshold, ATR, confirmation, stop, session, or remaining-MFE computation. The current generated validation record reports exact parity (`results/validation_report.json`) and positive candidate ATRs.

## Clean checks

- **Timestamp causality:** candidate decisions use `checkpoint_decision_ns`; one-second replay uses completed-bar `path_init_ns` and begins strictly after the decision (`run.py:151-153`, `engine.py:52-67`, `walks.py:146-151`). The canonical writer explicitly defines path rows as completed one-second bars and maps `path_decision_ns` to `path_init_ns` (`writer.py:100-105,123-145`).
- **Sealed 2026 containment:** score, path, and regime sources independently filter to 2021–2025 before collection (`run.py:24-37,144-148`, `candidates.py:45-52`, `engine.py:113-121`); all subsequent horizons are intraday and cannot reach a later calendar year.
- **First-qualified selection:** source checkpoints are sorted by decision time, age-gated before selection, and the independent and armed-later views take the first qualifying row per regime without reading any path or outcome (`run.py:73-102`, `candidates.py:39-71`).
- **Stop and confirmation timing:** confirmation and the 1-ATR stop inspect 1-second high/low excursions; an adverse touch fills only at the next same-session open, never at the trigger price (`walks.py:77-111,146-191`). Equal-second confirmation/stop ties are resolved adversely (`walks.py:174-185`).
- **Session cutoff:** RTH is calculated with `America/Chicago` from the completed-bar timestamp, exactly over `[08:30, 15:00)`, and both confirmation and MFE clamp to the entry session's exclusive endpoint (`writer.py:42-61`, `engine.py:108-141`, `walks.py:68-74,150-163`, `run.py:60-70`).
- **Remaining-MFE horizon:** MFE begins only after entry, uses high for longs and low for shorts, is intentionally not stop-censored, and ends at the earlier next opposing confirmed flip or own session close (`run.py:56-70`).

## Compliance matrix

| Rule | Status | Basis |
|---|---|---|
| A1 | PASS | Completed-bar decision timestamps are used throughout the selection/replay chain. |
| A2 | N/A | No raw BarType construction is in this scope. |
| A3-A4 | N/A | No live strategy callback or timer is in scope. |
| A5 | PASS | Named-zone conversion is explicit; no resampling occurs here. |
| B1-B7 | PASS | No centered/negative-lag feature transform, future fill, merge, or global normalization participates in selection. |
| B9-B10 | N/A | No feature tracker or multi-timeframe variant is implemented in this study. |
| C1 | PASS | Forward one-second paths are outcome measurements only, after candidate selection. |
| C2 | PASS | Measurement origin is the selected checkpoint and all replay starts strictly after it. |
| C3 | N/A | No model training or split is performed. |
| C4 | N/A | Contract-checker scope. |
| D1-D4 | N/A | Contract-checker scope. |
| E1-E5 | N/A | Contract-checker scope. |
| F1 | PASS | RTH classification uses close-time `path_init_ns`. |
| F2 | PASS | Every path is bounded to its entry session. |
| F3-F4 | PASS | `America/Chicago` is used for year and RTH boundaries, preserving DST handling. |
| G1 | PASS | Source writer identifies `NQ.XCME.v.0`; this study reads the accepted canonical store. |
| G2 | PASS | No stale-price forward fill or cross-session stitching occurs. |
| G3-G4 | N/A | No resampling or volume-based indicator is implemented in scope. |
| H1 | PASS | Stop detection uses one-second highs/lows. |
| H2 | PASS | Stop path resolution is one second. |
| H3 | N/A | This is a one-observation-per-regime descriptive measurement, not a re-entry simulator. |
| H4 | PASS | Stop outcomes use the next same-session bar open; final-bar fallback is the session's last close. |

## Referred to contract-checker

None.

---

*Audit complete. Findings reflect read-only static analysis; no pipeline was executed.*

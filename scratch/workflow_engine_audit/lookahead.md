# Workflow Engine Look-Ahead & Timestamp Re-Audit 2 (non-gate)

**Date:** 2026-08-27  
**Scope:** `research/schemas/study_spec.py`, forward-outcome contracts/selection/tracker, target and flip compilers, StudySpec projection, workflow fingerprints, and targeted workflow/forward-outcome tests.  
**Scope hash:** `b89da2b87b9e6cc49714d274bef611b0b153f5b20bb391b305572d03b468d448`  
**Method:** bounded read-only static re-audit. No workflow, tests, backtest, collection, or data execution. No protected data inspected.  
**Verdict:** **CLEAR**

## Summary

Critical: 0 · Warning: 0 · Note: 0 · New findings: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | B3/C2 — ATR numeric source/availability was not bound to the observed value | **FIXED** | `ProposedEntry` now carries `entry_atr_source` and `entry_atr_availability_ts`, requires complete provenance with a numeric ATR, and rejects availability later than `decision_ts` (`forward_outcomes/contracts.py:326-364`). `EntryColumns` declares both source columns and `_row_entry` copies them into the immutable entry (`forward_outcomes/selection.py:52-73,104-132`). The tracker rejects an entry whose source differs from the hashed `ForwardOutcomeSpec` or whose availability is absent (`forward_outcomes/tracker.py:667-678`). The deep projection pins the approved source and decision freeze (`study_spec_compiler.py:109-110`), while schema/runtime contract validators reject an ordered-barrier ATR frozen later than decision (`study_spec.py:245-257`; `forward_outcomes/contracts.py:240-250`). A post-decision ATR cannot enter this target path without a fail-closed exception. |
| 2 | B9 — completed episode source semantics were only a naming convention | **FIXED** | Episode state and emit declarations now require literal `bar_state: completed` and `availability_timestamp: completed_source_bar_ts_init` (`study_spec.py:67-85`). Projection reads those semantics from the governed candidate authority and refuses projection unless both exact values are present, then materializes them into both lifecycle legs (`study_spec_compiler.py:93-99`). Canonical flip fit independently requires the source identity and both completed availability declarations (`flip_prediction.py:39-57`). The candidate authority file is separately fingerprinted and mapped back to PREPARE invalidation (`workflow_engine.py:127-162`), and its hash is recorded in StudySpec compilation evidence (`study_spec_compiler.py:154-160`). Authority drift therefore cannot leave a valid completed-source contract silently in place. |

## Prior critical status

The previously fixed C2/F2/G2 session-end and missing-gap censoring remains fixed: projection still sets `session_end_censoring: true` and `max_gap_seconds: 1`, and target compilation still binds both into the trusted forward-outcome contract.

## New findings

None. The bounded remediation sweep found no new A/B/C1-C3/F/G/H blocker.

## Clean checks

- Decision/entry chronology remains completed 5s decision → first next-bar open → fully-forward 1s outcome path.
- Same-1s-bar dual barrier touches remain ambiguous/null; session and missing-gap paths remain censored.
- Forward outcome columns remain label-only under the existing guard.
- ATR value, source identity, and availability are now checked before tracker registration.
- TRAIN/OOS isolation is unchanged; no OOS open or collection path was introduced or accessed.

This scratch report is diagnostic and non-authoritative. It is not a study audit pass and does not issue or modify any governed audit status.

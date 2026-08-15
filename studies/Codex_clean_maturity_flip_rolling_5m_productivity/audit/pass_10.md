# Look-Ahead & Timestamp Audit — Pass 10

**Date:** 2026-08-15T00:52:30-05:00  
**Scope:** `implementation/run_exploratory_models.py`, root `study.yaml`, current 2021-2024 partition manifests/timestamp extents, and the audited collector/feature registry only for label and predictor provenance  
**Scope hash:** `9c63db864107e4f30525a3d704311056dc68acef0a1699d331289ff22430c926`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 2
- Warning: 0
- Note: 1

The model blocks use only audited NT snapshot columns and the future label does not enter the predictor lists. The execution order and partition-year assignment do not enforce the frozen temporal boundary.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C-03 | G4/C2 low-quality completed 1m bars entered collector state | FIXED | The collector surface is unchanged from Pass 09; its pre-update 1m quality gate and fail-closed reset remain present at `collector.py:257-309`. |

## Critical findings

### [C3] `implementation/run_exploratory_models.py:96-107,117-136` — 2024 is read and inspected before the Top-25 lists are frozen

**Failure path:** `_load_partitions` reads every supplied feature parquet, including 2024, into one materialized frame. `run` then creates `oos`, creates each `direction_oos`, and reads its height before calling `_freeze_top25`. Thus the frozen invariant that no 2024 data is read before the direction-specific feature freeze is already false on the intended four-partition invocation, even though the current ranking arguments happen to be train-filtered.

**Smallest fix:** Load and authenticate only 2021-2023 first; select and persist both direction-specific Top-25 lists and their hashes; only after that freeze succeeds may a separate code stage open the 2024 partition for scoring.

### [C3/G2] `implementation/run_exploratory_models.py:96-108,120-121` — manifest start year is assigned to every row without checking the partition end or row timestamps

**Failure path:** A valid collector invocation may write one directory from 2023 through the end of 2024. The loader reads `manifest.start[:4] == 2023`, stamps every row `partition_year = 2023`, and sends the embedded 2024 features and labels into baseline screening, Top-25 ranking, and fitting. Conversely, a 2024-start partition containing later years would be scored as 2024. Neither manifest end nor `checkpoint_decision_ns` is checked against the claimed year.

**Smallest fix:** Require exact non-overlapping annual manifest bounds for 2021, 2022, 2023, and 2024, derive/validate each row's year from `checkpoint_decision_ns`, reject duplicates or out-of-bound rows, and construct train/OOS from separately authenticated partitions.

## Warnings

- None.

## Notes

- The four currently materialized `exploratory_partition_2021` through `_2024` manifests and observed checkpoint extents are annual and correctly bounded; the blocker is that the runner does not enforce those properties for the inputs it will act on.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- C1-C2: `flip_within_300s` is used only for train ranking/fitting and OOS evaluation; it is absent from A/B/C predictor lists.
- B1-B7, B9-B10: A uses registry-derived baseline columns; B adds the audited structural family; C adds the audited rolling-productivity family. The three family sets do not overlap.
- OOS metrics and saved prediction rows are filtered from `direction_oos`; once partition identity is corrected, that scoring path is 2024-only.
- A1-A5, F1-F4, G1, G3-G4 are unchanged from the clean collector provenance. H1-H4 are not applicable.

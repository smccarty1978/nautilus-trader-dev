# Look-Ahead & Timestamp Audit — Pass 11

**Date:** 2026-08-15T00:57:32-05:00  
**Scope:** Pass-10 C3/G2 remediation in `implementation/run_exploratory_models.py`, root `study.yaml`, current annual partition manifests, and previously audited collector/registry provenance only as needed  
**Scope hash:** `6374955015acb992334671ff5370ae35e91fada9f70c7b4e4e891247f053e885`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 0
- Note: 1

The no-2024-before-freeze execution boundary is fixed. Partition row years are now authenticated, but exact annual coverage and partition uniqueness are still unenforced.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C-01 | C3 2024 was opened before direction-specific Top-25 freeze | FIXED | Only `train_dirs` are loaded at `run_exploratory_models.py:131-140`; both direction-specific lists and all A/B/C models are created at lines 146-166. The first OOS parquet read is the separate `_load_partitions(oos_dirs, {2024})` call at line 169. |
| C-02 | C3/G2 partition identity relied only on manifest start year | NOT FIXED | Row years are now checked (`run_exploratory_models.py:107-113`), preventing cross-year leakage. The interval check at lines 101-103 compares only four-character years, and the loader does not require exactly one non-overlapping partition per expected year or reject duplicate checkpoint rows. |

## Critical findings

### [G2/C3] `implementation/run_exploratory_models.py:97-114,131-169` — C-02 still accepts partial and duplicated year partitions

**Failure path:** A 2021 directory with `start=2021-06-01` and `end=2022-01-01` passes the interval check, and every row correctly reports year 2021, so the runner silently trains without the first half of 2021. The same directory may also be supplied twice because no year/path/checkpoint uniqueness is enforced; duplicated rows then double-weight that year during the final model fits and inflate recorded row counts. Equivalent overlapping 2024 inputs distort OOS counts and can change metrics when overlaps are partial.

**Smallest fix:** Parse manifest bounds and require exactly `[YYYY-01-01T00:00:00Z, (YYYY+1)-01-01T00:00:00Z)` for exactly one partition per required year; after concatenation, reject duplicate `checkpoint_decision_ns`/direction rows before ranking, fitting, or scoring.

## Warnings

- None.

## Notes

- The four currently materialized annual partition manifests are correctly bounded and their observed row years match. The blocker is the executable loader accepting other incomplete or duplicated inputs.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- C1-C2: the delayed flip label remains outside every predictor block and is used only for train selection/fitting or 2024 evaluation.
- C3: temporal-fold ranking receives only authenticated 2021-2023 rows; all fits finish before any 2024 partition is opened; OOS scoring receives only timestamp-verified 2024 rows.
- A1-A5, B1-B7, B9-B10, F1-F4, G1, G3-G4 remain clean on the unchanged provenance path. H1-H4 are not applicable.

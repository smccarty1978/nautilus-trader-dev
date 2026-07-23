# Path-Extrema Repair Completion Audit

**Date:** 2026-07-22  
**Verdict:** PASS — FINAL REPAIRED ARTIFACT ACCEPTED  
**Critical:** 0  
**Warning:** 0

## Root cause

The vectorized range query used a global loop but did not mask rows whose
individual `[left,right)` interval had already completed. Those rows continued
to traverse ancestor nodes and could receive extrema outside their requested
slice. This corrupted all MFE/MAE families and checkpoint-to-flip timestamps.

## Repair and prevention

- Both left and right candidates require an iteration-start per-row active mask.
- Inactive terminal candidate indexing is safe for power-of-two arrays.
- Exhaustive synthetic validation covers every interval, empty slices, repeated
  minima/maxima, and earliest-tie indices.
- Every production path family and year runs direct raw-slice parity validation.
- The independent completion audit replayed 28,672 available intervals and every
  unavailable path, including boundaries, magnitudes, timestamps, and gaps.

## Accepted replacement

- Parquet SHA-256:
  `97afa92a737749fe217a217f87f8ade25ef39cc14b18ad47f8a48b77f0a595c3`
- Rows: 727,482
- Columns: 81
- Duplicate/null primary keys: 0
- Bounded run: completed in 65 seconds; 3,484 MB peak memory
- Timestamp bound violations: 0

The obsolete `d6e5b71e...` artifact and every downstream path-policy analysis
derived from it remain explicitly invalidated.

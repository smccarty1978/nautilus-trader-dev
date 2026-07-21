# Runtime-vs-Collector Reconciliation — March 2025

**Live model**: top_15, Train 2020-2023, Val 2024 (same as feature_reduction sweep)
**Score threshold**: 0.468136
**Window**: 2025-03-01 to 2025-03-31 23:59:59

## Coverage

- Live scored checkpoints (Mar + T≤600): 12,528
- Offline ref predictions (Mar + T≤600): 6,222
- Both (matched on event_id × checkpoint_s): 0
- Live only (not in ref): 12,528
- Offline only (not scored in live): 6,222

**Note**: offline ref contains RESOLVED rows only (pt100 ∈ {0,1}). Live scores every fillable+feature-present checkpoint, including ones that end up unresolved. Live-only rows are primarily unresolved at event termination, which is legitimate divergence.


## Candidate-trade parity

- Live candidates (score >= threshold): 1,614
- Offline candidates (score >= threshold): 694
- Delta: +920

## Interpretation

- **Score parity fails**. Features or scoring logic diverges between runtime and collector paths. Investigate before trusting 2026 result.

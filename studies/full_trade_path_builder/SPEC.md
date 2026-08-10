# Full Trade Path Builder

The canonical design contract is:

`../../FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_FINAL.md`

Implementation is phased and acceptance is blocked until every gate in that
document passes.

## Phase A

Create and freeze a corrected causal Bullish Fade Top-25 artifact before any
canonical dual-model dataset is built.

Phase A is governed by `PHASE_A_TASK_PACKET.md` and
`config/phase_a.yaml`. No 2026 data may be read.

## Later phases

Phase B through E (global scores, trade selection, full paths, and acceptance)
may begin only after the Phase-A completion audit accepts the corrected Bullish
artifact with zero CRITICAL and zero WARNING.


# Pre-execution look-ahead audit: Pre-Flip D10 Reversal Entry

Date: 2026-07-11  
Gate status: **FAIL — FULL PIPELINE MUST NOT RUN**

No completion audit is appropriate because final economics have not been authorized to execute.

## Decisive NT microfixture evidence

Source: `audit/stop_entry_bar_microfixture.json`

The mandatory pre-execution mechanics fixture falsified two execution assumptions:

- Intended entry bar timestamp: `1741042801000000000`
- Entry bar open: `20511.25`
- Entry bar low: `20505.25`
- Actual market entry fill at that timestamp: `20514.25`, **not the bar open**
- Fill-anchored stop submitted in the entry-fill handler: `20511.00`
- The entry bar crossed the stop (`low 20505.25`), but no same-bar stop fill occurred
- Stop filled only at `1741042802000000000`, one bar later, at `20511.00`

Therefore the current reused NT bar-execution stack does not implement the brief's “fill at the next executable 1-second bar open” price contract, and a stop created in the entry fill callback misses a stop touch in the entry bar. These are material economics defects, not diagnostic-only differences.

## CRITICAL findings

### C1 — Entry and stop execution contract is false under the actual NT matcher

Files: `strategy.py`, reused `studies/_shared_exit_mgmt/nt_runner.py`, `SPEC.md`

The fixture proves that scheduling/submitting the market entry through the current bar-execution path does not fill at the referenced next bar open, and that creating a resting stop in `on_order_filled()` is too late for the matcher to consider the entry bar's remaining high/low. The current implementation will overstate survival and distort entry advantage, pre-flip MAE/PnL, stop rates, and every policy comparison.

Required fix: redesign and verify the executable entry/stop mechanism in NT. Use an NT-native order/contingency approach that produces the actual intended next executable price and protects the position from the instant of entry, or revise the estimand only with explicit user approval. Do not synthesize a stop fill from OHLC after the event and do not use a phantom stop price. Repeat deterministic fixtures for long/short, entry-bar touch/non-touch, gap through stop, and stop coincident with flip/D10. Assert exact timestamps and prices before the full run.

### C2 — Warmup filtering now manufactures false first crossings at the official boundary

File: `run_nt_policies.py`

`load_events()` filters `causal_scores.parquet` to the official window **before** calculating `prev` and selecting below-to-above crossings. If a regime crossed D10 before the official start and remains above D10 at its first in-window checkpoint, filtering deletes the prior above state; `shift(fill_value=False)` then treats the first in-window row as a new crossing. This violates the one-first-crossing-per-regime definition and creates test entries that never occurred.

Required fix: calculate valid score state and first crossing on the complete chronological regime sequence first, then filter the already-selected crossing events by causal availability into the official window. Alternatively consume the globally built `results/d10_entry_events.parquet` after verifying its definition. Placebo events may be window-filtered directly because they are already frozen individual events. Add an assertion that every loaded real event equals the globally frozen first crossing for its regime.

### C3 — Cancellation-rejection handling still does not retry or fail closed

File: `strategy.py`

`on_order_cancel_rejected()` only clears `stop_cancel_pending` and increments a diagnostic. `pending_exit_reason` remains, but no replacement exit is submitted and base retry logic cannot act because `exit_reason` was never set. Unless another D10/flip happens to call `_submit_exit()` again, the intended exit is lost while the stop remains live.

Required fix: implement a bounded causal retry or immediately halt/mark the run invalid on cancellation rejection. Persist each request/rejection/retry. Do not allow policy economics to continue after an unfulfilled exit trigger.

## Resolved findings retained

- Section 14 explicitly authorizes frozen offline score lookup/policy design while final economics run in NT.
- Coverage now uses exact F1 opposing-flip mapping and right-censors missing/cross-year ends rather than shifting scored regimes.
- Normal replacement exits wait for stop-cancel acknowledgement, retaining stop identity so a racing stop fill wins.
- Score/regime identity mismatch halts.
- Submitted-unfilled, pending, and filled-open data-end states are recorded.
- Tick rounding is frozen and documented.
- Placebos use never-treated/non-censored, past-only, same-month, one-per-donor matching with no overlap/reuse, a 30-second caliper, and balance output.
- Jan–Feb 2025 is excluded from policy economics.

## Remaining non-blocking robustness items

- Assert duplicate F1 rows have identical opposing ends before deduplication.
- Give zero-match placebo output a fixed schema so reporting does not crash.

## Conditions for the next pre-execution pass

1. Correct the globally frozen crossing/window-filter order and assert identity.
2. Correct cancellation-rejection behavior.
3. Replace or correct entry/stop mechanics and pass all deterministic NT fixtures with the promised prices/timestamps.
4. Reinvoke this auditor before any full policy execution.


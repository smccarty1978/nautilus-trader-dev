# chore/population_parity_reference_gate: evidence

Two pre-collection gates for `nq_fpr_price_action`: (1) the TRAIN/prohibited-year boundary, (2) governed population parity against the frozen FPR TRAIN frame.

## Gate 1: TRAIN / prohibited-year boundary

### Contract (code, unchanged)

The platform has one convention: **UTC calendar years**.

| Element | Semantics | Source |
|---|---|---|
| Role year Y | `primary_ns = [Y-01-01T00:00Z, Y-12-31T23:59:59.999999999Z]`, closed | `lifecycle_v2._partition_bounds` |
| Launch window | `[primary_start 00:00Z − warmup_days, run_end 23:59:59.999999999Z]` | `resolve_dataset_plan` / `host_runner.launch_data_plan` |
| Outcome tail | `run_end` = Dec 31 + 1 day + horizon, **only if** that year is itself train/dev; otherwise `run_end = Dec 31` | `_partition_bounds` |
| Warmup | 5 days before Jan 1 (into Y−1); warmup bars update state and emit no row | `HostCore` primary interval |
| Candidate emission | only checkpoints with `T ∈ primary_ns`; others are counted in `dropped_outside_primary` | `HostCore` / sink |
| Outcome resolution | in time order, on bars `ts > arm_end`; `session_end: truncate` sets `arm_end = min(entry + horizon, session_close)`; still-open arms at stream end become `CENSORED / DATA_END` (kept, never dropped) | `host/outcomes.py` |
| Catalog files | `{start}_{end}` filename interval, closed (`_query_intersects_filename`); a file whose interval meets the window **and** a prohibited UTC year refuses before a byte is read | `roots.verify_dataset_scope` |
| Trading session | the session table (CME Globex calendar) decides RTH membership; partition years remain UTC | `sessions` |

### Real catalog (manifest metadata only; no data byte of 2024+ read)

| File | Interval (UTC) |
|---|---|
| NQ 1m, 2023 | 2023-01-02 23:01 → **2023-12-29 22:00** (Fri 16:00 CT close) |
| NQ 1s, 2023 | 2023-01-02 23:00:01 → **2023-12-29 21:59:59** |
| NQ 1m / 1s, 2024 (first bar only) | **2024-01-01 23:01 / 23:00:01** (CME New-Year reopen, 17:00 CT, trade date Jan 2) |

The PA TRAIN-2023 launch window is `[2022-12-27T00:00Z, 2023-12-31T23:59:59.999999999Z]`. It contains every 2023 bar, and the first 2024 bar comes 23 h later, so the 2024 file is disjoint from the window. No session of trade date 2024 opens inside UTC-2023: the gap from Dec 29 22:00 to Jan 1 23:00 has no bars.

### Frozen FPR TRAIN-2023 (read-only, from its partition manifest and observations)

FPR declared `dev: [2024]`, so `run_end = 2024-01-01`. That is the declared tail convention, not a prohibited-year violation: 2024 was not prohibited in FPR.

| Failure mode | FPR TRAIN-2023 |
|---|---|
| (1) opened a 2024 file | **yes**: window end 2024-01-01T23:59:59.999999999Z ≥ 2024 file start |
| (2) processed 2024 bars | **yes**: `bar_range.last_ts_init` 1s = 2024-01-01 23:59:27Z, 1m = 2024-01-01 23:59Z. About 1 h of Globex bars of trade date 2024-01-02 were processed as tracker state |
| (3) emitted 2024 candidates | **no**: max `observation_ts` 2023-12-29 16:00Z. 2024-01-01 has no RTH session. The 359 `dropped_outside_primary` rows are consistent with the four Dec 27–30 2022 warmup RTH sessions (all are before `primary_ns`; none can be 2024) |
| (4) 2024 information in a 2023 row | **no, by ordering, not by labels**: max `resolved_at_ts` 2023-12-29 16:15Z, max `horizon_end_ts` 16:30Z. No `DATA_END` censoring in 2021–2023. Every 2023 row was final before the first 2024 bar (2024-01-01 23:00:01Z) reached the time-ordered host |

For the HV1 2024 holdout this means FPR's TRAIN-2023 replay **saw** the first hour of the 2024 Globex tape as tracker state, but no stored row depends on it.

### Synthetic fixtures (`research_workflow/tests/test_year_boundary_chronology.py`, 9 pass + 1 strict xfail)

Real NautilusTrader catalog (`ParquetDataCatalog.write_data`, Globex layout 2028 | 2029 | 2030), plus the real lifecycle and host on the golden 2029-12-31 | 2030-01-01 fixture:

- `run_end` extends only into a declared role year (PA layout, FPR layout, single year); inner years keep their tail.
- TRAIN-only window: warmup crosses into 2028; the 2030 files are never opened (spy on every hash and footer read); `CausalDataLoader.load_bars` returns every 2028 and 2029 bar (exact count) and none ≥ 2030.
- FPR layout (`dev: [2030]`): the same launch opens the 2030 file and streams its 23:00 UTC reopen; with 2030 prohibited, the identical tail refuses with zero files opened.
- UTC/Chicago divergence: a next-trade-date session opening Dec 31 17:00 CT (23:00 UTC, still UTC-2029) filed with 2030 refuses before any byte (`DATASET_SCOPE_UNAUTHORIZED_FILE`).
- Closed endpoints: window end = first 2030 ns − 1 passes; window end = first 2030 ns refuses.
- Real host: the TRAIN-only partition is handed no bar > 2029-12-31T23:59:59.999999999Z, emits only 2029 rows, has no `DATA_END`, and its candidates and observations are **frame-equal** to the dev-tail run that did stream 2030.
- An outcome left open by the stream end is kept and censored `DATA_END` (never dropped), which is visible to the parity gate.
- **Strict xfail, finding `PENDING_AT_END_VACUOUS`:** `HostCore.stats()` is read after `finalize()` has drained `kernel.pending`, so `stats.pending_at_end` is always 0.
  - Effect: the smoke check `pending_resolved_at_run_end` and the windowed `WINDOW_OUTCOME_UNRESOLVED` guard can never fire.
  - Smallest correction (not made here; it is in `host/strategy.py`, replay closure): record `len(kernel.pending)` before `kernel.finalize()` and report it.
  - Not required for the PA study: its `DATA_END` exposure is checked row by row by the parity gate's censoring comparison.

**Verdict, Gate 1: SAFE for `nq_fpr_price_action` under the existing convention; no platform correction required.**

## Gate 2: governed population parity

### Mechanism

The existing `analysis.gate.population_parity` (STOP GATE, aborts analyze before any artifact) is extended in `research/analysis/diagnostic_ops.py`:

- `reference_frame: {dir, candidates_sha256, observations_sha256}`: another study's **sealed merged frame**.
  - Both halves are sha256-pinned and resolved read-only against `studies_root`.
  - The frame is rebuilt by the analysis-frame join rule (`FRAME_JOIN_KEY == lifecycle_v2.KEY`, pinned by test).
  - A reference whose halves do not pair 1:1 refuses (`REFERENCE_INCONSISTENT`).
  - No receipt is written into the reference study; the frame store's `register_frame` would write one into the frozen FPR.
- Null keys and duplicate keys refuse on either side.
- `compare: {timing, membership, outcome, censoring, context}` gives per-key value equality: two nulls agree; null vs value differs, so a NaN flag is never cast to bool.
- Typed `failure_codes`:
  - `PARITY_COUNT_MISMATCH`, `PARITY_KEY_NULL`, `PARITY_DUPLICATE_KEY`, `PARITY_MISSING`, `PARITY_EXTRA`, `PARITY_RETIMED`;
  - `PARITY_{TIMING,MEMBERSHIP,OUTCOME,CENSORING,CONTEXT}_CHANGED`.
- Each failure carries full counts and ≤ 10 examples, and `verdict` is `PARITY_PASS` / `PARITY_FAIL`.
- On failure the report rides on the exception (`.report`) and, as JSON, in its message.
- Existing parameters, messages and tests are unchanged (54/54).

Candidate parity and outcome parity are **one stage** (analyze, step 1) but **separate categories**. The frame is candidates ⋈ observations, so identity, timing, A1/A2 membership, labels and censoring are each reported on their own.

### Synthetic proof (`research/analysis/tests/test_population_parity_reference.py`, 14/14)

| Case | Result |
|---|---|
| exact match (with added feature columns) | `PARITY_PASS` |
| different row order (both sides) | `PARITY_PASS` |
| one missing candidate | `PARITY_MISSING` + `PARITY_COUNT_MISMATCH` |
| one extra candidate | `PARITY_EXTRA` (+ per-year count) |
| duplicate candidate (sets equal) | `PARITY_DUPLICATE_KEY` only |
| retimed checkpoint | `PARITY_MISSING` + `PARITY_EXTRA` (counts unchanged) |
| retimed resolution | `PARITY_TIMING_CHANGED` (and `PARITY_RETIMED` with a timestamp column) |
| changed A1 / A2 flag | `PARITY_MEMBERSHIP_CHANGED` (per-column counts) |
| changed label | `PARITY_OUTCOME_CHANGED` |
| changed censor reason; null label vs 0.0 | `PARITY_CENSORING_CHANGED`; `PARITY_OUTCOME_CHANGED` |
| 25 missing / 35 retimed | full counts, 10 examples each |
| reference sha / missing dir / incomplete / ambiguous / unknown category / inconsistent halves | typed refusals |

Mutation (duplicate check and value comparison disabled): 5 of 14 fail; restored: 14/14.

### Real reference (`real_reference_self_parity.json`, TRAIN data only)

The FPR sealed merged frame (`candidates 606a4f4c…`, `observations f1a15a18…`) against the population rebuilt by `V2Lifecycle._train_frame_all_labels` from FPR's three sealed partitions:

- **`PARITY_PASS`, 69,369 = 69,369**, `_year` {2021: 23,088, 2022: 23,196, 2023: 23,085}, 0 null or duplicate keys, 0 changes in every category.
- Real-scale negative controls: shuffled gives PASS; drop one gives MISSING + COUNT; one `bos_signal` gives MEMBERSHIP; one label gives OUTCOME; one `DATA_END` gives CENSORING.

## Closure effect (correction to commit 4c8d9313)

The commit message says "not in any study closure stage". That holds only for studies that declare no `analysis:`. `research/analysis/diagnostic_ops.py` **is in the collection-stage closure** of every study that declares analysis ops, including `nq_fair_pricing_reversion_hv1_2024` (B) and `nq_fpr_price_action` once its parity step is declared.

- **Replay stage: not affected**, so replay-closure composites and partition-reuse keys do not move.
- After merge, B's collection-stage and overall composites (and so its plan hash) change. B's reuse requirement is unchanged: it already needs `REUSABLE_BY_CLOSURE_ATTESTATION` from the scoped-bytes merge.
- The frozen FPR (723a0b75, its own branch) is unaffected.

## Broad pre-merge gate (head 4c8d9313)

`python scripts/test_delta.py research_workflow/tests scripts/tests research/analysis/tests --json` (`test_delta_broad.json`): ran 2,793, passed 2,704, failed 61, wall 7,045 s. The 61 failing node ids are **identical** to the 61 known failures on `main` 19cb82cc, so **0 failures are attributable** to this chore. The baseline was not updated.

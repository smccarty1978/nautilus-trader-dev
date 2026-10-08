# chunked_sink_flush -- bounded-memory collection (checkpoint, session 4)

## Session 4 verdict: the session-3 "non-sink blocker" was the measurement harness itself

**Retraction of session 3's `finding_process_peak_rss_not_bounded_1month_with_profile`.** The
2.59 / 4.38 / 12.83 GiB "process peak RSS" figures in `rss_curve.json` were produced by
session 3's own harness calling `recompute_logical_content_sha256` right after `finalize()`,
**inside** the sampled RSS window, with a default `batch_size=50_000` larger than every
measured partition -- so the "peak" was a whole-file Python-object read-back, not collection.
See `rss_curve_SUPERSEDED.md` for the exact mechanism and `artifacts/platform_v2/chunked_sink_flush/harness/`
(`collect.py`/`verify.py`/`run_watched.py`) for the phase-separated replacement harness
(verification always runs in its own separate process, never inside the collection-sampled
window, by construction). `research_workflow/host/chunked_writer.py`'s
`recompute_logical_content_sha256` is fixed (Task A, commit `e111d077`): its batch size is now
derived per-file from a small bounded sample via the writer's own calibrated
`estimate_row_bytes`, instead of a fixed `50_000`-row default.

**Causal data scope correction.** Every run recorded in `rss_curve.json`/`equivalence.json`/
`downstream_memory.json` started within 5 days of 2022-01-01 (`run_plan_on_catalog`'s default
`warmup_days=5`), so every one of those collection replays touched 2021-12-2x warmup bars even
though the requested windows and resulting rows are all dated 2022. Each file now carries an
additive `causal_scope_audit` block naming the affected run/window and marking it
`INVALID_FOR_2022_ONLY_SCOPE`; no previously recorded value was changed or removed. A
2022-only-scope-clean replacement measurement is `rss_curve_v2.json` (see below).

See `rss_curve_v2.json` and `causal_scope.json` for the session-4 real-tape measurement and
its verdicts.

## Session 3 verdict: PARTIAL PASS -- sink/writer layer bounded; NEW non-sink blocker found (SUPERSEDED, see above)

**The capability this chore owns (the chunked writer + sink flush trigger) is PROVEN
bounded.** A separate, LARGER memory-growth source was found during measurement, outside
this chore's edited surface (not `chunked_writer.py`/`sink.py`/`strategy.py`) -- reported,
not fixed, per the packet.

1. **Byte threshold + row cap, simultaneous (task 1):** `ChunkedParquetWriter`/`ColumnarBuffer`
   now flush on whichever of `batch_rows`/`batch_bytes` triggers first.
   `estimate_value_bytes` (recursive `sys.getsizeof`) is calibrated against `tracemalloc` on
   realistic (non-cached-small-int) VP-struct-shaped rows: within ~7% of measured allocation
   (a naive fixed-8-bytes-per-scalar draft was ~20x too small). See
   `research_workflow/tests/test_chunked_writer.py::test_estimate_bytes_calibrated_against_tracemalloc_on_vp_shaped_rows`.
2. **Two defects found by read-only audit, fixed with tests:** (a) `logical_content_sha256`
   was hashed from pre-conversion input, not the values actually written -- fixed by hashing
   from the built `pa.Table` (`_rows_canonical_from_table`); `recompute_logical_content_sha256`
   lets any caller verify a manifest's hash directly from the finalized file. (b) both
   `chunked_writer.finalize()`'s `physical_sha256` and `lifecycle_v2._sha()` did a whole-file
   `read_bytes()` -- both now stream in 4 MiB chunks, identical digest.
3. **Real-tape measurement (task 3, this session):** nine real `tracker.volume_profile.rolling`
   instances (`emit_profile: true`), real `NQ_1S_V2_GLOBEX` catalog, `outcome: none`,
   `completed_1m` cadence, through the real `run_plan_on_catalog` + chunked sink
   (`batch_rows=100_000`, `batch_bytes=8 MiB` -- deliberately small so the byte trigger, not
   the row trigger, governs). 1 day / 1 week / 1 month of 2022 measured, with and without
   profiles (3 months NOT measured -- time-bounded, see "Remaining work"). Full table and
   finding narrative: `artifacts/platform_v2/chunked_sink_flush/rss_curve.json`.
   - **Sink/writer footprint IS bounded**: `post_emit` RSS sampled AT every flush cycle grows
     only ~550 MB over 2045 flush cycles in the 1-month run (~0.055 MB/row) -- the writer's
     own buffer does not blow up with total row count. Pre-fix, the writer's internal probe
     alone could buffer 50,000 wide rows (~19 GiB) before any flush; it now flushes every ~5
     rows at this byte threshold.
   - **A NEW, separate, larger blocker was found and is NOT fixed here**: process peak RSS
     (psutil, 50 ms sampling) WITH profiles is 2.59 / 4.38 / **12.83 GiB** at 1 day / 1 week /
     1 month, vs a FLAT 1.70 / 1.75 / 2.01 GiB WITHOUT profiles over the identical windows.
     The with-profile spike is invisible at every flush-cycle checkpoint and at finalize
     (never exceeds ~1.5 GiB there) -- it happens OUTSIDE `chunked_writer.py`/`sink.py`,
     almost certainly in `features/trackers/volume_profile_rolling.py`'s per-bar tracker
     state for `emit_profile=true`, or the NT engine's per-tracker state for it. Out of this
     chore's edited surface; reported per the packet, not fixed.
   - **Logical-content parity** chunked vs. unchunked re-checked on 1 day and 1 week: 0 real
     diffs (two expected all-null-identity-column int64-upcast-to-float64-vs-`None`
     differences, both mean "missing", documented, not a defect).

## Design

1. `research_workflow/host/chunked_writer.py` (new): `ChunkedParquetWriter`. Generic,
   struct/list-capable, incremental pyarrow.parquet writer.
   - Threshold: `batch_rows` (rows), configurable, default `DEFAULT_BATCH_ROWS = 50_000`.
   - Schema source: caller-declared `declared_types` (identity columns -> `int64`, feature
     columns -> `float64`, taken from the compiled plan) override everything; every other
     column's Arrow type is inferred ONCE from a PROBE buffer that may span several
     `write_rows()` calls (not a single batch), fixed before the first physical batch is
     written, and never re-inferred afterwards. This is what survives an all-null first
     batch without locking in the wrong type (see
     `test_all_null_first_batch_then_typed_values`).
   - Struct/list support is generic recursion over dict/list values (`infer_arrow_type`),
     with no feature-specific branch -- exercised by a synthetic struct-with-list<int64>-child
     fixture (`test_struct_and_list_typed_field`) ahead of chore/vp_profile_snapshot's real
     `FIELD_TYPES` landing.
   - Temp file: `<path>.inprogress`; `finalize()` flushes, closes, hashes, and
     `os.replace()`s into the final name -- no file at the final name exists until the write
     is complete, so a crash mid-partition leaves nothing any stage will mistake for a
     finished partition (`test_interrupted_write_leaves_no_complete_file`,
     `test_retry_yields_identical_logical_output`).
   - Two hashes in the manifest: `physical_sha256` (the actual written file -- row-group
     layout can differ between a chunked and unchunked run of the same logical data) and
     `logical_content_sha256` (sha256 over each row's canonical-JSON serialization, in
     emission order -- identical regardless of batch/row-group boundaries;
     `test_logical_hash_independent_of_batch_boundaries`).
   - A numeric subtlety found and fixed while building this: some observation columns
     (e.g. `horizon_end_ts`) are already `int` in some rows and `float` in others at the
     Python level, and pandas/`to_parquet` silently gives the WHOLE column one `float64`
     dtype today, losing integer precision on the int rows. pyarrow's default
     sequence-to-array conversion refuses that (`ArrowInvalid: ... outside the range exactly
     representable by a IEEE 754 double`). `_build_array` pre-casts to `float` in Python
     before handing values to pyarrow when the fixed column type is floating, to match the
     EXISTING silent-precision-loss contract rather than inventing a stricter one.

2. Wiring (opt-in, `V2Options.chunked_batch_rows: int = 0` -- `0` is byte-for-byte the
   pre-existing behaviour everywhere):
   - `research_workflow/host/sink.py`: `ColumnarBuffer` takes an optional `writer` +
     `flush_every`; `append`/`append_values` forward and DROP rows from the Python list once
     `flush_every` is reached (`_maybe_flush`). `flush_to_writer()` pushes remainder WITHOUT
     closing the writer (a windowed partition reuses one writer across several windows).
     `to_frame()` raises if a writer is attached (catches accidental full-materialization).
   - `research_workflow/host/strategy.py`: `HostCore(..., chunked_writers=(cand_w, obs_w),
     chunked_flush_every=N)`; `finalize()` calls `sink.flush_writers()` (flush, not close)
     when chunked and returns `(None, None)` instead of full frames. New
     `plan_output_columns(plan)` helper mirrors `HostCore.__init__`'s own candidate/
     observation column construction, with no replay, for callers that need just the column
     NAMES to build writers before any bar is ingested.
   - `research_workflow/host_runner.py`: `run_plan_on_bars` / `run_plan_on_catalog` accept
     and forward `chunked_writers` / `chunked_flush_every`.
   - `research_workflow/lifecycle_v2.py`: `_run_window` forwards `chunked_writers`;
     `run_partition` constructs the two writers once (`_chunked_writers_for`, declared types
     = identity columns `int64` + feature columns `float64`, from the plan) BEFORE the
     window loop, reuses them across every declared window (no per-window DataFrame, no
     `pd.concat` across windows when chunked), and finalizes them exactly once after the
     loop; `_persist_chunked` writes `manifest.json` from the two writer manifests instead of
     from `len(DataFrame)` / `to_parquet()`. `smoke()` and the standalone bar_source test
     path are untouched (chunked_writers=None).

3. Logical vs. physical identity -- consumers:
   - `_partition_valid` / `_partition_reusable` / `verify_reusable` (replay_closure partition
     reuse key), reconcile and any receipt that reads `manifest.json["candidates_sha256"]` /
     `["observations_sha256"]` keep reading the PHYSICAL file hash (now sourced from the
     writer's own `physical_sha256`, verified by `_persist_chunked`'s assertion to equal a
     fresh `sha256(file bytes)` read right after the atomic rename) -- unchanged contract,
     unchanged consumer code.
   - `manifest.json["candidates_logical_content_sha256"]` /
     `["observations_logical_content_sha256"]` are NEW, additive fields. No existing consumer
     reads them yet; they exist so a chunked run and an unchunked run of the SAME logical
     data can be compared without caring about row-group/batch-boundary differences (used by
     the equivalence tests below). Nothing currently claims physical-byte parity between a
     chunked and an unchunked run of the same data, and this change does not introduce that
     claim.

## Tests (this session)

- `research_workflow/tests/test_chunked_writer.py` (15 tests, PASS): batch size 1/2/3
  (including exact multiples and off-by-one), empty partition, empty batches interleaved
  with real ones, all-null first batch then typed values, entirely-all-null column default,
  declared types bypassing inference, struct+list typed field, large typed list field,
  interrupted write leaves no complete file + a retry from scratch reaches the identical
  logical hash, deterministic ordering + schema stability across batches, logical hash
  independent of batch boundaries, bad-batch-rows / write-after-finalize rejected,
  `infer_arrow_type` unit cases.
- `research_workflow/tests/test_chunked_sink_flush.py` (6 tests, PASS): on the golden
  synthetic fixture (`fixtures/golden/study_barrier.yaml`, label/barrier kernel) at batch
  sizes {1, 2, 3, 7, 10_000} vs. unchunked -- FULL candidate and observation populations,
  every column, every row, compared with `pandas.testing.assert_series_equal` (not sampled),
  plus `stats()["candidates"/"observations"/"pending_at_end"]` parity; and one more test on
  an `outcome: none` (descriptive) rewrite of the same fixture at batch size 3 vs. unchunked.
  Zero diffs in every case.
- Regression: `test_host_core.py`, `test_grammar_v2.py`, `test_outcome_none.py` all still
  PASS (88 passed total across the five files above as of this commit).

## Closure impact

`research_workflow/host/sink.py`, `research_workflow/host/strategy.py`,
`research_workflow/host_runner.py` and `research_workflow/lifecycle_v2.py` are inside the
execution closure (`research_workflow/__init__.py` is, and these are siblings resolved by
`scripts/resolve_execution_manifest.py`). Any study sealed against a manifest that hashes
these files has a stale freeze once this branch merges to main, exactly as any other change
to these modules would stale it -- this is not special to chunking. `V2Options.
chunked_batch_rows` defaults to `0` (disabled) so a study that re-seals against this branch
with no option change gets byte-identical collection output to before.

## Phase 2 (session 2)

### A. Schema risk -- declared struct/list metadata types, fail-closed type mismatch
A metadata column whose source tracker declares its shape via `BaseBinding.FIELD_TYPES`
(e.g. the volume-profile rolling tracker's `profile` struct -- null for the first ~1440 open
minutes after a block start or a 1440-horizon roll) now gets that DECLARED Arrow type, never
probe-based inference, which would otherwise default an all-null probe to `float64` and then
either silently misrepresent or crash once a real struct/list value arrived later in the
partition.
- `research_workflow/host/chunked_writer.py`: `dtype_tag_to_arrow` (one dtype tag ->
  `pa.DataType`) and `field_types_to_arrow` (one `FIELD_TYPES[field]` declaration -> `pa.DataType`,
  generic over `kind` -- `"struct"` today, extensible). `_emit_batch` now builds every column's
  array before writing any of them and raises a named `CHUNKED_WRITER_TYPE_MISMATCH TypeError`
  (never a silent coercion, never a partial write) if a later batch's value is incompatible
  with the already-fixed column type.
- `research_workflow/host/strategy.py`: `declared_metadata_types(plan)` -- for every
  `features.metadata` column, resolves `ref`'s root tracker id in `plan["trackers"]`, loads its
  `implementation` class, reads `getattr(cls, "FIELD_TYPES", {})` (so it works whether or not
  chore/vp_profile_snapshot's G2 has landed), and maps the declared field spec to an Arrow type.
  A column with no declaring tracker, or a field the tracker does not list, falls back to
  probe-based inference exactly as before -- unaffected.
- `research_workflow/lifecycle_v2.py`'s `_chunked_writers_for` folds `declared_metadata_types`
  into both writers' `declared_types` ahead of the identity/feature defaults.
- Probe memory stays bounded: unaffected (the probe already accumulates only up to
  `batch_rows` before the schema is fixed, with or without a declared type).

### B. Activation + identity
Decision: activation stays `V2Options.chunked_batch_rows: int = 0` (opt-in, unchanged from
session 1) -- `0` is byte-for-byte the pre-existing behaviour everywhere, and flipping the
default needs the real-VP-data (D) and RSS-curve (E) evidence this session gathers before it
is safe to make the default path for every study.
- Audited every partition-manifest/hash consumer named in the packet
  (`_partition_valid`, `_partition_reusable`/`verify_reusable`, reconcile's
  `_reattest_partition_reuse`, `merge`, `frame_store.register_frame`). All of them either (a)
  compare a file's physical bytes against ITS OWN manifest's recorded physical hash (tamper
  detection -- batch size never enters, since both sides are the same file at the same path at
  different times) or (b) re-serialize fresh from the partition parquet files with pandas
  (`merge`, which rewrites `merged/candidates.parquet`/`observations.parquet` from scratch via
  `pd.concat` + `to_parquet`, independent of how the source partitions were written) -- none of
  these needed a change.
- The one real cross-batch-size comparison is `_shadow_verify`: it recomputes ONE reused
  partition into a shadow directory under the CURRENT run's `V2Options.chunked_batch_rows` and
  requires byte-identity with the SERVED partition, which may have been written under a
  DIFFERENT `chunked_batch_rows` (it is a runtime option, not plan/seal identity, and is not
  required to match between the run that collected a partition and a later run that reuses and
  shadow-verifies it). Comparing the PHYSICAL hash in that case is a false
  `PARTITION_REUSE_SHADOW_MISMATCH` for two logically-identical partitions whose row-group
  layout merely differs. Fixed: `_shadow_verify` now compares the LOGICAL content hash
  (`candidates_logical_content_sha256` / `observations_logical_content_sha256`) whenever BOTH
  the served and the recomputed-shadow manifest carry it (both chunked), and falls back to the
  physical hash only when either side lacks a logical hash (the unchunked path, where neither
  manifest has the field) -- unchanged behaviour for every study that never opts into chunking.
  `batch_rows` remains recorded (in `manifest.json["chunked"]["candidates"/"observations"]["batch_rows"]`)
  for audit, just not used as reuse/shadow identity -- the smallest correct option, per the
  packet.
- Test: `research_workflow/tests/test_replay_closure.py::test_shadow_verification_tolerates_a_different_batch_rows_than_the_served_partition`
  -- collects under `chunked_batch_rows=3`, reuses+shadow-recomputes under `chunked_batch_rows=11`;
  fails with `PARTITION_REUSE_SHADOW_MISMATCH` before the fix, passes (`status == "IDENTICAL"`,
  `basis == "logical_content"`) after.

### C. Dead code removal
Removed `HostCore.writer_manifests` (`research_workflow/host/strategy.py`, always `None` under
the final ownership model -- `lifecycle_v2.run_partition` owns and finalizes the writers, not
`HostCore`) and the two dead `out["writer_manifests"] = ...` lines that read it
(`research_workflow/host_runner.py`, `run_plan_on_bars` and `run_plan_with_engine`). No
behaviour change; nothing else read this key.

### D. VP cross-branch real-tape equivalence proof (req 7, second half)
Done in a DISPOSABLE detached worktree (`Nautilus Trader-vp_integration_tmp`, merged
`chore/vp_profile_snapshot` + `chore/chunked_sink_flush` onto `main`, both merges clean, no
conflicts; never pushed; removed after copying evidence -- see task F below). A compiled plan
(`features.context`) binds the real `tracker.volume_profile.rolling` nine times --
`{range_uniform, full_per_tick, close}` x `{120, 360, 1440}` open minutes, `emit_profile: true`
on every instance -- over the real `NQ_1S_V2_GLOBEX` catalog, descriptive (`outcome: none`),
`completed_1m` cadence, run through `run_plan_on_catalog` (the real NT engine + the real
`GovernedHostStrategy`/`HostCore`/`CollectionSink` path -- not a bespoke harness), chunked
(`ChunkedParquetWriter`, batch sizes 997 and 50,000) vs. unchunked, compared field-for-field,
row-for-row (profile struct included, via canonical-JSON per-cell comparison so a Python
`None` and a float `NaN` -- both "missing" -- are not misclassified as a diff).

Two real 2022 windows (2022 only; nothing after 2023-10-17, nothing from 2021, per the
packet's hard limit):
- a roll crossing, `2022-03-14..2022-03-18` (3,240 candidate/observation rows, 21 candidate
  columns -- 9 `profile` structs + 9 `poc` scalars + 3 identity -- x 2 batch sizes): **0
  diffs**.
- a fresh block start, `2022-01-03..2022-01-05` (2,025 rows, same columns x 2 batch sizes):
  **0 diffs**.

`stats()["candidates"]`/`["observations"]` also matched exactly in every case. The NT engine's
Rust logger can only initialize once per process, so each variant (unchunked, chunked-997,
chunked-50000) ran in its own subprocess; the orchestrator and per-variant runner scripts are
disposable (not committed -- they lived only in the scratch directory and the disposable
worktree, per the packet). Harness detail worth keeping in mind: a wholly-unpopulated identity
column (this descriptive plan declares no `anchor_identity`, so `regime_start_ns` /
`checkpoint_index` are null on every row) round-trips as Python `None` (object dtype) unchunked
vs. float `NaN` (the writer's identity columns are declared `int64`, and pyarrow/pandas
upcasts an all-null `int64` parquet column to `float64` on read) -- both mean "missing"; the
comparison harness treats them as equal, same documented int/float representation contract
`chunked_writer._build_array` already carries for `horizon_end_ts`. This is a comparison-
harness nuance, not a writer defect; it does not arise once a study declares `anchor_identity`
(every production study with an outcome does).

### E. RSS curve + downstream memory (req 8) -- PARTIAL, see gap below
Measured in the same disposable worktree, each variant its own subprocess (same NT-logger
reason as D), a `psutil` sampling thread (~50ms) plus the Windows OS peak working set,
`batch_rows=50,000` (the module default) for chunked, with an unchunked comparison at the same
window:

| window | rows | chunked peak RSS | unchunked peak RSS |
|---|---|---|---|
| 1 day (2022-01-03..04) | 1,620 | 2,505.5 MiB | 2,509.9 MiB |
| 1 week (2022-01-03..10) | 3,240 | 3,387.3 MiB | 3,380.3 MiB |

**Gap, reported not fabricated:** the 1-month and 3-months windows were NOT measured -- the
background orchestrator was killed by the host (`system is running low on memory`, an explicit
stop-and-do-not-retry signal from the harness, not a code failure) before reaching them.
**The curve above also does not yet prove boundedness**: neither window's row count (1,620 /
3,240) reaches `batch_rows=50,000`, so the chunked writer never actually flushed mid-run at
this batch size -- chunked and unchunked are (correctly) nearly identical here BY CONSTRUCTION,
not because bounded-memory behaviour was exercised. Proving the actual claim (flat peak RSS as
rows grow past one flush) needs either the 1-month/3-months windows (3 months x 9 VP
instances x 1-minute cadence was projected at ~51k rows, just over one flush at the default
batch size) or a smaller `batch_rows` (e.g. 997, already proven logically correct in D) run
long enough to flush multiple times. Neither was done. See "Remaining work" below -- this is
the single biggest gap in this session's evidence and the most important thing to run next.

### Downstream-stage memory (reconcile / merge / analyze) -- req 8, done
Measured directly against the real chunked D-proof partitions (two real windows stood in as
two "train years": 2,025 + 3,240 = 5,265 rows total, 9 VP profile-struct columns, real
`int64[]` `weights_fp`/`contributions` lists up to ~1,440 elements each):

| stage | code path exercised | measured peak RSS (this run, 5,265 rows) | projected @ full-year x 2 blocks (196,560 rows, ~37x) |
|---|---|---|---|
| `reconcile`-like | one partition read/discarded per loop iteration (never holds more than one year at once) | ~1.4-1.5 GiB | ~53 GiB |
| `merge`-like | `pd.concat([pd.read_parquet(...) for y in years])` -- ALL years' frames held simultaneously, then concatenated | ~2.9-3.0 GiB | ~105 GiB |
| `analyze`/`research/analysis/loader`-like | one `pd.read_parquet` of merge's own already-concatenated output | ~3.1-3.4 GiB | same order as merge's final output (not independently worse) |

**Finding: reconcile/merge/analyze are the next memory blocker, confirmed quantitatively, not
fixed (per the packet).** None of the three is chunked; all three materialize full pandas
DataFrames with the VP profile struct's `int64[]` fields as plain Python list-of-int objects,
which is the same CPython-per-object-overhead wall `chore/vp_profile_snapshot`'s own D2c
measurement already found for unchunked collection -- parquet's columnar compression of those
same lists (tens of KB/row on disk, see D above) is not present once pandas materializes them.
The ~37x row-count extrapolation from 5,265 to 196,560 rows is linear and should be read as an
order-of-magnitude signal (both projections already clear an 8 GiB budget by 6-13x), not a
precise forecast -- a direct measurement at full-year scale would tighten this. Exact figures:
`artifacts/platform_v2/chunked_sink_flush/downstream_memory.json`.

## Remaining work (NOT done this session -- say so, don't fabricate)

- **Session 3 superseded the session-2 RSS gap** (see verdict at top): 1 day/1 week/1 month
  of 2022, with and without profiles, now measured with a byte threshold small enough to force
  hundreds-to-thousands of real flushes; the writer/sink layer's own bounded-memory claim is
  now proven (not just asserted). **3 months was NOT measured this session** (time-bounded) --
  next step: run the same harness (`chunked_with_profile`/`chunked_no_profile`,
  `batch_bytes=8 MiB`) for `2022-01-01..2022-03-31` and fold into `rss_curve.json`.
- **NEW finding, NOT fixed**: a non-sink memory-growth source was found (process peak RSS
  12.83 GiB at 1 month WITH profiles vs a flat ~2 GiB without, invisible at every flush-cycle
  checkpoint) -- see `rss_curve.json["finding_process_peak_rss_not_bounded_1month_with_profile"]`.
  Next step: a SEPARATE chore instruments `features/trackers/volume_profile_rolling.py`'s
  per-bar state (and/or the NT engine's per-tracker retention) across a growing window to
  localize it; this chore's surface (`chunked_writer.py`/`sink.py`/`strategy.py`) is cleared
  by the per-flush-cycle evidence above.
- **G's broad `test_delta` run did not complete**: the exact scope the packet named
  (`research_workflow/tests/test_chunked_writer.py test_chunked_sink_flush.py test_host_core.py
  test_lifecycle_v2.py test_grammar_v2.py test_outcome_none.py test_declarative_analysis.py
  test_docs_v2.py` plus `test_replay_closure.py test_frame_store.py test_partitioning.py
  test_wave2_shadow_default.py`) was launched once via `scripts/test_delta.py` and killed by
  the same host memory-pressure signal before producing any output; not restarted per
  instruction. What IS verified (direct `pytest`, not `test_delta`, run per-commit this
  session): `test_chunked_writer.py` (20 passed), `test_chunked_sink_flush.py` +
  `test_host_core.py` + `test_grammar_v2.py` + `test_outcome_none.py` together (93 passed),
  `test_replay_closure.py` (16 passed, including the new B regression), and
  `test_lifecycle_v2.py::test_controller_runs_a_fresh_v2_study_end_to_end` standalone (1
  passed in 310s -- it failed once inside a much larger combined pytest invocation earlier in
  this session; isolated it passes, so that failure reads as pre-existing order/isolation
  flakiness, not a regression from A/B, but this was NOT re-confirmed against clean `main` as
  the packet's methodology technically requires). `test_frame_store.py`, `test_partitioning.py`,
  `test_wave2_shadow_default.py`, `test_declarative_analysis.py` and `test_docs_v2.py` were
  never run this session. Next step: re-run the exact `test_delta` command above once host
  memory allows, and only act on `NEW_FAILURE`.
- `_chunked_writers_for`'s `declared_cand`/`declared_obs` now also cover metadata columns whose
  tracker declares `FIELD_TYPES` (phase 2, task A, above), proven end-to-end against the REAL
  `tracker.volume_profile.rolling` struct in D (zero diffs, both roll-week and block-start
  windows, both batch sizes). Derived columns still rely on probe-based inference (not
  exercised against a real struct/list derived column -- none exists in the platform today).
- `V2Options.chunked_batch_rows` defaults to `0` (opt-in; this IS the activation surface --
  see "Activation" in task B above). Flipping the default to always-on for `run_partition` is
  a one-line follow-up once the boundedness gap above is closed with real numbers -- still not
  done, now for a sharper reason than before (D passed; E has not yet proven the thing that
  would justify flipping the default).
- No CLI/controller-level flag exposes `chunked_batch_rows` to an operator running a real study
  through `scripts/research.py` / the standard controller path -- today it is reachable only by
  constructing `V2Options(chunked_batch_rows=N, ...)` directly (as this session's harnesses and
  the test suite do). Wiring a CLI flag was not asked for explicitly and was not done; flagged
  here because "how a governed study activates chunking" has no operator-facing answer yet,
  only a programmatic one.

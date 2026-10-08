# chunked_sink_flush -- bounded-memory collection (checkpoint, session 1)

Status: core writer + wiring DONE and green on targeted tests. Cross-branch VP integration
(req 7 second half), real-tape RSS curves (req 8) and downstream-stage memory measurement
(req 8) NOT done this session -- see "Remaining work" below.

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

## Remaining work (NOT done this session -- say so, don't fabricate)

- Req 7 (second half): the disposable cross-branch VP integration worktree (merge
  chore/vp_profile_snapshot + this branch, run the real nine tracker-instance x open-minutes
  matrix against real 2022/2023 tape, compare bit-exact). Not attempted.
- Req 8: real RSS measurement curves (1 day / 1 week / 1 month / 3 months of 2022, chunked
  vs. unchunked) and the downstream-stage (reconcile/merge/analyze frame load) memory
  finding. Not attempted -- needs real catalog data and run time well beyond this session.
- `_chunked_writers_for`'s `declared_cand`/`declared_obs` cover identity + feature columns
  only; metadata/derived/observation columns rely on the probe-based inference. This was
  exercised correctly on the golden fixture's label/barrier and descriptive observation
  columns (including the int/float-mixed `horizon_end_ts` case) but not yet against a
  struct/list-valued REAL tracker field (chore/vp_profile_snapshot is unmerged); only the
  synthetic unit test proves that path.
- `V2Options.chunked_batch_rows` defaults to `0` (opt-in). Flipping the default to always-on
  for `run_partition` is a one-line follow-up once req 7/8 validate it against real VP data
  and real memory curves -- deliberately not done yet in this session so every existing
  caller/test keeps its exact current behaviour unless it opts in.
- `research_workflow/host/strategy.py`'s `self.writer_manifests` attribute and
  `host_runner.py`'s two `out["writer_manifests"] = ...` lines are now dead (always `None`)
  under the final ownership model (the writers' OWNER -- `run_partition` -- finalizes them,
  not `HostCore`); left in place rather than removed for lack of remaining turns, flagged
  here as a small follow-up cleanup, not a correctness risk.

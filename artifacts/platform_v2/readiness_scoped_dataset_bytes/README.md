# chore/readiness_scoped_dataset_bytes: evidence

## Defect

`roots.compute_catalog_digest` re-hashed every file under `<catalog>/data`. It ran at readiness R1 (V2 `lifecycle_v2.readiness` and legacy `readiness.py`) and at every catalog launch (`data_plan.verify_launch_dataset_bytes`, via `host_runner.run_plan_on_catalog`: TRAIN/OOS partitions, smoke, shadow reattest). A TRAIN-only study on `NQ_1S_V2_GLOBEX` therefore read the bytes of 2024–2026 on every readiness and every launch.

## Change (d50d5171)

`roots.verify_dataset_scope(catalog, committed_digest, windows, bar_types, forbidden)` works in four steps:

1. **Identity, with no data byte read.**
   - The manifest's `(path, size, sha256)` inventory, in its recorded order, must re-hash to the committed `logical_digest`.
   - Malformed or duplicate entries refuse (`DATASET_SCOPE_MANIFEST_INCONSISTENT`).
   - `verify_dataset_files` checks names and sizes only, and refuses missing, extra or resized files.
2. **Interval consistency.**
   - Every bar file's NautilusTrader filename interval is parsed by NautilusTrader's own `_parse_filename_timestamps`.
   - Intervals within one bar directory must be disjoint and ordered.
3. **Scope.**
   - A file is out of scope **only** when it is a bar file whose filename interval is provably disjoint from every window. This uses NautilusTrader's closed-interval rule, `_query_intersects_filename`.
   - Unparseable names and non-bar files are always in scope. Legacy catalogs therefore keep full-hash behaviour.
4. **Authorization, then bytes.**
   - An in-scope bar file that overlaps a forbidden year, or that has an unknown interval while any year is forbidden, refuses (`DATASET_SCOPE_UNAUTHORIZED_FILE`) **before any byte is read**.
   - Only then are in-scope files hashed, and their parquet footer `ts_init` min/max is checked against the filename interval.
   - The returned record holds `logical_digest` (unchanged), `windows_ns`, per-file `{path, size, sha256, interval_ns, footer_ts_init_ns}`, `scoped_digest`, `covered_intervals_ns` and `out_of_scope_file_count`.

Callers:
- **Launch** (`verify_launch_dataset_bytes(data_plan, forbidden_years=)`): one window, `[warmup_start_dt, end_dt]`, which is exactly what `engine_builder` hands `CausalDataLoader.load_bars`. `host_runner` passes `chronology.prohibited`. A compact `bytes_scope` receipt goes into each run's `dataset` record.
- **V2 readiness R1** (`_readiness_byte_scope`): the union of the windows of every TRAIN partition (whole year with its outcome tail, or each declared window) and the smoke date. These come from the same `_partition_bounds` / `_window_bounds` / smoke-date logic and the same `host_runner.launch_data_plan` the runner uses. Forbidden = prohibited ∪ dev years, because readiness precedes any OOS opening. The full record is stored in the R1 check.
- **Legacy readiness R1:** the DataPlan window, no forbidden years (that path applies its own chronology gates).
- **`research data verify --recompute`** stays whole-catalog. It is an explicit operator audit.

## Tests

`research_workflow/tests/test_scoped_dataset_bytes.py` has 22 tests, all passing. They use a **real** NautilusTrader catalog written by `ParquetDataCatalog.write_data`, with synthetic years 2029–2031, one file per year per bar type: the Dataset V2 layout. They cover:

- authorized files verified; 2029 and 2031 files never hashed or footer-read (spy on every byte and footer read);
- warmup crossing a year boundary pulls the prior-year file in, and only when it reaches that file's bars;
- closed interval boundaries (`a`, `b`, `a−1`, `b+1`);
- scope selection equals NautilusTrader's `_query_intersects_filename` over 300 random windows;
- `CausalDataLoader.load_bars` returns only bars inside the scoped files' intervals, so the engine reads nothing the check did not prove;
- a forbidden year inside the window refuses with **zero files opened**, and the same year outside the window is irrelevant;
- tampering:
  - same-size tampering of an in-scope file is detected;
  - tampering of an out-of-scope file is detected by the run that reads it and by `verify_dataset_bytes`;
- missing, extra and resized files refuse, in scope or not;
- manifest inconsistencies refuse with zero files opened: wrong entry sha, wrong declared digest, duplicate entry, bad path;
- a file whose footer `ts_init` lies outside its filename interval refuses;
- an uninterval bar file is always in scope, and refuses when any year is forbidden;
- a window with no file of a requested bar type refuses;
- `compute_catalog_digest`, the manifest contract and `verify_dataset_bytes` are unchanged;
- the launch verifier is scoped and refuses prohibited years;
- readiness covers TRAIN plus smoke but not held-out years;
- **readiness refuses with zero files opened** when a TRAIN partition's `_partition_bounds` tail reaches the dev year.

**Mutation check:** with the scope filter and forbidden check disabled, 10 of the 22 fail. Restored, 22/22 pass.

Existing contracts are unchanged: `scripts/tests/test_roots.py` and `test_launch_verification.py` pass 19/19 without edits.

Targeted gate (`test_delta_targeted.json`, 37 files, 543 tests): 494 passed, 34 failed.
- 24 of the 34 are ids already failing on main 8404c72e (broad triage of the OOS chore).
- 10 are `scripts/tests/test_round2_invariants.py`. Each passes alone and passes immediately after the new test file (40/40). It is test-order pollution: a module resolves the repo root to the main checkout (`...\Nautilus Trader`). The same file set is being re-run on a main-identical tree to classify it (see `broad_triage.json`).

Registry: `research cap generate --check` gives 233 entries, 0 broken.

## Real catalog, dry selection (manifest metadata only; no data file opened or hashed)

`NQ_1S_V2_GLOBEX`: 15 inventory entries. There are 14 bar files (2 bar types × 7 source years), every one with a parseable interval, plus 1 non-bar file.

- **A TRAIN-only 2021–2023 study** (5-day warmup, smoke 2023-10-02) hashes **9 files, 1.21 GB**: the 2020 warmup year, 2021, 2022, 2023, and the instrument file. **No 2024–2026 file is in scope.**
- **The sealed `nq_fair_pricing_reversion` TRAIN-2023 launch window** was `[2022-12-27, 2024-01-01T23:59:59.999999999Z]`, because `dev: [2024]` makes `_partition_bounds` extend `run_end` to 2024-01-01. That window **intersects a 2024 bar file**, so that collection opened the 2024 file and streamed the 2024-01-01 Globex evening bars through the engine.
  - Labels are unaffected: candidates come only from the 2023 primary window, the entry cutoff is 11:00 ET, and the session-truncated outcomes end at the 11:30 ET cutoff.
  - It was nonetheless a 2024 read, not only a hash. Under this change, the same study's readiness refuses that window.

## Replay closure and partition reuse

`roots.py`, `backtests/nt_runtime/data_plan.py` and `research_workflow/host_runner.py` are in the replay-stage closure (144 files) and the collection-stage closure (156 files). After this merges, every study recompiled on main gets a **new replay-closure composite**. The plan, dataset, interval and authorization components are unchanged. No repo-file import was added, only lazy third-party imports (`nautilus_trader.persistence.catalog.parquet`, `pyarrow.parquet`), so closure membership is expected to be identical. This is verified on the HV1 recompile after the merge.

| Study | Effect |
|---|---|
| `nq_fair_pricing_reversion` (sealed, 723a0b75) | none: frozen on its own branch, never sees this change |
| `nq_fair_pricing_reversion_hv1_2024` (B) | TRAIN reuse moves from `REUSABLE_BY_AUTHORIZATION_ATTESTATION` (composite equal) to requiring `REUSABLE_BY_CLOSURE_ATTESTATION`: a new reattest must record the closure delta (`membership_identical`) and a bounded replay under the new closure that reproduces the reference replay byte for byte (`attestation_permits`). Separately, B's readiness now **refuses**, because its TRAIN-2023 window reaches into dev 2024 (above). |
| `nq_fpr_price_action` | collects fresh, so it is unaffected |

Replay behaviour: `engine_builder`, `CausalDataLoader`, the strategy and the host are untouched. Verification is read-only and runs before engine construction (the order is asserted by `test_launch_verification.py::test_verification_precedes_engine_construction_in_both_modes`). The loaded bars are whatever NautilusTrader selects for the same window, and that selection is proved equal to the scoped set. No causal or timing logic changed, so the causal audit was not re-run (CLAUDE.md tier rule).

## Broad pre-merge gate (`test_delta_broad.json`)

The run at d50d5171 covered `research_workflow/tests` and `scripts/tests`: 2,630 tests ran, 2,542 passed and 61 failed, in 6,773 s.
- All 61 failing ids are the ones already failing on main (the same set as in the OOS-latch broad triage).
- **0 failures are attributable to this chore.** The baseline was not re-recorded.
- The `test_round2_invariants` order pollution did not occur in the broad ordering.

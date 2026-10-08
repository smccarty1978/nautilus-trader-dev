# rss_curve.json is SUPERSEDED for its "process peak RSS" / "finding_process_peak_rss_not_bounded" claims

## Exact error

The 12.83 / 4.38 / 2.59 GiB "process peak RSS" figures recorded for `1_month` / `1_week` /
`1_day` `chunked_with_profile` in `rss_curve.json` are **not collection memory**. The harness
that produced them (session 3's `vp_rss_variant.py`, not committed) called
`recompute_logical_content_sha256(path, columns)` right after `finalize()`, **inside the same
sampled RSS window** it used to measure collection. At the time, that function's default
`batch_size` was a fixed `50_000` rows -- larger than every partition measured (1,620 / 3,240 /
9,930 rows) -- so `pf.iter_batches()` handed back the **whole file as one batch**, and
`_rows_canonical_from_table` materialized every row's 9 nested profile structs as Python
objects (dicts/lists of ints) all at once. That whole-file Python materialization, not
collection, is what the RSS sampler caught as the "peak".

Root-caused and reproduced in `../../../../../C:\Users\SCOTTM~1\AppData\Local\Temp\claude\...\diag2\DIAGNOSIS.md`
(scratch; not committed) -- see the corrected finding this file replaces, below.

## Corrected reading of `rss_curve.json`

- **`finding_sink_layer_bounded`** (the chunked writer/sink's own per-flush-cycle footprint
  growing only ~550 MB over 2045 flushes in the 1-month run) is **unaffected** and remains
  the valid evidence for the sink/writer's own bounded-memory claim -- it was sampled at
  flush-cycle checkpoints, which are all before the contaminated read-back step.
- **`finding_process_peak_rss_not_bounded_1month_with_profile`** is **WRONG AS STATED**. There
  is no blocker in `features/trackers/volume_profile_rolling.py` or the NT engine's per-tracker
  state proportional to window length. The real, now-fixed cause was this chore's own
  `recompute_logical_content_sha256` default batch size (see
  `research_workflow/host/chunked_writer.py`, Task A fix, commit `e111d077`): the default is
  now derived per-file from a small bounded sample via the writer's own calibrated
  `estimate_row_bytes`, targeting ~4 MiB of Python-object materialization per batch regardless
  of row width, instead of a fixed row count.
- The replay/collection-only peak (excluding any read-back) is, per the flush-cycle-sampled
  evidence already in `rss_curve.json`, bounded and small (well under 2 GiB at 1 month with
  profiles) -- see the corrected real-tape measurement in `rss_curve_v2.json` (bounded-stream
  verification run in its own process, per the new `harness/` scripts).

## What was NOT re-measured here

This note corrects the INTERPRETATION of the existing `rss_curve.json` numbers; it does not
retroactively re-run the 1-day/1-week/1-month variants with the fixed recompute AND a
phase-separated harness. That re-measurement is `rss_curve_v2.json` (one representative
real-tape run, collapsed Task C+D per the narrowed packet).

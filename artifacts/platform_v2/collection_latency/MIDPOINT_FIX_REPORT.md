# Bound the midpoint buffer — parity report

    task_id:   collection_latency_midpoint_fix
    change:    research_workflow/provider_host.py only: ContextAdapter._midpoints is deque(maxlen=64)
               (MIDPOINT_HISTORY = 64) instead of an unbounded list copied on every candidate snapshot
    evidence:  artifacts/platform_v2/collection_latency/evidence/midpoint_parity.{json,samples.jsonl,py}

## Readers of the buffer (all bound providers, all history)

| reader | deepest index | where |
|---|---|---|
| `GenericContextProvider.ema_slope` via `ContextAdapter.snapshot` (current) | `values[-6]` (`lookback` frozen at `FROZEN_FAMILY_A_EMA_SLOPE_STEPS = 5`) | `provider_host.py:286-288`, `generic_context.py:24-27` |
| same adapter before 0fcce218 (2026-08-28) | `values[-21]` (passed the instance's nominal `lookback: 20`) | git history of `provider_host.py` |
| `scripts/run_full_legacy_feature_parity.py` | reads the legacy engine's own `short_ema_history`, not this buffer | n/a |

No consumer slices, aggregates or indexes deeper than `[-21]` in any form the adapter has had. Bound
chosen: **64**, a 3x margin over the legacy nominal read and ~10x over the frozen read; copy cost per
snapshot is 64 floats. `ema_slope`'s warmup rule (`0.0` while fewer than `lookback + 1` values exist) is
unchanged because a deque and a list have the same length until the bound is reached.

## Gate — parity (one run, same harness)

Replayed the sealed `supv1_shape_a_flip_180s_r2` TRAIN 2021 partition (NQ_1S_V2, 13 feature instances,
`GenericContextProvider` bound) through `host_runner.run_plan_on_catalog` with the sealed compiled plan
read-only, whole year, 5-day warmup, persisted with `to_parquet(index=False)` exactly as `_persist` does:

| | sealed partition | replay under this change |
|---|---|---|
| candidates sha256 | `6db21030c189…` | identical |
| observations sha256 | `1132ca54e6c9…` | identical |
| rows | 453,768 / 453,768 | 453,768 / 453,768 |
| **byte-identical** | | **YES** |

## Secondary observation — throughput (same run)

| | before (S1.0 probe, same plan, same year) | after |
|---|---|---|
| engine run | 1,437 s | **408 s** (wall 422 s) |
| first-decile bars/s | 23,660 | 30,395 |
| final-decile bars/s | 3,704 | 30,284 |
| decay ratio (first/final) | 6.4 | **1.00** |
| cumulative bars/s | 8,625 | 30,535 |
| RSS start → end | 4.0 → 4.4 GB | 4.0 → 4.4 GB |

Throughput is flat across the year. The sealed partition's own recorded replay was 1,182 s, so a
single-year replay is now ~3.5x faster than the sealed baseline and 7 minutes rather than 20 to 24.

## Consequence for S2

At ~7 min a year, three concurrent years would meet the 15–20 minute target without concurrency work;
a sequential 4-year TRAIN is ~28 min against the 5,260 s (88 min) W0 baseline. S2 is optional. Not
started here. The C6 engine-config items are untouched (own commit, own parity check).

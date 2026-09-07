# NT_COLLECTION_PERFORMANCE.md

Class: **CURRENT**. Scope: the NautilusTrader-side conditions a Platform V2
collection host must satisfy, and the order in which to diagnose a slow replay.

This document is about **replay throughput only**. It says nothing about
governance, seals, audits or study lifecycle.

---

## 1. THE INVARIANT

> **A correct NT replay has flat throughput.**

NT is a streaming event loop with a bounded cache. Bars/s at hour 200 of a run
should equal bars/s at hour 1. **Any monotonic decay is a defect in the host or
the data-loading path, not a property of NT and not a property of the dataset.**

A decaying replay must be fixed, not parallelized around. Sharding a decaying
replay hides the defect and makes it permanent, because sharding resets the
accumulation and the symptom disappears while the cause remains.

Reference figure for this repo: record measured bars/s for a full year in
`WORKFLOW_REFERENCE_FACTS.md`, alongside the decay ratio (bars/s in the final
decile ÷ bars/s in the first decile). **Target decay ratio: 1.0. Alarm: > 1.2.**

---

## 2. DIAGNOSTIC ORDER

Work top to bottom. Stop when the decay ratio reaches ~1.0. Do not skip ahead to
parallelism.

### 2.1 `add_data()` call count per instrument — CHECK THIS FIRST

NT's documented behaviour: each `add_data()` call copies its input into an
independent stream, and the engine merges streams chronologically at run time.
Adding **one batch per instrument** does not repeatedly sort a cumulative list.

The inverse is the defect: **many `add_data()` calls for the same instrument
re-sort a growing list on every call.** A per-day or per-file loader over a year
pays roughly 250 sorts over a list growing to ~11M elements. This is
superlinear, invisible in a one-month benchmark, and produces exactly a
monotonic multi-fold decay.

**Check:** instrument the host; count `add_data()` calls per instrument per run.

**Fix, in preference order:**

1. One `add_data()` call per instrument per partition, with the batch assembled
   before the call.
2. If batching is structurally required: `add_data(..., sort=False)` for every
   batch, then a single `sort_data()` before `run()`. Note that `sort=False`
   marks the engine not-ready; readiness must be restored by `sort_data()` or a
   later `sort=True` call, or `run()` will refuse.

Reference: https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/

### 2.2 NT version

NT release notes record a fix for a `DataBackendSession` chunked streaming
memory leak causing RSS growth (#3889). If the host streams from the catalog on
a version predating that fix, this alone can produce the symptom.

**Check:** pin and record the NT version in
`WORKFLOW_REFERENCE_FACTS.md`. Compare against `RELEASES.md` for streaming and
memory fixes landed since.

Reference: https://github.com/nautechsystems/nautilus_trader/blob/develop/RELEASES.md

### 2.3 API level versus partition size

There is **no built-in chunking at the `BacktestEngine` (low-level) level**.
`chunk_size` exists only on the high-level `BacktestNode`. A low-level engine
holding a full year of 1s bars keeps every object resident for the whole run.

**Check:** which API the host uses, and peak RSS across a full-year partition.

**Two valid resolutions — pick one and declare it:**

- Keep the low-level engine and **reduce the partition to what fits comfortably**
  (month, or day). Governed partition semantics already exist for this.
- Move catalog-backed loading to the high-level `BacktestNode` with an explicit
  `chunk_size`.

Do not do both silently. The choice changes the memory profile and therefore the
safe concurrency bound.

References:
https://github.com/nautechsystems/nautilus_trader/discussions/3736
https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/

### 2.4 Engine configuration not stripped for collection

A collection run computes features. It does not trade. Everything execution-side
is pure overhead and some of it is per-event.

Baseline for a collection host:

```python
BacktestEngineConfig(
    logging=LoggingConfig(log_level="ERROR"),
    bypass_logging=True,          # collection emits rows, not logs
    run_analysis=False,           # no post-backtest performance analysis
    risk_engine=RiskEngineConfig(bypass=True),
    cache=CacheConfig(
        tick_capacity=<declared>,  # do not raise above what features need
        bar_capacity=<declared>,
    ),
)
```

Actors only. No Strategy, no orders. If the study declares no economic work, the
execution path should not be exercised at all.

References:
https://nautilustrader.io/docs/latest/concepts/logging/
https://nautilustrader.io/docs/core-nightly/nautilus_backtest/config/struct.BacktestEngineConfig.html

### 2.5 Cache capacity

Defaults are bounded: the Cache keeps the last 10,000 bars per bar type and
10,000 ticks per instrument. Bounded defaults mean the cache is **not** a decay
source unless someone raised them.

**Check:** the host's `CacheConfig`. If capacities were raised to accommodate a
feature's lookback, that is an unbounded-growth risk and the feature's lookback
should be satisfied by the provider, not by the cache.

Reference: https://nautilustrader.io/docs/latest/concepts/cache/

### 2.6 Telemetry

`tracemalloc` dominates replay wall time when enabled (`WORKFLOW.md` §7).
Confirm unset. Process RSS telemetry is cheap and stays on.

---

## 3. PARALLELISM — CORRECT, BUT SECOND

NT has **no multi-core parallelism within a single `BacktestEngine` run**; the
simulation loop is single-threaded by design, for determinism. The only sanctioned
parallelism is **process-per-partition**, which is what this repo already does.

So the partitioning architecture is right. It is simply in the wrong order:

1. Fix decay (§2). A flat replay may make the rest unnecessary.
2. Then concurrency across partitions, bounded by measured peak RSS ÷ available
   RAM, not by core count.
3. Then finer partition granularity, gated on the warmup question below.

Reference: https://github.com/nautechsystems/nautilus_trader/discussions/3736

---

## 4. WARMUP — GATE ON SUB-YEAR SHARDS

The compiler's proven warmup bound is a **feature** warmup bound. It does not
establish that a **sticky tracker** (one that holds state until opposite
conditions are met) has converged. These are different claims.

Before sharding below month granularity, measure convergence directly: identical
primary intervals with escalating prefixes, compared on regime state and
population membership at primary start. The shortest prefix giving exact
agreement across a representative sample is the bound, and it belongs in the
compiler as a tracker-convergence fact distinct from feature warmup.

If a sticky tracker never converges within a bounded prefix, sub-year sharding is
invalid for any study using it. Know this before building for it.

---

## 5. ACCEPTANCE TEST — THE DECAY TEST

Any change to the collection host must report:

    bars/s, first decile
    bars/s, final decile
    decay ratio
    peak RSS
    add_data() calls per instrument
    NT version

Pass: decay ratio ≤ 1.05. Investigate: > 1.2. A change that improves total wall
time while leaving the decay ratio above 1.2 has not fixed anything; it has
rescheduled the cost.

---

## 6. WHAT NOT TO CONCLUDE

- Do not conclude a month benchmark generalizes to a year. Under decay it never
  will, and the gap is the measurement of the defect.
- Do not attribute a shard speedup to concurrency until the decay ratio is ~1.0.
  Sharding resets accumulation, so it will appear to work regardless.
- Do not raise cache capacities to satisfy a feature lookback.
- Do not conclude the governance chain is the cost. Measured here: replay 58–82%
  of an iteration, audits 11–19%.

## 7. MEASURED OUTCOME (2026-09-06, chore/collection_latency)

The diagnostic order above was run statically against the host (no replays started). Verdicts:

| check | finding | verdict |
|---|---|---|
| 2.1 `add_data()` calls | two per partition, one batch per stream (`utils/causal_registration.py:56-57`), default sort | CLEAR |
| 2.2 NT version | 1.230.0; `DataBackendSession` (#3889) not on our path | CLEAR |
| 2.3 API level | low-level `BacktestEngine`, whole year resident (~4 GB), no chunking | CLEAR (memory, not decay) |
| 2.4 engine config | defaults; `log_level=ERROR` only | CLEAR (C6 wins are a separate commit) |
| 2.5 cache | bounded defaults | CLEAR |
| 2.6 telemetry | `NT_TELEMETRY_TRACEMALLOC` unset | CLEAR |
| host per-snapshot path | `research_workflow/provider_host.py` `ContextAdapter._midpoints`: unbounded list of every completed 1m midpoint, copied whole on every candidate snapshot although `ema_slope` reads only `[-1]` and `[-6]` | **CAUSE** |

Fix: `deque(maxlen=64)` (commit 3e441fcc). Decay test (§5) on the sealed `supv1_shape_a_flip_180s_r2`
TRAIN 2021 partition, same harness: byte-identical rows; first-decile 30,395 bars/s, final-decile
30,284 bars/s, **decay ratio 1.00** (was 6.4); engine time 408 s (was 1,437 s). A single year is ~7 minutes,
so §3 (parallelism) is optional and §4 (warmup before sub-year shards) is not yet needed. Figures live in
`WORKFLOW_REFERENCE_FACTS.md`; the run is `artifacts/platform_v2/collection_latency/MIDPOINT_FIX_REPORT.md`.

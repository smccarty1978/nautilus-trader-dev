# S1 — W2-prime: replay-closure partition reuse key

    task_id:      collection_latency_s1
    branch:       chore/collection_latency (from main be66e8de; W0 report at 5177f808)
    scope:        S1 only. Sub-year shards, collected-frame reuse (W3), warmup-prefix reduction and audit
                  triggering are NOT touched. Bounded concurrency is S2 (separate session).
    evidence:     artifacts/platform_v2/collection_latency/evidence/ (s10 probe samples, s1 real-data json)

## S1.0 Throughput probe — MONOTONIC DECAY (state accumulates)

Same harness as a partition (`host_runner.run_plan_on_catalog`), closed study `supv1_shape_a_flip_180s_r2`
plan read-only, NQ 2021 whole year, `progress.json` sampled every 10 s (`evidence/s10_probe.samples.jsonl`):

| bars (M) | elapsed s | cumulative bars/s | interval bars/s | interval candidates/s | interval epochs/s | RSS MB |
|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 39 | 25,774 | | | | 4,041 |
| 2.2 | 90 | 24,576 | 23,660 | 819 | 4,162 | 4,080 |
| 4.4 | 201 | 21,926 | 18,237 | 693 | 3,226 | 4,150 |
| 6.5 | 363 | 17,913 | 11,653 | 445 | 2,061 | 4,223 |
| 8.5 | 608 | 13,973 | 7,255 | 298 | 1,303 | 4,292 |
| 10.5 | 956 | 10,981 | 5,203 | 191 | 924 | 4,349 |
| 12.3 | 1,406 | 8,751 | 3,704 | 133 | 660 | 4,405 |

Totals: 12,392,181 bars in 1,437 s engine time (8,625 bars/s cumulative), 453,768 candidates — identical
to the sealed `train-2021` partition's count, so the probe is the partition's own path. Peak RSS of this
in-process run 4.67 GB (the W0 live partition child showed 1.06 GB working set mid-run; S2 must measure the
child directly rather than trust either figure).

Shape: **monotonic decay, 6.4x from the first million bars to the last** (23.7 k to 3.7 k bars/s), with
epochs/s and candidates/s decaying by the same factor while RSS grows only 9 %. Cost per epoch grows with
the number of candidates already emitted (31 k to 450 k), i.e. something on the per-epoch path scans or
copies accumulated state. Located by the follow-up static diagnostic (same day): `research_workflow/provider_host.py:259/273/287`
— the frozen-parent `ema_slope` adapter appends every completed 1m midpoint to an unbounded list and
copies the whole list (`values=list(self._midpoints)`) on every candidate snapshot, although the consumer
reads only the last six values. Sink, outcome kernel, mux and every other tracker are bounded. Smallest fix:
`deque(maxlen=FROZEN_FAMILY_A_EMA_SLOPE_STEPS + 1)`, output byte-identical. **Not fixed here; it is its own
packet**, confirmed by one single-year replay. Consequences stated plainly:

- the W0 month benchmark (23.4 k bars/s) is NOT representative of a year (8.8 k bars/s cumulative);
- S2's ~1,500 s projection for a 4-year TRAIN (max single year at today's rate) is the honest bound for
  concurrency alone; the remaining multiple (≈ 2.7x at today's decay) lives in the throughput packet;
- sub-year shards would recover most of the decay by construction (each shard restarts the accumulation),
  which is a reason to sequence the throughput fix before W1-shard so that a shard speedup is not
  misattributed.

## S1.1 Semantic decision — the replay closure is DERIVED

`replay_closure_sha256 = H(CompiledPlan.closure.stages.collection.composite + replay-affecting plan subset +
dataset {id, logical_digest} + partition interval {period, year, primary, run_end, warmup_days, windows} +
authorization_sha256)` — `research_workflow/replay_closure.py`. `stages.collection` is the compiler's own
derivation (bound host/provider/tracker modules + transitive repo imports), never an enumerated list.
The plan subset excludes only `analysis`, `model`, `study`, `notes`, the identity fields and
`chronology.partition_reuse` (proven output-neutral by test). `replay_closure ⊆ manifest` is tested.

**Empirical membership proof (smoke import trace) found a real hole.** On the first real-data smoke the
trace reported `REPLAY_CLOSURE_ESCAPE` for `backtests/nt_runtime/__init__.py` and
`research/schemas/__init__.py`: package `__init__` modules that Python executes on every import of a
submodule (the first one re-exports the compiled-study loader), yet the static walk resolved `a.b.c` to
`a/b/c.py` only. They were in neither the collection closure **nor the 90-file frozen manifest** — a
pre-existing closure hole (nine such package inits under the manifest's packages). Fixed in the strict
direction in `transitive_closure_files`: importing a module now also closes over every ancestor
package `__init__.py` and their imports. Collection-stage closure 85 → 111 files; the manifest grows
accordingly. This is a derivation fix, not a trace-driven widening: the trace stays a hard assertion.

**Escalation (not decided here):** `research_workflow/grammar/compiler.py` is a closure seed and statically
imports `research/analysis/diagnostic_ops.py` → `model_store.py` → `policy.py` → `lifecycle_v2.py` → …, so
the derived collection closure contains the controller and the analysis modules. Under the strict key both
2026-09-06 live cases (`controlled_feature_family_180s` it.2: `diagnostic_ops.py` + `lifecycle_v2.py`;
`es_180s_model_c_portability` it.2: the same two files) are **refused**, correctly by the rule and uselessly
for the latency goal. Two readings, both consequences stated:

1. keep the strict derived key (implemented): reuse fires for spec-only analysis/text/model edits and for
   platform changes outside the collection stage (audit packets, controllers' contracts, workspace), never
   for a controller or analysis-module change; both live cases stay re-collections;
2. remove the compiler from the seed set (it is compile-time code, not replay code) so the derivation
   stops at the host/provider/tracker modules and what THEY import: both live cases would reuse. This
   narrows the *key* only (the manifest keeps every file); whether a static-import walk seeded without
   the compiler still proves every replay module needs the smoke trace as its check — which now exists.

## S1.2 Re-attestation — reconcile, deterministic

`reconcile` re-attests every partition whose manifest plan differs from the current plan: receipt
present (`_work/controller/train_partition_reuse.json`), key re-derived from the CURRENT plan equal to
the recorded key, recorded components re-hash to the recorded key, parquet bytes re-hashed to the
manifest, shadow record for this seal IDENTICAL (or skipped by a declared sampled policy). Findings
otherwise; a foreign-plan partition under `off` is a finding. The contract audit packet carries
`partition_reuse` (declared policy + per-partition would-reuse decision and reason), so the auditor
audits the reuse decision and its receipt, never the data.

## S1.3 Shadow verification

Every reuse run recomputes one reused partition (uniform over the reused set, seeded by the seal so the
choice is reproducible) into `partitions_shadow/` and requires byte-identity; a mismatch raises
`PARTITION_REUSE_SHADOW_MISMATCH` (terminal; reconcile refuses afterwards). Bake-in proposal: `every_run`
until **five consecutive studies** have cleared, then `partition_reuse_shadow: sampled` (one run in four).
Cost of `every_run` with N reused partitions is 1/N of the replay saved.

## S1.4 Gates

| # | gate | result |
|---|---|---|
| V1 | replay-module change refuses reuse | PASS (test: host/strategy.py hash perturbed → REFUSED, all recomputed; real data: `features/trackers/generic_arrival.py` statement added → REFUSED for both years, reason `REPLAY_CLOSURE_CHANGED:collection_closure_composite_sha256`; file restored, no diff) |
| V2 | post-collection-only change reuses, bytes = forced recompute | PASS (test: study text and audit-stage module; real data ES 2020+2021: both partitions reused, served bytes identical to the baseline manifests; shadow recompute of 2021 IDENTICAL (candidates `6db21030…`, observations `1132ca54…`); reconcile PASS with both re-attested and receipt recorded) |
| V3 | live case | REFUSED BY THE STRICT KEY (escalated above; real data: `research/analysis/diagnostic_ops.py` perturbation → REFUSED for both years, same reason. Correct under the strict key; the latency goal for this case needs the escalated seed decision) |
| V4 | sealed studies reproduce bit-identically, reuse off and on | PASS. Real data: the scratch run under this branch (reuse declared, 111-file closure) reproduced the live sealed `es_180s_model_c_portability` partitions produced by `main` **byte-for-byte** — 2020 candidates `970834a5…`/observations `0eb4550f…`, 2021 `6db21030…`/`1132ca54…`, 494,455 and 478,407 rows. Test: `off` recompute bytes = `replay_closure` bytes; `off` remains plan+seal matching. |
| V5 | shadow on every partition of one full TRAIN year | PASS. Real data: shadow recompute of the full TRAIN year 2021 (11.0 M bars, 1,407 s) byte-identical to the reused partition. Test: injected shadow mismatch is terminal and reconcile refuses afterwards. |
| V6 | wall-clock, analysis-only iteration vs W0 | Baseline (phase A, ES 2020+2021 sequential): **3,032 s**. Analysis-only iteration with `every_run` shadow (phase B): **1,422 s** (both years served in <1 s, the shadow year 1,407 s) = 47 % of baseline, i.e. 1 − 1/N for N = 2. Analysis-only iteration with `sampled` shadow skipped by the seed (phase C): **0.07 s**. Against W0: the live analysis-only cff iteration paid ≥ 7,200 s of re-collection; under this key it would pay one shadow year (≈ 5,000 s for that 35-instance surface, 0 s under sampled), but only once the escalated seed question is settled, because its closure change was in the collection stage. |

Tests: `research_workflow/tests/test_replay_closure.py` (11). Targeted `test_delta` over the touched
suites (chronology windows, lifecycle v2, controller stages v2, grammar v2, partitioning, closure transitive
imports, red-team closure, docs v2, supervisor closure validity, closure validate-before-write, replay
closure): 88 ran, 88 passed, 0 `NEW_FAILURE` (`evidence/targeted_test_delta2.json`). Real-data phase A
baseline (ES 2020+2021, sequential, host contended by the S1.0 probe for the first year): 3,032 s;
smoke trace `WITHIN_CLOSURE`, 18 traced repo files, 0 preloaded-outside. `scripts/lint_host.py` CLEAR; `research cap generate --check` OK;
`scripts/gen_yaml_reference.py --check` current.

## Housekeeping

`scripts/benchmark_historical_same_harness.py` recorded as a known defect in
`docs/WORKFLOW_REFERENCE_FACTS.md` → "Known defects (framework backlog)". `docs/RESEARCH_WORKFLOW.md`
§21.13 documents the capability; `docs/RESEARCH_YAML_REFERENCE.md` regenerated.

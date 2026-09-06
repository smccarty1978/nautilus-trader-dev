# W0 — Platform V2 collection latency: measurement report

    task_id:      collection_latency_w0
    branch:       chore/collection_latency (from main be66e8de)
    measured:     2026-09-06, host NUCBOX_K10 (20 logical / 14 physical cores)
    scope:        measurement only; no code changed; no study recompiled, resealed or migrated
    evidence:     artifacts/platform_v2/collection_latency/evidence/*.json (same-harness benchmarks)

## W0.1 Cheap checks

| check | value |
|---|---|
| `NT_TELEMETRY_TRACEMALLOC` process env | unset |
| `NT_TELEMETRY_TRACEMALLOC` User / Machine env (registry) | unset / unset |
| partition child cmdline observed live | `python -m research_workflow.lifecycle_v2 partition --study ... --year 2024` (PID 12604), no telemetry override |

tracemalloc is off. It is not the cause.

## W0.2 Cycle decomposition (three real iterations, wall clock from artifact mtimes and controller logs)

Timing source: `_work/controller/logs/<stage>.log` create time (stage start), `progress.json` / `manifest.json`
`elapsed_s` (replay), audit packet mtime to `audit/*_pass_NN.md` mtime (audit incl. agent turnaround),
receipt mtimes (stage end). Receipts carry no timestamps; nothing in `_work/controller` records stage durations.

### A. `supv1_shape_a_flip_180s_r2` — NQ, TRAIN 2021 + OOS 2022, 13 feature instances, supervised, closed (00:44:34 to 01:59:10, 4,476 s)

| stage | s | % | note |
|---|---:|---:|---|
| design + compile | 57 | 1.3 | compile itself about 9 s |
| prepare / readiness / preflight | 23 | 0.5 | |
| tests (test_summary) | 49 | 1.1 | |
| causal audit (packet to pass_01.md) | 457 | 10.2 | agent turnaround; packet generation 5 s |
| contract audit (packet to contract_pass_01.md) | 376 | 8.4 | incl. 42 s packet generation |
| seal | 45 | 1.0 | |
| smoke | 26 | 0.6 | replay 17.6 s, 103,305 bars |
| collection TRAIN 2021 | 1,200 | 26.8 | replay 1,182 s, 12.39 M bars, 453,768 candidates |
| reconcile + merge + fit + freeze | 18 | 0.4 | |
| OOS 2022 collection | 1,350 | 30.2 | replay 1,312 s, 13.83 M bars |
| analyze (declarative) | 1 | 0.0 | |
| analysis decision (agent) | 494 | 11.0 | |
| close + handoff + validation card | 210 | 4.7 | |
| supervisor scheduling gaps | ~170 | 3.8 | |

Replay (smoke + TRAIN + OOS) **57.5 %**; audits **18.6 %**; analysis-decision agent **11 %**; everything else at most 5 % each.

### B. `controlled_feature_family_180s` — NQ, TRAIN 2024 (+ dev window 2025Q1), 35 feature instances

Iteration 1 (07:19:23 to 09:06:04, 6,401 s, ended in a fit-stage platform defect, `_train_frame_all_labels`):

| stage | s | % | note |
|---|---:|---:|---|
| prepare / readiness / preflight | 7 | 0.1 | |
| causal audit | 529 | 8.3 | |
| contract audit | 705 | 11.0 | |
| seal | 18 | 0.3 | |
| smoke | 70 | 1.1 | replay 66 s, 247,330 bars |
| collection TRAIN 2024 | 4,974 | 77.7 | replay 4,956 s, 12.50 M bars, 450,973 candidates |
| reconcile + merge | 6 | 0.1 | |
| fit, FAILED | 59 | 0.9 | |

Replay **78.8 %**, audits **19.3 %**.

Iteration 2 (10:06:15 to still collecting at 12:43): spec change was **analysis-only** (commit 843e84dd, `analysis:` block)
plus a merge of `main` carrying the `analysis.gate.arm_delta_integrity` capability. The frozen execution manifest
changed in exactly two of its 90 files: `research/analysis/diagnostic_ops.py` and `research_workflow/lifecycle_v2.py`
(composite `da3d3ab4...` to `14b13abb...`). Neither file runs during replay. Consequence: full re-audit (compile 65 s,
readiness/preflight 12 s, tests 49 s, causal audit 299 s, contract audit 337 s which FAILED, decision-contract fix,
contract pass 03 190 s plus about 245 s owner turnaround, seal 18 s, smoke 84 s: about 1,300 s) **and** a full
re-collection of 2024 (started 10:34:07; 7,195 s and 11.2 M bars at 12:34, not final; iteration 1 took 4,956 s; the
re-run is contended by a concurrent broad `test_delta` pytest). Iteration-2 cost so far about 9,400 s, at least 80 %
of it replaying a byte-identical replay closure.

### C. `es_180s_model_c_portability` — ES, TRAIN 2020–2023, 13 feature instances

Iteration 1 (07:34:26 to 09:21:54, 6,448 s, ended in a freeze-stage platform defect, `KeyError: 'name'`):

| stage | s | % | note |
|---|---:|---:|---|
| design (study.yaml, decision, SPEC, handoff) | 333 | 5.2 | |
| prepare / readiness / preflight | 7 | 0.1 | |
| causal audit | 413 | 6.4 | |
| contract audit | 276 | 4.3 | |
| seal | 15 | 0.2 | |
| smoke | 6 | 0.1 | replay 3.3 s, 93,720 bars |
| collection 2020 / 2021 / 2022 / 2023, **sequential** | 1,273 / 1,197 / 1,494 / 1,281 = 5,260 | 81.6 | replay 1,258 / 1,182 / 1,477 / 1,267 s |
| reconcile + merge + fit | 22 | 0.3 | |
| freeze, FAILED | 1 | 0.0 | |

Replay **81.7 %**, audits **10.7 %**. The four partitions finished at 08:15, 08:35, 09:00, 09:21: one at a time.

Iteration 2 (10:51:59 to 11:05:37 so far): **no spec change** (study.yaml mtime 07:34, one commit); the platform fix
for the freeze defect changed the closure (composite `da3d3ab4...` to `4f766f57...`, plan `e9faf3b0...` to `17b15976...`).
Re-audit done (readiness/preflight 12 s, tests 48 s, causal 300 s, contract 440 s). The four partition manifests still
carry plan `e9faf3b0...` / seal `661099...`; `_partition_valid()` (lifecycle_v2.py:619) compares `plan_sha256` and
`composite_seal_hash`, so the next `collection` call will re-replay all four years (about 5,200 s) for a freeze-stage fix.

### Cross-iteration summary

| iteration | replay % | audits % | trigger of the *next* iteration | replay closure changed? |
|---|---:|---:|---|---|
| A supv1_r2 | 57.5 | 18.6 | none (closed); r2 itself was a no-spec-change re-run of r1 | no |
| B cff_180s it.1 | 78.8 | 19.3 | platform defect at fit | no |
| B cff_180s it.2 | >= 80 | ~14 | analysis-only spec change + analysis capability merge | **no** (2 non-replay files) |
| C es_180s it.1 | 81.7 | 10.7 | platform defect at freeze | no |
| C es_180s it.2 | (pending 5,200 s) | ~800 s | platform fix in lifecycle_v2.py | **no** |

## W0.3 Iteration classification (every `study.yaml` change on every study branch since Platform V2)

| study | commit / event | class |
|---|---|---|
| v2_shape_c_barrier_race_fade | 1f5c8ea4 model+outcome (`horizon_end_rule`) | (a) |
| first_p90_warning_horizon_march2024 | a34f7e87, bc54c546, 48e25fe2 features (frozen-model bind / rebind / null_input) | (a) x3, all pre-execution design compiles |
| first_p90_warning_horizon_march2024 | 2d6071b6, ad916bbd `analysis:` | (c) x2, pre-execution |
| regime_transition_target_before_stop_v1 | fde7a968 target; b69739a6 execution+model | (a) x2, V1-era |
| controlled_feature_family_180s | 86cc048b `analysis:` (pre-execution) | (c) |
| controlled_feature_family_180s | 843e84dd `analysis:` (post-collection, **caused a full re-collection**) | (c) |
| supv1_shape_a_flip_180s to _r2 | new study id, identical spec, supervisor validation re-run | (d) |
| es_180s_model_c_portability it.2 | recompile after platform fix, spec untouched | (d) |
| es_180s_regime_flip_model_c_portability | uncommitted predecessor design, never executed | design only |

| class | count | of which caused a re-collection after a completed collection |
|---|---:|---:|
| (a) execution-closure change | 8 | 0 |
| (b) population-predicate change only | **0** | 0 |
| (c) analysis-declaration change only | 4 | 1 |
| (d) no spec change, re-run only | 2 | 2 (one pending) |

Every post-collection re-collection in the record (3 of 3) replayed a byte-identical replay closure. None was a
population change. Hypothesis B is confirmed, but its mechanism is **not** `population.qualify` inside `spec_sha256`
(that path has never been exercised). The measured mechanism is:

1. **Closure granularity.** `audit/frozen_execution_manifest.json` hashes 90 files, including modules that never run
   during replay: `research_workflow/lifecycle_v2.py` (the controller), `research/analysis/*` (five files),
   `tuning.py`, `model_store.py`, `model_artifacts.py`, `modeling_drivers.py`, `oos_analysis_lineage.py`,
   `study_closure.py`, `workspace.py`, `locks.py`, `test_selection.py`. Any analysis capability, freeze/OOS/analyze
   fix, or supervisor-adjacent change changes the composite.
2. **Partition cache key.** `_partition_valid()` keys reuse on `plan_sha256` **and** `composite_seal_hash`; the seal
   hash folds in both audit report hashes, so every re-seal (even with an unchanged plan) invalidates every partition.

Both are governance *granularity*, not governance *strength*: the seal chain is correct and stays as is.

## W0.4 Replay throughput baseline (same harness)

`scripts/benchmark_historical_same_harness.py` **cannot run on the current tree**: it hard-codes the historical study
`clean_maturity_flip_model_rolling_productivity`, whose compiled artifact is stale (`STALE_COMPILED_STUDY`, current
hash `0a682d1d...` vs compiled `f0d3623a...`), and recompiling a historical study is prohibited. It also drives the V1
`compiled_study_loader` / `MinimalCheckpointCollector` path, not the V2 host. Finding: the recorded benchmark is
no longer executable against the harness V2 studies use.

Substitute, same harness as a V2 partition (`research_workflow.host_runner.run_plan_on_catalog`, the exact call
`LifecycleV2._run_window` makes), read-only compiled plan of the closed study `supv1_shape_a_flip_180s_r2`
(NQ_1S_V2_GLOBEX, 13 feature instances), March 2021 with the standard 5-day warmup prefix, host
contended by one partition child and one broad pytest run:

| run | bars | engine.run s | bars/s | epochs/s | candidates (dropped warmup) |
|---|---:|---:|---:|---:|---:|
| 1 month plain (`evidence/w04_plain.json`) | 1,435,601 | 61.25 | **23,437** | 4,153 | 41,971 (6,628) |
| 1 month cProfile (`evidence/w04_prof.json`) | 1,435,601 | 102.95 | 13,945 | 2,471 | same |
| 2 months plain (`evidence/w04_2mo.json`) | 2,429,163 | 100.63 | 24,139 | 4,275 | 79,413 (6,628) |

Scaling: 1 month and 2 months run at the same per-bar rate (23.4 k vs 24.1 k bars/s), so cost is linear at that
scale; the full-year rate below is still 2.2x slower per bar than a 1–2 month window of the same plan, with the
same 13-instance surface, and this gap is not explained by contention (ES years ran at 9–10 k bars/s alongside
another collection, NQ 2021 ran alone at 10.5 k). Something grows with partition length beyond two months (the
host keeps the year's 450 k candidate rows in memory: 1.06 GB RSS). Measure a 6-month window before W1-shard so a
shard speedup is not misattributed to concurrency.

Full-year partitions today (from `partitions/*/progress.json`): NQ 2021 supv1_r2 12.39 M bars / 1,182 s =
**10,484 bars/s**; ES 2020–2023 10,005 / 9,214 / 9,038 / 8,706 bars/s; NQ 2024 cff (35 feature instances)
12.50 M / 4,956 s = **2,523 bars/s**.

Recorded figure (`docs/WORKFLOW_REFERENCE_FACTS.md`, 2026-08-24): 213,431 events in 5.73 s = **37,248 events/s**,
historical collector, one smoke day. Verdict: per-event throughput is 1.6x lower on a month and 3.6x lower on a
full year for the same 13-instance surface, and 15x lower for the 35-instance surface. The workload grew (every
qualifying epoch emits a wide candidate row: 450 k rows/year; instance count 13 to 35 triples cost); whether the
harness itself regressed cannot be separated without the historical benchmark, which no longer runs.

Per-component cost (cProfile, 104.4 s profiled; scale by 0.59 for the unprofiled run):

| component | s | % |
|---|---:|---:|
| NautilusTrader engine + catalog load + `add_bars_causal_order` (self time of `run_plan_on_catalog`, not Python-visible) | 32.1 | 31 |
| host `on_bar`: provider/tracker updates (`host_bindings.on_bar` 20.9 s + `provider_host.on_event` 9.4 s) | 30.3 | 29 |
| host `on_bar`: epoch evaluation (`_epochs` 26.2 s: predicates, candidate registration, `provider_host.snapshot` 14.0 s for 48,599 snapshots) | 26.2 | 25 |
| host `on_bar`: mux / routing / `resolve` overhead | ~10 | 10 |
| parquet materialisation, hashing, misc | ~5 | 5 |

Heaviest single tracker: `rolling_5m_productivity` (7.1 s update + 5.0 s snapshot = 12 % of the profiled run).

## W0.5 Concurrency observed

`LifecycleV2._collect_period` (lifecycle_v2.py:664–698) runs `subprocess.run(...)` per year **inside a for-loop**:
blocking, one child at a time. The V1 path (`research_workflow/collection.py:104`) is likewise a sequential
`ProcessPoolExecutor(max_workers=1)` per partition.

| observed (12:39, during `controlled_feature_family_180s` TRAIN 2024) | value |
|---|---|
| concurrent partition child processes | **1** (PID 12604) |
| partition child CPU | 0.94 cores, RSS 1,055 MB |
| system CPU (incl. an unrelated 1-core pytest) | 17–18 % |
| host cores | 20 logical / 14 physical |
| utilization ratio | 1 / 20 logical = **5 %**; 1 / 14 physical = 7 % |

ES 4-year TRAIN: 5,260 s sequential; the largest single partition is 1,494 s, so four concurrent children would
bound it at about 1,500 s (3.5x) with about 4.2 GB RSS, without any sub-year sharding.

## W0.6 Warmup breadth (no change made)

The prefix is **bounded, but fixed, not compiler-proven**. Code path: `LifecycleV2Options.warmup_days = 5`
(lifecycle_v2.py:299) to `_run_window` to `run_plan_on_catalog(..., warmup_days=5)` (host_runner.py:145) to
`resolve_dataset_plan`, `warmup_start_dt = start_dt - 5 days` (host_runner.py:140). The compiled plan carries
`warmup.max_warmup_seconds = 840` (14 x 1 m bars) and `warmup.days_before_partition = 5`; the runtime reads neither.
It streams 5 calendar days (all sessions, ETH included) ahead of `primary_start`, then `retain_primary_rows` drops the
prefix rows. Cost today: about 1.4 % of a whole-year partition (5,242 of 450,973 candidates dropped in cff 2024),
negligible. Cost for a monthly shard: **16 %** (6,628 of 41,971 in the March 2021 run), material for W1, where the
proven 840 s bound (plus the session table's own lookback) is the correct prefix. ETH is not cut and must not be.

## Recommendation

Both hypotheses are true, and they are independent. Hypothesis B dominates *iteration* cost: all three observed
re-collections replayed an unchanged replay closure, charged 5,000–7,700 s each, and were triggered by analysis-only
spec edits or post-collection platform fixes, never by a population change, so **W2 as scoped (a separate
`population.qualify` selection closure) is not what the evidence supports**. The supported form is a second, narrower
identity for the *replay closure* (plan replay subset + the modules the host actually imports during replay), used
only as the partition-reuse key, with a governed reconcile-time proof that a reused partition's replay identity equals
the current plan's; the seal, the 90-file manifest and every audit stay exactly as they are. Hypothesis A is real and
mechanically simpler: concurrency is 1 of 20 cores, and the existing per-year subprocesses are already isolated, so a
declared bounded pool over the current year partitions (no sub-year shards, no semantic collision) recovers about 3.5x on
multi-year TRAIN with no parity question; sub-year shards come after and need the W0.6 prefix bound first. Order:
**W2-prime (replay-closure identity + partition reuse), then W1-year (bounded concurrent year partitions), then
W1-shard, then W3.** W3's collected-frame reuse is the cross-study generalisation of W2-prime and should not be
proposed until W2-prime proves that partition reuse is expressible. Semantic decisions to escalate before W2-prime:
which files constitute the replay closure (candidate reading 1: the import set of `research_workflow.host` + bound
trackers/providers + `host_runner` + `partitioning` + data plan; reading 2: an explicit allowlist in the compiler),
and whether a partition reused across a re-seal must be re-attested by the contract audit or by the reconcile proof
alone.

# Workflow Reference Facts

Facts that were moved out of `docs/RESEARCH_WORKFLOW.md` because they describe **the state
of the system right now** rather than a rule. They go stale; the rules do not.

Each entry names the command that regenerates or re-verifies it. **Re-derive before relying
on a number here** — do not quote these figures into a study report.

---

## Feature authority bundle

| Fact | Value as of 2026-08-25 | Re-derive with |
|---|---|---|
| Active bundle | `candidate`, `activation_kind: feature_pipeline_v2` | `cat features/authority/active.json` |
| Canonical definitions | 129 | `python -c "import json;print(len(json.load(open('features/authority/candidate/canonical_registry.json'))['definitions']))"` |
| Legacy aliases mapped | 693 | `python -c "import json;print(len(json.load(open('features/authority/candidate/legacy_alias_mapping.json'))['aliases']))"` |
| Bundle composite | `133250b8…` | `cat features/authority/candidate/manifest.json` |

`scripts/activate_feature_pipeline_v2.py` asserts these counts before flipping the pointer,
so a mismatch here means the bundle changed and this table was not updated.

---

## Execution closure membership

The closure is **resolved, never enumerated by hand**:

```bash
python scripts/resolve_execution_manifest.py --study studies/<id>
```

Sampled from `studies/clean_maturity_flip_model_rolling_productivity` on 2026-08-25:

| Fact | Value |
|---|---|
| Files in closure | 109 |
| Markdown in closure | `study:SPEC.md` only |
| Root docs in closure (`AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `docs/*`) | none |

**Consequences worth knowing:**

- Editing repository documentation does **not** stale a study seal.
- `research_workflow/__init__.py` **is** in the closure. A cosmetic `__all__` edit stales a
  sealed study. This has actually happened.
- `GOVERNANCE_AUTHORITY_DATA_FILES` in `scripts/resolve_execution_manifest.py` pulls
  `features/feature_lifecycle_baseline.json` and `features/feature_lifecycle_promotions.json`
  into the closure. The second file is **absent**, which is a legitimate deny-state: a missing
  promotions file grants nothing.

---

## Hashing convention

`canonical_file_sha256()` in `scripts/resolve_execution_manifest.py` normalizes CRLF→LF for
`.py .json .yaml .yml .md .txt .toml .cfg .ini` before hashing (finding **W7**), so a seal
binds content rather than checkout policy. Everything else is hashed byte-exact.

This repository is checked out with `core.autocrlf=true` and carries no `.gitattributes`, so
**raw-bytes and normalized hashes of the same file differ on Windows**:

| `scripts/validate_smoke.py` | Hash |
|---|---|
| raw bytes | `56f8409a…` |
| normalized (what the gates use) | `27963595…` |

**Known defect:** `scripts/tests/test_round2_invariants.py:317` hashes with `read_bytes()`
instead of `canonical_file_sha256`, so four smoke-acceptance tests fail on any Windows
checkout with `SMOKE_VALIDATOR_STALE`. `stability_source_snapshot.json` (root, orphaned — no
code reads it) also holds raw-bytes hashes.

---

## Telemetry cost measurement

Measured 2026-08-24 on a 213,431-event smoke day, generic collector, full surface:

| Configuration | Replay wall time |
|---|---|
| `tracemalloc` off (default) | 5.73 s |
| `tracemalloc` on | 35.24 s |

≈6× — which is why it is opt-in (`NT_TELEMETRY_TRACEMALLOC=1`). Re-measure with
`scripts/benchmark_historical_same_harness.py` rather than quoting these numbers.

---

## Study-specific event ordering

Per-event callback ordering is a property of a **study family**, not of the infrastructure.
It belongs in that study's `SPEC.md` and audit passes.

For the regime-flip family the verified ordering is: completed 1s state update → checkpoint
snapshot → candidate registration → horizon handling → coincident completed-timeframe regime
update. Authority: `studies/clean_maturity_flip_model_rolling_productivity/` SPEC and audit
passes, not this file.

The **generic** guarantees (1s dispatched before its parent 1m, `ts_init` = close, derived
timeframes aggregated from completed lower-timeframe bars) are rules and live in
`docs/RESEARCH_WORKFLOW.md` §17.

---

## Known defects (framework backlog)

**RESOLVED 2026-08-28/29 — compiled `ordered_barrier` / `composite` targets are now
executed.** `research_workflow/target_runtime.py` (`OrderedBarrierTargetRuntime`,
`CompositeTargetRuntime`), `research_workflow/target_expression.py`,
`research_workflow/target_replay_oracle.py` and `research_workflow/generic_collector.py`
now resolve every compiled `primitive` from the contract:
* a single `ordered_barrier` condition runs the ±ATR barrier race off the 1s tape with the
  entry reference resolved from `next_bar_open` and the barrier ATR frozen at T (fixed
  first, proven by `studies/workflow_canary_ordered_barrier_v1`);
* a `composite` target (≥ 2 conditions) runs the **full** compiled Boolean expression —
  every child conjoined/disjoined per `condition_logic`, monotone `worst_status` censoring,
  no Boolean short-circuit (`docs/RESEARCH_WORKFLOW.md` §20.1).

Historically `generic_collector.py` resolved every candidate through a legacy 1m-regime-flip
path regardless of the compiled contract, and a `composite` `AND(flip, ordered_barrier)`
compiled to `primitive: "ordered_barrier"` with the `flip` child silently dropped — and the
replay oracle shared the omission so parity falsely passed (51.7% binary-label disagreement
found in `studies/deep_pullback_5s_reacceleration_model/artifacts/target_replay_diagnostic.json`,
2026-08-28). `studies/deep_pullback_5s_reacceleration_model` closed diagnostic-negative under
the correct label and is not reopened. `studies/workflow_canary_ordered_barrier_v1` (a
composite `AND` canary) was re-sealed, re-collected, re-fit, re-frozen and re-closed under
the corrected semantics; its pre-fix `target_replay_parity.json` is a HISTORICAL_FALSE_PASS.

**`GenericRollingProductivityProvider` (`Rolling5mProductivityTracker`) requires an exact
contiguous window of printed 1s bars** (301/301 for `window=300s`). NQ 1s bars print only on
traded seconds, so `rolling_300s_*` (and any frozen external score consuming them) is
~73–79% null on this instrument. This is `LINEAGE_MATCH_EXPECTED`, not a defect: the parent
`clean_maturity_flip_model_rolling_productivity` TRAIN surface is itself 72.7% null on these
features and Model-C was fit expecting it (LightGBM native NaN, no complete-case filter).
Recorded here only so a future study does not mistake the null rate for a wiring bug
(`studies/deep_pullback_5s_reacceleration_model/artifacts/rolling_300s_parent_parity_audit.json`).

**Execution-closure hole (found 2026-09-06 by the replay import trace; a governance finding, not a
performance note).** Package `__init__.py` modules that Python executes on the replay path
(`backtests/nt_runtime/__init__.py`, `backtests/nt_runtime/modes/__init__.py`, `features/__init__.py`,
`research/__init__.py`, `research/analysis/__init__.py`, `research/schemas/__init__.py`,
`research_workflow/forward_outcomes/__init__.py`, `research_workflow/host/__init__.py`, `utils/__init__.py`)
were in neither the collection closure nor the 90-file frozen manifest (`main` be66e8de), because the static import walk
resolved `a.b.c` to `a/b/c.py` only. `STALE_FREEZE` could therefore never fire on a change to them.
Retrospective (`git log` of those nine files against every sealed study's seal-to-closure window, main
2026-09-06): **every closed V2 study is retrospectively sound**: `v2_shape_a_flip_180s`,
`v2_shape_b_deep_pullback_5s`, `v2_shape_c_barrier_race_fade`, `first_p90_warning_horizon_march2024`,
`clean_maturity_flip_model_180s_horizon`, `deep_pullback_5s_reacceleration_model`,
`workflow_canary_ordered_barrier_v1` have zero such commits inside their seal windows. **Ten still-open
sealed studies have such commits inside their open-ended windows**:
`Codex_clean_maturity_flip_rolling_5m_productivity`, `Gemini_clean_maturity_flip_rolling_5m_productivity`,
`clean_maturity_flip_model_rolling_productivity`, `clean_tradable_reversal`, `es_wick_imbalance_acceptance_v2`,
`es_wick_imbalance_exploratory`, `regime_transition_target_before_stop_v1`, `test_level_break_collector`,
`test_minimal_checkpoint_collector`, `ym_prev5_range_position` (commits 97b97dba, e020bc94, dce66d49,
fb58531b, b939b471, 019221e0, cc23a48c, cd407353). Their results were produced under a manifest that
would have flagged stale had it been complete. Recorded here; not recompiled or resealed. Fixed in
`research_workflow/grammar/compiler.py::transitive_closure_files` (every ancestor package init is closed
over). The governance stage sets stay declared lists (red-team invariant: a perturbation moves its own stage
and the composite, never an unrelated stage); the five modules the collection walk used to reach only
through the removed `policy -> lifecycle_v2` import are declared on the `oos` list where `experiment.py`
lazily imports them. Closure sizes, each labelled by the set it counts (they are different sets and are
expected to differ), measured on the 13-instance `es_180s_model_c_portability` plan:

| set | what it is | files | at commit |
|---|---|---:|---|
| frozen execution manifest | union of every stage closure; what the seal covers | 90 | `main` be66e8de (before this chore) |
| frozen execution manifest | same, after the package-`__init__` hole fix | 116 | 08ba4123 (S1, chore/collection_latency) |
| frozen execution manifest | same, after the layering fixes and the `oos` list | **115** (strict superset of the 90) | 943442d4 (Reading 2) |
| collection stage | transitive import closure from the host + compiler seeds | 85 → 111 → **101** | be66e8de → 08ba4123 → 943442d4 |
| replay stage | the partition-reuse key: host + bound provider/tracker seeds, compiler and analysis modules removed | **95** | 943442d4 |

Read cold: "manifest 115, replay 95" is the current state; a manifest number and a replay number are never
supposed to match, because the replay stage is a subset of the collection stage, which is a subset of the
manifest.

**Replay import-trace policy.** Every smoke and every partition run records the repository modules first
imported during its replay (`artifacts/replay_closure_trace.json`, cumulative across runs). A module outside
the plan's replay stage halts the run (`REPLAY_CLOSURE_ESCAPE`); the key is never widened by a trace.

**NautilusTrader pin: 1.230.0.** The host uses the low-level `BacktestEngine` with two `add_data()` batches
per partition (1s then 1m, `utils/causal_registration.py`), a whole year resident; it does not use
`BacktestNode` / `DataBackendSession` chunked streaming, so the `DataBackendSession` memory-leak fix (#3889)
does not apply. That note becomes load-bearing the day the host moves to `BacktestNode` for chunking.
The replay throughput decay across a year (6.4x, 2026-09-06) was a host defect, not NT:
`research_workflow/provider_host.py` `ContextAdapter._midpoints` was an unbounded list of every completed 1m
midpoint, copied whole on every candidate snapshot although `ema_slope` reads only `[-1]` and `[-6]`.
**FIXED 2026-09-06 (chore/collection_latency 3e441fcc): `deque(maxlen=64)`.** Parity: the sealed
`supv1_shape_a_flip_180s_r2` TRAIN 2021 partition replays byte-identical; same run 408 s engine time vs
1,437 s before, first/final-decile 30.4k / 30.3k bars/s (decay ratio 1.00). A single year is ~7 minutes.
Report: `artifacts/platform_v2/collection_latency/MIDPOINT_FIX_REPORT.md`.

**`scripts/benchmark_historical_same_harness.py` cannot run on the current tree** (found by the
2026-09-06 collection-latency measurement, `artifacts/platform_v2/collection_latency/W0_REPORT.md`).
It hard-codes the historical study `clean_maturity_flip_model_rolling_productivity`, whose compiled
artifact is stale (`STALE_COMPILED_STUDY`), and recompiling a historical study is prohibited; it also
drives the V1 `compiled_study_loader` / `MinimalCheckpointCollector` path rather than the V2 host, so
the telemetry figures above are not reproducible through it. Same-harness V2 throughput is measured
instead through `research_workflow.host_runner.run_plan_on_catalog` on a closed study's compiled plan
(read-only): 23.4 k bars/s on one month, 10.5 k bars/s on a full year, 13-instance surface, 2026-09-06 --
before the midpoint-buffer fix; 30.5 k bars/s flat across the full year after it (same harness, same plan).

`scripts/tests/test_round2_invariants.py:317` hashes with `read_bytes()` instead of
`canonical_file_sha256` — see the Hashing convention section above.

---

## Audit history that justifies current limits

| Fact | Source |
|---|---|
| ~60% of blocking audit findings were completeness, not look-ahead (`D1` 22, `C4` 22, `C3` 12, `D4` 9) across ~100 reports | why the audit gate is split |
| One study ran **18 audit passes** and produced a 1,240-line append-only report | `studies/codex_5.6_short_rth_enriched_volume_level_retrain/` |
| The Codex auditor silently missed 14 checklist rules including C4 and D4 | why `scripts/sync_agents.py` exists |
| A cleanup followed a Windows junction out of a disposable worktree and destroyed 179 GB | why `scripts/safe_cleanup.py` fails closed |

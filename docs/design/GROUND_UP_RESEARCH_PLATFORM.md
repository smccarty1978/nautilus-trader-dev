# Ground-Up Research Platform — Architecture for Red-Team Review (revision 8)

**Status:** PROPOSAL, revision 8 after red-team reviews 1–8. **Phase 0 complete; Phase 1 synthetic
portion approved (review 8); the full platform contract is not yet approved.**

**Revision 8 change log (review 8 → resolution → section):**

| Item | Resolution | Section |
|---|---|---|
| 1 Dependency parameter change leaves the consumer's key unchanged | `gid` hashes the *resolved dependency gids* (transitive), not dependency code fingerprints; same for trigger dependencies in `spine_key` | §4.2, §4.5 |
| 2 Whole-module fingerprints invalidate unrelated features | Symbol-level fingerprint over the plugin class and the symbols it transitively references; whole-module fallback only where static resolution fails, and recorded as `fp_scope: module` | §4.5 |
| Phase 1: reader is not a manifest validator | Catalog manifest validation against the expected build plan (inventory, counts, safe relative paths, hashes); `read_group`'s role limited to group parts | §4.1 |
**Phase 0 outcome (2026-09-16, revision 2 after review 7):** `../ntr` at 36 tests passing; report
`../ntr/PHASE0_REPORT.md` with 21 demonstrated behaviours (D18 ancestor-junction refusal, D19
delivery permutations + negative control, D20 interrupted recovery chain), 4 failed assumptions
(F1–F4, absorbed in §3.4, §4.6, §6.7) and 9 unresolved cases (U8 registration-time I/O and U9
fingerprint tests are Phase 2 obligations). Phase 0 authorises Phase 1 only.
**Phase 1 outcome (2026-09-17):** synthetic portion complete (`../ntr/PHASE1_REPORT.md` rev 3), one
real TRAIN month built, independently verified and coverage-declared (`../ntr/PILOT_202101_REPORT.md`
rev 2, catalog `NQ_1S_P1_202101_r2`), memory task complete (`../ntr/MEMORY_TASK_REPORT.md`).
**Phase 2 prerequisites closed (2026-09-17):** registration-time boundary (U8), symbol-level
fingerprints (U9) and open-handle publication (U1) -- `../ntr/PHASE2_PREREQ_REPORT.md`.
**Phase 2 record layer, first slice (2026-09-17):** all §11 row 2 acceptance cases pass; real January
spine + two groups through the authorised ReadPlan path -- `../ntr/PHASE2_REPORT.md` (F22–F26), 131
tests. **Remainder complete (2026-09-17, rev 2):** batch-streamed engine input (F24 closed: 556 MB vs
1.47 GB on a day-streamed catalog), parallel shards via study modules, plan-authorised reference-input
loading, feature checkpoints on sequential attach, study-source validation, the fresh-interpreter
audit-armed 6.1 CLI, and layered receipts -- 139 tests.
**Phase 2 red team (2026-09-17):** nine gate-layer defects found by ten probes (`../ntr/PHASE2_REDTEAM.md`),
all remediated with negative controls (`../ntr/PHASE2_REDTEAM_RESPONSE.md`, 153 tests). Contract
amendments below: 6.4 compares the deliverable itself (§6.0); warm-up is denominated per plugin
timeframe and unbounded closures are refused in shards (§4.3); the study path validates plugin sources
and executes under the armed audit (§3.4); checkpoints are bound to plan, mode and plugin set (§4.3);
6.1/6.6 have no vacuous verdicts (§6.0).
**Phase 3 (2026-09-17):** labels implemented (`../ntr/PHASE3_REPORT.md`, 164 tests). Three NT 1.230
facts were probed and the 6.7 conventions bound to them (table below): a stop-market touched inside a
bar fills at the STOP price, not the extreme; a limit fills at its LIMIT price even when the bar opens
beyond it (a stop gapped through fills at the open); NT processes O, H, L, C for every bar, so a
same-bar hit always fills the PT first; the bar at `ts_open + horizon` is processed BEFORE a clock
alert at that time, so it is inside the window.
**Phase 4 (2026-09-17):** `fit` implemented (`../ntr/PHASE4_REPORT.md`, 174 tests): typed estimand and
selection, grouped chronological split (purge + embargo, `group` = `anchor_id` or `day`), receipts as
fit prerequisites, C / E / E∩O populations with coverage, bundle with `contract.json` +
`manifest.json` + card, 6.8 receipt at the fit layer, contract rebuild proven label-free and
unselected-feature-free. Model families v1: LightGBM and logistic.
**Phase 5 (2026-09-17):** backtest layer implemented (`../ntr/PHASE5_REPORT.md`, 182 tests):
`ModelStrategy` with 6.5 at start (the contract now also binds the trigger gids -- the population the
model was fitted on -- so a changed trigger is a stale contract, not a 6.9 surprise), `Policy` plugins
with a policy gid, `Scenario`/`xid`, `bt_key` (a holdout retry binds its exposure seq), 6.9 against the
recorded spine + selected-arm groups, `chronology.toml` with `chron_id` bound to the ledger lines, and
the three-event ledger under the OS byte-range lock. Instrument mapping is `single_contract_v1` until
multi-contract data arrives.
**Phase 6 (2026-09-17):** operator layer implemented (`../ntr/PHASE6_REPORT.md`, 190 tests): the CLI
verbs of §8, `status` with the §6.0 prerequisites table and one `next:` verb, semantic reviews bound
to fingerprints (§7 decides who needs one: labels, unbounded features, input consumers) gating `fit`
and `commit`, `report.md` with a preserved interpretation section, `commit` writing the COMMIT line
only over PASS receipts (6.7 when trade-shaped), analysis helpers (`UNEQUAL_WINDOWS`,
`SIGNAL_TOO_RARE`), `explore` over TRAIN/tune frames only, and the card audit (≤ 30 lines, one
`next:` verb, no questions). Found by the real walk-through and fixed: plugin sources may import
`__future__`; study modules may import `ntr.core.estimand`; the study loader binds `studies` to the
study's own root. **6.7 amendment:** NT 1.230 delays a touched limit fill when another open bracket on
the same instrument fills on the same tick (25 of 5,422 rows at a 60 s cadence, thin hours); a single
bracket fills at the touch. 6.7 therefore checks rows as isolated trades (non-overlapping lanes, one
engine per lane); overlapping-position matching is execution, reported by the backtest, never a label
gate. Open decision: `ntr/checks` is inside `rfp`, so a check fix re-keys every spine; receipts already
bind `checks_version`.
**Phase 7 (2026-09-17):** live layer implemented without a venue (`../ntr/PHASE7_REPORT.md`, 195 tests):
capture format of §3.6, one shared arrival-normalisation rule (a bar at or before the last delivered
bar is dropped and counted; arrival order is preserved through NT's per-batch sort), explicit
checkpoints carrying `last_ts_init`, restart = checkpoint + replay of every later bar verified against
the source (unfillable gap → WARMING statuses → ineligible; `warmup_bars = None` → cold start refused),
`live-equivalence` with the seven classes. Amendment found on real data: a restored session's capture
must be replayed from the SAME checkpoint, never cold (2,676 spurious STATE_RESTORE otherwise); the
capture header names the checkpoint. Execution residual unmeasured until a venue capture exists.
**Completed-repo red team (2026-09-17):** ten findings (`../ntr/REDTEAM_COMPLETED_REPO.md`), all
remediated (`../ntr/REDTEAM_COMPLETED_REPO_RESPONSE.md`). Contract amendments: §5.1 the split is
**walk-forward** by default (block k trains only on blocks before it; block 0 is never a test fold);
`purged_kfold` remains as a named option whose fit card says so, and `fit.py` asserts that no
deployment-scored row is a training row. §6.8 a trade-shaped label's 6.7 receipt is read at fit and
anything but PASS makes the verdict INCONCLUSIVE (the receipt state is in `eval_key`); a comparison
population below `Selection.min_coverage` of the deployment population is INCONCLUSIVE; the censored
fraction is reported by UTC hour; the selected arm's aggregate is disclosed as its selection statistic.
§3.6 classes: `STATE_RESTORE` is `REPLAY_DIVERGENCE` (replay from the same state reproduces the live
snapshots); `CATALOG_DIVERGENCE` compares the catalog leg; AGGREGATION is symmetric; a separate
**checkpoint-fidelity** check compares a restored session with an uninterrupted run past warm-up;
nothing compared is INCONCLUSIVE; a catalog-replay capture can only be `EQUIVALENT_REPLAY`; the
checkpoint a capture names is resolved under the runs root and hash-bound. §4.5 `rfp` covers
`ntr/{core,record,data}`; `ntr/checks` is bound through `checks_version` in receipts and `eval_key`.
**Phase 8 (2026-09-17):** a Sonnet-class operator re-ran the closed January question end to end
(`../ntr/PHASE8_REPORT.md`): 7 verbs, 12 tool calls, ~2 min wall, answer reproduced exactly, one
guess (the plugin to review, read off the status card), no card contradicted. Every phase of §11 is
now implemented and committed (195 tests). Open items: `ntr/checks` inside `rfp` (owner decision);
venue adapter and execution residual; multi-contract mapping and latency; CME holiday calendar;
censored outcomes (v1 by design).

**Revision 7 change log:**

| Item | Resolution | Section |
|---|---|---|
| Owner: iterate without running the full pipeline | Incremental research is the normal workflow; the verb sequence is one available path. Layered artifact keys with receipts bound to the narrowest layer they depend on; `ntr explore` is independent of fit/commit; evidence boundary stated | §8.1, §6.0 |
| Review 7 item 1 (Phase 0) | Containment = lexical + resolved + ancestor-reparse inspection, in both deletion and lock recovery | §4.6 |
| Phase 0 F4 | `os.replace` onto a file a reader has open fails on Windows; bounded retry on marker and info writes | §4.6 |
| Phase 0 U8 | Registration validates plugin source statically before executing it; import and construction run under a registration-scoped audit; constructor-time leakage is a negative control | §3.4 |

**Date:** 2026-09-16
**Scope:** a new repository, starting from (a) the Databento-derived bar data and (b) NautilusTrader
1.230. Nothing from the current `research_workflow/` platform is carried over as code.

**Revision 6 change log (review 5 item → resolution → section):**

| Review 5 item | Resolution | Section |
|---|---|---|
| 1 Abandoned reclaim still racy | Ownership is an OS-held advisory lock released on process death; acquisition is the atomic claim; the reclaim file is removed; combined crash-and-concurrency test | §4.6, §11 |
| 2 Scenario separation contradicted | Execution settings removed from the inference contract; label fidelity only under the label's reference scenario; sensitivity runs measure divergence and carry no fidelity gate; production invariance always | §5.3, §4.5, §6.0 |
| 3 `(model_id, xid)` incomplete | `bt_key` binds contract, `xid`, policy gid, effective ReadPlan, instrument mapping, `chron_id`, commitment, `rfp`; `(model_id, xid)` is a grouping only | §4.5 |
| Coverage per metric | Coverage is of the metric's own population relative to E: `|E∩O|/|E|` or `|C|/|E|` | §3.2 |

**Revision 5 change log (review 4 item → resolution → section):**

| Review 4 item | Resolution | Section |
|---|---|---|
| 1 `union_readiness` does not equalise populations | Three sets E, E∩O, C; equality claim removed; coverage and disposition counts beside every metric; censored outcomes declared unmodelled | §3.2 |
| 2 Identity blocks frozen-model sensitivity runs | `rfp` binds delivery only; execution scenario `xid` separate; backtests keyed `(model_id, xid)`; 6.9 production invariance; permitted `xid`s predeclared in the commitment; execution events added to live capture | §4.5, §3.6, §6.0 |
| 3 Cached artifacts need current authorisation | ReadPlan enumerates derived artifacts with their effective plan hash and `chron_id`; reauthorisation on every cache hit; effective range in `spine_key` | §4.0, §4.2 |
| 6.7 has no producer | `ntr check --fidelity` | §6.0, §8 |
| Abandoned reclaim lock; fallback publish untested | (reclaim state machine superseded in revision 6 by the OS-held lock) marker written via `os.replace`; concurrent-reader tests | §4.6, §11 |

**Revision 4 change log (review 3 item → resolution → section):**

| Review 3 item | Resolution | Section |
|---|---|---|
| 1 `next_open` mapping contradicts NT execution | Verified in `backtest/engine.pyx` 1.230: `process_bar` → `data_engine.process` → `_process_and_settle_venues(ts_init)`; a market order submitted in `on_bar(T)` settles at `T` against the book after bar `T`'s ticks, i.e. at the snapshot bar's close. `next_open` is removed. The only v1 entry convention is `snapshot_close`, fill timestamp `T`, fill price close(T) under the fidelity fill model. Fixture moved to Phase 0. | §6.7, §11 |
| 2 Deployment schema includes an outcome-dependent mask | Training population identity (historical mask, provenance only) separated from the inference contract (selected arm's gids + causal readiness predicate). Deployment population ⊇ comparison population; explicit `eligibility` policy; both subpopulation metrics on the card. | §3.2, §5.3 |
| 3 Holdout authorisation not specified for every physical read | `ReadPlan` computed and authorised before engine construction: partitions for range ∪ warm-up ∪ suffix ∪ origin replay, reference-input partitions, checkpoint provenance. Crossing into holdout is refused or truncated at the role boundary by declared disposition, never silent. Reference inputs are year-partitioned at registration and loaded with byte-level partition filtering. | §4.0, §3.4, §5.2 |
| 4 Dead-lock takeover races | (superseded in revision 6) Ownership is an OS-held advisory lock released on process death; acquisition is the atomic claim; no reclaim file. | §4.6 |
| Semantic review needs a next action | `ntr review request` / `ntr review ingest`; approval bound to exact fingerprints; stale approval is not an approval. | §8 |
| Checks need stage prerequisites | Prerequisite table by verb; "as applicable" is computed. | §6.0 |
| Phase 0 scope | Positive controls (permitted plugin, permitted `numba`) beside rejections; fill-timing fixture; Windows directory-rename atomicity and reclaim-race experiments explicitly in Phase 0. | §11 |

---

## 0. The one-paragraph version

There is **one engine**. Every feature, trigger and label is computed inside a NautilusTrader
`Actor` that receives data only through `on_bar` and resolved input values only through the
actor. Research is that actor with a recording sink; a backtest is that actor with a scoring
`Strategy`; live is the same objects with a live data client and an explicit equivalence test.
Every physical read is planned and authorised before an engine is built. Look-ahead is
*constrained* by a plugin trust boundary, *verified* by a stack-aware I/O audit plus a
multi-cutoff truncation test that regenerates the population, and *reviewed* semantically only
when a plugin introduces a new input source or temporal behaviour. Every stored artifact is
addressed by a digest of everything that produced it, including the platform's own execution
code. The holdout is touched only inside a three-event transaction. The operator, human or
model, runs a fixed verb sequence and reads cards.

---

## 1. Requirements and how each is met

| Requirement | Mechanism | Section |
|---|---|---|
| Fast to iterate | Spine recorded once; groups attach and are content-addressed | §4 |
| Fidelity research → training → backtest → live | One `FeatureActor`; bundle carries the inference contract; strategy refuses mismatch; live equivalence test | §3, §5.3, §3.6 |
| Flexible for novelty | Five plugin protocols; Python study file | §3.2, §7 |
| Minimise tokens; drivable by Opus/Sonnet | Fixed verbs, `next:` on every card, no governance decisions left to the operator | §8 |
| Plug into NT; no look-ahead | Plugins run only inside NT actors; `ts_init` only; coarse bars aggregated by NT from 1s and buffered to the next epoch; entry convention is NT's demonstrated one | §3.3, §3.4, §6.7 |
| Start from data + NT only | Library budget ≤ 6k lines; phased plan with adversarial and positive acceptance | §9, §11 |

---

## 2. What is deliberately not built

| Not built | Replaced by | Why |
|---|---|---|
| Declarative study grammar + compiler + capability registry | Python `Study` dataclass composing plugins | Every novel idea became a platform packet |
| Offline collector / replay host | NT `BacktestEngine` itself | The host re-implemented NT delivery and diverged (G7) |
| Full-pipeline parity scripts | One engine + narrow live equivalence test | Two engines are gone; live input divergence is measured |
| Causal auditor agent + checklist | Trust boundary + I/O audit + truncation + semantic-review verbs | These compute; review is retained narrowly and has a transition |
| Repo-closure hashing, seal/freeze/closure | `eval_key` with plugin fingerprints and `rfp` | Provenance answers "what produced this" |
| Supervisor, worker roles, leases | One worktree per study + PID lock | 301 turns / $27 per rehearsal study |
| 2.5 h broad suite, tiered gates | < 3 min synthetic suite with negative and positive controls + 15 min nightly on real months | Gate cost |
| External 1m catalog bars as feature inputs | NT internal aggregation from 1s | Catalog 1m defects; same aggregator in backtest and live |

---

## 3. Core architecture

### 3.1 One engine, three attachments

```
 ReadPlan (authorised) ──► ParquetDataCatalog 1s EXTERNAL ──► BacktestEngine / TradingNode
                                      │ BarAggregator: INTERNAL 1m/5m/… @1s
                                      ▼ on_bar
                              ┌──────────────────┐
                              │ FeatureActor     │ triggers → Epoch → Snapshot(snapshot_id, ready, …)
                              │ (trust boundary) │ inputs resolved to values here, never paths
                              └───────┬──────────┘
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             LabelActor         RecorderSink      ModelStrategy (backtest/live)
             pending by         spine + groups    inference contract check on start
             snapshot_id        atomic publish    score → Policy → NT orders
```

* **Snapshot identity.** `snapshot_id = h(instrument, ts_init, trigger_instance_name, anchor_id,
  epoch_index)`. Trigger instance names are unique per study; duplicates are refused.
* **Snapshot readiness.** Each snapshot carries `population_ready` (trigger warm-up complete,
  §4.3) and per-feature `<feature>__status`. Both are causal and computed at snapshot time.
* **`FeatureActor`** calls `on_bar` in dependency order, releases buffered coarse bars at the next
  1s epoch, raises epochs only on the 1s stream, publishes immutable snapshots.
* **`LabelActor`** opens a pending label per snapshot; entry at the snapshot bar's close (§6.7);
  observes bars with `bar.ts_init > snapshot.ts_init` strictly.
* **`RecorderSink`** buffers and publishes atomically (§4.6).
* **`ModelStrategy`** validates the inference contract (§5.3), scores, delegates to a `Policy`.

### 3.2 Plugin protocols, the study file, and the two populations

```python
class Feature(Protocol):
    name: str; params: JsonDict; subscribes: tuple[BarSpec, ...]
    depends_on: tuple[str, ...] = (); inputs: tuple[str, ...] = (); initial_state: JsonDict = {}
    def on_bar(self, bar: Bar, ctx: PluginContext) -> None: ...     # ctx.inputs[name] -> value visible at bar.ts_init
    def fields(self) -> dict[str, float | int | None]: ...
    def warmup_bars(self) -> int | None: ...
    def state(self) -> JsonDict: ...
    def restore(self, state: JsonDict) -> None: ...

class Trigger(Protocol):   # unique `name`; warmup_bars(); state()/restore(); on_bar(bar, ctx) -> Epoch | None
class Label(Protocol):     # open(snapshot) -> Pending; on_bar(pending, bar) -> Resolved | None; on_boundary(pending, kind) -> Resolved
class Policy(Protocol):    # on_snapshot(snap, score, strategy); on_bar(bar, strategy)
class Analysis(Protocol):  # run(frame: pl.LazyFrame, ctx) -> list[Table]
```

```python
STUDY = Study(
    id="nq_flip_180s", instrument="NQ.XCME", data="NQ_1S_V2_GLOBEX", timeframes=("1s", "1m"),
    origin="2020-01-02",
    triggers=[Cadence(name="cp5s", every="5s", session="RTH", within=RegimeAge(min="120s", max="1800s"))],
    features=[RegimeDualEMA(tf="1m"), Excursion(tf="1s"), ArrivalVelocity(lookback=20)],
    label=EventWithin(event="regime_1m.flipped", horizon="180s", boundary="censor"),   # entry is snapshot_close (§6.7)
    role_boundary="truncate",                                        # label window crossing a role boundary (§4.0)
    estimand=Estimand(
        hypothesis="Arrival velocity adds information about an imminent 1m regime flip beyond regime geometry.",
        arms=[Arm("base", features=["RegimeDualEMA", "Excursion"], baseline=True),
              Arm("plus_av", features=["RegimeDualEMA", "Excursion", "ArrivalVelocity"])],
        selection=Selection(metric="pr_auc", comparison="paired_delta_vs_baseline", threshold=0.02,
                            fold_aggregation="min", direction="greater",
                            comparison_mask=RowMask(label_status=("RESOLVED",),
                                                    feature_status="OK_for_union_of_arm_features",
                                                    population_ready=True),
                            censoring="exclude_and_report_count"),
        eligibility="selected_arm_readiness",                        # deployment population policy (§5.3)
    ),
    model=LightGBM(max_depth=3, num_leaves=7, learning_rate=0.03, n_estimators=200),
    split=GroupedChronological(group="anchor_id", embargo="1d", purge="label_horizon"),
)
```

Three observation sets are distinguished throughout, and no two are claimed equal:

| Set | Defined by | Knowable at snapshot time | Used for |
|---|---|---|---|
| **E — deployment-eligible** | `eligibility`: a causal predicate on `population_ready` and the *selected* arm's feature statuses | Yes | Trading in backtest and live; the inference contract validates it |
| **E∩O — eligible with an observed outcome** | E, and the label later resolved (`RESOLVED`) | No (outcome is future) | "Deployment-eligible, outcome-observed performance" |
| **C — paired comparison** | `comparison_mask`: `RESOLVED` label and readiness of the *union* of arm features | No | Fitting and paired arm comparison; hash in `eval_key` and the bundle manifest |

`eligibility="selected_arm_readiness"` (default) makes E ⊇ the readiness part of C.
`eligibility="union_readiness"` makes the *causal* part of E equal to the causal part of C by
computing every compared feature in deployment; it does not and cannot make E equal to C,
because C also requires an outcome that E cannot know. A feature-ready snapshot shortly before
the session close is in E, is traded, and is later `CENSORED`: it is excluded from every target
metric and counted in the coverage denominator. Every fit and backtest card therefore reports,
beside each metric, the **coverage of that metric's own population relative to E**: `|E∩O| / |E|`
for a deployment-eligible, outcome-observed metric and `|C| / |E|` for a comparison metric (C ⊆ E
under the default eligibility), together with the label-disposition counts over E. A comparison
metric can never appear beside a coverage figure computed for a different population.
Censored outcomes are not modelled in v1; the card says so.

### 3.3 Timeframes and visibility

1. Visibility clock is `ts_init` only; `ts_event` is unreadable in plugin packages.
2. Coarser bars are aggregated internally by NT from the canonical 1s stream
   (`…-1-MINUTE-LAST-INTERNAL@1-SECOND-EXTERNAL`, `time_bars_timestamp_on_close=True`).
3. Epochs are raised only on the 1s stream. A coarse bar closing at `T` is buffered by the actor
   and released to plugin state at the next 1s epoch after `T`; the fixture asserts this.
4. Sparse 1s is never forward-filled; `time_bars_build_with_no_updates` is pinned per study.
5. Session boundaries come from the calendar module; session close and role boundary are the
   only places labels are truncated or censored.

### 3.4 The plugin trust boundary

Controls for **trusted plugins written in this repository**, designed to make accidental
leakage fail loudly. Not a sandbox; process isolation is deferred and not claimed.

Bounded claim: **a plugin's `on_bar` can compute only from (a) the bar it is handed, (b)
plugins it declares in `depends_on`, (c) resolved values of declared `ReferenceInput`s handed
to it by the actor, and (d) its params and declared `initial_state`.**

* **Inputs are values, never paths.** `ReferenceInput(name, path, sha256, schema, provenance)`
  is registered in `inputs/registry.py`. Registration **requires the file to be partitioned by
  `available_from` year** (`<name>/year=YYYY/*.parquet`) and records per-partition hashes.
  `ntr.core.inputs` loads only the partitions the `ReadPlan` (§4.0) authorises, by partition
  path, so protected-period bytes are never materialised in a non-holdout process. The actor
  hands each plugin a `PluginContext` whose `inputs[name]` returns the latest payload with
  `available_from <= bar.ts_init`, or `None`. The input's partition hashes, schema and the
  `available_from` column are part of the plugin fingerprint.
* **Static boundary.** Plugin packages may import only `ntr.core`, `numpy`, `numba` and a
  standard-library allowlist (`math`, `collections`, `dataclasses`, `typing`, `enum`,
  `itertools`, `functools`, `statistics`). No `open`, `eval`, `exec`, `__import__`, `globals`,
  `getattr` on modules; no module-level statements other than imports, constants and
  definitions; no `ts_event`.
* **Stack-aware I/O audit.** Every recording, fitting and backtesting process installs
  `sys.addaudithook`. For `open`, `os.*`, `socket.*`, `subprocess.*`, `ctypes.*`, `mmap` and
  `import` events it walks the stack; **if any frame belongs to a plugin package or
  `studies/*/plugins.py`, the run fails**, regardless of path. Library-mediated I/O
  (`numpy.loadtxt`, `pandas.read_*`) is caught because the plugin frame is on the stack. Engine
  catalog reads and sink writes originate in `ntr.*` frames. `compile` and `exec` events are
  treated differently: they fail only when the **innermost** frame is a plugin frame, so
  a plugin-authored `exec` is refused. `ctypes.*` events follow the same innermost-frame rule
  (Phase 2 F20: numba/llvmlite resolve LLVM symbols through ctypes during compilation with the
  plugin frame further up the stack; a plugin calling ctypes itself is still refused).
  **Phase 0 finding F1 / Phase 2 F21:** numba's lazy JIT performed `open` events with the plugin
  frame on the stack while numba was cold; `audit.install()` now pre-initialises entry points and
  performs a dummy eager compile before arming, so the runtime hook no longer sees that I/O.
  The pinned rule is therefore **static**: plugin jit functions must carry an explicit signature,
  and registration refuses `NUMBA_LAZY_JIT` before any plugin code runs. The runtime hook is the
  net, not the rule. `numba` is configured `cache=False, fastmath=False, parallel=False` for
  plugin packages. Phase 0 proved the three rejections, the ordinary-plugin permission, the
  eager-numba permission, and the lazy-numba refusal.
* **Registration-time boundary (Phase 0 U8).** The runtime hook cannot see the period before it
  is armed, and plugins are imported and constructed then. Registration therefore (1) runs the
  static boundary check on the plugin module's source **before executing it**, (2) imports and
  constructs the plugin under a *registration-scoped* audit that permits only the import
  allowlist and no I/O, and (3) keeps import-time and constructor-time leakage as negative
  controls in the suite. Eager numba compilation is the one sanctioned bootstrap activity and it
  performs no I/O once entry points are pre-initialised.
* **Semantic review.** Registering a new `ReferenceInput`, a new `subscribes` bar spec,
  `warmup_bars = None`, or a new `Label` marks the study `NEEDS_SEMANTIC_REVIEW`; the transition
  is in §8.
* **Not guaranteed.** A literal parameter chosen with knowledge of the future; a
  `ReferenceInput` registered with a false `available_from`. Both are attributable and the
  second is what the semantic review reads.

### 3.5 Same-bar and delivery-order semantics

A snapshot at `T` is built from state after all bars with `ts_init <= T` on the 1s stream and
coarse bars released per §3.3. A label observes only bars with `ts_init > T`. Simultaneous
triggers at `T` yield distinct ids. Tests: both actor registration orders; two triggers at one
`T`; a snapshot bar whose own high/low would wrongly resolve the label.

### 3.6 Live

* **Capture.** Every arriving bar `(ts_init, ts_event, arrival_wall_ns, source)`; every emitted
  snapshot with checkpoint id and config hash; every timer firing `(scheduled_ns, fired_wall_ns)`;
  and **every execution event**: order submission `(snapshot_id, submit_wall_ns, ts_init at
  submit)`, venue acknowledgement, and fill `(fill_wall_ns, price, qty)`. The execution
  residual between simulated close(T) entry and achieved live entry is
  `(fill_wall_ns − T, fill_price − close(T))` per trade; until a capture exists this residual is
  unmeasured and the document claims nothing about live attainability of close(T).
* **Replay-equivalence.** `ntr live-equivalence --capture <day>` replays the captured arrival
  sequence through the actor and compares snapshots and aggregated bars to (a) the live emitted
  snapshots and (b) a catalog backtest over the same window; classes `LATE_BAR`, `MISSING_BAR`,
  `REVISED_BAR`, `TIMESTAMP_NORMALISATION`, `AGGREGATION`, `STATE_RESTORE`, `TIMER_DRIFT`.
* **Timestamp normalisation and late data.** Same normalisation function as the catalog build;
  a bar at or before the last raised epoch is dropped and counted.
* **Restart.** Restore = checkpoint + replay of every bar between the checkpoint's `ts_init` and
  now, from the capture log or `request_bars`; no bar is skipped. If the gap cannot be filled the
  actor stays `WARMING` and the policy does not trade. Any `warmup_bars = None` plugin forbids
  cold start. Snapshots emitted while `WARMING` carry that flag and fail `eligibility`.
* **Contract mapping.** Continuous series → tradable contract via the manifest's roll table.

---

## 4. Data and the record store

### 4.0 The ReadPlan (authorised before any engine is built)

Every verb that reads market or reference data first computes a `ReadPlan` and writes it to the
run manifest:

```
ReadPlan {
  catalog_partitions:   [(instrument, year, month)]   # requested range ∪ warm-up prefix ∪ label suffix ∪ origin replay
  input_partitions:     [(input_name, year)]
  checkpoints:          [(path, produced_under_readplan_hash)]
  roles_touched:        {train: [...], tune: [...], holdout: [...]}
  verb, study, commitment_id | null
}
```

Authorisation rules, applied before construction:

* A non-holdout verb whose plan touches a holdout partition **for any reason** (suffix, prefix,
  origin replay, reference input, checkpoint provenance) is refused with
  `READ_PLAN_CROSSES_HOLDOUT`, naming the cause, unless the study declares
  `role_boundary="truncate"`, in which case the plan is **trimmed to the role boundary** and the
  label actor treats the boundary exactly like a session close (`on_boundary(pending,
  ROLE_BOUNDARY)` → `TRUNCATED`, counted on the card). There is no silent authorisation to
  complete TRAIN labels.
* A warm-up prefix that would reach before `origin` is trimmed to `origin` (state starts at
  `initial_state`); a prefix that would reach into holdout is refused (a holdout year that
  precedes train is a configuration the roles file must not express; `ntr doctor` checks).
* A checkpoint whose recorded `ReadPlan` touched holdout cannot be restored by a non-holdout
  verb.
* Holdout verbs require the commitment id and the `EXPOSURE_START` line (§5.2) before the plan
  is executed.
* The engine is built from the authorised plan's partition list; the catalog loader takes
  explicit partition paths, never a date range it resolves itself.

**Derived artifacts are reads too.** The plan also enumerates every cached spine, group,
checkpoint, training frame and bundle the verb will consume, each with the **effective
`ReadPlan` hash recorded in its manifest** at production time (the partitions actually read
after any truncation) and the `chron_id` it was produced under, where
`chron_id = h(chronology.toml content, exposure-ledger lines for the instrument)`. Content
identity (hashes, `gid`, `eval_key`) says what the bytes are; it never says they may be consumed
now. **Reauthorisation on every cache hit:** the artifact's effective partitions must be ⊆ the
partitions the current `chron_id` authorises for this verb, and its exposure classification is
recomputed against the current ledger. A role change that leaves the bytes and receipts
unchanged therefore still refuses or reclassifies reuse, with no source read. Because the
effective range under `role_boundary="truncate"` depends on the roles, `spine_key` includes the
*effective* date range, not the requested one, so two chronologies that truncate differently
produce two spines rather than one ambiguous cache entry.

### 4.1 Ingest

`ntr data build` writes 1s `EXTERNAL` bars as NT-native Parquet (NT `ArrowSerializer` schema and
metadata) partitioned by month, plus `manifest.json` (per-partition sha256, row counts, first/last
`ts_init`, roll table, normalisation rule, source rules, and the **build plan**: the expected
partition inventory). Existing catalogs are adopted by re-partitioning into monthly files into a
*separate* output catalog and writing their manifest; the originals are never modified.

**Manifest validation (review 8).** A manifest is accepted only if: its partition inventory equals
the expected build plan exactly (no missing, no extra months); every path is relative, contains no
`..` or absolute component, and resolves under the catalog directory; every partition's row count,
first/last `ts_init` and sha256 match the bytes; partitions are non-overlapping and ordered; the
bar type metadata matches the manifest's declaration. An empty inventory is refused. The Phase 0
`read_group` helper validates *group parts only* and is not the catalog validator.

**Memory (Phase 1 memory task).** The builder buckets source rows by UTC day: one Arrow table and
one Parquet row group per day, freed as written, verified by a rolling value digest re-read one row
group at a time. At most two days of bars are resident. Measured on one real month of 1s NQ bars:
builder peak 1,082 MB with a month bucket, 333 MB with day buckets, values identical
(`../ntr/MEMORY_TASK_REPORT.md`). Whole-month `Bar` materialisation is not used anywhere in ingestion.

**Build refusals.** Duplicate `ts_init` within an instrument (`DUPLICATE_TIMESTAMP`), a bar whose
`ts_init` is not the declared close-time normalisation of its source stamp
(`TIMESTAMP_NORMALISATION`), an out-of-order source, and a partition that cannot be verified after
write all refuse the build and leave no manifest; a rebuild resumes by overwriting the unverified
partition. Publication of each partition and of the manifest uses the §4.6 protocol.

### 4.2 Layout and addresses

```
runs/<study>/spine/<spine_key>/                spine.parquet  ckpt_runtime/  _COMPLETE.json  manifest.json
runs/<study>/groups/<spine_key>/f_<name>_<gid12>/   part-*.parquet  ckpt_feature/  _COMPLETE.json  manifest.json
runs/<study>/groups/<spine_key>/l_<name>_<gid12>/   part-*.parquet  _COMPLETE.json  manifest.json
runs/<study>/evals/<eval_key>/                 checks/  fit/  backtest/  report.md
runs/<study>/holdout/<eval_key>/               (§5.2; separate, refused by fit/analyze)
```

* `gid = h(name, plugin fp, params, sorted gids of every plugin in depends_on, rfp)`. Because a
  dependency's gid already contains *its* params and *its* dependencies' gids, the identity is
  transitive over configured instances: changing feature A's period from 20 to 60 changes A's gid
  and therefore B's (which reads A), while an unrelated C keeps its gid and its receipts (review 8
  item 1; Phase 2 acceptance case). Directory carries 12 hex characters, manifest the full digest.
* `spine_key = h(data manifest, trigger gids (each including the gids of features the trigger
  depends on), origin, effective date range, role_boundary, timeframe + aggregation config,
  calendar version, rfp)`.
* `eval_key = h(spine_key, sorted gids selected, label gid, comparison mask, split, model family
  + params, estimand, checks version, rfp)`.

### 4.3 Execution modes, checkpoints, and the history origin

* **History origin.** `Study.origin`; every trigger and feature starts there in `initial_state`.
  Triggers declare `warmup_bars`; epochs during trigger warm-up carry `population_ready = False`
  and are excluded by both populations.
* **Runtime checkpoints** (`ckpt_runtime/`): trigger state, aggregator state, coarse-bar buffer,
  engine clock, producing `ReadPlan` hash. Schema fingerprint `h(trigger gids, rfp)`. Written at
  month boundaries of the sequential spine record. A restore is **refused** unless the
  checkpoint's ReadPlan hash, mode and plugin set (and gids when recorded) equal the restoring run's
  (red-team F4): a checkpoint carries its provenance and the actor enforces it.
* **Feature checkpoints** (`ckpt_feature/`, per group): `state()` at the same boundaries; schema
  fingerprint = gid. Only a sequentially recorded group has them.
* **Spine record**: sequential over `[origin, end)`.
* **Group attach, finite warm-up**: parallel shards over `[start − warmup, end + suffix)` within
  the authorised plan; triggers do not run; the spine's epochs are raised; features start from
  `initial_state` at `start − warmup`. Suffix = `max_horizon + one trading day` or the label's
  declared `max_suffix`.
* **Group attach, unbounded state**: sequential from `origin` against the spine's epochs,
  restoring runtime checkpoints for aggregator and buffer state, running the new feature from
  `initial_state`, writing its own feature checkpoints. A feature never claims history from
  another feature's or the spine's checkpoints.
* **Attach never moves the spine.** Population prefix consistency is proven by 6.1.
* **Engine input is batch-streamed (Phase 2 F24).** The authorised loader yields one Parquet row
  group (one UTC day) at a time and the runner feeds NautilusTrader's batch streaming; plugin and
  aggregator state persist inside the one engine, so memory is bounded by a day of bars plus the
  run's own snapshots. Only day-streamed catalogs realise this (F27).

### 4.4 Shard consistency

`ntr check shards` records one window sharded and sequentially and diffs every column including
status columns.

**Phase 2 amendments.** (red-team F2) Warm-up is denominated in each plugin's OWN timeframe: a
fine-stream plugin contributes a bar count, a coarse-stream plugin a time span (NT emits an internal
coarse bar per interval regardless of sparsity); a shard's prefix satisfies both and includes one bar
before the span so the aggregator covers it; an unbounded closure is refused in shards mode
(`UNBOUNDED_IN_SHARDS`) and its manifest records `warmup_ns: null`. A plugin whose state persists
until an event (a regime's anchor and age) is unbounded and records sequentially.
(F22) Warm-up is declared in bars and a shard's prefix is *counted* in bars,
walking back month by month through authorised ReadPlans until the declared count precedes the shard
start; the shard then receives exactly that many bars, never more, so an understated declaration is
detectable. (F23) Bit-identity under re-warm is unattainable for floating-point IIR features (an EMA
re-warmed from a finite prefix agrees to 1–2 ULP, not bit-for-bit); a plugin may declare
`shard_tolerance()` (relative, default 0), which 6.4 applies to floating columns only and records in
the receipt beside the observed maximum; status and integer columns stay exact. A finite-warm-up
feature must not expose unbounded state (a bar counter) as a field.

### 4.5 Fingerprints

* **Plugin fingerprint (symbol-level)** `fp = h(normalised AST of the plugin *class* and of every
  first-party symbol it references transitively -- functions, constants, base classes, helper
  classes -- resolved statically across the plugin packages and `ntr.core`; declared input
  partition hashes + schema)`. Adding an unrelated class to the same module leaves existing
  fingerprints, gids and receipts unchanged (review 8 item 2; Phase 2 acceptance case). Where
  static resolution fails (dynamic attribute access, `getattr` on modules, star imports) the
  fingerprint falls back to the whole module and the manifest records `fp_scope: module` so the
  conservative invalidation is visible rather than silent. Dependency *instances* are not part of
  `fp`; they enter through `gid` (§4.2).
* **Producer-runtime fingerprint** `rfp = h(normalised AST of every module reachable from the
  `ntr record` and `ntr fit` entrypoints within `ntr/`, excluding `ntr.analysis`, `ntr.cli`
  presentation and `ntr.backtest.execution`; pinned versions of Python, `nautilus_trader`,
  `numpy`, `numba`, `polars`, `pyarrow`, `lightgbm`; NT config values that affect **data
  delivery** only: aggregation flags, `time_bars_*`, calendar version)`. Execution settings are
  deliberately excluded (next bullet).
* **Execution scenario id** `xid = h(fill model params, latency model, slippage, order types,
  venue/account config, `ntr.backtest.execution` AST)`. Feature gids and the inference contract
  bind `rfp`, never `xid`; `(model_id, xid)` is a directory grouping only. The same frozen
  model bytes and contract run under any `xid` without retraining. A scenario is proven not to
  alter feature production by **6.9 production invariance**: the snapshots the actor emits during
  the backtest are compared bit-identically to the recorded spine and groups for the same
  window. Scenarios that will touch holdout are predeclared as a list of `xid`s in the
  commitment; an undeclared `xid` on holdout is refused.
* **Backtest identity** `bt_key = h(model_id, contract hash, xid, policy gid (policy code fp +
  params, including any score threshold), effective ReadPlan hash, instrument mapping (roll table
  hash + tradable-contract mapping), chron_id, commitment id | null, rfp)`. Every backtest
  artifact lives at `evals/<eval_key>/backtest/<model_id>/<xid>/<bt_key>/`; two runs that differ
  in period, policy parameter or mapping are two `bt_key`s under the same grouping.
* **Three separated obligations for a trade-shaped label.** (1) **Label fidelity** (6.7) is
  required once, under the label's declared **reference scenario** `xid_ref` (zero slippage, zero
  latency, `snapshot_close`), and is the only place exact agreement with fills is demanded.
  (2) **Execution sensitivity** runs the unchanged model and contract under alternative `xid`s;
  economic divergence from the `xid_ref` result *is the measured output*, and no fidelity gate
  applies to those runs. (3) **Production invariance** (6.9) must pass under every `xid`.
* **Non-determinism budget.** `OMP_NUM_THREADS=1` in record processes; `numba` flags as above;
  the truncation test's bit-identity is the detector for what remains.

### 4.6 Publication, concurrency and cleanup

* **Temp location.** `<parent>/<target>.tmp.<host>.<pid>.<uuid>/`, sibling on the same volume.
* **Ownership is an OS-held lock, not file content.** The publisher opens
  `<parent>/<target>.lock` and takes an exclusive advisory lock on it for the lifetime of the
  publish (`msvcrt.locking(fd, LK_NBLCK, 1)` on Windows, `fcntl.flock(LOCK_EX | LOCK_NB)` on
  POSIX). The operating system releases the lock when the process dies, however it dies. The
  lock file's *content* (`host, pid, temp_dir, gid, start_wall`) is informational: it tells a
  successor what to clean up, never whether the owner is alive.
* **Liveness = the lock is acquirable.** There is no pid or creation-time check and no
  observe-then-act step; the acquisition itself is the atomic ownership claim.
* **Reclaim = acquire.** A process that finds a `.lock` file simply attempts the non-blocking
  exclusive lock. Failure means a live owner (`ALREADY_PUBLISHING`). Success means it is the sole
  owner from that instant; it then reads the content, deletes exactly the named `temp_dir`
  (descendant inspection first; absent is a no-op), overwrites the content with its own record
  while still holding the lock, and proceeds to publish. No second lock file exists, so there is
  nothing recursive to reclaim; a successor that dies at any point releases the lock and the next
  successor repeats the same idempotent steps.
* **Remote volumes are unsupported in v1.** `runs/` must be a local volume; `ntr doctor` refuses
  a network path, because advisory-lock release semantics across SMB are not relied upon.
* **Phase 0 test (combined crash and concurrency).** Kill a publisher mid-write; start two
  successors and pause both immediately after each has read the dead owner's lock content; release
  both; exactly one acquires, the other reports `ALREADY_PUBLISHING`; then kill the winner during
  cleanup and repeat with two more successors. Testing crash recovery and concurrency separately
  does not count.
* **Publish.** Verify shard list, per-shard counts, exact key equality with the spine, part
  hashes; write `_COMPLETE.json` in the temp dir; `os.rename(temp, target)` where `target` must
  not exist. If it exists: identical `_COMPLETE.json` hashes → discard ours; different →
  `NONDETERMINISTIC_GROUP`, surfaced. Directory-rename atomicity on the target volume is a Phase
  0 experiment. The fallback, if it fails, is a `_COMPLETE.json`-last protocol in which the
  marker is written to `_COMPLETE.json.tmp` and `os.replace`d into place so a reader never sees
  a partial marker; selecting the fallback is not evidence it is safe, so Phase 0 also injects a
  crash mid-marker-write and runs concurrent readers against a publisher under both protocols.
* **Cleanup.** Only the lock holder (a successor that acquired the lock, or the process for its
  own temp dir). **Containment** of the deletion target is checked three ways before anything is
  removed: lexical containment under `runs/`, containment of the *resolved* path (`realpath`,
  junctions and symlinks followed) under the resolved root, and inspection of every ancestor
  strictly between root and target for a reparse point (Phase 0 D18: a junction at
  `runs/redirect` would otherwise redirect deletion outside `runs/`). Then walk **every
  descendant** and refuse if any entry is a symlink, junction or reparse point; never follow one.
  The same containment rule validates a recovered temp-dir path from lock metadata. Nothing
  outside `runs/` is ever deleted by `ntr`.
* **Replace with retry (Phase 0 F4).** On Windows, `os.replace` onto a file another process is
  reading at that instant fails with `PermissionError`, because Python's `open()` grants no delete
  sharing. Marker and lock-info writes use a bounded retry (100 × 20 ms); readers hold these files
  for microseconds. Exhausting the retry re-raises and the publish fails loudly.
* **Readers** require `_COMPLETE.json`, verify the manifest hash on open and part hashes before
  a fit or a check.
* **Dispositions.** `<feature>__status ∈ {OK, WARMING, NOT_READY, INPUT_UNAVAILABLE}`; label
  `status` per §6.7.

---

## 5. Training and the model bundle

### 5.1 Why training does not run inside NT

Rows are causal by construction; remaining leakage is cross-row: grouped chronological folds on
`anchor_id`, purge of rows whose label window crosses a fold boundary, embargo ≥ label horizon,
unique-group counts beside row counts.

### 5.2 Roles, commitment and the holdout transaction

* **Roles are repo-level, per instrument** in `chronology.toml`: `train`, `tune` (unprotected),
  `holdout` (protected). A study may narrow, never widen or rename. `ntr doctor` refuses a
  roles file in which a holdout year precedes a train year for the same instrument.
* **Holdout records are physically separate** and refused by `ntr fit` / `ntr analyze`.
* **Every read is a `ReadPlan`** (§4.0). The transaction below governs holdout partitions on
  any plan, whatever the verb.
* **Three ledger events**: `COMMIT` (commitment hash; not an exposure), `EXPOSURE_START`
  (written under an exclusive lock on the ledger file after checking prior exposure for the same
  (instrument, year); carries `untouched: true|false`; holdout bytes are read only after this
  line is fsynced), `RESULT` (outcome summary hash on completion).
* **Crash and retry.** `EXPOSURE_START` without `RESULT` is still an exposure. A re-run of the
  same commitment writes a new `EXPOSURE_START` (`untouched: false`, `retry_of`) and `RESULT`. A
  commitment whose fields differ from the current study is refused before any event.
* **Ledger authority.** Machine-local `$NTR_HOME/exposure_ledger.jsonl`; repository mirror with
  a `union` merge driver; two machines out of scope for v1.
* **Post-exposure class** propagates to every later artifact touching that (instrument, year);
  role changes for an exposed year require a `ROLE_CHANGE` ledger line.

### 5.3 The model bundle and the inference contract

```
models/<study>/<model_id>/  model.txt|model.onnx  contract.json  manifest.json  card.md
```

* `contract.json` (**inference contract**, validated by the strategy): ordered columns and dtypes
  of the *selected arm*, their gids, the `eligibility` predicate, `rfp`. **No execution setting
  is in the contract**; startup equality is about feature production and inference only. `ModelStrategy.on_start` rebuilds this from the running actor and refuses on any
  difference. It needs no label actor and no unselected-arm feature.
* `manifest.json` (**provenance only**): `eval_key`, comparison mask hash, per-fold metrics on
  the comparison population and on the deployment population, split, chronology roles used.
* Trading eligibility at each snapshot = `eligibility(snapshot)` evaluated by the strategy; a
  snapshot that fails it is scored for the record but never traded, and the count is on the
  backtest card.

---

## 6. Checks (`ntr check`)

### 6.0 Receipts, layered keys, and stage prerequisites

Artifacts and receipts live in **layers**, and a receipt binds to the narrowest layer it actually
depends on, so that an iteration invalidates only what it touched (§8.1):

| Layer | Key | Receipts bound here |
|---|---|---|
| Population | `spine_key` | 6.6 chronology of the spine's ReadPlan; spine half of 6.1 |
| Feature / label group | `gid` (with `spine_key`) | 6.2 static boundary (per plugin fp), 6.1 truncation for that group, 6.4 shards, 6.7 label fidelity (label gids, per `xid_ref`) |
| Training frame | `frame_key = h(spine_key, selected gids, label gid, comparison mask)` | 6.3 provenance |
| Fit | `fit_key = h(frame_key, split, model family + params, estimand)` | 6.8 selection verdict, coverage, metrics |
| Backtest | `bt_key` (§4.5) | 6.5 contract fidelity, 6.9 production invariance |

`eval_key` remains the name of the whole evaluated thing (it is `fit_key` plus checks version and
`rfp`) and is where cards and reports live, but a change to model parameters re-runs only the fit
layer: the spine, group and frame receipts stay valid because their keys did not change.

A receipt records verdict, reason, check version, and the `_COMPLETE.json` content hash of every
directory it read. Consumers recompute and refuse on any difference. "As applicable" is this
table, computed by `ntr status`:

| Verb | Required PASS receipts before it runs | Produced by it |
|---|---|---|
| `record` | 6.2 static boundary; 4.0 ReadPlan authorised (source and cached) | audit log; `_COMPLETE.json` |
| `check` (post-record) | — | 6.1 truncation, 6.4 shards, 6.6 chronology |
| `check --fidelity` | a published label group | **6.7 label fidelity**: a bounded isolated-engine run over the study's declared fidelity window (default: the first full train month), producing the receipt bound to (label gid, instrument, `xid`, `rfp`) |
| `fit` | 6.1, 6.2, 6.4, 6.6; cached inputs reauthorised (§4.0); semantic review approvals current (§8) | 6.3 provenance (refusal at fit time + receipt), 6.8 selection verdict, metrics with coverage over E, E∩O and C |
| `commit` | all of the above; 6.7 if the label is trade-shaped | `COMMIT` line, including the permitted `xid` list for holdout |
| `backtest` (train/tune) | 6.5 contract fidelity computed at start; 6.7 under the label's `xid_ref` (once) if trade-shaped | backtest card at `bt_key`; sensitivity divergence vs `xid_ref` when `xid ≠ xid_ref`; **6.9 production invariance** receipt |
| `backtest --holdout` / `record --holdout` | everything above + commitment matching (including `xid` ∈ permitted list) + `EXPOSURE_START` | `RESULT` line |

| # | Check | Computes |
|---|---|---|
| 6.1 | **Truncation** | Cutoffs `D1 < D2 < D3`, fresh interpreters, audit installed: run the full study (triggers and features) over `[A, Di]` and `[A, Di + k]` with the suffix perturbed. Compare the spine (`snapshot_id` set and trigger fields with `ts_init <= Di`) and every feature field with `ts_init <= Di`. Any difference or audit violation fails. A cutoff with an empty prefix, an empty perturbed suffix, or zero rows compared is `INCONCLUSIVE`, never `PASS` (red-team F5). The study module and every plugin it imports are validated statically and executed under the armed audit before any bar is delivered (F3). |
| 6.2 | **Static boundary** | §3.4 and §3.2 rules; params JSON-serialisable; trigger names unique; inputs year-partitioned. |
| 6.3 | **Label isolation (provenance)** | `X` only from `f_*` gids of the arm, `y` only from the label gid; label-provenance columns refused. Negative controls: `numpy.loadtxt` of a registered path from a plugin (audit), target copied from future bars (6.1). Permutation test is a diagnostic. |
| 6.4 | **Shard consistency** | §4.4. The check compares the **published group itself** against a fresh in-memory recompute in the other attach mode (a receipt must be about the bytes it binds; red-team F1); a deliverable recorded from a bar override is `INCONCLUSIVE`. |
| 6.5 | **Contract fidelity** | `contract.json` equals the running actor's rebuilt contract. |
| 6.6 | **Chronology** | Executed `ReadPlan` ⊆ authorised plan; holdout path untouched by fit/analyze; `EXPOSURE_START` present for any holdout partition; post-exposure class propagated. Permitted roles are enumerated per verb; an unknown verb is refused, never passed (F6). |
| 6.7 | **Label fidelity** | Below. |
| 6.8 | **Estimand execution** | Typed `Selection` over the comparison mask; per-arm row counts equal the mask; verdict on the card; equal elapsed windows and conditioning-signal rate enforced in analysis helpers. |
| 6.9 | **Production invariance** | During any backtest, the actor's emitted snapshots (spine fields and selected-arm feature fields) are compared bit-identically to the recorded spine and groups over the same window. Proves that the execution scenario `xid` did not alter feature production; a difference is a defect in the delivery/execution separation, surfaced as `SCENARIO_ALTERED_PRODUCTION`. |

**6.7 in detail.** Entry convention in v1 is **`snapshot_close`** only. Verified in NT 1.230
`backtest/engine.pyx`: the loop is `exchange.process_bar(bar)` → `data_engine.process(bar)`
(actors' `on_bar`, orders submitted) → `_process_and_settle_venues(bar.ts_init)`, so a market
order submitted during `on_bar(T)` is filled at `T` against the L1 book after bar `T`'s ticks,
i.e. at close(T) under `FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0)` (Phase 0 D1 confirmed
this empirically; F2: 1.230 has no stop-fill probability knob, so `xid_ref` is exactly those two
parameters plus zero latency). The label actor uses the same convention:
entry price close(T), entry time `T`, observation from `T + 1s`. At 1s resolution the
difference from a next-open convention is one second and is measured, not assumed, by the
Phase 0 fixture. A different execution timing (a limit at a price, a delayed market order) is a
different `Label`/`Policy` pair with its own fidelity evidence.

| Class | Definition | Disposition |
|---|---|---|
| `DETERMINISTIC` | Entry at close(T); barrier order decided by bar sequence with no gap across a barrier | Must agree **exactly** with NT fills in an isolated engine. SL convention `sl_fill="stop_price"` (NT: a stop touched inside a bar fills at the stop, not the bar extreme); the pessimistic `bar_extreme` convention is a label param that FAILS 6.7 by design |
| `SAME_BAR` | Both barriers inside one bar | Declared resolution (`worst_case` default = SL at the stop price); NT itself processes O,H,L,C and fills the PT first -- reported by 6.7, never compared |
| `GAP` | A bar opens beyond a barrier | Resolution known: a stop fills at the **open**, a limit at its **limit price** (NT 1.230 probe); compared exactly with NT fills like `DETERMINISTIC` |
| `HORIZON` | No barrier by `ts_open + horizon` | Timed market exit at `ts_open + horizon` against the last observed close (the bar AT the horizon is inside the window; NT fires the clock alert after it); compared exactly with NT fills |
| `DATA_GAP` | No bar for more than `max_gap` (default 60 s) in the window | Status `DATA_GAP`, excluded by default mask, counted |
| `SESSION_BOUNDARY` | Window crosses a session close or halt | `truncate`/`censor` per label param |
| `ROLE_BOUNDARY` | Window crosses a chronology role boundary (§4.0) | `TRUNCATED`, counted. Produced by a `ReadPlan` whose declared label suffix is truncated (`role_boundary: truncate`); with `refuse` the label group is refused (6.6). A suffix that ends while rows are still pending (declared coverage shorter than the label needs) is `SUFFIX_INSUFFICIENT`, never silent censoring |
| `ENTRY_UNFILLED` | No bar at `T` usable for entry (empty-window bar, halt) | Status `ENTRY_UNFILLED`, counted |

Every fit/backtest card reports the share of rows and of PnL in each non-deterministic class and
the best-case/worst-case PnL spread; a separate sensitivity backtest applies slippage and latency.
Evidence is bound to (label gid, instrument properties, fill model, order types, `rfp`).

---

## 7. Novelty paths

| Add | Write | Re-record | Review |
|---|---|---|---|
| Feature (finite warm-up) | one class + synthetic-bar test | its group, in shards | none |
| Feature (unbounded state) | same + `state()/restore()` | its group, sequential from origin | semantic review |
| Trigger | one class with unique `name` | spine | none |
| Label | one class + 6.7 evidence if trade-shaped | its group | semantic review |
| Reference input | year-partitioned files + registry entry | groups that declare it | semantic review |
| Analysis / Policy / Model family | one function / class / adapter | none | none |

---

## 8. Operator protocol (for a human, Opus or Sonnet running the show)

Every card is ≤ 30 lines, ends with a `next:` line naming exactly one verb, and never asks a
governance question.

```
ntr doctor                        environment, roles file sanity, NT version pin
ntr status  --study X             state at the current eval_key; prerequisites table; next verb
ntr record  --study X             ReadPlan → spine (once) + missing groups; detached; progress.json
ntr check   --study X [--fidelity]   post-record receipts (6.1, 6.4, 6.6); --fidelity runs the bounded isolated engine for 6.7
ntr explore --study X [script]    tables over the TRAIN/tune frame; no fit, no commit, no holdout (§8.1)
ntr review  request --study X     writes reviews/<plugin>_<fp12>.request.json (plugin fp, input partition hashes, subscribes, warmup)
ntr review  ingest  --study X --file <md> --reviewer <id>
                                  writes reviews/<plugin>_<fp12>.approval.json bound to those exact fingerprints;
                                  a changed fingerprint makes the approval stale, and stale is not approved
ntr fit     --study X             arms on the comparison mask; selection verdict; both population metrics
ntr report  --study X             report.md from artifacts; operator edits only the interpretation section
ntr commit  --study X             COMMIT line
ntr backtest --study X [--holdout --commitment <id>]     train/tune, or EXPOSURE_START … RESULT
```

### 8.1 Incremental research is the normal workflow

The verb sequence above is the *end-to-end path*. The normal interactive workflow is
dependency-driven: a change re-runs only the work it invalidates, and the operator may stop at
any layer and look. Nothing below requires a fit, a winner, a commitment or a backtest.

| What you change or want | Work executed | Reused untouched |
|---|---|---|
| Look at recorded TRAIN/tune rows, distributions, outcome tables; test an interpretation | `ntr explore --study X [script]` over the frame; no replay, no fit | everything |
| Add a feature | record its group (and any `depends_on` groups missing) against the existing spine; run the group-layer checks for it | spine, other groups, their receipts |
| Change a feature's parameters | new `gid` → record that group only | as above |
| Compare feature subsets or model settings | new `frame_key` / `fit_key`; fit and paired comparison on the same rows | spine, groups, group receipts |
| Add a label or change its horizon | record the label group; reuse features | spine, feature groups |
| Change the trigger or population logic | new `spine_key`: re-record the spine and dependent groups | nothing (correct: the population changed) |
| Change a policy or threshold | new `bt_key`; rerun the backtest with the same model | model, frame, fit |

`ntr explore` reads TRAIN and tune frames only and writes tables to `explore/<frame_key>/<spec
hash>/`; it never opens a holdout path. Commitment and holdout evaluation belong at the point where
a frozen candidate is to be tested, not at every iteration. **Evidence boundary:** iteration
informed by TRAIN/tune results is free; iteration informed by a holdout result is
`post_exposure` for that (instrument, year) by the ledger rule in §5.2 and cannot claim that
holdout as untouched validation.

Decisions the operator never makes: roles, holdout years, which checks apply, whether a review
is needed, what to delete, whether a stale approval still counts. Decisions the operator makes:
the hypothesis, plugin code, typed estimand fields, `eligibility`, `role_boundary`, the
interpretation paragraph, and the content of a review when acting as reviewer (the reviewer id
is recorded; a model reviewing its own plugin is recorded as such).

---

## 9. Layout and budget

```
ntr/  data/ core/ record/ train/ backtest/ live/ analysis/ checks/ cli.py      ≤ 6,000 lines
features/ triggers/ labels/ policies/ analysis/ inputs/
studies/<id>/ study.py notes.md plugins.py reviews/ runs/(gitignored)
models/  captures/  chronology.toml  exposure_ledger.jsonl (mirror)
tests/   synthetic catalog (values encode ts_init); negative and positive controls; both-order tests
```

---

## 10. Decisions traced to paid-for failures

| Decision | Failure it answers |
|---|---|
| One engine | Collector optimism; survivor-biased schedule eval; G7 |
| Internal aggregation from 1s, buffered to next epoch | Catalog 1m defects; MTF bar-open reads; tie-order dependence |
| `snapshot_close` entry, verified against the engine loop | Review 3 item 1; "anchor from bar close" owner rule |
| Values-not-paths inputs, year-partitioned; stack-aware audit | Review 2 B1; review 3 item 3 |
| `ReadPlan` authorised before construction | Review 3 item 3; scope loss at joins |
| `gid` in the address, `rfp` in every key, receipts bound to bytes | Review 2 B2 |
| Origin + runtime/feature checkpoints + spine regeneration in truncation | Review 2 B3 |
| Comparison population vs deployment population | Review 3 item 2; bare arm list trained one model |
| OS-held advisory lock as the only ownership claim; descendant inspection | Review 3 item 4, review 5 item 1; repository junction-safety rule |
| Three-event holdout transaction under a lock | 2023 double-use |
| Review request/ingest bound to fingerprints | Review 3 operator note |

---

## 11. Build plan (approval requested for Phase 0 only)

| Phase | Deliverable | Acceptance |
|---|---|---|
| 0 | Synthetic catalog; pinned ordering; coarse-bar buffering; stack-aware audit harness; **fill-timing fixture**; **filesystem experiments** | **Rejections:** coarse bar read at its own close caught; `open()` in a plugin fails; `numpy.loadtxt` of a registered path from a plugin fails; plugin-authored `exec` fails. **Permissions:** an ordinary plugin runs; a `numba`-jitted plugin runs with the hook armed. **Ordering:** both actor orders identical. **Fill timing:** snapshot bar close ≠ next open materially; assert submission at `T`, fill at `T`, price close(T). **Filesystem:** directory `os.rename` onto a non-existent target on the runs volume is atomic or the fallback is selected; under both protocols a crash mid-marker-write leaves no reader accepting a partial publish, and concurrent readers never observe a half-published group; the combined crash-and-concurrency lock test of §4.6 passes (two successors paused after observing the same dead owner, exactly one acquires; winner killed during cleanup, repeat); the OS releases the advisory lock on `TerminateProcess`/`SIGKILL` on the runs volume; a reparse point anywhere under a temp dir aborts deletion. **Report format:** demonstrated behaviour / failed assumptions / unresolved cases, each listed separately; success authorises Phase 1 only |
| 1 | `ntr data build` + monthly partitions + manifest; adopt existing catalogs; `ReadPlan` | Manifest round-trip; roll table maps every day; a TRAIN request whose suffix crosses holdout is refused before any holdout partition is opened, or truncated when declared; a year-partitioned reference input loads only authorised partitions |
| 2 | Protocols, registry (fp, gid, rfp), `FeatureActor` with `PluginContext`, spine record with runtime checkpoints, group attach (both modes), atomic publish, 6.1/6.2/6.4 | Two parameterisations coexist; an actor-dispatch edit changes `rfp`; a receipt from one group's bytes does not authorise another; unbounded-state feature added after the spine replays from origin; run starting inside a regime yields `population_ready=False` epochs; future-dependent trigger fails the spine comparison; concurrent publishers reconcile or fail `NONDETERMINISTIC_GROUP`; a checkpoint produced under a holdout plan is refused by a train verb |
| 3 | `LabelActor`, labels, 6.3, 6.7 classes | Same-bar high/low cannot resolve; simultaneous triggers; deterministic rows agree exactly; each class reproduced by a fixture including `ROLE_BOUNDARY` |
| 4 | `ntr fit`, split, bundle with `contract.json` + `manifest.json`, typed selection | Label-provenance column refused; per-arm count ≠ mask refused; leaking control refused; selected model starts with no label actor and no unselected-arm feature; both population metrics reported |
| 5 | `ModelStrategy`, policies, `chronology.toml`, three-event ledger, 6.5/6.6 | Two processes racing for an untouched year: exactly one `untouched: true`; crash after `EXPOSURE_START` leaves the year exposed; stale contract refused; ineligible snapshot scored but not traded |
| 6 | Analysis helpers, `ntr report`, `ntr status` prerequisites table, review verbs, card audit | Missing estimand refused; unequal windows refused; stale approval blocks fit; every card ends with `next:` |
| 7 | Live capture, `ntr live-equivalence`, restart | Restore skips no bar; unbounded-state study refuses cold start; captured day classified |
| 8 | Re-run one closed historical question end to end with a Sonnet-class operator | Written comparison of turns, wall time and checks fired |

---

## 12. Red-team brief for revision 4

1. §3.4: I/O with no plugin frame on the stack (library threads; C extensions without audit
   events); a `numba`-compiled function doing I/O through an intrinsic.
2. §4.0: a physical read the `ReadPlan` does not enumerate (NT internal `request_bars`, catalog
   metadata reads, instrument definitions spanning years).
3. §6.7: whether close(T) entry is achievable live (the 1s bar closes at `T`, the order is sent
   after `T`); the fixture pins the backtest, the live equivalence test must pin the residual.
4. §5.3: an eligibility predicate that is causal at snapshot time but depends on state a live
   restart cannot restore.
5. §4.6: a volume or filesystem driver where the advisory lock is not released on process death, or where two processes can both hold it; behaviour when the lock file is deleted while held.
6. §8: a state in which `next:` cannot name a single verb.

---

## 13. Decisions for the owner

| Decision | Recommendation |
|---|---|
| Model bytes | Native LightGBM; ONNX only when live requires it |
| Coarse-bar visibility | Next 1s epoch, by actor buffering |
| Entry convention | `snapshot_close` (NT's demonstrated behaviour); other timings are separate label/policy pairs with their own evidence |
| Deployment population | `selected_arm_readiness`, with both population metrics reported |
| Role boundary | `truncate` declared per study; never silent |
| Study spec | Python with §3.2 restrictions |
| Repository | New repository; adopt catalogs by monthly re-partition + manifest; port nothing as code |
| Isolation | Trusted-plugin controls now; process isolation deferred and not claimed |

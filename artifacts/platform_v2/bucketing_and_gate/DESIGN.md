# chore/bucketing_and_gate — DESIGN CARD (discovery session, 2026-09-14)

Written by the discovery session that ran the pilot re-collection (session bfb18698). **No code is written yet.**
The implementation session starts HERE, not from the packet alone. Owner decisions below are final — do not re-ask.

Claim: `ws chore claim bucketing_and_gate` is held by session bfb18698 (TTL 72h). The implementation session
re-claims with `ws chore release --force bucketing_and_gate` (same user@host) then claims as itself.
Branch base: main `78dc5879`.

## Owner decisions (2026-09-14)

| # | decision |
|---|---|
| D1 | A1 derived-stream source = the **coarsest external stream that divides the timeframe AND is visible at the epoch**. Pilot (1m cadence): 3m..4h from `nq_1m`, 5s/30s from `nq_1s`. A 1s-cadence study keeps deriving from `nq_1s` (no one-bar lag). OHLCV is identical either way because 1m is itself built from 1s with the same any-member rule (below). |
| D2 | A2: `seconds_since_update` beyond **8 calendar days** is a **hard runtime failure** `TRACKER_STALENESS_IMPOSSIBLE` (tracker id + age). Same bound for every timeframe. Below it: data, never null. |
| D3 | ~~A1 zero-trade window emits nothing.~~ **SUPERSEDED 2026-09-14 by the owner in the implementation session (see D3a/D3b).** It was decided on the wrong claim that NT emits nothing for an empty window. |
| D3a | A1 zero-trade window emits a **zero-volume bar** (O=H=L=C = previous close, volume 0): NT 1.230's `TimeBarAggregator` default (`build_with_no_updates=True`). No bar before the first member (NT `_build_bar` returns while the builder is uninitialized). |
| D3b | Fill scope **in-session only**: an empty window is emitted iff `[open_ts, close_ts)` overlaps a `TRADING_DAY` row `(open_ns, close_ns]` of the dataset's `sessions` calendar (holidays, early closes, the daily break and weekends excluded). **Known divergence from NT**: NT's timer also fires through closures. A dataset with no `sessions` table has no trading-day authority: the compiler records `empty_window: none` on its derived streams and says so in a compile note. The external `nq_1s`/`nq_1m` streams stay as the dataset built them (empty seconds/minutes absent) -- only derived timeframes are filled. |

## A1 — evidence gathered

- **Why the rule exists: undocumented.** `mux.py:19-24` cites "the accepted `collectors/collector_v2/aggregator.py`
  semantics". That aggregator's `is_complete` ("every expected one-second member is present once") arrived in
  commit `97b97dba` (2026-08-15, message "8.15", with the red-team rounds 2-6 exports and
  `NT_RESEARCH_FLOW_INDEPENDENT_AUDIT_BRIEF.md`). None of those documents discuss bucket completeness (grep for
  incomplete / missing second / partial bucket / forward fill: no hit). The only tests are synthetic:
  `test_completed_regime_state.py:41` (seconds 0,1,3,4 of a 5s bucket) and `test_host_core.py:27`. **No real 5s
  case is guarded → escalation condition "rule guards a real case at 5s" NOT triggered.**
- **1m provenance: clear, NOT Databento-native.** `research/datasets/NQ_1S_V2_GLOBEX.yaml:57-64`: 1m is
  `build_time_from_native_1s(closed=left,label=left,minute_exists_iff_native_second)`
  (`research_workflow/dataset_v2.py:416-419`, `resample(...).agg(...).dropna()`), with an independent integer-key
  implementation (`aggregate_minutes_independent`, `:422`). Parity:
  `artifacts/platform_v2_do_soon/dataset_v2/equivalence_NQ.json` — V2 1s == V0 1s and V2 1m == V0 1m exactly
  (2021/2022/2023/2025, `P1_all_exact`, `P2_all_exact`). Its verdict also records
  **`5m_runtime_rule_matching_v0: any_minute`** — the platform's own proof says the rule that reproduces the
  historical external 5m stream is ANY-member, i.e. `complete_bucket` contradicts it. Escalation "1m provenance
  unclear / parity failing" NOT triggered.
- **NT correction to the packet.** NautilusTrader 1.230.0 `TimeBarAggregator`: `build_with_no_updates: bool,
  default True` (`nautilus_trader/data/aggregation.pyx:1479,1501`); `_build_bar` skips an empty window only when it
  is False (`:1733`). So NT by default DOES emit a bar for a zero-update window (previous close, zero volume).
  D3 (emit nothing) equals the dataset build rule and equals NT **only with
  `DataEngineConfig(time_bars_build_with_no_updates=False)`**, which no file under backtests/, research_workflow/,
  utils/, strategies/ sets today. Record this in the code comment and in the report; any live NT aggregation must
  set it for offline/live parity.
- **Bit-identity of sealed studies.** Committed plans with `aggregation: complete_bucket`: only
  `studies/v2_shape_b_deep_pullback_5s` (`nq_5s`, `nq_5m` ← `nq_1s`); es_180s_model_c_portability,
  first_p90_warning_horizon_march2024, v2_shape_a_flip_180s, v2_shape_c_barrier_race_fade derive nothing.
  **Design:** keep `BucketAggregator` complete-bucket behaviour dispatchable for a plan that names
  `aggregation: complete_bucket` (sealed plans replay bit-identically); the compiler never emits it again and emits
  `aggregation: closed_window`. Mux dispatch at `mux.py:143` becomes a per-name table; an unknown name raises.
  Gate: replay shape_b's sealed plan on its smoke day before/after → identical candidates/observations sha256.

### A1 — implementation sketch

1. `mux.py`: `ClosedWindowAggregator(derived_key, bucket_ns, source_duration_ns)`: bucket keyed
   `ts_event // bucket_ns`, absorbs whatever arrives; publishes when (a) the source bar with `ts_init >= close_ts`
   arrives (existing finalize_through), or (b) **any** stream's bar with `ts_init > close_ts` (strict) is applied —
   add a mux-level clock sweep in `_apply` before delivery. Strict `>` matters: at `T` the 1m bar closing at `T` may
   still be queued behind the 1s bar at `T`; it is released before the first execution bar with `ts_init > T`
   (`_release_context`), so a sweep at `> close_ts` never excludes a member. No bars → no bucket → nothing.
   At every epoch the published set equals NT's timer-close set: an epoch at a 1s bar `T` implies the 1m bar at `T`
   exists (minute exists iff a second exists); an epoch at the 1m bar `T` finalizes via (a).
2. `compiler.py:264-276`: source = D1. Replace the `finest` override at `:271`. The cadence stream is only known
   after `_mark_epoch_bearing_stream` (`compiler.py:759-785`, called at `:853`): when it flips a context stream to
   `at_epoch`, re-point derived streams whose timeframe is a multiple of it to `derived_from: <cadence stream>`.
   Derived streams inherit the source's visibility. Emit `aggregation: closed_window`.
3. Keep `incomplete_close_ts` reporting only for `complete_bucket`. Gap censoring stays tape-level (`max_gap`).
4. `collectors/collector_v2/aggregator.py` is historical — do not edit.
5. Close-time evidence: derived `ts_init = close_ts` unchanged; add a test that a 4h bar from 1m has
   `ts_event = open`, `ts_init = close`, and that the 1m source carries `ts_init_delta_ns = 60e9`.

**Correction (implementation session).** Step 1's strict `>` sweep is not enough for "published set equals NT's
timer-close set": a 30s window from `nq_1s` whose last second is empty closes at `T`, and under a 1m cadence the
epoch at `T` is the 1m bar -- strict `>` would publish the window one epoch late. As built, a sweep is inclusive
(`close_ts == t`) when the applied bar's stream is always applied after the source at the same instant (execution
before context; finer context before coarser), strict otherwise. Tested in `test_host_core.py`.

Gates: 1h for 2023 → thousands of regimes; 4h → bars (acceptance in S2); shape_b sealed replay bit-identical;
`test_host_core` / `test_grammar_v2` / `test_completed_regime_state` updated — the synthetic "incomplete rejected"
test stays for `complete_bucket`, a mirror test proves `closed_window` publishes it.

## A2 — `seconds_since_update`

`features/trackers/host_bindings.py:60` `RegimeDualEmaBinding.EPOCH_FIELDS = ("age_s",)`; `last_bar_close_ts` is
already a FIELD (`:58`, set `:103`). Add epoch field `seconds_since_update = (epoch.T - last_bar_close_ts)/NS`
(None before the first bar) and raise `TRACKER_STALENESS_IMPOSSIBLE` past 8 days (D2). Column exposure: metadata
is compiled from `features.metadata` (`compiler.py:1091-1094`) — decide in-session whether the compiler adds
`<tracker>_seconds_since_update` automatically beside every metadata column that reads that tracker (packet
wording: "beside each tracker's state") — automatic is the packet's intent; it changes candidate schemas of new
compiles only. Check other tracker bindings for the same epoch field.

## A3 — plan-bound freshness

`research_workflow/governed_controller_v2.py:110-132`: readiness, preflight, seal compare only
`execution_composite`. Add `artifact.plan_sha256 == compiled plan_sha256` for readiness, preflight,
frozen_execution_manifest (prepare), seal; smoke receipt/`smoke_acceptance.json` (receipt stages) likewise.
Keep tests and causal audit composite-keyed (plan-independent) — say so. Gate: change only
`outcome.session_end_rule` in a fixture → all five go stale, tests + causal audit stay fresh.
Evidence it bit: pilot commits `da8d46f4`, `51948afd` on study/nq_mtf_regime_atlas_pilot2023.

## A4 — explore compile validates operators

`research_workflow/explore.py:88-136` proves ops/DAG/artifacts but never params; `precedence_labels` refuses
unknown ops at run (`research/analysis/diagnostic_ops.py:526-527`, vocabulary `_COMPARISONS` `:60-63`).
Point fix: validate rule ops at compile. General check to evaluate and report: dry-run the compiled pipeline on a
zero-row frame carrying the frame's column schema (the G7 pattern: compiler dry-constructs the StreamMux).

## A5 — `observed_seconds`

Flip kernel rows (`research_workflow/host/outcomes.py:48`, row build `:520-535`) carry `resolved_at_ts` but no
observed duration; `analysis.incidence.cumulative` / `decomposition.buckets` require `observed_seconds_column`
(`diagnostic_ops.py:239-255,290-308`). Add `observed_seconds = (resolved_at_ts - T)/1e9` for every disposition
(positive → flip, censored → session close / gap / data end). Not `time_to_flip_seconds` (null when censored).
Confirm the barrier kernel's existing definition first and match it.

## A6 — two analysis ops

Grouped descriptive summary (n, mean, median, declared quantiles, group keys, censoring-aware) and
session-day-clustered uncertainty (SE + CI for means and differences; `n_rows` AND `n_clusters` REQUIRED output
fields). Register via `research_workflow/capabilities_index.d/analysis_ops.yaml` + `research/analysis/ops.py`
boundary + golden fixtures; `cap generate --check`. Cost: an analysis-op addition derives to ~37 files / 428 tests
including the four heavy e2e proofs (memory: registration_boundaries_merged).

## A7 — `WORKFLOW.md:946-947`

Replace `session_end: censor` with `truncate` for an ETH+RTH next-event census; why: `censor` censors whenever the
observation window passes the close (`outcomes.py:277`) — pilot smoke 1380/1380; `truncate` (`:267-272`).

## B — anchors found (not yet read in full)

- B1: `scripts/test_delta.py:73-78` `baseline_issues` compares `platform_commit` to reference.
- B2: `_build_estimator` not found under research_workflow/*.py or scripts — locate first.
- B3: `lifecycle_v2.py:318` `compile_outcome`; `research_workflow/grammar/compiler.py:1722` `compile_study`.
- B4: `scripts/research.py:159` and `research_workflow/policy.py:321` emit `OLD_RUNTIME_LEGACY_ONLY`.

## Implementation session 1 (067506d2, 2026-09-14) -- HANDOFF

Ended past context budget, per the packet ("hand off with what is committed").

**Committed on `chore/bucketing_and_gate`:**
- `4ffe1189` **A1** -- `closed_window` + D1 repoint + D3a/D3b in-session zero-volume fill. Plan fields per derived
  stream: `aggregation: closed_window`, `empty_window: zero_volume_in_trading_day | none` (`none` only on a dataset
  with no `sessions` table, with a compile note). Runtime calendar: `resolve_calendar_session_spec` always
  materializes `TRADING_DAY` rows; `build_session_table` attaches them as `table.trading_day`; `HostCore` passes it
  to `StreamMux(trading_days=...)`; the mux refuses a fill plan without one (`TRADING_DAY_CALENDAR_ABSENT`), the
  compiler's dry construction passes `require_calendar=False`. Gates run: `test_host_core`, `test_grammar_v2`,
  `test_redteam_v2_sessions`, `test_trading_day_censoring`, `test_golden_fixture` (92 passed) + new D1 compile
  test (7 passed); `lint_host` CLEAR; shape_b sealed plan replay 2021-01-05 identical before/after (candidates
  `6d49d2a8`, observations `b5c075da`, 103305 bars). NOT run: broad `test_delta`, `cap generate --check`, a real
  GLOBEX run of a fill plan (that is S2's acceptance).
- `d9c1587f` **A7** -- WORKFLOW.md census wording: `session_end: truncate`.

**Not started: A2, A3, A4, A5, A6, B1-B4.** Anchors verified this session (do not re-derive):

- **A3.** `lifecycle_v2.fingerprints()` (`:330-343`) already returns `plan_sha256`. Artifacts already carrying
  `plan_sha256`: frozen manifest (`:405`), readiness (`:453`), preflight (`:494`), smoke manifest (`:589/596`);
  check the seal body (`:531`). `_fresh_stage` (`governed_controller_v2.py:110-132`) compares only the composite.
  Receipts: `governed_controller.py:302 _receipt_current` / `:324 _write_receipt` write and compare only
  `execution_composite_sha256` -- `plan_sha256` must be added to the receipt body AND compared; that is the one
  place the field does not exist yet.
- **A5.** `LEGACY_OBSERVATION_COLUMNS` (`host/outcomes.py:46-50`) is shared by the kernel (`:229`) and the compiler
  (`compiler.py:1091-1096`). Appending `observed_seconds` there changes the observation schema of every sealed
  plan's replay (shape_b's observations hash would change). Gate it on a contract field new compiles emit
  (e.g. `contract.observed_seconds: true`), appended by both compiler and kernel. Definition: `(resolved_at_ts - T)/1e9`,
  which matches the analysis harness's own anchor op (`research/analysis/diagnostic_ops.py:171`, terminal_ts minus
  anchor). The barrier arms' `<prefix>_resolution_seconds` (`outcomes.py:539-549`) is a DIFFERENT quantity
  (measured from `entry_ts`, horizon substituted at early DATA_END) -- do not reuse it.
- **A1 → live NT.** The zero-volume fill is in-session only; a live NT host with default
  `build_with_no_updates=True` would also emit bars through closures. A live deployment must suppress those (or
  use NT's `False` and synthesize in-session bars) to match offline. Not built; recorded.

## Implementation session 2 (2026-09-15) -- COMPLETE: A2-A6 + empty_windows_published, gated

Commits: `09ed261a` A3 · `2e80ed1d` A4 · `743f92fa` A6 · `5e50caf9` A5 · `b2abd8bf` A1 run stat · `15511dc6` A2 ·
plus the A4 audit-offender fix below. Part B not started (dropped per packet). shape_b sealed replay on
2021-01-05 checked after EVERY item (a3, a4, a5, a2, final): candidates `6d49d2a8`, observations `b5c075da`,
103305 bars, identical each time.

**Broad gate** (`test_delta` five scopes, run alone, head `15511dc6`): 2538 ran, 2442 passed, 69 failed;
KNOWN_BASELINE_FAILURE 60, BASELINE_FAILURE_NOW_FIXED 1 (`test_multi_agent_ownership::test_10_...`),
NEW_FAILURE 9. Wall **271m06s** -- slower than every prior run (74m41s, 81m59s, 83m14s, 88m02s, 97m53s,
99m02s, 211m29s; the 211m29s run was two scopes / 2258 tests). Not like-for-like with the one-/two-scope
runs; no B2 in either.

Baseline: `--check-baseline` returned `BASELINE_COMMIT_MISMATCH` (recorded on `c480d8af`, merge-base
`78dc5879` -- stale on arrival, as recorded). The run used `--baseline-reference c480d8af` (an ancestor;
`--check-baseline` then `OK`). Conservative: anything the five later commits broke is still NEW.

The 9 NEW, each resolved:

| node | verdict | evidence |
|---|---|---|
| `test_generic_contract_audit::test_no_hardcoded_feature_count_in_generic_workflow` | **one offender was mine** (`compiler.py` A4 `len(cond) != 3`) -- fixed by unpacking; the test also fails on main | worktree offenders after fix == main's five (`compiler.py:1020` here is main's `:997`, same statement, shifted) |
| `test_redteam_pass1_acceptance::test_acc12_canaries_green` | pre-existing | fails identically on main `78dc5879` (same 5 ordered-barrier subtests, CENSORED vs LABELED_NEGATIVE) |
| `test_direction_qualified_freeze_binding::test_aggregate_freeze_opens_the_real_oos_gate` | pre-existing / artifact | fails on main: closure evidence `bound model artifact corrupt/missing` |
| `test_external_model_scoring::..._repaired_model_c_...` | joblib (by design) | `train_fitted_models.joblib` absent in a fresh worktree; passes on main |
| `test_stage3_integration::test_stage3_model_c_long_short_routing` | joblib (by design) | same missing joblib; passes on main |
| `test_runtime_bindings::test_episode_study_...` | joblib (by design) | worktree `missing` = the unbound scorer for that joblib; main `missing` = [] |
| `test_catalog_materializer::test_materialization_required_when_catalog_absent` | environment | `RAW_DATA_MISSING` for YM raw parquet in the worktree; passes on main |
| `test_pre_flip_reliability_contracts::test_long_/short_candidates_...` (2) | environment | untracked `studies/*/_work/prepared_*.parquet`; pass on main |

Not verified on real data: the zero-volume fill on a GLOBEX run and the 8-day bound on a six-year run (S2).

## A4 -- the pattern, named (implementation session 2; not built)

**Compile accepts what runtime refuses** -- three instances, each fixed as a point fix:

| # | compile accepted | runtime refused | fix |
|---|---|---|---|
| G7 | a cadence stream declared `strictly_before` | `CONTEXT_STREAM_VISIBLE_AT_EPOCH` on the first epoch | compiler dry-constructs the real `StreamMux` |
| stream roles | `derived_from: <a key not in the plan>` | mux cannot build the aggregator | same dry construction |
| A4 | `>` / `==` in `classify.precedence` conditions | `ANALYSIS_RULE_INVALID` at run | vocabulary declared at the boundary (`research.analysis.ops.COMPARISON_OPS`), compiler checks against it, implementation refuses to import on drift |

The shared cause: the compiler carries its **own model** of what a runtime component accepts. Whenever the
compiler validates by re-stating a rule rather than asking the component, the two drift.

**Is a general check possible?** Partly, and the shape is known:
- *Streams*: already general -- dry construction of the real host object is the component answering.
- *Analysis pipelines*: a zero-row dry run of the compiled pipeline over the frame's column schema is NOT
  sufficient. Ops legitimately refuse empty populations (`ANALYSIS_TAIL_LIFT_ROWS_EMPTY`, `..._REFERENCE_EMPTY`),
  so a dry run would refuse valid specs, and ops that run no validation on empty input would pass invalid
  ones. It needs a per-op side-effect-free `validate(params, schema)` contract that the op's own run path
  also calls first -- one definition of "valid", used by both.
- *Trackers / predicates / outcome kernels*: same contract shape (`validate(declaration)` on the binding or
  kernel), called by the compiler instead of compiler-side re-statements.

Recommendation: scope "runtime-authoritative compile" as one capability -- every runtime component exposes
`validate`, the compiler's point checks are replaced by calls to it, and a registration-boundary test proves
no compiler-side re-statement of a runtime rule remains. Not a fourth point fix.

## S2 carry-overs (study/nq_mtf_regime_atlas_pilot2023, report `reports/s2_resume_and_collect.md`)

**Added by implementation session 1:** the pilot's committed plan names `complete_bucket`; recompile it (compile
now emits `closed_window` / `zero_volume_in_trading_day` on `NQ_1S_V2_GLOBEX`, 3m..4h from `nq_1m` under the 1m
cadence). Report `empty_windows_published` beside regime counts per timeframe once exposed -- today it is a mux
attribute only (`ClosedWindowAggregator.empty_windows_published`), not in run stats.

Fix in the study at recompile: `research_decision.yaml` flip anchor (`bars_1m == 0` with `flipped_1m`), identity
claim (`checkpoint_index` null on 100% of rows; `(regime_start_ns, observation_ts)` unique). After A3 merges the
manual gate-file deletion used in S2 must no longer be necessary — verify that, do not repeat it.

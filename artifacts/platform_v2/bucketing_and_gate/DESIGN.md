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
| D3 | A1 zero-trade window emits **nothing** (packet). Do not synthesize zero-volume bars. |

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

## S2 carry-overs (study/nq_mtf_regime_atlas_pilot2023, report `reports/s2_resume_and_collect.md`)

Fix in the study at recompile: `research_decision.yaml` flip anchor (`bars_1m == 0` with `flipped_1m`), identity
claim (`checkpoint_index` null on 100% of rows; `(regime_start_ns, observation_ts)` unique). After A3 merges the
manual gate-file deletion used in S2 must no longer be necessary — verify that, do not repeat it.

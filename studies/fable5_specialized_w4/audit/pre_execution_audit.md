# Look-Ahead & Timestamp Audit — PRE-EXECUTION GATE

**Date:** 2026-07-17T00:00:00Z (America/Chicago request date 2026-07-17)
**Revision:** v2 — delta re-verification of two post-audit edits (see
"Delta re-verification" section). v1 findings NOTE-1 and NOTE-2 are
resolved by this delta; NOTE-3 and NOTE-4 carry forward unchanged.
**Scope:** `studies/fable5_specialized_w4/` — pre-execution gate; nothing in this
study has executed yet (no `_work/`, `results/`, or `input_freeze.json` present
at audit time).
**Auditor:** lookahead-auditor v1

## Files inspected (current contents)

| File | SHA-256 | Changed since v1? |
|---|---|---|
| `SPEC.md` | `e619142be815bf504fc504b4091ca13d662b8118550802e450b82a4175f88237` | yes |
| `fable5_common.py` | `e07d35fdb0b467dbb7dae73287a1dbaffe00d74885d76522fd06364ea8a7b018` | no |
| `build_dataset.py` | `8f600d8b7451f531166541736223aee5390442d61aa33138e0fcc92f64c77863` | no |
| `train_models.py` | `47dc4563c4f79fd08baf7c52bd74e8a0c72a43fb1f02bbc33a2e9e10379943ac` | no |
| `replay_selection.py` | `9b7c6097d65840536fd8c487c828c647f0d3c7844c279b18d410e90f6de6f123` | yes |
| `tests/test_specialized_w4.py` | `636ed9bb6722091d2411318b2ee62d2cc16d1d4577521a7832340bc6cde6d8e6` | no |

`fable5_common.py`, `build_dataset.py`, `train_models.py`, and
`tests/test_specialized_w4.py` hashes are byte-identical to the v1 audit,
confirming the coordinator's "no other files changed" claim independently
(not just taken on trust).

Read for comparison only (not re-audited from scratch; treated as frozen,
previously-validated upstream contracts): `codex_5_w4_multi_candidate_reentry/run_study.py`
(`simulate_trade`, `touched_stop`, `stop_fill`, streaming busy-rule, `execute_policy`),
`CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`
(`canonical_regime_timeline`, `is_rth`, `validate_raw_bars`, `progress_window_counts`,
`established_state`, `collect_candidates`, `reconcile_first_candidates`),
`CODEX_5_X_weakness_atlas_repair/CODEX_5_X_common.py` (`RAW_1S`, `year_atlas_path`),
`regime_sequence_chop_context/train_weakness_model.py` (`CENTER_FEATS`,
`SEQUENCE_FEATS`, `LOCAL_FEATS`), `codex_5_w4_fade_confirmation_clock_isolation`
config/results (`POLICY_A_COMBINED_1P25_300S` trade diffs), plus parquet schema
inspection of `candidates_2025.parquet`, `CODEX_5_X_weakness_atlas_repaired_2025.parquet`,
`CODEX_5_X_established_fade_2025_trades.parquet`, `isolation_trade_diffs.parquet`.

Verification method: full read of all five in-scope source files plus the test
file; line-by-line diff of `fable5_common.simulate_trade_arrays` against
upstream `run_study.simulate_trade`; execution of the study's own fixture test
suite (`pytest studies/fable5_specialized_w4/tests/test_specialized_w4.py`,
9/9 passed, re-run after the delta) — this only exercises synthetic fixtures
and the pure `assign_windows`/`streaming_execution` functions, it does not
touch frozen study data and does not trigger `require_authorization()`, so it
does not constitute "execution of the study" in the sense gated by
`fable5_common.require_authorization()`; schema/dtype inspection of upstream
frozen parquet files to confirm column names and types referenced by
`reconcile_policy_a`/`join_features` actually exist as expected; `ast.parse`
syntax check on the edited `replay_selection.py`.

## Summary

- Critical: 0
- Warning: 0
- Note: 2 (carried forward from v1; 2 of the original 4 v1 notes are resolved
  by this delta, see below)

No look-ahead, train/serve skew, or timestamp-precision defect was found that
would corrupt results if this pipeline is executed as written.

## Delta re-verification (this revision)

Two edits were made in response to v1 NOTE-1 and NOTE-2. Both are confirmed
clean.

### Edit 1 — `SPEC.md:124-127` — baseline comparator wording now matches code

The "Baseline comparator" bullet now reads: "the frozen W4 ranked by
`score_margin` (= `w4_score − direction_threshold`, making sides comparable
under a global retention percentile; no retraining), plus the original
take-everything W4 candidate stream and the frozen Policy A first-candidate
arm." This is a documentation-only change (no code touched) that brings
SPEC.md into agreement with `train_models.py:104-105`
(`score_structure`, `structure == "baseline_w4"` uses `g["score_margin"]`).
Traced `score_margin`'s definition back to candidate generation
(`codex_5_w4_multi_candidate_reentry/run_study.py:190-191`:
`"score_margin": score - threshold`, where `threshold = float(cp.direction_threshold)`
at line 154) — confirms the parenthetical formula in the new SPEC wording is
correct, not just plausible-sounding. **Resolves v1 NOTE-2.** No causality
implication either way (both `w4_score` and `score_margin` were, and remain,
fully known at candidate decision time); this was always a documentation-
fidelity item, not a leakage risk, and is now closed.

### Edit 2 — `replay_selection.py:143-147` — quintile labels materialized in `run_window()`, isolated to the trade-diffs deliverable

```python
lo, hi = bundle["quintile_edges"]
diff["label_top_quintile_pnl"] = np.where(
    d.replayable, (d.net_pnl_usd >= hi).astype(float), np.nan)
diff["label_bottom_quintile_pnl"] = np.where(
    d.replayable, (d.net_pnl_usd <= lo).astype(float), np.nan)
```

Verified, in order:

1. **Edge provenance and freeze.** `bundle["quintile_edges"]` is written once
   by `train_models.py:288,330` as `list(np.percentile(train.net_pnl_usd.to_numpy(float),
   [20, 80]))`, where `train` is the H1-purged training window
   (`train_models.py:281-282`, same `train` frame used to fit every model
   structure). `lo, hi = bundle["quintile_edges"]` unpacks correctly as
   `[20th-percentile, 80th-percentile]` (order preserved from the `np.percentile`
   call), so `net_pnl_usd >= hi` is genuinely "top 20%" and `net_pnl_usd <= lo`
   is genuinely "bottom 20%" — no swap bug.
2. **Frozen, not recomputed per window/year.** `run_window()` receives
   `bundle` as a parameter on every call (`train_models.py`'s bundle is
   loaded once from the pickled `BUNDLE_PATH` in `main()` at
   `replay_selection.py:177-178` and passed unchanged into every
   `run_window()` call for H1-insample, H2-dev, and — on a later,
   separately-gated invocation — 2026). The same frozen H1 edges are applied
   identically to every window and year; there is no code path that
   recomputes `quintiles` from dev or 2026 data. This matches SPEC's "computed
   on the H1 training set only, then applied everywhere" contract exactly.
3. **No feature-matrix or acceptance-rule leakage.** Confirmed by full-text
   search of `train_models.py` and `replay_selection.py`: `label_top_quintile_pnl`
   and `label_bottom_quintile_pnl` do not appear in `RAW_FEATURES`,
   `POOLED_CONTEXT`, `STRUCTURE_FEATURES`, `segment_masks`, `fit_structure`,
   `score_structure`, `policy_arms`, `assign_cutoff`, or `streaming_execution`
   — the two new columns are written only onto the `diff` DataFrame (which
   feeds `trade_diffs_{year}.parquet` → `specialized_w4_trade_diffs.parquet`),
   strictly *after* `arms`/`scores`/`results` (the objects that drive
   acceptance and economics) have already been computed from `policy_arms(bundle, d)`
   at `replay_selection.py:135`, and the new lines never feed back into that
   call or into any subsequent one in the same function. This also confirms
   the code executes *after* both model fitting (`train_models.py`, a
   separate, already-completed, already-frozen run) and dataset/label
   construction (`build_dataset.py`), so there is no possibility of these
   outcome-derived diagnostic labels influencing what candidates get accepted
   or what features a model sees.
4. **Correct masking of non-replayable rows.** `d.replayable` gates both new
   columns to `np.nan` for non-replayable candidates, consistent with every
   other outcome-derived label in the codebase (`label_net_positive`,
   `label_alignment_5m`, etc. in `build_dataset.py` use the identical
   `np.where(replayable, ..., np.nan)` pattern). `np.where` evaluates both
   branches elementwise, so `NaN >= hi`/`NaN <= lo` on non-replayable rows
   silently evaluates to `False` before being overwritten by `np.nan` via the
   `replayable` condition — confirmed non-crashing and correct by inspection
   and by the passing test suite.

**Resolves v1 NOTE-1.** This is outcome-derived by design (as SPEC's own
"Labels" section already declares `net_pnl_usd`, `candidate_policy_net_positive`,
etc. to be) and is correctly confined to the descriptive trade-diffs
deliverable — it is never an input to feature matrices, model fitting, or the
causal acceptance rule, so no leakage channel is introduced.

## Critical findings

None.

## Warnings

None.

## Notes (carried forward from v1; unaffected by this delta)

### [C3/reporting-completeness] `train_models.py:82-84,299-301` — Model C insufficient-sample gate is structure-level, not cell-level

`SPEC.md:118-120` says each of the 4 side×session cells is checked against
the ≥150/≥150 gate independently and "that cell is reported
`INSUFFICIENT_SAMPLE`." `fit_structure` returns `None` for the whole
structure on the *first* failing cell encountered in iteration order, and
`insufficient.append(structure)` records only the structure name, not which
cell(s) failed or their actual pos/neg counts. The net behavior ("Model C not
promoted if any cell is under-sampled") matches SPEC's functional intent and
is not a correctness bug — no wrong result is produced — but the per-cell
diagnostic SPEC promises for the completion report will not exist unless this
is extended to check and record all 4 cells before short-circuiting.

### [H2/H4 — inherited, not re-flagged per SPEC caveat (c)] `fable5_common.py:180-186` — stop fills at exact trigger price on non-gap bars

`touched_stop`/`stop_fill` (byte-identical port of the frozen Policy A
contract) fill a triggered stop at the exact stop price when the 1s bar's
range includes the level but the open doesn't gap through it, and only use
the bar open when the open itself gaps past the stop. This is the standard
checklist-H4 concern ("credit the fill at exactly the trigger level" rather
than a true next-bar-open fill) and is inherited unchanged from the already-
reconciled upstream Policy A management contract. Per the task's explicit
instruction, SPEC.md's declared caveat (c) — "1-second OHLC research
simulation, not NT-native" — already covers this class of finding and it is
**not** being escalated to WARNING/CRITICAL. Noting it here only so the
report is transparent about what this caveat concretely means mechanically:
economics reported by this study (independent and streaming) are expected to
be mildly optimistic on stop-based exits relative to a true tick/NT-execution
replay, exactly as already disclosed.

## Focus-area verification detail (from v1, still current — code paths covered are unchanged by the delta except where noted)

**1. Feature causality.** `RAW_FEATURES = ATLAS_FEATURES + CANDIDATE_FEATURES`
(`fable5_common.py:45-48`) contains no field from `CENTER_FEATS`/`SEQUENCE_FEATS`/
`LOCAL_FEATS` (`regime_sequence_chop_context/train_weakness_model.py:1-42`)
that is outcome- or label-derived (all are geometry/statistics of the price
path up to the checkpoint; none reference `opp_flip_in_120s`,
`terminal_deterioration`, or any other post-checkpoint field). The join in
`build_dataset.join_features` (`build_dataset.py:31-53`) is keyed on
`(regime_start_ns, observation_time == candidate_time)` — an **exact**
timestamp match (not `merge_asof`/`<=`), `validate="one_to_one"`, followed by
a hard `isna()` check that aborts on any unmatched row, plus two independent
cross-checks (`regime_age` vs `regime_age_s`, `current_mfe` vs
`running_mfe_atr`, both `atol=1e-9`) that verify the joined atlas row is
literally the same checkpoint that originally produced the candidate — this
closes off the classic "off-by-one merge" failure mode. Candidate-only fields
(`candidate_seq`, `new_progress_windows`, `retained_mfe_ratio`,
`atr_at_checkpoint`) were traced to `codex_5_w4_multi_candidate_reentry/
run_study.py:117-123,152-212` and are computed from `progress[k]`/
`established_state(cp, ...)` at index `k = searchsorted(ts[a:b], decision,
"left") - 1` — strictly the checkpoint at-or-before the decision, causal.
`w4_score`/`score_margin`/`threshold` are confirmed absent from
`RAW_FEATURES`/`POOLED_CONTEXT` and from `STRUCTURE_FEATURES["A_pooled"/
"B_side"/"C_side_session"]` (`train_models.py:31-35`) — they appear only in
`baseline_w4` and `D_hier`, matching SPEC's declared exclusion. The two new
`label_top_quintile_pnl`/`label_bottom_quintile_pnl` columns from the delta
are likewise confirmed absent from every feature-matrix path (see "Delta
re-verification" above).

**2. Label replay.** `fable5_common.simulate_trade_arrays` was diff-read
line-by-line against `codex_5_w4_multi_candidate_reentry/run_study.py:402-447
simulate_trade` — identical variable derivation order, identical branch
order and conditions (pre/post stop ATR multipliers, `aligned`/
`timeout_pending` state transitions, `touched_stop`/`stop_fill` semantics,
scheduled-exit boundary via `searchsorted`), identical loop bound
(`range(start, scheduled_i + 1)`, so the entry bar `i == start` is inside the
stop-check loop in both). `tests/test_specialized_w4.py::test_sim_parity`
independently confirms exact field-for-field equality (`entry_fill_ts`,
`entry_fill_px`, `reached_aligning_flip`, `exit_fill_ts`, `exit_fill_px`,
`exit_reason`, `gross_pnl_pts`, `net_pnl_usd`) against the actual upstream
function (imported live, not re-implemented) across 7 fixture cases covering
pre-flip stop touch, gap-open stop fill, confirmation timeout (both the
"never aligns" and the "aligns exactly at timeout boundary" sub-cases),
post-alignment stop, and opposing-flip scheduled exit for both long and short
directions. All 9 tests pass (re-run after the delta; unaffected since
`fable5_common.py`/`build_dataset.py` are byte-identical to v1).
`build_dataset.replay_labels` (`build_dataset.py:56-108`) enters at
`candidate_fill_time` (first 1s bar open at/after the decision, confirmed via
`run_study.py:181-183` upstream construction) and correctly treats
`candidate_time >= confirm_flip_ns` and missing `candidate_fill_time` as
non-replayable with null labels, matching SPEC.

**3. Split discipline.** `assign_windows` (`build_dataset.py:149-161`) sets
`h1 = candidate_time < BOUNDARY_NS` and purges an H1 candidate iff its own
`exit_fill_ts >= BOUNDARY_NS` **or** its `opportunity_end_ts >= BOUNDARY_NS`.
Because `opportunity_end_ts` is assigned identically to *every* candidate in
an opportunity (`run_study.py:220-223`), any opportunity whose management
horizon crosses the boundary has **all** of its H1-side candidates purged
from train — not just the specific crossing one — while any of its
candidates with `candidate_time >= BOUNDARY_NS` correctly land in
`2025_H2_dev` and are kept. This closes the "same regime contributes rows to
both train and dev" leakage channel described in the task; confirmed
functionally via `tests/test_specialized_w4.py::test_window_purge`.
`train_models.py:286-287` additionally asserts `train.candidate_time.max() <
BOUNDARY_NS` as a runtime fail-safe. The delta's new quintile-label columns
are computed in `replay_selection.py` (post-training, post-freeze) and use
the frozen H1 edges regardless of which window a given row belongs to — this
does not reopen the boundary, since the edges themselves were already frozen
using H1-only data before this code runs.

**4. Selection isolation.** `train_models.py` reads only `C.dataset_path(2025)`
— no reference to `dataset_path(2026)` or any 2026-suffixed file anywhere in
the file. `fable5_common.require_2026_open_allowed` (`fable5_common.py:144-163`)
hard-gates `build_dataset.py --year 2026` (`build_dataset.py:202-205`, which
also requires the 2025 dataset to exist first) and `replay_selection.py --year
2026` (`replay_selection.py:179-180`) behind the frozen selection manifest
(`status == "FROZEN_ON_2025_ONLY"` + bundle hash match); the **2026 dataset
itself cannot be built** until after `train_models.py` has already frozen and
written the manifest, so there is no code path by which 2026 features/labels
could exist in memory or on disk while model family/hyperparameter/retention
selection is running. `train_models.py:277-278` additionally refuses to
re-run if `FIRST_2026_OPEN_PATH` already exists ("cannot refreeze after 2026
has been opened"). Retention cutoffs (`retention_cutoffs`,
`train_models.py:116-126`) and family/config selection (`selection_pnl`,
`train_models.py:129-141`) are computed exclusively from the `dev` argument,
which is always `labeled[window == "2025_H2_dev"]` — never touches 2026.

**5. Retention/replay causality.** `replay_selection.assign_cutoff`
(`replay_selection.py:25-35`) reads cutoffs from the frozen
`bundle["structures"][s]["cutoffs"]` dict (written once by `train_models.py`
and loaded read-only) — no per-replay recomputation. `streaming_execution`
(`replay_selection.py:92-106`) processes candidates strictly in
`(candidate_fill_time, candidate_seq)` order using only `busy_until` derived
from prior iterations' own `exit_fill_ts`/`exit_reason` — confirmed causal by
construction and by `tests/test_specialized_w4.py::test_streaming_busy_rule`,
which also confirms the busy-rule constant (`stop` exit frees at `exit+1s`,
non-stop frees at `exit_ts`) matches `codex_5_w4_multi_candidate_reentry/
run_study.py:483` exactly (`+ NS if "stop" in result["exit_reason"] else`).

**6. Timestamp precision.** All nanosecond timestamp fields
(`candidate_time`, `candidate_fill_time`, `confirm_flip_ns`, `regime_start_ns`,
`opportunity_end_ts`, `observation_time` in the atlas, `entry_fill_ts`,
`exit_fill_ts`, `timeout_ts`) are `int64` at the parquet-schema level
(confirmed by direct dtype inspection of `candidates_2025.parquet` and
`CODEX_5_X_weakness_atlas_repaired_2025.parquet`) and are kept as Python
`int`/nullable pandas `Int64` throughout `build_dataset.py` and
`fable5_common.py` — never cast to `float64`. `build_dataset.py:61-63`
explicitly documents and enforces this (`ts = raw.index.view(np.int64)`;
explicit nullable-`Int64` sentinel construction for non-replayable rows,
avoiding the `NaN`-forces-`float64` trap). `assign_windows`'s
`.fillna(0).astype(np.int64)` operates on an already-`Int64` nullable array,
not a `float64` one, so no precision loss occurs. `reconcile_policy_a`
(`build_dataset.py:111-146`) checked and confirmed exact-integer (`!=`)
comparison for all timestamp fields (`.to_numpy(np.int64)`), with `np.isclose`
tolerance comparison reserved for genuinely-float fields (prices, PnL). One
non-exact-reconciliation timestamp usage was found —
`train_models.stability_rows` converts `candidate_time` to a month bucket via
`pd.to_datetime(..., unit="ns")` (`train_models.py:256`) — this is a
diagnostic grouping key only (monthly feature-stability report), not used for
ordering, causality gating, or reconciliation, so it is out of scope for the
"never passes through float64" rule as stated (that rule targets exact
reconciliation/ordering, which this is not). The delta's `lo, hi =
bundle["quintile_edges"]` are plain Python floats (dollar PnL edges, not
timestamps) — no timestamp precision concern applies to them.

**7. Accepted caveats.** SPEC.md's three declared caveats — (a) 2025-H2
mild in-sample candidate-membership effect via the frozen W4 isotonic
calibration window, (b) limited sample depth, (c) 1-second OHLC research
simulation, not NT-native — are present and correctly scoped in SPEC.md and
are not re-flagged here as findings, per the task's explicit instruction.

## Clean checks

- A2/A5 equivalent (checkpoint-vs-decision-time join is exact-match, not
  interval/asof; atlas causality contract inherited and spot-checked, not
  violated by the new join code).
- B1–B7: no `.rolling(`, `center=True`, `.shift(-`, `.bfill(` found anywhere
  in the 5 in-scope files (`grep` swept clean); `SimpleImputer`/
  `StandardScaler` fit exclusively inside `Pipeline.fit(train)`, never
  re-fit on dev/test; `IsotonicRegression` (Model D) fit exclusively on
  `train` per segment.
- C1/C2: the two newly-materialized quintile labels are outcome-derived by
  design (as SPEC's Labels section intends) and confirmed confined to the
  trade-diffs reporting table, never a model input (see Delta re-verification
  point 3).
- C3/C4: split is strictly temporal (`candidate_time < BOUNDARY_NS`), no
  `cross_val_score`/`train_test_split` usage anywhere in scope.
- D2/D4: feature list and order (`fitted["features"]`) is identical between
  fit time and score time for every structure; no categorical/string columns
  reach `.to_numpy(float)`.
- H1: `touched_stop` uses `high`/`low`, never `close`, for trigger detection
  (confirmed by direct grep of all `close` occurrences in scope — none feed a
  stop/PT comparison).
- H3: streaming re-entry/busy-rule fixture-tested to match the upstream
  streaming-lifecycle contract exactly; SPEC explicitly declares "no
  re-entry logic beyond what the candidate stream already contains."
- Reconciliation-gate plumbing (`reconcile_policy_a`) references real,
  correctly-typed columns in `isolation_trade_diffs.parquet` (`new_exit_fill_ts`
  int64, `new_exit_fill_px`/`new_net_pnl_usd` float64) and
  `CODEX_5_X_established_fade_2025_trades.parquet` (`entry_fill_open`,
  `entry_direction`, `session`, `regime_start_ns` all present); `POLICY_A_ID`
  string (`"POLICY_A_COMBINED_1P25_300S"`) matches the isolation study's
  `config.json`/`policy_freeze.json` exactly.
- `input_hashes()`/`freeze_inputs_or_verify()` freezes all declared upstream
  inputs (including 2026 raw/atlas/candidates/scores/frozen-trades) by content
  hash before any candidate/feature/label computation runs, matching SPEC's
  "sha256-recorded ... before execution" declaration; hashing raw bytes does
  not expose analyzable 2026 content to model selection.
- `require_authorization()`/`require_2026_open_allowed()` fail closed (raise)
  rather than fail open on any missing/mismatched file, consistent across all
  three entry-point scripts.
- SPEC.md's baseline-comparator wording now matches `train_models.py`
  (Edit 1); the quintile-label deliverable is now actually produced,
  isolated to reporting (Edit 2).

---

**Status:** **PASS — AUTHORIZED FOR FIRST EXECUTION**
**Findings:** **0 CRITICAL, 0 WARNING**

*Audit complete. This is a static read-only review of the pre-execution
pipeline; it does not verify that `reconcile_policy_a`'s runtime reconciliation
gate actually passes against real data (that can only be checked by executing
`build_dataset.py`, which is exactly what this audit gates). The 2 remaining
notes above are non-blocking (no corrupting bug found) and should be triaged
before the completion audit, not before first execution.*

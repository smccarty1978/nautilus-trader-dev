# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20
**Scope:** `studies/nt_live_scoring_infra_prereqs/` (SPEC.md; `phase0_reconstruct_model.py` +
`results/phase0_manifest.json`; `phase1_feature_inventory.py` + `results/f3_feature_inventory.csv`/
`_summary.json`; `features/registry.py` Phase-2 diff; `results/feature_timing_causal_spec.md`;
`tests/test_registry_schema_extension.py`, `tests/test_feature_timing_causal_contract.py`,
`tests/test_coincident_bar_ordering.py`). Direct imports followed for verification:
`features/trackers/ohlcv_delta.py`, `features/trackers/price_levels.py`,
`features/FEATURE_REGISTRY_CONTRACT.md`, `studies/short_rth_pure_flip_prediction_enriched/`
(`_work/train_2021_2024_prepared.parquet`, `_work/prepared_2025.parquet`,
`_work/scored_dev_2025.parquet`, `_work/feature_sets.json`), `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py`
(`fit_gbt`), `studies/ohlcv_volume_delta_price_level_features/attach_features.py`,
`studies/short_rth_entry_surface_backfill/entry_surface.py` (+ its own prior `audit/audit.md`),
`studies/regime_sequence_chop_context/build_weakness_atlas.py`,
`studies/fable5_nt_short_rth_policy_a/run_nt.py`.
**Auditor:** lookahead-auditor v1

All three test files were executed directly (`pytest studies/nt_live_scoring_infra_prereqs/tests/ -v`):
**19/19 passed.** An additional adversarial re-run of the Phase 4 fixture (reversing the
`engine.add_data()` call order, outside the pytest suite) was performed to probe the robustness of
its claimed proof — see Critical finding 1.

## Summary

- Critical: **1**
- Warning: 5
- Note: 4

## Critical findings

### [Phase 4 / A4] `tests/test_coincident_bar_ordering.py` — the "coincident 1s-before-1m" proof is an artifact of `add_data()` call order, not a genuine NT engine guarantee

The test (and `SPEC.md`'s Phase 4 description, and `feature_timing_causal_spec.md`'s framing)
present this fixture as converting CLAUDE.md invariant 4 into "a tested, reproducible proof usable
by every future NT study." It is not that. `BacktestEngine.add_data(data, sort=True)` re-sorts the
*entire* accumulated stream by `ts_init` on every call, using a stable sort; at a `ts_init` tie
between two data streams added via two separate `add_data()` calls, the tie is broken purely by
*which stream's elements were already in the pre-sort array first* — i.e., by which `add_data()`
call happened first in the calling script, not by any bar-type-aware or timeframe-aware priority
inside NT itself.

Reproduced directly: taking the exact test fixture and only reversing the two `add_data()` calls
(1m added before 1s, instead of 1s before 1m) flips the observed arrival order at the coincident
timestamp from `["1s", "1m"]` to `["1m", "1s"]`:

```
reverse_add_order=False: [(1748872860000000000, '1s'), (1748872860000000000, '1m')]
reverse_add_order=True:  [(1748872860000000000, '1m'), (1748872860000000000, '1s')]
```

So the thing actually demonstrated is: *"if a script adds the 1s bar stream before the 1m bar
stream, coincident bars arrive 1s-then-1m."* That is a real, useful, and currently-true fact about
this repo's convention (confirmed: `fable5_nt_short_rth_policy_a/run_nt.py:64-65` also calls
`engine.add_data(bars_1s)` before `engine.add_data(bars_1m)`, so today's one live-validated
multi-timeframe NT study happens to follow it) — but it is a **calling-convention requirement**,
not an NT-native property, and nothing in this repo currently documents or enforces that
requirement. `docs/BACKTEST_EXECUTION.md` has zero mentions of `add_data` ordering. A future
author of the follow-on `nt_live_ml_scoring_population_parity` study (or any other NT study loading
1s+1m data) who writes `engine.add_data(bars_1m); engine.add_data(bars_1s)` — an entirely natural
ordering, e.g. if bar types are iterated in a config list that happens to list the coarser
timeframe first — would silently get the 1m bar delivered *before* the 1s bar at every
minute-boundary tie, exactly reintroducing the MFE/MAE blind spot CLAUDE.md invariant 4 and the
buffer-and-replay pattern in `OHLCVDeltaTracker`/`attach_features.py` exist to prevent, with no test
anywhere catching it (this test only re-validates its own fixture's own hard-coded call order).

This is CRITICAL because it corrupts silently: nothing fails, nothing warns, the score is just
computed as if the FeatureEngine already knew about the still-forming 1m bar's context a
minute early. It also means Phase 4's stated purpose — "usable by every future NT study, not just
this one" — is not yet true; the proof needs either (a) confirmation that NT's data-engine layer
does have some documented, type-aware tie-break independent of `add_data` call order when data is
loaded through the production path (e.g. via `ParquetDataCatalog`/`BacktestDataConfig` rather than
raw `add_data`), or (b) the call-order requirement made an explicit, tested, documented contract
(e.g. a runtime assertion in a shared NT-run helper, not just two scripts that happen to agree by
convention).

**Not a fix — for the record only:** re-running the identical fixture with the two `add_data` calls
combined into one list before a single `add_data()`/`sort_data()` pass, or checking whether
`ParquetDataCatalog`/`BacktestDataConfig`-driven loading (the production path, vs. this fixture's
and `run_nt.py`'s raw list-based `add_data`) has a different, more robust tie-break, would resolve
whether this is fixable structurally or must remain a documented calling convention. Out of scope
for this read-only audit to determine further.

## Warnings

### [SPEC internal consistency] `SPEC.md:168` vs `SPEC.md:30` — stale "~90" entry count never reconciled with the corrected 502

`SPEC.md`'s Finding 1 (lines 28-30) explicitly corrects an earlier scout claim: the registry has
**502** entries, not "~90." Confirmed directly (`len(FEATURE_REGISTRY) == 502`). But `SPEC.md`'s own
Phase 2 paragraph (line 168) still reads "backfills existing **~90** verified entries" — the
pre-correction number, never updated after Finding 1 corrected it earlier in the same document. The
actual Phase 2 implementation backfilled `window`/`window_unit`/`reset_policy` **only** for the two
programmatically-generated families added by `_add()` (`ohlcv_est_delta`: 214 entries,
`price_level_context`: 247 entries — 384 of 502 entries carry non-default values), and explicitly
left the ~41 pre-existing hand-written entries (`arrival_velocity` ×10, `arrival_volume` ×10,
`pullback_1s` ×8, `pullback_1m` ×8, `context` ×5) completely untouched at the dataclass defaults —
confirmed both by direct inspection of `registry.py:37-269` (no `window=`/`window_unit=`/
`reset_policy=` kwargs anywhere in that block) and by
`tests/test_registry_schema_extension.py:35-42`'s own `test_pre_existing_entries_unaffected`, whose
docstring states this is deliberate ("A feature not touched by Phase 2's edits (outside F3) keeps
the additive defaults"). That scoping decision is reasonable (F3 doesn't need those families) and
is tested, but `SPEC.md`'s own prose was never corrected to describe it — a reader auditing against
the literal frozen SPEC text would expect ~90 legacy entries to have been backfilled with
prose-inferred defaults ("default values inferred from FEATURE_REGISTRY_CONTRACT.md prose where
determinable, else left None/flagged" — SPEC.md:169-170), which did not happen for any of them
(e.g. `arrival_vel_5s`'s window is obviously inferable as 5 seconds from its own name/family, per
the exact same inference method already used for `rolling_{w}m_*` price levels, but was left
`None`/`None`/`"none"` rather than inferred or explicitly flagged as skipped).

### [SPEC internal consistency] `SPEC.md:136,140-141` — Phase 0's own prose target/data-source description is stale relative to Finding 6's correction

`SPEC.md`'s Phase 0 paragraph (lines 132-148) instructs reconstruction on "`outcome_class` target"
and comparison against "the stored `score_dev` array from the checkpoint pickle." Both phrases are
leftover from the *superseded* 5-class study Finding 6 discusses
(`short_rth_enriched_volume_level_retrain`'s checkpoint pickle, `{row, calib_frames,
importance_rows, cutoffs, score_train, score_dev, score_test}` — no model object, 5-class
`outcome_class` target). The actual implementation (`phase0_reconstruct_model.py`) instead correctly
reconstructs the **binary** `bearish_regime_flip_within_300s` model from a *different* study,
`short_rth_pure_flip_prediction_enriched` (its own `_work/train_2021_2024_prepared.parquet`,
`_work/prepared_2025.parquet`, and `_work/scored_dev_2025.parquet`'s
`score_F3_volume_delta_plus_price_levels__gbt_raw` column — verified these files exist and the
target/feature-list line up, no leakage: target column confirmed absent from the 695-feature F3
list, no duplicate feature names). This is the *correct* model (matches the SPEC's own overview,
lines 6-9: "the frozen bearish-flip GBT model"), and the script's own docstring (lines 9-12)
explicitly flags the distinction — but `SPEC.md`'s Phase 0 section itself was never corrected to
match, leaving two mutually-contradictory target/data-source descriptions inside the one "frozen"
document. Purely a documentation-consistency defect (the actual reconstruction is correct and
verified — see Clean checks), but exactly the kind of leftover-after-correction gap this audit was
asked to check for.

### [Phase 3 / B9] 17 `regime_*` (A4) features carry `status=verified`/`live_tracker_exists=True` despite Phase 3's own disclosed unverified dependency

`feature_timing_causal_spec.md`'s final section ("Open item not independently verified in this
pass") explicitly states that `regime_starts`' own construction
(`canonical_regime_timeline`/`timeline_from_flips`) was **not** traced to the same depth as the
feature trackers in this pass. All 17 of `OHLCVDeltaTracker`'s regime-relative (A4) features —
`regime_available`, `regime_vol_sum`, `regime_est_delta_sum`, `regime_elapsed_seconds`, etc. — are
gated entirely by when `reset_regime()` is called, i.e. by `regime_starts`. Confirmed all 17 are
present in F3's 695-feature list and all 17 carry `status="verified"`, `live_tracker_exists=True`
in `results/f3_feature_inventory.csv` with no distinguishing flag. `SPEC.md`'s own Phase 3 mandate
(lines 187-189) is explicit: "Any feature family whose timing cannot be confirmed causal within
this phase is flagged as `TIMING_UNVERIFIED` in the Phase 1 inventory, not silently assumed
correct." No feature in the CSV carries any value resembling `TIMING_UNVERIFIED` anywhere (`status`
column only ever contains `verified`/`unregistered`). The risk is meaningfully mitigated — the spec
document reasons the boundary is a completed minute's `close_ts` and cites an already-live-validated
`RegimeEngine` precedent (`nt_pure_flip_trigger_poc_and_mirrored_long_model`) rather than asserting
it blind — but the letter of the Phase 3 requirement (an inventory flag) was not carried out for
this specific, disclosed gap.

### [Phase 2] SPEC-mandated "codified mechanism for a consuming study to declare its `snapshot_anchor` binding" was not delivered

`SPEC.md:170-174` requires Phase 2 to add, in addition to the schema fields, "a codified (not
narrative-only) mechanism for a consuming study to declare its `snapshot_anchor` binding, per
`FEATURE_REGISTRY_CONTRACT.md:121-123`'s existing deferral." Searched `features/registry.py` and the
whole study directory: no such mechanism exists anywhere — `snapshot_anchor` remains a single
class-level default string (`"caller_defined"`) with no per-study override/declaration API, function,
or config surface added. `tests/test_registry_schema_extension.py` has no test covering this
requirement either. This specific, explicitly-required Phase 2 deliverable appears to have been
silently dropped without a documented descope decision anywhere in the study.

### [Required pytest coverage] Phase 0 ("model artifact load + rescoring tolerance") has zero pytest coverage

`SPEC.md`'s "Required pytest coverage" list (lines 204-208) names four items, one of which is
"model artifact load + rescoring tolerance (Phase 0)." Grepped all three test files for
`joblib`/`phase0`/`reconstructed`/`model_artifact`: zero matches. `phase0_reconstruct_model.py`
does perform its own internal tolerance check and raises `SystemExit` on failure (verified sound —
see Clean checks), but that is a one-shot script assertion, not a regression-tested pytest case that
independently loads the persisted `.joblib` artifact and re-confirms it still scores within
tolerance against the stored reference. If the artifact or upstream parquet files are ever silently
regenerated/changed, nothing in this study's test suite would catch a divergence.

## Notes

### [B9 / test design] `tests/test_registry_schema_extension.py:73-96` — `test_all_f3_ohlcv_and_price_level_features_have_reset_policy_populated` can't actually detect a skipped backfill

The docstring claims this confirms "Phase 2's backfill actually ran, it wasn't skipped," but the
assertion (`d.reset_policy in ("none", "event_start", "session_boundary")`) includes `"none"` — the
exact same value as the untouched dataclass default. A registry where the backfill silently never
ran at all (every entry left at the default `"none"`) would pass this assertion identically to one
where the backfill ran and legitimately assigned `"none"` to many features. The `checked == 546`
count (line 96) is the assertion actually doing useful work here (it would catch missing/renamed
features), not the `reset_policy` membership check itself, which is closer to tautological than the
test's own docstring claims.

### [Phase 3 test coverage] Empirical prefix-invariance/immutability tests exercise only `OHLCVDeltaTracker`, never `PriceLevelTracker`

`tests/test_feature_timing_causal_contract.py` imports and tests only `OHLCVDeltaTracker` (the
1s/`ohlcv_est_delta` family, 214 of 546 registered F3 features). `PriceLevelTracker` (the 1m/
`price_level_context` family, 332 of 546 — the larger share) has no equivalent runnable
prefix-invariance or snapshot-immutability test; its causal correctness rests entirely on the
citation-based prose in `feature_timing_causal_spec.md` and this auditor's own line-by-line
cross-check of `attach_features.py`/`price_levels.py` (which did check out — see Clean checks).
`SPEC.md`'s Phase 3 language ("a handful of targeted hand-computed checks... not full
re-derivation") is loose enough that this is arguably compliant, but a future reader should not
assume `PriceLevelTracker` has the same empirical test-backed confidence `OHLCVDeltaTracker` does.

### [Registry classification robustness] `phase1_feature_inventory.py:54,70` — `live_tracker_exists = bool(d.implementation)` would silently misclassify a registered-but-unimplemented feature

The five hand-written `context`-family entries (`regime_age_bars`, `ema_slope_short`,
`ema_slope_long`, `is_rth`, `minutes_since_rth_open`, `registry.py:259-269`) have `status="verified"`
but no `implementation=` set (defaults to `""`). Had any of these coincided with an F3 feature name,
`classify()` would report `in_registry=True` (correct) but `live_tracker_exists=False` for a feature
whose registry entry claims `status="verified"` — a latent inconsistency between "registered" and
"has a live tracker" that the current F3 list happens not to trigger (confirmed: zero overlap
between F3's 695 names and these five context-family names, and zero overlap with the 10
`arrival_velocity`/`arrival_volume` entries either, all of which do have `implementation` set). Not
a live bug today, but worth hardening (e.g. warn or classify separately) before this classification
logic is reused for a future feature-set inventory that does include one of these families.

### [Documentation staleness, cosmetic] `features/FEATURE_REGISTRY_CONTRACT.md:78-100`'s canonical `FeatureDefinition` example predates Phase 2

The contract doc's "Required Registry Metadata" example (§3) — the template future contributors are
told to copy — does not include the `window`/`window_unit`/`reset_policy` fields Phase 2 added,
even though §2's prose already described them as required tracker parameterization before Phase 2
existed. The window-unit vocabulary Phase 2 encoded in `registry.py` (`bars|seconds|minutes|
events|session|since_signal|since_regime_flip`) does exactly match §2's prose list — that part is
consistent — but the copy-paste template itself is now incomplete.

## Clean checks

- **Phase 0 model reconstruction is genuine, not a copied-scores false positive.** Loaded
  `_work/F3_volume_delta_plus_price_levels__gbt_reconstructed.joblib` directly: a real fitted
  `sklearn.ensemble.HistGradientBoostingClassifier` (`max_depth=3, learning_rate=0.05, max_iter=200,
  random_state=42`, `classes_=[0,1]`), SHA-256 `dd16ab38...` matches `phase0_manifest.json` exactly.
  `fit_gbt` (imported verbatim from `short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77`)
  does no scaling/imputation and is fit directly on `train_X`/`train_y` — no leakage path from
  dev/test into training. Confirmed the 695-column F3 feature list excludes the target column and
  contains no duplicates. `max_abs_diff=0.0` across all 198,255 dev rows is plausible (not
  suspicious) given `HistGradientBoostingClassifier`'s early-stopping-driven internal validation
  split is itself deterministic under a fixed `random_state`.
- **Phase 1 classification logic reproduces exactly.** Re-ran `phase1_feature_inventory.py` fresh:
  546/695 (78.6%), 430 exact + 116 one-hot-dummy matches (29 categorical bases × 4 suffixes),
  matching `results/f3_feature_inventory_summary.json` byte-for-byte. Checked for one-hot-suffix
  false positives against F0's 149 names: zero collisions. `feature_sets.json` copies used by
  Phase 0 (`short_rth_pure_flip_prediction_enriched`) and Phase 1
  (`short_rth_enriched_volume_level_retrain`) are content-identical for `F3_volume_delta_plus_price_levels`
  (695 entries, same order) — no cross-study drift risk from using two different file paths.
- **Phase 2 backfilled values for `ohlcv_est_delta`/`price_level_context` verified correct against
  tracker source.** `_WINDOWS_S`/`_ROLLING_WINDOWS_MIN` in `registry.py` match `WINDOWS_S`/
  `ROLLING_WINDOWS_MIN` in `ohlcv_delta.py`/`price_levels.py` exactly; `window_unit='since_regime_flip'`/
  `reset_policy='event_start'` for A4 matches `reset_regime()`'s semantics; `window_unit='session'`/
  `reset_policy='session_boundary'` for A5/prior-day/overnight/opening-range/rth_open levels matches
  `reset_rth()`/`end_rth()`/`_on_new_trading_day()` semantics exactly.
- **No positional-argument regression risk.** `FeatureDefinition(` is constructed nowhere else in
  the repo except `features/registry.py` itself, and every call site there uses keyword arguments —
  the three new fields (all with defaults) cannot break any existing call site.
- **Phase 3's core-rule citations check out against actual source.** Verified line-by-line against
  `attach_features.py` (update-loop unconditional `.update()` at line 215, `.calculate()` inline at
  259-260 with per-row ATR at 256-258, regime reset gated on completed-minute close at 227-229,
  `update_1m` fed the just-finalized previous minute's OHLC before overwrite at 241/245) and
  `build_weakness_atlas.py:96-99` (strict `<` checkpoint-to-bar match). The flagged strict-`<` vs
  `<=` discrepancy between `build_weakness_atlas.py` and `attach_features.py`'s re-snap is correctly
  characterized as benign: both independently satisfy `latest_source_ts_used <= observation_ts`
  (strict `<` is simply a tighter special case), neither is a look-ahead bug.
- **`entry_surface.py`'s fill-price/session-classification mechanics** (encountered while tracing
  Phase 3's citations) were not re-litigated here: this module already has its own independent,
  passed audit (`studies/short_rth_entry_surface_backfill/audit/audit.md`) explicitly covering fill
  causality (`fill_i = searchsorted(ts, decision, "left")`, fills at the bar's own **open**, never
  close/high/low) and the `is_rth(decision)` vs `is_rth(fill_ts)` boundary-divergence question, with
  a `rth_boundary_divergence` counter added as a result. No new claim in `feature_timing_causal_spec.md`
  depends on re-verifying that here.
- **`tests/test_coincident_bar_ordering.py` genuinely constructs the coincident case.** Its 1m bar's
  `ts_init = minute_start + 60s`, identical to the last child 1s bar's `ts_init` — a real tie, not
  the existing `fable5_nt_short_rth_policy_a` fixture's minute-open sidestep. (Its *conclusion* is
  the subject of Critical finding 1, but the fixture construction itself is sound and not a
  replication of the old sidestep.)
- **`test_prefix_invariance_calculate_at_T_unaffected_by_bars_after_T` and
  `test_snapshot_immutability_returned_dict_not_mutated_by_later_updates` are genuine, non-tautological
  causal-property tests**, not trivial assertions: the former independently constructs two separate
  tracker instances over different-length data and requires their computed feature dicts to be
  byte-identical; the latter feeds additional bars after taking a snapshot and requires the
  previously-returned dict to be unchanged. Both would fail on a real look-ahead bug.
- A2 (`ts_init_delta`): the coincident-bar fixture's own construction correctly encodes +60s for the
  1m bar and no shift beyond its own 1s close for 1s bars, matching CLAUDE.md invariant 3.
- B10 (multi-timeframe/family duplication): `ohlcv_est_delta` vs the pre-existing `arrival_volume`
  family is explicitly justified as non-duplicative in `registry.py:281-287` (different calculation
  basis — close-position-within-range vs candle-direction ratios), a documented exemption per
  `FEATURE_REGISTRY_CONTRACT.md`.
- C, D, E, F (session/label/train-serve-skew/backtest-config), H (bracket-sim price resolution):
  **N/A** — this study contains no label construction, no train/serve live-scoring code, no backtest
  economics, and no bracket/exit simulation; per its own guardrails, none of that is in scope here
  and none was found.

---

*Audit complete. Findings reflect read-only static analysis plus direct execution of the study's
own pytest suite and one adversarial reproduction (reversed `add_data` call order) outside that
suite. Dynamic bugs in a not-yet-built live `Strategy` are out of scope by construction — this study
precedes that implementation.*

---

# Follow-up Audit — Fix Verification (Second Pass)

**Date:** 2026-07-20
**Result: CRITICAL and all 5 Warnings independently confirmed RESOLVED. 0 CRITICAL, 0 Warning
remaining (2 Notes remain, both honestly still-open by design, not misrepresented as fixed).**

Re-verified independently (re-read current file state, re-ran tests, did not trust the fix summary):

1. **CRITICAL (coincident-ordering calling-convention finding)** — `tests/test_coincident_bar_ordering.py`
   rewritten: `add_bars_causal_order()` helper (1s added before 1m), a test confirming correct order
   under that helper, and `test_add_data_call_order_determines_the_tie_break_not_nt_native` as a
   permanent regression check reproducing the reversed-order flip to `["1m","1s"]`. Re-ran both tests
   together — no hang/crash (the `_LOG_GUARD` module-level sharing fix, mirroring
   `nt_pure_flip_trigger_poc_and_mirrored_long_model/phase2/run_nt.py`'s `run_one(..., log_guard=None)`
   pattern, resolved the exit-127 conflict from two sequential `BacktestEngine` instances with fresh
   log guards each). `SPEC.md`'s Phase 4 section corrected to state the honest finding.
2. **Warning (stale "~90" count)** — `SPEC.md` Phase 2 section now states 502/384/~41 correctly.
3. **Warning (stale Phase 0 prose)** — corrected to the binary `bearish_regime_flip_within_300s`
   target and `scored_dev_2025.parquet`, no more 5-class/checkpoint-pickle language.
4. **Warning (17 `regime_*` features silently verified)** — `phase1_feature_inventory.py` now emits
   `timing_status="TIMING_UNVERIFIED"` for exactly those 17 names; re-ran fresh, confirmed
   `n_timing_unverified: 17` matching the disclosed list exactly.
5. **Warning (snapshot_anchor binding mechanism missing)** — `bind_snapshot_anchor()`/
   `effective_snapshot_anchor()` added to `features/registry.py`, genuinely per-study
   (`(feature_name, study_name)`-keyed, no shared-object mutation), 5 new tests confirm isolation.
6. **Warning (Phase 0 pytest coverage missing)** — `tests/test_phase0_model_artifact.py` added:
   loads the persisted `.joblib` fresh, scores a held-out random sample, compares directly against
   `scored_dev_2025.parquet` (not the manifest's own self-reported numbers).

Full suite re-run: 30/30 in this study plus 10/10 `tests/test_feature_library.py` (no regression
from the `features/registry.py` changes) = 40/40 passed on independent re-execution.

**Safe to treat this study's findings as authoritative for scoping
`nt_live_ml_scoring_population_parity`.**

# NT Live-Scoring Infrastructure Prerequisites

## Status

**SPEC frozen, not yet implemented.** This study exists because scoping
`nt_live_ml_scoring_population_parity` (the user's actual target study —
reproduce the frozen bearish-flip GBT model's scoring LIVE inside a
NautilusTrader `Strategy`, and prove full population/feature/score/
trigger/trade parity against `nt_pure_flip_trigger_poc_and_mirrored_long_model`)
surfaced a blocking infrastructure gap during a dedicated `repo-scout` +
`contract-checker` scout pass, run BEFORE writing that study's SPEC. Per
the user's explicit decision (2026-07-20, via AskUserQuestion): split the
work into this smaller prerequisite study first; only once it lands does
`nt_live_ml_scoring_population_parity` get frozen and executed.

## Decision to inform

Whether the four concrete gaps below can be closed to a point where live,
causally-correct, NT-callback-driven feature computation and model
scoring is actually buildable and auditable — as opposed to discovering
this mid-implementation of the larger study, the way Phase 3 was
descoped in `nt_pure_flip_trigger_poc_and_mirrored_long_model` after the
SPEC had already assumed it was tractable
([[nt_poc_pure_flip_trigger_promising_phase3_descoped]]).

## Scout-pass findings (repo-scout + contract-checker, run in parallel)

1. **CORRECTED (both `repo-scout` and `contract-checker` were substantially
   wrong on this point — checked directly, not trusted).** `features/registry.py`
   actually defines **502** `FeatureDefinition` entries, not ~90.
   Cross-referencing the F3 list
   (`studies/short_rth_enriched_volume_level_retrain/_work/feature_sets.json`,
   695 entries, confirmed a genuine ordered list) against the registry by
   exact name AND by stripping one-hot dummy suffixes
   (`__ABOVE`/`__BELOW`/`__TOUCH`/`__UNAVAILABLE`) back to their
   categorical base name (implemented and run as
   `phase1_feature_inventory.py`, `results/f3_feature_inventory.csv`):
   **546 of 695 F3 features (78.6%) trace to registered,
   `status="verified"` implementations with genuine live NT-callback
   trackers** — `features/trackers/ohlcv_delta.py`'s `OHLCVDeltaTracker`
   (`update(ts_event, open_px, high, low, ...)` — 214/214 volume-delta
   features, 100%) and `features/trackers/price_levels.py`'s
   `PriceLevelTracker` (`update_1m(...)`/`calculate(...)` — 332/332
   price-level features once one-hot dummies are traced to their
   registered categorical base, 100%). Both expose genuine incremental
   `update`/`calculate` methods, not pandas-batch wrappers dressed up as
   trackers — confirmed by reading their signatures directly.
   **The real, concrete, unaddressed gap is F0's 149 "existing" features**
   (regime/median-center slope/alignment, e.g.
   `aligned_price_minus_center_5m`, `slope_5m_1m_aligned_atr`,
   `center_slope_change_5m`) — 0% registered, traced to
   `studies/regime_sequence_chop_context/build_median_centers.py`
   (`build_median_centers_df`/`compute_rolling_slopes`, vectorized pandas
   rolling-window/`.shift(N)` operations on 1s data) with no live NT
   equivalent found anywhere in the repo. **This means "use the
   centralized feature system" is already achievable for 78.6% of F3
   today; the follow-on study's real scope-defining question is whether
   it needs F0's 149 features at all, or whether it can proceed with the
   546 already-live-tracked ones and treat F0 as a separately-scoped
   porting effort.**
2. **The registry's own schema is missing 2 of the 8 per-feature binding
   fields the larger study's brief requires.** `FeatureDefinition`
   (`registry.py:5-24`) has `source_timeframe`, `update_anchor`,
   `snapshot_anchor`, `warmup`, `normalizer`, `null_policy` — 6 of 8. It
   has **no `window_unit` field** (window length is documented only in
   prose in `FEATURE_REGISTRY_CONTRACT.md` §2, never encoded per-instance)
   and **no `reset_policy`/gap-policy field** (also prose-only, never a
   registry key). `FEATURE_REGISTRY_CONTRACT.md:121-123` explicitly
   defers `snapshot_anchor`'s exact timing to "the study-specific
   contract" — i.e. even the fields that DO exist are partially
   aspirational for a consuming study, not self-sufficient.
3. **The offline feature-timing causal contract exists only as an
   implicit, multi-hop pandas import chain**, not as one authoritative
   document. `short_rth_pure_flip_prediction_enriched/phase0_prepare_data.py`
   documents its LABEL contract precisely (lines 1-10: pure arithmetic on
   `confirm_flip_ns` vs `observation_time`) but inherits its FEATURE
   contract from `ohlcv_volume_delta_price_level_features` →
   `short_rth_w4_retrain_entry_strength` →
   `short_rth_entry_surface_backfill`, three studies upstream, with no
   single restated ground truth. A live implementation has nothing
   authoritative to be checked against bar-for-bar without first
   extracting one.
4. **"1s bars process before their coincident 1m bar" is asserted in
   prose, not proven by a targeted test.** `docs/STUDY_METHODOLOGY.md:51-53,204-205`
   states it as the standing invariant (matches CLAUDE.md invariant 4),
   but `docs/BACKTEST_EXECUTION.md`/`docs/DATA_CATALOG.md` don't
   cross-reference it, and the one existing fixture that constructs both
   bar types (`fable5_nt_short_rth_policy_a/tests/test_policy_a_fixture.py:58-67`)
   sidesteps the exact tie by giving its synthetic 1m bar's `ts_init` the
   MINUTE-OPEN time, not the production minute-CLOSE convention
   (`ts_init_delta`) — so no test actually exercises two bars sharing an
   identical `ts_init` and asserts NT's tie-break order. This is an
   unverified structural assumption load-bearing for every NT study in
   this repo, not just the new one.
5. **No precedent exists anywhere for live model scoring inside an NT
   `Strategy`** (re-confirmed, consistent with
   `nt_pure_flip_trigger_poc_and_mirrored_long_model/SPEC.md` finding 1):
   `grep predict_proba` across every `studies/**/strategy.py` returns zero
   matches.
6. **The fitted F3+GBT model is NOT actually persisted — a scout-agent
   claim to the contrary was checked and found wrong.** A checkpoint
   pickle does exist at
   `studies/short_rth_enriched_volume_level_retrain/_work/checkpoints/F3_volume_delta_plus_price_levels__gbt.pkl`,
   but directly loading it and inspecting its keys
   (`pickle.loads(...).keys()`) shows it contains only
   `{row, calib_frames, importance_rows, cutoffs, score_train, score_dev,
   score_test}` — never the fitted `HistGradientBoostingClassifier`
   object itself. Tracing `train_and_evaluate.py:103-170`
   (`compute_combo`) confirms the `model` variable is used locally
   (`.predict_proba`, `.coef_`, `permutation_importance`) and never
   included in the returned `result` dict that gets pickled
   (`train_and_evaluate.py:166-170,206`). **This confirms, rather than
   overturns, the original POC study's finding**: hyperparameters are
   known (`HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
   max_iter=200, random_state=42)`, scored via `.predict_proba(...)[:, 1]`
   on a 5-class target), but there is no saved model artifact to load and
   hash. Phase 0 below is therefore the ORIGINAL brief's stated fallback
   (reconstruct once, confirm it reproduces stored reference scores
   within tolerance, persist that reconstruction as the frozen artifact),
   not a lighter-weight verification-only pass.

## Guardrails carried over from the larger study's brief

No NT `Strategy` scoring code is written in this study — that remains
entirely the follow-on study's Phase 2/5. This study produces the
contract, the inventory, and the proofs the follow-on study needs; it
does not port all 695 features to live trackers (a much larger,
separately-scoped effort once the inventory below shows its true size).
Mandatory `lookahead-auditor` pass, 0 CRITICAL required, before this
study's findings are treated as authoritative.

## Phase 0 — Model reconstruction and persistence (closes finding 6)

**Corrected during the completion-gate audit** (this section originally
described the WRONG, superseded model — leftover prose from before finding
6 was corrected; the actual implementation was always right, only this
description was stale): since no fitted model object exists anywhere on
disk (finding 6), refit `HistGradientBoostingClassifier(max_depth=3,
learning_rate=0.05, max_iter=200, random_state=42)` on
`short_rth_pure_flip_prediction_enriched/_work/train_2021_2024_prepared.parquet`
(F3's 695-column ordered feature list, binary target
`bearish_regime_flip_within_300s` — NOT the superseded 5-class
`outcome_class`), using the exact `fit_gbt` call path imported verbatim
from `short_rth_enriched_volume_level_retrain/train_and_evaluate.py:73-77`,
`.predict_proba(dev_X)[:, 1]` on `prepared_2025.parquet`, and confirm the
reconstructed scores match the stored
`score_F3_volume_delta_plus_price_levels__gbt_raw` column in that same
study's `_work/scored_dev_2025.parquet` (NOT a checkpoint pickle — no such
pickle contains this model, per finding 6) within machine-precision
tolerance. Only once that reproduction is confirmed, persist the fitted
model object itself (via `joblib.dump`, a genuinely new artifact this
study adds) and record its SHA-256, the reconstruction script's SHA-256,
sklearn/library versions actually used, and the reproduction tolerance
achieved. Treat failure to reproduce stored scores as a blocking finding
per the original brief's own stated rule — do not proceed to Phase 1 on
an unverified reconstruction. (Result: `max_abs_diff=0.0` across all
198,255 dev rows — see `results/phase0_manifest.json`.)

## Phase 1 — F3 feature inventory and registry-gap triage

Produce `results/f3_feature_inventory.csv`: one row per F3 feature with
`name, in_registry (bool), family, source_script, source_function,
timeframe, window_length, window_unit, update_anchor (best available),
reset_policy (best available), null_policy (best available),
live_tracker_exists (bool)`. This is a factual map, not a porting effort —
for any feature judged infeasible to trace to a single source function
within a bounded search, record `source_script=UNRESOLVED` rather than
guessing. Report the exact count of features with `live_tracker_exists=True`
vs `False` — this number directly determines the real size of the
follow-on study's Phase 2.

## Phase 2 — Registry schema extension

Added `window: Optional[float]`, `window_unit: Optional[str]`, and
`reset_policy: str = "none"` fields to `FeatureDefinition` in
`features/registry.py`. **Corrected during the completion-gate audit**:
this paragraph originally said "backfills existing ~90 verified entries,"
a number never reconciled with finding 1's own correction (502 total
entries, not ~90) earlier in this same document. The actual, precise
backfill covers the two programmatically-generated families that matter
for F3 — `ohlcv_est_delta` (214 entries) and `price_level_context` (247
entries, covering all 332 F3 price-level features once one-hot dummies
are traced to their registered categorical base) — 384 of 502 total
registry entries, threading real values through from the existing
`_WINDOWS_S`/`_ROLLING_WINDOWS_MIN` loop variables rather than inferring
from name-parsing. The ~90 (in fact ~41) pre-existing hand-written
entries (`arrival_velocity`, `arrival_volume`, `pullback_1s`,
`pullback_1m`, `context` families — none of which are part of F3) are
deliberately left at the additive dataclass defaults (`window=None,
window_unit=None, reset_policy="none"`) rather than backfilled, since
they are out of this study's scope; `tests/test_registry_schema_extension.py::test_pre_existing_entries_unaffected`
confirms this is deliberate, not an oversight.

A codified (not narrative-only) mechanism for a consuming study to
declare its `snapshot_anchor` binding, per
`FEATURE_REGISTRY_CONTRACT.md:121-123`'s existing deferral, was
originally required here but **not delivered** — flagged by the
completion-gate audit as a silently-dropped deliverable. See
`features/registry.py`'s `bind_snapshot_anchor()` (added post-audit) for
the actual implementation: a per-study override table keyed by
`(feature_name, study_name)` with a lookup helper
`effective_snapshot_anchor(name, study_name)`, closing this gap.

## Phase 3 — Authoritative feature-timing causal spec

Extract, from the actual pandas code across the 4-hop chain (`entry_surface.py`
→ `attach_features.py` → `ohlcv_volume_delta_price_level_features` →
`short_rth_pure_flip_prediction_enriched`), ONE markdown document stating
precisely: at `observation_time` T, which bars (by index/timestamp) are
available to each feature family, whether any feature ever reads a bar
with `ts_init > T`, and the exact snapshot-vs-update timing convention.
Verify this document's claims against the actual code with a handful of
targeted hand-computed checks (not full re-derivation) — this is a
documentation-extraction-and-verification task, not new feature logic.
Any feature family whose timing cannot be confirmed causal within this
phase is flagged as `TIMING_UNVERIFIED` in the Phase 1 inventory, not
silently assumed correct.

## Phase 4 — Coincident 1s/1m callback-ordering proof

Write a minimal `BacktestEngine` fixture (new, in `tests/`) that feeds a
1s bar and its parent 1m bar sharing the SAME `ts_init` (the production
minute-close convention, not the existing fixture's minute-open
convention) and asserts, via a strategy that logs callback-arrival order,
that the 1s bar's `on_bar` fires before the 1m bar's `on_bar`.

**CRITICAL finding, corrected post-audit**: the first version of this
phase claimed this converts CLAUDE.md invariant 4 into an NT-native
proof. It does not. The completion-gate audit reproduced directly that
reversing the fixture's two `engine.add_data()` calls (1m added before
1s) flips the observed coincident-timestamp arrival order to `["1m",
"1s"]` — `BacktestEngine.add_data(sort=True)` stably re-sorts the whole
accumulated stream by `ts_init`, and ties are broken purely by which
stream was appended first, not by any bar-type-aware priority inside NT
itself. The corrected, honest finding is: **"1s before 1m" is a calling-
convention requirement every NT study loading both timeframes must
follow — it is NOT automatically guaranteed by NT.**
`tests/test_coincident_bar_ordering.py` now: (a) provides
`add_bars_causal_order()`, a reusable helper future NT studies should
call instead of raw `engine.add_data()`, (b) asserts the correct order
under that helper, and (c) makes the reversed-order failure mode itself a
permanent regression test
(`test_add_data_call_order_determines_the_tie_break_not_nt_native`), so
this finding cannot be silently forgotten. This is the single most
important finding of this whole prerequisite study for the follow-on
`nt_live_ml_scoring_population_parity` study: whoever writes that
study's `run_nt.py` MUST use `add_bars_causal_order()` or replicate its
exact call order.

## Required pytest coverage

```text
model artifact load + rescoring tolerance (Phase 0)
registry schema migration backfill correctness (Phase 2)
FeatureDefinition new-field defaults / validation (Phase 2)
coincident-timestamp callback ordering (Phase 4)
```

Full-year or full-month NT runs are out of scope for this study; no
economics are computed here.

## Guardrails

Mandatory `lookahead-auditor` pass before this study's findings are
treated as authoritative for scoping `nt_live_ml_scoring_population_parity`.
No NT `Strategy` order-submission code is written in this study.

## Final decision vocabulary

- `INFRA_PREREQS_READY_FOR_LIVE_SCORING_STUDY` — all 4 phases land clean;
  the follow-on study can be scoped and frozen as originally briefed
  (with its true feature-porting size now known from Phase 1's
  inventory).
- `INFRA_PREREQS_READY_WITH_REDUCED_SCOPE` — phases land, but Phase 1's
  inventory shows most of the 695 features have no live tracker and
  would need individual porting; recommend the follow-on study be scoped
  to a feature-family subset rather than the full 695.
- `INFRA_PREREQS_BLOCKED` — one or more phases surfaces a finding that
  prevents live NT scoring from being causally trustworthy at all (e.g.
  the coincident-ordering proof fails, or the timing spec can't be
  verified for a load-bearing feature family).

# NT Live-Scoring Infrastructure Prerequisites — Report

## Decision

**`INFRA_PREREQS_READY_WITH_REDUCED_SCOPE`** — see
`results/final_decision.json` for the full structured record.

This study exists because scoping the user's actual target,
`nt_live_ml_scoring_population_parity` (reproduce a frozen bearish-flip
GBT model's scoring LIVE inside NT, prove full population/feature/score/
trigger/trade parity against `nt_pure_flip_trigger_poc_and_mirrored_long_model`),
surfaced infrastructure gaps during a dedicated scout pass run BEFORE
writing that study's SPEC. The user chose (2026-07-20) to close those
gaps as their own prerequisite study first.

## Summary of the four phases

### Phase 0 — Model reconstruction and persistence

No fitted model object existed anywhere on disk for the frozen bearish-
flip GBT model (a scout-agent claim to the contrary was checked directly
by loading the referenced pickle and inspecting its keys — found wrong;
it belonged to a different, superseded 5-class study). Refit
`HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
max_iter=200, random_state=42)` on the exact frozen training population
and confirmed **byte-identical reproduction** of the stored
`score_F3_volume_delta_plus_price_levels__gbt_raw` column
(`max_abs_diff=0.0` across all 198,255 dev rows). Persisted the fitted
model via `joblib` — a genuinely new artifact — with SHA-256 recorded.

### Phase 1 — F3 feature inventory and registry-gap triage

Both prior scout-agent passes (`repo-scout` and `contract-checker`)
claimed the F3 695-feature list was "almost entirely not in the central
registry" (~90 total registry entries). Checked directly and found
**substantially wrong**: `features/registry.py` has 502 entries, and
**546 of 695 F3 features (78.6%) trace to registered, verified
implementations with genuine live NT-callback trackers**
(`OHLCVDeltaTracker`, `PriceLevelTracker` — both expose incremental
`update`/`calculate` methods, not pandas-batch wrappers). The real,
concrete, unaddressed gap is **F0's 149 "existing" features**
(regime/median-center slope/alignment) — 0% registered, tracing to
pure pandas-batch code in `regime_sequence_chop_context/build_median_centers.py`
with no live equivalent anywhere in the repo.

### Phase 2 — Registry schema extension

Added `window`, `window_unit`, `reset_policy` fields to `FeatureDefinition`
in `features/registry.py`, precisely backfilled for the two F3-relevant
families (384 of 502 entries) by threading the existing loop variables
(`_WINDOWS_S`, `_ROLLING_WINDOWS_MIN`) through rather than guessing. Also
added `bind_snapshot_anchor()`/`effective_snapshot_anchor()`, a codified
per-study mechanism for declaring when a feature is snapped, closing
`FEATURE_REGISTRY_CONTRACT.md`'s existing narrative-only deferral. No
regression risk: all existing `FeatureDefinition` call sites use keyword
arguments, and `tests/test_feature_library.py` (10 tests, pre-existing)
still passes unchanged.

### Phase 3 — Authoritative feature-timing causal spec

Extracted one document (`results/feature_timing_causal_spec.md`) stating
the causal contract across the 4-hop chain `entry_surface.py` →
`attach_features.py` → the two live trackers, verified against actual
code with file:line citations and 4 empirical pytest checks (prefix
invariance, snapshot immutability, warmup unavailability, regime-reset
causality). Found and documented one benign discrepancy (strict `<` vs
`<=` in checkpoint-to-bar matching between two scripts) and flagged 17
regime-relative features as `TIMING_UNVERIFIED` in the Phase 1 inventory,
since their upstream `regime_starts` construction wasn't re-traced to the
same depth as everything else in this study.

### Phase 4 — Coincident 1s/1m callback-ordering proof

**This is the single most important finding of the whole study.** The
first version of this phase claimed to convert CLAUDE.md invariant 4
("1s bars process before their coincident 1m bar") into a proven,
NT-native invariant. A completion-gate audit found this claim
**materially wrong**: reversing the test fixture's two
`engine.add_data()` calls flips the observed coincident-timestamp arrival
order. `BacktestEngine.add_data(sort=True)` stably re-sorts the whole
accumulated stream by `ts_init`; ties are broken purely by which stream
was appended first — a **calling-convention requirement**, not a
bar-type-aware guarantee inside NT itself. Corrected the finding, added
`add_bars_causal_order()` (a reusable helper: always add 1s before 1m),
and converted the reversed-order failure mode into a permanent regression
test (`test_add_data_call_order_determines_the_tie_break_not_nt_native`)
so this can't be silently forgotten. **Any future NT study loading both
1s and 1m data — including the follow-on `nt_live_ml_scoring_population_parity`
study — must use this helper or replicate its exact call order**, or it
will silently reintroduce the MFE/MAE blind spot CLAUDE.md invariant 4
exists to prevent, with nothing to catch it.

## Completion-gate audit

Two audit passes: (1) initial completion-gate audit found **1 CRITICAL**
(the coincident-ordering false claim above) plus 5 Warnings (stale SPEC
prose in two places, the 17 unflagged `TIMING_UNVERIFIED` features, the
dropped `snapshot_anchor` binding mechanism, missing Phase 0 pytest
coverage) and 4 Notes; (2) a follow-up fix-verification pass independently
confirmed all 6 fixed, **0 CRITICAL, 0 Warning remaining** (2 Notes left
open by design, honestly reported rather than force-closed). Full test
suite: 30/30 in this study, 10/10 pre-existing `test_feature_library.py`
(no regression).

## Recommendation for the follow-on study

Scope `nt_live_ml_scoring_population_parity` to the **546 F3 features
already backed by live NT-callback trackers** (`ohlcv_est_delta` +
`price_level_context` families), explicitly excluding F0's 149
regime-slope-alignment features — porting those would be a separate,
from-scratch effort. Use `add_bars_causal_order()` (or replicate its
exact call order) for any multi-timeframe NT run in that study. Treat the
17 `TIMING_UNVERIFIED` regime-relative features as a known, disclosed
residual risk rather than a blocker — their causal reasoning is sound
(reset on completed-minute close, reusing the already-live-validated
`RegimeEngine` precedent) even though not independently re-traced to the
same depth as the rest of this study's findings.

## Key lesson for process

Two different sub-agent scout passes (`repo-scout`, `contract-checker`)
both independently produced materially wrong claims this session (the
"~90 total registry entries"/"almost none of F3 registered" claim, and
the "model IS persisted" claim) — both caught only because each was
checked directly against the actual code/data rather than trusted. This
reinforces the standing project discipline: sub-agent research findings
are leads to verify, not facts to build on.

# Study Report: OHLCV Volume/Delta + Price-Level Context Features

**Study directory:** `studies/ohlcv_volume_delta_price_level_features/`
**Final decision: `ACCEPT_FEATURE_FOUNDATION`**

## 1. How many volume/delta features were added?

**214** features, family `ohlcv_est_delta`, in `features/trackers/ohlcv_delta.py`
(`OHLCVDeltaTracker`). Covers bar-level estimated delta/bull-bear volume split
(A1), rolling windows from 5s to 1800s including full/partial-availability
flags (A2), cross-window ratios (A3), regime-relative cumulative and
first-half/second-half split (A4), and RTH-cumulative (A5).

## 2. How many price-level features were added?

**247** features, family `price_level_context`, in
`features/trackers/price_levels.py` (`PriceLevelTracker`). Covers prior-day
H/L/C and opening-range levels, raw and clustered above/below touch counts
and `level_balance`, nearest-level-above/below distance (points and ATR-
normalized), percent-of-levels-available proximity features, and direction-
normalized (long/short) transforms of the above. Includes the Addendum's
specific worked example (8 levels, 5 below/3 above → `level_balance = 0.25`),
verified in `tests/test_price_levels.py::test_raw_above_below_touch_counts_addendum_example`.

**Total: 461 new feature columns**, both families registered with
`status='provisional'` in `features/registry.py`.

## 3. Were they added to the shared feature library/registry?

Yes. Both trackers live in `features/trackers/`, both are registered in
`features/registry.py` via `FeatureDefinition` entries (461 total), and both
are wired into `features/engine.py`'s `FeatureEngine` (`update_1s`/`update_1m`)
so the same code path serves live trading and offline study replay — no
duplicate implementation exists inside the study directory, per the
feature-registry contract's two-layer design (library = HOW, study SPEC =
WHEN).

`FeatureEngine.update_1m` buffers each forming minute's 1-second bars
(`_minute_1s_buffer`) and only commits them to regime/RTH-conditional
cumulative state (`accumulate_regime_rth`) after the minute's parent 1m bar
confirms the regime/RTH context — the same buffered-retroactive-replay
pattern this project already uses for MFE/MAE, applied here to avoid
attributing 1-second bars to the wrong regime or RTH window.

## 4. Did deterministic tests pass?

Yes. **41 passed, 0 failed** across:
- `tests/test_feature_library.py` (repo-level, includes the new
  `FeatureEngine` buffer-and-replay regression test)
- `studies/.../tests/test_ohlcv_delta.py` (12 tests)
- `studies/.../tests/test_price_levels.py` (17 tests, including all 9 of the
  Addendum's required test types: raw above/below counts, clustered
  above/below counts, nearest-cluster distance, percent-of-levels-available,
  `level_balance`, unavailable-denominator handling, no-zero-fill-for-
  unavailable, and direction-normalization for both short and long)
- `studies/.../tests/test_attach_features.py` (4 tests, including the
  cross-pipeline offline-vs-live regime-transition parity test that caught
  CRIT-5)

Independently re-confirmed by the auditor in its third pass
(`audit/audit.md`, "Item 6").

## 5. Did runtime validation pass?

Yes, at two scales:
- **5-day smoke** (2025-01-06 to 2025-01-11, 2,248 rows):
  `row_count_unchanged=True`, `labels_unchanged=True`, 0 duplicates, 0
  provenance violations, all 461 feature columns present, 29 checkpoints
  gap-snapped to the nearest actual traded second (documented, not a defect).
- **Full 6-year production attachment** (2021-2026, run solo/foreground to
  avoid the earlier background-concurrency issue): all 6 years show
  `row_count_unchanged=True`, `labels_unchanged=True`, 0 duplicate rows, 0
  provenance violations, 100% join rate, all 461 feature columns present.

| year | surface rows | feature rows | gap-snapped checkpoints |
|------|--------------|--------------|--------------------------|
| 2021 | 212,241 | 212,241 | 11,119 |
| 2022 | 192,378 | 192,378 | 3,855 |
| 2023 | 204,742 | 204,742 | 6,058 |
| 2024 | 204,611 | 204,611 | 7,000 |
| 2025 | 198,255 | 198,255 | 8,396 |
| 2026 | 63,021 | 63,021 | 2,079 |
| **total** | **1,075,248** | **1,075,248** | 38,507 |

`results/feature_nan_rates.csv` / `feature_availability_by_year.csv` show
only expected, causally-explainable unavailability (e.g. opening-range
"final" features unavailable in the first 30 minutes of RTH each day;
nearest-cluster-above/below occasionally unavailable when no level exists on
one side) — no feature shows an anomalous NaN rate suggesting a bug.

## 6. Did the independent audit find any critical issues?

Yes, across the process — **0 remain**. Three audit passes:
1. **FAIL** — 4 CRITICAL (minute-bucket off-by-one, regime/RTH granularity
   mismatch, opening-range off-by-one, smoke-window padding), 3 WARNING, 3
   NOTE. All 4 CRITICAL fixed.
2. **FAIL** — 1 new CRITICAL (CRIT-5: offline replay and the newly-fixed live
   `FeatureEngine` disagreed on which minute's 1-second bars belong to a
   regime/RTH transition). Fixed by resolving transitions at minute-
   completion granularity in `attach_features.py`, verified by a dedicated
   cross-pipeline parity test.
3. **PASS** — 0 CRITICAL. 2 new WARNING (WARN-4: pre-loop-init anchor price
   used the wrong tick; WARN-5: trailing forming-minute at the end of a
   replay window was never flushed) and 1 new NOTE, both WARNINGs confirmed
   dormant for every artifact produced but fixed anyway (backward-scan for
   WARN-4, post-loop flush for WARN-5) before the full 6-year run.

An above/below touch-count swap bug (found via the user's Addendum, not the
audit) was also fixed, with a pre-existing test that had encoded the wrong
expectation corrected alongside it.

## 7. Did feature joining preserve all rows and labels?

Yes, for all 6 years, at both the 5-day-smoke and full-production scale
(table above). `build_join_reports.py`'s row-count-unchanged and labels-
unchanged checks were computed after windowing (not before), avoiding the
earlier baseline-comparison bug.

## 8. Primary remaining caveats

- **Mid-minute lag (self-identified, non-blocking):** because regime/RTH
  transitions are only resolved at minute-completion, a feature value at a
  checkpoint mid-way through a still-forming minute reflects state as of the
  *previous* confirmed minute close, not the current partial minute. This is
  inherent to the causal design (no look-ahead into an unconfirmed minute),
  not a defect.
- **WARN-1 resolution asymmetry:** `ohlcv_delta.py`'s rolling windows use a
  time-span-only availability check (not exact bar count), because an exact-
  count check made ~99% of 1800s windows falsely "unavailable" during normal
  RTH single-second gaps; `price_levels.py` keeps the stricter exact-count
  check since its 1-minute-bar gaps are a more meaningful signal. This is a
  deliberate, evidence-based asymmetry, documented in
  `validation/feature_validation.md`, not an inconsistency to fix.
  See [[ohlcv_delta_availability_check_asymmetry]].
- **Gap-snapped checkpoints (~3.6% of rows, 38,507 of 1,075,248):** the
  atlas's theoretical 5-second observation grid does not always land on an
  actually-traded second; these checkpoints are snapped to the nearest prior
  traded bar (`searchsorted(..., side="right") - 1`), which is a pre-existing
  data-gap characteristic of the underlying tick data, not introduced by this
  study.
- No economic or predictive-value claim is made for any of the 461 features
  — that is explicitly out of scope for this study (guardrails).

## 9. Next bounded study to test information content

A bounded, model-free information-content probe: compute per-feature
univariate separation (e.g. AUC vs. the existing `stop_survival_score`/
`hit_pre_alignment_stop` labels, and Cohen's d by outcome bucket) for the 461
new features against the short-RTH surface, gated by the project's standing
rule that high AUC does not imply PnL discrimination
([[rl_expanded_dynamic_closed]], [[bar4_knn_calibrated_wrong_dimensions]]).
This should remain diagnostic-only (no model training, no threshold
optimization, no economic conclusion) and explicitly flag any feature worth
carrying into a future modeling study versus one that is measurable but
inert, consistent with this project's established pattern of separating
signal detection from monetization claims.

## Final decision: `ACCEPT_FEATURE_FOUNDATION`

All acceptance criteria are met: deterministic tests pass (41/41);
runtime validation passes at both 5-day and full 6-year scale; the
independent audit ends at 0 CRITICAL; row counts and labels are preserved
exactly at every join; the feature schema documents all 461 new columns; no
unavailable numeric feature is zero-filled; source-timestamp provenance is
recorded and verified (0 violations); and both feature families are fully
integrated into the shared feature library (registry + `FeatureEngine`).
Recommend promoting both families from `status='provisional'` to
`status='verified'` in `features/registry.py`.

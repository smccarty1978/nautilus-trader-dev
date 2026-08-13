# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-09
**Scope:** `implementation/arming.py`, `implementation/walks.py`,
`implementation/build_paths.py`, `implementation/validate.py`,
`analysis/diagnostics.py` (pre-execution — no results exist yet)
**Scope hash:** `1a29308eafb4674c386cfe04fbe0475dd83bb3b93fc624952236c4aa1eda0bd5`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 11 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 1
- Note: 2

## Critical findings
None.

## Warnings

### [C2/A3] `arming.py:86-98` — `arm_population`'s from-below test cannot distinguish "no prior observation" from "prior observation did not qualify"
`prev_q=pl.col("q").shift(1, fill_value=False).over("regime_id")` fills the
first in-domain row of every regime's group with `False`. For the overwhelming
majority of regimes this is correct, because `bullish_in_domain`/
`bearish_in_domain` (established_regime_gate) fires around ~120s into a regime
(per `regime_complete_canonical_store` docs), leaving several minutes of true
in-domain dispatches before the 600s arm-age boundary. But if a regime's
*very first* in-domain dispatch is itself post-600s and already qualifies
(no earlier in-domain row exists at all — e.g. an unusually late
`established_regime_gate` fire coinciding with an already-elevated score),
`fill_value=False` silently treats the absent predecessor as "did not
qualify," and the row is accepted as a genuine from-below arm with zero
supporting evidence.
**Why this isn't caught downstream:** gate 1 (`validate.py:55-102`) only
reconciles regimes *excluded* from `arm_ids` (the `only_fq - arm_ids` delta);
a regime that stays in both `fq_ids` and `arm_ids` never surfaces there. Gate
3's own "from-below" check (`validate.py:154-163`) recomputes `prev_q` with
the identical `shift(1, fill_value=False)` expression over the identical
table used inside `arm_population`, so it is definitionally unable to
disagree — it verifies that the code agrees with itself, not that the claim
is true.
**Failure path:** a regime whose first in-domain dispatch is post-600s and
already ≥ Top-10 is counted as `arm_population`'s "first true crossing from
below," inflating the armed population and the score-path-shape/persistence
statistics attached to it with at least one row that never demonstrated a
crossing.
**Smallest fix:** either (a) require a non-null `prev_q` (drop
`fill_value=False`, treat first-observation-qualifies as unarmed, matching
the SPEC's literal "the immediately preceding in-domain dispatch ... did NOT
qualify" — vacuously false, not vacuously true, when no predecessor exists),
or (b) add a genuinely independent check in gate 3/gate 1 counting regimes
whose arm row is also each regime's first-ever in-domain row, and confirming
that count is 0 or is the SPEC's documented delta term.

## Notes

- **`arming.py`/`build_paths.py` — dormant cross-year partition risk.**
  `build(years=...)` and `arm_population`/`post_arm_scores` accept a `years`
  filter, but `load_scored(years)` drops out-of-window rows *before* the
  `shift(1).over("regime_id")` from-below test runs. A regime straddling a
  year boundary, run with a partial-years filter, would have its true
  predecessor dispatch silently excluded and `fill_value=False` would
  misrepresent it as "did not qualify" — the same partition-local-checks
  failure mode as `partition_local_checks_miss_cross_partition_defects.md`.
  Currently inert: the only call site is `build_paths.py:311`, which invokes
  `build()` with no `years` argument (full 2021-2025 population), and no
  runner in this study partitions by year. Flag before this parameter is ever
  exercised.
- **`walks.py` window-floor fix (`max(..., start + 1)`), `line 161-163`, verified correct.**
  The floor cannot extend past the session boundary because it is only one
  argument of the surrounding `min(..., session_end, market.n)` — confirmed
  by tracing both the "confirm stamped at entry second" case and the
  "confirm falls in next session" case; both clamp to `session_end` as
  intended.

## Referred to contract-checker
- `validate.py` gate 3's from-below re-check is the same computation as
  `arm_population`'s own filter (test-design/validation-quality, not a
  causality defect in the measured logic itself).
- `validate.py` gate 6 independently recomputes MAE arithmetic from raw
  `canonical_regime_paths_all.parquet` (a genuinely separate code path for
  the excursion math and correctly reuses the entry-exclusive `side="right"`
  convention), but derives its window's *far* boundary (`confirm_ns`) from
  `walk_b_seconds_to_confirm`, an output of the pipeline under test, rather
  than re-deriving the confirming flip via an independent `RegimeIndex`
  lookup — narrows what the gate can catch (test-quality/validation scope).

## Clean checks
- A1, A3 verified: `MarketData.ts`/`day_close_ns` reused unmodified from
  accepted `engine.py`; all indexing in scope uses `market.ts`
  (`path_init_ns`, close-time), never `ts_event`.
- B2, B4 verified: no `.shift(-N)`, no negative lag; `classify_shape` /
  `reexpansion_index` peak/drawdown use `np.maximum.accumulate` (expanding,
  not whole-window) bounded by `upto` = the Walk A terminal event's own
  dispatch index (`build_paths.py:150-151`).
- C1-C3 verified: `arm_population`'s `shift(1).over("regime_id")` only spans
  rows within one `regime_id`, which per `regime_complete_canonical_store`
  DECISIONS.md is single-direction by construction
  (`bullish_in_domain = direction==1 and established`), so the "from below"
  test can never mix bullish/bearish dispatches within one regime.
- F2, G2 verified: `_session_bounds`/`session_end` correctly clamp every
  window (`measure_to_confirm`, `continuation_label`, `build_paths.py` level
  reach gate) to the arm's own RTH session; traced both the "confirm exists
  but past session close" and "no bar exactly at session close" cases.
- H1, H2, H4 verified: `_excursions` uses bar high/low (not close);
  granularity is the 1s canonical path throughout; `_exit_price` fills a
  stop at the *following* bar's open (falling back to the session's last
  close only when no next bar exists in-session), never the trigger price.
- Same-bar stop/confirm tie (§5.3) verified resolved adversely:
  `confirm_censored` requires strict `confirm_idx < stop_idx`; the optimistic
  variant uses `<=` and is reported alongside per SPEC.
- `inclusive=True` semantics (`RegimeIndex.next_start_after`, reused
  unmodified from accepted `engine.py`) verified unchanged from the accepted
  upstream implementation; not re-audited per task scope.

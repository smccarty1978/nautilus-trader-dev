# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-13
**Scope:** `implementation/population.py`, `implementation/outcomes.py`,
`implementation/validate.py`, `implementation/analysis.py`, `implementation/contract.py`
(read for context only), `run_study.py`, `tests/test_diagnostic_contracts.py`.
Provenance-only (imported unmodified): `armed_fade_score_path_progression/implementation/{arming,walks}.py`,
`top10_fast_confirm_runner_path/implementation/engine.py`,
`model_driven_entry_exit_discovery/implementation/{engine,candidates}.py`.
**Scope hash:** `b4c0210dc53b2212ee6b26201d3e7ce6de1e17fb9388eae90066e8628486d1a7`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (9 files scanned)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 1
- Note: 2

## Critical findings

### [validate.py:213] `classify()` silently mislabels an unclassified verdict as `D5_NOTHING_CHANGES`
`primary_verdict = fired[0] if fired else "D5_NOTHING_CHANGES"` (validate.py:213). D5 is
only supposed to fire when `d_flip <= 0.02 and d_conf <= 0.02 and d_mfe_ab <= 0.15`
(lines 208-209) — its own condition is evaluated separately at 198-209 and appended to
`fired` only when true. But the fallback on line 213 assigns the `D5_NOTHING_CHANGES`
*label* whenever `fired` is empty, regardless of whether the D5 condition itself was
ever true.

**Failure path:** the D1-D3 age-contrast conditions are not logically exhaustive (SPEC
§7's table has gaps, e.g. "old bucket has both a higher flip rate by ≥25% AND a bigger
`median_eventual_mfe` by ≥0.25 ATR" fires neither D2 — whose "does not exceed" clause
requires `d_mfe > -0.25`, which is false here — nor D3, whose "young exceeds old" clause
is also false). If, in the same run, D4's velocity monotonicity also fails to hold and
A/B disagree beyond D5's own 2pp/2pp/0.15-ATR tolerance, `fired` is `[]` and
`primary_verdict` is written to `results/summary.json` as `"D5_NOTHING_CHANGES"` even
though the age contrast shows a real, sizeable divergence and A/B do not agree. This is
the study's single main deliverable (§6 #13, "the answered final question") reporting a
verdict its own stated condition contradicts — a wrong number in the headline output,
not a hypothetical.

**Smallest fix:** replace the fallback with an explicit `"D0_UNCLASSIFIED"` (or similar)
terminal label distinct from `D5_NOTHING_CHANGES`, so an empty `fired` list is visible as
its own outcome rather than silently aliased to D5's specific claim.

## Warnings

### [population.py:48-78] `arm_population(scored, min_age_s)` re-derives the crossing logic rather than calling the accepted function, and drops its full-population guard
SPEC §2.3 states `arm_population` is "reused verbatim ... with `MIN_REGIME_AGE_S` as an
argument — no re-derived crossing logic." In fact `population.py:48-78` is a
copy-pasted reimplementation of `arming.py:128-161`'s filter body (byte-identical
predicate logic, parameterized on `min_age_s`), not a call into the accepted
`arming.arm_population`. Two consequences:
1. The claim in the frozen SPEC is inaccurate — this is provenance-adjacent territory,
   noted here because it directly affects whether "no re-derived crossing logic" (the
   safety property the audit plan relies on) actually holds.
2. The accepted version's `_assert_arming_population_is_complete` guard (arming.py:107-125),
   which aborts if a partial-year slice is passed, is **not present** in the
   reimplementation. Currently harmless: the only call site (`build_populations`,
   population.py:167-169) always passes the full, unfiltered `load_observations()`
   frame, so no partial slice ever reaches it today. But there is no code-level
   enforcement against a future caller doing so — exactly the class of defect
   (`partition_local_checks_miss_cross_partition_defects`) the accepted module's
   assertion exists to prevent.
**Not CRITICAL**: no call path currently violates full-population arming; this is an
enforced-in-practice-but-not-in-code gap. Confirmed via `tests/test_diagnostic_contracts.py`
that both `min_age_s=0` and `min_age_s=600` reproduce the accepted from-below /
predecessor-exists / one-arm-per-regime semantics exactly.
**Smallest fix:** call `_assert_arming_population_is_complete(scored)` at the top of the
new `arm_population`, or better, have it delegate to `arming.arm_population` with the age
threshold as a parameter instead of duplicating the filter body.

## Notes

- `contract.py:63` computes `age_min` from a `regime_age_seconds` column while every
  other module in this study (population.py, outcomes.py) reads age from
  `seconds_from_regime_start`. If these two columns are not identical, Phase 0's
  contract row would fail loudly (`ABORT`) rather than silently mis-verify — low risk,
  and Phase-0 contract-table correctness is adjacent to contract-checker's C4 scope, but
  flagged here since it touches an age semantic this audit was asked to trace.
- `analysis.py:7-14`'s module docstring groups `p_flip_le_*` under the "over ALL arms"
  denominator alongside `p_confirmed`/`p_stopped`, but the actual `_p()`/`.mean()`
  behavior (correctly, per SPEC §4.1) excludes the ~54 right-censored
  (`sealed_boundary_censored`) regimes via null-skipping, and this is disclosed via
  `n_flip_censored` in `outcome1_table`. The code and disclosure are correct; only the
  summary comment is imprecise. No effect on any reported number.

## Referred to contract-checker
- `validate.py:212` / SPEC §6.2: whether the D1-D5 taxonomy (as written) is logically
  exhaustive over the age-contrast/velocity/AB-comparison inputs is a reachability
  question for the terminal-label set, separate from the CRITICAL above.

## Clean checks
- A1-A5, B1-B10, C1-C3: verified clean in the new surface — no `ts_event` misuse, no
  `center=True`/`.shift(-N)`/`bfill`, all buckets closed-left/open-right, no train/test
  randomization (temporal store only, 2026 structurally absent from source parquets,
  confirmed 2021-2025 only).
- F1-F4: session handling reused from already-audited `MarketData`/RTH conventions;
  new `secs_to_session_close` / `flip_window_crosses_session_close` columns are
  disclosure-only, never a filter on the primary Outcome-1 rate (verified in
  `analysis.py` AGGS and `primary_matrix`).
- G1-G4: no resampling in this study; reads accepted canonical store only.
- H1-H4: `measure_to_confirm`/`prepare` calls use correct positional signatures
  (`market, regimes, entry_ns, direction, entry_price, atr`); entry price/ATR are
  read directly from the arm's own score row (`checkpoint_reference_price`,
  `atr_at_checkpoint`), never recomputed or future-derived; verified against
  `arming.py`/`walks.py`/`engine.py` source.
- V-FROZEN/V-LABEL contract: `age_bucket`/`mfe_bucket`/`velocity_atr_per_min` are pure
  functions of `seconds_from_regime_start`/`running_mfe_atr`, confirmed by reading
  `validate.py`'s own reconstruction gates (V_FROZEN_velocity_is_at_arm_only,
  V_LABEL_buckets_from_at_arm_columns_only) and independently re-deriving the same
  logic by hand against `population.py:121-137`. `seconds_to_prevailing_flip` and
  `eventual_max_mfe_atr` never reach a bucket key or grouping column (confirmed via
  `analysis.py` group-by keys: `population`, `age_bucket`, `mfe_bucket`,
  `velocity_quartile`, `side`, `entry_year` — none retrospective).

# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-12
**Scope:** SPEC.md, implementation/{arms,build,common,phases,diagnostics,validate}.py
**Scope hash:** 0d1c7a06b54b5be6cd62a5119e809cc4bf8a724e88a23297d87c6734de4287bc
**Lint:** 0 critical / 0 warning from causal_lint.py (12 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [C-def] `ARM_CLOSED_AT_HWM` not excluded from recovery-timing primaries (phases.py) | FIXED | `phases.py:37-51` adds `_primary()` (`stratum==ARM_FRESH & ~arm_closed_at_hwm`); `_cell()` (line 54-56) routes through it. `recovery_probability` (144), `recovery_timing` (190), `recovery_curves` (271) all call `_cell(...)`, so the exclusion reaches all three. `_stop_live` (333-342) applies the identical exclusion to the state panel for Phases 8/9/11 and diagnostics 12-14. `n_arm_closed_at_hwm_excluded` is reported per cell in `recovery_probability.csv`/`recovery_timing.csv`/`adverse_before_recovery.csv` (146,192,233); the raw count is separately visible in `retracement_frequency.csv` (`n_arm_closed_at_hwm`, line 115), which intentionally still reports on the *unexcluded* ARM_FRESH population since Phase 1 is a frequency table, not a recovery-timing primary — consistent with SPEC 6.4's own wording ("excluded from recovery-timing primaries"). V9 (`validate.py:234-254`) reconciles the ARM_FRESH/ALREADY_AT_D/NO_ARM stratum partition, which is unaffected by the sub-split within ARM_FRESH and still sums correctly; the exclusion itself is visible via the `n_*_excluded` columns rather than a dedicated gate, which is adequate disclosure, not a reconciliation gap. |
| 2 | [W1] `RANDOM_TIMING`/`RETRACEMENT_ONLY` not count-matched (diagnostics.py) | FIXED | `_matched()` (diagnostics.py:122-143) draws a reproducible `crc32`-seeded random subsample of size `kk = min(k, pop.height)` from the control population and returns it alongside `control_cme_mean_full_population`. `RETRACEMENT_ONLY` (222-224) and `RANDOM_TIMING` (230-234) both now call `_matched(..., k, rule_mean)` with `k = trig.height`, so both are genuinely count-truncated to the rule's triggered count rather than averaged over the full eligible population. The written rationale (210-216) for also emitting the full-population value is sound: `RETRACEMENT_ONLY` has no ranking variable, so a "top-k" selection is meaningless and a seeded random draw is the correct matched estimator, with the full-population mean retained as the quantity the R4 branch decision actually needs. Residual: `RANDOM_TIMING`/`RETRACEMENT_ONLY` populations are drawn from the arm-level panel filtered only on `retracement_d` (not `horizon_s`/`recovery_level`, since arms are one row per trade×rung×D and carry no horizon dimension), while the rule and the other four controls condition on `horizon_s==T` too. This is a structural difference in what "matched" means for these two controls, already disclosed in the docstrings; it does not admit future information and does not change the direction of W1's original complaint (missing count truncation), so it is not re-raised as a new finding — see Note below for the record. |
| 3 | [N1] Gate V11 tautological | N/A — contract-checker scope, not re-adjudicated here. No change observed in `validate.py:256-292`; still a test-quality question. |

## Critical findings
None.

## Warnings
None.

## Notes

### [N2] `implementation/diagnostics.py:227-234` — `RANDOM_TIMING` control population is not conditioned on `horizon_s`/`recovery_level`
`_matched()` now correctly truncates `RANDOM_TIMING` to `kk = min(k, pop.height)`, resolving pass-1's W1 count-matching gap. The population it draws from (`rp`, line 227-229) is still filtered only on `retracement_d`, not on the rule's `horizon_s`/`recovery_level`, unlike the other four controls which use `pop = live.filter(horizon_s==T & retracement_d==D)`. This is structural (the arm panel has no horizon dimension — `placebo_cme_mean_fired` is a single per-arm average over `N_PLACEBO` grid draws, already verified length-blind by gate V12) rather than a causal leak, and is disclosed in the docstring. Flagged for visibility only; does not block.

## Referred to contract-checker
- N1 (V11 tautology) carried forward unchanged from pass 1 — test-quality, not re-litigated here.

## Clean checks
- A1-A5, F1-F4, G1-G4: no change since pass 1; `assert_sealed` (common.py:141-152) unchanged, still checks converted CT timestamps.
- `build.py::lineage_reconciliation` + `common.py::load_armed_panel` (new since pass 1): `load_armed_panel()` (common.py:120-130) is `pl.read_parquet(ARMED).filter(pl.col("valid"))` sealed on `arm_top10_ns` — byte-identical to the accepted predecessor's own reference load in `studies/post_confirm_profit_ratchet/implementation/validate.py:154-155`. Verified against the source parquet directly: 8,950 rows total, 8,950 after `.filter(valid)`, matching `ACCEPTED["entries"]`. The `pool`/`baseline` formulas (build.py:114-117) are line-for-line the predecessor's `validate.py:167-177` (`OPPOSING_FLIP`-only giveback pool; baseline = confirmed net + `STOPPED_BEFORE_CONFIRM` full_net_atr). This is faithful adoption of an already-accepted definition, not a novel derivation — no new causal claim to audit, and the reproduction (0.8980826 vs 0.89808, -0.0765296 vs -0.07653) is within `TOL_ATR`.
- `validate.py` V3 (new since pass 1): quoted-only pattern `[\"'](exit_now_hwm\w*)[\"']` (line 92) no longer self-flags prose/regex-literal. `tests/test_v3_hwm_scan.py` pins both a genuine leak (unsuffixed `exit_now_hwm*` string literal, including a near-miss `_CONTRAST` suffix) and the previous false-positive (comment text, the scanner's own regex-as-string) as passing/failing correctly, plus an end-to-end scan of the shipped package. This is a real gate again, not a tautology in either direction.
- Causal claims 1-9 from pass 1 (arm search causality, frozen anchors, label windows, EXIT NOW pricing, same-bar resolution, nat_i/unc_i non-contamination, ALREADY_AT_D windowing, length-blind placebo, first-trigger-per-trade): no code changed in these paths since pass 1; re-verified spot checks in `arms.py` (hwm_prev construction, frozen anchor capture) show no regression.
- 14/14 SPEC gates pass, 15/15 tests pass, causal_lint 0/0 over 12 files (confirmed this pass).

# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-11
**Scope:** SPEC.md, implementation/{arms,build,common,phases,diagnostics,validate}.py
**Scope hash:** 0d1c7a06b54b5be6cd62a5119e809cc4bf8a724e88a23297d87c6734de4287bc
**Lint:** 0 critical / 0 warning from causal_lint.py (10 files scanned)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 1
- Note: 1

## Critical findings

### [C-def] `implementation/phases.py:113-146,150-183,232-257` — `ARM_CLOSED_AT_HWM` arms are not excluded from recovery-timing primaries, contradicting frozen SPEC §6.4
**Failure path:** SPEC.md:224-232 defines the `DD <= 0` case (`ARM_CLOSED_AT_HWM` — the arm bar spiked down and closed at/above the old HWM) as "excluded from recovery-timing primaries (recovery is trivially satisfied at t=0)." `arms.py:197` correctly computes and stores the flag (`arm_closed_at_hwm = bool(dd <= 0.0)`), but no downstream table filters on it. `recovery_probability()` (phases.py:114-117), `recovery_timing()` (phases.py:160-162), and `recovery_curves()` (phases.py:242-244) all build their population as `arms.filter(rung_atr==X & retracement_d==D & stratum==ARM_FRESH)` — `arm_closed_at_hwm` is never excluded. `retracement_frequency()` only *counts* it (phases.py:85). Concretely: take an arm where the bar spikes down through the D breach on its low but closes back above the old high-water mark (`dd_atr = -0.05`, e.g.). `recovery_targets()` (arms.py:245-251) sets `R25 = mark_arm + 0.25*dd = mark_arm - 0.0125` — a target *below* the arm bar's own close. Because `recovery()` (arms.py:253-285) begins scanning at `a+1`, essentially any subsequent bar's high clears this already-cleared target, producing a near-zero `R25_secs`/`R50_secs`/`R75_secs`/`R100_secs` (R100 = `hwm_arm`, which is `<= mark_arm` by construction whenever `dd<=0`). These trivially-fast, by-construction "recoveries" are pooled directly into `p_recover_15/30/60/...` and `median_secs_to_recovery` — the exact headline numbers that answer Q2/Q3, the study's central deliverables — inflating recovery probability and deflating recovery-time medians in any cell where `ARM_CLOSED_AT_HWM` is a non-trivial share of arms (visible per-cell in `pct_dd_lt_d`/`n_arm_closed_at_hwm`, but not excluded from the primaries those two diagnostics sit beside). This is structurally the same "mechanically-contains-its-own-answer" defect the predecessor ratchet study already hit once with `ALREADY_MET` (21.9pp inflation) — the SPEC explicitly anticipated it for this exact case and wrote the exclusion rule, but the exclusion was not implemented.
**Smallest fix:** Add `& ~pl.col("arm_closed_at_hwm")` (or an explicit `.filter` on the flag) to the `fresh` population in `recovery_probability`, `recovery_timing`, and `recovery_curves`, and report the excluded count alongside `n_already_at_d`/`n_no_arm` so V9-style partition accounting still reconciles.

## Warnings

### [W1] `implementation/diagnostics.py:198-210` — `RANDOM_TIMING` and `RETRACEMENT_ONLY` controls are not count-matched to the rule, despite SPEC calling both "count-matched"
SPEC.md:313-329 states every §7.5 control selects "the SAME NUMBER of arms... at the SAME horizon" and explicitly labels `RANDOM_TIMING` "count-matched, LENGTH-BLIND." The four `*_ONLY` controls implement this correctly (`kk = min(k, uniq.height); ordered.head(kk)`, diagnostics.py:165,176). `RETRACEMENT_ONLY` (diagnostics.py:184-196) and `RANDOM_TIMING` (diagnostics.py:198-210) instead average over the *entire* eligible population (`arm_pop.height`, `rp.height`) with no `.head(kk)` truncation and no conditioning on horizon `T` or recovery level. This does not inject future information, but it changes what the comparison means: the rule's mean is conditioned on a specific, usually smaller, `failed_{lvl}_by_h`-selected set, while these two controls average over a much larger unconditioned population, which can pull the control mean toward the unconditional average and make the rule look better (or worse) than a genuine count-matched comparison would. Given placebo-matching defects have twice erased a headline result in this repo, this should be tightened before the R1/R4 verdict is drawn from Phase 13.

## Notes

### [N1] `implementation/validate.py:250-258` — Gate V11 is tautological
V11 checks for duplicate `(rule_id, side, entry_year)` rows in the already-deduplicated `price_only_diagnostics.csv` output. Since `_triggers()` (diagnostics.py:31-47) always applies `.unique(subset=["regime_id"])` before the table is written, V11 cannot fail regardless of whether the retained trigger is genuinely the earliest one — unlike V4/V5/V10, which the file's own docstring says re-derive from the trade window. Manual review of the sort key (`sort(["regime_id","decision_ts","rung_atr"]).unique(keep="first")`, diagnostics.py:46-47) confirms the underlying logic is correct, so this is a test-strength gap, not a demonstrated defect.

## Referred to contract-checker
- Gate V11's tautological self-check (test quality) — see N1; whether this needs strengthening before "V11 passing" is treated as evidence is a completeness/test-quality call.

## Clean checks
- A1-A5, F1-F4, G1-G4: no new session/timestamp handling in this package beyond the accepted `Window`; `assert_sealed` (common.py:123-134) correctly decides the 2021-2025 seal from converted CT timestamps, not partition columns.
- Causal claim 1 (hwm_prev vs run_mfe, arms.py:58-72, gate V4): verified clean — arm search starts at `r+1`, breach mask uses `hwm_prev[k]=run_mfe[k-1]`, independently re-derived by validate.py V4.
- Causal claim 2 (frozen HWM_ARM/MARK_ARM, arms.py:183-210,245-251, gate V5): verified clean — anchors captured once at `a`, targets are an affine function of them, independently re-derived by V5.
- Causal claim 3 (failed-recovery labels read only `(a,j]`, arms.py:390-394): verified clean — `k<=j` boundary check against a precomputed full-lifetime index is not a leak.
- Causal claim 4 (EXIT NOW priced at fill, never HWM, arms.py:401-407, phases.py:286-289, validate.py V3 hwm-leak scan): verified clean.
- Causal claim 5 (adverse arm / optimistic recovery same-bar resolution, gate V13): verified clean and explicitly documented as conservative-for-hypothesis.
- Causal claim 6 (nat_i/unc_i non-contamination, `_stop_live` in phases.py:306-309): verified clean — descriptive tables use UNCONSTRAINED by design (SPEC §4), economics tables filter `arm_stop_live_reachable & alive_stop_live`.
- Causal claim 7 (ALREADY_AT_D uses only bar-r-and-earlier data, arms.py:139-147): verified clean.
- Causal claim 8 (length-blind placebo, arms.py:214-241, gate V12): verified clean — offsets drawn from fixed grid, never realised lifetime; see W1 for a separate, non-causal aggregation defect in how the control is later compared.
- Causal claim 9 (first-trigger-per-trade, diagnostics.py:31-47): verified clean by manual derivation; see N1 for gate weakness.

# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-13
**Scope:** `implementation/{join,analysis,validate,lineage}.py`, `run_study.py`,
`tests/test_join_causality.py`, `SPEC.md`, `REPORT.md`,
`results/{summary,validation_report,lineage_reconciliation}.json`, plus
upstream `p90_5m_regime_context/implementation/regime_5m.py` and
`post_confirm_forward_opportunity/{analysis/buckets.py, implementation/build.py,
implementation/engine.py, analysis/phases.py}` (to trace `mfe_bucket`'s true
source). Actual pipeline run outputs and logs inspected, not just code.
**Scope hash:** `ceadcc56ea9cf1999c0f30bb7a2943464bf8a1bbfebaf018da2809faeaec6bef`
**Lint:** `causal_lint.py` — 9 files scanned, 0 CRITICAL, 0 WARNING.
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 1 (new)
- Note: 1 (new)

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [C1] LABEL_ONLY vs. permitted descriptive crosstab tension (SPEC §8-4 vs §4 Phase 11) | FIXED | `SPEC.md:140,432-434` states the carve-out precisely (grouping/filter key = forbidden; post-hoc descriptive crosstab = permitted). `analysis.py:406-410` (Phase 11 docstring) implements exactly this; `group` is always sourced from `group_transition`/`group_stable`, never from `mfe_bucket` (`join.py:63-70`, `lineage.py:84-91`). `validate.py:67-77` (`V_LABEL_group_values_clean`) ran and passed. |
| 2 | [C1] Phase 6/7 manifest LABEL_ONLY tagging missing | FIXED | `SPEC.md:379-381` — deliverables 8, 9, 10 now carry "LABEL_ONLY" / split disclosure, matching deliverable 7. |
| 3 | [C1] Phase 6 reconciliation tolerance/sample size unspecified | FIXED (redesigned) | `analysis.py:205-221` (`phase6_capture_curve`) implements an exact monotonicity check (`running_mfe_from_entry_atr < walk_a_mfe_to_confirm_atr - 1e-9` → `RuntimeError`), not a fuzzy tolerance. Confirmed it runs unconditionally, before any curve output is produced (`run_study.py:103-106`), and actually executed in the real run: log shows `Phase 6 OK (gate V-RECONCILE passed)` (`audit/logs/run_1786651606.log:8`). |
| 4 | [B2/G] Uninitialised-state (`NaN`/`-1`) handling undisclosed at new call site | FIXED | `SPEC.md` §3 states the convention; `join.py:83-89` discloses `n_uninit` count and retains (never drops or imputes) those rows — `assert state.height == 4656` runs before any NaN-based filtering. |
| 5 | [C2] Stop condition 5 had no named automated check | PARTIALLY FIXED — see new NOTE below | `SPEC.md:432-438` now cites `tests/test_join_causality.py` as the re-check for stop condition 5, but that file (read in full) contains no test touching Phase 12 strata or `STRATA_COLS`. The actual enforcement is `validate.py:90-92` (`V_MATCH_confirmation_time_only`, an allowlist diff against `CONFIRMATION_TIME_ONLY_COLS`), which did run and pass (`validation_report.json`). The invariant IS enforced in practice; only the SPEC's citation of which file enforces it is wrong. |

## Critical findings
None.

## Warnings

### [B9/C1] `mfe_bucket` is NOT the retrospective/terminal quantity the SPEC and Phase 11 docstring claim
**Location:** `SPEC.md:282-284` ("`mfe_bucket` ... retrospective, LABEL_ONLY (built on `eventual_max_mfe_atr`...)"); `analysis.py:406-410` (Phase 11 docstring, same claim); actual source: `post_confirm_forward_opportunity/analysis/buckets.py:60` — `bucketize("running_mfe_from_entry_atr", MFE_BUCKETS, "mfe_bucket")`, persisted to `observation_panel.parquet` by `analysis/phases.py:448` (`# persist buckets`). `running_mfe_from_entry_atr` is the **running** MFE-so-far at each panel row's `offset_s`, not the trade-terminal `eventual_max_mfe_atr`.

**Concrete effect:** bucket membership is not a fixed per-trade property — it drifts as `offset_s` increases (MFE only grows, so a trade migrates upward through buckets). Verified directly against the panel: 2,823 of 4,656 trades (61%) occupy more than one distinct `mfe_bucket` value across their own `offset_s` rows. `phase11_mfe_quality_buckets` (`analysis.py:406-437`) filters `mfe_bucket == bucket` *before* filtering `offset_s == offset`, so the population inside a named bucket is a different, re-selected set of trades at every landmark — not a fixed cohort followed forward in time, which is what "MFE quality bucket, re-run existing aggregations within it" implies and what `runner_bucket` (the genuinely terminal column, unused by this study) would have given. This is not a look-ahead violation — `running_mfe_from_entry_atr` at row `offset_s` is knowable causally at that instant, so the column itself introduces no future leakage — but it does mean Phase 11's output (`mfe_quality_buckets.csv`) does not measure what the SPEC and code comments say it measures.

**Materiality to this pass's headline result:** low. `REPORT.md` and `summary.json` never reference `mfe_quality_buckets.csv` or Phase 11 in deriving the `C3_EXPLAINED_BY_CONFIRMATION_QUALITY` verdict — `determine_verdict` (`validate.py:199-201`) short-circuits to `c3` before the `c2`/Phase-11 branch is ever evaluated in this run (`phase12_majority_survives=False` → `c3=True`, `c1`/`c2` unreached). If a future run's Phase 12 majority *did* survive, the `c2` branch (`validate.py:202-211`) would silently use this mischaracterised column to decide `C2_RUNNER_QUALITY_NOT_TIMING` vs. `C4_WEAK_UNSTABLE`.

**Smallest fix:** either rename `mfe_bucket` to something disclosing it's contemporaneous (e.g. `running_mfe_bucket_at_offset`) and correct the SPEC/docstring, or swap Phase 11 to bucket on `runner_bucket` (the actual terminal column already computed upstream) as the SPEC's prose describes.

## Notes

### [C2] Stop condition 5's cited enforcing test doesn't exist, but the invariant is enforced elsewhere
`SPEC.md:435-438` claims stop condition 5 is "re-checked at implementation time by `tests/test_join_causality.py`." That file has no such test. The real enforcement is `validate.py`'s `V_MATCH_confirmation_time_only` gate (a structural allowlist diff against `phase12_strata_cols`), which did run and pass in the actual pipeline execution. Functionally correct; only the citation is wrong. Doesn't affect the study's verdict.

## Pass 3 adjudication (resolved after this pass, before commit)

- **[B9/C1] `mfe_bucket` mischaracterization — FIXED, by switching to the
  correct column, not just relabeling.** Verified directly against the real
  data (0 of 4,656 trades have more than one distinct `runner_bucket`
  value; matches `eventual_max_mfe_atr`'s tier exactly). `phase11_mfe_quality_buckets`
  (`analysis.py`) rewritten to bucket on `runner_bucket` (`R0/R1/R2/R3`)
  instead of `mfe_bucket`; `validate.py`'s C2 branch's pivot updated to
  match. SPEC.md's Phase 11 section, §3.1 item 4, manifest item 14, and
  §8.1's boundary-convention bullet all corrected to name `runner_bucket`
  and explicitly disclose why the panel's native `mfe_bucket` was the wrong
  source. Full pipeline re-run after the fix: 9/9 gates still pass, verdict
  unchanged (`C3_EXPLAINED_BY_CONFIRMATION_QUALITY` — expected, since C3
  fires before the C2/Phase-11 branch is ever evaluated in this run, exactly
  as this pass's own materiality assessment predicted).
- **[C2] Stop condition 5's wrong citation — FIXED.** SPEC.md's stop
  condition 5 no longer cites `tests/test_join_causality.py`; it now cites
  `validate.py`'s `V_MATCH_confirmation_time_only` gate directly (the actual
  enforcement mechanism) and records the audit history of the citation
  error rather than silently correcting it.

## Referred to contract-checker
- (none new this pass — no completeness/manifest issues observed outside prior scope)

## Clean checks
- A (timestamp conventions): N/A, unchanged from pass 1 — no new bar-timestamp logic.
- §3 `Regime5m.age_seconds_at`/`age_bars_at`/`flip_ts_at` at `walk_a_confirm_ns` (`join.py:39-46`): causal bound (`close_ts <= t`) confirmed by direct code read of `_idx_at` (`regime_5m.py:149-151`, `searchsorted(..., side="right") - 1`) — identical helper used by the already-validated `state_at`. `age_bars_at`'s `_all_close_ts` grid lookup (`regime_5m.py:204-208`) is likewise bounded by `side="right"` search — no future bar can be read regardless of the grid's forward extent.
- `tests/test_join_causality.py`: exercises the real `Regime5m.load()` engine and real `join.build_confirmation_state` (no mocks) — confirmed by fixture code (`test_join_causality.py:25-39`). All 8 tests passed in the actual run (`audit/logs/run_1786651606.log:4`).
- Phase 6 gate V-RECONCILE: exact monotonicity (not fuzzy tolerance), runs before curve computation proceeds, unconditionally, actually executed with 0 violations against the real 4,656-trade population.
- Phase 8 (`phase8_adverse_path`, `analysis.py:318-349`): reads the 3-way categorical (`ADVERSE`/`FAVORABLE`/`UNRESOLVED`) plus a separate `_ambiguous` mean, not a boolean complement — confirmed against the upstream engine (`post_confirm_forward_opportunity/implementation/engine.py:198-209`), where `_ambiguous=True` rows are already folded into `ADVERSE` (same-bar collisions resolved conservatively), so `p_adverse` + `p_favorable` + `p_unresolved` sum to 1 and `p_ambiguous` is a non-double-counted diagnostic subset — verified by gate `V_RACE_probabilities_sum_to_one` (passed).
- Phase 11 `mfe_bucket` vs. Phase 12 `confirm_mfe_bucket`: genuinely different column names from genuinely different sources (`mfe_bucket` from the panel's `running_mfe_from_entry_atr`; `confirm_mfe_bucket` from `confirmation_state`'s `walk_a_mfe_to_confirm_atr`, `analysis.py:582-584`) — never conflated in code. (Note the separate Warning above about `mfe_bucket`'s own mischaracterisation as "retrospective.")
- `phase12_strata`/`STRATA_COLS` (`analysis.py:576-602`): every column sourced only from `confirmation_state` (`side`, `entry_year`, `arm_score`, `walk_a_*_to_confirm`, `walk_a_confirm_ns`) — none from `observation_panel.parquet`'s offset-indexed columns. Enforced by `V_MATCH_confirmation_time_only` (passed).
- `validate.py` gates V_CAUSAL, V_NOFUTURE, V_LABEL, V_MATCH, V_RACE: each reads real data/source text and checks what its name claims (age nonnegativity; source-scan for reassignment of `with_5m_at_*`; `group` column enum cleanliness; strata-column allowlist; race-probability sum-to-one). `results/validation_report.json` shows a real run, 9/9 gates passing.
- `summary.json`/`REPORT.md`: verdict `C3_EXPLAINED_BY_CONFIRMATION_QUALITY` is honestly derived — `facts` in `summary.json` (`phase12_n_metrics=8, phase12_n_ci_excludes_zero=0`) match REPORT.md's stated "0 of 8 metrics survive stratification" table exactly; `determine_verdict`'s `c3 = not phase12_majority_survives` logic correctly drives the verdict; REPORT.md's "Year/side stability" section correctly discloses `years_stable=False, no_side_inversion=False` rather than omitting it.
- Phase 0 lineage reconciliation (`lineage.py`): all 10 checks reproduced exactly against frozen expected constants; actual run confirms `all_reproduced: true, failed: []`.

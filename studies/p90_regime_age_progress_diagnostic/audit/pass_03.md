# Look-Ahead & Timestamp Audit — Pass 03 (final)

**Date:** 2026-08-13
**Scope:** `implementation/{analysis,contract,outcomes,population,validate}.py`, `run_study.py`,
`REPORT.md`, `SPEC.md` (§6.1/§7 denominator + verdict sections), `tests/test_diagnostic_contracts.py`,
`results/{summary,validation_report,phase0_contract}.json`,
`results/{primary_matrix,age_contrast,velocity_table,population_comparison,year_side_stability,
p90_eligibility_base_rates}.csv`, `results/p90_events.parquet`.
**Scope hash:** `e4bd9b2f361d1066682d88b663a88985e6a8708462de8802063d529bb9e18491`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 9 files scanned, re-run this pass)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| P1-1 | CRITICAL: `classify()` aliased empty `fired` to `D5_NOTHING_CHANGES` | **RESOLVED** (confirmed again) | `validate.py:279` still returns `"D0_UNCLASSIFIED"`, distinct from D5, with the pass-1 provenance comment at 270-276 intact. `summary.json`'s live run has `unclassified: false`, `verdicts_fired: [D3, D4, D5]` — not empty, so D0 path untested by this run but the code branch is correct. |
| P1-2 | WARNING: `arm_population` reimplemented the accepted filter, no full-population guard | **RESOLVED** (confirmed again) | `population.py` still delegates/guards per pass-2's fix; unchanged since pass 2, no regression in this pass's diff. |
| P1-3 | NOTE: `contract.py` age-column name divergence | **RESOLVED** (confirmed again) | `phase0_contract.json` row `age_column_identity`: `"0 disagreements"`, `match: true` — re-verified on the current run's artifact. |
| P1-4 | NOTE: docstring denominator imprecision | **SUPERSEDED** | Subsumed by the pass-2 CRITICAL below; docstring now states three denominators explicitly (`analysis.py:7-19`). |
| P2-1 | CRITICAL: `return_at_confirm_atr`/`mae_to_confirm_atr` pooled over `STOPPED_BEFORE_CONFIRM` trades | **RESOLVED** | Independently re-verified, not just trusted from the gate: recomputed `median(return_at_confirm_atr)` directly from `p90_events.parquet` with an explicit `pl.col("confirmed")` filter for population A, `>900s`/`300-600s` — got **0.83268 / 1.11703**, matching `age_contrast.csv` and `REPORT.md` §4 (0.833/1.117) exactly. Recomputing the same cell **without** the filter reproduces the old leaked figure **0.55786** exactly — confirms the fix is real, not a rounding coincidence. `analysis.py:83,90-97,103-106` now carry `.filter(CONFIRMER)` on every confirmer-denominated expression in the single shared `AGGS` list (used by every table). `validate.py::check_denominators` (gate `V_DENOM_*`) independently recomputes 4 of these columns from `events` and reports 0 mismatches across 22 non-empty cells each — see new finding below on this gate's actual coverage. SPEC.md:376-389 documents the leak, its measured effect, and the gate. REPORT.md's correction banner (lines 7-16) and §4's Δ column are now internally consistent: `1.117 − 0.833 = 0.284` matches the printed `+0.2843` (previously `0.777 − 0.558 = 0.219 ≠ 0.2843`, the exact inconsistency flagged in pass 2). |

## Critical findings

### [validate.py:118-174, SPEC.md:385-386] `V-DENOM` verifies 4 of the ~9 columns SPEC §6.1 claims it verifies; the exact same silent-pooling failure mode is unguarded on the columns that drive the primary verdict
SPEC.md:385-386 states: *"`V-DENOM` independently recomputes **every confirmer-denominated cell** from the event frame with an explicit filter."* `CONFIRMER_DENOMINATED` (`validate.py:118-123`) lists only 4 tuples: `median_return_at_confirm`, `mae_to_confirm_p50`, `median_secs_to_confirm`, `median_eventual_mfe`. SPEC.md:370-374 itself names the confirmer-only set as `median_return_at_confirm`, `median_secs_to_confirm`, `mae_to_confirm_*` (p50/p75/p90), `median_eventual_mfe`, and **every `p_mfe_ge_*`** — i.e. also `mae_to_confirm_p75`, `mae_to_confirm_p90`, `p_mfe_ge_1/2/3`, plus `mean_return_at_confirm` (emitted in `outcome2_table`). None of these six are checked by `V-DENOM`. `check_denominators`'s recompute loop is also hard-coded to `.median()` (`validate.py:155`) regardless of the declared aggregator in the (unused) third tuple element, so adding a `p75`/`p90`/mean column is not a one-line addition — the coverage gap is structural, not an oversight of a single line.

**Failure path:** `p_mfe_ge_3` is not a peripheral column — it is one of the four inputs `classify()` reads directly (`validate.py:216, 241-242`) to fire `D3_YOUNGER_TRADES_BETTER`, this study's **primary verdict**, and is quoted as a headline number in REPORT.md §4, §5, §6, §8. Its aggregation (`analysis.py:106`: `pl.col("mfe_ge_3_0").filter(CONFIRMER).mean()`) uses the identical `.filter(CONFIRMER)` idiom that was silently dropped from the sibling columns and reached `primary_matrix.csv` two passes ago (pass 2's CRITICAL). If that same edit-pattern regression recurs on `p_mfe_ge_3` specifically, none of the 26 gates would catch it — `V-DENOM` doesn't cover it, and (per the pass-2 finding itself) a null-check would not either, because non-confirmers' `mfe_ge_3_0` is left `None` at the source (`outcomes.py:150-151`) **only while `outcomes.py` stays correct** — the exposure is on the aggregation side, not disclosed anywhere as tested. I independently recomputed the current value from `p90_events.parquet` (confirmers-only filter) and it matches `summary.json`'s `p_mfe_ge_3` exactly (young 0.47794, old 0.36992) — **today's number is correct**; the defect is that this verdict-critical invariant is asserted by the SPEC to be gated and is not.

**Smallest fix:** extend `CONFIRMER_DENOMINATED` to the full six missing columns, generalize `check_denominators`'s hard-coded `.median()` to dispatch on the declared aggregator (or add a parallel `quantile`/`mean` recompute path), and correct SPEC.md:385-386's "every confirmer-denominated cell" claim to match actual coverage until it does.

## Warnings
None.

## Notes
None new this pass.

## Referred to contract-checker
- `check_denominators` (the `V-DENOM` gate) has no unit test in `tests/test_diagnostic_contracts.py` exercising it directly (only exercised via the full `run_study.py` pipeline) — test-quality/coverage question, contract-checker scope.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4: no new violations in the diff since pass 2; entry price/ATR/session/bracket logic unchanged.
- All-arms denominators (`p_confirm_before_1atr`, `p_stopped`, `p_session_unresolved`, `p_ambiguous`) re-verified as unfiltered `.mean()`/boolean-equality over every row in the group (`analysis.py:68-71`) — correct per SPEC 6.1's "over ALL arms" column.
- Measurable-flip denominator (`p_flip_le_*`) re-verified as null-skipping `.mean()` over `flip_le_*s` columns that are `None` only for `flip_censored` rows (`outcomes.py:108-118`), with `n_flip_censored` disclosed alongside in every emitting table (`outcome1_table`, `cell_table`) — correct.
- Descriptive columns (`pct_age_ge_1800s`, `median_age_s`, `median_running_mfe`, `median_velocity`) re-verified as unfiltered — correct, these are not confirmer-scoped by definition.
- Every number quoted in REPORT.md §1-§8 reconciled exactly to its source artifact this pass: §1/§2 to `phase0_contract.json`/`p90_eligibility_base_rates.csv` (19.5%/12.3% figures, contract table); §3 primary matrix to `primary_matrix.csv` (all 20 population-A cells, exact); §4 Δ column now internally consistent (`1.117 − 0.833 = 0.2843`, previously the flagged inconsistency); §4 duration-artifact table's session-remaining medians and −0.079 correlation unchanged from pass 2's verification; §5 to `year_side_stability.csv` (LONG/SHORT and 2023-tie/reversal figures, exact); §6 to `velocity_table.csv` (all 4 quartile rows, exact); §7 to `population_comparison.csv` (exact). No stale pre-fix figures found anywhere in REPORT.md.
- §4's bootstrap CI table correctly labelled "Supplementary robustness check, not a SPEC deliverable" (REPORT.md:142-143); not listed in SPEC's Deliverables Manifest; its point estimates now match the frozen-table deltas exactly (no divergence between the two computations).
- `entry_year` confirmed `{2021..2025}` only in `p90_events.parquet`; no `2026` outside disclosure strings/gate names; `grep` for `joblib`/`.onnx`/`load_model` across `implementation/*.py` and `run_study.py` returns nothing — no model artifact loaded, matching `phase0_contract.json`'s `"no_refit"` statement.

# Contract Audit — Pass 01

**Agent:** contract-checker · **Scope:** SPEC §6/7 (Deliverables Manifest), §8
(domain/completeness), §9 (V1–V8), §10 (decision-gate routing) · C4, D, E per
`docs/CAUSAL_CHECKLIST.md`
**Date:** 2026-08-11
**Verdict:** BLOCKED (1 critical, in-scope manifest-completeness — not a causal finding)

## Summary

- Critical: 1 · Warning: 1 · Note: 2

## §6/7 Deliverables Manifest — 16 rows

| # | Path | Verdict | Evidence | Remediation |
|---|---|---|---|---|
| 1 | `results/lineage_reconciliation.json` | PASS | 14 checks, `stop_triggered:false`, accepted/reproduced/delta all present | — |
| 2 | `results/low_tail_curve.csv` | PASS | `NESTED_CUTS` 11 entries incl. `ALL` (`common.py:31-32`); `DISJOINT_BANDS` 10 bands (`common.py:34-35`); both emitted by `curve()` | — |
| 3 | `results/low_tail_by_fold.csv` | PASS | `phase2_folds` emits FOLD_1/FOLD_2 × cuts × `WITHIN_FOLD`/`POOLED_THRESHOLD` | — |
| 4 | `results/low_tail_by_side.csv` | PASS | `phase3_sides` LONG/SHORT × {ALL,25,20,10,5} | — |
| 5 | `results/low_tail_by_rung.csv` | PASS | 6 rungs × {ALL,20,10} = 18 rows; `underpowered=True` correctly stamped on RUNG_3.0/4.0 bottom_10 | — |
| 6 | `results/low_tail_by_time_since_confirm.csv` | PASS | `phase5_time`, 3 frozen strata × {ALL,25,20,10,5} | — |
| 7 | `results/alternative_barrier_results.csv` | PASS | 4 adverse × 3 horizons = 12 targets, unconditional + AUC, × {ALL,25,20,10,5} | — |
| 8 | `results/low_tail_forward_geometry.csv` | PASS | ALL/20/10/5, timing columns present (V7 passed) plus `pct_window_reached_horizon` censoring exposure, resolving lookahead-auditor's pass-1 WARNING | — |
| 9 | `results/first_trigger_per_trade.csv` | PASS (code-verified) | `phase8_first_trigger` builds one row per triggered trade per cut via `_first_trigger` | row-level content inferred from code plus consistent aggregates in row 10, not independently re-tallied |
| 10 | `results/first_trigger_economics.csv` | PASS | all SPEC §Phase-8 fields present incl. `pct_R3/R4_intercepted`, `pct_eventual_{losers,winners}_intercepted` | — |
| 11 | `results/placebo_controls.csv` | PASS | `ML_LOW_SCORE`, `C1_RANDOM_MATCHED`, `C2/C3/C4_*_{ASC,DESC}` per cut, with `match_deficit` / `n_target_triggers` | — |
| 12 | `results/feature_forensics.csv` | PASS | named features × {25,10,5} vs ALL with SMD | — |
| 13 | `results/validation_report.json` | PASS | V1–V8 all present, `all_passed:true` | — |
| 14 | `results/summary.json` | **WARNING (N2)** | holds population/lineage/monotonicity/mechanism/decision/terminal_label — the inputs to the 17 answers, but does not enumerate Q1–Q17 | re-check once REPORT.md exists that every Qn traces to a summary.json field |
| 15 | `SPEC.md` · `README.md` · `REPORT.md` | PENDING (disclosed) | SPEC.md exists; README/REPORT not yet written, not scored as missing | — |
| 16 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | **FAIL (CRITICAL C1)** | `lint.json` critical:0 OK. `status.json` is lookahead-auditor's pass-1 file: `critical:1, verdict:BLOCKED`, predating the fix. SPEC §Phase-9 and `phases.py:293-322` show CRITICAL-1 **is fixed in code**, but no pass 2 has confirmed it. The manifest requires `critical: 0` literally. | run `lookahead-auditor` pass 2; it should adjudicate CRITICAL-1 FIXED and emit `pass_02.md` + `status.json` with `critical:0` |

## §8 Domain & completeness contract

| Check | Verdict | Evidence |
|---|---|---|
| Underpowered cells retained + flagged, never dropped | PASS | `common.py` stamps `underpowered` on every row; `gates.py` reads the flag rather than dropping rows |
| Disjoint bands partition exactly | PASS | V5: `sum_n:1410, pairwise_overlap:0, n_covered:1410`; pinned by `tests/test_gate_orientation.py::test_bands_partition_exactly` |
| Nulls never imputed / forward-filled | **WARNING (W1)** | SPEC §8 requires "a quantile over `n < 20` is emitted null with the count visible." `trade_clustered_ci` / `metrics()` computed CI/quantiles for every non-empty cell regardless of trade count, so `low_tail_by_rung.csv` RUNG_3.0/4.0 bottom_10 (n=16/11) carried numeric CIs. The `underpowered` boolean is present and is what the decision gate reads, so the terminal label is unaffected, but this is a literal deviation. |
| Integer-ns timestamps | PASS | `timing.py`, `_first_trigger`, `expected_first_ts` all sort on int-ns `rung_ts` |
| Boundary convention (CT, RTH) | PASS (inherited) | `assert_2024_seal` converts to `America/Chicago` |

## §10 Terminal-label routing (D1–D4)

Routing in `gates.py` is total: `n_passed==len(c) → D1`; `elif control_killed → D3`;
`elif incoherent → D4`; `elif tail_material.passed → D2`; `else → D4`. Every branch is
covered; no outcome falls through. `control_killed` is checked **before** `incoherent`,
correctly implementing "D3 dominates D2" per SPEC §10.

**NOTE (N1):** SPEC §10 states only that D3 dominates D2; it does not explicitly rank
D3 against D4. The code's choice (D3 first) is a defensible reading and matches the
actual run (`control_killed:true, incoherent:true → D3`), but it is a SPEC ambiguity.

Actual run: `n_passed=2/8` (`both_folds`, `sample`) → `D3 COMPOSITION / PLACEBO EFFECT`.

## §3 MARK-vs-HWM gate column

**PASS.** `analysis/gates.py`: `ECON = "continue_minus_exit_mark_atr"`, used throughout
`decide()` — monotonicity, tail_material, both_folds/sides, rung/time control,
beats_placebo. The HWM column is computed and reported but never read by the gate,
confirmed by grep: no `cme_hwm` / `_hwm_atr` reference inside `decide()`.

## §9 Validation gates V1–V8

All eight implemented and evaluated with real computed inputs, not merely declared.
V7 checks 53,838 quantities with 0 mismatches. V6's
`clause_minimality_n_non_earliest:0` is computed via `expected_first_ts` using
`groupby(...).min()`, a path distinct from `_first_trigger`'s sort-then-head — this
resolves lookahead-auditor pass-1's referred item on V6 second-clause fidelity, **FIXED**.
V3 is a static AST scan, stricter than a runtime check. All 8 read `passed:true`.

## Adjudication of lookahead-auditor pass-1 CRITICAL-1

**FIXED.** `phases.py:293-322` (`_threshold_trigger`) replaces hindsight global-extremum
selection with a causal pooled-threshold walkout and first-crossing-per-trade rule,
matching the SPEC §Phase-9 amendment text. `phase10_mechanism`'s NOTE-level reuse also
now calls `_threshold_trigger` — also fixed.

## Blocking verdict

**BLOCKED** solely on manifest row 16: `audit/status.json` still reported `critical:1`
from a pre-fix pass, though the underlying defect is verifiably fixed. This is a
process/deliverable gap in contract-checker's own scope, not a new causal claim.

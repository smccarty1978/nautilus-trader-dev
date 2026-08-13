# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-10
**Scope:** `implementation/paths.py`, `implementation/candidates.py`, `analysis/separation.py`, `analysis/evaluate.py`
**Scope hash:** `eec63d1a3dc54c2b32bb166950fff5a4bf67d6781e0a90efa21f98e8b9785294`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 9 files scanned)
**Verdict:** PASS

## Process note

This pass ran **after** the first full run completed (results already exist
under `results/`), not before, as the mandatory pre-execution gate calls for.
`causal_lint` did run pre-execution and was clean. No result has been
finalized or reported yet (`REPORT.md` does not exist), so nothing downstream
consumed unaudited numbers. Findings below were checked against the actual
produced parquet/CSV output as well as the code, which strengthens rather
than weakens this pass, but the ordering deviation itself should be recorded.

## Summary
- Critical: 0
- Warning: 0
- Note: 2

## Critical findings
None.

## Warnings
None.

## Notes

### [N1] Baseline parity is real corroboration, but only for the new stream-construction code
`analysis/evaluate.py` reproduces 0.5202/0.5892/0.6478/0.7313 confirm and
+0.8541/+0.655/+0.4753/+0.2951 median return against the frozen 0.520/0.589/
0.648/0.731 and +0.85/+0.66/+0.48/+0.30 targets exactly (`results/confirmation_move_frontier.csv`,
`results/validation_report.json` gate `baseline_parity`). This is a genuine
check on `paths.py::build_stream`/`arm_outcomes` and `candidates.py::first_firings`
— if arm identification, session bounding, or ATR selection were wrong, these
four independently-rederived selection rules (`obs_index==0`, `ge_top_5`, etc.)
would very likely drift from the quoted figures. It does **not** independently
re-verify `measure_to_confirm` (`armed_fade_score_path_progression/walks.py`)
itself, which is called unchanged — a latent defect there would replicate
identically and this parity check would not surface it. That module is
out of this pass's scope (already audited/accepted); noted so the parity
claim isn't over-read as full-pipeline validation.

### [N2] Confirming-flip boundary independently verified, not just accepted
Checked directly against `results/candidate_entries.parquet` joined to
`results/armed_score_path_diagnostics.parquet`: of 86,278 candidate entries
across all 12 rules, 900 have `entry_ns == arm_confirm_ns` (the inclusive
boundary second) and **zero** have `entry_ns > arm_confirm_ns`. This confirms
the SPEC 1.1 structural claim — a dispatch at the exact confirm second is
still legitimately part of the old regime under the project's 1s-before-1m
convention (documented in `walks.py`), but nothing fires strictly after. The
comment in `paths.py:14-15` and `candidates.py:7-8` asserting this is accurate,
not merely asserted.

## Detailed checks (highest-priority items)

1. **Trigger causality** — `score_running_max`, `delta_from_arm` (`paths.py:97-98`)
   are simple current-row/expanding values, causal. `consec_*`
   (`paths.py:105-117`) uses `cum_sum` of the *qualifying flag* within a
   run-group whose boundary increments on the non-qualifying row itself —
   traced through by hand: a miss row always reads `consec=0`, the first true
   dispatch after a miss reads `1`, matching the documented fix; verified
   against `validate.py` gate `persistence_no_carry_forward` (0/400 mismatches
   on independent recomputation). `reexpanded_*` (`candidates.py:60-74`):
   `prev_max = score.shift(1).cum_max()` excludes the current row by
   construction (shift-then-cummax), and `had_retreat` cum-sums the retreat
   flag then shifts by 1, so a retreat flagged at row `i` cannot satisfy the
   re-expansion test until row `i+1` or later. The flag cannot be set by the
   same bar that creates the peak. Clean.

2. **Armed window** — (a) session close is taken from the arm's own session
   (`market.day_close_ns[start]` where `start` is the first RTH bar after
   `arm_ns`), and the stream filter (`paths.py:237-240`) drops any dispatch
   after it; `validate.py` gate `session_containment_no_overnight` passed
   0 violations. No overnight stitching. (b) confirmed above (N2) rather than
   accepted. (c) the 1-ATR-arm-stop-does-not-bound-the-window choice is
   explicitly documented (`paths.py:226-236`) and reported per-candidate via
   `pct_entries_after_arm_1atr_adverse` (`evaluate.py:55-56`) — disclosed, not
   a leak.

3. **`_real_slopes`** — for each row `i`, `j` is found via `searchsorted(...,
   side='right') - 1`, which only ever returns indices with `t[j] <= t[i]-w`,
   i.e. strictly before `i`; the `t[i]-t[j] > 2*w` guard only *disables* a
   slope, it cannot pull in a future index. Clean.

4. **`snapshot()`** — the alive filter `(arm_terminal_ns - arm_ns)/NS > t`
   uses the arm's eventual outcome only to restrict which arms are eligible
   for the Phase 2 descriptive comparison (a landmark/survival-analysis
   convention, explicitly justified in the module docstring as removing the
   duration confound) — it is never used as a feature value read by a
   trigger. The aggregation (`separation.py:60-76`) filters to `elapsed_s <=
   t` before taking `.last()`, so it is provably last-at-or-before, never
   after. Clean.

5. **`evaluate.py`** — `measure_to_confirm` is called with `r["entry_ns"]`,
   `r["entry_price"]`, `r["entry_atr"]` — the candidate's own values from
   `first_firings`, not the arm's (`evaluate.py:118-121`); `validate.py` gate
   `candidate_uses_own_atr` passed 0 mismatches. `entered_after_arm_1atr_adverse`
   is grep-confirmed to appear only in the entries table and in
   `summarise()`'s reported mean (`evaluate.py:55-56`) — never in a `.filter(`.
   Clean.

6. **Baseline parity as evidence** — see N1.

## Referred to contract-checker
- `tests/` contains only `__init__.py` — no executable test coverage for this study.
- No `README.md` or `REPORT.md` present yet against the SPEC §6 Deliverables Manifest.
- Family D nominates only 1 of the 2 permitted retreat definitions (`0.05`); `0.03` is computed (`evaluate.py:87`) but not wired into `CANDIDATES` — manifest/cap bookkeeping, not a causal defect.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 verified clean for the files in scope (see detailed checks above for the load-bearing ones); no `center=True`, `.shift(-N)`, `bfill`, unbounded `merge_asof`, or non-`*.v.0` reference in the audited diff.

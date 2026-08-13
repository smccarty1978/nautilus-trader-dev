# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-11
**Scope:** `implementation/{timing.py,phases.py,common.py,lineage.py}`, `analysis/gates.py`, `run_study.py`, `SPEC.md`
**Scope hash:** `97d90ce588832449c40220ce22a1bf8f20e75db8b00182023425e081950e48d1`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 11 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | CRITICAL — C2/C3/C4 select each trade's hindsight extremum; feeds `beats_placebo` (D1 gate) | **FIXED** | `_threshold_trigger` (`phases.py:293-322`) walks a threshold out from the pooled distribution and fires each trade at its **first** crossing via the already-verified `_first_trigger` — a fixed-population-threshold, first-chronological-crossing rule, the same shape as the ML trigger. Independently re-ran `phase9_placebo(load())`: `bottom_25 / C3_TIME_SINCE_CONFIRM_ONLY_DESC` reproduces `-0.12375` (coordinator quoted `-0.1238`), confirming the reported collapse from `-1.0992` is real and not a reporting artifact. `n` (match target) is the ML trigger's own trade *count*, not an outcome — no label leaks into the threshold search. |
| 2 | Same hindsight pattern in `phase10_mechanism` C4 overlap | **FIXED** | `phases.py:490` now calls `_threshold_trigger(d, "drawdown_from_hwm_atr", False, n)` — same causal construction, verified by reading; consistent with fix #1. |
| 3 | Referred to contract-checker — V6 only checked uniqueness, not the SPEC's minimality clause | **FIXED** | `_v6` (`gates.py:30-47`) now checks both clauses; minimality is checked against `phases.expected_first_ts` (`phases.py:209-222`), which recomputes via `groupby("regime_id")["rung_ts"].min()` — a genuinely different code path from the `sort_values().groupby().head(1)` path in `_first_trigger`, so the gate does not audit itself. Independently executed both functions against the real 1,410-row OOS population: `{'passed': True, 'clause_uniqueness': True, 'clause_minimality_n_non_earliest': 0}`. `run_study.py:196-197` was updated to wire `P.expected_first_ts(d)` into `G.validation(...)`, so this runs in the real pipeline, not just in isolation. |

No withdrawals. All three fixes independently re-executed against the real frozen 1,410-row population, not merely read.

## New findings
None. Targeted review of `_threshold_trigger`'s tie-breaking (`kind="stable"` on the raw
row order, not `rung_ts`) confirms it cannot select a trade based on outcome or future
rungs — a trade enters the fired set solely because *some* row of it crosses a threshold
derived from the pooled `col` distribution, and `_first_trigger` then picks the earliest
chronological crossing. This mirrors the already-causal ML trigger construction and
introduces no new look-ahead.

## Notes

### Phase-7 timing medians remain resolved-only; answering the coordinator's question directly
The new `pct_window_reached_horizon` / `pct_censored_no_new_extreme` columns
(`phases.py:174-183`) are the right transparency fix and I confirm the disclosure is
structurally adequate — the imbalance is no longer hidden. But the underlying
`median_secs_to_*` values (`_med`, `phases.py:190-194`) are still plain
`.dropna().median()` over the *resolved* subset, not a censoring-adjusted (e.g.
Kaplan–Meier) estimate. Given the reported swing (89.3% resolved at ALL vs 65.7% at
bottom_5 for `secs_to_new_extreme`), those two medians are drawn from populations with
materially different survivorship, so **`median_secs_to_new_favourable_extreme` and the
`median_secs_to_adverse_*` columns are unsafe to quote in REPORT prose without the paired
`pct_window_reached_horizon`/`pct_censored_*` figure in the same sentence** — a table
column adjacent to the number is not the same as the number being self-describing.
This is a REPORT-wording discipline point, not a code defect, so it stays a Note here
and is contract-checker's to enforce against the manifest's Q1-Q17 text.

## Referred to contract-checker
(none new this pass)

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4: unchanged from pass 01, still clean —
  `_threshold_trigger` and `expected_first_ts` are the only new code and both verified
  causal above.
- `_first_trigger` re-confirmed chronological (integer-ns `rung_ts`, stable sort).
- V6 minimality now independently enforced by a second code path, verified 0 violations
  on the real population.

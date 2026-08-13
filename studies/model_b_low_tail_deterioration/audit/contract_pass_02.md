# Contract Audit — Pass 02

**Agent:** contract-checker · **Scope:** SPEC §6/7 (Deliverables Manifest), §8, §9
(V1–V8), §10 (routing) · C4, D, E per `docs/CAUSAL_CHECKLIST.md`
**Date:** 2026-08-11
**Verdict:** CLEAR

## Summary

- Critical: 0 · Warning: 0 · Note: 1 (new)

## Prior findings adjudicated (all 4)

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C1 | Manifest row 16 — `audit/status.json` stale (`critical:1`) despite CRITICAL-1 already fixed in code | **FIXED** | `audit/status.json` now `pass:2, critical:0, warning:0, note:1, verdict:"PASS"`; `audit/pass_02.md` exists and its adjudication table independently re-executed `_threshold_trigger` / `expected_first_ts` against the real 1,410-row population before marking FIXED. Manifest row 16 now satisfied across all three audit files. |
| W1 | `common.py::metrics` computed CI on underpowered (n<20) cells instead of nulling per SPEC §8 | **FIXED** | `common.py`: `if row["underpowered"]: lo = hi = None`, plus `row["ci_suppressed_underpowered"]`. Verified in `low_tail_curve.csv` bottom_2_5 (17 trades) and `low_tail_by_rung.csv` RUNG_3.0 / RUNG_4.0 bottom_10 (16 / 11) — all four CI columns blank, flag `True`, `n_obs` and `n_unique_trades` still visible. `gates.py` reads them null-safely via `pd.isna(...)` rather than crashing or coercing to 0. |
| N1 | SPEC §10 did not explicitly rank D3 vs D4 | **RESOLVED** | SPEC §10 now states `D1 > D3 > D4 > D2` explicitly with rationale, matching `gates.py` (`control_killed` before `incoherent`, `incoherent` before `tail_material`). SPEC and code agree. |
| N2 | `summary.json` lacked the 17 REPORT answers; REPORT/README pending | **FIXED** | `results/summary.json` now carries `report_answers.Q1_…` through `Q17_…`; `Q16_classification` equals the terminal label. `REPORT.md` and `README.md` exist and were read in full. |

No withdrawals.

## REPORT.md traceability spot-check

Cross-checked ~15 quantitative claims against their source artifacts: lineage deltas
(Q1), disjoint and nested Spearman (Q2), fold populations and bottom-10 CIs (Q4),
LONG/SHORT table (Q5), rung table (Q6), SINCECONF table (Q7), placebo numbers (Q8–Q9,
`placebo_controls.csv` and `summary.json.decision.conditions.beats_placebo`), barrier
AUC table (Q10), SMD values (Q12 — `+3.18 / +1.43 / +1.24 / +1.18` all match
`bottom_5_smd` to 2 dp), interception tables (Q14–Q15), and the full Phase-7 geometry
table (every ALL/20/10/5 cell matches to 3 dp). All traced exactly. **No claim
overstates its source.**

**NOTE N3 (wording scope, non-blocking).** The headline stated "No low-tail cut in this
study has a mark-based CI that excludes zero." Accurate as scoped, but
`low_tail_curve.csv` `band_50_60` — a *middle*-distribution disjoint band, not a
low-tail cut — does exclude zero (`ci95_hi_mark = −0.176`). A skimming reader could
misapply the sentence. Suggested "No **bottom-percentile** cut…" for unambiguity.

## Phase-7 timing table restructuring — confirmed adequate

REPORT.md now interleaves each `median s to X, given it happens` row directly beneath
its own `P(X happens)` row, for both adverse barriers and the favourable-extreme timing.
This is tighter than lookahead-auditor's minimum ask (an adjacent column): each median is
paired with the exact resolution rate for *that specific quantity*, not a generic
`pct_window_reached_horizon` proxy. The separate censoring paragraph correctly
distinguishes favourable-timing medians (optimistic under truncation, resolution
89.3% → 65.7%) from adverse-timing medians (98.6% of bottom-5 resolves; a 1-second
median cannot be produced by truncation). **lookahead-auditor pass-2 NOTE is closed.**

## Manifest re-check (rows previously PENDING / FAIL)

- Row 15 (`SPEC.md` / `README.md` / `REPORT.md`): **PASS** — all three exist; README
  discloses the pass-1 CRITICAL-1 correction rather than omitting it.
- Row 16 (`audit/lint.json` / `status.json` / `contract_status.json`): **PASS** —
  `lint.json` critical:0, lookahead `status.json` pass:2 critical:0, this file critical:0.

## New findings

None. 0 of the allowed 3 new criticals raised.

## Blocking verdict

**CLEAR** — all four pass-1 findings adjudicated FIXED/RESOLVED with direct evidence, no
new blocking findings, all 16 manifest rows PASS, both audit tracks read `critical: 0`.

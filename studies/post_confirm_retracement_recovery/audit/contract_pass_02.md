# Contract-Checker — Pass 02

**Date:** 2026-08-12
**Scope:** SPEC §6–10 — C4, D, E, Deliverables Manifest, terminal labels, domain/completeness.
Causality belongs to `lookahead-auditor` (PASS at its pass 2) and is not re-litigated.
**Verdict:** CLEAR — 0 blocking, 1 warning (new, non-blocking), 1 not-verified by design.

Transcribed from the agent's report by the calling session; the contract-checker
toolset is read-only.

## Adjudication of pass-1 findings

| Finding | Verdict | Evidence checked |
|---|---|---|
| **[B1]** panel missing `path='UNCONSTRAINED'` | **FIXED** | `arms.py:340-353` sets `key["path"] = PATH_UNC`; `validate.py:221-245` V8 now opens `recovery_state_panel.parquet`, checks non-null, and asserts the label set is exactly `{PATH_UNC}`. `validation_report.json` V8 detail: `tables_missing_path: []`, `state_panel_unexpected_path_labels: []`. 356,988 panel rows, all `UNCONSTRAINED`. `tests/test_v8_path_labelling.py` pins both directions — 5 tests on the real panel, 4 replaying the gate predicate against synthetic frames including a reproduction of the exact shipped defect. |
| **[N1]** gate V11 tautological (referred by `lookahead-auditor`) | **FIXED** (re-confirmed) | V11 re-derives triggers from the panel independently rather than reading the already-deduplicated CSV. 286,933 triggers checked, 0 violations. |
| **[W1]** manifest column-name drift | **PASS**, one residual gap → W3 | SPEC §11 Amendment A1's 7 mappings verified against actual CSV headers for `retracement_frequency.csv`, `recovery_timing.csv`, `runner_interception.csv`, `placebo_controls.csv`, `failed_recovery_economics.csv` — all exact. |
| **[N2]** label thresholds outside the §5 grid | **SUFFICIENT** | Amendment A2 lists all five scalars; `REPORT.md` §9 gives the deciding number for all seven clauses; `summary.json.checks`/`.evidence` emit each one (e.g. `retracement_only_gap_atr: -0.00234` against `material_threshold_atr: 0.05`), so the label is independently recomputable under different thresholds. |

## New finding

### [W3] WARNING — Amendment A1's joint entry was imprecise for `price_only_diagnostics.csv`
A1 mapped the runner-interception columns for `runner_interception.csv` and
`price_only_diagnostics.csv` jointly. Verified headers: the first emits
`pct_runners_ge3_0_intercepted`, the second emits
`pct_runners_ge3_0_intercepted_of_triggered`. The quantity is present in both;
only the documented name was wrong for one.

**Resolved.** A1's joint row was split into two rows recording each table's
actual name, and the note now states *why* they differ: the `_of_triggered`
denominator is the rule's triggered trades, not all runners. The two columns are
not interchangeable and the suffix is what says so. Documentation only, no code
change.

## Not verified, by design

**E — warmup fidelity.** The window is the accepted
`top10_fast_confirm_runner_path.prepare()`, inherited per SPEC §3 rather than
re-derived, so this study's own gate suite contains no independent warmup check.
Adjudged an acceptable lineage citation under the §3 inheritance rule, not a gap
in this study's contract.

## Pass

| Requirement | Verdict |
|---|---|
| Deliverables Manifest items 1–20 | PASS — all present; columns reconciled via A1 |
| `REPORT.md` answers Q1–Q13, emits exactly one label | PASS — §§2–10 verbatim, single label line, §11 defects table |
| Terminal-label reachability R1–R4 | PASS — all four branches reachable, R4 the residual `else` |
| Domain & completeness (SPEC §9) | PASS — V9 per cell **and** per year; underpowered NULLs with counts visible; `EMPTY_CELL` emitted |
| Seal integrity (SPEC §3, V1) | PASS — CT-converted timestamps at source scan |
| C4 / D | NOT APPLICABLE — no model trained, no serving path |
| E — fill model | PASS — V10 cross-checks against the accepted `Window.realise` bar-for-bar |

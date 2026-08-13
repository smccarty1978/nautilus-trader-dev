# Contract Audit — top10_armed_entry_refinement — Pass 01

**Date:** 2026-08-10
**Scope:** SPEC §6 Deliverables Manifest, §7 final classification reachability,
§3 candidate cap, §1.2 interpolated levels, §8 validation gates, §9 non-goals,
and C4/D/E. Causality is out of scope — `lookahead-auditor` returned PASS,
0 critical / 0 warning / 2 notes.
**Verdict at time of pass: BLOCKED (1 CRITICAL). After remediation: CLEAR.**

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. The table is verbatim; the
> remediation section was added afterwards.

## Blocking finding

**F1 — SPEC §6 item 10 missing.** `results/finalist_shortlist.json` did not
exist. The Phase 7 shortlist (B1_PERSIST_TOP10_x2 DIAGNOSTIC_ONLY,
A1_INTERP_L1 REJECT, D1_REEXPANSION_0_05 REJECT) was fully computed and
reported in `REPORT.md` §6 but never serialized to the named manifest artifact.
Checked literally against the manifest, not inferred.
Remediation: write the JSON from already-computed values; no new computation.

## Adjudication of findings referred by lookahead-auditor

- Empty `tests/` — **FIXED** (7 tests in `tests/test_triggers.py`).
- Missing README/REPORT — **FIXED** (both present; REPORT has the eleven
  questions and exactly one §7 label).
- Family D wiring 1 of 2 retreat definitions — **WITHDRAWN**. SPEC §3 caps the
  family at "at most 2"; there is no floor, so this was a misapplied reading.

## Compliance table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| §6 manifest items 1–9, 11–13 | PASS | all present with described contents; parquet gitignored, CSV mirrors for the small tabular ones | — |
| §6 item 10 `finalist_shortlist.json` | **FAIL** | absent from `results/` | serialize from REPORT §6 |
| §7 label A defensible over B–G | PASS | non-dominated on both frontiers (`frontier_points.json`); leads confirmed/100 arms 52.0 and ATR/100 arms 44.4 vs 40.4 next; no candidate meets the "beats A" condition of B–E; gates 1–11 pass so G does not fire | — |
| §3 candidate cap ≤8 + 4 baselines | PASS | exactly 4 + 8 counted in `candidates.py`; Family E omitted with a stated reason in code, REPORT and README | — |
| §1.2 interpolated-level labelling | PASS | consistent NOT-A-PERCENTILE string across `paths.py`, `validate.py`, `partition_manifest.json`, SPEC, README, REPORT; no threshold derived from the evaluation population | — |
| §8 twelve validation gates | PASS | all twelve implemented 1:1 with the SPEC text, each writing `passed`, plus top-level `all_passed`. Gate 12's dependency on this pass's own output is correct fail-closed logic | re-run `validate.py` after this file lands |
| §9 non-goals | PASS | no exit optimization, retraining, model-contract change or parameter grid in `implementation/` or `analysis/`; `measure_to_confirm` reused unchanged from the accepted upstream module; the deferred exit hypothesis is confirmed unexecuted | — |
| Process-deviation disclosure | PASS | REPORT §7 and README both disclose the post-execution auditor pass, name what did run pre-execution, and state that neither defect was caught by the deviated gate. Adequate — no overstatement | — |
| C4 selection seals | NOT APPLICABLE | no walk-forward refit or automated promotion; shortlist labels are analyst-assigned against gate-validated numbers | — |
| D train/serve skew | NOT APPLICABLE | no model trained or served; triggers are deterministic expressions over a frozen score stream | — |
| E backtest configuration | NOT APPLICABLE | no NT BacktestEngine run; the warmup analogue (600s regime age) is enforced upstream and verified by gate 1 | — |

## Blocking verdict

**BLOCKED** at time of pass, on one CRITICAL: a manifest artifact whose content
was computed and reported but never serialized. Everything else passes.

---

## Remediation applied after this pass (main session, 2026-08-10)

**F1 RESOLVED.** `results/finalist_shortlist.json` was generated
**programmatically** from `confirmation_move_frontier.parquet` and
`frontier_points.json` rather than hand-typed, so it cannot drift from the
computed table. It carries the final classification, the reference
immediate-Top-10 row, the ADVANCE criteria, all three shortlist entries with
their labels and metrics, the specific ADVANCE criteria each one failed, and the
free-option disclosure.

`validate.py` re-run afterwards: all twelve gates pass, `all_passed` true.
Verdict moves **BLOCKED → CLEAR**.

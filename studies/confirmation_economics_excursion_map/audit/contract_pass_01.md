# Contract Audit — confirmation_economics_excursion_map — Pass 01

**Date:** 2026-08-10 · **Verdict: CLEAR** · 0 critical · 0 blocking · 1 warning (since resolved) · 1 not-verified (since resolved)

Scope: SPEC §6 Deliverables Manifest, §7 terminal classification, §8
domain/completeness, §9 validation gates, and C4/D/E. Causality is out of scope —
`lookahead-auditor` blocked pass 1 on 2 CRITICALs and returned PASS with 0
findings at pass 2.

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. The table is verbatim; the
> remediation section was added afterwards.

## Compliance table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| §6 Deliverables Manifest, 16 items | PASS | All present: SPEC/README/REPORT, `excursion_panel.parquet` (gitignored, present locally), the nine phase JSONs, `validation_report.json`, `partition_manifest.json`, and the audit trio | — |
| §7 terminal label E reachable and exclusive | PASS | §7 makes E fire exactly when Gates A and B both pass materially. Gate A: 94.3% loser touch vs 31.4% of ≥2.5 ATR runners at 0.75 ATR. Gate B: capture 0.138, +0.89 ATR/entry recoverable. E correctly subsumes B and D; C excluded because an unconditional level does separate; F excluded because the gates pass | — |
| §8 domain/completeness | PASS | `partition_manifest.json`: NQ substrate, `min_regime_age_s` 600.0, population counts exactly matching §3.1, `path_modes` exactly the two named, landmark/floor/deterioration lists exactly matching §4 with no extra value, 2025 non-OOS disclosed with the canonical waiver cited. Gate 1 confirms exact reproduction; gate 10 confirms both-bounds ambiguity counting | — |
| C4 selection seals / promotion gates | NOT APPLICABLE | Diagnostic study; no model selection, promotion pipeline or walk-forward exists in scope | — |
| D train/serve skew, artifact binding | PASS (partly N/A) | No training or serving; Phase 9 reuses a frozen upstream score rather than retraining. `code_hashes` binds `panel.py` / `phases.py` / `overlay.py` | — |
| E backtest configuration | PASS | Stop, landmark and floor triggers all use the intrabar extreme; fills at the FOLLOWING bar's open, trigger price never credited. Substrate is the accepted canonical store | — |
| §9 gates 1–10 executed and populated | PASS | All ten `passed: true` with per-gate detail (population counts, zero mismatch counts, ambiguity counts, direction-normalisation stats) | — |
| §9 gate 11 `audit_gates` design | PASS (logic) | `g11_audit()` requires `verdict in (CLEAR, PASS)` and `critical == 0` from lint, lookahead-auditor and contract-checker. Correctly refuses to self-report clear | re-run `validate.py` after this file lands |
| §3.3 phase-depth split | PASS | `phases.py`: `FULL = (top_2_5, armed)`, `ANNEX = (top_10, top_5, top_1)`. REPORT Phases 1/2/8 show all five populations; Phases 3–7 show only the two full-depth ones. Matches §3.3; nothing silently dropped | — |
| §10 non-goals (no grid, no tuned parameter) | **WARNING** | The terminal-classification section named a 0.625–1.00 ATR band and 0.6/1.6 ATR room figures as "structural regions worth testing". Explicitly disclaimed, ranges not point values, deferred to a future study — defensible but close to the line. No new threshold is *computed*; the numbers read off existing phase tables | tighten to "candidate region, not evaluated as a rule" |

## Referred to lookahead-auditor

None — causality cleared at pass 2, no new causal theories found.

## Blocking verdict

**CLEAR.** All 16 manifest items exist with the described contents; the four base
populations and the armed population reproduce exactly; the two path modes and the
phase-depth annex split are honoured in code and report; all ten data-integrity
gates pass with zero mismatches; terminal label E is defensible and its logic
correctly subsumes B and D rather than leaving them independently reachable in
error. The only open item is gate 11, false purely because this agent's own output
did not yet exist. One WARNING on §10 boundary proximity, explicitly disclaimed in
the text and non-blocking. No C4/D/E defects.

---

## Remediation applied after this pass (main session, 2026-08-10)

- **CC-1 RESOLVED.** The terminal-classification wording was tightened to
  "Candidate regions — described, NOT evaluated as rules." Each item is reframed
  as a description of where the curves lie rather than a proposed setting, and the
  ladder finding is restated as a negative implication ("a rule that tightens with
  maturity would impose structure the data does not contain"). No figure changed.
- **CC-2 RESOLVED.** `validate.py` re-run after `contract_status.json` landed; all
  eleven gates pass and `all_passed` is `true`.

# contract-checker — pass 01

**Study:** `top10_fast_confirm_runner_path` · **Date:** 2026-08-10
**Verdict: BLOCKED** · blocking 1 · critical 1 · warning 0 · not_verified 1

Scope: deliverables, seals, terminal-label reachability, C4/D/E, SPEC §§6–9.
Causality is out of scope (see `lookahead-auditor` pass 01, verdict PASS).

## Compliance table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| §6 Manifest #1–5, 7–11 (tables + CSV mirrors) | PASS | all 11 parquet+CSV pairs present; columns match the manifest literally | none |
| §6 Manifest #6 `time_landmark_states.parquet` | PASS | present, parquet-only **by design** per manifest; 23,830 rows | none |
| §6 Manifest #12 `validation_report.json` | NOT VERIFIED | gates 1–14 `passed: true`; gate 15 false only because `contract_checker.present: false`, expected pending this pass | re-run `validate.py` after this file is written |
| **§6 Manifest #13 `results/summary.json`** | **FAIL (blocking)** | on disk `"phase12_ran": false` with no `phase12` key, contradicting the real, correct `policy_results` / `runner_destruction` / `policy_stability` artifacts and REPORT §11. Root cause: `analysis/phases.py::main()` unconditionally writes `"phase12_ran": False`, so any re-run of `phases.py` after `policies.py` silently reverts it. Separately, the manifest requires "headline answers to the 14 report questions + final classification" in this file; **no script path ever writes that content** — only `REPORT.md` §13 does | make `phases.py` merge rather than clobber; add a Q1–Q14 + `final_classification` block to the script that closes the run |
| §6 Manifest #14 `partition_manifest.json` | PASS | input paths, row counts, frozen constants, 2025 waiver, 2026-untouched | none |
| §6 Manifest #15 SPEC/README/REPORT | PASS | REPORT answers Q1–Q14 (§13), ends with exactly one label (**C**) | none |
| §6 Manifest #16 audit jsons | PASS / pending | `lint.json`, `status.json` present, `critical: 0`; `contract_status.json` produced by this pass | none |
| §6 Manifest #17 conditional Phase-12 outputs | PASS | present because the gate opened; numerically consistent with REPORT §11 | none (content correct; only #13's pointer is broken) |
| §6 Terminal labels A–G reachable | PASS | `cohort_test.passed` and `separation_gate.open` are independently computed booleans; actual routing (cohort FAILS 0/5 + gate OPENS → **C**) matches the §6 decision table; A/B/D/E/G each explicitly ruled out with a one-line justification; **G** reachable via the §8 abort branch | none |
| §7 10 partitions (5 years × 2 sides) non-empty | PASS | `confirm_speed_cohorts.csv`: LONG 1,079 / SHORT 1,304; 540/506/481/389/467 by year | none |
| §7 `FAST_0_60 + FAST_61_120 = FAST_CONFIRM_120` | PASS | 1,174 + 1,209 = 2,383 exactly | none |
| §7 zero-row / missing-dispatch handling | PASS | `model_context.csv` carries an explicit `n_null` column, never imputed | none |
| §8 separation gate + dated amendment | PASS | `phases.py` implements the amended text exactly (judged on `undetermined`), and reports **both** counts (25 undetermined / 27 constant) as the amendment requires | none |
| §8 count-matched placebo + mandatory runner destruction | PASS | `policies.py::evaluate()` draws 20 uniform exits over `[ci, nat_i)` with causal next-bar-open fill; `runner_destruction()` unconditional for all 4 policies | none |
| §9 the 15 gates | PASS 1–14, pending 15 | gate 9 is now genuinely **derived** from the 6-variable hard-truncated replay, no longer hardcoded | re-run `validate.py` |
| Disclosures (2025 waiver, 2026 untouched, EXPLORATORY_OUT_OF_DOMAIN, placebo) | PASS | all four present in `partition_manifest.json` and REPORT §14; `model_context` carries a literal `domain` column | none |
| REPORT Q1–Q14 vs artifacts | PASS (spot-checked) | Q1 2,392/2,383; Q5 53.3/42.2/34.6/22.8%; Q10 AUC 0.756/0.724/0.692 — all match the CSVs exactly | none |

## Adjudication of `lookahead-auditor` referrals

1. `no_future_extreme_in_causal_state` hardcoded `True` — **FIXED**; now derived from the replay gate.
2. Empty `tests/` — **FIXED**; `tests/test_engine.py`, 16 deterministic tests.

## Referred to lookahead-auditor

None. No new causal theories found.

## Blocking finding

`results/summary.json` does not reflect the Phase-12 result that actually ran and
never contains the manifest-required 14-answer / final-classification content.
The underlying analysis is correct and consistent; this is a deliverable-content
defect, not a result defect.

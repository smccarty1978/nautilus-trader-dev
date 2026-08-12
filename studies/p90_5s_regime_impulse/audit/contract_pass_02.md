# contract-checker — pass 02

**Study:** `p90_5s_regime_impulse` · **Date:** 2026-08-12
**Scope:** deliverables, seals, terminal-label reachability, C4/D/E.
**Verdict: CLEAR — 0 CRITICAL, 1 procedural WARNING (closed below).**

Bounded re-audit: all pass-01 findings adjudicated before any new finding was
raised. New CRITICALs raised: 0 (cap 3).

> As in pass 01, the `contract-checker` agent is read-only and its findings are
> transcribed here by the main session.

## Adjudication of pass-01 findings — all CONFIRMED FIXED

Each was verified against the files on disk, not inferred from the remediation
notes in `contract_pass_01.md`.

| ID | Verdict | Evidence checked |
|---|---|---|
| **C1** — PLACEBO_ENTRY copied PLACEBO_EXIT's economics | **CONFIRMED FIXED** | `run_study.py` builds `e_plac_entry` via `draw_stats()` over `bench_by_id` (benchmark-A `net_atr` / `gross_atr`), median across 1,000 count-matched draws. The 5s-only columns (`n_stop`, `n_5s_exit`, `n_session`, `median_hold_s`, `pct_ambiguous`) are explicitly `None`. `per_original_arm.csv`'s `PLACEBO_ENTRY` row now differs from `PLACEBO_EXIT`'s — no longer a copy. |
| **C2** — `walk_a_terminal_label` missing | **CONFIRMED FIXED** | `run_study.py` joins `arms.select("regime_id", "walk_a_terminal_label")` onto all three trade frames before writing. Gate `V9` confirms nothing in the policy consumed it. |
| **W1** — no `q1`–`q15`, no docs | **CONFIRMED FIXED** | `summary.json` carries `report_answers` keyed `q1_…`–`q15_…`; `README.md` and `REPORT.md` exist. |
| **W2** — manifest lacked input paths/sizes | **CONFIRMED FIXED** | `partition_manifest.json` has an `inputs` block with all six paths and `exists` / `size_bytes` / `rows`, including the generated `_work/regime_5s_flips.parquet`. |
| **W3** — column names not literal | **CONFIRMED FIXED** | `per_original_arm.csv` header carries `n_original_arms`, `total_net_atr`, `ci_low`, `ci_high`; `confirmation_capture` emits the unprefixed `return_at_confirm` / `mfe_at_confirm` / `return_at_5s_exit` / `mfe_at_5s_exit` / `n_zero_denominator`; `failure_cost` emits `net_atr_per_arm`. |

## New findings

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| **P1** | WARNING (procedural) | `audit/status.json` carried only the `lookahead-auditor` key. SPEC §9 and CLAUDE.md require the completion gate to read **both** agents' verdicts from that one file — "Gates read `audit/status.json`, never prose". | **CLOSED.** The main session restructured `status.json` to carry both `lookahead_auditor` and `contract_checker` keys plus a roll-up. Manifest item 23 is now satisfied. |
| — | — | SPEC §2.1 loader-path mismatch (raised by `lookahead-auditor` pass 1 and referred here). | **WITHDRAWN.** §2.1 now reads `implementation/lineage.py::load_arms`, matching the code exactly. |

No other new blocking findings.

## Re-verified clear on the current tree

- The 5s build reconciliation keys are internally consistent: `18,774,838`
  closed buckets = `18,774,839` slots touched − 1 discarded, and
  `absorbed_1s_rows` = `source_1s_rows − 1`. `final_partial_bucket_discarded`
  is now **computed** rather than hardcoded.
- All five terminal labels remain reachable; the verdict remains computed from
  the gate table.
- Seals: nothing reads 2026 (`V10`, max year 2025).
- Frozen values (§2.4): stop grid exactly `{1.00, 0.75}`, cost 0.50 points round
  turn, years 2021–2025.
- §10 prohibitions: Phases 2, 10, 11 remain descriptive; no filter derived from
  them feeds S1 or S075.

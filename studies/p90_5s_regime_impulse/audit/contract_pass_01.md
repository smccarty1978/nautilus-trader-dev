# contract-checker — pass 01

**Study:** `p90_5s_regime_impulse` · **Date:** 2026-08-12
**Scope:** deliverables, seals, terminal-label reachability, C4/D/E. Causality
(A, B, C1–C3, F, G, H) is out of scope and belongs to `lookahead-auditor`.

**Verdict at pass 01: BLOCKED — 2 CRITICAL, 3 WARNING.**
**All 5 findings remediated in-session; see the adjudication column.**

> Transcription note: the `contract-checker` agent is read-only (Read/Grep/Glob)
> and cannot write files. Its findings are transcribed here verbatim in
> substance by the main session, which then applied the fixes and re-ran the
> study. Two findings (W1 docs, C2 label) were partly artifacts of the agent
> scanning before `README.md`/`REPORT.md` were written; they are recorded as
> raised rather than quietly dropped.

---

## Terminal-label reachability — PASS

All five labels are reachable through real code paths in
`implementation/validate.py::determine_verdict`, and the verdict is computed from
the gate table rather than asserted in prose.

| Label | Path | Reachable |
|---|---|---|
| `ABORT_LINEAGE_FAILURE` | any failed gate | yes |
| `F1_STRONG_5S_IMPULSE_EDGE` | all-AND branch | yes |
| `F3_5S_USEFUL_ONLY_AS_LOSS_CONTROL` | independent boolean branch | yes |
| `F2_PROMISING_ENTRY_TIMING_NEEDS_WORK` | guarded `elif` | yes |
| `F4_NO_USEFUL_5S_EDGE` | `else` fallthrough | yes — **this run** |

## Findings and adjudication

| ID | Sev | Finding | Adjudication |
|---|---|---|---|
| **C1** | CRITICAL | `PLACEBO_ENTRY`'s row in `policy_comparison.csv` / `per_original_arm.csv` was built as `e_plac_entry = dict(e_plac)` — a copy of PLACEBO_EXIT's **5s-managed** economics — with only `exp_per_arm_net`, its CI and the counts overwritten. Every other column (`win_rate`, `profit_factor`, `net_atr_total`, `exp_per_arm_gross`, …) reported PLACEBO_EXIT's numbers under PLACEBO_ENTRY's name. The verdict was **not** corrupted (it reads the correct band from `summary.json["placebo"]`), but the deliverable was factually wrong. | **VALID — FIXED.** `run_study.py` now computes `draw_stats` over the benchmark-A trades of each of the 1,000 count-matched draws and reports the median of each statistic. The 5s-management columns (`n_stop`, `n_5s_exit`, `n_session`, `median_hold_s`, `pct_ambiguous`) are explicitly **null**, because this control has no 5s exit and any value there would be a false reading. Verified: `win_rate` 0.5157 and `exp_per_entry_net` −0.0515 now track benchmark A (0.5156 / −0.0518), not PLACEBO_EXIT (0.4238 / −0.0698). |
| **C2** | CRITICAL | `walk_a_terminal_label` named in manifest items 6/7 was never emitted by `walks_to_frame`. | **VALID — FIXED.** `run_study.py` joins `walk_a_terminal_label` from the frozen arm artifact onto all three trade tables after simulation. Sourced from the arm artifact rather than from `benchmark_a_next_open.parquet`'s `outcome` (the checker's suggestion) because the arm artifact's column *is* the accepted lifecycle's own terminal label. Attached post-simulation; gate V9 confirms nothing in the policy ever saw it. |
| **W1** | WARNING | `summary.json` lacked the required `q1`–`q15` report-answer keys; `README.md` and `REPORT.md` did not exist. | **VALID — FIXED.** `summary.json` now carries a `report_answers` block keyed `q1_…`–`q15_…`. `README.md` and `REPORT.md` were written after the agent's scan and now exist; `REPORT.md` answers all 15 questions in prose. |
| **W2** | WARNING | `partition_manifest.json` carried row counts but not the input file paths and sizes the manifest requires. | **VALID — FIXED.** An `inputs` block now records path, existence, `size_bytes` and row count for all six inputs, including the generated `_work/regime_5s_flips.parquet`. |
| **W3** | WARNING | Column names in `per_original_arm.csv`, `failure_cost.csv` and `confirmation_capture.csv` diverged from the manifest's literal names. | **VALID — FIXED.** `per_original_arm.csv` now emits `n_original_arms`, `total_net_atr`, `ci_low`, `ci_high`. `failure_cost.csv` adds `net_atr_per_arm`, keeping `net_atr_per_failure_arm` as a disambiguating alias (here "per arm" means per *failure* arm). `confirmation_capture.csv` adds the unprefixed `return_at_confirm`, `mfe_at_confirm`, `return_at_5s_exit`, `mfe_at_5s_exit`, `n_zero_denominator`. |

## Checked and clear

- Manifest items 1–5, 10–19, 21–23: present with required contents.
- `_work/regime_5s_flips.parquet` correctly generated-not-committed per the
  manifest's explicit carve-out.
- **Seals:** nothing reads 2026; gate `V10_2026_sealed` observes max year 2025.
- **Frozen values (§2.4):** stop grid exactly `{1.00, 0.75}`; cost
  `COST_POINTS` = 0.50 points round turn; years 2021–2025.
- **§7 completeness:** 5s bucket grid and 1s row counts both reconcile;
  non-entries retained in the denominator (gate V8, all three variants).
- **§10 prohibitions:** Phases 2, 10 and 11 are descriptive; no filter derived
  from them feeds S1 or S075.
- C4 / D / E: consistent with the frozen SPEC, no additional CRITICAL.

## Disposition

All 5 findings remediated. The study was re-run after the fixes; gates remain
**26/26** and the verdict is unchanged at `F4_NO_USEFUL_5S_EDGE`. A pass-02
re-check is required to close this gate.

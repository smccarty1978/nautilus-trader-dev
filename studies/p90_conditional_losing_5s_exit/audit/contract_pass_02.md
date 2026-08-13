# contract-checker — pass 02

**Study:** `p90_conditional_losing_5s_exit` · **Date:** 2026-08-12
**Scope:** deliverables, seals, terminal-label reachability, C4/D/E.
**Verdict: CLEAR — 0 CRITICAL. 3 non-blocking items, all fixed below.**

Bounded re-audit: all pass-01 findings adjudicated before any new finding.
New CRITICALs raised: **0** (cap 3).

> The `contract-checker` agent is read-only and its findings are transcribed here
> by the main session.

## Adjudication of pass-01 findings — all CONFIRMED FIXED

| ID | Verdict | Evidence checked |
|---|---|---|
| **C1** — `pct_losing_before_075` missing | **CONFIRMED FIXED** | `trade_level_signal_coverage.csv` now carries `pct_losing_before_075` (0.519 ALL / **0.808** failure / **0.255** confirming) and `pct_losing_before_100`. Matches REPORT.md's audit-trail claim exactly. |
| **C2** — `p_unreached` missing and never tracked | **CONFIRMED FIXED** | `matched_placebo.csv` carries `n_placebo_candidates=90381`, `n_placebo_unreached=32997`, `p_unreached=0.36509`. Satisfies SPEC §7. |
| **W1** — SPEC said "V1–V12" | **CONFIRMED FIXED in SPEC/REPORT, was PARTIALLY OPEN in code** | `SPEC.md` and `REPORT.md` updated; `validate.py`'s **module docstring** still read "Gates V1-V12" while defining `V13`. Now fixed. |
| Referral 1 — V10 covered only `COND_1.00` | **CONFIRMED FIXED** | `validate.py` emits `V10_COND_1.00_…` and `V10_COND_0.75_…`; both pass. Gate count 27 → 28. |
| Referral 2 — V13 naming | Same as W1; **CONFIRMED FIXED**. |

## Re-verified clear

- `validation_report.json`: **28 gates, 0 failed**, all V1–V13 families present
  including both stop-distance variants of V5/V8/V9/V10/V12.
- **Terminal-label reachability + §8.2 amendment: PASS.** `determine_verdict`
  implements mutually-exclusive branches, `improves` requiring
  `delta_per_arm > 0 AND delta_ci_excludes_zero`, and the placebo evaluated first
  with G3 gated behind `beats_placebo` — exactly as SPEC §8.2 describes. Produces
  `G4_NO_USEFUL_EDGE`, consistent with the stated G2 → G4 shift.
- **REPORT.md audit trail: accurate.** Describes the pass-1 findings and fixes
  with no overstatement and no omission.
- Frozen values, 2026 seal, §9 abort enforcement, §11 prohibitions: all pass.

## New findings at pass 02 — all non-blocking, all fixed

| ID | Sev | Finding | Fix |
|---|---|---|---|
| **N1** | WARNING | Manifest items 4 and 17 name `pct_losing_before_1atr` and `delta_vs_conditional`; the files delivered `pct_losing_before_1atr_stop` and `delta_placebo_minus_conditional`. Data present and unambiguous, but not under the literal manifest name. | **FIXED** — both manifest names now emitted as columns, with the self-describing longer names kept as aliases. The `delta_vs_conditional` alias carries a comment recording the sign convention (placebo **minus** conditional). |
| **N2** | WARNING | `REPORT.md` stated "32,981 of 90,381" unreached draws; the actual count is **32,997**. A transcription error — the figure was copied from the run *before* the N1 clock fix. `p_unreached = 0.365` was unaffected. | **FIXED** — corrected to 32,997. |
| **N3** | NOTE | `validate.py` module docstring still read "Gates V1-V12". | **FIXED**. |

## Cross-gate referral accepted from `lookahead-auditor` pass 02

| Item | Adjudication |
|---|---|
| `tests/` contained only `__init__.py` — no executable coverage for `policy.py` / `validate.py` | **FIXED** — `tests/test_conditional_rule.py` adds **23 passing tests** covering the frozen threshold (including that `return == 0` is *not* losing), long/short mirroring, the repeated-flip walk (the brief's ignore/ignore/exit example), causal fills, the adverse tie resolution, baseline isolation, the `adverse_075_ns`/`adverse_100_ns` landmarks, the placebo's unreached counting and its `entry_ns` anchoring, and every branch of `determine_verdict` — including that a positive point estimate with a CI spanning zero yields G4, and that G3 is unreachable while the placebo is unbeaten. |

## Disposition

All pass-01 findings fixed and independently re-verified; three new non-blocking
items and one referral fixed in-session. Study re-run: gates **28/28**,
`causal_lint` 0/0 over 9 files, tests **23/23**, verdict unchanged at
`G4_NO_USEFUL_EDGE`.

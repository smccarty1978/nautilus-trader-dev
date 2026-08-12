# contract-checker — pass 01

**Study:** `p90_conditional_losing_5s_exit` · **Date:** 2026-08-12
**Scope:** deliverables, seals, terminal-label reachability, C4/D/E. Causality
(A, B, C1–C3, F, G, H) belongs to `lookahead-auditor`.

**Verdict at pass 01: BLOCKED — 2 CRITICAL, 1 WARNING.**
**All three remediated in-session; pass 02 re-checks.**

> The `contract-checker` agent is read-only (Read/Grep/Glob) and cannot write
> files. Its findings are transcribed here in substance by the main session,
> which applied the fixes and re-ran the study.

## Findings and adjudication

| ID | Sev | Finding | Adjudication |
|---|---|---|---|
| **C1** | CRITICAL | `results/trade_level_signal_coverage.csv` was missing the manifest's required `pct_losing_before_075`. It carried `pct_losing_before_1atr_stop` and `pct_losing_before_confirm`, neither of which is the "before the 0.75 ATR stop" comparison the manifest names. | **VALID — FIXED.** The accepted lifecycle has only a 1.00 ATR stop, so `walk_a_stop_ns` structurally cannot answer this. `simulate()` now records `adverse_075_ns` / `adverse_100_ns` — the first time the baseline walk reached each adverse level — and `signal_coverage` computes `pct_losing_before_075` and `pct_losing_before_100` from them. Measured on the baseline walk, read by no policy (SPEC §11). Result: failures **0.808**, confirmers **0.255**. |
| **C2** | CRITICAL | `results/matched_placebo.csv` was missing `p_unreached`, and the underlying count was never tracked — the candidate-time filter in `policy.py` silently dropped out-of-window draws. SPEC §7 makes this a mandatory disclosure. | **VALID — FIXED.** `simulate()` now returns `n_placebo_candidates` and `n_placebo_unreached`; `run_study.py` aggregates them into `p_unreached` = **0.365** (32,981 of 90,381 draws). Reported in `matched_placebo.csv` and discussed in `REPORT.md` Q15: it makes the placebo a *conservative* control, so the real rule failing to beat it is a stronger negative. This is exactly the diagnostic `placebo_must_be_length_blind` exists for. |
| **W1** | WARNING | SPEC §8 item 20 and §8.1 said "gate V1–V12" while the implemented set is V1–V13. Stale cross-reference in the frozen contract. | **VALID — FIXED.** Both references updated to V1–V13. Subsequently the gate set grew to 28 checks after the `lookahead-auditor` referral below. |

## Checked and clear at pass 01

- Manifest items 1–3, 5–16, 18–23: present with the required columns.
- **Terminal-label reachability: PASS.** All five labels reachable. G3 is
  reachable only inside the `beats_placebo` branch, exactly as SPEC §8.2 claims.
  Code and prose agree, and the design was assessed as **coherent**: it prevents
  attributing informativeness to the 5s flip when a matched control does as well.
- **§8.2 amendment consistency: PASS.** SPEC.md, `validate.py` and `REPORT.md`
  describe the same two defects, the same corrected behaviour and the same
  outcome (G2 → G4). No drift.
- **Frozen values:** stop grid `{1.00, 0.75}`; threshold `current_return_atr < 0`;
  cost `COST_POINTS = 2 * TICK`; flat band 0.125; years 2021–2025.
- **2026 seal:** nothing reads 2026; gate V11 observes max year 2025.
- **§11 prohibitions:** Phases 1, 2, 9, 10 are computed strictly *after* all four
  policy frames are simulated; no derived threshold, count or time gate feeds any
  policy.
- Phase 0 abort enforcement (parity gate V2, MAE reference check) is real.

## Cross-gate referrals accepted from `lookahead-auditor` pass 01

Both were referred to this gate as completeness rather than causality issues.

| Item | Adjudication |
|---|---|
| Gate V10 (fires on the first losing flip) covered only `COND_1.00`, leaving the `COND_0.75` walk unverified | **FIXED** — extended to both variants; gate count 27 → 28. |
| `validate.py` defines a `V13` beyond the V1–V12 table named in SPEC | Same as W1 above; **FIXED**. |

## Disposition

Three findings plus two referrals, all remediated. The study was re-run; gates
**28/28**, verdict unchanged at `G4_NO_USEFUL_EDGE`. A pass-02 re-check is
required to close this gate.

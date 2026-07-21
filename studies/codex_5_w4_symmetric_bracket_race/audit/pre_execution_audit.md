# Look-Ahead & Timestamp Audit — Pre-Execution Re-Audit

**Date:** 2026-07-17T14:54:33.5418815-05:00  
**Scope:** `studies/codex_5_w4_symmetric_bracket_race/{SPEC.md,config.json,input_freeze.json,run_study.py,tests/test_bracket_race.py}`; the repaired W4 specification, original policy runner/policy/input contract; frozen model manifest, score files, original 2025/2026 trade files, reconciliations, pre-execution and completion audits; and `data/raw/NQ_v0_1s_{2025,2026_ytd}.parquet` timestamp/index contracts.  
**Mode:** mandatory narrow read-only static re-audit before rerun; neither tests nor study executed.  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — PRE-EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

The revised economic summary satisfies the frozen research contract. Its cost-adjusted breakeven rate now uses conditional gross winner and loser bracket magnitudes and therefore remains algebraically consistent with realized expectancy when ATR covaries with outcome. Primary first-touch and tail-path logic are unchanged and remain clean.

## Critical findings

None.

## Warnings

None.

## Narrow economic re-audit

### Conditional breakeven formula — clean

`run_study.py:265-269` implements `p_BE = (L + C) / (W + L)`, where `W` is average gross PT bracket value, `L` is average gross SL bracket magnitude, and `C = $10`. This follows directly from:

```text
p(W - C) + (1 - p)(-L - C) = 0
p = (L + C) / (W + L)
```

`run_study.py:282-290` selects resolved PT and SL cohorts separately and computes `W` and `L` from each cohort's `gross_bracket_value_usd`. Unresolved rows do not enter either conditional mean. Missing winner or loser cohorts propagate `NaN` rather than inventing a rate. The denominator is finite and positive before division.

`run_study.py:310-315` exports both conditional gross magnitudes alongside the breakeven rate, edge in percentage points, and realized net expectancy, making the calculation auditable. The sign of `pt_first_rate_resolved - p_BE` matches the sign of sample net expectancy because both use the same resolved cohort rate, conditional magnitudes, and fixed cost.

`tests/test_bracket_race.py:96-98` adds deterministic unrun coverage: `W=300, L=280` yields `0.50`, while equal `W=L=250` with `$10` cost yields `0.52`. The test was statically inspected and not executed.

`SPEC.md:42-51` documents the same conditional-cohort formula and explicitly states the ATR/outcome-covariance rationale. No pooled mean ATR remains in the summary path.

## Clean checks

- **Frozen population:** exactly 3,246 immutable 2025 entries and 1,137 immutable 2026 entries (4,383 total), with unique entry timestamps and material long/short and ETH/RTH representation.
- **Frozen fields and provenance:** entry timestamp/open, direction, checkpoint ATR, session, and scheduled horizon are consumed directly from hash-frozen original repaired W4 trade rows. Upstream strict regime-local first-crossing generation and complete candidate/trade accounting remain covered by the repaired-policy completion audit.
- **Raw entry reconciliation:** all 4,383 entry timestamps exactly match raw UTC one-second indexes and all stored entry opens match raw opens with maximum absolute error `0.0`; `run_study.py:123-128` enforces this at runtime.
- **Timestamp semantics:** raw one-second `ts_event=t` is the open label for `[t,t+1s)`. Both raw indexes are timezone-aware UTC, strictly increasing, and duplicate-free. No aggregated-bar `ts_init_delta` applies.
- **Primary race:** entry bar forward, high/low first-touch scan continues to raw-year end without regime, timeout, scheduled-exit, W4, or portfolio termination (`run_study.py:132-178`).
- **Bracket geometry and ties:** long/short PT/SL geometry is symmetric. Conservative same-bar ties are SL-first; decisive ties require strictly larger favorable normalized overshoot.
- **No future use:** primary classification stops on the first touching bar and never consults a later bar or terminal outcome field.
- **Unresolved handling:** unresolved paths retain null resolution and `NaN` PnL, remain in all-trade PT rates, and are excluded from resolved economics.
- **Fixed PnL and PF:** resolved PnL remains `± bracket × atr_at_checkpoint × $20 - $10`; PF uses summed net PT gains divided by absolute summed net SL losses (`run_study.py:167-178,282-315`).
- **Economic breakeven:** conditional `W/L` formula is correct, outcome-covariance aware, and sign-consistent with realized sample expectancy (`run_study.py:265-269,282-315`).
- **Splits:** combined, year, long/short, ETH/RTH, and four direction-session intersections remain explicit (`run_study.py:251-262`).
- **Time/excursion measures:** pre-resolution excursions exclude the resolution bar; through-resolution measures include it; resolution time uses exact raw timestamps.
- **Tail horizon:** path range excludes the scheduled exit fill bar's OHLC range and horizon PnL uses its open. Post-resolution labels require resolution strictly before the horizon.
- **Tail ordered events:** entry/2A same-bar order remains explicitly ambiguous; SL recovery begins after the SL resolution bar.
- **Fixed sensitivity:** only symmetric 1.00/1.25/1.50 ATR races and frozen conservative/decisive tie policies are accepted; no result-dependent selection exists.
- **2025 seal:** 2026 remains gated by exact zero-error 2025 reconciliation, dependency hashes, and work-artifact hashes.
- **Frozen dependency hashes:** all nine declarations match current bytes exactly—both trade files, raw years, score files, original policy, original completion audit, and frozen model manifest.
- **Authorization binding:** runtime authorization binds the exact current runner, config, freeze, and this clean audit.
- **No execution:** neither tests nor study were run during this re-audit.

## Sign-off

Scope hash (SHA-256 of ordered `path + file SHA-256` records): `5e8525744434fb8c7bc17cd3a6b19abd95a12fca5280d1ca844558f415ff07c7`

Authorized source hashes:

- Runner: `c8adf18abfb291ea0f14c7bf58f979ffa94399f0f0bcbd010f0613e55113659b`
- Config: `527811089025d4eb077967273bb4a9b7479b80a7a249b9ff21db7b214ce74691`
- Freeze: `fa1cd55fe8ac88bb1052b8355ebd15f1336756f27d7b815276399250a8e08d86`
- Specification: `a0e32b3aa3936bc24219abcf93f1c2d4dfbc6f3043875e41e50c59767d9bfb8a`
- Unrun tests: `51e6889f0ea6c0eb9ea59f3ed6e6f48045c277f99bd85d75d4bab2b30e7fc8da`

---

*Audit complete. Findings reflect read-only static analysis and frozen-artifact reconciliation. No study code, config, freeze, or tests were modified.*

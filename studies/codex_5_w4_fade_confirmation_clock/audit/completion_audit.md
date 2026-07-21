# Completion Lookahead and Reproducibility Audit

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope and authorization

Audited the completed `codex_5_w4_fade_confirmation_clock` study, including the specification, frozen configuration, policy freeze, runner, tests, pre-execution audit/authorization, both yearly work products and reconciliation seals, all combined result artifacts, run manifest, and final report.

The pre-execution authorization remains exact and current:

- runner SHA-256: `89956e5a280cfacea774882d51be06f02dc835a4acdda76d0f73deb92b907038`
- config SHA-256: `0fdbe5310e462c3a9c58369321e33c18b022e43ccd73c1053cd4b35cd3d6a8ca`
- freeze SHA-256: `ba47c2af356199f4ab16f018018b9378e83aea3d93b42661befcca75943fedac`
- pre-execution audit SHA-256: `dd3cd7caf6bd39990aa9c1441d267fb4d9bce8257d9efd256384791745b6b0ca`

The frozen raw, repaired-trade, and upstream dependency hashes still match the policy freeze. W4 was not retrained or rescored, the repaired 4,383-entry set was unchanged, and exactly the three predeclared A/B/C policies were executed. No grid, alternate clock, extra stop, or post-flip retained-profit rule was introduced.

## Independent full replay

I independently replayed all **4,383 baseline trades** and all **13,149 policy paths** directly from the frozen raw 1-second bars and repaired source trades, without relying on the study's generated summaries.

The independent replay produced **zero discrepancies** for:

- entry, aligning-flip, timeout, scheduled-decision, and actual fill timestamps;
- first-available-open fills across raw timestamp gaps;
- baseline 1.50 ATR stop paths and exact repaired baseline reconciliation;
- A/B 1.25 ATR and C 1.00 ATR pre-flip stop paths;
- exact-300-second flip equality and pre-flip to post-flip stop transitions;
- qualification using only completed bars with `ts_event < timeout`;
- timeout-bar stop activity and strictly-next-open A/C timeout fills;
- B's 0.75 ATR qualification, no early profit-taking, timeout activation, gap fills, persistence after a later aligning flip, and loss-first ambiguous-bar rule;
- scheduled opposing-flip boundary priority and exclusion of its bar range;
- direction-adjusted points, $20/point multiplier, one $10 round-trip cost, net-PnL deltas, and all requested causal flags.

I also independently reconstructed every 5-minute path diagnostic. All 4,383 rows matched for completed-bar MFE, mark-to-market PnL, alive state, exact flip-window classification, 0.75 ATR qualification, direction/session/year, and original outcome grouping.

## Seals, cardinality, and combined artifacts

- 2025 seal: **3,246 diagnostics / 9,738 paired policy rows**, zero blocking errors; both artifact hashes and all frozen dependency hashes match.
- 2026 seal: **1,137 diagnostics / 3,411 paired policy rows**, zero blocking errors; execution is tied to the exact clean 2025 predecessor artifacts and dependency seal.
- Combined outputs: **4,383 diagnostics / 13,149 paired policy rows** with non-null integer-nanosecond timestamps.
- The combined diagnostic and policy-difference files equal the exact ordered concatenation of their sealed 2025 and 2026 yearly files.
- Every output SHA-256 recorded by `run_manifest.json` matches its current artifact.

## Summary and report verification

I independently recomputed every row and field in:

- `confirmation_clock_policy_results.parquet`
- `confirmation_clock_diagnostic_summary.parquet`

Trade counts, mean/total net PnL, profit factor, win rate, stop rate, timeout counts, later-flip counts, baseline-survived-to-flip counts, B continuations, protected stops, clipped planned winners, converted planned losers, and reduced stop-before losses all match exactly across overall, year, direction, and session splits.

Every number and material claim in `final_report.md` was traced to the sealed trade-level or path-level outputs. This includes the yearly and combined Policy A improvements, Policy B's 2025/2026 comparison with A, Policy C's failed 2026 confirmation, all direction/session results, winner flip-time quantiles, five-minute outcome geometry, the 371 retrospectively qualified baseline survivors, the 339 actual B continuations, and the qualified-cohort winner clipping/giveback calculations.

The report clearly separates causal policy results from retrospective path diagnostics, labels 2026 as selection-isolated final testing, does not use 2026 to retune a parameter, and explicitly states the confounding between A's tighter pre-flip stop and confirmation timeout. The decision `TIMEOUT_EXIT_PROMISING` is supported by the predeclared Policy A package improving net PnL in both 2025 and untouched 2026 while the report appropriately stops short of production or NT validation claims.

The earlier report-encoding warning was corrected before completion. The final report contains no Unicode replacement characters and its current SHA-256 is `da2114cc9347cd593bf4ed72f6accf69c3f19dd111890dcea961839abf95b0f0`.

## Tests and contract limitation

- Repository study tests: **12 passed**.
- Research contract: causal **1-second OHLC research simulation**, not NT-native executable validation or tick-level touch-order proof.
- Ambiguous same-bar stop/favorable movement is handled by the frozen conservative loss-first rule; gap fills use the actual first available raw open.

The completed study is reproducible under its frozen inputs and passes the repository's lookahead, sequencing, time-isolation, and reporting gates.

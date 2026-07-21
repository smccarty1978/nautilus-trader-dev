# Look-Ahead & Timestamp Audit — Pre-Execution Re-Audit

**Date:** 2026-07-17T15:41:45.1941511-05:00  
**Scope:** `studies/codex_5_w4_two_contract_runner/{SPEC.md,config.json,input_freeze.json,run_study.py,tests/test_runner.py}`; frozen symmetric-bracket results/manifest/completion audit; frozen Policy A results/opportunities/manifest/completion audit; original repaired W4 lineage; and raw 2025/2026 Databento one-second timestamp contracts.  
**Mode:** mandatory full-scope read-only static re-audit after serialization remediation; no test or study execution.  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — PRE-EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**
**Notes:** **2**

## Summary

- Critical: 0
- Warning: 0
- Note: 2

All four prior blocking findings remain closed. The only new implementation change converts `floor_armed_ts` to pandas nullable `Int64` after simulation and before Parquet writing. It preserves exact nanosecond integers and missingness without entering any causal, fill, tail, or economic calculation.

No test or study code was executed during this re-audit. The companion authorization binds the exact current runner, config, freeze, and this audit.

## Serialization remediation — clean

`run_study.py:247-249` builds the completed trade DataFrame and then replaces only `floor_armed_ts` with `pd.array(..., dtype="Int64")`. Every non-missing source value is `now = int(ts[i])`, taken directly from the raw nanosecond index at the arming event (`run_study.py:132,150-153`); every missing value is `pd.NA` (`run_study.py:128`). There is no float intermediary, datetime conversion, timezone conversion, resampling, division, or unit scaling.

The conversion is after all rows, tail diagnostics, protective diagnostics, exits, PnL, MFE, and giveback values are computed. No consumer in `simulate_year`, `summarize`, `summarize_baselines`, or `protective_output` uses `floor_armed_ts` for a decision or metric. It is serialization-only.

Nullable `Int64` also survives the intended work-file read and 2025/2026 concatenation as an integer/NA column, avoiding the prior mixed-object inference failure without rounding values near `1.7e18`. The failed/partial predecessor artifacts cannot bypass chronology: their stored dependency seal carries the prior runner/audit/authorization hashes, while `require_2025` recomputes and requires the current exact seal before 2026 (`run_study.py:341-348`). A fresh authorized 2025 run is therefore mandatory.

## Critical findings

None.

## Warnings

None.

## Prior findings — closure verification

### Closed [A4 / H2]: horizon and ambiguous exit bars contaminated MFE/giveback

`run_study.py:131-153` now applies exits in the required order:

- the horizon branch exits at the horizon bar open before the favorable excursion is calculated;
- an SL-first contract event exits both legs before the resolution bar's high/low is incorporated;
- an active floor exit occurs before `max_fav` is updated;
- only bars on which the runner remains live through the range update causal MFE.

Consequently `runner_max_available_mfe_atr` and the trade-summary giveback fields no longer include the horizon bar or an ambiguous initial-stop/floor exit bar. This matches `SPEC.md:43-46` and the frozen config value `stop_exit_bar_excursion = exclude_entire_ambiguous_exit_bar` (`config.json:16`).

Static deterministic coverage was added for a long initial-stop bar with a large favorable extreme, the horizon range, and a floor-exit bar with a new favorable extreme (`tests/test_runner.py:27-31,62-74`). The tests were inspected but not executed.

### Closed [H4]: initial-stop gap-through exits were credited at the trigger

The shared helper `stop_fill` applies the adverse open for both directions (`run_study.py:110-111`). It is now used by:

- Contract 1 through `contract1_fill_and_gross` (`run_study.py:114-118`); and
- the runner's shared initial-stop exit (`run_study.py:137-139`).

`simulate_year` obtains the exact frozen resolution bar's open, computes Contract 1's executable gap-aware exit, and combines it with the independently computed runner leg (`run_study.py:191-210`). Both legs therefore receive the same adverse open when still active at the shared initial stop.

The original fixed-level symmetric-bracket PnL remains unchanged in `pure_bracket_net_pnl_usd` and is emitted separately through `BASELINE_PURE_1_25_BRACKET` (`run_study.py:208,293-310`). It is no longer silently substituted for the new two-contract executable fill assumption.

Long and short initial-gap cases plus the Contract 1/runner parity are covered statically at `tests/test_runner.py:27-42`. Total PnL remains Contract 1 gross + runner gross − two fixed $10 costs (`run_study.py:200-210`).

### Closed [H1 / H2]: floor versus 2A/3A/4A same-bar order was forced

`floor_before_touch` now returns `(pd.NA, True)` when an active floor exit and a favorable-level first touch share a one-second timestamp (`run_study.py:178-183`). The nullable ordered labels and explicit ambiguity flags propagate to:

- tail diagnostics (`run_study.py:216-234`);
- protective trade-level evidence (`run_study.py:235-246`); and
- aggregate ambiguity counts for each of 2A, 3A, and 4A (`run_study.py:313-336`).

The future-clipped labels are `pd.NA`, not false, on ambiguous bars (`run_study.py:240-242`). Long and short deterministic 2A/floor same-bar cases are present at `tests/test_runner.py:91-103`; they were inspected but not executed.

### Closed [D1 / G]: Policy A was hash-listed but never reconciled or emitted

`reconcile_policy_a` loads frozen executed R0 opportunity rows and enforces exact 3,246/1,137 counts, entry-timestamp uniqueness, one-to-one chronological timestamps, direction, actual fill session, entry price, and checkpoint ATR (`run_study.py:91-107`). It also reconciles each year's trade count and total net PnL against the frozen Policy A summary row.

`simulate_year` joins each bracket entry to its exact Policy A row by unique entry timestamp and emits Policy A PnL, exit timestamp, and exit reason on every variant row (`run_study.py:186-210`). `summarize_baselines` then produces combined/year/direction/session/direction-session Policy A baseline rows, alongside the separately imported pure bracket (`run_study.py:293-310,359-365`).

The audit independently compared the additional shared fields available in both frozen sources—`regime_start_ns`, `confirm_flip_ns`, direction label, and secondary session label—and found exact equality in all 3,246 2025 rows and all 1,137 2026 rows. This completes the all-entry-key/field verification on the exact hash-frozen population.

## Notes

### NOTE 1 — `run_study.py:133-136, 165-166` retains a retrospective horizon-bar floor flag

`horizon_floor_same_timestamp` inspects the horizon bar range solely to label whether that later range would touch an armed floor; it does not affect exit price, exit reason, MFE, giveback, or PnL. Because the runner exits at the bar open, this is retrospective post-exit information, not a causal execution ambiguity. The field is safe as implemented but should remain described as a diagnostic, not as an available live event.

### NOTE 2 — `run_study.py:91-107` does not assert every redundant shared regime field at runtime

The runtime reconciliation enforces the decisive unique entry key and immutable entry fields. The audit independently verified the additional shared regime and label fields exactly, and all source bytes are hash-frozen, so this is not a result risk for the authorized run. Adding those redundant assertions and a dedicated Policy A reconciliation unit test would strengthen defensive coverage.

## Clean checks

- **Input freeze:** all eleven declared hashes match current bytes exactly: bracket results/trades/tails/audit/manifest, Policy A results/opportunities/audit/manifest, and both raw files (`input_freeze.json:5-17`; `run_study.py:26-36`).
- **Upstream completion:** both the symmetric-bracket and multi-candidate Policy A sources have passing completion audits and manifest-matched immutable artifacts.
- **Population:** the exact conservative 1.25A primary population is 3,246 in 2025 and 1,137 in 2026, with no unresolved bracket paths (`run_study.py:83-88`).
- **Entry provenance:** entry timestamp/open/direction/ATR/session, contract-1 outcome/resolution, and scheduled horizon are frozen audited bracket fields. Policy A matches one-to-one on exact entry timestamp and fields.
- **Raw timestamps:** both raw indexes are UTC-aware, strictly increasing, and duplicate-free. Databento one-second `ts_event=t` is the open label for `[t,t+1s)`. The first raw bar at or after a scheduled horizon is its market-exit bar.
- **Boundary sequencing:** the runner begins on the entry bar. Horizon-open exit preempts that bar's range. Contract 1 may continue after a runner horizon exit, and `final_exit_ts` is the later leg exit (`run_study.py:121-166,186-210`).
- **Before-PT SL priority:** SL-first resolution exits before all favorable/floor/arm processing on that bar and uses adverse-open gaps for both legs.
- **Arming:** a floor arms only after its bar completes and activates on `i + 1`; an arm-bar floor range is explicitly deferred (`run_study.py:149-153`).
- **PT/floor tie:** an imported PT resolution on a bar with an already-active floor is PT-first and defers the floor (`run_study.py:143-148`).
- **Floor geometry/fills:** long floors use low, short floors use high, and adverse gaps use the bar open (`run_study.py:110-111,127,142-148`).
- **Excursion causality:** horizon, initial-SL, and floor exit bars do not update causal runner MFE/giveback. PT and arming bars do update it because the runner remains active through those ranges under the frozen ordering policy.
- **Tail horizon:** first favorable-level touches scan `[entry, horizon)`, excluding the horizon bar (`run_study.py:169-175`). Imported PT-tail applicability and entry/2A ambiguity remain nullable where required.
- **Protective ambiguity:** same-bar floor/2A–4A order is never invented; nullable labels and explicit counts are retained at trade and summary levels.
- **Economics:** both legs use $20/point and one $10 round-trip cost. Total equals both gross legs minus $20; leg-level nets and baseline nets are separately auditable.
- **Baselines:** Policy A and the pure fixed-level bracket are separately emitted and are not conflated with the gap-aware two-contract result.
- **Variants/isolation:** only V0, V75_25, and V100_50 are accepted; all sequencing assumptions are config-frozen; no parameter grid or result-driven selection exists (`run_study.py:51-72`).
- **Splits/output:** combined, year, long/short, ETH/RTH, and all direction-session intersections are explicit. Required trade, tail, protective, variant-summary, and baseline-summary semantics are retained.
- **2025/2026 seal:** 2026 requires the exact clean 2025 dependency seal and exact hashes of all three 2025 work artifacts (`run_study.py:339-358`). Runtime freeze validation rechecks both raw years and all upstream inputs.
- **Authorization gate:** execution requires exact clean audit markers and an authorization JSON bound to current runner/config/freeze/audit hashes (`run_study.py:39-48`).
- **Serialization exactness:** `floor_armed_ts` is exported as nullable signed 64-bit nanoseconds; armed rows retain raw-index integer timestamps and unarmed rows retain missing values. The coercion occurs after causal computation.
- **No execution:** neither the tests nor study were run during this re-audit.

## Sign-off

Scope hash (SHA-256 of ordered `path + file SHA-256` records): `6ff92ebabb617bfba3aa299fcfb8388957ff64e07fd1a802d16e2ed3f9c9fdc6`

Authorized source hashes:

- Runner: `221dbc50f9af44ca8c608958c3c0017753d8ae82ab90560bddc52b8fe3b4fa8b`
- Config: `a50eb8ec853ca3c6da2e33542d89aa917821813b2235615e6af838a2c18817e3`
- Freeze: `6f466c0a540d0ecbe539a38fc4cfc48336648f065b0e808f3edfa625c614fa84`
- Specification: `733899da355da162b81a0535cabfc480a6f07bf79384327bb883a8bca2dc8f09`
- Unrun tests: `87ef0b1ec8b6863d74807c87474d0f378fb4e28eaf2fb6e30fddfff186464f7b`

---

*Audit complete. Findings reflect read-only static analysis and frozen-artifact checks. No implementation, config, freeze, test, or result file was modified.*

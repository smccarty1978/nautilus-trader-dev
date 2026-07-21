# Look-Ahead, Timestamp, and Results Completion Audit

**Date:** 2026-07-17T15:56:41-05:00  
**Study:** `CODEX_5_X_ORIGINAL_W4_TWO_CONTRACT_RUNNER`  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS - COMPLETION AUDIT VERIFIED**  
**Findings:** **0 CRITICAL, 0 WARNING**  
**Notes:** **2**

## Summary

- Critical: **0**
- Warning: **0**
- Note: **2**
- Tests: **15 passed**

The implementation, sealed artifacts, report, and finalized manifest are
causally and numerically clean. Independent raw-bar reconstruction reproduced
all 13,149 variant executions, both 4,383-trade baselines, all required metrics,
tail/protective semantics, and the decision. Full re-audit confirmed that both
prior warnings were resolved without changing code or result data.

## Audit scope

Inspected in full:

- `SPEC.md`, `config.json`, `input_freeze.json`, and `run_study.py`;
- `tests/test_runner.py`;
- `audit/pre_execution_audit.md`, including its representation and closure of
  the initial 2-CRITICAL/2-WARNING iteration, and
  `audit/pre_execution_authorization.json`;
- both `reconciliation_*.json` seals and all six year-specific `_work`
  Parquets;
- all four final Parquets, `results/final_report.md`, and
  `results/run_manifest.json`.

The audit also inspected or independently reconciled every hash-frozen direct
dependency: symmetric-bracket results/trade diffs/tail diagnostics/completion
audit/manifest; Policy A results/opportunities/completion audit/manifest; and
both raw Databento one-second files.

## Critical findings

None.

## Warnings

None.

## Resolved findings

- `results/final_report.md:94-96` now states that 36.76% is 772/2,100
  ordered labels and explicitly excludes one of the 2,101 eligible paths
  because entry and +2A share an order-ambiguous one-second bar. This exactly
  matches the nullable tail artifact.
- `results/run_manifest.json:2-35` is valid JSON with status `COMPLETE`. It now
  records study/contract/decision/population metadata, 2025/2026 isolation,
  test command/count/file hash, pre-execution audit and authorization hashes,
  both year-seal hashes, a non-circular completion-audit path and required clean
  status, all four result hashes, and the final-report hash.

## Notes

### NOTE 1 - `run_study.py:133-136` retains a retrospective horizon-bar floor flag

`horizon_floor_same_timestamp` reads the range of a bar whose open already
exited the runner. The field is strictly diagnostic and cannot alter exit,
price, PnL, causal MFE, or giveback. The report correctly calls the 10/7 counts
retrospective at `results/final_report.md:133-135`. It must remain excluded from
live/causal event claims.

### NOTE 2 - `run_study.py:91-107` omits redundant Policy A regime assertions at runtime

Runtime reconciliation asserts the decisive unique entry timestamp and entry
fields plus yearly count/PnL. It does not redundantly assert every shared
regime field. This audit independently verified `regime_start_ns`,
`confirm_flip_ns`, direction label, and secondary session label on all 4,383
rows, and all source bytes are frozen. This is defensive coverage only, not a
current result risk.

## Independent verification

### Authorization, freezes, manifest, and 2025 isolation

- All eleven `input_freeze.json` dependency hashes match current bytes.
- Runner, config, freeze, and final pre-execution-audit hashes match
  `pre_execution_authorization.json` exactly.
- The final pre-execution audit documents closure of the initial two critical
  and two warning findings and authorized the exact executed runner with zero
  critical and zero warning findings.
- Both work seals report zero blocking errors; every one of the six work
  artifact hashes matches.
- The 2025 seal has 3,246 unique trades. The 2026 seal has 1,137 and carries the
  exact current 2025 runner/config/freeze/audit/authorization/raw dependency
  map. The 2026 path requires that seal and all three 2025 artifact hashes.
- The manifest's runner, config, freeze, test file, pre-audit, authorization,
  2025 seal, 2026 seal, four Parquet, and final-report hashes all match current
  files.
- The manifest completion-audit path resolves to this file without a circular
  self-hash. Its required status is `PASS_WITH_0_CRITICAL_AND_0_WARNING`, which
  matches this audit.
- Manifest contract, decision, population, development year, and isolated year
  match the specification/config/results exactly.
- No result-dependent or 2026-dependent parameter-selection branch exists.
  Only V0, V75_25, and V100_50 are accepted.

### Population and baseline reconciliation

- The conservative 1.25A bracket population is exactly 4,383 unique entries:
  3,246 in 2025 and 1,137 in 2026, with no unresolved primary races.
- Every study entry matches the frozen bracket row on trade ID, entry
  timestamp/open, direction, session, checkpoint ATR, contract-1 outcome and
  resolution, and frozen opposing-flip horizon.
- Every R0/Policy A row matches one-to-one on entry timestamp/open, direction,
  ATR, session, exit timestamp/reason, and net PnL. The yearly Policy A totals
  are -$8,114.842751 and +$17,988.060997, totaling +$9,873.218246.
- The imported pure bracket matches every frozen `net_pnl_usd` value and totals
  -$46,753.452654.

### Raw one-second execution reconstruction

All 13,149 `(variant, trade)` paths were independently replayed from raw OHLC
arrays without calling the study runner. There were zero discrepancies in:

- runner exit timestamp, price, or reason;
- long/short stop geometry and adverse-open gap fills;
- horizon-open precedence and exclusion of the horizon bar's range;
- shared initial-SL priority over favorable events;
- post-arming-bar floor activation;
- PT1/active-floor deferral;
- floor exit-bar range exclusion;
- runner MFE, realized ATR, giveback, hold time, arming state/timestamp, and all
  ambiguity/deferred flags.

Contract 1 independently uses the same adverse-open initial-stop gap fill as
the runner. There were zero PnL identity errors:

```text
contract1 gross = direction * (contract1 exit - entry) * $20
runner gross    = direction * (runner exit - entry) * $20
each leg net    = leg gross - $10
total net       = both leg gross values - $20
                = contract1 net + runner net
```

`final_exit_ts` equals the later leg exit on every row. The 309 paths where the
runner horizon precedes Contract 1 resolution are represented correctly.

### Tail and protective semantics

- Final trade and tail Parquets are dataframe-identical to the ordered
  2025+2026 work concatenations.
- Tail applicability, 2A/3A/4A reach, additional MFE, return-to-entry label,
  entry/2A ambiguity, maximum horizon MFE, capture, and giveback match the
  frozen audited tail artifact on every row.
- Independent raw scans reproduced every first 2A/3A/4A touch and every
  floor-before-touch/same-bar label for both years.
- All unavailable tail fields remain null rather than false. The sole
  applicable nullable ordering is one entry/+2A ambiguous trade: 2,101
  eligible tails, 2,100 ordered labels, 772 true, and one null. The remediated
  report discloses those exact denominators.
- Floor/+2A, +3A, and +4A same-bar ambiguity counts are zero in this
  population, so their corresponding clipped labels are fully ordered.
- `floor_armed_ts` is nullable `Int64`; armed timestamps retain exact raw
  nanosecond values and unarmed rows remain missing.
- All 8,766 protective trade rows reconcile to protected-runner gross minus V0
  gross. Saved/lost decomposition, clipped labels, giveback-avoided flags, and
  all six summary rows reproduce exactly.

### Metrics, splits, and report claims

- `w4_pt_runner_policy_results.parquet` contains exactly 55 unique rows: five
  policies/variants times combined, two year, two direction, two session, and
  four direction-session splits.
- Independent metric reconstruction found zero mismatches for trade counts,
  PnL, mean, profit factor, win rate, drawdown, PT/SL rates, runner
  rates/contributions, costs, and average winner/loser fields.
- Final row counts are exact: 13,149 trade rows; 13,149 tail rows; 8,766
  protective trade rows plus six protective summaries; and 55 policy rows.
- Every material numerical report claim was traced to the sealed Parquets,
  including the compact comparison, 2025/2026 reversal, two-leg decomposition,
  direction/session tables, short-RTH pocket, tail rates and quantiles,
  protective-floor table, one conservative PT/SL tie, 97/97 arming deferrals,
  10/7 retrospective horizon flags, zero PT/floor and floor/tail unordered
  events, and the 309 horizon-before-contract-1 paths.
- The label `PT_RUNNER_FAILS` is supported: every two-contract variant is
  negative combined and in 2025, the best combined variant remains worse than
  the pure bracket and Policy A, and protected-runner contribution reverses
  between years. The report appropriately rejects selection from 2026 or the
  short-RTH pocket.

### Output and deliverable completeness

- All five output hashes in the finalized manifest match current files.
- Required data files, report, manifest, seals, work artifacts, tests, audit,
  authorization, config, freeze, and specification are present.
- The exact deliverable set is complete and provenance-bound.

## Tests

Executed read-only with bytecode and pytest caching disabled:

```text
...............                                                          [100%]
15 passed in 0.35s
```

## Clean checklist

- A/F: UTC-aware, strictly increasing, duplicate-free raw one-second open
  labels; horizon market exits use the matching open before range.
- B/C/D: no feature look-ahead, label leakage, retraining, train/serve skew, or
  2026-driven selection exists in this diagnostic path.
- E/H: high/low stop detection, one-second resolution, adverse gap opens,
  horizon/SL/floor ordering, and independent two-leg lifecycle all verified.
- G: raw gaps are preserved; no forward/back fill or synthetic bar path is
  introduced.
- Baselines: exact frozen Policy A and bracket reconciliation completed.
- Results: row counts, schemas, identities, splits, metrics, diagnostics,
  report, manifest, decision, and deliverable completeness verified.

---

*Audit complete. Findings reflect read-only static analysis plus independent
read-only raw-data reconstruction; the study pipeline/backtest was not rerun.
Scope hash:
`ba9881c897d89bbcf980acb441716ffd70a06a7ae2c9255dc657b6d80bcfb0d8`
(SHA-256 over 34 sorted study/frozen-dependency path-hash records, excluding
this audit file). No implementation, result, report, manifest, config, freeze,
test, or upstream file was modified.*

# Look-Ahead, Timestamp, and Completion Audit

**Date:** 2026-07-17T08:27:25-05:00  
**Study:** `CODEX_5_X_W4_MULTI_CANDIDATE_REENTRY`  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — COMPLETION AUDIT VERIFIED**

## Summary

- Critical: **0**
- Warning: **0**
- Note: **0**
- Tests: **10 passed**

The causal study results, sealed populations, reconstructed executions, metrics,
and decision are internally consistent. No look-ahead, timestamp misuse,
candidate-state error, trade-path error, reconciliation failure, result-hash
mismatch, or 2026-driven parameter-selection path was found. Narrow
re-verification confirmed that the initial provenance warning and terminology
note were resolved without changing code or result data.

## Audit scope

The following study artifacts were inspected in full:

- `SPEC.md`, `config.json`, `input_freeze.json`, and `run_study.py`;
- `tests/test_multi_candidate.py`;
- `audit/pre_execution_audit.md` and
  `audit/pre_execution_authorization.json`;
- both `reconciliation_*.json` seals and all ten year-specific `_work` Parquets;
- all five final result Parquets, `results/final_report.md`, and
  `results/run_manifest.json`.

Direct frozen dependencies were also inspected or independently reconciled as
needed: both raw one-second files, both repaired atlases and W4 score streams,
both frozen candidate and trade files, Policy A isolation trade diffs, prior
PR10/PR30 trade diffs and policy results, the prior completion audit and
manifest, and the upstream established-fade runner and policy.

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Resolved findings and narrow re-verification

- `results/final_report.md:14` now correctly states that the 11,812 strict
  crossing candidates comprise 4,767 sequence-1 crossings and 7,045 later
  recrosses.
- `results/run_manifest.json:2-11` now records the completion-audit path, the
  exact initial audit SHA-256
  `c24210bd240a7905265e4b45553827ca7acc2b5f55a4fcf9309c5a45e7aa67fa`,
  the initial 0/1/1 findings, and their resolution.
- The manifest audit path resolves to this file, and the recorded initial hash
  matched the pre-update audit exactly.
- The revised report SHA-256 is
  `8c1a3b7fbac595d156ab41e57c52e29a9ba999bcafd507fb78c4ddab17a77fc3`
  and matches `results/run_manifest.json:28`.
- All five result-Parquet hashes remain unchanged and valid. No code or result
  data changed during resolution.

## Independent reconstruction results

### Frozen inputs, authorization, and year isolation

- Every one of the 16 hashes in `input_freeze.json` matches the current frozen
  dependency.
- Runner, config, freeze, and pre-execution-audit hashes exactly match
  `pre_execution_authorization.json`.
- Every 2025 and 2026 `_work` artifact matches its year seal.
- The 2026 seal retains the exact 2025 dependency map and the sealed 2025
  artifact hashes required by `run_study.py:780-806`.
- The policy set is exactly R0/R10/R30 with delays 0/10/30, zero virtual-PnL
  threshold, fixed stops, fixed 300-second timeout, and no direction/session
  selection rule. The runner contains no result-dependent or 2026-dependent
  parameter-selection branch.

### Candidate generation and opportunity termination

The complete checkpoint streams were independently replayed against raw
one-second highs/lows for both years. There were zero errors in:

- strict `previous_score < threshold <= current_score` transitions;
- absence of above-threshold plateau duplicates;
- sequence numbering within every opportunity;
- causal established-filter eligibility;
- exact first-candidate membership;
- inclusive 1,800-second horizon treatment;
- permanent termination at the first later ineligible checkpoint, regime end,
  or score-horizon end; and
- exclusion of later crossings after termination.

Counts reconcile exactly: 8,682 candidates/3,530 opportunities in 2025 and
3,130 candidates/1,237 opportunities in 2026. Candidate 1 reconciles to all
4,767 frozen candidates with zero timestamp, price, direction, session, score,
threshold, ATR, or regime mismatches.

### Gate observations and delayed fills

Every evaluated R10/R30 response row was independently checked against raw
bars. There were zero gate-time, completed-mark, virtual-PnL, approval-class,
or delayed-fill mismatches. The mark is always the latest close whose
`[ts_event, ts_event + 1s)` interval completed by the gate; approved entries
always use the first available raw open strictly after the gate. Exactly-zero
virtual response is accepted. Crossings at or before the active gate are not
queued, and terminal regime/opportunity conditions precede response approval.

### Policy A management and overlap

All 8,868 executed rows across R0/R10/R30 and both years were independently
replayed from raw one-second OHLC bars. Exit timestamp, exit price, and reason
matched on every trade. Verified mechanics include:

- 1.25 checkpoint-ATR pre-alignment stop and 1.50 ATR post-alignment stop;
- stop touch from high/low, conservative gap-through fill, and entry-bar stop
  activation;
- timeout equal to actual accepted fill plus exactly 300 seconds;
- aligning flip at the timeout treated as confirmed;
- timeout fill at the first raw open strictly after the decision, with the
  stop active through the decision-labelled bar;
- opposing-flip next-open exit before that fill bar's range; and
- stop-bar occupancy and market-open release in the R10/R30 global overlap
  rule.

Gross points, $20/point conversion, $10 round-trip cost, and net PnL matched on
all executed trades; all nonexecutions carry zero opportunity PnL.

### Baseline and prior skip-forever reconciliation

- R0 contains exactly 3,246 executions in 2025 and 1,137 in 2026.
- All 4,383 R0 rows match frozen Policy A on entry time/open, exit time/open,
  exit reason, direction, session, and net PnL. Total PnL is
  -$8,114.842750573298 in 2025 and +$17,988.060996803324 in 2026.
- The regenerated first-candidate-only PR diagnostic contains exactly 4,383
  rows for each delay. PR10 and PR30 each have zero discrepancies against the
  prior audited artifact for approval, rejection reason, delayed fill, exit,
  and PnL.
- Prior approvals/skips reconcile to 2,105/2,278 for PR10 and 1,811/2,572 for
  PR30. Prior PnL reconciles to -$10,918.304440 and +$4,299.203023.

### Outputs, metrics, accounting, and report claims

- Final generation audit, opportunity results, and trade diffs are byte-level
  hash-valid and dataframe-identical to the ordered 2025+2026 `_work`
  concatenations.
- All six Parquet/report hashes in `run_manifest.json` match current files.
- The 14,301 opportunity-policy rows have unique
  `(policy_id, opportunity_id)` keys; the five final Parquet schemas and all
  row counts are consistent.
- The 33 split-metric rows were rebuilt exactly for combined, year, direction,
  session, and direction-session splits, including trade/opportunity
  denominators, profit factor, win rates, stop/timeout rates, average
  winner/loser, and closed-sequence drawdown.
- Candidate, opportunity, change-attribution, and prior-comparison accounting
  reconciles to the authoritative opportunity/evaluation rows, including
  explicit zero-count classes.
- All material numerical claims in `final_report.md` were traced to the sealed
  Parquets. In particular, R10 changes R0 by +$15,792.799058 in 2025 and
  -$11,265.344568 in 2026; the combined +$4,527.454487 result therefore does
  not support promotion. R30 underperforms R0 globally. The decision label
  `REENTRY_RECOVERS_FIRST_CROSSING_DAMAGE`, together with its explicit
  instability/no-promotion caveat, is supported by the frozen results.

## Tests

Executed read-only with pytest cache and bytecode disabled:

```text
..........                                                               [100%]
10 passed in 0.39s
```

## Clean checklist

- A/F: raw timestamps are explicitly open-labelled; completed-close marks,
  strict post-decision opens, UTC-aware indices, and CT session classification
  were verified.
- B/C/D: no feature look-ahead, future-shift feature, retraining, rescaling,
  random split, train/serve skew, or 2026-dependent policy selection exists in
  the audited path.
- E/H: entry timing, high/low stop detection, one-second resolution, gap fills,
  next-open market fills, re-entry consumption, and global overlap were
  verified.
- G: raw gaps are preserved rather than filled; empty synthetic minutes are
  not introduced into the one-second replay.
- Reconciliation: frozen candidate 1, R0/Policy A, and prior PR10/PR30 all pass
  row by row.

---

*Audit complete. Findings reflect read-only static analysis plus independent
read-only reconstruction; no backtest or study pipeline was rerun. Scope hash:
`5c6e3ee6dd7650a6a9022cdbeb7144023cc64ad7456afa8562b4302a8ffde304`
(SHA-256 over 45 sorted study/frozen-dependency path-hash records, excluding
this audit file).*

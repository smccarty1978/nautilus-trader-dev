# Look-Ahead, Timestamp, and Completion Audit

**Date:** 2026-07-17T10:44:07.9413095-05:00  
**Study:** `CODEX_5_X_W4_STREAMING_LIFECYCLE`  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — COMPLETION AUDIT CLEAN**  
**Findings:** **0 CRITICAL, 0 WARNING, 0 NOTE**

## Scope and method

The full current pipeline was audited:

- `SPEC.md`, `config.json`, `input_freeze.json`, `run_study.py`, and the complete
  test file;
- pre-execution audit and exact authorization;
- both year reconciliation seals and all ten `_work` Parquets;
- all six final Parquets, `final_report.md`, and `run_manifest.json`;
- all frozen upstream candidates, opportunity/policy results, repaired W4
  scores and atlases, runtime helpers, raw one-second files, upstream runner,
  manifest, and completion audit referenced by the freeze.

Static review was supplemented by independent read-only reconstruction. The
audit did not call the study runner or modify code/results. It independently
aggregated raw one-second bars, rebuilt the one-minute EMA regime timeline,
replayed S1-S4 bar by bar, rebuilt overlap exposure, counterfactual exits,
metrics, drawdowns, and report arithmetic, and compared them with every sealed
artifact.

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Frozen inputs, authorization, and year isolation

- Every digest in `input_freeze.json` matches: 11,812 candidate rows, upstream
  opportunity/policy results, upstream runner/audits/manifest, all three runtime
  helpers, both repaired atlases, both W4 score streams, and both raw files.
- The frozen population is exactly 8,682 candidates/3,530 opportunities in
  2025 and 3,130/1,237 in 2026: 11,812 candidates and 4,767 opportunities total.
- Current runner/config/freeze/audit hashes match
  `pre_execution_authorization.json`; imported execution code and both years of
  inputs are revalidated before either year runs (`run_study.py:41-93`).
- The 2025 and 2026 seals both retain the authorized runner/config/freeze/audit
  and authorization hashes. Every one of their ten work-artifact hashes
  matches the current file.
- 2026 requires the unchanged clean 2025 seal before loading its raw data
  (`run_study.py:635-664`). No result-dependent or 2026-dependent policy branch
  exists. Policies, delays, stops, costs, and year roles remain exactly frozen.

## Candidate causality, gates, and consumption

- All 11,812 frozen candidate rows retain unique `(opportunity_id,
  candidate_seq)` keys and stable global chronological order.
- The 33 candidates emitted exactly at the inclusive 1,800-second horizon all
  have fills before their confirming flip and retain immediate S1/S2/S3
  eligibility. S4 still requires completed confirmation before the opportunity
  boundary (`run_study.py:148-197`).
- Every persisted candidate evaluation was independently classified against
  its frozen candidate and raw bars. There were zero mismatches in acceptance,
  rejection reason, gate timestamp, completed mark, virtual response, entry
  timestamp, or entry open.
- S4 marks always use the latest one-second close whose interval completed by
  the +10-second decision. Accepted entries always use the first available raw
  open strictly later than that decision.
- Global cursor reconstruction reproduced candidate consumption exactly.
  Crossings during confirmation and while occupied were consumed rather than
  queued; after exits only decisions strictly later than the exit timestamp
  were eligible (`run_study.py:316-392`).

## Independent trade-path reconstruction

An independent raw-bar/EMA-regime replay reproduced every S1-S4 trade with zero
differences in candidate, entry timestamp/open, exit timestamp/price/reason,
net PnL, W4 source, or reversal source:

| Year | S1 | S2 | S3 | S4 |
|:--|--:|--:|--:|--:|
| 2025 | 4,008 | 4,186 | 4,355 | 2,275 |
| 2026 | 1,387 | 1,476 | 1,526 | 797 |

Verified path mechanics include:

- exactly one net position; no entry precedes the preceding exit;
- equality only for the declared S3 same-fill close/reversal transition;
- high/low stop detection at one-second resolution, entry-bar activation, and
  Contract-2 trigger/adverse-gap fill convention;
- pre-alignment 1.25 ATR and post-alignment 1.50 ATR stops anchored to actual
  fill and frozen checkpoint ATR;
- alignment at the timeout boundary taking priority, timeout at fill +300s,
  and exit at the first strictly later raw open;
- W4/scheduled open-timestamp exits before that bar's OHLC stop range;
- scheduled opposing-regime fallback from the independently reconstructed
  causal regime timeline;
- $20/point conversion and exactly $10 round-trip cost per trade.

The Contract-2 stop convention is explicitly disclosed in `SPEC.md:19-27` and
`final_report.md`; these results are correctly labeled OHLC research, not
NT-native stop-market/next-fill validation.

## W4Exit and W4Reverse

- Every W4 lifecycle signal belongs to the newly aligned regime, has direction
  opposite the open position, and fills before that regime's scheduled terminal
  flip (`run_study.py:200-208,261-283`).
- S2 contains 392 W4 exits; S3 contains 410. All signal candidate IDs/times/fills
  match frozen candidates.
- S3 contains 410 same-fill reversals with 410 unique source candidates. No
  candidate is reused, and each reversal entry equals its source exit fill.
- All 802 no-W4 counterfactual paths were independently rerun. Exit timestamp,
  reason, price, PnL, and `w4_exit_change_usd` match every trade row.
- S2 direct W4 change is -$8,860.597669. S3 direct change is -$8,105.597669.
  S3 reversal PnL is -$23,171.798460 from 114 winners, 292 losers, and four
  flat trades. The 802 detail rows and two summary rows in lifecycle accounting
  reconcile exactly.

## Baseline and overlap reconstruction

- All 4,383 BASELINE rows match frozen Policy A/R0 on opportunity/candidate,
  direction, entry, exit, reason, and PnL. Counts are 3,246/1,137 and combined
  PnL is +$9,873.218246 with zero difference.
- Candidate-vs-baseline occupancy was rebuilt: 3,655/1,405 candidates occur
  while baseline positions are open, including 558/243 opposite candidates.
- Independent first-candidate replay produces 3,524/1,236 trades and
  -$14,985.508268/+$7,301.263780. It reaches maximum gross exposure two and
  maximum absolute net exposure one, with 254/90 offsetting events.
- These values exactly match both year overlap audits and the combined final
  overlap artifact. Independent-minus-one-position PnL is -$17,557.462734.

## Attempts, metrics, and reconciliation

- All 60 attempt rows were independently rebuilt for combined, 2025, and 2026
  splits across five policies and four attempt buckets.
- Both pre-alignment stop labels are recognized. Prior-attempt PnL is assigned
  only to the first successful alignment bucket.
- Recovery requires a later attempt to bring cumulative opportunity PnL above
  zero after an early stop. Totals are S1 103, S2 109, S3 114, and S4 38; every
  classified frozen opportunity crosses from nonpositive to positive and is
  attributed to its first recovery attempt.
- Attempt counts, PnL, win rates, stop counts, alignment counts/rates, prior-PnL
  attribution, per-bucket recovery, and split-level recovery total all match.
- All 55 policy rows were independently recomputed for combined, year,
  direction, session, and direction-session splits. Opportunity/trade
  denominators, total/mean PnL, profit factor, both win rates, stop/timeout
  rates, W4/reversal counts, average winners/losers, costs, attempts, and
  closed-trade-sequence drawdowns match to displayed precision and underlying
  floating-point values.
- Final trade log equals the ordered 2025+2026 work concatenation. Both-year
  reconciliation contains the exact candidate/opportunity counts, zero
  baseline differences, and the disclosed S1-vs-R0 and S4-vs-R10 attribution.

## Manifest and report claims

- All seven manifest output hashes (six Parquets plus `final_report.md`) match.
  All schemas and row counts are consistent: 24,393 trades, 55 policy rows, 60
  attempt rows, 804 lifecycle rows, 5,062 overlap rows, and 10 reconciliation
  rows.
- Report arithmetic was traced to authoritative Parquets. In particular:
  BASELINE +$9,873; S1 -$36,646; S2 -$67,188; S3 -$72,482; S4 -$5,668; S1
  attempts 2+ -$55,865; S2-vs-S1 -$30,542; and S4-vs-BASELINE -$15,541.
- The report correctly separates per-trade and per-opportunity statistics,
  discloses closed-trade-sequence drawdown, and labels direction/session and
  attempt-3 observations retrospective rather than selected policies.
- `REENTRY_ADDS_CHURN` is supported: no streaming policy exceeds BASELINE,
  immediate re-entry underperforms BASELINE in both years, W4Exit/Reverse are
  worse, and S4 is negative in both development and selection-isolated years.
- No report statement promotes a 2026-selected threshold, direction/session
  filter, delay, or lifecycle rule.

## Tests

Executed with bytecode and pytest cache disabled:

```text
............                                                             [100%]
12 passed in 0.43s
```

---

*Audit complete. Findings reflect full static review, required tests, and
independent read-only reconstruction. Scope hash:
`f81eea0abf208f33b5963530b3a32f2863eb2df7eeb157e587ebbfea198374ec`
(SHA-256 over 44 sorted path/hash records, excluding this audit file).*

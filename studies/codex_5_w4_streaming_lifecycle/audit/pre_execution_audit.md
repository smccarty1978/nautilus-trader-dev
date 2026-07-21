# Look-Ahead, Timestamp, and Pre-Execution Audit

**Date:** 2026-07-17T10:25:36.0916264-05:00  
**Study:** `CODEX_5_X_W4_STREAMING_LIFECYCLE`  
**Auditor:** lookahead-auditor v1  
**Status:** **PASS — AUTHORIZED FOR FIRST TEST/EXECUTION**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Audit scope

This was a full read-only static re-audit before any new study code, unit test,
or result-producing path was executed. Scope included:

- `AGENTS.md`;
- the complete current `SPEC.md`, `config.json`, `input_freeze.json`,
  `run_study.py`, and `tests/test_streaming_lifecycle.py`;
- the complete upstream `codex_5_w4_multi_candidate_reentry` specification,
  configuration, freeze, runner, tests, audits/authorization, manifest, report,
  work artifacts, and final artifact schemas/content;
- sealed 2025/2026 candidates, opportunity/policy results, repaired W4 scores,
  repaired atlases, and raw one-second OHLC files;
- imported runtime helpers `CODEX_5_X_common.py`,
  `CODEX_5_X_run_established_fade.py`, and
  `regime_sequence_chop_context/reproduce_regimes.py`.

Every digest in the expanded `input_freeze.json` matches its current file. Raw
indices are UTC-aware, monotonic, and unique. This refresh additionally audited
the reporting-only `attempt_accounting()` patch and inspected the already sealed
first-run trade logs read-only. No test or study runner was run.

## Summary

- Critical: 0
- Warning: 0
- Note: 1

## Notes

### [H4] `SPEC.md:19-27`; `run_study.py:139-145,246-250` — Contract-2 OHLC stop label is not NT stop-market validation

The study deliberately preserves the already authorized prior one-second OHLC
research convention: a touched stop receives the trigger price unless the bar
opens adversely through it, in which case the adverse open is used. The SPEC
now states this exact rule and explicitly disclaims NT stop-market sequencing,
next-NT-fill validation, and exact intrabar ordering. The code and unexecuted
gap-fill test match that declaration.

This is an evidence-boundary note, not an unresolved execution bug: changing
the stop rule in this follow-up would break comparability with the frozen prior
Contract-2 simulations the user directed this study to retain. Results must
continue to be described as OHLC research labels, never NT-native executable
validation.

## Clean checks

### Frozen candidate causality and horizon boundary

- The runner consumes only the SHA-256-frozen 11,812 candidate stream; it does
  not retrain, rescore, alter thresholds, or recompute candidate features.
- The delay-0 gate at `run_study.py:156-164` rejects only a fill at/after the
  confirming flip. It no longer rejects a causally emitted crossing merely
  because its audited next-open fill is at/after the inclusive opportunity
  horizon.
- Read-only inspection found exactly 33 frozen candidates emitted at
  `candidate_time == opportunity_end_ts` under `score_horizon_ended`; all 33
  have `candidate_fill_time < confirm_flip_ns` and therefore retain upstream
  immediate eligibility under S1/S2/S3.
- Delayed S4 confirmation still must occur strictly before both alignment and
  the opportunity-ending boundary. Its completed-close mark and strictly later
  entry open remain causal.
- The new unexecuted test at `tests/test_streaming_lifecycle.py:70-75`
  deterministically specifies the inclusive immediate-entry boundary.

### Streaming state, timing, and lifecycle exits

- Candidates are processed once in stable global chronological order.
- Crossings during a +10-second confirmation wait and while a position is open
  are consumed by advancing the global cursor; none is queued.
- After a stop or timeout, scanning resumes only at candidate decisions
  strictly later than the exit timestamp.
- A single global position is enforced; equality is permitted only for the
  declared S3 same-fill close/reversal transition.
- Entry-bar stops use high/low at one-second resolution and apply the declared
  Contract-2 trigger/adverse-gap convention.
- Alignment at the timeout timestamp confirms. An unaligned timeout exits at
  the first available raw open strictly after the timeout decision.
- Open-timestamp opposite-W4 and scheduled-regime exits precede that bar's OHLC
  stop-range test.
- S2/S3 W4 signals must be emitted in the newly aligned regime, have the
  opposite entry direction, and fill before the regime's scheduled terminal
  flip.
- S2 consumes the exit candidate and resumes only on later crossings. S3 uses
  the same audited fill for close and reverse, consumes through that fill, and
  manages the reversal under the normal stop/timeout/alignment lifecycle.
- Post-alignment 1.50 ATR stop and opposing-flip fallback remain anchored to
  the actual entry fill and causal checkpoint ATR.

### Opportunity, overlap, and metric semantics

- Each trade retains the opportunity ID that emitted its entry candidate;
  executed attempts are numbered per opportunity.
- Direction/session splits use frozen sequence-1 opportunity metadata, while
  actual entry session is exported separately.
- The denominator remains all 4,767 frozen opportunities. Per-trade and
  per-opportunity means/win rates, stop/timeout rates, profit factor, costs,
  and closed-trade-sequence drawdown use disclosed and internally consistent
  populations.
- The independent first-candidate overlap reconstruction and one-position
  baseline are exported separately; the current policies are not mislabeled as
  independent trades.
- S2/S3 lifecycle accounting separates realized W4 exits, counterfactual
  original-regime exits, and reversal outcomes.
- The reporting-only patch at `run_study.py:459-504` recognizes both current
  `stop_before_aligned_flip` and legacy baseline `preflip_policy_stop` labels.
- PnL accumulated before the first successful aligning attempt is attributed
  only to that success attempt's bucket; it is no longer repeated across every
  bucket.
- Early-stop recovery requires a later attempt to bring cumulative opportunity
  PnL above zero. The first such attempt receives the bucket attribution, while
  the separately named total is repeated only as an explicit split-level total.
- Read-only reconstruction against the sealed first-run trade logs found
  103/109/114/38 recovered opportunities for S1/S2/S3/S4. Every classified row
  crosses from cumulative PnL at or below zero to above zero after an early
  stop; there are no already-positive false recoveries in the frozen results.
- The updated deterministic test at
  `tests/test_streaming_lifecycle.py:133-150` specifies attempt-2 attribution,
  the split-level total, and the -$100 prior-attempt PnL without executing it.

### Authorization and 2025/2026 isolation

- `input_hashes()` now covers the imported common helper, established-fade
  helper, dynamically imported regime reproducer, both repaired atlases, both
  W4 score files, both candidate files, both raw files, upstream policy/results,
  completion audit, manifest, and runner.
- `validate_contract()` recomputes that entire frozen map before each year.
  The freeze file itself is sealed by the authorization's `freeze_sha256`, so
  helper or data changes invalidate execution even if the main runner is
  unchanged.
- Authorization also seals the exact main runner, config, freeze, and this
  audit. Any change to those files makes `require_authorization()` fail closed.
- The 2025 seal includes runner/config/freeze/audit/authorization hashes plus
  2025 raw/candidates and every 2025 artifact hash. Before 2026, authorization,
  full current-input validation, and the 2025 seal are all checked, closing the
  previously identified between-year helper-change path.
- 2026 cannot run before a clean 2025 reconciliation exists and every sealed
  2025 artifact still matches.
- No R30 path, new response threshold, direction/session selection rule,
  retained-profit rule, MFE continuation, or 2026-driven policy branch exists.

## Authorization conclusion

The current static scope has zero CRITICAL and zero WARNING findings. It is
authorized for its first test/execution only while the exact runner, config,
freeze, imported dependency/data hashes, and this audit retain the digests
recorded in `pre_execution_authorization.json`.

---

*Audit complete. Findings reflect read-only static analysis and read-only
inspection of frozen artifact invariants; no test or study pipeline was run.
Scope hash: `0fa4f5e64c435ea550840a3d451db7e744a6240d00cb9b32a6bb5edc20a34b43`
(SHA-256 over 27 sorted path/hash records, excluding this audit file).*

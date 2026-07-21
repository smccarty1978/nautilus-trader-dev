# Pre-Execution Look-Ahead and Execution-Contract Audit

**Study:** `CODEX_5_X_W4_MULTI_CANDIDATE_REENTRY`

**Status:** **PASS — AUTHORIZED FOR FIRST TEST/EXECUTION**

**Findings:** **0 CRITICAL, 0 WARNING**

**Audit mode:** Full read-only static analysis before execution. No new study code, unit test, candidate collection, replay, or result-producing path was executed during this audit cycle.

## Scope reviewed

- exact user prompt;
- `SPEC.md`, `config.json`, and `input_freeze.json`;
- all of `run_study.py` and `tests/test_multi_candidate.py`;
- frozen repaired W4 score/checkpoint, candidate, trade, Policy A, prior PR, raw one-second, and regime-timeline contracts referenced by the implementation.

This final pass re-audited the complete current files after repair of all earlier findings.

## Frozen population and candidate generation

- Every input dependency is SHA-256 frozen: 2025/2026 raw bars, repaired atlases and W4 scores, frozen first candidates and trades, Policy A isolation rows, prior PR trade/summary/audit/manifest artifacts, and the upstream candidate runner/policy.
- Configuration accepts exactly R0, R10, and R30; the only delays are 0, 10, and 30 seconds and the only virtual-PnL threshold is zero.
- Frozen cardinalities are validated as 4,767 first candidates and 4,383 Policy A trades, with year counts 3,530/1,237 and 3,246/1,137 respectively. The year counts are redundantly fail-fast checked inside reconciliation and again in `main()` before any artifact or zero-error seal can be written.
- The repaired score stream is one-to-one merged to causal five-second checkpoints and validated against frozen direction thresholds. Invalid, missing, or noncausal score rows cannot silently enter the collector.
- The strict state is exactly `previous_score < threshold <= current_score`. The previous score advances at every checkpoint, so an above-threshold plateau cannot emit duplicates; a later candidate requires an intervening below-threshold state.
- Candidate sequence is stable within each regime opportunity and duplicate `(opportunity_id, candidate_seq)` keys fail fast.
- Raw running MFE uses only one-second bars stamped strictly before the checkpoint. The raw MFE is compared with the repaired checkpoint MFE, and the frozen progress-window implementation is reused without future data.
- The established filter uses only causal checkpoint age, current MFE, progress count, and retained-MFE ratio. Once the first later checkpoint is ineligible, the opportunity ends and cannot reopen.
- The maximum regime-age horizon is the original inclusive 1,800-second checkpoint. A valid recross exactly at 1,800 seconds is emitted; checkpoints after it are excluded. The boundary is explicitly covered by an unexecuted test.
- Candidate 1 is reconciled one-to-one against every frozen candidate, including regime, crossing time, direction, score, threshold, ATR, would-be fill time/open, direction label, and session.

## Gate causality and terminal ordering

- R0 evaluates candidate 1 only and uses its immediate upstream next-open fill contract.
- R10/R30 anchor confirmation to each candidate's would-be immediate fill, not to an earlier opportunity or a later outcome.
- A gate mark is the close of the latest raw one-second bar whose full interval completed by the gate decision. The decision-time bar cannot leak into confirmation.
- Approval uses directional virtual PnL from the candidate would-be fill and accepts exactly zero.
- Approved delayed entries use the first available raw one-second open strictly after confirmation.
- A crossing at or before an active gate decision is classified as not queued. After an adverse decision, only a later strict recross can be evaluated.
- Regime end has priority at confirmation, then opportunity/score-horizon end, then completed price response. At delayed fill, regime end is checked before opportunity/score end. Terminal opportunities break rather than reviving a later candidate.
- The emitted generation audit includes complete candidate rows with candidate/opportunity IDs, sequence, crossing and would-fill time/open, score/threshold/margin, checkpoint ATR, direction/session/year, regime end, and opportunity end, alongside crossing and evaluation audit rows.

## Stops, timeouts, raw gaps, and scheduled exits

- Accepted trades use checkpoint ATR frozen at their selected candidate.
- The 1.25 ATR pre-alignment and 1.50 ATR post-alignment stops are anchored to the actual accepted fill and active on its entry bar.
- Long/short touch rules and conservative gap-through-open fills are directionally correct.
- The five-minute timeout restarts at actual delayed entry. An aligning flip exactly at the timeout confirms; a later flip cannot cancel a timeout decision already made.
- In raw gaps, within-window alignment is recognized before the first later raw open, while post-timeout alignment cannot retroactively suppress the exit.
- Timeout exits fill only at the first available open strictly after the timeout decision. The active stop remains applicable through the decision-labelled bar.
- Scheduled opposing-flip exits use their causal next available open and take precedence over the subsequent range of that fill bar.

## Global overlap and R0 reconciliation

- R0 uses the exact frozen set of 4,383 upstream executable regime starts (3,246/1,137 by year). That set was created by the pre-existing strategy's causal one-position eligibility, not by selecting profitable outcomes. It is SHA-256 frozen before this study and is used only to reproduce the current Policy A baseline.
- Current Policy A was an independent management replay over those frozen entries. R0 therefore executes every frozen-eligible candidate independently and labels the other accepted first candidates `frozen_upstream_position_overlap`; it does not incorrectly recompute overlap from changed Policy A exits.
- R0 membership is keyed only by `regime_start_ns`. Unique frozen membership count, exact year counts, and the complete entry/exit/PnL reconciliation all fail fast, so the baseline cannot silently add, drop, or outcome-select opportunities.
- R10/R30 do not use the frozen R0 allow-list. They apply the causal one-position rule to their own accepted-entry timelines. Stop exits block through the stopped bar, while market-open exits release at their fill timestamp.
- Candidate acceptance consumes the opportunity before R10/R30's overlap check. A globally blocked accepted candidate does not reopen scanning, avoiding an untested second re-entry policy.
- R0 is fail-fast reconciled to every audited Policy A execution for count, entry timestamp/open, exit timestamp/open/reason, direction, session, and net PnL. It therefore provides an exact current-policy baseline rather than an approximate candidate replay.

## Regenerated prior PR diagnostic

- `build_skip_forever_diagnostic()` regenerates candidate-1-only R10/R30 over exactly the 4,383 R0-executed opportunities.
- Rows map uniquely by original entry timestamp to every frozen prior PR trade row.
- The diagnostic independently reconstructs the completed gate mark, approval and skip reason, strict delayed fill time/open, actual-fill-anchored Policy A management, exit time/open/reason, and net PnL.
- Approval, skip reason, fill, exit, and PnL discrepancies fail fast row by row. The diagnostic is persisted in the final generation audit.
- Prior comparison accounting uses this regenerated diagnostic, not merely imported prior summary values. It separately reports prior approvals/skips, new accepted opportunities and executed trades, later-entry recovery count, PnL and win-rate differences, short-fade PnL recovery, and long-ETH retention.

## Metrics and accounting

- Performance output covers combined, year, long/short, ETH/RTH, and all four direction-session intersections for R0/R10/R30.
- Opportunities, executed trades, and no-trade opportunities are explicit. Opportunity PnL includes zero for no trade; executed-trade PnL distributions use executions only.
- Both mean PnL and win rate are reported per executed trade and per opportunity. Profit factor, stop/timeout rates, average winner/loser, and closed-trade-sequence drawdown use the disclosed appropriate denominators.
- Zero-PnL no-trade rows preserve chronological opportunity order without changing equity or drawdown.
- Candidate accounting has a fixed schema for total generated, evaluated, accepted, total rejected, all five required rejection reasons, all four accepted-sequence buckets, and improved/worsened/unchanged fills, including explicit zero counts.
- Boolean fields read back from the mixed-schema generation audit are explicitly normalized with `fillna(False).astype(bool)` before counts, filters, or inversion. This applies independently to candidate `evaluated`/`accepted` fields and the prior skip-forever `executed` field, preventing object-dtype bitwise inversion from producing negative integer counts.
- Opportunity accounting includes no trade, first-candidate trade, later-candidate trade, and zero/one/two/three/four-plus rejected-before-accept distributions.
- Improvement/worsening, loser-to-later-winner replacement, stop-before avoidance, later winner/loser creation, and winner opportunity-cost classes are exported with counts and paired R0/policy economics.
- A missed/lost baseline winner is separated from a clipped but still-profitable winner, preventing the earlier undercount/overcount ambiguity.

## Tests reviewed without execution

The test source correctly specifies strict recrossing without plateau duplication, permanent filter-window end, inclusive 1,800-second recross and exclusion after the horizon, rejected-first/later acceptance, nonqueued wait-period crossings, exactly-zero approval, strict delayed fills, R0 immediate fill, regime/opportunity terminal priority, entry-bar stop activation, and delayed-fill timeout restart. The corrected synthetic stream now crosses at the asserted 10- and 20-second checkpoints and fails the established filter at 25 seconds.

## Year isolation and guardrails

- 2026 cannot execute before a clean 2025 seal exists, every 2025 artifact hash matches, and all runner/config/freeze/audit/authorization dependencies remain unchanged.
- No W4 retraining, rescoring, threshold change, extra delay, extra PnL threshold, score-shape filter, direction/session rule, MFE continuation, or retained-profit rule is present.
- Candidate diagnostics remain distinct from executable policy outcomes, and the specification prohibits promoting a direction/session subgroup from this study.
- The contract is explicitly a one-second OHLC research simulation, not NT-native or tick-level executable validation.

## Authorization conclusion

The current implementation has no identified look-ahead path, timestamp leak, crossing-state defect, horizon error, opportunity revival, wait-queue leak, incomplete-bar mark, non-strict delayed fill, terminal-order error, fill-anchor error, entry-bar stop blind spot, raw-gap sequencing defect, overlap inconsistency, baseline mismatch path, accounting omission, or selection-isolation breach. It is authorized for its first test/execution only while the runner, config, freeze, and this audit retain the hashes recorded in `pre_execution_authorization.json`.

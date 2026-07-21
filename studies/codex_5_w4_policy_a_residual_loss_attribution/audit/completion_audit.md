# Completion Lookahead, Attribution, and Reproducibility Audit

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope and authorization

Audited the completed residual-loss attribution study's specification, config, input freeze, builder, tests, pre-execution audit/authorization, both Parquet outputs, run manifest, and final report.

The pre-execution authorization remains current:

- builder SHA-256: `0272c384a262d5a4f4d88c07ae6617438f71496dcd27b98a7ed9aa2edbc374a3`
- config SHA-256: `bd70c79fe5f61d33f5e8ab5293c14c9d90be5e44238be4cf98aab68d14d43150`
- freeze SHA-256: `228644fc08c614c8cfef5ce8c3af3934df37b70cf80053e57b5a76dd8885fd5e`
- pre-execution audit SHA-256: `aeaa05c087e0bbf5eb0da4ed21af585b7ca73ae414f05b6d7441e658d06fe45e`

All frozen upstream hashes still match: isolation trade differences, isolation completion audit, isolation manifest, both repaired trade files, and both raw one-second inputs.

## Input scope and independent reconstruction

The output contains exactly **4,383 unique Policy A rows**: 3,246 for 2025 and 1,137 for 2026. No S/T rows, retraining, entry alteration, policy replay, new threshold, or candidate filter is present.

I independently rebuilt every enriched row from the exact `POLICY_A_COMBINED_1P25_300S` isolation rows, repaired source trades, and frozen raw one-second bars. All newly derived fields across all 4,383 rows matched with **zero discrepancies**:

- one-to-one trade ID join and exact entry timestamp;
- confirming-flip timestamp and elapsed time;
- causal W4 checkpoint score;
- checkpoint regime age, decision timestamp, entry delay, and exact regime age at entry;
- direction, entry fill, checkpoint ATR, and integer-nanosecond timestamp preservation;
- timeout alive state;
- completed-path MFE and close-mark PnL at timeout;
- timeout mark timestamp and raw-gap staleness;
- every frozen align-time, regime-age, W4, MFE, and PnL bucket;
- direction/session/year interaction label;
- residual loss mode;
- late-aligning baseline-winner timeout flag;
- positive-PnL capture change.

## Timeout-path verification

- Only raw bars with `ts_event < entry + 300s` contribute to timeout MFE or PnL.
- A stop in the timeout-labelled bar is alive at the timeout-open instant; the frozen data contain both pre-flip and post-alignment stop cases at that exact timestamp. An opposing-flip open fill at timeout is not alive.
- Raw gaps are left unfilled. The latest actually completed close is used, and staleness is measured from that bar's end. Independent replay found valid path intervals for every alive trade; positive staleness is retained rather than hidden.
- Favorable excursion and timeout PnL use the stored entry fill, trade direction, and `atr_at_checkpoint` denominator exactly.
- The nullable `timeout_mark_ts` remains pandas `Int64`; all non-null nanosecond values are preserved exactly above `2^53`.

## Buckets and retrospective classifications

All frozen bucket boundaries, including equality at 60/120/300 seconds and every ATR/score/age edge, match the declared config.

The align-time classifier correctly distinguishes:

- Policy A paths with no aligning flip before exit;
- flips reached within the confirmation window;
- the one frozen `>300s` flip occurring before a pending timeout fill;
- flips equal to or later than the timeout exit, which remain `no_flip_before_exit`.

Entry regime age is correctly computed as checkpoint age plus exact decision-to-fill delay. Three trades enter the 30-60 minute bucket after this correction; no checkpoint-age label is misrepresented as entry age.

Residual loss modes form a mutually exclusive complete partition of all 4,383 trades. Late-winner and timeout-state labels are explicitly retrospective and do not enter execution.

## Independent reconstruction of all 54 summary rows

I independently recalculated every field in `policy_a_bucket_summary.parquet`. All **54 rows** matched with zero discrepancies across all 13 dimensions.

Verified fields include:

- count, total and mean Policy A net PnL;
- win rate and net-PnL profit factor;
- average positive winner and average negative loser;
- gross loss and gross-loss share within each complete dimension;
- bucket-only trade-sequence maximum drawdown in original entry order, starting at zero;
- original baseline total and paired Policy A change;
- positive-PnL capture change;
- separate 2025/2026 counts and net totals.

Each dimension contains exactly 4,383 trades, reproduces the same $9,873.22 Policy A combined net PnL, and has gross-loss shares summing to one up to floating-point representation. Bucket drawdowns are correctly labeled non-additive and are not marked-to-market portfolio drawdowns.

## Manifest and deliverables

- `policy_a_residual_loss_attribution.parquet`: SHA-256 `965dd5f88ab69243b526a85bba4517cf408a3ae53c8a682852c2a19a477dfe56`
- `policy_a_bucket_summary.parquet`: SHA-256 `2245d961f40c853e5165a06644312bce8519b1418fdd997da169c56499b54074`

Both hashes match `run_manifest.json`, whose policy ID, trade count, runner/config/freeze hashes, and completion state are internally consistent. `final_report.md` is present and has SHA-256 `db3e54f061f976c8b1b8c562dabc68808fe81a4a0355d06afd4db546a74c4acf`.

## Report verification and decision

Every report table and material claim was traced to the frozen enriched rows or independently rebuilt summaries. This includes:

- year, direction, session, and all eight year-direction-session results;
- residual loss-mode and final-exit-reason anatomy;
- original outcome, align-time, regime-age, W4, timeout-MFE, and timeout-PnL tables;
- 2025 gross-loss shares;
- 219 late-aligning baseline winners and their exact 2025/2026 capture loss;
- the full timeout cohort's +$10,212.64 paired improvement, -$79,405 positive-capture change, and $4,760 bucket-only drawdown.

The decision `LONG_FADE_DRAG_DOMINATES` is supported descriptively:

- long fades produce **-$18,990.81 combined** while short fades produce **+$28,864.03**;
- long-fade ETH is negative in both years (**-$12,151.72 in 2025; -$3,755.20 in 2026**), the only direction-session interaction with that sign stability;
- stopped-before-alignment losses are the largest residual loss mode and account for 61.3% of 2025 Policy A gross losses.

The report appropriately notes that ETH reverses positive in 2026 overall, other entry buckets are unstable, low MFE/negative PnL are contemporaneous path states, and no exclusion/filter was tested. It does not treat a 2026 description as a selected causal filter or policy result.

The report contains no Unicode replacement characters or malformed encoding.

## Tests and limitation

- Repository tests: **8 passed**.
- Contract: retrospective **1-second OHLC research attribution**, not NT-native executable validation, a new policy backtest, tick-level path reconstruction, or 2026-selected filter validation.

The completed study passes the repository's lookahead, frozen-input, timestamp, aggregation, attribution-only, and reporting gates.

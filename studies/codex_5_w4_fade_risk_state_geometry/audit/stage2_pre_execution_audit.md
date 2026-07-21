# CODEX 5 W4 Fade Risk-State Geometry — Stage 2 Pre-Execution Audit

**Scope:** `stage2_policy_freeze.json`, `run_stage2_policy.py`, `tests/test_stage2_policy.py`, the Stage 1 manifest/artifacts/completion audit, frozen 2025/2026 trades and raw one-second bars, and the frozen repair runner/common dependencies.  
**Mode:** mandatory pre-execution policy, causality, fill-order, holdout-seal, reconciliation, timestamp, and reproducibility audit. No Stage 2 policy simulation was run.  
**Status:** **PASS — STAGE 2 EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

Stage 2 contains exactly one policy: after the aligning flip, arm when entry-anchored post-flip MFE first reaches 1.00 ATR; the retained-profit floor becomes active on the next one-second bar; once active, a +0.25 ATR floor fills at the bar open when gapped through and otherwise at the floor. The original 1.5 ATR stop remains loss-first on the arm-reaching bar, and the original opposing-flip boundary open has priority over that boundary bar's later OHLC range.

The pre-flip branch is closed and no pre-flip candidate appears in the runner. The freeze is derived from the completion-audited 2025 gate, binds the exact Stage 1 artifacts/audit, and binds both years' raw/trade inputs plus the original runner/common dependencies. The original 4,383-entry set, stored entry fills, stops, fallback exits, $20 multiplier, and $10 round-trip cost remain unchanged.

An independent baseline-only replay over all 2,907 trades that reached alignment exactly reproduced every frozen exit timestamp, fill price, net PnL, and normalized exit class. All 1,476 stops before alignment bypass replay and remain byte-source values. No candidate policy outcome was generated during this audit.

The original implementation initially allowed nullable `arm_available_ts` values to be inferred through float64. This was repaired before authorization: optional arm timestamps are now constructed directly as nullable `Int64`, required timestamp columns are asserted integer-typed, and a mixed-null nanosecond value above `2^53` is preserved exactly in regression. The current combined suite passes all ten tests. There are no remaining critical findings or warnings.

## Single freeze derived from the audited 2025 gate

The freeze binds these exact Stage 1 artifacts:

| Stage 1 dependency | SHA-256 |
|---|---|
| Manifest | `0ace2f04291d882e8b0ea5847b61ad04b4c344213f261a4c1f8557051ad9e9e5` |
| Pre-flip MAE geometry | `bf54c16d3916704ff8c283d7f76b2d5771e7f32f9aa505ae0a57663a5f4c6f2d` |
| Conservative pre-stop MFE geometry | `143191ec94b3f153dccdc2c50be8ffd948da1aee00b844369b827fb95c091f5f` |
| Post-flip giveback geometry | `bfa305e0eaec6e5daea7603a2a07ea1375d1ac1c925abeea9e9990b398b730fa` |
| Stage 1 completion audit | `94275609227fe9513b1518faf2893f710d20130dccb4579f62382ce16ccb6c86` |

All current hashes match. The Stage 1 completion audit is a clean 0 CRITICAL / 0 WARNING pass and independently established:

- initial geometry failed;
- no 0.75/1.00/1.25 ATR stop preserved the required 95%;
- `selected_preflip_stop_atr` is null;
- post-flip geometry passed;
- the only selected rule is 1.00 ATR arm / +0.25 ATR floor;
- selection used 2025 only.

The freeze mirrors those conclusions exactly: `preflip_policy_test` is null, the closed-branch reason is explicit, and `postflip_policy_test` is one object with one policy ID. `validate_freeze` rejects any non-null pre-flip policy, requires the exact Stage 1/audit hashes, and rejects arm/floor values other than 1.00/0.25.

No other Stage 1 descriptive revisit level is read by Stage 2. There is no policy list, parameter loop, arm grid, floor grid, direction/session variant, or alternate entry/stop test.

## Frozen Stage 2 inputs and dependencies

Independent hashes match the freeze for:

| Input/dependency | SHA-256 |
|---|---|
| 2025 raw one-second bars | `c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d` |
| 2025 frozen trades | `149e2b039935a9dbf61cb2a0ff416ef0550f95e94c61a278b1a56998c718ef2e` |
| 2026 raw one-second bars | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` |
| 2026 frozen trades | `1bfe5696c24b990ee4ad693abfe707315fa92b7195837f193af32e6c0c062c83` |
| Original repair runner | `70d4dbad865fa52ed1d054941562f76f1ba4009edc8f693169c1044e2a5bf633` |
| Repair common/hash module | `302fab7b64178ee7626300048e9d1b66ab04b64c4a429a3fcbcd48175523e1c7` |

`validate_freeze` computes and requires exact equality of the full Stage 1 and Stage 2 dictionaries before either year is replayed. Raw bars are also passed through the frozen original runner's OHLC/timestamp validator.

The Stage 2 runner iterates every frozen trade after the same stable entry-time sort used upstream and creates one year-qualified trade ID per input row. It does not redetect, filter, rank, or resample entries. Stops before alignment remain unchanged records; every other trade receives a paired original replay and the single frozen policy replay.

## Baseline replay and original 1.5 ATR stop

The original baseline uses the same `simulate_from_align` state machine with `rule=None`. It therefore cannot arm or activate a retained-profit floor. For each reached-alignment trade, runtime reconciliation requires exact exit timestamp, fill price within `1e-12`, and stored net PnL within `1e-8` before the policy result can be accepted.

The audit independently ran only this no-policy baseline path over all 2,907 reached-alignment trades. Results:

```text
exit timestamp mismatches: 0
exit price mismatches:     0
net PnL mismatches:        0
normalized reason errors: 0
```

All 4,383 frozen stop prices also independently satisfy exactly:

```text
stop_px = entry_fill_open - entry_direction * 1.5 * atr_at_checkpoint
```

Maximum absolute error is `0.0`. The runner reads this stored stop directly and never substitutes a selected pre-flip distance.

For `stop_before_aligned_flip`, baseline and policy are the same unchanged dictionary using the original stored exit/fill/PnL. The row is never passed into the post-flip replay loop, cannot arm, and has zero post-flip runner MFE.

## Post-flip replay interval and missing bars

The loop begins at the first raw one-second bar with `ts_event >= confirm_flip_ns`, which is the same explicit next-available aligning open contract used by the frozen baseline. It ends strictly before `scheduled_exit_decision_ts` using a left-edge search. Consequently, the original scheduled opposing-flip fill is selected before any OHLC range from the decision-boundary bar is evaluated.

The exact frozen data contain 633 reached trades whose first aligning raw open is delayed beyond the nominal flip timestamp, 657 with a delayed raw open at the scheduled boundary, and 2,755 replay intervals containing at least one non-contiguous raw timestamp. The independent baseline replay remains exact across all of them.

Missing bars do not create fabricated ranges. An arm detected in bar `[t,t+1s)` becomes causally available at `t+1s`; `active_from_i=i+1` applies the floor on the next available raw bar, even if a data gap separates it. A gap through an active level then fills at that available bar's open. At a scheduled boundary in a data gap, the loop excludes the first bar at or after the decision and falls back to the frozen stored exit fill, preserving boundary priority.

The runner rejects an empty or inverted post-flip replay interval rather than silently using a later range.

## Arm, stop, and activation order

Post-flip favorable excursion is entry-anchored and direction symmetric:

- long: `max(high - entry, 0)`;
- short: `max(entry - low, 0)`.

`peak_pts` begins at zero at the aligning loop and accumulates only post-flip bars. The trade arms once that running peak reaches `1.0 * atr_at_checkpoint`.

Within an unprotected arm-reaching bar, the original stop is checked before the bar's favorable range is allowed to arm the policy. Thus a bar whose OHLC touches both the 1.00 ATR arm and original 1.5 ATR stop exits at the original stop. This is the declared conservative loss-first resolution and makes no favorable intrabar ordering assumption.

After a bar arms, `active_from_i=i+1`; the arm bar itself cannot hit the retained floor. `arm_available_ts` is the arm bar's open label plus exactly one second, the causal completion boundary. The next available bar is the first bar on which protection can act.

Once active, the +0.25 ATR retained floor is closer to price than the original adverse stop and is checked first. If an active bar's continuous path reaches the original stop from above/below, it must cross the nearer floor first; if the bar opens through both, both fill rules produce the same gap open. Therefore floor-first on an active bar does not introduce an optimistic unknown ordering assumption.

Policy MFE is updated only after active-floor and original-stop checks. A bar that exits at a protective level cannot contribute a later, unknown favorable extreme to the policy runner's MFE. On the arm bar, a stop prevents that same bar's favorable extreme from arming or inflating MFE.

## Floor fill and scheduled-exit semantics

The fixed floor price is:

```text
entry_fill_open + entry_direction * 0.25 * atr_at_checkpoint
```

For a long, a gap is `open <= floor`; for a short, `open >= floor`. A gap fills at the open. Otherwise an OHLC touch fills exactly at the floor. The logic and tests are symmetric for long and short.

Touch fills are one-second OHLC research fills. `new_exit_fill_ts` is the open label of the containing one-second bar, not a claim of tick-exact touch time or ordering within that bar. The declared ordering rules are limited to the conservative arm-bar stop resolution and the economically dominant active floor described above.

If neither original stop nor active floor exits before the frozen scheduled boundary, the runner uses the original stored exit timestamp and price. It then includes that known exit open as a discrete favorable point for runner MFE, matching the baseline's planned-exit convention while excluding the boundary bar's later range.

## Costs, PnL, and paired diagnostic definitions

The code constants exactly match the freeze:

```text
multiplier = $20 per point
round-trip cost = $10 per trade
```

Each policy replay calculates signed gross points from the unchanged stored entry, gross dollars as points times $20, and net dollars as gross dollars minus $10. The baseline reconciliation proves those formulas reproduce stored net PnL. Stops before alignment retain the original stored gross/net fields directly.

Each trade-diff row contains the original and policy exits/PnL and computes:

- `net_pnl_change_usd = new_net_pnl_usd - original_net_pnl_usd`;
- planned loser converted only when the frozen planned-loser group becomes strictly net profitable;
- stop-after loss reduced only when its paired net-PnL difference is positive;
- planned winner clipped only when paired net PnL falls by more than `1e-9`;
- planned winner lost when its policy net PnL is non-positive;
- runner MFE lost as `max(original_postflip_peak_mfe - policy_postflip_peak_mfe, 0)`.

The original runner MFE is the baseline post-flip MFE under the same stop loss-first and scheduled-exit-open conventions. Policy runner MFE ends at the policy exit and cannot use favorable range after that exit. The nonnegative clamp prevents floating noise or a later policy-only value from being reported as negative “lost” MFE.

Summaries remain paired over the identical trade set and report baseline and policy versions overall and by year, direction, and session. Profit factor uses positive net-PnL sum divided by absolute negative net-PnL sum. Conversion/clipping/reduction counts and runner-MFE loss are populated only for the policy version.

## 2025 seal and 2026 holdout isolation

The CLI accepts only one explicit year at a time. A 2026 invocation performs authorization and full freeze/input validation, then refuses to proceed unless a 2025 reconciliation seal exists with:

- zero blocking errors;
- exact current hashes for runner, freeze, 2025 raw/trades, Stage 1 manifest, Stage 2 audit, and Stage 2 authorization;
- an exact hash match for the sealed 2025 trade-diff parquet.

The 2025 diff is built completely in memory, with per-trade baseline reconciliation and duplicate/cardinality checks, before its work parquet and seal are written. No final policy result is published at that stage. The 2026 work diff is likewise built and checked before final combination. Final result parquets and `stage2_manifest.json` are written only during the sealed 2026 step.

Changing runner code, freeze, audit, authorization, Stage 1 manifest, or 2025 data invalidates the predecessor seal. `validate_freeze` independently binds the unchanged 2026 raw/trades and repair dependencies before the holdout replay.

The policy is frozen before either year runs. No 2025 result can mutate it, and no 2026 statistic is read by any selection or configuration function. The final combined summary is reporting only.

## Timestamp precision

All input/search timestamps remain integer nanoseconds. Required output timestamps (`entry_fill_ts`, `original_exit_fill_ts`, and `new_exit_fill_ts`) are constructed from Python integers and runtime-asserted as integer dtype.

The optional `arm_available_ts` initially presented a nullable coercion risk. The current `records_frame` constructs it directly from the original Python values using pandas nullable `Int64`, avoiding float64 entirely. A regression with `1_735_775_485_000_000_001` and `None` confirms exact preservation above `2^53` and a genuine null in the adjacent row.

## Tests and execution state

The complete study suite passes against the exact current source:

```text
10 passed in 0.39s
```

The five Stage 2 tests cover next-bar activation, arm/stop same-bar loss-first resolution, long/short gap-through-floor fills, scheduled-boundary priority, and nullable nanosecond precision. The five Stage 1 tests continue to cover direction symmetry, favorable-side exclusion, 2025-only selection behavior, smallest-preserving selection, and fail-closed hashes.

At audit time, `_work/` contains no Stage 2 artifact and `results/` contains only the four previously completion-audited Stage 1 files. No Stage 2 simulation or final policy output has run.

## Prior-finding closure

| Finding | Disposition |
|---|---|
| Nullable `arm_available_ts` would be inferred as float64 in the trade-diff frame | **Closed.** Direct nullable `Int64` construction, required timestamp dtype assertions, and a mixed-null >`2^53` regression preserve exact nanoseconds. |

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The exact current Stage 2 runner is authorized to execute the single frozen post-flip policy: 2025 first, then 2026 only under the exact predecessor seal. The pre-flip branch must remain closed. Outputs must be labeled paired one-second OHLC research simulation, not tick-exact or NT-native executable validation. Any change to runner, freeze, this audit, frozen inputs/dependencies, Stage 1 artifacts/audit, or ordering/fill semantics invalidates authorization and requires renewed pre-execution review.

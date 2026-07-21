# CODEX 5 W4 Fade Risk-State Geometry — Stage 1 Pre-Execution Audit

**Scope:** `SPEC.md`, `config.json`, `build_stage1_geometry.py`, and `tests/test_stage1_geometry.py`, traced against the completion-audited countertrade path outputs, frozen CODEX 5.X trades, and raw Databento one-second bars.  
**Mode:** mandatory pre-execution causality, timestamp, alignment, selection-gate, and reproducibility audit. The Stage 1 build was not run.  
**Status:** **PASS — STAGE 1 EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

Stage 1 is a retrospective descriptive geometry build over byte-frozen, completion-audited path artifacts and frozen trades/raw bars. It does not change an entry, stop, target, exit, W4 score, or outcome; it does not run any candidate policy; and it does not use 2026 in the Stage 2 gate or candidate selection.

Pre-flip MAE uses the correct known boundary mark: the explicit first available aligning-flip open for every trade that reaches the flip, and the stored stop fill for a stop before alignment. Pre-stop MFE comes from the audited final-exit path row whose primary favorable range excludes the unknown stop-bar OHLC range. Post-peak revisit flags start at causal peak availability, scan raw ranges strictly from that availability through before exit, and then include the known stored exit fill as a discrete reached price.

The direction formulas are symmetric. Stage 2 initial-stop preservation uses strict `MAE < candidate`, which is the correct preservation condition when equality touches a stop. The three fixed stop distances are evaluated only by one predeclared 2025 selection rule, not as three backtests. The post-flip candidate is the single fixed 1.00 ATR arm / +0.25 ATR floor rule declared before execution.

All frozen hashes, input identities, outcome labels, named boundary rows, and post-flip diagnostic timestamps reconcile exactly. The isolated suite passes all five tests. There are no remaining critical findings or warnings.

## Frozen input gate

`validate_inputs` constructs the complete current hash dictionary and requires exact dictionary equality with `config.json` before Stage 1 reads any geometry input into its build. Independent hashing matched every bound file:

| Input | SHA-256 |
|---|---|
| Audited path checkpoints | `a06d73ccecc15668f42c08f71c52692f29ff2a4a9aefbb74754980472113c993` |
| Audited post-flip diagnostic | `fcfe949d070c4f2685372397d9c715001af527210d3fe2332b6ec7911101d84a` |
| Audited path run manifest | `84acc063a7661253de3edc247e6290f76eb5ee1549df5b09c4deccb1b4854cc9` |
| 2025 raw one-second bars | `c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d` |
| 2025 frozen trades | `149e2b039935a9dbf61cb2a0ff416ef0550f95e94c61a278b1a56998c718ef2e` |
| 2026 raw one-second bars | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` |
| 2026 frozen trades | `1bfe5696c24b990ee4ad693abfe707315fa92b7195837f193af32e6c0c062c83` |

The three upstream diagnostic hashes are the exact artifacts accepted by `audit/completion_audit.md` at 0 CRITICAL / 0 WARNING. The path manifest itself binds the two consumed parquet outputs to those hashes. The raw bar indices are unique and strictly increasing, and all 16,339,267 combined one-second bars pass OHLC containment checks.

Execution additionally fails closed unless a clean Stage 1 audit and authorization JSON bind the exact script, config, specification, and this audit report.

## Trade, outcome, and boundary alignment

Stage 1 recreates trade IDs by the same stable `(year, entry_fill_ts sort, zero-padded row index)` contract used by the audited path study. Independent reconciliation found:

- 4,383 frozen trades and exactly the same 4,383 path trade IDs;
- exactly one aligning-flip named row and one final-exit named row per trade;
- 2,907 reached-alignment trades and exactly the same 2,907 post-flip diagnostic IDs;
- no missing, extra, or duplicate named-boundary IDs;
- zero mismatches in year, outcome group, trade direction, session, aligning-flip timestamp, or exit timestamp.

Outcome counts are exact and exhaustive: 1,476 stops before alignment, 375 stops after alignment, 1,360 planned winners, and 1,172 planned losers. Planned winner/loser status uses the frozen stored `net_pnl_usd > 0` rule. All other labels remain their frozen exit reasons.

The builder emits exactly one pre-flip row per frozen trade, one pre-stop row per stop-before-alignment trade, and one post-flip row per reached-alignment diagnostic. Runtime cardinality checks therefore require 4,383, 1,476, and 2,907 rows respectively before any result is written. Because the exact frozen input ID sets are unique and aligned, those counts also represent exact trade coverage rather than survivor or duplicate inflation.

## Pre-flip MAE and conservative pre-stop MFE

For reached-alignment trades, `build_preflip` reads the audited `aligning_flip` row. Independent reconciliation confirms all 4,383 such named rows use checkpoint time `confirm_flip_ns`, source `aligning_flip_next_open`, and a `price_mark_time` at the first available raw open at or after that boundary. The row's running MAE includes completed raw ranges in `[entry, aligning boundary)` plus that known discrete next-open mark.

For `stop_before_aligned_flip`, the builder instead reads the exact `final_exit` row. Every final row uses the stored exit timestamp and `stored_exit_fill` source, so pre-flip MAE includes the known stop fill and does not substitute a later counterfactual aligning mark.

Pre-stop MFE is also taken from that audited final row. The upstream completion audit independently reconciled every running-MFE value to raw ranges. Its stop contract scans `[entry_fill_ts, stop_fill_ts)`, excludes the stop bar's unordered favorable OHLC range, and includes only the known stop fill as a discrete price. Thus Stage 1 does not import the separate stop-bar upper bound or claim fill-anchored intrabar ordering.

All excursion units use the frozen `atr_at_checkpoint`, identical to the original 1.5 ATR stop denominator.

## Post-peak revisit semantics

The post-flip input contains only trades that reached the aligning flip. Independent reconciliation found zero peak-ordering errors: every `post_flip_peak_available_ts` is at or after its aligning fill and no later than exit. For each of the 2,906 OHLC-derived post-flip peaks, availability is exactly `post_flip_peak_bar_ts_event + 1s`; the remaining peak is the known aligning-flip open and is available at its exact fill time.

`build_postflip` starts its range at `searchsorted(raw_ts, peak_available, left)` and ends strictly before `exit_fill_ts`. Therefore the bar that retrospectively created an OHLC peak is excluded from the after-peak revisit window; the first included one-second range is the bar opening at causal peak availability. The stored exit fill is then checked separately, ensuring a floor reached by an exit gap is retained without using any later exit-bar OHLC range.

The same causal construction applies to the fixed entry-anchored floors and retained-MFE fractions. These fields are explicitly named retrospective `revisited_*_after_peak` labels. Neither the specification nor the code represents the final peak, its availability time, or a later revisit result as information available to a live policy before it occurs.

`price_revisited_entry_after_flip` begins at the actual aligning-flip fill open and scans forward to the same strict exit boundary plus known exit fill. It is descriptive geometry and is not used by the Stage 2 gate.

## Direction symmetry and floor definitions

For a long fade, an adverse floor touch is `low <= floor`; for a short fade it is `high >= floor`. The exit-fill comparison follows the same symmetry. Invalid directions fail closed.

Fixed profit floors are calculated as:

```text
floor_px = entry_fill_open + entry_direction * floor_atr * atr_at_checkpoint
```

Retained-MFE floors use the identical signed construction with `fraction * post_flip_peak_mfe_atr`. Eligibility for a fixed positive floor requires the retrospective peak to have reached that floor first. This prevents a “revisit” label for a level the trade never attained. The direction-symmetry and favorable-side exclusion tests pass for both long and short trades.

## 2025-only Stage 2 gate and selection

`stage2_gate_2025` immediately creates:

- `pre25`: year 2025 pre-flip rows excluding stops before alignment;
- `post25`: year 2025 post-flip rows;
- planned losers and winners selected only from `post25`.

No unfiltered pre/post frame is used after those assignments. The returned manifest explicitly records `selection_source: 2025_only`. The 2026 rows are produced only for later descriptive comparison and cannot alter a gate, pass/fail condition, selected stop, or selected post-flip rule. A mutation regression proves a pathological 2026 pre-flip row does not change the gate; static tracing independently confirms the same isolation for the post-flip frame.

Initial geometry passes only when the 2025 reached-flip p95 MAE is at most 1.25 ATR. Candidate preservation is:

```text
mean(pre_flip_mae_atr < candidate)
```

The strict inequality is correct: a path whose adverse excursion equals the candidate has touched that stop and is not preserved. The exact current candidate list is ordered `[0.75, 1.0, 1.25]`; the loop selects the first and therefore smallest level reaching the predeclared 95% preservation threshold. If initial geometry fails, no pre-flip stop is selected even if a preservation entry was computed descriptively.

Post-flip geometry passes only if all three fixed 2025 conditions hold: planned-loser median giveback at least 1.0 ATR, planned-loser 1.0 ATR reach rate at least 50%, and planned-winner 1.0 ATR reach rate at least 90%. On pass, the only selected candidate is the predeclared config pair `{arm_atr: 1.0, floor_atr: 0.25}`.

Stage 1 does not simulate fills or PnL under any candidate. The three stop candidates are one ordered descriptive selection rule rather than three policy tests. The additional fixed revisit floors/fractions are path-geometry labels, are not used to select the post rule, and cannot change the single fixed post candidate.

## Timestamp precision and output contract

All input event times remain integer nanoseconds. The post-flip peak availability field arrives as audited nullable `Int64`, is converted directly with Python `int`, and is passed to `np.searchsorted` against the raw `int64` nanosecond index. No timestamp is routed through float64. Output geometry stores durations as seconds and does not serialize a nanosecond timestamp column, so there is no optional-timestamp coercion surface in the Stage 1 outputs.

The manifest binds the exact script/config and all three produced parquet hashes. No result file is written until authorization, frozen hashes, all computations, and all cardinality gates have passed.

## Tests

The isolated Stage 1 suite was run without invoking `main` or writing a Stage 1 result:

```text
5 passed in 0.37s
```

Tests cover long/short adverse-floor symmetry, favorable-side exclusion, strict 2025-only initial-stop selection behavior, smallest-preserving-candidate selection, and fail-closed hash mutation. The remaining contracts were verified by static causal tracing and independent reconciliation of the exact frozen inputs described above.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The exact current Stage 1 source is authorized for one descriptive geometry build. Any change to the script, config, specification, this audit, the completion-audited path artifacts/manifest, frozen trades, or raw one-second bars invalidates authorization and requires a new audit. Stage 1 outputs must remain retrospective descriptive labels and must not be presented as a tested policy, live signal, NT-native execution validation, or 2026-independent result unless the unchanged 2025-only gate contract remains in force.

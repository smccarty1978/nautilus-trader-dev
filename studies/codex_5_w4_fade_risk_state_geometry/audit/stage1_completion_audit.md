# CODEX 5 W4 Fade Risk-State Geometry — Stage 1 Completion Audit

**Scope:** `results/pre_flip_mae_geometry.parquet`, `results/pre_stop_mfe_geometry.parquet`, `results/post_flip_giveback_geometry.parquet`, and `results/stage1_manifest.json`, independently traced to the frozen countertrade path outputs, frozen trades, raw one-second bars, authorized Stage 1 source/config/specification, and the predeclared 2025-only gate.  
**Mode:** mandatory post-execution completion and Stage 2 gate audit. No freeze or policy code was run or authorized by the Stage 1 build itself.  
**Status:** **PASS — STAGE 1 COMPLETE; FIXED POST-FLIP FREEZE ELIGIBLE**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

All three Stage 1 parquet outputs match an independent in-memory reconstruction from the byte-frozen path, raw-bar, and trade inputs exactly, including row order, values, nulls, and dtypes. Output hashes match the manifest, trade IDs are unique and exhaustive, and cardinalities are exactly 4,383 pre-flip rows, 1,476 conservative pre-stop rows, and 2,907 reached-alignment post-flip rows.

The 2025-only gate reproduces exactly. Initial-stop geometry fails: reached-flip p95 pre-flip MAE is 1.316890996992945 ATR, above the predeclared 1.25 limit, and none of the three candidates preserves 95% of reached-flip trades. Therefore `selected_preflip_stop_atr` is correctly null and no initial-stop candidate is eligible for Stage 2.

Post-flip geometry passes all three predeclared conditions. The only eligible Stage 2 freeze is the fixed post-flip rule with a 1.00 ATR arm and +0.25 ATR floor. This completion result does not itself validate that rule's expectancy and does not authorize an un-audited simulation implementation.

No policy backtest, alternative fill simulation, order submission, parameter optimization, or 2026-driven selection ran in Stage 1.

## Authorized source and input state

The executed manifest binds the exact authorized source and config:

| Artifact | SHA-256 |
|---|---|
| `build_stage1_geometry.py` | `63be45f7349630d0574081f5528d129ef89b49498dd7e2225cdbacbd0909071c` |
| `config.json` | `be00ce697f9821bec66bb21cd084a4a4baaa1ecbbc23566186a802413bbc8f7f` |
| `SPEC.md` | `1098ef0dae8fa849d84f9648b296b4fae6192eba02a623593f788329a903a99d` |
| Stage 1 pre-execution audit | `61e4fdc8643a792f5ad2bbdfdb02c9a090f65713c2848233fae135713844f914` |

The runtime authorization and frozen-input gates pass. The consumed upstream files remain the exact completion-audited path checkpoints, post-flip diagnostic, path manifest, 2025/2026 trades, and 2025/2026 raw one-second bars recorded in `config.json`. No bound input changed between authorization and Stage 1 execution.

## Manifest and output integrity

`stage1_manifest.json` has SHA-256:

```text
0ace2f04291d882e8b0ea5847b61ad04b4c344213f261a4c1f8557051ad9e9e5
```

It reports `STAGE1_COMPLETE`, 4,383 trades, the exact 2025 gate reproduced below, and these output hashes:

| Output | Rows | Unique trade IDs | Manifest/current SHA-256 |
|---|---:|---:|---|
| `pre_flip_mae_geometry.parquet` | 4,383 | 4,383 | `bf54c16d3916704ff8c283d7f76b2d5771e7f32f9aa505ae0a57663a5f4c6f2d` |
| `pre_stop_mfe_geometry.parquet` | 1,476 | 1,476 | `143191ec94b3f153dccdc2c50be8ffd948da1aee00b844369b827fb95c091f5f` |
| `post_flip_giveback_geometry.parquet` | 2,907 | 2,907 | `bfa305e0eaec6e5daea7603a2a07ea1375d1ac1c925abeea9e9990b398b730fa` |

The results directory contains only these three descriptive parquet artifacts and the Stage 1 manifest. There is no strategy, policy, fill, order, position, or backtest result artifact.

## Independent row-level reproduction

The completion audit independently rebuilt the expected records without calling `main` or writing a replacement output.

### Pre-flip geometry

For each frozen trade, the audit recreated the identical stable trade ID and outcome label, then selected:

- the audited final-exit row for `stop_before_aligned_flip`; or
- the audited aligning-flip row for every reached-alignment outcome.

It copied the causal running MAE at that boundary, recomputed every 0.50/0.75/1.00/1.25/1.50 ATR threshold flag, and reconciled year, direction, session, outcome, and boundary kind. The reconstructed frame is exactly equal to all 4,383 delivered rows with no numerical, null, dtype, ordering, or metadata mismatch.

Reached-flip boundaries use the explicit first available aligning next-open mark. Stop-before boundaries use the stored stop fill. Those semantics were already independently reconciled to raw prices during the upstream completion audit and remain frozen by hash.

### Conservative pre-stop geometry

For each of the 1,476 stop-before-alignment trades, the audit independently selected the final-exit path row, copied the conservative running MFE, and recomputed all 0.25/0.50/0.75/1.00 ATR flags. The reconstructed frame is exactly equal to the delivered artifact.

The source running MFE scans completed ranges strictly before the stop bar and does not import the stop-bar favorable OHLC upper bound. The known adverse stop fill cannot create phantom favorable excursion.

### Post-flip geometry

For all 2,907 reached-alignment trades, the audit independently joined the exact trade and post-flip diagnostic, read raw bars by integer nanosecond timestamp, and recomputed:

- entry revisit after the aligning flip;
- breakeven, +0.25 ATR, and +0.50 ATR eligibility and post-peak revisit flags;
- 25% and 50% MFE-retention revisit flags;
- all copied aligning-PnL, peak, time, giveback, and capture fields.

Each revisit scan begins at `post_flip_peak_available_ts`, not at the OHLC peak bar's open label, and ends strictly before exit. The known exit fill is included separately. Long floors use lows and `exit_fill <= floor`; short floors use highs and `exit_fill >= floor`. The reconstructed frame is exactly equal to every delivered row, including nullable ineligible revisit fields.

This exact match confirms that the output is retrospective path geometry. Final peak selection and after-peak revisits are labels learned from the completed path and are not represented as contemporaneous live signals.

## Exact 2025-only gate reproduction

The gate was independently recomputed using only:

- 2025 reached-flip pre-MAE rows for initial geometry and preservation;
- 2025 planned-loser and planned-winner post-flip rows for post geometry.

No 2026 row entered a quantile, median, rate, pass/fail test, or selection.

### Initial-stop gate: FAIL

| Metric | Exact result | Requirement |
|---|---:|---:|
| Reached-flip pre-MAE p95 | `1.316890996992945` | `<= 1.25` |
| Preservation at 0.75 ATR | `0.7438055165965405` | `>= 0.95` |
| Preservation at 1.00 ATR | `0.8499298737727911` | `>= 0.95` |
| Preservation at 1.25 ATR | `0.9308087891538102` | `>= 0.95` |

All preservation rates use the predeclared strict condition `pre_flip_mae_atr < candidate`; equality is a stop touch and is not preserved. The p95 gate fails and no candidate reaches 95% preservation. The manifest therefore correctly records:

```text
initial_geometry_pass = false
selected_preflip_stop_atr = null
```

No tighter initial stop may advance from this Stage 1 gate.

### Post-flip gate: PASS

| Metric | Exact result | Requirement |
|---|---:|---:|
| Planned-loser median giveback | `1.9357060240771657` ATR | `>= 1.0` |
| Planned-loser reach 1.0 ATR | `0.7104651162790697` | `>= 0.50` |
| Planned-winner reach 1.0 ATR | `0.996003996003996` | `>= 0.90` |

All three conditions pass. The manifest correctly records:

```json
{
  "postflip_geometry_pass": true,
  "selected_postflip_rule": {
    "arm_atr": 1.0,
    "floor_atr": 0.25
  }
}
```

The selected rule is the single fixed config rule. No floor, arm, retention fraction, year, direction, or session grid was optimized. Other Stage 1 revisit columns remain descriptive and do not participate in selection.

`stage2_pass` is true solely because the post-flip gate passes. It does not override the failed initial geometry and does not make a pre-flip candidate eligible.

## No policy execution

Static inspection and the result inventory confirm that Stage 1 only reads frozen parquet/raw inputs, calculates descriptive rows, evaluates the predeclared gate, and writes geometry plus a manifest. It contains no NautilusTrader backtest engine, strategy, order, position, fill matcher, stop/target simulator, commission model, or policy PnL comparison.

The isolated Stage 1 suite still passes against the exact executed source:

```text
5 passed in 0.36s
```

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** Stage 1 is complete and reproducible. The initial-stop branch is closed by its failed 2025 gate. The single fixed post-flip candidate (arm at 1.00 ATR, activate under its separately specified next-bar execution contract, protect +0.25 ATR) is eligible to be frozen for Stage 2.

Before any Stage 2 policy code is executed, its exact freeze/spec/config and implementation must receive the mandatory pre-execution lookahead audit, including arm-bar versus next-bar activation, same-bar ambiguity, fill timing, and unchanged 2026 holdout isolation. This completion audit does not itself authorize that future simulation.

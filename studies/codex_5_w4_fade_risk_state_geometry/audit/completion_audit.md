# CODEX 5 W4 Fade Risk-State Geometry — Completion Audit

**Scope:** complete Stage 1 and Stage 2 chain: source, config, specification, freeze, pre-execution audits/authorizations, Stage 1 artifacts/manifest/completion gate, both Stage 2 yearly work files and reconciliation seals, final Stage 2 parquets/manifest, and `results/final_report.md`, traced independently to the frozen raw bars and trades.  
**Mode:** mandatory post-execution causality, reconciliation, artifact, metric, deliverable, and report audit.  
**Status:** **PASS — STUDY COMPLETE**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The study is complete, internally consistent, reproducible, and correctly reported. Stage 1 remained descriptive. Its 2025 gate closed the pre-flip branch and froze exactly one post-flip rule. Stage 2 replayed the unchanged 4,383-entry set under the original baseline and that one policy, with 2025 sealed and reconciled before the selection-isolated 2026 policy replay.

An independent raw-bar implementation reproduced every delivered Stage 2 trade-diff field for all 4,383 trades with zero mismatch and zero numerical error. The final combined trade file is exactly the concatenation of the two hash-sealed yearly work files. The final summary is exactly reproducible from the paired trade file, every output hash matches its manifest/seal, and all cost/PnL identities are exact.

The tested policy lost $5,276.26 versus baseline in 2025 and $2,455.23 combined, despite gaining $2,821.03 in 2026. The report therefore uses the permitted and evidence-supported decision label `NO_POLICY_IMPROVEMENT`. It does not promote either the closed pre-flip stop branch or the failed combined post-flip rule.

The report initially overstated 2026 blindness and omitted two required descriptive revisit columns. Before this PASS, those issues were corrected: 2026 is now described as selection-isolated rather than unseen, and +0.50 ATR / 25%-MFE revisit results are included. There are no remaining critical findings or warnings.

## Current source, freeze, and authorization chain

| Artifact | SHA-256 |
|---|---|
| `build_stage1_geometry.py` | `63be45f7349630d0574081f5528d129ef89b49498dd7e2225cdbacbd0909071c` |
| `config.json` | `be00ce697f9821bec66bb21cd084a4a4baaa1ecbbc23566186a802413bbc8f7f` |
| `SPEC.md` | `1098ef0dae8fa849d84f9648b296b4fae6192eba02a623593f788329a903a99d` |
| Stage 1 pre-execution authorization | `d94bb7a63cc51f4eb0af48612686db258af7fd0a7ebca2d83d0e4309bd3c659c` |
| `stage2_policy_freeze.json` | `b46085995caab80e7abb377de83aa4914929b1ed446d4bc4dd2fc334ec3e72ec` |
| `run_stage2_policy.py` | `399e8410736e7f0878ef73b30af83e0737ed18a4430189c3984e8f3f3534efe8` |
| Stage 2 pre-execution audit | `d66d75fce9c09af07be676cffcbdd0e3255905b231e51871e697f443cf3e4684` |
| Stage 2 pre-execution authorization | `15886acc9d63bbfda67d3470e1a68fe1e98538a0eaac8791073ba0e4499e0057` |

Both runtime authorization gates still pass against the exact current files. The Stage 1 input gate, Stage 2 freeze gate, and 2025 predecessor-seal gate also pass after execution.

The freeze binds the exact Stage 1 manifest, all three Stage 1 parquets, Stage 1 completion audit, both years' raw/trade files, and the imported repair runner/common sources. No bound source, input, or audited predecessor changed between authorization and output generation.

## Stage 1 artifact and gate integrity

Stage 1 output hashes remain:

| Output | Rows | SHA-256 |
|---|---:|---|
| `pre_flip_mae_geometry.parquet` | 4,383 | `bf54c16d3916704ff8c283d7f76b2d5771e7f32f9aa505ae0a57663a5f4c6f2d` |
| `pre_stop_mfe_geometry.parquet` | 1,476 | `143191ec94b3f153dccdc2c50be8ffd948da1aee00b844369b827fb95c091f5f` |
| `post_flip_giveback_geometry.parquet` | 2,907 | `bfa305e0eaec6e5daea7603a2a07ea1375d1ac1c925abeea9e9990b398b730fa` |

`stage1_manifest.json` remains `0ace2f04291d882e8b0ea5847b61ad04b4c344213f261a4c1f8557051ad9e9e5`. Its exact 2025-only gate is unchanged:

- reached-flip pre-MAE p95: `1.316890996992945` ATR, so initial geometry fails the `<=1.25` gate;
- strict preservation (`MAE < candidate`): `0.7438055165965405`, `0.8499298737727911`, and `0.9308087891538102` for 0.75/1.00/1.25 ATR;
- selected pre-flip stop: null;
- planned-loser median post-flip giveback: `1.9357060240771657` ATR;
- planned-loser 1.0 ATR reach rate: `0.7104651162790697`;
- planned-winner 1.0 ATR reach rate: `0.996003996003996`;
- post-flip geometry passes and selects only 1.00 ATR arm / +0.25 ATR floor.

The previous Stage 1 completion audit independently reproduced every Stage 1 row. This completion audit rechecked all report aggregates, quantiles, thresholds, splits, and revisit rates against the unchanged parquets. Every Stage 1 table and prose figure matches, including the newly restored conditional +0.50 ATR revisit and 25%-MFE revisit columns.

## One policy and closed pre-flip branch

The freeze contains one `postflip_policy_test` object and `preflip_policy_test: null`. The runner reads no Stage 1 candidate array and contains no policy/parameter loop. `stage2_manifest.json` reports `policy_count: 1`, and all 4,383 final diff rows carry the single ID `POSTFLIP_ARM_1P0_FLOOR_0P25`.

All 1,476 `stop_before_aligned_flip` trades are unchanged: original and new timestamps, fill prices, gross/net PnL, and paired deltas reconcile exactly; every net-PnL change is zero. No tighter stop was simulated.

The remaining 2,907 trades use the single frozen rule. The original entry timestamps/prices, directions, ATRs, 1.5 ATR stops, sessions, outcomes, and scheduled exits come directly from the exact frozen trades. The final file has 4,383 unique year-qualified trade IDs with no missing, extra, or duplicate entry.

## Yearly seals and output hashes

The 2025 reconciliation seal records zero blocking errors, 3,246 trades, the exact dependency hashes, and work-diff hash:

```text
10e929ecb8308f48f1830d717f8e5cc909eac6933b6535b8449f9422267d2f61
```

The 2026 run verified that predecessor seal before replay. Its reconciliation records zero blocking errors, 1,137 trades, the same frozen 2025 dependencies, and work-diff hash:

```text
a90574550b211543c2d998c1960626a4c409375d84811a6ac307914322ca1a47
```

Both current work parquets match those hashes. Their exact ordered concatenation equals `results/policy_test_trade_diffs.parquet` row-for-row and dtype-for-dtype.

The final Stage 2 manifest (`257faeae88697ada57c4a79f8f2f1c98a7442dbbb430119ac8117acb2925b83c`) reports `STAGE2_COMPLETE`, one policy, 4,383 trades, the exact runner/freeze hashes, and current output hashes:

| Output | SHA-256 |
|---|---|
| `policy_test_trade_diffs.parquet` | `5b1cff8455c7250802d617458ada1c5e63ff7ee36b2752c3226e1062d03355b0` |
| `policy_test_results.parquet` | `398d29878c665c085f26331227ad49c83a3fb1d5ebaa9467050906e2beca244b` |

## Independent full policy replay

The audit independently reimplemented the paired state machine from raw bars and frozen trades without reading delivered policy values as expected answers. It checked every output column on all 4,383 rows.

Results:

```text
metadata/outcome/entry mismatches:     0
baseline peak/fill/PnL mismatches:     0
policy arm/timestamp mismatches:       0
policy exit timestamp/price mismatches:0
policy reason/PnL mismatches:          0
conversion/reduction/clipping errors:  0
runner-MFE-loss errors:                0
maximum numerical error:               0.0
```

Optional `arm_available_ts` remains nullable `Int64`; required entry/original/new-exit timestamps remain integer nanoseconds. Armed rows always have an arm timestamp, unarmed rows never do, and no exit precedes entry.

All PnL identities are exact:

```text
new_gross_pnl_usd = new_gross_pnl_pts * 20
new_net_pnl_usd   = new_gross_pnl_usd - 10
net_pnl_change    = new_net_pnl_usd - original_net_pnl_usd
```

Maximum absolute error for each identity is `0.0`.

## Causal fill and path ordering

The completed replay preserves the audited contract:

- post-flip replay starts at the first raw bar at or after the aligning-flip decision;
- original 1.5 ATR stop remains active and is loss-first on the arm-reaching bar;
- entry-anchored post-flip MFE arms at 1.00 ATR;
- the +0.25 ATR floor cannot act until the next available one-second bar;
- an active-floor gap fills at the bar open, otherwise an OHLC touch fills at the floor;
- the scheduled opposing-flip decision boundary exits before that boundary bar's range;
- the known scheduled exit open is included as a reached discrete point for runner MFE;
- policy runner MFE stops at the policy exit and does not use later favorable range.

The active retained floor is closer than the original stop, so floor-first after activation is not an optimistic same-bar ordering claim: a continuous move to the stop must cross the floor first, and a gap through both produces the same open fill. Before activation, the declared conservative arm-bar rule gives the original stop priority when both stop and arm are contained in one OHLC bar.

Touch timestamps identify the containing open-labelled one-second bar; the output does not claim tick-exact touch time. The final report correctly labels Stage 2 as a one-second OHLC research simulation, not NT-native executable validation, and explicitly disclaims exact intrabar touch ordering.

## No 2026-driven selection

Stage 1 produced descriptive rows for both years, but its gate and selection function read 2025 only. The freeze was created from that audited 2025 gate before any 2026 Stage 2 policy replay. The 2026 CLI path could run only after the exact 2025 trade diff reconciled and sealed with current runner/freeze/audit/auth/data hashes.

No 2025 or 2026 policy result can mutate the freeze. The runner has no selection function after the freeze and combines years only for final reporting. The final report now accurately calls 2026 “selection-isolated,” states that the rule was frozen before the 2026 Stage 2 replay, and says explicitly that no 2026 metric altered selection. It does not claim that Stage 1 never computed 2026 descriptive geometry.

## Exact Stage 2 metrics

The delivered summary has 14 unique version/split rows and exactly equals an independent aggregation from the paired trade file.

| Sample | Baseline net | Policy net | Change | Baseline PF | Policy PF |
|---|---:|---:|---:|---:|---:|
| 2025 | -$17,608.99 | -$22,885.25 | -$5,276.26 | 0.9668 | 0.9484 |
| 2026 | $7,595.77 | $10,416.80 | $2,821.03 | 1.0363 | 1.0629 |
| Combined | -$10,013.22 | -$12,468.45 | -$2,455.23 | 0.9865 | 0.9795 |

Combined win rate rises from 31.0% to 52.1%, but net PnL and profit factor worsen. Direction and session results reconcile exactly:

- long fade: -$13,182.78 change, PF 0.9180 → 0.8557;
- short fade: +$10,727.55 change, PF 1.0473 → 1.0916;
- ETH: +$6,010.70 change, PF 0.9527 → 0.9613;
- RTH: -$8,465.93 change, PF 1.0211 → 0.9975.

Year/direction and year/session claims also match the trade file: long changes -$6,852/-$6,330, short +$1,576/+$9,151; ETH +$7,429/-$1,418 and RTH -$12,705/+$4,239 for 2025/2026 respectively.

Trade-level diagnostic counts are exact:

| Metric | 2025 | 2026 | Total |
|---|---:|---:|---:|
| Armed | 1,718 | 630 | 2,348 |
| Planned losers converted | 571 | 221 | 792 |
| Stop-after losses reduced | 110 | 45 | 155 |
| Planned winners clipped | 303 | 117 | 420 |
| Planned winners lost | 15 | 2 | 17 |

Planned-winner mean runner MFE lost is 1.017/0.892 ATR in 2025/2026; among clipped winners it is 3.301/2.663 ATR. All figures and the report's interpretation reconcile.

## Deliverables and report decision

All required deliverables exist:

- `pre_flip_mae_geometry.parquet`;
- `pre_stop_mfe_geometry.parquet`;
- `post_flip_giveback_geometry.parquet`;
- `policy_test_results.parquet`;
- `policy_test_trade_diffs.parquet`;
- `final_report.md`.

The report contains all required Stage 1 outcome geometry, compact year/direction/session views, conservative pre-stop MFE, all requested post-flip revisit definitions, one-policy Stage 2 comparison, conversion/clipping/runner-MFE diagnostics, year/direction/session stability, costs/contract limitations, evidence-versus-speculation separation, and the final decision.

`final_report.md` has SHA-256:

```text
aef037b84d4d90bda7fe55455d87f116566cb669a00d7a03aa79104c362e569c
```

The decision `NO_POLICY_IMPROVEMENT` is one of the prompt's permitted labels and follows directly from the predeclared process: the initial-stop branch failed its gate; the only tested post-flip rule worsened 2025 and combined economics; the favorable selection-isolated 2026 result is reported but is not used to rescue or retune the failed rule.

## Tests and finding closure

The exact current combined suite passes:

```text
10 passed in 0.38s
```

| Completion finding | Disposition |
|---|---|
| Report called 2026 “untouched”/“unopened” although Stage 1 had computed descriptive 2026 geometry | **Closed.** Report now says selection-isolated, locates the freeze before the 2026 Stage 2 replay, and explicitly denies 2026-driven selection. |
| Required +0.50 ATR and 25%-MFE post-peak revisit columns were omitted from the report | **Closed.** Both columns and exact values are present; +0.25/+0.50 conditional eligibility is explicit. |

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The complete study is causally bounded, hash-reconciled, exactly reproducible, and accurately reported. The appropriate final decision is `NO_POLICY_IMPROVEMENT`. Neither the tighter pre-flip stop nor the tested retained-profit floor should advance into the established-regime fade policy on this evidence. Any later direction-specific, session-specific, state-adaptive, or retuned management rule is a new study and may not use the observed 2026 asymmetry as a selection target.

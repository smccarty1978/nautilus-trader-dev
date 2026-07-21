# CODEX 5.X — Post-2026 / Pre-Policy Audit

**Scope:** immutable first-2026-open ledger, frozen manifest/bundle/authorization chain, repaired 2026 atlas and rebuild audit, 2021–2026 excursion distribution gate, frozen 2026 W4 evaluation artifacts, unchanged 2025 score/freeze artifacts, and the declared established-regime filter semantics.  
**Mode:** read-only artifact/source audit with independent full-row scans, raw-path samples, frozen-bundle score replay, and metric/crossing recomputation. No source, atlas, score, manifest, ledger, authorization, model, or policy artifact was modified. This report is the only file created.  
**Status:** **PASS — PRE-POLICY GATE SATISFIED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The 2026 atlas build and frozen W4 evaluation obeyed the authorized first-open contract. The first-open ledger matches the current manifest, authorization, bundle, and raw-2026 hashes exactly. The frozen manifest, bundle, freeze report, and both 2025 score exports are byte-for-byte unchanged from the pre-2026 audit.

The repaired 2026 atlas contains 1,289,840 causal checkpoints with zero sign, monotonicity, alias, ATR, timing, direction, duplicate-key, or rebuilt-only parity violations. The expanded 2021–2026 excursion distribution gate passes with zero repaired negative cells and zero monotonicity violations.

The 2026 model evaluation loaded the exact frozen 154-feature order, directional-pair models, direction-specific isotonic calibrators, and frozen H2 P90 thresholds. An independent replay through the frozen bundle reproduced all 1,289,840 calibrated scores with maximum absolute error `0.0`, all keys in exact order, and zero threshold differences. Directional AUCs remain approximately 0.77, all scores are finite, both directions cross at nonzero and balanced regime rates, and all stored metrics independently reproduce.

The repaired W4 therefore passes the declared pre-policy gate. The established-regime filter may remain numerically unchanged:

```text
age >= 120 seconds
running MFE >= 1.0 ATR
distinct progress windows >= 2
retained-MFE ratio >= 0.50
```

Those four inputs are causal and direction symmetric. The bearish repair changes the sign/alignment of local W4 structural features, but it does not change the established-filter definitions or their thresholds. Any new policy implementation must still receive its own mandatory pre-execution audit before it runs.

No policy code or policy result exists in the CODEX repair scope.

## First-open ledger and immutable freeze chain

The first-open ledger was created for `build repaired 2026 atlas` at:

```text
2026-07-13T23:58:30.733612+00:00
```

Its SHA-256 is:

```text
deaa0758f7b19188ff29e8cee803e6549fc32352166d6eb9894ec3baf86aa480
```

Every recorded hash independently matches the current file:

| Ledger field | Recorded/current SHA-256 | Match |
|---|---|:---:|
| Frozen manifest | `2b0cc6d0ffd7fdcf28f29a0a73e973fd6b5bc0a797121f23430d220e03dd2180` | Yes |
| Pre-2026 authorization | `94d92379d8ab21008f813f24b7ff72a1176bf959de2132a52d0a4e9e45babcd0` | Yes |
| Frozen bundle | `cd1243dc0dc0bd37f1141d9d42a732cf5d7e52fa900536f7b64b9acecb9dc237` | Yes |
| Raw 2026 input | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` | Yes |

The authorization remains `status=PASS`, points to the same manifest and bundle, and authorizes only sealed atlas build/frozen evaluation.

## No refreeze or pre-2026 artifact mutation

The current manifest SHA-256 is identical to the pre-2026 freeze-audit value. Its frozen structure, thresholds, train years, atlas hashes, dependency hashes, and `no_2026_access` statement are unchanged.

The following pre-2026 artifacts also retain their exact audited hashes:

| Artifact | SHA-256 before and after 2026 evaluation |
|---|---|
| Frozen bundle | `cd1243dc0dc0bd37f1141d9d42a732cf5d7e52fa900536f7b64b9acecb9dc237` |
| Full-2025 score export | `f97c4e739cb11b19dbaaa3954175bb4f44b8346b7cc10d791dde22a122edeac9` |
| H2 score export | `949946e8d2cfb127a587912e12f19a8fa9a94171a507dbc1aa968ecc798875fb` |
| Freeze report | `8a6099b1f34ba25b376da40f849f4fc9e56f6dfd2eb114f01a2059d1e8cde4ba` |

The presence of the first-open ledger now makes refreezing fail closed. No 2026 value altered model structure, features, calibrators, thresholds, or 2025 outputs.

## Repaired 2026 atlas integrity

### Artifact and parity reconciliation

The repaired 2026 year artifact has SHA-256:

```text
76192163897e2075dc72e1742ca38d6d3a24aa5977a21bbc537eb2ebc89e2d44
```

The rebuild audit has SHA-256:

```text
eab31087492eac07dddbd7e6b410c020739ee97e0632f62bbc29f4c7ff709404
```

Its population reconciliation is exact:

| Legacy rows | Repaired rows | Exact endpoints removed | No-path gap rows removed | Rebuilt-only keys |
|---:|---:|---:|---:|---:|
| 1,298,168 | 1,289,840 | 8,206 | 122 | 0 |

```text
1,298,168 - 8,206 - 122 = 1,289,840
```

The rebuild audit records the same raw hash as the first-open ledger and confirms the causal context, entry-ATR excursion denominator, and checkpoint-ATR alias contracts.

### Full stored-row scan

Every 2026 artifact row was independently scanned. Results:

- zero duplicate `(regime_start_ns, observation_time, direction)` keys;
- direction domain exactly `{-1, +1}`;
- all 154 frozen input columns present and unique;
- zero `feature_bar_ts_event >= observation_time` rows;
- zero `observation_time >= regime_end_ns` rows;
- zero `entry_ts_event < flip_decision_ns` rows;
- zero negative `current_mfe`, `current_mae`, `running_mfe`, or `running_mae` cells;
- zero `current_mfe != running_mfe` aliases;
- zero `current_mae != running_mae` aliases;
- zero within-regime MFE/MAE monotonicity violations;
- zero `atr != atr_at_checkpoint` cells;
- zero nonfinite or nonpositive `atr_at_entry` / `atr_at_checkpoint` cells.

### Independent raw-path sign and denominator samples

Six deterministic raw-path samples were selected across the 2026 period: three bearish and three bullish. Paths ranged from 104 to 713 one-second bars. For each row, the raw interval `[entry_ts_event, observation_time)` independently reproduced:

- exact `entry_open`;
- direction-aligned current PnL;
- bullish/bearish running MFE;
- bullish/bearish running MAE;
- normalization by `atr_at_entry`.

Maximum absolute error was `0.0` for all four stored quantities. Both direction branches are therefore correct in the final-test artifact.

## 2021–2026 excursion distribution gate

The expanded distribution Parquet contains the complete:

```text
2 versions × 6 years × 2 directions × 4 variables = 96 rows
```

The gate is `pass=true` for years 2021–2026 with:

- repaired negative count: `0`;
- repaired monotonicity violations: `0`.

Current hashes:

| Artifact | SHA-256 |
|---|---|
| Distribution gate | `beb13702136b495265f69193472ebd54c659e6b93a4feaea5fd2eb7a56ec99b2` |
| Distribution Parquet | `486b51f8b0399c06134cb3f33f4c0971744d5c9192b8563565acbfb179d58805` |
| Distribution report | `69e2891c0ed75b9decca74be52b11c255aff23a3fb4f5aaafa894aa589fbb5ff` |

The 2026 repaired medians are directionally balanced:

| Direction | Median running MFE | Median running MAE |
|---:|---:|---:|
| Short `-1` | 1.548701 ATR | 0.604788 ATR |
| Long `+1` | 1.549211 ATR | 0.597065 ATR |

This is consistent with a correct direction-aligned repair and inconsistent with recurrence of the legacy bearish sign defect.

## Frozen bundle evaluation replay

The evaluation source calls the sealed `require_frozen_pre_2026_contract` before loading 2026, then:

1. loads the frozen bundle;
2. requires frozen `base_features == BASE_FEATURES` and frozen interaction fields equal current definitions;
3. loads the 2026 atlas through the same endpoint/direction/NaN gates;
4. creates the matrix in frozen bundle order;
5. routes through the frozen selected structure;
6. applies the two frozen direction-specific calibrators;
7. uses the bundle's frozen thresholds.

An independent 13-batch replay of every 2026 atlas row through that bundle found:

- processed rows: 1,289,840;
- exact key mismatches: 0;
- maximum calibrated-score error versus stored export: `0.0`;
- frozen threshold mismatches: 0;
- frozen base-feature order equals current sealed order: yes;
- frozen interaction-local order equals current sealed order: yes.

This proves the stored 2026 scores were produced by the exact frozen bundle contract.

## Directional 2026 metrics and crossings

Targets were independently reconstructed from the stored future-label fields, and all metrics were recomputed from the score export.

### Model metrics

| Direction | Rows | Base rate | ROC-AUC | PR-AUC | Brier |
|---:|---:|---:|---:|---:|---:|
| Long `+1` | 653,438 | 0.3889274881 | 0.7723712625 | 0.6752657858 | 0.1865952522 |
| Short `-1` | 636,402 | 0.3929245980 | 0.7685870135 | 0.6727269826 | 0.1886037063 |

These reproduce `CODEX_5_X_model_metrics_2026.parquet` exactly.

### Frozen thresholds and strict crossings

| Direction | Frozen threshold | Finite rate | Strict crosses | Regimes | Crossed regimes | Crossing rate |
|---:|---:|---:|---:|---:|---:|---:|
| Short `-1` | 0.7183653372722797 | 1.000 | 11,794 | 4,458 | 3,854 | 0.8645132346 |
| Long `+1` | 0.6883498713708196 | 1.000 | 12,873 | 4,463 | 4,042 | 0.9056688326 |

Stable within-regime previous-below/current-at-or-above recomputation exactly matches the stored distribution. The descriptive 2026 directional balance ratio is:

```text
0.9056688326 / 0.8645132346 = 1.0476055153
```

Both crossing rates are nonzero and well balanced. All scores are finite. The 2026 score export contains one unique score row per atlas checkpoint, exact frozen thresholds, valid ATR aliases, and `score_valid == isfinite(w4_score)`.

Current 2026 output hashes:

| Artifact | SHA-256 |
|---|---|
| Directional model metrics | `c9b8ab843f16eb3291f3be5c2360f30ec22c3209649c9f596e97034f36447076` |
| Crossing distributions | `bc5011264f88a64e0141ea638d394894e7b690e9e903071582b0f544499dce14` |
| Score export | `c5c1b42da0d5b0e42be36cb1642a04865d46d8601cf5d7abed0ba9ff360300a8` |
| 2026 report | `9261b17936a77ca430b1b39398a23c3709f8b957543a32af422fff09f61be94d` |

## Declared pre-policy W4 gate

The gate remains the frozen pre-2026 decision gate; 2026 is final-test evidence and does not retroactively select or reject parameters.

| Requirement | Evidence | Result |
|---|---|:---:|
| Unit tests pass | Last authorized isolated suite: 25 passed; sealed dependency hashes unchanged | PASS |
| No repaired negatives/monotonic violations | Expanded 2021–2026 gate: 0 / 0 | PASS |
| Finite-score rate ≥99% each direction | H2: 100% / 100% | PASS |
| H1 selected AUC >0.50 each direction | Long 0.772405; short 0.770096 | PASS |
| H2 crossing regime rate nonzero each direction | Long 0.876952; short 0.846209 | PASS |
| Larger/smaller crossing-rate ratio ≤2 | 1.036330 | PASS |

**Declared pre-policy W4 gate: PASS.** The 2026 results independently remain healthy—AUCs near 0.77, 100% finite scores, nonzero crossings, and balance ratio 1.0476—but did not alter the frozen gate.

## Established-regime filter disposition

The established filter can remain unchanged.

### Why the thresholds remain semantically valid

1. **Age ≥120 seconds** is pure timestamp elapsed time and is unaffected by excursion signs or W4 repair.
2. **Running MFE ≥1.0 ATR** is a nonnegative direction-aligned favorable excursion. The repaired bullish and bearish formulas now share exactly this meaning.
3. **At least two distinct progress windows** counts temporally separated increases in direction-aligned running MFE. It is direction symmetric and causal.
4. **Retained-MFE ratio ≥0.50** is direction-aligned current PnL divided by positive running MFE. Both numerator and denominator are aligned to trade/regime direction, making the ratio symmetric.

The original established-filter implementation computed these states directly from raw paths with separate bullish and bearish branches; it did not rely on the defective negative bearish atlas columns. The repair changes local W4 features (`current_mfe`, `current_mae`, `giveback`, and their direction interactions) and therefore correctly changes repaired W4 model structure/scores. It does not change what “1 ATR favorable,” “new progress,” or “50% retained” means.

The 2026 repaired distribution provides an additional semantic check: median running MFE is virtually identical long versus short, and all stored values are nonnegative and monotone.

### Conditions for future policy implementation

Keeping thresholds unchanged does not waive implementation auditing. New CODEX policy code must explicitly preserve:

- causal running state only through the decision time;
- direction-aligned MFE and current PnL;
- the frozen entry-ATR denominator/anchor contract;
- distinct progress-window timing without future extremes;
- retained ratio from state available at decision;
- frozen direction-specific W4 thresholds;
- explicit next-available one-second-open OHLC entry and the declared stop/exit contract.

That code must receive the mandatory pre-execution stop/fill/lookahead audit before any run.

## No policy execution

No file in the CODEX repair scope is named or structured as a policy, trade simulation, Stage 2 runner, or OHLC execution result. The current executable files are limited to atlas/regime construction, comparison, common seal logic, and W4 training/evaluation. This audit did not run a policy.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The repaired W4 passes its declared pre-policy gate, the 2026 final-test evaluation is a valid frozen-contract result, and the established direction-symmetric filter thresholds may remain unchanged. Creation of tightly scoped CODEX policy code is now permitted, but the policy must not run until that new execution/stop/exit implementation passes its own mandatory pre-execution lookahead audit.

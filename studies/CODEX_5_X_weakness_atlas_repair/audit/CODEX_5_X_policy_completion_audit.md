# CODEX 5.X Established Fade — Policy Completion Audit

**Scope:** authorized policy runner and frozen contract; pre-execution authorization chain; 2025 and 2026 candidate, trigger-audit, trade, skipped-candidate, summary, and reconciliation artifacts; fresh canonical regime timelines; raw one-second execution paths; and `results/CODEX_5_X_FINAL_REPORT.md`.  
**Mode:** post-execution read-only artifact and full-row causal/execution audit. No policy result was regenerated or modified by the auditor. A reporting omission identified during audit was corrected in the final report and re-audited before this PASS.  
**Status:** **PASS — COMPLETION GATE SATISFIED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The completed 2025 development run and untouched 2026 final run conform to the exact authorized one-second OHLC research contract. The frozen runner, policy, input contract, audit, authorization, raw bars, repaired atlases, frozen scores, manifest, bundle, and first-open ledger are unchanged. The 2025 reconciliation predates the 2026 reconciliation and the 2026 gate binds the exact clean 2025 predecessor dependency seal.

An independent full-row replay verified every one of the 4,383 completed trades against raw one-second OHLC bars and a freshly reconstructed canonical flip timeline. Entry opens, entry delays, fill-time sessions, stop levels, entry-bar activation, ordinary stop touches, adverse gap fills, scheduled flip exits, prices, timestamps, costs, PnL, and holding periods reproduce exactly with maximum absolute error `0.0`. There are no unresolved or false-censored trades.

Candidate accounting, position-state skips, trigger-audit joins, summaries, and reconciliations close exactly in both years. Both long and short trades participate materially. The final report's policy, gross/net performance, direction/session sensitivity, exit counts, and conclusion all reproduce from the stored artifacts.

The final decision `NO_MONETIZABLE_WEAKNESS_FADE` is warranted. The frozen policy loses in 2025 and loses across the combined 2025–2026 sample after the fixed cost assumption. The modest 2026 result has a profit factor of only 1.036 and does not override the negative development result. The report correctly declines NT execution validation and labels the output as a one-second OHLC research simulation, not an NT-validated or deployable strategy.

## Authorization, frozen inputs, and chronology

The active authorization passes its exact runtime validation and binds:

| Artifact | SHA-256 |
|---|---|
| Policy runner | `70d4dbad865fa52ed1d054941562f76f1ba4009edc8f693169c1044e2a5bf633` |
| Frozen policy | `1a22e4adaf7ebf141cb9b9011c4b5d05f7da8b0de7130ee4f7f7bcea7bc77c5b` |
| Frozen input contract | `aa5fab90f6c3afd73f19797cd4a7010eca8b0e83de1727f9750c3c8398214e79` |
| Policy pre-execution audit | `1a717f87b128363c1071c52228a99e9786550880a13e86677dd3197881fe33b2` |
| Policy pre-execution authorization | `4570dbc982355eff8100ec665d1f87007fed5633ea19dd27dd1a231b350cbb4e` |

Independent frozen-input validation passes for both years:

| Input | 2025 SHA-256 | 2026 SHA-256 |
|---|---|---|
| Raw one-second bars | `c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d` | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` |
| Repaired atlas | `c654da5016f7ec4bf26be11a390992dff851d38e81684a2a19f0bbed90ad9ce7` | `76192163897e2075dc72e1742ca38d6d3a24aa5977a21bbc537eb2ebc89e2d44` |
| Frozen W4 scores | `f97c4e739cb11b19dbaaa3954175bb4f44b8346b7cc10d791dde22a122edeac9` | `c5c1b42da0d5b0e42be36cb1642a04865d46d8601cf5d7abed0ba9ff360300a8` |

The manifest, bundle, and first-open hashes also remain exactly:

```text
manifest   2b0cc6d0ffd7fdcf28f29a0a73e973fd6b5bc0a797121f23430d220e03dd2180
bundle     cd1243dc0dc0bd37f1141d9d42a732cf5d7e52fa900536f7b64b9acecb9dc237
first_open deaa0758f7b19188ff29e8cee803e6549fc32352166d6eb9894ec3baf86aa480
```

The 2025 reconciliation was written before the 2026 reconciliation. Both store the same exact 2025 dependency seal. Recomputing that seal from current files matches exactly, and the runner's mandatory predecessor gate passes. Therefore 2026 could not have run under this contract without the clean, hash-matched 2025 predecessor.

## Candidate, trigger, and closure reconciliation

| Year | Trigger crossings failing filter | Eligible candidates | Trades | Skipped | Closure residual | Blocking errors |
|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 61,048 | 3,530 | 3,246 | 284 | 0 | 0 |
| 2026 | 20,608 | 1,237 | 1,137 | 100 | 0 | 0 |

Every eligible trigger-audit row joins one-to-one to exactly one candidate with identical direction, score, threshold, age, MFE, MAE, progress-window count, and retention ratio. Candidate decisions are chronologically sorted, unique by regime, strictly before the confirming flip, and use the direction opposite the prevailing regime. All meet the frozen age, MFE, progress, retention, and score-threshold requirements.

The trade and skipped-candidate keys are disjoint and their union is exactly the candidate set. There are no duplicate candidate, trade, or skipped keys. A sequential replay of `busy_until`, next-open availability, and confirming-flip cancellation reproduces every stored trade/skip decision and reason:

| Year | Position-open skips | Next open at/after confirming flip | Other skip reasons |
|---:|---:|---:|---:|
| 2025 | 278 | 6 | 0 |
| 2026 | 99 | 1 | 0 |

## Independent execution replay

Fresh canonical timelines contain 27,166 regimes for 2025 and 8,935 for 2026. Each is strictly ordered and alternating, with exactly one `None` end belonging to the true trailing regime. Atlas-populated direction/end parity passes. Three executed trades use confirming regimes with no checkpoint rows in the atlas—two in 2025 and one in 2026—and all three receive the correct known next-flip exit from the complete canonical timeline. This directly confirms that checkpointless regimes do not create false censoring.

For every trade, the audit independently recomputed:

- first raw `ts_event >= decision_ts` and its exact open;
- fill delay and RTH/ETH session from the actual fill timestamp;
- stop as `entry_fill_open - entry_direction × 1.5 × atr_at_checkpoint`;
- stop submission at entry and entry-bar stop reach;
- first stop-touch bar before the scheduled market exit;
- adverse-open price for a gap through the stop, otherwise exact stop price;
- confirming-regime end and first available raw open at or after the next against-flip decision;
- scheduled-market-exit priority before the range of its fill bar;
- `gross_pnl_pts`, NQ `$20/point` gross PnL, fixed `$10` round-trip cost, net PnL, and hold time.

Results:

| Year | Entry/exit replay errors | Stops | Gap-through stops | Scheduled flip exits | Censored exits | Maximum price/PnL/time error |
|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 0 | 1,385 | 250 | 1,861 | 0 | 0.0 |
| 2026 | 0 | 466 | 87 | 671 | 0 | 0.0 |

The stop-reason splits also reproduce exactly:

| Year | Opposite flip | Stop before aligned flip | Stop after aligned flip |
|---:|---:|---:|---:|
| 2025 | 1,861 | 1,107 | 278 |
| 2026 | 671 | 369 | 97 |

## Summary and final-report reconciliation

All stored summary keys and every summary metric—count, mean and total net PnL, win rate, profit factor, stop rate, and median holding time—recompute with zero discrepancy for all, direction, session, direction/session, and exit-reason slices.

| Period | Trades | Longs | Shorts | Mean gross | Total gross | Mean net | Total net | Win rate | PF | Stop rate | Median hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 3,246 | 1,390 | 1,856 | +$4.58 | +$14,851.01 | -$5.42 | -$17,608.99 | 30.84% | 0.967 | 42.67% | 491.5s |
| 2026 | 1,137 | 481 | 656 | +$16.68 | +$18,965.77 | +$6.68 | +$7,595.77 | 31.57% | 1.036 | 40.99% | 535.0s |

Combined gross PnL is `+$33,816.78` or `+$7.72/trade`. Combined net PnL is `-$10,013.22` or `-$2.28/trade` across 4,383 resolved trades. Long participation is 42.82% in 2025 and 42.30% in 2026, so the repaired policy is not effectively short-only. Long fades lose in both years. The direction and RTH/ETH figures in the final report exactly match the independent aggregates.

The final report initially omitted gross performance and exit-reason counts required by the study prompt. Those reporting-only omissions were corrected during the audit. The patched figures and the added statement that all 4,383 trades are resolved reproduce exactly; no analytical or policy result changed.

The final report SHA-256 after correction is:

```text
c1e71af788c2c5fe01870a09ba39b3d3d31167fbff92e8e2ecb9c0528ef0a2d6
```

## Deterministic test gate

The isolated suite was rerun without bytecode or pytest cache writes:

```text
PYTHONDONTWRITEBYTECODE=1
pytest -p no:cacheprovider
43 passed in 1.33s
```

Coverage includes causal progress state, strict regime-local crossings, both stop directions, entry-bar activation, adverse gaps, scheduled-exit priority, checkpointless regimes, delayed next opens and fill-time sessions, overlap state, malformed input rejection, audit/hash gates, and reconciliation-before-output behavior.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The completed artifacts and corrected final report satisfy the authorized research contract and reporting requirements. The evidence supports `NO_MONETIZABLE_WEAKNESS_FADE`; it does not support advancement to NT execution validation or deployment.

# CODEX 5 W4 Countertrade Path Diagnostic — Completion Audit

**Scope:** regenerated `results/` artifacts and refreshed `final_report.md`, traced against the exact authorized `build_diagnostic.py`, `config.json`, `SPEC.md`, frozen CODEX 5.X trades/W4/raw/atlas inputs, and imported canonical-regime dependencies.  
**Mode:** mandatory post-execution completion audit after repair of the open-labelled OHLC peak availability defect.  
**Status:** **PASS — OUTPUTS AND REPORT COMPLETE**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The corrected diagnostic was regenerated under the current pre-execution authorization and is reproducible from the frozen inputs. All four parquet artifacts and the run manifest are byte-identical to an independent clean rebuild. That rebuild completed without all-NaN aggregation warnings, regex warnings, or any other runtime warning.

Independent raw-bar reconciliation covered every one of the 1,320,819 path rows. Price mark timestamp/source, PnL, running MFE, running MAE, and old-prevailing-regime favorable-extreme status produced zero mismatches and zero numerical error. Independent W4 reconciliation likewise produced zero mismatches in active regime, observation availability, score, threshold, change from entry, threshold state, entry-regime identity, and 15/30/60-second slopes.

All 4,383 holding peaks were independently reconstructed from the frozen one-second bars and stored fills. The source bar timestamp is separated from causal availability for every OHLC-derived peak, every named peak checkpoint occurs at availability rather than the bar-open label, and the post-flip diagnostic has exact nullable timestamps. The repaired report uses the resulting availability-based timing medians and explicitly labels outcome groups and named peak selection as retrospective descriptive labels.

The result remains an exploratory one-second OHLC path diagnostic. It is not a policy backtest, an optimized rule, an NT-native execution validation, or evidence that any proposed management rule improves expectancy.

## Authorized source and current report

| Artifact | SHA-256 |
|---|---|
| `build_diagnostic.py` | `0fbfc96c1c905e0ef31176783ec0aec0c95092a14e6dab6fc757860c5a84f8b7` |
| `config.json` | `c5b5a367d499b6315576e83b1f8b4f81beb29159c997438adc8601ca764ae8d5` |
| `SPEC.md` | `b317f4d9a1f0245f2ea39f5c4a92842158a4fe45fce52905017cd6b6e435db68` |
| `pre_execution_audit.md` | `e22767f4bf3fd1c70308292d7063842375f9052e50bae6e4c2bed42203e63a3c` |
| `final_report.md` | `fa3de8cffd760293dda1098c6628ae55aed6907df328e5733ec42c7a0675ddae` |

The pre-execution authorization matches the first four bound hashes exactly, and the runtime authorization and frozen-input gates pass.

## Manifest and reproducibility

The manifest reports `DIAGNOSTIC_OUTPUTS_COMPLETE`, 4,383 trades, and 1,320,819 path rows. Every listed hash matches the current file and an independent clean rebuild:

| Output | Manifest/current/rebuild SHA-256 |
|---|---|
| `path_checkpoints.parquet` | `a06d73ccecc15668f42c08f71c52692f29ff2a4a9aefbb74754980472113c993` |
| `outcome_group_summary.parquet` | `0b89b4d86049a97d682552b1db3b46fa5317b5477ba2923d54bcc4da6847b7a2` |
| `early_window_summary.parquet` | `6370a05311037680b17c311eea48982e108bddace0beef3b941c6c618e33450e` |
| `post_flip_exit_diagnostic.parquet` | `fcfe949d070c4f2685372397d9c715001af527210d3fe2332b6ec7911101d84a` |

The manifest itself is also byte-identical to the clean rebuild (`84acc063a7661253de3edc247e6290f76eb5ee1549df5b09c4deccb1b4854cc9`). Rebuild counts were 3,246 trades / 971,157 rows for 2025 and 1,137 trades / 349,662 rows for 2026.

Outcome coverage is exact and exhaustive:

| Outcome | Trades |
|---|---:|
| Stop before aligning flip | 1,476 |
| Stop after aligning flip | 375 |
| Planned opposite-flip winner | 1,360 |
| Planned opposite-flip loser | 1,172 |

## Full path reconciliation

An independent vectorized reconstruction from each year's frozen raw one-second bars and frozen trades checked all 1,320,819 rows, not a sample.

| Field family | Mismatches | Maximum absolute error |
|---|---:|---:|
| Outcome/direction/session metadata | 0 | — |
| Price mark timestamp and source | 0 | — |
| Countertrade unrealized PnL / ATR | 0 | `0.0` |
| Running MFE / ATR | 0 | `0.0` |
| Running MAE / ATR | 0 | `0.0` |
| Old-prevailing-regime new favorable extreme | 0 | — |
| Active canonical regime | 0 | — |
| W4 availability/null state and observation timestamp | 0 | — |
| W4 score, threshold, and change from entry | 0 | `0.0` |
| W4 threshold state and same-entry-regime flag | 0 | — |
| W4 15/30/60-second slopes | 0 | `0.0` |

There are 728,093 W4-available rows and 592,726 explicitly unavailable rows. Every available observation is backward-only and no more than five seconds stale. Delayed aligning-flip opens are not misrepresented as checkpoint-time information: their `price_mark_time` is the actual first available open at or after the flip boundary and their source is `aligning_flip_next_open`. Ordinary rows use only the last completed one-second close; entry and final exit use their explicit stored fills.

Path keys are unique by trade/timestamp, all trades are covered, and each trade's rows are monotonic. The complete anchored five-second grids, fixed +60/+120 counterfactual windows, exact event rows, final exits, and strict after-exit labels pass the runtime validator in both the clean rebuild and the combined output validation.

## Peak localization and availability

Independent holding-peak reconstruction across all 4,383 trades found 4,244 OHLC-range peaks and 139 zero-MFE entry peaks. All 4,383 trades have exactly one `countertrade_peak_mfe` named row, and every row timestamp equals the reconstructed causal availability timestamp.

For every OHLC peak, the source bar is the open-labelled interval `[t,t+1s)` and availability is exactly `t+1s`. A zero-MFE peak has no bar timestamp and is available at entry. No stored planned-exit open exceeded the earlier holding peak in this frozen sample, although the contract correctly supports that source.

The 2,907 reached-alignment diagnostics independently reconcile as follows:

- holding peak: 2,897 OHLC-range peaks and 10 entry-zero peaks;
- post-flip peak: 2,906 OHLC-range peaks and one aligning-flip-open peak;
- zero mismatches in peak value, source, source-bar timestamp/null state, or availability timestamp.

`holding_peak_bar_ts_event`, `post_flip_peak_bar_ts_event`, `post_flip_peak_available_ts`, and `first_post_flip_w4_warning_ts` remain exact nullable `Int64` fields. Availability drives the named holding-peak row, holding time, peak-to-exit time, and post-flip time-to-peak. The stop bar remains excluded from primary holding MFE and retained only as the separately labeled upper bound, so the output makes no unsupported intrabar ordering claim.

## Summaries and report reconciliation

The overall/year/direction/session outcome summaries and +60/+120 early-window summaries were regenerated from the reconciled records and are byte-identical to the clean rebuild. Structurally inapplicable metrics remain null rather than being reduced through an all-NaN group. A warning-capturing clean rebuild emitted no all-NaN or regex warning.

Every numerical statement and table entry in `final_report.md` was reconciled against the current summaries or trade-level post-flip diagnostic. This includes counts, stop MFE thresholds, W4 states/changes, aligning-flip PnL, post-flip peaks/giveback, warning incidence/timing/PnL, profitable-at-warning and warning-before-peak rates, early-window PnL/MFE/MAE/W4 rates, and all cited year/direction/session splits.

The availability repair is reflected consistently in the report:

- pre-flip stop median time to peak availability: 17 seconds;
- pre-flip stop median peak-availability-to-stop time: 140 seconds;
- planned-winner median flip-to-peak availability: 639 seconds;
- planned-loser median flip-to-peak availability: 75 seconds;
- planned-loser median peak-to-exit duration: 237.5 seconds, reported as 238 seconds in prose.

Completion review initially found stale 638/74-second prose in one “Strongest path differences” bullet after the regenerated table had already moved to 639/75. The report was corrected without changing any data artifact, and its current hash above contains the consistent 639/75 values.

The report's qualitative claims are bounded by the delivered evidence. It states that price-path separation and preventable-looking giveback are descriptive findings, while explicitly denying that any probation, break-even, trailing, or W4-conditioned exit has been validated. It also states that path price/W4 observations are causal at their stored timestamps while outcome groups and the selected named peak are retrospective labels unavailable to a live policy. No 2026 result is used to choose a parameter or alter a policy.

## Test and warning result

The isolated contract suite passes against the exact current source:

```text
23 passed in 0.43s
```

The independent output rebuild completed with exit code zero and printed only its two yearly count lines. It emitted no runtime warning. Audit-only reconciliation code produced no study output and did not modify the authorized artifacts.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The regenerated outputs and refreshed report satisfy the causal timestamp, one-second OHLC availability, frozen-input, reproducibility, summary, and labeling contracts. Any later change to source, config, specification, frozen inputs/dependencies, output parquet files, manifest, or report invalidates this completion audit and requires renewed review.

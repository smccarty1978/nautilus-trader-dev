# CODEX 5 W4 Countertrade Path Diagnostic — Pre-Execution Audit

**Scope:** `SPEC.md`, `config.json`, `build_diagnostic.py`, and `tests/test_path_contract.py`, traced against the frozen CODEX 5.X policy artifacts, raw Databento one-second bars, repaired atlas/score contract, imported canonical regime logic, AGENTS.md, and the exploratory diagnostic prompt.  
**Mode:** pre-execution source, timestamp, causality, dependency, and deterministic-test delta re-audit after completion review found an open-label peak-timestamp defect. Existing result files belong to the superseded prior script and are not valid outputs of the current source. The corrected diagnostic has not been rerun.  
**Status:** **PASS — DIAGNOSTIC EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The current diagnostic is descriptive and causal. It does not search thresholds, simulate an alternative policy, select parameters from 2026, or change any frozen trade. Exact SHA-256 validation covers both years' trades, scores, raw bars, and repaired atlases, the frozen policy, and all imported causal code capable of changing raw validation or the canonical regime timeline. Execution is additionally blocked unless a clean audit and separate authorization bind the exact script, config, specification, and audit report.

Databento one-second bars are treated as open-labelled intervals `[t,t+1s)`. Ordinary checkpoint price marks use only the last completed close with `ts_event < checkpoint_time`. Entry and final exit use their stored explicit fill prices. The aligning flip is marked at the first available raw one-second open at or after the flip decision, with its possibly delayed `price_mark_time` and source retained explicitly.

W4 lookup is backward-only, five-second stale at most, and keyed to the active canonical regime at each checkpoint. The active regime changes exactly at every canonical flip, including multiple flips in counterfactual post-exit horizons. W4 is never carried across a regime boundary. Slopes compare observations from the same active regime and require at least the configured 15/30/60-second elapsed interval. Post-flip warning and aligned-regime trajectory windows end strictly before the causal exit boundary.

The stop path does not claim intrabar ordering. Primary MFE excludes the stop bar's unknown OHLC range; the stop-bar OHLC favorable extreme is reported only as an upper bound. The known stop fill is included as a discrete price point. Planned exit opens are known discrete points and can set the holding or post-flip peak. OHLC-derived peaks retain the source bar's open-labelled `ts_event` for localization but become available and receive their named checkpoint only at `ts_event + 1s`. Every stored row's marked PnL therefore lies inside its own running MFE/MAE envelope.

The current isolated suite passes all 23 tests. All issues found during iterative pre-execution and completion review were repaired and re-audited. There are no remaining critical findings or warnings.

## Frozen input and dependency gate

`validate_frozen_inputs` builds the complete current hash dictionary and requires exact dictionary equality with `config.json` before reading any diagnostic input into the study loop. Independent validation passes.

| Frozen input | 2025 SHA-256 | 2026 SHA-256 |
|---|---|---|
| Completed trades | `149e2b039935a9dbf61cb2a0ff416ef0550f95e94c61a278b1a56998c718ef2e` | `1bfe5696c24b990ee4ad693abfe707315fa92b7195837f193af32e6c0c062c83` |
| Repaired W4 scores | `f97c4e739cb11b19dbaaa3954175bb4f44b8346b7cc10d791dde22a122edeac9` | `c5c1b42da0d5b0e42be36cb1642a04865d46d8601cf5d7abed0ba9ff360300a8` |
| Raw one-second bars | `c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d` | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` |
| Repaired atlas | `c654da5016f7ec4bf26be11a390992dff851d38e81684a2a19f0bbed90ad9ce7` | `76192163897e2075dc72e1742ca38d6d3a24aa5977a21bbc537eb2ebc89e2d44` |

The frozen policy remains:

```text
1a22e4adaf7ebf141cb9b9011c4b5d05f7da8b0de7130ee4f7f7bcea7bc77c5b
```

Imported executable dependencies are also frozen and validated:

| Dependency | SHA-256 |
|---|---|
| CODEX 5.X policy runner | `70d4dbad865fa52ed1d054941562f76f1ba4009edc8f693169c1044e2a5bf633` |
| CODEX 5.X common paths/hash module | `302fab7b64178ee7626300048e9d1b66ab04b64c4a429a3fcbcd48175523e1c7` |
| Canonical regime reproduction module | `33823e22055836aa0c4914474ee01724e3e18c432a723079e9bf7a2c011137da` |

A synthetic mutation test proves that a changed imported-code dependency fails the exact hash gate. This prevents a post-authorization change in canonical timeline construction or raw validation from silently changing diagnostic results.

## No optimization or 2026 selection

- `exploratory_only` and `no_policy_backtest` are mandatory runtime guardrails.
- The script contains no parameter loop, objective, candidate comparison, threshold fitting, policy entry, stop, or exit simulation.
- Entry scores, direction thresholds, trades, stops, exits, and outcomes are loaded from byte-frozen artifacts.
- The warning threshold is each score row's already-frozen direction threshold; it is not estimated from either diagnostic year.
- 2025 and 2026 are processed under the identical fixed config only for descriptive comparison.
- No 2026 statistic can alter the config, filter, W4 trigger, stop, exit, or grouping rule.

## Timestamp and price contract

For a checkpoint boundary `t`:

- raw OHLC ranges use only indices with `ts_event < t`;
- the ordinary checkpoint mark is the last close from that completed interval;
- entry uses the stored explicit next-open fill;
- aligning-flip PnL uses the first available raw open with `ts_event >= aligning_flip_ts`, including when a data gap delays it;
- final exit uses the stored boundary-open or stop fill;
- `price_mark_time` and `price_mark_source` make boundary-vs-fill timing explicit.

Known discrete marks are included symmetrically in running MFE/MAE and in the original-prevailing-regime new-extreme flag. Thus a delayed open cannot produce a row PnL outside the row's extrema or be omitted from the causal new-extreme diagnostic.

The original-regime baseline uses raw ranges from its frozen causal entry through strictly before the countertrade entry. Subsequent new-extreme checks compare only price information known by each row's explicit mark. Bullish and bearish calculations are direction symmetric.

## Stop-bar and peak semantics

For every stop exit:

- primary holding MFE scans `[entry_fill_ts, stop_fill_ts)` and excludes the stop bar;
- the stored stop fill is included as a known point in PnL/MAE;
- the stop bar's full favorable OHLC range appears only in `stop_bar_mfe_upper_bound_atr`;
- threshold flags such as `mfe_ge_0p50_before_stop` use the conservative primary MFE, not the upper bound.

For planned flip exits, the stored exit open is an actually reached point. It can therefore become the holding or post-flip peak, with peak time equal to the exit fill timestamp. This keeps capture ratios and peak-to-exit giveback coherent without introducing any assumption about the exit bar's later OHLC ordering.

For an OHLC-derived peak in an open-labelled bar `[t,t+1s)`, `*_peak_bar_ts_event=t` is retained only as retrospective localization. `*_peak_available_ts=t+1s` is the causal completion boundary and drives the named peak checkpoint, time-to-peak, peak-to-exit time, and post-flip timing fields. Zero-MFE entry peaks and known aligning/scheduled-open peaks remain available at their exact discrete mark timestamps. Optional bar and availability timestamps are written as nullable `Int64` values.

All excursion values use `atr_at_checkpoint`, the same denominator as the frozen 1.5 ATR stop.

## W4 causality and regime reset

`ScoreLookup.latest` uses a right-edge binary search for observations no later than the checkpoint and rejects joins more than five seconds stale. Slope baselines are independently looked up in the same active regime at the earlier boundary and are emitted only when observation-time separation is at least the requested window.

`active_regime_start` searches the complete, strictly ordered canonical flip sequence. At the aligning flip boundary the regime key changes from the original prevailing regime to the aligned regime. Later counterfactual rows follow any additional canonical flips rather than retaining the aligned or entry regime. `w4_same_regime_as_entry` explicitly marks whether `w4_change_from_entry` is within-regime or cross-regime.

For planned exits, the W4 end is `scheduled_exit_decision_ts`, not a potentially delayed market fill. For stop exits it is the stop fill timestamp. Warning and aligned-regime first/last/max/change/above-threshold calculations use `[aligning_flip_ts, W4 exit boundary)`, so the exit boundary is excluded. Last pre-exit W4 is queried against the causal boundary rather than a later delayed fill.

Optional nanosecond fields are constructed directly as nullable `Int64` arrays from the original Python integers. A test above `2^53` verifies exact preservation and prevents float64 timestamp rounding.

## Checkpoint coverage and counterfactual labels

Each trade contains:

- a complete five-second grid anchored at entry through the configured horizon;
- exact entry offsets at +30/+60/+90/+120/+180/+300 seconds;
- exact aligning-flip, aligning-flip +60/+120 seconds, peak-MFE, and final-exit rows.

The horizon is the later of entry +300 seconds, aligning flip +120 seconds, or actual exit. Independent preflight checks confirm every frozen trade's horizon is within its year's raw-data end. Fixed horizons after an early exit are retained and labeled `counterfactual_after_exit=True` strictly when `checkpoint_time > exit_fill_ts`; the final exit itself is not counterfactual.

`validate_outputs` requires exact trade-ID coverage in paths and diagnostics, unique checkpoint timestamps, monotonic ordering, a complete grid with exact first and final anchors, every named label at its computed timestamp, exact after-exit labeling, and no forward W4 join. Synthetic corruption tests reject dropped grid endpoints and misplaced named labels.

The first authorized attempt exposed an event-label collision before any output write: when entry and peak MFE shared a timestamp, the former dictionary literal retained only the peak label, so validation correctly rejected the missing entry label. `named_times` now routes every entry, flip, peak, exit, entry-offset, and post-flip label through a single additive `add()` helper. Colliding timestamps retain all labels in deterministic insertion order; path serialization deduplicates only identical labels. A direct entry/peak collision regression test passes, and the additive construction applies identically to every other event collision.

Completion review then identified that an OHLC peak label used the peak bar's open timestamp even though the path row at that boundary correctly excluded the still-forming bar. The current code places the named peak row at the one-second completion/availability boundary and retains the bar timestamp separately. A direct regression proves the peak bar range is present at the named checkpoint rather than being labeled one second early.

## Outcome groups and summaries

Outcome grouping is fixed and exhaustive for the frozen exits:

- stop before aligning flip;
- stop after aligning flip;
- planned opposite-flip winner when stored net PnL is strictly positive;
- planned opposite-flip loser when stored net PnL is zero or negative.

The script produces outcome-group summaries overall and by year, trade direction, and RTH/ETH session. Metrics include count; means and medians for realized PnL, aligning-flip PnL, holding/post-flip peaks and timing, giveback/capture, W4 warning timing/PnL, last W4, and aligned-regime W4 trajectory; and rates for stop MFE thresholds, original-regime new extremes, W4 threshold state, and post-flip warnings.

The early-window summary retains all trades at +60/+120 seconds, including explicitly labeled counterfactual rows after early exits. It reports active-trade and already-flipped rates, price-path metrics, W4 change/availability/threshold rates, and old-prevailing new-extreme rate. The raw five-second and named-checkpoint path remains available for all other fixed horizons without survivor filtering.

The post-flip artifact excludes only `stop_before_aligned_flip`, matching the fact that those trades never reach an aligned-regime diagnostic interval.

Metrics that are structurally inapplicable to an outcome group remain explicit `NaN` cells: planned exits have no stop-threshold flags, and pre-alignment stops have no aligned/post-flip measurements. Aggregation now checks for a nonempty non-null applicability set before mean or median calculation, so these expected cells no longer emit all-NaN runtime warnings.

## Validation results

The isolated contract suite was rerun against the corrected source without rerunning the diagnostic:

```text
PYTHONDONTWRITEBYTECODE=1
pytest -p no:cacheprovider tests/test_path_contract.py
23 passed in 0.40s
```

Tests cover direction symmetry, completed-bar marks, delayed explicit opens, stop-bar MFE bounds, favorable scheduled-exit gaps, OHLC peak localization versus availability, backward/stale W4 lookup, exit-boundary exclusion, regime reset, outcome grouping, additive event-label collisions, exact named/grid coverage, strict after-exit labeling, nanosecond preservation, dependency mutation, and fail-closed invalid direction handling.

## Prior-finding closure

| Finding identified during audit | Final disposition |
|---|---|
| Delayed aligning-flip PnL/path row used a stale prior close | **Closed.** Both diagnostic and path mark use the explicit next available open; mark time/source are persisted and tested. |
| Output reconciliation did not enforce complete grid/named rows or exact labels | **Closed.** Exact IDs, endpoints, timestamps, uniqueness, monotonicity, after-exit labels, and backward W4 joins are enforced and corruption-tested. |
| Planned exit open omitted from holding/post-flip peak and final-row MFE | **Closed.** Known exit open is included for non-stop trades; stop-bar OHLC conservatism is unchanged. |
| Planned W4 interval used delayed fill rather than causal exit decision | **Closed.** Planned W4 end is the scheduled exit decision; stop W4 end is the stop fill. |
| Optional nanosecond timestamps risked float64 rounding | **Closed.** Nullable `Int64` construction preserves original integers exactly. |
| Imported canonical-regime code was not hash-bound | **Closed.** Runner, common module, and regime reproduction source are frozen and runtime-validated. |
| Known boundary marks were omitted from row extrema/new-extreme flags | **Closed.** Every known discrete mark is included direction symmetrically; stop-bar OHLC remains excluded from primary MFE. |
| Colliding named events overwrote the entry label and failed first-run validation | **Closed.** All labels now accumulate through one helper; collision behavior is regression-tested. The failed attempt wrote no result file. |
| OHLC peak labels/timing used the bar-open label before the peak range was complete | **Closed.** Bar localization and causal availability are separate; named rows and all timing use `bar_ts_event + 1s`, while known discrete-open peaks remain exact. |
| Expected all-NaN applicability groups emitted aggregation warnings | **Closed.** Empty applicability sets emit explicit NaN without invoking mean/median reductions. |

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The exact current diagnostic is authorized to regenerate and replace the superseded result set once. Any change to the script, config, specification, audit, frozen data, policy, or imported causal dependencies invalidates authorization and must trigger a new audit. Outputs must remain labeled exploratory one-second OHLC diagnostics and must not claim exact stop-bar intrabar ordering, live availability of retrospective outcome/peak labels, NT-native execution validation, or a validated policy edge.

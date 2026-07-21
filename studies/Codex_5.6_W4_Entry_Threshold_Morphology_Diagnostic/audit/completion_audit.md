# Completion Lookahead, Causality, and Reproducibility Audit

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope

Independently audited the completed `Codex_5.6_W4_Entry_Threshold_Morphology_Diagnostic` study against the frozen repaired W4 scores/trades, raw 2025/2026 one-second bars, and the previously audited confirmation-clock Policy A inputs. All generated Parquet artifacts, `final_report.md`, and `run_manifest.json` were checked. The study runner was not modified.

## Manifest, hashes, and frozen population

- Every output SHA-256 in `run_manifest.json` matches the current artifact.
- Runner, config, and clean pre-execution-audit hashes match the manifest and bound authorization.
- All frozen input hashes match the current raw bars, repaired scores/trades, confirmation-clock artifacts, upstream runners/common module, and confirmation-clock completion audit.
- The output preserves the exact 4,383-entry population: 3,246 trades from 2025 and 1,137 from 2026, with the same deterministic trade IDs and no duplicates or omissions.
- `trade_morphology_features.parquet` contains exactly one row per frozen trade.

## Score grid, timestamps, and censoring

- `score_paths.parquet` contains exactly 214,767 rows: 4,383 trades × 49 trigger-relative five-second checkpoints from -120 through +120 seconds.
- Offset zero exactly equals each frozen causal `decision_ts`, and its score equals the frozen trade's W4 trigger score.
- Every non-null score, threshold, validity flag, and score margin was independently joined back to the frozen yearly score artifacts and matched exactly.
- Score availability equals the declared censor union for every cell:
  - 23,657 flip-censored cells at `checkpoint_ts >= confirm_flip_ns`;
  - 3,048 administratively censored cells beyond regime age 1,800 seconds;
  - 1,131 cells carrying both censor causes.
- No successor-regime score is substituted after an aligning flip, no censored cell contains a score, and no at-risk cell is missing one.

## Independent feature reconstruction

All 4,383 morphology rows were independently recomputed from the frozen score paths. Exact matches were obtained for entry overshoot, all declared deltas, velocity/acceleration, pre-cross dwell counts and durations, monotonicity, sign changes, standard deviation/range, local extrema, threshold crosses, consecutive persistence, first-below timing, first-60-second at-risk/above-threshold exposure, censor flags, nullable collapse state, fixed-checkpoint margins, availability, gate states, local highs, and near-build flags.

The first-60-second durations correctly use completed five-second intervals in `[0, 60)`. Collapse is unresolved rather than false when censoring prevents observation through 60 seconds unless a collapse was already observed.

## Raw one-second price verification

Independently replayed every trade's +5, +10, +15, +30, +60, and +120 second price checkpoint directly from the frozen raw one-second bars.

- Every entry timestamp mapped to the exact raw bar open and frozen `entry_fill_open`.
- Marks used the last completed bar with timestamp strictly before each boundary.
- Directional PnL, MFE, and MAE matched all 26,298 trade/checkpoint combinations exactly.
- MFE/MAE used only the same completed-bar slice, the frozen fill baseline, and the correct long/short geometry.
- Underwater/favorable and immediate-adverse flags reconcile to those paths.

## Outcomes, splits, summaries, and paths

- All quick winner, late winner, planned loser, stop-before, Policy A timeout, and Policy A stop-after memberships were independently regenerated from frozen baseline and audited Policy A fields and matched exactly.
- `trade_direction` exactly follows validated frozen `entry_direction`; year, direction, and RTH/ETH membership match the frozen trades.
- All 12 group morphology rows were recomputed, including trade counts, medians, p25/p75 values, collapse-observable/unresolved denominators, and flip/admin censor counts.
- All 132 group score-path rows were recomputed. Trade counts, at-risk/censor counts, and score-margin p25/median/p75 values match for every group and reported offset.

## Gates and comparison tables

All 105 gate rows were independently reconstructed across overall, year, direction, and session splits. For every gate and subset, retained, removed, and unevaluable statuses are mutually exclusive and exhaustive. Trade counts, original baseline net PnL, baseline winners, quick winners, stop-before losses, and planned losers match exactly.

Administrative score unavailability is not mislabeled as removal; a regime ending by the score-confirmation checkpoint is correctly rejected. Price-response gates use completed-bar marks. The artifacts and report correctly describe these as original-entry selection diagnostics, not delayed-entry policy results.

All 120 comparison rows match independent recomputation for both sides of the five required comparisons, including trade count, mean, median, p25, and p75 for every metric.

## Report and decision

Every numerical statement in `final_report.md` was traced to the audited trade-level artifacts. This includes persistence medians, score-delta and near-build comparisons, collapse rates and their 791/1,471 observable denominators, +30-second directional PnL and underwater rates, yearly stability rows, and all fixed gate-retention table values.

The decision rule was independently evaluated:

- quick-winner minus stop-before median +30-second PnL gap: **3.25 points**;
- stop-before minus quick-winner underwater-rate gap: **0.380595**.

Both fixed conditions pass, producing `PRICE_RESPONSE_CONFIRMATION_PROMISING`, exactly matching the manifest and report. Persistence and collapse do not drive the label. The report explicitly requires a separate causal delayed-entry replay and makes no executable-performance claim.

## Execution warnings

Execution emitted pandas `FutureWarning` messages about silent object downcasting during `fillna(False)`. These are deprecation notices, not data or causality warnings. The code immediately applies explicit Boolean conversion, the tri-state masks were independently reconstructed, and every gate row reconciles exactly. The notices do not affect current results, frozen artifact hashes, or semantic reproducibility and are therefore non-material.

## Conclusion

The completed study is reproducible under its frozen inputs, preserves causal timestamp boundaries, handles flip and administrative censoring explicitly, and accurately labels its outputs as retrospective descriptive diagnostics. It passes the repository's completion audit with zero critical findings and zero warnings.

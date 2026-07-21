# W4 Entry Threshold Morphology Diagnostic - Final Report

## Scope and contract

This is retrospective descriptive analysis of the exact repaired **4,383** W4 fade entries. W4 was not retrained or rescored. Entry membership, fills, thresholds, baseline exits, and audited Policy A outcomes remain frozen. Score time zero is the causal 5-second trigger observation; price time zero is the next available 1-second entry-fill open. Post-entry price checkpoints use only completed 1-second bars.

The frozen W4 score exists only while the entry's prevailing regime remains active and only through the atlas's 30-minute regime-age horizon. Checkpoints at or after the aligning flip are flip-censored rather than filled with successor-regime scores; checkpoints beyond 30 minutes are administratively censored. Score-path tables include at-risk and both censor-cause counts at every offset. Confirmation gates treat a regime ending before confirmation as rejection, while administratively unavailable checkpoints are unevaluable. Persistence comparisons are descriptive competing-event summaries and do not drive the decision label.

Candidate confirmation tables below are selection diagnostics on the original entries and original PnL. They are **not causal policy results** because confirmation would delay fills.

## Main answers

1. **Persistence while at risk:** quick winners' median observed first-60s above-threshold time was **35.0s**, versus **20.0s** for stop-before losses, **35.0s** for Policy A timeouts, and **30.0s** for planned losers. These durations end at an aligning flip and must be read with the at-risk counts, not as uncensored survival estimates.
2. **Spike-through:** median 5-second crossing delta was **0.1038** for quick winners versus **0.0959** for stop-before losses. The full distributions are in `comparison_tables.parquet`; no data-selected spike cutoff was created.
3. **Near-threshold build:** quick winners had a median **2.0** prior checkpoints within 0.10 of threshold versus **2.0** for stop-before losses.
4. **Immediate collapse among observable paths:** collapse by +60s occurred in **77.9%** of **791** observable quick-winner paths versus **92.1%** of **1471** observable stop-before-loss paths. Censored-without-collapse paths are excluded rather than counted as non-collapses; full observable/unresolved and censor-cause counts are in the group summary.
5. **Immediate price response:** median directional PnL at +30s was **1.50 points** for quick winners versus **-1.75 points** for stop-before losses; underwater rates were **32.9%** and **70.9%**, respectively.
6. **Replay candidates:** only gates showing meaningful descriptive separation should advance, and every such gate requires a separate delayed-entry replay at the first available 1-second open after confirmation.
7. **Year stability:**

| Year | Quick winners | Quick persistence median | Stop-before persistence median | Quick delta-5s median | Stop delta-5s median |
|---:|---:|---:|---:|---:|---:|
| 2025 | 800 | 35.0 | 20.0 | 0.0977 | 0.0923 |
| 2026 | 292 | 35.0 | 20.0 | 0.1160 | 0.0970 |

## Fixed descriptive gate retention

| Gate | Retained trades | Retained baseline net PnL | Retained quick winners | Retained stop-before losses | Retained planned losers |
|---|---:|---:|---:|---:|---:|
| GATE_1_ABOVE_AT_5S | 2866 | $56,641.51 | 759 | 868 | 783 |
| GATE_2_ABOVE_AT_10S | 2515 | $45,019.51 | 696 | 696 | 727 |
| GATE_4_NEAR_BUILD_PRIOR_30S | 3405 | $-28,765.82 | 838 | 1125 | 937 |
| GATE_5_NONADVERSE_AT_10S | 2221 | $65,808.07 | 646 | 557 | 666 |
| GATE_5_NONADVERSE_AT_30S | 2208 | $173,234.64 | 733 | 429 | 717 |

Administrative-unavailable gate cases are emitted with status `unevaluable` and are excluded from retained/removed counts. Gate 3 is intentionally distribution-only: the specification forbids freezing a numeric spike threshold before inspecting distributions. No optimized threshold or performance claim was created.

## Decision

`PRICE_RESPONSE_CONFIRMATION_PROMISING`

This label nominates a hypothesis for causal delayed-entry replay; it does not amend Policy A or establish executable performance.

## Reproducible artifacts

- `trade_morphology_features.parquet`: one row per frozen trade.
- `score_paths.parquet`: exact requested score checkpoints.
- `group_morphology_summary.parquet`: morphology distributions by outcome/year/direction/session.
- `group_score_paths.parquet`: median and p25/p75 score-margin paths.
- `comparison_tables.parquet`: the five required compact comparisons.
- `candidate_gate_retention.parquet`: retained/removed baseline outcome accounting and splits.
- `run_manifest.json`: configuration, hashes, row counts, and decision label.

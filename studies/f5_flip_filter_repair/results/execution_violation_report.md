# Execution Violation Report
**Original violations reported (prior study):** 64 (all F2 population; F1 had 0)
**Violations found on independent re-detection:** 64

## Classification
All 64 violations are `decision_after_terminal_time`: the F2 confirmation decision (close of the confirmation 1m bar) occurs strictly after the episode's own terminal time `ep_end_time = min(opposing_flip_time, flip_time+30min)`.

### Root cause
`build_flip_atlas.py` selects the confirmation bar as `df_1m_list[idx+1]` -- the next row in the 1-minute bar *array* -- rather than the next bar within a bounded wall-clock tolerance of the flip. When the underlying 1m bar sequence has a gap (CME daily maintenance break, weekend/holiday closure, or thin-liquidity gap in raw 1s data), `idx+1`'s close timestamp can land far enough in wall-clock time that it falls after the episode's fixed 30-minute timeout, or even after the opposing-flip timestamp found earlier by the same forward scan (which also has no gap tolerance). This makes 64 'confirmed F2 entries' decisions made after their own episode had already economically terminated -- there is no valid trade to take.

**Observed gap distribution:** min=0
gap seconds: min=1860, median=1860, max=188160 (52.3h)

### Per-population, per-canonical-period breakdown
period_role
dev_test             1
secondary_2025H2     7
secondary_2026       8
train               46
validation           2

## Repair
All 64 episodes are excluded from the eligible F2 population (`repair = exclude_episode_from_eligible_population`). No entry, exit, or feature values are altered for any other episode.

## Post-repair assertion results
```json
{
  "decision_ts_le_fill_ts": true,
  "feature_ts_le_decision_ts": true,
  "entry_ts_lt_terminal_ts_violations_remaining": 0,
  "exit_ts_le_terminal_ts_check": "guaranteed_by_replay_construction",
  "duplicate_episode_ids": 0,
  "post_exit_position_check": "no_dedicated_flag_in_cache_structurally_guaranteed",
  "incomplete_bar_use_check": "no_dedicated_flag_in_cache_structurally_guaranteed",
  "future_regime_outcome_as_feature": "see_f5_score_reproduction_phase4_for_leakage_check"
}
```

**critical_execution_violations_remaining = 0**

Additionally, 61 F2 episodes were excluded for a separate, non-critical reason: `entry_price`/`exit_price`/`pnl_base` are null because the forward 1-second replay slice ran past the end of that calendar year's raw data file (year-boundary censoring). These are documented as `missing_replay_bar` and excluded from all economics but are not boundary violations (their observation_time never exceeds ep_end_time).

# Prior Contextual Study — Implementation Audit

Scope: `studies/rl_regime_feasibility/contextual_runner_exit/` (run_study.py, results/).

## 1. Multi-timeframe feature families

Implemented 3/11 requested families.

| Requested family | Implemented in prior? | matched tokens |
|---|---|---|
| slope_and_slope_change | NO | — |
| directional_efficiency | YES | progress_efficiency |
| favorable_vs_adverse_vol | NO | — |
| new_extreme_rate | NO | — |
| time_since_htf_extreme | NO | — |
| structural_hh_hl | NO | — |
| range_position | YES | position_in_trailing |
| volume_per_progress | NO | — |
| volume_per_retracement | NO | — |
| prior_pullback_recovery | NO | — |
| aligned_returns_multi_horizon | YES | ar_180s, ar_300s, ar_900s |

**Finding:** the prior 'MTF' block was essentially longer-window aligned returns plus a few cross-return ratios. Slope/slope-change, directional efficiency at higher horizons, favorable-vs-adverse volatility, new-extreme rate, structural HH/HL state, volume-per-progress, volume-per-retracement and pullback-recovery history were NOT implemented. Per the interpretation rule, MTF context was therefore never actually tested.

## 2. Regime-quality state collapse

- Saved `regime_quality_states.parquet` is a `.head(2000)` sample: `True` (rows in file: 2,000).
- Episode attribution used state at the FIRST checkpoint (`groupby('episode_id').first()[...regime_quality]`): `True`.

Forensic reproduction on the atlas test period (5,660 episodes) with a crude age-percentile state:

| Attribution | %ORDINARY | %HEALTHY | %PROLIFIC |
|---|---|---|---|
| first_checkpoint (prior bug) | 100.0% | 0.0% | 0.0% |
| last_checkpoint | 63.0% | 19.6% | 17.3% |
| modal | 65.5% | 18.1% | 16.4% |

**Root cause of the 5642/5660 ORDINARY collapse:** at the first checkpoint (~30s in) MFE is tiny, so the age-percentile is low and the state is ORDINARY for almost every episode. Taking `.first()` therefore stamps nearly the whole population ORDINARY regardless of what happened at the actual exit decision. The repair attaches state at the DECISION checkpoint and evaluates the state at every checkpoint (not a 2000-row sample).

## 3. P1c selection

- Prior best policy chosen by argmax over TEST-period policy EV: `True`. P1c (+$2.23/trade) was therefore an EXPLORATORY, test-selected result, not a validation-frozen out-of-sample winner. The repair freezes all policy definitions/thresholds on train+val before the single dev-test replay.

## 4. Weakness-stop proof-of-concept

- POC columns: ['episode_id', 'weakness_class', 'is_prolific', 'pnl_immediate_exit', 'pnl_e0', 'delta_immediate_vs_e0']
- Contains real stop-order fields (level/trigger/fill): `False`.

**Finding:** the POC compared immediate-exit vs E0 PnL but did not activate or monitor a real stop order (no stop level, activation time, trigger time, fill price, or recovery-vs-stop resolution). The 'weakness stop is null' conclusion was unsupported. The repair runs a real 1s-monitored stop simulation (Phase 8).

## Summary of required repairs

1. Implement the full MTF family set (returns/slope, efficiency, vol-decomposition, extremes, volume-response, structural, pullback, cross).
2. Evaluate regime state at every checkpoint; attribute at the decision checkpoint; save the full population.
3. Freeze all policies on train+val; replay dev-test once.
4. Run a real weakness-triggered stop simulation monitored on 1s bars.
# CAPABILITY_GAP_HANDOFF — nq_va_multitf_trade_state_geometry

Generated 2026-09-20T18:46:00.245767+00:00 on platform commit `d83be2fd00c351fdf187bf4451d2efa123e9f664`, branch `study/nq_va_multitf_trade_state_geometry`.

**STUDY OWNER: STOP. Do not implement this capability in the study session. Commit this file and END THE SESSION.**

## Research question

# NQ V_A multi-timeframe trade-state geometry (descriptive)

How do canonical confirmed 1-minute V_A flip-to-flip trades evolve through quick failure,
slow/grinding deterioration, and large trend-runner states when viewed jointly with 5m / 15m / 1h
regime state, higher-timeframe regime geometry, normalized structural levels, and fixed-time path
information?

The purpose is to build a causal, ATR-normalized map of the full UNTREATED flip-to-flip trade path
inside 5m/15m/1h current and prior regime geometry, using fixed-time observations (T0/T15/T30/T60/
T120/T300) so that informative depth and speed variation is preserved, and to determine whether the
data supports separate ensemble heads for (1) initial risk, (2) trend health / giveback, and
(3) runner preservation.

Descriptive only. Not an entry-filter search, not exit optimization, not a stop/PT sweep, not a
policy study. No stop, no target, no trailing exit, no higher-timeframe exit, no entry filter.
2023 discovery, 2024 frozen validation, 2025 SEALED, 2026 prohibited.

## Gaps (compiler evidence)

- `MISSING_CAPABILITY` at `context.mtf_state`: no registered tracker 'tracker.regime.completed_state_feed' (closest: `tracker.regime.dual_ema`)
- `INVALID_PARAMETERIZATION` at `features.instances[2]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_age_min supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[3]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_age_min supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[4]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_duration_min: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[5]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_duration_min: {'context': 'current', 'timeframe': '5m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[6]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[7]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[8]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_mfe_atr: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[10]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[11]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[12]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_range_atr: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[14]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[15]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[16]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_directional_move_atr: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[17]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_directional_move_atr: {'context': 'current', 'timeframe': '5m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[18]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[19]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[20]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_directional_displacement_atr: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[22]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_directional_displacement_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[23]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_directional_displacement_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[24]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_efficiency: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[26]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[27]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[28]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_move_atr_per_min: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[29]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_move_atr_per_min: {'context': 'current', 'timeframe': '5m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[30]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_move_atr_per_min supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[31]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_move_atr_per_min supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[32]`: UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_range_atr_per_min: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}
- `INVALID_PARAMETERIZATION` at `features.instances[34]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr_per_min supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[35]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr_per_min supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[37]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[38]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[40]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[41]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[43]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[44]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[46]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[47]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[49]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[50]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[51]`: UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '5m'
- `INVALID_PARAMETERIZATION` at `features.instances[52]`: UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[53]`: UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[54]`: UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '5m'
- `INVALID_PARAMETERIZATION` at `features.instances[55]`: UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[56]`: UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[57]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '1m'
- `INVALID_PARAMETERIZATION` at `features.instances[59]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[60]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '1h'
- `INVALID_PARAMETERIZATION` at `features.instances[62]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_alignment supports ['1m', '5m'], not '15m'
- `INVALID_PARAMETERIZATION` at `features.instances[63]`: UNSUPPORTED_TIMEFRAME_PARAMETER: regime_alignment supports ['1m', '5m'], not '1h'

## Requested semantics (from study.yaml at each gap)

- `context.mtf_state` -> `{"tracker": "regime.completed_state_feed", "timeframes": ["1m", "5m", "15m", "1h"], "atr_period": 14}`
- `features.instances[2]` -> `{"feature": "regime_mfe_atr", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[3]` -> `{"feature": "regime_range_atr", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[4]` -> `{"feature": "regime_net_directional_move_atr", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[5]` -> `{"feature": "regime_directional_displacement_atr", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[6]` -> `{"feature": "regime_efficiency", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[7]` -> `{"feature": "regime_net_move_atr_per_min", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[8]` -> `{"feature": "regime_range_atr_per_min", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[10]` -> `{"feature": "regime_range_atr", "over": {"timeframe": ["5m", "15m", "1h"]}, "context": "prior"}`
- `features.instances[11]` -> `{"feature": "regime_net_directional_move_atr", "over": {"timeframe": ["5m", "15m", "1h"]}, "context": "prior"}`
- `features.instances[12]` -> `{"feature": "regime_efficiency", "over": {"timeframe": ["5m", "15m", "1h"]}, "context": "prior"}`
- `features.instances[14]` -> `{"feature": "fraction_of_counter_regime_move_recovered", "over": {"timeframe": ["5m", "15m", "1h"]}}`
- `features.instances[15]` -> `{"feature": "recovery_from_counter_regime_extreme_atr", "over": {"timeframe": ["5m", "15m", "1h"]}}`
- `features.instances[16]` -> `{"feature": "regime_direction", "over": {"timeframe": ["1m", "5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[17]` -> `{"feature": "regime_alignment", "over": {"source_timeframe": ["1m"], "reference_timeframe": ["5m", "15m", "1h"]}, "context": "current"}`
- `features.instances[18]` -> `{"feature": "structural_current_expansion_atr", "over": {"context": ["current"]}}`
- `features.instances[19]` -> `{"feature": "structural_max_expansion_atr", "over": {"context": ["current"]}}`
- `features.instances[20]` -> `{"feature": "structural_giveback_atr", "over": {"context": ["current"]}}`
- `features.instances[22]` -> `{"feature": "structural_expansion_atr_per_min", "over": {"context": ["current"]}}`
- `features.instances[23]` -> `{"feature": "distance_to_completed_range_high_atr", "over": {"reference_timeframe": ["5m"]}, "bar_state": "completed"}`
- `features.instances[24]` -> `{"feature": "distance_to_completed_range_low_atr", "over": {"reference_timeframe": ["5m"]}, "bar_state": "completed"}`
- `features.instances[26]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[27]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[28]` -> `"UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_move_atr_per_min: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}"`
- `features.instances[29]` -> `"UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_net_move_atr_per_min: {'context': 'current', 'timeframe': '5m', 'bar_state': 'completed'}"`
- `features.instances[30]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_move_atr_per_min supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[31]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_move_atr_per_min supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[32]` -> `"UNSUPPORTED_FEATURE_PARAMETER_COMBINATION: regime_range_atr_per_min: {'context': 'current', 'timeframe': '1m', 'bar_state': 'completed'}"`
- `features.instances[34]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr_per_min supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[35]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr_per_min supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[37]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[38]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_mfe_atr supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[40]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[41]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_range_atr supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[43]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[44]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_net_directional_move_atr supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[46]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[47]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_efficiency supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[49]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '15m'"`
- `features.instances[50]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_duration_min supports ['1m', '5m', '5s'], not '1h'"`
- `features.instances[51]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '5m'"`
- `features.instances[52]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '15m'"`
- `features.instances[53]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: fraction_of_counter_regime_move_recovered supports ['5s'], not '1h'"`
- `features.instances[54]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '5m'"`
- `features.instances[55]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '15m'"`
- `features.instances[56]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: recovery_from_counter_regime_extreme_atr supports ['5s'], not '1h'"`
- `features.instances[57]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '1m'"`
- `features.instances[59]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '15m'"`
- `features.instances[60]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_direction supports ['5m'], not '1h'"`
- `features.instances[62]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_alignment supports ['1m', '5m'], not '15m'"`
- `features.instances[63]` -> `"UNSUPPORTED_TIMEFRAME_PARAMETER: regime_alignment supports ['1m', '5m'], not '1h'"`

## Affected YAML fields

- context.mtf_state
- features.instances[10]
- features.instances[11]
- features.instances[12]
- features.instances[14]
- features.instances[15]
- features.instances[16]
- features.instances[17]
- features.instances[18]
- features.instances[19]
- features.instances[20]
- features.instances[22]
- features.instances[23]
- features.instances[24]
- features.instances[26]
- features.instances[27]
- features.instances[28]
- features.instances[29]
- features.instances[2]
- features.instances[30]
- features.instances[31]
- features.instances[32]
- features.instances[34]
- features.instances[35]
- features.instances[37]
- features.instances[38]
- features.instances[3]
- features.instances[40]
- features.instances[41]
- features.instances[43]
- features.instances[44]
- features.instances[46]
- features.instances[47]
- features.instances[49]
- features.instances[4]
- features.instances[50]
- features.instances[51]
- features.instances[52]
- features.instances[53]
- features.instances[54]
- features.instances[55]
- features.instances[56]
- features.instances[57]
- features.instances[59]
- features.instances[5]
- features.instances[60]
- features.instances[62]
- features.instances[63]
- features.instances[6]
- features.instances[7]
- features.instances[8]

## Existing nearest capabilities

- tracker.regime.dual_ema

## Scientific decisions already resolved

```json
{
  "terminal_decisions": {},
  "autonomy_decisions": {
    "on_capability_gap": "stop_and_handoff",
    "platform_change_required": "chore_branch_and_fresh_session",
    "deterministic_defect": "auto_fix",
    "calendar_reference_parity": "common_interval_exact",
    "frozen_parent_model": "rescore_if_authenticated",
    "protected_period": "never_expand_authority"
  }
}
```

## Prohibited for the study owner

- modifying research_workflow/ (grammar, compiler, host, controller, outcomes, provider bindings)
- modifying features/ or the capability registry seeds from the study branch
- building the missing capability inside the study session
- patching around the gap with study Python
- continuing to accumulate context after this handoff: END THE SESSION

## Suggested platform files (hint)

- features/definitions/canonical/<name>.py
- features/definitions/golden/<name>.json
- features/definitions/promotions/<name>.json (written by `research feature promote`)
- features/trackers/
- features/trackers/host_bindings.py
- research_workflow/capabilities_index.yaml
- research_workflow/grammar/compiler.py
- research_workflow/provider_host.py

## Next action

Study owner: END THIS SESSION. Do not implement. Commit study.yaml + research_decision.yaml + this handoff on the study branch first.

Capability session (fresh, short):

- python scripts/research.py ws chore claim nq_va_multitf_trade_state_geometry-missing_capability --paths features/definitions/canonical/<name>.py features/definitions/golden/<name>.json features/definitions/promotions/<name>.json (written by `research feature promote`) --surface "<one line>" --as <agent>
- git worktree add "../<repo>-nq_va_multitf_trade_state_geometry-missing_capability" -b chore/nq_va_multitf_trade_state_geometry-missing_capability main
- implement ONLY the capability named above; targeted tests; research cap generate --check; audit/promotion if the capability flow requires it
- git switch main && git merge --no-ff chore/<topic>; write CAPABILITY_COMPLETE card (research study handoff --study <study> --phase A --note CAPABILITY_COMPLETE:<topic>)
- python scripts/research.py ws chore release nq_va_multitf_trade_state_geometry-missing_capability

Resume session (fresh):

- git -C <study worktree> merge --no-ff main
- python scripts/research.py ws claim nq_va_multitf_trade_state_geometry --as <agent>
- python scripts/research.py study compile --study studies/nq_va_multitf_trade_state_geometry

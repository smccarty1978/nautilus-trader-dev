# CAPABILITY_GAP_HANDOFF — nq_fair_pricing_reversion

Generated 2026-10-09T15:45:38.065463+00:00 on platform commit `4f53d9ae21fb0daf26aabfd51a22bbf6bd0662c7`, branch `study/nq_fair_pricing_reversion`.

**STUDY OWNER: STOP. Do not implement this capability in the study session. Commit this file and END THE SESSION.**

## Research question

Does NQ exhibit a statistically meaningful tendency to revisit its regular-session opening price following intraday displacement, and do displacement-candle or confirmed BOS entries improve subsequent reversion outcomes?

## Gaps (compiler evidence)

- `MISSING_CAPABILITY` at `features.instances`: feature host cannot bind the surface: RUNTIME_PROVIDER_BINDING_MISSING: canonical provider 'features.trackers.generic_price_levels.GenericPriceLevelProvider' (needed by ['distance_to_level']) has no registered RuntimeProviderAdapter
- `UNSUPPORTED_COMPOSITION` at `outcome.event`: predicate references unknown context tracker 'anchor'
- `INVALID_PARAMETERIZATION` at `outcome`: an outcome needs a barrier, an event, or both

## Requested semantics (from study.yaml at each gap)

- `features.instances` -> `[{"feature": "distance_to_level", "level": "rth_open", "level_context": "session", "normalization": "points", "timeframe": "1m"}]`
- `outcome.event` -> `"anchor.reverted"`
- `outcome` -> `{"kind": "label", "entry_reference": "next_bar_open", "event": "anchor.reverted", "horizon": "5400s"}`

## Affected YAML fields

- features.instances
- outcome
- outcome.event

## Existing nearest capabilities

- none named by the compiler; use `research cap search`

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
- research_workflow/grammar/spec.py
- research_workflow/host/outcomes.py
- research_workflow/provider_host.py
- research_workflow/target_replay_oracle.py

## Next action

Study owner: END THIS SESSION. Do not implement. Commit study.yaml + research_decision.yaml + this handoff on the study branch first.

Capability session (fresh, short):

- python scripts/research.py ws chore claim nq_fair_pricing_reversion-missing_capability --paths features/definitions/canonical/<name>.py features/definitions/golden/<name>.json features/definitions/promotions/<name>.json (written by `research feature promote`) --surface "<one line>" --as <agent>
- git worktree add "../<repo>-nq_fair_pricing_reversion-missing_capability" -b chore/nq_fair_pricing_reversion-missing_capability main
- implement ONLY the capability named above; targeted tests; research cap generate --check; audit/promotion if the capability flow requires it
- git switch main && git merge --no-ff chore/<topic>; write CAPABILITY_COMPLETE card (research study handoff --study <study> --phase A --note CAPABILITY_COMPLETE:<topic>)
- python scripts/research.py ws chore release nq_fair_pricing_reversion-missing_capability

Resume session (fresh):

- git -C <study worktree> merge --no-ff main
- python scripts/research.py ws claim nq_fair_pricing_reversion --as <agent>
- python scripts/research.py study compile --study studies/nq_fair_pricing_reversion

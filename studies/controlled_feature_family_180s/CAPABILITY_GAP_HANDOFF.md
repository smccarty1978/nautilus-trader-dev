# CAPABILITY_GAP_HANDOFF — controlled_feature_family_180s

Generated 2026-09-06T14:08:23.016326+00:00 on platform commit `843e84dd0b2a16be0c8260fab35cdef5c7eefa93`, branch `study/controlled_feature_family_180s`.

**STUDY OWNER: STOP. Do not implement this capability in the study session. Commit this file and END THE SESSION.**

## Research question

# Controlled feature-family additions to the frozen 180s flip model

Do volume/activity, directional delta/order-flow, or shorter-horizon productivity features add
stable forward classification information beyond the existing 13-feature 180-second regime-flip
baseline?

Four PREDECLARED arms on one collected population, compared pairwise against the 13-feature
control: A (baseline 13), B (+volume/activity), C (+direction-normalized estimated delta),
D (+60s/120s rolling productivity). No combined arm. No tuning. No feature selection.

## Gaps (compiler evidence)

- `MISSING_CAPABILITY` at `analysis.steps[1].op`: 'analysis.gate.arm_delta_integrity' is not a registered analysis operation (closest: `analysis.gate.population_parity`)

## Requested semantics (from study.yaml at each gap)

- `analysis.steps[1].op` -> `"analysis.gate.arm_delta_integrity"`

## Affected YAML fields

- analysis.steps[1].op

## Existing nearest capabilities

- analysis.gate.population_parity

## Scientific decisions already resolved

```json
{
  "terminal_decisions": {},
  "autonomy_decisions": {
    "platform_merge": "auto_if_green",
    "closed_study_merge": "auto_if_clean"
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

- research/analysis/
- research_workflow/analysis_v2.py

## Next action

Study owner: END THIS SESSION. Do not implement. Commit study.yaml + research_decision.yaml + this handoff on the study branch first.

Capability session (fresh, short):

- python scripts/research.py ws chore claim controlled_feature_family_180s-missing_capability --paths research/analysis/ research_workflow/analysis_v2.py --surface "<one line>" --as <agent>
- git worktree add "../<repo>-controlled_feature_family_180s-missing_capability" -b chore/controlled_feature_family_180s-missing_capability main
- implement ONLY the capability named above; targeted tests; research cap generate --check; audit/promotion if the capability flow requires it
- git switch main && git merge --no-ff chore/<topic>; write CAPABILITY_COMPLETE card (research study handoff --study <study> --phase A --note CAPABILITY_COMPLETE:<topic>)
- python scripts/research.py ws chore release controlled_feature_family_180s-missing_capability

Resume session (fresh):

- git -C <study worktree> merge --no-ff main
- python scripts/research.py ws claim controlled_feature_family_180s --as <agent>
- python scripts/research.py study compile --study studies/controlled_feature_family_180s

---

## Required op contract (added by the study owner; read study.yaml `analysis.steps[1]` for the bytes)

The study declares the gate exactly as:

```yaml
- id: arm_delta_integrity
  op: analysis.gate.arm_delta_integrity
  rows: frame
  params:
    baseline_arm: A_BASELINE_13
    scope: per_cell                     # LONG / SHORT are fit separately; a block can be dead in one cell only
    min_non_null_rate: 0.95             # (a) the added block is populated on the FITTED population
    require_positive_variance: true     # (b) and is not constant
    require_distinct_fit_identity: true # (c) and the fit actually differs from the baseline arm's
    require_distinct_predictions: true  # (d) and the predictions are not byte-identical
```

Semantics required, in one sentence: RAISE (aborting `analyze` before any declared artifact is
written) unless, for every non-baseline arm and every declared cell, the arm's ADDED feature
block (its columns minus the baseline arm's columns) is populated at >= `min_non_null_rate`,
has non-zero variance, and produced a model whose `fit_identity_sha256` and whose predictions
on the fitted population both differ from the baseline arm's. Rationale: at `num_leaves 4 /
max_depth 5` a degenerate added block is simply ignored, the arm collapses onto the baseline,
and the paired delta is ~0 with balanced fold signs -- indistinguishable from the genuine
negative result this study is most likely to report. `check_feature_surface.py` refuses only an
ALL-NULL column; it establishes neither variance nor prediction distinctness.

### Integration constraint the implementer will hit

`research_workflow/lifecycle_v2.py::_declared_analysis` dispatches every step through
`research.analysis.diagnostic_ops.run_op(op, rows, inputs=..., params=..., context=...)` and the
context it passes today is **only** `{"studies_root": ...}` (lifecycle_v2.py:1165). Checks (c)
and (d) need the fitted arms, i.e. `artifacts/experiment_models.json` (written by the `fit`
stage, which precedes `analyze`) plus the model-store bundles it points at -- and the current
context carries no study id or study dir with which to find them. Expect to extend that context
(or the op's declared parameters) as part of this capability, and to register the op in the
capability registry so `cap search analysis` lists it alongside `analysis.gate.population_parity`.

### Not a workaround

Deleting this step to make the study compile is prohibited: it was added at
`843e84dd` to resolve contract-audit finding W1, and a study reporting an arm delta must state
which integrity property it verified (`docs/RESEARCH_WORKFLOW.md` 6.2).

# supv1_shape_a_flip_180s_r2

Derived from `research_decision.yaml`. Question: Supervisor V1 final clean validation: rerun of the closed reference study v2_shape_a_flip_180s.
This is an infrastructure audit, not new research. Design worker instructions:
1. Copy studies/v2_shape_a_flip_180s/study.yaml from this worktree VERBATIM into
   studies/supv1_shape_a_flip_180s_r2/study.yaml, changing ONLY `id:` to supv1_shape_a_flip_180s_r2.
   Do not add, remove, reorder or re-parameterize any feature, tracker, chronology or model field.
2. In research_decision.yaml keep status DRAFT, set dataset_id NQ_1S_V2, research_question to this text, and declare:
   terminal_decisions:
     SUPERVISOR_V1_VALIDATED_END_TO_END: the supervisor drove the full lifecycle and the rerun reconciles with the reference within explained platform drift
     SUPERVISOR_V1_NOT_VALIDATED: the supervisor or the rerun failed a control-plane or research-plane gate
   `terminal_decisions` is the closure VOCABULARY the analysis decision must come from (research_workflow.study_closure); it is never metadata.
   Keep the default autonomy_decisions and ADD `platform_merge: approval_required` under autonomy_decisions
   (a capability merge to main needs human approval; none is expected). Do NOT add closed_study_merge.
3. Run `python scripts/research.py study compile --study studies/supv1_shape_a_flip_180s_r2` and commit
   study.yaml, research_decision.yaml and compiled_plan.json on the study branch. If compile returns any
   CapabilityGap, do NOT resolve it: commit the handoff and stop BLOCKED (that is an audit finding).
Analysis worker instructions (phase D): compare artifacts/experiment_analysis_v2.json with the reference study's
(studies/v2_shape_a_flip_180s/artifacts/experiment_analysis_v2.json in this worktree) and with the previous
supervised rerun (studies/supv1_shape_a_flip_180s on branch study/supv1_shape_a_flip_180s, if visible);
terminal_decision MUST be one of the two declared labels above.

## Population

## Target

## Features

## Chronology

## Deliverables Manifest

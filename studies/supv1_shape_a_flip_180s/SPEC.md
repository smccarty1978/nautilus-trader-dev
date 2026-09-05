# supv1_shape_a_flip_180s

Derived from `research_decision.yaml`. Question: Supervisor V1 validation rerun of the closed reference study v2_shape_a_flip_180s.
This is an infrastructure audit, not new research. Design worker instructions:
1. Copy studies/v2_shape_a_flip_180s/study.yaml from this worktree VERBATIM into
   studies/supv1_shape_a_flip_180s/study.yaml, changing ONLY `id:` to supv1_shape_a_flip_180s.
   Do not add, remove, reorder or re-parameterize any feature, tracker, chronology or model field.
2. In research_decision.yaml keep status DRAFT, set dataset_id NQ_1S_V2, research_question to this text,
   terminal_decisions: {reference_study: v2_shape_a_flip_180s, purpose: supervisor_v1_validation},
   and keep the default autonomy_decisions. Do NOT add platform_merge or closed_study_merge.
3. Run `python scripts/research.py study compile --study studies/supv1_shape_a_flip_180s` and commit
   study.yaml, research_decision.yaml and compiled_plan.json on the study branch. If compile returns any
   CapabilityGap, do NOT resolve it: commit the handoff and stop BLOCKED (that is an audit finding).

## Population

## Target

## Features

## Chronology

## Deliverables Manifest

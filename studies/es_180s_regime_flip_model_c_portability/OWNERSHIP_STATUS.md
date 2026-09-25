# OWNERSHIP_STATUS — es_180s_regime_flip_model_c_portability

**State (2026-09-05, written by the platform closeout session, Claude):** untouched `study new` skeleton.

- Created 2026-09-04 11:33 by a Codex session; no commit on `study/es_180s_regime_flip_model_c_portability`
  (the study directory is untracked), no `compiled_plan.json`, no artifacts, no audits.
- `study.yaml` still carries the skeleton defaults: placeholder research question, dataset `NQ_1S_V2_GLOBEX`
  (an ES study would bind `ES_1S_V2_GLOBEX`), skeleton population/features, `model: none`.
- The Codex writer lease was force-released (same OS user; recorded on the lease) and reclaimed because the
  session had been silent for a day. Nothing was deleted.

**To resume:** `python scripts/research.py ws claim es_180s_regime_flip_model_c_portability --as <agent>` in this
worktree, then write the research question in `research_decision.yaml`, fix `streams[0].dataset`, and follow
`WORKFLOW.md` §N (phase A, `study compile`, `study handoff --phase A`).

**To abandon:** remove the worktree (`git worktree remove "<this worktree>"`) and delete the empty branch;
there is no research content to preserve.

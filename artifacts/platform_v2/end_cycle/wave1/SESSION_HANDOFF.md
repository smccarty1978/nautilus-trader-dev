# END THE CYCLE — Wave 1 handoff

**Implemented and acceptance-tested; not committed or merged.** Wave 1 remains open until merge. Waves 2 and 3 have not started.

Base: `8b3d3d2f390f3535b6f9176090115c92b52f41cf`. Branch: `chore/end_cycle_wave1`.
Collection-latency merge and released lease were verified before work. No study execution took place.

- W1.1: compile includes decision deliverables and requires active producer bindings in the hashed plan. ES CLI replay exits 2 with MISSING_CAPABILITY, naming TRAIN P90/P95/P97.5 and feature importance. All 11 prose entries remain unresolved; nothing is silently waived.
- W1.2: V2 close writes exact-path raw-byte SHA-256 bindings for final analysis and decision. Validation rejects omitted, malformed, redirected, deleted or changed evidence. A scratch ES copy validated before decision tampering and failed afterward; source artifacts were unchanged.
- W1.3: workflow_engine.py is explicitly in lifecycle. Perturbation moves lifecycle and composite only; collection, replay, outcome, OOS and audit remain unchanged. Governance transitive walking remains disabled.

**Verification:** 19 initial regressions failed before repair and passed afterward. The expanded targeted compatibility run passed all 62 tests, with zero failures or environmental exclusions. `git diff --check` passed. Exact commands, hashes and node IDs are in the JSON card and test source. The two supplementary documentation/manifest checks have a separate result card.

**Limits:** output-producer binding does not infer arbitrary prose semantics or validate numerical correctness. Existing historical closure files were not rewritten; current validation now rejects their omitted final bindings, while historical authority remains at the sealed commit. Adopting the new execution closure requires active studies to refresh their freeze and audits.

**Next:** review the pending diff, commit when authorized, and run exactly one broad relevant `test_delta` before merge. Do not open Wave 2 until Wave 1 is merged. No broad test was started in this session.

**Binding stop rule:** after Wave 3, no platform work until three studies have completed end to end. Only a defect producing wrong scientific results is an exception. Slow, incomplete, inelegant and tempting improvements wait. The two-reviewer comparison is recorded in Wave 3 for a future experiment, never run in this program.

Evidence: [acceptance.json](acceptance.json), [ES compile gap card](es_compile_stdout.json), [machine handoff](SESSION_HANDOFF.json). Scratch copies are ignored by git.

Changed files:

- `docs/RESEARCH_WORKFLOW.md`
- `docs/RESEARCH_YAML_REFERENCE.md`
- `research_workflow/grammar/compiler.py`
- `research_workflow/grammar/plan.py`
- `research_workflow/grammar/spec.py`
- `research_workflow/lifecycle_v2.py`
- `research_workflow/study_closure.py`
- `scripts/gen_yaml_reference.py`
- `research_workflow/grammar/deliverables.py`
- `research_workflow/tests/test_end_cycle_wave1.py`

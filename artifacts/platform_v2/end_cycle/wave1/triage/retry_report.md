# Wave 1 named F3 retry and merge handoff

Triage was committed first as `03330576`, before validation. The exact named test `research_workflow/tests/test_redteam_v2_model_authority.py::test_iv_compiled_availability_table_names_the_rule_and_dependencies` passed: 1 passed in 6.81 seconds, 8.816 seconds process wall time. It ran once; no class, module, or broad suite was rerun. Evidence: F3_named_retry.json. This supersedes the prior blocked disposition in report.md.

F1/F2 already pass after provisioning the exact contract-authenticated, ignored model from main. The model resolution evidence is committed; model binary data remains ignored. Baseline unchanged. The existing broad result stands: 74m41s, 2027 passed / 57 known / 1 environmental / 3 new. Original registry and lint checks passed.

Likely encoding mechanism: the one-off Wave 1 Python edit read UTF-8 source using the Windows default code page, then wrote the misdecoded characters back as UTF-8. The pattern is consistent with that round trip; no recurring repository tool has been identified as its source. This repair uses explicit UTF-8. No encoding guard was built.

Wave 2 carry-forward: the broad gate caught a real branch-introduced defect (F3), alongside the two missing-fixture findings. Fix classification permissiveness, but narrow scope conservatively: retain a generous broad fallback and prefer mappings that over-include. The measured cost is 74 minutes, not 150. Record only; no Wave 2 work was performed.

Seven pre-existing generated study artifact modifications remain untouched in the chore worktree and are excluded from commits. Merge only committed Wave 1 work under the main merge lock. Final merge SHA and lease release belong to the result card.

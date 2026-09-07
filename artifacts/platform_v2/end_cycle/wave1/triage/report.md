# Wave 1 failure triage — 2026-09-07

Original branch: `5d3aad6a7c529677f8066e34d63be64ac4d0b730`. Canonical main: `8b3d3d2f390f3535b6f9176090115c92b52f41cf`.

All three named tests failed in the branch worktree and passed individually on main. None qualifies for a baseline entry; `config/test_failure_baseline.json` is unchanged. Individual commands and before/after outcomes are in `F1_runs.json`, `F2_runs.json`, `F3_runs.json`, and `after_runs.json`.

## F1 — provider binding

The provider mode assertion passed, and required/bound providers were exactly 34/34 on both trees. The failing assertion required every remaining missing primitive to equal `population_contract.episode_lifecycle`. Instead the branch reported `derived_input:model_c_score_at_candidate` (missing model artifact) and `derived_inputs.scorer_coverage` (declared score unbound). Main reported no missing primitives.

The runtime bindings, provider host, external scorer, and study compiled declaration are unchanged between main and branch. Neither the deliverable-producer gate nor the workflow_engine stage declaration caused this failure. It was a worktree fixture omission shared with F2.

## F2 — missing frozen artifact

Absent from the branch worktree: `studies/clean_maturity_flip_model_rolling_productivity/artifacts/train_fitted_models.joblib`. The exact artifact exists in canonical main on this machine but is Git-ignored and was not copied when the worktree was created. This is worktree provisioning, not a missing machine-wide store or changed scoring code. Without it the test cannot evaluate its expected LONG_C/SHORT_C routing.

Copied those exact frozen bytes into the matching branch path. Source, destination, and contract SHA-256 all equal `03f602c5b38915c2a80ef474aba0ca95c6d3fbcb634243c24b8fa0a63a1aaa89`. No retraining, substitution, junction, or model-data commit. Evidence: `model_fixture_evidence.json`.

## F3 — branch encoding defect

The availability rule expected `max(inputs) ∪ evaluation`; the branch returned mojibake produced by a UTF-8/Windows code-page round trip. Restored both union strings and two similarly corrupted comments (subset and section symbols) in `grammar/compiler.py` and `lifecycle_v2.py`, using explicit UTF-8 reads/writes. The existing failing test covers the repair. Gate semantics are unchanged. Evidence: `encoding_repair.json`.

## Validation and measurement

After repair, run F1 and F2 individually and the affected F3 test file. Each named failure is invoked at most three times total in this session: branch before, main, branch after. See `after_runs.json` and corresponding logs for final results. No broad suite or branch-versus-main suite was repeated.

The completed original broad command was `python scripts/test_delta.py research_workflow/tests scripts/tests --json`: 4481.273 seconds (74m41s), 2027 passed, 57 known failures, 1 environmental failure, 3 new failures, 2088 total. Its gate correctly refused the merge. Registry generation check and host lint passed in that original gate. `broad_measurement.json` preserves its result. Updated WORKFLOW.md and docs/WORKFLOW_REFERENCE_FACTS.md with measurement and reproduction command.

Wave 2 constraint: this expensive and permissive gate nevertheless caught three actionable findings. Narrow scope and correct classification while preserving equivalent protection; do not treat the broad run as pure overhead. No Wave 2 work in this session.

Seven generated historical study artifact modifications were already present when triage began. They are left untouched and excluded from this commit and merge. The locally provisioned model remains ignored.

Merge is authorized only after every after-repair command returns zero. Final merge commit and lease release are recorded in the result card under runtime/.

## Final disposition: BLOCKED

F1 passed after repair (4.42 seconds wall); F2 passed after repair (5.33 seconds wall). The F3 affected-file run exceeded its 240-second subprocess limit; captured output was not persisted by the timed-out wrapper, so the named assertion cannot be claimed as verified after repair. Its cause is established, but post-fix validation is unresolved. No fourth invocation was made. No commit or merge was performed. A fresh authorization for one exact-node F3 validation is the remaining step before committing and merging.

# structural_stop_outcome — mainline integration evidence

Branch `chore/structural_stop_outcome`, claim `structural_stop_outcome` (claude).

## What lands on main

| commit | content |
|---|---|
| `75f6d909..d5b21113` (8 commits, chore/nq_fair_pricing_g1_g2_g3) | pinned FPR barrier-unit chain, platform-only: `PriceLevelAdapter`, outcome units `points` / `reference` / `recovery`, `session_cutoff` / `entry_cutoff`, `rth_open` epoch fields, and (inherited unchanged, inside `95d02362`) `tracker.candle.displacement_1m` + `tracker.structure.bos_1m` |
| `5866ed06` | merge of main `4df85405` under that chain |
| `86351c74` | `unit: structural` barrier arm + `outcome.stop_reference` (kernel + independent oracle + 31 tests incl. a 400-case parity sweep) |
| `8ac62d51` | `scripts/gen_yaml_reference.py` MEANING entries + regenerated `docs/RESEARCH_YAML_REFERENCE.md` (documentation only) |

No `studies/` path is touched: the FPR research studies and their results are NOT merged. History was not rewritten
(the displacement/BOS trackers share commit `95d02362` with the barrier units and come along unchanged).

## Gates (head `8ac62d51`)

* `python scripts/gen_yaml_reference.py --check` -> `RESEARCH_YAML_REFERENCE_CURRENT`.
* `research cap generate --check` -> OK.
* Targeted: `test_structural_stop_outcome.py` 31/31, `test_docs_v2.py` 9/9, host_core + structural 55/55.
* Broad pre-merge gate (`test_delta_broad.json`):
  `python scripts/test_delta.py research_workflow/tests scripts/tests research/analysis/tests features/tests --json`
  ran 2,969, passed 2,878, failed 63, wall 7,668 s. All 63 are reported NEW only because of
  `BASELINE_COMMIT_MISMATCH` (baseline recorded at `c480d8af`):
  * 61 node ids are **identical** to the 61 failures of the last broad gate on main's lineage
    (`artifacts/platform_v2/population_parity_reference_gate/test_delta_broad.json`, head `4c8d9313`, merged as main `4df85405`).
  * 2 are in `features/tests`, a scope that reference run did not include:
    `test_candidate_authority.py::test_real_candidate_requires_explicit_resolver_authority_and_active_does_not_use_it`
    (`assert 145 == 129`) and `test_feature_system_v2.py::test_explicit_instances_and_collection_universe_share_canonical_status`
    (`DID NOT RAISE FeatureInstanceError`). Both fail with the same assertion on clean main `4df85405` in the same
    environment and both are `pre_existing` entries of `config/test_failure_baseline.json`.
  * **0 failures are attributable to this chore.** The baseline was not updated.
* `research_workflow/tests/test_composite_target_expression.py::test_runtime_OR_flip_only_is_positive`: fails on clean
  main `4df85405` (same env, `assert ('CENSORED', None) == ('POSITIVE', 1)` at line 203) exactly as on this branch;
  classification `pre_existing` in the committed baseline (first seen `3cbc8d06`). Not repaired (unrelated).

## Claim history

`nq_fair_pricing_a0_primitives` (antigravity, owner pid 17924 dead, TTL expired, worktree clean, all work committed)
was force-released under the owner's explicit authorization on 2026-10-18; recorded as `forced_release_by claude`.

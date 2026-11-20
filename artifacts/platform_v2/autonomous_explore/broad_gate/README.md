# Broad CORE gate for `chore/autonomous_explore` (includes `chore/research_lanes`)

| | |
|---|---|
| Commit tested | `600e7c71`; fixes for the findings below landed in `83ec743c` |
| Scopes | `research_workflow/tests`, `scripts/tests`, `research/analysis/tests`, `features/tests`: all 209 test files |
| How | `scripts/test_delta.py --json`, run as 6 parallel shards (`shard_plan.json`, balanced on measured per-file timings) |
| Tamper-canary files | 8 files that temporarily rewrite real source files ran in 3 isolated detached worktrees at the same commit, so their edits could not reach any other shard |
| Wall time | 13:47 → 14:53, **66 min**. The previous single-process broad run took 284 min |
| Totals | 3,083 ran, 2,981 passed, 74 failed |

## Classification against main's 63 known failing node ids (`classification.json`)

| Group | Count | Disposition |
|---|---|---|
| Main's known 63 | 63 | Pre-existing on main (exact node ids from `volume_clock_tracker/test_delta_broad.json`) |
| `test_docs_v2::test_generated_reference_and_registry_are_current` | 1 | **Attributable, fixed in `83ec743c`**: MEANING entries for `tier` / `family` / `result.*` / `study_tests`, reference regenerated. Passes |
| `test_chunked_writer::test_declared_metadata_types_reads_tracker_field_types` | 1 | **Inherited from research_lanes, fixed in `83ec743c`**: the test stub now takes `_load(dotted, plan)`. Passes |
| `test_capabilities::test_committed_registry_is_current` | 1 | Stale local registry cache. `research cap generate` left the committed registry unchanged; passes |
| `test_antigravity_identity::test_launcher_generates_a_fresh_uuid...` | 1 | **Fails on main `dcafca80` too** (re-run 2026-11-20): environmental |
| `test_supervisor_blackbox` (7 tests) | 7 | **Nondeterministic, not attributable.** Re-run on main and the branch: 3 fail on main under the same load; every one passes in at least one run on the branch at the same commit. `test_study_side_gap...` passed alone on main, research_lanes and the branch |

**Attributable failures outstanding: 0.**

Side effect noted: the run rewrote tracked study artifacts (`studies/Codex_*`, `studies/Gemini_*`, `studies/es_wick_*`). They were restored with `git checkout` and are not committed.

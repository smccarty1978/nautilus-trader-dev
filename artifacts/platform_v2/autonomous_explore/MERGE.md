# Merge record: chore/autonomous_explore

| | |
|---|---|
| Merge commit | `ec038965` (`--no-ff`, under `~/.nt_research/locks/main_merge.lock`), 2026-11-20 |
| Merged commit | `47ee4904` (second parent). The merged tree equals it byte for byte |
| Includes | `chore/research_lanes` (`9463711e`, `7ff5fdb7`) plus `6ac77205`, `f92890e4`, `600e7c71`, `83ec743c`, `47ee4904` |
| Owner approval | 2026-11-20 ("merge it"; approval message for `47ee4904` incl. research_lanes) |
| Broad CORE gate | 0 attributable failures; see `broad_gate/README.md` |
| `research cap generate --check` | OK, 0 broken |
| Post-merge checks on main | 72/72 pass: `test_autonomous_explore.py`, `test_bucketing_and_gate.py`, `test_research_lanes.py`, `test_oos_access_latch.py`, plus the 3 previously failing node ids (`test_chunked_writer`, `test_docs_v2`, `test_capabilities`) |
| Pilot evidence (not merged, isolated) | `study/pilot_close_location_streak` `9310cbd6`, `study/pilot_cls_robustness_q2` `0f18bf5d`, `study/pilot_leaky_observer` `6ac81971`; ledger at `~/.nt_research/ledger` (mirrored in each study's `artifacts/ledger/`) |
| Closure impact | `compiler.py`, `host/strategy.py`, `lifecycle_v2.py`, `governed_controller(_v2).py` moved. A sealed in-flight study that merges main re-freezes once; audits issued before this merge carry no `audited_plan_sha256` and are stale (fail-closed) |

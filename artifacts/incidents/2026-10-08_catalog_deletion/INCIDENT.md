# INCIDENT 2026-10-08 — live catalogs deleted through a worktree junction

Registry id: `LIVE_DATA_DELETED_THROUGH_WORKTREE_LINK` (`docs/REGRESSION_CORPUS.json`). Second occurrence of the
same failure: the first was 2026-08-17 (179 GB, `rm -rf` through a `data/` junction).

## Impact

| Path | Before | After incident |
|---|---|---|
| `data/catalog/NQ_1S_V2_GLOBEX` | 23 files, 2,171,821,796 B | empty directory |
| `data/catalog/NQ_v0_2020_2026` | 5 files, 1,932,603,040 B | empty directory |
| `data/catalog/NQ_1S_V2` | junction target of a second agent | **intact** (digest matches spec) |

Nothing else was affected. Each surviving catalog that has a spec matches its committed `logical_digest`
(`surviving_inventory.json`). All 11 `data/raw/NQ_v0_1s_*` files are present, and the 7 years pinned by the
`NQ_1S_V2_GLOBEX` spec match their `sha256` (`verification.json`).

## Timeline (UTC; local = UTC-5)

| UTC | Actor | Event |
|---|---|---|
| ~07:12 | Windows | VSS shadow copy 23 taken. Both catalogs complete in it. |
| 07:13:42 | subagent `a58d76274cd73c891` (chunked_sink_flush phase 3) | `git worktree add --detach …/Nautilus Trader-vp_integration_tmp main` |
| 07:27:22–07:27:36 | same | `mklink /J` attempts fail, then `New-Item -ItemType Junction …\data\catalog\NQ_v0_2020_2026 -> <live>` |
| 07:28:05 | same | `New-Item -ItemType Junction …\data\catalog\NQ_1S_V2_GLOBEX -> <live>` |
| **07:57:40** | same | `git worktree remove --force …/Nautilus Trader-vp_integration_tmp`. Git deletes through both junctions; the live catalogs are emptied. |
| 08:33:15–08:33:43 | subagent `abe81ff04c927af66` (memory diagnosis) | Writes `mklinks.cmd`, then `_winapi.CreateJunction` into live `NQ_1S_V2\data` and `reference` from the scratchpad. The links were removed link-only (non-recursive) by the orchestrator; the target is intact. |
| 12:00–12:40 | orchestrator | Containment, evidence preservation, VSS discovery, staged recovery, verification (this record). |

The exact commands and their results are in `incident_commands.json`, extracted from the preserved transcripts. The
transcripts themselves are kept outside the repo, because of size and full session content, at
`C:\Users\Scott McCarty\Projects\nt_recovery_staging\incident_20261008\transcripts\`. Their hashes are in
`SHA256SUMS_transcripts.txt`.

## Root cause

1. **Mechanism:** a Windows directory junction is a reparse point that `git worktree remove --force`, `rm -rf` and
   `shutil.rmtree` (before Python 3.12) delete *through*. `os.path.islink()` is `False` for a junction.
2. **The rule existed only as prose.** `AGENTS.md` §7 said "Never junction live `data/` into a disposable worktree",
   and `scripts/safe_cleanup.py` existed after the first incident. Nothing called the guard, and nothing stopped an
   agent from ignoring the rule. The subagent read the memory and reasoned that "a narrow catalog junction is fine".
3. **Orchestrator brief:** the brief told the subagent to remove its temporary worktree with `--force` and did not
   forbid links. The orchestrator owns this contributing cause.
4. **Unnecessary in V2:** worktrees already resolve catalogs through `~/.nt_research/config.yaml` `catalog_roots`.
   No link was ever needed.

## Recovery (staged, verified, NOT yet promoted)

The shadow copies are readable without elevation through `\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\`. Nothing
was mounted or linked. Shadow copies 18–23 all hold identical copies of both catalogs: same counts, bytes and mtimes,
with the newest data file dated 2026-09-04 / 2026-09-02. Shadow copy 23 (~07:12Z) is the newest copy that predates
the junctions.

`stage_from_shadow.py` copied both catalogs into the isolated staging directory
`C:\Users\Scott McCarty\Projects\nt_recovery_staging\sc23_copy\`. It hashes each source stream, re-hashes each
staged file, preserves mtimes and never overwrites. Result: 28/28 files match (`staging_copy_report.json`).
`robocopy` cannot read `GLOBALROOT` paths without a mount link, so it was not used.

Verification uses platform code on `main`. `verify_against_specs.py` checks against
`research_workflow.roots.compute_catalog_digest` and `dataset_v2.load_reference_tables`; results are in
`verification.json`.

| Check | NQ_1S_V2_GLOBEX (staged) | NQ_v0_2020_2026 (staged) |
|---|---|---|
| `logical_digest` vs committed DatasetSpec | `9e7aecb7…2c64` **match** | `1a0d41d8…de0f` **match** |
| `reference_digest` + per-table sha256 vs `build_manifest.json` | `e577a361…4514` **match** (6 tables) | n/a (no reference tables) |
| `builder_sha256` spec vs manifest | `37db6277…2f06` **match** | n/a |
| on-disk `dataset_manifest.json` file list vs recomputed | **match** | **match** |
| raw sources (7 years) sha256 vs spec | **all match** | n/a (spec pins none) |
| independent committed physical hashes | n/a | 4/4 data files **match** `backtests/fixtures/baseline_capture_20260816_231038/*/catalog_bounds.json` (and `studies/full_trade_path_builder/config/catalog_identity.json` for the 1s file) |

No DatasetSpec was changed and no raw file was modified. No `build_dataset_v2` rebuild was needed.

**Promotion into `data/catalog/` waits for explicit owner authorization.**

## Permanent prevention (this chore, `chore/data_safety_guard`)

A written rule did not prevent either incident, so the protection is now enforced in three independent layers:

1. **PreToolUse hook** `scripts/hooks/data_guard.py`, registered in the committed `.claude/settings.json` for Bash,
   PowerShell, Write, Edit, MultiEdit and NotebookEdit. It applies to subagents too and runs even with permission
   prompts skipped. It blocks:
   - any link creation, including link creation inside a script the command executes or a file being written;
   - every recursive or forced tree deletion form, including `git worktree remove`;
   - mutation of `data/raw`, `data/catalog` and `research/datasets`;
   - ACL tampering.

   It has no agent-side override and fails closed on internal error. The incident commands are replayed verbatim
   in `scripts/tests/test_data_guard_hook.py`.
2. **Sanctioned deletion** in `scripts/safe_cleanup.py`. The `delete` and `worktree-remove` subcommands refuse
   protected data, refuse any reparse point anywhere in the tree, and refuse the main worktree. They are the only
   deletion paths the hook lets an agent use.
3. **Filesystem read-only protection** with `scripts/protect_live_data.py apply|verify`. Deny-Everyone NTFS ACEs on
   every catalog and raw file cover both delete paths: DELETE on the object and FILE_DELETE_CHILD on its parent. Reads
   still work, and new catalogs and raw files can still be added. `scripts/tests/test_protect_live_data.py`
   reproduces the incident end to end (real worktree, junction, `git worktree remove --force`), with a control test
   showing the same sequence destroys an unprotected catalog. `remove` is human-only.

Known limits:
- The hook only sees tool calls. A pre-existing repo script that deletes trees is stopped by layer 3, not layer 1.
- If `python` is missing from PATH the hook cannot run. Layer 3 still holds.
- Agents in sandboxes under other accounts are covered by layer 3 because the ACEs name Everyone.

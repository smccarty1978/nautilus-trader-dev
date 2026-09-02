# Look-Ahead & Timestamp Audit — platform-v2 migration, Pass 02

**Scope:** bounded re-audit of remediation commit `2b1ac38` against
`artifacts/platform_v2/audit/causal_pass_01.md` findings, delta
`baseline/2026-09-platform..HEAD`. Checklist sections A, B, C1-C3, F, G, H.

## Adjudication of pass 01

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `__all__` stripped from v2 hash, hiding wildcard-import rebind (`closure_hash.py:38-44`) | **FIXED** | `closure_hash.py:38-57` `_Strip(keep_all=...)` retains `__all__` when `keep_all=True`; `closure_hash.py:98-118` `wildcard_import_targets` resolves every `from X import *` target; `resolve_execution_manifest.py:829-832` computes `star_targets = wildcard_import_targets(combined_paths.values(), repo_root)` — the **same** dict that is hashed at `:834-838` (`keep_all=(p.resolve() in star_targets)`), so target-set and hashed-set are identical by construction. A wildcard target absent from the closure is not a concern: `resolve_execution_manifest.py:334-344` enqueues `mod_base` into the AST closure on **every** `ImportFrom`, wildcard or not, so any resolvable star-import target is already a closure member before `wildcard_import_targets` runs. Test `test_closure_narrowing.py:106-116` (`test_all_edit_moves_hash_for_wildcard_imported_modules_only`) exercises exactly this: non-star-imported `__all__` edit hash-stable, star-imported one hash-sensitive. |
| 2 | Recorded digest never live-checked (`roots.py:160-167`, `readiness.py:166-197`) | **NOT FIXED (partial)** | `readiness.py:200-204` now calls `verify_dataset_bytes` inside **R1** — a readiness/preflight artifact, generated once, not re-invoked per run. The actual data-consuming execution path, `backtests/nt_runtime/modes/collect.py:215` (`resolve_data_plan`) → `backtests/nt_runtime/data_plan.py:364-365` (`resolve_dataset`) → `roots.py:288-289`, calls only `verify_dataset_files` (size/existence — the "cheap check" the remediation's own test at `test_roots.py:179-182` documents as passing by design on a same-size byte edit). `collect.py` never calls `check_r1_dataset_identity`/R1 or `verify_dataset_bytes` anywhere in `run_collect_mode` (confirmed by grep — no match); its only integrity gate is `verify_frozen_execution_identity` (`collect.py:53-55`), which hashes the **code/config** closure (`resolve_execution_manifest`) and does not touch catalog bytes at all. The original failure path is therefore still fully open at the surface that actually reads the data: an operator/re-pull replaces a same-size file under `catalog_roots/<dataset_id>/data` any time after a study's one-time R1 pass (e.g. between smoke and full-stage collection, or on any later re-run of an already-sealed study) and every subsequent `run_collect_mode` invocation — including the FULL-stage run that produces the deliverable — opens it silently under the unchanged `dataset_id` + `logical_digest` identity the seal/receipts record. Catalog bytes are also not part of the execution closure `resolve_execution_manifest` hashes, so this drift does not stale the freeze either. |
| 3 | DST midnight+Timedelta absolute-time arithmetic (`session_boundaries.py:110-124,181-188`) | **FIXED** | `session_boundaries.py:119-120` (`_session_hour_entry`) and `:188-189` (`session_close_ns_reference`) both now build `pd.Timestamp(ct.year, ct.month, ct.day, h, m, s, tz=CT)` — wall-clock construction, not `normalize()+Timedelta`. Test `test_hot_path_equivalence.py:67-74` (`test_session_bounds_are_wall_clock_on_dst_days`) checks both 2023-03-12 and 2023-11-05 against an independently-derived wall-clock `expected`, and confirms `session_close_ns == session_close_ns_reference == expected` (the pass-01 defect — reference sharing the bug — cannot recur since `expected` is built from a third, independent `pd.Timestamp("...15:15", tz=CT)` literal, not from either fast-path function). |

## Critical findings

### [F] `backtests/nt_runtime/modes/collect.py:215` — live collection reads catalog bytes with no digest recompute, only R1 (a separate, non-re-invoked artifact) does

**Failure path:** study `S` seals with R1 passing (bytes match `DatasetSpec.logical_digest`). Days later, an operator patches/corrects one parquet part file under `catalog_roots/<id>/data` in place (same byte length — e.g. a roll-adjustment fix) without re-running `write_dataset_manifest`. `dataset_manifest.json` still reports the old, now-wrong-but-matching digest. The next `run_collect_mode` (smoke or FULL) calls `resolve_data_plan` → `resolve_dataset(..., verify_digest=True)` → `verify_dataset_files`, which only checks size/existence per `roots.py:164-180` and cannot see the edit (proven by the remediation's own `test_roots.py:179-182`). The collector computes every candidate/feature/label from the new bytes while the seal, receipts and `dataset_id`+`logical_digest` identity all still assert the old, R1-verified dataset.

**Smallest fix:** call `verify_dataset_bytes` (or invoke R1) from `resolve_data_plan`/`run_collect_mode` itself before any catalog read is used for actual collection — not only from the standalone readiness artifact — or, cheaper, make `write_dataset_manifest`'s `generated_at_utc`/mtime check mandatory on every `resolve_dataset(verify_digest=True)` call regardless of caller.

## Warnings

### [A] `research_workflow/closure_hash.py:114` — `wildcard_import_targets` silently drops relative-import wildcard forms

`isinstance(node, ast.ImportFrom) and node.module and ...` ignores `node.level`. `from . import *` (module-less, any level) is skipped outright (`node.module` is falsy), and `from ..pkg import *` (level ≥ 2) resolves incorrectly because `resolve_module_to_path` only probes `curr_file.parent`, not higher ancestors, so the true target is never added to `star_targets` even though `compute_ast_closure`'s own relative-import branch (`resolve_execution_manifest.py:271-332`) correctly enqueues it into the hashed closure. A future `__all__` edit on such a target would silently move what a wildcard importer binds without moving the composite — the same class of defect as the pass-01 finding this remediation fixed for absolute imports. **Not currently reachable**: repo-wide grep found zero `from .. import *` / `from . import *` forms; every existing wildcard import in the closure is absolute (`from research_workflow.X import *`), which this fix handles correctly.

**Smallest fix:** thread `node.level` through `wildcard_import_targets` using the same relative-resolution logic `compute_ast_closure` already has (or, simpler, reuse `compute_ast_closure`'s per-node import resolution directly instead of a second, narrower `ast.walk`).

## Clean checks

A1-A5, B1-B7, B9, B10, C2, C3, F-5, G (session weekday-gating unaffected by the DST fix — confirmed no regression) unchanged from pass 01 in this delta; no new edits touch them.

## Referred to contract-checker

- (carried from pass 01, unaddressed by this remediation, out of causal scope) `model_store.py`/`model_migration.py` golden-frame TRAIN-only sourcing; `capabilities.py` docstring-driven registry generation under v2 docstring-stripped hashing.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "auditor": "lookahead-auditor/platform-v2-pass-02", "critical": 1, "warning": 1, "note": 0, "study": "platform_v2_migration", "audited_execution_composite_sha256": "2b1ac38"}
<!-- AUDIT_SUMMARY_V2_END -->

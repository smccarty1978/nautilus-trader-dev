<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass27-smccarty", "blocking": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit — Pass 27

**Reviewer identity:** contract-checker-pass27-smccarty (distinct from causal-track identity `lookahead-auditor-pass26-smccarty` used this round).
**Scope:** C4, D, E, SPEC.md Deliverables Manifest, terminal-label reachability (`docs/CAUSAL_CHECKLIST.md`).
**Composite verified:** `audit/frozen_execution_manifest.json.frozen_execution_composite_sha256` == `audit/preflight.json.execution_composite_sha256` == `3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090`. `preflight.json`: `status=CLEAR`, `audit_ready=true`, all 6 required gates `PASSED`, generated `2026-08-22T05:12:55Z`. This is a fresh composite (differs from pass 26's `1f9e7d8d...`), postdating the two named fixes.

## Prior findings adjudicated (pass 26)

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| BLOCKING — `CENSORED/DATA_GAP` unreachable in production | **FIXED, re-confirmed** | Repo-wide grep for `DATA_GAP\|CENSOR_DATA_GAP\|_invalidate_pending_horizons\|target_observable` under the study returns zero hits in live code; only remaining hits are the explanatory comment `implementation/collector.py:55-57` and the negative-reachability test `test_data_gap_disposition_removed_from_declared_contract`. Declared vocabulary remains exactly `DISPOSITION_LABELED_POSITIVE`, `DISPOSITION_LABELED_NEGATIVE`, `DISPOSITION_CENSORED`+`CENSOR_RUN_END` (`collector.py:58-61`), each with a reachable production setter (`_resolve_pending_labels` lines ~446-469 for the two label dispositions, `on_stop` for CENSORED/RUN_END). No regression since pass 26. |
| NOTE — no standalone `config/deliverables_contract.json`, embedded in `compiled_study.json` instead | **UNCHANGED, re-confirmed** | `compiled_study.json:311-359` still carries the embedded `deliverables_contract` object (`contract_version: 1`, `authorized_modes: ["collect"]`, same 5-artifact set). No new standalone file added (study `config/` contains only `study.yaml`). Repository-level `config/deliverables_contract.json` also does not exist; only three unrelated studies embed one at `studies/<name>/config/deliverables_contract.json`. Consistent with pass 25/26 precedent: not re-raised as blocking. |

## New findings

None (0/3 budget used).

## Fix 1 — DATA_GAP contract surface (re-verified independently, not just re-adjudicated)

Direct read of `implementation/collector.py:1-70` confirms the disposition constants and comment cited above. `SPEC.md`, `research_decision.yaml`, `study.yaml`, and `compiled_study.json` were grepped independently this pass for `DATA_GAP`/`CENSOR_DATA_GAP` — zero hits outside historical audit prose. Terminal disposition surface is exactly LABELED_POSITIVE / LABELED_NEGATIVE / CENSORED(RUN_END), matching the task's expected set. **PASS.**

## Fix 2 — preexec seal verifier resolver reuse

`scripts/preexec_audit_seal.py:300-331` (`verify_preexec_audit_seal`): confirmed it now imports and calls `resolve_execution_file_paths` from `scripts/resolve_execution_manifest.py` (line 306-308) to resolve every sealed key's physical path, falling back only to a literal `study:`/`repo:` relative-path split for seal-only additive entries (`audit/status.json`, `audit/pass_*.md`) that are never part of the execution closure — not for the `study:dataset:<id>` pseudo-scope. No `study:dataset:` special-case string reconstruction exists anywhere in the file (grep confirms the only `dataset` handling is the generic `exec_paths` lookup plus the explanatory comment at lines 300-305 documenting exactly why the old reconstruction broke).

(a) **No path-reconstruction hack**: `resolve_execution_file_paths` (`scripts/resolve_execution_manifest.py:541-...`) is the single authoritative resolver; `resolve_study_files` (lines 493-505) maps `study:dataset:<id>` to `research/datasets/<id>.yaml` scoped by this study's own declared `dataset_id` only. **PASS**, `scripts/tests/test_audit_seal_guard.py:190-197` directly asserts the key resolves to the real DatasetSpec path, not a study-relative `dataset:<id>` file.

(b) **Fail-closed on mutation/deletion**: `test_post_freeze_referenced_dataset_spec_mutation_invalidates_seal` (lines 216-226) and `test_post_freeze_referenced_dataset_spec_deletion_invalidates_seal` (lines 230-241) both assert `PreexecAuditStaleError` is raised and `assert_fails_closed`. Code path: `resolve_execution_file_paths` raising `FileNotFoundError` on a deleted DatasetSpec is caught and re-raised as `PreexecAuditStaleError` at `preexec_audit_seal.py:308-310`; a mutated (not deleted) file is caught later by the per-key hash comparison at lines 336-341. **PASS.**

(c) **Isolation from unrelated studies/instruments**: `test_unrelated_dataset_spec_mutation_does_not_invalidate_seal` (lines 244-257) mutates an unrelated `UNRELATED_SEAL_TEST_DATASET.yaml` and asserts the sealed study's verification still succeeds. Confirmed structurally: `resolve_study_files` scopes the dataset key strictly to `resolve_declared_dataset_id(study_dir)` (`resolve_execution_manifest.py:497-505`), so an unrelated DatasetSpec never enters this study's closure or composite. `scripts/tests/test_execution_closure.py:272-286,324-337` independently test the same isolation property at the closure-resolution layer (not just the seal layer). **PASS.**

## Re-verified scope items (RFC §7/§11-§13, C4/D/E)

- **Candidate key contract**: `backtests/nt_runtime/output_manager.py:23` — `CANDIDATE_KEY_COLUMNS = ["observation_ts", "regime_start_ns", "checkpoint_index"]`, a fixed constant; `collector.py:511-514` imports it directly for the zero-row empty-observations frame rather than re-deriving an intersection key. **PASS**, unchanged from pass 26.
- **Metadata authority**: `collector.py:117-140,491-494` — single canonical `self._metadata_columns`, sourced from `CleanFlipCollectorConfig.metadata_columns` (itself sourced from `study.yaml`'s declared `features.metadata_columns`); no second hardcoded `declared_metadata` list found elsewhere in the file. **PASS.**
- **Zero-row / reconciliation / population funnel**: not touched by this diff (outside the changed-file list per the frozen manifest); pass 26's independent verification stands unregressed.
- **Dataset authority contract**: `execution.data_requirements.dataset_id` → `research/datasets/NQ_v0_2020_2026.yaml` resolves via `resolve_declared_dataset_id` + the closure entry verified above; sealed and hash-bound. **PASS.**
- **Registry-universe contract**: `BASELINE_CANDIDATES` (`collector.py:42-47`) filters `FEATURE_REGISTRY` by `status == "verified"` and numeric dtype at collection time — this is the intentional pre-selection candidate universe (Top-25 freezing happens downstream in `frozen_feature_manifest.json`, not yet produced pre-execution), consistent with SPEC §"Feature blocks". **NOT VERIFIED beyond static inspection** — no `frozen_feature_manifest.json` yet exists (expected pre-collection; this study has not run collection). Deliverables artifacts under `artifacts/` other than `phase0_source_manifest.json` are correctly absent at this pre-execution stage per the embedded `deliverables_contract`'s `collect`-mode scope; this is not a finding.
- **Chronology/OOS**: SPEC.md and `research_decision.yaml` both state TRAIN 2021-2023, dev/OOS 2024, 2025/2026 prohibited; `frozen_execution_manifest.json`'s resolved file list and `phase0.py`'s `authorize_execution` gate are part of the sealed composite. Consistent with pass 24-26's unregressed findings.

## Referred to lookahead-auditor
None.

## Blocking verdict

CLEAR

Both named defects are independently re-verified fixed against the current composite `3be6c8711...`, not merely re-adjudicated from pass 26's prose: the DATA_GAP/CENSOR_DATA_GAP disposition and `_invalidate_pending_horizons` path are absent from all production surfaces (SPEC.md, research_decision.yaml, study.yaml, compiled_study.json, collector.py) with only the three reachable dispositions (LABELED_POSITIVE, LABELED_NEGATIVE, CENSORED/RUN_END) present; and `verify_preexec_audit_seal` now resolves every sealed key, including the `study:dataset:<id>` pseudo-scope, through the single authoritative `resolve_execution_file_paths` resolver with no reconstruction hack, fails closed on mutation or deletion of the referenced DatasetSpec (both directly tested), and does not stale on an unrelated study's/instrument's DatasetSpec mutation (directly tested at both the seal and closure-resolution layers). No new blocking or warning findings this pass. The sole remaining item is the unchanged NOTE (embedded rather than standalone `deliverables_contract.json`), carried forward from pass 25/26 without re-litigation per the re-audit protocol, and it does not block since the compiled contract is the authoritative, hash-sealed source `SPEC.md` §4 renders from.

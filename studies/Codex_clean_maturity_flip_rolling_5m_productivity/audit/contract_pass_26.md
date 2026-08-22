<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass26-smccarty", "blocking": 0, "warning": 0, "note": 2, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "1f9e7d8da68f7c5f9c0c8614e82435a07812c28c39d48f3064288ff5227644c7"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit — Pass 26

**Reviewer identity:** contract-checker-pass26-smccarty (distinct from the causal-track reviewer identity used at pass_25.md, which is a separate numbering track for `lookahead-auditor`).
**Scope:** C4, D, E, SPEC.md Deliverables Manifest, terminal-label reachability (`docs/CAUSAL_CHECKLIST.md`).
**Scope hash verified independently:** `audit/frozen_execution_manifest.json.frozen_execution_composite_sha256` = `1f9e7d8da68f7c5f9c0c8614e82435a07812c28c39d48f3064288ff5227644c7`; `audit/preflight.json.execution_composite_sha256` reads the identical value, `status=CLEAR`, `audit_ready=true`, all 6 required gates `PASSED`, generated `2026-08-22T01:41:29Z` — postdating the correction described in the task. This is a fresh composite, not the one contract_pass_25 reviewed (`ab0e65d5...`).

## Prior findings adjudicated (pass 25)

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| BLOCKING — `CENSORED/DATA_GAP` unreachable in production | **FIXED** | `implementation/collector.py` no longer defines `CENSOR_DATA_GAP` or `_invalidate_pending_horizons` anywhere (repo-wide grep for `DATA_GAP\|CENSOR_DATA_GAP\|_invalidate_pending_horizons\|target_observable` under the study returns zero hits in `collector.py` itself — the only remaining hits are (a) a documentation comment in `collector.py:55-57` explaining the removal, (b) the replacement test `test_data_gap_disposition_removed_from_declared_contract` in `tests/test_candidates_observations_interface.py:74-81`, which now asserts both symbols are absent via `hasattr`, and (c) historical prose in `audit/pass_06.md`, `pass_07.md`, `pass_23.md`, `pass_24.md`, `contract_pass_25.md` — all backward-referencing history, not live code). `pending` dicts in `_on_1s` (`collector.py:336-355`) no longer carry a `target_observable` key. `_resolve_pending_labels` (`collector.py:446-469`) unconditionally computes `flip_within_300s` and disposes every resolved candidate as `LABELED_POSITIVE`/`LABELED_NEGATIVE`; `on_stop` (`collector.py:473-488`) disposes all remaining pending candidates as `CENSORED`/`RUN_END`. The declared disposition vocabulary is now exactly `DISPOSITION_LABELED_POSITIVE`, `DISPOSITION_LABELED_NEGATIVE`, `DISPOSITION_CENSORED` + `CENSOR_RUN_END` (`collector.py:58-61`), and every one of these three values has a reachable production setter — no test-only reachability remains. `compiled_study.json` (grep for `disposition`/`DATA_GAP`, case-insensitive, whole file) contains zero references to the removed value. **The prior blocker is closed.** |
| NOTE — no standalone `config/deliverables_contract.json`, embedded in `compiled_study.json` instead | **UNCHANGED, re-confirmed** | `compiled_study.json:311-359` still carries the embedded `deliverables_contract` object (`contract_version: 1`, `authorized_modes: ["collect"]`, same 5-artifact set: `candidates.parquet`, `observations.parquet`, `collection_manifest.json`, `run_manifest.json`, `status.json`). No new `studies/.../config/deliverables_contract.json` file was added by this fix (confirmed via glob — `config/` only contains `study.yaml`). Not re-raised as blocking; this is the same narrower NOTE carried from pass 25, unaffected by the DATA_GAP remediation. |
| WARNING — contract_pass_21-24 templated boilerplate | Historical, out of scope for adjudication here (those files are unchanged; no new instance of the pattern in pass 25 or this pass) | Not re-litigated; pass 25 already recorded this once, per re-audit protocol. |

## New findings

None. No new blocking findings raised this pass (0/3 budget used).

## Notes

### NOTE: removal comment cites `research_decision.yaml` but the rationale is not actually there
`implementation/collector.py:56` states "a DATA_GAP censor reason previously existed here but was removed as a stale, production-unreachable contract member (see research_decision.yaml)." Direct read of `research_decision.yaml` (30 lines) shows it contains only `research_question`, `baseline`, `baseline_feature_selection`, `model_arms`, `variable_being_tested`, `prohibited_changes`, `allowed_changes`, `chronology`, `primary_comparison`, `terminal_question` — no mention of `DATA_GAP`, disposition, or censor logic. The actual justification lives in the task's research-decision evidence review / `contract_pass_25.md`, not in `research_decision.yaml`. This is a stale/misleading source citation in a code comment, not a contract violation (removing an implementation-detail disposition value is not the kind of baseline/model-arm/chronology change `research_decision.yaml` governs, so its absence there is not itself wrong) — cosmetic, does not block.

### NOTE: RFC §11/§12/§13 re-confirmed unchanged and still clean
- §13 (3-field reconciliation key): `backtests/nt_runtime/output_manager.py:23` — `CANDIDATE_KEY_COLUMNS = ["observation_ts", "regime_start_ns", "checkpoint_index"]` remains a fixed constant (not intersection-derived); `reconcile_candidate_dispositions` (lines 91-160) still fails closed on missing key columns before the zero-row branch. **PASS**, unchanged from pass 25.
- §11 (zero-row contract): `collector.py:495-499` (`get_candidates_dataframe`) and `:509-514` (`get_observations_dataframe`) both still return schema-carrying empty frames (`declared_metadata` / `CANDIDATE_KEY_COLUMNS`) rather than bare columnless frames; `test_empty_collector_returns_empty_dataframes` (`tests/test_candidates_observations_interface.py:148-151`) exercises this. **PASS**, unchanged.
- §12 (population funnel): telemetry counters and `test_population_funnel.py`'s funnel-identity test are untouched by this diff (not in the changed-file list); no regression found. **PASS**, unchanged.
- Reconciliation test coverage was strengthened, not weakened, by the fix: `test_candidates_and_observations_dataframes_reconcile_cleanly` (`tests/test_candidates_observations_interface.py:98-145`) now drives a real mixed batch through `_resolve_pending_labels`/`on_stop` and asserts `disposition_counts == {LABELED_POSITIVE: 1, LABELED_NEGATIVE: 1, CENSORED: 1}` — the DATA_GAP-only test slot was replaced by the reachability-negative-proof test, and the mixed-batch test no longer references a disposition value that cannot occur in production, closing the exact gap pass 25 identified.

## Referred to lookahead-auditor
None.

## Blocking verdict

CLEAR

The sole blocking finding from `contract_pass_25.md` — an unreachable `CENSORED/DATA_GAP` terminal disposition, the checklist's named repeat-historical-CRITICAL pattern for terminal-label reachability — is verified fixed by direct code and test inspection: `CENSOR_DATA_GAP` and `_invalidate_pending_horizons` no longer exist anywhere in `implementation/collector.py`, `compiled_study.json`, or any other production file, the `target_observable` flag/branch is gone, and the declared disposition vocabulary (`LABELED_POSITIVE`, `LABELED_NEGATIVE`, `CENSORED`/`RUN_END`) now has a reachable production setter for every value with an integration-style test (`test_candidates_and_observations_dataframes_reconcile_cleanly`) exercising all three through the real reconciliation path. RFC §11 (zero-row contract), §12 (population funnel), and §13 (3-field fixed reconciliation key) remain independently clean and unregressed. The embedded (not standalone-file) `deliverables_contract` in `compiled_study.json` is unchanged and was already accepted as a NOTE, not a blocker, at pass 25. This study's composite (`1f9e7d8d...`) matches across `frozen_execution_manifest.json`, `preflight.json`, and `readiness.json`, and preflight is CLEAR with all 6 required gates PASSED post-dating this fix.

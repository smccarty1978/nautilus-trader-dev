<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-pass26-smccarty", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 26

**Date:** 2026-08-22T05:20:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity` — fresh full causal pass against the freshly PREPARE'd/FROZEN composite `3be6c871...` (A, B, C1-C3, F, G, H only). No `audit_packet.json` was provided for this study directory and this session has no Bash tool, so the diff surface was built by: (1) reading `audit/frozen_execution_manifest.json`'s current 90-entry closure and file-hash map in full, (2) reading `git status` (provided in environment context) to identify which closure files have working-tree modifications since the last commit, (3) full reads of every causally-relevant modified file, and (4) full re-read of `implementation/collector.py` end-to-end (not diffed piecemeal) because it is the sole study-owned causal surface. Files read in full this pass: `implementation/collector.py`, `scripts/preexec_audit_seal.py`, `scripts/resolve_execution_manifest.py`, `backtests/nt_runtime/data_plan.py`, `backtests/nt_runtime/modes/collect.py`, `research/schemas/__init__.py`. Targeted greps confirmed `CENSOR_DATA_GAP`/`_invalidate_pending_horizons`/`target_observable` are absent from all production code (only historical audit-report prose and the study's own test/comment reference them) and confirmed `output_manager.py`'s `ts_event`/`ts_init` usages are metadata bookkeeping, not ordering logic. Unchanged closure members (`utils/runner/data.py`, `utils/causality.py`, `collectors/collector_v2/*`, `features/trackers/{structural_regime_geometry,rolling_5m_productivity}.py`, engine builder, fable5 `RegimeEngine`) were not reopened — prior passes' clean findings on those stand and the diff surface gives no reason to revisit them.
**Scope hash:** `3be6c8711aad4639263ca26241347d5f9adf17b64dc693b9a89d8ad57788a090` — verified equal across `audit/preflight.json.execution_composite_sha256` and `audit/frozen_execution_manifest.json.frozen_execution_composite_sha256` (both read directly, per task statement both already verified equal before this pass).
**Lint:** `audit/preflight.json` (`preflight_run_id 20260822T051255Z_f686d19d0e9a`) — all 6 required gates (`EXECUTION_MANIFEST`, `CAUSAL_LINT`, `ARTIFACT_SCHEMA`, `FEATURE_PROMOTION`, `RESEARCH_DECISION_FIDELITY`, `CAUSAL_INVARIANTS`) `PASSED`, `status: CLEAR`, `audit_ready: true`. Not re-derived; deterministic gate output taken as proven per scope boundary.
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 25 Note — dead-branch (`CENSOR_DATA_GAP`) removal causally inert | STILL CLEAN, re-confirmed at new composite | `implementation/collector.py` at `3be6c871...` (hash `86f8d14d...`) is content-identical in every causally-relevant line to what pass 25 reviewed at `1f9e7d8d...`: `_resolve_pending_labels` (446-471), `on_stop` (473-488), `_on_1s`/`_on_1m` timestamp guards (246-260, 361-377) read byte-for-byte and match pass 25's description exactly. The composite moved between passes 25 and 26 for a different reason (see below), not because of any further change to this file. |

## Critical findings
None.

## Warnings
None.

## Notes

### [Informational, not blocking] Composite delta this pass is the governance/seal fix, not the collector
The move from `1f9e7d8d...` (pass 25) to `3be6c871...` (this pass) is attributable to `scripts/preexec_audit_seal.py` and `scripts/resolve_execution_manifest.py` — both governance-closure members whose content hash feeds the composite. `implementation/collector.py`'s own hash (`86f8d14d...`) is unchanged from the value implied by pass 25's full-file review. Recorded for traceability only; not a defect.

## Manual verification of the two named bounded fixes

**1. Stale DATA_GAP contract surface removal —** confirmed clean, no regression:
- `implementation/collector.py:50-61` — disposition constants are exactly `LABELED_POSITIVE`, `LABELED_NEGATIVE`, `CENSORED`/`RUN_END`. No `DATA_GAP` constant, no `_invalidate_pending_horizons` method, no `target_observable` key anywhere in the file (confirmed by repo-wide grep — zero production hits; only test/comment/audit-history references remain, which is expected and correct).
- `_resolve_pending_labels` (:446-471) still takes exactly the two-branch positive/negative split on the surviving path; the resolution gate (`available_ns <= checkpoint+300s` **or** `_last_seen_1m_init_ns <= checkpoint+300s` → not yet resolvable) and the flip-membership test (`checkpoint < flip_ns <= checkpoint+300s`, strict-left/inclusive-right) are unchanged in position, operands, and boundary semantics (C1/C2). No self-labeling at the checkpoint bar itself.
- `on_stop` (:473-488) still honestly censors every still-pending candidate as `CENSORED/RUN_END` at run end rather than scoring it as an observed non-flip (C1) — this is the sole remaining terminal path other than the two label branches, matching the stated "reachable dispositions are now exactly LABELED_POSITIVE, LABELED_NEGATIVE, CENSORED/RUN_END."
- The **hard-fail replacement** for the old silent-censor path is present and causally sound: `_on_1m:371-373` calls `_has_expected_open_second(last+1s, decision-61s)` and raises `RuntimeError` only when a genuine CME trading session (via `pandas_market_calendars`, including the pre-2021-06-25 lunch-break split) overlaps the observed gap window — i.e. only on a real missing-data gap during expected trading time, not on ordinary overnight/weekend closures (G2). This is a fail-closed data-integrity check, not a look-ahead-relevant change: it terminates the run rather than computing anything from a gap.
- "Low-volume/native-filled bars remain accepted" — confirmed: `_on_1s`/`_on_1m` OHLC-sanity checks (:258-260, :375-377) validate price relationships only, no volume floor was added or removed, consistent with G4 already being N/A for this collector (no volume-gated indicator).

**2. Preexec seal verifier fix —** confirmed no causal-ordering or timestamp defect on the runtime path:
- `scripts/resolve_execution_manifest.py:541-556` documents and `verify_preexec_audit_seal` (`scripts/preexec_audit_seal.py:306-331`) now calls `resolve_execution_file_paths` — the same authoritative resolver `resolve_execution_manifest` itself uses — to map a sealed key (including pseudo-scoped `study:dataset:<id>` DatasetSpec-authority keys) to its physical path, instead of splitting the key string. The fallback branch for seal-only additive keys (`study:audit/status.json` etc., :316-331) is unchanged and still correctly literal.
- This code runs at seal-verification time in `run_collect_mode` (`backtests/nt_runtime/modes/collect.py:41`), strictly before `build_engine`/`engine.run()` (:256/:266) — i.e. before any bar is dispatched. It resolves and hashes files; it does not read, reorder, or timestamp any bar, indicator, or label. There is no path by which a defect here could produce a wrong number inside the NT event loop — at worst it fails the run closed (raises `PreexecAuditStaleError`) or passes it open, neither of which touches A-H causal surfaces.
- This finding's substantive/contract half (whether the fix correctly restores seal integrity, closes the prior false-negative/false-positive risk on `study:dataset:` keys, etc.) is C4/seal-design territory — referred, not itemized here.

## Referred to contract-checker
- Full C4 evaluation of the `CENSOR_DATA_GAP` disposition-vocabulary removal (whether `research_decision.yaml`/SPEC disclosure is complete, whether `reconcile_candidate_dispositions` in `output_manager.py` correctly enforces the narrowed 3-value contract end-to-end).
- Full seal-integrity evaluation of the `verify_preexec_audit_seal` / `resolve_execution_file_paths` fix (test coverage in `scripts/tests/test_audit_seal_guard.py`/`test_execution_closure.py`, whether the DatasetSpec pseudo-scope resolution is complete for all closure key shapes).

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4 verified clean on the causal-relevant diff surface (collector.py in full, seal/manifest resolver in full, data_plan.py/collect.py in full). H1-H4 N/A — no offline bracket simulation in this collector.

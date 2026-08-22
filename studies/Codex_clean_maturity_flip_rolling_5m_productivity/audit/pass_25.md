<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-pass25-smccarty", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "1f9e7d8da68f7c5f9c0c8614e82435a07812c28c39d48f3064288ff5227644c7"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 25

**Date:** 2026-08-22T02:15:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity` — fresh causal pass over the post-correction tree (A, B, C1-C3, F, G, H). No Bash/code-execution tool was available in this session, so `git diff` was not run directly; instead the review was scoped precisely by diffing `audit/frozen_execution_manifest.json`'s current `file_sha256_map` against pass_24's `audited_files` map (both read in full). Exactly 4 of 90 closure entries changed hash since pass_24: `implementation/collector.py`, `tests/test_candidates_observations_interface.py`, `tests/test_delayed_label_resolution.py`, and `artifacts/phase0_source_manifest.json` (a regenerated phase0 feature-authorization manifest, no code). All three code/test files were read in full; the manifest was spot-checked and confirmed to be a declarative candidate-feature/hash listing with no causal surface. No other file in the 90-file closure changed — not reopened, per re-audit protocol.
**Scope hash:** `1f9e7d8da68f7c5f9c0c8614e82435a07812c28c39d48f3064288ff5227644c7` — verified equal across `audit/preflight.json.execution_composite_sha256`, `audit/frozen_execution_manifest.json.frozen_execution_composite_sha256`, and `audit/readiness.json.r8_double_identity.composite_sha256` (all three read directly).
**Lint:** `audit/lint.json` — 0 critical / 0 warning, 82/82 files, `blocking_clean: true`, at this composite. `audit/preflight.json` (`preflight_run_id 20260822T014129Z_d7a2e24afe06`, `generated_at_utc 2026-08-22T01:41:29Z`) shows all 6 required checks (`EXECUTION_MANIFEST`, `CAUSAL_LINT`, `ARTIFACT_SCHEMA`, `FEATURE_PROMOTION`, `RESEARCH_DECISION_FIDELITY`, `CAUSAL_INVARIANTS`) `PASSED`, `status: CLEAR`, `audit_ready: true`.
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 24 Note — `_invalidate_pending_horizons`/`CENSOR_DATA_GAP` reachable only from tests, referred to contract-checker | RESOLVED (not a causal re-adjudication — this was C4/reachability, contract-checker's finding to close). The dead disposition and its only setter were **removed** from `implementation/collector.py` entirely (confirmed: `grep` for `CENSOR_DATA_GAP`/`_invalidate_pending_horizons`/`target_observable` in the study tree returns zero production hits; `tests/test_candidates_observations_interface.py::test_data_gap_disposition_removed_from_declared_contract` now asserts `not hasattr(collector_module, "CENSOR_DATA_GAP")` and `not hasattr(CleanFlipCollector, "_invalidate_pending_horizons")`). I confirm from the causal side only that the removal did not touch or weaken any live causal path (see Manual re-verification below); whether the contract-side deliverable/disposition-vocabulary implications are fully closed is contract-checker's call, not mine. |
| Pass 23 — stale preflight composite | Already FIXED as of pass 24 (adjudicated there); not reopened, composite here is a further-forward recompile, no regression. |

## Critical findings
None.

## Warnings
None.

## Notes

### [Informational, not blocking] Dead-branch removal is causally inert by construction
The removed branch (`target_observable=False` / `CENSOR_DATA_GAP`) was never reachable from `_on_1s`/`_on_1m`/`on_stop` in the tree pass_24 reviewed either — its only setter had zero production callers even before this correction. Removing an already-dead branch cannot itself introduce a causal regression; the only way this change could matter causally is if the **simplification of `_resolve_pending_labels`** (removing the `if not row.get("target_observable", True): <censor>` short-circuit that used to run before the flip-window check) altered the surviving positive/negative labeling path. It did not — see Manual re-verification.

## Manual causal re-verification performed this pass

- **`implementation/collector.py:446-471` (`_resolve_pending_labels`)** — re-derived byte-for-byte causal equivalence to pass_24's reviewed behavior on the surviving path:
  - Resolution gate: `available_ns <= checkpoint + 300*NS or _last_seen_1m_init_ns <= checkpoint + 300*NS` → `break`. Both operands are set to the same `decision_ns` at the `_on_1m` call site (`collector.py:379` then `:395`/`:413`) so a checkpoint is only popped once the full `(T, T+300s]` window has *strictly* elapsed — identical to pass_24's finding, unchanged.
  - Flip-membership test: `checkpoint < flip_ns <= checkpoint + 300*NS` — same strict-left/inclusive-right window as pass_24 (C1/C2); no self-labeling at the checkpoint bar itself.
  - `_flip_times_ns` trimming loop (`:470-471`) — unchanged text, correctly bounded by the earliest still-pending checkpoint so no flip needed by a later window is discarded.
  - The only structural change is that every resolved candidate now takes exactly one of two branches (`LABELED_POSITIVE`/`LABELED_NEGATIVE`) instead of three (the removed third being an unreachable censor short-circuit) — confirmed by reading the method top-to-bottom; there is no `target_observable` check anywhere in the current body.
- **`on_stop` (`:473-488`)** — unchanged: every still-pending candidate at run end is honestly `CENSORED/RUN_END`, never scored as an observed non-flip (C1).
- **`_on_1s`/`_on_1m` timestamp guards (`:246-260`, `:361-377`)** — re-read in full: `event_ns >= decision_ns` hard-fails (A1/A2); duplicate/out-of-order 1s and 1m guards intact; RTH gate (`is_rth_decision`) keyed on `decision_ns` (close-anchored `ts_init`), never `ts_event` (F1); `rolling_5m_crosses_rth_boundary` compares backward (`decision_ns - 300*NS`) only (F2). No change from pass_24's findings on this surface — byte-identical hash confirms these lines did not move.
- **`tests/test_delayed_label_resolution.py`** and **`tests/test_candidates_observations_interface.py`** (both read in full): assert the exact boundary behavior above (flip at `checkpoint+300s` invisible until `_last_seen_1m_init_ns` exceeds it; positive/negative dispositions match `flip_within_300s`; `CENSOR_DATA_GAP`/`_invalidate_pending_horizons` provably absent). No test asserts or exercises any pre-labeling look-ahead.
- **Deterministic evidence re-confirmed for this composite:** `readiness.json` r2 (1m delta `60_000_000_000`ns / 1s delta `1_000_000_000`ns, 200 samples each), r4 (0 causal-order inversions across 213,431 `(ts_init, timeframe)` events), r8 (execution identity resolved twice, exact match) — all at `1f9e7d8d...`, matching preflight.
- Confirmed unchanged-since-pass-24 causal core via identical hashes in `frozen_execution_manifest.json`: `utils/causality.py`, `collectors/collector_v2/{aggregator,regime_engine}.py`, `features/trackers/{structural_regime_geometry,rolling_5m_productivity}.py`, `features/registry.py`, fable5 `RegimeEngine`, `backtests/nt_runtime/{data_plan,modes/collect,output_manager,telemetry}.py`, `utils/runner/data.py` — not reopened.

## Referred to contract-checker
- Whether the `CENSOR_DATA_GAP` removal fully satisfies contract-checker's pass-25 (contract track) BLOCKING finding on unreachable terminal dispositions, and whether `research_decision.yaml`/`SPEC.md` need an explicit textual note recording the disposition-vocabulary change, is C4/deliverable-vocabulary territory — not itemized further here.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 (H1-H4 N/A — no offline bracket simulation in this collector) verified clean on the full causal-relevant surface: the 4 changed files by direct full read, the remaining 86 closure files by confirmed hash-identity to pass_24's already-clean review.

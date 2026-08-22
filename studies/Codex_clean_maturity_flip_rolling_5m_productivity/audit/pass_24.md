<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-pass24-smccarty", "critical": 0, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 24

**Date:** 2026-08-21T22:20:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity` — causal surfaces A, B, C1-C3, F, G, H. Same code tree pass_23 reviewed (composite unchanged); this pass independently re-verifies the deterministic gate evidence and re-derives the causal conclusions from the current files rather than reusing pass_23's prose as fact.
**Scope hash:** `ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b` — verified equal across all four independent artifacts: `audit/preflight.json.execution_composite_sha256`, `audit/execution_manifest.json.composite_sha256`, `audit/frozen_execution_manifest.json.frozen_execution_composite_sha256`, and `audit/readiness.json.r8_double_identity.composite_sha256` (all read directly, not taken on trust).
**Lint:** `audit/lint.json` — 0 critical / 0 warning, 82/82 files scanned, `blocking_clean: true`. `audit/preflight.json` (`preflight_run_id 20260821T215559Z_836c28e2a65b`, `generated_at_utc 2026-08-21T21:55:59Z`) shows all 6 required checks (`EXECUTION_MANIFEST`, `CAUSAL_LINT`, `ARTIFACT_SCHEMA`, `FEATURE_PROMOTION`, `RESEARCH_DECISION_FIDELITY`, `CAUSAL_INVARIANTS`) `PASSED`, `status: CLEAR`, `audit_ready: true`.
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 23 — [Gate integrity] `audit/preflight.json` pinned to stale composite `80d7ed15...` | FIXED | `audit/preflight.json` now reads `execution_composite_sha256: ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b`, `status: CLEAR`, `preflight_run_id: 20260821T215559Z_836c28e2a65b`, `generated_at_utc: 2026-08-21T21:55:59Z` — matching `execution_manifest.json`, `frozen_execution_manifest.json` and `readiness.json` exactly (all four checked independently, see Scope hash above). The old `superseded_by_preflight_run_id` chain in `audit/failure_packet.json` now correctly points forward to this run and is marked `superseded: true`/forensic-only. |
| Pass 23 — [Note/Process] Reviewed-but-unchanged causal core (`utils/causality.py`, `structural_regime_geometry.py`, `regime_engine.py`, `aggregator.py`, fable5 `RegimeEngine`) | WITHDRAWN as a distinct finding — folded into this pass's own clean-check list since no file in the tree changed since pass 23 (identical composite). Not re-reviewed a second time per the "don't reopen unchanged areas" rule. |

No other pass-23 findings existed to adjudicate (pass 23 raised exactly one CRITICAL and one NOTE, both handled above).

## Critical findings
None.

## Warnings
None.

## Notes

### [G2/C4-adjacent, referred in part] `_invalidate_pending_horizons` has no production call site
`implementation/collector.py:444-449` defines the 1s-data-gap label-invalidation path (and `CENSOR_DATA_GAP`/`DISPOSITION_CENSORED` exist and are exercised in `tests/test_candidates_observations_interface.py` and `tests/test_delayed_label_resolution.py`), but no code in `_on_1s`/`_on_1m`/`on_stop` ever calls `_invalidate_pending_horizons` in this tree — it is reachable only from unit tests that call it directly. This is not a demonstrated wrong-number defect: flip detection (`_flip_times_ns`) is derived exclusively from completed 1m bars, and `_on_1m` hard-fails the entire run (`RuntimeError("Unexpected gap in 1m reference bars")`, confirmed in `tests/test_shared_bar_quality_gate.py::test_dense_timeline_semantics_under_closures`) on any real 1-minute gap during a declared-open session — so a genuine gap crashes collection rather than silently mislabeling. Whether the `CENSOR_DATA_GAP` disposition is a reachable terminal label in the production build (as opposed to test-only) is a reachability-of-terminal-labels question — contract-checker's C4 domain, not mine to itemize further.

## Referred to contract-checker
- `_invalidate_pending_horizons` (`implementation/collector.py:444`) / `CENSOR_DATA_GAP` disposition reachability in the production collect path — see Note above; C4 territory (reachability of terminal decision labels).
- `audit/pass_ledger.json` / `audit/status.json` re-issuance bookkeeping once this pass is issued is seal/manifest-completeness (C4/seal domain), not itemized further.

## Manual causal re-verification performed this pass
- **`implementation/collector.py`** (read in full): `_on_1s` — `event_ns = ts_event`, `decision_ns = ts_init`; hard-fails if `event_ns >= decision_ns` (A1/A2). Duplicate/out-of-order 1s and 1m timestamp guards present. RTH gate `is_rth_decision(decision_ns)` uses close-anchored `ts_init`, never `ts_event` (F1). `rolling_5m_crosses_rth_boundary` compares `is_rth_decision(decision_ns - 300*NS)` vs. `is_rth_decision(decision_ns)` — backward-looking only (F1/F2). Feature snapshot (`self._features.snapshot(...)`) and structural snapshot (`self._geometry.snapshot(...)`) are built only from state already advanced by the just-dispatched bar (B2/B3). `_resolve_pending_labels` only pops and labels a pending checkpoint once **both** `available_ns > checkpoint + 300s` **and** `_last_seen_1m_init_ns > checkpoint + 300s` hold — the full (T, T+300s] window has strictly elapsed before any disposition is assigned, and the flip-membership test `checkpoint < flip_ns <= checkpoint + 300s` is strict on the left boundary, so the checkpoint bar itself cannot self-label (C1/C2). Every candidate reaches exactly one terminal disposition: `LABELED_POSITIVE`/`LABELED_NEGATIVE` (in-window resolution), `CENSORED/DATA_GAP` (`target_observable=False`), or `CENSORED/RUN_END` (`on_stop`) — none silently dropped.
- **`features/trackers/rolling_5m_productivity.py`** (read in full, new tracker bound into this study): window is strictly `[checkpoint-300s, checkpoint]` keyed on exact completed-1s `close_ts`; requires the exact boundary second to be present (`MISSING_EXACT_300S_BOUNDARY`) and the full dense 301-second run (`INCOMPLETE_1S_WINDOW`) or returns `available: False` rather than approximating — no forward reference, no `center=True`, no interpolation (B1-B7, B9).
- **`features/registry.py`** additions (`resolve_source_universe`, `bind_snapshot_anchor`, `effective_snapshot_anchor`): confirmed by direct read to be declarative metadata/bookkeeping only — no numeric feature computation, no causal surface.
- Confirmed unchanged-since-pass-22 causal core (`utils/causality.py`, `collectors/collector_v2/{aggregator,regime_engine}.py`, `features/trackers/structural_regime_geometry.py`, fable5 `RegimeEngine`) via identical file hashes in the current `execution_manifest.json` vs. what pass 22/23 reviewed — not reopened.
- `readiness.json` r2/r4 independently confirm, from actual sampled bar data (not just code reading): 1m `ts_init - ts_event == 60_000_000_000` for all 200 sampled bars, 1s delta `== 1_000_000_000` for all 200 sampled bars (A2), and zero causal callback-order inversions across 213,431 recorded `(ts_init, timeframe)` events (A1/A3/A4).

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1 (G3 excepted, N/A here), G4, H1-H4 (N/A — no offline bracket simulation in this collector) verified clean on the full causal-relevant surface, both by direct code re-read and by the deterministic `readiness.json`/`lint.json` evidence.

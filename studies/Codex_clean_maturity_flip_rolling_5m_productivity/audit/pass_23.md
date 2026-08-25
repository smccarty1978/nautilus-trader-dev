<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "auditor": "lookahead-auditor-pass23-smccarty", "critical": 1, "warning": 0, "note": 1, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 23

**Date:** 2026-08-21T22:00:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity` (causal-relevant surfaces A, B, C1-C3, F, G, H) plus the files whose hash changed since the last causal pass (`pass_22.md`, composite `80d7ed15c241d76b3e5ee6a6fe869e019725ef83ef43bf4bb22abf9ad9ee05ee`): `backtests/nt_runtime/data_plan.py`, `backtests/nt_runtime/modes/collect.py`, `backtests/nt_runtime/output_manager.py`, `backtests/nt_runtime/telemetry.py`, `features/registry.py`, `research/schemas/__init__.py`, `research/schemas/dataset_spec.py` (new), `utils/runner/data.py`, `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/collector.py`, `study.yaml`, `compiled_study.json`.
**Scope hash:** resolved execution manifest composite `ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b` (`audit/execution_manifest.json`, `audit/frozen_execution_manifest.json`, `audit/readiness.json` — all three agree).
**Lint:** No CAUSAL_LINT/CAUSAL_INVARIANTS run exists on disk for this composite (see Critical Finding 1). Last recorded lint result (`audit/lint.json`) reports 0 critical / 0 warning but is pinned to the prior, stale preflight run.
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 1

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 22 | 0 findings raised (pass 22 was CLEAR, 0/0/0) | N/A | Nothing to adjudicate; pass 22 was clean. |

This pass is a fresh review triggered by real code movement, not a re-litigation of pass 22's content.

## Critical findings

### [Gate integrity] `audit/preflight.json` is pinned to a stale, superseded composite
**Failure path:** `audit/preflight.json` (the only artifact this and every prior pass have cited as evidence that `CAUSAL_LINT`/`CAUSAL_INVARIANTS` passed) reports `execution_composite_sha256 = 80d7ed15c241d76b3e5ee6a6fe869e019725ef83ef43bf4bb22abf9ad9ee05ee`, generated `2026-08-21T04:13:51Z` (`preflight_run_id: 20260821T041351Z_1e69d74068bf`). The tree has since moved: `audit/execution_manifest.json`, `audit/frozen_execution_manifest.json`, and `audit/readiness.json` (generated `2026-08-21T21:18-21:19Z`) all independently resolve the **current** tree to a different composite, `ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b`. Diffing the two composites' file-hash maps (`audit/status.json` pass-22 `audited_files` vs. `audit/execution_manifest.json` `file_hashes`) shows at least 15 files changed hash between them, including causal-relevant runtime code: `backtests/nt_runtime/data_plan.py`, `backtests/nt_runtime/output_manager.py`, `backtests/nt_runtime/telemetry.py`, `utils/runner/data.py`, `features/registry.py`, and the study's own `implementation/collector.py`, plus two files that did not exist in the pass-22 closure at all (`research/schemas/dataset_spec.py`, `study:dataset:NQ_v0_2020_2026`). `audit/failure_packet.json` additionally records a *third*, later preflight attempt (`superseded_by_preflight_run_id: 20260821T212825Z_836c28e2a65b`, `superseded_at_utc: 2026-08-21T21:28:25Z` — after the frozen-manifest/readiness generation) whose own result was never written back to `audit/preflight.json`. There is therefore no deterministic-lint/invariant evidence on disk for the composite (`ab0e65d5...`) this pass, PREPARE and READINESS all treat as the frozen, audit-ready state. Per this repo's own mandatory-gate rule (`CLAUDE.md` Core Invariant 5 / my Step 1), a causal CLEAR must be conditioned on `audit/preflight.json` being CLEAR **for the composite under audit** — that is not currently demonstrable from artifacts, and I have no code-execution capability in this session to regenerate it.
**Manual mitigation performed:** I read every one of the changed causal-relevant files in full (not just their hashes) against checklist sections A, B, C1-C3, F, G, H (see Clean checks below) and found no look-ahead, timestamp, or label-causality defect in any of them. This does not substitute for the deterministic gate — a mechanically-catchable regression (e.g. a reintroduced `closed='right'`, `.shift(-1)`, or `center=True`) would not be visible to a manual pass with the same reliability as `causal_lint.py`, and the point of the mandatory gate is exactly to not depend on that reliability.
**Smallest fix:** Re-run `python scripts/research_preflight.py --study studies/Codex_clean_maturity_flip_rolling_5m_productivity` against the current tree and confirm the emitted `audit/preflight.json` reports `status: CLEAR` with `execution_composite_sha256 == ab0e65d5f02ac689b8e9b0fd901b0b05a38cb5846250ee5e5e373f077046252b` before this pass (or any pass) can be finalized as CLEAR at that composite.

## Warnings
None.

## Notes

### [Process] Reviewed-but-unchanged causal core
`utils/causality.py`, `features/trackers/structural_regime_geometry.py`, `collectors/collector_v2/regime_engine.py`, `collectors/collector_v2/aggregator.py`, and `studies/fable5_pre_flip_d10_reversal_entry/strategy.py` (the frozen `RegimeEngine`) are byte-identical between the pass-22 composite and the current one (hash match confirmed against both manifests) and were previously reviewed clean; not re-reviewed here per the re-audit protocol's "don't re-open unchanged areas" rule.

## Manual causal review of changed files (A, B, C1-C3, F, G, H)

- **`implementation/collector.py`** (core causal engine — hash changed): `_on_1s` enforces `event_ns < decision_ns` (A1/A2) before any state update; features/geometry snapshot only from bars already dispatched (B2/B3); `_current_regime_start_atr`/`_running_mfe_atr` are updated exclusively inside `_on_1m` from the just-closed 1m bar (no future bar referenced). Label resolution (`_resolve_pending_labels`) only pops a pending checkpoint once `available_ns > checkpoint + 300s` **and** the last-seen 1m init exceeds the same bound — the (T, T+300s] window is fully elapsed before any disposition is assigned (C1/C2 — the only look-ahead is inside the label column, by design). Data-gap and run-end paths (`_invalidate_pending_horizons`, `on_stop`) censor rather than silently drop or falsely label, so no candidate is selected out of the population on the future outcome. RTH gate (`is_rth_decision`) uses `decision_ns` (close-anchored), not `ts_event` (F1). `rolling_5m_crosses_rth_boundary` looks backward (`decision_ns - 300s`), not forward.
- **`backtests/nt_runtime/data_plan.py`**: `ts_init_delta_1s_ns`/`ts_init_delta_1m_ns` constants unchanged (1s: 1e9, 1m: 6e10 — A2, matches `readiness.json` r2 checks). New logic (`WrongPhysicalDatasetError`, `DatasetSpec` cross-check) is a declarative identity-binding assertion, not a data transformation; no causal surface.
- **`utils/runner/data.py`**: cache key widened to include catalog path (bug fix, closes a cross-catalog cache-collision risk) — strictly reduces risk, does not introduce look-ahead.
- **`backtests/nt_runtime/output_manager.py`, `telemetry.py`**: reconciliation/bookkeeping additions (population funnel, disposition counts) operate on already-produced dataframes; no feature or label computation occurs here.
- **`features/registry.py`**: additions are `resolve_source_universe` (metadata-only universe resolution) and snapshot-anchor bookkeeping (`bind_snapshot_anchor`/`effective_snapshot_anchor`) — declarative, no numeric computation.
- **`research/schemas/dataset_spec.py`, `research/schemas/__init__.py`**: new declarative Pydantic schema; `ExternalStreamSpec.availability_rule: "interval_end"` and `source_timestamp_semantics: "interval_open"` codify (not alter) the existing open-stamped/close-available convention.

## Referred to contract-checker
- `audit/status.json` (pass 22) and `audit/pass_ledger.json` pass-numbering conventions, and whether a fresh `status.json`/seal should be re-issued once preflight is regenerated, are gate/seal-integrity and manifest-completeness matters (C4/seal domain) — not itemized further here.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 verified clean on every causal-relevant file that changed since pass 22 (see manual review above); no regression found relative to pass 22's CLEAR verdict on the unchanged causal core.

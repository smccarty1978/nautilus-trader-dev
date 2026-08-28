# Phase 1 Error Registry (Packet F)

**Status:** Documentation only. No new runtime error subsystem.

This file reconciles the error codes actually introduced or exercised by Phase 1
Packets A1–B (`ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md`) against the existing
failure/status machinery:

- `<run_dir>/status.json` and `<run_dir>/run_manifest.json` — per-run terminal state,
  written by `OutputManager.finalize_failed` / `OutputManager.persist_collection`
  (`research_workflow/output_manager.py`).
- `<study>/audit/failure_packet.json` — per-preflight-attempt failure evidence,
  written by `research_workflow/preflight.py`.
- `<study>/audit/status.json` — the causal-audit-gate verdict (`lookahead-auditor` /
  `contract-checker`), written by `scripts/run_preexec_audits.py`. **Not the same file
  as `<run_dir>/status.json`** — same basename, different directory, different schema
  (audit verdict vs. run outcome). Do not conflate the two when triaging a failure.
- `<study>/audit/readiness.json` — Packet B READINESS evidence (R1–R9), written by
  `research_workflow/readiness.py::persist_readiness_artifact`.

No new artifact, exception hierarchy, or reporting path is introduced by this packet.

---

## How to read this table

- **Owning stage** — earliest point the error can fire.
- **Fail/warn** — every code below is fail-closed (raises / sets `passed: false` /
  sets `overall_status: BLOCKED`). None of these are warnings; Phase 1 has no
  soft-fail tier for these checks.
- **Artifact** — the machine-readable file a triager should open first.
- **Smallest investigation scope** — the file(s) to read before looking anywhere else.

---

## DATA / PREPARE

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `GOVERNED_CATALOG_NOT_FOUND` | PREPARE (`resolve_catalog_plan`) | `<run_dir>/status.json` (`error_message`) or preflight stdout if raised pre-run | `backtests/nt_runtime/data_plan.py` around the `catalog_rel_path` resolution (raised at the line quoting `catalog_rel_path=...`) — confirm `research/datasets/<dataset_id>.yaml` `catalog_rel_path` actually exists on disk relative to repo root |
| `CATALOG_COVERAGE_MISSING` | PREPARE (`resolve_catalog_plan`) | same as above | `backtests/nt_runtime/data_plan.py` — the named `bar_type` has zero rows in the resolved catalog; check the catalog was materialized for that bar type |
| `CATALOG_COVERAGE_GAP` | PREPARE (`resolve_catalog_plan`) | same as above | `backtests/nt_runtime/data_plan.py` — requested `[warmup_start, end]` window exceeds the catalog's actual coverage; check `coverage.start` / `coverage.end` in the `DatasetSpec` YAML against the physical catalog |
| `WRONG_PHYSICAL_DATASET` | PREPARE / READINESS (R1) | `<study>/audit/readiness.json` → `r1_dataset_identity`, or `<run_dir>/status.json` if it fires mid-run | `backtests/nt_runtime/data_plan.py` (PREPARE-side declared==resolved check) and `research_workflow/readiness.py::verify_dataset_identity_chain` (R1's declared==DatasetSpec==resolved==opened chain) — one link in that four-way identity chain disagrees |

**Note on `WRONG_PHYSICAL_DATASET`:** it is raised from two call sites — once inside
`resolve_data_plan` (PREPARE-time declared/resolved binding, `data_plan.py`) and once
inside `verify_dataset_identity_chain` (READINESS R1, `readiness.py`). Both raise the
same `WrongPhysicalDatasetError` / code string; they are not a collision, they are the
same invariant checked at two points in the pipeline (`FINAL.md` §6.5). Do not merge or
rename either occurrence.

---

## DATA / READINESS

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `TS_INIT_DELTA_MISMATCH` | READINESS (R2) | `<study>/audit/readiness.json` → `r2_1s_timestamp` / `r2_1m_timestamp` | `research_workflow/readiness.py::verify_stream_timestamp_delta` — read the `first_violation` embedded in the raised message; check the offending stream's `ts_init_delta_*_ns` in the `DatasetSpec` YAML against what the catalog actually contains |
| `CALLBACK_CAUSAL_ORDER_VIOLATION` | READINESS (R4) | `<study>/audit/readiness.json` → `r4_callback_order` | `utils/causal_registration.py::verify_callback_causal_order` (the shared verifier) fed from `research_workflow/readiness.py::run_callback_order_probe` — a 1m callback's `ts_init` preceded a 1s callback's `ts_init` it should have followed; check `add_bars_causal_order` registration order, not the probe strategy itself |
| `INSTRUMENT_PRECISION_MISMATCH` | READINESS (R3) | `<study>/audit/readiness.json` → `r3_instrument_precision` | `research_workflow/readiness.py::verify_instrument_precision` — compare `instrument.price_increment` / `price_precision` (from `create_futures_instrument`) against the sampled bar's actual close precision |

---

## COLLECTOR / READINESS

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `REAL_COLLECTOR_INSTANTIATION_FAILED` | READINESS (R5) | `<study>/audit/readiness.json` → `r5_real_collector` | `research_workflow/readiness.py::instantiate_real_collector` — the wrapped exception's `type(exc).__name__` and message are the real cause (e.g. a `RuntimeError` from `studies/<study>/implementation/phase0.py` phase-zero authorization check); do not debug READINESS itself first |
| `STRATEGY_OUTPUT_INTERFACE_MISSING` | READINESS (R6), also the pre-existing collector-mode check reused (not reimplemented) here | `<study>/audit/readiness.json` → `r6_output_interface` | `research_workflow/output_manager.py::verify_strategy_output_interface` — collector loaded bars but never produced the candidates/observations extraction interface; if R5 already failed, R6 reports `R5_PREREQUISITE_FAILED` and is not itself informative |
| `OUTPUT_SCHEMA_CONTRACT_FAILED` | READINESS (R7); also used generically inside `verify_derived_5m_path` (R2) for derived-5m schema failures | `<study>/audit/readiness.json` → `r7_synthetic_schema` (or `r2_derived_5m` for the 5m-path variant) | `research_workflow/readiness.py::build_synthetic_schema_fixture` — the synthetic candidate/observation fixture failed to pass through the real `OutputManager.persist_collection` path; check `features.metadata_columns` / `features.source` in `compiled_study.json` against what the fixture actually built |

**Current known cause of `REAL_COLLECTOR_INSTANTIATION_FAILED` on this study:** see
"Current Readiness Blocker" below — this is the stale `phase0_source_manifest.json`
condition, not a Packet B defect.

---

## OUTPUT

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `UNEXPECTED_OUTPUT_COLUMN` | output persistence (`OutputManager.persist_collection`) | `<run_dir>/status.json` / `<run_dir>/run_manifest.json` (`error_message`) | `research_workflow/output_manager.py` — candidates dataframe contains a column not in the declared surface (`declared_metadata` + registry feature universe); the error message lists the offending columns directly |
| `MISSING_CANDIDATE_KEY_COLUMN` | output persistence | same as above | `research_workflow/output_manager.py` — one of `observation_ts` / `regime_start_ns` / `checkpoint_index` (`CANDIDATE_KEY_COLUMNS`) is absent from the candidates dataframe |
| `MISSING_OBSERVATION_KEY_COLUMN` | output persistence | same as above | `research_workflow/output_manager.py` — same key columns, checked against the observations dataframe |
| `DUPLICATE_OUTPUT_COLUMNS` | output persistence | same as above | `research_workflow/output_manager.py` — candidates or observations dataframe has a repeated column name; check the collector's frame-assembly step, not the schema contract |
| `UNKNOWN_FEATURE_SOURCE` | output persistence / feature resolution | same as above (raised inside `resolve_source_universe`, called from both `output_manager.py` R7 fixture path and normal collection) | `features/registry.py::resolve_source_universe` — `features.source` in `compiled_study.json` does not match a recognized source name; check the study's `FeaturesSpec.source` value against the registry's known source set |

---

## POPULATION

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `POPULATION_FUNNEL_INCONSISTENT` | output persistence (Packet E funnel accounting) | `<run_dir>/status.json` / `<run_dir>/run_manifest.json` | `research_workflow/output_manager.py` (two call sites: reported `candidates_emitted` vs. actual emitted count; and collection-window filter producing more rows than the pre-filter count) — an accounting bug in the funnel counters, not in eligibility logic |
| `POPULATION_FUNNEL_RECONCILIATION_FAILED` | output persistence (Packet E) | same as above | `research_workflow/output_manager.py` — `total_population_checkpoints != declared_contract_exclusions + implementation_only_exclusions + candidates_emitted`; the error message states the actual totals on both sides of the identity |

---

## IDENTITY / READINESS

| `TARGET_RUNTIME_MISMATCH` | PREFLIGHT runtime binding | `<study>/audit/preflight.json` | Compare compiled `target_contract.primitive`, resolved target runtime, and collector dispatch evidence. |
| `UNKNOWN_TARGET_PRIMITIVE` | target resolution | preflight failure packet | Only `flip_within_horizon` and `ordered_barrier` are executable primitives. |
| `PRESERVED_MODEL_MISSING` / `PRESERVED_MODEL_CORRUPT` | frozen external model resolution | `studies/model_registry/<model_id>.json` | Verify the immutable registry record, artifact hash, and golden fixture. |

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `READINESS_IDENTITY_INSTABILITY` | READINESS (R8) | `<study>/audit/readiness.json` → `r8_double_identity` | `research_workflow/readiness.py::verify_identity_double_resolution` — `resolve_execution_manifest` returned two different `composite_sha256` values (or two different resolved file sets) across back-to-back calls with no mutation in between; check for non-determinism in hashing or a file changing on disk mid-resolution |
| `READINESS_IDENTITY_UNRESOLVED` | READINESS (R8) | same as above | `scripts/resolve_execution_manifest.py` — `unresolved_dependencies` is non-empty on one or both resolutions; a declared file/import in the execution closure could not be located |
| `READINESS_IDENTITY_COVERAGE_INCOMPLETE` | READINESS (R8) | same as above | `scripts/resolve_execution_manifest.py` — `coverage_pct != 100.0`; the closure does not fully account for every file it should hash |

---

## ALTERNATE EXECUTION

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `QUARANTINED_ENTRYPOINT` | static (import-time guard) | N/A — raised directly if the file is executed or imported as a runtime path; not a persisted artifact code | `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/run_collect.py` — this is the Packet A3 quarantine: the file now raises on execution rather than silently opening a hardcoded catalog. Verified at quarantine time (2026-08-21) that zero code imports it; if this fires, something re-added a live import/call path to this file |
| `ALTERNATE_CATALOG_OPENER_VIOLATION` | READINESS (R9), also runnable standalone via `scripts/scan_alternate_catalog_openers.py` | `<study>/audit/readiness.json` → `r9_alternate_opener`, or CLI stdout (`ALTERNATE_CATALOG_OPENER_VIOLATIONS: N`) when run standalone | `scripts/scan_alternate_catalog_openers.py::scan_study_for_alternate_catalog_openers` — static scan found a catalog-opening construct under `studies/<study>/**/*.py` outside `resolve_catalog_plan`. Intentionally not scoped to the execution closure (`FINAL.md` §6.6) so it also catches out-of-closure files like `run_collect.py` |

`QUARANTINED_ENTRYPOINT` and `ALTERNATE_CATALOG_OPENER_VIOLATION` are complementary,
not redundant: the former is the fixed entrypoint's own fail-closed guard (defense in
depth if something re-links it), the latter is the general static scan that would catch
*any* new alternate opener, including ones that don't yet exist.

---

## EXISTING GOVERNANCE

| Code | Owning stage | Artifact | Smallest investigation scope |
|---|---|---|---|
| `FEATURE_READINESS_SCOPE_ESCALATION` | existing fail-closed path, representative collector | `<run_dir>/status.json` / `<run_dir>/run_manifest.json` | `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/collector.py:331` — a feature became unavailable at a point that would otherwise silently suppress/admit/default/relabel a candidate (D5 in `FINAL.md` §3); this is a bare `RuntimeError("FEATURE_READINESS_SCOPE_ESCALATION")`, study-local, not shared framework code |
| `POST_FREEZE_MUTATION` | existing freeze boundary | `<study>/audit/failure_packet.json` → `failure_ids` | `scripts/resolve_execution_manifest.py` (`PostFreezeMutationError`, three raise sites: missing frozen manifest, unreadable frozen manifest, composite hash mutated after FREEZE) — something in the execution closure changed after `frozen_execution_manifest.json` was written |
| `STALE_AUDIT_EVIDENCE` | PREFLIGHT / launch | `<study>/audit/failure_packet.json` | The runtime code for this concept is `PREFLIGHT_EVIDENCE_STALE`, raised in `research_workflow/preflight.py` (~line 291): preflight validated an execution composite that no longer matches the current tree. `FINAL.md` §14's taxonomy table uses the name `STALE_AUDIT_EVIDENCE` for the same concept; **no rename applied** — the two names refer to the same check, `PREFLIGHT_EVIDENCE_STALE` is the actual code, documented here without cosmetic renaming per Packet F scope |
| `UNAUTHORIZED_EXECUTION_DOMAIN` | existing data-plan gate | `<run_dir>/status.json` / preflight output | `backtests/nt_runtime/data_plan.py` (two raise sites, both OOS/chronology gating) — requested dates fall outside the study's authorized TRAIN/DEV/OOS-unlock window |

---

## Current Readiness Blocker (expected, not a Packet B defect)

`studies/Codex_clean_maturity_flip_rolling_5m_productivity/audit/readiness.json`
currently shows `overall_status: BLOCKED`, with `r5_real_collector` failing as
`REAL_COLLECTOR_INSTANTIATION_FAILED` wrapping:

```
RuntimeError: phase-zero authorization is stale or altered; collection and fit are refused
```

(raised from `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/phase0.py:161`)
and `r6_output_interface` failing as `R5_PREREQUISITE_FAILED` in consequence. R1–R4,
R7, R8, R9 all pass (`resolved_catalog`, timestamp contracts, derived-5m path,
instrument precision, callback order, synthetic schema, identity stability, and the
alternate-opener scan are all clean).

This is **expected**: `phase0_source_manifest.json` under the study's `artifacts/`
predates the execution-affecting edits made across Packets A1–B, so phase-zero
authorization correctly refuses to proceed against a stale manifest. Regenerating
`phase0_source_manifest.json` is owned by PREPARE during final governed acceptance
(`FINAL.md` §17: `RESEARCH DECISION → PREPARE → READINESS → ...`), not by this
documentation packet. **Packet F does not touch `phase0_source_manifest.json`.**

Do not classify this R5/R6 failure as a Packet B (`readiness.py`) defect — R1–R4 and
R7–R9 prove the READINESS implementation itself is sound; R5 is correctly refusing to
instantiate the collector under a manifest it has correctly identified as stale.

---

## Carry-Forward Item (flagged, not fixed in Packet F)

`scripts/validate_smoke.py:242` derives its duplicate-candidate-key check via column
intersection rather than the full declared key:

```python
key_cols = [c for c in ["observation_ts", "regime_start_ns", "checkpoint_index"] if c in cand_df.columns]
duplicates_count = int(target_day_df.duplicated(subset=key_cols).sum()) if key_cols else 0
```

If any of the three candidate-key columns (`CANDIDATE_KEY_COLUMNS` in
`research_workflow/output_manager.py`) is absent from the smoke output, this
silently narrows the duplicate check to whichever columns happen to survive, rather
than hard-failing on the missing key field — the same failure mode `FINAL.md` §13
explicitly prohibits for candidate/observation reconciliation ("No intersection-derived
narrowing... Missing key field => hard failure").

This does not currently produce a wrong PASS on the representative study (all three key
columns are present in its output), so it is not a live defect today. It is flagged
here for final acceptance hardening before any future study relies on this particular
smoke check with a narrower candidate key surface. Not fixed in Packet F — output-manager
and smoke-validator behavior changes are out of this packet's scope.

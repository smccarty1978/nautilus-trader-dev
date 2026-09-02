<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"causal","auditor":"lookahead-auditor","critical":0,"warning":0,"note":4,"study":"regime_transition_target_before_stop_v1","audited_execution_composite_sha256":"4f45256b975f8f3b4ef310f941a00a0efbe16e4c62e5b193e769c8fa4a0b3ea9"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 08

**Date** 2026-09-01 · **Scope** `research_workflow/experiment.py`; removed `studies/regime_transition_target_before_stop_v1/implementation/{canary_diagnostics,gap_diagnostic}.py`; regenerated `artifacts/experiment_authorization.json`, `audit/pass_ledger.json`; local read-only catalog junction · **Scope hash** exec composite `4f45256b975f8f3b4ef310f941a00a0efbe16e4c62e5b193e769c8fa4a0b3ea9` · **Lint** 0 critical / 0 warning (preflight CAUSAL_LINT + CAUSAL_INVARIANTS PASSED) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 4

Inputs verified: `audit/preflight.json` status `CLEAR` for this composite (8/8 checks); `audit/readiness.json` R1–R10 PASS. Frozen manifest `audit/frozen_execution_manifest.json` `frozen_execution_composite_sha256` matches the declared composite. The delta since pass 07 is confined to authorization-record plumbing, dead-script deletion, and ledger/artifact regeneration — no feature, label, timestamp, session, barrier, or fold logic is touched. `research_workflow/modeling_drivers.py` (`85d6bee3…`), `research/analysis/modeling.py` (`f6b35f6c…`), `research_workflow/modeling_closure.py` (`5de90e51…`), `implementation/phase_d_modeling.py` (`03c2e4ba…`), `research_workflow/generic_collector.py`, `research_workflow/target_runtime.py`, `research_workflow/forward_outcomes/*` are all byte-identical to the pass-07 surface and are not in `changed_files`.

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| P01–P05 | Candidate timing T on completed bars; 13 raw causal features completed-only; `next_bar_open` strictly `ts > T`; ATR frozen at `decision_ts`; first-touch barrier race; same-bar / session-end / gap / timeout censoring → `y=null` | STILL CLEAN | Runtime files unchanged this pass; preflight CAUSAL_INVARIANTS PASSED at `4f45256b` |
| P07 [G2] | Positional Phase-D target join authenticated externally by SHA pin (not row-key) | STILL STANDS (note, disclosure only) | `phase_d_modeling.py:32-33` `AUTHORITATIVE_TARGET_SHA256` / `AUTHORITATIVE_TARGET_LOGICAL_SHA256` unchanged; re-stated as N1 |
| P07 [C3] | Selected-config metrics are post-selection, reported within TRAIN only | STILL STANDS (note, disclosure only) | Folds `phase_d_modeling.py:37-38` fit⊂past, validate future; TRAIN_YEARS gate `:142`, `:267`; re-stated as N2 |

No prior CRITICAL or WARNING was ever raised (passes 01–07 all CLEAR); nothing to mark NOT FIXED.

## Critical findings
None.

## Warnings
None.

## Notes

**N1 [G2] — Phase-D target join authenticated by SHA pin (re-stated from pass 07, disclosure only).**
`implementation/phase_d_modeling.py:32-33` binds the frozen Phase-C target table by `AUTHORITATIVE_TARGET_SHA256` / `…_LOGICAL_SHA256` and joins positionally (`pd.concat(..., axis=1)` at `:136`, with `PHASE_D_DUPLICATE_JOIN_COLUMN` guard `:138`). Correctness of row alignment rests on the pinned digest, not a join key. Unchanged this pass.

**N2 [C3] — Selected-config metrics are post-selection (re-stated from pass 07, disclosure only).**
The 108-config LightGBM grid (`phase_d_modeling.py:40-47`) is scored on expanding TRAIN folds; the selected cell's reported metrics are in-sample to the selection and must be read as TRAIN-internal, not as a held-out estimate. OOS (2024) remains behind `assert_oos_open`. Unchanged this pass.

**N3 — Read-only catalog junction into the worktree (disclosure).**
`studies-worktree/data/catalog/NQ_v0_2020_2026` is a read-only directory junction to the canonical main-repo catalog so readiness R1 can resolve. `study:dataset:NQ_v0_2020_2026` digest in the frozen manifest is `20cd3365a0013fed0691cfad09d43abc92b4a0dd9760633373d15f5ea895a146` — identical to the pass-05 audited surface and to what Phase C consumed, so no dataset substitution occurred. Year reachability is gated by authorization / the Phase-D driver, not by filesystem visibility; the physical catalog spans 2020–2026 in the main repo too. No causal exposure.

**N4 — `load_authorization` staleness check narrowed to year roles (disclosure).**
`research_workflow/experiment.py:146-154` now compares only `(train_years, oos_years, prohibited_years)` between the stored artifact and `authorize_experiment(path, write=False)` (freshly derived from `study.yaml`), instead of the full authorization hash. `study_id` / `study_path` / `schema_version` drift versus `study.yaml` is no longer flagged as stale. The TRAIN/OOS/prohibited boundary itself is still fully re-derived from `study.yaml` and re-compared on every call, and `authorize_experiment:106-107` still enforces disjointness. Governance-provenance scope only.

## Answers to referred questions

1. **Authorization change — TRAIN/OOS boundary.** No weakening. `_repo_relative_study_ref` (`experiment.py:77-90`) records `studies/<id>` so the same study resolves one authorization identity from both the main checkout and a worktree — that is the intent. Every downstream door still derives year authority freshly from `study.yaml`: `runtime_authorization` / `verify_runtime_authorization` / `assert_oos_open` call `load_authorization`, which returns `current = authorize_experiment(path, write=False)`, not a reconstruction of the stored artifact. `verify_runtime_authorization:252` still rejects prohibited years [2025, 2026]; `:254-257` still binds OOS to the current TRAIN freeze; `assert_oos_open` lineage-closure checks (`:295-309`) are untouched. The new `authorization_sha256` value differs from the pass-07 pin, so any freeze/seal that pinned the old value fails **closed** (`TrainFreezeRequired`). No non-TRAIN year becomes reachable. Provenance-scope narrowing referred below.

2. **Catalog exposure via read-only junction.** No 2024+ access path is created during readiness/preflight. Readiness reads only a ~1h TRAIN-era window (R1–R10 PASS); preflight CAUSAL_LINT / CAUSAL_INVARIANTS are static + bounded; no collection or OOS run occurs before the seal. `phase_d_modeling.py:142` (`PHASE_D_NONTRAIN_YEAR_READ`) hard-rejects any observed year outside {2021, 2022, 2023} and any of {2024, 2025, 2026}. The junction is read-only, uncommitted, and not study state; dataset digest unchanged (N3).

3. **Removed diagnostics.** No causal content. Both files are absent from the current `resolved_execution_file_list` (frozen manifest lists only `phase_d_modeling.py` and `target_before_stop_diagnostics.py` under `implementation/`). Repo-wide search finds no import of either module from collector, target-runtime, feature, or driver code — remaining mentions are in prior-seal snapshots (`audit/status.json`, `audit/contract_status.json`, `artifacts/preexec_audit_seal.json`). Deleting print-only scripts with a hardcoded catalog literal and no replacement cannot introduce look-ahead.

4. **Pass-07 clean checks re-confirmed at `4f45256b`.**
   - Expanding folds strict: `phase_d_modeling.py:36-39` — `fold_2022` fits (2021,)→validates 2022; `fold_2023` fits (2021,2022)→validates 2023. Fit years strictly precede the validation year.
   - `_assert_group_integrity` (`:169-174`): raises `PHASE_D_REGIME_GROUP_CROSSES_FOLD` if any `regime_start_ns` appears in both fit and validation partitions.
   - `fit_temporal_fold` gate (`:246-248`, delegated to `research_workflow.modeling`): `SplitPolicy(kind="explicit_index")` with explicit fold indices; chronology assertion `:267` requires `train == (2021,2022,2023)` and `2024 ∈ dev`.
   - Timestamp-evidence reuse anchored to the immutable seal: `resolve_modeling_closure` / `assert_declared_modeling_drivers` imports (`:26-27`) unchanged; ATR/timestamp contract file `config/timestamp_contract.json` digest unchanged; forward-outcome guard (`forward_outcomes/guard.py` `c7688bd3…`) unchanged.
   All four hold — the underlying files are byte-identical to the pass-07 surface and preflight CAUSAL_INVARIANTS PASSED.

## Referred to contract-checker
- `experiment.py` `authorization_sha256` value changed (record now repo-relative); verify no seal/freeze pins the prior value and that `pass_ledger.json` restoration + `experiment_authorization.json` regeneration are internally consistent.
- `load_authorization` staleness check no longer detects `study_id` / `study_path` / `schema_version` drift versus `study.yaml` (N4) — provenance completeness.
- Stale references to the deleted `canary_diagnostics.py` / `gap_diagnostic.py` remain in `audit/status.json`, `audit/contract_status.json`, `artifacts/preexec_audit_seal.json` — seal-freshness.
- Read-only catalog junction into a worktree versus `AGENTS.md` §7 data-safety policy.

## Clean checks
A1–A5, B1–B7, B9–B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — the delta touches no timestamp, feature, label, session, data-integrity, or bracket-resolution code; verified clean in passes 01–07 and unchanged at this composite.

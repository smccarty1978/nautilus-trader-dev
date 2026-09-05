# Look-Ahead & Timestamp Audit — Pass 04 (DELTA)

**Date** 2026-09-04 · **Scope** `research/schemas/study_spec.py`
(`DerivedCausalInputSpec.null_input_policy`, lines 552-560), `research_workflow/external_model_scoring.py`
(`FrozenExternalModelScorer.score()` null handling + float64 coercion, lines 295-305, 311-322;
`DerivedScoreObservation.null_inputs`/`null_input_policy`, lines 27-39), `features/trackers/host_bindings.py`
(`FrozenExternalScoreBinding.derive()`, lines 682-714), `studies/first_p90_warning_horizon_march2024/study.yaml`
(`features.derived_inputs[].null_input_policy: model_native`, lines 113, 156) ·
**Scope hash (audited composite)** `ac9af444a809134bbea524b04c65d98f5a5f5d69a44871cda275acc820e01e57`
(matches `audit/frozen_execution_manifest.json:frozen_execution_composite_sha256`,
`audit/preflight.json:execution_composite_sha256`, `audit/readiness.json:execution_composite_sha256`, and
`_work/controller/audit_packet_causal.json:identity.execution_composite_sha256` — not stale) ·
**Lint** 0 critical / 0 warning (preflight CLEAR, all 8 required checks PASSED, tests 109/109 PASS,
`FORWARD_OUTCOME_GUARD` PASSED, `leaked_outcome_columns: []`) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 (carried, unchanged) · Note: 2 (1 carried, 1 new)

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `[B2] host_bindings.py:698-705`(now 699-713) — blanket `availability_ts`/`score_evaluation_ts` makes the causal-availability refusal structurally inert | **UNCHANGED — still holds, now exercised more often** | `derive()` still assigns `ts` (=`epoch.T`) as both `score_evaluation_ts` and every input's `availability_ts` (`host_bindings.py:710-711`), regardless of policy. `available_at_ns = max(latest_input_availability_ts, evaluation_ts)` is therefore always `== checkpoint_ts`, never `>`, so the `available_at_ns > checkpoint_ts` refusal (`external_model_scoring.py:291-294`) still can never fire. `model_native` widens which *rows* reach `score()` but does not touch this mechanism at all — same inert-by-construction property as pass 01-03, just triggered on a larger row count now that fewer rows short-circuit before reaching it. |
| 2 | Note: flip kernel has no `max_gap_ns` censoring path (`host/outcomes.py`) | **N/A — file unchanged** | Not touched by this delta. |
| 3 | Referred to contract-checker: population is a declared superset of the parent's training population (D2) | **N/A — unadjudicated by this role**, same boundary as pass 03 | See "Referred to contract-checker" below |

## Critical findings
None.

## Delta-specific verification (the questions posed)

**1. No look-ahead from passing a null through.** A null in `row.get(n)` (`host_bindings.py:687`)
means the upstream causal feature computation (unchanged this delta) had nothing computable at
epoch `T` — e.g. `rolling_300s_*` before 300s of arrival data exist. `derive()` reads the row
verbatim; nothing backfills or forward-fills a later value into it before `score()` sees it
(`host_bindings.py:687, 706-713`; confirmed no write-back path exists anywhere in the diff). A
null is therefore strictly *less* information reaching the estimator, never more. `B5` clean.

**2. float64 coercion cannot fabricate a value.** `external_model_scoring.py:300-302`:
`pd.DataFrame(...).astype("float64")` turns Python `None`/`NaN` into `NaN` only; a non-numeric
scalar (e.g. a stray string) raises `ValueError` from `astype` before scoring, it is not
silently coerced to `0.0`. Confirmed by test `test_model_native_on_a_family_without_missing_support_fails_closed`
(`research_workflow/tests/test_train_provenance_attestation.py:418-425`) — an estimator without
native NaN support raises rather than scoring a fabricated value. `test_model_native_reproduces_the_estimator_on_missing_inputs_exactly`
(`:393-405`) confirms the passed-through NaN reaches `predict_proba` byte-for-byte identically
to a direct call.

**3. `null_inputs`/`null_input_policy` are observation-only provenance.** `DerivedScoreObservation`
(`external_model_scoring.py:27-39`) carries both fields; `derive()` returns only `float(obs.score)`
(`host_bindings.py:714`) — the dataclass instance itself is discarded after that one line. Grepped
the full repo (`.py`) for `null_inputs`/`DerivedScoreObservation`: the only other references are
the scorer's own construction and two unit-test assertions
(`test_train_provenance_attestation.py:405,415`). No write path carries it into the candidate row,
the compiled feature contract, or any output artifact. Cannot leak into the causal surface.

**4. All-inputs-null still yields no score.** `host_bindings.py:696-697`:
`elif all(v is None or nan for v in inputs.values()): return None`. This branch is reached only
under `model_native` (the `if` at 693 already handles `refuse` unconditionally). No test at the
binding layer exercises this specific branch directly (see Notes) — the logic itself is a
one-line guard, correctly placed before the scorer is ever called, so nothing-observed rows never
reach `score()`.

**5. Blanket-`availability_ts` warning — unaffected in kind, wider in extent.** See adjudication
row 1. No new causal exposure: the mechanism was already inert before this delta; it remains
identically inert, just invoked on more rows.

**6. Widened scored population is reproduction, not a new population.** The 100%-vs-27% jump is
exactly the gap the parity evidence measures, not a byproduct of a policy that admits new
information. `artifacts/parity/frozen_180s_null_input_policy_evidence.json` records the frozen
parent scored **all** 35,872 March candidates including the 26,018 (73%) with null
`rolling_300s_*` inputs, and re-scoring the 181 (of 239) frozen first-P90 fires sitting on such
rows with NaN passed to the same LightGBM estimator reproduces the parent's own recorded score
exactly (`max_abs_delta_vs_parent_recorded: 0.0` for both LONG and SHORT arms). The binding uses
the identical `ordered_feature_surfaces`/estimator/arm-selection path in both policies
(`host_bindings.py:672-679`) — only the null-gate at line 693 changes. The widened population is
therefore the same population the parent itself scored, not a superset invented by this delta.

## Warnings
Carried unchanged — see adjudication table row 1.

## Notes
- Carried unchanged — see adjudication table row 2.
- **New:** the all-inputs-null guard (`host_bindings.py:696-697`) has no dedicated unit test at
  the binding layer (only the scorer-level null/model_native paths are covered,
  `test_train_provenance_attestation.py:382-425`). The guard is correct by inspection and
  structurally unreachable to bypass, but an explicit `derive()`-level test would make the
  "nothing observed still yields no score" invariant regression-proof rather than
  inspection-proof. Hygiene only — does not block.

## Referred to contract-checker
- Whether the child study's `ordered_feature_surfaces`/estimator bytes are provably the exact
  ones the parent used when it produced the 35,872-row evidence (vs. a re-resolved equivalent)
  is a model-integrity/D-domain question already covered by this study's existing
  `parent_train_freeze_artifact_sha256`/`model_hashes` declarations in `study.yaml`; re-verifying
  that binding is theirs, not re-raised here as new.

## Clean checks
B5 (no backfill/imputation of nulls), B7 (n/a — no normalization in this diff) clean for the
delta. C1-C3 unaffected — this is a feature-surface input policy, not a label or split change.
A1-A5, F1-F4, G1-G4, H1-H4 not applicable — no timestamp-indexing, session, dataset-continuity,
or bracket-price code in the diff.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-claude", "critical": 0, "warning": 1, "note": 2, "study": "first_p90_warning_horizon_march2024", "audited_execution_composite_sha256": "ac9af444a809134bbea524b04c65d98f5a5f5d69a44871cda275acc820e01e57"}
<!-- AUDIT_SUMMARY_V2_END -->

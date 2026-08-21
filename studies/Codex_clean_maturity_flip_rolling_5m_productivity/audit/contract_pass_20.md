# Contract Pass 20

**Reviewer identity:** contract-checker-pass20-smccarty (distinct from any causal-audit identity used on this study)
**Study:** Codex_clean_maturity_flip_rolling_5m_productivity
**Scope:** C4, D, E, and the SPEC.md Deliverables Manifest (`docs/CAUSAL_CHECKLIST.md`).

## Adjudication of pass 19

Pass 19 recorded 0 CRITICAL / 0 WARNING, CLEAR. Nothing to adjudicate.

## What changed since pass 19

`artifacts/phase0_source_manifest.json` was regenerated via the study's own, unmodified
`implementation/phase0.write_manifest()` because the prior 2026-08-15 copy failed
`phase0.authorize_execution`'s exact-match check ("stale or altered") against current repo state.
No study code changed. Repo-wide, `features/registry.py` did change substantively since pass 19
(commit `e020bc9`, YM provisioning + range-position feature) — its embedded `registry_sha256`
(`a891f04c...`) differs from the pass-19-recorded value (`7eaac1b9...`), confirming this is a real
content change upstream, not merely a re-hash of identical bytes.

### C4 — frozen selection/chronology fidelity of the regenerated manifest

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Frozen `train_years`/`oos_year`/`unused_years`/`sealed_years`/`session`/`instrument_id` unchanged | PASS | `artifacts/phase0_source_manifest.json:12413,12424-12439` show `oos_year:2024`, `train_years:[2021,2022,2023]`, `unused_years:[2025]`, `sealed_years:[2026]`, `session:"RTH"` — identical to values pass-18/19 reviewed. `implementation/phase0.py:57-70` (`_read_config`) hard-codes these exact values and raises `RuntimeError("frozen config authentication failed...")` on any deviation; the manifest field `"authenticated": true` at line 7 proves this assertion passed against the current repo state. | `tests/test_phase0.py:13` (`candidate_count >= 25`) plus existing phase0 fixture tests exercise `authenticate()`; no test needed changing since `_read_config` is unmodified. | None. |
| Frozen `candidate_universe` selection method/years/feature_count unchanged | PASS | `phase0.py:71-79` asserts `candidate_universe == {"source": "features.registry.FEATURE_REGISTRY", "allowed_status": "verified", "selection_years": [2021,2022,2023], "feature_count": 25, "selection_method": "frozen_train_only_temporal_rank"}` byte-for-byte, raising on mismatch. Manifest `config.candidate_universe` (lines 12381-12391) matches exactly. | Same authenticate() call path; a mismatch would have produced a raised exception rather than `"authenticated": true`. | None. |
| `forbidden_lineage_tokens` guard unchanged and still enforced against current source | PASS | `phase0.py:27-31,104-109,138` — the 3-token tuple (`canonical_regime_scores_all.parquet`, `F3_top25`, `frozen_train_only_baselines`) is a module-level constant, unchanged, and `_assert_no_forbidden_lineage` is re-run against the *current* `registry.py`/`engine.py`/collector/implementation source set at generation time — meaning the regenerated manifest is a stronger check (against updated `registry.py`) than the stale one it replaced, not a weaker one. Manifest lines 12445-12449 show the same 3 tokens persisted. | None new needed; guard executed as part of `write_manifest()` that produced this artifact — a `RuntimeError` would have blocked generation had a token been found. | None. |
| `candidate_count` (497) is descriptive, not a frozen contract element, so its numeric drift potential from the `registry.py` content change is not itself a compliance issue | PASS | `tests/test_phase0.py:13` only asserts `manifest["candidate_count"] >= 25` — no exact-value pin exists anywhere in the study's frozen contract (`research_decision.yaml`, `study.yaml`, `SPEC.md` all pin `feature_count: 25` for the *selected* set, not the raw candidate universe size). `phase0.py:43-54` computes `candidate_count` dynamically from `FEATURE_REGISTRY` at generation time by design. | `tests/test_phase0.py:13`. | None — if the study wants candidate_count pinned exactly, that would be a new contract element, not a defect in this pass. |

### D — artifact-hash binding / config-building determinism

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Regenerated manifest's `spec_sha256`/embedded config bind to the SPEC.md actually audited | PASS | Manifest `spec_sha256` (`aced28d76f44...`) at line 12463 equals `audit/preflight.json:11` `"spec_hash": "aced28d76f44..."` for the current run, and equals the `study:SPEC.md` hash recorded in pass 19's `contract_status.json:105`. SPEC.md is therefore byte-identical to what pass 19 cleared; the Deliverables Manifest section did not change and needs no re-walk. | Preflight `RESEARCH_DECISION_FIDELITY: PASSED` (`audit/preflight.json:25`). | None. |
| `authorize_execution` fail-closed comparison logic unchanged | PASS | `implementation/phase0.py:153-162` (unchanged since pass 19, per task statement and no diff found in this pass's read) — exact-match-or-refuse semantics preserved; the prior manifest's rejection ("stale or altered") is exactly this gate doing its job against a genuinely outdated artifact, not a bypass. | N/A (structural read; this pass did not re-derive test coverage since the module is unmodified). | None. |

### E — not implicated (no backtest fill-model/warmup/config touched).

## New findings this pass

None.

## Referred to lookahead-auditor

(none) — this is an authenticated data-artifact refresh via unmodified fail-closed code; no causal-timing surface changed.

## Blocking verdict

CLEAR

The regenerated `artifacts/phase0_source_manifest.json` is produced by the same unmodified
`phase0.write_manifest()`/`authenticate()` code path pass 18/19 already reviewed. That code hard-codes
and asserts-equal every frozen contract element this pass owns — train/OOS/sealed years, session,
instrument, candidate-universe source/selection-method/selection-years/feature_count, and the
forbidden-lineage token list — and raises `RuntimeError` on any deviation before a manifest can be
written. The manifest's `"authenticated": true` plus a fresh `CLEAR` preflight
(`execution_composite_sha256 44a42f5f...`, `RESEARCH_DECISION_FIDELITY: PASSED`) is direct evidence
those assertions passed against current repo state, not evidence I am asked to trust blindly. The one
substantive upstream change (`features/registry.py`, YM provisioning + range-position feature, commit
`e020bc9`) changed the registry hash but not `candidate_count`'s status as a non-frozen, dynamically
computed field, and the forbidden-lineage guard was re-run against that updated file with no hits.
SPEC.md's hash is unchanged from pass 19, so the Deliverables Manifest remains internally consistent
by construction. This study remains pre-execution; no governed collect/fit/score evidence exists yet,
and its absence is correctly not a finding.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass20-smccarty", "blocking": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "44a42f5fc16b7a933689e4f755632521eba13f665a2e887c04c0b3bf0328a8fc"}
<!-- AUDIT_SUMMARY_V2_END -->

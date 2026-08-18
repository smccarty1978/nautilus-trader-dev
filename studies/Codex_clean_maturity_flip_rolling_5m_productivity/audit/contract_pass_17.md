# Contract Pass 17

**Reviewer identity:** contract-checker-pass17-smccarty (distinct from any causal-audit identity used on this study)
**Study:** Codex_clean_maturity_flip_rolling_5m_productivity
**Scope:** C4, D, E, and the SPEC.md Deliverables Manifest (`docs/CAUSAL_CHECKLIST.md`).

## Adjudication of pass 16

Pass 16 (`audit/contract_pass_16.md`, `audit/contract_status.json`) recorded 1 CRITICAL / 4 not_verified,
condensed into a single prose finding: "Coverage artifact marker persistence and previous runner refusal
paths remain not independently verified" — i.e. `structural_coverage.json`'s on-disk persistence, and
`run_exploratory_models.run()`'s own refusal behavior on (a) OOS-vs-TRAIN phase-zero lineage divergence and
(b) a stale/altered `phase0_source_manifest.json`, were implemented but only covered by tests against
isolated helpers (`_assert_structural_coverage`, `authorize_stage`), never through `run()` itself.

### FIXED: coverage-marker persistence and runner refusal paths

Verified by direct code reading, not by trusting the new test file's name or docstring:

- `implementation/run_exploratory_models.py:187-276` (`run()`) calls `authorize_stage(phase0_path, "feature_freeze", ...)` at line 193 — **before** any train partition is opened — and separately drives `_load_partitions` for TRAIN (line 195) and OOS (line 234) and `_assert_structural_coverage` for TRAIN (line 198) and OOS (line 237). These are not incidental imports; `run()`'s control flow genuinely depends on their return values (`coverage_rows` accumulates from both calls and is the exact payload later persisted).
- `structural_coverage.json` is written by `run()` itself at lines 263-265 (`(output_dir / "structural_coverage.json").write_text(...)`), from the in-memory `coverage_rows` list built during the same call. The new test `test_run_persists_structural_coverage_marker_on_disk` (`tests/test_run_exploratory_runner_integration.py:106-123`) never pre-creates this file; it calls `run()` on a tmp_path fixture and only then asserts `marker_path.is_file()`, checks `mode`, `minimum_required_coverage == 0.90`, and exactly 12 cells (2 directions × 3 buckets × {TRAIN, OOS}) all at `coverage == 1.0` — a schema+content check that would fail if `run()` stopped writing the marker or wrote a different shape.
- `_load_partitions` (lines 134-184) raises `"...has a different phase-zero lineage"` at line 148 when a partition manifest's `phase0_sha256` disagrees with the value computed from the authenticated `phase0_source_manifest.json`. `test_run_refuses_when_oos_partition_lineage_diverges_from_train_phase0` (lines 126-134) tampers only the OOS `manifest.json`'s `phase0_sha256` and calls `run()` end-to-end (not `_load_partitions` directly); since TRAIN's manifests are untouched, TRAIN loads fine and the refusal is only reachable if `run()` genuinely re-checks lineage when it opens the OOS partitions later in the same call — confirmed by matching `pytest.raises(RuntimeError, match="different phase-zero lineage")`.
- `phase0.authorize_execution` (`implementation/phase0.py:153-162`) raises `"...stale or altered..."` at line 161 when the persisted manifest content no longer equals a freshly recomputed `authenticate()`. `test_run_refuses_when_phase0_manifest_is_stale_or_altered` (lines 137-144) corrupts the actual `phase0_source_manifest.json` on disk (`phase0_path.write_text("{}")`) built by the real `phase0.write_manifest()` during fixture construction (not a mock), then calls `run()` and asserts the refusal happens before any collection/fit — consistent with `authorize_stage` being the first call inside `run()`.
- Regression sensitivity: if any of these three behaviors were removed or weakened (e.g. `run()` stopped calling `authorize_stage`, stopped re-verifying OOS lineage, or stopped writing the marker to disk), the corresponding test would fail — these are not tautological or vacuously-passing assertions.

The fixture itself is a genuine synthetic dataset (real `BASELINE_CANDIDATES`/`STRUCTURAL_FEATURES`/`ROLLING_FEATURES` pulled live from `implementation/collector.py`, RTH-clamped timestamps, all 6 directional×bucket cells populated for TRAIN and OOS), not a stub that bypasses the eligibility/coverage cascade in `_load_partitions`/`_assert_structural_coverage`.

**Verdict: FIXED.** All facets of pass 16's single critical finding (marker persistence, OOS lineage refusal, phase-zero staleness refusal) are now exercised through `run()` itself, closing the "isolated helper only" gap. `authorize_stage`'s forbidden-year refusal was already covered end-to-end in `tests/test_phase0.py:38-44` prior to pass 16 and is unaffected by this finding.

### Second/third/fourth pass-16 bullets

- "90% per-direction/per-primary-bucket structural coverage threshold frozen and tested" — reconfirmed: `config/study.yaml` value read at `run_exploratory_models.py:100-105`, asserted `== 0.90` in `tests/test_structural_coverage_gate.py:26-27`. No regression. **PASS** (unchanged from pass 16).
- "Completed-1m parent aggregation contract-clean" — causal scope (owned by `lookahead-auditor`, pass 14); not re-litigated here. **NOT APPLICABLE** to this pass.
- "Promotion, accepted conclusions, export, and Notebook knowledge-base export remain prohibited under the non-promotable waiver" — reconfirmed: every artifact `run()` writes is stamped with `MODE = "EXPLORATORY — CONTRACT GATE BLOCKED"` (`run_exploratory_models.py:31`, applied at lines 229, 252, 264, 267-268, 271, 273), and no promotion/export code path exists in this module. **PASS** (unchanged from pass 16).

## Deliverables Manifest re-check (SPEC.md)

This study predates `config/deliverables_contract.json` machinery (confirmed absent at
`studies/Codex_clean_maturity_flip_rolling_5m_productivity/config/deliverables_contract.json` and no such
mechanism exists elsewhere in the study). Per pass 01 (`audit/contract_pass_01.md`), this was already raised
once and remediated by requiring a literal Deliverables Manifest directly in `SPEC.md` (§"Deliverables
Manifest", lines 69-86), confirmed FIXED at pass 12 line 7 ("C-01: FIXED — literal Deliverables Manifest
remains present"). Re-raising the missing-JSON-contract absence now would violate the re-audit protocol
(no re-raising an already-adjudicated finding under new framing); it is recorded here as WITHDRAWN/already
resolved, not re-opened.

The literal manifest (`SPEC.md:69-86`) names frozen-contract artifacts (`artifacts/model_manifest.json`,
`artifacts/score_manifest.json`, `artifacts/result_seal.json`, `artifacts/promotion_gate.json`, etc.). None
of these exist on disk, and that is correct: no real collection/fit/score has run under this study — only
the exploratory, explicitly non-promotable diagnostic (`run_exploratory_models.run()`) has been exercised,
and only inside tests against tmp_path fixtures, never against the study's own `artifacts/` directory. The
exploratory runner writes a disjoint, differently-named artifact set (`structural_coverage.json`,
`frozen_top25.json`, `directional_oos_metrics.parquet`, `oos_predictions.parquet`,
`exploratory_model_manifest.json`, `EXPLORATORY_STUDY_REPORT.md`) under a caller-supplied `output_dir`, every
one of them mode-stamped `EXPLORATORY — CONTRACT GATE BLOCKED`. This was the explicit remediation required by
pass 12 finding 3 and remains satisfied. Absence of the frozen-contract artifacts is not a new finding at this
pre-execution stage — the SPEC's manifest describes what a promoted run must produce, not what exists today,
and nothing in `SPEC.md` or the promotion gate description claims otherwise.

## New findings this pass

None. No new blocking or warning findings identified within C4/D/E/Deliverables-Manifest scope.

## Referred to lookahead-auditor

(none)

## Blocking verdict

CLEAR

Pass 16's sole critical finding is FIXED with direct, non-tautological evidence that
`run_exploratory_models.run()` itself — not an isolated helper — persists `structural_coverage.json` to disk
and refuses on both OOS/TRAIN phase-zero lineage divergence and a stale/altered `phase0_source_manifest.json`.
The Deliverables Manifest remains the literal, already-adjudicated remediation from pass 01/12; the frozen-contract
artifacts it names are correctly absent because this study has not executed a real (non-exploratory) collection,
fit, or score pass, and the exploratory diagnostic's own output set is fully mode-stamped as non-promotable per
the pass-12 remediation. No new blocking or warning issues were found in this pass's scope.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass17-smccarty", "blocking": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "d5ebb932ccf38bd47d06a17850bca001ddb2463d5886cbf5bb0c2193952bc22e"}
<!-- AUDIT_SUMMARY_V2_END -->

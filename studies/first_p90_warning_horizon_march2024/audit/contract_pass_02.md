# Contract audit — studies/first_p90_warning_horizon_march2024 — pass 02 (DELTA)

Reviewer identity: `contract-checker-pass02-2026-09-04` (distinct from `lookahead-auditor-claude`,
the causal identity on this target — see `audit/status.json`, pass 03, `CLEAR`).
Scope: verify only the delta since `contract_pass_01.md` (BLOCKED, one CRITICAL). Pass-01 findings
not touched by this delta (provenance-attestation binding, threshold/feature-surface fidelity,
chronology narrowing, control-design deviation discipline) are not re-derived here.

## The CRITICAL — population parity STOP GATE

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Gate is registered and reachable from the compiled study | PASS | `research/analysis/diagnostic_ops.py:547-641` defines `population_parity_gate`; `OPS["analysis.gate.population_parity"]` at line 654; seeded in `research_workflow/capabilities_index.yaml:271-274` (`implementation: research.analysis.diagnostic_ops.population_parity_gate`); declared as `study.yaml:207-221` step `population_parity_gate`, `rows: first_p90`, placed as analysis step **2**, immediately after `first_p90` (step 1) and before `cumulative_incidence` (step 3) | `research/analysis/tests/test_diagnostic_ops.py:319-369` — 6 tests covering PASS, missing/extra key, moved timestamp, wrong total/stratum count, reference-sha drift, unmapped value, and `run_op` context resolution | — |
| A failure genuinely blocks every downstream artifact, not just the ones after it | PASS | `research_workflow/lifecycle_v2.py::_declared_analysis` (966-1019): the steps loop (991-1000) calls `run_op` with **no try/except**; the artifact-writing loop (1001-1012), which is the only place any file is written, runs strictly *after* the steps loop completes. A raised `AnalysisOpError` anywhere in step 2 unwinds through `_declared_analysis` before any `art in spec["artifacts"]` is reached — this is true even for `first_p90_warning_horizon_contract.json`, whose source is step 1, because the artifact loop is not interleaved with the steps loop. Zero artifacts on failure, confirmed by direct read of the control flow, not by prose. | n/a (would require a live failing run; the control-flow proof does not depend on one) | — |
| The gate fails closed, not open, on drift | PASS | Reads `expected_total`, `expected_by`, key-set equality (both directions), and per-key timestamp equality; raises `AnalysisOpError("ANALYSIS_POPULATION_PARITY_FAILED: ...")` if `failures` is non-empty (`diagnostic_ops.py:637-640`); reference bytes are sha256-pinned so the comparison target cannot itself silently drift (`:577-580`) | `test_the_gate_raises_on_a_missing_row_a_extra_row_and_a_moved_timestamp`, `test_the_gate_raises_when_the_declared_counts_do_not_hold`, `test_the_reference_itself_cannot_drift` | — |

**Pass-01 CRITICAL: CLOSED.** The gate exists, is wired into the executed step order ahead of
every scientific artifact, and a failure genuinely produces zero deliverables rather than
partial or misleading ones. This is a mechanically enforced STOP GATE, not prose.

## Are the gate's expectations the right ones

Cross-checked `study.yaml:211-221` params against `research_decision.yaml:80-121`
(`parent_dependency.march_2024_reference`) and against the parent's own
`validation_march2024/artifacts/first_p90_summary.json` (read directly, not from prose):
`{"LONG": {"reference_regimes_with_fire": 115, "exact_first_fire_matches": 115, "PASS": true}, "SHORT": {"reference_regimes_with_fire": 124, "exact_first_fire_matches": 124, "PASS": true}, "PASS": true}`.
`expected_total: 239`, `expected_by.regime_direction: {1: 115, -1: 124}` match this exactly, and
`reference_path`/`reference_sha256` point at the same `first_p90_parity.parquet` named in
`research_decision.yaml:81-82` with the identical sha256. The `value_map` (`LONG→1, SHORT→-1`)
correctly translates the reference's own vocabulary into `regime_direction`'s sign convention
before comparison, and is itself refused-not-dropped on any unmapped value
(`test_an_unmapped_reference_value_is_refused_rather_than_dropped`). **PASS.**

## D2 referral — scores evaluated outside the fitted domain

**CLOSED**, conditioned on the gate holding at runtime. The gate's key equality check (`missing`/
`extra` in `diagnostic_ops.py:615-623`) forces the anchor set (`first_p90`, built under
`eligible_when: *parent_eligibility`) to be exactly the parent's 239-row frozen set before
`cumulative_incidence` or any other statistic runs. The deliberately-superset *collected*
population (no maturity gates, no 1800s cap — `research_decision.yaml:93-95`) is unaffected by
the gate and remains available for the anchored score path by design; the gate binds only the
anchor identity, which is the one the D2 referral was about.

## regime_start_ns ↔ regime_id key semantics (causal auditor's referral)

Not independently re-derivable from source — no producing script for `first_p90_parity.parquet`
is present in this worktree (`validation_march2024/` contains only artifacts, no scripts) — but
`ordering_and_context.json:10` states the parent's own first-fire dedup is
`armed.groupby('regime_start_ns').head(1)`, and the two frames' row shape (115/124/239, matching
exactly) is consistent with `regime_id` in the reference parquet being the same regime-anchor
identity as `regime_start_ns` under the reference pipeline's own naming, not a coincidentally
equal-cardinality unrelated key. This is a **data-contract assumption true in observed data, not
structurally proven from this worktree's source**. It is not a demonstrated defect: the gate's
key-set equality check fails closed on any mismatch (wrong join → missing/extra keys reported
explicitly, not a silent pass), so a genuine semantic mismatch would surface as a gate FAILURE
(zero artifacts) rather than a silently wrong population. Verdict: **NOT VERIFIED** (assumption,
not gated by structural proof) but **risk-bounded to FAIL-closed**, which is enough to close the
referral operationally — nothing downstream can consume a mismatched key silently.

## Deliverables mapping

`research_decision.yaml:195-206` declares 11 items. Confirmed: 10 map 1:1 to `study.yaml:314-324`
(`analysis.artifacts`, including the new `first_p90_population_parity.json` → source
`population_parity_gate`), and the 11th, `FIRST_P90_WARNING_HORIZON_REPORT.md`, is the disclosed
hand-authored report (unchanged from pass 01). This is the expected mapping, not a discrepancy —
confirmed.

## Seal / freshness

`audit/frozen_execution_manifest.json:frozen_execution_composite_sha256` =
`76945644f68d00e3ff19db8399ac951eefdf4bbcdb1e2eee69d8f52ea3cf9d0c`. Same value in
`audit/status.json` (causal, pass 03, `CLEAR`), `audit/readiness.json` (`R9_closure_current:
current=76945644f68d frozen=76945644f68d`), `audit/preflight.json`, and
`_work/controller/status.json` fingerprints (`execution_composite`, `current_execution_composite`,
`plan_closure_composite` all match). No stale composite anywhere. `_work/controller/status.json`
`state: NEEDS_CONTRACT_AUDIT` confirms this remains a pre-execution audit: no `collection`/
`analyze`/`freeze` artifacts and no `preexec_audit_seal.json` exist yet, which is expected at this
stage, not a gap (consistent with pass 01's framing).

## Referred to lookahead-auditor

None new.

## Blocking verdict

**CLEAR.** The single demonstrated CRITICAL from pass 01 — a population-parity STOP GATE declared
in prose but wired to nothing — is now a mechanically enforced pipeline step that runs before any
scientific statistic and, on failure, blocks every declared artifact (verified from the actual
control flow of `_declared_analysis`, not from the step's own claim). Its declared expectations
(239 / LONG 115 / SHORT 124, correct reference path and sha256) match the parent's own frozen
summary exactly. The deliverables mapping is complete and unchanged in shape from pass 01. The
key-name heterogeneity referred by the causal auditor is a data-contract assumption this audit
cannot independently re-derive from source in this worktree, but it is structurally risk-bounded:
a genuine mismatch fails the gate closed rather than passing silently, so it does not block
clearance. Seals and composites are current and consistent across both audits.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "audited_execution_composite_sha256": "76945644f68d00e3ff19db8399ac951eefdf4bbcdb1e2eee69d8f52ea3cf9d0c", "auditor": "contract-checker-pass02-2026-09-04", "critical": 0, "note": 1, "study": "first_p90_warning_horizon_march2024", "verdict": "CLEAR", "warning": 0}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 03 (DELTA)

**Date** 2026-09-04 · **Scope** `research/analysis/diagnostic_ops.py` (`population_parity_gate`,
`OP_CONTEXT`, `OP_INPUTS["analysis.gate.population_parity"]`), `research_workflow/lifecycle_v2.py`
(`_declared_analysis` — `context={"studies_root": ...}` threading, `analyze()`), `research_workflow/grammar/compiler.py`
(`_resolve_analysis` — unchanged DAG proof, re-verified against the new step),
`studies/first_p90_warning_horizon_march2024/study.yaml` (new `analysis.steps[1]` = `population_parity_gate`,
new artifact `first_p90_population_parity.json`), `research_workflow/capabilities_index.yaml` (new
`analysis.gate.population_parity` capability), `research/analysis/tests/test_diagnostic_ops.py`
(A7 stop-gate unit tests) · **Scope hash (audited composite)**
`76945644f68d00e3ff19db8399ac951eefdf4bbcdb1e2eee69d8f52ea3cf9d0c` (matches
`audit/frozen_execution_manifest.json:frozen_execution_composite_sha256`, `audit/preflight.json:execution_composite_sha256`,
and `_work/controller/audit_packet_causal.json:identity.execution_composite_sha256` — not stale) ·
**Lint** 0 critical / 0 warning (preflight CLEAR, all 8 required checks PASSED, tests 105/105 PASS,
`FORWARD_OUTCOME_GUARD` PASSED, `leaked_outcome_columns: []`) · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 1 (carried, unchanged) · Note: 1 (carried, unchanged)

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `[B2] features/trackers/host_bindings.py:698-705` — `FrozenExternalScoreBinding.derive()` blanket `availability_ts`/`score_evaluation_ts` makes the availability refusal structurally inert | **UNCHANGED — still holds** | `host_bindings.py:690-706` re-read byte-identical to pass 01/02's citation; not in this delta's changed-file set (closure `collection` composite is the only stage that moved, and its file set now additionally includes `diagnostic_ops.py`/`study_spec.py` machinery already covered — `host_bindings.py`'s own hash is unchanged from pass 02). The new gate is an analysis-stage op; it never touches `derive()` or the scoring call site. |
| 2 | Note: flip kernel has no `max_gap_ns` censoring path (`host/outcomes.py`) | **N/A — file unchanged** | Not touched by this delta. |
| 3 | Referred to contract-checker: population is a declared superset of the parent's training population (D2) | **N/A — unchanged**, and now the subject of the gate this delta wires up (contract-checker's C4/D2 domain, not re-adjudicated here) | See "Referred to contract-checker" below |

## Critical findings
None.

## Delta-specific verification (the questions posed)

**1. The gate cannot influence collection, features, population membership at T, or the outcome.**
`analysis:` runs strictly after `collection`/`merge`/`fit`/`freeze` as a distinct governed-controller
stage (`governed_controller.py:379-397`); `_declared_analysis` (`lifecycle_v2.py:966-1019`) only ever
reads an already-materialised frame built by `self._train_frame_all_labels(...)` from already-collected
partitions. `_resolve_analysis` (`grammar/compiler.py:1090-1154`, unchanged) proves at compile time that
`population_parity_gate`'s `rows: first_p90` resolves only to the earlier `first_p90` step, never back
into `population`/`features`/`triggers` — no code path exists for an analysis artifact to feed
collection. Confirmed clean.

**2. It reads the frozen reference only; cannot feed parent data back into this study's rows/scores.**
`population_parity_gate` (`diagnostic_ops.py:547-641`) returns `{"frame": rows, ...}` — the exact
`rows` object passed in, unmodified; it never merges reference columns into the frame it returns. The
reference (`ref = reference.copy()`) is used only for set/count comparison (`left`/`right` key sets,
`expected_by` counts, `timestamp_mismatches`) and discarded. Confirmed by unit test
`test_a_matching_population_passes_the_gate_and_reports_its_evidence`
(`test_diagnostic_ops.py:319-323`, asserts `len(out["frame"]) == 3`, i.e. passthrough). Downstream
steps (`cumulative_incidence`, `negative_decomposition`, `control_selection`, `score_path`) all declare
`rows: first_p90` / `inputs: {anchors: first_p90}` directly — none reference `population_parity_gate`'s
output — so even the passthrough frame is structurally unreachable by any statistic-producing step.

**3. Ordering gives the stop-gate property — a raise prevents every later step and every artifact write.**
Traced `_declared_analysis`'s step loop (`lifecycle_v2.py:991-1000`): no `try`/`except` wraps
`run_op(...)`; an `AnalysisOpError` from `population_parity_gate` propagates directly out of the `for`
loop, out of `_declared_analysis`, and out of `analyze()` (`lifecycle_v2.py:1021-1035`, also no local
catch) — the artifact-writing loop (`for art in spec["artifacts"]`, line 1002) is unreached, so **zero**
`first_p90_*` files are written on failure. `governed_controller.py:383-397` is the only catcher in the
call chain: it wraps the whole `action(self.study)` call, converts the exception into a
`BlockerType.RUNTIME_FAILURE` card, and — critically — only calls `self._write_receipt(...)` inside the
`try` block on success (line 388), so no `analyze` receipt is written either. `study.yaml`'s declaration
order (`first_p90` → `population_parity_gate` → `cumulative_incidence` → …, `study.yaml:178-291`)
places the gate immediately after the anchor step and before every statistic, matching the description.
Confirmed the stop-gate property holds mechanically, not just in prose. Unit tests
`test_the_gate_raises_on_a_missing_row_a_extra_row_and_a_moved_timestamp`,
`test_the_gate_raises_when_the_declared_counts_do_not_hold`, `test_the_reference_itself_cannot_drift`,
`test_an_unmapped_reference_value_is_refused_rather_than_dropped` (`test_diagnostic_ops.py:326-359`)
exercise every failure branch directly against `AnalysisOpError`.

**4. `studies_root` via `context` does not smuggle a machine-local path into plan identity or the closure.**
`OP_CONTEXT = frozenset({"analysis.gate.population_parity"})` (`diagnostic_ops.py:670`); `run_op`
(`diagnostic_ops.py:673-685`) injects `context` into `kwargs` **only** when `op in OP_CONTEXT`, so no
other op (including all 6 pre-existing ones) ever receives it — confirmed no cross-op leakage.
`context={"studies_root": str(self.opts.studies_root or (self.repo_root / "studies"))}` is constructed
at runtime inside `_declared_analysis` (`lifecycle_v2.py:995`), never placed into the `plan` dict that
`compile_study` hashes into `plan_sha256`/`spec_sha256`/the execution closure — `_resolve_analysis`
returns only `{"source", "steps", "artifacts", "ops"}` (no context). The gate's own report writes back
only the **declared relative** `reference_path` string (`diagnostic_ops.py:595`, `str(reference_path)`
— the study.yaml param, not the resolved absolute `path`) and the **recomputed** `reference_sha256` —
so no absolute machine-local path reaches `first_p90_population_parity.json`, `lineage`, or
`analysis_identity_sha256`. Confirmed clean.

**5. Pass-01/02 warning (blanket `availability_ts` in `derive()`) — unaffected.**
Confirmed above (adjudication row 1). This delta is entirely post-collection/analysis-stage; it does
not touch `external_model_scoring.py`, `host_bindings.py`, or the scoring/availability call site at
all. No causal relationship between the two.

## Warnings
Carried unchanged — see adjudication table row 1.

## Notes
Carried unchanged — see adjudication table row 2.

## Referred to contract-checker
- Whether wiring this gate as `analysis.steps[1]` (rather than a `required_gates` primitive, which
  `contract_pass_01.md` noted does not exist on the packet-v2 closure) satisfies contract-checker's
  own BLOCKED finding is theirs to re-verify — mechanically it does prevent every downstream
  artifact on failure (§3 above), which is the property their finding demanded, but re-closing that
  finding is a contract-review call, not a causal one.
- `key: [regime_start_ns]` vs `reference_key: [regime_id]` is a heterogeneous-name key join; I did not
  independently verify the two columns share identity semantics beyond the fact that a type/value
  mismatch would fail closed (report every key as missing+extra, tripping the gate) rather than
  silently pass — a false-negative risk if the columns happened to coincidentally collide is a
  data-contract question for contract-checker, not evidence of one found here.

## Clean checks
B6 (join direction), C1-C3 clean for the delta — the gate is a post-collection equality check on
already-resolved columns, not a merge feeding a feature or label. A1-A5, B1-B5, B7, B9-B10, F1-F4, G1-G4,
H1-H4 not applicable — no timestamp-indexing, rolling-computation, session, dataset, or bracket-price
code in the diff. Compile-time DAG proof (`_resolve_analysis`) re-verified unaffected by the new step
(step ordering/earlier-step-only rule applies identically to `population_parity_gate`).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-claude", "critical": 0, "warning": 1, "note": 1, "study": "first_p90_warning_horizon_march2024", "audited_execution_composite_sha256": "76945644f68d00e3ff19db8399ac951eefdf4bbcdb1e2eee69d8f52ea3cf9d0c"}
<!-- AUDIT_SUMMARY_V2_END -->

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "causal-audit-scottm-ym-prev5-pass03", "critical": 0, "warning": 0, "note": 1, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "4f28b073556e060e91079706473f837aaa7e7bb09b82a5bbbc61d25ff410c758"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 03

**Date:** 2026-08-18
**Scope:** `backtests/nt_runtime/engine_builder.py::create_futures_instrument` (new
`price_precision` derivation, lines 170-176); cross-checked against
`backtests/nt_runtime/catalog_materializer.py:218-224` (pre-existing sibling
implementation of the same pattern) and `utils/runner/data.py` (`CausalDataLoader.load_bars`,
`PRODUCT` table lines 86-120) to trace bar-data provenance independent of the instrument
object. Pass_02 scope (`strategies/flip_prediction_collector.py`,
`features/trackers/range_position.py`) re-read only to confirm no further edits.
**Preflight:** run_id `20260818T130959Z_02f3877c87e1` — **CLEAR**, all 6 checks PASSED,
composite `4f28b073...` matches target.
**Lint:** N/A — `CAUSAL_LINT` reported PASSED in preflight; no new lint run needed (no
feature/label/session code touched).
**Verdict:** CLEAR (causal scope A, B, C1–C3, F, G, H)

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated (pass_02, carried forward)
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | pass_02 verdict CLEAR on `RangePositionTracker` wiring (4-line diff in `flip_prediction_collector.py`) | **CARRIED FORWARD CLEAR** | Nothing in that scope changed in this diff. `flip_prediction_collector.py` and `features/trackers/range_position.py` are untouched between the pass_02 composite (`9b6b512...`) and the pass_03 composite (`4f28b07...`); the only new file in the audited-file diff is `engine_builder.py`, which was already part of pass_02's audited set (hash `a26fbcb7...` in pass_02's status.json) and has changed hash since (confirming this is the only delta). No re-audit of the tracker logic was performed or needed. |

## Critical findings
None.

## Analysis of the new diff — `create_futures_instrument` price_precision fix

### Causally neutral — instrument metadata, not data timing (out of A/B/C/F/G/H's failure surface)
`create_futures_instrument` builds a static `FuturesContract` definition object used once, at
engine construction (`build_engine:219-220`), for `engine.add_venue`/`engine.add_instrument`
— i.e. contract specification (tick size, multiplier, activation/expiration window), not a
per-bar or per-tick computation. It contains no timestamp, no ordering logic, and executes
once before any bar is dispatched. There is no rolling window, indicator, label, or session
boundary anywhere in this function. This class of change has no causal-ordering surface to
violate (A1-A5, B1-B10, C1-C3, F1-F4 do not apply to a static, one-time contract-spec
constructor).

### Bar OHLCV values are NOT derived from the instrument's `price_precision` — verified by tracing data provenance
`build_engine` loads bars via `CausalDataLoader.load_bars` (`utils/runner/data.py:18-31`),
which calls `ParquetDataCatalog.bars(...)` directly — this returns already-materialized `Bar`
objects whose `Price` precision was fixed when the catalog parquet was written (by
`catalog_materializer.py`, a separate, earlier pipeline stage), independent of the `instrument`
object constructed at `engine_builder.py:219`. `add_bars_causal_order` (`utils/causal_registration.py:52-60`)
adds these pre-built bars to the engine via `engine.add_data(...)` with no reference to
`instrument` at all. The crash message quoted in the task
(`'price_precision' ... of 2 was not equal to 'price_increment.precision' ... of 0`) is
`FuturesContract`'s own internal self-consistency validation between two fields *on the same
object* — it fires during instrument *construction*, before any bar is touched. There is
therefore no code path by which a wrong `price_precision` on the instrument silently rounds or
otherwise alters a bar's OHLCV values: the two are structurally decoupled, and the failure mode
for a mismatch is exactly what was observed — a hard construction-time `ValueError`, not a
quiet rounding defect. This answers the task's third question: no latent causal consequence to
YM's OHLCV bars or downstream feature/label computation beyond the crash itself.

### ES/NQ — confirmed no behavioral change
`utils/runner/data.py:86-107`: NQ and ES both declare `"price_increment": "0.25"`. Applying the
new derivation, `"0.25".split(".")[1]` = `"25"`, `len(...)` = `2` — identical to the template's
prior hardcoded/inherited default of 2 (`TestInstrumentProvider.future`'s ES-shaped default).
No sealed study importing `create_futures_instrument` for NQ or ES sees any change in the
constructed `FuturesContract` (same `price_precision`, same `price_increment` string, same
`multiplier`). This is a pure bug-for-YM / no-op-for-ES/NQ fix.

### Fix matches an existing, already-correct convention
`backtests/nt_runtime/catalog_materializer.py:220-223` already implements the identical
`len(price_increment_str.split(".")[1]) if "." in ... else 0` derivation, in the earlier
catalog-build stage, for the same reason (YM's `price_increment="1"` has no template
precedent). The `engine_builder.py` fix brings the run-time instrument constructor in line with
a pattern already validated and in production use one stage earlier in the same pipeline —
this is corroborating evidence for correctness, not a novel untested formula.

### Regression characterization confirmed
`RESEARCH_AGENT_WORKFLOW_PLAYBOOK.md:585-589` ("G. Historical/stale unrelated study seals")
documents, independent of this task, a pre-existing stale-seal issue on an unrelated Gemini
study caused by an older `data_plan.py` hash mismatch, explicitly flagged as debt not to be
fixed opportunistically. This matches the task's characterization of the 1 failing test as
pre-existing, unrelated backlog debt, not a regression introduced by this change.

## Warnings
None.

## Notes

### [N1] Shared canonical infra — confirm no other symbol besides YM currently exercises the previously-silent branch
`engine_builder.py` is shared infra (per CLAUDE.md's canonical-import table); this audit
confirms the fix is correct for the three products in `utils/runner/data.py`'s `PRODUCT` table
(NQ, ES, YM). If a future product is added with a non-decimal-fraction `price_increment` string
representation not covered by the `"." in price_increment_str` branch (e.g. scientific
notation or a trailing-zero artifact from `str(Decimal(...))`), the same derivation logic would
need re-verification. Disclosure only — not a defect in the current diff.

## Referred to contract-checker
None new this pass.

## Clean checks
- A1-A5, B1-B10, C1-C3, F1-F4, G1-G4, H1-H4 — no causal/timestamp/session/label/bracket surface
  touched by this diff; instrument-construction metadata fix only, verified structurally
  decoupled from bar-data provenance.

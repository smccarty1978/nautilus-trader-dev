# Contract audit — studies/ym_prev5_range_position — pass 03

Reviewer identity: `contract-checker-pass03-2026-08-18` (distinct from the
lookahead-auditor identity for this target; distinct session from pass_01/pass_02,
same role). Scope: C4, D, E + SPEC Deliverables Manifest (docs/CAUSAL_CHECKLIST.md).
No causal theories raised here.

## Adjudication of pass_02 finding

**FIXED — carried forward, unaffected by this diff.** Pass_02 confirmed the
`RangePositionTracker` wiring fix (`strategies/flip_prediction_collector.py`
lines 28, 186, 332-333, 874, 887). The current diff touches only
`backtests/nt_runtime/engine_builder.py::create_futures_instrument` (lines
158-176) — a distinct file, distinct concern (instrument price-precision
derivation vs. feature-tracker wiring). Re-grepped
`strategies/flip_prediction_collector.py` surface for this pass: no changes
found relative to pass_02's cited lines. Pass_02's CLEAR verdict stands
unmodified.

## New diff under review: `create_futures_instrument` price-precision derivation

Prior behavior (per task description): `price_precision` was silently
inherited from `TestInstrumentProvider.future(...)`'s ES-shaped default
template (2), never overridden. Correct by coincidence for ES/NQ
(`price_increment "0.25"` → precision 2) but wrong for YM
(`price_increment "1"` → precision should be 0), producing NT's
instrument-construction error `'price_precision' of 2 was not equal to
'price_increment.precision' of 0`.

Current code (`backtests/nt_runtime/engine_builder.py:170-175`):
```
d["multiplier"] = str(data_plan.multiplier)
price_increment_str = str(data_plan.price_increment)
d["price_increment"] = price_increment_str
d["price_precision"] = (
    len(price_increment_str.split(".")[1]) if "." in price_increment_str else 0
)
```
derives `price_precision` deterministically from `data_plan.price_increment`
instead of leaving the template default. Verified against
`backtests/nt_runtime/data_plan.py:85-125` `PRODUCT_CATALOGS`:
- NQ: `price_increment: "0.25"` → `"25".__len__()` = 2 (unchanged from prior
  hardcoded/template value)
- ES: `price_increment: "0.25"` → 2 (unchanged)
- YM: `price_increment: "1"` → no `"."` → 0 (the fix; previously silently 2,
  which is the root cause of the crash described in the task)

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Fix lives in canonical shared infrastructure, not a study-local workaround | PASS | `backtests/nt_runtime/engine_builder.py:158-176` is the sole `create_futures_instrument` definition; grep of `studies/ym_prev5_range_position/**` for `price_precision\|price_increment\|create_futures_instrument` returns no matches — no bespoke per-study instrument code introduced | n/a | — |
| CLAUDE.md "Import, don't regenerate" canonical-import table honored | PASS | `engine_builder.py` is the exact file named in CLAUDE.md's BACKTEST/COLLECT table ("Engine + venue + instrument" → `backtests/nt_runtime/engine_builder.py` → `build_engine`, `create_futures_instrument`); the fix is a correction inside that canonical function, not a new sibling function or study override | n/a | — |
| Study's declared population/target/feature-list/chronology/authorized_dates unaffected | PASS | `studies/ym_prev5_range_position/study.yaml` lines 15-27 (population/target/features), 32-38 (chronology), 44-46 (authorized_dates) contain no reference to instrument precision/increment fields; diff is confined to `d["price_precision"]` derivation, a formatting/tick-size concern orthogonal to these sections | n/a | — |
| YM price_precision now correctly derived (0, not silently-inherited 2) | PASS | `data_plan.py:117` `price_increment: "1"` (no decimal) → `engine_builder.py:174` `else 0` branch fires; NT's `FuturesContract.from_dict` requires `price_precision == price_increment.precision`, satisfied for YM only after this fix | No test cited exercising `create_futures_instrument(YM_data_plan)` directly asserting `precision == 0`; the evidence is the crash-to-non-crash transition described in the task, not a new unit test in this diff | Optional: add a parametrized unit test over `PRODUCT_CATALOGS` asserting `create_futures_instrument(...).price.precision` matches each product's `price_increment` decimal length |
| ES/NQ instrument construction behaviorally unchanged (no silent re-seal trigger) | PASS (informational, not this study's scope) | `data_plan.py:91,104` both `"0.25"` → derived precision 2, identical to the value the template previously supplied unconditionally; the new derivation is a no-op for both sealed ES/NQ studies' instrument construction | n/a | — |
| Deliverables contract / authorized_modes unchanged | PASS | `studies/ym_prev5_range_position/config/deliverables_contract.json` unchanged from pass_02 (`authorized_modes: ["collect"]`, 5-artifact set) | n/a | — |

## Referred to lookahead-auditor

(none — this diff is instrument tick-size/precision metadata resolved once at
engine construction time from static `PRODUCT_CATALOGS` config; it has no
temporal or causal-ordering dimension)

## Blocking verdict

CLEAR. Pass_02's fix (RangePositionTracker wiring) is unaffected — the two
diffs touch disjoint files and disjoint concerns. The new `price_precision`
derivation in `create_futures_instrument` is the correct location under
CLAUDE.md's canonical-import contract (fixes the one function every study's
`build_engine` call imports, rather than adding a per-study override), is
deterministic and config-driven (no magic constants), leaves this study's
population/target/feature-list/chronology/authorized_dates untouched, and is
a verified no-op for ES/NQ (`price_increment "0.25"` derives the same
precision — 2 — the template previously supplied), so no re-seal is
contractually implicated for `es_wick_imbalance_acceptance_v2` or any other
already-sealed ES/NQ study by this shared-code change. No new blocking
findings; one optional non-blocking test-coverage note above.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass03-2026-08-18", "blocking": 0, "warning": 0, "note": 1, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "4f28b073556e060e91079706473f837aaa7e7bb09b82a5bbbc61d25ff410c758"}
<!-- AUDIT_SUMMARY_V2_END -->

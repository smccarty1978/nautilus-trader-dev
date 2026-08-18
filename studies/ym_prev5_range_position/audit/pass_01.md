<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "causal-audit-scottm-ym-prev5-pass01", "critical": 0, "warning": 0, "note": 1, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "e0e613caa9a4382846a99a6af20b52a292ad46bc7ae1381b568d346dee4de436"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-18
**Scope:** `features/trackers/range_position.py`, `features/engine.py`, `features/registry.py`
(range_position entry), `backtests/nt_runtime/catalog_materializer.py`,
`backtests/nt_runtime/data_plan.py` (PRODUCT_CATALOGS['YM']), `strategies/flip_prediction_collector.py`,
`studies/ym_prev5_range_position/{study.yaml,SPEC.md,compiled_study.json,config/*.json}` diffed
against `studies/es_wick_imbalance_acceptance_v2/config/*.json`.
**Preflight:** CLEAR (run `20260818T123706Z_7a57e510557a`), all 6 required checks PASSED — relied on, not re-derived.
**Verdict:** CLEAR (causal scope A, B, C1–C3, F, G, H)

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Findings

### Feature-window causality — CLEAN (B2, B3, B9)
`RangePositionTracker.update(high, low, close)` (`features/trackers/range_position.py:50-65`)
appends the just-completed bar's `(high, low)` to its `maxlen=5` deque **after** computing
`prev5_high`/`prev5_low` from the deque's pre-update contents — the current bar t is
structurally excluded from its own reference range (verified by
`scripts/tests/test_range_position_availability.py::test_current_bar_excluded_from_reference_range`
and `::test_incomplete_or_future_bar_never_observed`). `is_available` correctly requires
`bar_count >= lookback + 1` (6 completed bars) before emitting a non-`None` value, matching
the registry's declared `warmup=6, window=5, source_timeframe='1m', update_anchor='completed_1m_bar'`
(`features/registry.py:291-307`). Matches the already-verified `WickTracker` pattern
(`features/trackers/wick.py`) byte-for-byte in structure.

### Update-site timing — CLEAN (A1, B2)
`features/engine.py:201` calls `self._range_position_tracker.update(...)` from inside
`update_1m(self, bar, regime)`, whose docstring states "after regime calculations close"
(`features/engine.py:130-131`) and which derives RTH/session state from `bar.ts_init`
(close-stamped), not `bar.ts_event`. No forming/in-progress bar can reach this call site.

### Timestamp convention (YM catalog) — CLEAN (A2, A5, G1, G3)
`catalog_materializer.py:179` builds 1m/5m aggregates with
`resample(rule, label="left", closed="left")` from OPEN-stamped 1s source rows, matching
the existing frozen ES/NQ builder (`scripts/build_es_v0_2020_2026_catalog.py:44`,
`label="left"`, default `closed='left'`). `BarDataWrangler.process(..., ts_init_delta=...)`
is then applied per-stream using `PRODUCT_CATALOGS['YM']['ts_init_delta_1s_ns'/'1m_ns']`
(`data_plan.py:112-124`: 1s=+1s, 1m=+60s), producing the same OPEN-stamped `ts_event` /
CLOSE-stamped `ts_init` convention already measured for ES/NQ. `timestamp_contract.json`'s
empirical measurement (1000-sample) confirms `ts_init - ts_event == 60_000_000_000` for
1m and `== 1_000_000_000` for 1s on the actual materialized YM catalog (both `pass: true`).
`_load_raw_1s` rejects any non-`{symbol}.v.0` rows (`catalog_materializer.py:163-174`) —
G1's volume-continuous-only rule is enforced, not merely assumed.

### Population/target/censoring inheritance claim — VERIFIED, not divergent
Byte-diffed `population_contract.json`, `target_contract.json`, and `execution_contract.json`
against `studies/es_wick_imbalance_acceptance_v2/config/`: identical except `instrument.symbol/venue`
(YM/XCBT vs ES/XCME) and `chronology` (unchanged, both `train:[2024]`). `causal_checkpoint`
(5s grid, `completed_1s_bar` trigger, `interval_close` timing), `target_type=flip`,
`horizon_seconds=300`, `confirmation.mode=bar_close`, and `censoring_policy` (session-end,
max 300s) are byte-identical. The claim in `study.yaml`/`SPEC.md` that these mechanics are
inherited unchanged holds.

### Feature role — descriptive only, confirmed by absence (C1–C3)
`strategies/flip_prediction_collector.py` never references `range_position` or
`RangePositionTracker` anywhere (repo-wide grep, `strategies/` scope: zero matches). The only
places the feature name appears are `features/`, the study's own config/spec files, and its
tests. It cannot enter candidate selection, direction eligibility, regime state, or target
labeling — those all run through the strategy's own hand-rolled tracker set
(`self.structural_geometry_tracker`, `self.wick_tracker`, etc., `flip_prediction_collector.py:180-190`),
none of which includes this tracker.

## Referred to contract-checker
- `strategies/flip_prediction_collector.py` (the study's bound `strategy_class`) never
  instantiates or updates `RangePositionTracker` — only `features/engine.py`'s
  `FeatureEngine` does, and that engine is not used by this collector. `study_universe`
  resolves to `['latest_1m_close_position_prev5_range']` and is read via
  `merged_raw.get(k, None)` (`flip_prediction_collector.py:872-889`) against a `merged_raw`
  dict that never contains that key — so this is a D1 (train/serve skew, features computed
  offline ≠ features computed live in `on_bar`) / deliverable-completeness finding, not a
  causal defect: no future information is used, the column is simply never populated. Concrete
  failure path for contract-checker: every `observations.parquet` row for this study's sole
  declared feature will be `None`, on a single-day pilot whose entire stated purpose is to
  observe this feature.

## Clean checks
- A1, A2, A3, A5, B1-B9, C1, C2, C3, F1, F2 (unchanged from already-audited ES architecture;
  no new session-boundary logic introduced by the delta), G1, G2, G3 verified clean.
- H1-H4 not applicable — `collect`-only study, no bracket/exit simulation in this SPEC.

# Contract audit — studies/ym_prev5_range_position — pass 01

Reviewer identity: `contract-checker-pass01-2026-08-18` (distinct from the
lookahead-auditor identity for this target).
Scope: C4, D, E + SPEC Deliverables Manifest (docs/CAUSAL_CHECKLIST.md). No causal
theories raised here.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| population/target fidelity (session=RTH, horizon=300s, direction=both) research_decision.yaml vs study.yaml vs compiled_study.json | PASS | `study.yaml:15-23`, `compiled_study.json:21-33,111-140` all agree: RTH, both, flip, prevailing_1m_regime_transition, 300s | n/a | — |
| feature_list is exactly `[latest_1m_close_position_prev5_range]`, no extra | PASS | `study.yaml:24-28`, `compiled_study.json:40-42,144-146` | `scripts/tests/test_range_position_availability.py::test_registry_entry_identity_and_metadata` | — |
| authorized_dates = exactly `["2024-09-03"]` end to end | PASS | `study.yaml:44-47`, `compiled_study.json:89-93`, `config/execution_contract.json:7-17` (chronology only; dates live in study.yaml/compiled_study.json — all agree) | n/a | — |
| chronology train=[2024], dev=[], prohibited=[2025,2026] | PASS | `study.yaml:32-38`, `compiled_study.json:56-67,175-185`, `config/execution_contract.json:7-17` | n/a | — |
| research_decision.yaml fidelity (baseline/prohibited/allowed bindings) | PASS | `artifacts/research_decision_fidelity_report.json:2` `"status": "PASSED"`, `findings: []` — deferring to this rather than re-running per task instructions | n/a | — |
| deliverables: authorized_modes exactly `["collect"]`, matches ES precedent shape | PASS | `config/deliverables_contract.json:3-5`, SPEC.md §4 renders identically | n/a | — |
| SPEC §4 rendered from contract, not hand-authored | PASS | SPEC.md:39-57 lists same 5 artifacts/producers as `config/deliverables_contract.json` verbatim | n/a | — |
| execution.strategy_class resolves to canonical `strategies.flip_prediction_collector.FlipPredictionCollector`, no bespoke code | PASS | `compiled_study.json:171,290`; `study.yaml:50` `bespoke: {}` empty | n/a | — |
| `timing_contract: "verified"` in study.yaml/compiled_study.json does not contradict feature's `provisional` lifecycle status | PASS (not a defect) | `research/schemas/study_spec.py:124-126` — `timing_contract` is a generic causal-timing-audit default, orthogonal to per-feature lifecycle `status`; the real lifecycle status is separately and correctly captured at `compiled_study.json:157-165` (`feature_statuses: provisional`, `contains_provisional_features: [...]`) matching `research_decision.yaml:69-78`'s caveat exactly | n/a | — |
| **Runtime feature binding: does the collector strategy actually compute `latest_1m_close_position_prev5_range` at runtime?** | **FAIL** | `strategies/flip_prediction_collector.py` instantiates trackers at lines 180-193 (`ohlcv_tracker`, `price_level_tracker`, `structural_geometry_tracker`, `rolling_productivity_tracker`, `wick_tracker`, `velocity_tracker`, `volume_tracker`) — **no `RangePositionTracker` is instantiated anywhere in the file** (repo-wide grep for `RangePositionTracker`/`range_position` inside `strategies/flip_prediction_collector.py` returns zero hits). The fallback candidate-record path (`flip_prediction_collector.py:872-889`) builds `merged_raw` only from the trackers listed above, then does `feats_to_log = {k: merged_raw.get(k, None) for k in study_universe}` (line 889) where `study_universe = self.cfg.feature_list` = `["latest_1m_close_position_prev5_range"]`. Since `merged_raw` never contains that key, `feats_to_log["latest_1m_close_position_prev5_range"]` is unconditionally `None` for every candidate, regardless of the true feature value. The feature *is* correctly implemented and emits real values through `features/engine.py`'s `FeatureEngine.snapshot()` (proven by `scripts/tests/test_range_position_availability.py::test_runtime_emission_via_feature_engine`), but `FlipPredictionCollector` does not import or use `features.engine.FeatureEngine` anywhere (repo-wide grep: zero hits) — that emission path is not wired into the strategy this study actually seals and runs. | `test_range_position_availability.py::test_runtime_emission_via_feature_engine` validates a component (`FeatureEngine`) that is not in the execution path of `execution_contract.json`'s `strategy_class`. No test exercises `FlipPredictionCollector` producing a non-null value for this feature. | Wire `RangePositionTracker` (or route through `features.engine.FeatureEngine`) into `FlipPredictionCollector`'s fallback feature-merge dict (`merged_raw` at line 872) before first collection run. |

This is a D1 (train/serve skew — "features computed offline match features computed
live in the strategy's `on_bar`") violation in its most acute form: the feature is not
computed live *at all* under the sealed strategy class, so `observations.parquet`'s
sole feature column — the entire subject of this study's `terminal_question`
(`research_decision.yaml:84-87`) — would be 100% null for every emitted candidate on
2024-09-03. This is not an ambiguous spec question; it is a concrete, demonstrable
runtime gap that changes the study's ability to answer its own research question and
must block first collection.

### BLOCKING: sole study feature never computed by the sealed collector strategy

See table row above. `strategies/flip_prediction_collector.py` has no
`RangePositionTracker` instantiation and does not use `features/engine.py`'s
`FeatureEngine`, so `latest_1m_close_position_prev5_range` resolves to `None` for
every row via the `merged_raw.get(k, None)` fallback at `flip_prediction_collector.py:889`.

## Referred to lookahead-auditor

(none — no causal theory identified beyond the above contract/wiring defect)

## Blocking verdict

BLOCKED. One demonstrated CRITICAL: the study's sole declared feature has no runtime
computation path inside the sealed `FlipPredictionCollector` strategy, so the
`collect`-mode deliverables would carry an entirely null feature column, defeating the
study's stated purpose before any economic or causal question can even be asked. All
other C4/D/E and Deliverables-Manifest checks pass. Remediation is narrow: wire
`RangePositionTracker` (or `FeatureEngine`) into the collector's feature-merge path;
no scope, chronology, or contract change is implicated.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "auditor": "contract-checker-pass01-2026-08-18", "blocking": 1, "warning": 0, "note": 0, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "e0e613caa9a4382846a99a6af20b52a292ad46bc7ae1381b568d346dee4de436"}
<!-- AUDIT_SUMMARY_V2_END -->

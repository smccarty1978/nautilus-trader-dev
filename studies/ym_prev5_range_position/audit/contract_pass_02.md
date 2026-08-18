# Contract audit — studies/ym_prev5_range_position — pass 02

Reviewer identity: `contract-checker-pass02-2026-08-18` (distinct from the
lookahead-auditor identity for this target; distinct session from pass_01, same role).
Scope: C4, D, E + SPEC Deliverables Manifest (docs/CAUSAL_CHECKLIST.md). No causal
theories raised here.

## Adjudication of pass_01 finding

**FIXED.** `strategies/flip_prediction_collector.py` now:
- imports `RangePositionTracker` (line 28: `from features.trackers.range_position import RangePositionTracker`)
- instantiates it unconditionally in `__init__` (line 186: `self.range_position_tracker = RangePositionTracker()`), directly beside `self.wick_tracker = WickTracker()` (line 185) — not gated by `self._is_targeted_60`
- updates it on every completed 1m bar inside the single, unconditional `_handle_1m_bar` handler (line 333: `self.range_position_tracker.update(h, l, c)`), directly after `self.wick_tracker.update(o, h, l, c)` (line 332)
- snapshots it and merges the result into `merged_raw` in the general/fallback feature path (line 874: `range_position_feats = self.range_position_tracker.calculate()`; line 887: `**range_position_feats,` inside the `merged_raw = {...}` literal at 876-888)

Since `_is_targeted_60 = bool(config.feature_list and len(config.feature_list) == 60)` (line 178) and this study's `feature_list` has length 1 (`study.yaml:27`, `["latest_1m_close_position_prev5_range"]`), `_is_targeted_60` is `False` for this study, so execution takes the general fallback path (lines 844-894) — the exact path now wired. `study_universe = self.cfg.feature_list` (line 890) = `["latest_1m_close_position_prev5_range"]`, and `feats_to_log = {k: merged_raw.get(k, None) for k in study_universe}` (line 894) now resolves that key against a `merged_raw` dict that actually contains it (via `range_position_feats`), so the value is the tracker's live `latest_value` — `None` only during the tracker's own documented warmup/flat-range conditions (`features/trackers/range_position.py:50-65`, `is_available` requires `bar_count >= lookback + 1 = 6`), not a structural absence. This is no longer a D1 train/serve-skew defect; the collector now computes the same feature at runtime that `scripts/tests/test_range_position_availability.py` already validates in isolation for the tracker's own logic.

## Compliance table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Runtime feature binding: collector computes `latest_1m_close_position_prev5_range` | PASS | `strategies/flip_prediction_collector.py:28,186,332-333,874,887` — tracker imported, instantiated, updated every 1m bar, merged into `merged_raw` before `feats_to_log` resolution (line 894) | `scripts/tests/test_range_position_availability.py` validates tracker warmup/value logic in isolation; no new test added exercising `FlipPredictionCollector` end-to-end, but the wiring pattern is mechanically identical to the already-accepted `wick_tracker` path (lines 185/332/873/886) | none required; optional: an integration test asserting `FlipPredictionCollector`'s `merged_raw` contains a non-None value after 6 bars, mirroring the tracker unit test |
| Diff confined to general/fallback feature-snapshot path only | PASS | All 4 new/changed lines (28, 186, 333, 874/887) sit outside the `if self._is_targeted_60:` gate at line 645 that scopes the `all_computed_60` candidate-record block (lines 802-841); `_handle_1m_bar` (line 246) and its tracker-update calls (lines 300-333) are unconditional, not branch-gated | n/a | — |
| `all_computed_60` / targeted-60 candidate path untouched | PASS | Lines 802-841 (`all_computed_60` dict, `for col in (self.cfg.feature_list or all_computed_60.keys())` at 837) contain no reference to `range_position_feats` or `RangePositionTracker`; not in scope for this study (`_is_targeted_60` is `False` here) and correctly left unchanged | n/a | — |
| WickTracker behavior/output unchanged | PASS | `wick_tracker` init (line 185), update (line 332), calculate/merge (lines 873, 886) are byte-identical to pass_01 audited state; the new tracker's lines were inserted adjacent, not interleaved into WickTracker's own calls | n/a | — |
| `deliverables_contract.json` unchanged | PASS | `studies/ym_prev5_range_position/config/deliverables_contract.json` — `authorized_modes: ["collect"]`, 5-artifact `collect` deliverable set, identical to pass_01 | n/a | — |
| authorized_dates / chronology / feature-list identity unchanged | PASS | `study.yaml:27` still exactly `["latest_1m_close_position_prev5_range"]`; authorized_dates and chronology fields not touched by this diff (not present in the grep surface for this change; pass_01's citations at `study.yaml:15-23,32-38,44-47` are structurally distinct sections from the `__init__`/`_handle_1m_bar`/merge-path lines this diff touched) | n/a | — |
| No other sealed study's strategy behavior affected | PASS | `flip_prediction_collector.py` is shared across studies (e.g. `es_wick_imbalance_acceptance_v2`); the added tracker only appends a new key to `merged_raw`/`all_computed_60`-adjacent dicts and does not remove or rename any existing key, so other studies' `feature_list` resolutions via `merged_raw.get(k, None)` are unaffected (they simply ignore the new key if not in their own `feature_list`) | n/a | — |

## Referred to lookahead-auditor

(none — no causal theory identified; `RangePositionTracker.update()` is called only with completed-bar OHLC per its own docstring contract, consistent with pass_01's scope boundary)

## Blocking verdict

CLEAR. The single pass_01 CRITICAL (sole declared feature never computed by the sealed
collector strategy) is FIXED by a minimal, pattern-matched 4-line wiring change that
exactly mirrors the already-accepted `WickTracker` integration. The fix is confined to
the general/fallback feature-snapshot path this study actually exercises
(`_is_targeted_60 == False`); the targeted-60 candidate path, deliverables contract,
chronology, authorized_dates, feature-list identity, and other sealed strategies'
behavior are all unchanged. No new blocking findings.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker-pass02-2026-08-18", "blocking": 0, "warning": 0, "note": 0, "study": "ym_prev5_range_position", "audited_execution_composite_sha256": "9b6b51243d215f3c6d83909c84d06c9805b2091d1eb23fe96bdad1d0b48d187a"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 03

**Date** 2026-09-06 · **Study** `es_180s_model_c_portability` · **Auditor** `lookahead-auditor:008_causal_audit_0e982346`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (sha256 `3555ab1deee1…`, packet_version 2) + the 1-file closure delta since the prior audited composite; branch `study/es_180s_model_c_portability` @ `85a7724d`
**Audited execution composite** `6d44da61d0649a99f3491ee413ae449c71de8dd1aaf793b64aa8ddadc0bf0222` (90 files, hash v2) · prior audited `4f766f573447` @ `fd943207`
**Gate facts cited, not re-derived** preflight CLEAR (8/8 required, `leaked_outcome_columns=[]`) · readiness PASS (R1_ES, R3, R5, R8, R9, R10) · tests PASS 132/0 @ `6d44da61d064` · controller STATUS=OK / NEEDS_CAUSAL_AUDIT, fingerprints frozen==current
**Changed executable surface** 1 changed, 0 added, 0 removed: `research_workflow/lifecycle_v2.py` (`d107c8aed9cd`→`4afdce38d4fc`). Source delta reviewed via `git diff fd943207e35a..HEAD -- research_workflow/lifecycle_v2.py` (37 insertions / 4 deletions, 3 hunks). Post-collection stage only — no collection-time feature, tracker, kernel or label code is touched.
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 7 (6 standing from pass 02, 1 new)

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| B9 | `host_bindings.py:154,219-239` excursion extremes miss the regime-start minute | STANDING (note) | `features/trackers/host_bindings.py` is not in the 1-file delta (brief §3); unchanged since `4f766f573447`. Past-information omission, conservative on the qualify gate. |
| G2 | `host_bindings.py:275-317` 5m calendar buckets require no completeness | STANDING (note) | Same file, unchanged; dependent `prior_5m_*` still gated by `features.structural_snapshot_ready` (packet `population.qualify`). |
| F2 | `research_workflow/host/…` rolling providers — no session reset on `rolling_300s_*` | STANDING (note) | No `research_workflow/host/*` file is in the delta; `chronology.windows` still `[]` (packet). Aggregated bars remain strictly past. |
| G4 | `host_bindings.py:591` 1m dispatch hardcodes `volume: 0.0` | STANDING (note) | Same file, unchanged; the 13 declared aliases (packet `features.aliases`) are volume-free and no `ohlcv_delta` tracker is instantiated (packet `trackers`). |
| A1 | `structural_regime_geometry.py:176` `can_snapshot` admits `close_ts == T` | STANDING (note) | Same file, unchanged; equality case still unreachable — `streams[es_1m].visibility = strictly_before`, `same_ts = unavailable`, `same_timestamp_rule` unchanged in the packet. |
| C1/C3 | `lifecycle_v2.py:1199-1206` declared-analysis step context carries `study_dir`/`model_root`, bypassing `assert_oos_open` | STANDING (note) | The declared-analysis branch (`lifecycle_v2.py:1280-1286`) is byte-identical in this delta; still inert here — `compiled_plan.json:2` is `"analysis": null`, so the branch cannot execute and `assert_oos_open` (`:1288`) remains the only door taken. |

No prior finding is re-raised under new framing; none was CRITICAL or WARNING, so none blocked. No prior finding is WITHDRAWN.

## Critical findings

None.

## Warnings

None.

## Notes

### [C1] `research_workflow/lifecycle_v2.py:127-140` — the new subset guard keys on `arm`/`cell`, not on `direction`
`_model_record_subset` refuses a record that carries `arm` or `cell` but no `"subset"` key (`:135-138`), and otherwise returns `{}` (no population filter). The field that actually signals a sliced population is `direction`: a hypothetical record with `direction: "long"` and no `arm`/`cell`/`subset` would fall through to `{}` and be scored over the whole undirected OOS population — exactly the defect the guard exists to prevent. **Not reachable in the audited closure:** every record written by the fit path carries `arm`, `cell`, `subset` and `direction` together (`:980-989`), `direction` is itself derived from `cell["subset"]` (`:964`), and `mode: score` records are handled by the earlier branch (`:1306-1316`) which never calls this helper. Hardening disclosure, not a defect.

## Verified positives (the delta-specific checks that mattered)

- **The subset change is strictly tightening, in the direction the checklist wants.** OOS binding moved from `dict(m.get("subset") or {})` to `_model_record_subset(m)` at both use sites (`:1342`, `:1346`). The old expression silently mapped a missing subset to "score on everything"; the new one raises `MODEL_RECORD_SUBSET_MISSING`. For a record that does carry `"subset"`, behaviour is byte-identical (`:133`). No population can now be widened silently between fit and OOS — the scope of the OOS metric is still carried by the record, never re-derived from a recompiled plan.
- **The subset is applied, and a typo cannot silently disable it.** `_score_models` filters `rows[rows[col] == val]` per subset entry and raises `MODEL_SUBSET_COLUMN_MISSING` if the column is absent (`:1095-1098`), so a stale subset key fails loudly rather than producing an unfiltered, plausible number.
- **No fit is reachable in the changed path.** Both changed OOS call sites feed `_score_models`, which only calls `authenticate_model`/`read_manifest`/`score` on stored canonical bytes (`:1083-1109`). Feature identity comes from the store's `lineage.ordered_inputs` (`:1090`), not from the frame — passing a wider frame cannot admit the label column or reorder inputs (C1, C2, C3 clean).
- **Both changed OOS lines sit behind the OOS door.** `assert_oos_open(self.study)` is at `:1288`; `base = self.work/"partitions"/"oos"` restricted to `self._authorized_years(plan, "oos", …)` at `:1290-1291`; the multi-cell branch at `:1330-1347` runs strictly after both. The declared invariant "assert_oos_open is the only OOS door" is unchanged by this delta.
- **`_model_record_metrics` cannot import an OOS number into a TRAIN freeze.** It reads only `experiment_models.json` (`:1148`), written at fit/score time before OOS is opened, and returns either the mirrored top-level `metrics` (`:145`) or the per-record `cell_metrics` (`:147`). Those metrics are folds + `final_validation` over `final_train_validation_years` and the tuning report (`:975-976`) — TRAIN-declared windows, with fold thresholds taken from the fit window's own score distribution and applied unchanged to validation (`:933-934`). Feature/label separation and the temporal split are unaffected (C3 clean).
- **`new_models_trained` still reads False where it should.** `bool(models.get("new_models_trained") or models.get("model_id"))` (`:1186`) is False for `mode: score` (body writes `new_models_trained: False` and `model_id: None`, `:1122-1126`) and True for a fit (`:1001`). The OR only repairs the multi-cell fit case, which previously declared no training had happened.
- **Blast radius for this study is nil on the executed path.** `model.arms` is `[]` and no cells are declared (packet `model`), so fit mirrors a single record to the top level (`:1003-1007`); freeze then takes the `models.get("model_id")` branch (`:1154`) with `metrics` already non-null, and `analyze` takes the `elif models.get("model_id")` branch (`:1317-1329`). `_model_record_subset` is never invoked here; `_model_record_metrics` returns `models["metrics"]` unchanged. The delta is a closure-membership change on this study — which is what a portability comparison requires.
- **No feature-path or timestamp code in the delta.** The 3 hunks introduce no `center=True`, `.shift(-N)`, `bfill`, `merge_asof`, resampling, `BarType` construction, session gate or bracket simulation. Year assignment in the scored frame is still UTC from `observation_ts` (`:1075`), and RTH emission 08:30–15:15 CT = 14:30–21:15 UTC keeps the UTC date equal to the CT date, so no candidate migrates across a partition boundary (F3, F4 clean).

## Referred to contract-checker

- Freeze payload provenance semantics of the delta: `new_models_trained` now ORs the fit body's own flag, and `metrics` falls back to a per-record map — in `mode: score` that fallback yields `{name: null}` rather than `null` (`:141-147`). Deliverable content and model-integrity declaration, not causality.
- `MODEL_RECORD_SUBSET_MISSING` as a hard refusal of legacy records (freeze/OOS reuse of pre-existing artifacts) and the empty `model.arms` / `model.validation` against the 2020-2023 TRAIN declaration.

## Clean checks

A1–A5 clean (A3, A4 not applicable: host-driven collector, no strategy price lookup, no timer/alert callbacks) — carried from passes 01–02 for the unchanged collection surface; the delta adds no timestamp construction or resampling. B1–B7, B9, B10 clean — the delta contains no feature-path code at all. C1–C3 clean (C1 with the new note above). F1–F4 clean. G1–G4 clean (G2, G4 with the carried notes). H1–H4 not applicable: `outcome.contract` is `label`, `kernel: flip`, `atr: null`; no bracket simulation exists and the delta adds none.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "es_180s_model_c_portability", "auditor": "lookahead-auditor:008_causal_audit_0e982346", "audited_execution_composite_sha256": "6d44da61d0649a99f3491ee413ae449c71de8dd1aaf793b64aa8ddadc0bf0222", "critical": 0, "warning": 0, "note": 7}
<!-- AUDIT_SUMMARY_V2_END -->

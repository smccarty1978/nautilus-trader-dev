# Look-Ahead & Timestamp Audit — Pass 02

**Date** 2026-09-06 · **Study** `controlled_feature_family_180s` · **Auditor** `lookahead-auditor:008_causal_audit_6dd5120e`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (packet_version 2, sha256 `3f9a1811c0d1…`) + the 2-file closure delta since the prior audited composite + 4 targeted source reads
**Scope hash** execution composite `14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d` (90 closure files, hash v2) · plan `b845b9c35d75` · spec `bcc1f0fcd49f`
**Gates cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1/R3/R5/R8/R9/R10) · tests PASS 132/0 · controller OK, all fingerprints at `14b13abb23e5`
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 4

The delta since `da3d3ab4ee9b` is **analysis-stage only**: `research/analysis/diagnostic_ops.py` (+243, the new `analysis.gate.arm_delta_integrity` STOP GATE) and `research_workflow/lifecycle_v2.py` (+8/-2, three machine-local context keys handed to `run_op`). No feature tracker, no outcome kernel, no session table, no stream/visibility declaration and no chronology changed; the study branch still changes **no** closure file against `main`. Every A/B/C/F/G/H conclusion from pass 01 therefore stands on an unchanged surface and is not re-derived. Reading was bounded to the two diffs plus four ranges needed to settle whether the new gate's rebuilt population is a real reconciliation or a self-derived scope.

## Prior findings adjudicated

| # | Finding | Status | Evidence |
|---|---|---|---|
| F2 | `rolling_5m_productivity.py:53` vs `generic_ohlcv_delta.py:57-61` — divergent session-reset conventions | NOT FIXED (carried, NOTE) | Neither file is in the 2-file closure delta; `rolling_5m_productivity.py` still hashes `666be87d…` (`compiled_plan.json:810`), unchanged from the prior manifest. Bound unchanged: `qualify` still requires `regime_1m.age_s >= 120s`. |
| G2 | `host_bindings.py:275-281,306` — derived 5m buckets published without source completeness | NOT FIXED (carried, NOTE) | `host_bindings.py` hashes `c6804676…` (`compiled_plan.json:807`), not in the delta; packet still routes `completed_5m` with `ready_gate: false`. |
| G2/C1 | `host/outcomes.py:246-285` — within-session tape gaps do not censor the flip label | NOT FIXED (carried, NOTE) | `outcomes.py` not in the delta; packet `outcome.max_gap_ns` still `null`, `session_end_censoring: true`, `horizon_end_rule: "strict"`. |

All three were NOTEs (disclosure / inherited platform semantics); none blocks, and none is re-framed here.

## Critical findings

None.

## Warnings

None.

## Notes

### [N4] `research/analysis/diagnostic_ops.py:825-833` — the population reconciliation fails **open** when the fit stage recorded no `final_fit_rows`

`recorded` is built from `m["final_fit_rows"] is not None`; the mismatch branch is `elif recorded and recorded != [...]`, so an empty `recorded` skips the check while `population_reconciled` is reported `False` in the payload. The gate's own docstring asserts it "RAISES when the count disagrees with the `final_fit_rows` the fit stage recorded" — that guarantee is conditional on the field existing. **Cannot arise for this study**: `lifecycle_v2.py:931` writes `final_fit_rows` for every trained arm/cell in schema_version 3, so `recorded` is always a 1-element set here (all arms in a cell fit the same `final_rows`, which is arm-independent — `lifecycle_v2.py:907`). Disclosure only; no failure path on this surface.

## Referred to contract-checker

- Whether the new gate's coverage matches the deliverable it vouches for (all four properties enforced for arms B/C/D in the single declared cell) and whether the fail-open branch above should be a hard requirement — gate/deliverable completeness.
- `population_parity_vs_parent` references a *parent* study artifact (`clean_maturity_flip_model_180s_horizon/artifacts/oos_candidates_merged.parquet`, sha `6c35c786…`, `expected_total: 450973`) — cross-study provenance and pin freshness.
- Carried from pass 01: `chronology.authorized_dates` (one date) vs `month_folds` spanning 2024-01…2024-12; `resolution_precedence` declaring `BARRIER_TOUCH` with `outcome.arms: []`.

## Evidence for the changed surface

- **The new gate cannot enter a feature path.** `analysis.gate.arm_delta_integrity` is registered in `OPS`/`OP_INPUTS` alongside the existing diagnostic ops (`diagnostic_ops.py:918,933`) and runs only as an `analyze` step. It returns `{"frame": rows, …}` — the *original* frame object; the `_year` column it needs is added on a copy (`frame = frame.assign(_year=…)`), so no synthetic column propagates to any downstream step or artifact. The module contract ("run AFTER collection on already-materialized frames … must never be used to build a feature") is unchanged.
- **The rebuilt population is a genuine reconciliation, not a derived scope.** The gate mirrors the fit stage operation-for-operation: binary-label rows (`diagnostic_ops.py:800` ≡ `lifecycle_v2.py:786`), the manifest's `tuning_years` (`:802` ≡ `:791`, which records `sorted(tuning)` at `:942` after falling back to `plan.chronology.train = [2024]` when `validation.tuning_years` is `[]` — so the manifest carries `[2024]`, not the empty list), then the cell subset (`:812-815` ≡ `_rows_for`, `lifecycle_v2.py:830-834`). The analyze frame `_train_frame_all_labels` (`:1008`) and the fit frame `_train_frame` (`:758`) are the same inner merge over the same `merged/` parquet with `MERGE_DUPLICATE_KEYS` asserted, so the counts are comparable by construction, and any divergence raises (`diagnostic_ops.py:830-833`). Set-filter order differs from the fit's; set intersection is order-independent.
- **`_year` uses one convention on both sides (F3/F4).** `pd.to_datetime(observation_ts, unit="ns", utc=True).dt.year` appears identically at `lifecycle_v2.py:764`, `:1019` and `diagnostic_ops.py:798`. UTC year cannot misassign an RTH row: RTH 08:30–15:15 CT is 14:30–21:15 UTC on the same calendar day in both DST states, so no year-boundary session crosses. No fixed-offset arithmetic and no naive timestamp is introduced.
- **No OOS door is opened.** The `analyze` step's frame selection is untouched by the diff; the OOS branch still goes through `assert_oos_open` (`lifecycle_v2.py:1149-1153`) and this study declares `analysis.source: "train"`. The three new context keys are path strings (`study_dir`, `artifacts_dir`, `model_root`) consumed only for manifest/model resolution (`diagnostic_ops.py:788-796`); they carry no data and no year authority. With no `models_manifest`/`study_id` param declared (`compiled_plan.json:53-60`), resolution goes to this study's own `artifacts/experiment_models.json`; an unresolvable study raises rather than defaulting.
- **The gate's own diagnostics are past-closed and in-sample by design.** `_block_population` computes non-null rate, `nunique` and `std(ddof=0)` over the fitted population purely to report on it — no statistic is fed back into any feature or scaler (B7 unaffected). The prediction-divergence check scores arm and baseline models on the *fitted* rows via `model_store.score`, which authenticates canonical bytes first; both are post-fit diagnostics of an already-materialized frame.
- **No forbidden idiom introduced.** The +243 lines contain no `center=True`, no `.shift(-N)`, no `bfill`/`backfill`, no `merge_asof`, no resample. The only coercion is `pd.to_numeric(errors="coerce")` on a diagnostic copy.
- **Contract unchanged where it matters.** Packet still declares `nq_1m` `visibility: strictly_before` / `same_ts: unavailable`, `nq_1s` `at_epoch`, `same_timestamp_rule: "context streams expose events with ts_init < T only"`, `outcome.kernel: flip` with `horizon_ns 180e9`, `inclusive_start: true`, `contract: "label"`, `arms: []`, `atr: null`; `chronology.train=[2024]`, `dev=[2025]`, `prohibited=[2021,2022,2023,2026]`; nine walk-forward folds each fitting three months strictly preceding a single validation month.

## Clean checks

A1, A2, A3, B1-B7, B9, B10, C1, C2, C3, F1, F3, F4, G1, G3, G4 clean — unchanged surface at pass 01 (verdict CLEAR) plus the delta evidence above; the two changed files touch no timestamp, feature, label or session code path.
A4 not applicable — still no `TimeEvent` timer/alert; the 5s grid cadence is driven by `nq_1s` bar events.
A5, G3 not applicable to the study path — no resampling; 1m/1s arrive as catalog streams (`NQ_1S_V2_GLOBEX`, digest `e577a361…`), 5m is aggregated from completed 1m bars in-runtime.
F2, G2 carry the pass-01 notes, re-adjudicated above.
H1-H4 not applicable — label contract, flip kernel, no bracket simulation, no fill semantics; the diff adds none.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "controlled_feature_family_180s", "auditor": "lookahead-auditor:008_causal_audit_6dd5120e", "audited_execution_composite_sha256": "14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d", "critical": 0, "warning": 0, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->

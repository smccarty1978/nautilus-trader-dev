# Look-Ahead & Timestamp Audit — Pass 02 (delta)
**Date** 2026-09-11 · **Scope** recomposed plan `3ff96583` / `compiled_plan.json`, `research_decision.yaml` (G7 route), `research_workflow/grammar/compiler.py`, `research_workflow/host/mux.py`, `research_workflow/host/strategy.py` · **Scope hash** `plan_sha256 3ff965835895b9b9...`, `execution_composite_sha256 61c3d45721c97a3f...` · **Lint** 0 critical / 0 warning (preflight CLEAR; readiness PASS) · **Verdict** BLOCKED (new CRITICAL)

`audit_type: causal`
`study: nq_mtf_regime_atlas_pilot2023`
`audited_execution_composite_sha256: 61c3d45721c97a3fd75990ce8e594a99e6da010e5bc096d3b3973176b9a8548d`
`auditor: lookahead-auditor (claude, pass 02)`

## Summary            Critical: 1 · Warning: 1 · Note: 1

## Prior findings adjudicated
| # | Finding (pass 01) | Status | Evidence |
|---|---|---|---|
| 1 | `[readiness-scope]` R2/R4 not present for this study (WARNING) | **OPEN, unchanged** | `readiness.json` for plan `3ff96583` still lists only R1_NQ/R3_session_table/R5_binding_proof/R8_host_boundary_lint/R9_closure_current/R10_zero_study_python. No R2/R4 artifact was added by the recomposition. |
| 2 | `[feature-surface]` registered-but-uncomposed context features self-disclosed (NOTE) | **Superseded** | Plan `3ff96583` carries `"features": null`, `columns.features: []` — the G3/G6 narrow-domain gap this note described no longer applies to a feature-free plan; the underlying completeness gaps (G3, G6) are unchanged and still contract-checker's. |

## Critical findings
### [B9/mux] `research_workflow/grammar/compiler.py:237,244,258-259` — stream-role resolution ignores the study's requested timeframe set; `nq_1m` is mis-tagged `context` and derived buckets point at a nonexistent `nq_1s` stream
**Failure path:** `_resolve_streams` computes `externals` (line 233) and `finest = min(externals, key=_tf_ns)` (line 237) from the **dataset's** declared external streams (`research/datasets/NQ_1S_V2_GLOBEX.yaml:50-64` declares `1s` and `1m` as external unconditionally), not from the study's requested `s.timeframes`. G7's documented fix ("declare no 1s stream, so 1m becomes the finest external stream and the EXECUTION stream" — `research_decision.yaml` line 364) never actually changes `finest`: `1s` is still in `externals` even though this study never requests it. Consequently:
- Line 244: `nq_1m`'s role is forced to `"context"` (`tf==finest` fails, `1m` is in `externals`) — `compiled_plan.json:836` confirms `"key": "nq_1m", "role": "context", "visibility": "strictly_before"` — the opposite of what `research_decision.yaml`'s G7 route declares was done.
- Lines 253-259: for `nq_3m..nq_4h`, the loop at 253-257 correctly finds `src="nq_1m"` (a valid multiple, already in `ctx.streams`), but line 259 **unconditionally overrides** it with `finest` ("nq_1s") because `finest in externals` is a dataset-level fact, independent of whether `nq_1s` was ever added to `ctx.streams`. `compiled_plan.json:845` (and the identical field on `nq_5m/nq_15m/nq_30m/nq_1h/nq_4h`) declares `"derived_from": "nq_1s"` — a stream key **absent** from the plan's own 7-entry `streams` array.
- At runtime, `HostCore.__init__` (`research_workflow/host/strategy.py:50`) builds `self.streams = list(self.plan["streams"])` then `self.mux = StreamMux(self.streams, self._deliver)`. `StreamMux.__init__` (`research_workflow/host/mux.py:130-134`) does, for every derived/complete_bucket stream, `src = self.streams[s.derived_from]` — `self.streams["nq_1s"]` raises `KeyError: 'nq_1s'` immediately, before a single bar is ingested. Zero rows, zero frame, total collection-stage failure — not merely an unvalidated assumption.
- Independent of the crash: even if the KeyError were bypassed, `self._aggregators` would be keyed under `"nq_1s"` (`mux.py:134` `self._aggregators.setdefault(src.key, ...)`), so `_apply()` on an actual `nq_1m` bar (`mux.py:174` `self._aggregators.get(bar.stream)` = `.get("nq_1m")`) would find **no** aggregator and never produce a single `nq_3m..nq_4h` bar — the derived-bucket mechanism this study's whole alignment-context design depends on is silently dead, not merely mis-timed.
- Separately, tagging `nq_1m` `context` while `population.cadence.stream` is `nq_1m` (`compiled_plan.json` population block) reproduces exactly the G7 defect the recomposition was meant to close: `assert_epoch_visibility` (`mux.py:186-192`) treats any non-`execution_streams` key `>= T` as `CONTEXT_STREAM_VISIBLE_AT_EPOCH`, and `nq_1m` is not in `self.execution_streams` (built from `role=="execution"` entries, which here are only the — non-functional — derived timeframes). The G7 fix ("declare no 1s stream") does not achieve its stated effect because `finest`/`externals` are dataset-scoped, not study-scoped.

**Smallest fix:** in `_resolve_streams`, restrict `externals` used for `finest` (role assignment, line 237) and for `derived_from` resolution (line 259) to the timeframes the study actually requests (`{tf for tf in s.timeframes if tf in externals}`), or equivalently gate line 259's override on `finest` having actually been added to `ctx.streams` this compile. This is a platform-level defect in `research_workflow/grammar/compiler.py` (inside the execution closure), not a study-declared choice — every study that requests a coarser-than-dataset-finest execution stream on a multi-granularity dataset is exposed to it, not just this pilot.

## Warnings
### [carried] R2/R4 not proven for this recomposed plan
Unchanged from pass 01 (see adjudication table). The same-instant `at_epoch`/`strictly_before` boundary this plan depends on for `nq_3m..nq_4h` is covered only by the generic `test_host_core.py`, and that boundary is now moot until the critical above is fixed — a study-scoped R2/R4 run against this actual plan would have caught the `KeyError` at readiness time rather than leaving it for first execution.

## Notes
### [pre-execution] The critical above is exactly what a smoke/collection run would hit next
`study.yaml` status is `phase: B ... continues in session one`; readiness/preflight are schema/static checks (R8 lints `research_workflow/host/*.py` source files generically — `lifecycle_v2.py:428-430` — it does not construct a `StreamMux` against this plan's data). No execution has occurred against plan `3ff96583` yet. Flagging this now is the intended purpose of a pre-execution causal audit (per prior-session memory: audit causal/matching logic before first execution) rather than letting it surface as a second smoke failure under a new name.

## Referred to contract-checker
- gap_inventory G0/G3/G4/G5/G6/G7 (multi-timeframe population fan-out, narrow/zero feature surface, missing VWAP/percentile/session features, missing grouped-descriptive/cluster-robust ops, unbound runtime adapters) — completeness/deliverable-producer gaps, self-disclosed in `research_decision.yaml`.
- `stage: collect` frame-seal / lifecycle state (no STUDY_CLOSED, contract audit `NOT_REQUIRED`) — unchanged from pass 01.

## Clean checks (conditional on the critical above being fixed; logic itself is sound)
- **A (tracker state at T):** `features/trackers/regime_dual_ema.py` and `host_bindings.py` unchanged from pass 01 (identical closure hashes) — `flipped`/`bars_in_regime`/excursion fields still computed only from the completed bar passed to `on_bar`, never from a later one. Question (3) clean.
- **A (same-bar ordering within `_deliver`):** `strategy.py:209-213` routes `tracker.on_bar` for the anchor stream **before** `if bar.stream == self.epoch_stream: self._epochs(bar)` — the design correctly updates `regime_1m`/`excursion_1m` from a bar before emitting the candidate for that same bar (question 1's intended semantics are sound; execution is blocked by the critical, not by this ordering).
- **F (bucket completeness/ordering logic itself):** `mux.py:83-113` `_complete()`/`on_source_bar()` and the larger-bucket-first publish sort (`mux.py:174-182`) are unchanged from pass 01's clean check and remain causally correct *as algorithms* — the defect is in wiring (`derived_from` target), not in the aggregation logic itself. Question (2)'s ordering guarantee is sound; its wiring is not.
- **G (TRADING_DAY censoring, warmup):** `target_runtime.py` and `chronology.warmup` unchanged from pass 01 (`candidate_emission:false, target_generation:false`, `CHRONOLOGY_ROLE_TABLE: PASSED`). Questions (4)'s censoring semantics and (5) remain clean.
- **F (session-table causality, question 6):** `session_table.in_session(T)` (`strategy.py:274`) is a pure timestamp-membership check against the committed calendar reference table; it does not depend on which raw streams are ingested (1s vs 1m), so the loss of the 1s stream has no causal effect on session-table evaluation itself — only on the derived-timeframe wiring above.
- **H, C1-C3:** no change to outcome/label construction from pass 01; `FORWARD_OUTCOME_GUARD: PASSED`, `leaked_outcome_columns: []` still hold for plan `3ff96583`.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "61c3d45721c97a3fd75990ce8e594a99e6da010e5bc096d3b3973176b9a8548d", "auditor": "claude-lookahead-auditor-pass02", "critical": 1, "note": 1, "study": "nq_mtf_regime_atlas_pilot2023", "verdict": "BLOCKED", "warning": 1}
<!-- AUDIT_SUMMARY_V2_END -->

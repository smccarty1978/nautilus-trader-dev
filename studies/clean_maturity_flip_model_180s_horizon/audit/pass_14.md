# Look-Ahead & Timestamp Audit — Pass 14

**Date** 2026-08-29 ·
**Scope** `research_workflow/target_runtime.py` (`FlipTargetRuntime`, `resolve_target_runtime`,
`TargetRuntime.from_disposition`); `research_workflow/generic_collector.py` target dispatch
(`__init__` 415-431, `_track_pending` 647-725, `_emit_observation` 744-786,
`_sweep_elapsed_horizons` legacy branch, `_on_regime_flip` 1015-1050, `_evaluate_checkpoint`
`target_frozen_atr`); `research_workflow/target_expression.py` (disposition constants);
`features/trackers/structural_regime_geometry.py` (`prior_1m`/`prior_5m` split);
`backtests/nt_runtime/modes/collect.py:244-324` (config binding); study contract mirrors
(`compiled_study.json`, `config/target_contract.json`, `SPEC.md`, `tests/`). ·
**Scope hash (frozen execution composite)** `bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e` ·
**Lint** 0 critical / 0 warning (`audit/preflight.json` CAUSAL_LINT PASSED, re-run 2026-08-29T06:16:52Z) ·
**Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 2

## Composite freshness
Declared composite `bd2e9cf1…4203e0e` is byte-identical across
`audit/frozen_execution_manifest.json` (`frozen_execution_composite_sha256`),
`audit/preflight.json` (`execution_composite_sha256`, `status: CLEAR`, all 8 gates PASSED
incl. `EXECUTION_MANIFEST` which re-derives via `scripts/resolve_execution_manifest.py`),
`audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`),
`audit/pass_13.md`, and `FRAMEWORK_RECONCILIATION_2026-08-29.md`. Preflight was regenerated
today. `Bash` is disabled this session, so `resolve_execution_manifest.py` was not re-run
by hand; its output is the input to the `EXECUTION_MANIFEST` gate, which passed at this
composite today. Not stale.

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| pass_12 (composite `85efdcc4…`, **STALE** — pre-reconcile TRAIN-freeze stage) NOTE: `_partition` is sole TRAIN/not-TRAIN boundary at final-freeze; correctness assumes upstream partition labeling | CARRIED (still valid, unchanged) | `implementation/final_train_freeze.py` untouched by reconcile; three-layer `_partition` check intact. TRAIN-stage, not collection-stage; not re-raised here. |
| pass_12 "Referred to contract-checker" (parent SPEC.md drift, `model_family_resolution` joblib claim, `model.params` `random_state` landmine, optional `pre_fit` gate) | CONTRACT SCOPE | Re-referred below; `model_selection.json` `random_state` drift already corrected per reconcile §2d. |
| pass_13 (library `research_workflow.causal_audit`, current composite) — CLEAR 0/0/0 | NOTHING TO ADJUDICATE | 8/8 checks passed incl. `legacy_runtime_excluded`, `composite_target_label_only`, `real_output_parity`, `causal_lint`. |

## Analysis — does the new flip-target path preserve causality?

**The new `FlipTargetRuntime` pending/terminal machinery is not on this study's live path.**
`config.target_contract.primitive == "flip_within_horizon"` and the target is neither
`composite` nor `ordered_barrier`, so `resolve_target_runtime` returns a bare
`FlipTargetRuntime` but `_track_pending` (gc:658-725), `_sweep_elapsed_horizons`
(gc:1090-1100 dispatch) and `_on_regime_flip` (gc:1015-1035) all fall through the
`composite`/`ordered_barrier` guards to the **unchanged legacy inline path**.
`FlipTargetRuntime.open_pending` / `_terminal_pending` / `ingest_bar` / `ingest_flip` are
never invoked. Verified by reading current `generic_collector.py`, not the diff alone.

The only new code executed for every observation is `_emit_observation` →
`runtime.from_disposition(disposition, resolved_at_ts=…, censor_reason=…)`
(`target_runtime.py:45-49`). Traced field-by-field against the pre-reconcile inline dict:

| observation field | old inline | new via `from_disposition` | equal? |
|---|---|---|---|
| `target_flip_within_horizon` | `1 / 0 / None` on `DISPOSITION_*` | `TargetResult.label` (`LABELED_POSITIVE`→1, `LABELED_NEGATIVE`→0, else None) | yes |
| `disposition` | `disposition` | `target_result.disposition` (pass-through) | yes |
| `censored` | `int(== DISPOSITION_CENSORED)` | `int(target_result.disposition == "CENSORED")` | yes |
| `censor_reason` | `censor_reason` | retained on non-labeled branch; `None` on POS/NEG (already `None`) | yes |
| `resolved_at_ts` | `censored_at_ts if flip_ts is None else flip_ts` | same value passed into `from_disposition` | yes |

`DISPOSITION_POSITIVE = "LABELED_POSITIVE"` matches the `{POSITIVE, "LABELED_POSITIVE"}`
set in `from_disposition`. This is a behaviour-preserving refactor for this study.

**Horizon 300→180.** Flows solely through `spec.target.horizon_seconds`
(`collect.py:268`) → `cfg.horizon_seconds` → `horizon_end_ts = T + int(cfg.horizon_seconds)*NS`
(`gc:715,722`). Window boundary in `_on_regime_flip`: `cand_ts <= flip_ts <= horizon_end_ts`;
`_sweep_elapsed_horizons` holds a candidate whose `horizon_end == now_ts` for one extra 1s
tick (`horizon_end == now_ts and not final`) so a coincident minute-boundary 1m flip stays
visible (pass_01 rule, intact). `session_close_ts = session_close_ns(T, "RTH")` — pure
function of T. `_is_censored_by_session`: censor iff `horizon_end_ts > session_close_ts`
(gc:968-981). No forward information in any boundary computation.

**Confirmation (1 completed 1m bar).** The flip event is `new_regime = regime_engine.update(h,l,c)`
inside `_handle_1m_bar` on the completed 1m bar, `flip_ts = bar.ts_init` (close time, A1/A2).
Checkpoint T is evaluated from the 1s bar whose `ts_init == T`, dispatched **before** the 1m
bar closing at the same T (1s-before-1m, MEMORY / RESEARCH_WORKFLOW §17), so the candidate's
prevailing regime and feature snapshot never see the forming 1m bar. Confirmation semantics
unchanged.

**Tape-gap / session-end censoring.** `on_stop` (gc:983+) censors every still-pending
candidate (`SESSION_END` if horizon spilled past close, else `DATA_END`) — no silent drop,
no silent label. Legacy flip path has no separate intra-horizon 1s-gap censor, but 1m flip
detection does not depend on the 1s tape and RTH intraday gaps are covered by preflight
`CAUSAL_INVARIANTS` + readiness G-series; unchanged from pass_12/13.

**1m/5m feature split (`4e46c0b3…`→`38c0201f…`).** `StructuralRegimeGeometryTracker.snapshot`
has always emitted `prior_1m_regime_*` from `self._completed("prior_1m_regime", self._prior_one)`
(line 147) and `prior_5m_regime_*` from `self._completed("prior_5m_regime", self._prior_five)`
(line 166) as six distinct keys. `_prior_one` is frozen at `on_1m_flip` from the previous
regime's last completed close; `_prior_five` from completed 5m bars only, with snapshot
guards `NO_COMPLETED_PRIOR_*_REGIME` and `FORMING_OR_MISSING_5M_STATE`
(`five_provenance_close_ts > checkpoint_ns`). The repair changes only which alias the
compiled contract binds; the runtime reads no forming bar on either timeframe. readiness
R2-derived-5m (275 completed 5m from 1380 1m parents, no external stream) and R4 (213,431
callbacks, no inversion) confirm on real samples. The old collapsed-alias collection is a
train/serve identity issue → contract-checker.

**Repeat offenders.**
- `_T_*` / accumulated fields: `target_frozen_atr` (`= regime_engine.atr` at T, completed-bar
  Wilder ATR) is written to `cand_record` but excluded from the persisted surface by
  `_append_candidate`'s keep-set and used only by the dormant `ordered_barrier`/`composite`
  paths. `running_mfe_atr` / `new_progress_windows` / `retained_mfe_ratio` are unchanged
  metadata, updated strictly ≤T in `_handle_1s_bar` before checkpoint eval.
- Running vs eventual extremum: `highest_high_since_flip` / `lowest_low_since_flip` feed
  qualification-time metadata only, not a model feature; the 13-feature surface is
  `prior_{1m,5m}_regime_*` (frozen completed regimes), `rolling_300s_*` (trailing 300s
  window — past), `arrival_velocity/acceleration`, `ema_slope` (completed-1m EMA history).
  No eventual-extremum column.
- Cross-event elapsed: `time_to_flip_seconds` is label-only (`observations.parquet`);
  `regime_age_seconds` = `T - regime_start_ns`, both known at T.
- Forward-outcome columns: none in the feature surface (readiness R10 emitted-feature list
  = the 13 declared, `unexpected_columns: []`).

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] Live flip path and dormant `FlipTargetRuntime` disagree on the T boundary
The legacy path counts a flip at `flip_ts == cand_ts` (exactly T) as POSITIVE
(`cand_ts <= flip_ts`, gc:1032); `FlipTargetRuntime._terminal_pending` uses strict
`start < ts` (`target_runtime.py:142`). Only the legacy path runs for this study, so
collection is unaffected and identical to pass_12. If this study ever migrates to the
`composite` runtime or the flip runtime is wired onto the bare-flip path, a ~1-in-12
(minute-aligned) candidate class would flip label. Flagged for the pre-TRAIN
target-replay parity gate to pin the boundary convention explicitly.

### [NOTE] Shorter horizon reduces session-end censoring
`horizon_end_ts > session_close_ts` is true less often at 180s than 300s, so more
near-close candidates now receive a real label rather than `SESSION_END`. Expected and
correct; the researcher should expect a modest population shift near RTH close versus the
300s parent when comparing base rates.

## Referred to contract-checker
- Parameterized-feature identity repair (`prior_1m_*` vs `prior_5m_*`, `feature_list_sha256`
  `38c0201f…`) — train/serve completeness vs. the collapsed parent collection.
- Carried pass_11/12 referrals: parent SPEC.md drift, `model_family_resolution` joblib
  claim, dormant `model.params` `random_state`, optional `pre_fit` gate adoption.
- Stale downstream TRAIN artifacts left on disk (reconcile §5) must be regenerated, not
  reused, at stages 10–13.

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4, H1–H4 clean (H not exercised — flip target, no
bracket sim on this path).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "clean_maturity_flip_model_180s_horizon", "audited_execution_composite_sha256": "bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e"}
<!-- AUDIT_SUMMARY_V2_END -->

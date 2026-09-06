# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-09-06 · **Study** `controlled_feature_family_180s` · **Auditor** `lookahead-auditor:001_causal_audit_2e1d03e5`
**Scope** compiled semantic contract `_work/controller/audit_packet_causal.json` (packet_version 2, sha256 `09cce894c5e9…`) + 5 targeted source reads
**Scope hash** execution composite `da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540` (90 closure files, hash v2) · plan `a1552a5b7ebe` · spec `e483ea7a53e9`
**Gates cited, not re-derived** preflight CLEAR (8/8, `leaked_outcome_columns=[]`) · readiness PASS (R1/R3/R5/R8/R9/R10) · tests PASS 116/0 · controller OK @ same composite
**Verdict** CLEAR

## Summary

Critical: 0 · Warning: 0 · Note: 3

Pass 01; no prior findings to adjudicate. The study branch changes **no** closure file against `main`, so the executable surface is main's audited platform composed by a declarative contract. Reading was bounded to the packet plus five source ranges where the packet could not settle a claim (write sites for the running-excursion gate, the trend normalization, the rolling-window cutoff, the 5m bucket publication rule, and the flip-label resolution path).

## Critical findings

None.

## Warnings

None.

## Notes

### [F2] `features/trackers/rolling_5m_productivity.py:53` vs `features/trackers/generic_ohlcv_delta.py:57-61` — the two feature families use different session-reset conventions

The rolling-productivity family (`rolling_{60,120,300}s_*`, shared by every arm and extended by arm `D_PLUS_SHORT_PRODUCTIVITY`) is a plain time-trimmed deque with **no** session reset: at an early-RTH checkpoint its trailing window reaches back across the open into ETH. The OHLCV/delta family (arms `B_PLUS_VOLUME`, `C_PLUS_DELTA`) delegates to `OHLCVDeltaTracker`, whose documented semantics include an **RTH reset** (`reset_rth` / `end_rth`, `generic_ohlcv_delta.py:57-61`). At the same T the two blocks therefore see different effective histories. This is not look-ahead in either direction — both read only completed past bars — and the exposure is bounded: `population.qualify` needs `regime_1m.age_s >= 120s`, so the earliest checkpoint is ~08:32 CT and only checkpoints inside the first 300s of RTH (~3 of 405 session minutes, <1% of rows) can diverge. Disclosed rather than blocked because it cannot change an arm ranking at that share.

### [G2] `features/trackers/host_bindings.py:275-281,306` — derived 5m buckets are published without requiring source completeness

`CalendarRegimeBarBinding` publishes a 5m regime bar at every 1m bar whose `ts_init` is a multiple of the bucket, "whatever source bars printed"; its docstring states no completeness is required, and the packet routes `completed_5m` with `ready_gate: false`. The causally relevant half of the declared invariant *derived buckets complete-only* holds — nothing is published between boundaries, `close_ts == available_ts == bar.ts_init`, and the direction carried is `dir_pre_bar_or_current`, i.e. the regime **before** the closing bar is applied — so `prior_5m_regime_*` cannot read a partial bucket. What is not enforced is that all five 1m bars printed: where the 1m tape has a hole, `prior_5m_regime_range_atr` / `_mfe_atr` / `_efficiency` are computed from an under-filled bucket and understate range. Inherited platform semantics, preserved by name; negligible on RTH NQ 1m.

### [G2/C1] `research_workflow/host/outcomes.py:246-285` — within-session tape gaps do not censor the flip label

`outcome.max_gap_ns` is `null`, and the executing flip branch resolves a pending candidate on flip events plus `session_close` only. `SESSION_END` censoring is the operative boundary rule: a candidate whose 180s horizon crosses the RTH close is censored (`outcomes.py:277-278`), consistent with `horizon_end_rule: strict`. A within-session data hole spanning the horizon would therefore yield `label=0` (flip unobserved) rather than a censor. Direction of error is conservative and population-uniform; `GAP` and `BARRIER_TOUCH` in `resolution_precedence` are inert for a flip label with no barrier arms.

## Referred to contract-checker

- `chronology.authorized_dates` holds one date (`2024-03-01`) while `model.validation.month_folds` span 2024-01…2024-12 — authorization coverage vs. declared folds.
- `outcome.resolution_precedence` declares `BARRIER_TOUCH` though `outcome.arms` is empty and `outcome.atr` is null — spec hygiene / completeness.

## Evidence for the non-obvious clean results

- **Running-vs-eventual extremum, armed (`host_bindings.py:212-266`).** `excursion.mfe_atr`, `retained_ratio` and `progress_windows` are properties over state accumulated in `on_bar` from completed 1s bars and reset wholesale on the `regime_1m:changed` event — no finalize-time write site, so the `_T_*` accumulated-field trap does not apply. `mfe_atr >= 1.0`, `progress_windows >= 2` and `retained_ratio >= 0.5` appear only in `population.qualify`, i.e. as the arming condition the running-extremum rule requires, evaluated at T. `frozen_atr` is the ATR at the regime-start bar (`host_bindings.py:155,218`), past-known.
- **Trend normalization is a sign, not a statistic (`generic_ohlcv_delta.py:76-103`).** `trend_normalized_est_delta_sum_*` multiplies the window sum by `prevailing_direction`, sourced from `regime_1m.dir` (packet `features.snapshot.episode_state`) on a `strictly_before`-visible context stream. The label direction is the *opposite* of that same prevailing direction, so no post-flip quantity enters the feature. No z-score or scaler over the full dataset anywhere in the surface (B7).
- **Rolling windows are strictly trailing and anchored on the checkpoint (`rolling_5m_productivity.py:53,76-81`).** The snapshot refuses unless `self._bars[-1].close_ts == checkpoint_ns`, then filters `anchor_ts <= close_ts <= checkpoint_ns` with `anchor_ts = checkpoint_ns - window_ns`. `max_progress` is the maximum over that past window only; `giveback = max - current`, `retention = current / max` (lines 109-110) are past-only transforms of it.
- **No 1s-before-1m partial-bar read.** `nq_1m` is declared `visibility: strictly_before` with `same_ts: unavailable`, so `ema_slope` and every `prior_1m_regime_*` feature see only 1m bars with `ts_init < T`; the 1s execution stream is `at_epoch`, which admits exactly the 1s bar closing at T. `regime_1m` consumes 1s bars only as `reference` for `last_reference_close` (`host_bindings.py:132-134`), which feeds `prior_end_close` in the changed payload, not a declared feature.
- **Label alignment (`outcomes.py:242-248,266-282`).** The pending window is opened at the same T the features are snapped, `flip_end = T + 180_000_000_000`, and `inclusive_start: true` is honored (`started = p.T <= flip_ts`). Admitting a flip stamped exactly at T is legal here precisely because the 1m context is `strictly_before`-visible, so such a flip is invisible to the features. The composite/declarative `FlipTargetRuntime._terminal_pending` (`target_runtime.py:186`, exclusive start) is not the path for this contract — `composition` is null and `arms` is empty, selecting the `kernel == "flip"` branch above.
- **Temporal splits.** All nine walk-forward folds fit on three months strictly preceding their single validation month; dev/OOS 2025 is disjoint from and later than train 2024; 2021-2023 and 2026 prohibited. No random split anywhere in `model.validation`.
- **No forbidden pandas idiom.** Repo-wide grep over `features/`, `research_workflow/`, `research/` for `center=True`, `.shift(-`, `bfill`/`backfill`, `merge_asof`: zero code hits (one prose comment in `research/analysis/loader.py:176`).

## Clean checks

A1, A2, A3, B1-B7, B9, B10, C1, C2, C3, F1, F3, F4, G1, G4 clean.
A4 not applicable — no `TimeEvent` timer or alert callback; the 5s grid cadence is driven by `nq_1s` bar events (`population.cadence.stream`), so it cannot fire ahead of the bar.
A5, G3 not applicable to the study path — no resampling occurs here; 1m/1s arrive as catalog streams (`NQ_1S_V2_GLOBEX`, digest `e577a361…`, R1/R3 pass) and 5m is aggregated from completed 1m bars inside the runtime, never loaded as an independent stream.
F2, G2 carry the notes above.
H1-H4 not applicable — `outcome.contract: "label"` with `kernel: "flip"`, `arms: []`, `atr: null`; there is no offline bracket simulation, no SL/PT price resolution and no fill semantics in the label path (declared invariant *label contract has no fill semantics*). The declared `entry_reference: "next_bar_open"` is the correct convention and is unused by the flip kernel.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "controlled_feature_family_180s", "auditor": "lookahead-auditor:001_causal_audit_2e1d03e5", "audited_execution_composite_sha256": "da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 05 (delta)
**Date** 2026-09-15 · **Scope** delta since pass 04: main `d83be2fd` (chore/bucketing_and_gate A1–A7) merged into the study branch at `797d8b16`, study recompiled · **Scope hash** `plan_sha256 10209696eb4e898fe25d47eb1467bece1ddde7cae653edf466b70fab81a6f08a` (was `ed2b9dfa…`), `execution_composite_sha256 4e28ee0a8adf712acc52373811af61c4fd6bc2806c97b2b4894c7e458f84ac03` (was `041379f7…`, 159 files) · **Lint/gates** `audit/preflight.json` CLEAR, `leaked_outcome_columns: []`; `audit/readiness.json` PASS (R1 R3 R5 R8 R9 R10); both carry plan `10209696…` and composite `4e28ee0a…`; tests stage 158 passed / 0 failed at `4e28ee0a…` · **Verdict** CLEAR

`audit_type: causal`
`study: nq_mtf_regime_atlas_pilot2023`
`audited_execution_composite_sha256: 4e28ee0a8adf712acc52373811af61c4fd6bc2806c97b2b4894c7e458f84ac03`
`auditor: claude-delta-pass05-inline`

## Summary            Critical: 0 · Warning: 4 · Note: 2

## The delta, exactly (compiled_plan.json old `ed2b9dfa` vs new `10209696`)
| surface | change |
|---|---|
| `streams[]` | `nq_5s`, `nq_30s`: `aggregation complete_bucket → closed_window`, `empty_window → zero_volume_in_trading_day`, source unchanged (`nq_1s`). `nq_3m/5m/15m/30m/1h/4h`: same, **and `derived_from nq_1s → nq_1m`**. Roles and `visibility` unchanged on every stream. |
| `trackers[]` | the nine `regime_*` dual-EMA trackers: `epoch_fields [age_s] → [age_s, seconds_since_update]`. Nothing else. |
| `columns.metadata` | +9: `regime_<tf>_seconds_since_update` (ref `regime_<tf>.seconds_since_update`). None removed. |
| `outcome` | `observed_seconds: true`; `observation_columns` + `observed_seconds`. `session_end_rule truncate` unchanged. |
| `availability.rows` | 32 → 32. |
| `notes` | +6 (the `nq_1m` re-point). `registry_sha256` `8cd68dde…` → `888bda09…`. |
| closure files changed | `research_workflow/host/mux.py`, `host/outcomes.py`, `host/strategy.py`, `grammar/compiler.py`, `sessions.py`, `governed_controller_v2.py`, `features/trackers/host_bindings.py`, `research/analysis/ops.py`. |

## Prior findings adjudicated
| # | Finding (pass 04) | Status | Evidence |
|---|---|---|---|
| 1 | six gate artifacts bound to a superseded plan hash (WARNING) | **RESOLVED** | controller regenerated prepare/readiness/preflight on its own after the recompile; frozen manifest, readiness and preflight all carry `10209696…`; no file was deleted by hand. Seal and smoke are regenerated after this pass. (The composite also changed here, so this recompile does not isolate plan-only staling — see N2.) |
| 2 | R2/R4 not proven on real bars (WARNING) | **OPEN, carried** | unchanged; smoke/collection are the proof. |
| 3 | `compiler.py` hardcoded `same_timestamp_rule` text (WARNING) | **OPEN, carried** | packet still reads "context streams expose events with ts_init < T only" while `nq_1m` is a context stream declared `at_epoch`; the enforcement is the plan field, the prose is stale. |
| 4 | `bar_volume` 1s vs 1m-cadence scale (WARNING) | **OPEN, carried** | untouched by this delta. |

## Critical findings
None.

## Warnings

### [W-new/governance] This pass is not independent of the code it clears
The delta's runtime surface (A1 aggregation, A2 staleness field, A5 observed_seconds) was implemented in the same
agent lineage that writes this pass. The checks below cite code and the plan directly and each is re-derivable,
but an independent pass on `mux.py` `ClosedWindowAggregator` / `StreamMux._apply` is recommended before the
six-year atlas seals on this composition.

### [carried] R2/R4 real-bar proof · [carried] hardcoded same-timestamp prose · [carried] `bar_volume` scale
As pass 04.

## Notes

### [N1] Zero-volume fill changes feature VALUES, not causality
An empty window inside a trading day is now a bar with O=H=L=C = previous close and volume 0
(`mux.py:190`). Dual-EMA and Wilder ATR on 3m–4h (and 5s/30s) consume those bars: a quiet stretch lowers ATR
and holds the EMAs. Owner decision D3a/D3b (bucketing card), not a leak. Its extent is measurable per run as
`stats.empty_windows_published`.

### [N2] A3 is not isolated by this recompile
Both plan and composite changed, so every gate was stale on composite alone. Plan-only staling is proven by
`research_workflow/tests/test_bucketing_and_gate.py::test_a3_plan_only_change_stales_every_plan_bound_gate_and_nothing_closure_bound`,
not by this study's history.

## Clean checks
- **Closed-window publication never includes a bar after the close, never publishes before every possible member arrived.**
  A window keyed `ts_event // bucket` publishes (a) on the source bar with `ts_init >= close_ts` (`mux.py:217`)
  or when a later-bucket source bar opens (`mux.py:198-216`); or (b) by sweep (`mux.py:222`) when an applied bar
  has `ts_init > close_ts`, or `== close_ts` only when `inclusive` (`mux.py:359`): the applied stream's
  same-instant rank is after the source's (execution before context; finer context before coarser), so every
  source bar with `ts_init <= close_ts` has already been applied. Sweeps run only for non-derived streams
  (`mux.py:355`) and never for the source itself (`:357`). Derived `ts_event = open`, `ts_init = close`.
- **Epoch visibility unchanged in kind.** Every derived stream is still `at_epoch`; at a 1m cadence epoch `T`
  (the `nq_1m` bar) windows closing `<= T` are published before that bar is delivered, windows closing `> T`
  cannot be (their members have not arrived), and `assert_epoch_visibility` still enforces
  `visible_through <= T` at every epoch.
- **The zero-volume bar reads no future.** Its price is `_last_close`, the close of the latest window already
  published (`mux.py:179-196`); whether a window overlaps a trading day is read from the dataset's committed
  `sessions` table (`TRADING_DAY` rows, reference digest `e577a361…`) — calendar, not price.
- **`derived_from nq_1s → nq_1m` adds no visibility.** `nq_1m` is the cadence stream already cleared `at_epoch`
  (pass 03/04, single scoped override site); a window built from `nq_1m` bars closing `<= T` contains only bars
  that were visible at `T`. OHLCV equals the 1s-built window (1m is built from 1s with the any-member rule,
  `artifacts/platform_v2_do_soon/dataset_v2/equivalence_NQ.json`).
- **`seconds_since_update` is causal.** `epoch.T - last_bar_close_ts` (`host_bindings.py:135-146`), where
  `last_bar_close_ts` is the `ts_init` of a bar already delivered, `<= T`. Past 8 days it raises
  `TRACKER_STALENESS_IMPOSSIBLE` — a run failure, not a value.
- **`observed_seconds` is an observation column only.** Written in the outcome kernel's row
  (`outcomes.py:544`, `resolved_at_ts - T`), listed in `outcome.observation_columns`, absent from candidate
  columns; preflight `leaked_outcome_columns: []` at `10209696…`.
- **Other closure files.** `governed_controller_v2.py` (gate freshness only), `research/analysis/ops.py`
  (analysis condition vocabulary; not on the collection path), `sessions.py` (TRADING_DAY rows attached as
  `table.trading_day`; the gate/censor tables are built exactly as before), `strategy.py` (`tracker_id` stamp,
  `empty_windows_published` stat, mux calendar hand-off), `compiler.py` (the plan delta above).
- **Chronology unchanged.** `train [2023]`, `prohibited [2026]`, warmup 5 days, no candidate emission or target generation in warmup.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "audited_execution_composite_sha256": "4e28ee0a8adf712acc52373811af61c4fd6bc2806c97b2b4894c7e458f84ac03", "auditor": "claude-delta-pass05-inline", "critical": 0, "note": 2, "study": "nq_mtf_regime_atlas_pilot2023", "verdict": "CLEAR", "warning": 4}
<!-- AUDIT_SUMMARY_V2_END -->

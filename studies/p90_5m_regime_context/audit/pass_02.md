# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-12
**Scope:** `implementation/{regime_5m.py,classify.py,lineage.py,analysis.py,validate.py}`, `run_study.py`, `tests/test_regime_5m_parity.py`, `results/{validation_report.json,summary.json}`, `_work/regime_5m_build.json`, `SPEC.md` §2–§5 (completion audit — actual code and outputs, not SPEC text alone).
**Scope hash:** `fde67e4060cb53037316120e40886d67408d2928390bbed2a54f6c162fa04ca6`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (10 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C2 (CRITICAL) — SPEC §5 decision-timestamp ambiguity | FIXED | `classify.py::classify_core` groups every row by `with_5m_at_p90`/`against_5m_at_p90`/`uninit_at_p90` only (`classify.py:80-90`); `with_5m_at_confirm` is a separate nullable column, not the group key. `analysis.py::build_base` derives `group` solely from the three at-P90 booleans (`analysis.py:40-43`), and every phase function (1,2,3,4,6,7,9,10,11) consumes only `base["group"]`. Phase 5 (`phase5_transition_matrix`, `analysis.py:180-223`) is the sole consumer of `with_5m_at_confirm`, restricted to `walk_a_confirm_reached_censored & with_5m_at_confirm.is_not_null()` (4,656 rows) — confirmed by `V9_transition_matrix_reconciles` gate passing (`validation_report.json`, `n=4656`). |
| C1 (WARNING) — Phase 6 isolation not structurally enforced | FIXED | `regime_5m.py:164-188` renames both forward-looking methods to `lookahead_next_change_after`/`lookahead_next_change_into_direction_after`. `validate.py:85-101` (`V11_lookahead_single_call_site`) source-scans `implementation/*.py` via regex for `.lookahead_next_change_into_direction_after(` and asserts exactly one call site restricted to `classify.py`. Live result: `validation_report.json` V11 `pass: true`, `sites=['classify.py:110']` — the one call inside `phase6_future_flip_labels`. Independently grepped: no other call site exists anywhere under `studies/p90_5m_regime_context/` outside `classify.py` and the test file. |
| F1/A1 (WARNING) — runtime cross-check compared against wrong checkpoint offset | FIXED | `regime_5m.py:238-243` (`_runtime_cross_check`) now filters `v2_feature_snapshots_<year>.parquet` to `checkpoint_s == 0` before comparing, with an inline comment citing this exact pass-1 finding. Re-run confirmed: `_work/regime_5m_build.json` reports `agreement_rate_overall: 0.99914` (67,550 rows compared, per-year 0.998–0.99993) — up from the pre-fix 79.5% cited in the SPEC's own adjudication note, consistent with the fix actually taking effect rather than being fixed in prose only. |
| hygiene note — unused `lookahead_next_change_after` sibling on `Regime5m` | Acknowledged, unchanged | Confirmed still present and still unused by any `implementation/*.py` call site (only referenced from `tests/test_regime_5m_parity.py`). No new risk introduced. |
| G-adjacent note — Phase 6 future-flip can resolve into calendar 2026 | Acknowledged, unchanged | Spot-checked directly: `max(walk_a_confirm_ns)` across all 8,950 arms = 2025-12-30 20:29 UTC and `max(arm_top10_ns)` = 2025-12-30 20:27:30 UTC — neither the P90 query timestamp nor the confirm-timestamp query used by `classify_core` ever crosses into 2026. `V8_2026_sealed` gate passes (`validation_report.json`, `observed: 2025`). Phase 6's *label-only* future-flip result can still land in 2026 per the accepted convention; disclosed, not gated, unchanged from pass 1. |
| Referred-to-contract-checker item (Phase 6 manifest prefix wording) | Resolved by contract-checker (W2, `contract_pass_01.md`) | Out of this agent's scope; not re-litigated. |

No prior finding required re-raising; none were insufficiently fixed.

## New findings this pass

None. (Cap: 3 new CRITICALs permitted — 0 used.)

## Verification performed beyond adjudication

- **`state_at`/causal boundary**: `Regime5m._idx_at` uses `searchsorted(close_ts, t, side="right") - 1`, giving the last flip with `close_ts <= t`; `tests/test_regime_5m_parity.py::test_lookup_never_reads_an_incomplete_bucket` proves state is visible exactly at `close_ts` and invisible one nanosecond earlier, against a real slice of the canonical store. Confirmed the parity suite actually ran (not just claimed): `audit/logs/run_1786571967.log` shows `8 passed in 2.32s`, and `run_study.py::_run_parity_tests` invokes it as a real subprocess gate that raises before any classification runs on nonzero exit — matches SPEC §9 condition 4's ordering requirement.
- **`with_5m_at_confirm` computation**: `classify_core` computes `state_at(walk_a_confirm_ns)` unconditionally for all 8,950 arms, then masks to `null` for the 4,294 non-confirming arms via `pl.when(conf_mask).then(...).otherwise(None)` (`classify.py:87-89`). Verified directly against the source parquet that `walk_a_confirm_ns` is never null and never precedes `arm_top10_ns` for any of the 8,950 arms (`0` violations), so the unconditional lookup is a real, causally-ordered timestamp even for the rows whose result is subsequently discarded — no risk of a garbage/sentinel timestamp reaching `state_at`.
- **Grouping-variable consistency**: read every phase function in `analysis.py` (1,2,3,4,6,7,8,9,10,11) — all consume `base["group"]` (at-P90 only) except Phase 5 (`with_5m_at_confirm`, restricted to confirming trades per the fixed contract) and Phase 8's alternate `group_at_flip` classification, which is an explicitly separate, independently-causal lookup at the 5s-flip timestamp (SPEC's own "repeated using 5m state at P90 instead of at the flip" design), not a violation of the single-grouping rule.
- **`lineage.py`**: confirmed it performs no simulation — `reconcile()` only aggregates/quantiles columns already present on the loaded parquet (`terminal_label_full`, `entry_year`, `side`, `walk_a_confirm_reached_censored`, `walk_a_mae_to_confirm_atr`) and diffs against frozen reference constants; no `state_at`/regime computation of any kind.
- **V7 label-only leak scan**: `run_study.py:130-138` builds `non_phase6_frames` covering all 15 non-Phase-6 output tables (including `primary_table`, `matched_stratified_control`); `V7` gate passed with an empty leak dict in the live run.
- **Gate results are from a real run, not stubbed**: `validation_report.json` shows 11/11 gates passing with concrete `observed` values (e.g., `V9` observed `4656`, `V8` observed `2025`) rather than boilerplate `true`/`[]` placeholders, and `summary.json`'s verdict (`M2_POST_CONFIRM_CONTEXT`) is derived from measured deltas (e.g., `confirm_rate_delta: -0.0254`) consistent with `determine_verdict()`'s logic in `validate.py`.

## Clean checks
- A1-A5: `state_at`/`age_seconds_at`/`age_bars_at` all availability-clock-bounded (`close_ts <= t`); confirmed by both source review and the parity test's causal-boundary assertions.
- B1-B10: `ewm_mean(adjust=False)` + `forward_fill` (no `center=True`, no `.shift(-N)`, no `bfill`); bit-parity to a literal bar-by-bar replay proven by `test_regime_matches_exactly`/`test_age_bars_matches_bars_in_regime`.
- C1-C2: Phase 6 is the sole forward-looking computation, walled into a separate frame with a source-scanned single call site (V11); grouping-timestamp ambiguity from pass 1 resolved in both SPEC and code.
- C3: not applicable (no train/test split).
- F1-F4: RTH/CT time-of-day bucketing uses `dt.convert_time_zone("America/Chicago")`, not fixed offsets; regime engine kept continuous RTH+ETH by design.
- G1-G4: final partial bucket discarded (`regime_5m.py:283-284`, confirmed in `_work/regime_5m_build.json`: `final_partial_bucket_discarded: true`); bucket/row reconciliation enforced and passing (`buckets_reconcile`/`rows_reconcile: true`); no synthetic/forward-filled bars — a bucket exists only if ≥1 real 1s row fell in its slot.
- H: not applicable — no trade-lifecycle simulation in this study; all outcome fields read verbatim from already-audited predecessor artifacts.

## Referred to contract-checker
(none new this pass — the one pass-1 item was already resolved per `contract_pass_01.md`)

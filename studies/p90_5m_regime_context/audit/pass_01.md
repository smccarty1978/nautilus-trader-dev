# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-12
**Scope:** `studies/p90_5m_regime_context/SPEC.md` §2–§5 (pre-execution; no implementation code exists yet). Cross-checked against `studies/p90_5s_regime_impulse/implementation/{regime_5s.py,policy.py}`, `studies/p90_5s_regime_impulse/tests/test_regime_5s_parity.py`, `collectors/collector_v2/{aggregator.py,regime_engine.py}`, `backtests/studies/1m_regime_collector_v2/collector.py`, `studies/p90_conditional_losing_5s_exit/implementation/lineage.py`, and `armed_regime_score_paths.parquet` (schema/height spot-check).
**Scope hash:** `45f984a52e4a1ef505949104eed81fc4098410d8cb85e2e858b705a2c09e72f7`
**Lint:** 0 critical / 0 warning from `causal_lint.py` (3 files scanned — only `SPEC.md` + empty `__init__.py`s exist)
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 2
- Note: 2

## Critical findings

### [C2] `SPEC.md:276-278` — §5's decision-timestamp mapping is ambiguous for Phase 2/3/4's grouping variable, and the literal reading breaks Phase 2's own metric
**Failure path:** §5 states: *"Decision timestamps: `arm_top10_ns` for the primary classification and Phase 1/7/11; `walk_a_confirm_ns` for the transition matrix (Phase 5) **and Phase 2/3/4 outcome tables**."* Read literally, this assigns Phase 2/3/4's `group` column to `with_5m_at_confirm` (classified at `walk_a_confirm_ns`) rather than `with_5m_at_p90`. But `with_5m_at_confirm` is undefined for the 4,294 non-confirming arms (`walk_a_confirm_ns` is null for them — nothing to snap `state_at` against). Phase 2's own deliverable columns are `p_confirm_lt_1atr` and `p_stop_before_confirm` — i.e. Phase 2 measures *whether* confirmation happens, which requires grouping non-confirming trades too. If implemented per the literal reading, non-confirming trades cannot be assigned a group, so `p_confirm_lt_1atr` computed within a `with_5m_at_confirm`-defined group is circular (the group only contains trades that already confirmed) — the metric Phase 2 exists to report becomes tautologically ~1.0 or undefined, not a real number.
**Evidence this is a real ambiguity, not just careless reading:** Phase 1's manifest schema (`results/p90_5m_context.csv`) explicitly defines `group(WITH_5M/AGAINST_5M/UNINIT)`; Phase 2's manifest schema (`results/pre_confirm_outcome.csv`) reuses the bare name `group` without redefining it, implying reuse of Phase 1's at-P90 classification — which contradicts §5's literal timestamp assignment. Phase 5 is the only phase that explicitly restricts to "confirming trades only," which only makes sense if Phase 2/3/4 do *not* share that restriction, i.e. they use the at-P90 classification. §5's bullet is most plausibly intending to say "the *metrics themselves* (MAE-to-confirm, MFE-to-confirm) are anchored at `walk_a_confirm_ns`," not "the *grouping variable* switches to at-confirm" — but as frozen, the text says the latter and would abort the study on a first read-through implementation.
**Smallest fix:** Reword §5's bullet to separate the *grouping* timestamp (always `arm_top10_ns`/`with_5m_at_p90` for Phase 1/2/3/4/7/9/10/11; `with_5m_at_p90 × with_5m_at_confirm` transition group only for Phase 5) from the *metric-anchor* timestamp (`walk_a_confirm_ns`, used only to compute the outcome values within each group for Phase 2/3/4). This is a one-sentence SPEC clarification, not a code change, but it must be resolved before `classify.py`/`validate.py` are written or the ambiguity becomes an implementation coin-flip.

## Warnings

### [C1] `SPEC.md:284-287` — Phase 6 isolation is enforced only by column-name-prefix scanning, not by any structural restriction on who calls `Regime5m.next_change_after`
**Failure path:** §5 states `classify.phase6_future_flip_labels(...)` is "the only function permitted to call `Regime5m.next_change_after`," and stop condition 6 / gate V-LABEL scans *output frame column names* for a stray `label_only_` prefix. Nothing in the described design prevents a second call site (e.g. a future Phase 7/11 helper that reuses `next_change_after` to compute a convenience column under a *non*-prefixed name) — the column-name scan only catches the case where the original prefixed column is copied verbatim into another frame, not the case where a call-site restriction is violated and the value re-emerges under an innocuous name. This is a real gap given `Regime5m` will almost certainly expose the same method surface as `Regime5s` (which additionally has `first_non_aligned_after`/`first_aligned_after`), all unused by this study but sitting on the shared class.
**Smallest fix:** Have `validate.py` additionally assert (via `git grep` or an AST scan) that `next_change_after` appears in exactly one call site (`classify.phase6_future_flip_labels`) across `implementation/`, not just scan output columns.

### [F1/A1] `SPEC.md:95-107` — the non-blocking runtime cross-check's comparison source (`v2_feature_snapshots_<year>.parquet`) is a multi-checkpoint table; the SPEC doesn't pin which row represents "at signal time"
**Failure path:** `backtests/studies/1m_regime_collector_v2/collector.py:1889-1898` (`_ckp_5m_state`) populates `regime_5m_direction`/`regime_5m_aligned` inside `_snapshot_features_at`, which fires at **every** checkpoint offset `T` for an event (`T_000`, `T_030`, `T_060`, ... — see call site `collector.py:1722-1728`), not once at signal time. `T_000`'s comment (`collector.py:696`) confirms it is the row aligned to signal time; later `T_*` rows reflect a *later* 5m state. If `regime_5m.py`'s reconciliation script samples "signal timestamps from these files" without explicitly filtering to the `T_000` checkpoint row per event, it will compare `Regime5m.state_at(signal_time)` (correct) against a 5m state snapshot taken tens of seconds to minutes later (from a different checkpoint row), inflating or deflating the reported agreement rate for reasons unrelated to engine correctness.
**Smallest fix:** State explicitly in `regime_5m.py`/`SPEC.md` that only `T_000` rows are used for the cross-check. Low severity because §2 already treats this cross-check as non-blocking/informational and the authoritative check is the §2.1 parity test — but a corrupted agreement number in a committed deliverable (`_work/regime_5m_build.json`) is still worth getting right the first time.

## Notes

- **[G-adjacent]** §9 stop condition 7 / gate V-SEALED ("no `state_at`/`age_*` call issued a 2026+ timestamp") guards the *query* timestamp only. Phase 6's `next_change_after` search for a late-2025 P90 arm could legitimately *resolve* to a close_ts that falls in calendar 2026 (the regime engine is built continuously across all years in the store, per §2's "continuous across RTH+ETH" design). This mirrors the already-accepted upstream convention that `full_*`/`walk_a_*` outcome columns for late-year arms can themselves resolve past the calendar year boundary (evidenced by `FULL_LABEL_COUNTS` including non-`SESSION_EXIT` terminal labels that can cross session/day boundaries), so this is disclosure rather than a new defect. Worth one line in `regime_5m_build.json` if it occurs, since "2026 sealed" is a load-bearing convention elsewhere in this repo.
- **[hygiene]** `Regime5m` will likely be built by copying `Regime5s` verbatim (per §2's "only `BUCKET_NS` changes" instruction), which means `first_non_aligned_after`/`first_aligned_after` will exist on the class even though this study has no trade-lifecycle simulation and never calls them. Unused forward-looking methods on a shared, reusable class are a standing invitation for a *later* study to call them without re-deriving the causal guarantee. Not a defect in this SPEC.

## Referred to contract-checker
- Deliverable #9 (`phase6_timing.csv`) schema lists unprefixed derived columns (`timing_bucket, confirm_rate, mfe_mean, mae_mean, terminal_return_mean`) alongside the two `label_only_`-prefixed raw columns, while §5 states "every column [Phase 6] produces is prefixed `label_only_`" — a manifest/prose consistency issue, not a causal defect.

## Pass 2 adjudication (resolved in SPEC.md / implementation before Phase 0-classify code was finalized)

- **[C2] CRITICAL — FIXED.** SPEC.md §5's decision-timestamp bullet reworded:
  `arm_top10_ns`/`with_5m_at_p90` is now stated explicitly as the ONLY
  grouping variable for Phases 1,2,3,4,6,7,10,11; `walk_a_confirm_ns` is
  scoped explicitly to (a) outcome-metric anchoring within those groups and
  (b) the Phase-5 transition's `with_5m_at_confirm` variable, restricted to
  the 4,656 confirming trades. `implementation/classify.py::classify_core`
  already implemented the correct behavior (grouping by `with_5m_at_p90`
  throughout; `with_5m_at_confirm` a separate nullable column used only for
  the transition matrix) — this was a SPEC wording defect, not a code defect.
- **[C1] WARNING — FIXED.** `Regime5m.next_change_after` /
  `next_change_into_direction_after` renamed to `lookahead_next_change_after`
  / `lookahead_next_change_into_direction_after` in
  `implementation/regime_5m.py`, so the forward-looking surface is
  grep-identifiable independent of the caller's column-naming discipline.
  `validate.py` (implemented in a later step) additionally source-scans
  `implementation/*.py` to assert `lookahead_next_change_into_direction_after`
  has exactly one call site (`classify.py::phase6_future_flip_labels`), per
  the auditor's own suggested remediation.
- **[F1/A1] WARNING — FIXED.** `regime_5m.py::_runtime_cross_check` now
  filters `v2_feature_snapshots_<year>.parquet` to `checkpoint_s == 0` before
  comparing (confirmed present: ~9k rows/year at that checkpoint), rather
  than reading all checkpoint rows unfiltered. SPEC.md §2 updated to state
  this explicitly. Re-running `regime_5m.py` after this fix is required
  before trusting `_work/regime_5m_build.json`'s reported agreement rate (the
  earlier 79.5% figure was computed pre-fix and is superseded).
- **[hygiene note]** Acknowledged: `Regime5m` does carry
  `lookahead_next_change_after` on the class surface even though only
  `lookahead_next_change_into_direction_after` is called by this study. Left
  as-is (mirrors `Regime5s`'s equivalent unused surface); the call-site gate
  in `validate.py` covers the method actually used, and the `lookahead_`
  prefix makes the unused sibling equally conspicuous to a future reader.
- **[G-adjacent note]** Acknowledged, not fixed as a gate: Phase 6's
  `lookahead_next_change_into_direction_after` result CAN resolve to a
  close_ts in calendar 2026 for a late-2025 arm. This mirrors the accepted
  upstream convention (terminal/exit fields can cross the calendar boundary)
  and is disclosed in the Phase 6 output rather than blocked, since the QUERY
  timestamp (the P90 arm) stays sealed to 2021-2025 — consistent with SPEC
  §9 condition 7's wording ("any `state_at`/`age_*` call is issued a 2026+
  timestamp"), which the auditor confirmed guards the query side.
- **Referred-to-contract-checker item** was independently resolved in the
  same pass by the contract-checker's own W2 finding (audit/contract_pass_01.md).

## Clean checks
- A1-A5 verified clean by design (all lookups documented as `close_ts <= decision_ts`, matching `CompletedBarRegistry`'s enforced invariant; `TimeframeAggregator` confirmed to already support `"5m"` in `TIMEFRAME_TO_BUCKET_NS`).
- B1-B10 clean: no rolling/ewm feature computation introduced beyond the reused, parity-tested EMA3/EMA9 sticky rule; no `.shift(-N)`, no `bfill`, no `center=True` in the described design.
- C1 clean in intent (Phase 6 correctly identified as the sole forward-looking lookup and walled off by construction) — enforcement gap noted above as a WARNING, not a design defect.
- C3 not applicable — no train/test split, no ML, purely descriptive study.
- F1-F4 clean: regime state kept continuous RTH+ETH by design (not session-reset), entries/classification correctly gated to RTH P90 population downstream; Phase 11's time-of-day windows use named CT boundaries, not fixed UTC offsets.
- G1-G3 clean by inheritance from the already-parity-tested `Regime5s`/`TimeframeAggregator` pattern (final partial bucket explicitly discarded; bucket/row reconciliation required before any classification runs; §2.1 parity gate aborts before use).
- H not applicable — SPEC explicitly performs no trade-lifecycle simulation; all outcome/exit prices are read verbatim from already-audited predecessor artifacts, not recomputed.

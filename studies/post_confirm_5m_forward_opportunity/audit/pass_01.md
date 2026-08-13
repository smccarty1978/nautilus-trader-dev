# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-13
**Scope:** `studies/post_confirm_5m_forward_opportunity/SPEC.md` (pre-execution, no implementation code exists); spot-checked `studies/p90_5m_regime_context/implementation/regime_5m.py`, `studies/p90_5m_regime_context/SPEC.md`, `studies/post_confirm_forward_opportunity/SPEC.md` for inherited-contract context.
**Scope hash:** `4973aa7009a2499db462cdc40fc46849766dbcf56344ffb6d700eb42d67435b8`
**Lint:** `causal_lint.py` — 4 files scanned, 0 CRITICAL, 0 WARNING (only `__init__.py` stubs exist; no implementation to lint yet).
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 3
- Note: 2

## Critical findings
None.

## Warnings

### [C1] SPEC.md §8 stop-4 vs §4 Phase 11 — LABEL_ONLY guardrail is in tension with the SPEC's own Phase 11 design
**Location:** `SPEC.md:212` (Phase 11: "Re-run Phases 3/4/5/6/9/10's aggregations crossed with this bucket × WITH/AGAINST") vs `SPEC.md:382-384` (stop condition 4: "A retrospective/future-derived column (`eventual_max_mfe_atr`, `runner_bucket`, any `NEXT`-window field) is used as a grouping or filter key anywhere outside its declared LABEL_ONLY role → **ABORT**").
`runner_bucket`/`mfe_bucket` is derived from `eventual_max_mfe_atr` (a fully-retrospective, trade-terminal quantity) and Phase 11 explicitly groups by it. Read literally, stop-4 would trip on Phase 11's own design the moment it's implemented as a source-scan check; read loosely enough to exempt Phase 11 ("descriptive stratification is part of the declared LABEL_ONLY role"), the same loose reading would also silently pass a real future misuse (e.g. `runner_bucket` accidentally entering Phase 12's stratum list). As written, "declared LABEL_ONLY role" is never defined precisely enough to distinguish "permitted post-hoc descriptive crosstab" from "forbidden causal grouping key" — the two phrases used in the SPEC (line 250, "descriptive label, never a causal predictor" vs. stop-4's blanket "grouping... key") don't resolve the ambiguity.
**Concrete risk:** either (a) `validate.py`'s stop-4 check is implemented literally and false-positive-aborts a phase the SPEC itself requires, forcing an undocumented mid-study spec patch, or (b) it is implemented loosely/not at all, in which case stop-4 is a check that can never fire — the "validation check that always passes is worse than no check" failure mode already logged elsewhere in this repo's history.
**Smallest fix:** add one sentence to §3.1 item 4 / §8-4 distinguishing "grouping key used to define or filter the WITH/AGAINST comparison population or the C1–C5 verdict inputs" (forbidden) from "post-hoc descriptive stratification column reported alongside, never fed back into the group definition" (Phase 11's actual use, permitted).

### [C1] SPEC.md §7 manifest — Phase 6 and Phase 7 outputs are not tagged LABEL_ONLY, unlike Phase 5's
**Location:** `SPEC.md:330` (deliverable 7, `remaining_mfe.csv` — "LABEL_ONLY" explicitly appended) vs `SPEC.md:331-333` (deliverables 8/9/10 — `opportunity_capture.csv`, `opportunity_capture_time_to_threshold.csv`, `new_extreme_probability.csv` — no LABEL_ONLY tag), contradicting `SPEC.md:131` (§3.1 item 4: "Phase 5/7 output columns prefixed/flagged" — claims both Phase 5 *and* 7 carry the tag).
Phase 6's `fraction_realized`/time-to-threshold and Phase 7's `p_new_extreme_next_30s/60s/120s/300s` are both structurally dependent on retrospective, trade-terminal information (`eventual_max_mfe_atr`, or a self-join across a trade's own future offset rows) exactly like Phase 5's `remaining_mfe` — but only Phase 5's deliverable carries the disclosure tag in the manifest that a downstream reader or `validate.py` could key off of.
**Concrete risk:** a mechanical "grep for LABEL_ONLY-tagged columns" enforcement (the only enforcement mechanism the SPEC describes) would miss Phase 6/7 columns entirely, since the manifest — the one place the tag is actually instantiated — doesn't carry it for those two deliverables.
**Smallest fix:** add "— LABEL_ONLY" to deliverables 8, 9, and 10's Required-contents column, matching deliverable 7.

### [C1] SPEC.md §4 Phase 6 — reconciliation-check tolerance and sample size are unspecified
**Location:** `SPEC.md:196-199` ("assert agreement within tolerance on a sample before use, and disclose which is authoritative").
No numeric tolerance or minimum sample size is frozen, unlike every other threshold in this SPEC (e.g. §6's verdict table gives concrete ATR/second bars). A check with no frozen tolerance can be implemented as a no-op that always passes (set the tolerance arbitrarily loose), which is exactly the failure mode this project has hit before with unfalsifiable validation checks. This gates whether `walk_a_mfe_to_confirm_atr` (armed engine) and the panel's own confirmation-anchor MFE (a different engine) can be safely treated as interchangeable before Phase 6's capture-curve denominator is built from one and the numerator from the other.
**Smallest fix:** freeze a tolerance (e.g. `abs(Δ) < 0.05 ATR` — the same floor already used elsewhere in Phase 6) and a minimum sample size (e.g. full population, not a subsample) in the SPEC text, not left to implementation discretion.

## Notes

### [B2/G] `age_seconds_at`/`age_bars_at` uninitialized-state handling undisclosed at the new call site
`Regime5m.age_seconds_at`/`age_bars_at` return `NaN`/`-1` when no flip has occurred yet before `t_ns` (`regime_5m.py:190-208`). The predecessor already handles this for `regime_age_s_at_p90`; this SPEC doesn't restate how `regime_age_s_at_confirm`/`regime_age_bars_at_confirm` handle the same edge case (low-probability at confirmation time, given P90 arms occur well after 5m-engine warmup, but undisclosed).

### [C2] Stop condition 5 (Phase 12 no post-confirmation columns) has no named automated check, unlike stop condition 3
Stop condition 3 names its enforcing test (`tests/test_join_causality.py`); stop condition 5 does not. The Phase 12 stratification variable list itself (`SPEC.md:254-260`) is verified clean as written — every variable is confirmation-time-or-earlier (`walk_a_..._to_confirm`, `arm_score`, `side`, `entry_year`, time-of-day derived from `arm_top10_ns`). This is a hygiene gap, not a live defect.

## §3 — the new `Regime5m` call site (primary audit target): CLEAN
`age_seconds_at`/`age_bars_at`/`flip_ts_at` all route through the identical `_idx_at(t_ns) = searchsorted(close_ts, t_ns, side="right") - 1` helper that `state_at` already uses (`regime_5m.py:149-208`) — the causal bound (`close_ts <= t`) is a property of the index, not of which attribute is read off it, so calling it at `walk_a_confirm_ns` instead of `arm_top10_ns` introduces no new structural risk. Confirmed further: the predecessor (`p90_5m_regime_context/SPEC.md:146-149`) already calls `Regime5m.state_at(walk_a_confirm_ns)` to build the reused `with_5m_at_confirm` column under its own gate `V-CAUSAL-2`, and already calls `age_seconds_at`/`age_bars_at` (at `arm_top10_ns`) under `V-CAUSAL-1` (`p90_5m_regime_context/SPEC.md:85-92,159`). This study's §3 is the same two methods at the same already-validated timestamp the predecessor used for the boolean — genuinely low incremental risk, correctly scoped as "no new engine code."

## Pass 2 adjudication (resolved in SPEC.md before implementation)

- **[C1] LABEL_ONLY vs. permitted descriptive crosstab — FIXED.** §3.1 item 4
  now states explicitly: LABEL_ONLY forbids a retrospective field driving
  the WITH/AGAINST grouping or any row-inclusion filter; it does NOT forbid
  using one as a post-hoc descriptive stratification axis (Phase 11's
  entire purpose). Stop condition 4 cross-references this distinction and
  Phase 11's own text now states the carve-out.
- **[C1] Phase 6/7 manifest tagging — FIXED.** Deliverables 8, 9 now carry
  "— LABEL_ONLY"; deliverable 10 carries a split disclosure (the `NEXT`-window
  columns are LABEL_ONLY, `p_new_extreme_since_confirm` is not).
- **[C1] Phase 6 reconciliation tolerance/sample size — FIXED, and
  redesigned, not just parameterized.** On reflection while fixing this, the
  originally-described "cross-engine tolerance comparison" was itself
  conceptually flawed: the panel has no offset=0 row, so there is no
  independent panel-native value AT the confirmation instant to compare
  against — the nearest available point (offset=15s) is confounded by 15
  real seconds of possible additional favorable movement, making a fuzzy
  tolerance both unmotivated and hard to set meaningfully. Replaced with an
  exact monotonicity invariant instead (`running_mfe_from_entry_atr` at
  offset=15s >= `walk_a_mfe_to_confirm_atr` for 100% of trades, since
  running MFE cannot decrease) — **verified directly against the real data
  before freezing this as a gate: 0 violations across all 4,656 trades.**
  No fuzzy tolerance is needed once framed correctly.
- **[B2/G] Uninitialized-state disclosure — FIXED.** §3 now states the
  `NaN`/`-1` convention explicitly and requires retention (never imputation)
  of any such row.
- **[C2] Stop condition 5 unnamed check — FIXED.** Now references
  `tests/test_join_causality.py` explicitly, matching stop condition 3's
  pattern.

## Referred to contract-checker
- §7 Deliverables Manifest completeness/wording (all 23 items) and §7.2 terminal-label reachability — not reviewed here, per scope split.

## Clean checks
- A (timestamp conventions): inherited, not re-simulated; N/A to this join-only study.
- §2 time-zero convention: unchanged from predecessor's D3, correctly restated.
- §5 dual-track convention: precisely stated — UNCONSTRAINED primary for Phases 2-9/11/13 (avoids the documented 5x censored-population understatement), stop-live PRIMARY only for Phase 10's continuation value (a deliberately different, executable-path question) — no re-introduction of the prior defect.
- §4 Phase 8 race-column complement logic: correct (adverse-first = NOT favorable-first, restricted to resolved observations, UNRESOLVED reported separately, never counted as adverse).
- §4 Phase 12 stratification variables: all confirmation-time-or-earlier, none post-confirmation offset-indexed (F1-analog, C1-C2 verified).
- §8 stop conditions 1, 2, 3, 6, 7: each concretely testable against a named number or named test.
- F, G (session/data integrity): N/A — no raw-data resampling or session gating in this study; both inherited from already-audited upstream artifacts.

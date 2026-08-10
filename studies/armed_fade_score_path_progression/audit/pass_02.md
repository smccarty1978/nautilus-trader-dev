# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-09
**Scope:** `implementation/arming.py`, `implementation/validate.py`,
`implementation/build_paths.py`, `implementation/walks.py`,
`analysis/diagnostics.py`
**Scope hash:** `e1c77b8f91a93af4f4f8e46a5657ac69547d80232a2bb6672211d9aa4a2cc5ec`
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 11 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [C2/A3 WARNING] `arming.py` — `shift(1, fill_value=False)` treats "no predecessor" as "predecessor did not qualify", accepting a regime's already-qualifying first dispatch as a from-below arm | **RESOLVED** | `arming.py:120,124` now uses bare `.shift(1)` (null on absent predecessor) and filters `pl.col("prev_q").is_not_null() & ~pl.col("prev_q")` — a null predecessor no longer satisfies `~prev_q`. New test `test_first_ever_dispatch_already_above_is_not_an_arm` (`tests/test_arming.py:89-98`) constructs exactly the failure case (regime's first-ever dispatch already above Top-10) and asserts 0 arms; ran green (`pytest studies/armed_fade_score_path_progression/tests -q` → 25 passed). |
| 2 | [NOTE] dormant cross-year partition bug — a `years` filter before arming would drop a regime's predecessor dispatch at year boundaries | **RESOLVED** | `arming.py:78-96` adds `_assert_arming_population_is_complete`, called from `arm_population` (line 118) unless the test-only `require_full_population=False` is set; raises unless all of 2021-2025 are present. `build_paths.py:76-92` `build()` no longer takes a `years` parameter (confirmed by direct read — no `years` arg in signature or body), and `load_population()` (`arming.py:314-322`) takes none either. New test `test_arming_refuses_a_partial_year_population` (`tests/test_arming.py:101-108`) passes. `require_full_population=False` greps to test-file call sites only — no production path can bypass the guard. |
| 3 | [NOTE/referred] `validate.py` gate 3's from-below check recomputed `prev_q` with the identical `shift` expression over the identical table as `arm_population` — could only agree with itself | **RESOLVED** | Gate 3 (`validate.py:178-253`) now recovers the predecessor via `join_asof(strategy="backward", allow_exact_matches=False, by="regime_id")` against `universe` sorted on `prev_ns`, comparing `prev_probability` to `prev_thr` directly — a structurally different code path from the positional shift under test. Gate 1 (`validate.py:55-140`) was rewritten the same way and now reports `excluded_predecessor_already_qualified` / `excluded_no_predecessor_dispatch` as a reconciled, non-negative split of the exclusion delta. |

## Critical findings
None.

## Warnings
None.

## Notes
None new. See verification below for the specific `join_asof` scrutiny requested.

## `join_asof` verification (validate.py gates 1 and 3)
Confirmed by direct code read plus an isolated reproduction of the exact
`join_asof(strategy="backward", allow_exact_matches=False, by="regime_id")`
call shape used in both gates:
- **Strictly-earlier predecessor:** an arm/fq row with `arm_ns == 5` against a
  same-regime universe row at `prev_ns == 5` is skipped; the match returned is
  `prev_ns == 3`, the next-earlier row — `allow_exact_matches=False` behaves as
  documented, not as a same-timestamp match.
- **`by="regime_id"` isolation:** interleaved two-regime universe
  (`A: ns=1,3,6`, `B: ns=2,4,7`) with both left rows querying `arm_ns=5`
  returns `A→3`, `B→4` — no cross-regime bleed.
- **Sort correctness:** both frames are sorted on the exact column passed to
  `left_on`/`right_on` (`excluded.sort("fq_ns")` / `universe.sort("prev_ns")`
  in gate 1; `arm_keys.sort("arm_ns")` / the join input `.sort("prev_ns")` in
  gate 3) — polars' as-of sortedness requirement is on the `on` column
  globally, which a global sort satisfies per-group by construction (a
  subsequence of a sorted sequence is sorted). `scored` itself is
  `load_scored()`-sorted by `checkpoint_decision_ns` (`candidates.py:52`), so
  the source order is consistent throughout.
- **Population match:** `universe` in both gates is built from the same
  `scored` frame passed into `arm_population`/`arm_population`'s own
  `shift(1).over("regime_id")`, i.e. the same in-domain-only substrate
  (`load_scored` filters `bullish_in_domain | bearish_in_domain` before
  either function sees it) — the two mechanisms disagree only if one has a
  bug, not because they operate on different populations.

No inconsistency found. `build_paths.py` and `walks.py` are otherwise
unchanged from pass 1 (walks.py content is byte-identical to the version
verified clean in pass 1's H1/H2/H4/F2/G2 checks); `diagnostics.py` is
purely descriptive over the finished table with no new causal surface.

## Referred to contract-checker
None new this pass.

## Clean checks
- C2, A3 (arm from-below logic) re-verified clean per adjudication above.
- G-class (partition completeness) re-verified clean per adjudication above.
- A1, A3, B2, B4, C1-C3, F2, G2, H1, H2, H4 — unchanged since pass 1 (walks.py,
  build_paths.py path logic identical); not re-audited, per re-audit protocol
  (no diff in those regions).

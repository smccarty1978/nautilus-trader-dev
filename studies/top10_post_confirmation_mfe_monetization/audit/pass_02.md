# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-10
**Scope:** `implementation/engine.py`, `implementation/build.py`, `analysis/policies.py`, `implementation/validate.py` (new)
**Scope hash:** 8a0763c885daac74312c58b0ce253e61a2a85569c707081e4ce19987eee818ad
**Lint:** 0 critical / 0 warning (7 files)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 3 (1 carried, 2 new)
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | CRITICAL — `P90ARM_PRICE` scanned from bar `jb` itself, tautologically firing same-bar | **RESOLVED** | `engine.py:233-237`: `seg = slice(jb+1, nat_i+1)`, remap `jb+1+h`/`jb+1+h2`. Traced the arithmetic: `h` is 0-based within `seg`, whose first element is `bar_lo[jb+1]`, so absolute index `= (jb+1)+h` is correct — no second off-by-one. `finish()`'s `trig_i>=nat_i` clamp still bounds the result to `<= nat_i`. Reported coverage/delta shift (97.9→97.0% coverage, +0.0051→+0.0086/entry) is consistent with a policy that now waits for a real subsequent crossing instead of firing immediately. |
| 2 | WARNING — `exit_at` falls back to same-bar close when a STOP's next-bar-open would exceed the truncated window | **NOT RESOLVED (carried, non-blocking)** | Unchanged at `engine.py:96-101`. Confirmed still narrow (only the final bar of an already session/opposing-flip-truncated window) and not future information. SPEC §8 states "Any CRITICAL finding blocks conclusions" — WARNINGs do not block per the frozen contract's own text. No change requested. |

## New findings (Warnings)

### [W1] `implementation/validate.py:87-111` — `crossing_uses_prior_true_observation_same_regime` re-executes the same join/shift/threshold expression as `first_events()` in `build.py`, not an independent derivation.
Both use the identical source table, the identical join (`regime_id`↔`new_regime_id`, `checkpoint_decision_ns >= confirm_ns`), the identical `THRESHOLDS["top_10"]` selection, and the identical `.shift(1).over("regime_id")` crossing definition. A systematic defect in that shared logic (wrong shift direction, wrong `.over()` key, wrong threshold side) would reproduce identically in the "check" and pass trivially. This is a validation-design gap, not a demonstrated wrong number: I re-verified `first_events()` directly in pass 1 (correct `shift(1)` — not `-1` — over `regime_id`, `in_domain` applied post-crossing, null-filtered stream) and found it clean, so nothing currently fails. `WARNING` per "not independently validated ⇒ WARNING unless shown to fail" (no fail shown). **Smallest fix:** derive `firsts` via a method structurally different from `first_events()` (e.g., a `group_by` first-min-`ns`-above-threshold computed from a `pl.col("score").diff()`-based crossing, or a row-by-row loop over a materialized frame) rather than re-typing the same `.shift().over()` expression.

### [W2] `implementation/validate.py:70-74` — `score_causally_available` checks only `bullish_score_available_ns`, never `bearish_score_available_ns`.
`lag` is computed exclusively from the bullish column, yet ~half the confirmed population uses the **bearish** score (new-regime direction −1, per SPEC's own model-selection rule). A bearish-only latency defect would go undetected by this gate. I independently queried `canonical_regime_scores_all.parquet` (RTH) directly: `max|bearish_score_available_ns − checkpoint_decision_ns| = 0` and `bearish_score_is_new.all() = True`, matching bullish — so **no current defect exists**, hence `WARNING` not `CRITICAL`. **Smallest fix:** `lag = max(abs(bullish_available−decision), abs(bearish_available−decision))` over both columns.

## `independent_replay_causal_fill` — verified clean
Re-derives `ts`/`O` from `canonical_regime_paths_all.parquet` with the identical `session=="RTH"` / sort / `unique(subset=["path_init_ns"])` pipeline that `MarketData.load_market()` uses (confirmed by reading that function directly — same filter, same `side="right"` searchsorted semantics as `index_strictly_after`). Because both are a contiguous slice of the same underlying file with identical filtering, `a + exit_idx` reconstructs the same *relative* bar `MarketData`'s `start + exit_idx` would, without reusing the `MarketData` object itself. This is genuinely independent of the panel's own computation, not self-confirming. No finding.

## Clean checks
- A, B, C1-C3, F1-F4, G1-G4, H1-H3 unchanged from pass 1 (files not modified besides the noted fix).
- H4 (`P90ARM_PRICE`): now clean, see adjudication above.

## Referred to contract-checker
- (carried from pass 1) same-bar tie flagging gap (P90/P80-vs-stop) — now explicitly disclosed in `validate.py`'s `same_bar_ambiguity_flagged` gate as a `known_gap`; still a completeness item, not causality.

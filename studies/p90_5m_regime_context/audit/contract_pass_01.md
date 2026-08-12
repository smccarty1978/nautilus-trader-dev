# Contract-checker — Pass 1 (pre-execution)

Scope: Deliverables Manifest (§8), terminal-label reachability (§7/§8.2),
domain/completeness contract (§8.1), stop conditions (§9). C4/D/E are N/A —
this study trains no model, runs no walk-forward split, builds no
trade-lifecycle simulator (SPEC §1, §6).

## CRITICAL

**C1. M1 verdict condition is not computable from any declared deliverable.**
§7's `M1_STRONG_ENTRY_CONTEXT` requires "confirm-rate delta ≥5pp AND median
return-at-confirm delta ≥0.10 ATR, **same sign in ≥4/5 years and both
sides**." No manifest item produces a confirm-rate/return-at-confirm delta
stratified by `entry_year` and `side`. `results/pre_confirm_outcome.csv`
(item #4) only has `group, n, p_confirm_lt_1atr, ..., return_at_confirm_mean,
return_at_confirm_median` — no `entry_year`/`side` columns, and Phase 2's own
description never mentions a per-year/per-side breakdown either.
`results/full_economics_by_year.csv`/`_by_side.csv` (items #14-15) carry
`full_net_atr`-family FULL-lifecycle economics, not pre-confirm
`p_confirm`/`return_at_confirm`. As written, `determine_verdict()` cannot
evaluate M1's stated condition.
*Remediation:* add `entry_year`, `side` columns to Phase 2's output.

## WARNING

**W1.** M2's "P(MFE≥3 ATR) delta ... between transition groups" is only
partially backed — `transition_matrix.csv` (all 4 groups) lacks
`p_mfe_ge_3atr`; `against_with_deep_dive.csv` has it but only for 3 of 4
groups (no `WITH_AGAINST`). Unclear which table backs M2's condition.
*Remediation:* add `p_mfe_ge_3atr`/`p_mfe_ge_4atr` to `transition_matrix.csv`
for all 4 groups.

**W2.** §5's "every column [Phase 6] produces is prefixed `label_only_`"
appears to contradict item #9's declared schema
(`confirm_rate, mfe_mean, mae_mean, terminal_return_mean, timing_bucket` are
unprefixed). *Remediation:* clarify the prefix rule applies to the raw
timing/flip columns only, not aggregate outcome statistics joined in
afterward.

**W3.** §8.1's zero-row/missing-partition rule is scoped only to Phase 11;
Phases 1, 3, 4, 6, 7 have bucket/group breakdowns that could also be empty in
some stratum. *Remediation:* extend the zero-row rule to all bucketed tables.

**W4.** §8.1's "Global validation" enumeration omits Phase 6, 8, 9 (which
should reconcile to 8,950 / the 8,950-8,379-571 split per §5.1).
*Remediation:* add Phase 6/8/9 to the §8.1 enumeration.

## NOTE

**N1.** `NOT_5S_ENTERED` schema ambiguity in items #11/#12 — row-level
category vs. constant denominator column. Either resolution satisfies "no
silently shrunk denominator," but should be pinned down.

**N2.** §9 stop condition #3 ("5m bucket/row reconciliation fails") lacks an
explicit numeric pass/fail criterion in the SPEC text (though §2's build
description does define `buckets_reconcile`/`rows_reconcile` booleans in
practice).

**N3.** `with_5m_at_confirm` is not persisted in any manifest item — feeds
Phase 5 but isn't independently auditable without re-deriving it.

## Confirmed PASS
- §7 threshold wording correctly avoids presenting thresholds as settled.
- §5.1's 8,950-vs-8,379 handling is concretely specified with named count
  columns.
- M3, M4, M5, `ABORT_LINEAGE_FAILURE` are each reachable from an existing
  manifest table.
- §10's audit-plan scope split matches `docs/CAUSAL_CHECKLIST.md`.

## Summary
CRITICAL: 1, WARNING: 4, NOTE: 3.

## Blocking verdict
**BLOCKED** on C1 — the primary decision function cannot be implemented to
match its own specified M1 condition as written. Resolve before
implementation. W1-W4 touch the same manifest/verdict-logic seam and should
be resolved in the same pass to avoid a second contract-checker pass.

## Pass 2 adjudication (resolved in SPEC.md before implementation)
- **C1**: FIXED. Phase 2's `pre_confirm_outcome.csv` (manifest #4) now
  carries `side` and `entry_year` breakdown rows in addition to the
  aggregate WITH_5M/AGAINST_5M rows (a `stratum` column distinguishes
  `ALL`/`side`/`entry_year` rows), so M1's per-year/per-side delta is
  directly computable from the declared deliverable.
- **W1**: FIXED. `p_mfe_ge_3atr`/`p_mfe_ge_4atr` added to
  `transition_matrix.csv` for all 4 groups; §7 M2 now cites it explicitly.
- **W2**: FIXED. §5 reworded: the `label_only_` prefix rule applies to the
  raw future-flip timing/relationship columns only; outcome aggregates
  joined in afterward for reporting are exempt (they contain no forward
  information themselves, only backward-looking outcome stats keyed by a
  label-only bucket).
- **W3**: FIXED. §8.1 zero-row rule generalized to every bucketed table.
- **W4**: FIXED. §8.1 global-validation enumeration now includes Phase 6, 8, 9.
- **N1**: RESOLVED. `NOT_5S_ENTERED` is a row-level category value in the
  `group` column of items #11/#12, alongside `n_*` denominator columns.
- **N2**: RESOLVED. §9 condition #3 now cross-references §2's
  `buckets_reconcile`/`rows_reconcile` booleans explicitly.
- **N3**: RESOLVED. `with_5m_at_confirm` added to
  `results/p90_classification.parquet` (manifest #2) as a nullable column
  (null for non-confirming arms).

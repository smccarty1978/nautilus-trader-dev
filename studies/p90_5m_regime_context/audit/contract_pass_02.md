# Contract-checker — Pass 2 (completion)

Scope: deliverables/manifest/seal completeness, terminal-label reachability,
C4/D/E (confirmed still N/A — no model, walk-forward split, or
trade-lifecycle simulator exists in `implementation/`).

## Adjudication of Pass-1 findings

| Finding | Verdict | Evidence |
|---|---|---|
| C1 (M1 uncomputable) | **FIXED** | SPEC.md §8 item #4 declares `stratum, stratum_value` columns; `results/pre_confirm_outcome.csv` has real per-`side`/`entry_year` rows; `validate.py::determine_verdict` reads `_stratum_deltas` from exactly these columns to compute `years_positive`/`no_side_inversion`. |
| W1 (M2 p_mfe_ge_3atr missing) | **FIXED** | `transition_matrix.csv` header includes `p_mfe_ge_3atr, p_mfe_ge_4atr` for all 4 groups; `validate.py` reads it directly. |
| W2 (label_only_ prefix ambiguity) | **FIXED** | SPEC §5 states the prefix rule scopes to raw future-flip columns only; `phase6_timing.csv` header confirms aggregates are absent from that per-arm table (aggregates live separately in `summary.json`'s `phase6_bucket_summary`). Gate V7 passes with empty leak set. |
| W3 (zero-row rule scope) | **FIXED** | SPEC §8.1 "Zero-row/missing-partition" now explicitly enumerates Phase 1/3/4/6/7/11. |
| W4 (global validation enumeration) | **FIXED** | SPEC §8.1 "Global validation" now lists Phase 6, 8, 9 explicitly alongside 1/10/11 and 2-5. |
| N1 (`NOT_5S_ENTERED` schema) | **RESOLVED** | Manifest #11/#12 pins it as a row-level `group` category; `five_m_x_5s_failure.csv`/`stop_075_context.csv` carry `n_total_8950/n_5s_entered_8379/n_not_5s_entered_571` per row as declared. |
| N2 (§9 stop condition #3 no numeric criterion) | **RESOLVED** | §9 item 3 cross-references `buckets_reconcile`/`rows_reconcile`; `_work/regime_5m_build.json` shows both `true`, and gate V4 checks both. |
| N3 (`with_5m_at_confirm` not persisted) | **RESOLVED** | `classify.py` assigns `with_5m_at_confirm`; manifest item #2 declares it (nullable for non-confirmers). Not independently verified for exact null semantics on non-confirmers (parquet not directly readable by this agent) — acceptable, not re-raised. |

All 8 prior findings are genuinely resolved, not just re-worded.

## New findings (Pass 2) — both non-blocking

1. **NOT VERIFIED (informational):** Manifest #23 `audit/status.json` "roll-up
   with a key per agent" — at the time of this pass, `status.json` had not
   yet been merged across both agents (this pass's own status was still
   pending write). Remediation: orchestrator merges each agent's status into
   one keyed object before final commit.
2. **NOT VERIFIED (ambiguity, non-blocking):** SPEC §7 M2's "delta ... between
   transition groups" doesn't name which pair. `validate.py` resolves it as
   `WITH_WITH` vs `AGAINST_AGAINST` (the two well-populated groups) — matches
   REPORT.md's own framing, defensible, but not pinned in the SPEC text
   itself. Cosmetic fix for a future re-run: name the pair explicitly in §7.

No new CRITICALs. Gates 11/11 pass genuinely (computed, not asserted). The
M1-M5/ABORT label set is exhaustive and each label is reachable. REPORT.md
correctly flags the n=6 AGAINST→WITH cell as statistically unreliable rather
than presenting it as a finding, and explicitly disclaims Phase 6's
label-only output as non-causal/non-actionable.

## Blocking verdict

**CLEAR.** All 8 pass-1 findings are genuinely fixed and corroborated by the
actual implementation and produced results. The 23-item Deliverables
Manifest is present; every sampled artifact's header/schema matches its
declared columns, including the three items amended mid-implementation
(#4's `stratum` rows, #7's `p_mfe_ge_3atr/4atr`, #9's per-arm/per-bucket
split). All 11 gates in `validation_report.json` genuinely ran with real
expected/observed pairs, and `determine_verdict()` faithfully implements SPEC
§7's frozen M1-M5/ABORT conditions including the Phase-11-must-confirm-
direction credit rule for M1. The bounded run completed with exit_code 0.

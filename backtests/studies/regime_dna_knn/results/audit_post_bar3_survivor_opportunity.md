# Look-Ahead & Timestamp Audit — Post-Bar3 Survivor Opportunity

**Date:** 2026-06-15
**Auditor:** lookahead-auditor v1
**Scope:** `studies/regime_dna_knn/post_bar3_survivor_opportunity.py` (primary), with verification of call sites into `progressive_separability.py`, `rejection_power.py`, `early_health_filter.py`.

> Persisted manually from the auditor's returned findings (the subagent reported in chat
> but did not write the file during its run). Both warnings below were addressed before the
> result was trusted.

---

## Summary

- **Critical: 0**
- **Warning: 2**
- **Info: 4**

The pipeline is causally clean. The prior CRITICAL leak (`max(Nbar,1)`) is confirmed fixed in `progressive_separability.py:59`. No look-ahead survives into features, training, or scoring. The two warnings are a barrier-probability reference-price inconsistency and the OOS-relative percentile cut.

---

## Warnings

### [W1] `post_bar3_survivor_opportunity.py` — `barrier_first_touch` anchored to raw entry, `bracket_pnl` to fill-adjusted entry
`barrier_first_touch` used `entry_raw` (Bar-4 open, no slip) for pt_px/sl_px; `bracket_pnl` used `fill = entry_raw + d*ENTRY`. The PT level in the touch-prob table was ~0.125 pt easier than the level used for $/trade — Table 2 slightly optimistic on PT, pessimistic on SL vs Table 3. Small (0.5–1% of ATR) but inconsistent.
**Status:** FIXED — `barrier_first_touch` now computes `fill = entry + d*ENTRY` internally and anchors pt_px/sl_px to it, matching `bracket_pnl`.

### [W2] `post_bar3_survivor_opportunity.py` — "reject worst X%" cut is OOS-rank-relative, not IS-derived
The percentile cut is computed on the OOS pool's pQ ranking (inherent to a reject-worst-X% framing). The MODEL is strictly walk-forward (trained IS-only); only the cut floats with the OOS distribution. Not a bias for a composition/opportunity screen, but "reject worst 20%" is not a portable deployment threshold.
**Status:** ADDRESSED — explicit `[!NOTE]` added to the report stating the cut is OOS-rank-relative and a deployment gate would fix θ from the IS score distribution.

---

## Info

- **[I1]** `progressive_separability.py:59` — `k=Nbar` prior-leak fix confirmed present; grep found no remaining `max(Nbar,1)`/`max(window,1)` in feature paths.
- **[I2]** Population `n >= ENTRY_BAR` (=4) correctly means "alive at Bar 3 AND Bar 4 exists"; within survivors, QuickFailure ≡ `npost==4` (intersection of `npost<5` and `npost>=4`). For `npost==4`, MFE/MAE slice `Hs[:,4:]` includes only the entry/flip bar — causally valid.
- **[I3]** `BMAX=61` hold-to-flip cap truncates regimes with `n_post>61` — a coverage limitation, not a leak (later W2 fix in the conversion study used the exact terminal close).
- **[I4]** `ys` closure defined inside the year-split loop captures the correct `keep`/`ykeep` because it's called within the same iteration — no current bug.

---

## Clean Checks
- Entry causality: features end Bar 3 (`feats_through` cols 0..3); entry `O[:,4]` strictly later. No feature touches col 4+.
- Forward-only MFE/MAE from `Hs[:,4:]`.
- Barrier/bracket: adverse-first same-bar resolution (SL dominates); flip-close fallback uses CLOSE not open; entry/exit market slip adverse, PT limit no favorable slip; fills within bar OHLC.
- Walk-forward: IS=`yr<2025`, OOS=`yr>=2025`; ranking uses `pQ` (score), never the true label.

**Conclusion:** Zero CRITICAL. Causal separation between the Bar-3 feature window and the Bar-4 entry is correctly enforced.

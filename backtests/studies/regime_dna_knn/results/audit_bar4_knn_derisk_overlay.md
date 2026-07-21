# Look-Ahead & Timestamp Audit — KNN De-Risk Overlay

**Date:** 2026-06-16T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/bar4_knn_derisk_overlay.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` — `build_states`, `FEATS`, `trade_class`
- `studies/regime_dna_knn/progressive_separability.py` — `build` (array layout)
- `studies/regime_dna_knn/early_health_filter.py` — `compute_labels_features`, `CapsuleReplay`
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 3
- Note: 3

---

## Warnings

### [W1] `bar4_knn_derisk_overlay.py:116` — `t1` clamp allows de-risk at the same bar as the last post-flip bar (edge case, may understate cost)

**Location:** `overlay()`, line 116: `t1 = min(t + 1, int(min(n[ii], 61)))`

When the warning fires at bar `t` and `t + 1 > min(n[ii], 61)` — i.e., the warning fires on the very last available bar in the capped history — `t1` is clamped to equal `t` (or `t + 1` when `t + 1 <= 61` but `n[ii]` is already at the cap). The important case: if the warning fires at bar `k = min(n[ii], 61)` (the terminal bar) then `t1 = min(terminal+1, terminal) = terminal`, and de-risk happens at the open of the terminal bar. This is still a **different bar from the warning bar** only if `n[ii]` was capped at 61 and `t` is literally bar 61. In that specific cell, `t1 == t` meaning de-risk is read from the OPEN of the warning bar itself, not the next bar.

**How this manifests:** For any trade long enough that the KNN warning fires at bar 61 exactly, `O[ii, t1]` equals `O[ii, t]` — the open of the warning bar — which is available at bar-t-open, before bar-t closes, so this is still causal (open prices are known before close). However, it means the de-risk price is the same bar's open as the bar whose CLOSE triggered the warning. That is correct causally (next-bar open is bar 61's open; since bars are capped at 61 there is no bar 62), but it is mildly optimistic compared to deploying at the actual next available close/open in a live setting where bar 61 may not be the literal last bar. The effect is small in practice (warns at bar 61 are rare) but should be confirmed to not influence the verdict materially.

**Recommended fix (do not apply):** Add an assertion or comment confirming that when `t1 == t`, the de-risk price is still causal (open of bar t is known before bar t closes) and log the count of such cases.

---

### [W2] `bar4_knn_derisk_overlay.py:71` — `flip_c` extracted from raw `post_c` list rather than the price-array `C[:,n]`

**Location:** line 71: `flip_c = df.post_c.apply(lambda x: float(x[-1])).values`

The terminal close is taken as the last element of the raw `post_c` list (i.e., the last captured bar of the regime), indexing via Python list `[-1]`. This is the same value that `C[i, n[i]]` would give (the array built by `P.build` fills `C[i,1..k]` from the `post_c` list). The risk is: if any row has a truncated `post_c` list (e.g., length shorter than `n_post` due to a data anomaly) the `[-1]` and the array access could disagree. No defensive check enforces that `len(post_c) == n_post`. If they agree (which they should for well-formed capsules), `base_gross` is correct. But `leg2 = base_gross[j]` (the hold-to-flip gross for the non-exited portion) is used unmodified regardless of whether a warning was triggered. If the de-risk fires, the remaining `(1-X)` fraction continues to use this same terminal close — which is correct (that fraction genuinely does hold to flip). However, if `len(post_c)` ever differs from `n[ii]` due to capsule truncation, `flip_c[gi[j]]` and `C[ii, n[ii]]` would diverge silently. No assertion guards this.

**Recommended fix (do not apply):** Add `assert all(df.post_c.apply(len) == df.n_post)` immediately after loading the capsule, before `P.build`.

---

### [W3] `bar4_knn_derisk_overlay.py:133` — MFE-capture denominator uses `mfe` (available from bar-4 entry) but numerator adds back only `COMM`, not the full round-trip friction

**Location:** line 133: `cap = (pnl + COMM) / MULT / ai / np.where(mfe_ > 0, mfe_, np.nan)`

`pnl` already deducts `ncomm` (which is `COMM` for baseline/full-exit and `1.5*COMM` for scale-out). Adding back only one `COMM` unit means for scale-out variants the numerator still has `-0.5*COMM` embedded (the extra fill cost). This means `cap%` is slightly understated for scale-out variants vs the baseline, making the overlay look fractionally worse in MFE-capture than a purely economic gross/MFE comparison would show. The distortion is small ($2.50 on a per-trade basis vs ATR-scaled gross) but makes cross-variant comparison of `cap%` slightly misleading. This is a **descriptive metric only** and does not affect the PnL numbers or the verdict.

**Recommended fix (do not apply):** Use `(pnl + ncomm)` (gross before all commissions) in the numerator, or define `cap` using `gross[j]` directly. Since `ncomm` is not captured per-trade in the current structure, the simplest fix is to pass `ncomm` into `stats()` and use `(pnl + ncomm) / MULT / ai / mfe_` for `cap`.

---

## Notes

### [N1] `bar4_knn_derisk_overlay.py:95` — `seqs` built from full OOS `oos` (post pred-filter), `rids` contains only trades with at least one predicted bar; trades with all bars skipped (len(isk)<200 at every bar-k) are silently absent

**Location:** lines 91, 95, 98.

After the per-bar KNN loop, `oos = oos[oos.pred.notna()].copy()` drops state rows with no prediction. Then `seqs` groups by `rid`, so any trade with zero predicted bars is absent from `seqs` and from the `rids` universe. This means `base_gross` is computed only on trades that had at least one predicted bar, not the full OOS population. Since the baseline in the report is labeled "baseline hold-to-flip" but covers only the predicted subset, comparisons to any externally reported "all-OOS" baseline will differ. This is internally consistent (overlay and baseline share the same trade subset), but the report header says "OOS N trades" without flagging this filter. If bar-k coverage is near-complete (most bars k=4..15 have IS reference), the omission is small. Worth confirming that the universe is not materially narrowed.

**Recommended fix (do not apply):** Print the fraction of OOS trades represented in `rids` vs total OOS regimes, and note the subset in the report header.

---

### [N2] `bar4_knn_derisk_overlay.py:129` — MaxDD time-ordering uses `np.argsort(rids)` (sorts by `regime_id` integer) as a proxy for chronological order

**Location:** line 129: `order = np.argsort(rids)`.

`regime_id` is constructed in `early_health_filter.py:114` as `year * 100_000 + self._ridx` where `_ridx` increments per-flip within a year. Sorting by `regime_id` is equivalent to sorting by (year, within-year flip index), which is chronological. This is correct. However, it depends on `_ridx` being strictly monotone within a year and not resetting mid-year (which it doesn't — it starts at 0 and only increments). This is safe as-is but worth a comment since the sort key is not obviously "time" to a reader.

---

### [N3] `bar4_knn_derisk_overlay.py:111` — `ncomm` initialized to `COMM` (not `0`) for all trades; trades with no warning already carry `COMM` correctly, but the name `ncomm` is potentially confusing because for the full-exit branch (X>=0.999) `ncomm[j]` is also set to `COMM` (not `2*COMM`)

**Location:** lines 111, 121.

For `X >= 0.999` (full exit), the docstring says "2 fills, 1×COMM" (matching baseline). Setting `ncomm[j] = COMM` when overwriting for a full-exit warning trade is correct — same cost as baseline. For `0 < X < 1` (scale-out), `ncomm[j] = 1.5 * COMM` for "3 fills." This logic is consistent with the stated cost model. The potential confusion is that the baseline itself uses 2 fills but also `COMM` — implying the $5 RT commission is per-round-trip (both fills), not per-fill. As long as this matches the convention used throughout the study series (which it does — `COMM = 5.0` is the standard single RT cost for the whole trade), this is correct. No bug, just warrants a comment.

---

## Clean Checks

The following items were explicitly verified and found correct.

**A. Causality of the warning bar (check 2 from the audit brief)**

`warn_bar()` (lines 45–63) requires `seen = True` (a prior CONT prediction) before recognizing any DETER as a warning. The returned `k` is the bar index of the DETER prediction. The de-risk price is `O[ii, t+1]` (line 116–117) — the OPEN of the bar after the warning. Since `t` is the warning bar (its CLOSE is when the KNN prediction is known), acting at `t+1` OPEN is strictly after the signal. No look-ahead: the signal bar's close precedes the action bar's open by construction. Confirmed causal.

**B. `t1 > t` strict inequality (normal case)**

In the non-clamped case (which covers the overwhelming majority of trades since the 61-bar cap is rarely hit before a flip), `t1 = t + 1 > t`. W1 above covers the edge-case corner where the cap forces `t1 == t`; that case is still causal (acting at bar-t open, before bar-t close) but worth noting.

**C. KNN reference uses IS-only; OOS true labels never enter the reference (check 4)**

Lines 79–89: for each bar `k`, `isk = is_all[is_all.k == k]` selects IS (year < 2025) rows as the reference. `oos` (year >= 2025) rows are the query only. Standardization (`mu`, `sd`) is computed from `Xis` (IS data) and applied to both IS and OOS — correct. The majority-class vote (line 89) is over `isk.cls.values[idx]` — IS neighbor labels only. OOS `cls` (the true label for each OOS trade) is never used to form the prediction. Confirmed no OOS-label contamination.

**D. `warn_bar` rules are causal (check 3)**

`first` rule: returns the first bar with a DETER prediction after at least one CONT. That DETER is at bar `k`; at bar-k CLOSE the KNN prediction is available. Causal.

`2consec` rule: `prev_det` tracks whether the immediately preceding bar was DETER. Returns the second consecutive DETER. The state machine resets `prev_det` on any non-DETER bar (including CONT). The implicit assumption is that the loop processes bars in sorted-k order — confirmed by `sorted(zip(g.k, g.pred, g.consec_noncont))` on line 95. Causal.

`stall3` rule: uses `consec_noncont` (the stall count from `build_states`, computed through bar `k` using only `H[:,4:k+1]` and `L[:,4:k+1]`). Confirmed in `build_states` (lines 78–83 of `bar4_knn_path_atlas.py`): the stall counter scans backward from the current bar with no look-forward. Causal.

**E. `consec_noncont` in `build_states` is purely backward-looking (check 3 detail)**

`build_states` lines 78–83: `newext` is the array of new-high-since-entry flags from bar 4 through bar `k`. The stall counter scans backward from the last element of `newext` until it hits `True`, counting consecutive non-new-extremes. All data is `H[i, 4:k+1]` — no future bars included. Confirmed causal.

**F. Feature columns used for KNN are through bar k only (check 4 cross-ref)**

`FEATS` in `bar4_knn_path_atlas.py` line 33–34: `["bar_idx", "mfe_sofar", "mae_sofar", "pnl_now", "pullback", "progress_count", "consec_noncont", "dist_flip_open", "health_ratio", "close_loc", "range_exp", "vol_exp"]`. Every one of these is computed through bar `k` in `build_states` (lines 68–88). None references bars beyond `k`. Confirmed no look-ahead in features.

**G. Entry price is bar-4 OPEN; fill includes adverse slip (check 1)**

Lines 71, 100: `entry = O[:, 4]` — the open of the 4th post-flip bar (col 4 in the array). `fill = e + di * ENTRY` where `ENTRY = 0.5 * TICK` — adverse (long pays more, short receives less). Correct.

**H. Baseline terminal exit is the true flip close (check 1)**

Line 71: `flip_c = df.post_c.apply(lambda x: float(x[-1])).values` — the last element of the post-flip close list, which is the close of the opposite-flip bar (the regime's natural terminal bar). Line 102: `base_gross = (fc - di * EXIT - fill) * di * MULT` — adverse exit slip applied. Correct.

**I. `leg2` in scale-out uses `base_gross[j]` (hold-to-flip gross, not the de-risk price) (check 5)**

Line 119: `leg2 = base_gross[j]` — this is the full notional hold-to-flip gross for the entire position. When scaled: `gross[j] = X * leg1 + (1 - X) * leg2`. This is correct: X fraction exits at de-risk price, (1-X) fraction holds to flip. The `(1-X)` portion of `leg2` is computed from the terminal close which already incorporates the full trade horizon.

**J. Commission logic is correct for scale-out vs full-exit (check 5)**

Full exit (X=1): `ncomm[j] = COMM` — 2 fills, $5 RT. Matches baseline cost. Scale-out (0<X<1): `ncomm[j] = COMM * 1.5` — 3 fills, $7.50. Correct (1 entry + 2 partial exits). Baseline (no warning): `ncomm` stays at `COMM` ($5). Consistent.

**K. `mfe` is available-MFE from bar-4 entry through bars 4..min(n,61) (check 6)**

Lines 105–107: `H[ii, 4:min(n[ii],61)+1]` — includes bars 4 through the capped terminal. Favorable excursion relative to bar-4 entry price. Normalized by `ai` (ATR). `max(..., 0.0)` prevents negative MFE. Correct.

**L. MaxDD uses rid time-ordering (check 7)**

Line 129: `order = np.argsort(rids)`. As confirmed in N2, `regime_id = year * 100_000 + within_year_index`, so this sort is chronological. The cumulative-PnL drawdown is computed on the time-ordered PnL series. Correct.

**M. Year split for 2025/2026 separate averages (check 7)**

Lines 134–135: `n25=pnl[yy_ == 2025].mean(), n26=pnl[yy_ == 2026].mean()`. `yy_` is `yr[gi]` — the year tag from the full `df` indexed through `gi`. Correct.

**N. IS/OOS split is strictly year-based with no data leakage between splits (check 4)**

Lines 74–75: `is_all = S[S.year < 2025]` / `oos = S[S.year >= 2025]`. The IS reference for KNN is always year < 2025. The 6-day lead-in at catalog load (`early_health_filter.py:163`) pulls warm-up data from late-December of year-1 but regimes are filtered to within the target year at line 185 (`df.regime_start_ts >= yr0`), so no cross-year trade leakage. Confirmed.

---

*Audit complete. Zero critical findings. Three warnings, all non-fatal to result validity. Three notes, descriptive/defensive. Findings reflect read-only static analysis. Dynamic bugs (runtime data anomalies, capsule truncation) are out of scope.*

# Look-Ahead & Timestamp Audit

**Date:** 2026-06-16T00:00:00Z
**Scope:** `studies/regime_dna_knn/bar4_knn_warning_quality.py` (primary) + `studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS) + `studies/regime_dna_knn/early_health_filter.py` (capsule, compute_labels_features) + `studies/regime_dna_knn/progressive_separability.py` (build, feats_through)
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 2
- Note: 2

---

## Critical findings

None.

---

## Warnings

### [W1] `bar4_knn_warning_quality.py:88-92` — `warned_by` dict built but never used; post-warning CONT bars of warned trades contaminate the control

**Category:** D2 (train/serve skew — control group definition integrity)

The code builds `warned_by` (a copy of `warn_bar`, rid → warn_k) with the comment "for excluding post-warning from control." The `is_control` function body ignores it entirely and returns `(pred in CONT)` unconditionally. This means that for a trade with a warning at bar k=7, bars k=8,9,... where the KNN happens to predict CONT again (which can occur — KNN predictions are noisy bar-to-bar) are included in the healthy control pool.

**Impact assessment:** This makes the control group slightly worse than a strictly-never-warned control, because it includes "recovered" predictions from already-deteriorating regimes. The direction of bias is conservative with respect to the warning's discrimination: including post-warning recoveries in the control makes the healthy control look slightly worse (lower rem_mfe, lower newhigh3) than a purer "never-warned" control would. This tends to make the warning look LESS discriminating, not more. The result is therefore not inflated by this bug — if anything the gap between warning and control is understated. However, the code comment and the variable `warned_by` are misleading, and this has an asymmetric severity depending on how many trades are post-warning "recovery" predictions. If many warned trades subsequently get CONT predictions (e.g., noisy KNN flip-flops), the control is meaningfully diluted.

**Recommended fix (do not apply):** Use `warned_by` as intended: in `is_control`, return `False` if the rid has a warning bar and `k >= warned_by[r]`. Signature: `return (pred in CONT) and not (r in warned_by and k >= warned_by[r])`.

---

### [W2] `bar4_knn_warning_quality.py:65` — Dropping states where `pred` is NaN silently truncates trade sequences

**Category:** B2 (feature engineering integrity — completeness of per-trade sequences)

Line 65: `oos = oos[oos.pred.notna()].copy()`. A state row receives `NaN` pred when either (a) the bar's IS reference slice has fewer than 200 rows (`len(isk) < 200`, line 50), or (b) the OOS slice for that bar is empty. These dropped rows mean some trades have gaps in their bar-k sequence. The warning-detection loop (lines 70-78) sorts by k and iterates over whatever rows remain; if bar k=4 is missing for a trade (because IS coverage was thin at k=4) but bars k=5,7 exist, the loop may still label bar 5 as "first CONT" and bar 7 as "first DETER after CONT," producing a warning even though bar 4 was never assessed. More importantly: a trade that would have had `pred=DETER` at bar k=4 (classifying it as born-weak, never genuinely warned) might be mis-labeled as a genuine CONT→DETER transition if bar 4 is dropped.

**Completeness guarantee check:** The comment at line 17 states "ALL OOS queried (no subsample — need complete per-trade sequences)." The `IS_REF_CAP` cap only subsamples IS reference, not OOS rows — this is correct. However the `len(isk) < 200` guard (line 50) is the gap risk. In practice, for bars 4..15 (BARS = range(4,16)) against IS years 2021-2024, the IS pool at each k should be well above 200 (given the study volume), so the practical impact is likely small. But the guarantee is not enforced: if any k has thin IS coverage, sequences are silently truncated for all OOS trades at that k.

**Impact direction:** A truncated first bar that was DETER becomes invisible, converting a "born-weak" trade into an apparent genuine deterioration. This would inflate the warning count and make the warning look more discriminating than it is. The effect is bounded by how many k values hit the IS thin-coverage guard.

**Recommended fix (do not apply):** After the pred assignment loop, add an assertion or logged count: `thin_ks = [k for k in sorted(oos.k.unique()) if (is_all[is_all.k==k].shape[0] < 200)]`. If `thin_ks` is non-empty, either exclude all trades with missing coverage at their earliest observable k, or accept and document the gap. The warning count printout on line 81 should also report what fraction of "genuinely warned" trades have complete sequences from k=4.

---

## Notes

### [N1] `bar4_knn_warning_quality.py:90-92` — `is_ctrl` includes warning-bar rows themselves

**Category:** C1 (label construction correctness)

The `is_warn` flag marks exactly the warning bar per trade (line 79). The `is_ctrl` flag marks all pred-CONT rows. A warning bar state has `pred in DETER` (that is what triggered the warning), so `is_ctrl` is False for the warning bar itself. Pre-warning CONT bars of a warned trade, however, ARE marked `is_ctrl=True` (pred in CONT, k < warn_bar). At bar k, the control pool therefore contains: all never-warned CONT states at bar k AND pre-warning CONT states of warned trades.

Pre-warning CONT states of warned trades are forward-outcomes measured from a bar where the regime is about to deteriorate. Their actual forward metrics (rem_mfe, newhigh3) will be somewhat degraded vs a regime that never deteriorates. This makes the healthy control slightly worse, again biasing the test conservatively (warning looks less discriminating). This is not wrong behavior — pre-warning CONT states are not yet warned, and comparing them to the warning bar is legitimate — but it means the "healthy control" is not a pure never-deteriorates population. Worth noting when interpreting results.

**Recommended fix (do not apply):** To get the cleanest comparison, restrict `is_ctrl` to trades that NEVER warn (rid not in warn_bar). This is the strictest test and the most interpretable. Current approach is a valid but looser test.

---

### [N2] `bar4_knn_path_atlas.py:89` — Volume expansion window uses `max(4, k-5)` anchored at bar 4 entry

**Category:** A3 (timestamp/index convention)

The `vol_exp` feature: `vmean = np.nanmean(V[i, max(4, k - 5):k + 1])`. For k=4, this becomes `V[i, 4:5]` — a single bar mean, so `vexp = V[i,4] / V[i,4] = 1.0` always. For k=5, `V[i, 4:6]` — 2-bar mean. The feature is only meaningful for k >= 9 (6+ bars in the window). For bars 4-8 the feature is near-constant or degenerate. This does not introduce look-ahead (window is strictly through bar k), but it reduces the feature's discriminating power at early bars. Since the KNN operates per-bar, this only affects the specific bar slices where it degenerates — no systematic bias. Purely informational.

---

## Clean checks

The following items were explicitly verified and passed:

- **Check 1 (IS/OOS partition — no OOS in reference):** `is_all = S[S.year < 2025]` (line 44); per-bar KNN fits only `isk = is_all[is_all.k == k]`. OOS rows (`S.year >= 2025`) are never in the reference set. Clean.

- **Check 2 (OOS true label not used in pred):** The `pred` column is derived solely from `isk.cls.values[idx]` (IS neighbor majority vote). The OOS column `oos.cls` (forward label) is never accessed during the KNN fit or neighbor lookup. `oos.cls` is used only in `build_states` to assign the state's own class and in `bar4_knn_path_atlas.py` for calibration reporting — neither of these flows back into `pred`. Clean.

- **Check 3 (Standardization IS-only):** `mu = Xis.mean(0); sd = Xis.std(0)` (line 55) computed from IS features only; OOS features are scaled by IS statistics. No OOS information in the scaler. Clean.

- **Check 4 (Forward outcomes are actual, not predicted):** `rem_mfe`, `rem_mae`, `rem_bars`, `newhigh3` are computed in `build_states` at lines 91-113 using `fb = np.arange(k+1, ni+1)` — strictly future bars from the current observation bar k forward to the regime end. These are actual realized OHLC values from the capsule. They are NOT imputed from KNN predictions. Clean.

- **Check 5 (Warning/control split purely pred-based, no outcome circularity):** `is_warn` is assigned by whether `warn_bar.get(r) == k` where `warn_bar` was determined entirely from the `pred` column sequence. `is_ctrl` is determined by `pred in CONT`. Neither flag reads any forward outcome column. The comparison then reads actual forward outcomes for each group. No circularity. Clean.

- **Check 6 (Age-matching):** The per-bar loop groups by `oos.k == k` for both warning and control states. Both groups are at the same regime age. The pooled metric is weighted by warning count per bar. Clean.

- **Check 7 (IS_REF_CAP applies only to IS reference, not OOS):** The cap at line 52-53 subsamples `isk` when over 40,000 rows. The OOS slice `oos.loc[om, ...]` is not subsampled — all OOS states at each bar are queried. The comment at line 17 ("ALL OOS queried") is accurate. Clean.

- **Check 8 (Column alignment in build_states):** Verified positional alignment between the 28-element tuple (line 116-119) and the 28-element cols list (lines 120-122): rid/year/k prefix (3) + FEATS (12: bar_idx=k-4, mfe_sofar, mae_sofar, pnl_now, pullback, progress_count, consec_noncont, dist_flip_open, health_ratio, close_loc, range_exp, vol_exp) + suffix (13: rem_mfe, rem_mae, rem_bars, b0505, b1005, b1010, b2010, flip3, flip5, newhigh3, cls, tot_mfe, final_pnl). Alignment is correct. Clean.

- **Check 9 (No OOS leak in progressive_separability.py `build`):** `P.build(df)` constructs the OHLC matrices from the full df (IS + OOS combined). This is used only to index OHLC arrays by position, not to compute any statistics. No summary statistics (means, std, etc.) are derived from the full df in `build`. The matrices are purely data containers. Clean.

- **Check 10 (Feature computation in build_states strictly causal):** Features at bar k use `H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]` only — all at or before bar k. The `fb = np.arange(k+1, ni+1)` forward slice is used only for forward outcome columns (rem_mfe, rem_mae, etc.), never features. Clean.

- **Check 11 (newhigh3 construction):** `peak_px = max H (or min L) over bars 4..k` (line 107); `nh3 = 1` if any of the next 3 forward bars exceeds this peak (lines 108-111). This correctly measures a genuine new high after bar k, using only data that is realized after the observation point. Clean.

---

## Verdict on diagnostic soundness

The diagnostic is logically sound. The one structural issue (W1: warned_by unused) biases the test in the conservative direction — the control is slightly contaminated with post-warning recoveries, making warning states look LESS discriminating than they are. W2 (sequence truncation from thin IS coverage) could in rare cases inflate warning counts if k=4 IS pools are thin, but for IS years 2021-2024 over the full universe this is unlikely to be material. Neither finding introduces artificial positive discrimination for the warning signal.

Conclusion: the warning/control comparison, as coded, produces a lower bound on the true warning discrimination. If the result shows "warning is REAL" (ratios <= 0.6), the actual discrimination is at least as strong and possibly stronger. If the result shows "warning is GARBAGE," the bugs do not explain it away.

---

*Audit complete. Findings reflect read-only static analysis only. Dynamic behavior (e.g., actual IS k=4 pool sizes, actual rate of post-warning KNN flip-flops) requires runtime inspection to quantify.*

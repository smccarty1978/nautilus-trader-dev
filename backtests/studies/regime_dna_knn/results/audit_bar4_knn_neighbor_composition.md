# Look-Ahead & Timestamp Audit

**Date:** 2026-06-16T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/bar4_knn_neighbor_composition.py` (primary — full read)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (imports: `build_states`, `FEATS`, `CLASSES` — full read)
- `studies/regime_dna_knn/progressive_separability.py` (imports: `build` — full read)
- `studies/regime_dna_knn/early_health_filter.py` (imports: `compute_labels_features` — full read)
**Auditor:** lookahead-auditor v1
**Prior audit credit:** `build_states` / `FEATS` / `CLASSES` were declared clean in a prior pass. This audit re-verifies the boundary assertions that matter for the new composition script and audits all new code in `bar4_knn_neighbor_composition.py`.

---

## Summary

- Critical: 0
- Warning: 1
- Note: 2

---

## Critical Findings

None.

---

## Warnings

### [B7 / D1] `bar4_knn_neighbor_composition.py:82–84` — Subsampling RNG is shared across bar iterations; subsampling path differs between bar-4, bar-5, bar-6, bar-8

**File:** `bar4_knn_neighbor_composition.py`, lines 73, 82–84

```python
RNG = np.random.default_rng(0)          # module-level, shared
...
for k in BARS_C:                        # iterates [4, 5, 6, 8]
    ...
    if len(isk) > IS_REF_CAP:
        isk = isk.iloc[RNG.choice(len(isk), IS_REF_CAP, replace=False)]
    if len(ook) > OOS_CAP:
        ook = ook.iloc[RNG.choice(len(ook), OOS_CAP, replace=False)]
```

The `RNG` object is stateful and advances across loop iterations. The IS subsample drawn for bar-4 consumes RNG state that affects the bar-5 subsample, and so on. This is not a look-ahead leak, but it means:

1. The IS reference set for bar-5 depends on whether bar-4 exceeded `IS_REF_CAP` (i.e., on the *size* of bar-4's dataset). If bar sizes change (e.g., more data added), the subsamples for all downstream bars shift, making results not reproducible across data updates without re-running from scratch.
2. The `RNG` module-level definition means any other code that imports this module and calls `RNG` would cross-contaminate state. In the current script this is not triggered, but it is fragile.

**Impact:** Results are reproducible within a single run. AUC/lift numbers reported in the output `.md` file are consistent within themselves. This is not a bias issue — it only affects reproducibility hygiene across partial re-runs or dataset expansions.

**Recommended fix (do not apply):** Use per-bar seeded RNGs: `rng_k = np.random.default_rng(k)` inside the loop so each bar's subsample is independently deterministic regardless of loop order or dataset size changes.

---

## Notes

### [Note 1] `bar4_knn_neighbor_composition.py:63` — Base-rate denominator is per-trade (deduped by `rid`) but OOS predictions are per-bar-state (not deduped)

**File:** `bar4_knn_neighbor_composition.py`, line 63

```python
base = S.drop_duplicates("rid").cls.value_counts(normalize=True)
```

The base rate is computed over unique trades (one row per `rid`, the first bar-4 state row). The reliability tables and AUC/lift at lines 97–106 operate on `out`, which is the OOS bar-k state frame (`ook`) — potentially containing multiple rows per trade if the same trade appears at multiple `k` values. However, the loop body filters to a single `k` per iteration (`is_all[is_all.k == k]`; `oos_all[oos_all.k == k]`), so within each bar, `out` is one row per OOS state at that bar. A trade that survives to bar-8 will appear once at bar-4, once at bar-5, once at bar-6, and once at bar-8. The base rate computed from `drop_duplicates("rid")` therefore reflects the **per-trade** label distribution, while the AUC/lift compares against **per-bar-state** distributions that are length-biased toward longer-duration regimes (they appear at more bar values).

This mismatch means the base Runner% printed in the header and used in the dispersion/bifurcation commentary (lines 127, 136) may differ from the actual prevalence in `out.y_Runner` for any given bar-k slice. The printed base could over- or under-state relative to `out.y_Runner.mean()`, which is what AUC/lift is actually computed against. This is not a look-ahead bug but could cause the "KNN DOES locate runner-rich pockets (p99 vs base)" decision on line 127 to use a mismatched denominator for the threshold comparison.

**Recommended fix (do not apply):** Inside the `if k == 4:` block, derive the base rate from `out.y_Runner.mean()` (the actual Bar-4 OOS proportion) rather than the pre-computed per-trade `base.get('Runner', 0)`. The per-trade base is still valid for the preamble summary line; the dispersion/bifurcation comparison should use the in-scope bar-k base.

### [Note 2] `bar4_knn_neighbor_composition.py:88–89` — `idx` indexing into post-subsample `isk` is positional, which is correct but depends on pandas `.values` extraction order matching `NearestNeighbors.fit` input order

**File:** `bar4_knn_neighbor_composition.py`, lines 85–89

```python
Xis = isk[A.FEATS].values.astype(np.float32)
...
nn = NearestNeighbors(...).fit((Xis - mu) / sd)
_, idx = nn.kneighbors((Xoo - mu) / sd)
nbcls = isk.cls.values[idx]
nb_mfe = isk.tot_mfe.values[idx]
```

`idx` holds row positions (0-based) into the array that was passed to `.fit()`. That array is `(Xis - mu) / sd`, which is derived from `Xis = isk[A.FEATS].values`. Both `Xis` and `isk.cls.values` are extracted from `isk` in the same row order, so positional indexing `isk.cls.values[idx]` correctly retrieves the IS neighbor labels.

This is clean. The note is that if `isk` ever had a pandas index with gaps (e.g., after `.iloc[...]` subsampling), using `.values` before indexing is the correct pattern — `.iloc` selection followed by `.values` resets to 0-based positions, and `NearestNeighbors` indices are likewise 0-based positions into the fitted array. No risk here as written; flagging only for explicit confirmation.

---

## Clean Checks

The following checklist items were explicitly verified and pass.

**Check 1 (primary audit target) — IS/OOS separation is strict.**
`bar4_knn_neighbor_composition.py:73`: `is_all = S[S.year < 2025]`; `oos_all = S[S.year >= 2025]`. No row appears in both. The NearestNeighbors model is fitted exclusively on `isk` (IS subset for bar-k), and `nn.kneighbors` queries exclusively `Xoo` (OOS). No OOS rows enter the reference set.

**Check 2 (primary audit target) — Standardization fit on IS only.**
`bar4_knn_neighbor_composition.py:86`: `mu = Xis.mean(0); sd = Xis.std(0)`. Both statistics computed from `Xis` (IS rows only). The same `mu`/`sd` are applied to both `(Xis - mu)/sd` (fitting) and `(Xoo - mu)/sd` (querying). No OOS data influences the scale parameters.

**Check 3 (primary audit target) — Neighbor labels are IS-only; OOS true label is never used as a neighbor label.**
`bar4_knn_neighbor_composition.py:89`: `nbcls = isk.cls.values[idx]`. `idx` indexes into `isk` (IS only). The OOS true label (`out.cls`, `out[f"y_{c}"]`, lines 91–95) is assigned to `out` (the OOS frame) and is used only as the evaluation target in `auc()`, `topdec()`, and `reliability()`. The predicted `p_Runner` column is formed from `(nbcls == "Runner").mean(1)` — purely IS neighbor proportions. The OOS label cannot contaminate the prediction.

**Check 4 (primary audit target) — `cls` and `tot_mfe` used only as evaluation targets, never as KNN features.**
`bar4_knn_path_atlas.py:33–34, 120–122`: `FEATS` = `["bar_idx", "mfe_sofar", "mae_sofar", "pnl_now", "pullback", "progress_count", "consec_noncont", "dist_flip_open", "health_ratio", "close_loc", "range_exp", "vol_exp"]`. These 12 columns are all within-bar state features computed through bar-k from the entry at bar-4 open. `cls` and `tot_mfe` appear only in cols `k+1`..`n` of the `build_states` output (column positions after `FEATS` in the `cols` definition, line 120–122 of atlas). `Xis = isk[A.FEATS].values` and `Xoo = ook[A.FEATS].values` — neither includes `cls` or `tot_mfe`. Clean.

**Check 5 (primary audit target) — `base` deduplication is per-trade, not a leak.**
`bar4_knn_neighbor_composition.py:63`: `S.drop_duplicates("rid")` deduplicate to one row per trade (earliest bar-k row per regime). This is used only to print and display base rates, not in any prediction path. The deduplication reduces length bias in the displayed base rate and is a methodologically defensible choice. Not a leak.

**Check 6 — Subsampling is fixed-seed.**
`RNG = np.random.default_rng(0)` at module level (line 43). Within a single run the subsample is deterministic. The Warning above notes the cross-bar state contamination, but this does not introduce bias.

**Check 7 — FEATS are all causal (state through bar-k, not forward-looking).**
Confirmed in `bar4_knn_path_atlas.py:build_states` lines 65–119: every feature in FEATS is computed from `H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]`, `O[i, k]`, etc. — strictly through bar-k. The forward quantities `rem_mfe`, `rem_mae`, `rem_bars`, `b*`, `flip3`, `flip5`, `newhigh3`, `cls`, `tot_mfe`, `final_pnl` are outcome/label columns that do not enter `FEATS`.

**Check 8 — `build_states` uses `O[:, 4]` as entry price (bar-4 open), not a future close.**
`bar4_knn_path_atlas.py:54`: `entry = O[:, 4]`. `O` is the open-price matrix with col-0 = flip bar, col-1 = first post-flip bar, col-4 = bar-4 open. Entry at bar-4 open is the first price knowable at the bar-4 decision point. No look-ahead in entry price construction.

**Check 9 — `progressive_separability.build(df)` returns raw OHLCV matrices only; no labels.**
`progressive_separability.py:35–47`: `build(df)` returns `(H, L, C, O, V, n)` — the padded numpy matrices of bar OHLCV data and bar counts. No label columns, no forward quantities. The `M` tuple passed to `A.build_states` contains only price/volume data, consistent with prior audit findings.

**Check 10 — `compute_labels_features` forward-label columns (`mfe10`, `mae10`, `is_tradable`, etc.) are not in FEATS and do not enter the KNN feature matrix.**
`early_health_filter.py:203–319`: forward-computed labels (`mfe10`, `tradable`, `quick_fail`, `mfe3`, `mae3`, etc.) are attached to `df` as additional columns. However, `build_states` (atlas:49–123) extracts only OHLCV data from the `M` tuple (which comes from `P.build(df)`, not from `df` columns), and `FEATS` does not reference any of those label columns. The label columns in `df` are used by `build_states` only for `df.year`, `df.flip_o`, `df.atr_base`, `df.atr_20`, `df.direction`, `df.regime_id`, `df.n_post` — all causal metadata, not forward outcomes.

---

*Audit complete. Findings reflect read-only static analysis. No code was modified. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

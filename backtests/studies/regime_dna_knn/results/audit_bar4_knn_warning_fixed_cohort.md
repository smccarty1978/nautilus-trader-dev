# Look-Ahead & Timestamp Audit

**Date:** 2026-06-17T00:00:00Z
**Scope:** studies/regime_dna_knn/bar4_knn_warning_fixed_cohort.py (primary) + direct imports: bar4_knn_path_atlas.py (build_states, FEATS, BARS), early_health_filter.py (compute_labels_features, CapsuleReplay), progressive_separability.py (build)
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 0
- Note: 3

---

## Critical Findings

None.

---

## Warnings

None.

---

## Notes

### [N1] `bar4_knn_warning_fixed_cohort.py:114-122` — "CONSTANT N" in pre-window is contingent on IS coverage, not structurally guaranteed

The docstring and report header state that pre-window N is "CONSTANT" across relative bars t=-5..0 for cohort members. The `traj()` function accumulates `cnt[rel]` only when `oos_ix.get((rid, k0 + rel))` returns a non-None index (line 114-116). `oos_ix` is built from `oos` after the `pred.notna()` filter at line 71. A bar k is absent from `oos_ix` if the IS reference set at that bar had fewer than 200 samples (line 58 skip condition). Bars 4-8 (the pre-window for a k0=9 trade) over 4 IS years (2021-2024) are high-traffic and almost certainly exceed 200 samples in practice, so the practical impact is negligible. But the guarantee is not structural: if bar 4 IS had fewer than 200 samples, all cohort members with k0=9 would silently contribute zero to cnt[rel=-5], making the reported N at t=-5 lower than the stated cohort size.

**Recommended fix (do not apply):** Add an assertion after the KNN loop confirming that bars 4 through 28 all received predictions (i.e., `assert oos[oos.k.between(4, 8)].pred.notna().all()`). Alternatively, print the per-bar pred coverage before the cohort analysis and compare against the cohort size.

---

### [N2] `bar4_knn_warning_fixed_cohort.py:137` — `ctrl_ok` exclusion boundary is correct but has an invisible no-op zone for the minimum-wbar case

For a warned trade with `wbar[rid] == MIN_WARN_BAR == 9`, the exclusion condition `k >= wbar[rid] - 5` evaluates to `k >= 4`. Since `cand` already requires `k >= MIN_WARN_BAR = 9` (line 140), the effective exclusion is all k >= 9 for such a trade — no states from it can enter the control pool. This is the correct behavior. However, for warned trades with wbar[rid] > MIN_WARN_BAR, early states k = MIN_WARN_BAR .. wbar[rid]-6 remain eligible for the control pool. For example, a trade with wbar=15 contributes states k=9..9 (k < wbar-5=10) as potential controls. This is the intended audit-fixed design (including warned trades' genuinely healthy early states). The boundary arithmetic is correct, but it is non-obvious; a reader could mistake it for a leak. No bug here.

**Recommended fix (do not apply):** Add a comment at line 137 clarifying that `cand` has already enforced `k >= MIN_WARN_BAR`, so the effective exclusion zone per warned trade is `k in [max(MIN_WARN_BAR, wbar[rid]-5) .. wbar[rid]-1]`, and states strictly before wbar[rid]-5 remain eligible as controls.

---

### [N3] `bar4_knn_warning_fixed_cohort.py:126,37` — Cohort restricts to late-warnees (bar >= 9); World A/B conclusion does not generalize to early-warning trades

`MIN_WARN_BAR = 4 + K = 9` excludes trades that warn at bars 4-8. This is a selection for window-availability, not a causal or quality filter. Trades that warn at bar 4 (the earliest possible bar) represent regimes where KNN deteriorates within one bar of entry — by definition, the pre-window t=-5..−1 does not exist for them. By restricting to late-warnees, the cohort is implicitly selecting regimes that:
- Survived long enough to accumulate MFE through at least bar 8 before warning.
- Had a healthy CONT period of at least several bars (wbar-4 bars of CONT classification after the first CONT bar).

This population is structurally different from early-warnees. The World A (sudden) vs World B (gradual) classification from the fixed cohort applies only to the late-warning subpopulation and cannot be extrapolated to the full set of KNN-warned trades without a separate analysis of early-warning behavior. This is an intentional methodological tradeoff (pre-window availability requires it), but the output report does not state this restriction explicitly. If the decay pattern among early-warning trades is predominantly World A (immediate collapse at bar 4-5 = the warning IS the event, no pre-cursor), the aggregate conclusion about KNN opportunity monitoring could be distorted toward World B because the World A cases were excluded by design.

**Recommended fix (do not apply):** Add a limitation section to the output report (`bar4_knn_warning_fixed_cohort.md`) noting that the cohort covers wbar >= 9 and that early-warning trades (wbar 4-8) are excluded. Report the fraction of total warned trades excluded by the MIN_WARN_BAR filter (i.e., `len([r for r in wbar if wbar[r] < MIN_WARN_BAR]) / len(wbar)`) and, if material, characterize their World A/B behavior in a separate table with the acknowledged caveat that pre-window metrics are unavailable.

---

## Clean Checks

**A1.** No `ts_event` or `ts_init` timestamps appear in the fixed-cohort script; all bar indexing uses integer column positions in the M matrices built by `P.build()`. No NT timestamp mis-binning possible.

**A2.** Data ingestion uses `b.ts_init` (early_health_filter.py:175), which is correct — 1s bars carry `ts_init = ts_event + 1s`. The 1m resampling is handled by the live `TimeframeAggregator` inside CapsuleReplay, which is an NT streaming engine (not pandas resample). Catalog is `NQ_v0_2020_2026` (v.0 volume-continuous per repo rules). No `closed='right'` resample bug.

**B1.** No `rolling`, `ewm`, or `expanding` calls with `center=True` in any audited file.

**B2/B3.** `build_states` (bar4_knn_path_atlas.py:65-123) computes all state features from columns 4 through k inclusive (`H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]`) and forward metrics from columns k+1 onward (`fb = np.arange(k+1, ni+1)`). No column > k appears in state features.

**B4.** No `.shift(-N)` or negative-lag operations anywhere in the fixed-cohort script or its imports.

**B5.** No `ffill()` or `bfill()` calls in the audited scope.

**C1/C2.** `realized()` in the fixed-cohort script (lines 87-105): forward slices use `H[i, k+1:hi+1]` and `L[i, k+1:hi+1]` strictly. `peak_k` uses columns 4 through k (causal running peak). Direction handling is correct: longs check H for new-highs, shorts check L for new-lows (line 95). `rmfe` correctly uses `fh - cnow` for longs and `cnow - fl` for shorts (line 102).

**C3.** IS/OOS split is strictly temporal: `S[S.year < 2025]` as IS, `S[S.year >= 2025]` as OOS (line 50). KNN standardization uses IS-only mean/std (lines 63-64). `pred`, `pRun`, `pFail`, `eMFE` are derived from IS neighbors' labels and values applied to OOS queries only (lines 66-69). No OOS information enters IS reference.

**D1 (train/serve).** This is a descriptive event study with no trading logic and no model artifact. KNN is used as a smooth continuous estimator (eMFE = neighbor mean of rem_mfe). No ONNX export, no sklearn pipeline persisted. Out of scope.

**D2 (control pool integrity — C2/W1 fix).** The prior audit found that the original control pool excluded entire warned-trade histories. The fix is confirmed: `ctrl_ok` at line 134-139 only excludes a warned trade's states at `k >= wbar[rid] - 5`, allowing its states at `k < wbar[rid] - 5` to remain eligible as controls. `cand` at line 140 already restricts to `pred.isin(CONT)` and `k >= MIN_WARN_BAR`, so the union of filters is: CONT-predicted, age >= 9, and not within 5 bars of any warning. Warned trades' genuinely healthy early states are included. Fix verified correct.

**E4 (no future-indexed order submission).** No trading logic is present. This is a descriptive event study only.

**F3 (timestamp handling).** `early_health_filter.py:175` uses `b.ts_init` for 1s bars, which equals `ts_event + 1s` for NT 1s bars — i.e., the bar CLOSE time. This is the correct NT convention. The `CapsuleReplay.on_bucket_closed()` triggers only on completed 1m bar events, so all capsule data reflects bar-CLOSE information.

**G1.** Catalog uses `NQ.v.0` volume-continuous data (repo rule, confirmed by CATALOG path = `NQ_v0_2020_2026`). No c.0 roll-day contract spreads.

---

## Interpretation Caveat (not a bug)

The fixed-cohort design cleanly solves the composition-shift problem. The World A/B read from `nh3` trajectory shape and `eMFE` drift is methodologically sound for the audited population. The one caveat that belongs in the output (see N3): the cohort is restricted to late-warnees by construction, and the fraction of total KNN-warned trades excluded should be stated. If early-warning trades predominate and they are pure World A (no pre-cursor), the aggregate picture of KNN as an "opportunity-state monitor with gradual decay" would be overstated. This is not an audit finding (there is no data leak or bias introduced) — it is an interpretation-scope caveat.

---

*Audit complete. 0 CRITICAL, 0 WARNING, 3 NOTE. Findings reflect read-only static analysis of bar4_knn_warning_fixed_cohort.py and its direct imports. Dynamic runtime behavior and actual cohort N values are out of static scope.*

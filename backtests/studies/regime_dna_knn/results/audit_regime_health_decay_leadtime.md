# Look-Ahead & Timestamp Audit — Regime Health Decay Lead-Time Diagnostic

**Date:** 2026-06-16
**Auditor:** lookahead-auditor v1
**Scope:**
- `studies/regime_dna_knn/regime_health_decay_leadtime.py` (primary)
- `studies/regime_dna_knn/progressive_separability.py` (supporting: `build`, `feats_through`, used by `feats_at`)
- `studies/regime_dna_knn/early_health_filter.py` (supporting: `compute_labels_features`, capsule column convention)

> Note: this file was persisted manually from the auditor's returned findings on 2026-06-16
> (the subagent reported in chat but did not write the file during its run). Content is the
> auditor's verbatim report. The W2 fix below was subsequently applied; W1 was waived.

---

## Summary

- **Critical: 0**
- **Warning: 2**
- **Info: 4**

The causal construction is **sound**. The prior `k=max(Nbar,1)` leak (fixed to `k=Nbar`) is confirmed absent. The study's NEGATIVE conclusion (health separation is concurrent/tautological, not leading) is **not inflated by look-ahead**.

---

## Critical Findings

None.

---

## Warnings

### [W1] `progressive_separability.py:109` — `fillna(0.0)` on `feats_through` return computed over the full IS+OOS dataframe

`feats_at` invokes `P.feats_through(df, M, k)` on the full `df` (IS+OOS combined), then subsets. The final `fillna(0.0)` (line 109) fills NaN globally before subsetting. For all `HEALTH_FEATS` the computation is strictly per-row (no cross-row aggregation), so the constant `0` fill is equivalent to filling each subset independently — **no actual leakage**. The fragility is structural: a future edit adding a cross-row normalization inside `feats_through` before the `fillna` would silently mix IS and OOS.

**Severity:** WARNING — no current leak, structurally fragile for future edits.
**Status:** WAIVED (per-row confirmed safe; `feats_through` is shared code used by other audited-clean callers — hardening it is out of scope for this diagnostic).

### [W2] `regime_health_decay_leadtime.py:82` — dead `m.values` guard / boolean-index fragility

`Xk = feats_at(df, M, k)[m.values if hasattr(m, "values") else m]` — `m` is always a numpy boolean array here, so the `hasattr` branch is dead code. Boolean-indexing the returned DataFrame is safe given the default RangeIndex (guaranteed by `reset_index(drop=True)` at load), but is fragile if `df` ever arrives with a non-default index. The OOS path at line 100 uses the strictly-safe `.iloc[gi]` (integer position).

**Severity:** WARNING — no current bug, index-alignment risk for future edits.
**Status:** FIXED — training-pool indexing changed to integer positions: `gi_tr = np.where(m)[0]; feats_at(...).iloc[gi_tr].values`.

---

## Info

- **[I1]** `feats_through` appends all five `pre5_*` columns, but `feats_at` subsets to `HEALTH_FEATS` which excludes them — pre-flip constants correctly kept out of the per-bar model. Clean.
- **[I2]** `mfe_full` (outcome) is computed over bars 4..n inclusive (terminal flip bar included) via `nanmax` ignoring NaN. Used only as label/cohort, never as a feature. Intentional and documented.
- **[I3]** `feats_through` close-at-obs-bar uses `np.minimum(Nbar, n)`, which for a dead regime (`n < Nbar`) would read the terminal bar — but the `n >= k` guard excludes those from scoring, so it is never read. Coupling is implicit; safe as written.
- **[I4]** `HEALTH_FEATS` includes `mfe`, `mae`, and `health = mfe/max(mae,0.1)` — `health` is a deterministic function of the other two. Benign for LightGBM (tree model); a model-quality note, not a causality issue.

---

## Clean Checks

- **B2/B3:** `feats_through(df, M, k)` slices strictly `[:, :k+1]` (bars 0..k). Prior `k=max(Nbar,1)` leak confirmed fixed at `progressive_separability.py:59` (`k = Nbar`). No window-widening guard remains.
- **B4:** No `.shift(-N)` in feature path. `reach2`/`lose`/`fail` are forward outcomes used ONLY as labels/cohort masks (lines 84, 106, 133-134), never as features.
- **B7:** No `StandardScaler`/population normalization in the study; LightGBM fit on IS pool only (line 89). `feats_through` normalization is per-row by regime-level constants (atr, a20) captured at flip time.
- **C3/C4:** IS = `year<2025`, OOS = `year>=2025`, split at regime-year level (a regime belongs wholly to one year) — no temporal bleed; single model fit on IS, no OOS in training.
- **E5:** `alive = n >= 4` minimum enforced before scoring; features only for `k >= 4`.
- **G1:** Catalog `NQ_v0_2020_2026` (volume-continuous `NQ.v.0`) per the HARD RULE — no calendar-roll contamination.

---

## Conclusion on the Study's Central Claim

The causal apparatus is sound. The `mfe` feature tautologically encodes past excursion, creating CONCURRENT separation between cohorts — but that is precisely the observation the study is designed to detect, not a leak. The j=5 flip-aligned gap reflects information genuinely available at bar `n-5` (mostly MFE-so-far), not a leading predictive signal. The study correctly distinguishes "born unhealthy" vs "decayed from health," and the negative verdict (no usable lead time at 1m) is supported by the causal construction. A leak, if present, would only have made the negative look falsely positive — none found.

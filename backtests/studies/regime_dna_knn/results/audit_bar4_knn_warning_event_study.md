# Look-Ahead & Timestamp Audit

**Date:** 2026-06-17T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/bar4_knn_warning_event_study.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (`build_states`, `A.FEATS`, `A.BARS`)
- `studies/regime_dna_knn/progressive_separability.py` (`P.build`)
- `studies/regime_dna_knn/early_health_filter.py` (`E.compute_labels_features`, capsule build)
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 2
- Note: 3

---

## Critical Findings

None.

---

## Warnings

### [W1] Control-pool exclusion creates a directional bias toward World B

**File:** `bar4_knn_warning_event_study.py`, lines 148–152

**Code:**
```python
cand = oos[oos.pred.isin(CONT) & ~oos.rid.isin(warned)].copy()
```

**Description:**

`~oos.rid.isin(warned)` excludes every state row from every trade that fires a CONT→DETER warning anywhere in bars 4–28, including all the pre-warning CONT states of those trades. Specifically: if trade T warns at k0=15, its state rows at k=4,5,...,14 (all CONT-predicted, potentially healthy) are excluded from the control pool.

This is structurally distinct from the user's prior C2 leak (which excluded entire warned-trade histories from outcome tables) but produces a directional bias of the same sign:

- The warning trajectory (World A/B hypothesis) includes pre-warning states drawn from trades that eventually degraded enough to cross the warning threshold.
- The control trajectory is drawn exclusively from trades that never degraded (no warning anywhere in bars 4–28) — not only at the control anchor bar, but for the entire trade lifetime.

The result: the control's pre-event opportunity metrics (pRun, nh3, rmfe) are drawn from a population of globally clean trajectories, while the warning pre-event metrics reflect trades that, by selection, experienced a health transition somewhere. This inflates the pre-event gap between warning and control, making **World B (gradual decay) look stronger than the data actually supports**.

**Quantitative risk:** Substantial. Trades that warn tend to be structurally different from non-warning trades (that is the whole premise of the warning signal). Excluding ALL their pre-warning states removes the most relevant comparable population — "trade was healthy at rel=-5, then degraded" — from the control pool. The control becomes "trade was healthy at rel=-5 AND stayed healthy forever." If healthy-then-degraded trajectories exist in meaningful numbers, the pre-event gap is inflated.

**Directional bias statement:** This bias will make World B appear stronger and World A weaker. If the study concludes World B, that conclusion should be considered provisionally suspect until the control is rebuilt with the fix below. If the study concludes World A (no pre-warning decay), the bias argues against that finding — a World A conclusion is therefore robust to this bias direction.

**Recommended fix (do not apply):** Replace the blanket exclusion with a per-state exclusion. Allow a warned trade's states to enter the control pool provided that specific state is at least some buffer before the warning and is predicted CONT. A conservative version: allow states from warned trades where `k < wbar[rid] - 5`, i.e., the state is more than 5 bars before the warning fire. This retains the design intent (control states have no DETER predicted in their next 5 bars) while removing the tautological "globally clean trade" selection criterion. Concretely, replace line 148 with:

```python
# Include a warned trade's pre-warning CONT states (with buffer) as valid controls.
# Only exclude states that ARE the warning bar or within 5 bars before it.
def not_near_warning(rid, k):
    w = wbar.get(rid)
    return w is None or k < w - 5

cand = oos[
    oos.pred.isin(CONT) &
    oos.apply(lambda r: not_near_warning(r.rid, r.k), axis=1)
].copy()
```

Then the `stable()` filter still applies to remove states with DETER predictions in their own next 5 bars, ensuring the control represents locally-stable CONT states regardless of which trade they come from.

---

### [W2] `stable()` uses the control trade's global `deter_bars` (future KNN predictions) as a selection gate

**File:** `bar4_knn_warning_event_study.py`, lines 149–152

**Code:**
```python
def stable(rid, k):
    db = deter_bars.get(rid, set())
    return not any((k + 1) <= b <= (k + 5) for b in db)
cand = cand[[stable(r, k) for r, k in zip(cand.rid, cand.k)]]
```

**Description:**

`deter_bars[rid]` (line 80) contains every bar index where the trade's KNN prediction was DETER, across the full observed window (bars 4–28). The `stable()` check at state (rid, k) asks: does any future bar in (k, k+5] have a DETER KNN prediction?

This is a forward-looking selection criterion (it uses KNN outputs at bars k+1 through k+5 to decide whether bar k is a valid control anchor). This is **intentional by design** and is correctly described in the file's docstring — the study wants control states that are "locally stable" for 5 bars forward. A descriptive World A/B comparison requires a control group that does not transition, so this is sound.

The residual concern is the **interaction with W1**: when combined with the blanket `~warned` exclusion, `stable()` adds a second layer of forward filtering. For the fix in W1 (allowing pre-warning states from warned trades), the `stable()` condition already handles the key exclusion: any state within 5 bars of a warning fires DETER in bars (k, k+5] by definition, so those states would naturally be filtered out by `stable()` without needing the blanket `~warned` exclusion.

This warning is filed to document that `stable()` is a **forward-looking selection gate** applied to control candidates. This is appropriate for control group membership but would be an error if applied to the warning group or to any causal metric computation. Confirm: `stable()` is used only for control candidate filtering at lines 149–152; it is never applied to the warning group or to any metric computation path. Confirmed clean.

**Severity rationale:** Filed as Warning rather than Critical because the design intent is legitimate and documented. The concern is the interaction with W1, not a standalone error.

---

## Notes

### [N1] `A.BARS` module-attribute mutation and `A.FEATS` constant sharing

**File:** `bar4_knn_warning_event_study.py`, line 42

**Code:**
```python
A.BARS = list(range(4, 29))
```

**Description:**

`bar4_knn_path_atlas` defines `BARS = list(range(4, 16))` at module scope (line 24 of `bar4_knn_path_atlas.py`). The event study mutates this at runtime: `A.BARS = list(range(4, 29))`. `build_states` uses `BARS` as a loop bound (line 65: `for k in BARS`). This works correctly — widening `BARS` adds state rows for k=16..28 with the same per-bar causal logic. No bias introduced.

However, if any other import of `bar4_knn_path_atlas` in the same process re-reads `A.BARS` after this mutation, it will see the widened range. In this script's execution context (single-process, no parallel imports), this is harmless. Note for defensive hygiene: prefer passing `bars` as a parameter to `build_states` rather than mutating the module attribute.

`A.FEATS` (the feature list) is shared by reference and not mutated. Clean.

---

### [N2] `build_traj` accumulates realized metrics for pre-warning bars that include the warning horizon

**File:** `bar4_knn_warning_event_study.py`, lines 118–137

**Description:**

At relative bar rel=-3, `k = k0 - 3`. The call `realized(i, k)` computes forward outcomes from bar k+1 onward to `ni` (end of regime). This means the realized metrics at rel=-3 (e.g., `rmfe`, `fl3`) include what happens at and after the warning bar (k0). This is correct and expected for an event study — the forward outcomes at pre-warning bars DO span the warning period. The study measures "how much MFE remains from 3 bars before the warning," which appropriately includes what happens after the warning.

The metrics are labeled as "realized" not "KNN estimates," so this is not a look-ahead bias. Filed as Note to confirm this design intent is understood and to flag it for result interpretation: `fl3` at rel=-3 asks "does the regime flip within 3 bars of this state?", so at rel=-3 it asks about flip within bars k0-2..k0+0, not post-warning.

---

### [N3] `warn_k` computed but never used

**File:** `bar4_knn_warning_event_study.py`, line 140

**Code:**
```python
warn_k = np.array([k for _, k in warn_events])
```

**Description:**

`warn_k` is assigned but not referenced anywhere else in the script. Dead code with no bias implications, but flagged for cleanliness.

---

## Clean Checks

The following items from the audit checklist were examined and confirmed clean:

- **KNN IS/OOS split (Checklist item 1):** IS reference = `S[S.year < 2025]`, OOS query = `S[S.year >= 2025]`. StandardScaler statistics (`mu`, `sd`) computed from IS only (lines 62–64). OOS points are only queried against the IS KNN index; no OOS label (`cls`, `rem_mfe`, `rem_mae`) enters the KNN estimate for any OOS point. The KNN outputs `pRun`, `pFail`, `eMFE`, `eMAE` are all neighbor (IS) means. Confirmed clean.

- **`build_states` per-bar causal feature construction:** At bar k, all state features (`mfe_sofar`, `mae_sofar`, `pnl_now`, `pullback`, `progress_count`, `consec_noncont`, `dist_flip_open`, `health_ratio`, `close_loc`, `range_exp`, `vol_exp`) are computed using slices `H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]`, `V[i, max(4,k-5):k+1]` — strictly through bar k. Confirmed causal.

- **`build_states` forward label columns:** `rem_mfe`, `rem_mae`, `barr`, `nh3`, `flip3`, `flip5` are computed from `fb = np.arange(k+1, ni+1)` — strictly forward of k. These are IS labels used as KNN neighbor targets, not features. Confirmed clean.

- **`realized()` direction logic:** Long (di=1): `rmfe = (fh - cnow).max()` (upward = favorable), `rmae = (cnow - fl).max()` (downward = adverse). Short (di=-1): `rmfe = (cnow - fl).max()` (downward = favorable), `rmae = (fh - cnow).max()` (upward = adverse). Both correct. New-high long: `fh.max() > peak_k` (new H above prior high). New-high short: `fl.min() < peak_k` (new L below prior low-minimum). Both correct. No direction inversion bug.

- **`peak_k` computation:** `np.max(H[i, 4:k+1])` for long, `np.min(L[i, 4:k+1])` for short — running peak through bar k, causal. No data from k+1 onward.

- **Event alignment causality (Checklist item 2):** Pre-warning states at rel<0 use `oos_ix.get((rid, k0+rel))` to retrieve the state row at bar `k0+rel`. That row's KNN metrics (`pRun`, `pFail`, `eMFE`, `eMAE`) were computed from features strictly through bar `k0+rel`. The warning bar index `k0` is used only as an alignment anchor for the `rel` offset — it is not passed into any feature computation or KNN lookup for the pre-warning bars. Confirmed: event alignment is retrospective and does not contaminate pre-warning metrics with post-warning information.

- **`A.BARS` widening causality:** `build_states` uses `BARS` only as a loop bound for k (line 65: `for k in BARS`). Widening to range(4,29) adds more per-bar state rows. The per-bar causal logic inside the loop is unchanged. No look-ahead introduced by widening. Confirmed clean.

- **Warning event identification:** Lines 75–86 scan each trade's KNN prediction sequence in bar order. `seen=True` is set on first CONT prediction; the warning bar is the first subsequent DETER prediction. This correctly identifies the first CONT→DETER transition. No forward information used in this detection — it processes bars in ascending k order. Confirmed clean.

- **`fl{h}` (flip-within-h) metric:** `int((ni-k) <= h)` where `ni = min(n[i], 61)`. This correctly asks whether the trade ends within h bars of k. `n[i]` is the regime length (set in `build_states` from `n_post`). Causal — uses only the known end of the regime, not a forward prediction. Confirmed clean.

- **World A/B decision logic (Checklist item 6):** Lines 204–222 read `wM[rel]["nh3"]` and `wM[rel]["pFail"]` at rel=-5 and rel=-1, which are the causal pre-warning metrics from `build_traj`. The threshold `wC[rel] >= 30` gates on sample count. Confirmed clean in code structure (subject to the W1 bias in the underlying data).

- **n<30 omission:** Lines 166–175 (`fmt` function) and lines 195–200 (Output 3 loop) both gate on `cnt[rel] < 30`. Confirmed. Sparse relative bars are omitted from output.

- **No `.shift(-N)` or negative-lag operations** in any feature path across the three imported modules. Confirmed.

- **No `bfill`, `center=True` rolling, or future-indexed join** anywhere in the three imported modules. Confirmed.

- **No `ts_event` used as close-time index:** The capsule builder in `early_health_filter.py` uses `regime_start_ts = completed.close_ts` (line 116). The event study itself operates on the state DataFrame (no raw bar timestamps in the event study pipeline). Confirmed clean.

---

## World A/B Honest-Answer Assessment

The study as written will produce a **directionally biased World A/B conclusion** due to W1. The control pool is drawn exclusively from globally non-warning trades, which are structurally "always healthy" trades rather than "healthy at this moment" trades. The pre-warning trajectory of warned trades is being compared against a tautologically cleaner reference.

**Specific impact on outputs:**
- Output 3 (Warning vs matched-control trajectory) will show the control with persistently higher `nh3` and lower `pFail` across all relative bars, including pre-warning bars. The pre-event gap will be inflated.
- The World B lead-time detection (line 211: `wM[rel]["nh3"] < cM[rel]["nh3"] - 0.10`) will trigger at earlier relative bars if the control is artificially inflated. The 0.10 threshold (10 percentage point gap) may be crossed even if the true pre-warning decay is smaller than 10pp.
- A genuine World A result (no pre-warning decay) could be obscured if the inflated control creates an apparent gap at pre-warning bars.

**Bias direction summary:** Pushes toward World B. A World B conclusion from this study should be treated as tentative, pending the W1 fix. A World A conclusion (if it survives the inflated control) is stronger evidence, because the bias argued against it.

**Recommendation:** Apply the W1 fix before treating the World A/B conclusion as reliable. The fix is non-trivial (requires rebuilding `cand` to include buffered pre-warning states from warned trades) but is mechanically straightforward using the per-state `not_near_warning()` filter described in W1.

---

*Audit complete. Findings reflect read-only static analysis. No code was modified. Dynamic bugs (e.g., numeric edge cases in NearestNeighbors at k=500 on small IS slices) are out of scope.*

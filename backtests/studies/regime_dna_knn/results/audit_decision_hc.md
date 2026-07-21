# Look-Ahead & Timestamp Audit — decision_hc_studies.py / decision_hc_sprint.py

**Date:** 2026-06-18T00:00:00Z  
**Scope:**
- `studies/regime_dna_knn/decision_hc_studies.py`
- `studies/regime_dna_knn/decision_hc_sprint.py`
- `studies/regime_dna_knn/early_health_filter.py` (capsule builder + `compute_labels_features`)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (`build_states`, `FEATS`, hC inputs)
- `studies/regime_dna_knn/progressive_separability.py` (`build` — constructs H/L/C/O/V/n matrices)

**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 2
- Warning: 4
- Note: 3

---

## Critical Findings

### [C-SURV-1] `decision_hc_studies.py:411–412` / `decision_hc_sprint.py:364–365` — Study 3 (Peak-Decay Exit) population silently excludes ~22% of all NT-detected flips

**Category:** Survivor bias / population selection  
**Severity:** CRITICAL

**The definitive answer to the user's question:** The headline "Peak-Decay Exit" result (Study 3 in `decision_hc_studies.py`, Study 2 in `decision_hc_sprint.py`) is computed on a **survivor-biased subset**. Both files contain an explicit per-row guard that skips any regime that did not survive past bar 4:

```python
# decision_hc_studies.py lines 411–412
for _, r in df.iterrows():
    if r["n_post"] < 4: continue  # only look at regimes that live past bar 4
```

```python
# decision_hc_sprint.py lines 364–365
for _, r in df.iterrows():
    if r["n_post"] < 4: continue
```

This filter silently removes all "QuickFailure" regimes (defined in `early_health_filter.py:285` as `npost < 5`; those with `n_post == 1, 2, or 3` are excluded by the `< 4` guard). According to the note already in the project memory (`knn_health_early_entry.md`, referenced in the user's briefing), approximately 22% of NT-detected flips are QuickFailures that die before bar 5. Those trades are the fastest and largest losers in the raw distribution. By dropping them from the denominator before computing expectancy, the reported baseline and "Decay 20%" expectancy numbers (+$15.73/tr and +$15.49/tr) are measured against a pre-filtered population, not the full live-trading universe.

**Mechanism:** The `early_health_capsule.parquet` file (built by `early_health_filter.py`) contains the FULL set of NT-detected flips (all `n_post` values). The capsule is not itself filtered. The survivor filter is applied inline during the Study 3 simulation loop. Any regime that lives only 1, 2, or 3 bars is skipped — its losses never enter the PnL array.

**Scope of impact:** Study 3 / Study 2 (Peak-Decay Exit, the headline "Most Promising Rule"). Study 1 (HardStall Fork Analysis in `decision_hc_studies.py`) and Study 5 (First-Bar hC Predictor) also apply `n_post_val < 4: continue` at lines 542 and 563 respectively. Studies 2, 4, and 6 in `decision_hc_studies.py` operate on `va_trades` (the V_A-filtered subset), which is a separate concern (see C-SURV-2 below).

**Quantitative framing from prior work:** The project memory entry for `knn_health_early_entry.md` documents that when the same study was run on the full flip universe, a +$60/tr apparent edge collapsed to -$20.7/tr. The 30,730 OOS trades cited in the sprint's "baseline +$15.73/tr" headline are the n_post >= 4 survivors, not the 39,000+ full-universe OOS flips.

**Recommended fix (do not apply):** Remove the `if r["n_post"] < 4: continue` guard from the Study 3 simulation loop. For regimes with `n_post < 4`, simulate what actually happens: the trade either stops out or exits at the close of the last post-flip bar before the opposite flip. These trades need to be included in the PnL distribution at face value. Run the full population baseline first to establish what the true no-filter expectancy is before interpreting any "Peak-Decay Exit" lift.

---

### [C-BARMODE-1] `decision_hc_studies.py:230–235`, `367–372`, `488–500`, `561–573` / `decision_hc_sprint.py:318–325`, all stop-fill lines — Catastrophic stop filled at stop price using 1m-bar intra-bar level touch

**Category:** Bar-mode simulation overstates edge (E3, B2)  
**Severity:** CRITICAL

All stop fills in both files follow the pattern:

```python
# Representative — decision_hc_studies.py lines 230–235 (sim_exit_study)
# decision_hc_sprint.py lines 318–325 (sim_decay_study), identical pattern
if (d_val == 1 and bl <= stop) or (d_val == -1 and bh >= stop):
    exit_px = stop - d_val * EXIT_SLIP_T * TICK
    reason = "stop"
    break
```

The stop price used is the static level `(flip_l - TICK)` for longs or `(flip_h + TICK)` for shorts (set at entry). When the 1m bar's low/high touches or breaches that level, the code credits a fill at exactly `stop ± EXIT_SLIP_T * TICK`. This is a 1m-bar intra-bar level-touch fill — a simulation mode that the project has already documented inflates PnL by $15–25K/year on fade strategies (MEMORY.md: `bar_mode_overstates_fade_strategies`).

The specific failure mode here: on a 1m bar where `bl <= stop` (long stop triggered), the actual fill price in live trading is determined by the next available tick after the stop level is first breached — which in fast-moving markets (the same conditions that cause stall-then-reverse) is typically several ticks through the stop level. The code credits exactly `stop - EXIT_SLIP_T * TICK` regardless. This is the same structural blind spot documented for `TAPE-REPLAY MECHANICAL EXITS` and `BE-ARMING TIMING` in the project memory.

This affects all simulated PnL in both scripts: Studies 2, 3, 4, 5, 6 in `decision_hc_studies.py` and Studies 1, 2, 4 in `decision_hc_sprint.py`.

The exit on bar close (decay exit, flip exit) is also at `bc - d_val * EXIT_SLIP_T * TICK` (e.g., `decision_hc_studies.py:244`, `decision_hc_sprint.py:333`). Bar-close exits are less problematic because a close price is known exactly, but the 1-tick exit slippage is a fixed assumption rather than empirically derived from tick data.

**Recommended fix (do not apply):** Validate any "most promising rule" candidate using 1s-bar or tick-mode NT BacktestEngine streaming before trusting the PnL headline. Per project methodology, the 1m-bar result is appropriate for directional screening but not for a deployment claim. A 1s-bar re-run of the "Decay 20%" rule is required before citing its OOS PnL as meaningful.

---

## Warnings

### [WARN-1] `decision_hc_studies.py:192–200` / `decision_hc_sprint.py:122–129` — V_A percentile gates computed on IS-only but applied to the combined df (IS + OOS together); slight information leak for OOS years 2021–2024 that were included in IS

**Category:** B7 (normalization/thresholds from the right window)  
**Severity:** WARNING

The V_A filter percentile gates (`p70_eff`, `p40_comp`, `p60_vol`) are computed on `is_df = df[df.year < 2025]`. This is correct — the percentiles do not see OOS data. However, the IS window includes 2021 data (`IS_YEARS = [2021, 2022, 2023, 2024]` in `early_health_filter.py`), and the walk-forward KNN loop (`decision_hc_studies.py:42–68`) starts at year 2022 using only year < 2022 as training data. Year 2021 states are dropped after KNN scoring (line 75: `S = S[S.pred.notna()]`) because 2021 has no training set. Yet the percentile gates that define V_A membership include 2021 in `is_df`. This means the V_A gate is calibrated partially on regimes that are later excluded from KNN-driven studies. This is a minor inconsistency, not a major leak, but the V_A population definition is slightly contaminated by 2021 data.

**Recommended fix (do not apply):** Compute V_A percentile gates from `df[df.year.isin([2022, 2023, 2024])]` (the years that actually feed KNN training), or at minimum, document that 2021 is included in the IS gate but excluded from KNN scoring.

---

### [WARN-2] `decision_hc_studies.py:75–88` / `decision_hc_sprint.py:84–88` — `hC_pk` (cummax) and `dd` computed on the post-filter S frame; if any bar k for a regime is missing from S, the cummax restarts incorrectly

**Category:** B5 (sequential computation with possible gap)  
**Severity:** WARNING

After the walk-forward KNN loop, both scripts filter `S = S[S.pred.notna()]` then compute:

```python
g = S.groupby("rid")
S["hC_pk"] = g.hC.cummax()
S["dd"] = 1 - S.hC / S.hC_pk.clip(lower=1e-6)
```

`cummax()` is a strictly backward-looking operation on the sorted dataframe (sorted by `["rid", "k"]` just before), which is correct as long as no bar k is missing from a regime's sequence. However, `build_states` in `bar4_knn_path_atlas.py` only creates state rows where `n > k` (line 66: `act = np.where(n > k)[0]`). With `BARS = list(range(4, 29))`, a regime with `n_post = 7` will have state rows at k=4, 5, 6 and then stop. The cummax at k=6 correctly reflects the peak of hC across bars 4–6. This part is clean.

The warning is different: the KNN training pool for bar k at year Y requires `len(isk) >= 100` (line 51). If a specific bar k has fewer than 100 IS observations, that bar's states are skipped entirely, leaving gaps in the per-regime hC sequence. A regime might have hC scored at k=4, 6, 7 but not k=5 (if k=5 training pool was < 100 for that year). The cummax would then jump from k=4 to k=6, and any exit-rule trigger at k=5 would silently fall through the `if feat and feat["dd"] >= thresh` guard (since k=5 has no entry in `hs_info`). This means some bar-5 decay signals are never fired, marginally biasing exit timing toward later bars.

**Recommended fix (do not apply):** Assert that no gaps exist in per-regime k sequences after KNN scoring, or explicitly document that bars with insufficient training pool are dropped and this affects when decay exits can fire.

---

### [WARN-3] `decision_hc_studies.py:127–143`, `149–157` / `decision_hc_sprint.py:429–434` — Study 3 atlas and Study 1 Study 3 "new high" computation uses the peak price `H[i_idx, 4:k+1].max()` at the first-HardStall bar, computed from the beginning of the trade; this includes ALL data up to k and is clean, but the "forward new-high" lookup `H[i_idx, k+1:future_k_max+1]` requires that `H` matrix padding is correct

**Category:** B2 (indicator values at correct bar)  
**Severity:** WARNING

In `decision_hc_studies.py:143–148` (Study 1) and `decision_hc_sprint.py:445–450` (Study 3 atlas), the "forward new-high" excess is computed as:

```python
peak_px = H[i_idx, 4:k+1].max() if di == 1 else L[i_idx, 4:k+1].min()
fH = H[i_idx, k+1:future_k_max+1]
fL = L[i_idx, k+1:future_k_max+1]
excess = ((fH.max() - peak_px) if di == 1 else (peak_px - fL.min())) / ai
```

The `H` and `L` matrices come from `P.build(df)` (`progressive_separability.py:35–47`), which pads with `np.nan`. If `future_k_max` is beyond `n[i_idx]` (i.e., beyond the last post-flip bar), the slice includes NaN columns. `fH.max()` of a NaN array will issue a warning and return NaN, but with `np.nanmax()` not used here, `fH.max()` on an all-NaN slice returns NaN, which would make `excess = NaN - peak_px = NaN`, causing `nh05 = int(NaN >= 0.5)` to evaluate as `int(False) = 0`. This is a silent false-negative: forward new-highs that could theoretically be measured are counted as 0 when the future window extends past the regime end.

However, `future_k_max = min(k + hor, nf - 1)` clips to `nf - 1` where `nf = n[i_idx]`, so `H[i_idx, k+1:nf]` should always be in-bounds for valid data. The risk is whether `nf` was correctly set in `build_states`. In `build_states` (`bar4_knn_path_atlas.py:68`): `ni = int(min(n[i], 61))`, and the loop uses `H[i, 4:k+1]` up to k. Given `BARS = list(range(4, 29))` and H has 62 columns (index 0..61), this is in-bounds. This is a warning (potential off-by-one on the matrix width for very long regimes clipped to 61) rather than a confirmed bug, but the computation should use `np.nanmax` to be defensive.

**Recommended fix (do not apply):** Replace `fH.max()` and `fL.min()` with `np.nanmax(fH)` and `np.nanmin(fL)` for defensiveness, and add an assertion that `future_k_max <= ni` before slicing.

---

### [WARN-4] `decision_hc_sprint.py:269–275` (Study 1 Interpretation A metrics calculation) — Interpretation A IS/OOS split has a dead-code bug that computes IS metrics twice before the correct split

**Category:** Code integrity / data integrity  
**Severity:** WARNING

In `decision_hc_sprint.py:269–275`:

```python
# Interpretation A metrics
met_is_a = calc_s1_metrics(pnls_a)       # line 270 — BUG: operates on full array
met_oos_a = calc_s1_metrics(pnls_a)      # line 271 — BUG: same as above
# Re-split for IS / OOS correctly
p_a = np.array(pnls_a)
met_is_a = calc_s1_metrics(p_a[is_mask])   # line 274 — correct
met_oos_a = calc_s1_metrics(p_a[oos_mask]) # line 275 — correct
```

Lines 270–271 compute IS and OOS as identical (both operating on the full unsplit `pnls_a` array). These results are immediately overwritten by lines 274–275, so the final values written to `s1_a_results` are correct. This is dead code with the wrong computation, not a live reporting bug. However, it creates a maintenance risk: if someone moves or re-orders the lines, the dead code paths become live and produce wrong numbers. The IS/OOS split for Interpretation B (`decision_hc_sprint.py:279–282`) does not have this issue.

**Recommended fix (do not apply):** Delete lines 270–271. The correct IS/OOS split is already done at lines 273–275.

---

## Notes

### [NOTE-1] `decision_hc_studies.py:43` / `decision_hc_sprint.py:43` — 2025 and 2026 both use `S[S.year < 2025]` as KNN training set (frozen at 2024 cutoff), not a true rolling walk-forward for 2026

Both scripts use the walk-forward loop:

```python
for year in [2022, 2023, 2024, 2025, 2026]:
    db = S[S.year < year] if year < 2025 else S[S.year < 2025]
```

For years 2025 and 2026, the KNN training database is the same frozen set (years < 2025). This means year 2026 states are scored using a KNN model trained on 2021–2024, ignoring 2025 data entirely. This is conservative (2025 is not contaminated into 2026 evaluation) but slightly suboptimal — 2025 could be used as training data when predicting 2026. More importantly, the combined "OOS" label (years >= 2025) spans both 2025 and 2026, and the hC values for 2026 rows were computed using a smaller training set than 2025 rows. The two OOS years are not equivalent in their KNN quality. This is not a bias in the sense of look-ahead, but it means OOS metrics blend two cohorts with different model quality.

---

### [NOTE-2] `bar4_knn_path_atlas.py:65–66` — `build_states` `n > k` condition means the final bar of each regime (the flip bar) is never included as a state row

The loop `act = np.where(n > k)[0]` with `k` starting at 4 means a regime with `n_post = 5` has states at k=4 only (requires n > k, i.e., n=5 > k=4). The bar at k=5 (the flip bar close, where post_c[-1] lives) is never a state row. This is logically correct — by the time bar k is processed, the regime is already flipped, and hC cannot be computed. But it means the decay-exit simulation in the decision scripts can never fire a "decay" exit on the final bar; those trades always exit via the "flip" path. This is clean behavior but should be noted: some exit signals that would fire in bar n_post are silently absorbed into "flip" exits.

---

### [NOTE-3] `decision_hc_studies.py:32` / `decision_hc_sprint.py:32` — `flip_c` variable computed but never used in either script

```python
# decision_hc_studies.py:32 and decision_hc_sprint.py:32
entry4 = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
```

`flip_c` is defined at the top level of `main()` in both scripts. It is only used in `decision_hc_sprint.py:499` inside Study 4 (HardStall Transition Atlas), where it provides the hold-to-flip exit price: `exit_px = flip_c[i_idx] - di * EXIT`. This is correct: `post_c[-1]` is the close of the last post-flip bar (the bar at which the opposing regime flips), which is the natural exit point for a hold-to-flip strategy. In `decision_hc_studies.py`, `flip_c` is defined but never referenced. This is dead code / minor inconsistency, not a bug.

---

## Clean Checks

The following items were verified and found clean:

- **A1/A2 (timestamp conventions):** These are offline pandas simulation scripts, not live NT strategies. No `ts_event` vs `ts_init` distinction applies. The capsule builder (`early_health_filter.py:175`) correctly reads `b.ts_init` from catalog bars and uses it for year-boundary filtering (`regime_start_ts >= yr0`). Clean.

- **A5 (resampling convention):** `early_health_filter.py` does not resample bars — it reads 1s bars from the NT catalog and feeds them through the NT `TimeframeAggregator`. The catalog is the `NQ_v0_2020_2026` v.0 volume-continuous catalog per project rules. No `closed`/`label` pandas resample call is present. Clean.

- **B1 (no center=True rolling):** No `rolling(..., center=True)` calls found in any of the four files. Clean.

- **B4 (no `.shift(-N)` in features):** No `.shift(-N)` or negative-lag operations in feature paths. The `shift(-N)` construct does not appear anywhere in any of these files. Clean.

- **B5 (no bfill):** No `.bfill()` operations found. Clean.

- **B6 (merge alignment):** No cross-frequency merges or `merge_asof` calls in these files. The capsule already contains the full post-flip bar array inline. Clean.

- **hC causality (checklist item A3/B3):** `hC = pNH3 - pFL3` where each is the mean of KNN neighbor labels at bar k. The KNN features (`FEATS` in `bar4_knn_path_atlas.py:33`) are `["bar_idx", "mfe_sofar", "mae_sofar", "pnl_now", "pullback", "progress_count", "consec_noncont", "dist_flip_open", "health_ratio", "close_loc", "range_exp", "vol_exp"]`. All of these are computed from `H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]` — data strictly through bar k (`bar4_knn_path_atlas.py:69–90`). The cummax `hC_pk` is a pandas groupby-then-cummax on the already-sorted-by-k frame, which is a backward-looking running maximum. Clean: hC and its peak/drawdown are strictly backward-looking at each bar k.

- **C3 (train/test split temporal):** IS = years < 2025, OOS = years >= 2025. Walk-forward KNN uses only past years as training at each query year. No random split. Clean.

- **C4 (walk-forward no overlap):** KNN training set for year Y uses `S.year < year` (or `< 2025` for 2025/2026). No overlap between training and test windows. Clean.

- **D1 (train/serve consistency):** Not applicable — these are offline research scripts, not paired with a live strategy. No ONNX model or serve-side code is present.

- **E5 (indicator warmup):** The capsule replay uses a 6-day lead-in (`lead_in_days=6`) before each year (`early_health_filter.py:162–163`) to warm up the `RegimeStateEngine` and ATR history. ATR and regime state are derived from the NT engine, not pandas. Clean.

- **F3 (timezone handling):** All internal timestamps are `int64` nanoseconds UTC from NT catalog. Year boundary filtering uses `pd.Timestamp(..., tz="UTC").value`. No naive timestamps in the capsule builder. Clean.

- **G1 (continuous contract):** Catalog is `NQ_v0_2020_2026` (volume-continuous), consistent with the project rule mandating v.0 data. Clean.

- **progressive_separability.py `feats_through` lookahead fix:** The comment at line 53–58 documents the 2026-06-15 fix where `k = max(Nbar, 1)` was replaced with `k = Nbar`. This fix is present and applied. The pre-flip window (Nbar=0) correctly uses only column 0 (the flip bar). Clean.

---

## Scope Hash

Files inspected (sha-summary, read-only static analysis):
- `decision_hc_studies.py` (869 lines)
- `decision_hc_sprint.py` (703 lines)  
- `early_health_filter.py` (649 lines)
- `bar4_knn_path_atlas.py` (443 lines)
- `progressive_separability.py` (first 140 lines covering `build` and `feats_through`)

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (race conditions, live trading sequencing) are out of scope.*

# Look-Ahead & Timestamp Audit — Precompute Mapping Scripts

**Date:** 2026-06-18T00:00:00Z
**Scope:**
- `collectors/collector_v2/extract_pqf_mapping.py`
- `collectors/collector_v2/extract_hc_perbar_mapping.py`
- `backtests/studies/regime_dna_knn/rejection_power.py` (MODEL_B, gbm)
- `backtests/studies/regime_dna_knn/progressive_separability.py` (feats_through, build, PRE5)
- `backtests/studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS)
- `backtests/studies/regime_dna_knn/early_health_filter.py` (compute_labels_features, CapsuleReplay)
- `collectors/collector_v2/aggregator.py` (bucket assignment, close_ts)

**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 1
- Note: 3

---

## Critical Findings

None.

---

## Warnings

### [B2/D1] `collectors/collector_v2/aggregator.py:98` and `early_health_filter.py:155` — ts_event parameter receives ts_init value; safe only while 1s delta=0

`TimeframeAggregator.on_1s_bar()` parameter is named `ts_event` (line 98) but `CapsuleReplay.on_1s` (early_health_filter.py line 155) passes `tsi` which is extracted as `b.ts_init` (early_health_filter.py line 175). For NT 1s bars loaded from the `NQ_v0_2020_2026` catalog, this is benign because the CLAUDE.md spec states no `ts_init_delta` is applied to 1s bars (`ts_init == ts_event` for 1s bars). However, the mismatch is invisible in the call site — if any future catalog build applies a nonzero `ts_init_delta` to 1s bars, all 1m bucket assignments would shift by the delta, silently mis-labeling every `regime_start_ts` by that amount and corrupting the live lookup key.

**Recommended fix (do not apply):** Either (a) document prominently in `on_1s_bar` that it expects `ts_init` for NT 1s bars and rename the parameter to `ts_init`; or (b) add an assertion in `run_year` that the 1s catalog was built with `ts_init_delta=0` before replay begins.

---

## Notes

### [N1] `collectors/collector_v2/extract_pqf_mapping.py:57` — walk-forward for year 2022 trains on 2021 only; small IS sample risk not guarded at feature-level

For `year=2022`, IS is `yr < 2022` filtered to `alive4`, which is 2021 data only. The `is_m.sum() < 200` guard at line 59 will skip 2022 if 2021 IS data is too sparse. However, there is no explicit warning in the output (the `print` line 68 only fires for passing years, not skipped ones), and the mapping parquet would silently contain no rows for 2022 without any log entry indicating the skip reason. If 2022 is skipped, the downstream NT strategy will find no pQF value for 2022 regimes and must handle the NaN/missing case explicitly.

**Recommended fix (do not apply):** Add a `print(f"  SKIPPED {year}: IS={is_m.sum()}, OOS={oos_m.sum()}")` in the `continue` branch at line 60, and document in the output audit report that 2022 may have no coverage.

### [N2] `collectors/collector_v2/extract_hc_perbar_mapping.py:107` — rid→regime_start_ts mapping has no gap guard

Line 107: `S["regime_start_ts"] = S.rid.map(rst).astype(np.int64)`. If any `rid` in `S` (which comes from `build_states`) is not present in `rst` (built from `df.regime_id.values`), `pandas.Series.map` silently returns `NaN`, and `astype(np.int64)` would either raise (with newer pandas) or coerce silently. In practice this cannot happen because `build_states` derives `rid` from the same `df`, but there is no assertion confirming zero nulls before the cast. A silent NaN-to-int coercion would corrupt `regime_start_ts` for affected rows.

**Recommended fix (do not apply):** Add `assert S.rid.map(rst).isna().sum() == 0, "rid mapping gap detected"` before line 107.

### [N3] `backtests/studies/regime_dna_knn/bar4_knn_path_atlas.py:132` — `knn_predict` uses a flat IS<2025 split, not year-by-year walk-forward

`knn_predict` (used only in `bar4_knn_path_atlas.py:main()` for the diagnostic study, NOT in `extract_hc_perbar_mapping.py`) uses a single IS<2025 / OOS>=2025 split (line 132). This means 2025 IS neighbors include 2021-2024 and the 2026 OOS sees those same neighbors. In `extract_hc_perbar_mapping.py`, the walk-forward is correctly year-by-year (line 61-67: `db = S[S.year < year]`). The `knn_predict` function in `bar4_knn_path_atlas.py` is strictly diagnostic (no output parquet consumed by the strategy), so this is not a production causality problem. However, callers of `bar4_knn_path_atlas.py`'s `knn_predict` should be aware that its outputs represent a pooled OOS (2025+2026 treated identically), not a true year-by-year walk-forward.

**Recommended fix (do not apply):** Add a module-level docstring note to `knn_predict` stating it uses a flat IS/OOS split and is not year-annually walk-forward. No production mapping output should be generated from this function.

---

## Verification Results — Checklist Items (PASS/FAIL)

### 1. Walk-Forward Training Integrity

**PASS.**

`extract_pqf_mapping.py:57`: `is_m = (yr < year) & alive4 if year < 2025 else (yr < 2025) & alive4`. For each test year Y in [2022..2024], IS is strictly `yr < Y`. For Y in [2025, 2026], IS is capped at `yr < 2025` — no same-year or future-year rows can enter training. The guard `is_m.sum() < 200` prevents degenerate models.

`extract_hc_perbar_mapping.py:62`: `db = S[S.year < year] if year < 2025 else S[S.year < 2025]`. Same capping logic applied per (year, k) pair. OOS query is `S[S.year == year]` — no overlap with IS. KNN neighbors (`isk`) are always drawn from `db` (IS only), never from `q` (OOS).

### 2. Feature Causality

**PASS (k=Nbar fix confirmed present).**

`progressive_separability.py:59`: `k = Nbar`. The prior `max(Nbar,1)` leak (documented in the 2026-06-15 audit, and in the MEMORY.md structural-leak entry) is confirmed replaced. Grep found zero remaining `max(Nbar,1)` or `max(window,1)` in any feature path across both the study and collector directories.

`feats_through(df, M, 3)` (called from `extract_pqf_mapping.py:50`): Slices `H[:, :k+1] = H[:, :4]` (columns 0,1,2,3 = flip bar + post-flip bars 1..3). Python half-open slice `[:4]` excludes column 4 (bar-4 OHLC). Features `mfe`, `mae`, `health`, `pullback`, `dist_flip_open`, `progress_count`, `close_prog_ratio`, `flip_open_viol`, PRE5 are all through bar-3 close or earlier. No bar-4 data enters the Model B feature matrix.

`build_states` in `bar4_knn_path_atlas.py:69`: `hk = H[i, 4:k+1]`. At k=4, this is `H[i, 4:5]` = only bar-4 data. At k=5, `H[i, 4:6]` = bars 4..5. No future bars beyond the current observation bar k are included. The entry guard `act = np.where(n > k)[0]` ensures only regimes that have completed bar k are processed.

`A.FEATS = ["bar_idx","mfe_sofar","mae_sofar","pnl_now","pullback","progress_count","consec_noncont","dist_flip_open","health_ratio","close_loc","range_exp","vol_exp"]` — all are computed from bars 4..k only. None of the forward outcome columns (`flip3`, `flip5`, `newhigh3`, `cls`, `tot_mfe`, `final_pnl`, `rem_mfe`, `rem_mae`, `rem_bars`, `b0505`..`b2010`) appear in `A.FEATS`.

### 3. Label Causality — newhigh3, flip3, QuickFailure not fed as features

**PASS.**

`newhigh3` (`nh3`) is computed from `fb = np.arange(k+1, ni+1)` (bar4_knn_path_atlas.py:91) — bars strictly after the current observation bar k. It is a forward outcome label stored in the DataFrame and used ONLY as a KNN neighbor target from IS rows (`isk.newhigh3.values[idx]`). OOS regimes contribute `pNH3` (line 78 of extract_hc_perbar_mapping.py) drawn entirely from IS neighbor outcomes; the OOS regime's own `newhigh3` value is never read.

`flip3 = int(rbars <= 3)` where `rbars = ni - k` (bar4_knn_path_atlas.py:122) is a remaining-bar count — forward outcome. Same treatment as `newhigh3` above.

`cls[i]` (the trade path class: Failure/Chop/Continuation/Runner) is computed from `mfe_e` and `mae_e` over the full post-entry path (bar4_knn_path_atlas.py:56-62) — a forward outcome. Used only as IS neighbor target for majority-class voting. Not in `A.FEATS`.

`QuickFailure` (yQ) is the GBM target in extract_pqf_mapping.py, never a feature. It is only passed as `ytr` in the `gbm(XB[is_m], yQ[is_m], ...)` call (line 62), trained on IS features `XB[is_m]`. OOS labels `yQ[oos_m]` are never passed to the model.

### 4. hC_pk cummax and dhC diff(3) are backward-looking

**PASS.**

`extract_hc_perbar_mapping.py:89`: `S = S[S.pNH3.notna()].copy().sort_values(["rid","k"]).reset_index(drop=True)`. The frame is sorted by `(rid, k)` before any derived column is computed.

Line 91: `S["hC_pk"] = S.groupby("rid").hC.cummax()`. Within each rid group, rows are in ascending k order (guaranteed by the sort on line 89). `cummax()` at position k uses only hC values at bars ≤ k. Strictly backward-looking.

Line 93: `S["dhC"] = S.groupby("rid").hC.diff(3)`. `diff(3)` within a group computes `hC[row_i] - hC[row_{i-3}]`. Since rows are sorted by ascending k, this looks back 3 bar steps — never forward. For k=4,5,6 (fewer than 3 prior bars in the group), `dhC` is NaN, not a forward value.

### 5. Thresholds are IS-derived, not OOS-rank-relative

**PASS.**

`extract_pqf_mapping.py:63-66`: `pis = gbm(XB[is_m], yQ[is_m], XB[is_m])` fits the same model and scores IS features. `thr = float(np.percentile(pis, 100 - rp))` derives the reject threshold entirely from the IS pQF distribution. These thresholds are written to `pqf_is_thresholds.parquet` and are portable to live deployment. OOS pQF values `pQF[oos_m]` are produced by `gbm(..., XB[oos_m])` (line 62) and are never used to set thresholds.

### 6. Lookup-key integrity

**PASS (with audit-time verification required at join).**

`extract_pqf_mapping.py:79`: `dup = mapping.regime_start_ts.duplicated().sum()` is computed and reported in the audit document. The script halts writing the audit md file regardless of the dup count, but the value is printed. If dup > 0, the live lookup would return non-unique results.

`extract_hc_perbar_mapping.py:111`: `dupkey = mapping.duplicated(subset=["regime_start_ts","bars_in_regime"]).sum()` is computed and reported.

`bars_in_regime = k + 1` (line 108): at k=4 (bar-4 close), `bars_in_regime=5`. This matches the NT regime engine convention stated in the docstring (`bars_in_regime==5 <=> bar-4 close`). The convention is correct: if the regime engine counts completed bars including the flip bar (bar 0), then 5 bars means the flip bar plus 4 post-flip bars have closed — i.e., bar-4 is the most recent completed bar. Live consumers MUST use the same `bars_in_regime` convention or the lookup will be systematically off by one.

`regime_start_ts` is derived from `completed.close_ts` (early_health_filter.py:115), which equals `(bucket_id+1) * bucket_size_ns` from aggregator.py:130. For a 1m bar, this equals `ts_event_1m + 60_000_000_000` = the NT bar's `ts_init` (after ts_init_delta=60s is applied). The live NT strategy would look up by `bar.ts_init` at the flip bar. These values should be identical — confirmed consistent.

### 7. OOS regime's own future path does not leak into pQF or hC value

**PASS.**

For pQF: The OOS regime's `XB[oos_m]` (features through bar 3) is passed as query to `gbm(...)` which returns predicted probabilities using only the fitted model from IS data. The OOS regime's `yQ` (whether it actually quick-failed) is never read during model inference.

For hC: The KNN is fit on `Xis` (IS bar-k feature vectors). `nn.kneighbors((Xoo - mu)/sd)` finds the nearest IS neighbors and returns `idx` into `isk`. The OOS regime's own forward path (`newhigh3`, `flip3`, `cls`) is in `S` but is never accessed through `idx` — `idx` indexes `isk` (IS), and the OOS outcome values stored in `S.loc[om, ...]` are never read during the KNN inference pass.

---

## Additional Observations

### Capsule Universe Coverage

The capsule is built from the full NT-streaming regime universe (all flips, not just bar1-confirmed). The NOTE embedded in `extract_pqf_mapping.py:114-117` correctly flags that the live NT regime engine flip set must join to this mapping at a high rate. If a discrepancy exists (e.g., the capsule was filtered before writing), pQF gating would silently apply to only a subset of live flips. This self-audit note in the script is appropriate; it should be verified empirically when the live strategy runs.

### Prior Leak (k=max(Nbar,1)) — Confirmed Absent

Grep across both the `collectors/collector_v2/` and `backtests/studies/regime_dna_knn/` directories finds `max(Nbar,1)` only in comments documenting the prior bug, not in active code. The fix (`k = Nbar`) is present at `progressive_separability.py:59`. No analogous `max(window,1)` or off-by-one guard in `feats_through` or `build_states` was found.

### Direction Bug Fix in build_states

`bar4_knn_path_atlas.py:94-99`: Comment documents a 2026-06-17 fix where `rmfe`/`rmae` for short trades was previously inverted (highs used for short MFE, lows for short MAE). The fix is present in the code. This does not affect look-ahead causality — it corrects directional label accuracy for IS neighbors, which improves (but does not invalidate) the KNN hC estimates.

---

## Clean Checks

- **A1/A5** — `regime_start_ts = completed.close_ts` equals `ts_init` of the NT 1m bar (after ts_init_delta=60s). Lookup key semantics match live strategy. PASS.
- **A2** — Capsule built from 1s bars with `ts_init` passed as bucket timestamp; for 1s bars `ts_init_delta=0` so `ts_init == ts_event`. Buckets correctly aligned to minute boundaries. PASS (conditional on 1s delta=0, documented as WARNING above).
- **B1** — No `center=True` in any rolling/ewm operation. FEATS are per-row or accumulated forward from a fixed anchor (entry). PASS.
- **B2** — `feats_through(df, M, Nbar)` slices `H[:, :Nbar+1]` (bars 0..Nbar). The old `max(Nbar,1)` off-by-one is confirmed fixed (`k = Nbar` at progressive_separability.py:59). PASS.
- **B4** — No `.shift(-N)` or negative-lag operations in the feature path. `.diff(3)` in `dhC` is within-group on ascending-k sorted data — backward. PASS.
- **B5** — No `.ffill()` or `.bfill()` in any feature computation path. PASS.
- **B7** — `StandardScaler` in `progressive_separability.py:113` is fitted on `Xtr` (IS training rows) only; `sc.transform(Xte)` applies IS statistics to OOS. The KNN `mu/sd` normalization is fitted on `Xis` (IS neighbors), applied to both `Xis` and `Xoo`. Both patterns are IS-derived. PASS.
- **C1** — Forward labels (`newhigh3`, `flip3`, `cls`, `yQ`) use future data by design. Confirmed they appear only in the training target or neighbor target positions, never in `FEATS` or `MODEL_B`. PASS.
- **C3** — All train/test splits are temporal (year-by-year or IS<2025/OOS>=2025). No random splits. PASS.
- **D1** — Model B features (`feats_through(df, M, 3)[MODEL_B]`) are computed from OHLCV arrays constructed by the same `build()` function called identically in both the training context and the live `on_bar` context (via the regime engine capsule). Train/serve feature parity is maintained by design. PASS.
- **D5** — IS threshold percentiles are pre-computed and stored in `pqf_is_thresholds.parquet` — deterministic and identical between offline scoring and live deployment lookup. PASS.
- **E5** — `alive4 = npost >= 4` ensures the pQF model only scores regimes where bar 4 exists. `build_states` guard `act = np.where(n > k)[0]` ensures per-bar hC states only exist where the regime survived through bar k. No indicator values are produced for regimes that have not yet reached the observation bar. PASS.

---

*Audit complete. Findings reflect read-only static analysis of the five files listed in scope plus their direct dependencies. Dynamic runtime bugs (race conditions, catalog corruption, NT engine dispatch order) are out of scope.*

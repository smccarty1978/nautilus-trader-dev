# Look-Ahead & Timestamp Audit

**Date:** 2026-07-21 (original) · **updated 2026-07-21** (confirmatory re-audit after remediation)
**Scope:** `studies/long_rth_pure_flip_top50_top25_training/` — `implementation/build_feature_sets.py`, `implementation/train_reduced.py`, `implementation/decide.py`, `SPEC.md`, `REPRODUCE.md`, all of `results/`. Read-only upstream inputs inspected for independent recomputation: `studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv`, `studies/long_rth_mirrored_surface_top100_training/_work/{prepared,attached}_long_{2021..2026}.parquet`, `studies/long_rth_mirrored_surface_top100_training/results/top100_feature_manifest.json`, `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py` (source of reused `fit_logistic`/`fit_gbt`).
**Auditor:** lookahead-auditor v1
**Method:** All headline claims were independently recomputed from raw source files using a fresh Python process (pandas/sklearn), not read from the study's own logs/manifests, except where explicitly noted as a manifest cross-check.

## Summary (FINAL, post-remediation)

- Critical: 0
- Warning: 0
- Note: 1 (N2, informational only — no gate/decision impact)

Both items raised in the original pass (W1, N1) were remediated and independently re-verified below. **Final verdict: 0 CRITICAL, 0 WARNING — study passes acceptance.**

## Independent recomputation results (claims 1–7 + headline sanity check)

**1. TOP50/TOP25 exact-prefix claim, SHA-256 provenance.** Recomputed `sha256` of `top_100_raw_feature_columns.csv` from scratch: `6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619` — matches exactly. Re-derived the ordered top-100 list from `rank` ascending and recomputed `sha256("\n".join(names)+"\n")`: `f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992` — matches exactly. Independently truncated to `top100[:50]` and `top100[:25]` and hashed: `5a2b1a70ebaff75ef70cccfd5337059b840b882eb6bb996635d9d5c1b4ac9978` (TOP50) and `d601abe692c78c0471088b41cae1fe80bbb918bbe7e7af067ddb45e7b0ce45bf` (TOP25) — both match `feature_sets_manifest.json` exactly, and `top25 == top50[:25]` verified True programmatically. `build_feature_sets.py:88-97` performs the same check at build time; independently reproduced, clean. `train_reduced.py:52-53` re-asserts the prefix property at fit time — clean, defensive, correct.

**2. Strict causality of consumed data.** Recomputed `gap = observation_time - latest_source_ts_used` directly from `attached_long_{year}.parquet` for all six years (2021–2026), bypassing the study's own `data_readiness.csv`. Result: `min_gap == 1_000_000_000 ns` (exactly 1s) and `n_rows_at_or_after_obs == 0` for every year — matches the study's claim exactly. The corrected bar-snap convention has **not** been reintroduced inclusively.

**3. Target unchanged.** `TARGET = "bullish_regime_flip_within_300s"` is read from the pre-built parquet, never recomputed in this study (no assignment to this column anywhere in the three implementation files — confirmed by inspection). Cross-checked per-year row counts and positive rates in this study's `data_readiness.csv` against the prior study's own `data_readiness.csv` (`studies/long_rth_mirrored_surface_top100_training/results/data_readiness.csv`): row counts and positive rates match to 5 decimal places for all six years (e.g. 2021: 164940 rows, 0.29417 both; 2026: 52488 rows, 0.28037 both). This confirms the same underlying label column is being consumed, not silently rebuilt. Traced the target's construction in the prior study (`assemble_and_label.py:9`: `bullish_regime_flip_within_300s = (confirm_flip_ns - observation_time)/1e9 <= 300`) purely for provenance — this study does not touch that logic.

**4. No outcome/future column in the feature matrix.** Enumerated all 115 columns of `prepared_long_2026.parquet`; the 15 non-feature columns are `year, regime_start_ns, observation_time, regime_start_time, confirm_flip_ns, prevailing_direction, entry_direction, atr_at_entry, regime_age_s, fill_ts, fill_px, session, time_to_bullish_flip_s, bullish_flip_within_600s, bullish_regime_flip_within_300s`. Intersected this list against the frozen TOP100 feature list: **zero overlap**. `FORBIDDEN_IN_MATRIX` (`train_reduced.py:64-66`) is checked defensively at fit time and raises on any match; independently confirmed unnecessary in practice because the frozen list is clean, but the guard is correctly wired.

**5. 2026 never used for fitting/feature-selection/hyperparameters/calibration.**
- Training: `fit_logistic`/`fit_gbt` (`train_reduced.py:177,181`) are called only on `Xb["train"]`/`yb["train"]` (2021–2024). Verified in the reused source (`short_rth_enriched_volume_level_retrain/train_and_evaluate.py:56-64,73-77`) that `SimpleImputer`/`StandardScaler`/`LogisticRegression`/`HistGradientBoostingClassifier` are all `.fit()` only on the passed `train_X`; `train_reduced.py:178` wraps the already-fitted imputer/scaler/model in a `Pipeline`, so subsequent `est.predict_proba(Xb[sp])` calls only `.transform()` on 2025/2026 — no refit, no leakage.
- Permutation importance (GBT): `train_reduced.py:182-187` samples and scores exclusively on `Xb["2025"]`/`yb["2025"]`. 2026 is never referenced in this block.
- Calibration: `train_reduced.py:204-205`, `CalibratedClassifierCV(FrozenEstimator(est), method=method).fit(Xb["2025"], yb["2025"])` — fit exclusively on 2025; 2026 only receives `.predict_proba()` (transform-only) at line 207. No calibration refit on 2026.
- Model selection: `train_reduced.py:230-233`, `chosen[fs_name] = max(cands, key=lambda t: (store[t]["2025_auc"], store[t]["2025_ap"]))` — only 2025 metrics are in the key; 2026 is absent from the selection tuple. Verified against `model_manifest.json`: `TOP100→TOP100_gbt, TOP50→TOP50_logreg, TOP25→TOP25_logreg`, and independently recomputed from `model_metrics.csv` that in each of the three feature sets the model with the higher **2025** AUC was chosen (e.g. TOP25: logreg 2025 AUC 0.67290 > gbt 2025 AUC 0.66879 → logreg chosen, matching the manifest) — confirms the selection rule is applied exactly as coded, with no hidden 2026 tie-break.
- **`decide.py` preference logic — originally flagged as W1, now remediated. See "Confirmatory re-audit" section below.**

**6. Feature order frozen, not re-ranked.** `build_feature_sets.py` never computes an importance score from the prepared long-side data; it only reads `rank` from the frozen CSV and slices. No re-ranking code path exists anywhere in the three implementation files. Confirmed independently by recomputing the hashes in item 1 directly from the source CSV rather than trusting any long-side computation.

**7. TOP100 honestly re-fit, reproduces 0.6682/0.6512.** `model_metrics.csv` row `TOP100,gbt`: `2025_auc = 0.66816246971099`, `2026_auc = 0.6512041025210216`. These round to 0.6682 / 0.6512 exactly, and `decide.py`'s tolerance check (`< 5e-4`) is satisfied by a wide margin (actual diffs ≈ 3.8e-5 and ≈ 4e-9). `model_manifest.json` confirms `TOP100` selection chose `gbt` (2025 AUC 0.6682 > logreg's 0.6660), i.e. TOP100 was actually re-fit and re-selected inside this harness rather than transcribed.

**Headline sanity check (results/model_metrics.csv, viability_gates.json vs selected_model_predictions_*.parquet).** Recomputed AUC and top-decile flip rate directly from `results/selected_model_predictions_{2025,2026}.parquet` (raw `score` + `bullish_regime_flip_within_300s` columns, not from any study-authored aggregate):
- 2025: recomputed AUC = 0.6729, top-decile flip = 0.50887 (n=163,397) — matches `final_decision.json` headline exactly.
- 2026: recomputed AUC = 0.64619, top-decile flip = 0.54506 (n=52,488) — matches exactly.
- Confirmed `results/selected_model_predictions_2026.parquet` is byte-for-byte (`DataFrame.equals`) identical to `_work/pred_TOP25_logreg_2026.parquet`, and *not* equal to `pred_TOP50_logreg_2026.parquet`'s scores — the promoted file really is TOP25/logreg, as claimed, not silently a different candidate.
- Also cross-verified family-composition table in SPEC.md (44/29/27/3, 17/17/16/1, 6/9/10/0 across TOP100/TOP50/TOP25) and the `pct_levels_behind_trade` rank-25 claim by independent `value_counts()` / row lookup on the source CSV — both match exactly.

**Additional independent check (not explicitly requested but material to look-ahead scope):** verified no `regime_start_ns` value appears in more than one year's prepared parquet (train/dev/test split does not leak any regime across the year boundary) — zero overlaps found across all six years.

## Confirmatory re-audit after remediation

The coordinator remediated the two items from the original pass and re-ran `decide.py`. Re-verified both changes directly against the current file contents (not the coordinator's description of them) and independently re-ran the decision script myself.

### W1 remediation — `decide.py` "materially better" tie-break

**Before:** `decide.py:101-105` (original) computed `g50["metrics"]["2026_auc"] - g25["metrics"]["2026_auc"] >= 0.010` — a direct pairwise comparison of two candidate feature sets on the sealed 2026 test AUC, reachable if neither TOP25 nor TOP50 passed strong preservation but at least one passed minimum-viable.

**After, re-read line-by-line (`decide.py:101-116`):**
```
better = (g50["minimum_viable_pass"]
          and (g50["metrics"]["2025_auc"] - g25["metrics"]["2025_auc"] >= 0.010
               or (abs(g50["metrics"]["2025_auc"] - g25["metrics"]["2025_auc"]) < 1e-12
                   and g50["metrics"]["2025_average_precision"]
                   > g25["metrics"]["2025_average_precision"])))
```
This now references only `2025_auc` and `2025_average_precision` for both TOP50 and TOP25 — **no `2026_` key appears anywhere in this expression**. I traced every branch of the `if/elif/else` block at `decide.py:97-125`:
- Line 97 (`g25["strong_preservation_pass"]`) and line 99 (`g50["strong_preservation_pass"]`) gate on pre-registered pass/fail booleans that read 2026 thresholds — this is the explicitly mandated, disclosed pass/fail use of 2026 (per SPEC.md and the coordinator's note), not a ranking, and was never the concern.
- Line 101's `better` comparison (the only place two feature sets are ranked *against each other*) is now 2025-only, confirmed by direct inspection — no 2026 key, no monthly-AUC reference, no lift reference.
- Lines 118-124 (the "neither viable" branch) reference `2025_auc>=0.63` and `2026_auc>=0.62` per-feature-set pass/fail booleans only to choose a decision *label* (`LONG_REDUCED_FEATURE_FAILS_2026` vs `LONG_TOP100_STILL_REQUIRED`) when both candidates have already failed — this does not rank TOP25 against TOP50, it only distinguishes two failure narratives, and was correctly out of scope for W1.

**Conclusion: no reachable code path lets a 2026 metric rank one feature set against another.** W1 is fully remediated.

### N1 remediation — `regime_end_ns` in `FORBIDDEN_IN_MATRIX`

`train_reduced.py:59-66` now carries an explicit comment: `FORBIDDEN_IN_MATRIX` is documented as a deliberate superset, with `regime_end_ns` called out by name as absent from the current prepared schema and retained defensively in case of a future upstream rename. Re-verified the column is still genuinely absent from `prepared_long_2026.parquet` (unchanged from the original pass). N1 fully remediated — no residual ambiguity for a future reader.

### Independent re-run of `decide.py` and artifact consistency check

Re-ran `implementation/decide.py` myself from a clean shell (not trusting the coordinator's own re-run) and independently recomputed the headline metrics fresh from `selected_model_predictions_*.parquet` a second time:

- Script output: `DECISION: LONG_TOP25_SIGNAL_STRONG_PRESERVATION  (preferred=TOP25)` — **unchanged** from the original pass.
- `results/final_decision.json`: `decision = "LONG_TOP25_SIGNAL_STRONG_PRESERVATION"`, `preferred_feature_set = "TOP25"`, `selected_model = "TOP25_logreg"` — matches the coordinator's claim and my own regenerated output exactly.
- Cross-checked `results/viability_gates.json` and `results/final_decision.json` headline numbers against `results/model_metrics.csv` row `TOP25,logreg`: `2025_auc 0.6729`, `2026_auc 0.64619`, `2025_top_decile_flip_rate 0.50887`, `2026_top_decile_flip_rate 0.54506` — all fields in both JSON artifacts match the CSV row to the reported precision, and both `minimum_viable_pass` and `strong_preservation_pass` are `true` for both TOP25 and TOP50 in the freshly regenerated `viability_gates.json`, consistent with the pre-remediation values.
- Re-recomputed AUC/top-decile flip directly from `selected_model_predictions_{2025,2026}.parquet` after the re-run: 2025 AUC 0.6729 / top-decile 0.50887; 2026 AUC 0.64619 / top-decile 0.54506 — identical to the original independent recomputation, and confirmed `selected_model_predictions_2026.parquet` is still byte-identical to `_work/pred_TOP25_logreg_2026.parquet`.
- This is expected and correct: neither remediation touched `train_reduced.py`'s fitting/selection logic or any upstream data, only a dead-code comparison expression and a comment, so `model_metrics.csv` and all fitted scores are unchanged; only the `decide.py`-authored JSON artifacts were regenerated, and they regenerated identically because the reachable decision path (line 97) was never affected by the change.

**No new findings introduced by the remediation.**

## Notes (residual, non-blocking)

### [N2] `train_reduced.py:204-209` — 2025 calibration diagnostics (`*_cal_isotonic`, `*_cal_sigmoid` for split `2025`) are in-sample for the calibrator

`CalibratedClassifierCV(FrozenEstimator(est), method=...).fit(Xb["2025"], yb["2025"])` fits the calibration map on 2025, and `model_metrics.csv`'s `2025_auc_cal_isotonic` / `2025_auc_cal_sigmoid` columns are then evaluated on that same 2025 set — i.e., these particular calibration-quality numbers for the 2025 split are not out-of-sample. This has **zero effect on any gate or decision**: `decide.py` reads only the uncalibrated `2025_auc`/`2026_auc` columns (verified by direct inspection — no `_cal_` suffix appears anywhere in `decide.py`). Flagging only so a future reader does not mistake the `2025_*_cal_*` columns in `model_metrics.csv` for held-out calibration validation; the 2026 `_cal_*` columns are legitimately out-of-sample (calibrator fit on 2025, applied to 2026). Not remediated (not requested), not blocking.

## Clean checks

- A1–A5 (NT timestamp conventions): N/A — this study runs no NT strategy code or `on_bar` logic; it is a pure offline pandas/sklearn re-fit over already-materialized parquet.
- B1 (no `center=True` rolling in feature path): N/A — no rolling computation exists in this study; all features are pre-computed upstream and consumed as-is.
- B2/B3 (features causal at bar `i`): inherited and re-verified via the strict-causality gap recomputation above (item 2); this study introduces no new feature computation.
- B4 (no `.shift(-N)` in feature path): confirmed absent — grepped all three implementation files, no `.shift(` calls anywhere.
- B5 (no leaking `.ffill()`/`.bfill()`): confirmed absent — no fill operations in this study; `SimpleImputer(strategy="median")` is fit on train only and applied via `.transform()` to dev/test, standard and correct.
- B7 (scaler/normalization statistics from a strictly past window): `StandardScaler`/`SimpleImputer` fit exclusively on `Xb["train"]` (2021–2024) then `.transform()`-only on 2025/2026 — verified by tracing the `Pipeline` construction (`train_reduced.py:177-178`) and the reused `fit_logistic` source.
- B9/B10 (feature tracker timeframe discipline / duplication): N/A to this study — no new feature trackers are created; TOP50/TOP25 are pure prefix subsets of an already-registered, already-audited TOP100 list.
- C1–C2 (label construction / alignment): unchanged, reused as-is; independently confirmed identical row counts and positive rates vs. the prior study (item 3).
- C3 (temporal, non-random train/test split): confirmed — train 2021–2024, dev 2025, test 2026, with zero cross-year `regime_start_ns` overlap (independently checked).
- C4 (no refit on test-overlapping data): confirmed — training uses only 2021–2024 rows; calibration uses only 2025 rows; 2026 receives predict-only calls throughout `train_reduced.py`.
- D1/D3/D4 (train/serve consistency, deterministic ordering): N/A — no live NT scoring path exists in this study; feature order is frozen and hash-verified (item 1/6), and `assert RANDOM_STATE == 42` (`train_reduced.py:75`) plus identical reused fit functions make the TOP100 re-fit deterministic and reproducible (item 7).
- D2/model-vs-feature-set selection: **now clean end-to-end** — confirmed no reachable path in either `train_reduced.py` or `decide.py` lets a 2026 metric rank one candidate (model or feature set) against another; 2026 is used only as a pre-registered pass/fail gate and for decision labelling, exactly as briefed.
- E1–E5, F1–F4, G1–G4 (NT backtest config, session handling, data integrity): N/A — no bar subscriptions, no venue simulation, no session logic; scope is explicitly excluded per `SPEC.md`/`REPRODUCE.md` ("no NautilusTrader, no MBP-1, no surface rebuild").
- H1–H4 (bracket-simulation price resolution): N/A — no trade/bracket simulation of any kind in this study; explicitly out of scope per SPEC ("no trade economics, no entry/stop/exit/threshold optimization").
- Prefix property (TOP50/TOP25 exact prefixes of TOP100, TOP25 prefix of TOP50): independently reproduced from source CSV, matches all three SHA-256 values exactly.
- Strict-causality of consumed prepared data (min gap 1s, zero at-or-after rows, all 6 years): independently reproduced from raw `attached_long_*.parquet`, not from the study's own CSV.
- Target column unchanged and unrebuilt: independently cross-checked positive rates/row counts against the prior study's own readiness table.
- No outcome/PnL/future column in any of the TOP100/TOP50/TOP25 feature lists: independently enumerated all 115 raw columns and intersected against the frozen feature lists — zero overlap.
- Model-level selection (`train_reduced.py`) never reads 2026: independently traced every fit/selection call site.
- TOP100 honest re-fit reproduces 0.6682/0.6512: independently recomputed from `model_metrics.csv` raw values, matches within noise (~4e-5).
- Headline 2025/2026 AUC and top-decile flip rate: independently recomputed directly from `selected_model_predictions_*.parquet` raw scores/labels, matches reported values exactly, both before and after the remediation re-run.
- Promoted prediction file identity: independently confirmed `selected_model_predictions_2026.parquet` is byte-identical to `pred_TOP25_logreg_2026.parquet` and distinct from the TOP50 candidate, both before and after the remediation re-run.
- No file outside this study's directory was modified (`git status` clean for all read-only upstream study directories).
- Post-remediation decision artifacts (`viability_gates.json`, `final_decision.json`) are internally consistent with `model_metrics.csv` and reproduce the identical decision (`LONG_TOP25_SIGNAL_STRONG_PRESERVATION`, preferred `TOP25`, selected `TOP25_logreg`) as the pre-remediation run.

---

*Audit complete. **FINAL: 0 CRITICAL, 0 WARNING, 1 NOTE (informational only, non-blocking)** — acceptance criterion met. Findings reflect read-only static analysis plus independent numeric recomputation from raw parquet/CSV artifacts using a fresh Python process, including an independent re-run of `decide.py` after remediation; no NT execution or dynamic run was performed.*

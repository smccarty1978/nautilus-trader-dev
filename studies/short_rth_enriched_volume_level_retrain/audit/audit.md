# Look-Ahead & Timestamp Audit

**Date:** 2026-07-19T20:05:38-05:00
**Scope:**
- `studies/short_rth_enriched_volume_level_retrain/SPEC.md`
- `studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py` (251 lines)
- `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py` (247 lines)
- `studies/short_rth_enriched_volume_level_retrain/layer2_policy.py` (140 lines)
- `studies/short_rth_enriched_volume_level_retrain/layer3_overlay.py` (88 lines)
- `studies/short_rth_enriched_volume_level_retrain/select_and_attribute.py` (277 lines)
- `studies/short_rth_enriched_volume_level_retrain/REPRODUCE.md`
- `features/registry.py` (443 lines) — `ohlcv_est_delta` and `price_level_context` family definitions
- `studies/regime_sequence_chop_context/train_weakness_model.py` (CENTER_FEATS/SEQUENCE_FEATS source, lines 1-63)
- Produced artifacts inspected for internal consistency: `_work/feature_sets.json`, `results/phase0_manifest.json`, `results/manifest.json`, `_work/checkpoints/*.pkl` (timestamps only)

**Not in scope (upstream, previously audited elsewhere per project memory):** NT catalog build, bar-timestamp construction, bracket-fill simulation, and the score-independent candidate-population definition. This study consumes `studies/ohlcv_volume_delta_price_level_features/_work/full_{year}.parquet` and the `short_rth_w4_retrain_entry_strength` control reconciliation as fixed, already-validated upstream artifacts and does not re-derive labels, population, or exits. Sections A/E/F/G/H below are marked N/A for this study's own code where the underlying mechanism lives upstream; this audit does **not** re-verify those upstream studies' own audits, it only verifies this study does not re-introduce a defect by how it *consumes* that data.

**Auditor:** lookahead-auditor v1 (first pass for this study — no prior audit.md existed)

## Summary

- Critical: 0
- Warning: 1
- Note: 3

## Warnings

### [D4] `train_and_evaluate.py:198-206` — model checkpoints have no input-fingerprint validation

```python
ckpt_path = ckpt_dir / f"{key}.pkl"
if ckpt_path.exists():
    print(f"--- {key}: loading from checkpoint ---")
    result = pickle.loads(ckpt_path.read_bytes())
else:
    result = compute_combo(fs_name, model_name, cols, train_X, train_y, dev_X, dev_y, test_X, test_y)
    ckpt_path.write_bytes(pickle.dumps(result))
```

The checkpoint key is only `{feature_set}__{model}`, with no hash of `train_X`/`dev_X`/`test_X`/`feature_sets.json` embedded. If `phase0_prepare_data.py` is ever re-run with corrected or updated upstream data (e.g. a fix to the feature-foundation study, a corrected `outcome_class` mapping, or a changed feature list) without manually deleting `_work/checkpoints/`, `train_and_evaluate.py` will silently reuse a stale fitted model/scores while all downstream files (`economic_results.csv`, `manifest.json`, the final `ENRICHED_RETRAIN_OVERFITS_2025` decision) will report as if computed against current data. This is a train/serve-consistency risk in the sense of D4 (deterministic, identical inputs between what was fit and what is scored) — a stale checkpoint could mask a genuine improvement (false negative) or manufacture a phantom one (false positive) after a legitimate upstream fix, with no error surfaced.

**Verification for the current run:** I compared file timestamps — `_work/feature_sets.json` and `_work/train_2021_2024_prepared.parquet` (7/19/2026 4:54 PM) predate all six `_work/checkpoints/*.pkl` files (6:37 PM–7:57 PM same day), so this specific run's checkpoints are consistent with the current data. No evidence this bug fired for the result now labeled `ENRICHED_RETRAIN_OVERFITS_2025`. Flagging as a warning for future reruns, not as an active defect in the current result.

**Recommended fix (do not apply):** include a hash of the input frames (or at least a hash of `phase0_prepare_data.py`'s `generator_sha256` + `feature_sets.json` content) in the checkpoint filename or as a stored field checked before reuse.

## Notes

### [Documentation drift] `SPEC.md:59-71` vs `phase0_prepare_data.py:71-73,192-193` — categorical column count mismatch (28 vs 29)

SPEC.md's Scout-pass finding §5 states "28 bounded categorical columns following the pattern `*_position`". The actual code (`find_position_cols`, and the explicit assertion `if len(ref_pos) != 29: raise RuntimeError(...)` at line 192) requires and finds **29** such columns, confirmed directly against `full_2021.parquet` (29 columns ending in `_position`, dtype object). `REPRODUCE.md:23` correctly says "29 bounded `*_position` categorical columns", so the implementation and its own reproduce doc agree with each other — only the frozen SPEC.md scout-pass count is off by one. This is a pure documentation-accuracy issue, not a functional bug: the feature-count arithmetic is internally self-consistent everywhere it matters (247 total `price_level_context` registered features = 29 base levels × 6 suffixes [174] + 4 session_state + 14 aggregate_counts + 13 nearest_geometry + 20 density_envelope + 13 clustering + 9 direction_normalized = 247; numeric F2 additions = 247 − 29 position − 2 name = 216, matching `results/phase0_manifest.json`'s `n_price_level_features_numeric: 216`; dummy columns = 29 × 4 = 116, matching `n_price_level_dummy_features: 116`). No leakage or miscount of actual model inputs results from this; flagged only because a frozen SPEC with a wrong verified-fact count undermines the document's stated purpose ("grounds this SPEC in verified fact, not assumption").

### [Documentation drift] `SPEC.md:51-54` vs `phase0_prepare_data.py:38,46` — wrong provenance path for `CENTER_FEATS`/`SEQUENCE_FEATS`

SPEC.md's Scout-pass finding §3 states F0 is "importable unchanged from `studies/short_rth_w4_retrain_entry_strength/train_weakness_model.py`." That file does not exist — `studies/short_rth_w4_retrain_entry_strength/` contains no `train_weakness_model.py` (confirmed via glob). The actual, correct import (`phase0_prepare_data.py:43-46`) adds `studies/regime_sequence_chop_context` to `sys.path` and imports `CENTER_FEATS, SEQUENCE_FEATS` from `regime_sequence_chop_context/train_weakness_model.py`, which is where the 149-column list is actually defined. This mirrors the same pattern already used by the prior retrain study's own `short_rth_w4_retrain_entry_strength/phase0_prepare_data.py` (also imports from `regime_sequence_chop_context`), so the code is consistent with established precedent and the actual F0 feature set is correct and unchanged — this is a citation error in SPEC.md, not a functional defect. Confirmed clean: none of `CENTER_FEATS`/`SEQUENCE_FEATS` (regime-center slopes, ordering state, swing/duration statistics — all computed from completed regime history) reference `exit_ts`, `exit_px`, `net_pnl`, or `alignment_ts`.

### [Selection-gate scope note] `select_and_attribute.py:132-146` — 2025 gate criteria mix split scopes (not a leakage issue)

`apply_gate()` checks `per_trade_beats_baseline_a` against `BASELINE_A["2025"]` (a true 2025-only constant) but checks `profit_factor_beats_baseline_a` and `max_dd_better_than_baseline_a` against `BASELINE_A["combined"]` (a 2025+2026 aggregate constant), while `dev_row` itself is always 2025-only. This does not leak any of *this pipeline's own* 2026 data into the 2025 selection or gate decision — `BASELINE_A`'s numbers are fixed, hardcoded historical constants from an entirely different, already-completed study (`short_rth_retrain_baseline_still_best`), not derived from this study's own sealed-test run. So there is no causality violation. It is, however, an apples-to-oranges comparison (2025-only model metric vs. a combined-years baseline metric) that makes the "beats baseline on 2 of 3" 2025 gate check easier or harder to satisfy than a like-for-like comparison would, and is worth the report author being aware of when writing `STUDY_REPORT.md`, since `note_on_2025_gate_scope` in `manifest.json` documents the missing-constants rationale but does not call out this scope mismatch specifically.

## Clean checks

- **A1-A5 (NT timestamp conventions):** N/A for this study's own code — this study performs no bar indexing, `BarType` construction, or NT strategy callbacks; it consumes already-labeled/featured parquet rows keyed by `regime_start_ns`/`observation_time` from the upstream feature-foundation study.
- **B1 (`center=True` rolling):** No pandas `.rolling(center=True)` found anywhere in the five reviewed files; no rolling computations are performed in this study at all (they live in the upstream `features/trackers/*` modules, out of scope per the audit brief's file list).
- **B2/B3 (indicator timing):** Confirmed via `features/registry.py`: every `ohlcv_est_delta` and `price_level_context` feature is defined with `source_timeframe`/`update_anchor` metadata consistent with causal, completed-bar computation (`rolling_window`, `regime_relative`, `rth_cumulative` subfamilies all describe backward-looking windows). No feature name or implementation reference in the registry touches `exit_ts`, `exit_px`, `alignment_ts`, `net_pnl`, or `outcome_class`.
- **B4 (`.shift(-N)` in feature path):** Grepped all five study files and `features/registry.py`; no `.shift(` calls of any kind exist in this study's code (rolling/shift logic lives entirely upstream, out of this study's scope).
- **B5 (`.ffill()`/`.bfill()` leakage):** None found in the five reviewed files.
- **B6 (asof-join alignment):** Not applicable — this study performs no cross-frequency joins; all features arrive pre-joined from the upstream `full_{year}.parquet`.
- **B7 (scaler/imputer statistics from past-only window):** Confirmed directly in code. `fit_logistic()` (`train_and_evaluate.py:56-64`) calls `imputer.fit_transform`/`scaler.fit_transform` **only** on `train_X` (2021-2024). `score_logistic()` (`train_and_evaluate.py:67-70`) calls `.transform()` (not `.fit_transform()`) on `dev_X`/`test_X`. No refitting of imputer/scaler statistics on 2025 or 2026 data anywhere in the pipeline.
- **C1/C2 (label construction correctness):** `build_outcome_class()` (`phase0_prepare_data.py:93-111`) is a pure case-when mapping from existing `exit_reason`/`net_pnl` columns with an exhaustiveness assertion (`if cls.isna().any(): raise`) and a cross-check against the existing `opposing_flip_exit_positive` column. `outcome_class` is a label, never included in `F0_FEATS`/`ohlcv_feats`/`level_feats` (directly verified: none of `exit_reason`, `net_pnl`, `exit_ts`, `alignment_ts`, `outcome_class`, or any `*pnl*`/`*exit*`/`*outcome*`/`*label*`/`*target*`-named column appears in any of the four `feature_sets.json` lists, confirmed by direct string scan of all 695 unique feature names across F0-F3).
- **C3 (temporal train/test split, no `cross_val_score`):** Train/dev/test are explicit year-based splits (2021-2024 / 2025 / 2026); no `cross_val_score`, `KFold`, or random splitting anywhere in the pipeline.
- **C4 (walk-forward refit leakage):** Not applicable — single static train/dev/test split, no walk-forward refitting performed.
- **D1/D2/D3:** N/A for this study — no live `on_bar` strategy code, no meta-label filter cascade, no ONNX export exists in this study (it is Layer-1/2/3 offline diagnostics only, per SPEC.md; promotion to NT validation is explicitly deferred pending this audit and the sealed-test result).
- **D4 (cutoff/selection never touches 2026):** Directly verified in `train_and_evaluate.py:164` (`cutoffs = {band: float(np.quantile(score_dev, 1 - band)) ...}` — computed from `score_dev` i.e. 2025 only) and reused unchanged for the 2026 split in `layer2_policy.py:113` (`cutoff = cutoffs[key][str(band)] ...`, same dict for all three splits). Directly verified in `select_and_attribute.py:61-65` (`select_best()` filters `econ.split == "2025"` before sorting/selecting) — no code path in `select_and_attribute.py` filters or sorts by `split == "2026"` before the final `decision` is computed; `apply_gate()` only *evaluates* (does not re-select using) 2026 metrics.
- **E1-E5 (backtest configuration):** N/A — no `subscribe_bars`, `BarType`, simulated venue, or `on_bar` order-submission code in this study.
- **F1-F4 (session/timezone handling):** N/A for new logic — this study reuses the RTH population and timestamps unchanged from the upstream, already-validated feature-foundation/W4 studies; no new session-boundary or DST-sensitive logic is introduced. `monthly()`/`exit_attribution()` (`layer2_policy.py:74-91`) use `pd.to_datetime(..., unit="ns", utc=True)` consistently for month-bucketing (UTC-aware, not naive).
- **G1-G4 (data integrity):** N/A — this study performs no continuous-contract adjustment, gap handling, or resampling; `verify_identity_vs_prior_retrain()` (`phase0_prepare_data.py:123-148`) re-confirms row counts, keys, and label columns are identical to the previously-validated `labeled_featured_{year}.parquet` for all six years before proceeding (all six years pass in `results/phase0_manifest.json`).
- **H1-H4 (bracket-simulation price resolution):** N/A — this study contains no bar-scanning simulation loop of its own; `exit_reason`/`net_pnl`/`exit_ts` are read as already-computed upstream columns, not recomputed here.

---

*Audit complete. Findings reflect read-only static analysis of the five pipeline scripts plus the feature registry and F0 feature-list source file. Dynamic bugs (e.g., a stale checkpoint actually firing on a future rerun) are called out as a risk (Warning D4) but not directly observable from static analysis of a single completed run's timestamps. 0 CRITICAL findings — the mandatory audit gate (CLAUDE.md, "Mandatory Audit Gate") is clear to finalize the `ENRICHED_RETRAIN_OVERFITS_2025` result.*

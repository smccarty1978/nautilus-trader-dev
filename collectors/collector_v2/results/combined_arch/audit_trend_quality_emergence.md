# Look-Ahead & Timestamp Audit — trend_quality_emergence.py

**Date:** 2026-06-24
**Auditor:** lookahead-auditor v1
**Scope:**
- `collectors/collector_v2/trend_quality_emergence.py` (primary target)
- `backtests/studies/regime_dna_knn/early_health_filter.py` (capsule builder + `compute_labels_features`)
- `backtests/studies/regime_dna_knn/progressive_separability.py` (`build()` matrix builder)
- `collectors/collector_v2/extract_hc_perbar_mapping.py` (hC per-bar mapping builder, for convention verification)

---

## Summary

- CRITICAL: 0
- WARNING: 0
- NOTE: 2

---

## Critical Findings

None.

---

## Warnings

None.

---

## Notes

### [NOTE-1] `trend_quality_emergence.py:292` — Section C report header says "bar k open"; actual PnL entry is bar k+1 open

The Section C output block writes this line to the markdown report:

```python
"Entry sim: enter at bar k open (age entry, unconditional), 1 lot bar-mode.",
```

The actual PnL computation (lines 332–337) correctly enters at `O[idx, k+1]` — bar k+1 open — after observing the bar-k state. The table footnote at line 375 states the correct semantics ("causal: enter bar k+1 open (state observed at bar k close)").

This is a documentation inconsistency in the generated report only. The code is causal; only the Section C header text is inaccurate. A reader of `trend_quality_emergence.md` who reads the header but not the footnote may think the Section C "pnl $/tr†" column reflects bar-k entry rather than bar-(k+1) entry.

**No code change required.** Consider updating the Section C header string (line 292) to match the footnote: "Entry pnl: enter at bar k+1 open (state observed at bar k close), 1 lot bar-mode."

---

### [NOTE-2] `trend_quality_emergence.py:491` — Section D "ALL" row includes regimes with no hC mapping entry

At line 491:
```python
R.append(f"| ALL | {len(sub8):,} | ${sub8.loc[sub8.year==2025,'pnl'].mean():+.0f} | ...")
```

`sub8` is built from `alive8_oos` (all regimes where `npost >= 8` and year in OOS). It is merged with `hc_at_7` (bars_in_regime==8 rows) using a left join (line 472). Regimes with no hC entry at bar 7 get `state=NaN`, are fillna'd to `state=""` (line 474), fall into the "Other" bucket excluded from per-state rows, but remain in `sub8` and contribute to the "ALL" row mean.

The fraction of OOS regimes with no mapping entry at bars_in_regime=8 is unlikely to be large (the mapping covers bars 4..28 for all regimes surviving to those bars), but the "ALL" average PnL silently pools mapped and unmapped regimes. If the unmapped fraction differs systematically in PnL (e.g., very short-lived regimes that flipped before bar 7 is KNN-scored), the ALL mean is slightly noisy.

This is a reporting precision issue only — no look-ahead or survivorship bias, since the unmapped regimes are still required to satisfy `npost >= 8` before inclusion.

**No code change required.** Consider adding a note to the ALL row or computing `sub8[sub8.hC.notna()]` for a "matched" ALL average alongside the raw ALL.

---

## Clean Checks

All of the following were verified and passed.

### Checklist A — Timestamp conventions
- **A1:** No NT strategy or bar-level timestamp indexing in this script. Not applicable.
- **A2:** Catalog usage is in `early_health_filter.py` (capsule builder), verified via `ts_init` (line 175 of `early_health_filter.py`). The capsule builder correctly uses `ts_init` for bar ordering. Not re-audited here (previously audited; capsule treated as pre-built artifact).
- **A3–A5:** No live strategy code. Not applicable.

### Checklist B — Feature engineering look-ahead
- **B1:** No `rolling`, `ewm`, or `expanding` calls with `center=True`. No rolling operations in the target file.
- **B2:** All indicator values used at decision point come from `hc_perbar_mapping` where hC at bar k uses only bars 4..k (confirmed in `extract_hc_perbar_mapping.py` build_states contract).
- **B3:** Not applicable (no EMA/ATR in this file; those are upstream in capsule builder, previously audited).
- **B4:** No `.shift(-N)` anywhere in the file.
- **B5:** No `.ffill()` or `.bfill()` in the file.
- **B6:** No cross-frequency merges in the feature path. The only merge is `hc_at_k` joined to the OOS subset (same frequency, same regime key).
- **B7:** IS thresholds (`p33_hs`, `p67_hs`) are computed strictly on `hc_df.year < 2025` rows (lines 107–111). Applied as fixed thresholds to OOS data. Correct train/serve split.

### Checklist C — Label construction
- **C1:** `runner` (lines 92–93) uses `mfe4_atr = mfe_remaining_after(3)` (future data, bar 4 onward) and `pnl4_atr` (outcome PnL). Both are correct label-only uses of future data. Neither is used as a feature or entry gate anywhere.
- **C2:** `runner` is defined from bar-4 entry perspective (entry at `O[:,4]`), used as the prediction target for AUC at each age. Label alignment is consistent.
- **C3:** AUC (Section A) is computed on `oos_mask = alive & np.isin(year, OOS)` — OOS only. No IS contamination in AUC computation.
- **C4:** Not applicable (no walk-forward re-fitting in this script; hC values are pre-built with proper walk-forward in `extract_hc_perbar_mapping.py`).

### Checklist D — Train/serve consistency
- **D1–D4:** This is a pure offline research study; no live strategy component. hC thresholds (`p33_hs`, `p67_hs`) are IS-derived and fixed before any OOS data is touched.

### Checklist E — Backtest configuration
- **E1–E5:** No NT BacktestEngine in this script. Bar-mode simulation only, explicitly caveated in the output report (lines 14–19).

### Checklist F — Session and time handling
- **F1–F4:** No session filtering, timezone conversion, or time-of-day logic in this script.

### Checklist G — Data integrity
- **G1–G4:** Capsule is pre-built from previously audited NT BacktestEngine run. Data integrity of the capsule is outside scope of this audit.

### Specific items requested by user

1. **Section C pnl_k entry causality (line 334):** `entry_k = np.where(can_enter_k1, O[idx, np.minimum(k+1, NCOL-1)], np.nan)` — enters at bar k+1 open. `can_enter_k1 = npost[idx] >= k+1` gates survivorship correctly. PASS.

2. **hC state classification `bars_in_regime == k+1` (lines 206, 311):** Per `extract_hc_perbar_mapping.py` line 108, `bars_in_regime = k_mapping + 1`. So `bars_in_regime == k+1` retrieves rows where `k_mapping == k`, meaning hC was computed using bars 4..k and is known at bar-k close. Correct. PASS.

3. **`first_match_bar` entry at `k_idx + 1` (lines 135–141, 433):** `fhh_k` returns the bar index (k_idx) of the first HH-HardStall occurrence. `entry_col = fhh_k_i[idx] + 1` enters at the bar immediately after detection. `can_enter = has_fhh & (fhh_k_i + 1 < NCOL) & (npost >= fhh_k_i + 1)` correctly requires the regime to survive to the entry bar and the entry column to be within matrix bounds. PASS.

4. **`mfe4_atr = mfe_remaining_after(3)` as label only (line 92):** `mfe_remaining_after(3)` computes max favorable from bar 4 onward — future data. Used only to define the `runner` label (line 93). `runner` is used only as an AUC target (Section A) and descriptive statistic (Sections C, E). Never used as an entry filter or threshold for trade selection. PASS.

5. **`wf_knn` not in this file (confirmed):** No reference to `wf_knn` exists in `trend_quality_emergence.py`. The pre-built `hc_perbar_mapping.parquet` is loaded directly. PASS.

---

*Audit complete. Findings reflect read-only static analysis of the target file and its direct imports. Dynamic bugs, catalog content validity, and NT BacktestEngine capsule quality are outside scope.*

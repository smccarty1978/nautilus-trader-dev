# Look-Ahead & Timestamp Audit

**Date:** 2026-06-16T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/regime_5s_microstructure_leadtime.py` (PRIMARY — full audit)
- `studies/regime_dna_knn/early_health_filter.py` (SUPPORTING — call-site verification: `compute_labels_features`, capsule column conventions)
- `studies/regime_dna_knn/progressive_separability.py` (SUPPORTING — call-site verification: `build(df)`)
- `studies/regime_dna_knn/results/survivor_1s_paths.parquet` (schema reference only; not read)
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

### [W1] `regime_5s_microstructure_leadtime.py:170-173` — ORACLE exit uses raw peak price (ATR-denominated peak_mfe * atr), not the actual 5s bar high/low

**Description.** `net_oracle` reconstructs the exit price as `ex = r.e + r.d * r.peak_mfe * r.a` (line 172). `peak_mfe` is computed at lines 108-111 as `(pk_px - e) * dd / a` where `pk_px = h5[pk_i]` for longs and `l5[pk_i]` for shorts. Reconstructing `ex` from the ATR-normalized round-trip introduces a floating-point round-trip: the original price is divided by `atr` (float32 from the capsule) and then multiplied back. If `atr` is stored as float32, the recovered price can differ from the original `h5[pk_i]` by up to 1 tick depending on rounding. The delta is cosmetically small (~$5 level) and does not change the study's negative conclusion, but it means the ORACLE is not provably the true maximum achievable price — it may be marginally off in either direction.

The correct exit price for ORACLE is `pk_px` directly (already stored as `h5[pk_i]` or `l5[pk_i]` at the time of computation), but `pk_px` is not stored in the per-trade row dict. Only `peak_mfe` (the ATR-normalized scalar) is stored, forcing the reconstruction.

**Impact on conclusion:** Negligible for the negative diagnostic conclusion. The ORACLE is presented as an upper bound; a small float32-induced price error does not change the finding that causal give-back exits underperform holding.

**Recommended fix (do not apply):** Store `pk_px` directly in the per-trade row dict alongside `peak_mfe`, and use `pk_px` as the exit price in `net_oracle` without the round-trip through ATR normalization.

---

### [W2] `regime_5s_microstructure_leadtime.py:112-113` — `peak_to_flip_s` can be negative for truncated paths; no guard or annotation

**Description.** `T_flip = r.n * 60 * NS` (line 112) is the offset of the terminal 1m flip bar's close from the flip-bar-zero origin. `t5[pk_i]` is the 5s close offset of the price peak found within the post-entry 5s path (starting from ENTRY_T = +180s). For truncated paths (`p1s_trunc == True`, capped at 1800s = +30 min), when `n > 30` the 5s path does not reach T_flip. In that case `t5` values are all ≤ 1800s * NS, but `T_flip = n * 60 * NS` can be substantially larger (e.g., n=60 → T_flip = 3600s). `peak_to_flip_s` will then be correctly positive (T_flip > t5[pk_i]).

However, the inverse case is a risk: if by any data artifact a 5s bar's close-offset exceeds T_flip (e.g., a 1s bar was stored with an offset past the 1m flip due to sub-second timing), `peak_to_flip_s` could be negative. A negative value would be nonsensical (peak after the flip) and would silently shift median/p25/p75 statistics downward. The code does not assert `peak_to_flip_s >= 0` before appending to `rows`, and the summary statistics (Section 1, lines 136-137) would silently include the negatives.

There is also an asymmetric reporting bias for truncated paths: trades where n > 30 (path exceeds 1800s cap) have their full price peak observed (the 5s path covers the first 30 min), so peak_to_flip_s will tend to be large. This is directionally conservative — it inflates the median peak-to-flip duration, making 5s appear LESS useful. Since the conclusion is negative (5s doesn't help), this bias does not artificially inflate an apparent edge.

**Recommended fix (do not apply):** Add `assert peak_to_flip_s >= 0, f"negative peak_to_flip_s for regime {r.regime_id}"` after line 113, or equivalently filter `A[A.peak_to_flip_s >= 0]` before the Section 1 statistics. Add a note in the report that truncated-path trades conservatively inflate peak-to-flip duration.

---

## Notes

### [N1] `regime_5s_microstructure_leadtime.py:146-154` — flip-aligned `aligned()` with `j=0` pulls the last 5s bar at-or-before T_flip, which may be outside the 5s path for truncated trades

**Description.** At `j=0`, `target = r.T_flip`. For truncated paths, `t5` ends at ≤ 1800s*NS while `T_flip = n*60*NS` may be much larger. `searchsorted(t5, T_flip, side="right") - 1` returns `len(t5) - 1` (the last bar in the path), which is the last available 5s bar rather than a bar near the flip. For large-n truncated trades, this bar could be 30+ minutes before the flip. The `0 <= k < len(t5)` guard (line 152) passes, so these values enter the median silently.

This biases the `j=0` (at-the-flip) row of the flip-aligned table (Section 2) by mixing genuine at-flip readings for short-duration trades with far-from-flip readings for truncated long-duration trades. Since the conclusion is negative and the smooth bleed narrative is supported by the non-zero j rows too, this does not change the outcome. Still worth flagging as a silent bias in the table's j=0 row.

**Recommended fix (do not apply):** At `j=0`, additionally require that `t5[k]` is within some tolerance of `T_flip` (e.g., `abs(t5[k] - target) <= 60 * NS`) before including the value, or exclude truncated paths entirely from the flip-aligned curve (annotating the exclusion in the report).

---

### [N2] `regime_5s_microstructure_leadtime.py:75-77` — `ce_nm1` and `flip_c` matrix-cap behavior is acceptable but undocumented in the study

**Description.** `nb1 = np.clip(n - 1, 0, 61)` at line 75 and `np.minimum(n, 61)` at line 77 apply the B=62 matrix cap from `progressive_separability.build()`. For regimes with n > 61 (surviving > 61 bars), `ce_nm1` reads column 61 rather than column n-1, and `flip_c` reads column 61 rather than column n. The study report does not document this limitation; readers may not realize that long-lasting regimes (n > 61 bars) have their "bar n-1" close-excursion measured at bar 61, not their actual penultimate bar. This affects cohort membership: for long regimes that happen to be high at bar 61 but low at bar n-1, `ce_nm1 >= 1.0` may misclassify them as "still-healthy." For regimes that decline to ≤ 1 ATR between bar 61 and bar n-1, the opposite misclassification occurs.

Given that long-duration regimes represent the truncated tail and the study's negative conclusion is robust, this does not change the finding. It should be noted in the report as a known approximation.

**Recommended fix (do not apply):** Add a footnote in the study output: "ce[n-1] uses the matrix cap of 61 bars; for n>61 this reads bar 61 rather than the true penultimate bar (~X% of trades affected)."

---

### [N3] Diagnostic study parameter tuning: `GIVEBACK_P`, `HEALTHY_ATR`, `ENTRY_T`, and `JBINS` are module-level constants — confirm no IS-tuned selection

**Description.** `GIVEBACK_P = [0.5, 0.75, 1.0]`, `HEALTHY_ATR = 1.0`, `ENTRY_T = 180*NS`, and `JBINS` are declared as module-level constants (lines 43-45). They are not fitted on data; they are domain-prior values (1 ATR healthy threshold, standard give-back fractions, Bar-4 entry). No grid search over these parameters is performed in the script, and no "best" parameter is selected on OOS data and then re-presented as validated. The study correctly presents all three give-back thresholds together in a single table (line 196-203), and the verdict logic (lines 208-214) checks the best causal result only to determine which narrative branch to print — it does not gate any parameter selection.

However, a future reader might note that if `HEALTHY_ATR` were tuned to select the subset that maximally inflates the ORACLE relative gain, the hindsight-cohort comparison would look misleadingly strong. The present value of 1.0 ATR is a natural boundary and its selection is not data-driven within this script.

This is an INFO-level observation only: the study is clean on this axis as written, but the constants should be documented as prior-specified rather than data-tuned if the script is shared.

---

## Clean Checks

The following checklist items were examined and verified clean:

- **A1/A2 (timestamp conventions):** The study operates entirely on pre-built path offsets in nanosecond delta from the flip-bar close. No raw `ts_event` / `ts_init` timestamps are used in the main analysis; `T_flip = r.n * 60 * NS` is a duration offset, not an absolute timestamp. No NT bar indexing by `ts_event` occurs in this file.

- **B1 (rolling center=True):** No `rolling()` or `ewm()` calls exist in the primary file. `np.maximum.accumulate` (line 103) is a strictly causal running maximum.

- **B2/B3 (indicator causal ordering):** The 5s running peak (`run_ext_px`, line 103) uses `np.maximum.accumulate` over the full 5s bar sequence for the trade, producing a per-bar cumulative maximum. At bar index `i`, the running peak uses only bars `0..i`. The `giveback` array (line 105) is `peak_exc - fav_c`, both computed at the same bar index. Causal.

- **B4 (no negative shifts in features):** No `.shift(-N)` appears anywhere in this file. Confirmed by grep.

- **B5 (no bfill):** No `bfill` or backward-fill operation exists in this file. Confirmed by grep.

- **B6 (cross-frequency join):** The merge at line 83-84 is an inner join on `regime_id` (a unique key per trade), not a time-based cross-frequency merge. No `merge_asof` is needed here; the join is identity-safe.

- **B7 (normalization uses per-trade ATR, not global statistics):** All ATR normalization uses `r.atr` (the per-trade `atr_base` fixed at entry time). No `StandardScaler` or dataset-wide statistics are applied to features in this script.

- **C1-C4 (label construction):** `ce_nm1` is correctly identified and disclosed as a hindsight quantity. It is used only for cohort stratification, not as a feature fed into any model or trading decision. The `[!NOTE]` at lines 192-196 explicitly states it is a hindsight cohort and that the baseline is not a tradeable entry edge.

- **D1-D4 (train/serve skew):** Not applicable. This is a model-free diagnostic; no model is trained or served.

- **E1-E5 (backtest configuration):** Not applicable. No `BacktestEngine`, strategy, or bar subscription is used in this script.

- **F1-F4 (session and time handling):** Not applicable. The study operates on path offsets in nanoseconds relative to flip-bar close, inheriting session filtering from the upstream path builder.

- **G1-G4 (data integrity):** The study consumes pre-validated parquet files (`early_health_capsule.parquet` and `survivor_1s_paths.parquet`). No raw data loading, resampling, or contract-roll handling occurs here.

- **agg_5s causality (B2 applied to aggregation):** `agg_5s` (lines 48-63) groups 1s bars by `floor(t1s / 5s)` bucket. Within each bucket, `seg_c = c1s[i-1]` (line 58) is the last 1s close in bucket order — the trailing element of the current-bucket slice `[start:i]`. Since `i` is the exclusive end of the current bucket's contiguous run, `c1s[i-1]` is the last chronological element of the bucket. This is correctly the causal close for a right-labeled 5s bar. No future 1s bar is used.

- **5s close-offset labeling (A5 analog):** `out_t.append(int((bid[start] + 1) * BUCKET5))` (line 59) sets the 5s bar timestamp to `(bucket_index + 1) * 5s`, i.e., the RIGHT edge (close time) of the bucket. This is consistent with right-labeled 5s bars and with how `T_flip` is defined (as `n * 60 * NS`, the close of the terminal 1m bar). The comparison `T_flip - j * BUCKET5` in `aligned()` is therefore comparing close-time offsets to close-time offsets, correctly aligned.

- **give-back causal check (B2 extended):** `net_giveback` (lines 175-182) uses `r.giveback` (the per-bar running-peak give-back array) and takes `hit[0]` — the first bar index where give-back exceeds threshold. The exit price is `c5[hit[0]]` (the close of that bar). The running peak at bar `i` is `np.maximum.accumulate(h5)[i]` — uses only `h5[0..i]`. The give-back at bar `i` is `running_peak[i] - fav_c[i]`, both known at the close of bar `i`. This is genuinely causal: the exit fires on the bar where the condition is first met and fills at that bar's close.

- **ORACLE labeling:** `net_oracle` is labeled "(upper bound)" in the policy list (line 197) and "ORACLE = exit at the 5s peak (unbeatable upper bound)" in the report header (line 190). The `[!CAUTION]` note (lines 130-131) explicitly warns that 5s exits overstate vs 1s/tick. The `[!NOTE]` on the hindsight cohort (lines 192-196) is present and accurate. The study does not promote the ORACLE result as achievable.

- **No IS data in OOS analysis:** The `early_health_capsule.parquet` loaded at line 68 contains both IS (2021-24) and OOS (2025-26) years. The merge at line 83-84 with `survivor_1s_paths.parquet` (described as OOS-only 2025-26) acts as a natural OOS filter — only regimes with a 1s path in the OOS file will join. The study's Section 3 money table is labeled "OOS 2025-26" in the report header. However, the main loop at lines 89-118 iterates all merged rows without an explicit year filter before computing `A`. The `ce_nm1` and subset flag at line 121 operate on `A` which contains only the merged (OOS) set. This is clean because the upstream join on OOS paths enforces OOS scope.

- **No model trained or fit on OOS data:** Confirmed. There are no `fit()`, `predict()`, `train()`, or `score()` calls in this file. This is a pure diagnostic aggregation.

- **Supporting file call sites:**
  - `E.compute_labels_features(cap)` (line 69): confirmed the function uses only data from within each regime's own capsule rows; no cross-row future leakage in that function's vectorized operations (previously audited clean; re-verified against lines 203-319 of early_health_filter.py).
  - `P.build(df)` (line 70): confirmed the function pads post-flip bar arrays up to `min(n[i], B-1)` and does not inject future bars beyond each regime's own `n_post` count (lines 42-46 of progressive_separability.py). The audit fix comment at line 59 of progressive_separability.py confirms `k = Nbar` (not `max(Nbar, 1)`) is the correct post-audit state. Clean.

---

## Study Integrity Assessment

This is a model-free OOS-only diagnostic. No training occurs; no parameter is selected on OOS data and re-presented as validated. The hindsight cohort definition (`ce_nm1 >= 1 ATR`) is correctly disclosed with a `[!NOTE]` caveat in the report output, and no part of the money table is presented as a tradeable entry edge. The ORACLE upper bound is correctly labeled as such and not sold as achievable. The causal give-back exit is genuinely causal (running max through current bar only, exit at current bar's close). The 5s aggregation is correctly right-labeled and uses only bars within each bucket.

The two warnings (ORACLE float32 round-trip, unguarded negative peak_to_flip_s) are edge-case precision issues that do not affect the study's negative conclusion. The three notes are documentation/edge-case observations.

The study's conclusion — that 5s adds no actionable information, with the price peak landing a median ~5 min before the flip and the give-back being a smooth monotonic bleed visible to 1m bars — is not inflated by any look-ahead, train/serve skew, or timestamp misuse found in this audit.

---

*Audit complete. Findings reflect read-only static analysis of the primary file and supporting call sites. Dynamic bugs (e.g., race conditions in live trading) are out of scope. Scope hash (file sizes at audit time): primary ~8.5 KB, early_health_filter.py ~22 KB, progressive_separability.py ~10 KB.*

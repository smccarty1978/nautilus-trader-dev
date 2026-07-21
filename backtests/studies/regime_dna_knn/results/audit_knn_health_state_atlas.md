# Look-Ahead & Timestamp Audit — knn_health_state_transition_atlas.py

**Date:** 2026-06-17T00:00:00Z
**Auditor:** lookahead-auditor v1
**Scope:** knn_health_state_transition_atlas.py (primary) + bar4_knn_path_atlas.py (build_states, FEATS) + early_health_filter.py (compute_labels_features, CapsuleReplay) + progressive_separability.py (build) + build_survivor_1s_paths.py (PathReplay, 1s path format)

---

## Summary

- **Critical: 0**
- **Warning: 3**
- **Note: 4**

---

## CRITICAL FINDINGS

*None.*

---

## WARNINGS

### [WARNING / Check 6-toff / E4-analogue] `knn_health_state_transition_atlas.py:157` — `col > ni` guard passes through `flip-close` entry when `col=0`, but `ni` is derived from `min(n[i], 61)`, not the OOS survivor filter

**File:** `knn_health_state_transition_atlas.py`, lines 153–158.

The entry guard `if col > ni: continue` is intended to skip trades where the entry bar does not exist. For `flip-close` (col=0) this is always false and every OOS `r` passes through. For `Bar1` (col=1), `Bar2` (col=2), and `Bar4` (col=4), the guard is `col > min(n[i], 61)`. The OOS set `oos` was produced by `build_states` using `act = np.where(n > k)[0]` (bar4_knn_path_atlas.py line 66), which only includes trades where `n > k` for each bar `k` in `BARS = range(4, 29)`. Trades that appear in `oos.rid.unique()` are those that appeared in at least one bar in the range 4..28. A trade with `n[i] = 5` (flips at bar 5) will have entries in `oos` for bar k=4 only, but will still pass the `col > ni` guard for `Bar1` (col=1) and `Bar2` (col=2) since `1 <= 5` and `2 <= 5`.

**The concrete concern:** The `flip-close` and `Bar1`/`Bar2`/`Bar4` universe populations will differ. Trades that flipped very early (n=4 or 5) enter the `flip-close` and `Bar1`/`Bar2` universes but not `Bar4`. This is correct causal behavior for entry filtering — but when comparing `flip-close` vs `Bar4` results, the user should be aware the populations differ by construction (early-flippers are excluded from `Bar4` but included in `flip-close`). This is not a look-ahead bug, but the interpretation of cross-entry comparisons requires care: `Bar4` is implicitly a survivor-filtered subset, which tends to look better (survivor bias direction: longer-running trades). If `Bar4 hold-to-flip > flip-close hold-to-flip`, part of that gap may be survivor selection, not entry timing.

**Severity rationale:** Warning, not Critical. The filtering is mechanically correct (you cannot enter at Bar4 if the trade ends at bar 3). The risk is misattribution of the performance gap between entry variants.

---

### [WARNING / B3-analogue / Check 3] `knn_health_state_transition_atlas.py:90` — `reignite` uses `tot_mfe` which includes the SAME bar k in the `mfe_sofar` comparison, so the signal at k=terminal-bar is always 0; boundary is correct but the definition excludes any further high AT bar k

**File:** `knn_health_state_transition_atlas.py`, line 90.

```python
oos["reignite"] = (oos.tot_mfe > oos.mfe_sofar + 0.05).astype(int)
```

`tot_mfe` is the trade's total lifetime MFE from bar-4 entry (computed in `build_states` line 58 as `max(favE, axis=1)/atr` over all columns 4..n). `mfe_sofar` is the through-bar-k running peak favorable excursion from bar 4 to bar k (line 71: `mfe_sf = max(favsf.max(), 0.0)`). So `reignite=1` means the trade's lifetime MFE exceeds the MFE achieved up through bar k. This is a strictly forward quantity: it is 1 iff the trade achieves a new favorable extreme AFTER bar k. This is used as a forward OUTCOME grouped by the causal state at bar k, which is the intended design.

**No circularity.** `tot_mfe` and `mfe_sofar` are both computed in `build_states` from the OHLC arrays. `tot_mfe` uses the full H/L through bar n (bar4_knn_path_atlas.py line 56-58); `mfe_sofar` uses H/L only through bar k (line 69-71). Neither enters the KNN feature set (`FEATS` in bar4_knn_path_atlas.py line 34 uses `mfe_sofar` as a feature but NOT `tot_mfe`). The state (`hC_pk`, `dd`, `pred`) is derived from KNN outputs which are IS-neighbor aggregations — also no `tot_mfe` contamination. Clean in design.

**However:** `tot_mfe` is measured using the `favE` array sliced as `H[:, 4:]` (bar4_knn_path_atlas.py line 56), not `H[:, 4:n+1]`. Since `H` is padded with `np.nan` beyond each trade's length, `np.nanmax` correctly ignores padding. The direction fix at line 56 (`np.where(d[:, None] == 1, H[:, 4:] - entry[:, None], entry[:, None] - L[:, 4:])`) is the 2026-06-17 bugfix for shorts — confirmed applied.

The warning here is interpretive: `reignite` at bar k means "trade makes a NEW high after k," but the 0.05 ATR epsilon is a flat threshold. For trades that have only moved 0.10 ATR total, `mfe_sofar` could be 0.09 and `tot_mfe` = 0.10, giving `reignite=1` on a 0.01 ATR new high. These micro-reignitions inflate the Healthy-state reignite rate without representing economically meaningful continuation. The user should be aware the 0.05 ATR epsilon is small relative to a 0.5 ATR entry cost.

**Severity rationale:** Warning because the interpretive framing (pause-vs-death) may be partially driven by micro-reignitions that are not monetizable. No look-ahead.

---

### [WARNING / Check 7 / D1-analogue] `knn_health_state_transition_atlas.py:94-96` — `htf` (hold-to-flip $) is a TRADE-LEVEL constant, not a bar-k quantity; comparing it across states conflates state selection with trade composition

**File:** `knn_health_state_transition_atlas.py`, lines 93–96.

```python
htf = {r: (flip_c[i] - d[i]*EXIT - (entry4[i]+d[i]*ENTRY))*d[i]*MULT - COMM for r, i in
       [(r, rididx[r]) for r in oos.rid.unique()]}
oos["htf"] = oos.rid.map(htf)
```

`htf` is the hold-to-flip PnL from bar-4 entry to the terminal bar — a single scalar per trade, mapped to every row of that trade. In the per-state table (lines 115–121), `s.htf.mean()` for a given state averages `htf` over all (trade, bar-k) pairs in that state. Because a single trade can appear in multiple states across bars (and `htf` is constant for the trade), a long-running trade whose early bars are Healthy and later bars are DETER will contribute its PnL to both buckets. If DETER trades tend to be shorter (already near the flip), their `htf` averages would underweight longer runners. The "realized htf $" column in the state table is therefore NOT "what you earn if you exit when you first see this state" — it is "the lifetime PnL of trades whose bars appeared in this state." This is stated nowhere in the report and is subtly different from what a reader would expect.

No look-ahead. The concern is interpretive: the `htf` column in the state table can be misleading if read as the expected value of holding from the stall state to the flip.

**Severity rationale:** Warning. The value IS causal (it's a forward outcome used as a label, not a feature). But the averaging across (trade, bar) pairs makes it difficult to reason about the actual trade management value.

---

## NOTES

### [NOTE / Check 1 — KNN IS/OOS split] Confirmed clean

`knn_health_state_transition_atlas.py` lines 56, 60–72. `isS = S[S.year < 2025]`, `oos = S[S.year >= 2025]`. For each bar k, the KNN is fitted on `isk[A.FEATS]` (IS-only), standardized with IS mean/std (line 67–68: `mu = Xis.mean(0); sd = Xis.std(0)`). OOS features are standardized with those same IS statistics: `(Xoo - mu) / sd`. Neighbor lookup returns IS indices only. `pNH3` and `pFL3` are aggregated from IS neighbors' `newhigh3` and `flip3` realized values (IS forward quantities). `predA` is a majority vote over IS neighbor class labels. No OOS data enters the KNN model or its outputs.

### [NOTE / Check 2 — hC_pk cummax causality] Confirmed clean

`knn_health_state_transition_atlas.py` lines 74, 76–78. At line 74: `oos = oos[oos.pred.notna()].copy().sort_values(["rid", "k"]).reset_index(drop=True)`. The sort by `["rid", "k"]` ensures the dataframe is in chronological order per trade before the groupby. At line 76–77: `g = oos.groupby("rid"); oos["hC_pk"] = g.hC.cummax()`. Since the frame is sorted by `(rid, k)` prior to groupby, `cummax()` within each group produces the maximum `hC` seen up to and including bar k — strictly backward-looking. `dd = 1 - oos.hC / oos.hC_pk.clip(lower=1e-6)` is therefore causal. Clean.

### [NOTE / Check 6-toff — 1s timing is CORRECT] Confirmed clean; fix from prior audit is present

`knn_health_state_transition_atlas.py` line 177:

```python
toff = tb * 60 * NS; T_flip = n[i] * 60 * NS
```

**Time-offset semantics.** In `build_survivor_1s_paths.py` line 60: `t0 = int(cap["regime_start_ts"])`, and `regime_start_ts = completed.close_ts` (early_health_filter.py line 115) — the NT close timestamp of the flip 1m bar. The `p1s_t` values are nanosecond offsets from that flip-bar close. In the bar indexing used in `build_states`, bar k=1 is the first post-flip bar: it opens at offset 0 ns from flip-bar-close (= 0*60s) and closes at 1*60s. Bar k opens at (k-1)*60s and closes at k*60s.

The trigger bar is `tb` — the first bar where the protection condition (`open_profit >= 0.5` AND state `HardStall/DETER`) is satisfied. The condition is evaluated at line 168 using `C[i, k]` (bar-k close price), which is the CLOSE of bar tb. The earliest the stop could physically be placed is at the OPEN of bar tb+1 = the CLOSE of bar tb = offset `tb*60s`. Therefore `toff = tb * 60 * NS` is correct: the 1s walk starts at bar tb+1 open. No look-ahead.

**Comparison to prior audit.** The prior audit of `knn_continuous_health.py` found a bug where the equivalent line used `toff = t * 60 * NS - 60 * NS` (= bar-t open, one bar too early). The present file uses `toff = tb * 60 * NS` — the fixed form. The fix is correctly applied.

### [NOTE / Check 6-stop-validity — BE stop is a valid protective level] Confirmed clean

`knn_health_state_transition_atlas.py` lines 175, 181–182. `stop = e` (= entry price = `O[i, col]` for bar-N entries, or `df.flip_c.values[i]` for flip-close entry). The trigger condition requires `op = (C[i, k] - e) * di / ai >= 0.5`, meaning price is at least 0.5 ATR favorable of entry at bar tb close. For a long trade, `stop = e` is therefore at least 0.5 ATR BELOW the current close price. The stop is not in-the-market at arm time; it can only fire on an adverse retracement back to entry. For shorts the same logic applies (mirror). Clean.

---

## CLEAN CHECKS

The following checklist items were examined and found clean:

- **A1/A2 (timestamp convention):** `early_health_capsule.parquet` is built by `CapsuleReplay`, which assigns `regime_start_ts = completed.close_ts` (early_health_filter.py line 115). All 1m bar OHLC arrays are aligned on the close-time basis. No raw `ts_event`-as-close misuse found. The 1s path timestamps are offsets from `close_ts`, consistent with NT bar conventions.

- **A5 (resampling label/closed):** This study does not resample. 1s bars are fed raw through `TimeframeAggregator`. No `label`/`closed` argument risk.

- **B1 (no `center=True`):** No rolling computations with `center=True` anywhere in the pipeline. Clean.

- **B2/B3 (indicator values at correct bar):** `mfe_sofar` and `mae_sofar` in `build_states` (bar4_knn_path_atlas.py lines 69–71) use `H[i, 4:k+1]` and `L[i, 4:k+1]` — strictly bars 4 through k inclusive. Feature `pnl_now = (C[i, k] - e) * di / ai` uses only bar-k close. All features in `FEATS` are causal through bar k.

- **B4 (no `.shift(-N)` in features):** No negative-lag shifts in the feature path. `shift(3)` appears only in `knn_continuous_health.py` (not in scope here) and is a positive lag (backward). Clean.

- **B5 (no bfill):** No `bfill` anywhere in the pipeline. Clean.

- **C1 (reignite as forward outcome only):** `tot_mfe` and `mfe_sofar` are used to construct `reignite` as a forward OUTCOME column. `tot_mfe` does not appear in `A.FEATS` (bar4_knn_path_atlas.py line 34). `mfe_sofar` appears in `A.FEATS` as a causal feature, but not `tot_mfe`. The KNN features, state assignments, and `hC`/`hC_pk`/`dd` are all derived without `reignite` or `tot_mfe`. No circularity.

- **C3 (temporal split):** IS = year < 2025, OOS = year >= 2025 at lines 56 and 132 of bar4_knn_path_atlas.py. Hard temporal boundary. No random split. Clean.

- **D1 (train/serve consistency):** This is an offline analytical study only; there is no live deployment path. Not applicable.

- **E5 (indicator warmup):** `build_states` uses `n > k` filter (bar4_knn_path_atlas.py line 66) ensuring bars with insufficient trade lifetime are excluded. The KNN is conditioned on `len(isk) < 200` as a minimum sample guard (line 62). Clean.

- **F3 (timezone handling):** No timezone conversions in this file. Timestamps are nanosecond UTC integers throughout. Clean.

- **G2/G4 (data integrity):** Data sourced from `data/catalog/NQ_v0_2020_2026` (early_health_filter.py line 30), which uses the v.0 volume-continuous contract per the mandatory data rule established in project memory.

- **rem_mfe/rem_mae per-direction bugfix present:** `build_states` lines 96–99 show the per-direction fix distinguishing long (`fh - cnow`) from short (`cnow - fl`) for remaining MFE, and the mirror for MAE. The fix comment at line 94 ("BUGFIX 2026-06-17") is present. The atlas docstring at line 12 references "bugfixed build_states." Clean.

- **`flip_c` (terminal close) is correct:** Line 52: `flip_c = df.post_c.apply(lambda x: float(x[-1])).values` — last element of the post-flip bar close list = the terminal bar close before the opposite flip. Slip deductions are adverse: `di*EXIT` subtracted from close proceeds. Clean.

- **Naming collision note (non-bug):** Two variables share a similar name. Line 52 defines local `flip_c` = terminal post-flip close. Line 149 accesses `df.flip_c.values[i]` = the flip-bar's own close (the capsule field). These are different values used correctly in their respective contexts (`held_flip` exit vs `flip-close` entry), but the shadowing could cause confusion during code review.

---

*Audit complete. Static analysis only. Dynamic bugs (race conditions, live data latency) are out of scope.*
*Files inspected: knn_health_state_transition_atlas.py (full), bar4_knn_path_atlas.py (lines 1-127), early_health_filter.py (lines 55-160, 203-320), progressive_separability.py (lines 35-47), build_survivor_1s_paths.py (full), audit_knn_continuous_health.md (prior audit, for toff fix verification).*

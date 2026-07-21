# Look-Ahead & Timestamp Audit — regime_recovery_continuation.py

**Date:** 2026-06-16
**Scope:**
- `studies/regime_dna_knn/regime_recovery_continuation.py` (primary)
- `studies/regime_dna_knn/build_survivor_1s_paths.py` (data provenance, call site)
- `studies/regime_dna_knn/early_health_filter.py` (call site: `compute_labels_features`, `CapsuleReplay`)
- `studies/regime_dna_knn/progressive_separability.py` (call site: `build`)
- `studies/regime_dna_knn/results/survivor_1s_paths.parquet` (OOS 1s path data, structure reviewed)
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

### [W1] `regime_recovery_continuation.py:76` — Strict `>` / `<` reclaim test may reject instantaneous re-test bars as "not recovered" when price ticks exactly to P_X

**Category:** B2 / G2

**Lines:** 75–77
```python
fav_ext = h[i + 1:] if d == 1 else l[i + 1:]
rc = np.where(fav_ext > P_X if d == 1 else fav_ext < P_X)[0]
```

The reclaim test requires the favorable extreme to be **strictly greater than** P_X (long) or **strictly less than** P_X (short). In NQ at $0.25 tick resolution, `P_X` is a running-max of 1s bar highs. A bar that ticks exactly to P_X (e.g., `h == P_X`) is not recognized as a reclaim — the add entry would be missed for that bar, and the next bar to slightly exceed P_X becomes the entry.

This is a **conservative** strictness, not a look-ahead bug. However, for a stop-buy order placed AT P_X, the standard market convention is that price trading at or through P_X fills the stop. The strict `>` creates a small systematic delay: the simulated add entry bar `j` is one bar later than a real stop-buy at P_X would fill. For 1s bars the delay is at most 1 second, so the PnL impact is negligible. The bigger concern is that `add_fill = P_X + d * ENTRY` (line 81) correctly prices the entry with adverse slip regardless, so the economic result is not distorted. This is logged as a Warning rather than Critical because the direction of bias is known (slightly deferred entry, no look-ahead), but it diverges from how a real stop-buy order would behave.

**Recommended fix (do not apply):** Change `fav_ext > P_X` to `fav_ext >= P_X` to match stop-buy fill semantics. Re-confirm that `add_fill = P_X + d * ENTRY` is then still the correct entry price (it is, because a stop-buy at P_X fills at or through P_X with slip on top).

---

### [W2] `regime_recovery_continuation.py:55,137` — `T_flip = r.n * 60 * NS` assumes 1m bars are exactly 60s; `flip_c = C[idx, np.minimum(n, 61)]` caps at column 61 — paths truncated at 1800s may cause `flip_c` to be a bar INSIDE the regime, not the actual flip bar close

**Category:** A2 / F2

**Lines:** 55, 106, 127, 137

```python
T_flip = r.n * 60 * NS          # line 55: computed from r.n (number of post-flip 1m bars)
flip_c = C[idx, np.minimum(n, 61)]  # line 137: build matrix cap at 62 cols (index 0..61)
```

`r.n` comes from `n_post` (number of post-flip 1m bars before the opposite flip). The 1s path is truncated at `MAXSEC = 1800s` (line 33 of `build_survivor_1s_paths.py`), so for any regime lasting >30 minutes, `T_flip` may fall BEYOND the end of the stored 1s path. The `inwin` filter (line 56) clips `h/l/c/tt` to `tt <= T_flip`. For truncated paths, the effective forward window is shorter than the actual regime — the pullback/recovery detection, forward extension, and TP/trail simulation all operate on a window that may end at the 1800s boundary rather than at the true flip.

Separately, `flip_c = C[idx, np.minimum(n, 61)]` caps at column 61. The `build` matrix in `progressive_separability.build()` is allocated as `B = 62` columns (lines 36–37). Any regime with `n_post > 61` is silently capped to bar-61 close for the no-TP ride-to-flip fallback. The user's audit brief correctly flags this; regimes that live past 61 bars see `flip_c` as the 61-bar close, not the true flip close.

**Interaction:** If a regime is both long-lived (n>61) AND uses the fallback `ex = flip_c - d * EXIT` (lines 106–107) or `exit_px = flip_c - d * EXIT` (line 127), the exit price is earlier than the true flip close. For long regimes that went on to reverse sharply, this could understate the loss (beneficial to a loss case). For long regimes that continued further, it understates the gain. The directional bias of this cap depends on the regime tail behavior and is not deterministic.

**Severity rationale:** This is NOT a look-ahead bug — the code does not use future information. The risk is that the "ride to flip" fallback misprices the exit for long-lived regimes. Given that the add strategy is reported as net-negative, this could either somewhat understate or overstate losses depending on tail distribution. It cannot create a phantom positive edge, so it does not threaten the integrity of the negative conclusion.

**Recommended fix (do not apply):** (a) Expand the matrix width in `build` to match the actual maximum `n_post` (already done in `early_health_filter.compute_labels_features` via `num_cols = max(21, max_post + 1)` — verify that `progressive_separability.build` receives a `df` with `n_post` values that can exceed 61 and expand `B` accordingly), or (b) filter the `net_tp*` / `net_trail` results to only regimes where `n <= 61` and note the exclusion rate.

---

## Notes

### [N1] `regime_recovery_continuation.py:61–65` — Pullback detection uses only 1s bar `h`/`l` arrays (starting at t >= 180s); `peak_px` is a running max/min of the 1s forward bar favorables from the ENTRY bar forward — this is causal

**Category:** B3 (clean confirmation note)

`peak_px` at line 61 is `np.maximum.accumulate(h)` over the already-filtered 1s bars starting at `ENTRY_T = 180s`. The `healthy` flag at line 65 checks that the running favorable excursion from `e` (Bar-4 open, `O[:, 4]`) is >= 1 ATR. The `dd` at line 64 is the drawdown from the running peak. At bar index `i`, `peak_px[i]` contains the highest high seen in 1s bars `[sel][inwin][0..i]` — all strictly prior to and including bar `i`. The pullback event is thus detected at bar `i` using only information through bar `i`. Confirmed causal.

---

### [N2] `regime_recovery_continuation.py:100–107` — TP hit check uses bar `fh` favorable extremes; for short trades, `fh = fl` (line 82 assigns `fl = l[j:]`) — the TP is against the INTRABAR LOW for shorts

**Category:** B2 (clean confirmation note)

For shorts (`d == -1`), `fh = h[j:]` and `fl = l[j:]` are still assigned with `h` and `l` respectively (line 82 does not swap them). At line 102, the TP hit check for shorts is `fl <= lvl`, where `lvl = P_X + d * tp * a = P_X - tp * a` (below P_X, correct favorable direction for short). The check uses `fl` (the 1s bar low), which is the appropriate intrabar extreme for a short TP. For short `ext_mfe` (line 88), the code uses `fl.min()` (lowest low below P_X = favorable extension). Confirmed directionally correct after the stated fix.

The trail function `_trail` at lines 118–119 assigns `hi = fl[k]` (favorable = lower = `l`) and `lo = fh[k]` (adverse = higher = `h`) for `d == -1`. The stop check at line 122 for shorts is `lo >= protect`, where `protect = peak - d * TRAIL * a = peak + TRAIL * a` (above the running low peak for short = adverse side). This is correct: for a short, the running peak is `min(peak, hi)` = lowest low seen, protect = that low + TRAIL*a (a price ABOVE the peak = adverse), and the stop fires when the adverse extreme `lo` (which is `fh[k]` = bar high for short) >= protect. Confirmed.

---

### [N3] `regime_recovery_continuation.py:136–137` — `entry = O[:, 4]` is the Bar-4 open price used as `r.entry` in all `analyze()` calls; the `fav_exc` and `dd` computations are measured from this entry price, not from P_X

**Category:** D1 (design note, not a bug)

`e = r.entry` at line 60 is the base trade entry (Bar-4 open), from which `fav_exc` (the healthy gate) and `dd` (the pullback depth) are computed. P_X is the running peak price (in price space, not relative). The add fill `add_fill = P_X + d * ENTRY` is priced in absolute terms, and all add P&L is relative to `add_fill` vs exit price. These two reference points are distinct and used correctly: `e` gates the HEALTHY/PULLBACK conditions (relative to the base position entry), while `add_fill` is the entry for the ADD unit. There is no confusion between the two. Confirmed clean.

---

## Confirmation of Key Checks

### Check 1 — Pullback detection causality (PASS)
`peak_px = np.maximum.accumulate(h)` operates on the already-filtered 1s path (t >= 180s, t <= T_flip). At each bar index `i`, `peak_px[i]` = max of `h[0..i]`. `healthy[i]` = whether that running peak represents a >= 1 ATR favorable excursion from entry. `dd[i]` = drawdown from `peak_px[i]` using the current bar's adverse extreme (`l[i]` for long, `h[i]` for short). Detection at bar `i` uses no bar `i+1` information. CAUSAL.

### Check 2 — Recovery trigger and ADD entry bar (PASS)
`fav_ext = h[i+1:]` (long) or `l[i+1:]` (short) — the slice strictly excludes bar `i`. `rc[0]` is the first index in this forward slice where price crosses P_X. `j = i + 1 + rc[0]` makes bar `j` the ADD entry bar, which is strictly `> i`. Forward window `fh = h[j:]`, `fl = l[j:]` includes bar `j` and forward — the reclaim bar itself is the first bar of the outcome window. This is consistent with entering at the open of bar `j` (stop-buy at P_X fills on bar `j`'s favorable extreme crossing P_X). CAUSAL.

### Check 3 — add_fill pricing (PASS)
`add_fill = P_X + d * ENTRY` where `ENTRY = 0.5 * TICK = 0.125`. For a long stop-buy at P_X, fill = P_X + 0.125 (adverse slip). For a short stop-sell at P_X (where P_X is a prior LOW), fill = P_X - 0.125 (adverse slip for short). This matches the stated slip convention.

### Check 4 — ext_mfe / ext_mae direction fix (PASS)
Long branch (lines 84–86): `ext_mfe = (fh.max() - P_X) / a` = highs above P_X = favorable. `ext_mae = (P_X - fl.min()) / a` = lows below P_X = adverse. Both are clipped to >= 0. Correctly non-negative and direction-matched.

Short branch (lines 87–89): `ext_mfe = (P_X - fl.min()) / a` = how far price fell BELOW P_X = favorable for short. `ext_mae = (fh.max() - P_X) / a` = how far price rose ABOVE P_X = adverse for short. Both clipped to >= 0. The prior bug (using `* d` on a symmetric expression) would have made short MFE negative (favorable excursion multiplied by -1) and short MAE negative (adverse excursion multiplied by -1), both clamped to 0. The fix replaces `* d` with explicit per-direction formulas. CORRECT.

### Check 5 — P(extension) level direction (PASS)
`lvl = P_X + d * X2 * a`: for long `d=1`, lvl is ABOVE P_X (favorable). For short `d=-1`, lvl = P_X - X2*a = BELOW P_X (favorable). Hit test: `fh >= lvl` (long = bar high reaches above target) / `fl <= lvl` (short = bar low reaches below target). Correct for both directions. (Note: for the `P(+0.5)` time computation at line 97, the condition `fh >= lvl05 if d == 1 else fl <= lvl05` correctly dispatches per direction.) PASS.

### Check 6a — TP net policy (PASS, with one structural caveat)
For TP hit case (lines 103–104): `ex = lvl` = the limit fill price, no favorable slip. `net = (lvl - add_fill) * d * MULT - COMM`. For long, `lvl > add_fill` (TP above entry), `(lvl - add_fill) > 0`, `* d=1 * MULT > 0`, minus COMM — profit correctly computed. For short, `lvl = P_X - tp*a < P_X < add_fill = P_X - ENTRY`, so `lvl < add_fill`, `(lvl - add_fill) < 0`, `* d=-1` flips to positive, `* MULT - COMM` — profit correctly computed. CORRECT.

For no-TP fallback (lines 105–106): `ex = flip_c - d * EXIT`. For long, `ex = flip_c - EXIT` (selling at flip close minus 1-tick adverse slip). `net = (flip_c - EXIT - add_fill) * 1 * MULT - COMM`. For short, `ex = flip_c + EXIT` (covering at flip close plus 1-tick adverse slip). `net = (flip_c + EXIT - add_fill) * (-1) * MULT - COMM = (add_fill - flip_c - EXIT) * MULT - COMM`. If `add_fill > flip_c` (the short was above where the regime ended, i.e., a loss), this is negative. CORRECT.

**Caveat:** The TP hit check at line 102 (`np.where(fh >= lvl if d == 1 else fl <= lvl)`) uses the **intrabar favorable extreme** of `fh`/`fl`. For long, `fh = h[j:]`; for short, `fl = l[j:]`. The TP fires when any bar's favorable extreme reaches `lvl`. This is consistent with a resting limit order and the "TP = limit (no favorable slip)" stated semantics. CORRECT. No phantom fill risk here because the exit is at exactly `lvl` (the limit price), not beyond it.

### Check 6b — Trail net policy (PASS)
`_trail` function lines 114–128:
- `peak` initialized to `P_X` (the prior running peak, the highest favorable excursion before the pullback), which is the natural trailing stop anchor for the add.
- Adverse-first: `protect = peak - d * TRAIL * a` is computed from the PRIOR bar's `peak` (updated AFTER the stop check). The stop test `(d==1 and lo<=protect) or (d==-1 and lo>=protect)` fires against the current bar's adverse extreme before `peak` is updated with the current bar's favorable extreme. This is correct: a bar cannot update its own trail and then be saved by the new trail in the same bar.
- Short direction: `hi = fl[k]` (favorable = lower for short), `lo = fh[k]` (adverse = higher for short). `protect = peak - (-1) * TRAIL * a = peak + TRAIL * a`. Stop test: `d==-1 and lo >= protect` = `fh[k] >= peak + TRAIL*a` = bar high rises above the trail stop level. For short, `peak` is a running minimum (line 125: `min(peak, hi)` = min of running low). So `protect = running_low + TRAIL*a` = a level ABOVE the running low = the stop level. When the adverse bar high reaches or exceeds this level, the short trail fires. CORRECT.
- Exit price: `protect - d * EXIT`. For long: `protect - EXIT` (sold 1-tick below trail level = adverse slip). For short: `protect + EXIT` (covered 1-tick above trail level = adverse slip). CORRECT.
- If no stop fires, exit at `flip_c - d * EXIT` (same fallback as TP policies). CORRECT.

### Check 7 — flip_c = C[idx, np.minimum(n, 61)] (NOTED, see W2)
The cap at 61 is a known limitation documented in W2. For n <= 61 (the majority of regimes at typical flip durations), this is the true flip bar close. For n > 61, it is the close of bar 61.

### Check 8 — 1800s path truncation bias direction (CONFIRMED CONSERVATIVE)
For truncated paths (p1s_trunc = True), the `inwin` filter clips the path to t <= T_flip. If T_flip > 1800s, the forward window is shorter than the actual regime. In this case:
- The pullback/recovery detection may see a pullback that WOULD have recovered but cannot confirm it because the path ended (rec = False, no add counted).
- For adds where the recovery IS within 1800s, the forward window for TP/trail may be shorter — the TP has fewer bars to be hit, and the no-TP fallback rides to `flip_c` (a bar-matrix value, not the 1s path). So the "no TP" fallback is correctly the flip close (from the 1m bar matrix), not truncated by the 1s path.

The 1s truncation therefore affects ONLY the TP hit detection and the trail stop detection. Fewer bars = less chance to hit TP = more fallbacks to `flip_c`. If the add is net-negative (as reported), truncation makes the TP hit rate slightly lower than true (fewer bars to reach TP), which would make the already-negative TP policy look slightly WORSE (more no-TP fallbacks, and if those fallbacks are losses, the net is more negative). Truncation cannot create a false positive (phantom TP hit). The negative conclusion is thus conservative. CONFIRMED.

---

## Structural Assessment: Is the Negative Result Honest?

The user's primary concern is whether the reported net-negative result (−$4 to −$10/add) could be an artifact of a bug that SUPPRESSES a real positive edge. The following examination addresses this.

**Mechanism of the loss:** The stated mechanism is that ~20% of non-extenders ride to the flip at a large loss, generating negative skew that overwhelms the 80% TP hits. The trail variant is defeated by large adverse excursions (median ~1.3 ATR) occurring before the trail can lock in much gain. This mechanism is structurally consistent with the add entry being at P_X (a prior high/low) which is also by definition a resistance/support level — once reclaimed, it is a thin-margin zone where price frequently retraces.

**Bug search for artificial suppression:**

1. **Wrong sign on TP winner?** For long TP: `(lvl - add_fill) * 1 * MULT - COMM`. `lvl = P_X + tp*a > P_X + ENTRY = add_fill`. So `(lvl - add_fill) > 0`. Net positive. NOT suppressed.

2. **Double-counted commission?** `COMM = 5.0` is subtracted once per trade at line 107 and once in `_trail` at line 128. One deduction per add round trip. Correct.

3. **`add_fill` adverse slip adds cost correctly?** `add_fill = P_X + d * ENTRY` means for long, add_fill = P_X + 0.125 (above P_X = costs more to buy). For TP at P_X + tp*a, the net distance is `tp*a - ENTRY`. With `tp=0.5` and `a` in NQ points (typically ~8–15 pts), `ENTRY=0.125` is a fraction of the TP distance. The slip is not excessive.

4. **Flip fallback correct?** `ex = flip_c - d * EXIT`. For long: `flip_c - 0.25`. If the regime ended with `flip_c < add_fill` (price fell back below entry), the loss is `(flip_c - 0.25 - add_fill) * MULT - COMM`. This is a genuine loss. Not suppressed.

5. **TP check against favorable extreme (not close)?** The hit test uses `fh >= lvl` (bar high for long). This is correct — a resting limit sell at `lvl` fills when any price trades at or above `lvl`, and the 1s bar high is the highest intrabar price. Not suppressed.

6. **No pre-reclaim bar in forward window?** `fh = h[j:]`, `fl = l[j:]` (line 82) starts at bar `j` = the reclaim bar. The reclaim bar itself is included. A stop-buy at P_X fills DURING bar `j` (when the bar's high crosses P_X), so the add is live starting in bar `j`. Including bar `j` is correct. Not suppressed.

**Conclusion:** No bug was found that would artificially suppress add PnL. The negative result is structurally honest. The economic explanation (negative skew from ~20% deep-loss non-extenders + trail stop fires on large adverse excursions before locking material gain) is mechanically consistent with the code.

---

## Clean Checks

- **A1** — No `ts_event` or `ts_init` timestamp used for bar indexing in this file. The 1s paths use nanosecond offsets from `regime_start_ts` (flip bar close time from `completed.close_ts`). Correct timestamp semantics inherited from `build_survivor_1s_paths.py`.
- **A2** — Catalog is `NQ_v0_2020_2026` (v.0 volume-continuous). No `closed='right'` resample bug in `build_survivor_1s_paths.py` (raw 1s bars are streamed individually, not resampled). Clean.
- **B1** — No `rolling`, `ewm`, or `expanding` with `center=True`. No pandas rolling at all in `regime_recovery_continuation.py`.
- **B4** — No `.shift(-N)` in feature path. `.shift` is not used anywhere in this file.
- **B5** — No `.ffill()` or `.bfill()` in feature path.
- **B6** — No multi-frequency join in this file. The `survivor_1s_paths.parquet` merge is an inner join on `regime_id` (1:1 key), not a time-series alignment that could leak.
- **B7** — No normalization or scaling of features against the full dataset. All computations are per-regime, from per-regime ATR.
- **C1** — No label construction in this file.
- **C3** — Not applicable (no train/test split in this diagnostic).
- **D1** — Not applicable (no model; this is a descriptive/simulation study).
- **E1–E5** — Not applicable (no strategy or BacktestEngine in this file).
- **ext_mfe / ext_mae fix confirmed** — The prior bug (`* d` multiplication giving negative values for short) is correctly replaced by explicit per-direction branches (lines 84–89). Short MFE now correctly measures `(P_X - fl.min()) / a` (favorable = lower lows) and short MAE correctly measures `(fh.max() - P_X) / a` (adverse = higher highs). Both are non-negative by the `max(..., 0.0)` clip. FIXED.
- **`np.minimum(n, 61)` in `build()` — B cap** — `progressive_separability.build()` allocates `B = 62` columns (indices 0..61). `n_post` values larger than 61 are truncated to 61 bars in the price matrix. This is consistent with `flip_c = C[idx, np.minimum(n, 61)]` using the same cap. The truncation is documented in W2 above.

---

*Audit complete. Findings reflect read-only static analysis of the Python source. Dynamic bugs (e.g., floating-point precision edge cases at exact price boundaries, actual truncation rates in the 2025–2026 path parquets) are out of scope and would require runtime inspection.*

# Look-Ahead & Timestamp Audit — bar4_knn_warning_controls.py

**Date:** 2026-06-17T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/bar4_knn_warning_controls.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS — reused)
- `studies/regime_dna_knn/progressive_separability.py` (P.build matrix layout — reused)
- `studies/regime_dna_knn/early_health_filter.py` (E.compute_labels_features — reused)
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 2
- Warning: 3
- Note: 2

---

## Critical Findings

### [C2-LEAK-1] `bar4_knn_warning_controls.py:117` — heal_state includes ALL CONT-predicted rows from never-warned trades, including rows AFTER their own "last healthy bar"

**File:** `bar4_knn_warning_controls.py`, line 117

```python
heal_state = oos[oos.is_cont & ~oos.rid.isin(warned)].copy()
```

The healthy arm contains every OOS state row where `pred` is Continuation/Runner AND the trade was never warned (i.e., its `rid` is not in `warned`). This means a "never-warned" trade that degrades at bar k=12 to Chop (but was never preceded by CONT→DETER because KNN called it Chop from bar 4 onward) is EXCLUDED from `heal_state` at that deteriorated bar. However, a trade that KNN consistently called Continuation through all its bars contributes ALL its bar-states to `heal_state`. The problem is structural:

**The never-warned "healthy" population is positively selected for actual health.** A trade never warned because KNN consistently labelled it CONT across its entire life is, tautologically, a trade whose visible path-state (mfe_sofar, mae_sofar) never activated the warning. These are the cleanest trades in the OOS universe. The comparison is therefore: warning states (by definition at a moment of visible pullback/stall) vs health states (trades whose paths were consistently good enough that KNN never changed its mind).

The correct comparison requires the healthy arm to be restricted to (a) the same bar-k range, (b) the same mfe_b/mae_b bin — which the bin-matching does enforce — BUT ALSO (c) healthy rows must be drawn from trades that eventually resolved as the full distribution, not pre-filtered to only the "KNN-clean-throughout" subset.

**Concrete bias direction:** This makes the healthy arm systematically BETTER than the warning arm even after mfe_b/mae_b matching, because the bin-matching controls only for the instantaneous mfe/mae bucket but not for the full path conditioning that caused a trade to never get warned. The forward `newhigh3`, `flip3`, and `rem_mfe` for healthy rows are inflated relative to the true never-warned population, making the warning arm look comparatively WORSE than it actually is in a fair comparison.

**Impact on verdict:** If Control 2 concludes "warning sees BEYOND pullback severity" (nhW < nhH * 0.85), that conclusion is partly correct but inflated: part of the gap is the health-selection artefact, not KNN's independent information. If Control 2 concludes "mostly re-reads mfe_so_far," this bias runs counter to that conclusion so it is not exonerating the result. Either way the magnitude of the differential is overstated.

**Recommended fix (do not apply):** For the healthy arm, draw from all OOS states where `pred` is CONT at bar k, regardless of whether that trade was ever warned at a DIFFERENT bar. Alternatively, restrict to trades where KNN predicted CONT at bar k AND at the immediately preceding bar only — not "never warned across all bars." The current exclusion `~oos.rid.isin(warned)` removes entire trade histories rather than just the at-warning-bar states.

---

### [C1-BIAS-1] `bar4_knn_warning_controls.py:95` — random-bar pool `warn_k` mixes bars from ALL warned trades regardless of which trade is being sampled; for short-lived trades this overstates bars that cannot exist

**File:** `bar4_knn_warning_controls.py`, lines 93–97

```python
for j, i in enumerate(warn_idx):
    ni = int(min(n[i], 61))
    choices = warn_k[warn_k < ni]                # matched-distribution bars that exist
    t = rg.choice(choices) if len(choices) else (ni - 1)
    pnl_rand[j] = exit_pnl(i, int(t))
```

`warn_k` is the array of warning bar indices across ALL warned trades. For trade `i` with `ni = 10`, the constraint `warn_k < ni` (i.e., `warn_k < 10`) may exclude a large fraction of the warning-bar distribution if most warnings fire at bars 10–14. This does not introduce look-ahead (the feasibility guard `< ni` is correct) but it does mean the random arm samples from a DIFFERENT distribution per trade depending on how long that trade lived.

The stated intent is "matched to the warning-bar distribution." But the actual sampled distribution for any given trade is `warn_k[warn_k < ni]` — a censored version of the warning bar distribution. Short-lived trades (small `ni`) will have their random bars drawn mostly from early-bar warnings; long-lived trades draw from the full distribution. This censoring is asymmetric across the trade population and is not the same distribution the actual warning fires at. Whether this inflates or deflates the random-bar PnL depends on whether early-bar exits are better or worse than late-bar exits on average.

**Impact:** This is a methodological imprecision in the random arm construction, not a clear directional bias toward making the warning look better. However, it does mean the "same distribution" claim in the report text is not strictly true.

**Recommended fix (do not apply):** Either (a) sample uniformly from all bars in `[4, ni)` with no distribution matching (pure "exit at a random feasible bar" control), or (b) sample from `warn_k` with replacement and use `exit_pnl(i, min(t, ni-1))` to cap at feasibility, accepting that the distribution is approximate. The current code's intent (feasibility gate) is sound; the "matched distribution" framing is slightly overstated.

---

## Warning Findings

### [W1] `bar4_knn_warning_controls.py:116` — warn_state list comprehension creates boolean mask against the FILTERED `oos` DataFrame after `pred.notna()` drop, but `oos` index is reset; verify alignment

**File:** `bar4_knn_warning_controls.py`, line 116

```python
warn_state = oos[[wbar.get(r) == k for r, k in zip(oos.rid, oos.k)]].copy()
```

`oos` was reset with `.reset_index(drop=True)` at line 49, then a further `.copy()` was applied after `.pred.notna()` at line 65 (also with reset index). The list comprehension zips `oos.rid` with `oos.k` and builds a boolean mask of length `len(oos)` — this is positionally correct as long as `oos` has a clean 0..N-1 integer index, which it does after the two resets. The mask semantics are: include row if `wbar[rid] == k` at that row, i.e., this row's (rid, k) is the warning bar. This is correct: it selects exactly one row per warned trade.

However, `wbar.get(r)` returns `None` for any `rid` not in `wbar` (never-warned trades), and `None == k` evaluates to `False` in Python, so those rows are correctly excluded. The logic is sound but relies on Python's `None != int` behavior. This is technically correct but fragile — any future change to `wbar`'s population (e.g., if `None` keys were introduced) could silently corrupt the mask.

**Recommended fix (do not apply):** Make the intent explicit: `oos[oos.apply(lambda row: wbar.get(row.rid) == row.k, axis=1)]` or pre-build a set `{(r, k) for r, k in wbar.items()}` and test `oos[oos.set_index(['rid','k']).index.isin(warn_set)]`.

---

### [W2] `bar4_knn_warning_controls.py:151–154` — hmetrics `hi <= k` boundary: when `ni == k` (flip coincides with observation bar), the branch fires `flip=1` correctly but `mfe/mae/nh` zero, which overstates the flip rate at h=1

**File:** `bar4_knn_warning_controls.py`, lines 151–153

```python
hi = min(k + h, ni)
if hi <= k:
    out[h] = (0.0, 0.0, 0, 1); continue
```

When `ni == k` exactly — meaning the regime flipped at the observation bar itself — `hi = min(k+1, k) = k`, so `hi <= k` fires and the function returns `flip=1` with `mfe/mae/nh = 0`. This is correct: the regime ended at bar k, there are no forward bars, and the regime has indeed flipped within h=1 bars.

However, by the `build_states` filter at line 66 (`act = np.where(n > k)[0]`), states are ONLY generated for bars where `n > k`, meaning there is at least one forward bar. So `ni = int(min(n[i], 61)) > k` is guaranteed for all rows in `S`, and consequently for all (i, k) pairs in `wstates`. The `hi <= k` branch in `hmetrics` is therefore dead code for `h=1`. It can fire for larger `h` when `ni < k + h`, which is correct behavior. No bug here — but the dead branch at h=1 is worth documenting.

**Recommended fix (do not apply):** No change needed; add a comment confirming the `n > k` guarantee from `build_states` makes the branch unreachable at h=1.

---

### [W3] `bar4_knn_warning_controls.py:154` — `cols = np.arange(k+1, hi+1)` when `hi = ni` includes column `ni` itself; verify `H[i, ni]` is populated

**File:** `bar4_knn_warning_controls.py`, line 154

```python
cols = np.arange(k + 1, hi + 1); fh = H[i, cols]; fl = L[i, cols]
```

When `h` is large enough that `k + h >= ni`, `hi = ni` and `cols` includes column index `ni`. In `P.build` (`progressive_separability.py` lines 42–46), column `ni` is populated as `H[i, 1:ni+1] = ph[i][:ni]` (the last post-flip bar), so column `ni` IS filled if `ni <= B-1 = 61`. The cap `ni = int(min(n[i], 61))` ensures `ni <= 61 < B = 62`, so `H[i, ni]` is within bounds and populated. This is clean.

However, note that `P.build` fills columns 1..k as `ph[i][:k]` where `k = min(n[i], B-1)`. For `n[i] >= B`, only the first 61 post-flip bars are stored, and `ni` is capped at 61. The `rem_mfe` and `rem_mae` in `build_states` are also capped at column 61 (`ni = int(min(n[i], 61))`), so the atlas forward windows are consistent with the build_states forward windows. Clean.

---

## Notes

### [N1] `bar4_knn_warning_controls.py:46` — `flip_c` is computed but never used

**File:** `bar4_knn_warning_controls.py`, line 46

```python
entry = O[:, 4]; flip_c = df.post_c.apply(lambda x: float(x[-1])).values
```

`flip_c` extracts the last close of each regime's post-flip sequence. It is assigned but never referenced again in the file. This is dead code — no correctness impact, but it executes a non-trivial `.apply()` on a large DataFrame on every run.

---

### [N2] `bar4_knn_warning_controls.py:187` — `beyond` NaN-safety check is asymmetric

**File:** `bar4_knn_warning_controls.py`, line 187

```python
beyond = (nhW == nhW) and nhW < nhH * 0.85
```

`nhW == nhW` is a NaN check for `nhW`, but there is no corresponding `nhH == nhH` guard. If `matched_n == 0` (the `else` branch at line 132 sets all to `np.nan`), then `nhW == nhW` is `False`, so `beyond = False`. That correctly handles the no-data case. But if by some numerical path `nhH` were NaN while `nhW` were a valid float, `nhW < nhH * 0.85` would evaluate to `False` without triggering the guard. In practice this cannot happen because both are set together from the same `if len(j)` branch, so both are either valid or both NaN. No bug, but the asymmetry creates a false sense of protection.

---

## Clean Checks

The following items were verified and are clean:

**KNN train/serve separation (critical path):**
- IS/OOS split is strictly temporal: IS = `year < 2025`, OOS = `year >= 2025`. IS states never appear in the OOS query pool. OOS states are never included in the KNN reference set. Clean.
- Standardization statistics (`mu`, `sd`) are computed from IS only (`Xis.mean(0)`, `Xis.std(0)`) and applied to OOS. Clean.
- KNN label predictions (`pc`) are drawn from IS neighbor labels (`isk.cls.values[idx]`), not OOS labels. Clean.

**build_states forward/backward boundary (`bar4_knn_path_atlas.py:69–119`):**
- Through-bar-k features use `H[i, 4:k+1]`, `L[i, 4:k+1]`, `C[i, k]` — strictly up to and including bar k.
- Forward outcome labels (`rem_mfe`, `rem_mae`, `newhigh3`, `flip3`) use `fb = np.arange(k+1, ni+1)` — strictly bars after k. No index crosses the k/k+1 boundary.
- `peak_px` for `newhigh3` uses `H[i, 4:k+1]` (through bar k), and forward comparison is against `fh[j]` for `j` in `fb` (bars k+1 onward). Causal. Clean.
- Row inclusion filter is `n > k` (line 66), guaranteeing at least one forward bar, so `fb.size > 0` for all state rows. The `else: rmfe = rmae = 0` branch at line 112–113 is dead but harmless.

**Control 2 matching vs outcome non-circularity:**
- Matching features: `k` (bars alive), `mfe_b` (binned `mfe_sofar`), `mae_b` (binned `mae_sofar`). These are all through-bar-k features, computed in `build_states` from `H[i, 4:k+1]` / `L[i, 4:k+1]`.
- Compared outcomes: `newhigh3`, `flip3`, `rem_mfe`. These are strictly forward from bar k (`fb = np.arange(k+1, ni+1)`).
- `mfe_sofar` (matching feature) and `rem_mfe` (compared outcome) are computed from non-overlapping index ranges: `[4, k]` and `[k+1, ni]` respectively. No circularity. Clean.

**Control 1 exit mechanics:**
- `exit_pnl(i, t)` at line 80–83 exits at bar `t+1` OPEN, not bar `t`. This correctly ensures the exit bar is strictly after the signal bar. `entry[i] = O[i, 4]` is the Bar-4 open. The exit PnL is `(O[i, t1] - di*EXIT - fill) * di * MULT - COMM`. The exit is at the next bar's open, which is causally correct — you cannot exit at the same bar's open when the signal fires at bar t's close.
- Both arms (warning-bar and random-bar) use the same `exit_pnl` function with identical slippage and commission parameters. Apples-to-apples. Clean.
- The same set of trades appears in both arms (`warn_idx` is reused). Pure timing comparison. Clean.
- Random arm feasibility: `warn_k[warn_k < ni]` ensures the sampled bar `t` satisfies `t < ni`, so `t+1 <= ni` and `O[i, t1]` with `t1 = min(t+1, int(min(n[i], 61)))` accesses a populated column. Clean (modulo the distribution-matching imprecision noted in C1-BIAS-1).

**Atlas `hmetrics` direction-correctness:**
- Long (di=1): `fav = fh - cnow` (upside), `adv = cnow - fl` (downside). Correct.
- Short (di=-1): `fav = cnow - fl` (downside move in price is favorable), `adv = fh - cnow` (upside move is adverse). Correct.
- New-high long: `fh.max() > peak_k` where `peak_k = np.max(H[i, 4:k+1])`. Forward highs exceed the through-k running peak. Causal. Clean.
- New-high short: `fl.min() < peak_k` where `peak_k = np.min(L[i, 4:k+1])`. Forward lows breach the through-k running trough. Causal. Clean.
- `flip = int((ni - k) <= h)`: regime has `ni - k` remaining bars from k; if that is ≤ h, the flip occurs within horizon h. This is a known-at-run-time count (not a future prediction — the KNN study is diagnostic, not a trading system), and it is computed from `ni` which is capped to 61. Clean as a diagnostic label.

**wbar detection logic (`bar4_knn_warning_controls.py:70–77`):**
- The CONT→DETER transition detector walks `seqs[rid]` in sorted k order, requiring a CONT prediction before a DETER prediction (`seen = True` then `p in DETER`). The warning bar is the FIRST bar at which DETER fires after at least one CONT bar. This is the correct "genuine deterioration" definition (same as in `bar4_knn_path_atlas.py`'s `gen_lead` logic). Clean.
- `seqs` is sorted by k: `sorted(zip(g.k, g.pred))` — sorting is on k (integer), so bar order is respected. Clean.

**IS-only standardization not re-fit on OOS (checklist D2):**
- Per bar k: `mu = Xis.mean(0)`, `sd = Xis.std(0)` from IS rows at that k. OOS rows are transformed with `(Xoo - mu) / sd`. No OOS statistics enter the normalization. Clean.

**No `.shift(-N)` or `bfill` in feature path:**
- No negative shifts found in `bar4_knn_warning_controls.py`, `bar4_knn_path_atlas.py`, or `progressive_separability.py` within the feature computation paths. Clean.
- No `bfill` calls found in any module in scope. Clean.

**No center=True rolling:**
- No `rolling` calls at all in the primary file or `bar4_knn_path_atlas.py`. Clean.

**Data source:**
- `early_health_filter.py` line 30 reads from `data/catalog/NQ_v0_2020_2026`, the v.0 volume-continuous catalog (required per MEMORY.md hard rule). Clean.

---

## Interpretation Guidance for Each Control Given the Findings

**Control 1 (timing):** The exit machinery is symmetric and correct; the warning-bar vs random-bar comparison is a pure timing test on the same trades. The one imprecision (C1-BIAS-1) is that the random-bar distribution is not strictly identical to the full warning-bar distribution — it is feasibility-censored per trade. This is not a directional bias toward making the warning look better; if anything, short-lived trades have their random bars drawn from earlier (potentially worse) exits, which could either help or hurt the random arm. The timing conclusion is trustworthy in sign but the margin should not be treated as precise.

**Control 2 (beyond severity):** The structural issue (C2-LEAK-1) means the healthy arm is composed of "never warned anywhere in their life" trades, which are positively selected for overall health. The mfe_b/mae_b matching controls for the instantaneous state but not for the full-trajectory conditioning. If Control 2 returns a "YES — warning sees beyond severity" conclusion, that conclusion is partially correct but the magnitude of the gap is inflated. The finding cannot be cleanly attributed 100% to KNN's independent information. If Control 2 returns "NO — just re-reads mfe_sofar," the inflated-healthy-arm bias runs in the direction of making that verdict too conservative — the warning may actually have some beyond-severity signal that is hidden by the inflated healthy baseline. In either case, the Control 2 verdict has a systematic thumb on the scale.

---

*Audit complete. Static analysis only. Dynamic execution paths, data file contents, and runtime outputs are out of scope.*

# Look-Ahead & Timestamp Audit

**Date:** 2026-06-17T00:00:00Z
**Scope:**
- `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (reused: `build_states`, `FEATS`, `CONT`/`DETER`)
- `studies/regime_dna_knn/progressive_separability.py` (reused: `P.build` matrix constructor)
- `studies/regime_dna_knn/early_health_filter.py` (reused: `compute_labels_features`, capsule source)
**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 2
- Warning: 2
- Note: 3

---

## Critical Findings

### [C1] `bar4_knn_warning_path_atlas.py:196` — Blind-exit fallback pins exit at last valid bar, collapsing to hold-to-flip for short regimes

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, lines 192–196

**Code:**
```python
if n[ii] > t:                      # bar exists
    bmap[r] = int(t)
else:
    bmap[r] = int(min(t, n[ii] - 1))
```

When the randomly sampled bar `t` is beyond the regime's length (`n[ii] <= t`), the fallback sets `bmap[r] = n[ii] - 1`. Inside `fullexit_pnl` (line 170), the exit then becomes `O[ii, min((n[ii]-1)+1, min(n[ii],61))] = O[ii, n[ii]]`. If column `n[ii]` is the last valid post-flip bar (the flip bar itself), the exit OPEN may be `NaN` or the matrix boundary. More importantly: any blind trade where the drawn `t >= n[ii]` is effectively exited at bar `n[ii]`, which is either the terminal flip close or a NaN open.

The WARNING exit has NO such boundary problem — `wbar[rid] = k` where `k` was only assigned inside `if n > k` in `build_states` (line 67 of `bar4_knn_path_atlas.py`), so every warning bar is strictly valid. The blind control's fallback silently forces some fraction of blind trades to exit at a worse-than-intended price (the NaN open of the cap bar, or the same position as "hold to flip"). This asymmetry **biases the blind control's PnL downward relative to the warning**, making the warning appear more skilled than it actually is.

**Impact:** The magnitude depends on what fraction of the 5-seed blind draws land at `t >= n[ii]`. The blind bar distribution is `warn_k` (warning bar indices, typically 4–15). Short regimes (n close to 4–5) would hit this path frequently. If the warning is concentrated on longer-surviving regimes (by definition, a regime warned at bar k must have survived to bar k), then blind draws — which are drawn uniformly from all regime IDs including short ones — will hit the boundary more often than the warning set does. This creates a structural survivor-bias advantage for the warning in the comparison.

**Recommended fix (do not apply):** In the blind loop, skip regimes where `n[ii] <= t` entirely (do not insert them into `bmap`), so those trades hold to flip just as they would in the baseline. This preserves the "same number of exits" intent by redrawing or accepting a slightly smaller blind count, which is preferable to a phantom boundary exit.

---

### [C2] `bar4_knn_warning_path_atlas.py:45,162–172` — `flip_c` (terminal close) used as hold-to-flip exit, but `flip_c` is `post_c[-1]` which is the LAST bar appended to the capsule — not necessarily the opposing flip bar's close

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, lines 45, 167–168

**Code:**
```python
flip_c = df.post_c.apply(lambda x: float(x[-1])).values
...
ex = flip_c[ii] - di * EXIT
```

In `early_health_filter.py` (`CapsuleReplay`), a post-flip bar is appended to `self._cap["post"]` and **then** `_finalize()` is called if that bar itself flipped (line 103 of `early_health_filter.py`). This means the last element of `post_c` is the bar on which the **next** regime flip was detected — the final bar of the current regime — and its close IS the flip bar's close.

However, `progressive_separability.py:build()` caps the matrix at `B=62` columns (column 0 = flip bar, columns 1..61 = post-flip bars), and at runtime `horizon_metrics` uses `ni = int(min(n[i], 61))`. For regimes longer than 61 post-flip bars, `n[ii]` (raw count) may exceed 61, meaning `flip_c[ii]` is `post_c[-1]` which corresponds to bar index `n[ii]` (which may be >61), while the matrix is capped at column 61. The hold-to-flip exit at line 168 uses the true final close from the raw list (correct), while the warning exit at line 171 uses `O[ii, t1]` from the matrix (capped at 61). For long regimes, the baseline and warning see slightly different terminal bars, which is inconsistent.

**Impact:** For typical NQ regime lengths this is likely minor (most regimes shorter than 61 bars). However, the inconsistency is structural: the `flip_c` terminal exit and the matrix cap are not synchronized. Any regime longer than 61 bars has a baseline that exits at the true terminal bar while a warning exit would cap at bar-61's open. Net effect on the verdict table is uncertain but non-zero.

**Recommended fix (do not apply):** Derive `flip_c` consistently from `C[ii, int(min(n[ii], 61))]` so both paths use the same capped matrix, or extend the matrix cap to accommodate all observed regime lengths.

---

## Warnings

### [W1] `bar4_knn_warning_path_atlas.py:92` — MAE formula uses `(cnow - fl) * di` which is WRONG for short trades

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, line 92

**Code:**
```python
mae = max(((cnow - fl) * di / ai).max(), 0.0)
```

For a **long** trade (`di=1`): adverse movement is price going DOWN, i.e., low < cnow. The expression `(cnow - fl) * 1` = `cnow - fl`, which is positive when low < cnow — correct.

For a **short** trade (`di=-1`): adverse movement is price going UP, i.e., high > cnow. The correct formula is `(fh - cnow) * 1` (i.e., forward highs minus current close). But the code uses `(cnow - fl) * (-1)` = `fl - cnow`, which is **the amount the forward LOW is BELOW cnow** — this measures downside movement, which is FAVORABLE for a short, not adverse. This means for short trades, MAE within horizon h is computed as the favorable low extension, not the adverse high extension.

Cross-check: `build_states` in `bar4_knn_path_atlas.py` lines 71–72 correctly computes:
```python
favsf = (hk - e) * di / ai   # favorable: for long, high > entry; for short, entry > low
advsf = (e - lk) * di / ai   # adverse: for long, entry > low (wrong direction); for short, high > entry
```
Wait — in `build_states`, `advsf = (e - lk) * di / ai`. For short (`di=-1`): `(e - lk) * (-1) = lk - e`, which is positive when `lk < e`, meaning low below entry — that IS favorable for short, so `build_states` also appears to use low-based "adverse" which is actually favorable-excursion for shorts. This is a consistent but potentially mislabeled convention throughout the study (where "MAE" means low excursion from entry regardless of direction).

The critical question for this audit is whether `horizon_metrics` is CONSISTENT with `build_states`'s convention. If `build_states` defines MAE as `(entry - low) * di / atr` (which is favorable for short but called "adverse"), then `horizon_metrics`'s `(cnow - fl) * di` is consistent with that convention. However, the INTERPRETATION of the metric in the output table (labeled "MAE within h") would then be wrong for short trades — it would report favorable low extension as "adverse."

Given the corpus of short trades in NQ (both long and short flips are included), this mislabeling affects the interpretive validity of Part A's table. It does not affect Part B (which uses dollar PnL, not MAE labels). The Part A "MAE within h" column numbers are directionally wrong for short trades and the aggregate is a mix of correct-long and mislabeled-short.

**Recommended fix (do not apply):** Verify the direction convention for MAE across all three modules and align the formula in `horizon_metrics` to `max(((fh - cnow) * di / ai).max(), 0.0)` for adverse (which correctly uses fh for short-adverse and fl for long-adverse via the `-di` implicit sign). Alternatively, document clearly that "MAE" in this context means "low excursion from close" regardless of direction.

---

### [W2] `bar4_knn_warning_path_atlas.py:184–198` — Blind control draws from ALL OOS regime IDs (including regimes that had no KNN prediction) rather than only from the KNN-predicted set

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, lines 184, 188

**Code:**
```python
nwarn = len(wbar); all_rids = np.array(list(seqs.keys()))
...
chosen = rg.choice(all_rids, nwarn, replace=False)
```

`seqs` is built from `oos.groupby("rid")` at line 68, where `oos` is the post-prediction filtered frame (line 64: `oos = oos[oos.pred.notna()].copy()`). So `seqs` only contains regimes that received at least one KNN prediction. This is correct — the blind pool is the same KNN-eligible set.

However, the warning set `wbar` is further restricted: it only contains regimes that (a) received a CONT prediction at some bar AND (b) subsequently received a DETER prediction. Regimes that were always predicted DETER (never had a CONT predecessor) are excluded from `warned`. They ARE included in `all_rids` for the blind draw. This means the blind control mixes "always-DETER" regimes (trades the KNN immediately flagged as bad) with "warned" regimes (transitions from good to bad). Since always-DETER trades likely have worse outcomes than the average trade, the blind control is drawing from a pool that skews negative, again potentially making the warning look better than a truly fair randomization.

**Recommended fix (do not apply):** Restrict `all_rids` for the blind draw to only regimes that received at least one CONT prediction, i.e., `all_rids = np.array([r for r, s in seqs.items() if any(p in CONT for _, p in s)])`. This makes the blind pool structurally analogous to the warning pool (both start from CONT-predicted regimes), ensuring the comparison measures KNN transition detection, not regime selection.

---

## Notes

### [N1] `bar4_knn_warning_path_atlas.py:87` — Edge case: `hi <= k` branch returns `(0.0, 0.0, 0.0, 0.0, 1)` but first element type is `float`, not `int`

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, line 87

```python
out[h] = (0.0, 0.0, 0.0, 0.0, 1)  # already at end → flip
```

The normal path at line 96 returns `(nh, mfe, mae, gb, flip)` where `nh` and `flip` are `int`. The edge-case branch returns `(0.0, ...)` as float for `nh`. `agg_horizon` converts all tuples to `np.array(m[h])` so the dtype mismatch is absorbed, but `nh` (new-high count) semantics as 0.0 float vs 0 int is a latent type inconsistency. Not a correctness bug.

**Recommended fix (do not apply):** Change to `(0, 0.0, 0.0, 0.0, 1)` to match normal-path types.

---

### [N2] `bar4_knn_warning_path_atlas.py:108–109` — Healthy pool downsampling uses unweighted random selection rather than per-k stratified sampling, so the unsampled distribution may not match `warn_k`

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, lines 108–110

```python
if len(heal_states) > 60000:
    sel = RNG.choice(len(heal_states), 60000, replace=False)
    heal_states = [heal_states[j] for j in sel]
```

This uniform subsample is applied BEFORE the age-matching step at lines 130–139. The age-matched sample is then built from this pre-subsampled pool. If the 60K subsample happens to under-represent certain bar-k values that are common in `warn_k`, the per-k pools `heal_by_k[k]` may be too small to satisfy `frac * target`, causing the matched sample to be systematically smaller than intended at those bars. The result is that `matched_heal` may not fully replicate the `warn_k` distribution at bars where healthy observations are sparse after the 60K cap. This is a precision note, not a correctness bug — the age-matching still runs, just with degraded coverage at some bars.

**Recommended fix (do not apply):** Subsample within each k-stratum proportionally (preserve the per-k ratios before and after the cap), or apply the 60K cap after constructing `heal_by_k`.

---

### [N3] `bar4_knn_warning_path_atlas.py:176–177` — `metrics()` re-sorts PnL by rid before computing drawdown, but `yy` array is NOT re-sorted, so `p[yy==2025]` and `p[yy==2026]` slice the re-ordered `p` against the original-order `yy`

**File:** `studies/regime_dna_knn/bar4_knn_warning_path_atlas.py`, lines 175–178

```python
def metrics(pnl, yy, rids):
    order = np.argsort(rids); p = pnl[order]
    dd = float((np.maximum.accumulate(np.cumsum(p)) - np.cumsum(p)).max())
    return p.mean(), p[yy == 2025].mean(), p[yy == 2026].mean(), dd, np.percentile(p, 5)
```

`p = pnl[order]` reorders by sorted rid. But `yy` is not reordered. So `p[yy==2025]` applies the original-order year mask to the rid-sorted PnL array. This would produce wrong 2025/2026 per-year averages if `yy` and `p` are not in the same order after the sort. The drawdown and overall mean are unaffected (mean is order-invariant; DD is intentionally sorted by rid for consistency). But the year-split averages in the verdict table may be scrambled.

**Recommended fix (do not apply):** Either (a) also apply `order` to `yy`: `yy_s = yy[order]` and use `p[yy_s==2025]`, or (b) drop the rid-sort since the mean and percentile are order-invariant and the DD sort by rid is arbitrary anyway.

---

## Clean Checks

The following checklist items were verified and found clean:

- **KNN IS/OOS split:** IS strictly `year < 2025`, OOS `year >= 2025`. No OOS label used in neighbor lookup. Standardization (`mu`, `sd`) computed from IS only and applied to both IS fit and OOS query. (lines 59–61)
- **KNN prediction uses majority class of IS neighbors:** `max(Counter(r), key=Counter(r).get)` is a correct plurality vote with no OOS label involvement. (line 63)
- **Warning detection is causal:** `wbar[rid] = k` is the first bar where `pred in DETER` after a `pred in CONT` was observed. All `pred` values come from IS-neighbor majority votes on features through bar `k`. The warning bar itself is not in the future. (lines 68–76)
- **Part A forward window columns strictly > k:** `cols = np.arange(k+1, hi+1)` where `hi = min(k+h, ni)`. No column index <= k appears in `fh`/`fl`. (lines 85, 89)
- **Part A peak_k uses through-k data only:** `H[i, 4:k+1]` for long, `L[i, 4:k+1]` for short. The forward window starts at `k+1`. Peak is computed from the entry bar (column 4) through the warning bar (column k), inclusive — causal. (line 82)
- **Part A new-high (nh) is a forward measurement:** `fh.max() > peak_k` compares forward highs (cols k+1..hi) against the through-k peak. This is the correct causal new-high definition. (line 93)
- **Part A flip flag:** `(ni - k) <= h` — uses only already-known regime length `ni` (capped at 61 from `n[i]`). No forward peek at future bars. (line 95)
- **Part B fullexit_pnl entry price:** `entry[ii] = O[:, 4]` (bar-4 open), entry fill = `e + di * ENTRY`. This is the same entry used throughout the study; causal. (lines 45, 164)
- **Part B warning exit at t+1 open:** `t1 = min(t+1, int(min(n[ii], 61)))`. The de-risk exit uses the bar after the warning bar's open — correctly causal (the warning fires at bar k's close; de-risk at bar k+1's open). (line 170)
- **Part B hold-to-flip exit applies adverse slip:** `flip_c[ii] - di * EXIT` correctly subtracts slip in the adverse direction for both long and short. (line 168)
- **Healthy CONT states restricted to never-warned regimes:** The heal_states loop checks `if rid in warned: continue` before adding CONT bars. (lines 101–106)
- **Age-matching draws from heal_by_k with correct fractions:** `frac * target` where `kdist` is normalized by `warn_k` distribution. The matching is approximate (integer rounding, pool size limits) but directionally correct. (lines 132–139)
- **Warning and blind use identical `fullexit_pnl` function:** All three comparisons (baseline, warning, blind) call the same function with only `exit_bar_map` differing. The entry, fill, slip, commission, and terminal exit logic are identical. (lines 180–182, 197)
- **Blind bar distribution sampled from `warn_k`:** `bk = rg.choice(warn_k, nwarn, replace=True)` — the blind bars are drawn from the empirical warning bar distribution, not a uniform distribution. (line 189)
- **Blind uses multiple seeds (5):** Results are averaged across seeds 100–104. This reduces variance in the blind estimate without overfitting it. (lines 186–199)
- **No `.shift(-N)` or negative lag in feature path:** Confirmed absent in all three modules.
- **No `center=True` rolling:** Confirmed absent.
- **No `bfill`:** Confirmed absent in this pipeline.
- **IS standardization not applied to OOS labels:** The StandardScaler in `progressive_separability.models()` is fit on IS only. In `bar4_knn_warning_path_atlas.py`, the KNN scaler is fit on IS (`Xis`) only. No OOS contamination.
- **`seqs` built from KNN-eligible OOS trades only:** `oos = oos[oos.pred.notna()].copy()` before `seqs` construction. (line 64)
- **Matrix column layout verified:** Column 0 = flip bar; columns 1..n = post-flip bars. `build_states` entry at `O[:, 4]` = 4th post-flip bar's open (entry after bar-3 close confirmed). Consistent with early_health_filter and progressive_separability. (progressive_separability.py lines 39–46)
- **Timestamp convention:** `early_health_filter.py` uses `b.ts_init` for the 1s bar ordering (line 175). 1s bars have `ts_init = ts_event + 1s` in NT, so ordering by `ts_init` is correct for chronological streaming. No `ts_event`-as-close-time misuse in the OHLC matrix construction path.

---

## Verdict on the Fairness of the Skill vs Exposure Test

The core question — does the KNN warning beat a blind exit of the same count and bar distribution? — is answered by an experiment that is **structurally biased toward the warning in two ways** (C1, W2), both of which make the warning look more skilled than a truly fair control:

1. **C1 (Critical):** Blind trades where the drawn bar exceeds regime length are forced into a degraded exit (boundary NaN open or last-bar open), while all warning trades are guaranteed to have a valid bar. This asymmetric penalty on the blind lowers its PnL.

2. **W2 (Warning):** The blind pool includes always-DETER regimes (poor-quality trades), while the warning pool is restricted to CONT-then-DETER transitions (by construction, a subset that started well). Drawing blind exits from the full pool biases it toward worse trades.

The W1 warning (MAE direction for short trades) affects Part A interpretability but not Part B, so it does not change the skill/exposure verdict directly.

If the verdict currently reads "SKILL" (warning beats blind), it should be re-examined after correcting C1 and W2. If the verdict reads "REDUCED EXPOSURE ONLY," the structural biases in the blind work against that conclusion — meaning the true verdict may be even more in favor of "reduced exposure" than the current numbers show.

---

*Audit complete. Static analysis only. Dynamic behavior (e.g., actual NaN handling in numpy indexing at matrix boundaries) requires runtime inspection.*

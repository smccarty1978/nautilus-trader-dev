# Look-Ahead & Timestamp Audit

**Date:** 2026-06-17
**Scope:**
- `studies/regime_dna_knn/bar4_knn_opportunity_decay_atlas.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS, BARS — imported as A)
- `studies/regime_dna_knn/progressive_separability.py` (build — imported as P)
- `studies/regime_dna_knn/early_health_filter.py` (compute_labels_features — imported as E)
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

### [B3/D1] `bar4_knn_path_atlas.py:94-95` — `rem_mae` formula uses `fl` (lows) for both long and short trades

**Location:** `build_states()`, lines 94-95:

```python
rmfe = max(((fh - cnow) * di / ai).max(), 0.0)
rmae = max(((cnow - fl) * di / ai).max(), 0.0)
```

For a **long** (`di=1`): `(cnow - fl) * 1` = how far future lows fall below current close. Correct — adverse for a long is downside price movement measured via lows.

For a **short** (`di=-1`): `(cnow - fl) * (-1)` = `(fl - cnow) / ai`. If `fl < cnow` (lows drop below current price), the result is negative, clipped to zero. If `fl > cnow` (low moves above current — unlikely / noise), it would be positive. This does NOT measure adverse movement for a short. For a short, adverse means highs (`fh`) moving above current close, i.e., `(fh - cnow) * (-1)` would be negative (adverse), which would also be wrong. The correct formula for short `rem_mae` should use `fh`: `max(((fh - cnow) * di / ai).max(), 0.0)` — the same operand as `rmfe` but note the overall `advE` at lines 56-57 correctly does `H[:, 4:] - entry` for shorts.

**Impact:** The `rem_mae` column in the states DataFrame (`S`) is directionally incorrect for short trades. In the opportunity-decay atlas, `rem_mae` is used in: Study 1 (reported as "rem MAE"), Study 2 (reported as "rem MAE"), and the Deliverable ("rem MAE (risk)"). The KNN itself queries neighbors based on `FEATS` only (not `rem_mae`), so **KNN neighbor selection is not affected**. However, the `rem_mae` outcome reported in the Study 1/2/Deliverable tables is mislabeled for short-direction trades — the "rem MAE" column measures lows-below-close, which for shorts approximates the favorable direction, not the adverse one.

**Severity assessment:** This is inherited from `bar4_knn_path_atlas.py` (pre-existing, not introduced by the new script). The atlas is primarily a descriptive/calibration study — no trading logic reads `rem_mae` to make entry/exit decisions. However, the `rem_mae` column is presented as a "risk" dimension in the deliverable and is queried as a KNN output (`eMAE`). Any conclusion drawn about "risk" from `rem_mae` for a dataset containing both longs and shorts is potentially misleading. Flag for correction in `build_states()`.

**Recommended fix (do not apply):** Change line 95 to:
```python
rmae = max(((fh - cnow) * (-di) / ai).max(), 0.0)
```
which is `max((fh - cnow) / ai, 0.0)` for shorts and `max((cnow - fl) / ai, 0.0)` for longs — mirroring the correct `advE` formula at line 57.

---

### [E3/E4] `bar4_knn_opportunity_decay_atlas.py:184` — `dd20_scale` commission undercharges by $2.50 per scaled trade

**Location:** `policy()`, line 184:

```python
pnl[j] = 0.5 * leg1 + 0.5 * leg2 - COMM * 1.5
```

The scale-out policy executes 3 fills: 1 entry (full lot) + 1 partial exit (0.5 lot at the dd>20% trigger bar+1 open) + 1 final exit (0.5 lot at flip close). If `COMM = $5.00` represents a round-turn for 1 lot (entry + exit), the correct commission structure is:

- Entry ($5.00 RT, covering the initial fill and its paired half-exit)
- Partial exit of 0.5 lot: $2.50 (half the RT commission)
- Final exit of 0.5 lot: $2.50 (half the RT commission)
- Total: $10.00 = `2.0 * COMM`

The code charges `1.5 * COMM = $7.50`, under-billing by $2.50 per trade versus the hold policy (charged `1.0 * COMM = $5.00` for 2 fills). This means the Study 3 comparison **slightly flatters the `dd20_scale` policy relative to hold-to-flip** by $2.50/trade.

This is a Study 3 diagnostic only (explicitly disclaimed as "1m scale-out, BE-stop rules need 1s, deferred") so the impact on decisions is bounded. But the reported avg/trade comparison is skewed by this amount.

**Recommended fix (do not apply):** Change `COMM * 1.5` to `COMM * 2.0` (3 fills at half-lot cost for exits, or equivalently 2 full RT equivalents).

---

## Notes

### [Note 1] `bar4_knn_opportunity_decay_atlas.py:157` — `exit_open` at terminal bar uses OPEN, not CLOSE

**Location:** `exit_open()`, line 157:

```python
t1 = min(t + 1, int(min(n[i], 61)))
return (O[i, t1] - di * EXIT - fill) * di * MULT, fill, di
```

When the exit bar `t+1` equals or exceeds the terminal bar index `n[i]`, `t1` is clamped to `n[i]` and the function returns the **open** of the terminal bar. The `hold_pnl` function uses `flip_c[i]` (the close of the terminal bar). For the "deter" policy (and the 50%-leg of "dd20_scale"), any trade where the DETER warning fires at or near the terminal bar will exit at `O[i, n[i]]` rather than `C[i, n[i]]`. This is a minor inconsistency rather than a look-ahead bug — the OPEN is still a valid causal price — but the reported avg/trade for "exit on DETER" will diverge slightly from a hold-to-flip-close comparison on those trades. Affects a small fraction of trades where the KNN DETER label fires very late.

---

### [Note 2] `bar4_knn_opportunity_decay_atlas.py:138-139` — Study 4 "first_sl" uses `slope3` which is NaN at early bars, handled only by NaN-identity check

**Location:** Study 4 loop, line 139:

```python
first_sl = next((k for k, v in zip(ks, s3) if (v == v and v < 0) and k <= wb), None)
```

`slope3 = pRun - g.pRun.shift(3)` is NaN for the first 3 bars within a trade (bars k=4, k=5, k=6 will have NaN slope3 because there are fewer than 3 predecessors in the group). The NaN guard `v == v` correctly skips NaN values. This is handled cleanly. No bug — documenting for clarity that the first-NaN behavior is intentional and correct.

---

### [Note 3] `bar4_knn_opportunity_decay_atlas.py:42` — `A.BARS` module-level mutation

**Location:** Line 42:

```python
A.BARS = list(range(4, 29))
```

This mutates the module-level `BARS` list in `bar4_knn_path_atlas` at runtime. The original value is `list(range(4, 16))`. This is a side effect on an imported module — if any other module subsequently imports or re-uses `A.BARS` in the same process, it will see the extended range (4..28). This is not a causality or look-ahead issue, but it is a fragile pattern. If `build_states` is called elsewhere in a multi-module session with the mutated range, states beyond bar 15 will be included where the original script intended only bars 4-15. No current correctness bug given single-script execution, but defensive note.

---

## Checklist Results — Items Confirmed Clean

**KNN train/test separation (Check 1):**
`is_all = S[S.year < 2025]` / `oos = S[S.year >= 2025]`. Confirmed. The `nbc` (neighbor class labels), `eMFE`, `eMAE`, `eTTF`, `pRun`, `pFail`, and `pred` values at lines 66-70 are all derived exclusively from `isk` (IS neighbors). No OOS label or outcome leaks into the KNN output.

Standardization uses `mu = Xis.mean(0); sd = Xis.std(0)` computed on IS only (line 63), applied to both IS and OOS query. Confirmed clean.

IS reference cap sampling uses `RNG = np.random.default_rng(0)` with fixed seed — deterministic and reproducible. Confirmed.

**Per-trade peak/drawdown causality (Check 2):**
`oos.sort_values(["rid", "k"])` at line 73 ensures each trade's bars are ordered by bar index before grouped operations.

`g.pRun.cummax()` at line 77: pandas `groupby.transform` with `cummax()` computes a running maximum within each group in the order the rows appear. Since rows are sorted by `(rid, k)` before the groupby, this is equivalent to `max(pRun[4..current_k])` — strictly backward-looking. Confirmed causal.

`g.pRun.shift(1)` and `g.pRun.shift(3)` at lines 79-80: pandas `groupby.shift(n)` shifts within group, producing NaN for the first `n` rows of each group. Shift uses past bars only (positive shift = look back). Confirmed causal. NaN at early bars is handled by `oos.dropna(subset=["slope3"])` in Study 2 (line 120) and by the NaN guard `v == v` in Study 4 (line 139).

**Forward outcomes as outcomes, not features (Check 3):**
`rem_mfe`, `rem_mae`, `rem_bars`, `newhigh3`, `b1010` are all sourced from `build_states` columns (computed from `fb = np.arange(k+1, ni+1)`, i.e., strictly bars after `k`). These columns are used only as **outcome dimensions** in Study 1/2/Deliverable bucketing tables — they are never part of `A.FEATS` (which are: `bar_idx, mfe_sofar, mae_sofar, pnl_now, pullback, progress_count, consec_noncont, dist_flip_open, health_ratio, close_loc, range_exp, vol_exp`). Confirmed: no forward outcome leaks into the KNN feature vector.

**`b1010` provenance (Check 7):**
`b1010` in `build_states` (line 117-119 of `bar4_knn_path_atlas.py`) is stored as `barr[(1.0, 1.0)]`, which is the barrier-race result computed over `fb = np.arange(k+1, ni+1)` — a 1 ATR PT vs 1 ATR SL race using only future bars. It is used in the Deliverable as the "direction" dimension at line 207. This is correct: it is a realized forward barrier outcome, not a feature, used only as a classification/outcome label in the descriptive table.

**Study 1 bucketing causality (Check 4):**
`dd` (score drawdown from peak) is computed causally via `cummax()`. `rem_mfe`, `rem_mae`, `newhigh3`, etc. are realized forward outcomes from `build_states`. The bucketing variable (`dd`) and the reported metrics (`rem_mfe`, etc.) are distinct quantities — no circularity. Confirmed.

**Study 2 bucketing causality (Check 4):**
`slope3 = pRun - g.pRun.shift(3)` is causal. Outcome columns (`rem_mfe`, `rem_mae`, `newhigh3`, `fl3`, `fl5`) are realized forward. Confirmed no circularity.

**Study 4 causality (Check 5):**
`dd` at bar `k` uses info through bar `k` (causal cummax). `slope3` at bar `k` uses bar `k` and 3 bars prior (causal). The warning bar `wb` is `wbar[rid]` — first bar where KNN pred transitions from CONT to DETER, computed from causal `pred` values. "Fired before" counts `first_dd < wb` strictly — comparing two causally-detected bar indices. Confirmed descriptively sound.

**Study 3 exit timing causality (Check 6):**
`exit_open(i, t)` exits at `O[i, t+1]` — the OPEN of bar `t+1`. Signal known at close of bar `t`, action taken at next bar's open. Confirmed causal (no intrabar trigger). `flip_c[i]` is `post_c[-1]` — the close of the terminal/flip bar, the true terminal value. Confirmed. Commission for `dd20_scale` is charged at `1.5 * COMM` (see Warning 2 above for undercharge note, not a look-ahead issue).

**`newhigh3` construction:**
`nh3` is set using `fb` (strictly future bars k+1..k+3), checking whether any future high (long) or low (short) exceeds the peak through bar `k`. Strictly forward — correctly a forward outcome. Confirmed.

**`flip_c` terminal price:**
`flip_c = df.post_c.apply(lambda x: float(x[-1])).values` at line 47. `post_c` is the list of post-flip close prices, and `[-1]` is the last element — the close of the bar that triggered the opposite flip. This is the true terminal close for the trade. Confirmed as valid terminal exit price.

**BARS extension:**
`A.BARS = list(range(4, 29))` extends the bar range to 29 bars post-entry. `build_states` uses `act = np.where(n > k)[0]` gating — only processes row `i` at bar `k` if the trade lasted beyond bar `k`. No out-of-bounds access for short trades. Confirmed.

**OOS-only policy evaluation:**
`rids = list(oos.rid.unique())` at line 168 — Study 3 evaluates only OOS trades. IS data is used only as KNN reference set. Confirmed no IS contamination of the money comparison.

---

## Overall Assessment

The new script is **causally clean** for all look-ahead purposes. The KNN is properly IS→OOS separated with IS-only standardization. Per-trade peak, drawdown, and slope are all backward-looking within properly ordered per-group pandas operations. Forward outcome columns (`rem_mfe`, `rem_mae`, `rem_bars`, `newhigh3`, `b1010`) are strictly realized forward quantities from `build_states` and are used only as outcome dimensions in descriptive bucketing, never as KNN features.

The two warnings are: (1) an inherited `rem_mae` direction bug for short trades that makes the "risk" interpretation of `rem_mae` unreliable for mixed long/short datasets; (2) a $2.50 commission undercharge on the `dd20_scale` policy that mildly flatters its Study 3 comparison. Neither constitutes look-ahead bias or train/serve skew. The study is safe to read as described.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g., race conditions in live trading) are out of scope.*

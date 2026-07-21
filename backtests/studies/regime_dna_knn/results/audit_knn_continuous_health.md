# Look-Ahead & Timestamp Audit — knn_continuous_health.py

**Date:** 2026-06-17T00:00:00Z
**Auditor:** lookahead-auditor v1
**Scope hash:** knn_continuous_health.py + bar4_knn_path_atlas.py + early_health_filter.py + progressive_separability.py + build_survivor_1s_paths.py

---

## Summary

- **Critical: 1**
- **Warning: 2**
- **Note: 3**

---

## CRITICAL FINDINGS

### [CRITICAL / Study 4 / E4-analogue] `knn_continuous_health.py:269` — 1s stop replay starts at bar-t OPEN, not bar-(t+1) OPEN — one-bar look-ahead on every protection policy

**This is the key check you requested. It is a genuine look-ahead.**

**The bug.** `stop_pnl` at line 264 is called with trigger bar `t`, which is the 1m bar index at which the drawdown + profit condition is first satisfied. The condition is evaluated using `dd` (health drawdown) and `op` (open_pnl / pnl_now), both of which are state values computed THROUGH the CLOSE of bar t — specifically `pnl_now = (C[i, k] - e) * di / ai` (bar4_knn_path_atlas.py line 72), which uses the bar-t close price.

At line 269 the 1s walk offset is:

```python
toff = t * 60 * NS - 60 * NS          # bar t open offset from flip close
```

This resolves to `(t - 1) * 60s` from the flip-bar close, which is exactly the OPEN of bar t. The 1s selection filter at line 271 then includes all 1s bars with `ts >= toff`, meaning the entire duration of bar t itself — from its open through its close — is included in the stop walk.

But the trigger is only known after bar t CLOSES. During the open-through-close period of bar t, the strategy cannot yet know that the drawdown/profit condition has been met. Including the body of bar t in the stop walk means: if price touches the protective stop DURING bar t (before bar t closes), the stop fires — but that price action was the information that caused the trigger condition in the first place. This is a one-bar look-ahead that inflates the protective value of every policy.

**The correct `toff` is:**

```python
toff = t * 60 * NS          # bar (t+1) open offset = bar t close offset
```

i.e., start the 1s walk from bar t's CLOSE (= bar t+1's OPEN). With this fix, the stop is set at bar-t close time and begins walking from that moment forward, which is the earliest a causal system could act.

**Magnitude.** For a protective stop that is close to the current price at trigger time, a non-trivial fraction of stop firings happen WITHIN bar t itself (the bar whose close revealed the trigger). These would all be phantom fills under the look-ahead. The closer the stop to the current price and the more volatile bar t, the larger the inflation. This is the exact same mechanism identified in the memory entry `be_simulation_path_checkpoint_inflation` and `level_momentum_be_arming_timing_artifact`. Expect the protection policies to look materially better than they are.

**Fix (do not apply):** Change line 269 from:
```python
toff = t * 60 * NS - 60 * NS
```
to:
```python
toff = t * 60 * NS
```

This starts the 1s walk at the open of bar t+1 (= close of bar t), which is the first moment the protective stop order could physically be submitted.

---

## WARNINGS

### [WARNING / Check 1] `knn_continuous_health.py:65-66` — IS KNN uses non-deterministic random subsampling; IS percentile reference can vary across runs

At line 65-66, when the IS set for a given bar exceeds `IS_REF_CAP=40000`, a random sample is drawn using `RNG.choice`. The global `RNG = np.random.default_rng(0)` is seeded, so this is deterministic on a single run. However, the IS KNN pass (lines 94-109) draws another set of random samples using the same `RNG` object, and because the two loops share state, the IS self-scoring reference distribution will depend on which bars are processed first and how many samples each bar draws in the main OOS pass. If `BARS` range changes (line 45 sets it to `range(4, 29)` vs the default `range(4, 16)` in bar4_knn_path_atlas.py), the RNG state entering the IS scoring pass differs, producing slightly different IS percentile reference distributions.

This is a reproducibility concern, not look-ahead: the IS reference is always IS-only. But the composite score percentiles are not stable across runs with different `BARS` settings, which could cause a borderline verdict in Study 4 or 5 to flip. The fix is to reseed RNG before the IS scoring pass, or use a dedicated RNG for each use.

**Severity rationale:** Warning, not Critical. The IS distribution changes are small (random subsampling of a large IS set), and the leakage direction is not clear. But the non-determinism is real and should be documented.

### [WARNING / Check 5 / Study 5 Control B] `knn_continuous_health.py:332-339` — Control B matched comparison pools within OOS only; no IS anchor for the matching bins

Study 5 Control B (lines 332-339) matches triggered vs non-triggered states on `(k, mfe_b, mae_b)` bins and compares `newhigh3` and `fl3`. The matching is done purely within the OOS dataset (2025-2026). There is no IS-derived bin definition: the bins are `pd.qcut`-equivalent rounding applied to OOS-computed `mfe_sofar` and `mae_sofar`. This means the bin boundaries shift with the OOS data distribution, which is fine for a comparison-within-OOS design, but it means "same mfe/mae/age" is defined on the OOS distribution, not the IS one.

More importantly, the forward outcomes `newhigh3` and `fl3` used in the comparison (lines 334-335) come from `build_states` and are the realized IS forward labels for IS rows, but for OOS rows they are the OOS-realized outcomes — which is correct. No look-ahead here. The concern is that the matched comparison is not testing "does the KNN health signal add information beyond what MFE/MAE/age already encode," because the triggered flag itself is a function of the KNN-derived composite indicator, which has already been fit on IS data. If the IS KNN is miscalibrated, the trigger assignments could systematically partition the OOS population in a way that mimics the forward outcome split for reasons unrelated to genuine health information. This is a design subtlety, not a hard bug. Flag as Warning.

---

## NOTES

### [NOTE / Check 2(a)] `knn_continuous_health.py:104` — Self-exclusion in IS KNN: confirmed clean

At line 104, `idx = idx[:, 1:]` correctly drops column 0 (the self-match) from the IS self-KNN, preventing each IS state from contributing its own labels to its own indicator score. The IS reference distribution for the composite percentile-rank is therefore genuinely IS-only, with no self-contamination.

### [NOTE / Check 3] `knn_continuous_health.py:116-120` — Per-trade derivatives use within-group cummax and shift: confirmed causal

The derivative computation at lines 116-120:
```python
g = oos.groupby("rid")
oos[f"{ind}_pk"] = g[ind].cummax()
oos[f"{ind}_dd"] = 1 - oos[ind] / oos[f"{ind}_pk"].clip(lower=1e-6)
oos[f"{ind}_sl3"] = oos[ind] - g[ind].shift(3)
```

`cummax()` within group is backward-looking (peak so far at bar k uses only bars 4..k). `shift(3)` within group shifts forward (value at bar k-3, using earlier data). Because the dataframe is sorted by `(rid, k)` at line 79 before groupby, both operations are correctly causal. No look-ahead.

### [NOTE / Check 4] `knn_continuous_health.py:124` — `open_pnl` assignment is causal

`pnl_now` in `build_states` (bar4_knn_path_atlas.py line 72) is `(C[i,k] - e) * di / ai`, using only the close price of bar k and the fill price from bar 4 open. This is causal through bar k close. The assignment at line 124 is therefore causal. No look-ahead.

---

## CLEAN CHECKS

The following items from the audit checklist were examined and found clean:

**Check 1 — KNN IS/OOS split:** Lines 53 and 62 correctly partition `isS = S[S.year < 2025]` and `oos = S[S.year >= 2025]`. The KNN at lines 67-76 trains `NearestNeighbors` on `Xis` (IS only), standardizes with IS mean/std (line 68), and queries OOS. Forward columns `pRun`, `pFail`, `pNH3`, `pFL3`, `eMFE`, `eMAE`, `eBARS` are all aggregated from IS neighbors' realized labels, never from OOS labels. `pred` is a majority-vote over IS neighbor classes. Clean.

**Check 2(b) — IS percentile reference is IS-only:** The IS self-scoring pass (lines 94-109) touches only `isS` rows. The resulting `is_sorted` dictionaries (line 110) contain no OOS data. The `pct_rank` calls at lines 111-113 apply those IS-derived sorted arrays to OOS indicator values via `np.searchsorted`, which is a lookup, not a fit. No OOS contamination of the thresholds. Clean.

**Check 2(c) — `pct_rank` implementation:** Line 41: `np.searchsorted(is_sorted, x, side="right") / max(len(is_sorted), 1)`. `is_sorted` is IS-only. `x` is OOS values. No OOS data enters the denominator or the sorted array. Clean.

**Check 3 — Derivatives are causal:** As noted above, `cummax` and `shift(3)` within sorted `(rid, k)` groups are backward-looking. Clean.

**Check 4 — `open_pnl` is causal:** `pnl_now` uses only bar-k close and the bar-4 fill. Clean.

**Check 5 — Forward outcomes are not circular:** `newhigh3`, `fl3`, `fl5`, `rem_mfe`, `rem_mae`, `b1010` in the OOS state rows are realized forward outcomes from `build_states` (bar4_knn_path_atlas.py lines 91-123). They are computed from bars k+1..n (strictly future of bar k). The health indicators (`hA`, `hB`, `hC`, `composite`) are KNN aggregations of IS neighbors' forward outcomes — which are IS-forward quantities, not the OOS row's own future. Using IS-neighbor forward outcomes to construct an indicator and then measuring OOS-row forward outcomes against it is not circular. Clean.

**Check 6(b) — Protective stop validity:** For longs, `e` (entry) = `O[:, 4]` (bar-4 open), and the stops are `e` (BE), `e + 0.5*ai` (lock 0.5), `e + 1.0*ai` (lock 1.0). For a long trade to reach the trigger condition it must have `open_pnl >= 0.5 ATR`, meaning the price is already above entry by at least 0.5 ATR. The BE stop `e` is therefore below the current price; lock stops are between entry and current price. These are all genuine protective levels that can only fire on an adverse retracement, not on the initial favorable move. Clean in principle, but the one-bar look-ahead (Critical finding above) means the walk includes bar t which has already moved favorably to create the trigger condition. 

**Check 6(c) — `flip_c` is the true terminal close:** `flip_c = df.post_c.apply(lambda x: float(x[-1])).values` (line 50). `post_c` is the list of post-flip 1m bar closes, so `x[-1]` is the final bar before the opposite flip. This is the correct terminal exit price. Clean.

**Check 6(d) — Slip is adverse on both stop and flip:** Stop fill: `(stop - di * EXIT - fill) * di * MULT` where EXIT=1.0 tick. For long (di=1), stop fill is `stop - 1t`, reducing proceeds. For flip: `(flip_c[i] - di * EXIT - fill) * di * MULT`. Again EXIT tick deducted. Both correct. Clean.

**Check 6(e) — Adverse-first within a 1s bar:** 1s bars are checked sequentially (lines 273-275); within each 1s bar only a single stop-side check is made (`ll[j] <= stop` for long). No simultaneous high/low ambiguity within a bar. Clean for 1s resolution.

**Check 7 — Study 5 Control B matching on causal features:** `mfe_b` and `mae_b` bucket `mfe_sofar` and `mae_sofar`, which are computed from bars 4..k (strictly causal through bar k). The `trig` flag (line 333) is derived from the composite drawdown which is also causal through bar k. Forward outcomes `newhigh3` and `fl3` in the grouped comparison are the OOS-row realized futures. The matching is causal; the comparison is forward. Clean.

**A1/A2 (timestamp convention):** This study uses the `early_health_capsule.parquet` built by `CapsuleReplay`, which drives 1s bars through `TimeframeAggregator`. The 1m bar aggregation uses NT's `ts_init` from 1s bars (line 175 of early_health_filter.py). Regime start is assigned `completed.close_ts` (line 115 of early_health_filter.py), which is the close time of the flip bar. The 1s path uses `ts_init` offsets from that close. This is consistent with NT conventions — no raw `ts_event` misuse found.

**B1 (no `center=True`):** No rolling computations use `center=True`. Clean.

**B5 (no bfill):** No `bfill` in the feature path. Clean.

**C3 (temporal split):** IS is year < 2025, OOS is year >= 2025. Hard temporal boundary. No random split. Clean.

---

## Recommended Action Before Trusting Study 4 Results

Fix line 269 (`toff = t * 60 * NS` instead of `t * 60 * NS - 60 * NS`) and re-run. The one-bar look-ahead is guaranteed to inflate the apparent benefit of all four protection policies (P1–P4). If Study 4 is the basis for any deployment decision, the current result is not trustworthy.

---

*Audit complete. Static analysis only. Dynamic bugs (race conditions, live data latency) are out of scope.*
*Files inspected: knn_continuous_health.py, bar4_knn_path_atlas.py (lines 49-127, 130-158), early_health_filter.py (lines 55-160, 203-320), progressive_separability.py (lines 35-110), build_survivor_1s_paths.py (full).*

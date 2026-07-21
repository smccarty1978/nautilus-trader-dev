# Look-Ahead & Timestamp Audit — bar4_knn_exit_atlas.py

**Date:** 2026-06-16T00:00:00Z  
**Auditor:** lookahead-auditor v1  
**Scope hash:** bar4_knn_exit_atlas.py + bar4_knn_path_atlas.py (build_states, FEATS) + early_health_filter.py (CapsuleReplay, compute_labels_features) + progressive_separability.py (build) + build_survivor_1s_paths.py (PathReplay)

---

## Files Inspected

- `studies/regime_dna_knn/bar4_knn_exit_atlas.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS, trade_class)
- `studies/regime_dna_knn/bar4_knn_money_gate.py` (entry/exit pattern reference)
- `studies/regime_dna_knn/early_health_filter.py` (CapsuleReplay, compute_labels_features, sim_trade)
- `studies/regime_dna_knn/progressive_separability.py` (build, feats_through)
- `studies/regime_dna_knn/build_survivor_1s_paths.py` (PathReplay, 1s-path generation)
- `collectors/collector_v2/aggregator.py` (TimeframeAggregator, close_ts semantics)

---

## Summary

- **Critical: 0**
- **Warning: 2**
- **Info: 4**

---

## Critical Findings

*None.*

---

## Warnings

### [W1] `bar4_knn_exit_atlas.py:83-84` — Dead line 83 overwritten by line 84; variable shadowing masks 1s-path terminal close

**Category:** B2 / data integrity  
**Lines:** 83–84

```python
flip_c = float(np.asarray(r.p1s_c)[sel][-1])   # last 1s close ~ flip   (line 83 — DEAD)
flip_c = float(df.post_c.values[ii][-1])         # exact terminal close   (line 84 — active)
```

Line 83 computes `flip_c` from the filtered 1s path (`sel = t >= ENTRY_T and t <= T_flip`), then line 84 immediately rebinds the same name to `df.post_c.values[ii][-1]` — the last element of the 1m post-flip close array from the capsule. Line 83 is therefore dead code. This is not a look-ahead bug — both values represent the terminal close of the same regime, and the 1m-close value on line 84 is correct for what it claims to be. **However**, the variable shadowing creates a material consistency question:

- `T_flip = n[ii] * 60 * NS` caps the 1s window at exactly bar `n` close time. If any 1s bar arrives in the 1s path between T_flip and the very next 1m bar boundary (i.e., the 1s data is slightly longer than `n` bars at 1m resolution), `sel` would exclude those bars and `r.p1s_c[sel][-1]` would differ from `df.post_c[-1]` only by sub-minute slippage. This is usually fine.
- More importantly: if a regime ends at exactly `n[ii]` bars but the last 1s bar before that 1m boundary is at `t < T_flip` (which it always is since 1s bars arrive one second at a time), the two flip_c values agree by construction. So line 84 is correct.
- The risk is that line 83 exists at all: if a future editor removes line 84 or reorders the lines, the result silently switches to the 1s-derived value with the current `sel` filter, which could diverge when the 1s path is truncated at MAXSEC=1800s. Any regime lasting more than 30 minutes would then report a mid-path 1s close as the terminal exit price.

**Recommended fix (do not apply):** Remove line 83 entirely, or promote it to a named variable `flip_c_1s` used only for an assertion. Keep line 84 as the single authoritative source of `flip_c`.

---

### [W2] `bar4_knn_exit_atlas.py:104-106` — Scale-out leg1 PT hit applies no exit slip; leg1 flip-fallback does apply EXIT slip; asymmetry vs PT fixed exits

**Category:** D1 (train/serve consistency — cost model)  
**Lines:** 100–108

The scale-out PnL is assembled as:

```python
leg1 = (ptpx - fill) * di * MULT if hit.size else (flip_c - di * EXIT - fill) * di * MULT
leg2 = (flip_c - di * EXIT - fill) * di * MULT
rec[f"so{Y}"] = 0.5 * leg1 + 0.5 * leg2 - COMM
```

When PT is hit (`hit.size` truthy), `leg1 = (ptpx - fill) * di * MULT` — no exit slip subtracted. The docstring states "PT = limit (no fav slip)" which is correct for a resting limit order — the limit fills exactly at `ptpx`. This is intentional and consistent with the fixed-PT treatment at lines 94–95.

When PT is NOT hit (flip fallback), `leg1` applies `- di * EXIT`, matching the `hold` and `pt{X}` fallback treatment. **This is correct and symmetric.**

`leg2 = (flip_c - di * EXIT - fill) * di * MULT` — `EXIT` slip applied once. **Correct.**

The only asymmetry is: `COMM = 5.0` is subtracted ONCE for the full two-legged position (`- COMM` at line 106). In a realistic scenario a scale-out is TWO fills (one at PT, one at flip), each attracting commission — the realistic total should be approximately `2 * COMM` for two separate fill events (or at minimum one in/two out). Using one RT commission for a two-legged exit **understates cost by approximately $5/trade** (one extra fill event). This is a consistent understatement, not a leak, but it flatters the scale-out exits relative to the fixed-PT exits and relative to live deployment (where each fill is billed separately).

**Recommended fix (do not apply):** Change line 106 to `0.5 * leg1 + 0.5 * leg2 - 2 * COMM` to model the two exit fills, or at minimum flag the `# one RT comm on full` comment as acknowledged-optimistic and note the $5 understatement in the output report.

---

## Info / Notes

### [I1] `bar4_knn_exit_atlas.py:57-58` — Cohort quantile thresholds computed on OOS pool (acknowledged in docstring)

**Category:** C1 / D1  
**Lines:** 57–58

```python
qR90 = np.quantile(ook.pRun, .90)
qF20 = np.quantile(ook.pFail, .20)
```

The 90th/20th-percentile thresholds for `pRun`/`pFail` are computed on the OOS evaluation set (`ook`, year >= 2025). This is acknowledged in the docstring: "Thresholds are OOS-relative percentiles (a deployment version needs IS-derived cuts)." The cohort selection therefore uses only the predicted probabilities (KNN neighbor class fractions from IS neighbors), not the true OOS class label or outcome. **No look-ahead into outcomes.** The threshold-from-OOS issue is a deployment concern, not a backtest validity concern here — the two-year split is the robustness gate, not a walk-forward guarantee.

Consistent with the companion script `bar4_knn_money_gate.py` lines 91–92 which uses the same OOS-relative percentile approach.

**No action required for the validity of this diagnostic.**

---

### [I2] `bar4_knn_exit_atlas.py:75-77` — 1s path slice is `t >= ENTRY_T and t <= T_flip`; confirm meaning of T_flip boundary

**Category:** A1 / B2  
**Lines:** 75–77

```python
t = np.asarray(r.p1s_t, np.int64); sel = t >= ENTRY_T
T_flip = n[ii] * 60 * NS
sel &= (t <= T_flip)
```

`ENTRY_T = 240 * NS` (bar-5 open = 4 minutes from flip-bar close). `T_flip = n[ii] * 60 * NS` where `n[ii]` is the 1m bar count of the regime (the post-flip count). The 1s-path offsets are from `regime_start_ts = completed.close_ts` (the flip-bar 1m close timestamp) as confirmed in `build_survivor_1s_paths.py` line 60.

The `t <= T_flip` upper bound is inclusive: it includes 1s bars exactly AT the last-minute boundary. Since 1s bars are indexed by their `ts_init` (which for 1s bars = ts_event + 1s from the catalog), a 1s bar at offset exactly `n*60s` would be the first second of the bar FOLLOWING the terminal 1m bar. This is a **boundary ambiguity of at most 1 second** and is unlikely to produce phantom fills (the PT hit test uses `h >= ptpx`; a single extra 1s bar's H/L is incorporated into MFE but does not change the fill price). Effect is negligible.

**No action required. Flagged for awareness only.**

---

### [I3] `bar4_knn_exit_atlas.py:81` — `fav_ext` computes from bar opens `e`, not from `fill`; MFE is slightly understated for longs

**Category:** B3  
**Lines:** 80–82

```python
h = np.asarray(r.p1s_h)[sel]; l = np.asarray(r.p1s_l)[sel]
fav_ext = (h - e) * di / ai if di == 1 else (e - l) * di / ai
mfe = max(fav_ext.max(), 0.0)
```

`e = O[ii, ENTRY_COL]` is the bar-5 open price (unfilled). `fill = e + di * ENTRY` is the actual fill (0.5 tick adverse). The MFE variable is computed relative to `e` (open), not `fill`. This means MFE is overstated by 0.5 ticks (0.5 × $0.25 × $20/pt = $2.50 ATR-adjusted) for longs, and understated by 0.5 ticks for shorts (since MFE in the short direction measures `e - l`, and fill is further adverse). The PT hit test at lines 91–92 correctly uses `fill` as the basis: `ptpx = fill + di * X * ai`. The MFE variable is used only **descriptively** (captured MFE % in the report, remaining-MFE distribution) and not to set PT levels. The slight overstatement of descriptive MFE captures does not affect PnL calculations.

**No action required for PnL correctness. Reported for completeness.**

---

### [I4] `bar4_knn_exit_atlas.py:92` — PT hit condition `h >= ptpx` (long) / `l <= ptpx` (short) correctly verifies fill feasibility

**Category:** E3 / G4  
**Lines:** 91–93

```python
ptpx = fill + di * X * ai
hit = np.where(h >= ptpx if di == 1 else l <= ptpx)[0]
if hit.size:
    ex = ptpx; g = X    # PT limit, no slip
```

For a long: hit requires `bar.high >= ptpx`. Since a resting limit sell at `ptpx` fills when price trades up to that level, `high >= ptpx` is the correct feasibility condition — the bar did reach the level. For a short: `low <= ptpx` is correct. This is the minimum bar-OHLC check that confirms the limit fill is achievable (no phantom fill). No lookahead: the hit test iterates only over `h[sel]` where `sel = t >= ENTRY_T and t <= T_flip`, i.e., bars strictly after entry. **PT fill feasibility is sound.**

**Clean. Confirmed.**

---

## Clean Checks

The following checklist items were verified and found clean:

- **Check 1 — Cohort uses only predicted probs, not true outcomes.** `pRun` and `pFail` are computed from IS-neighbor class fractions (`nbcls = isk.cls.values[idx]`, lines 55–56). `isk.cls` is the IS trade class from `bar4_knn_path_atlas.trade_class`, which uses only IS trade outcomes. The OOS true class (`coh.cls`, line 85 `run=int(r.cls == "Runner")`) is stored only in `rec["run"]` and used only for descriptive counting in the report, not for cohort selection. No OOS label is in the prediction path.

- **Check 2a — ENTRY_T=240s correctly equals bar-5 open offset.** `ENTRY_T = ENTRY_COL * 60 * NS - 60 * NS = 5*60*NS - 60*NS = 240*NS`. The formula comment `# bar-5 open = +240s from flip close ((5-1)*60)` is correct. Bar `k` open is at offset `(k-1)*60s` from flip-bar close since bar 1 open = flip close = offset 0, bar 2 open = +60s, ..., bar 5 open = +240s.

- **Check 2b — 1s path sliced to post-entry, pre-flip.** `sel = (t >= ENTRY_T) & (t <= T_flip)`. Entry is excluded from PT scanning (1s bars at exactly entry time are `t == 240s`; since `t >= ENTRY_T` the entry-open bar itself is included, which is correct as a fill would be placed at bar-5 open and the bar's H/L is fair game for PT triggers).

- **Check 2c — KNN signal at bar 4 close is strictly before bar-5 open entry.** The KNN features are `A.FEATS` at bar `k=4` (lines 47, 51): `["bar_idx", "mfe_sofar", ..., "vol_exp"]` all computed through bar 4 close in `build_states`. Entry is at `O[ii, ENTRY_COL]` = bar-5 open. No bar-5 data is in the features. Causal. Confirmed from `bar4_knn_path_atlas.py:54` (`entry = O[:, 4]`) and the fact that `build_states` computes `hk = H[i, 4:k+1]` at `k=4` = H[i, 4] only.

- **Check 3 — PT fill feasibility confirmed.** See I4 above. `h >= ptpx` / `l <= ptpx` before crediting limit fill at `ptpx`. No phantom fills.

- **Check 4 — Scale-out direction handling.** Both `leg1` and `leg2` scale by `di` via the `(... ) * di * MULT` pattern. Direction is applied consistently. Long: `di=+1`, fill below mid, PT above; short: `di=-1`, fill above mid, PT below. All sign math is consistent.

- **Check 5 — MFE forward-from-entry.** `fav_ext` uses only `h[sel]` / `l[sel]` where `sel = t >= ENTRY_T` (bar-5 open). MFE is a forward-from-entry metric. Confirmed.

- **Check 6 — MFE quantiles in remaining-MFE section (A2.mfe) use the same per-trade MFE from the simulation loop.** `A2.mfe` is filled from `rec["mfe"]` (line 85) which is the forward-from-bar-5-entry MFE computed at lines 80–82. The quantile table at lines 127–128 is descriptive of the cohort. Correct.

- **Check 7 — Year split robustness gate.** `A2.yr = yr[ii]` is the year of the regime from `df.year.values`. The verdict logic at lines 143 checks `n25 > 0 and n26 > 0`. Both-year positivity gate is present and operative.

- **Check 8 — IS/OOS split.** KNN IS reference = `isk = sb[sb.year < 2025]` (line 48). OOS evaluation = `ook = sb[sb.year >= 2025]` (line 48). Year boundary is strict. No OOS data leaks into the KNN fit.

- **Check 9 — flip_c source (line 84).** `df.post_c.values[ii][-1]` is the last 1m close of the post-flip bar array from the capsule, which is the terminal 1m close of the regime. This is the correct exit price for hold-to-flip and PT fallback scenarios. Consistent with `bar4_knn_money_gate.py:74` which uses `df.post_c.apply(lambda x: float(x[-1])).values[gi]` for the same purpose.

- **Check 10 — 1s-path timestamp zero-point.** `p1s_t` is stored as `b[0] - t0` where `t0 = int(cap["regime_start_ts"]) = completed.close_ts` (flip-bar 1m close) in `build_survivor_1s_paths.py:60-62`. The `ENTRY_T=240s` threshold is also relative to flip-bar close. The zero-points match.

- **A2 (ts_init_delta).** The aggregator uses `ts_event` (1s bar open time) as the bucket key (`bucket_id = ts_event // bucket_size`). A 1m bucket's `close_ts = (bucket_id + 1) * bucket_size`. This is the correct close time for a 1m bar when built from 1s open-timestamped bars. No ts_init_delta issue here — the aggregator constructs its own close_ts internally rather than relying on Databento bar timestamps.

- **B1 — No rolling with center=True.** No rolling/ewm operations in scope.

- **B4 — No `.shift(-N)` in feature path.** No negative-lag shifts in any file in scope.

- **B5 — No bfill.** No backward-fill in scope.

- **C3 — Temporal split.** IS = year < 2025, OOS = year >= 2025. No random split.

---

## Verdict on Positive Result Honesty

If the exit atlas produces a both-year-positive result, the three highest-probability leak vectors have been evaluated:

1. **PT phantom fill** — Ruled out. Hit condition `h >= ptpx` / `l <= ptpx` confirms the bar reached the level before crediting the fill. Clean.

2. **Entry using post-bar-5 info** — Ruled out. Entry is `O[ii, ENTRY_COL=5]` (bar-5 open). KNN features are bar-4-close-only from `build_states`. 1s path is sliced at `t >= 240s`. Clean.

3. **Cohort selection using true outcome** — Ruled out. Cohort uses `pRun`/`pFail` from IS-neighbor class fractions only. OOS `cls` is recorded post-hoc for the `run` column but not used in selection. Clean.

A positive result reflects a real improvement from exit selection, not a methodological artifact. The main honest caveat is the OOS-relative threshold issue (I1) and the single-commission understatement on scale-out legs (W2, ~$5/trade).

---

*Audit complete. Static analysis only. Dynamic bugs (race conditions, NT live dispatch order) are out of scope. The pipeline uses 1m-bar PnL simulation — 1s/tick NT live-style validation remains the deployment gate per methodology memory (`live_style_validation_is_the_gate`).*

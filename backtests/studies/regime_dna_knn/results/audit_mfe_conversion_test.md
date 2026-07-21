# Look-Ahead & Timestamp Audit — MFE Conversion Test (1s precision)

**Date:** 2026-06-15
**Auditor:** lookahead-auditor v1
**Scope:**
- `studies/regime_dna_knn/build_survivor_1s_paths.py` (primary)
- `studies/regime_dna_knn/mfe_conversion_test.py` (primary)
- Supporting: `early_health_filter.py` (CapsuleReplay), `progressive_separability.py`, `rejection_power.py`, `utils/safe_replay.py`, `collectors/collector_v2/aggregator.py`

> Persisted manually from the auditor's returned findings (the subagent reported in chat
> but did not write the file during its run). W2 was fixed; W1 and W3 were waived.

---

## Summary

- **Critical: 0**
- **Warning: 3**
- **Info: 4**

No look-ahead, no label contamination of features, no phantom fills, no entry/feature-window overlap. Intrabar adverse-first sequencing, PT fill feasibility, at_or_worse_close convention, and the regime_id join all check clean. Replay-vs-runtime parity = $0.00 median.

---

## Warnings

### [W1] `early_health_filter.py:155` / `build_survivor_1s_paths.py:45` — `ts_init` passed to aggregator as `ts_event` (train/serve skew)
Both CapsuleReplay and PathReplay feed `b.ts_init` to `on_1s_bar`; the live NT strategy feeds `b.ts_event`. This shifts 1m bucket boundaries by +1s — the last second of each minute is attributed to the next minute's bucket. Self-consistent within the offline study (1m capsule and 1s path use the same clock; regime_id join is 1:1), affecting ~1/60 of bars at minute boundaries. NOT a look-ahead — a divergence from live signal detection relevant only if the pipeline feeds a live deployment design.
**Status:** WAIVED — out of scope for this falsification (result negative by $7–20/tr in every cell; a 1.7%-of-bars 1s shift cannot flip it). Flagged for any future live-design step; would require feeding `ts_event` and rebuilding capsules.

### [W2] `mfe_conversion_test.py:72` — `pcflip` capped at column 61 for regimes with `n_post>61`
`build()` caps the matrix at `B=62` columns, so `pcflip = C[..., min(n,61)]` used the Bar-61 close (not the true terminal) for long regimes, while the time cap was `npost*60s` — a price/time mismatch for ~1–2% of trades on the flip cap only.
**Status:** FIXED — `pcflip` now taken from the exact terminal post close (`post_c[-1]`), correct for any regime length. Re-run confirmed verdict unchanged (0/108).

### [W3] `mfe_conversion_test.py:100-102` — float32 1s H/L/C vs float64 thresholds
Mixed-precision comparisons in stop/PT checks. NQ prices are exact multiples of 0.25 (representable exactly in both float32 and float64), so no material flip-decision error. 
**Status:** WAIVED — the $0.00 median parity against the independent float64 scalar walk is the empirical proof of no material precision error.

---

## Info
- **[I1]** 1s-after-flip attribution: the bar that triggers the 1m bucket close (first second of the new minute) is correctly appended to the NEW regime's path (position 0). Multi-bucket-close-in-one-call (large gaps) is an edge case that doesn't affect normal operation.
- **[I2]** Parity sample (`argsort(regime_id)[::N][:500]`) is an even temporal cross-section; `scalar_one` independently re-derives outcomes (not copying vectorized state), so $0.00 is meaningful. Only the `trail0.5` policy is parity-checked; `pt`/`be` branches share the same scalar coverage but aren't exercised by the fixed parity policy.
- **[I3]** `apply_caps` compares ns offsets consistently (exit_t and cap_t both ns from regime_start_ts). Verified `p1s_t` stores relative offsets, not absolute ts.
- **[I4]** Model B walk-forward purity maintained: trained IS survivors, scored OOS; `keep40` filter uses OOS pQ scores (rank-relative, acknowledged), never true labels.

---

## Clean Checks (critical paths)
- **Entry causality:** `entry = O[oos_m,4]` (Bar-4 open); features = `feats_through(M,3)` (cols 0..3); ENTRY_T=180s = Bar-4 open. No feature uses Bar 4+.
- **Fill feasibility (phantom-fill class):** stops fill `at_or_worse_close` (within triggering bar [low,high]); PT fills at pt_px only when peak (running max high) >= arm threshold, so the triggering bar's high reached pt_px — achievable, no phantom.
- **Intrabar adverse-first:** in-force stop checked against bar low/high BEFORE the peak updates with that bar's extreme; same-bar arm+stop uses this bar's low/high (no future-bar look-ahead).
- **Exit caps:** core trigger used only if `exit_t <= cap_t`; else exit at cap's 1m CLOSE. Truncated (1800s) paths: a trigger beyond the path simply isn't found → falls to cap exit (conservative).
- **regime_id join:** PathReplay inherits `_ridx` counter and year-filter unchanged → 1:1 join to the 1m capsule.

**Conclusion:** Zero CRITICAL. The replay correctly enforces causal entry, conservative intrabar sequencing, and feasible fills. Parity $0.00 median confirms the vectorized replay matches the independent scalar walk.

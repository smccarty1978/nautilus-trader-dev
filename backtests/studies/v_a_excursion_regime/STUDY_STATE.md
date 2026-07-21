# V_A Excursion Regime — Study State (handoff doc)

> **Purpose**: Snapshot of where the V_A delayed-entry + checkpoint-filter
> investigation stands as of 2026-05-13. Written so a fresh agent can
> pick up any thread without re-deriving context.

---

## TL;DR  (revised May 13 2026 after no-delay collector re-run)

**Status: NO DEPLOYMENT-GRADE STRATEGY YET.** All 4 candidate variants
(C/E × with-delay/no-delay) have material defects.

Headline numbers across the 4 variants:

| Strategy | n | Total $ | $/tr | 2024 | 2025 | 2026 bar | 2026 tick | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| WITH-DELAY C | 1,269 | +$61,370 | +$48.36 | −$9K | +$57K | +$13K | **+$10.6K** | **30s delay artifact + V-shape selection** |
| WITH-DELAY E | 3,890 | +$65,415 | +$16.82 | +$21K | +$53K | −$9K | est −$10K | 30s delay artifact, fragile |
| NO-DELAY C | 1,261 | +$22K | +$17.28 | −$3K | +$14K | +$10K | est +$8K | Methodologically clean, smaller edge |
| **NO-DELAY E** | 3,831 | **+$74,080** | +$19.34 | +$10K | +$43K | −$12K | **−$18K** | 2025-driven, 2026 collapses |

**Key finding (May 13)**: removing the 30s entry delay revealed two
inflation sources in the original C result:
1. **cp_ts timing**: WITH-DELAY cp_ts at bar1+331s gave the filter MORE
   information than NO-DELAY cp_ts at bar1+301s. ~$30K of the C drop
   was this. (See `constant_anchor_c_vs_delay.py`.)
2. **V-shape recovery selection**: V_A-anchored unr_pnl filter implicitly
   selected trades that dipped 0-30s after bar1 close and recovered by
   +5m. Worth ~$13K extra in 2025 — non-deployable artifact.

The +$48 to +$17 per-trade drop is real and material. The original
"strong C result" was mostly methodological inflation.

**2026 OOS is genuinely bad across all variants** — no methodology
fix saves it. This is regime-level, not signal-level.

**Best deployable per-trade economics**: WITH-DELAY C (+$10.6K tick)
but uses an arbitrary 30s delay. Cleanest deployable: NO-DELAY C
(+$22K bar / est +$8K tick) — smaller edge, 2026-positive, no
methodology defect.

Both ~2× the V_A baseline total $ and ~60% smaller max drawdown.

**Structural finding (decompose_c6_by_va.py)**: HH/LL+momentum confirmation
IS the directional edge. Splitting all-flips C6/E8 cohorts by
is_VA_confirmed yields:

| Cohort | V_A confirmed | NOT confirmed | spread |
|---|---:|---:|---:|
| C6 | −$1/tr (15/29 +mo) | **−$39/tr** (12/29 +mo) | $38/tr |
| E8 | +$4/tr (14/29 +mo) | **−$42/tr** (8/29 +mo) | $46/tr |

There is **no second profitable continuation family** outside V_A
confirmation. The "delayed-entry + checkpoint filter" framework only
works as a refinement layer on V_A-confirmed signals.

---

## Strategy definitions

### Underlying signal: V_A

V_A trades = 1m regime flip + bar+1 confirmation:
1. 1m regime indicator flips direction (+1 ↔ −1) on bar close
2. Next 1m bar (bar+1) makes a new HH (long) or LL (short) of the flip bar
3. Bar+1 close is in the trade direction (close > open for long; close < open for short)
4. **Entry**: OPEN of next 1s bar after bar+1 close (= flip_bar_close + 1s)
5. Exit: OPEN of 1s bar after detection of opposing regime flip

**Two collector outputs exist:**
- `collectors/collector_v2/results/v_a_v0_{year}/trades.parquet`: WITH 30s
  delay (legacy). entry_ts = flip_bar_event + 150s. Used by all studies
  before May 13 2026.
- `collectors/collector_v2/results/v_a_v0_nodelay_{year}/trades.parquet`:
  NO 30s delay (correct). entry_ts = flip_bar_event + 121s. Used by
  no-delay studies after May 13 2026.

**Code change committed**: `collectors/collector_v2/strategy.py:637`
changed `decision_ts + 30 * 1_000_000_000` → `decision_ts`. The legacy
trades parquet remains for comparison — do not regenerate it.

**Going forward**: use `_nodelay` variants for new analysis. The
methodology is correct (anchor from bar close, no arbitrary delays).

### The 5 variants under study

All variants use V_A trades unless noted. "T" measured from V_A entry
(which has the 30s legacy offset).

| | Name | Entry | Filter | Description |
|---|---|---|---|---|
| **A_5m** | matched T0 baseline (alive@5m cohort) | T0 | none | T0 entry on V_A trades that survived past +5m. *Survivor-biased upper bound — not deployable.* |
| **B** | delayed-only @+5m | +5m delay | alive@5m | Skip if dead before +5m, else enter at OPEN of 1s bar at +5m. Held to regime flip. |
| **C** | delayed @+5m + unr filter | +5m delay | alive@5m AND `f_unr_pnl_T_5m ≥ $325` | Same as B, plus skip unless trade is up ≥ $325 unrealized at +5m. |
| **A_7m** | matched T0 baseline (alive@7m cohort) | T0 | none | T0 on alive-@-7m cohort. Also survivor-biased. |
| **D** | delayed-only @+7m | +7m delay | alive@7m | Mirror of B at the +7m mark. |
| **E** | delayed @+7m + dual momentum | +7m delay | alive@7m AND `f_net_move_150s_7m ≥ −$11.25` AND `f_net_move_300s_7m ≥ −$5.25` | Skip unless 5min and 10min momentum (direction-aware) is not strongly against the trade. |

### All-flips analog (for sanity check, NOT deployment)

Same template, but base population = ALL regime_flip snapshots
(unfiltered, no HH/LL+momentum confirmation). Anchored from
`decision_ts` (= flip_bar_close + 1s), so the wall-clock equivalent of
V_A's "+5m" is **+6m** here, "+7m" is **+8m**.

| | Name | Description |
|---|---|---|
| A6m_T0 | matched T0 (alive@6m cohort, all flips) | Survivor-biased |
| B6 | all-flips delayed-only @+6m | |
| C6 | all-flips delayed @+6m + unr filter (IS-q80 = $385) | |
| A8m_T0 | matched T0 (alive@8m cohort, all flips) | |
| D8 | all-flips delayed-only @+8m | |
| E8 | all-flips delayed @+8m + dual momentum (IS-q10/q20) | |

**All all-flips variants are net negative.** Confirms V_A's HH/LL+momentum
filter is doing real work. See `all_flips_matched.log` for full numbers.

---

## Current results (matched cohorts, 1c, RTH NQ.v.0 2024-2026)

### V_A variants

| Strategy | n | Total $ | $/tr | Max DD | 2024 | 2025 | 2026 | +mo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full V_A baseline 1c T0 | 7,745 | +$33,700 | +$4.35 | −$50,590 | +$14,475 | +$52,560 | −$33,335 | 14/29 |
| A_5m matched T0 *(survivor-biased)* | 5,954 | +$816,745 | +$137.18 | −$8,500 | +$293,300 | +$406,500 | +$116,945 | 29/29 |
| B delayed-only @+5m | 5,954 | +$50,520 | +$8.49 | −$32,315 | +$18,440 | +$56,030 | −$23,950 | 17/29 |
| **C +5m + unr ≥ $325** | **1,269** | **+$61,370** | **+$48.36** | **−$19,790** | −$9,065 | +$57,165 | **+$13,270** | 15/28 |
| A_7m matched T0 *(survivor-biased)* | 5,130 | +$1,136,575 | +$221.55 | −$5,840 | +$407,045 | +$561,955 | +$167,575 | 29/29 |
| D delayed-only @+7m | 5,130 | +$46,525 | +$9.07 | −$28,675 | +$20,430 | +$46,680 | −$20,585 | 15/29 |
| **E +7m + dual momentum** | **3,890** | **+$65,415** | **+$16.82** | **−$18,765** | +$20,995 | +$53,395 | −$8,975 | **17/29** |

### All-flips variants

| Strategy | n | Total $ | $/tr | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| Full all-flips T0 | 16,264 | −$505,570 | −$31.09 | −$130,455 | −$216,115 | −$159,000 |
| C6 +6m + unr filter | 2,299 | −$28,260 | −$12.29 | −$25,445 | +$12,310 | −$15,125 |
| E8 +8m + dual momentum | 6,816 | −$122,745 | −$18.01 | −$63,530 | −$7,900 | −$51,315 |

---

## Critical methodology rules

These ARE invariants. Don't violate.

1. **Anchor checkpoint timing from BAR CLOSE.** Regime flips aren't
   known until the 1m bar closes. All "+Nm" measurements anchor from
   `flip_bar_close` (= `decision_ts`). NOT bar open. NOT signal +
   arbitrary delay.

2. **NO 30s post-confirmation delay.** V_A entry is intended to be
   OPEN of next 1s bar after bar+1 close. The legacy
   `entry_ts = flip_bar_event + 150s` in the data IS WRONG. Future
   collector re-runs must fix.

3. **IS = 2024+2025, OOS = 2026.** All threshold fits use IS only.
   All quantile bins, feature ranking, and threshold sweeps must
   compute on IS-only data. OOS is for evaluation only.

4. **Causality**: `searchsorted(side="left")` on bar timestamps. The
   bar AT the checkpoint timestamp is excluded from feature
   computation (it hasn't closed yet at decision time). Momentum
   windows `[cp_ts − W, cp_ts)` use bars strictly before cp_ts.

5. **No tape-replay claims without tick-NT validation.** Memory rule:
   tape-replay overstates 5-10× vs tick-driven NT. Any C/E
   deployment claim needs MBP-1 tick validation first.

6. **NQ.v.0 data only.** Calendar-continuous c.0 files quarantined
   to `data/raw/legacy_c0/`. Never use them.

7. **Audit gate**: Before declaring any new study/strategy script
   "done", invoke the lookahead-auditor sub-agent. Address every
   CRITICAL finding by editing code (don't dismiss).

---

## Filter thresholds (FIXED, IS-fit, do not re-derive)

These were fit on IS (2024+2025) alive cohort and should be treated
as constants going forward. Re-deriving on different splits invalidates
the OOS results.

| Filter | Threshold (with-delay data) | Threshold (no-delay data) | Source | Rule |
|---|---|---|---|---|
| C: `f_unr_pnl_T_5m` | ≥ $325 | **≥ $335** | IS q=0.80 of V_A alive@5m | KEEP if ≥ |
| C alt: `f_unr_atr_T_5m` | ≥ 0.75 ATR | (similar) | hand-set | KEEP if ≥ — methodology-cleaner |
| E: `f_net_move_150s_7m` | ≥ −$11.25 | **≥ −$9.75** | IS q=0.10 of V_A alive@7m | KEEP if ≥ |
| E: `f_net_move_300s_7m` | ≥ −$5.25 | **≥ −$3.75** | IS q=0.20 of V_A alive@7m | KEEP if ≥ |
| C6 (all-flips): `f_unr_pnl_T_6m` | ≥ $385 | (not refit) | IS q=0.80 of all-flips alive@6m | reference only |
| E8 (all-flips): `f_net_move_150s_8m` | ≥ −$9.00 | (not refit) | IS q=0.10 | reference only |
| E8 (all-flips): `f_net_move_300s_8m` | ≥ −$3.25 | (not refit) | IS q=0.20 | reference only |

### Why both fixed-$ and ATR-normalized are kept

The fixed $ threshold has an **implicit ATR-multiple drift across years**
because NQ vol has risen 53% from 2024 to 2026 (median ATR 10.14 → 15.55).
For a 2024 trade $325 ≈ 1.6 ATR; for 2026 ≈ 1.05 ATR. Filter selectivity:
2024 16.7% / 2025 24.2% / 2026 27.0% pass. ATR-normalized is uniform
(~36% pass each year).

This vol-drift effect is part of why removing the 30s entry delay
collapsed C — the fixed-$ filter calibration was tied to the specific
WITH-DELAY V_A entry timing AND the 2024-2025 vol regime. Both
assumptions can shift independently.

If/when expanding to ES/YM or a different vol regime, the ATR-normalized
version is the right starting point. For NQ today, neither produces
deployment-grade economics with the no-delay (correct) methodology.

---

## Feature definitions (computed at checkpoint time T)

All features are direction-aware (long uses upside, short uses downside)
and causal (computed from bars with `ts_event < cp_ts`).

| Feature | Definition |
|---|---|
| `f_mfe_atr_T` | Maximum favorable excursion since V_A entry, normalized by `atr_at_signal` |
| `f_mae_atr_T` | Maximum adverse excursion, normalized by `atr_at_signal` |
| `f_unr_pnl_T` | Current unrealized PnL in $ (at last bar close before cp_ts), `(close − fill_px) × direction × 20` |
| `f_mfe_to_mae` | Ratio f_mfe_atr_T / f_mae_atr_T |
| `f_close_loc_in_range` | Where last close sits in [low, high] of segment, direction-aware |
| `f_net_move_30s/60s/150s/300s` | Net price move (direction-aware) over W seconds ending strictly before cp_ts |
| `f_atr` | atr_at_signal |
| `f_direction` | +1 long, −1 short |

---

## Data sources

| What | Path | Notes |
|---|---|---|
| 1s bars | `data/catalog/NQ_v0_2020_2026/` | Active catalog. Use `ParquetDataCatalog`. |
| 1s raw | `data/raw/NQ_v0_1s_{year}.parquet` | Used directly for feature computation in studies. UTC-indexed, ts_event = bar OPEN. |
| 1m bars | same catalog | DO NOT use the legacy `data/catalog/NQ_v0_2025/` (had the `closed='right'` resample bug — see MEMORY.md). The active 2020-2026 catalog is rebuilt with `closed='left'`. |
| Quarantined data | `data/raw/legacy_c0/` | Calendar-continuous c.0 files. Never use. |
| V_A trades | `collectors/collector_v2/results/v_a_v0_{year}/trades.parquet` | HH/LL+momentum filtered. ⚠ entry_ts has legacy 30s delay. |
| All regime flips | `collectors/collector_v2/results/v_a_v0_{year}/snapshots.parquet`, kind=='regime_flip' | Unfiltered. RTH only. |

### Cross-year overlap

V_A trades.parquet has 49 trades duplicated across 2024/2025 boundary
(same trade processed by both year-collector runs). Snapshot data has
~100 duplicates. **Always dedupe by `entry_ts` (or `decision_ts`)
keeping `keep="first"` (earlier year).** Current scripts (matched_comparison.py,
all_flips_matched.py) do this.

---

## Key scripts

Listed in chronological discovery order. Each is audit-clean (CRITICAL
findings addressed before result interpretation).

### Active / authoritative

| Script | Purpose | Output |
|---|---|---|
| `delayed_only_sweep.py` | Wait-time sweep {2,3,4,5,7,10,15}m + V4 stack on each | `delayed_only_sweep.parquet`, `.log` |
| `checkpoint_filter_search.py` | Univariate quintile + threshold sweep on +5m/+7m | `checkpoint_features.parquet`, `.log` |
| `matched_comparison.py` | A/B/C/D/E V_A matched comparison report | `matched_comparison.log` |
| `all_flips_matched.py` | Same methodology on unfiltered regime flips | `all_flips_features.parquet`, `.log` |
| `decompose_c6_by_va.py` | Splits all-flips C6/E8 by `is_VA_confirmed` to isolate the structural edge | `decompose_c6_by_va.log` |
| `bootstrap_va_c.py` | Bootstrap battery for fixed-$ C filter (with-delay) | `bootstrap_va_c.log` |
| `bootstrap_va_e.py` | Bootstrap battery for E filter (with-delay) | `bootstrap_va_e.log` |
| `bootstrap_va_c_atr.py` | Bootstrap battery for ATR-normalized C (with-delay) | `bootstrap_va_c_atr.log` |
| `bootstrap_va_e_nodelay.py` | Bootstrap battery for E (no-delay) | `bootstrap_va_e_nodelay.log` |
| `tick_validate_va_c_2026.py` | MBP-1 tick validation for fixed-$ C, 2026 OOS (with-delay) | `tick_validate_va_c_2026.log`, `.parquet` |
| `tick_validate_va_c_atr_2026.py` | Same but for ATR ≥ 0.6/0.75 variants (with-delay) | `tick_validate_va_c_atr_2026.log` |
| `tick_validate_va_e_nodelay_2026.py` | MBP-1 tick validation for E, 2026 OOS (no-delay) | `tick_validate_va_e_nodelay_2026.log`, `.parquet` |
| `atr_normalized_c_filter.py` | ATR threshold sweep + vol regime analysis | `atr_normalized_c_filter.log` |
| `rerun_pipeline_nodelay.py` | Rebuilds checkpoint features + matched comparison from no-delay collector outputs | `rerun_pipeline_nodelay.log`, `checkpoint_features_nodelay.parquet` |
| `constant_anchor_c.py` | Constant-anchor (bar1_close) version of C, isolating from V_A entry timing | `constant_anchor_c.log` |
| `constant_anchor_c_vs_delay.py` | 4-way comparison: WITH-DELAY/NO-DELAY × V_A-anchor/bar1-anchor (decomposes the +$61K → +$22K drop) | `constant_anchor_c_vs_delay.log` |
| `alive_at_5m_study.py` | Earlier "alive at +5m" cohort study (anatomy) | `alive_at_5m.parquet`, `.log` |
| `va_baseline_diagnostic.py` | V_A fundamentals (trades/day, MFE distribution, hold-time WR) | `.log` |

### Reference / superseded

| Script | Status |
|---|---|
| `two_contract_pt1_calc.py` | Tested 2c PT1 — DEAD (sacrifices runners) |
| `delayed_entry_2bar.py`, `delayed_entry_dip_filter.py` | Earlier delayed-entry experiments — superseded by sweep |
| `early_kill_overlay.py` | V4 overlay original — V4 windows hard-coded at +3m/+4m from V_A entry |
| `tick_validate_v4.py` | V4 tick validation (memory: V4 retains 69% of 1s-bar lift on tick) |
| `mr_companion_v1.py`, `mr_companion_v2_sweep.py` | Mean-reversion companion — DEAD |
| `ml_early_kill_classifier.py`, `ml_walk_forward.py` | ML classifier attempt — DEAD on walk-forward OOS |
| `sl_grid_study.py` | Catastrophic SL grid — DEAD (cuts runners) |

---

## Where we came from (key learnings)

In rough chronological order:

1. **V_A baseline diagnostic established the population shape.**
   - 12.9 trades/day, 34.8% WR, 76.9% survive 5+ min
   - 4+ ATR runners are 17.4% of trades but 81.5% of winner PnL
   - Hold time bands: <10min trades are 0-6% WR (pure losers); 20+ min are 86-97% WR

2. **Naive 2-contract PT1 fails** — sacrifices the runners that produce
   most of V_A's PnL. Dead branch.

3. **Alive-at-+5m study** showed:
   - Dead-<5m cohort = 1,800 trades, 0.3% WR, −$787K (loss center)
   - Alive cohort = 5,994 trades, 45.1% WR, +$824K (+$138/tr)
   - "Skip the early-failure trades" hypothesis emerged

4. **Wait-time sweep** found +5m and +7m delayed entry both improve
   on V_A baseline. **+4m is a hazard zone** (avoid). +10m/+15m wait
   too long.

5. **Checkpoint filter search** found:
   - At +5m: `f_unr_pnl_T` (currently profitable) is the only stable
     filter. IS q=0.80 cuts 79% of trades but doubles per-trade.
     Per-trade is consistent IS vs OOS (+$45 vs +$42). **Turns 2026
     positive.**
   - At +7m: `f_net_move_150s` and `f_net_move_300s` (5/10min
     momentum) work in BOTH IS and OOS. Pair filter at IS-q10/q20
     keeps 76% of trades, lifts both.

6. **Matched comparison** revealed:
   - The "matched T0 alive cohort" baselines are SURVIVOR-BIASED
     upper bounds (+$817K for V_A, +$1.8M for all-flips). Not
     deployable.
   - Real per-trade cost of delaying 5min ≈ $128/tr; 7min ≈ $212/tr.
     Most of V_A's edge is in the first few minutes.
   - C and E both ~2× V_A baseline total $ with ~60% lower DD.

7. **All-flips comparison** confirmed:
   - V_A's HH/LL+momentum filter is doing real work — without it,
     no variant survives.
   - Even C6 (best all-flips) is −$28K. V_A C is +$61K on a smaller pool.

8. **C6/E8 decomposition by V_A confirmation** (decompose_c6_by_va.py)
   nailed down WHERE the alpha lives:
   - C6 V_A subset (1,619): −$1/tr ≈ breakeven
   - C6 NOT-confirmed subset (680): **−$39/tr**
   - E8 V_A subset (3,517): +$4/tr (14/29 +mo)
   - E8 NOT-confirmed subset (3,299): **−$42/tr**
   - Forward MFE/MAE patterns are nearly identical between subsets —
     the difference is WHICH side touches first. V_A's bar+1
     mechanics are the directional truth, not the post-flip
     excursion magnitude.
   - **No second profitable continuation family exists** outside
     V_A confirmation.

9. **Bootstrap CI** (bootstrap_va_c.py / _e.py / _c_atr.py) revealed
   **all C/E variants are statistically fragile**:
   - Fixed $325 C: pooled PASS (+$0.41 5th pctile), per-year FAIL,
     rolling FAIL. 2024 P(mean>0) = 26.9%.
   - E (+7m + dual mom): pooled FAIL (−$1.87 5th pctile), all years
     FAIL. Lowest per-trade edge → widest variance.
   - ATR ≥ 0.75 C: pooled FAIL (−$2.17), but **2024 P(mean>0) = 66%**
     — much better year-level stability.
   - **None pass the strict per-year + rolling consistency battery.**

10. **Tick validation 2026 OOS** (tick_validate_*.py) revealed **fixed-$
    survives slippage better than ATR-normalized**:
    - Slippage cost is roughly fixed per trade (~$13/tr).
    - Fixed $325 retains 80% of bar edge ($46/tr after slippage).
    - ATR ≥ 0.75 retains 53% ($14.79/tr after slippage).
    - ATR ≥ 0.60 turns NEGATIVE on tick (−$2.83/tr).
    - **2026 OOS tick measurements**: Fixed-$ +$10,610 vs ATR≥0.75
      +$4,480.
    - **Fixed $325 wins on deployable economics** despite worse
      bar-level cross-year stability.

11. **MAJOR (May 13 2026): collector re-run without 30s delay revealed
    fundamental result inflation.** Previous "deployable" C result was
    methodologically suspect.
    - V_A baseline 1c dropped from +$33,700 → +$8,060 (mostly 2025: −$24K)
    - C ($325 unr) dropped from +$61,370 → +$22K (2025: −$43K)
    - E (+7m + dual mom) IMPROVED from +$65,415 → +$74,080 (2025: +$15K, 20/29 +mo)
    - **The 30s delay was selecting V-shape recovery trades** in 2025
    - cp_ts timing shift (5.5m → 5m) accounted for $30K of the C drop
    - V-shape selection accounted for additional $13K in C
    - See `constant_anchor_c_vs_delay.py` for the decomposition.
    - Lesson: arbitrary delays in entry timing can act as silent
      feature selectors. The 30s wait gave the +5m unr_pnl filter
      MORE information AND implicitly selected for v-shape recoveries.

12. **Tick validation of no-delay E on 2026 OOS**: −$18,070 / −$34.82/tr
    on valid quotes (tick_validate_va_e_nodelay_2026.py). The +$74K
    E total is essentially all 2025; tick-level 2026 is decisively
    negative.

13. **Bootstrap on no-delay E**: pooled 5th pctile −$0.36 (FAIL),
    2026 P(mean>0) = 24% (worst rolling-50 ALL in Feb-Mar 2026).
    Slightly more robust than with-delay E but still doesn't pass.

---

## Open questions / next steps

Listed in priority order. Each is independently actionable.

### Done since last edit

1. ✅ Decompose all-flips C6 by V_A confirmation — confirmed HH/LL+momentum
   IS the structural edge. No second profitable continuation family.
2. ✅ Tick-validate fixed-$ C on 2026 OOS — 80% edge retention, +$10.6K
   tick PnL.
3. ✅ Tick-validate ATR-normalized variants — 53% retention; ATR≥0.6
   turns negative on tick.
4. ✅ Bootstrap CI on C, E, ATR≥0.75 — all fragile; ATR has best
   year-level base rate but lowest pooled CI.

### Done since last edit

5. ✅ Removed 30s delay in collector code, re-ran for 2024-2026
6. ✅ Decomposed C drop ($61K → $22K) into cp_ts timing ($30K) + V-shape selection ($13K)
7. ✅ Tick-validated no-delay E on 2026 OOS — −$18K (worse than expected)
8. ✅ Bootstrapped no-delay E — slightly more robust than with-delay E but still fails

### High priority

1. **Decide on deployment posture.** We have two paths and they're both flawed:
   - **NO-DELAY C**: cleanest methodology, smaller edge (+$22K bar / est +$8K tick),
     2026-positive but tiny. Bootstrap likely fails.
   - **NO-DELAY E**: bigger total ($74K bar) but mostly 2025-driven; 2026 OOS
     decisively negative on tick (−$18K). Bootstrap fails.
   - **Honest answer**: don't deploy yet. Either find a more robust signal
     or accept that V_A's edge is regime-dependent and thinner than thought.

2. **Sub-sweep around +5m / +5.5m / +6m on no-delay data** to test if the
   "more wait = more info = better filter" effect is exploitable.
   - The cp_ts at bar1+331s gave +$48K (with-delay bar1-anchor)
   - The cp_ts at bar1+301s gave +$19K (no-delay bar1-anchor)
   - Is there a sweet spot at bar1+331s+ that's deployable on its own?
   - Quick test: compute features at +5.5m and +6m on no-delay data
   - 1-2 hour task

3. **Tick-validate fixed-$ C and NO-DELAY E across IS years (2024-2025)**
   if/when MBP-1 data becomes available for those years. Currently we only
   have 2026 ticks. Until then, all "tick-validated" claims apply to 2026
   OOS only.

### Medium priority

4. **Stack V4 on top of C and E** — does V4 still add value once we're
   already using C or E? V4 fires at +3m / +4m from V_A entry; C/E
   gate at +5m / +7m. They could compound or be redundant.
   - Reference: `early_kill_overlay.py` for V4 implementation
   - 1-2 hour task

5. **Investigate Apr 2026 drawdown in C.**
   - C cumulative chart: peak +$73,695 in Feb 2026, gave back to
     +$61,370 by Apr (−$10,110 in Apr alone)
   - Only material DD in C's lifetime
   - If regime change identified, may need a vol-regime gate

6. **Walk-forward bootstrap on C** to get CI on per-trade edge.
   - Memory pattern: many V_A leads have failed the bootstrap
     robustness battery
   - C has only 1,269 trades over 3 years — small sample
   - 5th-percentile bootstrap mean > $0 would survive the fragile-signal
     test
   - 2-3 hour task

### Lower priority / exploratory

7. **T0 survival classifier.** The matched A_5m baseline (+$817K) shows
   enormous edge if we could pre-identify surviving trades AT T0.
   Even a mediocre classifier (60-65% accurate) would dominate C/E.
   Features available at T0: ATR, regime context, time-of-day,
   recent vol, prior bar pattern.
   - Memory warning: prior `ml_early_kill_classifier.py` failed on
     walk-forward OOS. Risk of repeat.
   - 2-3 day task

8. **Sub-sweep wait time around +6m / +8m** to find precise per-trade
   optimum. We only have +5m, +7m (jumped to +10m).
   - 1-2 hour task

---

## Don't waste time on

These were tried and failed. Don't re-attempt without structural change.

- 2-contract PT1 at any ATR level (sacrifices runners)
- Catastrophic SL grid at 0.5-1.5 ATR (cuts winners more than losers)
- MR companion (regime non-stationarity)
- ML +1m early-kill classifier (IS-fit, fails OOS)
- 0-bar / 2-bar / 4-bar entry delays in dip-filter style (alpha cost > savings)
- All-flips strategies (without V_A's HH/LL+momentum filter)
- **Searching for non-V_A continuation families** (decompose_c6_by_va
  proved hypothesis B is dead — only V_A-confirmed signals carry edge)

See MEMORY.md for full dead-branch list across the project.

---

## Files in this directory (current)

```
studies/v_a_excursion_regime/
├── STUDY_STATE.md              # this file
├── alive_at_5m_study.py        # cohort anatomy
├── all_flips_matched.py        # all-flips comparison (latest)
├── checkpoint_filter_search.py # filter sweep (top features at +5m, +7m)
├── delayed_only_sweep.py       # wait-time sweep + V4 stack
├── early_kill_overlay.py       # V4 original (reference)
├── matched_comparison.py       # A/B/C/D/E V_A matched
├── two_contract_pt1_calc.py    # 2c PT1 (dead)
├── va_baseline_diagnostic.py   # V_A fundamentals
└── results_v0/
    ├── alive_at_5m.parquet
    ├── checkpoint_features.parquet
    ├── delayed_only_sweep.parquet
    ├── all_flips_features.parquet
    ├── matched_comparison.log
    ├── checkpoint_filter_search.log
    ├── all_flips_matched.log
    └── (many other .log / .parquet files from prior experiments)
```

The `results_v0/*.parquet` files are CACHES. If you re-run a script
and want fresh features, delete the corresponding parquet first. The
matched comparison loads `checkpoint_features.parquet` if it exists,
otherwise re-computes.

---

## Contact / context handoff

If picking this up cold:
1. Read MEMORY.md first (esp. CRITICAL methodology rules + dead branches)
2. Read this file (STUDY_STATE.md) for current state
3. Read `matched_comparison.log` and `all_flips_matched.log` for the
   latest numbers
4. The audit gate is mandatory. Don't trust any new script result
   without invoking lookahead-auditor.

Last updated: 2026-05-13

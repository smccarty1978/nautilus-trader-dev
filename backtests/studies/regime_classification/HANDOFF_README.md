# Regime Classification Research — Handoff README

**Status as of writing:** Phases 1–5 complete, NT live-validated.
One mechanism identified (state persistence). One specific deployable
filter awaiting test (`state_dur_before ≥ N`).

---

## 1. Quick context

**What we're trying to do.** Identify market-state regimes from 1s
OHLCV alone, then test whether existing 1m flip signals perform
materially differently conditioned on state. Goal is NOT a profitable
signal-by-itself; goal is to find at least one state where an
existing signal's win-rate / EV materially improves (≥ +3–5pp) and
holds year-by-year.

**Prior context worth knowing.** Seven independent angles on the
1m regime-flip signal class with OHLCV-derived features have been
proven dead (see `~/.claude/projects/.../memory/v_a_1m_flip_signal_class_dead.md`).
Hence the pivot from "predict flips" to "classify market state and
overlay existing signals."

**Key methodology rules** (all in the memory dir, but flagged here
because every prior attempt that ignored them got bitten):

- `v2_feature_snapshots` is a FILTERED universe (bar1-confirmed only;
  100% selection bias). Do NOT use as a "raw universe". Always use
  NT-detected flips from `backtests/baseline_flip_parity/results/`.
  See `memory/v2_collector_universe_filtered.md`.
- Causal anchors only: bar1-confirm is observable at `T + 60s`. If a
  filter uses bar1-confirm, the entry must be at `T + 60s`, not `T`.
  Mixing them inflates win rates by ~25-30pp. Don't.
- IS = 2020-2022, OOS = 2023-2026. Fit scalers, models, thresholds on
  IS only.
- NT BacktestEngine is the gate for any deployment claim. Offline
  Python scans are for screening only.

---

## 2. File map (regime_classification folder)

### Scripts in execution order

| # | Script | What it does |
|---|--------|--------------|
| 1 | `build_features.py` | Compute 24 causal features per 1m bar from 1s OHLCV. ~3 min. |
| 2 | `fit_regimes.py` | Fit HMM + GMM + KMeans × k=3,4,5,6 on IS, predict on all years. ~40 min. |
| 3 | `interpret_states.py` | Per-state share / feature means / duration / transition matrix. ~1 min. |
| 4 | `overlay_signals.py` | Phase 4 v0: state overlay on 4 cohorts — NOT CAUSAL for bar1_confirm. Reference only. |
| 5 | `bar1_deployable_state_overlay.py` | Phase 4 corrected: bar1_confirm with bar1-close entry (deployable). ~5 min. |
| 6 | `survivor_deep_dive.py` | Per-state $/tr, MAE, transitions for the 8 survivor cells. ~2 min. |
| 7 | `diagnose_2025_effect.py` | Per-trade MFE/MAE/state_dur_before. 2025 vs 2023+24 comparison. ~1 min. |

### Output parquets (under `results/`)

| File | Contents |
|---|---|
| `features_nq_1m.parquet` | 2.23M rows × 24 features + atr_1m + calendar cols |
| `states_nq_1m.parquet` | Same + 12 state columns (`hmm_K`, `gmm_K`, `kmeans_K` for K∈{3,4,5,6}) |
| `bar1_deployable_state_nq.parquet` | bar1-confirm cohort (45K rows) with bracket + regime outcomes at bar1-close anchor + state lookups at both flip and bar1 moments |
| `diagnose_2025_nq.parquet` | NT-validated trades (1,180 OOS rows) with MFE / MAE / state_dur_before / PDH/PDL/ONH/ONL distances / full 24 state features at entry |
| `interpretation_summary_nq.csv` | Model degeneracy / separation comparison |
| `overlay_survivors_nq.csv` | 13-cell survivor list from non-causal v0 overlay |

### NT validation (separate folder)

```
backtests/hmm_state_filtered/
├── strategy.py                              — Live-style NT strategy
├── run_backtest.py                          — One-year runner
├── run_all_years.py                         — 7-year sweep, 3 parallel
└── results/nq_hmm_4_s3_{2020..2026}/
    ├── trades.parquet                       — Recorded trades
    └── run.log                              — Strategy diagnostics
```

---

## 3. What's been done

### Phase 1 — Features
24 causal features per 1m bar, computed from strictly-backward-looking
1s lookback windows. Six feature groups: returns / vol-range / path /
candle / VWAP-session / compression. All windows end at the 1m bar
close (causal).

### Phase 2 — Models
12 unsupervised fits (HMM × GMM × KMeans × k=3,4,5,6) on IS rows
(2020–2022, ~840K rows after dropping NaN warmup). StandardScaler fit
on IS only and applied to all years.

### Phase 3 — Interpretation
KMeans-4 emerged as best-balanced (max share 43.5%, separation 1.38).
HMMs are sticky to a dominant ~70% "calm" state at k=3,4,5 — not a
bug, just reflects that most 1m bars are quiet. Four readable
archetypes appear: **Compression**, **Expansion/Breakout**, **Chop**,
**Stretched from VWAP**.

### Phase 4 — Signal overlay
Tested 12 models × 4 cohorts (raw NT flips, bar1_confirm, launchpad,
5s pullback-resume) under filters: pooled OOS n ≥ 200, |lift| ≥ 3pp,
per-year n ≥ 30 in 3+ years, same sign in 3+ years.

**Initial (non-causal) result:** 13 survivor cells, mostly on
bar1_confirm cohort with +3-5pp lift. Then realized the bar1_confirm
cohort was using flip-close entry pricing while the bar1_confirm
filter was bar1-close-observable — same anchor-mismatch trap that
killed v2. Reran with bar1-close entry. Bracket outcome collapsed to
50% baseline (true causal). **REGIME-EXIT outcome survived** with
real lifts (+5-7pp in multiple models). 31 survivor cells in the
corrected sweep, of which 28 are regime-exit.

### Phase 5 — Survivor deep-dive
For the 7 best positive cells + 1 worst negative cell, computed
$/trade, ATR/trade, median win, median loss, 90th-pct winner, MAE,
hold time, year-by-year EV, long/short split, and post-entry state
transitions.

**Cleanest cell:** `hmm_4` flip state 3 — +$37/trade pooled OOS,
3 of 4 OOS years positive, both long ($67) and short ($10)
contributing, 82% state persistence at +1m, n=1,408.

But: PnL is heavily concentrated in 2025 (+$110/tr) with 2023/2024
losing.

### NT live-style validation
Built `HMMStateFilteredStrategy` — subscribes to 1s bars, detects
1m flips via sticky EMA3/9 of high/low, looks up flip-bar state
from offline-computed `states_nq_1m.parquet` (causally OK because
features ended at flip-close), waits for bar1 confirmation at
T+60s, enters market FOK at next 1s open (= bar1 close), exits on
next 1m regime flip out of trade direction.

**Result:** NT validates the offline finding directionally — OOS
pooled win 40.2% (offline 39.1%), net $/tr +$51.54 (offline +$37.10).
Causality confirmed. **BUT** the 2025 concentration is even worse in
NT: 4 of 7 years lose money, only 2025 (+$183/tr) and 2026 (+$17/tr)
are positive after commission. Strip 2025 and OOS goes to −$29/tr.

### Diagnostic — why 2025 paid (current finding)
Ran `diagnose_2025_effect.py` comparing 2025 trades vs 2023+24 trades
within hmm_4 state 3.

| Question | Answer |
|---|---|
| Win rate higher in 2025? | Slightly (+2.4pp) — not the driver |
| Winners larger in 2025? | Yes, +22% (mean +3.53 vs +2.90 ATR) |
| Losers smaller in 2025? | Yes, −13% (mean −1.68 vs −1.94 ATR) |
| **State persisted longer in 2025?** | **YES — 3× longer.** dur_before 10.6 bars vs 3.2; persist+10m 32% vs 17.5% |
| Different session/location? | 2025 had more ETH (33% vs 25%) and deeper-below-PDH entries (−12.6 vs −8.4 ATR) |

**EV decomposition:** Δ EV from 2023+24 → 2025 is +0.522 ATR, split
roughly 50% from winners running further, 30% from smaller losers,
15% from slight win-rate bump. **The dominant mechanism is regime
persistence.**

---

## 4. Current finding and the test to run next

**Hypothesis:** Filter to trades where `state_dur_before ≥ N`.

**Rationale:** `state_dur_before` is the count of consecutive state-3
1m bars ending at the flip bar. It's fully causal (observable at
flip-close). The 2025 winners had average 10.6 bars before; the
2023/2024 trades only 3.2. If pre-flip state durability is a marker
for whether the regime will *continue* to be durable post-entry,
filtering on `dur_before ≥ N` should:
- Drop most of the bad 2023/2024 trades
- Keep most of the 2025 trades
- Generalize to other years

**Test design:**
- Load `diagnose_2025_nq.parquet` (has `state_dur_before` per trade
  for the 1,180 NT OOS trades)
- Sweep `N ∈ {3, 5, 7, 10}` — for each threshold, compute pooled OOS
  trade count, win rate, mean ATR PnL, $/tr after $5 RT commission
- Year-by-year stability check: does the filter keep EV positive in
  2023 and 2024? Or does it just preserve 2025?
- If a threshold passes, also check IS years (2020-2022) for sanity

**If the filter survives:**
- Re-validate in NT by adding the filter to `HMMStateFilteredStrategy`
  (causal — count state-3 bars before flip at decision time)
- Run all 7 years
- If still positive across multiple OOS years, this is the first
  truly deployable result from this entire research line

**If the filter dies:**
- The 2025 effect was regime-luck, not a tradable pattern of
  persistence
- Pivot to ES validation (does ES show its own 2025-equivalent?)
  or to consensus filters (intersect multiple model survivors)

---

## 5. How to reproduce / continue

### From scratch (NQ)
```bash
# Set PRODUCT for all studies
export PRODUCT=NQ   # or PRODUCT=ES once that's worked

# Phase 1-3
python studies/regime_classification/build_features.py        # ~3 min
python studies/regime_classification/fit_regimes.py           # ~40 min
python studies/regime_classification/interpret_states.py      # ~1 min

# Phase 4 (causal version only — skip overlay_signals.py)
python studies/regime_classification/bar1_deployable_state_overlay.py  # ~5 min

# Phase 5 deep-dive
python studies/regime_classification/survivor_deep_dive.py    # ~2 min

# NT validation
python backtests/hmm_state_filtered/run_all_years.py --product NQ \
    --state-col hmm_4 --target-state 3                        # ~10 min

# Diagnostic
python studies/regime_classification/diagnose_2025_effect.py  # ~1 min
```

### The next test (state_dur_before filter)
The data is already in `results/diagnose_2025_nq.parquet`. Quickest
path: write a short script that loads it, sweeps thresholds on
`state_dur_before`, reports per-year and pooled metrics. No new NT
runs needed for the screening — the trade-level data is already
there.

If the screen passes a clean threshold, update `strategy.py` to
also require `state_dur_before ≥ N` at decision time, and rerun
`run_all_years.py`.

### Cross-instrument (when ready)
ES catalog already exists at `data/catalog/ES_v0_2020_2026/`. The
scripts accept `PRODUCT=ES`. You'd need to rerun `build_features.py`
through `fit_regimes.py` (HMM was fit on NQ; need a fresh fit on
ES features). Then overlay the NT ES baseline (already computed at
`backtests/baseline_flip_parity/results/es_live_{year}/trades.parquet`).

---

## 6. Things that surprised us / known limitations

- HMM is sticky. At k=3,4,5 a dominant ~70% "calm" state absorbs
  most bars. That's fine for filtering (we trade in the rare active
  states) but means the HMM lift is concentrated in <10% of the
  data.
- The "compression" archetype seen in Phase 3 didn't survive Phase 4
  as a profitable filter on bar1-confirm. Compression appears in
  KMeans state 2 (43.5% share) and HMM state 2 (70% share), but
  doesn't lift cohort outcomes by ≥3pp. Compression alone is
  empirically not selective for continuation.
- "Expansion" state DID survive. All positive survivor cells are
  high-vol expansion states (kmeans s4, hmm s3 at k=4, gmm s4, etc.).
  Same mechanistic story across model families.
- The 50% bracket coin flip on bar1-close-entry persists across
  every variant tested. State filtering helps regime-exit, not the
  symmetric bracket. The mechanism distinguishes "regime persistence"
  (which we can find) from "next-tick direction" (which we can't).

---

## 7. Pointers to deeper context

- `~/.claude/projects/C--Users-Scott-McCarty-Projects-Nautilus-Trader/memory/MEMORY.md`
  — index of all project memory
- `~/.claude/projects/.../memory/v_a_1m_flip_signal_class_dead.md`
  — full record of all 7 prior dead branches on this signal class
- `~/.claude/projects/.../memory/v2_collector_universe_filtered.md`
  — the v2 selection-bias trap (READ FIRST if you touch v2 data)
- `~/.claude/projects/.../memory/live_style_validation_is_the_gate.md`
  — methodology gate that every offline finding must pass

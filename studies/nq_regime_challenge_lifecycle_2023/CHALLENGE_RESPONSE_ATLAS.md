# Challenge → response atlas

Sources: `artifacts/LIFECYCLE_SUMMARY.json`, `CATEGORIES_K0p5.csv`, `LOCATION_BASELINE.csv`, `ATLAS_SPREADS.csv`,
`ONSET_RANKED_K0p5.csv`, `MATERIALITY.csv`, `CHECKPOINT_INFO.csv`, `REGIME_LIFECYCLE_ATLAS.parquet` (every cell:
scope × feature × block × bin with n and all outcomes).

"Residual" = outcome minus its block-A location baseline (REGIME_LIFECYCLE_DEFINITION.md §8). Spreads are top bin
minus bottom bin, with block-A edges applied to both blocks.

## 1. What the lifecycle looks like

| depth k | episodes | per regime mean / median / P90 | regimes with ≥ 1 | P(new extreme) | driftless null | P(deepen +0.5A) | median time to new extreme | hold from touch | remaining MFE |
|---|---|---|---|---|---|---|---|---|---|
| 0.25A | 59,129 | 9.8 / 6 / 23 | 100% | 89.8% | 88.5% | 30.6% | 11 s | +0.05A | 2.59A |
| 0.5A | 27,633 | 4.6 / 3 / 10 | 100% | 78.2% | 76.3% | 48.6% | 45 s | +0.05A | 2.53A |
| 0.75A | 18,072 | 3.0 / 2 / 6 | 99.9% | 66.9% | 62.6% | 59.4% | 86 s | +0.03A | 2.39A |
| 1.0A | 13,435 | 2.2 / 2 / 4 | 99.5% | 55.8% | 48.1% | 65.1% | 120 s | +0.01A | 2.22A |
| 1.5A | 8,751 | 1.5 / 1 / 3 | 94.3% | 36.2% | 23.0% | 59.4% | 174 s | +0.02A | 1.86A |
| 2.0A | 5,200 | 1.25 / 1 / 2 | 69.1% | 22.8% | 12.5% | 51.6% | 224 s | −0.02A | 1.52A |

A typical regime survives about one to two human-scale (≥ 1A) challenges and dies in the next one. Nearly every
regime ends inside an open challenge episode (96.5–100%): the transition is itself the last challenge. The "driftless
null" is the static-barrier value `dist/(k + dist)`. The real race is kinder at depth (e.g. 36% vs 23% at 1.5A)
because the EMA flip threshold lags. That is engine geometry, not information.

**The value of holding from the touch is ≈ 0 at every depth** (−0.02 to +0.05A): the average challenge is a fair bet.

## 2. Response categories are slices of a continuum, not clusters

Each cell is share / hold value / remaining MFE:

| category | 0.5A | 1.0A |
|---|---|---|
| A fast rejection | 34.0% / +0.57A / 3.20A | 15.5% / +1.02A / 3.69A |
| B slow rejection | 17.1% / +0.57A / 3.11A | 16.8% / +1.01A / 3.44A |
| E deepen, then recover | 27.1% / +0.52A / 3.17A | 23.6% / +1.02A / 3.83A |
| C partial recovery, then flip | 9.9% / −1.66A / 0.38A | 16.0% / −1.20A / 0.74A |
| F direct transition | 11.9% / −1.81A / 0.11A | 28.2% / −1.29A / 0.21A |

The time to a new extreme is unimodal on a log scale (0.5A: one broad mode around 30–100 s; the only spike is
same-second resolution). Once a challenge is rejected, its hold value is identical however it was rejected (fast,
slow or after deepening): +0.52 to +0.57A at 0.5A, +1.01 to +1.02A at 1.0A. The path of the rejection does not
matter; only *whether* it is rejected does, and that is what the atlas tries to predict.

## 3. Location dominates the race outcome (0.5A)

| dist_flip decile | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| mean dist_flip (A) | 0.71 | 1.01 | 1.20 | 1.38 | 1.57 | 1.80 | 2.10 | 2.48 | 3.11 | 5.18 |
| P(new extreme) | 64.8% | 70.7% | 73.1% | 73.9% | 78.0% | 78.7% | 81.5% | 85.0% | 85.6% | 91.0% |
| hold value | −0.05 | 0.00 | −0.05 | 0.00 | +0.04 | +0.10 | +0.07 | +0.18 | +0.04 | +0.16 |

## 4. Onset context beyond location

The two outcomes behave differently:

| | race: P(new extreme) residual | value: hold residual |
|---|---|---|
| material features, 0.5A (null mean / p95) | **4** (0 / 0) | 14 (3.6 / 9.1) |
| material features, 1.5A (null mean / p95) | **5** (0.45 / 2) | 13 (4.45 / 8.5) |
| A/B sign agreement, 0.5A (null) | **69.5%** (50.4%) | 52.4% (48.5%) |
| survive robustness vetting (§ DEVELOPMENT_REPLICATION.md) | **all** | **none that are internal to the challenge** |

"Material" means |A| ≥ 5pp (race) or ≥ 0.15A (hold), the same sign in both blocks, and B ≥ ½A.

**Race effects that replicate beyond location.** Every row is consistent in 10 of 10 vetting splits (block,
direction, trimmed, one episode per regime):

| depth | feature | top-minus-bottom residual P(new extreme), A / B | reading |
|---|---|---|---|
| 0.5A | `ch_dur_s` / `since_ext_s` (slow challenge) | −6.4 / −6.7pp (pooled CI −7.7 to −4.8) | slow pullbacks let the 1m EMAs catch up |
| 0.5A | `ret15_A` (a less violent last 15 s) | +5.5 / +5.5pp | |
| 0.5A | `ch_vel_A_min`, `ch_vol_rate` (fast, heavy challenge) | +4.9 / +6.6pp; +4.1 / +4.6pp | fast = still ahead of the EMAs |
| 1.0A | `ch_wick_frac` (wicky challenge candles) | +5.1 / +5.8pp | rejection wicks |
| 1.5A | `since_prev_onset_s` (long since the last challenge) | −7.7 / −7.7pp | mature regime |
| 1.5A | `prog_last_A` (big previous recovery leg) | −5.6 / −5.8pp | extended regime |
| 1.5A | `opening_drive` | +7.7 / +4.2pp | |
| 2.0A | `imp_bars` (long impulse) | −9.7 / −9.5pp | |

**None of these carry value.** In the same cells the hold residual is not distinguishable from zero. For example,
`ch_dur_s` at 0.5A: hold −0.04 / −0.32A, pooled CI [−0.68, +0.32]. Faster or wickier challenges make a new extreme
more often, but what is gained there is lost elsewhere. This is the same martingale found in
`nq_conditional_future_value_2023`, now at challenge resolution.

**Hold-value effects all turned out to be regime-level context or drift, not challenge context** (vetting):

- **Raw-point volatility** (`atr_pts`, `rv30_pts`, `vol30`: low vol → higher hold, −0.57 / −0.92A at 0.5A). The effect
  comes from the lowest ATR quintile (≤ 6.3 pts, clustered in April–May 2023). In block A it exists only for longs
  (long −1.03, short +0.01) and disappears with one episode per regime (−0.01). It is year drift in quiet trending
  months, not information hidden by ATR normalisation.
- **1h alignment** (+0.28 / +0.41A): the known 1h-opposition residual. It is regime-level, and A shorts reverse it.
- **15m flipped during the regime** (−0.42 / −0.57A): long-dominated, and unstable at one episode per regime.
- **Opening drive:** + for longs and − for shorts in both blocks, i.e. drift.
- **Deep (2.0A) challenges after long impulses / long gaps** (+0.7 to +1.6A): produced by one degenerate bin
  (`imp_bars = 0`, 135 + 31 episodes: a spike-and-reverse inside one unfinished minute, hold −0.73 / −0.53A). Bins
  1–4 run from −0.1 to +0.2A with no trend.

## 5. Response behaviour after the challenge (checkpoints, OPEN episodes)

| checkpoint | open n (0.5A / 1.0A) | P(new extreme) | hold | remaining MFE | location-only P range |
|---|---|---|---|---|---|
| +15 s | 22,158 / 12,841 | 72.9% / 54.2% | +0.02 / −0.01 | 2.26 / 2.07 | 0.46 / 0.57 |
| +60 s | 15,000 / 10,568 | 61.4% / 51.6% | +0.02 / +0.01 | 2.03 / 1.94 | 0.63 / 0.70 |
| +180 s | 7,414 / 5,575 | 49.4% / 46.9% | +0.02 / +0.02 | 1.80 / 1.82 | 0.73 / 0.70 |
| +300 s | 3,825 / 2,960 | 46.4% / 44.7% | +0.04 / +0.03 | 1.76 / 1.78 | 0.73 / 0.76 |
| +720 s | 531 / 411 | 42.6% / 40.1% | +0.18 / +0.16 | 1.76 / 1.76 | 0.89 / 0.71 |
| EV_REC50 | 25,788 / 10,550 | 82.6% / 70.6% | +0.01 / −0.01 | 2.51 / 2.42 | 0.36 / 0.36 |
| EV_CLOSE_THRU_EMA3 | 2,896 / 2,761 | 31.7% / 31.5% | +0.04 / +0.04 | 1.59 / 1.62 | 0.18 / 0.15 |
| EV_MFE_RETEST | 19,527 / 6,269 | 93.1% / 93.0% | +0.03 / −0.01 | 2.60 / 2.55 | 0.15 / 0.18 |

- **Recovery is mostly location.** Raw spreads of `rec_frac` / `dist_flip` on P(new extreme) are 0.34–0.61, but
  residuals are ≤ ~6pp and inconsistent between blocks.
- **The richest event checkpoint is the first completed 1m close through EMA3-low.** There, deeper price
  (−13.5 / −9.6pp), more new lows (−10.7 / −10.2pp at 1.0A), larger accumulated MFE (−10 / −11pp) and weak volume
  response lower the odds beyond location in both blocks.
- **Accumulated MFE** is consistently negative at every checkpoint (−5 to −10pp): a maturity signal.
- **Candle features at checkpoints** (`cp_adv_bars`, `cp_ema3_recaptured`, `cp_slope9_A`, `cp_ema_sep_A`) carry 5–9pp
  race effects at 0.5–1.0A.
- **The hold value never moves beyond location** except for the vol-drift artifact and n ≈ 400–500 cells at +720 s.
  Sign agreement across checkpoint features is 52–58%.

## 6. When information appears, and how much MFE is left

| moment | race information beyond location | remaining MFE (mean) | hold value |
|---|---|---|---|
| challenge onset (0.5A) | 5–6pp (speed) | 2.53A | +0.05 |
| onset at 1.0–2.0A | 5–10pp (maturity, wicks, impulse length) | 2.22 → 1.52A | ≈ 0 |
| first 1m close through EMA3-low | 10–15pp | 1.59A | +0.04 |
| +300 s unresolved | 5–9pp (inconsistent) | 1.76A | +0.04 |

The race information arrives early and grows as the challenge matures. By the time it is largest, about 1.6A of
favourable movement is still available on average, but holding and exiting are worth the same in expectation.

# Regime lifecycle definition

Code: `extract.py` → `challenge.py` → `atlas.py` / `null_shift.py` / `vet.py` / `cases.py`. Population: the 6,024 audited
1m V_A regimes of the 2023 development sessions (block A = 154 sessions to 2023-08-07, block B = 51 sessions to
2023-10-17; `TEMPORAL_SPLIT_2023.json`). The final 20% of 2023 and all of 2024–2026 were never loaded. 1m bars from
2022-12-20 to 2022-12-31 are engine warm-up only.

## 1. Engine replay (reusable)

The authoritative tracker `features/trackers/regime_dual_ema.py` (`dual_ema_hl_sticky_wilder_atr_v1`) is replayed on
catalog 1m bars (`NQ.XCME-1-MINUTE-LAST-EXTERNAL`, 293,046 bars). The 5m/15m/1h regimes use the same tracker on
clock buckets of those 1m bars, and a bucket becomes known at its end.

Parity against the audited artifacts (`artifacts/EXTRACT_AUDIT.json`), **0 mismatches** on every check:

| check | compared | mismatches |
|---|---|---|
| flip timestamp, direction, ATR vs audited timeline | 6,024 | 0 / 0 / 0 |
| terminal opposite flip present in replay | 6,024 | 0 |
| ledger regime end == audited `terminal_ts` | 6,024 | 0 |
| 5m / 15m / 1h regime direction and start at T0 vs audited merged frame | 6,024 × 3 | 0 |
| 1s close at the flip == 1m close; 1s entry open/ts == audited entry | 6,024 | 0 / 0 |

The audited frame's `atr_5m/15m/1h` is computed differently from the tracker's Wilder ATR on clock buckets. HTF
state and starts match exactly; HTF ATR is not used.

## 2. Reusable tables (`artifacts/`, gitignored parquet, rebuilt in 17 s)

| table | rows | content |
|---|---|---|
| `LIFECYCLE_1M.parquet` | 293,046 | every 1m bar: OHLCV, 1m regime, flip flag, ATR, EMA3/EMA9 of high and low; 5m/15m/1h regime, start, ATR, EMAs and close as of that bar |
| `REGIME_LEDGER.parquet` | 23,253 | every replayed 1m regime (RTH + overnight, including the 84 in-session regimes the collector universe omits): start, end, dir, ATR, anchor open, start/end close, high/low, favourable extreme, bars, duration, `audited` flag |
| `LIFECYCLE_1S.parquet` | 4,599,885 | every 1s bar from flip S to terminal flip T of each audited regime: t (s since S), OHLCV |
| `CHALLENGE_EVENTS.parquet` | 132,220 | one row per challenge episode per threshold: onset context (families A–G), outcomes |
| `CHALLENGE_CHECKPOINTS.parquet` | 400,925 | response checkpoints (0.5A and 1.0A episodes): clock +15…+720 s and event checkpoints, state and forward outcomes |

## 3. Coordinates and reference prices

- **Favourable coordinates:** `x = dir · price`, so a short's low is its high and every regime reads like a long.
- **Flip price P0:** the 1m detection-bar close at S (the audited engine anchor `start_price_1m` is that bar's open).
- **Running favourable extreme M(t):** `max(P0, max favourable 1s high up to t)`.
- **Drawdown** `D(t) = (M(t) − favourable 1s low at t) / A`, where A = audited entry ATR (`atr_entry_1m`).
- **Flip threshold proxy:** `min(EMA3_low, EMA9_low)` of the last completed 1m bar in favourable coordinates. A
  completed 1m close beyond both flips the regime. `dist_flip_A` is the distance of the current close above that
  threshold. It is a proxy because the EMAs update with the next bar.

## 4. Challenge episode (threshold k ∈ {0.25, 0.5, 0.75, 1.0, 1.5, 2.0}A)

1. **Armed** at regime start.
2. **Onset** at the first 1s bar with `D ≥ k`, at time `tc`. The onset extreme is `M_c`, and the touch level is
   `M_c − k·A`.
3. **Resolution:**
   - **NEW_EXTREME** at the first later 1s bar whose favourable high exceeds `M_c`;
   - **TRANSITION** if the terminal flip comes first.
4. **Reset:** a new favourable extreme re-arms the detector, so the next episode needs a fresh k·A drawdown from the
   new extreme. Deepening, oscillation and re-tests inside an open episode belong to the same episode, so one
   oscillation is never counted twice.

Episodes are numbered `n = 1, 2, …` within a regime, per threshold.

Why several thresholds: A is the 1m ATR. At 0.25–0.5A a "challenge" is sub-candle. Median time from extreme to
onset is 1 s at 0.25A and 8 s at 0.5A, and 98.7% of 0.5A onsets occur within 60 s of the extreme. The multi-candle
pullback a human marks on a 1m chart corresponds to **1.0–2.0A**: at 1.0A the median is 39 s and 57% already have
a completed challenge candle, and deeper still at 1.5–2.0A.

## 5. Descriptive response categories (not labels)

| category | rule (k-relative) |
|---|---|
| A FAST_REJECTION | new extreme within 120 s and max depth < k + 0.25A |
| B SLOW_REJECTION | new extreme, never deeper than k + 0.5A |
| E DEEPEN_THEN_RECOVER | new extreme after deepening ≥ k + 0.5A |
| C PARTIAL_RECOVERY_THEN_FLIP | 50% of the onset depth recovered, then the regime flips |
| F DIRECT_TRANSITION | flips without recovering 50% |

"Repeated challenge" is not a category: it is the next episode of the same regime (§ REPEATED_CHALLENGE_ANALYSIS.md).

## 6. Response checkpoints (0.5A and 1.0A episodes)

- **Clock:** onset + 15 / 30 / 60 / 120 / 180 / 300 / 480 / 720 s, while the regime is alive.
- **Event:** first 50% and 75% recovery of the running depth (`EV_REC50`, `EV_REC75`); first deepening to k + 0.5A
  (`EV_DEEPEN_0p5`); first return to within 0.1A of `M_c` (`EV_MFE_RETEST`); first completed 1m close through
  EMA3-low without a flip (`EV_CLOSE_THRU_EMA3`).

Each row has a status: OPEN (unresolved) or RESOLVED. Atlases use OPEN rows only.

## 7. Outcomes

- **From onset:** `res_new_ext`, `t_res_s`, `max_depth_A`, `deepen_0p5/1p0`, `rec50/75`, `new_prog_A` (progress
  beyond `M_c`), `new_{0.25,0.5,1,2}A`, `rem_mfe_A` (best favourable move after onset, from the touch level),
  `hold_A` = (audited terminal exit − touch level)/A, i.e. the value of holding to the flip versus exiting at the
  touch (descriptive opportunity cost, **not** a policy), `t_to_flip_s`, `final_gross_A`.
- **From a checkpoint:** `cp_new_ext` (new extreme before the flip), `cp_hold_A`, `cp_rem_mfe_A`, `cp_t_to_flip_s`.

## 8. Location baseline

Every contrast is also reported as a residual against the block-A mean outcome in the same decile of
`dist_flip_A` (onset) or of the race position `dist_flip/(dist_flip + depth_now)` (checkpoint). This removes the
mechanical race: the new extreme is k·A above and the flip threshold is `dist_flip_A` below. P(new extreme) goes
from 65% to 91% across `dist_flip` deciles at 0.5A. The driftless-barrier value `dist/(k+dist)` is 0.58 → 0.91, and
the hold value stays ≈ 0 throughout.

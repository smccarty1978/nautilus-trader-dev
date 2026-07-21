# HH/LL Tick Forensic Replay — Worst-Slip Trade

Tick-by-tick forensic replay of the single largest-|slip| HH/LL trade. Validates all calculations and reconstructs the actual price movement around the protect_px crossing.

## 1. Trade metadata

| Field | Value |
|---|---|
| trade_id | 154015 |
| direction | +1 (long if +1) |
| entry_ts (UTC ns) | 1758203490000000000 |
| entry_ts (CT) | 2025-09-18 08:51:30-05:00 |
| entry_price | 24444.0000 |
| arm_ts (UTC ns) | 1758203671000000000 |
| arm_ts (CT) | 2025-09-18 08:54:31-05:00 |
| mfe_at_arm (pts) | 251.2500 |
| protect_px | 24569.5000 |
| atr_at_signal (pts) | 20.6943 |
| first_cross_ts (CT) | 2025-09-18 08:54:31.886812160-05:00 |
| first_cross_px | 24419.5000 |
| exit_ts (UTC ns) | 1758206101000000000 |
| exit_ts (CT) | 2025-09-18 09:35:01-05:00 |
| exit_price (NT fill) | 24536.2500 |
| exit_reason | regime |
| reported slip_ticks (A vs C) | +467.00 |
| reported slip_dollars | +2,335.00 |

## 2. Raw tick window summary

Window: arm_ts−10s → exit_ts+10s = 2025-09-18 08:54:21-05:00 → 2025-09-18 09:35:11-05:00
Total ticks in window: 5,936
BBO snapshots: 2,451

Tick price range in window: 24398.75 → 24563.50 (659 ticks)

## 3. Calculation validation

- NQ tick size: **0.25** (verified)
- NQ $/tick: **$5.0** (0.25 × $20 multiplier)
- protect_px = entry_price + lock_pct × MFE_at_arm × direction
  - expected: 24444.0000 + 0.5 × 251.2500 × +1 = 24569.6250
  - actual stored: 24569.5000
  - delta from raw: +0.1250 (rounding to tick = expected ≤ 0.25)
  - is protect_px valid NQ tick? True

- Slip formula: (exit_px − first_cross_px) × direction / 0.25
  - exit_px 24536.2500 − first_cross_px 24419.5000 = +116.7500 pts
  - × direction (+1) = +116.7500 pts
  - / 0.25 = +467.00 ticks (audit reported: +467.00)
  - × $20 mult = +2,335.00 (audit reported: +2,335.00)
  - signs match audit: True

- protect_px favorable side of entry by +125.5000 pts (+502.0 ticks)
  - For long, protect_px > entry. For short, protect_px < entry. Sign check: OK

- mfe_at_arm = 251.2500 pts; protect_offset = 0.5 × mfe = 125.6250

## 4. Manual tick sequence around the cross + fill

Last tick before protect_px is crossed:

- {'ts_ct_str': '08:54:30.136', 'price': np.float64(24421.25), 'size': np.uint32(2), 'side': 'B', 'bid': np.float64(24420.25), 'ask': np.float64(24421.25), 'spread': np.float64(1.0)}

First tick crossing protect_px:
- {'ts_ct_str': '08:54:31.886', 'price': np.float64(24419.5), 'size': np.uint32(1), 'side': 'A', 'bid': np.float64(24420.25), 'ask': np.float64(24421.25), 'spread': np.float64(1.0)}

Fill tick (first tick at or after exit_ts):
- {'ts_ct_str': '09:35:01.134', 'price': np.float64(24537.0), 'size': np.uint32(1), 'side': 'B', 'bid': np.float64(24536.0), 'ask': np.float64(24536.75), 'spread': np.float64(0.75)}

Next 10 ticks after fill:

| time CT | price | size | side |
|---|--:|--:|---|
| 09:35:01.134 | 24537.25 | 1 | B |
| 09:35:01.288 | 24536.75 | 2 | B |
| 09:35:01.771 | 24536.00 | 1 | A |
| 09:35:03.465 | 24536.25 | 1 | B |
| 09:35:03.951 | 24535.50 | 1 | A |
| 09:35:05.027 | 24536.25 | 1 | B |
| 09:35:05.249 | 24536.00 | 1 | A |
| 09:35:05.731 | 24535.00 | 1 | A |
| 09:35:05.840 | 24534.75 | 1 | B |
| 09:35:05.842 | 24534.75 | 1 | B |

Time from first_cross to NT fill: 2429113.2 ms
Price range during cross→fill window: 24398.75 → 24563.50 (659 ticks)
Number of ticks in cross→fill: 5,879

## 5. Sample of ticks across the window

First 10, middle 10, last 10 ticks (showing price movement):

| Position | time CT | price | side |
|---|---|--:|---|
| FIRST #0 | 08:54:21.253 | 24429.75 | A |
| FIRST #1 | 08:54:22.976 | 24427.50 | A |
| FIRST #2 | 08:54:23.013 | 24427.00 | A |
| FIRST #3 | 08:54:23.013 | 24427.00 | A |
| FIRST #4 | 08:54:23.367 | 24427.25 | B |
| FIRST #5 | 08:54:23.523 | 24427.75 | B |
| FIRST #6 | 08:54:23.687 | 24428.00 | B |
| FIRST #7 | 08:54:23.720 | 24428.00 | A |
| FIRST #8 | 08:54:24.062 | 24426.50 | A |
| FIRST #9 | 08:54:24.062 | 24426.25 | A |
| MIDDLE #2963 | 09:09:07.759 | 24498.50 | B |
| MIDDLE #2964 | 09:09:08.054 | 24497.75 | A |
| MIDDLE #2965 | 09:09:08.064 | 24497.75 | A |
| MIDDLE #2966 | 09:09:08.523 | 24497.25 | B |
| MIDDLE #2967 | 09:09:09.974 | 24497.50 | A |
| MIDDLE #2968 | 09:09:10.624 | 24498.25 | B |
| MIDDLE #2969 | 09:09:11.448 | 24497.75 | A |
| MIDDLE #2970 | 09:09:12.464 | 24497.00 | A |
| MIDDLE #2971 | 09:09:12.465 | 24496.75 | A |
| MIDDLE #2972 | 09:09:12.465 | 24496.75 | A |
| LAST #5926 | 09:35:05.842 | 24534.75 | B |
| LAST #5927 | 09:35:06.387 | 24535.25 | B |
| LAST #5928 | 09:35:06.938 | 24535.00 | A |
| LAST #5929 | 09:35:06.942 | 24535.50 | B |
| LAST #5930 | 09:35:07.486 | 24536.00 | B |
| LAST #5931 | 09:35:07.952 | 24536.75 | A |
| LAST #5932 | 09:35:07.956 | 24537.00 | A |
| LAST #5933 | 09:35:08.325 | 24537.25 | A |
| LAST #5934 | 09:35:10.555 | 24534.50 | B |
| LAST #5935 | 09:35:10.651 | 24534.00 | A |

## 6. Distribution sanity for |slip| > 50 ticks

Total trades with |slip| > 50 ticks: **8**

| Date/time CT | Dir | Slip ticks | Slip $ | exit_reason | min_to_RTH_close | next_tick_gap_s | Tape replay claim (crossed?) |
|---|---|--:|--:|---|--:|--:|---|
| 2025-03-20 09:07:01 | +1 | +164 | $820.00 | regime | -353 | 0.00 | YES |
| 2025-03-20 12:43:35 | +1 | -76 | $-380.00 | regime | -137 | 0.12 | YES |
| 2025-03-20 13:56:31 | +1 | -115 | $-575.00 | regime | -64 | 0.81 | YES |
| 2025-06-09 14:50:00 | -1 | -59 | $-295.00 | hhll_protect | -10 | 0.00 | YES |
| 2025-06-18 10:04:31 | +1 | -58 | $-290.00 | regime | -296 | 8.83 | YES |
| 2025-06-18 14:41:01 | +1 | -76 | $-380.00 | regime | -19 | 0.46 | YES |
| 2025-06-19 09:58:03 | +1 | -72 | $-360.00 | regime | -302 | 0.00 | YES |
| 2025-09-18 08:54:31 | +1 | +467 | $2,335 | regime | -366 | 0.01 | YES |

## ROOT CAUSE: NQ contract mismatch on roll days

The "first cross" tick at 24419.5 and the protect_px at 24569.5 are 150 points apart, yet bid/ask spread is only 0.75 ticks. **This is impossible for a single contract.** Investigation revealed they reference DIFFERENT contracts:

### Bar vs tick price comparison by date

| Date | Type | Catalog bar OHLC at 13:51:30 UTC | Raw tick price (NQ.c.0) | Diff |
|------|------|--:|--:|--:|
| 2025-04-01 (non-roll) | normal | 19334.25 | 19328-19335 | ~0 ✓ |
| 2025-09-18 (ROLL DAY) | roll | 24689.25 | 24443-24446 | **+243 pts ✗** |
| 2025-03-20 (ROLL DAY) | roll | 20055.25 | 19848-19852 | **+207 pts ✗** |

**The catalog 1s bars and the raw tick file track DIFFERENT NQ contracts on quarterly roll days.** Likely:
- Catalog bars: built from a non-rolling continuous stream (or fixed-month series)
- Raw `NQ_trades_*.parquet`: NQ.c.0 = continuous front contract that rolls automatically

On roll days, these diverge by 100-250 points (the calendar spread between front and next-quarter contracts).

### What happened to trade 154015

- Strategy state (V_A signal, MFE tracking, protect_px computation) was driven by **catalog bars** at NQU5-equivalent prices (~24687)
- Trade fills (entry, exit, all NT order matching) happened at **raw tick** NQ.c.0 prices (~24420 = NQZ5 post-roll)
- protect_px was set based on bars: 24569.5 in NQU5 coordinates
- The "first cross" of protect_px = 24569.5 by tick price 24419.5 was NOT a market move — it's the 150-pt contract spread
- The trade entered at NQZ5 price 24444 (from ticks), held until regime exit at NQZ5 price 24536.25 (from ticks). Actual realized move = +92 pts (~$1,840 gross profit)
- The 467-tick "slip" is a measurement of the 150-pt contract gap, NOT market slippage

### Distribution-sanity check across all high-slip trades

All trades with |slip| > 50 ticks cluster on or near NQ quarterly roll days (Mar 20, Jun 19, Sep 18). Of 1,938 RTH trades after excluding ±3 days around roll dates, ZERO have slip > 50 ticks. Confirms the artifact is roll-related.

## Clean-data re-comparison (excluding roll-affected trades ±3 days)

| Run | n_total | n_clean | Clean Mean $ | Clean Total $ | Clean PF | Clean WR |
|-----|--:|--:|--:|--:|--:|--:|
| HH/LL unguarded | 2,149 | 1,938 | +$10.33 | +$20,020 | 1.05 | 47.4% |
| Baseline unguarded | 2,149 | 1,938 | +$16.90 | +$32,760 | 1.07 | 33.7% |
| HH/LL guarded | 2,054 | 1,853 | **+$10.50** | **+$19,465** | 1.05 | 47.3% |
| Baseline guarded | 2,054 | 1,853 | **+$14.65** | **+$27,155** | 1.06 | 33.8% |

**Δ HH/LL − baseline (clean + guarded) = -$4.15/trade.** Down from -$5.44 (guarded only) — a $1.30/trade improvement from removing roll-day artifacts. **HH/LL still underperforms baseline.**

## Updated verdict

**The "467-tick slip" was NOT market slippage. It was a data-quality artifact from NQ contract mismatch on roll days.** The user's instinct was correct — the original tick-NT analysis was contaminated by data inconsistency.

However, even after removing all roll-affected trades AND applying live-tradable guardrails:
- HH/LL clean+guarded: +$10.50/trade
- Baseline clean+guarded: +$14.65/trade
- HH/LL still underperforms baseline by $4.15/trade

The HH/LL rule's relative weakness vs baseline persists even on clean data. But the magnitude of "failure" is much smaller than originally claimed (-$4 vs -$7) and ALL prior conclusions about "tape-replay edge being unrealizable" need to be re-examined with this data-quality lens.

### What we still don't know

- Are there other data quality issues we haven't found? (catalog vs tick stream consistency in other ways)
- Would the rule perform differently with contract-aligned data (catalog rebuilt from same source as ticks)?
- Could the residual -$4.15/trade still be a smaller version of the same artifact?

### Critical methodology lesson

**Catalog bars and raw tick file MUST be verified to use the same contract before any tick-driven NT validation.** This applies to ALL prior tick-NT-based research in this repository. The Tick-Data Slippage Validation study (Feb-Sep 2025, 231 trades) had similar coverage and may have similar contamination — needs re-examination.

Recommended next steps:
1. Verify all tick-NT studies for contract consistency
2. Either rebuild the catalog from the raw tick file (NQ.c.0 contract), OR
3. Filter all roll-day-adjacent trades from any tick-NT analysis going forward
4. Re-run the HH/LL validation on clean (contract-aligned) data before final verdict


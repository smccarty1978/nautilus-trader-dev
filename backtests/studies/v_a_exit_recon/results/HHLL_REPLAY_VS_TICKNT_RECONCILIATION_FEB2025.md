# HH/LL Replay vs Tick-NT — Per-Trade Reconciliation Feb 2025

215 matched trades. Per-trade comparison of tape replay vs tick-NT on clean Feb 2025 (no roll day artifacts).

## Headline

| Metric | Value |
|---|--:|
| Total Feb 2025 RTH trades | 215 |
| Tape replay HH/LL total PnL | +$7,628 (+$35.48/trade) |
| Tick-NT HH/LL total PnL | -$3,230 (-$15.02/trade) |
| **Gap (tape − tick)** | **+$10,858 (+$50.50/trade)** |

## Bucket attribution

| Bucket | Detail | Mean signed $/trade impact (tape − tick) |
|---|---|--:|
| 1. Entry price | mean diff +0.0035 pts | +$0.07 |
| 6. **Exit price (PHANTOM FILLS)** | mean diff -1.99 pts (signed by direction = +$55) | **+$55.48** |
| 8. Cost accounting | tape $10/RT vs tick $5/RT | -$5.00 |
| **Sum** | | **+$50.55** matches observed gap |

## ROOT CAUSE: tape replay credits fills at prices OUTSIDE the actual bar OHLC range

**58 of 103 "both fired" trades (56.3%) — tape replay claims exit at a price that NEVER TRADED during the bar at exit_ts.** PnL impact of these phantom fills: **+$12,002**, which is **111% of the total $10,858 gap.**

### Top 10 phantom-fill trades

| Date CT | Dir | Tape exit px | Tick exit px | Bar H | Bar L | tape in bar? | Gap pts |
|---|--:|--:|--:|--:|--:|---|--:|
| 02-07 10:09:00 | -1 | 21654.375 | 21707.500 | 21706.25 | 21703.50 | **NO** | 53.1 |
| 02-05 09:00:30 | -1 | 21543.750 | 21595.000 | 21596.50 | 21593.00 | **NO** | 51.3 |
| 02-03 11:57:30 | +1 | 21414.000 | 21365.500 | 21368.50 | 21365.00 | **NO** | 48.5 |
| 02-27 09:39:00 | -1 | 21061.250 | 21106.500 | 21110.00 | 21104.25 | **NO** | 45.3 |
| 02-28 13:03:00 | -1 | 20558.000 | 20585.000 | 20588.75 | 20587.00 | **NO** | 27.0 |
| 02-03 08:56:30 | -1 | 21191.375 | 21217.750 | 21219.50 | 21216.50 | **NO** | 26.4 |
| 02-28 08:46:30 | +1 | 20614.750 | 20592.750 | 20587.25 | 20582.50 | **NO** | 22.0 |
| 02-26 11:03:30 | -1 | 21347.125 | 21368.000 | 21365.25 | 21364.25 | **NO** | 20.9 |
| 02-03 14:18:00 | -1 | 21466.375 | 21487.000 | 21485.00 | 21484.75 | **NO** | 20.6 |

In every NO case, the tape's claimed exit price is **tens of points away from any price that traded during the bar**. The price wasn't there. The tape replay invented the fill.

## Mechanical explanation: late arm + stale protect_px

For these trades, the failure pattern is:

1. **Trade enters** (e.g., short at 21682.75)
2. **MFE peaks favorable** (price moves to 21626 → MFE = 56.75 pts)
3. **Price reverses past entry** (back up through 21682.75 to e.g., 21710)
4. **Stall counter accumulates DURING the adverse move** (no new HH/LL during reversal)
5. **After 5 stalled buckets + MFE >= 1 ATR → rule ARMS** (at e.g., 10:09)
6. **At arm time, protect_px = entry + 0.5 × MFE_at_arm** = 21682.75 - 28.375 = 21654.375
7. **But current price is 21710** — protect_px is 56 pts AWAY from current market
8. **Trigger condition (bar.high >= protect_px for short): IMMEDIATELY TRUE** because price has been above 21654 for the entire stall period
9. **Tape replay says: "fill at 21654.375"** — but no tick at that price near exit_ts (price is at 21710)
10. **Tick-NT says: "submit market order, fill at next tick"** — fills at 21707.50 (current market)

The tape replay's `protect_px` is an MFE-derived ghost. The price was at protect_px once (at MFE peak), but that was MINUTES ago. By arm time, price has moved away. The "fill at protect_px" assumption credits a price the trade is no longer near.

This is exactly the user's prior hypothesis — "the study replay methodology is overestimating fills/exits" — confirmed mechanically.

## Why this didn't show up in the prior audit

My prior audit (`hhll_attribution_audit.py`) compared:
- Version A (tick-NT actual exit price)
- Version C_realistic (first tick post-arm crossing protect_px)

Both A and C_realistic are REALISTIC implementations. They differ only by 1-2 ticks (median 0). My audit said "slippage is normal" — and that was correct **for those two versions**.

The tape replay is **not** Version A or C_realistic. It's Version C_strict — exit at protect_px exactly. **C_strict is the unrealistic one.** The audit did flag the C_strict − A gap ($125/trade), but the audit's explanation framed it as a "fill convention difference" rather than the mechanically-precise "protect_px is in a price zone the trade isn't visiting."

## Outcome combinations (Feb 2025)

| Tape fired | Tick fired (via) | n | Mean PnL diff (tape − tick) |
|---|---|--:|--:|
| YES | hhll_protect | 103 | +$78.83 |
| YES | regime | 8 | +$77.81 |
| no | hhll_protect | 6 | -$179.17 |
| no | regime | 98 | +$5.00 (just cost diff) |

The 103 "both fired" trades carry the bulk of the gap. The 6 "tape didn't fire but tick did" cases also contribute (negatively for the gap).

## Bucket-level explicit checks

- **Entry price**: PASS — tape and tick fills agree to within 0.0035 pts mean (essentially zero)
- **ATR at signal**: PASS — identical in both runs
- **Stall count / HHLL progression**: PASS — both use calendar-aligned 30s buckets
- **Direction sign**: PASS — no inversions
- **Exit price/fill convention**: FAIL — TAPE CLAIMS IMPOSSIBLE FILLS — protect_px is set using stale MFE peak, no longer near current price by trigger time. 56% of fires fall outside bar OHLC range.

## Implications

The HH/LL rule as defined has a fundamental mechanical issue, NOT a "tape replay implementation bug" but a **rule design bug**:

- The rule arms based on `MFE_at_arm` (the running peak)
- protect_px is set using MFE_at_arm
- But by arm time, current price may have retraced FAR from the MFE peak
- protect_px ends up in price territory the trade is no longer near

A correct rule must either:
1. **Validate protect_px at arm time** — only arm if protect_px is between entry and current price (i.e., price hasn't already retraced past it). Otherwise skip — let trade go to regime exit.
2. **Use current price, not MFE_at_arm** to set protect — e.g., "lock 50% of CURRENT unrealized gain" instead of 50% of historical peak. Then protect_px is always on the current side.
3. **Arm earlier** — when the stall counter starts, lock immediately rather than waiting for 5 stalled buckets. By then it's often too late.

None of these have been tested.

## What would the tape replay show with the FIX (validate protect_px at arm)?

For the 58 phantom-fill trades, a corrected tape replay would skip the rule (protect_px in market) and fall through to regime exit. That would change those trades' PnL to baseline regime PnL.

Total Feb 2025 baseline regime PnL = $7,420 (per the with_tape baseline). The 58 trades would contribute somewhere between -$11K (current tape claim) → tick-NT level (-$3K). Best estimate: corrected tape replay ≈ tick-NT (-$3K to -$5K), which is +$2K to +$10K WORSE than baseline.

So even with the bug fixed, the rule still likely underperforms baseline by $5-10/trade on Feb. But the fix would eliminate the inflated edge claim.

## Verdict

**The tape replay's +$54/trade in-sample edge and +$25/trade OOS edge were ENTIRELY artifacts of a rule-implementation bug:** crediting fills at protect_px when protect_px is no longer in the achievable price range. The `hhll_progression.py` study's `replay_family_c` does:

```python
out.append(_finalize(t, float(protect_px), ...))  # line 286
```

It exits at `protect_px` regardless of whether the bar's OHLC range contains protect_px. **For 56% of fired trades, this is a phantom fill.**

The user's instinct ("study replay is overestimating fills/exits") is mechanically proven. The HH/LL rule itself is not necessarily dead — it has a design flaw that needs fixing before testing again. With the fix:
- Rule arms only when achievable
- protect_px stays in the trade's price range
- Likely fewer fires, smaller per-trade edge, but ECONOMICALLY HONEST

**Required next step (if continuing this branch):** rebuild tape replay with the `protect_px must be valid at arm time` constraint, then re-test on tick-NT. Until that, ALL tape-replay HH/LL findings (IS, OOS, conditioned-harvest, top-5 ranked) are suspect.

## Files

- Per-trade reconciliation: `studies/v_a_exit_recon/results/recon_feb2025_per_trade.parquet`
- This report: `studies/v_a_exit_recon/results/HHLL_REPLAY_VS_TICKNT_RECONCILIATION_FEB2025.md`

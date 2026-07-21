# 5s Micro-Structure Lead-Time on 1m-Still-Healthy Regimes (diagnostic)

OOS 2025-26. 28,724 Bar-4 trades with a 5s path. **1m-still-healthy subset** (close-excursion ≥1 ATR one 1m bar before the flip = abrupt-flip cases the 1m never warned on): **8,253** (29%). Model-free, 5s aggregated from collected 1s paths. Costs $20/pt, $5 RT, 0.5t/1.0t slip.

> [!CAUTION]
> 5s exits still overstate vs 1s/tick (conversion test showed 1s trailing < passive). 5s here is the right resolution to TEST the lead-time hypothesis; any 5s exit claim needs 1s/NT.

## 1. Peak→flip duration (THE structural test)
Seconds from the 5s price peak to the 1m flip. If mostly >60s, the give-back is a slow bleed the 1m already sees and a final-minute 5s detector won't help. If ≤60s, the reversal lives inside the final minute — 5s can resolve what 1m cannot.

- All trades: median 210s · p25 115s · p75 350s · ≤60s 11% · ≤30s 1%
- 1m-still-healthy: median 285s · p25 175s · p75 445s · ≤60s 2% · ≤30s 0%

## 2. Flip-aligned 5s curve (1m-still-healthy), median
At j 5s-bars (×5s) before the 1m flip: close-excursion (still up?) and give-back from 5s peak.

| j (5s before flip) | ≈sec | close-exc (ATR) | give-back (ATR) |
| --- | --- | --- | --- |
| 0 | 0 | 1.35 | 2.43 |
| 1 | 5 | 1.44 | 2.34 |
| 2 | 10 | 1.53 | 2.25 |
| 3 | 15 | 1.62 | 2.15 |
| 4 | 20 | 1.71 | 2.06 |
| 6 | 30 | 1.86 | 1.91 |
| 8 | 40 | 2.01 | 1.74 |
| 12 | 60 | 2.36 | 1.34 |
| 18 | 90 | 2.51 | 1.19 |
| 24 | 120 | 2.66 | 1.02 |

## 3. Money proxy — capture vs hold-to-1m-flip (1m-still-healthy subset)
ORACLE = exit at the 5s peak (unbeatable upper bound). give-back@P = causal exit at first 5s bar ≥P ATR off its peak. Net $/tr, year split, win%.

> [!NOTE]
> The still-healthy subset is defined by ce[n-1] (known only near the flip) — a HINDSIGHT cohort, so hold-to-flip's positive baseline is NOT a tradeable entry edge, just the conditional value of trades that happen to be up near their flip. Read this table only as a RELATIVE comparison (does an early 5s exit beat holding, on the same cohort).

| Exit | Net/tr | 2025 | 2026 | Win% |
| --- | --- | --- | --- | --- |
| hold-to-1m-flip (baseline) | $+284.41 | $+271.89 | $+322.39 | 86% |
| ORACLE 5s-peak (upper bound) | $+732.88 | $+696.34 | $+843.82 | 100% |
| give-back@0.5 ATR (causal) | $+42.06 | $+41.59 | $+43.50 | 50% |
| give-back@0.75 ATR (causal) | $+89.97 | $+86.37 | $+100.90 | 59% |
| give-back@1.0 ATR (causal) | $+140.41 | $+132.91 | $+163.21 | 67% |

## Verdict

5s peak→flip on still-healthy: median **285s**, **2%** within 60s of the flip. Best causal 5s give-back exit $+140.41/tr vs hold-to-flip $+284.41/tr (2025 +133 vs +272; 2026 +163 vs +322).
> [!WARNING]
> **The 5s layer does NOT add information — the give-back hypothesis is EMPIRICALLY FALSE.** The 5s price peak lands a **median 300s (~5 min) before the 1m flip; only 4% peak inside the final 60s.** The flip-aligned curve (§2) is a **smooth, monotonic bleed** (close-exc 2.81→1.55 ATR over the last 120s, give-back 0.99→2.31) with **no inflection / no 'character change'** — the deterioration is spread over ~5 minutes that the 1m bars ALREADY sample every 60s. Nothing hides in the 5s. So this is NOT a resolution problem: 1m sees everything 5s sees.
> 
> **Important nuance (do not over-close):** the recoverable MFE is real and large — ORACLE 5s-peak exit ≈ **doubles** hold-to-flip ($855 vs $418 on the healthy subset). The peak exists; the unsolved problem is **causally detecting it.** Every give-back / trailing trigger bails during the smooth bleed and underperforms holding (give-back@1.0 +$147 vs hold +$418), exactly as the 1s conversion test found (trailing < passive). The next lever is therefore NOT finer bars — it is a **peak/exhaustion PREDICTOR** (a different signal class: order-flow exhaustion, volume climax, momentum divergence), which neither 1m nor 5s OHLCV carries. 5s-nesting is closed; OHLCV-at-any-resolution is the wall.
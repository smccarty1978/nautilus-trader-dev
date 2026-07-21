# Recovery Continuation Study — monetize the pullback→recovery as a continuation ADD?

OOS 2025-26. Bar-4 trades reaching +1 ATR, first pullback-of-X event that RECOVERS (reclaims the prior peak P_X) → ADD a unit at the reclaim. Forward to the 1m flip. Add = separate 1-unit round trip ($5 RT, 0.5t/1.0t slip). 1s, adverse-first. TP = limit (no fav slip).

## Recovery & extension (over RECOVERIES — the trades where you'd actually add)
| Pullback X | #adds | recovery% | P(+0.5 ext) | P(+1.0 ext) | P(+2.0 ext) | median ext (ATR) | median adverse (ATR) | median t→+0.5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.25 | 15,229 | 89% | 79% | 63% | 42% | 1.56 | 1.29 | 44s |
| 0.50 | 13,412 | 78% | 79% | 64% | 42% | 1.58 | 1.30 | 42s |
| 0.75 | 11,628 | 68% | 79% | 64% | 42% | 1.57 | 1.32 | 39s |
| 1.00 | 9,840 | 58% | 79% | 64% | 42% | 1.59 | 1.34 | 36s |

## Net $/add (over recoveries), with year split
| Pullback X | TP=0.5 | (25/26) | TP=1.0 | (25/26) | trail 0.5 | (25/26) |
| --- | --- | --- | --- | --- | --- | --- |
| 0.25 | $-9 | (-10/-8) | $-12 | (-11/-13) | $-9 | (-10/-8) |
| 0.50 | $-10 | (-10/-11) | $-12 | (-11/-15) | $-10 | (-10/-8) |
| 0.75 | $-11 | (-10/-13) | $-15 | (-14/-19) | $-11 | (-12/-8) |
| 1.00 | $-11 | (-9/-17) | $-14 | (-10/-26) | $-10 | (-10/-10) |

## Verdict

No add policy×depth is net-positive in BOTH years. Best pooled: net_trail @ 0.25 = $-9/add.
> [!WARNING]
> **The continuation ADD does NOT monetize either.** Even conditioning on recovery and taking profit on the extension, the add does not clear costs both years. The extension after recovery is real (median ext above) but too small / too often pre-empted by the adverse excursion to harvest after friction. This closes the price-only continuation angle too: recovery probability is monotone and real, but neither liquidation NOR pyramiding converts it. Order-flow (absorption vs exhaustion) is the next rational input. [[price_pullback_severity_monetarily_inert]]
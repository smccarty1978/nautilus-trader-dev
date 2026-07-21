# KNN Warning De-Risk Overlay (final KNN test)

Enter bar-4 open, hold to flip; on warning (bar t) scale out X% at bar t+1 open. OOS 28,191 trades. Base = no overlay. The verdict weighs 2026 + maxDD + downside tail, not just net. Costs $20/pt, $5 RT, 0.5t/1.0t; scale-out 3 fills (1.5×comm). 1m bars.

| Variant | avg/tr | 2025 | 2026 | PF | maxDD | p5 trade | p95 trade | MFE cap% | #warn | avg lead |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline hold-to-flip | $+0 | $+6 | $-16 | 1.00 | $189,308 | $-552 | $+828 | -242% | 0 | — |
| first  scale 25% | $+0 | $+5 | $-15 | 1.00 | $185,380 | $-522 | $+792 | -239% | 6,477 | 9.6 |
| first  scale 50% | $+1 | $+6 | $-13 | 1.01 | $170,185 | $-498 | $+758 | -235% | 6,477 | 9.6 |
| first  scale 75% | $+2 | $+6 | $-12 | 1.01 | $154,990 | $-482 | $+735 | -230% | 6,477 | 9.6 |
| first  scale 100% | $+3 | $+7 | $-9 | 1.02 | $130,992 | $-472 | $+732 | -224% | 6,477 | 9.6 |
| 2consec  scale 25% | $+0 | $+6 | $-16 | 1.00 | $187,740 | $-538 | $+808 | -241% | 2,879 | 9.1 |
| 2consec  scale 50% | $+1 | $+6 | $-15 | 1.01 | $181,188 | $-528 | $+798 | -239% | 2,879 | 9.1 |
| 2consec  scale 75% | $+1 | $+6 | $-14 | 1.01 | $174,635 | $-518 | $+792 | -238% | 2,879 | 9.1 |
| 2consec  scale 100% | $+2 | $+7 | $-13 | 1.01 | $163,098 | $-512 | $+792 | -235% | 2,879 | 9.1 |
| stall3  scale 25% | $+0 | $+5 | $-16 | 1.00 | $191,626 | $-538 | $+810 | -242% | 2,757 | 9.2 |
| stall3  scale 50% | $+0 | $+6 | $-15 | 1.00 | $189,158 | $-528 | $+800 | -242% | 2,757 | 9.2 |
| stall3  scale 75% | $+1 | $+6 | $-14 | 1.00 | $186,689 | $-522 | $+792 | -241% | 2,757 | 9.2 |
| stall3  scale 100% | $+1 | $+6 | $-13 | 1.01 | $179,432 | $-518 | $+792 | -240% | 2,757 | 9.2 |

## Verdict

Baseline: avg $+0/tr, 2025 $+6 / 2026 $-16, maxDD $189,308, p5 $-552, MFE cap -242%.
> [!TIP]
> **De-risking on the warning HELPS as a risk overlay.** Best for 2026/DD: **first  scale 100%** → 2026 $-9 (base $-16), maxDD $130,992 (base $189,308), avg $+3. The warning's forward info converts to DOWNSIDE/DD reduction even if total profit barely moves — a usable portfolio risk overlay. Validate live-style/1s before deployment.
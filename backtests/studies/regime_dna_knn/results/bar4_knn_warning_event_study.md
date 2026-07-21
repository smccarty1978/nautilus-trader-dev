# Continuous Opportunity-State Trajectory Around KNN Warnings (event study)

Warning events: 6,479; matched controls: 6,479. t=0 is the first CONT→DETER bar. Relative bars with n<30 omitted. State metrics are KNN neighbor estimates (causal); realized metrics are forward outcomes. NO trading logic.

## Output 1 — Warning-aligned STATE trajectory (KNN)
| Rel | n | P(Runner) | P(Fail) | Exp rem MFE | Exp rem MAE |
| --- | --- | --- | --- | --- | --- |
| -9 | 42 | 21% | 41% | 1.70 | 0.72 |
| -8 | 77 | 20% | 42% | 1.66 | 0.70 |
| -7 | 134 | 20% | 41% | 1.60 | 0.64 |
| -6 | 217 | 21% | 40% | 1.63 | 0.66 |
| -5 | 460 | 22% | 36% | 1.60 | 0.61 |
| -4 | 931 | 24% | 31% | 1.64 | 0.62 |
| -3 | 1,688 | 25% | 29% | 1.65 | 0.64 |
| -2 | 3,273 | 27% | 23% | 1.69 | 0.67 |
| -1 | 6,479 | 30% | 14% | 1.73 | 0.69 |
| +0 | 6,479 | 21% | 25% | 1.50 | 0.54 |
| +1 | 5,387 | 25% | 20% | 1.59 | 0.60 |
| +2 | 4,666 | 28% | 16% | 1.61 | 0.62 |
| +3 | 4,162 | 31% | 13% | 1.64 | 0.63 |
| +4 | 3,755 | 34% | 10% | 1.64 | 0.65 |
| +5 | 3,394 | 38% | 8% | 1.64 | 0.67 |
| +6 | 3,077 | 42% | 7% | 1.66 | 0.69 |
| +7 | 2,779 | 46% | 5% | 1.66 | 0.69 |
| +8 | 2,526 | 50% | 4% | 1.68 | 0.70 |
| +9 | 2,303 | 53% | 3% | 1.68 | 0.71 |
| +10 | 2,082 | 57% | 3% | 1.68 | 0.71 |

## Output 2 — Warning-aligned REALIZED opportunity trajectory
| Rel | n | P(new high ≤1) | ≤3 | ≤5 | rem MFE | P(flip ≤3) |
| --- | --- | --- | --- | --- | --- | --- |
| -9 | 42 | 5% | 12% | 14% | 2.14 | 0% |
| -8 | 77 | 1% | 5% | 8% | 2.09 | 0% |
| -7 | 134 | 9% | 16% | 23% | 2.00 | 0% |
| -6 | 217 | 8% | 20% | 35% | 2.16 | 0% |
| -5 | 460 | 19% | 44% | 54% | 2.10 | 0% |
| -4 | 931 | 25% | 53% | 59% | 1.95 | 0% |
| -3 | 1,688 | 29% | 50% | 61% | 1.82 | 0% |
| -2 | 3,273 | 40% | 50% | 61% | 1.76 | 19% |
| -1 | 6,479 | 17% | 39% | 49% | 1.54 | 28% |
| +0 | 6,479 | 14% | 34% | 43% | 1.87 | 36% |
| +1 | 5,387 | 24% | 43% | 50% | 1.95 | 30% |
| +2 | 4,666 | 27% | 45% | 53% | 2.00 | 27% |
| +3 | 4,162 | 28% | 46% | 53% | 2.01 | 26% |
| +4 | 3,755 | 27% | 45% | 52% | 2.03 | 26% |
| +5 | 3,394 | 28% | 44% | 51% | 2.02 | 26% |
| +6 | 3,077 | 25% | 43% | 50% | 2.03 | 25% |
| +7 | 2,779 | 25% | 42% | 51% | 2.06 | 25% |
| +8 | 2,526 | 25% | 43% | 50% | 2.06 | 25% |
| +9 | 2,303 | 24% | 42% | 49% | 2.07 | 24% |
| +10 | 2,082 | 25% | 42% | 49% | 2.10 | 24% |

## Output 3 — Warning vs matched-control trajectory
| Rel | P(Fail) W/C | P(new high ≤3) W/C | rem MFE W/C | P(flip ≤3) W/C |
| --- | --- | --- | --- | --- |
| -9 | 41% / 31% | 12% / 52% | 2.14 / 3.24 | 0% / 0% |
| -8 | 42% / 28% | 5% / 45% | 2.09 / 3.50 | 0% / 0% |
| -7 | 41% / 26% | 16% / 48% | 2.00 / 3.57 | 0% / 0% |
| -6 | 40% / 21% | 20% / 50% | 2.16 / 2.92 | 0% / 0% |
| -5 | 36% / 22% | 44% / 61% | 2.10 / 2.93 | 0% / 0% |
| -4 | 31% / 20% | 53% / 69% | 1.95 / 2.85 | 0% / 0% |
| -3 | 29% / 18% | 50% / 74% | 1.82 / 2.83 | 0% / 0% |
| -2 | 23% / 16% | 50% / 78% | 1.76 / 2.83 | 19% / 7% |
| -1 | 14% / 13% | 39% / 81% | 1.54 / 2.77 | 28% / 13% |
| +0 | 25% / 6% | 34% / 68% | 1.87 / 2.46 | 36% / 19% |
| +1 | 20% / 3% | 43% / 59% | 1.95 / 2.37 | 30% / 21% |
| +2 | 16% / 2% | 45% / 53% | 2.00 / 2.34 | 27% / 21% |
| +3 | 13% / 2% | 46% / 50% | 2.01 / 2.33 | 26% / 22% |
| +4 | 10% / 1% | 45% / 48% | 2.03 / 2.33 | 26% / 23% |
| +5 | 8% / 1% | 44% / 45% | 2.02 / 2.30 | 26% / 24% |
| +6 | 7% / 1% | 43% / 44% | 2.03 / 2.30 | 25% / 23% |
| +7 | 5% / 1% | 42% / 43% | 2.06 / 2.30 | 25% / 23% |
| +8 | 4% / 1% | 43% / 42% | 2.06 / 2.31 | 25% / 23% |
| +9 | 3% / 1% | 42% / 41% | 2.07 / 2.30 | 24% / 24% |
| +10 | 3% / 0% | 42% / 40% | 2.10 / 2.30 | 24% / 24% |

## Decision — World A (sudden) vs World B (continuous decay)

> [!CAUTION]
> **The auto-verdict fired on a 0.0003 margin and the design has TWO confounds — do NOT read a clean "9-bar lead".**
> (1) **Composition shift:** each rel bar is a DIFFERENT subset (t=-9 n=42 late-warners; t=-1 n=6,479 all) — deep
> pre-bars reflect rare late warnings, not the typical one. (2) **Mechanical CONT/DETER artifact:** t=-1 is by
> definition the last CONT bar (low P(Fail)) and t=0 the first DETER bar (high P(Fail)); Output-1 P(Fail) and its
> t=-1→0 jump are CIRCULAR, unusable for World A/B.
>
> **What IS clean (full cohort at t=-1, no composition shift):** one bar before the warning, warning trades are
> ALREADY heavily degraded vs matched controls — **P(new high ≤3) 39% vs 81%** (42pp gap), rem MFE 1.54 vs 2.77; and
> the within-bar matched gap WIDENS toward t=0 (t=-5 17pp → t=-1 42pp). Realized new-high drifts modestly t=-4..-2
> (~50%) then drops sharply at t=-1/0 — most of the collapse is the final 1-2 bars.
>
> **Verdict: leans WORLD B** (a real precursor exists ≥1-2 bars before the warning; warning trades sit below matched
> controls throughout the pre-window) **but the deep lead-time is NOT reliably established** (composition shift
> inflates it). A FIXED-COHORT design (trades with a full −K..0 window tracked as one set) is required to cleanly
> measure the decay rate and lead time.
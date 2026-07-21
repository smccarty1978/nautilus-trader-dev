# KNN Money Gate — high-P(Runner)/low-P(Failure) cohort, net of costs

Signal through bar 4 (close) → enter bar 5 open (causal), hold to flip, NO SL. KNN ref = IS only. OOS-relative percentile cohorts; **both-year split is the robustness gate.** Costs $20/pt, $5 RT, 0.5t/1.0t slip. 1m bars.

| Cohort | n | Run% | Fail% | avgMFE | avgMAE | net/tr | PF | 2025 | 2026 | maxDD | win% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (all bar-5 entries) | 28,191 | 32% | 22% | 1.82 | 0.73 | $-17 | 0.89 | $-12 | $-33 | $500,515 | 30% |
| P(Run) top 10% | 2,839 | 61% | 0% | 2.57 | 1.04 | $+1 | 1.00 | $+15 | $-44 | $56,942 | 35% |
| P(Run) top 20% | 5,720 | 51% | 0% | 2.26 | 0.96 | $-16 | 0.92 | $-4 | $-51 | $130,015 | 34% |
| P(Fail) bottom 50% | 14,108 | 40% | 4% | 1.99 | 0.82 | $-20 | 0.88 | $-11 | $-45 | $300,232 | 32% |
| P(Fail) bottom 30% | 8,543 | 46% | 0% | 2.13 | 0.92 | $-21 | 0.88 | $-9 | $-58 | $206,855 | 32% |
| P(Fail) bottom 20% | 5,796 | 50% | 0% | 2.25 | 0.99 | $-11 | 0.94 | $+4 | $-56 | $121,272 | 33% |
| Run top10 & Fail bot50 | 2,839 | 61% | 0% | 2.57 | 1.04 | $+1 | 1.00 | $+15 | $-44 | $56,942 | 35% |
| Run top10 & Fail bot30 | 2,818 | 61% | 0% | 2.57 | 1.03 | $+1 | 1.00 | $+15 | $-46 | $56,780 | 35% |
| Run top10 & Fail bot20 | 2,643 | 61% | 0% | 2.53 | 1.01 | $+3 | 1.01 | $+15 | $-35 | $44,072 | 35% |
| Run top20 & Fail bot50 | 5,717 | 51% | 0% | 2.26 | 0.96 | $-15 | 0.92 | $-4 | $-50 | $128,672 | 34% |
| Run top20 & Fail bot30 | 5,483 | 52% | 0% | 2.26 | 0.96 | $-15 | 0.92 | $-2 | $-53 | $122,338 | 33% |

## Verdict

Baseline (all bar-5 entries): $-17/tr, win 30%, 2025 $-12 / 2026 $-33.
> [!WARNING]
> **The probability edge is PRICED — no combined cohort is net-positive in both years after costs.** Best combined (Run top10 & Fail bot20): 2025 $+15 / 2026 $-35, net $+3/tr, PF 1.01. KNN calibrates the Runner/Failure DISTRIBUTION (real), but the high-P(Runner) cohort's runners are paid for by its failures — same as pullback severity: probability separates, magnitude compensates, EV stays flat. Calibrated ≠ tradable. This is the clean result that now justifies order-flow for the direction residual. [[price_pullback_severity_monetarily_inert]]
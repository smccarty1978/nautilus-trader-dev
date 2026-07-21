# Policy Strict Gate — OOS (2025 & 2026)

Gate: OOS net>0 AND 2025 net>0 AND 2026 net>0 AND PF>1.05, next-open fills, $7.50/trade. Official gate = **first-entry-only** mode.

| Mode | Score | Top% | Trades | Net OOS | Net 2025 | Net 2026 | PF | Avg/tr | PASS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| first-entry | score_opportunity | 1% | 1,972 | $-2,015 | $-672 | $-1,342 | 1.00 | $-1.02 | ❌ |
| first-entry | score_opportunity | 2% | 3,666 | $-9,700 | $-2,220 | $-7,480 | 0.98 | $-2.65 | ❌ |
| first-entry | score_cost_aware | 2% | 4,248 | $-16,295 | $-14,632 | $-1,662 | 0.98 | $-3.84 | ❌ |
| first-entry | score_cost_aware | 1% | 2,302 | $-18,885 | $-2,700 | $-16,185 | 0.96 | $-8.20 | ❌ |
| first-entry | score_payoff | 1% | 5,162 | $-40,345 | $-11,565 | $-28,780 | 0.91 | $-7.82 | ❌ |
| first-entry | score_opportunity | 5% | 8,264 | $-62,970 | $-52,245 | $-10,725 | 0.94 | $-7.62 | ❌ |
| first-entry | score_payoff | 2% | 8,663 | $-89,438 | $-39,252 | $-50,185 | 0.88 | $-10.32 | ❌ |
| first-entry | score_cost_aware | 5% | 9,434 | $-89,730 | $-60,408 | $-29,322 | 0.93 | $-9.51 | ❌ |
| first-entry | score_payoff | 5% | 15,633 | $-97,332 | $-49,255 | $-48,078 | 0.92 | $-6.23 | ❌ |
| first-entry | score_opportunity | 10% | 14,120 | $-143,755 | $-91,840 | $-51,915 | 0.90 | $-10.18 | ❌ |
| first-entry | score_payoff | 10% | 21,992 | $-173,065 | $-102,938 | $-70,128 | 0.90 | $-7.87 | ❌ |
| first-entry | score_cost_aware | 10% | 15,709 | $-194,172 | $-126,632 | $-67,540 | 0.89 | $-12.36 | ❌ |
| re-entry | score_opportunity | 2% | 3,910 | $-3,140 | $6,402 | $-9,542 | 1.00 | $-0.80 | ❌ |
| re-entry | score_cost_aware | 2% | 4,528 | $-7,690 | $-3,878 | $-3,812 | 0.99 | $-1.70 | ❌ |
| re-entry | score_opportunity | 1% | 2,036 | $-7,900 | $-6,398 | $-1,502 | 0.98 | $-3.88 | ❌ |
| re-entry | score_cost_aware | 1% | 2,377 | $-26,278 | $-5,255 | $-21,022 | 0.95 | $-11.05 | ❌ |
| re-entry | score_payoff | 1% | 5,635 | $-35,428 | $-8,218 | $-27,210 | 0.93 | $-6.29 | ❌ |
| re-entry | score_opportunity | 5% | 9,600 | $-64,700 | $-53,612 | $-11,088 | 0.95 | $-6.74 | ❌ |
| re-entry | score_payoff | 2% | 10,054 | $-96,550 | $-42,398 | $-54,152 | 0.89 | $-9.60 | ❌ |
| re-entry | score_cost_aware | 5% | 10,995 | $-103,802 | $-72,785 | $-31,018 | 0.93 | $-9.44 | ❌ |
| re-entry | score_opportunity | 10% | 18,479 | $-147,692 | $-94,495 | $-53,198 | 0.93 | $-7.99 | ❌ |
| re-entry | score_payoff | 5% | 21,052 | $-150,310 | $-88,595 | $-61,715 | 0.91 | $-7.14 | ❌ |
| re-entry | score_payoff | 10% | 35,231 | $-239,058 | $-151,260 | $-87,798 | 0.91 | $-6.79 | ❌ |
| re-entry | score_cost_aware | 10% | 20,674 | $-260,060 | $-168,855 | $-91,205 | 0.89 | $-12.58 | ❌ |

**Configs passing the full gate: 0** (first-entry-only: 0).
No configuration passes the strict gate under first-entry-only. Tick/NT parity is moot (parity only reduces edge); the policy is not deployable.
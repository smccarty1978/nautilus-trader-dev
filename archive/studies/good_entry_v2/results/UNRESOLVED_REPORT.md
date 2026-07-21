# Unresolved Bracket Investigation

## Bracket resolution mix (all RTH OOS 2025)

| Status | n | % |
|---|--:|--:|
| pt_hit | 38,129 | 47.6% |
| sl_hit | 31,989 | 40.0% |
| unresolved | 9,917 | 12.4% |

## regime_exit PnL profile of unresolved rows

| Subset | n | Mean $ | Median $ | Trim 5% | Win% | PF |
|---|--:|--:|--:|--:|--:|--:|
| Unresolved bracket | 9,917 | $-179.41 | $-145.00 | $-167.21 | 2.3% | 0.01 |
| Resolved (PT or SL) | 70,118 | $52.48 | $-130.00 | $-23.04 | 36.8% | 1.23 |

**Interpretation**: unresolved rows by definition never saw price move ±1 ATR from entry before the event terminated. Their regime-exit PnL reflects the small end-of-event drift (much smaller in absolute terms than a resolved ±1 ATR outcome).

## ALL RTH: A vs B fallback comparison

- n=80,035, unresolved=9,917 (12.4% of this cut)

| Rule | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A: regime-exit fallback (current) | 80,035 | $1.04 | $-70.00 | $-0.68 | 47.9% | 1.01 | $83,234 |
| B: commission-only (pessimistic) | 80,035 | $22.65 | $-5.00 | $22.61 | 47.6% | 1.18 | $1,812,844 |
| C: resolved-only (drop unresolved) | 70,118 | $26.56 | $114.64 | $26.87 | 54.4% | 1.19 | $1,862,429 |

## top 10% (all RTH, by score): A vs B fallback comparison

- n=8,003, unresolved=1,063 (13.3% of this cut)

| Rule | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A: regime-exit fallback (current) | 8,003 | $10.39 | $-60.00 | $8.99 | 48.7% | 1.07 | $83,129 |
| B: commission-only (pessimistic) | 8,003 | $36.22 | $-5.00 | $36.77 | 48.3% | 1.27 | $289,889 |
| C: resolved-only (drop unresolved) | 6,940 | $42.54 | $142.50 | $43.69 | 55.7% | 1.28 | $295,204 |

## RTH-Short top-10%: A vs B fallback comparison

- n=3,891, unresolved=942 (24.2% of this cut)

| Rule | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A: regime-exit fallback (current) | 3,891 | $22.33 | $-75.00 | $22.15 | 46.4% | 1.13 | $86,889 |
| B: commission-only (pessimistic) | 3,891 | $66.98 | $-5.00 | $70.26 | 46.1% | 1.50 | $260,634 |
| C: resolved-only (drop unresolved) | 2,949 | $89.98 | $206.43 | $96.96 | 60.9% | 1.52 | $265,344 |

## RTH-Short 180-300s top-10%: A vs B fallback comparison

- n=819, unresolved=207 (25.3% of this cut)

| Rule | n | Mean $ | Median $ | Trim 5% | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| A: regime-exit fallback (current) | 819 | $36.25 | $-75.00 | $25.24 | 46.2% | 1.21 | $29,689 |
| B: commission-only (pessimistic) | 819 | $80.18 | $-5.00 | $73.32 | 45.9% | 1.64 | $65,669 |
| C: resolved-only (drop unresolved) | 612 | $108.99 | $206.43 | $103.60 | 61.4% | 1.66 | $66,704 |

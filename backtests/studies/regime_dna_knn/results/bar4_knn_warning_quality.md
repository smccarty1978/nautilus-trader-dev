# KNN Warning-Quality Audit — does CONT→DETER predict a forward CHANGE?

OOS warning trades (predicted Continuation→then Failure/Chop): **6,477** (23% of OOS). Forward outcomes are ACTUAL (from build_states). The test: WARNING states vs same-age still-healthy (predicted-CONT) states. A useful warning is forward-DEAD relative to its age-matched healthy control.

## Warning vs same-age healthy control, by regime age (bar k)
| Bar k | n warn | n healthy | P(new high≤3) warn / healthy | rem MFE warn / healthy | P(+1 ATR) warn / healthy | time-to-flip warn / healthy |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 3,206 | 13,833 | 38% / 73% | 1.50 / 2.10 | 41% / 51% | 9.9 / 13.1 |
| 6 | 1,585 | 14,523 | 34% / 63% | 1.58 / 2.01 | 40% / 49% | 9.6 / 12.7 |
| 7 | 757 | 14,459 | 31% / 56% | 1.37 / 1.96 | 39% / 48% | 8.9 / 12.4 |
| 8 | 471 | 13,902 | 29% / 52% | 1.45 / 1.94 | 38% / 48% | 8.8 / 12.1 |
| 9 | 243 | 13,177 | 24% / 49% | 1.48 / 1.91 | 35% / 47% | 8.6 / 12.0 |
| 10 | 83 | 12,413 | 30% / 46% | 1.84 / 1.89 | 42% / 46% | 9.6 / 11.8 |
| 11 | 57 | 11,556 | 28% / 45% | 1.14 / 1.89 | 26% / 46% | 8.6 / 11.7 |
| 12 | 35 | 10,669 | 37% / 44% | 1.61 / 1.89 | 49% / 45% | 10.6 / 11.6 |

## Pooled (age-matched, weighted by warning count)

| metric | WARNING | same-age HEALTHY | warning/healthy |
| --- | --- | --- | --- |
| P(new high ≤3 bars) | 34% | 65% | 0.53 |
| P(+0.5 ATR after) | 53% | 63% | 0.85 |
| P(+1.0 ATR after) | 40% | 50% | 0.80 |
| remaining MFE (ATR) | 1.50 | 2.04 | 0.74 |
| remaining MAE (ATR) | 0.56 | 0.75 | 0.75 |
| time to flip (bars) | 9.5 | 12.8 | 0.75 |

## Verdict

Age-matched: warning states make a new high (≤3 bars) 34% vs healthy 65% (ratio 0.53); remaining MFE 1.50 vs 2.04 ATR (ratio 0.74); time-to-flip 9.5 vs 12.8 bars.
> [!NOTE]
> **Partial signal.** Warning states are somewhat worse forward than same-age healthy (new highs and/or remaining MFE reduced), but not dramatically — and many still run. The warning carries SOME forward information but with high reversion. Attack further (reversion rate, money overlay) before trusting; not clearly garbage, not clearly actionable.
# NQ 5s Regime Scalp Study Inside Active 1m Regimes

## Objective
Evaluate whether 5s regime flips that align with the active 1m regime direction are independently tradable scalps (not adds to the 1m trade). RTH-only (08:30–15:00 CT). Causal MTF replay; next-1s-open fills; no phantom fills. Best config + tertile edges are FIT on 2021–2024 and VALIDATED on a held-out OOS year.

## Summary of Findings
> [!WARNING]
> **Negative expectancy.** No config is net-positive after primary costs. Best IS config **pos100_050_5s_bo_300** averaged **$-5.10/tr**.

---

## 1. Global 5s Scalp Performance (IS)
Top configs by IS primary net $/trade ($5 RT commission + 0.5-tick non-PT slippage).

| Configuration | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pos100_050_5s_bo_300 | 183,827 | 35.4% | 41.2% | -5.8% | $1.51 | $-5.10 | 0.78 | 0/4 |
| pos100_050_5s_bo_120 | 183,827 | 35.4% | 41.2% | -5.8% | $1.51 | $-5.10 | 0.78 | 0/4 |
| pos100_050_5s_bo_90 | 183,827 | 35.4% | 41.2% | -5.8% | $1.51 | $-5.10 | 0.78 | 0/4 |
| pos100_050_5s_bo_60 | 183,827 | 35.4% | 41.2% | -5.8% | $1.51 | $-5.10 | 0.78 | 0/4 |
| pos100_050_5s_b5f_300 | 183,827 | 35.3% | 41.2% | -5.8% | $1.51 | $-5.11 | 0.78 | 0/4 |
| pos100_050_5s_b5f_120 | 183,827 | 35.3% | 41.2% | -5.8% | $1.51 | $-5.11 | 0.78 | 0/4 |
| pos100_050_5s_b5f_90 | 183,827 | 35.3% | 41.2% | -5.8% | $1.51 | $-5.11 | 0.78 | 0/4 |
| pos100_050_5s_b5f_60 | 183,827 | 35.3% | 41.2% | -5.8% | $1.51 | $-5.11 | 0.78 | 0/4 |
| pos100_050_5s_bo_30 | 183,827 | 35.5% | 41.4% | -5.9% | $1.50 | $-5.13 | 0.78 | 0/4 |
| pos100_050_5s_b5f_30 | 183,827 | 35.4% | 41.4% | -5.9% | $1.50 | $-5.13 | 0.78 | 0/4 |

### Side split (best config)
| Side | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Longs | 96,701 | 35.3% | 41.6% | -6.3% | $1.40 | $-5.22 | 0.77 | 0/4 |
| Shorts | 87,126 | 35.5% | 40.9% | -5.4% | $1.65 | $-4.97 | 0.80 | 0/4 |

### Cost scenarios (best config)
| Cost | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Gross | 183,827 | 35.4% | 33.6% | 1.8% | $1.51 | $1.51 | 1.08 | 4/4 |
| Primary Net | 183,827 | 35.4% | 41.2% | -5.8% | $1.51 | $-5.10 | 0.78 | 0/4 |
| Stress Net | 183,827 | 35.4% | 42.8% | -7.5% | $1.51 | $-6.72 | 0.73 | 0/4 |

### No-bracket (held to 5s/1m regime flip)
Side question: is simply holding the 5s regime to its next opposite flip (or the parent 1m flip) profitable on its own?

| Configuration | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nobr_5s_bo_300 | 183,827 | 45.2% | 46.7% | -1.5% | $0.66 | $-6.84 | 0.94 | 0/4 |
| nobr_1m_bo_300 | 183,827 | 45.2% | 46.7% | -1.5% | $0.66 | $-6.84 | 0.94 | 0/4 |
| nobr_5s_b5f_30 | 183,827 | 42.3% | 47.6% | -5.3% | $-0.20 | $-7.70 | 0.81 | 0/4 |
| nobr_1m_b5f_30 | 183,827 | 42.3% | 47.6% | -5.3% | $-0.20 | $-7.70 | 0.81 | 0/4 |
| nobr_5s_bo_30 | 183,827 | 44.8% | 50.1% | -5.3% | $-0.30 | $-7.80 | 0.81 | 0/4 |

---

## 1b. OUT-OF-SAMPLE validation (2025, n=45,526)
IS-best config and IS-fitted bucket edges applied UNCHANGED to a year never used for selection. This is the deployment-relevant number.

| | Gross $/Trade | Net $/Trade | Net PF | Win % |
| --- | --- | --- | --- | --- |
| OOS best config (pos100_050_5s_bo_300) | $1.98 | $-4.64 | 0.85 | 35.1% |

### IS bucket 'winners' vs OOS
> [!CAUTION]
> Section 2's IS bucket table is the maximum of ~80 in-sample tertile draws under the in-sample-best config — a multiple-comparisons selection. Here each IS-top bucket is re-scored on OOS with the SAME edges. Survivors must stay net-positive OOS; collapses are noise.

| Feature | Bucket | IS Net $/tr | IS Yrs+ | OOS Net $/tr | OOS Trades |
| --- | --- | --- | --- | --- | --- |
| time_since_1m | 0–30s | $-4.42 | 0/4 | $-11.44 | 420 |
| ema9_5s_dist_atr | Mid | $-4.71 | 0/4 | $-4.50 | 14,736 |
| time_since_1m | 90–120s | $-4.71 | 0/4 | $-3.73 | 1,636 |
| vol_aligned_opposing_ratio | Low | $-4.75 | 0/4 | $-4.70 | 15,707 |
| ema9_5s_slope | Mid | $-4.76 | 0/4 | $-3.90 | 15,077 |
| time_since_1m | 180–300s | $-4.86 | 0/4 | $-5.70 | 6,004 |
| regime_5m | Bear | $-4.86 | 0/4 | $-4.43 | 20,355 |
| prior_5s_mae | High | $-4.87 | 0/4 | $-4.04 | 15,527 |
| ema9_1m_dist_atr | Mid | $-4.88 | 0/4 | $-5.06 | 15,723 |
| spread_9_21_1m | Low | $-4.89 | 0/4 | $-4.26 | 15,005 |

---

## 2. Best IS Buckets (in-sample; see OOS caveat above)
> [!CAUTION]
> In-sample tertile descriptions under the in-sample-best bracket. NOT validated edges — see Section 1b. A bucket is only 'interesting' if net-positive, edge > 2pp, positive in ≥3/4 years, AND survives OOS.

| Feature | Bucket | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| time_since_1m | 0–30s | 1,878 | 35.4% | 40.3% | -4.9% | $2.19 | $-4.42 | 0.81 | 0/4 |
| ema9_5s_dist_atr | Mid | 61,275 | 35.7% | 41.0% | -5.3% | $1.89 | $-4.71 | 0.80 | 0/4 |
| time_since_1m | 90–120s | 6,844 | 35.7% | 41.0% | -5.3% | $1.89 | $-4.71 | 0.80 | 0/4 |
| vol_aligned_opposing_ratio | Low | 61,147 | 35.8% | 41.2% | -5.4% | $1.85 | $-4.75 | 0.80 | 0/4 |
| ema9_5s_slope | Mid | 61,275 | 35.8% | 41.2% | -5.5% | $1.84 | $-4.76 | 0.79 | 0/4 |
| time_since_1m | 180–300s | 23,775 | 35.5% | 40.9% | -5.5% | $1.76 | $-4.86 | 0.79 | 0/4 |
| regime_5m | Bear | 83,422 | 35.5% | 40.6% | -5.1% | $1.75 | $-4.86 | 0.80 | 0/4 |
| prior_5s_mae | High | 61,276 | 35.4% | 40.9% | -5.5% | $1.75 | $-4.87 | 0.79 | 0/4 |
| ema9_1m_dist_atr | Mid | 61,275 | 35.7% | 41.5% | -5.8% | $1.73 | $-4.88 | 0.78 | 0/4 |
| spread_9_21_1m | Low | 61,276 | 35.5% | 40.6% | -5.0% | $1.72 | $-4.89 | 0.81 | 0/4 |
| 1m_pnl_atr | Low | 61,276 | 35.6% | 41.4% | -5.7% | $1.71 | $-4.89 | 0.79 | 0/4 |
| prior_5s_mfe | Low | 61,276 | 35.5% | 41.2% | -5.7% | $1.71 | $-4.90 | 0.79 | 0/4 |

## 3. Time-in-1m-Regime Table
Net by time since the parent 1m regime flipped.

| Time since 1m Flip | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0–30s | 1,878 | 35.4% | 40.3% | -4.9% | $2.19 | $-4.42 | 0.81 | 0/4 |
| 30–60s | 4,866 | 34.4% | 41.2% | -6.8% | $0.61 | $-6.03 | 0.75 | 0/4 |
| 60–90s | 6,981 | 35.2% | 41.2% | -5.9% | $1.27 | $-5.35 | 0.78 | 0/4 |
| 90–120s | 6,844 | 35.7% | 41.0% | -5.3% | $1.89 | $-4.71 | 0.80 | 0/4 |
| 120–180s | 13,373 | 34.8% | 41.6% | -6.8% | $0.57 | $-6.06 | 0.75 | 0/4 |
| 180–300s | 23,775 | 35.5% | 40.9% | -5.5% | $1.76 | $-4.86 | 0.79 | 0/4 |
| 300–600s | 44,227 | 35.3% | 41.2% | -5.9% | $1.48 | $-5.14 | 0.78 | 0/4 |
| 600s+ | 81,883 | 35.5% | 41.3% | -5.8% | $1.64 | $-4.97 | 0.78 | 0/4 |

## 4. 5s Flip Ordinal Table
Net by the aligned 5s flip ordinal inside the parent 1m regime.

| Ordinal | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1st aligned 5s flip | 26,775 | 34.9% | 41.0% | -6.1% | $1.06 | $-5.56 | 0.77 | 0/4 |
| 2nd | 23,353 | 35.2% | 40.9% | -5.7% | $1.51 | $-5.11 | 0.79 | 0/4 |
| 3rd | 19,947 | 35.6% | 41.2% | -5.7% | $1.59 | $-5.02 | 0.79 | 0/4 |
| 4th | 17,051 | 34.9% | 41.1% | -6.2% | $1.17 | $-5.46 | 0.77 | 0/4 |
| 5th+ | 96,701 | 35.6% | 41.4% | -5.8% | $1.68 | $-4.92 | 0.78 | 0/4 |

## 5. Parent Regime Quality Table
Net conditioned on parent 1m state at scalp entry.

| Parent Condition | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1m_reached_100: MFE < 1.00 ATR | 61,612 | 35.6% | 41.5% | -5.8% | $1.65 | $-4.96 | 0.78 | 0/4 |
| 1m_reached_050: MFE < 0.50 ATR | 36,172 | 35.5% | 41.5% | -5.9% | $1.60 | $-5.01 | 0.78 | 0/4 |
| 1m_reached_150: MFE < 1.50 ATR | 82,951 | 35.4% | 41.4% | -5.9% | $1.57 | $-5.04 | 0.78 | 0/4 |
| 1m_reached_025: MFE >= 0.25 ATR | 162,381 | 35.4% | 41.1% | -5.8% | $1.56 | $-5.06 | 0.78 | 0/4 |
| 1m_net_positive: Net Positive | 141,428 | 35.4% | 41.1% | -5.8% | $1.54 | $-5.08 | 0.78 | 0/4 |
| 1m_reached_050: MFE >= 0.50 ATR | 147,655 | 35.3% | 41.2% | -5.8% | $1.49 | $-5.12 | 0.78 | 0/4 |
| 1m_reached_150: MFE >= 1.50 ATR | 100,876 | 35.3% | 41.1% | -5.8% | $1.47 | $-5.15 | 0.78 | 0/4 |
| 1m_reached_100: MFE >= 1.00 ATR | 122,215 | 35.3% | 41.1% | -5.8% | $1.45 | $-5.17 | 0.78 | 0/4 |
| 1m_net_positive: Net Negative | 42,399 | 35.4% | 41.5% | -6.1% | $1.44 | $-5.18 | 0.77 | 0/4 |
| 1m_reached_025: MFE < 0.25 ATR | 21,446 | 35.3% | 41.8% | -6.5% | $1.17 | $-5.44 | 0.76 | 0/4 |

## 6. EMA / Slope Bucket Table
Net by trend geometry tertiles.

| EMA Feature & tertile | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ema9_5s_dist_atr: Mid | 61,275 | 35.7% | 41.0% | -5.3% | $1.89 | $-4.71 | 0.80 | 0/4 |
| ema9_5s_slope: Mid | 61,275 | 35.8% | 41.2% | -5.5% | $1.84 | $-4.76 | 0.79 | 0/4 |
| ema9_1m_dist_atr: Mid | 61,275 | 35.7% | 41.5% | -5.8% | $1.73 | $-4.88 | 0.78 | 0/4 |
| spread_9_21_1m: Low | 61,276 | 35.5% | 40.6% | -5.0% | $1.72 | $-4.89 | 0.81 | 0/4 |
| spread_9_21_1m: Mid | 61,275 | 35.5% | 41.4% | -5.9% | $1.64 | $-4.97 | 0.78 | 0/4 |
| ema9_1m_slope: Mid | 61,275 | 35.5% | 41.4% | -5.9% | $1.63 | $-4.98 | 0.78 | 0/4 |
| spread_9_21_5s: Low | 61,276 | 35.3% | 40.9% | -5.6% | $1.62 | $-4.99 | 0.79 | 0/4 |
| spread_9_21_5s: Mid | 61,275 | 35.7% | 41.5% | -5.8% | $1.59 | $-5.02 | 0.78 | 0/4 |
| ema9_1m_dist_atr: Low | 61,276 | 35.5% | 41.6% | -6.1% | $1.51 | $-5.10 | 0.77 | 0/4 |
| ema9_1m_slope: Low | 61,276 | 35.4% | 40.8% | -5.4% | $1.50 | $-5.11 | 0.80 | 0/4 |
| ema9_5s_dist_atr: Low | 61,276 | 35.3% | 41.3% | -6.0% | $1.47 | $-5.15 | 0.77 | 0/4 |
| ema9_1m_slope: High | 61,276 | 35.2% | 41.5% | -6.3% | $1.41 | $-5.21 | 0.77 | 0/4 |
| ema9_5s_slope: Low | 61,276 | 35.1% | 41.1% | -6.0% | $1.41 | $-5.22 | 0.77 | 0/4 |
| spread_9_21_5s: High | 61,276 | 35.2% | 41.2% | -6.1% | $1.33 | $-5.29 | 0.77 | 0/4 |
| ema9_1m_dist_atr: High | 61,276 | 34.9% | 40.6% | -5.6% | $1.30 | $-5.32 | 0.79 | 0/4 |
| ema9_5s_slope: High | 61,276 | 35.2% | 41.3% | -6.0% | $1.29 | $-5.33 | 0.77 | 0/4 |
| ema9_5s_dist_atr: High | 61,276 | 35.1% | 41.3% | -6.2% | $1.18 | $-5.44 | 0.77 | 0/4 |
| spread_9_21_1m: High | 61,276 | 35.1% | 41.8% | -6.7% | $1.18 | $-5.44 | 0.75 | 0/4 |

---

## Critical Questions

**Q1 — Positive expectancy (gross)?** Yes, gross **$1.51/tr** (best config pos100_050_5s_bo_300).

**Q2 — Positive after realistic costs?** No — every config is net-negative after primary costs; the gross edge is smaller than the per-trade friction.

**Q3 — 1:1 vs positive-RR?** Best is **positive-RR** (pos100).

**Q4 — Depends on position in parent 1m regime?** Best at **0–30s** ($-4.42/tr), worst at **120–180s** ($-6.06/tr). In-sample shape, not a validated rule.

**Q5 — Recovery flips better than the 1st aligned flip?** Yes (2nd $-5.11 > 1st $-5.56).

**Q6 — Does 5m alignment help?** Aligned $-5.04/tr vs not-aligned $-5.20/tr — not materially different.

**Q7 — EMA slope/distance identify better flips?** In-sample best cell is **ema9_5s_dist_atr Mid** ($-4.71/tr) — in-sample only.

**Q8 — Volume features identify better flips?** In-sample best is **vol_aligned_opposing_ratio Low** ($-4.75/tr) — needs OOS (Section 1b).

**Q9 — Stable by year and side?** Best config positive in **0/4** IS years; longs $-5.22/tr vs shorts $-4.97/tr; OOS -4.64/tr.

**Q10 — Repeatable intraregime scalp, or near-scratch?** Conclusion: **another near-scratch gross edge consumed by costs / not robust OOS.** Best IS primary $-5.10/tr, OOS $-4.64/tr.
---

## Verdict (final)

**DEAD — the 5s intra-regime aligned scalp has no tradable edge after costs.**

- **Gross edge is real but tiny:** best config +$1.51/tr (edge +1.8pp). The 7-day smoke's +$6.66/tr gross was trending-January noise — overturned 4.4× by the full 4 years (chop whipsaws the 5s flips), exactly the recurring smoke trap.
- **Net is decisively negative everywhere:** best of all 180 configs = **−$5.10/tr IS (0/4 yrs), −$4.64/tr OOS 2025**. ~$6.6/tr round-trip friction ($5 commission + 0.5-tick non-PT slippage) swamps the gross edge. Stress cost −$6.72/tr.
- **Side question answered:** simply holding the 5s regime to its next opposite flip (`nobr`) is **gross +$0.66/tr → net −$6.84/tr** (45% WR). The 5s regime has essentially *zero* gross directional edge held to flip.
- **No conditioning rescues it:** every segmentation cell (time-in-regime, flip ordinal, parent-1m quality incl. "reached +1 ATR / net-positive", 5m alignment, EMA slope/distance, volume) is net-negative and 0/4 years; the IS bucket "winners" all stay negative or collapse OOS (multiple-comparisons noise).
- **Both sides negative:** longs −$5.22, shorts −$4.97.

Consistent with the whole program: NQ price-geometry/regime signals carry at most a thin gross edge that costs consume. The binding constraint remains **entry edge** (needs orderflow/book microstructure), not exit or timeframe.

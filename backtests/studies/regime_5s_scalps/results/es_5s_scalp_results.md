# ES 5s Regime Scalp Study Inside Active 1m Regimes

## Objective
Evaluate whether 5s regime flips that align with the active 1m regime direction are independently tradable scalps (not adds to the 1m trade). RTH-only (08:30–15:00 CT). Causal MTF replay; next-1s-open fills; no phantom fills. Best config + tertile edges are FIT on 2021–2024 and VALIDATED on a held-out OOS year.

## Summary of Findings
> [!WARNING]
> **Negative expectancy.** No config is net-positive after primary costs. Best IS config **sym050_1m_bo_300** averaged **$-7.87/tr**.

---

## 1. Global 5s Scalp Performance (IS)
Top configs by IS primary net $/trade ($5 RT commission + 0.5-tick non-PT slippage).

| Configuration | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sym050_1m_bo_300 | 202,859 | 50.0% | 56.7% | -6.7% | $0.26 | $-7.87 | 0.77 | 0/4 |
| sym050_1m_bo_120 | 202,859 | 49.5% | 56.5% | -7.1% | $0.28 | $-8.04 | 0.75 | 0/4 |
| sym025_1m_bo_300 | 202,859 | 49.6% | 62.6% | -13.0% | $0.03 | $-8.11 | 0.59 | 0/4 |
| sym025_1m_bo_120 | 202,859 | 49.6% | 62.6% | -13.0% | $0.03 | $-8.11 | 0.59 | 0/4 |
| sym100_5s_bo_300 | 202,859 | 49.8% | 62.0% | -12.1% | $0.02 | $-8.11 | 0.61 | 0/4 |
| sym100_5s_bo_120 | 202,859 | 49.8% | 62.0% | -12.1% | $0.02 | $-8.11 | 0.61 | 0/4 |
| sym025_1m_bo_90 | 202,859 | 49.5% | 62.6% | -13.0% | $0.03 | $-8.12 | 0.59 | 0/4 |
| sym100_5s_bo_90 | 202,859 | 49.8% | 61.9% | -12.2% | $0.02 | $-8.12 | 0.61 | 0/4 |
| sym075_5s_bo_300 | 202,859 | 49.4% | 65.2% | -15.8% | $0.01 | $-8.14 | 0.52 | 0/4 |
| sym075_5s_bo_120 | 202,859 | 49.4% | 65.2% | -15.8% | $0.01 | $-8.14 | 0.52 | 0/4 |

### Side split (best config)
| Side | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Longs | 107,646 | 50.1% | 56.9% | -6.7% | $0.40 | $-7.72 | 0.76 | 0/4 |
| Shorts | 95,213 | 49.9% | 56.5% | -6.6% | $0.09 | $-8.05 | 0.77 | 0/4 |

### Cost scenarios (best config)
| Cost | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Gross | 202,859 | 50.0% | 49.8% | 0.2% | $0.26 | $0.26 | 1.01 | 3/4 |
| Primary Net | 202,859 | 50.0% | 56.7% | -6.7% | $0.26 | $-7.87 | 0.77 | 0/4 |
| Stress Net | 202,859 | 50.0% | 58.8% | -8.8% | $0.26 | $-11.00 | 0.70 | 0/4 |

### No-bracket (held to 5s/1m regime flip)
Side question: is simply holding the 5s regime to its next opposite flip (or the parent 1m flip) profitable on its own?

| Configuration | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nobr_1m_bo_300 | 202,859 | 44.5% | 49.0% | -4.5% | $0.29 | $-10.96 | 0.83 | 0/4 |
| nobr_5s_bo_300 | 202,859 | 44.5% | 49.0% | -4.5% | $0.29 | $-10.96 | 0.83 | 0/4 |
| nobr_5s_bo_120 | 202,859 | 45.9% | 53.0% | -7.1% | $-0.01 | $-11.26 | 0.75 | 0/4 |
| nobr_1m_bo_120 | 202,859 | 45.9% | 53.0% | -7.1% | $-0.01 | $-11.26 | 0.75 | 0/4 |
| nobr_1m_bo_60 | 202,859 | 44.7% | 54.8% | -10.1% | $-0.09 | $-11.34 | 0.67 | 0/4 |

---

## 1b. OUT-OF-SAMPLE validation (2025, n=48,599)
IS-best config and IS-fitted bucket edges applied UNCHANGED to a year never used for selection. This is the deployment-relevant number.

| | Gross $/Trade | Net $/Trade | Net PF | Win % |
| --- | --- | --- | --- | --- |
| OOS best config (sym050_1m_bo_300) | $0.68 | $-7.45 | 0.83 | 50.0% |

### IS bucket 'winners' vs OOS
> [!CAUTION]
> Section 2's IS bucket table is the maximum of ~80 in-sample tertile draws under the in-sample-best config — a multiple-comparisons selection. Here each IS-top bucket is re-scored on OOS with the SAME edges. Survivors must stay net-positive OOS; collapses are noise.

| Feature | Bucket | IS Net $/tr | IS Yrs+ | OOS Net $/tr | OOS Trades |
| --- | --- | --- | --- | --- | --- |
| age_5m | High | $-7.23 | 0/4 | $-7.02 | 14,890 |
| spread_9_21_1m | Mid | $-7.25 | 0/4 | $-6.61 | 15,917 |
| ema9_5s_dist_atr | Low | $-7.27 | 0/4 | $-7.82 | 16,291 |
| vol_aligned_opposing_ratio | Low | $-7.40 | 0/4 | $-8.19 | 17,352 |
| vol_5s_vs_avg | Mid | $-7.42 | 0/4 | $-8.04 | 17,529 |
| ema9_1m_dist_atr | Low | $-7.43 | 0/4 | $-8.04 | 16,025 |
| 1m_ordinal | 4th | $-7.49 | 0/4 | $-8.35 | 4,390 |
| ema9_1m_slope | Mid | $-7.50 | 0/4 | $-7.99 | 15,738 |
| ema9_5s_slope | Mid | $-7.50 | 0/4 | $-7.17 | 16,398 |
| 1m_path_efficiency | Low | $-7.52 | 0/4 | $-8.23 | 16,107 |

---

## 2. Best IS Buckets (in-sample; see OOS caveat above)
> [!CAUTION]
> In-sample tertile descriptions under the in-sample-best bracket. NOT validated edges — see Section 1b. A bucket is only 'interesting' if net-positive, edge > 2pp, positive in ≥3/4 years, AND survives OOS.

| Feature | Bucket | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| age_5m | High | 64,852 | 50.6% | 56.9% | -6.3% | $0.87 | $-7.23 | 0.78 | 0/4 |
| spread_9_21_1m | Mid | 67,619 | 50.4% | 56.7% | -6.4% | $0.86 | $-7.25 | 0.77 | 0/4 |
| ema9_5s_dist_atr | Low | 67,620 | 50.4% | 56.4% | -6.0% | $0.83 | $-7.27 | 0.78 | 0/4 |
| vol_aligned_opposing_ratio | Low | 67,426 | 50.1% | 56.5% | -6.4% | $0.73 | $-7.40 | 0.77 | 0/4 |
| vol_5s_vs_avg | Mid | 67,617 | 50.4% | 56.1% | -5.6% | $0.69 | $-7.42 | 0.80 | 0/4 |
| ema9_1m_dist_atr | Low | 67,620 | 50.0% | 56.3% | -6.3% | $0.70 | $-7.43 | 0.78 | 0/4 |
| 1m_ordinal | 4th | 18,034 | 50.0% | 56.2% | -6.2% | $0.64 | $-7.49 | 0.78 | 0/4 |
| ema9_1m_slope | Mid | 67,618 | 50.1% | 56.6% | -6.6% | $0.63 | $-7.50 | 0.77 | 0/4 |
| ema9_5s_slope | Mid | 67,619 | 50.4% | 56.6% | -6.2% | $0.61 | $-7.50 | 0.78 | 0/4 |
| 1m_path_efficiency | Low | 67,431 | 50.0% | 56.6% | -6.6% | $0.61 | $-7.52 | 0.77 | 0/4 |
| prior_5s_duration | High | 60,909 | 50.2% | 56.2% | -6.0% | $0.60 | $-7.52 | 0.78 | 0/4 |
| flip_bar_range_atr | Mid | 67,619 | 50.1% | 56.2% | -6.1% | $0.54 | $-7.58 | 0.78 | 0/4 |

## 3. Time-in-1m-Regime Table
Net by time since the parent 1m regime flipped.

| Time since 1m Flip | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0–30s | 2,539 | 49.9% | 57.6% | -7.6% | $-0.20 | $-8.33 | 0.74 | 0/4 |
| 30–60s | 5,800 | 48.6% | 57.6% | -8.9% | $-2.23 | $-10.44 | 0.70 | 0/4 |
| 60–90s | 7,719 | 49.8% | 56.2% | -6.4% | $0.44 | $-7.71 | 0.77 | 0/4 |
| 90–120s | 7,799 | 49.2% | 56.9% | -7.7% | $-0.92 | $-9.10 | 0.73 | 0/4 |
| 120–180s | 14,826 | 49.6% | 56.5% | -6.9% | $-0.02 | $-8.18 | 0.76 | 0/4 |
| 180–300s | 26,559 | 50.0% | 56.4% | -6.4% | $0.53 | $-7.60 | 0.77 | 0/4 |
| 300–600s | 48,762 | 50.2% | 56.6% | -6.5% | $0.44 | $-7.68 | 0.77 | 0/4 |
| 600s+ | 88,855 | 50.2% | 56.7% | -6.6% | $0.38 | $-7.74 | 0.77 | 0/4 |

## 4. 5s Flip Ordinal Table
Net by the aligned 5s flip ordinal inside the parent 1m regime.

| Ordinal | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1st aligned 5s flip | 27,339 | 49.6% | 56.5% | -6.9% | $-0.45 | $-8.61 | 0.76 | 0/4 |
| 2nd | 24,197 | 49.8% | 56.5% | -6.6% | $-0.04 | $-8.18 | 0.77 | 0/4 |
| 3rd | 21,017 | 50.0% | 56.4% | -6.4% | $0.30 | $-7.83 | 0.77 | 0/4 |
| 4th | 18,034 | 50.0% | 56.2% | -6.2% | $0.64 | $-7.49 | 0.78 | 0/4 |
| 5th+ | 112,272 | 50.2% | 56.9% | -6.7% | $0.42 | $-7.70 | 0.76 | 0/4 |

## 5. Parent Regime Quality Table
Net conditioned on parent 1m state at scalp entry.

| Parent Condition | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1m_reached_025: MFE >= 0.25 ATR | 176,974 | 50.1% | 56.6% | -6.5% | $0.39 | $-7.73 | 0.77 | 0/4 |
| 1m_reached_150: MFE < 1.50 ATR | 94,595 | 49.9% | 56.7% | -6.8% | $0.33 | $-7.80 | 0.76 | 0/4 |
| 1m_reached_100: MFE >= 1.00 ATR | 132,360 | 50.1% | 56.6% | -6.5% | $0.32 | $-7.81 | 0.77 | 0/4 |
| 1m_reached_050: MFE >= 0.50 ATR | 160,897 | 50.1% | 56.7% | -6.6% | $0.30 | $-7.82 | 0.77 | 0/4 |
| 1m_net_positive: Net Positive | 150,943 | 50.1% | 56.7% | -6.5% | $0.27 | $-7.85 | 0.77 | 0/4 |
| 1m_reached_150: MFE >= 1.50 ATR | 108,264 | 50.1% | 56.7% | -6.6% | $0.19 | $-7.94 | 0.77 | 0/4 |
| 1m_net_positive: Net Negative | 51,916 | 49.7% | 56.7% | -7.0% | $0.21 | $-7.94 | 0.75 | 0/4 |
| 1m_reached_100: MFE < 1.00 ATR | 70,499 | 49.8% | 56.7% | -6.9% | $0.14 | $-8.00 | 0.76 | 0/4 |
| 1m_reached_050: MFE < 0.50 ATR | 41,962 | 49.7% | 56.7% | -7.0% | $0.07 | $-8.08 | 0.75 | 0/4 |
| 1m_reached_025: MFE < 0.25 ATR | 25,885 | 49.2% | 56.9% | -7.7% | $-0.68 | $-8.86 | 0.73 | 0/4 |

## 6. EMA / Slope Bucket Table
Net by trend geometry tertiles.

| EMA Feature & tertile | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spread_9_21_1m: Mid | 67,619 | 50.4% | 56.7% | -6.4% | $0.86 | $-7.25 | 0.77 | 0/4 |
| ema9_5s_dist_atr: Low | 67,620 | 50.4% | 56.4% | -6.0% | $0.83 | $-7.27 | 0.78 | 0/4 |
| ema9_1m_dist_atr: Low | 67,620 | 50.0% | 56.3% | -6.3% | $0.70 | $-7.43 | 0.78 | 0/4 |
| ema9_1m_slope: Mid | 67,618 | 50.1% | 56.6% | -6.6% | $0.63 | $-7.50 | 0.77 | 0/4 |
| ema9_5s_slope: Mid | 67,619 | 50.4% | 56.6% | -6.2% | $0.61 | $-7.50 | 0.78 | 0/4 |
| spread_9_21_5s: Low | 67,620 | 50.1% | 56.5% | -6.5% | $0.40 | $-7.72 | 0.77 | 0/4 |
| ema9_1m_dist_atr: Mid | 67,619 | 50.2% | 56.9% | -6.7% | $0.31 | $-7.81 | 0.76 | 0/4 |
| spread_9_21_5s: Mid | 67,619 | 50.2% | 57.0% | -6.8% | $0.17 | $-7.95 | 0.76 | 0/4 |
| spread_9_21_5s: High | 67,620 | 49.8% | 56.5% | -6.7% | $0.19 | $-7.95 | 0.76 | 0/4 |
| ema9_5s_slope: High | 67,620 | 49.9% | 56.7% | -6.8% | $0.18 | $-7.95 | 0.76 | 0/4 |
| ema9_1m_slope: Low | 67,621 | 50.0% | 56.4% | -6.4% | $0.14 | $-7.98 | 0.77 | 0/4 |
| ema9_5s_dist_atr: Mid | 67,619 | 49.7% | 56.5% | -6.7% | $0.06 | $-8.09 | 0.76 | 0/4 |
| spread_9_21_1m: Low | 67,620 | 49.9% | 56.2% | -6.3% | $0.02 | $-8.11 | 0.78 | 0/4 |
| ema9_1m_slope: High | 67,620 | 49.9% | 57.0% | -7.0% | $-0.01 | $-8.14 | 0.75 | 0/4 |
| ema9_5s_slope: Low | 67,620 | 49.8% | 56.8% | -7.0% | $-0.03 | $-8.17 | 0.75 | 0/4 |
| ema9_5s_dist_atr: High | 67,620 | 49.9% | 57.2% | -7.2% | $-0.12 | $-8.26 | 0.75 | 0/4 |
| spread_9_21_1m: High | 67,620 | 49.8% | 57.1% | -7.3% | $-0.11 | $-8.26 | 0.74 | 0/4 |
| ema9_1m_dist_atr: High | 67,620 | 49.8% | 56.8% | -6.9% | $-0.25 | $-8.39 | 0.76 | 0/4 |

---

## Critical Questions

**Q1 — Positive expectancy (gross)?** Yes, gross **$0.26/tr** (best config sym050_1m_bo_300).

**Q2 — Positive after realistic costs?** No — every config is net-negative after primary costs; the gross edge is smaller than the per-trade friction.

**Q3 — 1:1 vs positive-RR?** Best is **symmetric 1:1** (sym050).

**Q4 — Depends on position in parent 1m regime?** Best at **180–300s** ($-7.60/tr), worst at **30–60s** ($-10.44/tr). In-sample shape, not a validated rule.

**Q5 — Recovery flips better than the 1st aligned flip?** Yes (2nd $-8.18 > 1st $-8.61).

**Q6 — Does 5m alignment help?** Aligned $-7.74/tr vs not-aligned $-8.11/tr — not materially different.

**Q7 — EMA slope/distance identify better flips?** In-sample best cell is **spread_9_21_1m Mid** ($-7.25/tr) — in-sample only.

**Q8 — Volume features identify better flips?** In-sample best is **vol_aligned_opposing_ratio Low** ($-7.40/tr) — needs OOS (Section 1b).

**Q9 — Stable by year and side?** Best config positive in **0/4** IS years; longs $-7.72/tr vs shorts $-8.05/tr; OOS -7.45/tr.

**Q10 — Repeatable intraregime scalp, or near-scratch?** Conclusion: **another near-scratch gross edge consumed by costs / not robust OOS.** Best IS primary $-7.87/tr, OOS $-7.45/tr.
---

## Verdict (final)

**DEAD — same as NQ, and more decisively so.** The ES 5s intra-regime aligned scalp has no tradable edge after costs.

- **Gross edge is essentially zero:** best config (0.50/0.50 ATR-1m) gross **+$0.26/tr** (edge +0.2pp, 3/4 yrs gross-positive at ~coin-flip 50.0% win). Smaller than NQ's already-thin +$1.51.
- **Net decisively negative everywhere:** best of all 180 configs = **−$7.87/tr IS (0/4 yrs), −$7.45/tr OOS 2025**. ES friction is the killer — $5 commission + 0.5-tick (**$6.25**) slippage = ~$11.25/tr round trip on non-PT exits (vs $7.50 on NQ), against a ~$0.3/tr gross edge. Stress cost −$11.00/tr.
- **Symmetric 1:1 = literal coin flip:** win rate caps at **50.0%** globally (52.1% on a 748-trade cherry-picked `flips_seen=2` slice). Net break-even for symmetric 1:1 after ES costs is **56.7%**, so 50% is ~7pp underwater → net −$7.87.
- **Side question:** held-to-flip 5s regime (`nobr`) gross +$0.29 → net **−$10.96/tr**. Zero directional edge.
- Both sides negative (long −$7.72, short −$8.05). Every segmentation cell net-negative, 0/4 yrs.

Identical conclusion to NQ: thin/zero gross edge consumed by friction; binding constraint is ENTRY edge (orderflow/microstructure), not exit/timeframe/instrument. ES is worse only because its per-tick cost is higher relative to a comparably tiny gross edge.

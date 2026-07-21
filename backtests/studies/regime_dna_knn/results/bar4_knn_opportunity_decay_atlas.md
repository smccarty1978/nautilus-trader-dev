# Continuous KNN Opportunity-State Decay Atlas

OOS Bar-4 states: 296,816. OpportunityScore = P(Runner) (KNN, causal). Per-trade running peak, score-drawdown%, slope. Forward outcomes from causal build_states columns. NO label thresholding.

## Study 1 — Opportunity-score drawdown vs forward outcome
| Score DD% | n | %DETER(now) | rem MFE | rem MAE | P(new high≤3) | P(+1 ATR) | P(flip≤3) | P(flip≤10) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0-5% | 169,537 | 11% | 2.51 | 1.33 | 59% | 59% | 18% | 55% |
| 5-10% | 20,044 | 8% | 2.04 | 1.06 | 41% | 52% | 26% | 61% |
| 10-20% | 32,029 | 12% | 2.02 | 1.05 | 40% | 52% | 27% | 63% |
| 20-30% | 27,255 | 19% | 2.02 | 1.01 | 35% | 51% | 30% | 64% |
| 30-40% | 22,014 | 25% | 1.93 | 0.98 | 28% | 50% | 33% | 67% |
| 40-101% | 25,937 | 31% | 1.87 | 0.96 | 19% | 48% | 39% | 70% |

## Study 2 — Opportunity-score SLOPE (ΔScore over 3 bars) vs forward outcome
| Slope3 bucket | n | rem MFE | rem MAE | P(new high≤3) | P(flip≤3) | P(flip≤5) |
| --- | --- | --- | --- | --- | --- | --- |
| strong + (>+.05) | 93,234 | 2.39 | 1.28 | 58% | 16% | 29% |
| flat (-.02..+.05) | 74,314 | 2.43 | 1.26 | 39% | 24% | 37% |
| mild - (-.10..-.02) | 32,249 | 1.88 | 0.96 | 28% | 34% | 47% |
| severe - (<-.10) | 19,295 | 1.94 | 0.97 | 22% | 37% | 49% |

## Study 4 — Early-warning lead (continuous trigger → DETER)
- Of 6,479 warned trades, **21%** had a continuous trigger (dd>20% or slope<0) fire BEFORE the discrete DETER bar.
- DD>20% trigger lead before DETER: median **0** bars (n=5,472); slope<0 lead: median 0 bars (n=1,391).

## Study 3 — Profit-protection overlay (1m scale-out; BE-stop rules need 1s, deferred)
| Policy | avg/tr | 2025 | 2026 | PF | maxDD |
| --- | --- | --- | --- | --- | --- |
| hold-to-flip | $+0 | $+6 | $-16 | 1.00 | $189,308 |
| exit on DETER | $+3 | $+7 | $-9 | 1.02 | $131,308 |
| scale 50% @ dd>20% | $-2 | $+2 | $-13 | 0.98 | $197,360 |

## Deliverable — what dimension does the OppScore drawdown separate?
Low-drawdown (healthiest) vs high-drawdown (most decayed) quintiles:
| dimension | low-dd | high-dd | Δ |
| --- | --- | --- | --- |
| new-high (opportunity) | 0.63 | 0.25 | -0.38 |
| P(flip≤3) (maturity/reversal-timing) | 0.16 | 0.35 | +0.20 |
| rem MAE (risk) | 1.37 | 0.98 | -0.39 |
| rem MFE (opportunity magnitude) | 2.68 | 1.92 | -0.76 |
| P(+1 before -1) [direction] | 0.48 | 0.44 | -0.04 |

## Verdict — what is KNN measuring?

OppScore drawdown most strongly separates **new-high 63%→25%**, **rem MFE 2.68→1.92**, **flip≤3 16%→35%**, but barely moves **direction P(+1 before -1) 48%→44%**.

> [!TIP]
> **THE DELIVERABLE — KNN measures OPPORTUNITY / TREND-HEALTH / MATURITY, NOT direction.** The continuous
> OppScore drawdown monotonically tracks collapsing new-high prob, falling MFE magnitude, and rising flip-timing
> (Study 1), and the SLOPE carries the same (Study 2) — but it does NOT separate the +1-before-−1 directional race
> (flat 48→44%). KNN is a continuous trend-HEALTH monitor. This vindicates the reframe: it answers "is this trend
> getting less healthy?", not "which way next?".

> [!WARNING]
> **But the two OPERATIONAL hopes do NOT materialize from the 1m score:**
> - **Not earlier than the label (Study 4):** the continuous trigger (dd>20% / slope<0) fires a **median 0 bars**
>   before DETER, and only **21%** of warned trades trigger before DETER at all. The continuous score and the
>   discrete label are two views of the SAME P(Runner) collapse — they fire together. So the binary label throws
>   away GRADATION (Study 1/2 granularity) but NOT EARLINESS. (The underlying realized opportunity decays earlier —
>   fixed-cohort study — but KNN's SCORE does not register it early; the score is itself threshold-ish.)
> - **No better protection (Study 3):** scale-out on dd>20% nets −$2/tr and WORSENS maxDD ($197K vs hold $189K) —
>   the discrete DETER exit (+$3, DD $131K) is strictly better. The continuous drawdown fires too often (cuts
>   recoverers) to be a useful protection trigger.
>
> **Net:** KNN is a granular trend-health monitor (the reframe is right) but the 1m score gives no early lead over
> its own DETER label and no profit-protection edge. The earlier-detection layer must come from a different input
> (5s / order-flow); the 1m KNN score cannot hand off before DETER.
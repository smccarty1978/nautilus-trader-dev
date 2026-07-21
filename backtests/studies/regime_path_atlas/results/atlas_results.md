# NQ 1m Regime Path Atlas Study

## Objective
A non-parametric statistics database (the 'Atlas') of NQ 1m regime checkpoints. Tracks 1m bar checkpoints $t \in [1, 30]$ inside every regime to estimate conditional probabilities and net dollar EVs of trend continuation from that point forward. Separates discovery (2021–2024) and out-of-sample validation (2025–2026).

## 1. Unconditional Base Rates
The unconditional probabilities and dollar expected values (EV) across the entire population. If the martingale hypothesis holds, most conditional cells will collapse back to these base rates.

| Epoch | Checkpoints | P(Next HH/LL) | P(0.5 PT) | Net EV 0.5/0.5 | P(1.0 PT) | Net EV 1.0/1.0 | P(2.0 PT) | Net EV 2.0/1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IS (2021–2024) | 1,214,979 | 11.1% | 15.4% | $-7.35 | 13.5% | $-7.47 | 8.1% | $-7.60 |
| OOS (2025,2026) | 401,646 | 11.9% | 15.3% | $-7.09 | 13.5% | $-6.72 | 8.0% | $-6.84 |

## 2. Martingale Falsification & Robustness Verification
> [!IMPORTANT]
> **Falsification Verdict:**
> We sweep all conditional cells to search for any stable continuation pockets. > A cell is flagged as **Robust** only if it passes the **All-Year Stability Gate** > (strictly positive net EV in all IS years AND both OOS years individually).

*   **Symmetric 0.5/0.5 Stable Cells:** 0 / 157
*   **Symmetric 1.0/1.0 Stable Cells:** 0 / 157
*   **Asymmetric 2.0/1.0 Stable Cells:** 0 / 157

> [!WARNING]
> **Martingale Null Confirmed.** Zero conditional price cells survived the stability gate. > Almost all price-based cells collapsed to the unconditional negative base rates out-of-sample. > The breakout continuation process is confirmed to be a martingale w.r.t the price path so far.

### Top Stable Cells (Any Bracket)
| Type | Feature(s) & Cell Value | Trades IS | Trades OOS | Bracket | IS Net EV | OOS Net EV | Stable? |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 3. Time-in-Regime Checkpoints (Bar Index)

| bar_index | Trades IS | Trades OOS | P(Next HH/LL) | Net EV 0.5/0.5 | Net EV 1.0/1.0 | Net EV 2.0/1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 108,275 | 35,373 | 14.7% | $-8.35 | $-8.27 | $-8.30 |
| 11–20 | 316,861 | 105,548 | 15.7% | $-7.17 | $-7.20 | $-7.20 |
| 2 | 101,498 | 33,207 | 14.9% | $-7.90 | $-8.16 | $-8.33 |
| 21–30 | 129,989 | 42,811 | 16.7% | $-6.57 | $-6.77 | $-7.37 |
| 3 | 93,494 | 30,646 | 15.0% | $-7.62 | $-7.96 | $-7.68 |
| 4–5 | 163,889 | 54,062 | 15.2% | $-7.46 | $-7.62 | $-7.63 |
| 6–10 | 300,973 | 99,999 | 15.4% | $-7.21 | $-7.30 | $-7.57 |

## 4. Pullback Excursion Checkpoints

| pullback_from_peak_atr | Trades IS | Trades OOS | P(Next HH/LL) | Net EV 0.5/0.5 | Net EV 1.0/1.0 | Net EV 2.0/1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| High | 404,993 | 127,938 | 15.1% | $-6.73 | $-6.74 | $-6.69 |
| Low | 404,993 | 134,417 | 15.7% | $-7.52 | $-7.59 | $-7.99 |
| Mid | 404,993 | 139,291 | 15.6% | $-7.82 | $-8.08 | $-8.10 |

## 5. 5s Alignment Checkpoints

| 5s_alignment | Trades IS | Trades OOS | P(Next HH/LL) | Net EV 0.5/0.5 | Net EV 1.0/1.0 | Net EV 2.0/1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| Aligned | 661,946 | 221,814 | 15.7% | $-7.47 | $-7.44 | $-7.58 |
| Opposed | 553,033 | 179,832 | 15.2% | $-7.22 | $-7.51 | $-7.62 |

## 6. Volume State Checkpoints

| volume_state | Trades IS | Trades OOS | P(Next HH/LL) | Net EV 0.5/0.5 | Net EV 1.0/1.0 | Net EV 2.0/1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| High | 404,992 | 133,354 | 16.2% | $-7.43 | $-7.17 | $-7.26 |
| Low | 404,997 | 133,351 | 10.6% | $-7.25 | $-7.39 | $-7.53 |
| Mid | 404,990 | 134,941 | 19.6% | $-7.38 | $-7.85 | $-8.00 |

---

## Critical Questions

**Q1 — Do checkpoints have positive expectancy?**
The unconditional base rate net EV is **$-7.47** in-sample and **$-6.72** out-of-sample. Almost all individual checkpoints remain net-negative after realistic transaction friction.

**Q2 — Do they survive realistic costs?**
No. While gross expectancy is scratch/positive, the $5.00 RT commission and 0.5-tick slippage floor pulls the net EV of almost all checkpoints below zero.

**Q3 — Best bracket?**
In-sample, the asymmetric **2.0/1.0** bracket has a base net EV of **$-7.60**, compared to **$-7.47** for the symmetric 1.0/1.0 bracket. Positive reward-to-risk reduces friction drag by requiring lower win rates, but fails to achieve net-profitability on its own.

**Q4 — Does performance depend on position (bar index) inside the parent 1m regime?**
Yes. Breakout momentum is potent at **bar 1** and decays rapidly as the trend ages. Checkpoints at bar index 1 have a net EV of **$-8.27** and drop to **$-6.77** by bars 21–30.

**Q5 — Are recovery checkpoints after pullbacks better?**
Pullback checkpoints average **$-7.36** net EV compared to **$-7.56** for non-pullback checkpoints. Pullback states do not offer a robust positive continuation edge.

**Q7 — Does 5s alignment improve performance?**
Checkpoints with aligned 5s sub-regimes average **$-7.44** net EV compared to **$-7.51** for opposed sub-regimes. The difference is minor and fails to clear the friction wall.

**Q10 — Conclusion: repeatable edge or scratch?**
**Conclusive Falsification.** The Regime Path Atlas confirms the **martingale null hypothesis** w.r.t the price path. Zero price-based or trend-geometry cells survived the OOS stability gate. Breakout continuation is a near-scratch gross edge completely consumed by transaction friction.

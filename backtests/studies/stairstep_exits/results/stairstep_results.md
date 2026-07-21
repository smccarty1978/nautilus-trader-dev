# Stair-Step Exit Comparison — Results

NQ `NQ.v.0` 2021-2024, 1s-OHLC execution, safe-replay fills (0 phantom by construction). Cost: PRIMARY = entry 0 / exit 0.5 tick / PT 0 / $5 RT. STRESS = exit 1.0 tick. Warmed entries only.

Entries: 39,953 (A=39,468, B=29,930). cat-invalid-at-entry (V0): 1.1%.


## Population A (raw flips) — all sides

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 110,507 | -12.6 | -5.1 | -15.1 | 0.84 | 0.93 | -0.61 | -1,409,835 | 681 | 64% | 36% | 0% | 0% | 27% | 10% | 6% | -0.81 | +1.62 | -1.76 | +4.84 |
| BR10 | 110,507 | -11.1 | -4.4 | -12.8 | 0.87 | 0.94 | -1.01 | -1,229,928 | 429 | 55% | 14% | 31% | 0% | 25% | 15% | 0% | -0.85 | +1.26 | -1.35 | +2.02 |
| BR15 | 110,507 | -9.7 | -3.1 | -11.3 | 0.90 | 0.97 | -0.78 | -1,071,722 | 541 | 31% | 33% | 36% | 0% | 30% | 18% | 0% | -0.58 | +1.55 | -1.81 | +2.03 |
| V1_ladder | 110,507 | -13.6 | -6.1 | -16.1 | 0.75 | 0.88 | -0.31 | -1,509,405 | 320 | 94% | 6% | 0% | 0% | 16% | 4% | 3% | -0.41 | +1.12 | -1.04 | +2.68 |
| V2_gate_ladder | 110,507 | -12.1 | -4.6 | -14.6 | 0.73 | 0.88 | -0.28 | -1,344,530 | 246 | 58% | 5% | 0% | 37% | 14% | 3% | 2% | -0.46 | +0.99 | -0.98 | +2.40 |
| V3_struct_1m | 110,507 | -12.7 | -5.2 | -15.2 | 0.75 | 0.89 | -0.35 | -1,406,722 | 261 | 63% | 0% | 0% | 37% | 17% | 6% | 3% | -0.64 | +1.01 | -1.01 | +2.94 |
| V3_struct_5s | 110,507 | -11.1 | -3.6 | -13.6 | 0.71 | 0.89 | -0.17 | -1,223,145 | 82 | 63% | 0% | 0% | 37% | 5% | 2% | 1% | -0.27 | +0.64 | -0.94 | +1.58 |
| V4D1_ma_1m | 110,507 | -14.2 | -6.7 | -16.7 | 0.80 | 0.90 | -0.76 | -1,571,888 | 470 | 94% | 6% | 0% | 0% | 24% | 9% | 5% | -0.85 | +1.37 | -1.13 | +3.98 |
| V4D1_ma_5s | 110,507 | -11.8 | -4.3 | -14.3 | 0.65 | 0.85 | -0.18 | -1,307,565 | 62 | 100% | 0% | 0% | 0% | 5% | 2% | 1% | -0.29 | +0.60 | -0.89 | +1.51 |
| V4D2_ma_1m | 110,507 | -14.2 | -6.7 | -16.7 | 0.80 | 0.90 | -0.76 | -1,571,158 | 480 | 93% | 7% | 0% | 0% | 24% | 9% | 5% | -0.86 | +1.37 | -1.13 | +4.02 |
| V4D2_ma_5s | 110,507 | -12.2 | -4.7 | -14.7 | 0.66 | 0.85 | -0.16 | -1,345,245 | 73 | 100% | 0% | 0% | 0% | 6% | 2% | 1% | -0.25 | +0.63 | -0.96 | +1.58 |
| V5_hybrid_1m | 110,507 | -12.1 | -4.6 | -14.6 | 0.75 | 0.89 | -0.30 | -1,333,065 | 220 | 63% | 0% | 0% | 37% | 15% | 5% | 3% | -0.50 | +0.93 | -0.97 | +2.81 |
| V5_hybrid_5s | 110,507 | -11.8 | -4.3 | -14.3 | 0.73 | 0.89 | -0.27 | -1,301,650 | 106 | 63% | 0% | 0% | 37% | 7% | 2% | 1% | -0.50 | +0.75 | -0.95 | +1.76 |

## Population B (bar1-confirmed) — all sides

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 47,068 | -10.5 | -3.0 | -13.0 | 0.91 | 0.97 | -0.78 | -549,288 | 1125 | 0% | 100% | 0% | 0% | 40% | 14% | 10% | -0.48 | +2.24 | -2.89 | +6.25 |
| BR10 | 47,068 | -12.3 | -5.5 | -14.0 | 0.86 | 0.93 | -1.01 | -582,315 | 398 | 58% | 11% | 31% | 0% | 26% | 15% | 0% | -0.89 | +1.25 | -1.31 | +2.02 |
| BR15 | 47,068 | -10.3 | -3.7 | -11.9 | 0.90 | 0.96 | -0.83 | -494,675 | 534 | 35% | 27% | 37% | 0% | 31% | 18% | 0% | -0.58 | +1.59 | -1.76 | +2.03 |
| V1_ladder | 47,068 | -16.4 | -8.9 | -18.9 | 0.72 | 0.83 | -0.32 | -781,820 | 317 | 94% | 6% | 0% | 0% | 16% | 4% | 3% | -0.42 | +1.11 | -1.01 | +2.66 |
| V2_gate_ladder | 47,068 | -14.5 | -7.0 | -17.0 | 0.69 | 0.83 | -0.28 | -692,885 | 248 | 56% | 5% | 0% | 39% | 13% | 3% | 2% | -0.50 | +0.96 | -0.94 | +2.33 |
| V3_struct_1m | 47,068 | -14.3 | -6.8 | -16.8 | 0.73 | 0.86 | -0.34 | -677,272 | 245 | 61% | 0% | 0% | 39% | 16% | 6% | 3% | -0.67 | +0.97 | -0.97 | +2.90 |
| V3_struct_5s | 47,068 | -13.1 | -5.6 | -15.6 | 0.67 | 0.84 | -0.18 | -617,520 | 75 | 61% | 0% | 0% | 39% | 5% | 2% | 1% | -0.33 | +0.63 | -0.92 | +1.56 |
| V4D1_ma_1m | 47,068 | -15.5 | -8.0 | -18.0 | 0.80 | 0.89 | -0.77 | -737,855 | 469 | 95% | 5% | 0% | 0% | 24% | 9% | 5% | -0.89 | +1.36 | -1.08 | +4.01 |
| V4D1_ma_5s | 47,068 | -14.2 | -6.7 | -16.7 | 0.60 | 0.78 | -0.17 | -669,125 | 55 | 100% | 0% | 0% | 0% | 5% | 2% | 1% | -0.32 | +0.57 | -0.87 | +1.42 |
| V4D2_ma_1m | 47,068 | -15.2 | -7.7 | -17.7 | 0.80 | 0.89 | -0.77 | -726,420 | 478 | 94% | 6% | 0% | 0% | 24% | 9% | 5% | -0.89 | +1.36 | -1.08 | +4.05 |
| V4D2_ma_5s | 47,068 | -14.5 | -7.0 | -17.0 | 0.63 | 0.79 | -0.13 | -682,260 | 68 | 100% | 0% | 0% | 0% | 5% | 2% | 1% | -0.20 | +0.62 | -0.94 | +1.53 |
| V5_hybrid_1m | 47,068 | -14.1 | -6.6 | -16.6 | 0.72 | 0.85 | -0.30 | -668,665 | 211 | 61% | 0% | 0% | 39% | 15% | 5% | 3% | -0.50 | +0.90 | -0.93 | +2.77 |
| V5_hybrid_5s | 47,068 | -13.6 | -6.1 | -16.1 | 0.70 | 0.84 | -0.27 | -644,952 | 105 | 61% | 0% | 0% | 39% | 7% | 2% | 1% | -0.50 | +0.75 | -0.93 | +1.75 |

## The key question: loser tail vs runner tail (Population A)

Cut the loser tail (bottom-10% mean, less negative = better) WITHOUT cutting the runner tail (% captured +2/+3 ATR, top-10% mean)?

| version | net/tr | loser bot10 (ATR) | capt+2 | capt+3 | runner top10 (ATR) | giveback (ATR) |
| --- | --- | --- | --- | --- | --- | --- |
| V0_regime | -12.6 | -1.76 | 10% | 6% | +4.84 | +1.62 |
| BR10 | -11.1 | -1.35 | 15% | 0% | +2.02 | +1.26 |
| BR15 | -9.7 | -1.81 | 18% | 0% | +2.03 | +1.55 |
| V1_ladder | -13.6 | -1.04 | 4% | 3% | +2.68 | +1.12 |
| V2_gate_ladder | -12.1 | -0.98 | 3% | 2% | +2.40 | +0.99 |
| V3_struct_1m | -12.7 | -1.01 | 6% | 3% | +2.94 | +1.01 |
| V3_struct_5s | -11.1 | -0.94 | 2% | 1% | +1.58 | +0.64 |
| V4D1_ma_1m | -14.2 | -1.13 | 9% | 5% | +3.98 | +1.37 |
| V4D1_ma_5s | -11.8 | -0.89 | 2% | 1% | +1.51 | +0.60 |
| V4D2_ma_1m | -14.2 | -1.13 | 9% | 5% | +4.02 | +1.37 |
| V4D2_ma_5s | -12.2 | -0.96 | 2% | 1% | +1.58 | +0.63 |
| V5_hybrid_1m | -12.1 | -0.97 | 5% | 3% | +2.81 | +0.93 |
| V5_hybrid_5s | -11.8 | -0.95 | 2% | 1% | +1.76 | +0.75 |

## Long-only cut (Population A)


## Population A — LONG only

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 55,254 | -12.0 | -4.5 | -14.5 | 0.85 | 0.94 | -0.60 | -680,198 | 669 | 63% | 37% | 0% | 0% | 27% | 10% | 7% | -0.81 | +1.59 | -1.71 | +4.74 |
| BR10 | 55,254 | -10.7 | -4.0 | -12.5 | 0.87 | 0.95 | -1.01 | -596,715 | 460 | 55% | 14% | 31% | 0% | 25% | 15% | 0% | -0.83 | +1.27 | -1.33 | +2.02 |
| BR15 | 55,254 | -9.2 | -2.6 | -10.8 | 0.90 | 0.97 | -0.76 | -511,868 | 571 | 31% | 33% | 36% | 0% | 29% | 18% | 0% | -0.56 | +1.55 | -1.78 | +2.03 |
| V1_ladder | 55,254 | -12.8 | -5.3 | -15.3 | 0.77 | 0.89 | -0.31 | -716,498 | 338 | 93% | 7% | 0% | 0% | 16% | 4% | 3% | -0.41 | +1.12 | -1.02 | +2.73 |
| V2_gate_ladder | 55,254 | -11.5 | -4.0 | -14.0 | 0.75 | 0.90 | -0.27 | -641,975 | 254 | 58% | 5% | 0% | 37% | 13% | 4% | 2% | -0.46 | +0.99 | -0.95 | +2.43 |
| V3_struct_1m | 55,254 | -11.7 | -4.2 | -14.2 | 0.77 | 0.91 | -0.33 | -652,680 | 269 | 63% | 0% | 0% | 37% | 16% | 6% | 3% | -0.63 | +0.99 | -0.98 | +2.90 |
| V3_struct_5s | 55,254 | -10.6 | -3.1 | -13.1 | 0.71 | 0.90 | -0.16 | -585,698 | 74 | 63% | 0% | 0% | 37% | 5% | 2% | 1% | -0.25 | +0.62 | -0.92 | +1.53 |
| V4D1_ma_1m | 55,254 | -13.1 | -5.6 | -15.6 | 0.82 | 0.91 | -0.76 | -733,750 | 486 | 94% | 6% | 0% | 0% | 24% | 9% | 5% | -0.84 | +1.35 | -1.10 | +3.93 |
| V4D1_ma_5s | 55,254 | -11.4 | -3.9 | -13.9 | 0.66 | 0.86 | -0.17 | -630,850 | 61 | 100% | 0% | 0% | 0% | 5% | 2% | 1% | -0.29 | +0.58 | -0.88 | +1.47 |
| V4D2_ma_1m | 55,254 | -13.0 | -5.5 | -15.5 | 0.82 | 0.92 | -0.76 | -725,440 | 497 | 93% | 7% | 0% | 0% | 24% | 9% | 5% | -0.85 | +1.35 | -1.10 | +3.98 |
| V4D2_ma_5s | 55,254 | -11.9 | -4.4 | -14.4 | 0.67 | 0.86 | -0.15 | -657,645 | 71 | 100% | 0% | 0% | 0% | 5% | 2% | 1% | -0.22 | +0.60 | -0.93 | +1.53 |
| V5_hybrid_1m | 55,254 | -11.3 | -3.8 | -13.8 | 0.76 | 0.91 | -0.29 | -627,348 | 216 | 63% | 0% | 0% | 37% | 15% | 5% | 3% | -0.50 | +0.91 | -0.93 | +2.77 |
| V5_hybrid_5s | 55,254 | -11.4 | -3.9 | -13.9 | 0.73 | 0.90 | -0.27 | -627,810 | 97 | 63% | 0% | 0% | 37% | 6% | 2% | 1% | -0.50 | +0.74 | -0.92 | +1.73 |

## Per-year net $/tr (Population A, primary cost)

| version | 2021 | 2022 | 2023 | 2024 |
| --- | --- | --- | --- | --- |
| V0_regime | -12.7 | -12.6 | -14.4 | -10.8 |
| BR10 | -11.5 | -11.6 | -11.4 | -9.9 |
| BR15 | -11.0 | -8.9 | -10.3 | -8.5 |
| V1_ladder | -13.2 | -15.2 | -13.0 | -13.0 |
| V2_gate_ladder | -11.7 | -13.2 | -12.2 | -11.2 |
| V3_struct_1m | -11.9 | -15.0 | -11.9 | -12.1 |
| V3_struct_5s | -10.6 | -12.3 | -11.5 | -10.0 |
| V4D1_ma_1m | -13.1 | -16.3 | -14.3 | -13.0 |
| V4D1_ma_5s | -11.3 | -13.3 | -12.0 | -10.7 |
| V4D2_ma_1m | -13.3 | -16.3 | -14.3 | -12.9 |
| V4D2_ma_5s | -11.6 | -13.9 | -12.4 | -10.8 |
| V5_hybrid_1m | -11.0 | -14.2 | -11.7 | -11.4 |
| V5_hybrid_5s | -11.1 | -12.8 | -12.1 | -11.2 |

# VERDICT — Can stair-step protection cut the loser tail without cutting the runner tail?

## NO. And the issue is not stop design.

**0 of 208 cells** (13 versions × {A,B} × {long,short} × 4 years, n≥500) are net-positive.
Every version is **gross-negative** before costs (−3.1 to −6.1 $/tr pooled A),
net −9.7 to −13.6 $/tr, **0/4 years positive for every version**. Best single
cell anywhere = −$4.1/tr. Least-bad overall = BR15 (wide fixed bracket) at
−$9.7/tr pooled, −$8.5 best year — still negative every year.

## The loser/runner trade-off is structural (the core finding)
Tight 5s trails (V3/V4/V5_5s) **halve the loser tail** (bot-10% −1.76 → −0.90 ATR)
and **slash giveback** (1.62 → 0.62 ATR) — exactly the protection requested. But
they **also halve the runner tail** (top-10% +4.84 → ~+1.55 ATR) and crush +3 ATR
capture (6% → 1%). The two effects cancel; net/tr stays flat and deeply negative.
You cannot keep the runners while cutting the losers on this signal — the same
volatility that produces the loser tail produces the runner tail.

Per the pre-registered falsification: **if no, the issue is not stop design.**
The entry signal has no gross edge; no exit overlay (ladder, structure trail,
corrected-MA, hybrid, fixed bracket) rescues it. Consistent with the entire prior
body of work on the 1m regime-flip class.

## What DID show a consistent (small) effect
- **Prove-it gate**: V1→V2 (add gate to ladder) = **+$1.4 to +$1.7/tr** across
  both/long/short — the only component with a robust positive sign (cuts
  net-negative trades at +30/+60s, per the DD-feasibility study). Real but far
  too small to reach profitability (base ≈ −$13/tr).
- **Corrected MA stall trail did NOT revive the dead stall system** — V4 still
  negative; the 1m-clock MA versions are the WORST (−$16 to −$22/tr in 2022,
  longs) because a slow MA holds losers.
- Wider beats tighter only because it churns less cost (BR15 > BR10 > trails),
  not because of any edge.

## Bottom line
Exit management is not the missing piece. The 1m regime-flip entry is
gross-negative and the loser tail and runner tail are the same distribution seen
from two ends — protecting one necessarily forfeits the other. Real improvement
needs a different ENTRY (orderflow / book microstructure), not a better stop.

## Methodology notes
Offline safe-replay (0 phantom fills by construction; inline fill bit-identical
to safe_replay at_or_worse_close, parity-tested 0/20000). Realistic costs
(entry 0 / exit 0.5 tick / PT 0 / $5 RT). lookahead-auditor: 0 CRITICAL.
Long-only screen via slicing; a true long-only NT rerun would be required before
any long-side deployment claim — but there is no positive long-side cell to
pursue.

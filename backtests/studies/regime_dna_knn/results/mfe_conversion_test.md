# MFE Conversion Test (1s precision) — harvest the move before the round-trip?

OOS 2025-26 Bar-4-entry survivors with 1s path: **30,730**. Entry = Bar 4 open. All arm/trail/BE/stop detection on **1s bars** (REQUIRED — 1m arming sign-flips this study class). Intrabar = adverse-first. PT = limit fill (no slip); stops = at_or_worse_close − slip; cap = 1m close − slip. Costs $20/pt, $5 RT, 0.5t/1.0t slip.

**Parity gate (replay-vs-runtime, scalar re-sim of 500 trades, SL1.25/arm1.0/trail0.5/flip):** median |Δ| = $0.00/tr, max $0.00 → PASS ✅ (≤ $5).

## Passive baselines (entry → cap close, no active exit)
| Cap | n | Win% | Net/tr | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- |
| Bar10 | 30,730 | 41.2% | $-12.79 | $-9.66 | $-22.25 |
| Bar15 | 30,730 | 35.1% | $-13.97 | $-10.81 | $-23.53 |
| flip | 30,730 | 29.9% | $-15.61 | $-9.31 | $-34.67 |

## Conversion grid — net $/trade (pooled OOS), unfiltered Bar-4 population

Cell = mean net $/tr. ✅ = net-positive in BOTH 2025 and 2026.

| Init SL | Arm | Action | Bar10 | Bar15 | flip |
| --- | --- | --- | --- | --- | --- |
| 1.0 | 0.75 | pt | $-12.97 | $-13.34 | $-13.40 |
| 1.0 | 0.75 | be | $-19.57 | $-20.56 | $-22.55 |
| 1.0 | 0.75 | trail0.5 | $-20.48 | $-20.85 | $-21.75 |
| 1.0 | 0.75 | trail0.75 | $-20.78 | $-21.49 | $-23.96 |
| 1.0 | 1.0 | pt | $-13.42 | $-13.48 | $-13.51 |
| 1.0 | 1.0 | be | $-19.25 | $-20.59 | $-22.62 |
| 1.0 | 1.0 | trail0.5 | $-21.08 | $-21.24 | $-21.57 |
| 1.0 | 1.0 | trail0.75 | $-20.47 | $-21.08 | $-22.19 |
| 1.0 | 1.5 | pt | $-14.66 | $-15.12 | $-15.57 |
| 1.0 | 1.5 | be | $-18.19 | $-19.86 | $-21.44 |
| 1.0 | 1.5 | trail0.5 | $-20.15 | $-21.60 | $-22.56 |
| 1.0 | 1.5 | trail0.75 | $-19.45 | $-21.39 | $-22.72 |
| 1.25 | 0.75 | pt | $-12.33 | $-12.88 | $-13.02 |
| 1.25 | 0.75 | be | $-19.55 | $-20.85 | $-23.53 |
| 1.25 | 0.75 | trail0.5 | $-20.44 | $-21.17 | $-22.24 |
| 1.25 | 0.75 | trail0.75 | $-20.70 | $-21.80 | $-24.82 |
| 1.25 | 1.0 | pt | $-12.59 | $-12.88 | $-13.00 |
| 1.25 | 1.0 | be | $-18.82 | $-20.48 | $-23.39 |
| 1.25 | 1.0 | trail0.5 | $-20.82 | $-21.30 | $-22.04 |
| 1.25 | 1.0 | trail0.75 | $-20.25 | $-21.25 | $-22.91 |
| 1.25 | 1.5 | pt | $-13.85 | $-14.50 | $-14.95 |
| 1.25 | 1.5 | be | $-17.55 | $-19.39 | $-22.05 |
| 1.25 | 1.5 | trail0.5 | $-19.52 | $-21.43 | $-22.50 |
| 1.25 | 1.5 | trail0.75 | $-18.96 | $-21.41 | $-23.10 |
| 1.5 | 0.75 | pt | $-11.61 | $-12.07 | $-12.21 |
| 1.5 | 0.75 | be | $-19.19 | $-20.88 | $-23.31 |
| 1.5 | 0.75 | trail0.5 | $-20.09 | $-21.08 | $-22.13 |
| 1.5 | 0.75 | trail0.75 | $-20.37 | $-21.83 | $-24.77 |
| 1.5 | 1.0 | pt | $-11.73 | $-12.05 | $-12.10 |
| 1.5 | 1.0 | be | $-18.35 | $-20.51 | $-23.02 |
| 1.5 | 1.0 | trail0.5 | $-20.41 | $-21.28 | $-21.77 |
| 1.5 | 1.0 | trail0.75 | $-19.85 | $-21.30 | $-22.63 |
| 1.5 | 1.5 | pt | $-13.20 | $-13.77 | $-14.18 |
| 1.5 | 1.5 | be | $-17.18 | $-19.57 | $-21.88 |
| 1.5 | 1.5 | trail0.5 | $-19.13 | $-21.24 | $-22.17 |
| 1.5 | 1.5 | trail0.75 | $-18.58 | $-21.32 | $-22.52 |

## Win%/detail for the best pooled cell + both-year survivors

- Best pooled cell: **SL1.5 / arm0.75 / pt / Bar10** → $-11.61/tr (win 58.6%, 2025 $-9.05, 2026 $-19.36).
- Both-year-positive cells (unfiltered): **0 / 108**.
- Both-year-positive cells (reject worst 40% by Model B QF risk): **0 / 108**.

## Verdict

> [!WARNING]
> **NO — even with 1s-precision active exits, no cell is net-positive in both years.** The move is real but un-harvestable: arming after the trade proves itself is already too late (the round-trip beats the trail), and tight initial stops bleed the adverse-path trades. The conversion problem is structural, not a tuning miss. Consistent with [[post_bar3_survivor_not_monetizable]] — entries have reach, exits fail.
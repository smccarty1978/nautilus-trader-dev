# Bar1-Confirmed Stair-Step Validation Study

Population: Bar1-confirmed regime flips ONLY (Population B), NQ `NQ.v.0` 2021-2024, warmed. n entries = 29,930. Same audited replay engine, same 13 versions, same costs (PRIMARY: entry 0 / exit 0.5 tick / PT 0 / $5 RT; STRESS: exit 1.0 tick). 0 phantom fills.

> Interpretation rule honored: this study asks only whether exits improve monetization of the BEST-confirmed population, on its own terms.

## 1. Full metrics

### All Bar1 (both sides) — pooled 2021-2024

| version | n | gross_tr | net_tr | stress_tr | pf_gross | pf_net | max_dd | win | lose | giveback | mfe_cap | capt2 | capt3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 47,068 | -3.0 | -10.5 | -13.0 | 0.97 | 0.91 | -549,288 | 33% | 67% | +2.24 | -0.48 | 14% | 10% |
| BR10 | 47,068 | -5.5 | -12.3 | -14.0 | 0.93 | 0.86 | -582,315 | 32% | 68% | +1.25 | -0.89 | 15% | 0% |
| BR15 | 47,068 | -3.7 | -10.3 | -11.9 | 0.96 | 0.90 | -494,675 | 39% | 61% | +1.59 | -0.58 | 18% | 0% |
| V1_ladder | 47,068 | -8.9 | -16.4 | -18.9 | 0.83 | 0.72 | -781,820 | 24% | 76% | +1.11 | -0.42 | 4% | 3% |
| V2_gate_ladder | 47,068 | -7.0 | -14.5 | -17.0 | 0.83 | 0.69 | -692,885 | 19% | 81% | +0.96 | -0.50 | 3% | 2% |
| V3_struct_1m | 47,068 | -6.8 | -14.3 | -16.8 | 0.86 | 0.73 | -677,272 | 19% | 81% | +0.97 | -0.67 | 6% | 3% |
| V3_struct_5s | 47,068 | -5.6 | -13.1 | -15.6 | 0.84 | 0.67 | -617,520 | 30% | 70% | +0.63 | -0.33 | 2% | 1% |
| V4D1_ma_1m | 47,068 | -8.0 | -15.5 | -18.0 | 0.89 | 0.80 | -737,855 | 23% | 77% | +1.36 | -0.89 | 9% | 5% |
| V4D1_ma_5s | 47,068 | -6.7 | -14.2 | -16.7 | 0.78 | 0.60 | -669,125 | 28% | 72% | +0.57 | -0.32 | 2% | 1% |
| V4D2_ma_1m | 47,068 | -7.7 | -15.2 | -17.7 | 0.89 | 0.80 | -726,420 | 23% | 77% | +1.36 | -0.89 | 9% | 5% |
| V4D2_ma_5s | 47,068 | -7.0 | -14.5 | -17.0 | 0.79 | 0.63 | -682,260 | 31% | 69% | +0.62 | -0.20 | 2% | 1% |
| V5_hybrid_1m | 47,068 | -6.6 | -14.1 | -16.6 | 0.85 | 0.72 | -668,665 | 15% | 85% | +0.90 | -0.50 | 5% | 3% |
| V5_hybrid_5s | 47,068 | -6.1 | -13.6 | -16.1 | 0.84 | 0.70 | -644,952 | 26% | 74% | +0.75 | -0.50 | 2% | 1% |

### Bar1 LONG-only — pooled

| version | n | gross_tr | net_tr | stress_tr | pf_gross | pf_net | max_dd | win | lose | giveback | mfe_cap | capt2 | capt3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 23,856 | -1.8 | -9.3 | -11.8 | 0.98 | 0.92 | -251,858 | 34% | 66% | +2.16 | -0.46 | 15% | 10% |
| BR10 | 23,856 | -5.5 | -12.2 | -13.9 | 0.93 | 0.86 | -302,155 | 32% | 68% | +1.27 | -0.88 | 15% | 0% |
| BR15 | 23,856 | -3.9 | -10.5 | -12.0 | 0.96 | 0.90 | -259,228 | 38% | 62% | +1.58 | -0.55 | 18% | 0% |
| V1_ladder | 23,856 | -8.2 | -15.7 | -18.2 | 0.84 | 0.73 | -381,895 | 24% | 76% | +1.11 | -0.43 | 4% | 3% |
| V2_gate_ladder | 23,856 | -6.2 | -13.7 | -16.2 | 0.85 | 0.71 | -334,875 | 19% | 81% | +0.95 | -0.50 | 3% | 2% |
| V3_struct_1m | 23,856 | -6.1 | -13.6 | -16.1 | 0.87 | 0.74 | -328,468 | 19% | 81% | +0.95 | -0.67 | 6% | 3% |
| V3_struct_5s | 23,856 | -5.6 | -13.1 | -15.6 | 0.83 | 0.66 | -315,085 | 31% | 69% | +0.60 | -0.32 | 2% | 0% |
| V4D1_ma_1m | 23,856 | -7.8 | -15.3 | -17.8 | 0.89 | 0.80 | -368,402 | 24% | 76% | +1.34 | -0.90 | 9% | 5% |
| V4D1_ma_5s | 23,856 | -6.7 | -14.2 | -16.7 | 0.77 | 0.59 | -341,062 | 28% | 72% | +0.55 | -0.30 | 2% | 0% |
| V4D2_ma_1m | 23,856 | -7.4 | -14.9 | -17.4 | 0.90 | 0.81 | -359,168 | 24% | 76% | +1.34 | -0.90 | 9% | 5% |
| V4D2_ma_5s | 23,856 | -6.8 | -14.3 | -16.8 | 0.79 | 0.62 | -343,892 | 31% | 69% | +0.58 | -0.20 | 2% | 1% |
| V5_hybrid_1m | 23,856 | -5.8 | -13.3 | -15.8 | 0.86 | 0.73 | -321,842 | 15% | 85% | +0.88 | -0.50 | 5% | 3% |
| V5_hybrid_5s | 23,856 | -6.4 | -13.9 | -16.4 | 0.84 | 0.69 | -333,332 | 25% | 75% | +0.72 | -0.50 | 2% | 1% |

### Bar1 SHORT-only — pooled

| version | n | gross_tr | net_tr | stress_tr | pf_gross | pf_net | max_dd | win | lose | giveback | mfe_cap | capt2 | capt3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 23,212 | -4.2 | -11.7 | -14.2 | 0.96 | 0.90 | -300,028 | 31% | 69% | +2.32 | -0.50 | 14% | 10% |
| BR10 | 23,212 | -5.6 | -12.3 | -14.0 | 0.93 | 0.86 | -288,635 | 32% | 68% | +1.24 | -0.89 | 16% | 0% |
| BR15 | 23,212 | -3.6 | -10.1 | -11.7 | 0.96 | 0.90 | -243,255 | 39% | 61% | +1.59 | -0.60 | 19% | 0% |
| V1_ladder | 23,212 | -9.7 | -17.2 | -19.7 | 0.81 | 0.70 | -401,790 | 23% | 77% | +1.12 | -0.42 | 4% | 2% |
| V2_gate_ladder | 23,212 | -7.9 | -15.4 | -17.9 | 0.81 | 0.68 | -358,670 | 19% | 81% | +0.97 | -0.50 | 3% | 2% |
| V3_struct_1m | 23,212 | -7.5 | -15.0 | -17.5 | 0.85 | 0.73 | -351,212 | 18% | 82% | +0.99 | -0.67 | 6% | 3% |
| V3_struct_5s | 23,212 | -5.5 | -13.0 | -15.5 | 0.84 | 0.68 | -303,945 | 30% | 70% | +0.67 | -0.33 | 2% | 1% |
| V4D1_ma_1m | 23,212 | -8.2 | -15.7 | -18.2 | 0.88 | 0.80 | -375,788 | 22% | 78% | +1.39 | -0.88 | 8% | 5% |
| V4D1_ma_5s | 23,212 | -6.7 | -14.2 | -16.7 | 0.78 | 0.61 | -330,170 | 27% | 73% | +0.60 | -0.33 | 2% | 1% |
| V4D2_ma_1m | 23,212 | -8.1 | -15.6 | -18.1 | 0.89 | 0.80 | -373,062 | 22% | 78% | +1.40 | -0.89 | 8% | 5% |
| V4D2_ma_5s | 23,212 | -7.1 | -14.6 | -17.1 | 0.80 | 0.63 | -340,295 | 31% | 69% | +0.67 | -0.20 | 2% | 1% |
| V5_hybrid_1m | 23,212 | -7.4 | -14.9 | -17.4 | 0.83 | 0.71 | -348,098 | 15% | 85% | +0.92 | -0.50 | 5% | 3% |
| V5_hybrid_5s | 23,212 | -5.9 | -13.4 | -15.9 | 0.85 | 0.70 | -313,195 | 26% | 74% | +0.76 | -0.50 | 3% | 1% |

## 2. Critical comparison (decision tables)

### Decision table — All Bar1

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.89 | +2.24 | +6.25 | 10% | -10.5 |
| BR10 | -1.31 | +1.25 | +2.02 | 0% | -12.3 |
| BR15 | -1.76 | +1.59 | +2.03 | 0% | -10.3 |
| V1_ladder | -1.01 | +1.11 | +2.66 | 3% | -16.4 |
| V2_gate_ladder | -0.94 | +0.96 | +2.33 | 2% | -14.5 |
| V3_struct_1m | -0.97 | +0.97 | +2.90 | 3% | -14.3 |
| V3_struct_5s | -0.92 | +0.63 | +1.56 | 1% | -13.1 |
| V4D1_ma_1m | -1.08 | +1.36 | +4.01 | 5% | -15.5 |
| V4D1_ma_5s | -0.87 | +0.57 | +1.42 | 1% | -14.2 |
| V4D2_ma_1m | -1.08 | +1.36 | +4.05 | 5% | -15.2 |
| V4D2_ma_5s | -0.94 | +0.62 | +1.53 | 1% | -14.5 |
| V5_hybrid_1m | -0.93 | +0.90 | +2.77 | 3% | -14.1 |
| V5_hybrid_5s | -0.93 | +0.75 | +1.75 | 1% | -13.6 |

### Decision table — Bar1 LONG-only

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.83 | +2.16 | +5.99 | 10% | -9.3 |
| BR10 | -1.30 | +1.27 | +2.02 | 0% | -12.2 |
| BR15 | -1.76 | +1.58 | +2.03 | 0% | -10.5 |
| V1_ladder | -1.00 | +1.11 | +2.68 | 3% | -15.7 |
| V2_gate_ladder | -0.93 | +0.95 | +2.34 | 2% | -13.7 |
| V3_struct_1m | -0.96 | +0.95 | +2.84 | 3% | -13.6 |
| V3_struct_5s | -0.91 | +0.60 | +1.49 | 0% | -13.1 |
| V4D1_ma_1m | -1.07 | +1.34 | +3.90 | 5% | -15.3 |
| V4D1_ma_5s | -0.87 | +0.55 | +1.36 | 0% | -14.2 |
| V4D2_ma_1m | -1.07 | +1.34 | +3.95 | 5% | -14.9 |
| V4D2_ma_5s | -0.94 | +0.58 | +1.46 | 1% | -14.3 |
| V5_hybrid_1m | -0.92 | +0.88 | +2.75 | 3% | -13.3 |
| V5_hybrid_5s | -0.91 | +0.72 | +1.70 | 1% | -13.9 |

### Decision table — Bar1 SHORT-only

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.95 | +2.32 | +6.51 | 10% | -11.7 |
| BR10 | -1.32 | +1.24 | +2.02 | 0% | -12.3 |
| BR15 | -1.76 | +1.59 | +2.03 | 0% | -10.1 |
| V1_ladder | -1.02 | +1.12 | +2.63 | 2% | -17.2 |
| V2_gate_ladder | -0.95 | +0.97 | +2.32 | 2% | -15.4 |
| V3_struct_1m | -0.98 | +0.99 | +2.97 | 3% | -15.0 |
| V3_struct_5s | -0.93 | +0.67 | +1.63 | 1% | -13.0 |
| V4D1_ma_1m | -1.09 | +1.39 | +4.11 | 5% | -15.7 |
| V4D1_ma_5s | -0.88 | +0.60 | +1.49 | 1% | -14.2 |
| V4D2_ma_1m | -1.09 | +1.40 | +4.14 | 5% | -15.6 |
| V4D2_ma_5s | -0.95 | +0.67 | +1.60 | 1% | -14.6 |
| V5_hybrid_1m | -0.95 | +0.92 | +2.80 | 3% | -14.9 |
| V5_hybrid_5s | -0.94 | +0.76 | +1.80 | 1% | -13.4 |

## 3. Per-year net $/trade (All Bar1, primary cost)

| version | 2021 | 2022 | 2023 | 2024 | yrs+ |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -12.1 | -12.8 | -12.0 | -5.0 | 0/4 |
| BR10 | -12.0 | -17.5 | -9.4 | -10.1 | 0/4 |
| BR15 | -10.5 | -16.3 | -7.4 | -7.0 | 0/4 |
| V1_ladder | -16.2 | -19.2 | -14.8 | -15.6 | 0/4 |
| V2_gate_ladder | -13.6 | -18.2 | -13.5 | -12.9 | 0/4 |
| V3_struct_1m | -14.0 | -18.1 | -11.5 | -13.6 | 0/4 |
| V3_struct_5s | -12.4 | -16.8 | -11.8 | -11.3 | 0/4 |
| V4D1_ma_1m | -15.8 | -18.7 | -14.1 | -13.3 | 0/4 |
| V4D1_ma_5s | -13.6 | -16.9 | -12.9 | -13.4 | 0/4 |
| V4D2_ma_1m | -16.1 | -18.0 | -13.8 | -13.1 | 0/4 |
| V4D2_ma_5s | -13.7 | -18.3 | -12.4 | -13.4 | 0/4 |
| V5_hybrid_1m | -13.2 | -16.9 | -12.5 | -13.8 | 0/4 |
| V5_hybrid_5s | -13.1 | -16.6 | -12.3 | -12.6 | 0/4 |

## 4. Validation questions

**Q1 — Does any stair-step improve expectancy vs Bar1 regime exit (V0)?**
V0 net = -10.5 $/tr. Best version = BR15 (-10.3 $/tr). 1/12 beat V0; 0/13 are net-positive. YES (some beat V0) — but NONE reach positive expectancy.

**Q2 — Any architecture that cuts the loser tail while PRESERVING the runner tail?**
V0: loser_bot10=-2.89, runner_top10=+6.25. Versions cutting loser tail (>+0.05) AND preserving runner (within 0.10): NONE. NO — every loser-tail cut comes with a runner-tail cut.

**Q3 — Is stall/MA-protection lift reproducible on Bar1?**
- V4D1_ma_1m: net -15.5 vs V0 -10.5 (lift -5.0/tr)
- V4D1_ma_5s: net -14.2 vs V0 -10.5 (lift -3.7/tr)
- V4D2_ma_1m: net -15.2 vs V0 -10.5 (lift -4.8/tr)
- V4D2_ma_5s: net -14.5 vs V0 -10.5 (lift -4.0/tr)
  => NO MA lift on Bar1.

**Q4 — Is the prove-it gate additive on Bar1 (V1 ladder -> V2 gate+ladder)?**
- all: V1=-16.4 -> V2=-14.5 (gate +1.9/tr)
- long: V1=-15.7 -> V2=-13.7 (gate +2.0/tr)
- short: V1=-17.2 -> V2=-15.4 (gate +1.8/tr)

**Q5 — If Bar1 also fails, is the remaining problem ENTRY quality, not exit quality?**
Best-confirmed population + best exit still gross = -3.0 $/tr (V0_regime); all 13 versions gross-negative. If gross is negative under the strongest entry filter AND every exit architecture, the deficit is in the ENTRY edge, not the stop. (See verdict.)


## 5. VERDICT — Bar1-confirmed population (on its own terms)

**The best exit on Bar1 is the NAKED regime exit (V0), and it is still net-negative.**
V0 = −$10.5/tr (gross −$3.0). Every protection architecture makes Bar1 WORSE,
because Bar1 has a genuinely large runner tail (top-10% +6.25 ATR, 10% capture
+3 ATR) and every stop/trail forfeits it.

- **Q1 — improve expectancy vs Bar1 regime exit? NO.** 1/12 beat V0 (BR15 by $0.2);
  **0/13 net-positive; 0/4 years positive for every version.** Best year/version
  is V0 2024 at −$5.0/tr.
- **Q2 — cut loser tail while preserving runner tail? NO.** None. The loser/runner
  trade-off is structural here too — and starker, because Bar1's runner tail is
  large (+6.25 ATR), so tight trails destroy more (top-10% +6.25 → +1.5;
  +3 ATR capture 10% → 1%).
- **Q3 — stall/MA lift reproducible? NO.** V4 MA trails are −$3.7 to −$5.0/tr
  WORSE than V0. Stall protection actively hurts the confirmed population.
- **Q4 — prove-it gate additive? YES.** V1→V2 = +$1.9/tr (all), +$2.0 long,
  +$1.8 short — the ONLY consistently positive component (cuts net-negative
  trades at +30/60s). But the base is −$16, so it lands at −$14.5. Insufficient.
- **Q5 — entry quality vs exit quality? ENTRY.** The best-confirmed population,
  under the best-performing exit (naked regime), is **gross-negative (−$3.0/tr)**;
  ALL 13 architectures are gross-negative. A deficit that survives the strongest
  entry filter AND every exit design is an ENTRY-edge deficit, not a stop deficit.

### Conclusion — exit-research branch CLOSED
Bar1 confirmation produces real runners (bigger than the unfiltered set), but not
enough net edge: 67% of Bar1 trades lose, and the best monetization of the
runners (ride naked to the regime flip) is still gross-negative. No stair-step
architecture improves it; most degrade it. The binding constraint is the entry
edge. Per the study's own rule, the exit-research branch is now closed.

(Footnote: the one combination NOT in the specified 13 is "V0 + prove-it gate"
— ride naked but cut early net-negative trades. The gate's +$1.9 effect on a
−$10.5 V0 base would land ~−$8.6/tr — still negative and still gross-bound. Out
of scope per "no new exit ideas"; noted for completeness, not pursued.)

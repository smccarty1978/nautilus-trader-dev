# V_A Exit Reconciliation — Mechanical Rules vs Regime Exit

Tests whether any mechanical exit rule outperforms the lagging regime-flip exit on the V_A trade population (NQ 2024+2025+2026 RTH).

- Population: 7,659 unfiltered V_A trades (NQ 2024+2025+2026 RTH)
- Tape: 6,203,529 per-1s-bar rows during open trades
- Cost: $5 commission + $5 tick = $10 round-trip
- Each rule re-uses the SAME entry. Only exit logic changes.
- Exit-rule precedence: rule fires first → use rule's exit. Otherwise → fall back to regime exit.

## Rule scoreboard — per-year mean $/trade

| Rule | n | Med Hold s | 2024 mean / total | 2025 mean / total | 2026 mean / total | All mean | All total | All PF | All WR |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 00_baseline_regime | 7,659 | 631 | $7.51 / $24,965 | $17.67 / $58,465 | $-18.74 / $-18,400 | $8.30 | $63,605 | 1.04 | 34.8% |
| 01_pt_cap_0.50atr | 7,659 | 86 | $-14.46 / $-48,097 | $-8.13 / $-26,895 | $-10.40 / $-10,209 | $-11.38 | $-87,146 | 0.90 | 77.1% |
| 01_pt_cap_0.75atr | 7,659 | 151 | $-10.05 / $-33,423 | $-1.39 / $-4,588 | $-13.66 / $-13,419 | $-6.96 | $-53,307 | 0.95 | 69.1% |
| 01_pt_cap_1.00atr | 7,659 | 211 | $-9.36 / $-31,124 | $2.62 / $8,657 | $-23.90 / $-23,466 | $-6.19 | $-47,399 | 0.96 | 61.8% |
| 01_pt_cap_1.50atr | 7,659 | 282 | $1.79 / $5,952 | $4.51 / $14,920 | $-17.38 / $-17,063 | $0.32 | $2,454 | 1.00 | 50.5% |
| 01_pt_cap_2.00atr | 7,659 | 391 | $1.50 / $4,993 | $5.65 / $18,694 | $-8.41 / $-8,255 | $1.92 | $14,671 | 1.01 | 42.8% |
| 02_trail_act0.50_pct0.30 | 7,659 | 91 | $-136.53 / $-454,090 | $116.70 / $386,175 | $-19.36 / $-19,010 | $-11.57 | $-88,610 | 0.97 | 76.5% |
| 02_trail_act0.50_pct0.50 | 7,659 | 116 | $-136.42 / $-453,730 | $117.10 / $387,490 | $-7.06 / $-6,930 | $-9.82 | $-75,180 | 0.97 | 75.7% |
| 02_trail_act0.50_pct0.70 | 7,659 | 151 | $-145.76 / $-484,810 | $145.54 / $481,580 | $-100.99 / $-99,175 | $-13.70 | $-104,935 | 0.96 | 70.6% |
| 02_trail_act1.00_pct0.30 | 7,659 | 211 | $-199.38 / $-663,130 | $117.94 / $390,260 | $8.09 / $7,940 | $-34.82 | $-266,665 | 0.90 | 61.5% |
| 02_trail_act1.00_pct0.50 | 7,659 | 271 | $-149.85 / $-498,385 | $119.26 / $394,615 | $113.69 / $111,640 | $0.77 | $5,890 | 1.00 | 61.4% |
| 02_trail_act1.00_pct0.70 | 7,659 | 331 | $-230.25 / $-765,820 | $156.58 / $518,125 | $71.99 / $70,690 | $-23.40 | $-179,250 | 0.93 | 60.8% |
| 03_be_stop_act0.50 | 7,659 | 211 | $-9.71 / $-32,280 | $11.59 / $38,340 | $-4.79 / $-4,700 | $-0.12 | $-920.00 | 1.00 | 13.7% |
| 03_be_stop_act1.00 | 7,659 | 391 | $-2.41 / $-8,000 | $16.48 / $54,540 | $-19.63 / $-19,280 | $3.26 | $24,970 | 1.02 | 22.1% |
| 03_be_stop_act1.50 | 7,659 | 511 | $6.52 / $21,675 | $17.14 / $56,710 | $-16.87 / $-16,565 | $7.81 | $59,850 | 1.04 | 27.6% |
| 04_time_winner_120s | 7,659 | 120 | $5.73 / $19,045 | $-7.18 / $-23,745 | $280.86 / $275,800 | $35.06 | $268,490 | 1.13 | 57.8% |
| 04_time_winner_300s | 7,659 | 300 | $-7.81 / $-25,985 | $26.89 / $88,990 | $147.49 / $144,840 | $26.85 | $205,630 | 1.08 | 52.8% |
| 04_time_winner_600s | 7,659 | 600 | $-110.21 / $-366,570 | $109.85 / $363,495 | $439.39 / $431,485 | $55.82 | $427,490 | 1.17 | 44.5% |

## Δ vs baseline (rule – baseline)

| Rule | Δ 2024 mean | Δ 2025 mean | Δ 2026 mean | Δ All mean | Δ All total |
|---|--:|--:|--:|--:|--:|
| 01_pt_cap_0.50atr | $-21.97 | $-25.80 | $8.34 | $-19.68 | $-150,751 |
| 01_pt_cap_0.75atr | $-17.55 | $-19.06 | $5.07 | $-15.26 | $-116,912 |
| 01_pt_cap_1.00atr | $-16.86 | $-15.05 | $-5.16 | $-14.49 | $-111,004 |
| 01_pt_cap_1.50atr | $-5.72 | $-13.16 | $1.36 | $-7.98 | $-61,151 |
| 01_pt_cap_2.00atr | $-6.00 | $-12.02 | $10.33 | $-6.39 | $-48,934 |
| 02_trail_act0.50_pct0.30 | $-144.03 | $99.04 | $-0.62 | $-19.87 | $-152,215 |
| 02_trail_act0.50_pct0.50 | $-143.93 | $99.43 | $11.68 | $-18.12 | $-138,785 |
| 02_trail_act0.50_pct0.70 | $-153.27 | $127.87 | $-82.26 | $-22.01 | $-168,540 |
| 02_trail_act1.00_pct0.30 | $-206.88 | $100.27 | $26.82 | $-43.12 | $-330,270 |
| 02_trail_act1.00_pct0.50 | $-157.35 | $101.59 | $132.42 | $-7.54 | $-57,715 |
| 02_trail_act1.00_pct0.70 | $-237.76 | $138.91 | $90.72 | $-31.71 | $-242,855 |
| 03_be_stop_act0.50 | $-17.21 | $-6.08 | $13.95 | $-8.42 | $-64,525 |
| 03_be_stop_act1.00 | $-9.91 | $-1.19 | $-0.90 | $-5.04 | $-38,635 |
| 03_be_stop_act1.50 | $-0.99 | $-0.53 | $1.87 | $-0.49 | $-3,755 |
| 04_time_winner_120s | $-1.78 | $-24.84 | $299.59 | $26.75 | $204,885 |
| 04_time_winner_300s | $-15.32 | $9.22 | $166.23 | $18.54 | $142,025 |
| 04_time_winner_600s | $-117.72 | $92.18 | $458.13 | $47.51 | $363,885 |

## Years positive per rule

| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |
|---|--:|---|---|---|
| 00_baseline_regime | 2/3 | ✅ | ✅ | ❌ |
| 01_pt_cap_0.50atr | 0/3 | ❌ | ❌ | ❌ |
| 01_pt_cap_0.75atr | 0/3 | ❌ | ❌ | ❌ |
| 01_pt_cap_1.00atr | 1/3 | ❌ | ✅ | ❌ |
| 01_pt_cap_1.50atr | 2/3 | ✅ | ✅ | ❌ |
| 01_pt_cap_2.00atr | 2/3 | ✅ | ✅ | ❌ |
| 02_trail_act0.50_pct0.30 | 1/3 | ❌ | ✅ | ❌ |
| 02_trail_act0.50_pct0.50 | 1/3 | ❌ | ✅ | ❌ |
| 02_trail_act0.50_pct0.70 | 1/3 | ❌ | ✅ | ❌ |
| 02_trail_act1.00_pct0.30 | 2/3 | ❌ | ✅ | ✅ |
| 02_trail_act1.00_pct0.50 | 2/3 | ❌ | ✅ | ✅ |
| 02_trail_act1.00_pct0.70 | 2/3 | ❌ | ✅ | ✅ |
| 03_be_stop_act0.50 | 1/3 | ❌ | ✅ | ❌ |
| 03_be_stop_act1.00 | 1/3 | ❌ | ✅ | ❌ |
| 03_be_stop_act1.50 | 2/3 | ✅ | ✅ | ❌ |
| 04_time_winner_120s | 2/3 | ✅ | ❌ | ✅ |
| 04_time_winner_300s | 2/3 | ❌ | ✅ | ✅ |
| 04_time_winner_600s | 2/3 | ❌ | ✅ | ✅ |

## Best rule by 3-year aggregate total $

- **04_time_winner_600s**: total $427,490 (Δ vs baseline $363,885)
- Baseline (regime exit): total $63,605

## Verdict — answers to "can we improve on regime exit?"

**Short answer: yes, mechanically — but the alpha is regime-conditional, not universal. The previous "no exit rule helps" conclusion was correct on aggregate-only metrics; per-year inspection reveals real but uneven exit alpha.**

### What worked (at aggregate)

Three time-based "cut winners" rules dominated the scoreboard:

| Rule | All Δ mean | 2024 Δ | 2025 Δ | 2026 Δ |
|---|--:|--:|--:|--:|
| **time_winner_600s** | **+$47.51** | -$117.72 | +$92.18 | +$458.13 |
| **time_winner_300s** | **+$18.54** | -$15.32 | +$9.22 | +$166.23 |
| **time_winner_120s** | **+$26.75** | -$1.78 | -$24.84 | +$299.59 |

The mechanic is asymmetric: at elapsed = T seconds, exit if winning, hold if losing. This locks in winning trades that would otherwise give back to the lagging regime exit, while letting losing trades reach the regime-exit fallback.

### Why this works (and why it's regime-dependent)

The regime exit fundamentally lags by ≥1m because it waits for a 1m flip. By the time the flip happens, the trade has typically given back a meaningful slice of MFE. The "cut winners at T" rule captures that slice — IF the trade has actually peaked early.

- **2026 (high-ATR / choppy)**: +$166-$458/trade improvement. Trades hit peak MFE quickly, then give back violently as the regime stays unstable. Exiting winners at T captures peak MFE before reversion. This is the SAME structural pattern that made the entry filter unstable in 2026.
- **2025 (smoother trends)**: modest +$9-$92 improvement. Some trades genuinely keep going past T, others give back. Net positive on aggregate.
- **2024 (best baseline year, smoothest trends)**: -$1 to -$118/trade hurt. Winners that reach T are still in the early-middle of their move; cutting them off prevents the largest wins from materializing.

This is the inverse of the entry-filter pattern. The entry filter (`flip2conf_dir_efficiency >= 0.30`) thrived in 2024-25 trending regimes and broke in the 2022 high-ATR regime. The time-cut exit thrives in the 2026 choppy regime and breaks in the 2024 trending regime. **The two findings together suggest the V_A trade population contains TWO distinct sub-distributions** — one trend-friendly (2024 long runners), one chop-friendly (2026 fast peak-then-give-back). Neither rule is right for both.

### What didn't work

- **PT caps (0.5–2.0 ATR)**: All hurt aggregate. PT_cap_2.0 is closest to neutral (-$6/trade) but still net worse. The very large winners are essential to baseline economics; capping kills them.
- **Trailing stops**: Catastrophic in 2024 (-$140 to -$240/trade), partial wins in 2025-26. Worst risk-adjusted profile of any rule tested.
- **Break-even stops**: Inert. BE-at-1.5-ATR ≈ baseline (+$7.81 vs +$8.30). Doesn't materially capture the early-MFE pattern because by the time MFE = 1.5 ATR, the trade is already deep enough that BE stops rarely trigger.

### Comparison to prior path-diagnostics study

The prior `PATH_DIAGNOSTICS_REPORT.md` concluded "no exit overlay improves baseline economics." That conclusion is consistent with this study's aggregate findings IF you require a rule to help every year. With per-year inspection, time-cuts deliver real aggregate alpha — they were missed because the prior framing emphasized cross-year robustness over per-year economics.

### Recommendation

The user's intuition — that regime exit is lagging and there should be a better mechanical alternative — is correct. But the same robustness trap that took down the entry filter applies here: the best-aggregate rule (time_winner_600s) has a -$118/trade catastrophic 2024 swing. Any deployment would need to either:
1. Accept the 2024 vulnerability as a known cost
2. Find a regime-conditional version (e.g., apply time-cut only when atr_1m > X) — but this risks the curve-fitting trap from MEMORY.md
3. Find a per-trade signal that distinguishes "early-peak then give back" trades from "slow runner" trades

Option 3 is the cleanest research path. The needed signal is essentially: "at T seconds, predict whether this trade is at peak MFE or still has runway." This is a different ML target than the previous exit-policy study (which predicted generic giveback). Worth one more pass with the trade tape now available — but should be approached cautiously given the entry-side robustness lessons.

If proceeding, the natural next study is: **train a per-trade classifier on the 1s tape to predict, at each elapsed second, whether MFE is at-or-near peak vs. still climbing**. Walk-forward by year. Test as a per-trade exit override.

## Files

- Full per-trade results per rule: `studies/v_a_exit_recon/results/trades_*.parquet`
- Summary: `studies/v_a_exit_recon/results/exit_rules_summary.parquet`
- Strategy edit (tape emission): `collectors/collector_v2/strategy.py` — `emit_trade_tape` config
- Tape runner: `collectors/collector_v2/run_with_tape.py`
- Per-cell tape: `collectors/collector_v2/results/with_tape/NQ_<year>/trade_tape.parquet`

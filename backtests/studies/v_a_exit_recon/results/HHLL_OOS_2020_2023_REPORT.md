# V_A HH/LL Progression Exit Study — OOS Validation 2020-2023

Re-applies the top 5 HH/LL exit rules from the in-sample study (NQ 2024+2025+2026) to four unseen years (NQ 2020+2021+2022+2023 RTH). Same rule definitions, same cost model, same tape-replay method. **No tuning.**

- OOS population: 14,032 V_A trades (NQ 2020-2023 RTH)
- OOS tape: 10,958,468 per-1s-bar rows
- Cost: $10 round-trip

## OOS scoreboard — per-year stats

| Rule | %fired | Med Hold s | 2020 mean / total / WR | 2021 mean / total / WR | 2022 mean / total / WR | 2023 mean / total / WR | All mean | All total | All PF | %base-W cut | %base-L improved | Top-1% share |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE_regime | 0.0% | 631 | $-9.29 / $-33,590 / 35.7% | $-23.75 / $-85,015 / 33.1% | $-13.46 / $-46,250 / 34.2% | $-14.12 / $-48,030 / 34.3% | $-15.17 | $-212,885 | 0.92 | 0.0% | 0.0% | -187.7% |
| C_lock50_30s_5 | 49.8% | 391 | $23.77 / $85,922 / 59.7% | $12.66 / $45,332 / 57.3% | $40.57 / $139,368 / 57.9% | $22.00 / $74,838 / 58.0% | $24.62 | $345,460 | 1.18 | 37.7% | 35.9% | 97.7% |
| C_lock50_5s_20 | 53.1% | 331 | $18.40 / $66,532 / 61.9% | $4.09 / $14,648 / 59.4% | $29.33 / $100,738 / 59.8% | $15.56 / $52,920 / 60.1% | $16.74 | $234,838 | 1.12 | 44.6% | 39.1% | 133.3% |
| B_be_30s_5 | 48.4% | 360 | $13.46 / $48,660 / 23.1% | $0.62 / $2,210 / 21.6% | $27.01 / $92,790 / 22.4% | $10.12 / $34,425 / 22.2% | $12.69 | $178,085 | 1.12 | 35.1% | 53.8% | 204.4% |
| C_lock50_30s_3 | 52.9% | 331 | $15.60 / $56,380 / 62.0% | $3.95 / $14,158 / 59.7% | $26.41 / $90,720 / 60.2% | $13.53 / $46,042 / 60.5% | $14.77 | $207,300 | 1.11 | 44.6% | 39.5% | 150.2% |
| C_lock25_30s_5 | 40.5% | 442 | $8.33 / $30,126 / 59.5% | $-4.63 / $-16,566 / 57.3% | $15.58 / $53,526 / 57.9% | $2.49 / $8,469 / 57.9% | $5.38 | $75,555 | 1.04 | 31.2% | 35.9% | 475.3% |

## Δ vs OOS baseline regime exit

| Rule | Δ 2020 | Δ 2021 | Δ 2022 | Δ 2023 | Δ All mean | Δ All total |
|---|--:|--:|--:|--:|--:|--:|
| C_lock50_30s_5 | $33.06 | $36.41 | $54.04 | $36.12 | $39.79 | $558,345 |
| C_lock50_5s_20 | $27.70 | $27.84 | $42.79 | $29.67 | $31.91 | $447,722 |
| B_be_30s_5 | $22.75 | $24.36 | $40.48 | $24.24 | $27.86 | $390,970 |
| C_lock50_30s_3 | $24.89 | $27.70 | $39.87 | $27.65 | $29.94 | $420,185 |
| C_lock25_30s_5 | $17.63 | $19.12 | $29.05 | $16.61 | $20.56 | $288,440 |

## Years positive per rule

| Rule | Yrs +mean OOS | 2020 ✓? | 2021 ✓? | 2022 ✓? | 2023 ✓? |
|---|--:|---|---|---|---|
| BASELINE_regime | 0/4 | ❌ | ❌ | ❌ | ❌ |
| C_lock50_30s_5 | 4/4 | ✅ | ✅ | ✅ | ✅ |
| C_lock50_5s_20 | 4/4 | ✅ | ✅ | ✅ | ✅ |
| B_be_30s_5 | 4/4 | ✅ | ✅ | ✅ | ✅ |
| C_lock50_30s_3 | 4/4 | ✅ | ✅ | ✅ | ✅ |
| C_lock25_30s_5 | 3/4 | ✅ | ❌ | ✅ | ✅ |

## In-sample (2024-26) vs OOS (2020-23) side-by-side

| Rule | IS All Mean | IS All Total | IS PF | IS Yrs+ | OOS All Mean | OOS All Total | OOS PF | OOS Yrs+ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| C_lock50_30s_5 | $54.33 | $416,148 | 1.30 | 3/3 | $24.62 | $345,460 | 1.18 | 4/4 |
| C_lock50_5s_20 | $45.06 | $345,120 | 1.26 | 3/3 | $16.74 | $234,838 | 1.12 | 4/4 |
| B_be_30s_5 | $43.62 | $334,115 | 1.32 | 3/3 | $12.69 | $178,085 | 1.12 | 4/4 |
| C_lock50_30s_3 | $41.84 | $320,452 | 1.24 | 3/3 | $14.77 | $207,300 | 1.11 | 4/4 |
| C_lock25_30s_5 | $35.90 | $274,981 | 1.20 | 3/3 | $5.38 | $75,555 | 1.04 | 3/4 |

## Verdict — answers to the four key questions

**1. Does the edge persist pre-2024?**
**Yes — strongly.** Four of five rules are positive in all 4 OOS years (2020, 2021, 2022, 2023). Best rule (C_lock50_30s_5): OOS total +$345,460 vs baseline -$212,885, a **$558,345 swing across 14,032 trades**. OOS mean +$24.62/trade (vs baseline -$15.17). PF 1.18 (vs baseline 0.92).

**2. Does 2022 still behave poorly?**
**No — 2022 is now the BEST year.** Baseline 2022: -$13.46/trade. C_lock50_30s_5 in 2022: **+$40.57/trade, +$139,368 total**. The 2022 regime that broke every entry filter and most exit rules ("trades stall, then violently reverse") is exactly the pattern the structural lock-50% rule was designed to protect against. WR jumps from 34.2% to 57.9%.

**3. Does the rule still reduce outlier dependence?**
**Yes.** Top-1% share for C_lock50_30s_5:
- Baseline OOS: -187.7% (baseline negative aggregate; outliers can't even keep it afloat)
- C_lock50_30s_5 OOS: **97.7%**
- Both are dramatically less outlier-dependent than baseline IS (506%)

**4. Does WR improvement hold?**
**Yes.** Across OOS years C_lock50_30s_5 delivers **57.3-62.0% WR** (vs 33-36% baseline). The win-rate transformation is consistent IS and OOS — the small protected wins from lock-50% reliably push WR above 55% in every regime tested.

## In-sample vs OOS — robust shrinkage, no breakdown

| Rule | IS Mean (2024-26) | OOS Mean (2020-23) | Shrinkage |
|---|--:|--:|--:|
| C_lock50_30s_5 | $54.33 | **$24.62** | 55% retention |
| C_lock50_5s_20 | $45.06 | $16.74 | 37% |
| B_be_30s_5 | $43.62 | $12.69 | 29% |
| C_lock50_30s_3 | $41.84 | $14.77 | 35% |
| C_lock25_30s_5 | $35.90 | $5.38 | 15% |

OOS shrinkage is real (selected the best 5 of 36 IS rules), but **all 5 rules remain positive on aggregate AND in 2022 specifically.** That's an unusual robustness signature in this research series — most prior promising findings broke down on the unseen years.

The shrinkage hierarchy is informative: rules with **larger lock buffer (lock50 over lock25)** and **30s granularity over 5s** retain more of their IS edge. C_lock50_30s_5 is the cleanest selection.

## Combined 7-year picture (best rule: C_lock50_30s_5)

| Period | Total trades | Mean $ | Total $ | PF | Yrs positive |
|---|--:|--:|--:|--:|--:|
| Baseline 2020-26 | 21,691 | -$6.88 | -$149,280 | 0.97 | 2/7 |
| **C_lock50_30s_5 2020-26** | 21,691 | **+$35.10** | **+$761,608** | **1.23** | **7/7** |
| Δ vs baseline | — | +$41.98 | +$910,888 | +0.26 | +5 years |

**Every year 2020-2026 becomes positive** under this single fixed rule. This is the strongest cross-year exit finding in the entire research series, and the only V_A-derived result so far that delivers positive economics in 2022 *and* 2026 simultaneously without curve-fit-trap signatures.

## Critical caveats before deployment claim

1. **Tape-replay vs NT runtime parity not yet confirmed.** The intra-bar resolution (low for long, high for short) uses 1s-bar extremes from the tape. Should match NT bar_execution but must be validated by an actual NT runtime backtest of one rule before any live deployment claim.
2. **Cost model assumed $10/RT.** Tick-data slippage validation (Feb-Sep 2025) confirmed this is realistic for the entry filter rule. Need to revalidate for the new rule because it exits at intra-bar protective stops, not bar OPEN — fill mechanics may differ.
3. **Same trade population.** This is the same V_A entries (1m HH/LL + bar+1 momentum). Only exits change. Entry-side fragility from the prior robustness battery still applies — don't conflate "exit rule survives 2022" with "V_A signal survives 2022".
4. **No threshold sweep.** stall_bars=5 in 30s buckets was inherited from the IS top result. Sensitivity not yet tested OOS.

## Recommendation

This is a deployment-grade exit overlay candidate, pending:
1. **NT runtime backtest** of C_lock50_30s_5 across all 7 years for parity verification
2. **Threshold sensitivity sweep** of stall_bars (3, 5, 7, 10) in 30s granularity to verify razor-edge isn't an issue
3. **Equity curve / drawdown depth analysis** to verify the WR improvement actually delivers smoother equity (not just higher mean)

If those three pass, this is the first V_A variant in this research series with credible cross-year robust positive economics.

## Files

- Per-rule per-trade results (OOS): `studies/v_a_exit_recon/results/oos_<rule>.parquet`
- Summary: `studies/v_a_exit_recon/results/hhll_oos_summary.parquet`
- IS report: `studies/v_a_exit_recon/results/HHLL_PROGRESSION_REPORT.md`
- OOS report: this file

# Conditioned Winner-Harvest Exit Rules — NQ 2024-2026 RTH

Five conditioned exit rules tested at three checkpoints (T=300s, 600s, 900s) using the existing trade tape. Rule fires only when `pnl > 0` at checkpoint AND rule-specific condition holds. Otherwise fall through to regime exit.

**Rules**:
- **A**: no new MFE peak in last 120s
- **B**: last 60s net move against trade direction
- **C**: MFE ≥ 1.0 ATR AND giveback from MFE ≥ 0.50 ATR
- **D**: MFE ≥ 1.0 ATR AND time since MFE peak ≥ 120s
- **E**: 30s regime flipped against trade OR rolling 60s directional efficiency ≤ -0.30

Reference rows: baseline regime exit + `04_time_winner_600s` (the blunt prior winner).

## Per-rule per-year scoreboard

| Rule | %fired | 2024 mean / total / dmg→winners / impr→losers | 2025 mean / total / dmg / impr | 2026 mean / total / dmg / impr | All mean | All total | All PF | Top-1% share |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| BASELINE_regime | 0.0% | $7.51 / $24,965 / $0.00 / $0.00 | $17.67 / $58,465 / $0.00 / $0.00 | $-18.74 / $-18,400 / $0.00 / $0.00 | $8.30 | $63,605 | 1.04 | 506.6% |
| REF_time_winner_600s | 41.5% | $-110.21 / $-366,570 / $-263,765 / $165,950 | $109.85 / $363,495 / $-423,040 / $439,375 | $439.39 / $431,485 / $-312,410 / $623,385 | $55.82 | $427,490 | 1.17 | 352.4% |
| A_no_new_mfe_120s_T300 | 14.1% | $0.92 / $3,075 / $-93,655 / $61,975 | $16.17 / $53,520 / $-102,420 / $82,215 | $-15.18 / $-14,905 / $-32,430 / $31,580 | $5.07 | $38,830 | 1.02 | 802.4% |
| A_no_new_mfe_120s_T600 | 19.7% | $5.71 / $18,980 / $-109,390 / $51,135 | $19.86 / $65,705 / $-130,260 / $77,360 | $-12.23 / $-12,010 / $-35,015 / $21,700 | $9.39 | $71,950 | 1.04 | 428.7% |
| A_no_new_mfe_120s_T900 | 17.7% | $0.87 / $2,895 / $-97,925 / $22,485 | $10.60 / $35,085 / $-131,290 / $41,185 | $-2.73 / $-2,685 / $-27,180 / $12,680 | $4.49 | $34,355 | 1.02 | 844.9% |
| B_adverse_60s_momentum_T300 | 17.0% | $1.46 / $4,840 / $-111,605 / $71,945 | $15.28 / $50,550 / $-148,750 / $115,400 | $-15.72 / $-15,440 / $-38,245 / $32,885 | $5.07 | $38,805 | 1.02 | 750.7% |
| B_adverse_60s_momentum_T600 | 17.3% | $1.12 / $3,710 / $-103,075 / $36,185 | $17.40 / $57,590 / $-125,685 / $60,325 | $-27.77 / $-27,270 / $-42,685 / $16,770 | $4.29 | $32,840 | 1.02 | 894.5% |
| B_adverse_60s_momentum_T900 | 13.6% | $4.25 / $14,145 / $-76,865 / $19,000 | $11.80 / $39,035 / $-95,525 / $22,340 | $-10.50 / $-10,315 / $-24,320 / $9,945 | $5.47 | $41,875 | 1.02 | 736.4% |
| C_giveback_from_mfe_T300 | 21.6% | $-1.02 / $-3,390 / $-153,910 / $92,675 | $13.91 / $46,020 / $-192,990 / $137,430 | $-7.28 / $-7,145 / $-36,680 / $35,960 | $4.38 | $33,535 | 1.02 | 831.0% |
| C_giveback_from_mfe_T600 | 25.1% | $2.17 / $7,220 / $-156,790 / $59,470 | $16.22 / $53,675 / $-184,025 / $82,410 | $-23.76 / $-23,335 / $-58,425 / $25,875 | $4.78 | $36,625 | 1.02 | 747.6% |
| C_giveback_from_mfe_T900 | 21.0% | $-4.07 / $-13,545 / $-135,280 / $26,830 | $3.18 / $10,530 / $-170,020 / $37,965 | $-2.29 / $-2,250 / $-34,775 / $12,785 | $-0.83 | $-6,325 | 1.00 | -4351.5% |
| D_stalled_after_mfe_T300 | 10.5% | $1.99 / $6,605 / $-69,070 / $41,625 | $17.78 / $58,850 / $-76,670 / $62,355 | $-24.27 / $-23,830 / $-28,010 / $18,285 | $5.06 | $38,745 | 1.02 | 808.4% |
| D_stalled_after_mfe_T600 | 18.1% | $7.32 / $24,360 / $-97,030 / $44,210 | $18.24 / $60,365 / $-123,125 / $65,095 | $-15.82 / $-15,540 / $-34,445 / $17,735 | $8.93 | $68,365 | 1.04 | 451.2% |
| D_stalled_after_mfe_T900 | 17.1% | $1.01 / $3,365 / $-96,420 / $21,465 | $11.13 / $36,830 / $-124,285 / $35,925 | $-4.25 / $-4,175 / $-26,955 / $10,965 | $4.58 | $35,100 | 1.02 | 826.9% |
| E_ltf_deterioration_T300 | 3.8% | $5.75 / $19,130 / $-22,770 / $16,310 | $18.83 / $62,325 / $-22,190 / $25,020 | $-16.03 / $-15,740 / $-7,465 / $9,210 | $8.40 | $64,315 | 1.04 | 499.2% |
| E_ltf_deterioration_T600 | 8.1% | $8.45 / $28,105 / $-39,045 / $25,535 | $19.75 / $65,350 / $-47,395 / $32,535 | $-18.24 / $-17,910 / $-12,145 / $7,260 | $9.67 | $74,075 | 1.04 | 430.2% |
| E_ltf_deterioration_T900 | 8.3% | $4.56 / $15,175 / $-42,920 / $12,840 | $12.77 / $42,270 / $-66,745 / $23,030 | $-12.25 / $-12,030 / $-9,305 / $4,945 | $5.77 | $44,195 | 1.03 | 681.5% |

## Δ vs baseline regime exit

| Rule | Δ 2024 | Δ 2025 | Δ 2026 | Δ All | Δ All total |
|---|--:|--:|--:|--:|--:|
| REF_time_winner_600s | $-117.72 | $92.18 | $458.13 | $47.51 | $363,885 |
| A_no_new_mfe_120s_T300 | $-6.58 | $-1.49 | $3.56 | $-3.23 | $-24,775 |
| A_no_new_mfe_120s_T600 | $-1.80 | $2.19 | $6.51 | $1.09 | $8,345 |
| A_no_new_mfe_120s_T900 | $-6.64 | $-7.07 | $16.00 | $-3.82 | $-29,250 |
| B_adverse_60s_momentum_T300 | $-6.05 | $-2.39 | $3.01 | $-3.24 | $-24,800 |
| B_adverse_60s_momentum_T600 | $-6.39 | $-0.26 | $-9.03 | $-4.02 | $-30,765 |
| B_adverse_60s_momentum_T900 | $-3.25 | $-5.87 | $8.23 | $-2.84 | $-21,730 |
| C_giveback_from_mfe_T300 | $-8.53 | $-3.76 | $11.46 | $-3.93 | $-30,070 |
| C_giveback_from_mfe_T600 | $-5.34 | $-1.45 | $-5.03 | $-3.52 | $-26,980 |
| C_giveback_from_mfe_T900 | $-11.58 | $-14.49 | $16.45 | $-9.13 | $-69,930 |
| D_stalled_after_mfe_T300 | $-5.52 | $0.12 | $-5.53 | $-3.25 | $-24,860 |
| D_stalled_after_mfe_T600 | $-0.18 | $0.57 | $2.91 | $0.62 | $4,760 |
| D_stalled_after_mfe_T900 | $-6.49 | $-6.54 | $14.49 | $-3.72 | $-28,505 |
| E_ltf_deterioration_T300 | $-1.75 | $1.17 | $2.71 | $0.09 | $710.00 |
| E_ltf_deterioration_T600 | $0.94 | $2.08 | $0.50 | $1.37 | $10,470 |
| E_ltf_deterioration_T900 | $-2.94 | $-4.89 | $6.49 | $-2.53 | $-19,410 |

## Years positive per rule

| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |
|---|--:|---|---|---|
| BASELINE_regime | 2/3 | ✅ | ✅ | ❌ |
| REF_time_winner_600s | 2/3 | ❌ | ✅ | ✅ |
| A_no_new_mfe_120s_T300 | 2/3 | ✅ | ✅ | ❌ |
| A_no_new_mfe_120s_T600 | 2/3 | ✅ | ✅ | ❌ |
| A_no_new_mfe_120s_T900 | 2/3 | ✅ | ✅ | ❌ |
| B_adverse_60s_momentum_T300 | 2/3 | ✅ | ✅ | ❌ |
| B_adverse_60s_momentum_T600 | 2/3 | ✅ | ✅ | ❌ |
| B_adverse_60s_momentum_T900 | 2/3 | ✅ | ✅ | ❌ |
| C_giveback_from_mfe_T300 | 1/3 | ❌ | ✅ | ❌ |
| C_giveback_from_mfe_T600 | 2/3 | ✅ | ✅ | ❌ |
| C_giveback_from_mfe_T900 | 1/3 | ❌ | ✅ | ❌ |
| D_stalled_after_mfe_T300 | 2/3 | ✅ | ✅ | ❌ |
| D_stalled_after_mfe_T600 | 2/3 | ✅ | ✅ | ❌ |
| D_stalled_after_mfe_T900 | 2/3 | ✅ | ✅ | ❌ |
| E_ltf_deterioration_T300 | 2/3 | ✅ | ✅ | ❌ |
| E_ltf_deterioration_T600 | 2/3 | ✅ | ✅ | ❌ |
| E_ltf_deterioration_T900 | 2/3 | ✅ | ✅ | ❌ |

## Verdict — answer to the main question

**Can we preserve 2024 trend runners while capturing the 2026 peak-then-giveback trades better than blunt time_winner_600s?**

**Partially: 2024 is preserved easily, but >97% of the 2026 alpha disappears the moment you add ANY conditioning.**

### Comparison table (Δ vs baseline regime exit)

| Rule | Δ 2024 | Δ 2025 | Δ 2026 | Δ All total | 2024 preserved? | 2026 captured? |
|---|--:|--:|--:|--:|---|---|
| REF_time_winner_600s | -$117.72 | +$92.18 | +$458.13 | **+$363,885** | ❌ destroyed | ✅ all |
| A_no_new_mfe_120s_T600 | -$1.80 | +$2.19 | +$6.51 | +$8,345 | ✅ near-flat | ❌ 1.4% of REF |
| **E_ltf_deterioration_T600** | **+$0.94** | **+$2.08** | **+$0.50** | **+$10,470** | ✅ improved | ❌ 0.1% of REF |
| D_stalled_after_mfe_T600 | -$0.18 | +$0.57 | +$2.91 | +$4,760 | ✅ near-flat | ❌ 0.6% of REF |
| C_giveback_from_mfe_T900 | -$11.58 | -$14.49 | +$16.45 | -$69,930 | ❌ hurt | ❌ 3.6% of REF |

### The structural finding

The conditioned rules can preserve 2024 — but they cannot meaningfully recover 2026 alpha. The best conditioned rule for 2026 is `C_giveback_from_mfe_T900` at +$16.45/trade (3.6% of the +$458/trade time_winner_600s captured). And it hurts 2024 by -$11.58/trade in exchange.

This means the 2026 alpha is **broad, not selective.** In 2026, MOST winning trades at T=600s go on to give back. The blunt rule catches all of them. Adding any structural filter (no new MFE, adverse momentum, giveback, stall, LTF deterioration) screens OUT most of the catches because the "give back" pattern is uniform across the 2026 trade population.

This mirrors the earlier exit-policy ML finding: the available features cannot reliably distinguish winners that will keep running from winners that will give back. The 2026 effect is a regime effect (high-ATR mean-reversion environment), not a per-trade microstructure effect.

### One genuinely Pareto-improving rule found

**`E_ltf_deterioration_T600`** is the only rule with positive Δ in every year:

| Metric | Baseline | E_T600 | Δ |
|---|--:|--:|--:|
| 2024 mean | +$7.51 | +$8.45 | **+$0.94** |
| 2025 mean | +$17.67 | +$19.75 | **+$2.08** |
| 2026 mean | -$18.74 | -$18.24 | **+$0.50** |
| All total | $63,605 | $74,075 | **+$10,470** |
| Fire rate | — | 8.1% | small surface |
| Damage to original winners | — | $-98,585 | |
| Improvement to original losers | — | $65,330 | |

The rule fires when an open winning trade shows BOTH a positive PnL at T=600s AND clear LTF deterioration (30s regime against trade direction OR 60s directional efficiency ≤ -0.30). That selectivity is the trade-off: it only fires on 8.1% of trades but preserves baseline structure on the other 91.9%.

The +$10K total over 7,659 trades is a +$1.37/trade improvement. Real but modest. Equivalent to recovering ~16% of the cost model ($10/round-trip).

### Recommendation

1. **For deployment of regime-exit V_A**: `E_ltf_deterioration_T600` is the only rule that strictly improves baseline economics in every year. Apply as overlay. Modest win.

2. **For chasing the 2026-style alpha**: the time_winner_600s blunt rule reveals a real $450/trade pattern in high-ATR/choppy regimes, but the available features cannot identify WHICH trades exhibit it ahead of time. The cleanest path forward is to test whether a **regime-conditional** approach works — e.g., apply blunt time_winner_600s only when atr_1m exceeds a threshold determined from the prior N days. This risks the curve-fit trap from MEMORY.md, but it's the natural next experiment given this study's findings.

3. **Per-trade ML to select WHICH 2026 winners to cut**: would address the same question that the prior exit-policy study failed at. Worth one more attempt with the trade tape now available, but expectations should be calibrated by how dense the 2026 effect is — if 70%+ of 2026 winners give back, classifier-based selection has little to discriminate.

## Files

- Per-rule per-trade results: `studies/v_a_exit_recon/results/trades_<rule>_T<n>.parquet` (15 files)
- Summary: `studies/v_a_exit_recon/results/conditioned_harvest_summary.parquet`
- Replay code: `studies/v_a_exit_recon/conditioned_harvest.py`
